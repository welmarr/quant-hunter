"""Owner-private, bounded synthetic replay; Item 8 owns every research attempt."""

from __future__ import annotations

import base64
import hashlib
import re
import sqlite3
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from pathlib import Path
from typing import cast
from uuid import uuid4

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.lab import LabService
from quant_hunter.markets import InstrumentRevision, sessions
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.simulation import accounting as a
from quant_hunter.simulation import paper_engine as p
from quant_hunter.web.admission import resource_counts
from quant_hunter.web.state import AccessError, AppState, User

D = Decimal
START = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
BUSY = {"STARTING", "STEPPING", "RECOVERING"}
MAX_JOBS = 32
MAX_EVENTS = 600
MAX_AUDIT_BYTES = 24 * 1024 * 1024
MAX_EVENT_BYTES = 4096
FINALIZATION_HEADROOM = 12
SOURCE_FILES = (
    "web/paper_access.py",
    "web/paper_halt.py",
    "web/admission.py",
    "simulation/paper_engine.py",
    "simulation/accounting.py",
    "lab/service.py",
    "markets/instruments.py",
    "markets/calendars.py",
)


class PaperWorkflowError(ValueError):
    """A bounded workflow refusal; exception messages contain no request content."""


class PaperConflictError(PaperWorkflowError):
    """State or capacity prevents the requested transition."""


def _resume_admission_missing(
    user: User, paper_id: str, expected_revision: int
) -> AbstractContextManager[object]:
    raise PaperConflictError("RESUME_READ_ADMISSION_REQUIRED")


def _json(value: object) -> JsonValue:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if is_dataclass(value) and not isinstance(value, type):
        return _json(asdict(value))
    if isinstance(value, tuple | list):
        return [_json(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json(item) for key, item in value.items()}
    raise PaperWorkflowError("INVALID_EVIDENCE_TYPE")


def _record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise PaperWorkflowError("INVALID_EVIDENCE_RECORD")
    return value


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes, maximum: int = 2_000_000) -> JsonRecord:
    if not 1 <= len(raw) <= maximum:
        raise PaperWorkflowError("EVIDENCE_SIZE")
    result = _record(parse_json_document(raw))
    if canonicalize_json(result) != raw:
        raise PaperWorkflowError("NONCANONICAL_EVIDENCE")
    return result


def _stamp(value: datetime) -> str:
    return cast(str, _json(value))


def _at(value: JsonValue) -> datetime:
    if not isinstance(value, str) or not value.endswith(("Z", "+00:00")):
        raise PaperWorkflowError("UTC_REQUIRED")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def default_paper_config(market: str = "EQUITY") -> JsonRecord:
    """Explicit editable inputs; neither this function nor create evaluates them."""
    return {
        "market": market,
        "mode": "LOCAL_PAPER",
        "bars": 24,
        "lookback": 2,
        "initial_cash": "10000",
        "quantity": "1000" if market == "FX_SPOT" else "10",
        "max_fill_quantity": "400" if market == "FX_SPOT" else "4",
        "commission_per_fill": "1",
        "slippage_bps": "1",
        "max_order_notional": "5000",
        "max_exposure": "5000",
        "max_concentration": "0.8",
        "max_drawdown": "0.2",
        "max_loss": "2000",
        "max_spread_bps": "10",
        "max_slippage_bps": "5",
        "max_orders_per_window": 20,
    }


def validate_paper_config(value: Mapping[str, JsonValue]) -> JsonRecord:
    config = dict(value)
    if set(config) != set(default_paper_config()):
        raise PaperWorkflowError("CLOSED_CONFIGURATION_REQUIRED")
    if not isinstance(config["market"], str) or not isinstance(config["mode"], str):
        raise PaperWorkflowError("UNSUPPORTED_PROFILE")
    if config["market"] not in {"EQUITY", "ETF", "FX_SPOT"} or config["mode"] not in {
        "LOCAL_PAPER",
        "REPLAY",
    }:
        raise PaperWorkflowError("UNSUPPORTED_PROFILE")
    for key, lower, upper in (
        ("bars", 20, 100),
        ("lookback", 1, 10),
        ("max_orders_per_window", 1, 100),
    ):
        item = config[key]
        if type(item) is not int or not lower <= item <= upper:
            raise PaperWorkflowError("INTEGER_RANGE")
    for key in set(config) - {
        "market",
        "mode",
        "bars",
        "lookback",
        "max_orders_per_window",
    }:
        number = config[key]
        if not isinstance(number, str) or not re.fullmatch(
            r"(?:0|[1-9][0-9]{0,6})(?:[.][0-9]{1,6})?", number
        ):
            raise PaperWorkflowError("DECIMAL_RANGE")
        parsed = D(number)
        if parsed > 1_000_000 or (
            parsed == 0 and key not in {"commission_per_fill", "slippage_bps"}
        ):
            raise PaperWorkflowError("DECIMAL_RANGE")
    for key in ("quantity", "max_fill_quantity"):
        units = D(cast(str, config[key]))
        if units != units.to_integral_value():
            raise PaperWorkflowError("LOT_GRID")
    if D(cast(str, config["max_fill_quantity"])) > D(cast(str, config["quantity"])):
        raise PaperWorkflowError("FILL_CAP_RANGE")
    if any(D(cast(str, config[k])) > 1 for k in ("max_concentration", "max_drawdown")):
        raise PaperWorkflowError("FRACTION_RANGE")
    if any(
        D(cast(str, config[k])) > 1000
        for k in ("slippage_bps", "max_slippage_bps", "max_spread_bps")
    ):
        raise PaperWorkflowError("BASIS_POINT_RANGE")
    return config


def _instrument_payload(market: str) -> JsonRecord:
    fx = market == "FX_SPOT"
    return {
        "instrument": {
            "asset_class": market,
            "venue": "OTC_NY_17_CONVENTION" if fx else "XNYS",
            "base_currency": "EUR" if fx else "USD",
            "quote_currency": "USD",
            "price_precision": 5 if fx else 2,
            "quantity_precision": 0,
            "lot_size": "1",
            "tick_size": "0.00001" if fx else "0.01",
            "multiplier": "1",
            "timezone": "America/New_York",
            "calendar_id": "FX_NY_17" if fx else "XNYS",
            "activity": [{"start": _stamp(START), "end": None}],
            "symbols": [
                {
                    "symbol": "EUR/USD"
                    if fx
                    else ("SYNTH_ETF" if market == "ETF" else "SYNTH_EQ"),
                    "start": _stamp(START),
                    "end": None,
                }
            ],
            "status": "ACTIVE",
        },
        "reason": "Synthetic replay metadata, not a historical security claim",
        "evidence_mode": "SYNTHETIC",
        "source_reference": "SYNTHETIC_TEST_ONLY",
    }


