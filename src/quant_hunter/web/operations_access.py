"""Bounded read-only operational observations, never admission or recovery."""

from __future__ import annotations

import math
import os
import shutil
import sqlite3
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from quant_hunter.config import JsonRecord
from quant_hunter.web.admission import resource_counts
from quant_hunter.web.state import AccessError, AppState, User

_TABLES = ("jobs", "data_operations", "publication_operations", "paper_jobs")
_STATES = frozenset(
    {
        "QUEUED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "INTERRUPTED",
        "COMPLETED",
        "CREATED",
        "ACTIVE",
        "PAUSED",
        "STARTING",
        "STEPPING",
        "RECOVERING",
        "AMBIGUOUS",
    }
)
_PAPER_FINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_PAPER_ACTIVE = frozenset({"STARTING", "STEPPING", "RECOVERING"})
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_RESERVE = 20 * 1024**3
_BUDGET = 30_000_000_000
_HEADROOM = 64_000_000
_MAX_ENTRIES = 100_000


class OperationsUnavailableError(ValueError):
    """A sanitized unavailable observation; no cached authorization fallback."""


@dataclass(frozen=True)
class WorkerStatus:
    """Host-owned cheap observation; generation is not an invented restart count."""

    state: Literal["RUNNING", "STOPPED", "RESTARTING", "UNKNOWN"]
    generation: int | None = None
    started_at: datetime | None = None

    def to_record(self) -> JsonRecord:
        if self.state not in {"RUNNING", "STOPPED", "RESTARTING", "UNKNOWN"}:
            raise ValueError("Invalid worker state")
        if self.generation is not None and (
            type(self.generation) is not int or not 0 <= self.generation <= 2**31 - 1
        ):
            raise ValueError("Invalid worker generation")
        if self.started_at is not None and (
            not isinstance(self.started_at, datetime)
            or self.started_at.tzinfo is None
            or self.started_at.utcoffset() is None
        ):
            raise ValueError("Invalid worker timestamp")
        return {
            "state": self.state,
            "generation": self.generation,
            "started_at": (
                self.started_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
                if self.started_at is not None
                else None
            ),
        }


def _utc(clock: Callable[[], float]) -> str:
    value = clock()
    if not math.isfinite(value):
        raise ValueError("Invalid observation clock")
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def _status_counts(
    db: sqlite3.Connection, table: str, owner_id: int | None
) -> dict[str, int]:
    if table not in _TABLES:
        raise ValueError("Unknown observation table")
    clause = " WHERE owner_id=?" if owner_id is not None else ""
    rows = db.execute(
        f"SELECT status,COUNT(*) FROM {table}{clause} GROUP BY status",  # noqa: S608 -- fixed allowlist and bound owner
        (owner_id,) if owner_id is not None else (),
    )
    result: dict[str, int] = {}
    for state, count in rows:
        key = str(state) if state in _STATES else "OTHER"
        result[key] = result.get(key, 0) + int(count)
    return result


