"""Durable at-most-one wire attempt per approved paper action; no automatic retry."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .common import (
    MAX_REQUEST,
    BrokerConfig,
    BrokerError,
    RiskAuthorization,
    canonical,
    digest,
    identifier,
    parse,
    record,
)


@dataclass(frozen=True)
class Submission:
    action_id: str
    action: str
    client_order_id: str
    state: str
    reason: str
    broker_order_id: str | None
    revision: int


class SubmissionJournal:
    """Host-owned file; account identity binds a single owner across restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS account_bindings(provider TEXT NOT NULL,account_id TEXT NOT NULL,owner_id TEXT NOT NULL,PRIMARY KEY(provider,account_id));
                CREATE TABLE IF NOT EXISTS actions(provider TEXT NOT NULL,account_id TEXT NOT NULL,action_id TEXT NOT NULL,action TEXT NOT NULL,client_id TEXT NOT NULL,request BLOB NOT NULL,authorization BLOB NOT NULL,fingerprint TEXT NOT NULL,PRIMARY KEY(provider,account_id,action_id),FOREIGN KEY(provider,account_id) REFERENCES account_bindings(provider,account_id));
                CREATE UNIQUE INDEX IF NOT EXISTS one_order_identity ON actions(provider,account_id,client_id) WHERE action IN ('SUBMIT','REPLACE');
                CREATE TABLE IF NOT EXISTS receipts(provider TEXT NOT NULL,account_id TEXT NOT NULL,action_id TEXT NOT NULL,revision INTEGER NOT NULL,state TEXT NOT NULL,reason TEXT NOT NULL,broker_id TEXT,previous_hash TEXT NOT NULL,receipt_hash TEXT NOT NULL,PRIMARY KEY(provider,account_id,action_id,revision),FOREIGN KEY(provider,account_id,action_id) REFERENCES actions(provider,account_id,action_id));
                CREATE TABLE IF NOT EXISTS heads(provider TEXT NOT NULL,account_id TEXT NOT NULL,action_id TEXT NOT NULL,revision INTEGER NOT NULL,receipt_hash TEXT NOT NULL,PRIMARY KEY(provider,account_id,action_id),FOREIGN KEY(provider,account_id,action_id) REFERENCES actions(provider,account_id,action_id));
                CREATE TRIGGER IF NOT EXISTS bindings_update BEFORE UPDATE ON account_bindings BEGIN SELECT RAISE(ABORT,'immutable account'); END;
                CREATE TRIGGER IF NOT EXISTS bindings_delete BEFORE DELETE ON account_bindings BEGIN SELECT RAISE(ABORT,'immutable account'); END;
                CREATE TRIGGER IF NOT EXISTS actions_update BEFORE UPDATE ON actions BEGIN SELECT RAISE(ABORT,'immutable action'); END;
                CREATE TRIGGER IF NOT EXISTS actions_delete BEFORE DELETE ON actions BEGIN SELECT RAISE(ABORT,'immutable action'); END;
                CREATE TRIGGER IF NOT EXISTS receipts_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
                CREATE TRIGGER IF NOT EXISTS receipts_delete BEFORE DELETE ON receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END;
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.path.exists() and self.path.stat().st_size > 33_554_432:
            raise BrokerError("JOURNAL_SIZE_LIMIT")
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            identity = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if (
                identity == 0
                and version == 0
                and not db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchone()
            ):
                db.execute("PRAGMA page_size=4096")
                db.execute("PRAGMA application_id=1363690033")
                db.execute("PRAGMA user_version=1")
            elif identity != 1363690033 or version != 1:
                raise BrokerError("JOURNAL_FORMAT")
            if db.execute("PRAGMA page_size").fetchone()[0] != 4096:
                raise BrokerError("JOURNAL_FORMAT")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute("PRAGMA max_page_count=8192")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _owner(
        db: sqlite3.Connection, config: BrokerConfig, *, create: bool = False
    ) -> None:
        config.validate()
        row = db.execute(
            "SELECT owner_id FROM account_bindings WHERE provider=? AND account_id=?",
            (config.provider, config.account_id),
        ).fetchone()
        if row is None and create:
            if db.execute("SELECT count(*) FROM account_bindings").fetchone()[0] >= 32:
                raise BrokerError("JOURNAL_ACCOUNT_LIMIT")
            db.execute(
                "INSERT INTO account_bindings VALUES(?,?,?)",
                (config.provider, config.account_id, config.owner_id),
            )
        elif row is None or row["owner_id"] != config.owner_id:
            raise BrokerError("ACCOUNT_OWNER_MISMATCH")

    @staticmethod
    def _fingerprint(request: bytes, authorization: bytes) -> str:
        return digest(len(request).to_bytes(4, "big") + request + authorization)

    def reserve(
        self,
        config: BrokerConfig,
        action: str,
        client_id: str,
        request: bytes,
        authorization: RiskAuthorization,
    ) -> tuple[bool, Submission]:
        identifier(client_id)
        config.validate()
        if not isinstance(request, bytes) or not 0 < len(request) <= MAX_REQUEST:
            raise BrokerError("REQUEST_BOUND")
        value = record(parse(request))
        if (
            set(value) != {"action", "intent", "original_client_id"}
            or action not in ("SUBMIT", "CANCEL", "REPLACE")
            or value.get("action") != action
            or canonical(value) != request
            or (
                action == "CANCEL"
                and (
                    value.get("intent") is not None
                    or value.get("original_client_id") != client_id
                )
            )
            or (
                action != "CANCEL"
                and record(value.get("intent")).get("client_order_id") != client_id
            )
        ):
            raise BrokerError("JOURNAL_ACTION_BINDING")
        authorization.validate(config, request, datetime.now(UTC))
        auth = canonical(asdict(authorization))
        fingerprint = self._fingerprint(request, auth)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owner(db, config, create=True)
            old = db.execute(
                "SELECT * FROM actions WHERE provider=? AND account_id=? AND action_id=?",
                (config.provider, config.account_id, authorization.authorization_id),
            ).fetchone()
            if old:
                if (
                    old["fingerprint"] != fingerprint
                    or old["action"] != action
                    or old["client_id"] != client_id
                ):
                    raise BrokerError("CONFLICTING_ACTION_ID")
                return False, self._load(db, config, authorization.authorization_id)
            if db.execute("SELECT count(*) FROM actions").fetchone()[0] >= 2000:
                raise BrokerError("JOURNAL_ACTION_LIMIT")
            try:
                db.execute(
                    "INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)",
                    (
                        config.provider,
                        config.account_id,
                        authorization.authorization_id,
                        action,
                        client_id,
                        request,
                        auth,
                        fingerprint,
                    ),
                )
            except sqlite3.IntegrityError:
                raise BrokerError("CLIENT_ORDER_ID_ALREADY_RESERVED") from None
            state = Submission(
                authorization.authorization_id,
                action,
                client_id,
                "UNKNOWN",
                "WIRE_ATTEMPT_RESERVED",
                None,
                1,
            )
            receipt_hash = self._append(db, config, state, fingerprint)
            db.execute(
                "INSERT INTO heads VALUES(?,?,?,?,?)",
                (config.provider, config.account_id, state.action_id, 1, receipt_hash),
            )
            return True, state

    @staticmethod
    def _append(
        db: sqlite3.Connection, config: BrokerConfig, state: Submission, previous: str
    ) -> str:
        hashed = digest(previous.encode() + canonical(asdict(state)))
        db.execute(
            "INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?,?)",
            (
                config.provider,
                config.account_id,
                state.action_id,
                state.revision,
                state.state,
                state.reason,
                state.broker_order_id,
                previous,
                hashed,
            ),
        )
        return hashed

    def _load(
        self, db: sqlite3.Connection, config: BrokerConfig, action_id: str
    ) -> Submission:
        self._owner(db, config)
        action = db.execute(
            "SELECT * FROM actions WHERE provider=? AND account_id=? AND action_id=?",
            (config.provider, config.account_id, action_id),
        ).fetchone()
        if action is None:
            raise BrokerError("ACTION_NOT_FOUND")
        if not isinstance(action["request"], bytes) or not isinstance(
            action["authorization"], bytes
        ):
            raise BrokerError("JOURNAL_INTEGRITY")
        if (
            not 0 < len(action["request"]) <= MAX_REQUEST
            or not 0 < len(action["authorization"]) <= MAX_REQUEST
        ):
            raise BrokerError("JOURNAL_INTEGRITY")
        previous = self._fingerprint(
            bytes(action["request"]), bytes(action["authorization"])
        )
        if previous != action["fingerprint"]:
            raise BrokerError("JOURNAL_INTEGRITY")
        latest: Submission | None = None
        for row in db.execute(
            "SELECT * FROM receipts WHERE provider=? AND account_id=? AND action_id=? ORDER BY revision",
            (config.provider, config.account_id, action_id),
        ):
            state = Submission(
                action_id,
                action["action"],
                action["client_id"],
                row["state"],
                row["reason"],
                row["broker_id"],
                row["revision"],
            )
            expected_revision = latest.revision + 1 if latest else 1
            if (
                state.revision != expected_revision
                or row["previous_hash"] != previous
                or row["receipt_hash"]
                != digest(previous.encode() + canonical(asdict(state)))
            ):
                raise BrokerError("JOURNAL_INTEGRITY")
            previous, latest = row["receipt_hash"], state
        head = db.execute(
            "SELECT * FROM heads WHERE provider=? AND account_id=? AND action_id=?",
            (config.provider, config.account_id, action_id),
        ).fetchone()
        if (
            latest is None
            or head is None
            or head["revision"] != latest.revision
            or head["receipt_hash"] != previous
        ):
            raise BrokerError("JOURNAL_INTEGRITY")
        return latest

    def load(self, config: BrokerConfig, action_id: str) -> Submission:
        identifier(action_id)
        with self._connect() as db:
            db.execute("BEGIN")
            return self._load(db, config, action_id)

    def finish(
        self,
        config: BrokerConfig,
        action_id: str,
        state: str,
        reason: str,
        broker_id: str | None = None,
    ) -> Submission:
        identifier(action_id)
        if state not in ("UNKNOWN", "ACKNOWLEDGED", "REJECTED", "RECONCILED"):
            raise BrokerError("INVALID_SUBMISSION_STATE")
        identifier(reason)
        if broker_id is not None:
            identifier(broker_id)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._load(db, config, action_id)
            if old.revision >= 32:
                raise BrokerError("RECONCILIATION_LIMIT")
            if old.state in {"REJECTED", "RECONCILED"} and state != old.state:
                raise BrokerError("TERMINAL_ACTION_STATE")
            result = Submission(
                action_id,
                old.action,
                old.client_order_id,
                state,
                reason,
                broker_id,
                old.revision + 1,
            )
            previous = db.execute(
                "SELECT receipt_hash FROM heads WHERE provider=? AND account_id=? AND action_id=?",
                (config.provider, config.account_id, action_id),
            ).fetchone()[0]
            hashed = self._append(db, config, result, previous)
            db.execute(
                "UPDATE heads SET revision=?,receipt_hash=? WHERE provider=? AND account_id=? AND action_id=?",
                (
                    result.revision,
                    hashed,
                    config.provider,
                    config.account_id,
                    action_id,
                ),
            )
            return result

    def request(self, config: BrokerConfig, action_id: str) -> dict[str, object]:
        identifier(action_id)
        with self._connect() as db:
            db.execute("BEGIN")
            self._load(db, config, action_id)
            raw = db.execute(
                "SELECT request FROM actions WHERE provider=? AND account_id=? AND action_id=?",
                (config.provider, config.account_id, action_id),
            ).fetchone()[0]
            return record(parse(raw))