def _prepare(config: JsonRecord, instrument: JsonRecord) -> tuple[JsonRecord, bytes]:
    """Generate only deterministic inputs. No signal, return, fit or book evaluation."""
    metadata = _record(instrument["record"])
    item = _record(metadata["instrument"])
    schedule = sessions(
        cast(str, item["calendar_id"]), date(2024, 1, 2), date(2024, 1, 2)
    )
    count = cast(int, config["bars"])
    tick = D(cast(str, item["tick_size"]))
    base_ticks = 100_000 if config["market"] == "FX_SPOT" else 10_000
    changes = (0, 20, 40, 10, -20, -30, 30, 50)
    bars: list[JsonValue] = []
    with localcontext(a.CONTEXT):
        for index in range(count):
            opening = START + timedelta(minutes=index)
            closing = opening + timedelta(seconds=59)
            open_mid = D(base_ticks + changes[index % len(changes)]) * tick
            close_mid = D(base_ticks + changes[(index + 1) % len(changes)]) * tick
            bars.append(
                {
                    "open_at": _stamp(opening),
                    "close_at": _stamp(closing),
                    "open_available_at": _stamp(opening),
                    "close_available_at": _stamp(closing),
                    "open_bid": str(open_mid - tick),
                    "open_ask": str(open_mid + tick),
                    "close_bid": str(close_mid - tick),
                    "close_ask": str(close_mid + tick),
                }
            )
    frozen: JsonRecord = {
        **config,
        "evidence_mode": "SYNTHETIC",
        "random_seed": 0,
        "dataset_start": _stamp(START),
        "dataset_end": _stamp(START + timedelta(minutes=count)),
        "instrument_id": metadata["instrument_id"],
        "instrument_revision_digest": instrument["digest"],
        "calendar_digest": schedule.digest,
        "generator": "fixed-eight-point-tick-cycle-v1",
        "base_ticks": base_ticks,
        "offset_ticks": list(changes),
        "half_spread_ticks": 1,
        "bar_seconds": 60,
        "close_offset_seconds": 59,
        "quote_receipt_delay_seconds": 0,
        "accounting_symbol": (
            "EUR_USD"
            if config["market"] == "FX_SPOT"
            else ("SYNTH_ETF" if config["market"] == "ETF" else "SYNTH_EQ")
        ),
        "decision_policy": "close_bid[index] > close_bid[index-lookback]; long fixed quantity else flat",
        "execution_policy": "strictly next or later open; at most one partial fill per bar; cancel rejected match remainder",
        "commission_policy": "per fill; reserve ceil(order quantity / max fill quantity) times fee",
        "end_policy": "cancel unfilled remainder, retain bid-marked holdings; no fabricated liquidation",
        "financing_policy": "zero for fully funded intraday long spot; borrow, leverage, overnight carry unsupported",
        "max_quote_age_seconds": 60,
        "order_window_seconds": 3600,
        "software_method": {
            "implemented_scope": "Deterministic causal replay with actual persistent Decimal accounting and risk decisions; no empirical strategy validation",
            "source_citations": ["Repository specification: docs/v0/PAPER_WORKFLOW.md"],
            "assumptions": [
                "Synthetic one-minute cash-funded long equity, ordinary ETF or FX spot only",
                "Fixed seed zero means no random draws or parameter search",
                "Synthetic price availability is fixture-defined, not provider evidence",
            ],
            "cost_model": "Explicit executable bid/ask, tick-rounded adverse slippage and per-partial-fill commission; zero declared intraday financing",
        },
    }
    return frozen, canonicalize_json(
        {
            "format": "v0-paper-fixture-1",
            "evidence_mode": "SYNTHETIC",
            "instrument": metadata,
            "instrument_revision_digest": instrument["digest"],
            "calendar": schedule.to_record(),
            "bars": bars,
        }
    )


def _spec(config: JsonRecord, fixture: JsonRecord) -> a.InstrumentSpec:
    canonical = _record(fixture["instrument"])
    metadata = InstrumentRevision.from_record(
        {
            key: value
            for key, value in canonical.items()
            if key
            not in {
                "schema_version",
                "instrument_id",
                "revision",
                "previous_revision_digest",
            }
        }
    ).instrument
    expected = _record(_instrument_payload(cast(str, config["market"]))["instrument"])
    actual = _record(canonical["instrument"])
    if (
        {key: value for key, value in actual.items() if key != "instrument_id"}
        != expected
        or canonical["evidence_mode"] != "SYNTHETIC"
        or canonical["source_reference"] != "SYNTHETIC_TEST_ONLY"
    ):
        raise PaperWorkflowError("SYNTHETIC_INSTRUMENT_PROFILE")
    calendar = _record(fixture["calendar"])
    if _hash(canonicalize_json(calendar)) != config["calendar_digest"]:
        raise PaperWorkflowError("CALENDAR_DIGEST_MISMATCH")
    windows = tuple(
        a.TradingWindow(_at(_record(s)["open_at"]), _at(_record(s)["close_at"]))
        for s in cast(list[JsonValue], calendar["sessions"])
    )
    return a.InstrumentSpec(
        metadata.instrument_id,
        cast(str, config["accounting_symbol"]),
        metadata.asset_class,
        metadata.quote_currency,
        metadata.lot_size,
        metadata.tick_size,
        windows,
        metadata.base_currency if metadata.asset_class == "FX_SPOT" else None,
    )


def _limits(config: JsonRecord, strategy_id: str) -> p.RiskLimits:
    return p.RiskLimits(
        D(cast(str, config["max_order_notional"])),
        D(cast(str, config["max_exposure"])),
        D(cast(str, config["max_exposure"])),
        D(cast(str, config["max_concentration"])),
        D(cast(str, config["max_drawdown"])),
        D(cast(str, config["max_loss"])),
        D(cast(str, config["max_spread_bps"])),
        D(cast(str, config["max_slippage_bps"])),
        60,
        cast(int, config["max_orders_per_window"]),
        3600,
        (p.StrategyBudget(strategy_id, D(cast(str, config["max_exposure"]))),),
    )


