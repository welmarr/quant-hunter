"""Operational ownership and bounded admission for immutable data services."""

from __future__ import annotations

import json
import secrets
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol, cast

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.web.state import AccessError, AppState, User


class DatasetImporter(Protocol):
    def import_bytes(
        self,
        payload: bytes,
        *,
        file_format: Literal["CSV", "PARQUET"],
        metadata: Mapping[str, JsonValue],
        corrects_dataset_id: str | None = None,
        correction_reason: str | None = None,
    ) -> JsonRecord: ...

    def get_dataset(self, dataset_id: str) -> JsonRecord: ...


class SourceProber(Protocol):
    def probe(self, catalogue_id: str) -> JsonRecord: ...


class DataAccess:
    """SQLite controls visibility; immutable services remain data authority.

    Imports and probes are bounded request/response operations, not economic
    executions. Unknown interrupted operations are retained and never replayed.
    A failure after immutable publication may leave an unlinked audit object;
    it never permits another user to claim it through an arbitrary dataset ID.
    """

    def __init__(
        self,
        state: AppState,
        runtime: Path,
        importer: DatasetImporter,
        prober: SourceProber,
    ) -> None:
        self.state, self.runtime = state, runtime
        self.importer, self.prober = importer, prober
        with state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS data_ownership (
                    dataset_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS data_operations (
                    id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
                    kind TEXT NOT NULL, catalogue_id TEXT, created REAL NOT NULL,
                    status TEXT NOT NULL, result TEXT, error TEXT,
                    FOREIGN KEY(owner_id) REFERENCES users(id));
                INSERT OR IGNORE INTO migrations VALUES (2);
            """)

    def recover(self) -> None:
        with self.state.connection() as db:
            db.execute(
                "UPDATE data_operations SET status='INTERRUPTED',"
                "error='Interrupted; no automatic replay' WHERE status='RUNNING'"
            )

    def _capacity(self) -> None:
        usage = shutil.disk_usage(self.runtime)
        reserve = max(20 * 1024**3, usage.total * 15 // 100)
        if usage.free - 32_000_000 < reserve:
            raise AccessError("Data operation refused: disk reserve would be breached")
        budget_root = next(
            (p for p in (self.runtime, *self.runtime.parents) if p.name == ".local"),
            self.runtime,
        )
        total = sum(p.stat().st_size for p in budget_root.rglob("*") if p.is_file())
        if total + 64_000_000 > 30_000_000_000:
            raise AccessError("Runtime size limit reached; owner review required")

    def _begin(self, user: User, kind: str, catalogue_id: str | None = None) -> str:
        if user.role not in ("owner", "researcher"):
            raise AccessError("Researcher role required")
        self._capacity()
        now = time.time()
        operation_id = secrets.token_hex(16)
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM data_operations WHERE status='RUNNING'"
                ).fetchone()[0]
                >= 2
            ):
                raise AccessError("Data operations busy; wait for completion")
            # At most 2 GB raw imports under this initial profile. No automatic
            # deletion or widening of the mission's cumulative download bound.
            if db.execute("SELECT COUNT(*) FROM data_operations").fetchone()[0] >= 1000:
                raise AccessError("Data operation quota reached; owner review required")
            if kind == "PROBE":
                if db.execute(
                    "SELECT 1 FROM data_operations WHERE owner_id=? AND kind='PROBE' "
                    "AND created>? LIMIT 1",
                    (user.id, now - 60),
                ).fetchone():
                    raise AccessError(
                        "Source probes limited to one per minute per user"
                    )
                if (
                    catalogue_id == "SRC-04"
                    and db.execute(
                        "SELECT COUNT(*) FROM data_operations WHERE catalogue_id='SRC-04' "
                        "AND created>?",
                        (now - 86400,),
                    ).fetchone()[0]
                    >= 25
                ):
                    raise AccessError(
                        "BLS application quota reached: 25 probes per 24 hours"
                    )
            db.execute(
                "INSERT INTO data_operations VALUES(?,?,?,?,?,'RUNNING',NULL,NULL)",
                (operation_id, user.id, kind, catalogue_id, now),
            )
        return operation_id

    def _finish(
        self,
        operation_id: str,
        *,
        result: JsonRecord | None = None,
        error: str | None = None,
        owner: User | None = None,
    ) -> None:
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if result is not None and owner is not None:
                dataset_id = result.get("dataset_id")
                if not isinstance(dataset_id, str):
                    raise ValueError("Importer returned no dataset identity")
                db.execute(
                    "INSERT INTO data_ownership VALUES(?,?)", (dataset_id, owner.id)
                )
            db.execute(
                "UPDATE data_operations SET status=?,result=?,error=? "
                "WHERE id=? AND status='RUNNING'",
                (
                    "FAILED" if error else "SUCCEEDED",
                    json.dumps(result) if result else None,
                    error,
                    operation_id,
                ),
            )

    def owns(self, user: User, dataset_id: str) -> None:
        with self.state.connection() as db:
            row = db.execute(
                "SELECT 1 FROM data_ownership WHERE dataset_id=? AND owner_id=?",
                (dataset_id, user.id),
            ).fetchone()
        if row is None:
            raise AccessError("Dataset is unavailable")

    def dataset_count(self, user: User) -> int:
        with self.state.connection() as db:
            return int(
                db.execute(
                    "SELECT COUNT(*) FROM data_ownership WHERE owner_id=?", (user.id,)
                ).fetchone()[0]
            )

    def datasets(
        self, user: User, *, limit: int = 25, offset: int = 0
    ) -> list[JsonRecord]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or type(offset) is not int
            or not 0 <= offset <= 1000
        ):
            raise AccessError("Invalid dataset page")
        with self.state.connection() as db:
            ids = [
                str(r[0])
                for r in db.execute(
                    "SELECT dataset_id FROM data_ownership WHERE owner_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (user.id, limit, offset),
                )
            ]
        return [self.importer.get_dataset(dataset_id) for dataset_id in ids]

    def dataset(self, user: User, dataset_id: str) -> JsonRecord:
        self.owns(user, dataset_id)
        return self.importer.get_dataset(dataset_id)

    def import_data(
        self,
        user: User,
        payload: bytes,
        *,
        file_format: Literal["CSV", "PARQUET"],
        metadata: Mapping[str, JsonValue],
        corrects_dataset_id: str | None = None,
        correction_reason: str | None = None,
    ) -> JsonRecord:
        if corrects_dataset_id is not None:
            self.owns(user, corrects_dataset_id)
        operation_id = self._begin(user, "IMPORT")
        try:
            result = self.importer.import_bytes(
                payload,
                file_format=file_format,
                metadata=metadata,
                corrects_dataset_id=corrects_dataset_id,
                correction_reason=correction_reason,
            )
            self._finish(operation_id, result=result, owner=user)
            return result
        except Exception as exc:
            self._finish(operation_id, error=type(exc).__name__)
            raise

    def probe(self, user: User, catalogue_id: str) -> JsonRecord:
        if catalogue_id not in ("SRC-04", "SRC-08"):
            raise AccessError("This connector is not implemented")
        operation_id = self._begin(user, "PROBE", catalogue_id)
        try:
            result = self.prober.probe(catalogue_id)
            # Probe datasets use their own format; they are not OHLC imports and
            # never enter the synthetic backtest or import ownership table.
            self._finish(
                operation_id,
                result=result,
                error=str(result.get("error_code", "SourceProbeFailed"))
                if result.get("status") == "FAILED"
                else None,
            )
            return result
        except Exception as exc:
            self._finish(operation_id, error=type(exc).__name__)
            raise

    def operations(self, user: User) -> list[JsonRecord]:
        with self.state.connection() as db:
            return [
                cast(
                    JsonRecord,
                    {
                        "id": r["id"],
                        "kind": r["kind"],
                        "catalogue_id": r["catalogue_id"],
                        "created_at_unix": str(r["created"]),
                        "status": r["status"],
                        "error": r["error"],
                        "result": json.loads(r["result"]) if r["result"] else None,
                    },
                )
                for r in db.execute(
                    "SELECT * FROM data_operations WHERE owner_id=? ORDER BY rowid DESC LIMIT 100",
                    (user.id,),
                )
            ]
