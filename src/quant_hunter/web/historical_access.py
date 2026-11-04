"""Owned chart-only historical inspection; no causal or research authorization."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.data_quality import QualityError, SelectedSnapshot
from quant_hunter.identity import StaleWriterError
from quant_hunter.provenance.hashing import require_sha256_digest
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.state import AccessError, AppState, User

_MAX_INSPECTIONS = 10_000
_TIMES = ("open_at", "close_at", "available_at", "revision_time", "ingestion_time")
_LIMITATIONS = [
    "Chart-only exploratory inspection; no predictive pattern search, fit, outcome inference or causal admission.",
    "Historical availability and revision timestamps are uploader declarations, not independently verified publication evidence.",
    "Missing availability/revision times remain null; ingestion time is never substituted for historical knowledge.",
    "Instrument/calendar rules are retained references, not proof of their historical publication.",
    "Viewing these unsealed exploratory rows grants no sealed-data, empirical-validation or trading authority.",
]


def _utc(clock: Callable[[], float]) -> str:
    return datetime.fromtimestamp(clock(), UTC).isoformat().replace("+00:00", "Z")


def _record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise QualityError("INSPECTION_RECEIPT_INVALID")
    return value


def _rows(
    payload: bytes, snapshot: SelectedSnapshot, start: int, stop: int
) -> list[JsonValue]:
    if len(payload) > 64_000_000:
        raise QualityError("INSPECTION_PARQUET_LIMIT")
    parquet = pq.ParquetFile(pa.BufferReader(payload))
    if parquet.metadata.num_rows != snapshot.row_count:
        raise QualityError("INSPECTION_ROW_BINDING")
    columns = ["source_row", *_TIMES, "revision_time_status", *snapshot.feature_columns]
    if not set(columns) <= set(parquet.schema_arrow.names):
        raise QualityError("INSPECTION_COLUMNS")
    result: list[JsonValue] = []
    offset = 0
    prior_close: int | None = None
    for batch in parquet.iter_batches(
        batch_size=4096, columns=columns, use_threads=False
    ):
        length = batch.num_rows
        if offset + length <= start:
            offset += length
            continue
        selected = batch.slice(
            max(0, start - offset), min(length, stop - offset) - max(0, start - offset)
        )
        actual_start = max(start, offset)
        table = pa.Table.from_batches([selected])
        times = {
            name: table[name]
            .cast(pa.timestamp("ns", tz="UTC"))
            .cast(pa.int64())
            .to_pylist()
            for name in _TIMES
        }
        for index, row in enumerate(table.to_pylist()):
            opening, closing = times["open_at"][index], times["close_at"][index]
            values = []
            for name in snapshot.feature_columns:
                value = row[name]
                if not isinstance(value, Decimal) or not value.is_finite():
                    raise QualityError("INSPECTION_PRICE_SCHEMA")
                values.append(format(value, "f"))
            result.append(
                {
                    "row": actual_start + index,
                    "source_row": row["source_row"],
                    "open_ns": str(opening),
                    "close_ns": str(closing),
                    "available_ns": str(times["available_at"][index])
                    if times["available_at"][index] is not None
                    else None,
                    "revision_ns": str(times["revision_time"][index])
                    if times["revision_time"][index] is not None
                    else None,
                    "ingestion_ns": str(times["ingestion_time"][index]),
                    "revision_time_status": row["revision_time_status"],
                    "gap_before_ns": str(opening - prior_close)
                    if prior_close is not None and opening != prior_close
                    else None,
                    "values": cast(list[JsonValue], values),
                }
            )
            prior_close = closing
        offset += length
        if offset >= stop:
            break
    if len(result) != stop - start:
        raise QualityError("INSPECTION_ROW_BINDING")
    return result


class HistoricalPreviewAccess:
    """Explicit read exposure audit; no experiment, model or pattern writer.

    STARTED rows are recorded before graph/Parquet inspection. A process crash
    leaves that unresolved state visible; there is no retry or replay. Final
    immutable receipts bind exact returned rows by hash without duplicating bars.
    """

    def __init__(
        self,
        state: AppState,
        quality: QualityAccess,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if quality.state is not state:
            raise ValueError("Historical inspection requires shared state")
        self.state, self.quality, self.clock = state, quality, clock
        with state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS historical_inspections (
                    id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
                    created TEXT NOT NULL, request TEXT NOT NULL,
                    status TEXT NOT NULL, receipt_digest TEXT, error_code TEXT);
                CREATE TRIGGER IF NOT EXISTS historical_inspection_identity
                BEFORE UPDATE OF id,owner_id,created,request ON historical_inspections
                BEGIN SELECT RAISE(ABORT,'immutable inspection identity'); END;
                CREATE TRIGGER IF NOT EXISTS historical_inspection_terminal
                BEFORE UPDATE ON historical_inspections WHEN OLD.status!='STARTED'
                BEGIN SELECT RAISE(ABORT,'terminal inspection'); END;
                CREATE TRIGGER IF NOT EXISTS historical_inspection_delete
                BEFORE DELETE ON historical_inspections
                BEGIN SELECT RAISE(ABORT,'retained inspection'); END;
            """)

    def _actor(self, user: User) -> None:
        with self.state.connection() as db:
            row = db.execute(
                "SELECT username,role FROM users WHERE id=?", (user.id,)
            ).fetchone()
        if row is None or tuple(row) != (user.username, user.role):
            raise AccessError("Historical inspection access denied")

    def _begin(self, user: User, request: JsonRecord) -> str:
        identity = secrets.token_hex(16)
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute("SELECT COUNT(*) FROM historical_inspections").fetchone()[0]
                >= _MAX_INSPECTIONS
            ):
                raise AccessError(
                    "Inspection audit capacity reached; owner review required"
                )
            db.execute(
                "INSERT INTO historical_inspections VALUES(?,?,?,?,'STARTED',NULL,NULL)",
                (
                    identity,
                    user.id,
                    _utc(self.clock),
                    canonicalize_json(request).decode(),
                ),
            )
        return identity

    def inspect(
        self,
        user: User,
        dataset_id: str,
        *,
        record_digest: str,
        quality_report_digest: str,
        start: int,
        stop: int,
    ) -> JsonRecord:
        self._actor(user)
        self.quality.owns(user, dataset_id)
        require_sha256_digest(record_digest)
        require_sha256_digest(quality_report_digest)
        if (
            type(start) is not int
            or type(stop) is not int
            or not 0 <= start < stop <= 100_000
            or stop - start > 512
        ):
            raise QualityError("INSPECTION_RANGE")
        request: JsonRecord = {
            "dataset_id": dataset_id,
            "record_digest": record_digest,
            "quality_report_digest": quality_report_digest,
            "start": start,
            "stop": stop,
        }
        with self.quality.inspection(user):
            self.quality.data._capacity()
            identity = self._begin(user, request)
            try:
                detail = self.quality._receipt(
                    user, dataset_id, record_digest, quality_report_digest
                )
                snapshot, payload = self.quality.service.select(
                    dataset_id,
                    expected_record_digest=record_digest,
                    expected_report_digest=quality_report_digest,
                    purpose="EXPLORATORY_INSPECTION",
                )
                if (
                    snapshot.evidence_mode != "HISTORICAL"
                    or snapshot.admission != "HISTORICAL_EXPLORATORY"
                    or snapshot.causal_eligible
                ):
                    raise QualityError("HISTORICAL_CHART_ONLY_PROFILE_REQUIRED")
                if stop > snapshot.row_count:
                    raise QualityError("INSPECTION_RANGE")
                rows = _rows(payload, snapshot, start, stop)
                configuration = self.quality._metadata(
                    cast(str, detail["configuration_digest"])
                )
                response: JsonRecord = {
                    "inspection_id": identity,
                    "snapshot": snapshot.to_record(),
                    "source": {
                        key: detail[key]
                        for key in (
                            "source_id",
                            "raw_dataset_id",
                            "raw_digest",
                            "configuration_digest",
                            "metadata",
                        )
                    },
                    "mapping": configuration.get("mapping"),
                    "row_start": start,
                    "row_stop": stop,
                    "feature_columns": cast(
                        list[JsonValue], list(snapshot.feature_columns)
                    ),
                    "rows": rows,
                    "availability_mode": "UPLOADER_DECLARED_UNVERIFIED",
                    "causal_research": "BLOCKED",
                    "empirically_validated": False,
                    "host_enforced": False,
                    "limitations": cast(list[JsonValue], list(_LIMITATIONS)),
                }
                response_bytes = canonicalize_json(response)
                if len(response_bytes) > 1_000_000:
                    raise QualityError("INSPECTION_RESPONSE_LIMIT")
                receipt: JsonRecord = {
                    "schema_version": "qh-historical-chart-inspection-v1",
                    "inspection_id": identity,
                    "owner_id": user.id,
                    "observed_at": _utc(self.clock),
                    "request": request,
                    "snapshot": snapshot.to_record(),
                    "response_digest": "sha256:"
                    + hashlib.sha256(response_bytes).hexdigest(),
                    "response_bytes": len(response_bytes),
                    "disposition": "SERVER_PREPARED_FOR_DELIVERY; NOT_CLIENT_ACKNOWLEDGEMENT",
                    "purpose": "CHART_ONLY_EXPLORATORY_INSPECTION",
                }
                retained = self.quality.service.objects.publish(
                    canonicalize_json(receipt)
                )
                with self.state.connection() as db:
                    changed = db.execute(
                        "UPDATE historical_inspections SET status='PREPARED',receipt_digest=? WHERE id=? AND owner_id=? AND status='STARTED'",
                        (retained.digest, identity, user.id),
                    ).rowcount
                    if changed != 1:
                        raise QualityError("INSPECTION_FINALIZATION")
                return {**response, "inspection_receipt_digest": retained.digest}
            except Exception as error:
                code = "INSPECTION_FAILED"
                if (
                    isinstance(error, QualityError)
                    and len(error.code) <= 100
                    and all(c.isupper() or c.isdigit() or c == "_" for c in error.code)
                ):
                    code = error.code
                elif isinstance(error, StaleWriterError):
                    code = "STALE_DATASET_SELECTION"
                with self.state.connection() as db:
                    db.execute(
                        "UPDATE historical_inspections SET status='FAILED',error_code=? WHERE id=? AND owner_id=? AND status='STARTED'",
                        (code, identity, user.id),
                    )
                if isinstance(error, AccessError | QualityError | StaleWriterError):
                    raise
                raise QualityError("INSPECTION_FAILED") from None

    def get(self, user: User, identity: str) -> JsonRecord:
        self._actor(user)
        with self.state.connection() as db:
            row = db.execute(
                "SELECT * FROM historical_inspections WHERE id=? AND owner_id=?",
                (identity, user.id),
            ).fetchone()
        if row is None:
            raise AccessError("Historical inspection is unavailable")
        request = _record(parse_json_document(str(row["request"]).encode()))
        if row["status"] not in {"STARTED", "PREPARED", "FAILED"} or (
            (row["status"] == "PREPARED") != (row["receipt_digest"] is not None)
        ):
            raise QualityError("INSPECTION_RECEIPT_BINDING")
        receipt: JsonRecord | None = None
        if row["receipt_digest"] is not None:
            with self.quality.inspection(user):
                receipt = self.quality._metadata(str(row["receipt_digest"]))
            if (
                receipt.get("inspection_id") != identity
                or receipt.get("owner_id") != user.id
                or receipt.get("request") != request
                or receipt.get("schema_version") != "qh-historical-chart-inspection-v1"
                or receipt.get("purpose") != "CHART_ONLY_EXPLORATORY_INSPECTION"
                or receipt.get("disposition")
                != "SERVER_PREPARED_FOR_DELIVERY; NOT_CLIENT_ACKNOWLEDGEMENT"
            ):
                raise QualityError("INSPECTION_RECEIPT_BINDING")
            snapshot = _record(receipt.get("snapshot"))
            if any(
                snapshot.get(key) != request.get(key)
                for key in ("dataset_id", "record_digest", "quality_report_digest")
            ) or (
                snapshot.get("evidence_mode") != "HISTORICAL"
                or snapshot.get("admission") != "HISTORICAL_EXPLORATORY"
                or snapshot.get("causal_eligible") is not False
            ):
                raise QualityError("INSPECTION_RECEIPT_BINDING")
            require_sha256_digest(cast(str, receipt.get("response_digest")))
        return {
            "inspection_id": identity,
            "created_at": str(row["created"]),
            "request": request,
            "status": str(row["status"]),
            "error_code": row["error_code"],
            "receipt_digest": row["receipt_digest"],
            "receipt": receipt,
            "inspection": "RETAINED_AUDIT_METADATA_ONLY; NO_SOURCE_REPLAY",
        }

    def list(self, user: User, *, limit: int = 25, offset: int = 0) -> list[JsonRecord]:
        self._actor(user)
        if (
            type(limit) is not int
            or not 1 <= limit <= 50
            or type(offset) is not int
            or not 0 <= offset < _MAX_INSPECTIONS
        ):
            raise AccessError("Invalid inspection page")
        with self.state.connection() as db:
            rows = db.execute(
                "SELECT id,created,status,error_code,receipt_digest FROM historical_inspections WHERE owner_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (user.id, limit, offset),
            ).fetchall()
        return [
            {
                "inspection_id": row["id"],
                "created_at": row["created"],
                "status": row["status"],
                "error_code": row["error_code"],
                "receipt_digest": row["receipt_digest"],
            }
            for row in rows
        ]
