"""Private mapped-data admission through the existing resource-operation journal."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Context, Decimal, localcontext
from typing import Any, cast

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.data_quality import (
    MappingSpec,
    PartitionSelection,
    QualityError,
    QualityService,
    SelectedSnapshot,
)
from quant_hunter.data_quality.checks import stamp
from quant_hunter.data_quality.partitions import compose
from quant_hunter.identity import StaleWriterError
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.web.admission import resource_counts
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.state import AccessError, AppState, User


class QualityAccess:
    """Operational ownership only; canonical datasets and quality remain immutable."""

    def __init__(
        self,
        state: AppState,
        service: QualityService,
        data: DataAccess,
        instruments: InstrumentRegistry,
    ) -> None:
        if data.state is not state or instruments.store is not service.registry:
            raise ValueError("Quality access requires shared governed stores")
        for name in ("registry", "objects"):
            governed = getattr(data.importer, name, None)
            if governed is not None and governed is not getattr(service, name):
                raise ValueError(
                    "Quality and data import require shared governed stores"
                )
        self.state, self.service, self.data, self.instruments = (
            state,
            service,
            data,
            instruments,
        )
        with state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS quality_ownership (
                    dataset_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS quality_selection_ownership (
                    manifest_digest TEXT NOT NULL, owner_id INTEGER NOT NULL,
                    PRIMARY KEY(manifest_digest,owner_id),
                    FOREIGN KEY(owner_id) REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS resource_readers (
                    id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
                    created REAL NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES users(id));
            """)

    @contextmanager
    def inspection(
        self, user: User, *, operation_id: str | None = None
    ) -> Iterator[None]:
        """Transient reader reservation, or a verified existing worker/mutation slot.

        A reservation is operational only: no scientific trial or import quota.
        The leased Runtime clears process-loss remnants before accepting work.
        """
        identity = secrets.token_hex(16)
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = db.execute(
                "SELECT role FROM users WHERE id=?", (user.id,)
            ).fetchone()
            if actor is None or actor[0] not in {"owner", "researcher", "reader"}:
                raise AccessError("Authenticated reader required")
            if operation_id is not None:
                if (
                    db.execute(
                        "SELECT 1 FROM data_operations WHERE id=? AND owner_id=? AND status='RUNNING'",
                        (operation_id, user.id),
                    ).fetchone()
                    is None
                ):
                    raise AccessError("Active owned resource operation required")
            else:
                active, queued = resource_counts(db)
                if active >= 2 or queued >= 8:
                    raise AccessError("Inspection resources busy; wait for completion")
                db.execute(
                    "INSERT INTO resource_readers VALUES(?,?,?)",
                    (identity, user.id, time.time()),
                )
        try:
            yield
        finally:
            if operation_id is None:
                with self.state.connection() as db:
                    db.execute(
                        "DELETE FROM resource_readers WHERE id=? AND owner_id=?",
                        (identity, user.id),
                    )

    def owns(self, user: User, dataset_id: str) -> None:
        with self.state.connection() as db:
            if (
                db.execute(
                    "SELECT 1 FROM quality_ownership WHERE dataset_id=? AND owner_id=?",
                    (dataset_id, user.id),
                ).fetchone()
                is None
            ):
                raise AccessError("Quality dataset is unavailable")

    def _dataset(self, user: User, dataset_id: str) -> JsonRecord:
        self.owns(user, dataset_id)
        return self.service.get_dataset(dataset_id)

    def dataset(
        self, user: User, dataset_id: str, *, operation_id: str | None = None
    ) -> JsonRecord:
        self.owns(user, dataset_id)
        with self.inspection(user, operation_id=operation_id):
            return self._dataset(user, dataset_id)

    def _metadata(self, digest: str) -> JsonRecord:
        if self.service.objects.get(digest).byte_size > 2_000_000:
            raise QualityError("QUALITY_METADATA_LIMIT")
        value = parse_json_document(self.service.objects.read_bytes(digest))
        if not isinstance(value, dict):
            raise QualityError("QUALITY_METADATA_OBJECT_REQUIRED")
        return value

    def _dataset_summary(self, user: User, identity: str) -> JsonRecord:
        """Hash-verified metadata graph only; never decodes raw or normalized rows."""
        self.owns(user, identity)
        head = self.service.registry.verify_object(identity)[-1]
        lineage = self._metadata(cast(str, head.record["provenance_lineage_digest"]))
        transformation = cast(JsonRecord, lineage["transformation"])
        config_digest = cast(str, transformation["configuration_digest"])
        config = self._metadata(config_digest)
        if (
            config.get("dataset_id") != identity
            or config.get("created_at") != head.record["created_at"]
        ):
            raise QualityError("QUALITY_METADATA_BINDING")
        report_digest = cast(str, config["quality_report_digest"])
        report = self._metadata(report_digest)
        if report.get("dataset_id") != identity:
            raise QualityError("QUALITY_METADATA_BINDING")
        origin = config
        if config.get("schema_version") == "qh-session-aggregation-v1":
            parent_id = cast(str, config["parent_dataset_id"])
            self.owns(user, parent_id)
            parent = self.service.registry.verify_object(parent_id)[-1]
            if parent.digest != config["parent_record_digest"]:
                raise StaleWriterError("Quality parent changed; refresh exact receipts")
            parent_lineage = self._metadata(
                cast(str, parent.record["provenance_lineage_digest"])
            )
            origin = self._metadata(
                cast(
                    str,
                    cast(JsonRecord, parent_lineage["transformation"])[
                        "configuration_digest"
                    ],
                )
            )
        if origin.get("schema_version") != "qh-mapped-import-v1":
            raise QualityError("NOT_A_QUALITY_DATASET")
        return {
            "dataset_id": identity,
            "record_digest": head.digest,
            "normalized_digest": head.record["physical_object_digest"],
            "quality_report_digest": report_digest,
            "configuration_digest": config_digest,
            "row_count": report["row_count"],
            "bounds": head.record["coverage"],
            "instrument_id": origin["instrument_id"],
            "instrument_revision_digest": origin["instrument_revision_digest"],
            "calendar_digest": origin["calendar_digest"],
            "metadata": origin["metadata"],
            "evidence_mode": cast(JsonRecord, origin["metadata"])["evidence_mode"],
            "reported_admission": report["admission"],
            "admission": "NOT_FRESH_ADMISSION",
            "causal_eligible": False,
            "inspection": "IMMUTABLE_METADATA_SUMMARY; NOT_FRESH_ADMISSION",
            "empirically_validated": False,
            "host_enforced": False,
        }

    def datasets(
        self, user: User, *, limit: int = 25, offset: int = 0
    ) -> list[JsonRecord]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or type(offset) is not int
            or not 0 <= offset <= 1000
        ):
            raise AccessError("Invalid quality dataset page")
        with self.state.connection() as db:
            ids = tuple(
                str(row[0])
                for row in db.execute(
                    "SELECT dataset_id FROM quality_ownership WHERE owner_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (user.id, limit, offset),
                )
            )
        result: list[JsonRecord] = []
        size = 0
        for identity in ids:
            summary = self._dataset_summary(user, identity)
            size += len(canonicalize_json(summary))
            if size > 2_000_000:
                raise QualityError("QUALITY_SUMMARY_PAGE_LIMIT_REDUCE_LIMIT")
            result.append(summary)
        return result

    def _receipt(
        self, user: User, dataset_id: str, record_digest: str, report_digest: str
    ) -> JsonRecord:
        detail = self._dataset(user, dataset_id)
        if (
            detail["record_digest"] != record_digest
            or detail["quality_report_digest"] != report_digest
        ):
            raise StaleWriterError("Quality dataset changed; refresh exact receipts")
        return detail

    def selected(
        self,
        user: User,
        dataset_id: str,
        *,
        record_digest: str,
        quality_report_digest: str,
        purpose: str = "PATTERN_CAUSAL",
        operation_id: str | None = None,
    ) -> tuple[SelectedSnapshot, bytes]:
        self.owns(user, dataset_id)
        with self.inspection(user, operation_id=operation_id):
            return self._selected(
                user,
                dataset_id,
                record_digest=record_digest,
                quality_report_digest=quality_report_digest,
                purpose=purpose,
            )

    def _selected(
        self,
        user: User,
        dataset_id: str,
        *,
        record_digest: str,
        quality_report_digest: str,
        purpose: str,
    ) -> tuple[SelectedSnapshot, bytes]:
        """Internal only: caller already holds one actual resource reservation."""
        self._receipt(user, dataset_id, record_digest, quality_report_digest)
        return self.service.select(
            dataset_id,
            expected_record_digest=record_digest,
            expected_report_digest=quality_report_digest,
            purpose=purpose,
        )

    def _finish(
        self,
        user: User,
        operation: str,
        result: JsonRecord,
        *,
        dataset_ids: tuple[str, ...] = (),
        selection_digest: str | None = None,
    ) -> None:
        # This transaction either grants all returned pointers and success together,
        # or leaves unlinked immutable evidence requiring owner review.
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE data_operations SET status='SUCCEEDED',result=?,error=NULL WHERE id=? AND owner_id=? AND status='RUNNING'",
                (json.dumps(result, allow_nan=False), operation, user.id),
            )
            if changed.rowcount != 1:
                raise AccessError(
                    "Quality operation was interrupted; no ownership granted"
                )
            for identity in dataset_ids:
                db.execute(
                    "INSERT INTO quality_ownership VALUES(?,?)", (identity, user.id)
                )
            if selection_digest is not None:
                db.execute(
                    "INSERT OR IGNORE INTO quality_selection_ownership VALUES(?,?)",
                    (selection_digest, user.id),
                )

    def _mutate(
        self,
        user: User,
        kind: str,
        action: Callable[[], JsonRecord],
        *,
        result_kind: str,
    ) -> JsonRecord:
        operation = self.data._begin(user, kind)
        try:
            result = action()
            identities: tuple[str, ...]
            if result_kind == "DATASET":
                identities = (cast(str, result["dataset_id"]),)
            elif result_kind == "DEMO":
                identities = tuple(
                    cast(str, cast(JsonRecord, row)["dataset_id"])
                    for row in cast(list[JsonValue], result["datasets"])
                )
            else:
                identities = ()
            selection_digest = (
                cast(str, result["manifest_digest"])
                if result_kind == "SELECTION"
                else None
            )
            self._finish(
                user,
                operation,
                result,
                dataset_ids=identities,
                selection_digest=selection_digest,
            )
            return result
        except Exception as error:
            code = (
                error.code
                if isinstance(error, QualityError)
                else "STALE_REVISION"
                if isinstance(error, StaleWriterError)
                else "QUALITY_OPERATION_FAILED"
            )
            retained: JsonRecord | None = (
                {"audit_digest": error.audit_digest}
                if isinstance(error, QualityError) and error.audit_digest
                else None
            )
            self.data._finish(operation, error=code, result=retained)
            raise
        # Process loss/BaseException is retained by existing DataAccess recovery;
        # no automatic replay and no inferred ownership from orphaned evidence.

    def import_mapped(
        self,
        user: User,
        payload: bytes,
        *,
        file_format: str,
        metadata: JsonRecord,
        mapping: MappingSpec,
        instrument_id: str,
        instrument_revision_digest: str,
        calendar_start: date,
        calendar_end: date,
    ) -> JsonRecord:
        if self.instruments.get(instrument_id)["digest"] != instrument_revision_digest:
            raise StaleWriterError("Instrument changed; refresh its canonical revision")
        return self._mutate(
            user,
            "QUALITY_IMPORT",
            lambda: self.service.ingest_mapped(
                payload,
                file_format=file_format,
                metadata=metadata,
                mapping=mapping,
                instrument_id=instrument_id,
                instrument_revision_digest=instrument_revision_digest,
                calendar_start=calendar_start,
                calendar_end=calendar_end,
            ),
            result_kind="DATASET",
        )

    def aggregate(
        self,
        user: User,
        dataset_id: str,
        *,
        record_digest: str,
        quality_report_digest: str,
        timeframe: str,
        partial_policy: str,
        as_of: datetime,
    ) -> JsonRecord:
        self.owns(user, dataset_id)

        def action() -> JsonRecord:
            self._receipt(user, dataset_id, record_digest, quality_report_digest)
            return self.service.aggregate(
                dataset_id,
                expected_record_digest=record_digest,
                expected_report_digest=quality_report_digest,
                timeframe=timeframe,
                partial_policy=partial_policy,
                as_of=as_of,
            )

        return self._mutate(
            user,
            "QUALITY_AGGREGATE",
            action,
            result_kind="DATASET",
        )

    def compose(
        self,
        user: User,
        parents: tuple[tuple[str, str, str], ...],
        *,
        purpose: str = "PATTERN_CAUSAL",
    ) -> JsonRecord:
        if not isinstance(parents, tuple) or not 1 <= len(parents) <= 1024:
            raise AccessError("Invalid quality selection size")

        def action() -> JsonRecord:
            for identity, revision, quality in parents:
                self._receipt(user, identity, revision, quality)
            return self.service.compose(parents, purpose=purpose).to_record()

        return self._mutate(
            user,
            "QUALITY_COMPOSE",
            action,
            result_kind="SELECTION",
        )

    def _selection(self, user: User, digest: str) -> PartitionSelection:
        with self.state.connection() as db:
            if (
                db.execute(
                    "SELECT 1 FROM quality_selection_ownership WHERE manifest_digest=? AND owner_id=?",
                    (digest, user.id),
                ).fetchone()
                is None
            ):
                raise AccessError("Quality selection is unavailable")
        if self.service.objects.get(digest).byte_size > 2_000_000:
            raise QualityError("SELECTION_MANIFEST_LIMIT")
        manifest = parse_json_document(self.service.objects.read_bytes(digest))
        if not isinstance(manifest, dict) or not isinstance(
            manifest.get("parent_snapshots"), list
        ):
            raise QualityError("INVALID_PARTITION_SELECTION")
        parents = cast(list[JsonValue], manifest["parent_snapshots"])
        if not 1 <= len(parents) <= 1024:
            raise QualityError("PARTITION_SELECTION_LIMIT")
        references: list[tuple[str, str, str]] = []
        for row in parents:
            if not isinstance(row, dict) or any(
                not isinstance(row.get(key), str)
                for key in ("dataset_id", "record_digest", "quality_report_digest")
            ):
                raise QualityError("INVALID_PARTITION_PARENT")
            reference = (
                cast(str, row["dataset_id"]),
                cast(str, row["record_digest"]),
                cast(str, row["quality_report_digest"]),
            )
            self._receipt(user, *reference)
            references.append(reference)
        selected = compose(
            self.service,
            tuple(references),
            purpose=cast(str, manifest.get("purpose")),
            _publish=False,
        )
        if selected.manifest_digest != digest:
            raise QualityError("PARTITION_MANIFEST_REPLAY_MISMATCH")
        return selected

    def selection(
        self, user: User, digest: str, *, operation_id: str | None = None
    ) -> JsonRecord:
        with self.inspection(user, operation_id=operation_id):
            return self._selection(user, digest).to_record()

    def selections(
        self, user: User, *, limit: int = 25, offset: int = 0
    ) -> list[JsonRecord]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or type(offset) is not int
            or not 0 <= offset <= 1000
        ):
            raise AccessError("Invalid quality selection page")
        with self.state.connection() as db:
            ids = tuple(
                str(row[0])
                for row in db.execute(
                    "SELECT manifest_digest FROM quality_selection_ownership WHERE owner_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?",
                    (user.id, limit, offset),
                )
            )
            owned_ids = {
                str(row[0])
                for row in db.execute(
                    "SELECT dataset_id FROM quality_ownership WHERE owner_id=?",
                    (user.id,),
                )
            }
        output: list[JsonRecord] = []
        size = 0
        for digest in ids:
            manifest = self._metadata(digest)
            parents = manifest.get("parent_snapshots")
            if (
                manifest.get("schema_version") != "qh-owned-partition-selection-v1"
                or not isinstance(parents, list)
                or not 1 <= len(parents) <= 1024
            ):
                raise QualityError("INVALID_PARTITION_SELECTION")
            for parent in parents:
                if not isinstance(parent, dict) or not isinstance(
                    parent.get("dataset_id"), str
                ):
                    raise QualityError("INVALID_PARTITION_PARENT")
                if parent["dataset_id"] not in owned_ids:
                    raise AccessError("Quality dataset is unavailable")
            first = cast(JsonRecord, parents[0])
            summary: JsonRecord = {
                "manifest_digest": digest,
                "total_rows": manifest["total_rows"],
                "bounds": manifest["bounds"],
                "parent_snapshots": parents,
                "parent_count": len(parents),
                "calendar_profile_digest": manifest["calendar_profile_digest"],
                "instrument_id": first["instrument_id"],
                "instrument_revision_digest": first["instrument_revision_digest"],
                "feature_columns": first["feature_columns"],
                "step_ns": first["step_ns"],
                "evidence_mode": first["evidence_mode"],
                "causal_eligible": False,
                "inspection": "IMMUTABLE_METADATA_SUMMARY; NOT_FRESH_ADMISSION",
            }
            size += len(canonicalize_json(summary))
            if size > 2_000_000:
                raise QualityError("QUALITY_SUMMARY_PAGE_LIMIT_REDUCE_LIMIT")
            output.append(summary)
        return output

    def iter_selection(
        self, user: User, digest: str, *, operation_id: str | None = None
    ) -> Iterator[tuple[int, Any]]:
        with self.inspection(user, operation_id=operation_id):
            selected = self._selection(user, digest)
            for parent_index, batch in self.service.iter_batches(digest):
                self.owns(user, selected.parent_snapshots[parent_index].dataset_id)
                yield parent_index, batch

    def demo(self, user: User) -> JsonRecord:
        if user.role != "owner":
            raise AccessError(
                "Owner role required to create shared synthetic instruments"
            )
        return self._mutate(user, "QUALITY_DEMO", self._demo, result_kind="DEMO")

    def _demo(self) -> JsonRecord:
        # The fixture is a versioned deterministic dataset, independent of an
        # unrelated caller's Decimal precision, exponent bounds or traps.
        with localcontext(Context(prec=38)):
            return self._generate_demo()

    def _generate_demo(self) -> JsonRecord:
        output: list[JsonValue] = []
        names = (
            "open_at",
            "close_at",
            "open",
            "high",
            "low",
            "close",
            "available_at",
            "open_bid",
            "open_ask",
            "volume",
        )
        mapping = MappingSpec(
            tuple((name, name) for name in names),
            revision_mode="SYNTHETIC_NOT_APPLICABLE",
        )
        start = datetime(2025, 1, 6, 14, 30, tzinfo=UTC)
        for number, symbol in enumerate(("QHDEMOA", "QHDEMOB")):
            created = self.instruments.create(
                {
                    "instrument": {
                        "asset_class": "EQUITY",
                        "venue": "XNYS",
                        "base_currency": "USD",
                        "quote_currency": "USD",
                        "price_precision": 2,
                        "quantity_precision": 0,
                        "lot_size": "1",
                        "tick_size": "0.01",
                        "multiplier": "1",
                        "timezone": "America/New_York",
                        "calendar_id": "XNYS",
                        "activity": [{"start": "2020-01-01T00:00:00Z", "end": None}],
                        "symbols": [
                            {
                                "symbol": symbol,
                                "start": "2020-01-01T00:00:00Z",
                                "end": None,
                            }
                        ],
                        "status": "ACTIVE",
                    },
                    "reason": "Explicit owner-requested software demonstration",
                    "evidence_mode": "SYNTHETIC",
                    "source_reference": "qh-quality-demo-v1 deterministic generated prices; no market observations",
                }
            )
            lines = [",".join(names)]
            for index in range(240):
                opened = start + timedelta(minutes=index)
                closed = opened + timedelta(minutes=1)
                opening = Decimal(100 + number * 20) + Decimal((index % 24) - 12) / 100
                closing = opening + Decimal((index % 5) - 2) / 100
                high, low = (
                    max(opening, closing) + Decimal(".02"),
                    min(opening, closing) - Decimal(".02"),
                )
                lines.append(
                    ",".join(
                        (
                            stamp(opened),
                            stamp(closed),
                            str(opening),
                            str(high),
                            str(low),
                            str(closing),
                            stamp(closed),
                            str(opening - Decimal(".01")),
                            str(opening + Decimal(".01")),
                            str(100 + index % 11),
                        )
                    )
                )
            metadata: JsonRecord = {
                "source_name": "Quant Hunter explicit synthetic demo",
                "declared_license": "Generated fixture; no upstream market data",
                "evidence_mode": "SYNTHETIC",
                "instrument": {
                    "symbol": symbol,
                    "asset_class": "EQUITY",
                    "base_currency": "USD",
                    "quote_currency": "USD",
                    "quantity_step": "1",
                },
            }
            output.append(
                self.service.ingest_mapped(
                    ("\n".join(lines) + "\n").encode(),
                    file_format="CSV",
                    metadata=metadata,
                    mapping=mapping,
                    instrument_id=cast(
                        str, cast(JsonRecord, created["record"])["instrument_id"]
                    ),
                    instrument_revision_digest=cast(str, created["digest"]),
                    calendar_start=start.date(),
                    calendar_end=start.date(),
                )
            )
        return {
            "evidence_mode": "SYNTHETIC",
            "datasets": output,
            "generator": {
                "profile": "XNYS_TWO_INSTRUMENTS_240_MINUTES",
                "version": "qh-quality-demo-v1",
                "empirically_validated": False,
            },
        }