def _counts(db: sqlite3.Connection, owner_id: int | None) -> JsonRecord:
    tables = {
        str(row[0])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('jobs','data_operations','publication_operations','paper_jobs',"
            "'resource_readers')"
        )
    }
    counts = {
        name: _status_counts(db, name, owner_id) for name in _TABLES if name in tables
    }
    readers = 0
    if "resource_readers" in tables:
        query = (
            "SELECT COUNT(*) FROM resource_readers"
            if owner_id is None
            else "SELECT COUNT(*) FROM resource_readers WHERE owner_id=?"
        )
        readers = int(
            db.execute(
                query,
                (owner_id,) if owner_id is not None else (),
            ).fetchone()[0]
        )
    linked = orphans = 0
    if "data_operations" in tables and any(
        row[1] == "worker_job_id"
        for row in db.execute("PRAGMA table_info(data_operations)")
    ):
        clause = " AND d.owner_id=?" if owner_id is not None else ""
        row = db.execute(
            "SELECT SUM(CASE WHEN j.id IS NOT NULL THEN 1 ELSE 0 END),"
            "SUM(CASE WHEN j.id IS NULL THEN 1 ELSE 0 END) "
            "FROM data_operations d LEFT JOIN jobs j ON j.id=d.worker_job_id "
            "AND j.owner_id=d.owner_id AND j.status='RUNNING' "
            "WHERE d.status='RUNNING' AND d.worker_job_id IS NOT NULL" + clause,
            (owner_id,) if owner_id is not None else (),
        ).fetchone()
        linked, orphans = int(row[0] or 0), int(row[1] or 0)
    if owner_id is None:
        active, reserved = resource_counts(db)
    else:
        active = (
            readers
            + sum(counts.get(name, {}).get("RUNNING", 0) for name in _TABLES[:3])
            - linked
        )
        reserved = active + counts.get("jobs", {}).get("QUEUED", 0)
        paper = counts.get("paper_jobs", {})
        active += sum(
            count for status, count in paper.items() if status in _PAPER_ACTIVE
        )
        reserved += sum(
            count for status, count in paper.items() if status not in _PAPER_FINAL
        )
    return {
        "components": cast(JsonRecord, counts),
        "active_slots": active,
        "reserved_slots": reserved,
        "reader_slots": readers,
        "linked_worker_children": linked,
        "orphaned_active_children": orphans,
        "meaning": "Operational reservations only; not scientific attempt counts",
    }


def _safe_node(path: Path) -> os.stat_result:
    value = path.lstat()
    if (
        stat.S_ISLNK(value.st_mode)
        or getattr(value, "st_file_attributes", 0) & _REPARSE
    ):
        raise OperationsUnavailableError("STORAGE_REDIRECTION")
    return value


