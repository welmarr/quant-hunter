"""Persistent local-paper stop barrier; no external execution authority.

The host's single-process lease is mandatory. Every instance uses the same
path-keyed lock, and every decision also verifies the SQLite event history.
"""

from __future__ import annotations

import hashlib
import sqlite3
from _thread import RLock
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, cast
from weakref import WeakValueDictionary

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.web.state import AccessError, User

if TYPE_CHECKING:
    from quant_hunter.web.paper_access import PaperAccess

MAX_CONTROLS = 65  # Alternation reserves the final record for HALT.
MAX_TASKS = 32
MAX_RECEIPTS = 8
MAX_EVENT_BYTES = 16384
MAX_RECEIPT_BYTES = 2048
_LOCKS: WeakValueDictionary[str, RLock] = WeakValueDictionary()
_LOCKS_GUARD = Lock()
PROTECTED = {"PROTECTED", "NOT_STARTED", "TERMINAL_NOT_RUNNABLE"}


class HaltError(ValueError):
    """Closed operational failure; never contains session or request content."""


def gate_lock(path: Path) -> RLock:
    return _shared_lock("STEP:" + str(path.resolve()).casefold())


def proof_lock(path: Path) -> RLock:
    """All controls and complete linked-reader lifetimes share this short gate."""
    return _shared_lock("PROOF:" + str(path.resolve()).casefold())


def _shared_lock(key: str) -> RLock:
    with _LOCKS_GUARD:
        result = _LOCKS.get(key)
        if result is None:
            result = RLock()
            _LOCKS[key] = result
        return result


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes, maximum: int) -> JsonRecord:
    if not 1 <= len(raw) <= maximum:
        raise HaltError("HALT_EVIDENCE_SIZE")
    try:
        value = parse_json_document(raw)
        if not isinstance(value, dict) or canonicalize_json(value) != raw:
            raise ValueError
    except ValueError:
        raise HaltError("HALT_EVIDENCE_FORMAT") from None
    return value


def _head(db: sqlite3.Connection) -> JsonRecord:
    head: JsonRecord = {"revision": 0, "action": "CLEAR", "tasks": []}
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='qhp_halt_events' AND type='table'"
    ).fetchone():
        return head
    previous = ""
    previous_at = ""
    for index, row in enumerate(
        db.execute("SELECT * FROM qhp_halt_events ORDER BY revision"), 1
    ):
        raw = bytes(row["payload"])
        item = _decode(raw, MAX_EVENT_BYTES)
        tasks = item.get("tasks")
        at = item.get("at")
        if (
            index > MAX_CONTROLS
            or row["revision"] != index
            or row["previous"] != previous
            or row["digest"] != _hash(previous.encode() + raw)
            or set(item) != {"revision", "action", "owner_id", "at", "tasks", "proofs"}
            or type(item["revision"]) is not int
            or item["revision"] != index
            or type(item["owner_id"]) is not int
            or item["owner_id"] < 1
            or item["action"] != ("HALT" if index % 2 else "CLEAR")
            or not isinstance(at, str)
            or not at.endswith("+00:00")
            or at < previous_at
            or not isinstance(tasks, list)
            or len(tasks) > MAX_TASKS
            or (item["action"] == "CLEAR" and tasks)
        ):
            raise HaltError("HALT_CHAIN_INTEGRITY")
        try:
            datetime.fromisoformat(at)
        except ValueError:
            raise HaltError("HALT_TIME_INTEGRITY") from None
        ids: set[str] = set()
        for task in tasks:
            if (
                not isinstance(task, dict)
                or set(task) != {"job_id", "owner_id", "workflow_revision"}
                or not isinstance(task["job_id"], str)
                or not task["job_id"].startswith("PAPER-")
                or len(task["job_id"]) != 38
                or task["job_id"] in ids
                or type(task["owner_id"]) is not int
                or task["owner_id"] < 1
                or type(task["workflow_revision"]) is not int
                or not 1 <= task["workflow_revision"] <= 600
            ):
                raise HaltError("HALT_TASK_INTEGRITY")
            ids.add(task["job_id"])
        expected_proofs = _proof_refs(db, head) if item["action"] == "CLEAR" else []
        if item["proofs"] != expected_proofs:
            raise HaltError("CLEAR_PROOF_BINDING")
        head, previous, previous_at = item, row["digest"], at
    return head


