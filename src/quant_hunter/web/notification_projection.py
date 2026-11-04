"""Bounded, restartable local-inbox projection of authoritative terminal jobs.

Only the existing NotificationAccess.record_job hook is called. Publication and
cursor commits are deliberately separate: a crash between them repeats an
idempotent publication. Neither research execution nor external send is invoked.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass, replace
from typing import cast

from quant_hunter.config import JsonRecord, parse_json_document
from quant_hunter.notifications.types import NotificationError, canonical, digest
from quant_hunter.web.notification_access import NotificationAccess
from quant_hunter.web.state import AccessError, User

MAX_JOBS = 10_000
MAX_PAGE = 100
MAX_COUNTER = 9_007_199_254_740_991
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
CODES = {
    "JOB_CAPACITY",
    "PROJECTION_INTEGRITY",
    "PROJECTION_CAPACITY",
    "PROJECTION_STORAGE_UNAVAILABLE",
    "INBOX_CAPACITY",
    "INBOX_INTEGRITY",
    "LOCAL_DELIVERY_REFUSED",
    "LOCAL_DELIVERY_UNAVAILABLE",
}


class ProjectionError(ValueError):
    """A fixed local projection diagnostic, never an exception-message channel."""


@dataclass(frozen=True)
class _Failure:
    code: str
    cycle: int
    cursor: str


@dataclass(frozen=True)
class _Head:
    owner_id: int
    cycle: int = 0
    cursor: str = ""
    ceiling: str = ""
    revision: int = 0
    unavailable: bool = False
    first_failure: _Failure | None = None
    last_failure: _Failure | None = None

    @property
    def payload(self) -> bytes:
        return canonical(asdict(self))


def _counter(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_COUNTER


def _identity(value: object) -> bool:
    return isinstance(value, str) and (
        value == "" or re.fullmatch(r"[a-f0-9]{32}", value) is not None
    )


def _failure(value: object) -> _Failure | None:
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"code", "cycle", "cursor"}
        or not isinstance(value["code"], str)
        or value["code"] not in CODES
        or not _counter(value["cycle"])
        or not _identity(value["cursor"])
    ):
        raise ProjectionError("PROJECTION_INTEGRITY")
    return _Failure(value["code"], value["cycle"], value["cursor"])


def _code(error: Exception) -> str:
    if isinstance(error, ProjectionError) and str(error) in CODES:
        return str(error)
    if isinstance(error, sqlite3.Error):
        return "PROJECTION_STORAGE_UNAVAILABLE"
    if isinstance(error, NotificationError):
        if str(error) in {"INBOX_CAPACITY", "AUDIT_CAPACITY"}:
            return "INBOX_CAPACITY"
        if str(error) in {"INBOX_INTEGRITY", "AUDIT_INTEGRITY", "INBOX_SCHEMA_VERSION"}:
            return "INBOX_INTEGRITY"
        return "LOCAL_DELIVERY_REFUSED"
    return "LOCAL_DELIVERY_UNAVAILABLE"


class NotificationProjection:
    """Host scheduler/inbox hook; each call examines at most 100 owned jobs.

    A fixed-ceiling cycle prevents new work from starving older jobs. Completed
    cycles restart on the next call, catching jobs that were pending on an
    earlier pass and new random primary keys inserted behind the cursor. The
    host must call sweep repeatedly; a single page is never a completeness claim.

    The mutable operational head retains the first and latest fixed failure
    receipts, not an unbounded event log. Inbox events retain their own reviewed
    immutable audit. This head grants no scientific or external-send authority.
    """

    def __init__(self, access: NotificationAccess) -> None:
        if access.store.path != access.state.path:
            raise ProjectionError("PROJECTION_INTEGRITY")
        self.access, self.state = access, access.state
        with self.state.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS qhn_projection (owner_id INTEGER PRIMARY KEY "
                "REFERENCES users(id),payload BLOB NOT NULL,digest TEXT NOT NULL)"
            )

    @staticmethod
    def _actor(db: sqlite3.Connection, user: User) -> None:
        actual = db.execute(
            "SELECT username,role FROM users WHERE id=?", (user.id,)
        ).fetchone()
        if actual is None or tuple(actual) != (user.username, user.role):
            raise AccessError("Notification projection access denied")

    @staticmethod
    def _head(db: sqlite3.Connection, user: User) -> _Head:
        row = db.execute(
            "SELECT payload,digest FROM qhn_projection WHERE owner_id=?", (user.id,)
        ).fetchone()
        if row is None:
            return _Head(user.id)
        raw = row["payload"]
        if (
            not isinstance(raw, bytes)
            or len(raw) > 4096
            or digest(raw) != row["digest"]
        ):
            raise ProjectionError("PROJECTION_INTEGRITY")
        try:
            value = parse_json_document(raw)
        except ValueError:
            raise ProjectionError("PROJECTION_INTEGRITY") from None
        if (
            not isinstance(value, dict)
            or set(value) != set(asdict(_Head(user.id)))
            or value["owner_id"] != user.id
            or type(value["owner_id"]) is not int
            or not all(_counter(value[k]) for k in ("cycle", "revision"))
            or not all(_identity(value[k]) for k in ("cursor", "ceiling"))
            or cast(str, value["cursor"]) > cast(str, value["ceiling"])
            or type(value["unavailable"]) is not bool
        ):
            raise ProjectionError("PROJECTION_INTEGRITY")
        result = _Head(
            user.id,
            cast(int, value["cycle"]),
            cast(str, value["cursor"]),
            cast(str, value["ceiling"]),
            cast(int, value["revision"]),
            value["unavailable"],
            _failure(value["first_failure"]),
            _failure(value["last_failure"]),
        )
        if (
            result.payload != raw
            or (result.first_failure is None) != (result.last_failure is None)
            or (result.unavailable and result.last_failure is None)
            or any(
                failure.cycle > result.cycle
                for failure in (result.first_failure, result.last_failure)
                if failure is not None
            )
        ):
            raise ProjectionError("PROJECTION_INTEGRITY")
        return result

    def _save(self, user: User, old: _Head, new: _Head) -> bool:
        """Compare-and-swap; concurrent losers never move a cursor backwards."""
        if old.revision >= MAX_COUNTER:
            raise ProjectionError("PROJECTION_CAPACITY")
        new = replace(new, revision=old.revision + 1)
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._actor(db, user)
            if self._head(db, user) != old:
                return False
            db.execute(
                "INSERT INTO qhn_projection VALUES(?,?,?) ON CONFLICT(owner_id) "
                "DO UPDATE SET payload=excluded.payload,digest=excluded.digest",
                (user.id, new.payload, digest(new.payload)),
            )
        return True

    @staticmethod
    def _view(
        head: _Head, *, scanned: int = 0, projected: int = 0, persisted: bool = True
    ) -> JsonRecord:
        return {
            "status": "LOCAL_DELIVERY_UNAVAILABLE"
            if head.unavailable
            else "READY"
            if head.cycle
            else "NOT_STARTED",
            "local_delivery_unavailable": head.unavailable,
            "failure_code": head.last_failure.code
            if head.unavailable and head.last_failure
            else None,
            "failure_receipt_persisted": persisted,
            "first_failure": cast(JsonRecord, asdict(head.first_failure))
            if head.first_failure
            else None,
            "last_failure": cast(JsonRecord, asdict(head.last_failure))
            if head.last_failure
            else None,
            "cycle": head.cycle,
            "cursor": head.cursor,
            "ceiling": head.ceiling,
            "cycle_complete": head.cycle > 0 and head.cursor == head.ceiling,
            "scanned": scanned,
            "projected": projected,
            "page_limit": MAX_PAGE,
            "automatic_external_delivery": False,
            "authority": "LOCAL_INBOX_PROJECTION_ONLY",
        }

    def _unavailable(
        self, user: User, error: Exception, *, scanned: int = 0, projected: int = 0
    ) -> JsonRecord:
        code = _code(error)
        head = _Head(user.id)
        persisted = False
        try:
            with self.state.connection() as db:
                self._actor(db, user)
                head = self._head(db, user)
            receipt = _Failure(code, head.cycle, head.cursor)
            failed = replace(
                head,
                unavailable=True,
                first_failure=head.first_failure or receipt,
                last_failure=receipt,
            )
            persisted = failed == head or self._save(user, head, failed)
        except AccessError:
            raise
        except Exception:
            persisted = False  # Never log arbitrary exception text or promise a write.
        receipt = _Failure(code, head.cycle, head.cursor)
        return self._view(
            replace(
                head,
                unavailable=True,
                first_failure=head.first_failure or receipt,
                last_failure=receipt,
            ),
            scanned=scanned,
            projected=projected,
            persisted=persisted,
        )

    def status(self, user: User) -> JsonRecord:
        """Private saved projection state; no job evaluation or network work."""
        try:
            with self.state.connection() as db:
                self._actor(db, user)
                return self._view(self._head(db, user))
        except AccessError:
            raise
        except Exception as error:
            return self._unavailable(user, error)

    def _project(self, user: User, row: sqlite3.Row) -> None:
        self.access.record_job(user, row["id"])
        expected = (
            "NOTICE-" + digest(canonical([row["id"], row["status"]])).split(":")[1]
        )
        # Confirm a real retained inbox event, not merely a callback return value.
        event = self.access.store.get(str(user.id), expected).event
        body = (
            f"Job {row['id']} is {row['status']}. Inspect its retained evidence. "
            "This operational notification is not scientific approval."
        )
        if (
            event.notification_id != expected
            or event.dedupe_key != expected
            or event.title != "Local experiment job status"
            or event.experiment_id != row["experiment_id"]
            or event.mode != "SYSTEM"
            or event.body != body
            or event.kind != ("FAILURE" if row["status"] == "FAILED" else "SYSTEM")
            or event.severity != ("ERROR" if row["status"] == "FAILED" else "INFO")
        ):
            raise ProjectionError("PROJECTION_INTEGRITY")

    def sweep(self, user: User, *, limit: int = MAX_PAGE) -> JsonRecord:
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
            raise ValueError("Projection page limit must be between 1 and 100")
        scanned = projected = 0
        try:
            with self.state.connection() as db:
                self._actor(db, user)
                head = self._head(db, user)
                if (
                    db.execute(
                        "SELECT count(*) FROM (SELECT 1 FROM jobs LIMIT ?)",
                        (MAX_JOBS + 1,),
                    ).fetchone()[0]
                    > MAX_JOBS
                ):
                    raise ProjectionError("JOB_CAPACITY")
                for anchor in {head.cursor, head.ceiling} - {""}:
                    if (
                        db.execute(
                            "SELECT 1 FROM jobs WHERE id=? AND owner_id=?",
                            (anchor, user.id),
                        ).fetchone()
                        is None
                    ):
                        raise ProjectionError("PROJECTION_INTEGRITY")
                ceiling = db.execute(
                    "SELECT COALESCE(MAX(id),'') FROM jobs WHERE owner_id=?", (user.id,)
                ).fetchone()[0]
            if not _identity(ceiling):
                raise ProjectionError("PROJECTION_INTEGRITY")
            if head.cursor == head.ceiling:
                if head.cycle >= MAX_COUNTER:
                    raise ProjectionError("PROJECTION_CAPACITY")
                started = replace(
                    head, cycle=head.cycle + 1, cursor="", ceiling=ceiling
                )
                if not self._save(user, head, started):
                    return self.status(user)
                head = replace(started, revision=head.revision + 1)
            with self.state.connection() as db:
                self._actor(db, user)
                rows = db.execute(
                    "SELECT id,status,experiment_id FROM jobs WHERE owner_id=? AND id>? AND id<=? "
                    "ORDER BY id LIMIT ?",
                    (user.id, head.cursor, head.ceiling, limit),
                ).fetchall()
            for row in rows:
                if (
                    not _identity(row["id"])
                    or not row["id"]
                    or row["status"] not in (TERMINAL | {"QUEUED", "RUNNING"})
                ):
                    raise ProjectionError("PROJECTION_INTEGRITY")
                if row["status"] in TERMINAL:
                    self._project(user, row)
                    projected += 1
                next_head = replace(head, cursor=row["id"], unavailable=False)
                if not self._save(user, head, next_head):
                    return {
                        **self.status(user),
                        "scanned": scanned,
                        "projected": projected,
                    }
                head = replace(next_head, revision=head.revision + 1)
                scanned += 1
            if not rows and head.unavailable:
                clean = replace(head, unavailable=False)
                if self._save(user, head, clean):
                    head = replace(clean, revision=head.revision + 1)
            return self._view(head, scanned=scanned, projected=projected)
        except AccessError:
            raise
        except Exception as error:
            return self._unavailable(user, error, scanned=scanned, projected=projected)