class OperationsAccess:
    """Observe actual counts without altering jobs, receipts, quotas or lifecycle.

    Worker callback is a trusted, nonblocking in-memory host observation. Storage
    scans never open file contents. Samples may become stale; stale cannot imply
    capacity to admit work. Database authorization is always freshly verified.
    """

    def __init__(
        self,
        state: AppState,
        runtime: Path,
        *,
        worker_status: Callable[[], WorkerStatus],
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not runtime.is_absolute() or (
            os.name == "nt" and runtime.drive.upper() != "D:"
        ):
            raise ValueError("Absolute runtime on the project volume required")
        _safe_node(runtime)
        self.state, self.runtime = state, runtime
        self.budget_root = next(
            (p for p in (runtime, *runtime.parents) if p.name == ".local"), runtime
        )
        for path in (self.budget_root, *self.budget_root.parents):
            _safe_node(path)
        self.worker_status, self.clock, self.monotonic = worker_status, clock, monotonic
        self._storage_lock = threading.Lock()
        self._sample: JsonRecord | None = None
        self._sample_at: float | None = None
        self._attempt_at: float | None = None
        self._storage_error: str | None = None

    def _database(self, user: User) -> tuple[JsonRecord, JsonRecord | None]:
        db: sqlite3.Connection | None = None
        try:
            # mode=ro cannot create an absent operational database.
            db = sqlite3.connect(
                self.state.path.as_uri() + "?mode=ro", uri=True, timeout=0.25
            )
            db.execute("PRAGMA query_only=ON")
            deadline = self.monotonic() + 2
            db.set_progress_handler(lambda: int(self.monotonic() >= deadline), 1000)
            db.execute("BEGIN")
            actor = db.execute(
                "SELECT username,role FROM users WHERE id=?", (user.id,)
            ).fetchone()
            if actor is None or tuple(actor) != (user.username, user.role):
                raise AccessError("Operations access denied")
            private = _counts(db, user.id)
            global_counts = _counts(db, None) if user.role == "owner" else None
            return private, global_counts
        except (sqlite3.Error, OSError, ValueError) as error:
            if isinstance(error, AccessError):
                raise
            raise OperationsUnavailableError("DATABASE_UNAVAILABLE") from None
        finally:
            if db is not None:
                db.close()

    def _scan_storage(self) -> JsonRecord:
        started = self.monotonic()
        _safe_node(self.runtime)
        _safe_node(self.budget_root)
        usage = shutil.disk_usage(self.runtime)
        if not 0 <= usage.free <= usage.total or usage.total <= 0:
            raise OperationsUnavailableError("STORAGE_UNAVAILABLE")
        total = entries = 0
        stack = [self.budget_root]
        while stack:
            parent = stack.pop()
            _safe_node(parent)
            with os.scandir(parent) as nodes:
                for node in nodes:
                    entries += 1
                    if entries > _MAX_ENTRIES or self.monotonic() - started >= 2:
                        raise OperationsUnavailableError("STORAGE_SCAN_LIMIT")
                    item = _safe_node(Path(node.path))
                    if stat.S_ISDIR(item.st_mode):
                        stack.append(Path(node.path))
                    elif stat.S_ISREG(item.st_mode):
                        total += item.st_size
                    else:
                        raise OperationsUnavailableError("STORAGE_SPECIAL_FILE")
        reserve = max(_RESERVE, usage.total * 15 // 100)
        status = "OK"
        if usage.free - _HEADROOM < reserve:
            status = "RESERVE_LOW"
        if total + _HEADROOM > _BUDGET:
            status = "CAP_REACHED"
        return {
            "observed_at": _utc(self.clock),
            "status": status,
            "volume": "D" if os.name == "nt" else "RUNTIME_VOLUME",
            "volume_total_bytes": usage.total,
            "volume_free_bytes": usage.free,
            "required_free_reserve_bytes": reserve,
            "budget_observed_bytes": total,
            "budget_cap_bytes": _BUDGET,
            "reference_operation_headroom_bytes": _HEADROOM,
            "entries_observed": entries,
            "scope": "Runtime .local ancestor, or runtime itself when absent",
        }

    def _storage(self) -> JsonRecord:
        now = self.monotonic()
        age = max(0.0, now - self._sample_at) if self._sample_at is not None else None
        due = self._sample_at is None or age is None or age >= 30
        retry = self._attempt_at is None or now - self._attempt_at >= 5
        busy = False
        sampled = False
        if due and retry:
            if self._storage_lock.acquire(blocking=False):
                try:
                    self._attempt_at = now
                    try:
                        self._sample = self._scan_storage()
                        self._sample_at = self.monotonic()
                        self._storage_error = None
                        age, sampled = 0.0, True
                    except OSError, ValueError:
                        self._storage_error = "STORAGE_SAMPLE_UNAVAILABLE"
                finally:
                    self._storage_lock.release()
            else:
                busy = True
        stale = age is None or age >= 30 or self._storage_error is not None or busy
        sample = self._sample
        return {
            "visibility": "OWNER_ONLY",
            "status": "UNKNOWN" if stale or sample is None else sample["status"],
            "freshness": (
                "UNAVAILABLE"
                if sample is None
                else "STALE"
                if stale
                else "LIVE_SAMPLE"
                if sampled
                else "CACHED"
            ),
            "sample_age_seconds": round(age, 3) if age is not None else None,
            "sample": dict(sample) if sample is not None else None,
            "error_code": "STORAGE_SAMPLE_BUSY" if busy else self._storage_error,
            "limitations": [
                "A bounded metadata sample can race active writes; it is not admission authority.",
                "Operation-specific reserves may be stricter. No host enforcement is claimed.",
            ],
        }

    def status(self, user: User) -> JsonRecord:
        private, global_counts = self._database(user)
        try:
            worker = self.worker_status().to_record()
            worker["observed_at"] = _utc(self.clock)
            worker["error_code"] = None
        except Exception:
            worker = {
                "state": "UNKNOWN",
                "generation": None,
                "started_at": None,
                "observed_at": _utc(self.clock),
                "error_code": "WORKER_OBSERVATION_UNAVAILABLE",
            }
        return {
            "observed_at": _utc(self.clock),
            "database": "AVAILABLE",
            "private": private,
            "global": global_counts,
            "worker": worker,
            "limits": {"active_slots": 2, "reserved_slots": 8},
            "storage": self._storage()
            if user.role == "owner"
            else {"visibility": "OWNER_ONLY"},
            "authority": "READ_ONLY_OBSERVATION; NOT_ADMISSION; NOT_SCIENTIFIC_VALIDATION",
        }