def _proof_refs(db: sqlite3.Connection, head: JsonRecord) -> list[JsonValue]:
    result: list[JsonValue] = []
    for task in cast(list[JsonRecord], head["tasks"]):
        receipt = GlobalPaperHalt._receipt(
            db, cast(int, head["revision"]), cast(str, task["job_id"])
        )
        if not receipt or receipt["status"] not in PROTECTED:
            raise HaltError("CLEAR_PROOF_MISSING")
        tail = db.execute(
            "SELECT digest FROM qhp_halt_receipts WHERE halt_revision=? AND job_id=? ORDER BY attempt DESC LIMIT 1",
            (head["revision"], task["job_id"]),
        ).fetchone()
        result.append({"job_id": task["job_id"], "receipt_digest": tail[0]})
    return result


def halted(db: sqlite3.Connection) -> bool:
    return _head(db)["action"] == "HALT"


def task_authorized(db: sqlite3.Connection, job_id: str, halt_revision: int) -> int:
    head = _head(db)
    if (
        head["action"] == "HALT"
        and type(halt_revision) is int
        and head["revision"] == halt_revision
    ):
        for task in cast(list[JsonRecord], head["tasks"]):
            if task["job_id"] == job_id:
                return cast(int, task["owner_id"])
    raise HaltError("PERSISTED_PROTECTIVE_TASK_REQUIRED")


def _denied_resource(
    actor: User, paper_id: str, halt_revision: int
) -> AbstractContextManager[None]:
    raise HaltError("HALT_READ_ADMISSION_REQUIRED")


