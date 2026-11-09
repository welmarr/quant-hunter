"""Persistent fixed public collections through the existing owned job/data queue."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.sources.connectors import default_query
from quant_hunter.web.admission import resource_counts
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.state import AccessError, Job, User

MAX_SCHEDULES = 32
MAX_EVENTS = 160
MAX_RECORD = 4096
MAX_RESULT = 64_000
MAX_CONTROLS = 64
PUBLIC_SOURCES = {"SRC-04", "SRC-06", "SRC-08"}


class ScheduleError(ValueError):
    """A fixed, bounded operational refusal with no provider content."""


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes) -> JsonRecord:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RECORD:
        raise ScheduleError("SCHEDULE_RECORD_BOUND")
    item = parse_json_document(raw)
    if not isinstance(item, dict) or canonicalize_json(item) != raw:
        raise ScheduleError("SCHEDULE_RECORD_INVALID")
    return item


def public_profile(catalogue_id: str) -> JsonRecord:
    """Explicitly fixed historical diagnostics; never a latest-price subscription."""
    if catalogue_id not in PUBLIC_SOURCES:
        raise ScheduleError("PUBLIC_PROFILE_UNSUPPORTED")
    if catalogue_id == "SRC-06":
        query: JsonRecord = {"release_date": "2025-01-17", "expected_base_year": 2017}
    else:
        selected = default_query(catalogue_id)
        query = {
            "series_id": selected.series_id,
            "start": selected.start.isoformat(),
            "end": selected.end.isoformat(),
            "unit": selected.unit,
        }
    return {
        "profile_version": "FIXED_PUBLIC_DIAGNOSTIC_V1",
        "catalogue_id": catalogue_id,
        "query": query,
        "collection_mode": "FIXED_HISTORICAL_DIAGNOSTIC",
        "maximum_response_bytes": 2_000_000,
        "maximum_pages": 1,
        "credentials_required": False,
        "freshness_claim": False,
    }


class SourceSchedules:
    """The runtime lease owns pump/execute/recover; this class starts no thread.

    A dormant schedule consumes no worker slot. Every actual occurrence is an
    existing AppState job and its PROBE is the same worker-linked DataAccess
    operation. No experiment, private credential, paid request or new transport
    authority is introduced. Public configuration always starts paused.
    """

    def __init__(
        self,
        data: DataAccess,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        fault: Callable[[str], None] = lambda phase: None,
    ) -> None:
        self.data, self.state, self.clock, self.fault = data, data.state, clock, fault
        with self.state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS collection_heads(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,revision INTEGER NOT NULL,payload BLOB NOT NULL,digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_events(id TEXT NOT NULL,revision INTEGER NOT NULL,payload BLOB NOT NULL,digest TEXT NOT NULL,previous_digest TEXT,PRIMARY KEY(id,revision));
                CREATE TABLE IF NOT EXISTS collection_occurrences(job_id TEXT PRIMARY KEY,schedule_id TEXT NOT NULL,number INTEGER NOT NULL,payload BLOB NOT NULL,digest TEXT NOT NULL,UNIQUE(schedule_id,number));
                CREATE TABLE IF NOT EXISTS collection_dispatches(job_id TEXT PRIMARY KEY,payload BLOB NOT NULL,digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_operation_links(job_id TEXT PRIMARY KEY,operation_id TEXT NOT NULL UNIQUE,payload BLOB NOT NULL,digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_receipts(job_id TEXT PRIMARY KEY,payload BLOB NOT NULL,digest TEXT NOT NULL);
            """)
            for table in (
                "collection_events",
                "collection_occurrences",
                "collection_dispatches",
                "collection_operation_links",
                "collection_receipts",
            ):
                for action in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable collection history'); END"
                    )

    def _now(self) -> int:
        instant = self.clock()
        if (
            not isinstance(instant, datetime)
            or instant.tzinfo is not UTC
            or not 2020 <= instant.year <= 2100
        ):
            raise ScheduleError("SCHEDULE_UTC_CLOCK_REQUIRED")
        return int(instant.timestamp())

    @staticmethod
    def _actor(db: sqlite3.Connection, user: User, *, mutation: bool = False) -> None:
        row = db.execute(
            "SELECT username,role FROM users WHERE id=?", (user.id,)
        ).fetchone()
        if (
            row is None
            or tuple(row) != (user.username, user.role)
            or (mutation and user.role != "owner")
        ):
            raise AccessError("Current source schedule owner required")

    def _head(
        self, db: sqlite3.Connection, identity: str, owner: int | None = None
    ) -> JsonRecord:
        row = db.execute(
            "SELECT * FROM collection_heads WHERE id=?", (identity,)
        ).fetchone()
        if row is None or (owner is not None and row["owner_id"] != owner):
            raise AccessError("Source schedule unavailable")
        sizes = db.execute(
            "SELECT COUNT(*),MAX(length(payload)) FROM collection_events WHERE id=?",
            (identity,),
        ).fetchone()
        if (
            not 1 <= sizes[0] <= MAX_EVENTS
            or sizes[1] > MAX_RECORD
            or len(row["payload"]) > MAX_RECORD
        ):
            raise ScheduleError("SCHEDULE_HISTORY_BOUND")
        previous: str | None = None
        latest: JsonRecord = {}
        original: JsonValue = None
        for index, event in enumerate(
            db.execute(
                "SELECT * FROM collection_events WHERE id=? ORDER BY revision",
                (identity,),
            ),
            1,
        ):
            value = _decode(bytes(event["payload"]))
            if index == 1:
                original = value.get("configuration")
            if (
                event["revision"] != index
                or value.get("revision") != index
                or event["previous_digest"] != previous
                or value.get("id") != identity
                or value.get("owner_id") != row["owner_id"]
                or value.get("configuration") != original
                or value.get("configuration_digest")
                != _digest(canonicalize_json(original))
                or not isinstance(original, dict)
                or _digest(bytes(event["payload"])) != event["digest"]
            ):
                raise ScheduleError("SCHEDULE_HISTORY_BINDING")
            previous, latest = event["digest"], value
        if (
            row["revision"] != sizes[0]
            or row["digest"] != previous
            or bytes(row["payload"]) != canonicalize_json(latest)
        ):
            raise ScheduleError("SCHEDULE_HEAD_BINDING")
        return latest

    def _save(
        self, db: sqlite3.Connection, prior: JsonRecord, updates: JsonRecord, event: str
    ) -> JsonRecord:
        revision = cast(int, prior.get("revision", 0)) + 1
        if revision > MAX_EVENTS:
            raise ScheduleError("SCHEDULE_HISTORY_FULL")
        value: JsonRecord = {
            **prior,
            **updates,
            "revision": revision,
            "event": event,
            "at_unix": self._now(),
        }
        if cast(int, value["at_unix"]) < cast(int, prior.get("at_unix", 0)):
            raise ScheduleError("SCHEDULE_CLOCK_REGRESSION")
        raw = canonicalize_json(value)
        if len(raw) > MAX_RECORD:
            raise ScheduleError("SCHEDULE_RECORD_BOUND")
        identity, owner = cast(str, value["id"]), cast(int, value["owner_id"])
        old_digest = _digest(canonicalize_json(prior)) if revision > 1 else None
        db.execute(
            "INSERT INTO collection_events VALUES(?,?,?,?,?)",
            (identity, revision, raw, _digest(raw), old_digest),
        )
        if revision == 1:
            db.execute(
                "INSERT INTO collection_heads VALUES(?,?,?,?,?)",
                (identity, owner, revision, raw, _digest(raw)),
            )
        elif (
            db.execute(
                "UPDATE collection_heads SET revision=?,payload=?,digest=? WHERE id=? AND revision=? AND digest=?",
                (revision, raw, _digest(raw), identity, revision - 1, old_digest),
            ).rowcount
            != 1
        ):
            raise ScheduleError("SCHEDULE_STALE_REVISION")
        return value

    def create(
        self, user: User, catalogue_id: str, *, interval_seconds: int, maximum_runs: int
    ) -> JsonRecord:
        profile = public_profile(catalogue_id)
        if (
            type(interval_seconds) is not int
            or not 3600 <= interval_seconds <= 604800
            or type(maximum_runs) is not int
            or not 1 <= maximum_runs <= 30
        ):
            raise ScheduleError("SCHEDULE_CONFIGURATION_BOUND")
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._actor(db, user, mutation=True)
            if (
                db.execute("SELECT COUNT(*) FROM collection_heads").fetchone()[0]
                >= MAX_SCHEDULES
            ):
                raise ScheduleError("SCHEDULE_CAPACITY")
            config: JsonRecord = {
                "profile": profile,
                "interval_seconds": interval_seconds,
                "maximum_runs": maximum_runs,
            }
            return self._save(
                db,
                {},
                {
                    "id": "COLL-" + secrets.token_hex(16),
                    "owner_id": user.id,
                    "configuration": config,
                    "configuration_digest": _digest(canonicalize_json(config)),
                    "status": "PAUSED",
                    "next_due_unix": None,
                    "dispatched": 0,
                    "controls": 0,
                    "pending_job_id": None,
                    "last_receipt_digest": None,
                    "reason": "EXPLICIT_ACTIVATION_REQUIRED",
                },
                "CREATED",
            )

    def get(self, user: User, identity: str) -> JsonRecord:
        with self.state.connection() as db:
            self._actor(db, user)
            return self._head(db, identity, user.id)

    def list_schedules(self, user: User) -> list[JsonRecord]:
        with self.state.connection() as db:
            self._actor(db, user)
            ids = [
                str(row[0])
                for row in db.execute(
                    "SELECT id FROM collection_heads WHERE owner_id=? ORDER BY rowid DESC LIMIT 33",
                    (user.id,),
                )
            ]
            if len(ids) > MAX_SCHEDULES:
                raise ScheduleError("SCHEDULE_CAPACITY")
            return [self._head(db, identity, user.id) for identity in ids]

    def control(
        self, user: User, identity: str, action: str, *, expected_revision: int
    ) -> JsonRecord:
        if (
            action not in {"ACTIVATE", "PAUSE", "RESUME", "CANCEL"}
            or type(expected_revision) is not int
        ):
            raise ScheduleError("SCHEDULE_CONTROL_INVALID")
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._actor(db, user, mutation=True)
            head = self._head(db, identity, user.id)
            if head["revision"] != expected_revision or head["status"] in {
                "CANCELLED",
                "COMPLETED",
            }:
                raise ScheduleError("SCHEDULE_STALE_OR_TERMINAL")
            if cast(int, head["controls"]) >= MAX_CONTROLS and action != "CANCEL":
                raise ScheduleError("SCHEDULE_PROTECTIVE_HEADROOM")
            update: JsonRecord = {
                "controls": cast(int, head["controls"]) + 1,
                "status": "ENABLED"
                if action in {"ACTIVATE", "RESUME"}
                else "CANCELLED"
                if action == "CANCEL"
                else "PAUSED",
                "reason": None,
            }
            if action in {"ACTIVATE", "RESUME"}:
                if head["pending_job_id"] is not None or head["status"] != "PAUSED":
                    raise ScheduleError("SCHEDULE_PENDING_OR_NOT_PAUSED")
                config = cast(JsonRecord, head["configuration"])
                if cast(int, head["dispatched"]) >= cast(int, config["maximum_runs"]):
                    raise ScheduleError("SCHEDULE_RUN_LIMIT")
                update["next_due_unix"] = self._now() + cast(
                    int, config["interval_seconds"]
                )
            elif head["pending_job_id"] is not None:
                job_id = cast(str, head["pending_job_id"])
                if db.execute(
                    "UPDATE jobs SET status='CANCELLED' WHERE id=? AND owner_id=? AND status='QUEUED'",
                    (job_id, user.id),
                ).rowcount:
                    update["last_receipt_digest"] = self._receipt(
                        db,
                        job_id,
                        {
                            "status": "CANCELLED_BEFORE_FETCH",
                            "reason": action,
                            "operation_id": None,
                            "result_digest": None,
                            "completed_unix": self._now(),
                            "recovered": False,
                        },
                    )
                    update["pending_job_id"] = None
            return self._save(db, head, update, action)

    def _receipt(self, db: sqlite3.Connection, job_id: str, value: JsonRecord) -> str:
        occurrence = self._occurrence(db, job_id)
        raw = canonicalize_json(
            {
                **value,
                "job_id": job_id,
                "occurrence_digest": _digest(canonicalize_json(occurrence)),
            }
        )
        if len(raw) > MAX_RECORD:
            raise ScheduleError("COLLECTION_RECEIPT_BOUND")
        digest = _digest(raw)
        db.execute(
            "INSERT INTO collection_receipts VALUES(?,?,?)", (job_id, raw, digest)
        )
        return digest

    def pump_due(self) -> bool:
        """Queue at most one due occurrence; no HTTP and no resource-cap relaxation."""
        # Generic job cancellation is a valid API path. Settle its reservation
        # before considering another schedule, without dispatching any request.
        with self.state.connection() as db:
            cancelled = db.execute(
                "SELECT o.job_id FROM collection_occurrences o JOIN jobs j ON j.id=o.job_id LEFT JOIN collection_receipts r ON r.job_id=o.job_id WHERE j.status='CANCELLED' AND r.job_id IS NULL ORDER BY o.rowid LIMIT 1"
            ).fetchone()
        if cancelled is not None:
            self._complete(str(cancelled[0]))
            return True
        now = self._now()
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if resource_counts(db)[1] >= 8:
                return False
            for row in db.execute(
                "SELECT id,owner_id FROM collection_heads ORDER BY rowid LIMIT 33"
            ).fetchall():
                head = self._head(db, str(row["id"]))
                if (
                    head["status"] != "ENABLED"
                    or head["pending_job_id"] is not None
                    or cast(int, head["next_due_unix"]) > now
                ):
                    continue
                actor = db.execute(
                    "SELECT role FROM users WHERE id=?", (row["owner_id"],)
                ).fetchone()
                if actor is None or actor[0] != "owner":
                    self._save(
                        db,
                        head,
                        {"status": "PAUSED", "reason": "CURRENT_OWNER_REQUIRED"},
                        "AUTHORITY_PAUSED",
                    )
                    return True
                config = cast(JsonRecord, head["configuration"])
                number = cast(int, head["dispatched"]) + 1
                if number > cast(int, config["maximum_runs"]):
                    self._save(db, head, {"status": "COMPLETED"}, "EXHAUSTED")
                    return True
                interval = cast(int, config["interval_seconds"])
                due = cast(int, head["next_due_unix"])
                job_id = hashlib.sha256(f"{head['id']}:{number}".encode()).hexdigest()[
                    :32
                ]
                job_config: JsonRecord = {
                    "kind": "SOURCE_COLLECTION",
                    "schedule_id": str(head["id"]),
                    "occurrence": number,
                    "configuration_digest": str(head["configuration_digest"]),
                }
                occurrence: JsonRecord = {
                    "job_id": job_id,
                    "schedule_id": head["id"],
                    "owner_id": head["owner_id"],
                    "number": number,
                    "due_unix": due,
                    "queued_unix": now,
                    "skipped_windows": (now - due) // interval,
                    "configuration": config,
                    "job_configuration": job_config,
                }
                raw = canonicalize_json(occurrence)
                if len(raw) > MAX_RECORD:
                    raise ScheduleError("COLLECTION_OCCURRENCE_BOUND")
                db.execute(
                    "INSERT INTO collection_occurrences VALUES(?,?,?,?,?)",
                    (job_id, head["id"], number, raw, _digest(raw)),
                )
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,'QUEUED',?,NULL,NULL)",
                    (job_id, head["owner_id"], json.dumps(job_config, sort_keys=True)),
                )
                self._save(
                    db,
                    head,
                    {
                        "pending_job_id": job_id,
                        "dispatched": number,
                        "next_due_unix": due + ((now - due) // interval + 1) * interval,
                    },
                    "QUEUED",
                )
                self.fault("BEFORE_QUEUE_COMMIT")
                return True
        return False

    def _occurrence(self, db: sqlite3.Connection, job_id: str) -> JsonRecord:
        row = db.execute(
            "SELECT * FROM collection_occurrences WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if row is None or _digest(bytes(row["payload"])) != row["digest"]:
            raise ScheduleError("COLLECTION_OCCURRENCE_BINDING")
        value = _decode(bytes(row["payload"]))
        head = self._head(db, str(row["schedule_id"]))
        expected: JsonRecord = {
            "kind": "SOURCE_COLLECTION",
            "schedule_id": head["id"],
            "occurrence": row["number"],
            "configuration_digest": head["configuration_digest"],
        }
        if (
            value.get("job_id") != job_id
            or value.get("schedule_id") != head["id"]
            or value.get("owner_id") != head["owner_id"]
            or value.get("number") != row["number"]
            or value.get("configuration") != head["configuration"]
            or value.get("job_configuration") != expected
            or job_id
            != hashlib.sha256(f"{head['id']}:{row['number']}".encode()).hexdigest()[:32]
        ):
            raise ScheduleError("COLLECTION_OCCURRENCE_BINDING")
        job = db.execute(
            "SELECT owner_id,config,experiment_id,status,length(CAST(config AS BLOB)) FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if (
            job is None
            or job[0] != head["owner_id"]
            or job[2] is not None
            or job[3] not in {"QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}
            or job[4] > MAX_RECORD
            or parse_json_document(str(job[1])) != expected
        ):
            raise ScheduleError("COLLECTION_JOB_BINDING")
        return value

    def execute_job(self, job: Job) -> None:
        """Execute one actual claimed job; interrupted unknowns are never retried."""
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            occurrence = self._occurrence(db, job.id)
            head = self._head(db, cast(str, occurrence["schedule_id"]), job.owner_id)
            actual = db.execute("SELECT * FROM jobs WHERE id=?", (job.id,)).fetchone()
            if (
                actual is None
                or actual["status"] != "RUNNING"
                or job.status != "RUNNING"
                or actual["owner_id"] != job.owner_id
                or json.loads(actual["config"]) != occurrence["job_configuration"]
                or job.config != occurrence["job_configuration"]
                or head["configuration"] != occurrence["configuration"]
                or head["pending_job_id"] != job.id
                or actual["experiment_id"] is not None
            ):
                raise ScheduleError("COLLECTION_JOB_BINDING")
            if (
                db.execute(
                    "SELECT 1 FROM collection_operation_links WHERE job_id=?", (job.id,)
                ).fetchone()
                or db.execute(
                    "SELECT 1 FROM collection_receipts WHERE job_id=?", (job.id,)
                ).fetchone()
                or db.execute(
                    "SELECT 1 FROM collection_dispatches WHERE job_id=?", (job.id,)
                ).fetchone()
            ):
                raise ScheduleError("COLLECTION_ALREADY_DISPATCHED")
            claimed_at = self._now()
            if claimed_at < cast(int, occurrence["queued_unix"]):
                raise ScheduleError("SCHEDULE_CLOCK_REGRESSION")
            claim = canonicalize_json(
                {
                    "job_id": job.id,
                    "owner_id": job.owner_id,
                    "occurrence_digest": _digest(canonicalize_json(occurrence)),
                    "at_unix": claimed_at,
                }
            )
            db.execute(
                "INSERT INTO collection_dispatches VALUES(?,?,?)",
                (job.id, claim, _digest(claim)),
            )
        self.fault("AFTER_DISPATCH_CLAIM")
        try:
            with self.state.connection() as db:
                actor = db.execute(
                    "SELECT username,role FROM users WHERE id=?", (job.owner_id,)
                ).fetchone()
                if actor is None:
                    raise AccessError("Current source schedule owner required")
                user = User(job.owner_id, actor["username"], actor["role"])
                self._actor(db, user, mutation=True)
            config = cast(JsonRecord, occurrence["configuration"])
            profile = cast(JsonRecord, config["profile"])
            source = cast(str, profile["catalogue_id"])
            if profile != public_profile(source):
                raise ScheduleError("COLLECTION_PROFILE_CHANGED")

            def started(operation_id: str) -> None:
                with self.state.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    self._actor(db, user, mutation=True)
                    fresh = self._head(
                        db, cast(str, occurrence["schedule_id"]), user.id
                    )
                    if (
                        fresh["status"] != "ENABLED"
                        or fresh["pending_job_id"] != job.id
                    ):
                        raise ScheduleError("COLLECTION_PAUSED_BEFORE_FETCH")
                    operation = db.execute(
                        "SELECT * FROM data_operations WHERE id=?", (operation_id,)
                    ).fetchone()
                    if (
                        operation is None
                        or operation["owner_id"] != user.id
                        or operation["kind"] != "PROBE"
                        or operation["catalogue_id"] != source
                        or operation["status"] != "RUNNING"
                        or operation["worker_job_id"] != job.id
                    ):
                        raise ScheduleError("COLLECTION_OPERATION_BINDING")
                    raw = canonicalize_json(
                        {
                            "job_id": job.id,
                            "operation_id": operation_id,
                            "owner_id": user.id,
                            "catalogue_id": source,
                        }
                    )
                    db.execute(
                        "INSERT INTO collection_operation_links VALUES(?,?,?,?)",
                        (job.id, operation_id, raw, _digest(raw)),
                    )
                self.fault("AFTER_OPERATION_LINK")

            self.data.probe(
                user, source, worker_job_id=job.id, operation_started=started
            )
            self.fault("AFTER_PROBE_RETURN")
            self._complete(job.id)
        except Exception:
            self._complete(job.id, forced_reason="COLLECTION_FAILED")

    def _complete(
        self, job_id: str, *, forced_reason: str | None = None, recovered: bool = False
    ) -> None:
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            occurrence = self._occurrence(db, job_id)
            head = self._head(db, cast(str, occurrence["schedule_id"]))
            if db.execute(
                "SELECT 1 FROM collection_receipts WHERE job_id=?", (job_id,)
            ).fetchone():
                self._verified_receipt(db, job_id)
                return
            if head["pending_job_id"] != job_id:
                raise ScheduleError("COLLECTION_PENDING_BINDING")
            link = db.execute(
                "SELECT * FROM collection_operation_links WHERE job_id=?", (job_id,)
            ).fetchone()
            operation_id: str | None = None
            operation_status: str | None = None
            result_digest: str | None = None
            status, reason = "FAILED", forced_reason or "COLLECTION_RESULT_UNAVAILABLE"
            if link is not None:
                self._dispatch(db, job_id, occurrence)
                if _digest(bytes(link["payload"])) != link["digest"]:
                    raise ScheduleError("COLLECTION_LINK_BINDING")
                binding = _decode(bytes(link["payload"]))
                operation_id = str(link["operation_id"])
                if (
                    binding.get("job_id") != job_id
                    or binding.get("operation_id") != operation_id
                    or binding.get("owner_id") != occurrence["owner_id"]
                    or binding.get("catalogue_id")
                    != cast(
                        JsonRecord,
                        cast(JsonRecord, occurrence["configuration"])["profile"],
                    )["catalogue_id"]
                ):
                    raise ScheduleError("COLLECTION_LINK_BINDING")
                size = db.execute(
                    "SELECT length(CAST(result AS BLOB)) FROM data_operations WHERE id=?",
                    (operation_id,),
                ).fetchone()
                if size is None or (size[0] is not None and size[0] > MAX_RESULT):
                    raise ScheduleError("COLLECTION_RESULT_BOUND")
                operation = db.execute(
                    "SELECT * FROM data_operations WHERE id=?", (operation_id,)
                ).fetchone()
                operation_status = str(operation["status"])
                if (
                    operation["owner_id"] != occurrence["owner_id"]
                    or operation["worker_job_id"] != job_id
                    or operation["kind"] != "PROBE"
                    or operation["catalogue_id"] != binding["catalogue_id"]
                ):
                    raise ScheduleError("COLLECTION_OPERATION_BINDING")
                if operation["result"] is not None:
                    value = parse_json_document(str(operation["result"]))
                    if not isinstance(value, dict):
                        raise ScheduleError("COLLECTION_RESULT_BINDING")
                    result_digest = _digest(canonicalize_json(value))
                if operation["status"] == "SUCCEEDED" and forced_reason is None:
                    if result_digest is None:
                        raise ScheduleError("COLLECTION_RESULT_BINDING")
                    status, reason = (
                        "SUCCEEDED",
                        "RECOVERED_RESULT" if recovered else "",
                    )
                elif operation["status"] in {"RUNNING", "INTERRUPTED"}:
                    status, reason = "UNKNOWN", "INTERRUPTED_NEVER_REPLAYED"
            elif recovered:
                status, reason = "UNKNOWN", "INTERRUPTED_NEVER_REPLAYED"
            job = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job is not None and job[0] == "SUCCEEDED":
                # Our job completion and receipt commit atomically. A successful
                # job without that receipt is contradictory, not recovery proof.
                raise ScheduleError("COLLECTION_JOB_BINDING")
            if job is not None and job[0] == "FAILED" and status == "SUCCEEDED":
                status, reason = "FAILED", "RETAINED_JOB_FAILURE_WITH_SOURCE_RESULT"
            if link is None and job is not None and job[0] == "CANCELLED":
                status, reason = "CANCELLED_BEFORE_FETCH", "QUEUED_JOB_CANCELLED"
            receipt = self._receipt(
                db,
                job_id,
                {
                    "status": status,
                    "reason": reason,
                    "operation_id": operation_id,
                    "operation_status": operation_status,
                    "result_digest": result_digest,
                    "recovered": recovered,
                    "schedule_status_at_completion": head["status"],
                    "completed_unix": self._now(),
                },
            )
            config = cast(JsonRecord, head["configuration"])
            next_status = head["status"]
            if next_status != "CANCELLED":
                if status != "SUCCEEDED" or recovered:
                    next_status = "PAUSED"
                elif next_status == "ENABLED" and cast(int, head["dispatched"]) >= cast(
                    int, config["maximum_runs"]
                ):
                    next_status = "COMPLETED"
            self._save(
                db,
                head,
                {
                    "status": next_status,
                    "pending_job_id": None,
                    "last_receipt_digest": receipt,
                    "reason": reason or None,
                },
                "OCCURRENCE_FINISHED",
            )
            db.execute(
                "UPDATE jobs SET status=?,error=? WHERE id=? AND status='RUNNING'",
                (
                    "SUCCEEDED" if status == "SUCCEEDED" else "FAILED",
                    reason or None,
                    job_id,
                ),
            )
            self.fault("BEFORE_COMPLETION_COMMIT")

    def _verified_receipt(
        self, db: sqlite3.Connection, job_id: str
    ) -> JsonRecord | None:
        row = db.execute(
            "SELECT payload,digest FROM collection_receipts WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        raw = bytes(row[0])
        receipt = _decode(raw)
        occurrence = self._occurrence(db, job_id)
        if (
            row[1] != _digest(raw)
            or receipt.get("job_id") != job_id
            or receipt.get("occurrence_digest")
            != _digest(canonicalize_json(occurrence))
        ):
            raise ScheduleError("COLLECTION_RECEIPT_BINDING")
        expected_status = (
            "SUCCEEDED"
            if receipt.get("status") == "SUCCEEDED"
            else "CANCELLED"
            if receipt.get("status") == "CANCELLED_BEFORE_FETCH"
            else "FAILED"
        )
        job = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if job is None or job[0] != expected_status:
            raise ScheduleError("COLLECTION_RECEIPT_JOB_BINDING")
        operation_id = receipt.get("operation_id")
        if operation_id is not None:
            self._dispatch(db, job_id, occurrence)
            operation = db.execute(
                "SELECT owner_id,worker_job_id,result,length(CAST(result AS BLOB)),status,kind,catalogue_id FROM data_operations WHERE id=?",
                (str(operation_id),),
            ).fetchone()
            profile = cast(
                JsonRecord, cast(JsonRecord, occurrence["configuration"])["profile"]
            )
            if (
                operation is None
                or operation[0] != occurrence["owner_id"]
                or operation[1] != job_id
                or (operation[3] is not None and operation[3] > MAX_RESULT)
                or operation[4] != receipt.get("operation_status")
                or operation[5] != "PROBE"
                or operation[6] != profile["catalogue_id"]
            ):
                raise ScheduleError("COLLECTION_RECEIPT_BINDING")
            link = db.execute(
                "SELECT operation_id,payload,digest FROM collection_operation_links WHERE job_id=?",
                (job_id,),
            ).fetchone()
            expected: JsonRecord = {
                "job_id": job_id,
                "owner_id": occurrence["owner_id"],
                "operation_id": operation_id,
                "catalogue_id": profile["catalogue_id"],
            }
            if (
                link is None
                or link[0] != operation_id
                or bytes(link[1]) != canonicalize_json(expected)
                or link[2] != _digest(bytes(link[1]))
            ):
                raise ScheduleError("COLLECTION_LINK_BINDING")
            result = (
                None
                if operation[2] is None
                else _digest(canonicalize_json(parse_json_document(str(operation[2]))))
            )
            if result != receipt.get("result_digest"):
                raise ScheduleError("COLLECTION_RESULT_BINDING")
        elif (
            receipt.get("result_digest") is not None
            or receipt.get("status") == "SUCCEEDED"
        ):
            raise ScheduleError("COLLECTION_RECEIPT_BINDING")
        return receipt

    @staticmethod
    def _dispatch(db: sqlite3.Connection, job_id: str, occurrence: JsonRecord) -> None:
        row = db.execute(
            "SELECT payload,digest FROM collection_dispatches WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            raise ScheduleError("COLLECTION_DISPATCH_BINDING")
        value = _decode(bytes(row[0]))
        if (
            row[1] != _digest(bytes(row[0]))
            or value.get("job_id") != job_id
            or value.get("owner_id") != occurrence["owner_id"]
            or value.get("occurrence_digest") != _digest(canonicalize_json(occurrence))
            or type(value.get("at_unix")) is not int
            or cast(int, value["at_unix"]) < cast(int, occurrence["queued_unix"])
        ):
            raise ScheduleError("COLLECTION_DISPATCH_BINDING")

    def history(self, user: User, identity: str) -> list[JsonRecord]:
        """Owned bounded operational receipts; source object graphs remain authoritative."""
        with self.state.connection() as db:
            self._actor(db, user)
            self._head(db, identity, user.id)
            rows = db.execute(
                "SELECT job_id FROM collection_occurrences WHERE schedule_id=? ORDER BY number LIMIT 31",
                (identity,),
            ).fetchall()
            if len(rows) > 30:
                raise ScheduleError("COLLECTION_HISTORY_BOUND")
            result: list[JsonRecord] = []
            for row in rows:
                job_id = str(row[0])
                result.append(
                    {
                        "occurrence": self._occurrence(db, job_id),
                        "receipt": self._verified_receipt(db, job_id),
                    }
                )
            return result

    def recover(self) -> None:
        """Called under the runtime lease after DataAccess.recover, before orphan jobs."""
        with self.state.connection() as db:
            pending = [
                str(row[0])
                for row in db.execute(
                    "SELECT o.job_id FROM collection_occurrences o JOIN jobs j ON j.id=o.job_id LEFT JOIN collection_receipts r ON r.job_id=o.job_id WHERE r.job_id IS NULL AND j.status<>'QUEUED' LIMIT 961"
                )
            ]
        if len(pending) > MAX_SCHEDULES * 30:
            raise ScheduleError("COLLECTION_HISTORY_BOUND")
        for job_id in pending:
            self._complete(job_id, recovered=True)