class PaperAccess:
    """Trusted scheduler bridge. Authentication and runtime lease remain host duties."""

    def __init__(
        self,
        state: AppState,
        lab: LabService,
        engine: p.PaperEngine,
        *,
        capacity: Callable[[], None] = lambda: None,
        instrument_factory: Callable[[JsonRecord], JsonRecord] | None = None,
        fault: Callable[[str], None] = lambda phase: None,
        resume_resource: Callable[
            [User, str, int], AbstractContextManager[object]
        ] = _resume_admission_missing,
    ) -> None:
        if engine.path.resolve() != (state.path.parent / "paper.sqlite3").resolve():
            raise PaperWorkflowError("DEDICATED_PAPER_DATABASE_REQUIRED")
        self.state, self.lab, self.engine = state, lab, engine
        self.capacity, self.fault = capacity, fault
        self.resume_resource = resume_resource
        self.instrument_factory = (
            instrument_factory or InstrumentRegistry(lab.registry).create
        )
        self._source_digest = self._source(lab.environment_digest, current=True)
        with state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS paper_jobs (
                    id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
                    status TEXT NOT NULL, experiment_id TEXT, payload BLOB NOT NULL,
                    digest TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS paper_events (
                    job_id TEXT NOT NULL REFERENCES paper_jobs(id), sequence INTEGER NOT NULL,
                    payload BLOB NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL,
                    PRIMARY KEY(job_id, sequence));
                CREATE TABLE IF NOT EXISTS paper_step_receipts (
                    job_id TEXT NOT NULL REFERENCES paper_jobs(id), operation INTEGER NOT NULL,
                    digest TEXT NOT NULL, PRIMARY KEY(job_id, operation));
                CREATE TRIGGER IF NOT EXISTS paper_event_update BEFORE UPDATE ON paper_events BEGIN SELECT RAISE(ABORT,'immutable paper event'); END;
                CREATE TRIGGER IF NOT EXISTS paper_event_delete BEFORE DELETE ON paper_events BEGIN SELECT RAISE(ABORT,'immutable paper event'); END;
                CREATE TRIGGER IF NOT EXISTS paper_receipt_update BEFORE UPDATE ON paper_step_receipts BEGIN SELECT RAISE(ABORT,'immutable paper receipt'); END;
                CREATE TRIGGER IF NOT EXISTS paper_receipt_delete BEFORE DELETE ON paper_step_receipts BEGIN SELECT RAISE(ABORT,'immutable paper receipt'); END;
            """)

    def _source(self, environment_digest: str, *, current: bool) -> str:
        environment = self._object(environment_digest)
        digest = environment.get("source_snapshot_digest")
        if not isinstance(digest, str):
            raise PaperWorkflowError("SOURCE_SNAPSHOT_REQUIRED")
        source = self._object(digest, maximum=64 * 1024 * 1024)
        files = _record(source.get("files"))
        if source.get("encoding") != "base64-exact-bytes":
            raise PaperWorkflowError("SOURCE_ENCODING")
        package = Path(__file__).resolve().parents[1]
        for name in SOURCE_FILES:
            encoded = files.get("src/quant_hunter/" + name)
            if name == "web/paper_halt.py" and not current and encoded is None:
                producer = files.get("src/quant_hunter/web/paper_access.py")
                try:
                    old_bytes = base64.b64decode(cast(str, producer), validate=True)
                except TypeError, ValueError:
                    raise PaperWorkflowError("SOURCE_ENCODING") from None
                if b"quant_hunter.web.paper_halt" not in old_bytes:
                    # Historical producers predating the halt do not depend on it.
                    # New producers and all current execution still require it.
                    continue
            if not isinstance(encoded, str):
                raise PaperWorkflowError("SOURCE_FILE_MISSING")
            try:
                exact = base64.b64decode(encoded, validate=True)
            except ValueError:
                raise PaperWorkflowError("SOURCE_ENCODING") from None
            if current and exact != (package / name).read_bytes():
                raise PaperWorkflowError("EXECUTING_SOURCE_MISMATCH")
        return digest

    def _object(self, digest: str, *, maximum: int = 2_000_000) -> JsonRecord:
        path = self.lab.objects.get(digest).path
        if path.stat().st_size > maximum:
            raise PaperWorkflowError("EVIDENCE_SIZE")
        return _decode(path.read_bytes(), maximum)

    @staticmethod
    def _actor(db: sqlite3.Connection, user: User, *, mutation: bool) -> None:
        actual = db.execute(
            "SELECT username,role FROM users WHERE id=?", (user.id,)
        ).fetchone()
        if (
            actual is None
            or tuple(actual) != (user.username, user.role)
            or (mutation and user.role == "reader")
        ):
            raise AccessError("Paper access denied")

    def _load(
        self, db: sqlite3.Connection, job_id: str, owner: int | None = None
    ) -> JsonRecord:
        row = db.execute("SELECT * FROM paper_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None or (owner is not None and row["owner_id"] != owner):
            raise AccessError("Paper session unavailable")
        previous = ""
        last: JsonRecord | None = None
        for index, event in enumerate(
            db.execute(
                "SELECT * FROM paper_events WHERE job_id=? ORDER BY sequence", (job_id,)
            ),
            1,
        ):
            payload = bytes(event["payload"])
            digest = _hash(previous.encode() + payload)
            last = _decode(payload)
            if (
                index > MAX_EVENTS
                or event["sequence"] != index
                or event["previous"] != previous
                or event["digest"] != digest
                or last["id"] != job_id
                or last["owner_id"] != row["owner_id"]
                or last["revision"] != index
            ):
                raise PaperWorkflowError("OPERATIONAL_CHAIN_INTEGRITY")
            previous = digest
        if (
            last is None
            or canonicalize_json(last) != bytes(row["payload"])
            or previous != row["digest"]
            or last["revision"] != row["revision"]
            or last["status"] != row["status"]
            or last["experiment_id"] != row["experiment_id"]
        ):
            raise PaperWorkflowError("OPERATIONAL_HEAD_INTEGRITY")
        return last

    def _save(
        self, db: sqlite3.Connection, row: JsonRecord, changes: JsonRecord, event: str
    ) -> JsonRecord:
        current = db.execute(
            "SELECT revision,digest FROM paper_jobs WHERE id=?", (row["id"],)
        ).fetchone()
        if current is None or current[0] != row["revision"]:
            raise PaperConflictError("STALE_WORKFLOW_REVISION")
        version = cast(int, row["revision"]) + 1
        if version > MAX_EVENTS:
            raise PaperConflictError("SESSION_EVENT_LIMIT")
        result: JsonRecord = {
            **row,
            **changes,
            "revision": version,
            "last_event": event,
            "updated_at": _stamp(datetime.now(UTC)),
        }
        payload = canonicalize_json(result)
        used = db.execute(
            "SELECT COALESCE(SUM(length(payload)),0) FROM paper_events"
        ).fetchone()[0]
        if len(payload) > MAX_EVENT_BYTES or used + len(payload) > MAX_AUDIT_BYTES:
            raise PaperConflictError("OPERATIONAL_CAPACITY")
        digest = _hash(cast(str, current[1]).encode() + payload)
        db.execute(
            "INSERT INTO paper_events VALUES(?,?,?,?,?)",
            (row["id"], version, payload, current[1], digest),
        )
        db.execute(
            "UPDATE paper_jobs SET status=?,experiment_id=?,payload=?,digest=?,revision=? WHERE id=?",
            (
                result["status"],
                result["experiment_id"],
                payload,
                digest,
                version,
                row["id"],
            ),
        )
        return result

    def _queue_capacity(self, db: sqlite3.Connection) -> None:
        # Reserve worst-case remaining bytes before admitting another session.
        # Terminal heads retain one timing-event allowance for a finishing worker.
        used = db.execute(
            "SELECT COALESCE(SUM(length(payload)),0) FROM paper_events"
        ).fetchone()[0]
        remaining = sum(
            1 if item["status"] in TERMINAL else max(1, MAX_EVENTS - item["revision"])
            for item in db.execute("SELECT status,revision FROM paper_jobs")
        )
        if used + (remaining + MAX_EVENTS) * MAX_EVENT_BYTES > MAX_AUDIT_BYTES:
            raise PaperConflictError("AUDIT_RESERVATION_CAPACITY")
        if resource_counts(db)[1] >= 8:
            raise PaperConflictError("SHARED_QUEUE_LIMIT")

    def create(self, user: User, config: Mapping[str, JsonValue]) -> JsonRecord:
        validated = validate_paper_config(config)
        with self.state.connection() as db:
            self._actor(db, user, mutation=True)
        self.capacity()
        identity = "PAPER-" + uuid4().hex
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._actor(db, user, mutation=True)
            self._queue_capacity(db)
            if db.execute("SELECT count(*) FROM paper_jobs").fetchone()[0] >= MAX_JOBS:
                raise PaperConflictError("SESSION_LIFETIME_LIMIT")
            row: JsonRecord = {
                "id": identity,
                "owner_id": user.id,
                "status": "CREATED",
                "configuration": validated,
                "configuration_digest": _hash(canonicalize_json(validated)),
                "experiment_id": None,
                "cursor": 0,
                "bars": validated["bars"],
                "report_digest": None,
                "error": None,
                "requested": None,
                "inflight": None,
                "controls": 0,
                "operation": 0,
                "revision": 0,
                "created_at": _stamp(datetime.now(UTC)),
                "elapsed_milliseconds": 0,
            }
            db.execute(
                "INSERT INTO paper_jobs VALUES(?,?,?,?,?,?,?)",
                (identity, user.id, "CREATED", None, b"", "", 0),
            )
            self._save(db, row, {}, "CREATED")
        return self.get(user, identity)

    def list_sessions(self, user: User) -> list[JsonRecord]:
        with self.state.connection() as db:
            self._actor(db, user, mutation=False)
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM paper_jobs WHERE owner_id=? ORDER BY rowid DESC",
                    (user.id,),
                )
            ]
            rows = [self._load(db, identity, user.id) for identity in ids]
        # Detail explicitly verifies and loads the large canonical report. A list
        # never expands32 full ledgers or claims a fresh scientific evaluation.
        return [
            {
                **row,
                "evidence_mode": "SYNTHETIC",
                "network_enabled": False,
                "status_authority": "OPERATIONAL_SESSION",
            }
            for row in rows
        ]

    def get(self, user: User, job_id: str) -> JsonRecord:
        with self.state.connection() as db:
            self._actor(db, user, mutation=False)
            row = self._load(db, job_id, user.id)
        report = (
            self._object(cast(str, row["report_digest"]))
            if row["report_digest"]
            else None
        )
        if report is not None and (
            report["job_id"] != job_id
            or report["experiment_id"] != row["experiment_id"]
        ):
            raise PaperWorkflowError("REPORT_BINDING")
        run = self._binding(row)[0] if row["experiment_id"] else None
        return {
            **row,
            "report": report,
            "evidence_mode": "SYNTHETIC",
            "scientific_disposition": "FAILED"
            if run and run["evaluation_outcome"] == "FAILED"
            else "INCONCLUSIVE",
            "lifecycle_status": run["lifecycle_status"] if run else None,
            "evaluation_outcome": run["evaluation_outcome"] if run else None,
            "network_enabled": False,
        }

    def operational_head(self, user: User, job_id: str) -> JsonRecord:
        """Private verified acknowledgement, without replaying source/report bytes."""
        with self.state.connection() as db:
            self._actor(db, user, mutation=False)
            row = self._load(db, job_id, user.id)
        return {
            **row,
            "evidence_mode": "SYNTHETIC",
            "network_enabled": False,
            "status_authority": "OPERATIONAL_SESSION",
            "report_verification": "NOT_FRESH_ADMISSION",
        }

    def execution_receipt(
        self, user: User, job_id: str, *, workflow_revision: int
    ) -> JsonRecord:
        """Inspect an original paused execution report through its retained chain."""
        with self.state.connection() as db:
            self._actor(db, user, mutation=False)
            if user.role != "owner":
                raise AccessError("Owner role required for broker protocol checks")
            head = self._load(db, job_id, user.id)
            if type(workflow_revision) is not int or not 1 <= workflow_revision <= cast(
                int, head["revision"]
            ):
                raise PaperWorkflowError("EXECUTION_RECEIPT_REVISION")
            event = db.execute(
                "SELECT payload FROM paper_events WHERE job_id=? AND sequence=?",
                (job_id, workflow_revision),
            ).fetchone()
            if event is None:
                raise PaperWorkflowError("EXECUTION_RECEIPT_MISSING")
            original = _decode(bytes(event[0]))
        if (
            original["status"] != "PAUSED"
            or original["requested"] is not None
            or original["inflight"] is not None
            or original["experiment_id"] is None
        ):
            raise PaperWorkflowError("EXECUTION_RECEIPT_STATE")
        run, _ = self._binding(original)
        report = self._object(cast(str, original["report_digest"]))
        snapshot = _record(report.get("snapshot"))
        if (
            report.get("job_id") != job_id
            or report.get("experiment_id") != original["experiment_id"]
            or report.get("completed_bars") != original["cursor"]
            or snapshot.get("owner_id") != str(user.id)
        ):
            raise PaperWorkflowError("EXECUTION_RECEIPT_BINDING")
        return {
            "context": {
                "paper_id": job_id,
                "workflow_revision": workflow_revision,
                "report_digest": original["report_digest"],
                "experiment_id": original["experiment_id"],
                "strategy_id": _record(run["bindings"])["strategy_id"],
                "snapshot_digest": _hash(canonicalize_json(snapshot)),
                "mode": original["configuration"]["mode"]
                if isinstance(original["configuration"], dict)
                else None,
                "evidence_mode": "SYNTHETIC",
                "network_order_authority": False,
            },
            "snapshot": snapshot,
        }

    def control(
        self, user: User, job_id: str, action: str, *, expected_revision: int
    ) -> JsonRecord:
        from quant_hunter.web.paper_halt import gate_lock, halted, proof_lock

        if action not in {"ACTIVATE", "RESUME", "RESET_KILL"}:
            with proof_lock(self.state.path):
                return self._control(
                    user, job_id, action, expected_revision=expected_revision
                )
        with gate_lock(self.state.path), proof_lock(self.state.path):
            with self.state.connection() as db:
                self._actor(db, user, mutation=True)
                self._load(db, job_id, user.id)
                if halted(db) and action in {"ACTIVATE", "RESUME", "RESET_KILL"}:
                    raise PaperConflictError("GLOBAL_PAPER_HALTED")
            return self._control(
                user, job_id, action, expected_revision=expected_revision
            )

    def _control(
        self, user: User, job_id: str, action: str, *, expected_revision: int
    ) -> JsonRecord:
        if action not in {
            "ACTIVATE",
            "PAUSE",
            "RESUME",
            "CANCEL",
            "KILL",
            "RESET_KILL",
        }:
            raise PaperWorkflowError("UNSUPPORTED_CONTROL")
        if type(expected_revision) is not int:
            raise PaperWorkflowError("REVISION_REQUIRED")
        if action == "RESUME":
            with self.state.connection() as db:
                self._actor(db, user, mutation=True)
                candidate = self._load(db, job_id, user.id)
            if candidate["experiment_id"]:
                with self.resume_resource(user, job_id, expected_revision):
                    self._binding(candidate, current=True)
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._actor(db, user, mutation=True)
            row = self._load(db, job_id, user.id)
            if row["revision"] != expected_revision:
                raise PaperConflictError("STALE_WORKFLOW_REVISION")
            if (
                cast(int, row["revision"]) >= MAX_EVENTS - FINALIZATION_HEADROOM
                and action != "CANCEL"
            ):
                raise PaperConflictError("FINALIZATION_CAPACITY_RESERVED")
            if (
                row["status"] in TERMINAL
                or cast(int, row["controls"]) >= 64
                or (cast(int, row["controls"]) >= 63 and action != "CANCEL")
                or row["requested"] == "CANCEL"
                or (row["requested"] and action != "CANCEL")
            ):
                raise PaperConflictError("CONTROL_NOT_AVAILABLE")
            status = row["status"]
            changes: JsonRecord = {"controls": cast(int, row["controls"]) + 1}
            if action == "ACTIVATE" and status == "CREATED":
                changes["status"] = "ACTIVE"
            elif action == "RESUME" and status == "PAUSED":
                changes["status"] = "ACTIVE"
            elif action == "PAUSE" and status == "ACTIVE":
                changes["status"] = "PAUSED"
            elif (
                action == "CANCEL"
                and status in {"CREATED", "ACTIVE", "PAUSED", "AMBIGUOUS"}
                and row["experiment_id"] is None
            ):
                changes["status"] = "CANCELLED"
            elif (
                action in {"CANCEL", "KILL", "RESET_KILL"}
                and row["experiment_id"]
                and status not in {"CREATED", "STARTING"}
            ):
                if status == "AMBIGUOUS" and action != "CANCEL":
                    raise PaperConflictError("RECONCILIATION_REQUIRED")
                changes["requested"] = action
            elif status in BUSY and action in {"PAUSE", "CANCEL", "KILL"}:
                changes["requested"] = action
            else:
                raise PaperConflictError("INVALID_CONTROL_STATE")
            self._save(db, row, changes, action + "_REQUESTED")
        return self.operational_head(user, job_id)

    def execution_snapshot(
        self, user: User, job_id: str, *, expected_revision: int
    ) -> tuple[JsonRecord, p.PaperSnapshot]:
        """Verify a paused owned reservation for an offline protocol demonstration.

        This is neither a new economic reservation nor permission for a network
        order. The trusted caller admits the shared resource slot first and must
        recheck this exact snapshot before retaining a current result.
        """
        with self.state.connection() as db:
            self._actor(db, user, mutation=True)
            if user.role != "owner":
                raise AccessError("Owner role required for broker protocol checks")
            row = self._load(db, job_id, user.id)
            if (
                type(expected_revision) is not int
                or row["revision"] != expected_revision
                or row["status"] != "PAUSED"
                or row["requested"] is not None
                or row["inflight"] is not None
                or row["experiment_id"] is None
            ):
                raise PaperConflictError("PAUSED_EXECUTION_SNAPSHOT_REQUIRED")
        run, _ = self._binding(row, current=True)
        if run["lifecycle_status"] != "RUNNING" or run["variants_attempted"] != 0:
            raise PaperConflictError("RESEARCH_ATTEMPT_ALREADY_TERMINAL")
        snapshot = self._snapshot(row)
        report = self._object(cast(str, row["report_digest"]))
        if (
            report["snapshot"] != _json(snapshot)
            or report["completed_bars"] != row["cursor"]
        ):
            raise PaperConflictError("UNJOURNALLED_ENGINE_CHANGE")
        if (
            snapshot.killed
            or not snapshot.healthy
            or not snapshot.reconciled
            or len(snapshot.reservations) != 1
        ):
            raise PaperConflictError("ACTIVE_RISK_RESERVATION_REQUIRED")
        reservation = snapshot.reservations[0]
        orders = [
            order
            for order in snapshot.book.orders
            if order.order_id == reservation.order_id
        ]
        quotes = [
            quote
            for quote in snapshot.quotes
            if quote.instrument_id == reservation.instrument_id
        ]
        specs = [
            spec
            for spec in snapshot.book.instruments
            if spec.instrument_id == reservation.instrument_id
        ]
        if (
            len(orders) != 1
            or len(quotes) != 1
            or len(specs) != 1
            or orders[0].status not in {"OPEN", "PARTIALLY_FILLED"}
            or orders[0].quantity - orders[0].filled != reservation.remaining
            or orders[0].side != reservation.side
            or not specs[0].is_open(snapshot.at)
            or quotes[0].available_at > snapshot.at
            or not timedelta(0)
            <= snapshot.at - quotes[0].at
            <= timedelta(seconds=snapshot.limits.max_quote_age_seconds)
        ):
            raise PaperConflictError("RESERVATION_OR_QUOTE_STATE_INVALID")
        manifest = _record(run["bindings"])
        if reservation.strategy_id != manifest["strategy_id"]:
            raise PaperWorkflowError("RESERVATION_STRATEGY_BINDING")
        with self.state.connection() as db:
            self._actor(db, user, mutation=True)
            if self._load(db, job_id, user.id) != row:
                raise PaperConflictError("EXECUTION_SNAPSHOT_CHANGED")
        if self.engine.load(job_id, str(user.id)) != snapshot:
            raise PaperConflictError("EXECUTION_SNAPSHOT_CHANGED")
        return {
            "paper_id": job_id,
            "workflow_revision": expected_revision,
            "report_digest": row["report_digest"],
            "experiment_id": row["experiment_id"],
            "strategy_id": reservation.strategy_id,
            "snapshot_digest": _hash(canonicalize_json(_json(snapshot))),
            "mode": snapshot.provenance.mode,
            "evidence_mode": "SYNTHETIC",
            "network_order_authority": False,
        }, snapshot

    def _binding(
        self, row: JsonRecord, *, current: bool = False
    ) -> tuple[JsonRecord, JsonRecord]:
        run = self.lab.get_run(cast(str, row["experiment_id"]))
        frozen = _record(run["configuration"])
        manifest = _record(run["bindings"])
        original = _record(row["configuration"])
        if (
            frozen.get("paper_job_id") != row["id"]
            or frozen.get("paper_owner_id") != row["owner_id"]
            or any(frozen.get(key) != value for key, value in original.items())
            or _hash(canonicalize_json(original)) != row["configuration_digest"]
        ):
            raise PaperWorkflowError("CANONICAL_OWNER_BINDING")
        self._source(cast(str, manifest["environment_digest"]), current=current)
        if current and (
            manifest["environment_digest"] != self.lab.environment_digest
            or manifest["code_revision"] != self.lab.code_revision
        ):
            raise PaperWorkflowError("EXECUTION_ENVIRONMENT_CHANGED")
        revisions = self.lab.registry.verify_object(cast(str, frozen["instrument_id"]))
        if not any(
            rev.digest == frozen["instrument_revision_digest"] for rev in revisions
        ):
            raise PaperWorkflowError("INSTRUMENT_REVISION_MISSING")
        fixture = self._object(cast(str, manifest["dataset_digest"]))
        if fixture["instrument_revision_digest"] != frozen[
            "instrument_revision_digest"
        ] or fixture["instrument"] != next(
            rev.record
            for rev in revisions
            if rev.digest == frozen["instrument_revision_digest"]
        ):
            raise PaperWorkflowError("INSTRUMENT_FIXTURE_BINDING")
        return run, fixture

    def _snapshot(self, row: JsonRecord) -> p.PaperSnapshot:
        run, fixture = self._binding(row)
        manifest = _record(run["bindings"])
        frozen = _record(run["configuration"])
        state = self.engine.load(cast(str, row["id"]), str(row["owner_id"]))
        expected = p.Provenance(
            cast(str, row["experiment_id"]),
            self._source(cast(str, manifest["environment_digest"]), current=False),
            cast(str, manifest["environment_digest"]),
            cast(str, manifest["configuration_digest"]),
            "SYNTHETIC",
            cast(str, frozen["mode"]),
        )
        if (
            state.provenance != expected
            or state.book.instruments != (_spec(frozen, fixture),)
            or state.book.base_currency != "USD"
            or state.limits != _limits(frozen, cast(str, manifest["strategy_id"]))
            or state.inception_equity != D(cast(str, frozen["initial_cash"]))
        ):
            raise PaperWorkflowError("PAPER_GENESIS_BINDING")
        return state

    def has_pending(self) -> bool:
        with self.state.connection() as db:
            return (
                db.execute(
                    "SELECT 1 FROM paper_jobs WHERE status NOT IN ('STARTING','STEPPING','RECOVERING','COMPLETED','FAILED','CANCELLED') AND (status='ACTIVE' OR json_extract(payload,'$.requested') IN ('CANCEL','KILL','RESET_KILL')) AND (status!='AMBIGUOUS' OR json_extract(payload,'$.requested')='CANCEL') LIMIT 1"
                ).fetchone()
                is not None
            )

    def process_one(self) -> bool:
        """Advance one input-only initialization, control, or at most one replay bar."""
        from quant_hunter.web.paper_halt import gate_lock, halted

        lock = gate_lock(self.state.path)
        if not lock.acquire(blocking=False):
            return False
        try:
            with self.state.connection() as db:
                stopped = halted(db)
            return self._process_one(protective_only=stopped)
        finally:
            lock.release()

    def _process_one(
        self, *, protective_only: bool = False, job_id: str | None = None
    ) -> bool:
        self.capacity()
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            selected = db.execute(
                "SELECT id FROM paper_jobs WHERE status NOT IN ('STARTING','STEPPING','RECOVERING','COMPLETED','FAILED','CANCELLED') AND (status='ACTIVE' OR json_extract(payload,'$.requested') IN ('CANCEL','KILL','RESET_KILL')) AND (status!='AMBIGUOUS' OR json_extract(payload,'$.requested')='CANCEL') AND (? IS NULL OR id=?) AND (?=0 OR (experiment_id IS NOT NULL AND json_extract(payload,'$.requested') IN ('KILL','CANCEL'))) ORDER BY rowid LIMIT 1",
                (job_id, job_id, int(protective_only)),
            ).fetchone()
            if selected is None:
                return False
            if resource_counts(db)[0] >= 2:
                return False
            row = self._load(db, selected[0])
            operation = cast(int, row["operation"]) + 1
            kind = (
                "INITIALIZE"
                if row["experiment_id"] is None
                else cast(str, row["requested"] or "BAR")
            )
            if cast(
                int, row["revision"]
            ) >= MAX_EVENTS - FINALIZATION_HEADROOM and kind not in {"CANCEL", "KILL"}:
                kind = "CAPACITY"
            before: p.PaperSnapshot | None = None
            inflight: JsonRecord = {
                "kind": kind,
                "prior_status": row["status"],
                "cursor": row["cursor"],
                "operation": operation,
                "start_revision": before.revision if before else None,
                "start_digest": _hash(canonicalize_json(_json(before)))
                if before
                else None,
            }
            row = self._save(
                db,
                row,
                {
                    "status": "STARTING" if kind == "INITIALIZE" else "STEPPING",
                    "operation": operation,
                    "inflight": inflight,
                },
                "CLAIMED",
            )
        started = time.monotonic()
        try:
            if kind != "INITIALIZE":
                before = self._snapshot(row)
                if inflight["prior_status"] != "AMBIGUOUS":
                    previous = self._object(cast(str, row["report_digest"]))
                    if previous["snapshot"] != _json(before):
                        raise PaperWorkflowError("UNJOURNALLED_ENGINE_CHANGE")
                inflight["start_revision"] = before.revision
                inflight["start_digest"] = _hash(canonicalize_json(_json(before)))
                with self.state.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = self._save(
                        db,
                        self._load(db, cast(str, row["id"])),
                        {"inflight": inflight},
                        "PREPARED",
                    )
            self.fault("CLAIMED")
            if kind == "CAPACITY":
                self._fail(row, "PaperEventCapacity")
            elif kind == "INITIALIZE":
                self._initialize(row)
            else:
                with localcontext(a.CONTEXT):
                    self._advance(row, cast(p.PaperSnapshot, before), kind)
        except Exception:
            # BaseException represents a test/process crash: leave ambiguity visible.
            self._fail(row, "PaperStepFailed")
        finally:
            with self.state.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                fresh = self._load(db, cast(str, row["id"]))
                self._save(
                    db,
                    fresh,
                    {
                        "elapsed_milliseconds": cast(int, fresh["elapsed_milliseconds"])
                        + max(0, int((time.monotonic() - started) * 1000))
                    },
                    "WORKER_TIME",
                )
        return True

    def protective_halt_step(self, job_id: str, halt_revision: int) -> bool:
        """Trusted host protection, restricted to actual persisted global tasks."""
        from quant_hunter.web.paper_halt import gate_lock, proof_lock, task_authorized

        with gate_lock(self.state.path):
            with proof_lock(self.state.path), self.state.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                owner_id = task_authorized(db, job_id, halt_revision)
                row = self._load(db, job_id, owner_id)
                if row["status"] in TERMINAL:
                    return False
                if row["status"] in BUSY or row["status"] == "AMBIGUOUS":
                    raise PaperConflictError("RECONCILIATION_REQUIRED")
                if row["experiment_id"] is None:
                    if row["inflight"] is not None:
                        raise PaperConflictError("RECONCILIATION_REQUIRED")
                    if row["status"] != "CREATED":
                        self._save(
                            db,
                            row,
                            {"status": "CREATED", "requested": None},
                            "GLOBAL_NOT_STARTED",
                        )
                    return False
                if cast(int, row["revision"]) > MAX_EVENTS - 6:
                    raise PaperConflictError("PROTECTIVE_CAPACITY")
                if row["requested"] not in {"KILL", "CANCEL"}:
                    self._save(db, row, {"requested": "KILL"}, "GLOBAL_KILL_REQUESTED")
            return self._process_one(protective_only=True, job_id=job_id)

    def protection_receipt(self, job_id: str, halt_revision: int) -> JsonRecord:
        """Verify current protection under the host's read reservation and gate."""
        from quant_hunter.web.paper_halt import task_authorized

        with self.state.connection() as db:
            owner_id = task_authorized(db, job_id, halt_revision)
            row = self._load(db, job_id, owner_id)
        result: JsonRecord = {
            "job_id": job_id,
            "halt_revision": halt_revision,
            "workflow_revision": row["revision"],
            "report_digest": row["report_digest"],
            "snapshot_digest": None,
        }
        if row["status"] in TERMINAL:
            result["status"] = "TERMINAL_NOT_RUNNABLE"
        elif (
            row["status"] == "CREATED"
            and row["experiment_id"] is None
            and row["inflight"] is None
        ):
            result["status"] = "NOT_STARTED"
        elif (
            row["status"] == "PAUSED"
            and row["inflight"] is None
            and row["requested"] is None
        ):
            snapshot = self._snapshot(row)
            report = self._object(cast(str, row["report_digest"]))
            if (
                not snapshot.killed
                or snapshot.reservations
                or any(order.status in a.OPEN for order in snapshot.book.orders)
                or report.get("snapshot") != _json(snapshot)
                or report.get("job_id") != job_id
                or report.get("experiment_id") != row["experiment_id"]
            ):
                raise PaperConflictError("PROTECTION_UNVERIFIED")
            result["status"] = "PROTECTED"
            result["snapshot_digest"] = _hash(canonicalize_json(_json(snapshot)))
        else:
            raise PaperConflictError("PROTECTION_UNVERIFIED")
        return result

    def _initialize(self, row: JsonRecord) -> None:
        config = _record(row["configuration"])
        instrument = self.instrument_factory(
            _instrument_payload(cast(str, config["market"]))
        )
        frozen, payload = _prepare(config, instrument)
        frozen.update({"paper_job_id": row["id"], "paper_owner_id": row["owner_id"]})
        experiment_id = self.lab.begin_run(
            frozen, payload, name="Synthetic local paper replay"
        )
        self.fault("AFTER_BEGIN_RUN")
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._save(
                db,
                self._load(db, cast(str, row["id"])),
                {"experiment_id": experiment_id},
                "REGISTERED",
            )
        run, fixture = self._binding(row, current=True)
        spec = _spec(frozen, fixture)
        manifest = _record(run["bindings"])
        limits = _limits(frozen, cast(str, manifest["strategy_id"]))
        snapshot = self.engine.create_account(
            cast(str, row["id"]),
            str(row["owner_id"]),
            a.initial_book(
                "USD",
                START,
                (spec,),
                (a.CashBalance("USD", D(cast(str, config["initial_cash"]))),),
            ),
            limits,
            p.Provenance(
                experiment_id,
                self._source_digest,
                self.lab.environment_digest,
                cast(str, manifest["configuration_digest"]),
                "SYNTHETIC",
                cast(str, config["mode"]),
            ),
        )
        snapshot = self._snapshot(row)
        self.fault("AFTER_ACCOUNT")
        report = self._report(row, snapshot, [], 0)
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            fresh = self._load(db, cast(str, row["id"]))
            self._save(
                db,
                fresh,
                {
                    "status": "PAUSED" if fresh["requested"] == "PAUSE" else "ACTIVE",
                    "requested": None
                    if fresh["requested"] == "PAUSE"
                    else fresh["requested"],
                    "inflight": None,
                    "report_digest": report,
                },
                "INITIALIZED",
            )

    def _report(
        self,
        row: JsonRecord,
        snapshot: p.PaperSnapshot | None,
        signals: list[JsonValue],
        cursor: int,
        *,
        error: str | None = None,
    ) -> str:
        report: JsonRecord = {
            "format": "v0-paper-report-1",
            "job_id": row["id"],
            "experiment_id": row["experiment_id"],
            "evidence_mode": "SYNTHETIC",
            "scientific_disposition": "FAILED" if error else "INCONCLUSIVE",
            "completed_bars": cursor,
            "signals": signals,
            "snapshot": _json(snapshot),
            "error": error,
            "limitations": [
                "Synthetic deterministic software demonstration, not empirical profitability",
                "Long cash-funded intraday spot only; shorts, leverage, derivatives, overnight financing and external orders unsupported",
                "Closing equity retains bid-marked positions, without assuming liquidation or an exit fee",
            ],
        }
        if snapshot:
            rejected = [o for o in snapshot.outcomes if o.status == "REJECTED"]
            with localcontext(a.CONTEXT):
                commissions = sum((f.commission for f in snapshot.book.fills), D(0))
                slippage = sum((f.adverse_slippage for f in snapshot.book.fills), D(0))
            report.update(
                {
                    "engine_rejections": _json(rejected),
                    "first_rejected_reason": rejected[0].reason if rejected else None,
                    "commissions": str(commissions),
                    "adverse_slippage": str(slippage),
                    "equity": str(snapshot.equity),
                    "max_drawdown": str(snapshot.max_drawdown),
                }
            )
        return self.lab.objects.publish(canonicalize_json(report)).digest

    def _advance(self, row: JsonRecord, snapshot: p.PaperSnapshot, kind: str) -> None:
        run, fixture = self._binding(row, current=True)
        if run["lifecycle_status"] != "RUNNING" or run["variants_attempted"] != 0:
            raise PaperWorkflowError("RESEARCH_ATTEMPT_ALREADY_TERMINAL")
        config = _record(run["configuration"])
        manifest = _record(run["bindings"])
        cursor = cast(int, row["cursor"])
        prior = (
            self._object(cast(str, row["report_digest"]))
            if row["report_digest"]
            else {}
        )
        signals = list(cast(list[JsonValue], prior.get("signals", [])))
        start_revision = snapshot.revision
        command_ids: list[JsonValue] = []
        prefix = f"{row['id']}.{row['operation']}"

        def command(value: p.PaperCommand) -> None:
            nonlocal snapshot
            snapshot = self.engine.process(
                cast(str, row["id"]), str(row["owner_id"]), value, snapshot.revision
            )
            command_ids.append(value.command_id)
            self.fault("AFTER_ENGINE_COMMAND")

        def cancel_all(at: datetime) -> None:
            for order in tuple(snapshot.book.orders):
                if order.status in a.OPEN:
                    suffix = str(len(command_ids))
                    if order.status != "CANCEL_PENDING":
                        command(
                            p.Cancel(
                                command_id=prefix + ".cancelrequest" + suffix,
                                at=at,
                                order_id=order.order_id,
                                action="REQUEST",
                            )
                        )
                    command(
                        p.Cancel(
                            command_id=prefix + ".cancelconfirm" + suffix,
                            at=at,
                            order_id=order.order_id,
                            action="CONFIRM",
                        )
                    )

        if kind in {"CANCEL", "KILL", "RESET_KILL"}:
            if kind == "RESET_KILL":
                command(
                    p.Reconcile(
                        command_id=prefix + ".reconcile",
                        at=snapshot.at,
                        cash=snapshot.book.cash[0].amount,
                        positions=tuple(
                            (pos.instrument_id, pos.quantity)
                            for pos in snapshot.book.positions
                        ),
                        observation_at=snapshot.at,
                    )
                )
                command(
                    p.Kill(
                        command_id=prefix + ".reset",
                        at=snapshot.at,
                        enabled=False,
                        reason="EXPLICIT_LOCAL_RESET",
                    )
                )
            else:
                command(
                    p.Kill(
                        command_id=prefix + ".kill",
                        at=snapshot.at,
                        enabled=True,
                        reason="EXPLICIT_LOCAL_" + kind,
                    )
                )
                cancel_all(snapshot.at)
        elif kind == "BAR":
            bars = cast(list[JsonValue], fixture["bars"])
            bar = _record(bars[cursor])
            instrument_id = cast(str, config["instrument_id"])
            opened, closed = _at(bar["open_at"]), _at(bar["close_at"])
            open_quote = a.Quote(
                instrument_id,
                opened,
                _at(bar["open_available_at"]),
                D(cast(str, bar["open_bid"])),
                D(cast(str, bar["open_ask"])),
            )
            close_quote = a.Quote(
                instrument_id,
                closed,
                _at(bar["close_available_at"]),
                D(cast(str, bar["close_bid"])),
                D(cast(str, bar["close_ask"])),
            )
            command(
                p.Mark(command_id=prefix + ".open", at=opened, quotes=(open_quote,))
            )
            for reserve in tuple(snapshot.reservations):
                command(
                    p.Match(
                        command_id=prefix + ".fill",
                        at=opened,
                        order_id=reserve.order_id,
                        quantity=min(
                            reserve.remaining, D(cast(str, config["max_fill_quantity"]))
                        ),
                        quote=open_quote,
                        commission=D(cast(str, config["commission_per_fill"])),
                        slippage_bps=D(cast(str, config["slippage_bps"])),
                    )
                )
                if snapshot.outcomes[-1].status == "REJECTED":
                    cancel_all(opened)
            command(
                p.Mark(command_id=prefix + ".close", at=closed, quotes=(close_quote,))
            )
            lookback = cast(int, config["lookback"])
            comparison = (
                D(cast(str, _record(bars[cursor - lookback])["close_bid"]))
                if cursor >= lookback
                else None
            )
            long = comparison is not None and close_quote.bid > comparison
            target = D(cast(str, config["quantity"])) if long else D(0)
            held = sum((pos.quantity for pos in snapshot.book.positions), D(0))
            side = "BUY" if target > held else "SELL"
            if snapshot.reservations and (
                target == held or any(r.side != side for r in snapshot.reservations)
            ):
                cancel_all(closed)
            signal: JsonRecord = {
                "index": cursor,
                "decision_at": _stamp(closed),
                "available_at": _stamp(closed),
                "current_bid": str(close_quote.bid),
                "comparison_bid": str(comparison) if comparison is not None else None,
                "target_quantity": str(target),
                "explanation": "WARMUP"
                if comparison is None
                else "LAGGED_BID_INCREASE"
                if long
                else "FLAT_NONPOSITIVE_MOMENTUM",
                "order_id": None,
            }
            if cursor + 1 < len(bars) and target != held and not snapshot.reservations:
                quantity = abs(target - held)
                with localcontext(a.CONTEXT):
                    fee = (
                        quantity / D(cast(str, config["max_fill_quantity"]))
                    ).to_integral_value(rounding=ROUND_CEILING) * D(
                        cast(str, config["commission_per_fill"])
                    )
                order_id = prefix + ".order"
                command(
                    p.Admit(
                        command_id=prefix + ".admit",
                        at=closed,
                        order_id=order_id,
                        strategy_id=cast(str, manifest["strategy_id"]),
                        instrument_id=instrument_id,
                        side=side,
                        quantity=quantity,
                        decision_at=closed,
                        quote=close_quote,
                        commission_budget=fee,
                    )
                )
                signal["order_id"] = order_id
                signal["admission_status"] = snapshot.outcomes[-1].status
                signal["admission_reason"] = snapshot.outcomes[-1].reason
            cursor += 1
            if cursor == len(bars):
                cancel_all(closed)
            signals.append(signal)
        else:
            raise PaperWorkflowError("INVALID_OPERATION")
        report_digest = self._report(
            row,
            snapshot,
            signals,
            cursor,
            error="PaperCancelled" if kind == "CANCEL" else None,
        )
        receipt: JsonRecord = {
            "job_id": row["id"],
            "operation": row["operation"],
            "kind": kind,
            "start_revision": start_revision,
            "end_revision": snapshot.revision,
            "snapshot_digest": _hash(canonicalize_json(_json(snapshot))),
            "command_ids": command_ids,
            "cursor": cursor,
            "report_digest": report_digest,
        }
        digest = self.lab.objects.publish(canonicalize_json(receipt)).digest
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO paper_step_receipts VALUES(?,?,?)",
                (row["id"], row["operation"], digest),
            )
        self.fault("AFTER_STEP_RECEIPT")
        self._complete_step(row, receipt, recovered=False)

    def _complete_step(
        self, row: JsonRecord, receipt: JsonRecord, *, recovered: bool
    ) -> None:
        kind = receipt["kind"]
        finished = receipt["cursor"] == row["bars"]
        if kind == "CANCEL":
            self.lab.fail_run(cast(str, row["experiment_id"]), "PaperCancelled")
        elif finished:
            self.lab.evaluate_run(
                cast(str, row["experiment_id"]),
                self._object(cast(str, receipt["report_digest"])),
            )
        self.fault("AFTER_FINALIZATION")
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            fresh = self._load(db, cast(str, row["id"]))
            requested = fresh["requested"]
            status = (
                "CANCELLED"
                if kind == "CANCEL"
                else "COMPLETED"
                if finished
                else "PAUSED"
                if recovered or kind in {"KILL", "RESET_KILL"} or requested == "PAUSE"
                else "ACTIVE"
            )
            self._save(
                db,
                fresh,
                {
                    "status": status,
                    "cursor": receipt["cursor"],
                    "report_digest": receipt["report_digest"],
                    "inflight": None,
                    "requested": None
                    if requested == kind or requested == "PAUSE" or status in TERMINAL
                    else requested,
                },
                "STEP_COMMITTED",
            )

    def _fail(self, row: JsonRecord, reason: str) -> None:
        with self.state.connection() as db:
            fresh = self._load(db, cast(str, row["id"]))
        snapshot = None
        if fresh["experiment_id"]:
            try:
                snapshot = self._snapshot(fresh)
            except Exception:
                snapshot = (
                    None  # Fail closed; retain sanitized failure without raw errors.
                )
            run = self.lab.get_run(cast(str, fresh["experiment_id"]))
            if run["lifecycle_status"] == "RUNNING":
                run = (
                    self.lab.recover_run(cast(str, fresh["experiment_id"]))
                    if run["variants_attempted"]
                    else self.lab.fail_run(cast(str, fresh["experiment_id"]), reason)
                )
            if self._adopt_finalization(fresh, run):
                return
            if run["evaluation_outcome"] == "INCONCLUSIVE":
                raise PaperWorkflowError("UNBOUND_COMPLETED_RESULT")
        prior = (
            self._object(cast(str, fresh["report_digest"]))
            if fresh["report_digest"]
            else {}
        )
        report = self._report(
            fresh,
            snapshot,
            cast(list[JsonValue], prior.get("signals", [])),
            cast(int, fresh["cursor"]),
            error=reason,
        )
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._save(
                db,
                self._load(db, cast(str, row["id"])),
                {
                    "status": "FAILED",
                    "error": reason,
                    "report_digest": report,
                    "requested": None,
                    "inflight": None,
                },
                "FAILED",
            )

    def owned_experiment_ids(self) -> frozenset[str]:
        """Verified session bindings only; callers cannot provide orphan exclusions."""
        with self.state.connection() as db:
            rows = [
                self._load(db, r[0])
                for r in db.execute(
                    "SELECT id FROM paper_jobs WHERE experiment_id IS NOT NULL"
                )
            ]
        result: set[str] = set()
        for row in rows:
            self._binding(row)
            result.add(cast(str, row["experiment_id"]))
        return frozenset(result)

    def recover(self) -> None:
        """Under the host runtime lease, stop clean sessions and retain uncertainty."""
        with self.state.connection() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM paper_jobs WHERE status NOT IN ('COMPLETED','FAILED','CANCELLED','CREATED')"
                )
            ]
        for identity in ids:
            with self.state.connection() as db:
                row = self._load(db, identity)
            if row["experiment_id"]:
                run, _ = self._binding(row)
                if run["lifecycle_status"] == "RUNNING" and run["variants_attempted"]:
                    run = self.lab.recover_run(cast(str, row["experiment_id"]))
                if run["lifecycle_status"] != "RUNNING":
                    if not self._adopt_finalization(row, run):
                        self._fail(row, "PaperLifecycleInterrupted")
                    continue
            with self.state.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                current = self._load(db, identity)
                if current["status"] in {"PAUSED", "AMBIGUOUS"}:
                    continue
                status = (
                    "AMBIGUOUS"
                    if current["status"] in BUSY or current["status"] == "AMBIGUOUS"
                    else "PAUSED"
                )
                self._save(db, current, {"status": status}, "RESTART_PAUSED")

    def _adopt_finalization(self, row: JsonRecord, run: JsonRecord) -> bool:
        if row["inflight"] is None:
            return False
        with self.state.connection() as db:
            marker = db.execute(
                "SELECT digest FROM paper_step_receipts WHERE job_id=? AND operation=?",
                (row["id"], row["operation"]),
            ).fetchone()
        if marker is None:
            return False
        receipt = self._verify_receipt(row, marker[0])
        if run["evaluation_outcome"] == "INCONCLUSIVE":
            if (
                receipt["kind"] != "BAR"
                or receipt["cursor"] != row["bars"]
                or run["result_digest"] != receipt["report_digest"]
            ):
                raise PaperWorkflowError("CANONICAL_RESULT_BINDING")
            status = "COMPLETED"
        elif (
            receipt["kind"] == "CANCEL"
            and run["evaluation_outcome"] == "FAILED"
            and run["failure_modes"] == ["PaperCancelled"]
        ):
            status = "CANCELLED"
        else:
            return False
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._save(
                db,
                self._load(db, cast(str, row["id"])),
                {
                    "status": status,
                    "cursor": receipt["cursor"],
                    "report_digest": receipt["report_digest"],
                    "inflight": None,
                    "requested": None,
                },
                "RECOVERED_FINALIZATION",
            )
        return True

    def _verify_receipt(self, row: JsonRecord, digest: str) -> JsonRecord:
        receipt = self._object(digest)
        snapshot = self._snapshot(row)
        inflight = _record(row["inflight"])
        start, end = (
            cast(int, receipt["start_revision"]),
            cast(int, receipt["end_revision"]),
        )
        if (
            receipt["job_id"] != row["id"]
            or receipt["operation"] != row["operation"]
            or receipt["kind"] != inflight["kind"]
            or start != inflight["start_revision"]
            or end != snapshot.revision
            or receipt["snapshot_digest"] != _hash(canonicalize_json(_json(snapshot)))
            or receipt["command_ids"]
            != [outcome.command_id for outcome in snapshot.outcomes[start:end]]
        ):
            raise PaperWorkflowError("STEP_RECEIPT_MISMATCH")
        report = self._object(cast(str, receipt["report_digest"]))
        if (
            report["snapshot"] != _json(snapshot)
            or report["completed_bars"] != receipt["cursor"]
            or report["job_id"] != row["id"]
        ):
            raise PaperWorkflowError("STEP_REPORT_MISMATCH")
        return receipt

    def reconcile(
        self, user: User, job_id: str, *, expected_revision: int
    ) -> JsonRecord:
        from quant_hunter.web.paper_halt import gate_lock

        with gate_lock(self.state.path):
            return self._reconcile(user, job_id, expected_revision=expected_revision)

    def _reconcile(
        self, user: User, job_id: str, *, expected_revision: int
    ) -> JsonRecord:
        with self.state.connection() as db:
            self._actor(db, user, mutation=True)
            self._load(db, job_id, user.id)
        self.capacity()
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._actor(db, user, mutation=True)
            row = self._load(db, job_id, user.id)
            if (
                row["status"] != "AMBIGUOUS"
                or type(expected_revision) is not int
                or row["revision"] != expected_revision
                or row["requested"] == "CANCEL"
                or cast(int, row["revision"]) >= MAX_EVENTS - FINALIZATION_HEADROOM
            ):
                raise PaperConflictError("RECONCILIATION_NOT_AVAILABLE")
            if resource_counts(db)[0] >= 2:
                raise PaperConflictError("SHARED_RESOURCE_LIMIT")
            marker = db.execute(
                "SELECT digest FROM paper_step_receipts WHERE job_id=? AND operation=?",
                (job_id, row["operation"]),
            ).fetchone()
            row = self._save(
                db, row, {"status": "RECOVERING"}, "RECONCILIATION_CLAIMED"
            )
        try:
            self._binding(row, current=True)
            if marker:
                receipt = self._verify_receipt(row, marker[0])
                self._complete_step(row, receipt, recovered=True)
            else:
                snapshot = self._snapshot(row)
                inflight = _record(row["inflight"])
                if (
                    snapshot.revision != inflight["start_revision"]
                    or _hash(canonicalize_json(_json(snapshot)))
                    != inflight["start_digest"]
                ):
                    raise PaperConflictError("PARTIAL_STEP_REQUIRES_CANCEL")
                with self.state.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    fresh = self._load(db, job_id)
                    self._save(
                        db,
                        fresh,
                        {"status": "PAUSED", "inflight": None},
                        "RECONCILED_NO_EFFECT",
                    )
        except Exception:
            with self.state.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                self._save(
                    db,
                    self._load(db, job_id),
                    {"status": "AMBIGUOUS"},
                    "RECONCILIATION_REFUSED",
                )
            raise
        return self.operational_head(user, job_id)