class GlobalPaperHalt:
    """Owner stop/clear, aggregate status, and one bounded protective scheduler step.

    read_resource(actor, paper_id, halt_revision) reserves a shared host slot,
    borrowing only that verified existing paper queue reservation. It must call
    authorize_reader under its admission transaction and release on every exit.
    """

    def __init__(
        self,
        paper: PaperAccess,
        *,
        read_resource: Callable[
            [User, str, int], AbstractContextManager[None]
        ] = _denied_resource,
    ) -> None:
        self.paper, self.state, self.read_resource = paper, paper.state, read_resource
        with self.state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS qhp_halt_events (
                    revision INTEGER PRIMARY KEY, payload BLOB NOT NULL,
                    previous TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS qhp_halt_receipts (
                    halt_revision INTEGER NOT NULL REFERENCES qhp_halt_events(revision),
                    job_id TEXT NOT NULL REFERENCES paper_jobs(id), attempt INTEGER NOT NULL,
                    payload BLOB NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL,
                    PRIMARY KEY(halt_revision,job_id,attempt));
                CREATE TRIGGER IF NOT EXISTS qhp_halt_update BEFORE UPDATE ON qhp_halt_events BEGIN SELECT RAISE(ABORT,'immutable halt'); END;
                CREATE TRIGGER IF NOT EXISTS qhp_halt_delete BEFORE DELETE ON qhp_halt_events BEGIN SELECT RAISE(ABORT,'immutable halt'); END;
                CREATE TRIGGER IF NOT EXISTS qhp_halt_receipt_update BEFORE UPDATE ON qhp_halt_receipts BEGIN SELECT RAISE(ABORT,'immutable halt receipt'); END;
                CREATE TRIGGER IF NOT EXISTS qhp_halt_receipt_delete BEFORE DELETE ON qhp_halt_receipts BEGIN SELECT RAISE(ABORT,'immutable halt receipt'); END;
            """)
            _head(db)

    def authorize_reader(
        self, db: sqlite3.Connection, actor: User, paper_id: str, halt_revision: int
    ) -> JsonRecord:
        """Trusted host admission helper, called inside BEGIN IMMEDIATE.

        This is not an ordinary portfolio authorization API. Root holds proof_lock
        through admission, reading and release, then inserts a uniquely linked
        reader only after this check, preserving active2.
        """
        if not db.in_transaction:
            raise HaltError("ADMISSION_TRANSACTION_REQUIRED")
        self.paper._actor(db, actor, mutation=False)
        head = _head(db)
        owner_id = task_authorized(db, paper_id, halt_revision)
        if actor.id != head["owner_id"] and actor.role != "owner":
            raise AccessError("Global protective reader unavailable")
        row = self.paper._load(db, paper_id, owner_id)
        if (
            row["status"] != "PAUSED"
            or row["experiment_id"] is None
            or row["inflight"] is not None
            or row["requested"] is not None
        ):
            raise HaltError("EXISTING_PAPER_PROOF_RESERVATION_REQUIRED")
        control = db.execute(
            "SELECT digest FROM qhp_halt_events WHERE revision=?", (halt_revision,)
        ).fetchone()
        return {
            "paper_job_id": paper_id,
            "paper_owner_id": owner_id,
            "workflow_revision": row["revision"],
            "halt_revision": halt_revision,
            "halt_digest": control[0],
            "reader_owner_id": actor.id,
        }

    def _proof(self, actor: User, paper_id: str, revision: int) -> JsonRecord:
        with proof_lock(self.state.path):
            with self.state.connection() as db:
                owner_id = task_authorized(db, paper_id, revision)
                row = self.paper._load(db, paper_id, owner_id)
            if (
                row["status"] == "PAUSED"
                and row["experiment_id"] is not None
                and row["inflight"] is None
                and row["requested"] is None
            ):
                with self.read_resource(actor, paper_id, revision):
                    return self.paper.protection_receipt(paper_id, revision)
            # CREATED/terminal proofs and uncertain refusals read operational metadata
            # only. They must not borrow a non-existent terminal paper reservation.
            return self.paper.protection_receipt(paper_id, revision)

    def _owner(self, db: sqlite3.Connection, user: User) -> None:
        self.paper._actor(db, user, mutation=True)
        if user.role != "owner":
            raise AccessError("Global paper halt owner access required")

    @staticmethod
    def _receipt(
        db: sqlite3.Connection, revision: int, job_id: str
    ) -> JsonRecord | None:
        previous = ""
        result = None
        for index, row in enumerate(
            db.execute(
                "SELECT * FROM qhp_halt_receipts WHERE halt_revision=? AND job_id=? ORDER BY attempt",
                (revision, job_id),
            ),
            1,
        ):
            raw = bytes(row["payload"])
            result = _decode(raw, MAX_RECEIPT_BYTES)
            if (
                index > MAX_RECEIPTS
                or row["attempt"] != index
                or row["previous"] != previous
                or row["digest"] != _hash(previous.encode() + raw)
                or result.get("halt_revision") != revision
                or result.get("job_id") != job_id
                or result.get("status") not in PROTECTED | {"BLOCKED"}
                or type(result.get("workflow_revision")) is not int
            ):
                raise HaltError("HALT_RECEIPT_INTEGRITY")
            previous = row["digest"]
        return result

    def _save_receipt(self, receipt: JsonRecord) -> None:
        raw = canonicalize_json(receipt)
        if len(raw) > MAX_RECEIPT_BYTES:
            raise HaltError("HALT_RECEIPT_SIZE")
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            task_authorized(
                db, cast(str, receipt["job_id"]), cast(int, receipt["halt_revision"])
            )
            row = self.paper._load(db, cast(str, receipt["job_id"]))
            if row["revision"] != receipt["workflow_revision"]:
                raise HaltError("HALT_STALE_PROOF")
            last = self._receipt(
                db, cast(int, receipt["halt_revision"]), cast(str, receipt["job_id"])
            )
            if last == receipt:
                return
            tail = db.execute(
                "SELECT attempt,digest FROM qhp_halt_receipts WHERE halt_revision=? AND job_id=? ORDER BY attempt DESC LIMIT 1",
                (receipt["halt_revision"], receipt["job_id"]),
            ).fetchone()
            attempt, previous = (tail[0] + 1, tail[1]) if tail else (1, "")
            if attempt > MAX_RECEIPTS:
                raise HaltError("HALT_RECEIPT_CAPACITY")
            db.execute(
                "INSERT INTO qhp_halt_receipts VALUES(?,?,?,?,?,?)",
                (
                    receipt["halt_revision"],
                    receipt["job_id"],
                    attempt,
                    raw,
                    previous,
                    _hash(previous.encode() + raw),
                ),
            )

    def status(self, user: User) -> JsonRecord:
        with gate_lock(self.state.path), self.state.connection() as db:
            self.paper._actor(db, user, mutation=False)
            head = _head(db)
            result: JsonRecord = {
                "halted": head["action"] == "HALT",
                "revision": head["revision"],
                "scope": "LOCAL_PAPER_ONLY",
                "automatic_resume": False,
            }
            if user.role == "owner":
                counts = {"pending": 0, "protected": 0, "blocked": 0}
                for task in cast(list[JsonRecord], head["tasks"]):
                    row = self.paper._load(
                        db, cast(str, task["job_id"]), cast(int, task["owner_id"])
                    )
                    receipt = self._receipt(
                        db, cast(int, head["revision"]), cast(str, row["id"])
                    )
                    key = (
                        "pending"
                        if not receipt
                        or receipt["workflow_revision"] != row["revision"]
                        else "blocked"
                        if receipt["status"] == "BLOCKED"
                        else "protected"
                    )
                    counts[key] += 1
                result["counts"] = cast(JsonRecord, counts)
            return result

    def _append(
        self, db: sqlite3.Connection, user: User, action: str, tasks: list[JsonValue]
    ) -> None:
        head = _head(db)
        revision = cast(int, head["revision"]) + 1
        if revision > MAX_CONTROLS or (action == "CLEAR" and revision >= MAX_CONTROLS):
            raise HaltError("HALT_CONTROL_CAPACITY")
        item: JsonRecord = {
            "revision": revision,
            "action": action,
            "owner_id": user.id,
            "at": datetime.now(UTC).isoformat(),
            "tasks": tasks,
            "proofs": _proof_refs(db, head) if action == "CLEAR" else [],
        }
        raw = canonicalize_json(item)
        if len(raw) > MAX_EVENT_BYTES:
            raise HaltError("HALT_EVENT_CAPACITY")
        tail = db.execute(
            "SELECT digest FROM qhp_halt_events ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        previous = tail[0] if tail else ""
        db.execute(
            "INSERT INTO qhp_halt_events VALUES(?,?,?,?)",
            (revision, raw, previous, _hash(previous.encode() + raw)),
        )
        _head(db)  # Also rejects backwards clock movement before commit.

    def halt(self, user: User, *, expected_revision: int) -> JsonRecord:
        with gate_lock(self.state.path):
            with self.state.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                self._owner(db, user)
                head = _head(db)
                if (
                    type(expected_revision) is not int
                    or head["revision"] != expected_revision
                ):
                    raise HaltError("STALE_HALT_REVISION")
                if head["action"] == "HALT":
                    raise HaltError("ALREADY_HALTED")
                tasks: list[JsonValue] = []
                for selected in db.execute(
                    "SELECT id FROM paper_jobs WHERE status NOT IN ('COMPLETED','FAILED','CANCELLED') ORDER BY id"
                ):
                    row = self.paper._load(db, selected[0])
                    tasks.append(
                        {
                            "job_id": row["id"],
                            "owner_id": row["owner_id"],
                            "workflow_revision": row["revision"],
                        }
                    )
                if len(tasks) > MAX_TASKS:
                    raise HaltError("HALT_TASK_CAPACITY")
                self._append(db, user, "HALT", tasks)
            return self.status(user)

    def clear(self, user: User, *, expected_revision: int) -> JsonRecord:
        with gate_lock(self.state.path):
            with self.state.connection() as db:
                self._owner(db, user)
                head = _head(db)
                if (
                    type(expected_revision) is not int
                    or head["revision"] != expected_revision
                    or head["action"] != "HALT"
                ):
                    raise HaltError("STALE_HALT_REVISION")
                tasks = cast(list[JsonRecord], head["tasks"])
            verified: list[JsonRecord] = []
            for task in tasks:
                proof = self._proof(user, cast(str, task["job_id"]), expected_revision)
                with self.state.connection() as db:
                    receipt = self._receipt(
                        db, expected_revision, cast(str, task["job_id"])
                    )
                if proof != receipt:
                    raise HaltError("PROTECTIVE_RECEIPT_REQUIRED")
                verified.append(proof)
            with self.state.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                self._owner(db, user)
                for proof in verified:
                    row = self.paper._load(db, cast(str, proof["job_id"]))
                    if row["revision"] != proof["workflow_revision"]:
                        raise HaltError("HALT_STALE_PROOF")
                self._append(db, user, "CLEAR", [])
            return self.status(user)

    def process_one(self) -> bool:
        """No automatic retry of unknown commands; at most one protective task."""
        from quant_hunter.web.paper_access import PaperConflictError

        with gate_lock(self.state.path):
            with self.state.connection() as db:
                head = _head(db)
                if head["action"] != "HALT":
                    return self.paper.process_one()
                issuer = db.execute(
                    "SELECT id,username,role FROM users WHERE id=?", (head["owner_id"],)
                ).fetchone()
                if issuer is None:
                    raise AccessError("Retained halt issuer unavailable")
                actor = User(issuer["id"], issuer["username"], issuer["role"])
                selected = None
                for task in cast(list[JsonRecord], head["tasks"]):
                    row = self.paper._load(
                        db, cast(str, task["job_id"]), cast(int, task["owner_id"])
                    )
                    last = self._receipt(
                        db, cast(int, head["revision"]), cast(str, row["id"])
                    )
                    if last is None or last["workflow_revision"] != row["revision"]:
                        selected = row
                        break
            if selected is None:
                return (
                    self.paper.process_one()
                )  # Only pending local KILL/CANCEL can run.
            job_id, revision = cast(str, selected["id"]), cast(int, head["revision"])
            try:
                try:
                    proof = self._proof(actor, job_id, revision)
                except PaperConflictError:
                    progressed = self.paper.protective_halt_step(job_id, revision)
                    try:
                        proof = self._proof(actor, job_id, revision)
                    except PaperConflictError:
                        if not progressed:
                            return False  # Occupied worker slots: no audit retry churn.
                        raise
            except PaperConflictError as error:
                with self.state.connection() as db:
                    row = self.paper._load(db, job_id)
                proof = {
                    "job_id": job_id,
                    "halt_revision": revision,
                    "workflow_revision": row["revision"],
                    "status": "BLOCKED",
                    "reason": "RECONCILIATION_REQUIRED"
                    if str(error) == "RECONCILIATION_REQUIRED"
                    else "PROTECTION_UNVERIFIED",
                }
            self._save_receipt(proof)
            return True

    def has_pending(self) -> bool:
        with gate_lock(self.state.path), self.state.connection() as db:
            head = _head(db)
            if head["action"] == "HALT":
                for task in cast(list[JsonRecord], head["tasks"]):
                    row = self.paper._load(
                        db, cast(str, task["job_id"]), cast(int, task["owner_id"])
                    )
                    receipt = self._receipt(
                        db, cast(int, head["revision"]), cast(str, row["id"])
                    )
                    if not receipt or receipt["workflow_revision"] != row["revision"]:
                        return True
                return (
                    db.execute(
                        "SELECT 1 FROM paper_jobs WHERE status NOT IN ('STARTING','STEPPING','RECOVERING','COMPLETED','FAILED','CANCELLED') AND experiment_id IS NOT NULL AND json_extract(payload,'$.requested') IN ('KILL','CANCEL') LIMIT 1"
                    ).fetchone()
                    is not None
                )
            return self.paper.has_pending()
