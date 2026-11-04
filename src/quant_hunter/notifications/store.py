"""Additive application-SQLite inbox and immutable delivery attempts/receipts."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .types import (
    Notification,
    NotificationError,
    SendAuthorization,
    TelegramConfig,
    VaultReference,
    canonical,
    digest,
    identity,
    message_payload,
    stamp,
)


@dataclass(frozen=True)
class InboxEntry:
    sequence: int
    event: Notification
    local_status: str
    published_at: str
    read_at: str | None


@dataclass(frozen=True)
class Delivery:
    notification_id: str
    authorization_id: str
    configuration_digest: str
    state: str
    reason: str
    message_id: int | None


def _event(raw: bytes) -> Notification:
    try:
        values = json.loads(raw)
        values["created_at"] = datetime.fromisoformat(values["created_at"])
        values["expires_at"] = datetime.fromisoformat(values["expires_at"])
        event = Notification(**values)
        event.validate()
        if event.payload != raw:
            raise NotificationError("INBOX_INTEGRITY")
        return event
    except TypeError, ValueError, KeyError, UnicodeError:
        raise NotificationError("INBOX_INTEGRITY") from None


class NotificationStore:
    """Use the existing app database; no journal-mode/application-ID takeover."""

    def __init__(
        self, path: Path, *, before_commit: Callable[[], None] | None = None
    ) -> None:
        self.path, self.before_commit = path, before_commit
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS qhn_meta(version INTEGER NOT NULL CHECK(version=1));
                INSERT INTO qhn_meta SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM qhn_meta);
                CREATE TABLE IF NOT EXISTS qhn_events(sequence INTEGER PRIMARY KEY,owner TEXT NOT NULL,event_id TEXT NOT NULL,dedupe TEXT NOT NULL,payload BLOB NOT NULL,payload_digest TEXT NOT NULL,local_status TEXT NOT NULL,published_at TEXT NOT NULL,UNIQUE(owner,event_id),UNIQUE(owner,dedupe));
                CREATE TABLE IF NOT EXISTS qhn_reads(owner TEXT NOT NULL,event_id TEXT NOT NULL,read_at TEXT NOT NULL,PRIMARY KEY(owner,event_id),FOREIGN KEY(owner,event_id) REFERENCES qhn_events(owner,event_id));
                CREATE TABLE IF NOT EXISTS qhn_configs(owner TEXT NOT NULL,revision INTEGER NOT NULL,payload BLOB NOT NULL,payload_digest TEXT NOT NULL,PRIMARY KEY(owner,revision));
                CREATE TABLE IF NOT EXISTS qhn_attempts(owner TEXT NOT NULL,event_id TEXT NOT NULL,authorization_id TEXT NOT NULL,authorization BLOB NOT NULL,config BLOB NOT NULL,config_digest TEXT NOT NULL,request_digest TEXT NOT NULL,chat_id TEXT NOT NULL,attempted_at TEXT NOT NULL,fingerprint TEXT NOT NULL,PRIMARY KEY(owner,event_id),UNIQUE(owner,authorization_id),FOREIGN KEY(owner,event_id) REFERENCES qhn_events(owner,event_id));
                CREATE TABLE IF NOT EXISTS qhn_receipts(owner TEXT NOT NULL,event_id TEXT NOT NULL,revision INTEGER NOT NULL,state TEXT NOT NULL,reason TEXT NOT NULL,message_id INTEGER,receipt_hash TEXT NOT NULL,PRIMARY KEY(owner,event_id,revision),FOREIGN KEY(owner,event_id) REFERENCES qhn_attempts(owner,event_id));
                CREATE TABLE IF NOT EXISTS qhn_audit(sequence INTEGER PRIMARY KEY,owner TEXT NOT NULL,identity TEXT NOT NULL,operation TEXT NOT NULL,status TEXT NOT NULL,at TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS qhn_owner_inbox ON qhn_events(owner,sequence);
                CREATE INDEX IF NOT EXISTS qhn_owner_audit ON qhn_audit(owner,sequence);
            """)
            for table in (
                "qhn_events",
                "qhn_reads",
                "qhn_configs",
                "qhn_attempts",
                "qhn_receipts",
                "qhn_audit",
            ):
                # All names here are fixed code constants, never caller-supplied SQL.
                for operation in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable notification row'); END"
                    )
            if [row[0] for row in db.execute("SELECT version FROM qhn_meta")] != [1]:
                raise NotificationError("INBOX_SCHEMA_VERSION")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA temp_store=MEMORY")
            with db:
                yield db
        finally:
            db.close()

    def _audit(
        self,
        db: sqlite3.Connection,
        owner: str,
        item: str,
        operation: str,
        status: str,
        now: datetime,
    ) -> None:
        at = stamp(now)
        if db.execute("SELECT count(*) FROM qhn_audit").fetchone()[0] >= 50_000:
            raise NotificationError("AUDIT_CAPACITY")
        old = db.execute(
            "SELECT at,event_hash FROM qhn_audit WHERE owner=? ORDER BY sequence DESC LIMIT 1",
            (owner,),
        ).fetchone()
        if old and at < old["at"]:
            raise NotificationError("CLOCK_MOVED_BACKWARDS")
        previous = old["event_hash"] if old else "GENESIS"
        hashed = digest(canonical([owner, item, operation, status, at, previous]))
        db.execute(
            "INSERT INTO qhn_audit(owner,identity,operation,status,at,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?)",
            (owner, item, operation, status, at, previous, hashed),
        )
        if self.before_commit is not None:
            self.before_commit()

    @staticmethod
    def _entry(db: sqlite3.Connection, owner: str, event_id: str) -> InboxEntry:
        row = db.execute(
            "SELECT e.*,r.read_at FROM qhn_events e LEFT JOIN qhn_reads r USING(owner,event_id) WHERE owner=? AND event_id=?",
            (owner, event_id),
        ).fetchone()
        if row is None:
            raise NotificationError("NOTIFICATION_NOT_FOUND")
        raw = row["payload"]
        if not isinstance(raw, bytes) or digest(raw) != row["payload_digest"]:
            raise NotificationError("INBOX_INTEGRITY")
        return InboxEntry(
            row["sequence"],
            _event(raw),
            row["local_status"],
            row["published_at"],
            row["read_at"],
        )

    def publish(self, owner: str, event: Notification, *, now: datetime) -> InboxEntry:
        identity(owner)
        raw, at = event.payload, stamp(now)
        if event.created_at > now:
            raise NotificationError("FUTURE_EVENT")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT event_id,payload FROM qhn_events WHERE owner=? AND (event_id=? OR dedupe=?)",
                (owner, event.notification_id, event.dedupe_key),
            ).fetchall()
            if old:
                if len(old) != 1 or old[0]["payload"] != raw:
                    raise NotificationError("CONFLICTING_NOTIFICATION")
                return self._entry(db, owner, old[0]["event_id"])
            if db.execute("SELECT count(*) FROM qhn_events").fetchone()[0] >= 10_000:
                raise NotificationError("INBOX_CAPACITY")
            recent = db.execute(
                "SELECT count(*) FROM qhn_events WHERE owner=? AND local_status='DELIVERED_LOCAL' AND published_at>?",
                (owner, stamp(now - timedelta(minutes=1))),
            ).fetchone()[0]
            status = (
                "EXPIRED"
                if event.expires_at <= now
                else "RATE_LIMITED"
                if recent >= 30
                else "DELIVERED_LOCAL"
            )
            db.execute(
                "INSERT INTO qhn_events(owner,event_id,dedupe,payload,payload_digest,local_status,published_at) VALUES(?,?,?,?,?,?,?)",
                (
                    owner,
                    event.notification_id,
                    event.dedupe_key,
                    raw,
                    digest(raw),
                    status,
                    at,
                ),
            )
            self._audit(db, owner, event.notification_id, "PUBLISH", status, now)
            return self._entry(db, owner, event.notification_id)

    def get(self, owner: str, event_id: str) -> InboxEntry:
        identity(owner)
        identity(event_id)
        with self._db() as db:
            return self._entry(db, owner, event_id)

    def inbox(
        self, owner: str, *, after: int = 0, limit: int = 100
    ) -> tuple[InboxEntry, ...]:
        identity(owner)
        if (
            type(after) is not int
            or not 0 <= after <= 10_000
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise NotificationError("INBOX_PAGE_BOUND")
        with self._db() as db:
            db.execute("BEGIN")
            rows = db.execute(
                "SELECT event_id FROM qhn_events WHERE owner=? AND sequence>? ORDER BY sequence LIMIT ?",
                (owner, after, limit),
            ).fetchall()
            return tuple(self._entry(db, owner, row["event_id"]) for row in rows)

    def mark_read(self, owner: str, event_id: str, *, now: datetime) -> InboxEntry:
        identity(owner)
        identity(event_id)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            entry = self._entry(db, owner, event_id)
            if entry.read_at is None:
                db.execute(
                    "INSERT INTO qhn_reads VALUES(?,?,?)", (owner, event_id, stamp(now))
                )
                self._audit(db, owner, event_id, "READ", "READ", now)
            return self._entry(db, owner, event_id)

    @staticmethod
    def _configuration(db: sqlite3.Connection, owner: str) -> TelegramConfig | None:
        row = db.execute(
            "SELECT * FROM qhn_configs WHERE owner=? ORDER BY revision DESC LIMIT 1",
            (owner,),
        ).fetchone()
        if row is None:
            return None
        raw = row["payload"]
        if not isinstance(raw, bytes) or digest(raw) != row["payload_digest"]:
            raise NotificationError("CONFIGURATION_INTEGRITY")
        try:
            value = json.loads(raw)
            value["vault"] = VaultReference(**value["vault"])
            config = TelegramConfig(**value)
            if (
                config.payload != raw
                or config.owner_id != owner
                or config.revision != row["revision"]
            ):
                raise NotificationError("CONFIGURATION_INTEGRITY")
            return config
        except ValueError, TypeError, KeyError:
            raise NotificationError("CONFIGURATION_INTEGRITY") from None

    def configuration(self, owner: str) -> TelegramConfig | None:
        identity(owner)
        with self._db() as db:
            return self._configuration(db, owner)

    def configure(
        self,
        owner: str,
        config: TelegramConfig,
        *,
        expected_revision: int,
        now: datetime,
    ) -> TelegramConfig:
        identity(owner)
        raw = config.payload
        if (
            config.owner_id != owner
            or type(expected_revision) is not int
            or config.revision != expected_revision + 1
        ):
            raise NotificationError("CONFIGURATION_OWNER_OR_REVISION")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._configuration(db, owner)
            if (old.revision if old else 0) != expected_revision:
                raise NotificationError("STALE_CONFIGURATION")
            if db.execute("SELECT count(*) FROM qhn_configs").fetchone()[0] >= 10_000:
                raise NotificationError("CONFIGURATION_CAPACITY")
            db.execute(
                "INSERT INTO qhn_configs VALUES(?,?,?,?)",
                (owner, config.revision, raw, digest(raw)),
            )
            self._audit(
                db,
                owner,
                owner,
                "CONFIGURE",
                "ENABLED" if config.enabled else "DISABLED",
                now,
            )
            return config

    @staticmethod
    def _delivery(db: sqlite3.Connection, owner: str, event_id: str) -> Delivery | None:
        attempt = db.execute(
            "SELECT * FROM qhn_attempts WHERE owner=? AND event_id=?",
            (owner, event_id),
        ).fetchone()
        if attempt is None:
            return None
        if (
            not isinstance(attempt["authorization"], bytes)
            or not isinstance(attempt["config"], bytes)
            or not 0 < len(attempt["authorization"]) <= 8192
            or not 0 < len(attempt["config"]) <= 8192
        ):
            raise NotificationError("DELIVERY_INTEGRITY")
        previous = digest(
            canonical(
                [
                    owner,
                    event_id,
                    attempt["authorization_id"],
                    digest(attempt["authorization"]),
                    digest(attempt["config"]),
                    attempt["request_digest"],
                    attempt["chat_id"],
                    attempt["attempted_at"],
                ]
            )
        )
        if (
            previous != attempt["fingerprint"]
            or digest(attempt["config"]) != attempt["config_digest"]
        ):
            raise NotificationError("DELIVERY_INTEGRITY")
        result = None
        revision = 0
        for row in db.execute(
            "SELECT * FROM qhn_receipts WHERE owner=? AND event_id=? ORDER BY revision",
            (owner, event_id),
        ):
            revision += 1
            hashed = digest(
                canonical(
                    [
                        owner,
                        event_id,
                        revision,
                        row["state"],
                        row["reason"],
                        row["message_id"],
                        previous,
                    ]
                )
            )
            if (
                revision > 2
                or row["revision"] != revision
                or row["receipt_hash"] != hashed
            ):
                raise NotificationError("DELIVERY_INTEGRITY")
            previous = hashed
            result = Delivery(
                event_id,
                attempt["authorization_id"],
                attempt["config_digest"],
                row["state"],
                row["reason"],
                row["message_id"],
            )
        if result is None:
            raise NotificationError("DELIVERY_INTEGRITY")
        return result

    def delivery(self, owner: str, event_id: str) -> Delivery | None:
        identity(owner)
        identity(event_id)
        with self._db() as db:
            self._entry(db, owner, event_id)
            return self._delivery(db, owner, event_id)

    def reserve_send(
        self,
        owner: str,
        event_id: str,
        authorization: SendAuthorization,
        *,
        now: datetime,
    ) -> tuple[bool, Delivery]:
        identity(owner)
        identity(event_id)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            entry = self._entry(db, owner, event_id)
            existing = self._delivery(db, owner, event_id)
            if existing is not None:
                return False, existing
            config = self._configuration(db, owner)
            if config is None:
                raise NotificationError("TELEGRAM_NOT_CONFIGURED")
            payload = message_payload(config, entry.event)
            authorization.validate(
                owner, digest(entry.event.payload), digest(config.payload), payload, now
            )
            if authorization.purpose == "EXPLICIT_TEST" and entry.event.kind != "TEST":
                raise NotificationError("TEST_EVENT_REQUIRED")
            recent = db.execute(
                "SELECT count(*) FROM qhn_attempts WHERE chat_id=? AND attempted_at>?",
                (config.chat_id, stamp(now - timedelta(minutes=1))),
            ).fetchone()[0]
            fast = db.execute(
                "SELECT 1 FROM qhn_attempts WHERE chat_id=? AND attempted_at>? LIMIT 1",
                (config.chat_id, stamp(now - timedelta(seconds=1))),
            ).fetchone()
            global_fast = db.execute(
                "SELECT count(*) FROM qhn_attempts WHERE attempted_at>?",
                (stamp(now - timedelta(seconds=1)),),
            ).fetchone()[0]
            state, reason = "UNKNOWN", "RESERVED_BEFORE_WIRE_NO_AUTOMATIC_RETRY"
            if not config.enabled:
                state, reason = "BLOCKED", "CONFIGURATION_DISABLED"
            elif entry.event.expires_at <= now:
                state, reason = "EXPIRED", "EVENT_EXPIRED"
            elif entry.local_status != "DELIVERED_LOCAL":
                state, reason = "BLOCKED", "LOCAL_EVENT_NOT_DELIVERED"
            elif recent >= 20 or fast or global_fast >= 25:
                state, reason = "RATE_LIMITED", "DELIVERY_RATE_LIMIT"
            auth_bytes = canonical(asdict(authorization))
            fingerprint = digest(
                canonical(
                    [
                        owner,
                        event_id,
                        authorization.authorization_id,
                        digest(auth_bytes),
                        digest(config.payload),
                        digest(payload),
                        config.chat_id,
                        stamp(now),
                    ]
                )
            )
            try:
                db.execute(
                    "INSERT INTO qhn_attempts VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        owner,
                        event_id,
                        authorization.authorization_id,
                        auth_bytes,
                        config.payload,
                        digest(config.payload),
                        digest(payload),
                        config.chat_id,
                        stamp(now),
                        fingerprint,
                    ),
                )
            except sqlite3.IntegrityError:
                raise NotificationError("AUTHORIZATION_ALREADY_USED") from None
            db.execute(
                "INSERT INTO qhn_receipts VALUES(?,?,1,?,?,NULL,?)",
                (
                    owner,
                    event_id,
                    state,
                    reason,
                    digest(
                        canonical(
                            [owner, event_id, 1, state, reason, None, fingerprint]
                        )
                    ),
                ),
            )
            self._audit(db, owner, event_id, "SEND_RESERVED", state, now)
            result = self._delivery(db, owner, event_id)
            if result is None:
                raise NotificationError("DELIVERY_INTEGRITY")
            return state == "UNKNOWN", result

    def finish_send(
        self,
        owner: str,
        event_id: str,
        state: str,
        reason: str,
        *,
        message_id: int | None = None,
        now: datetime,
    ) -> Delivery:
        identity(owner)
        identity(event_id)
        identity(reason)
        if (
            state not in ("SENT", "REJECTED", "UNKNOWN", "BLOCKED")
            or (
                message_id is not None
                and (type(message_id) is not int or not 0 < message_id < 2**52)
            )
            or (state == "SENT" and message_id is None)
        ):
            raise NotificationError("INVALID_DELIVERY_RESULT")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._delivery(db, owner, event_id)
            if old is None:
                raise NotificationError("DELIVERY_NOT_FOUND")
            count = db.execute(
                "SELECT count(*) FROM qhn_receipts WHERE owner=? AND event_id=?",
                (owner, event_id),
            ).fetchone()[0]
            if count != 1 or old.state != "UNKNOWN":
                if (old.state, old.reason, old.message_id) == (
                    state,
                    reason,
                    message_id,
                ):
                    return old
                raise NotificationError("DELIVERY_ALREADY_FINALIZED")
            db.execute(
                "INSERT INTO qhn_receipts VALUES(?,?,2,?,?,?,?)",
                (
                    owner,
                    event_id,
                    state,
                    reason,
                    message_id,
                    digest(
                        canonical(
                            [
                                owner,
                                event_id,
                                2,
                                state,
                                reason,
                                message_id,
                                db.execute(
                                    "SELECT receipt_hash FROM qhn_receipts WHERE owner=? AND event_id=? AND revision=1",
                                    (owner, event_id),
                                ).fetchone()[0],
                            ]
                        )
                    ),
                ),
            )
            self._audit(db, owner, event_id, "SEND_RESULT", state, now)
            return Delivery(
                event_id,
                old.authorization_id,
                old.configuration_digest,
                state,
                reason,
                message_id,
            )

    def audit(self, owner: str, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        identity(owner)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise NotificationError("AUDIT_PAGE_BOUND")
        with self._db() as db:
            previous, result = "GENESIS", []
            for row in db.execute(
                "SELECT * FROM qhn_audit WHERE owner=? ORDER BY sequence", (owner,)
            ):
                expected = digest(
                    canonical(
                        [
                            owner,
                            row["identity"],
                            row["operation"],
                            row["status"],
                            row["at"],
                            previous,
                        ]
                    )
                )
                if row["previous_hash"] != previous or row["event_hash"] != expected:
                    raise NotificationError("AUDIT_INTEGRITY")
                previous = expected
                result.append(dict(row))
            return tuple(result[-limit:])
