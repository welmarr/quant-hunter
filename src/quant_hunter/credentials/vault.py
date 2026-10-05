"""Encrypted credential versions with SQLite-serialized use and key rotation."""

from __future__ import annotations

import base64
import hashlib
import inspect
import os
import re
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar, cast

from cryptography.fernet import Fernet, InvalidToken

from quant_hunter.config import JsonRecord, canonicalize_json, parse_json_document
from quant_hunter.credentials import protection
from quant_hunter.credentials.errors import VaultError

T = TypeVar("T")
PURPOSE = "PAPER_OR_READ_ONLY"
MAX_SECRET_BYTES = 8192
MAX_VERSIONS = 10_000
MAX_KEY_FILES = 256
MAX_EVENTS = 50_000
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_KEY_ID = re.compile(r"[0-9a-f]{32}")
_FORMAT = "qh-credential-envelope-1"


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _identifier(value: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise VaultError("INVALID_SLOT_IDENTITY")
    if {"live", "production"} & set(re.split("[_-]", value.lower())):
        raise VaultError("LIVE_CREDENTIAL_SCOPE_FORBIDDEN")
    return value


def _record(content: bytes) -> JsonRecord:
    invalid = False
    try:
        value = parse_json_document(content)
    except ValueError, UnicodeError:
        invalid = True
        value = None
    if invalid or not isinstance(value, dict):
        raise VaultError("CREDENTIAL_INTEGRITY")
    return value


class CredentialVault:
    """Privileged server-only capability; management APIs expose fixed masks only.

    The private root (ciphertexts AND key versions) must be separate from the
    application root and ordinary exports/backups. This is not HOST_ENFORCED
    research isolation and grants no network or trading authority.
    """

    def __init__(self, private_root: Path, application_root: Path) -> None:
        protection.safe_path(private_root)
        protection.safe_path(application_root)
        if private_root.is_relative_to(
            application_root
        ) or application_root.is_relative_to(private_root):
            raise VaultError("PRIVATE_ROOT_OVERLAPS_APPLICATION")
        self.private_root = private_root
        self.application_root = application_root
        self.keys = private_root / "keys"
        self.database = private_root / "vault.sqlite3"
        self.protection_scheme = protection.scheme()
        protection.private_directory(private_root)
        protection.private_directory(self.keys)
        if not self.database.exists():
            try:
                protection.publish_private(self.database, b"")
            except FileExistsError:
                pass  # A competing initializer must still pass schema checks.
        with self._transaction() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS vault_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL, vault_id TEXT NOT NULL, active_key TEXT NOT NULL, protection TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS credentials (provider TEXT NOT NULL, account TEXT NOT NULL, slot TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose='PAPER_OR_READ_ONLY'), revision INTEGER NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), updated_at TEXT NOT NULL, PRIMARY KEY(provider,account,slot))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS credential_versions (provider TEXT NOT NULL, account TEXT NOT NULL, slot TEXT NOT NULL, revision INTEGER NOT NULL, key_id TEXT NOT NULL, ciphertext BLOB NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(provider,account,slot,revision))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS credential_events (sequence INTEGER PRIMARY KEY, action TEXT NOT NULL, provider TEXT, account TEXT, slot TEXT, created_at TEXT NOT NULL)"
            )
            meta = db.execute("SELECT * FROM vault_meta WHERE singleton=1").fetchone()
            if meta is None:
                if (
                    db.execute("SELECT COUNT(*) FROM credential_versions").fetchone()[0]
                    or db.execute("SELECT COUNT(*) FROM credential_events").fetchone()[
                        0
                    ]
                ):
                    raise VaultError("VAULT_METADATA_MISSING")
                vault_id = uuid.uuid4().hex
                key_id = self._publish_key(vault_id)
                db.execute(
                    "INSERT INTO vault_meta VALUES(1,1,?,?,?)",
                    (vault_id, key_id, self.protection_scheme),
                )
            else:
                self._meta(db)

    def __repr__(self) -> str:
        return "CredentialVault(<private>, secrets=<masked>)"

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        protection.permissions(self.private_root, directory=True)
        protection.permissions(self.keys, directory=True)
        protection.permissions(self.database, directory=False)
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = self.database.with_name(self.database.name + suffix)
            try:
                protection.permissions(sidecar, directory=False)
            except FileNotFoundError:
                # SQLite DELETE journals can vanish when another admitted writer
                # commits. Only a genuinely absent optional sidecar is allowed;
                # existing unsafe paths and broken links must still fail closed.
                if os.path.lexists(sidecar):
                    raise
        db = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _meta(self, db: sqlite3.Connection) -> sqlite3.Row:
        row = db.execute("SELECT * FROM vault_meta WHERE singleton=1").fetchone()
        if (
            row is None
            or row["schema_version"] != 1
            or row["protection"] != self.protection_scheme
        ):
            raise VaultError("UNSUPPORTED_VAULT_VERSION_OR_PROTECTION")
        if _KEY_ID.fullmatch(row["vault_id"]) is None:
            raise VaultError("CREDENTIAL_INTEGRITY")
        self._fernet(row["vault_id"], row["active_key"])
        return cast(sqlite3.Row, row)

    def _publish_key(self, vault_id: str) -> str:
        if sum(1 for _path in self.keys.iterdir()) >= MAX_KEY_FILES:
            raise VaultError("KEY_RETENTION_LIMIT")
        key_id = uuid.uuid4().hex
        key = Fernet.generate_key()
        document: JsonRecord = {
            "format": "qh-credential-key-1",
            "vault_id": vault_id,
            "key_id": key_id,
            "key": key.decode("ascii"),
            "key_digest": "sha256:" + hashlib.sha256(key).hexdigest(),
        }
        plaintext = canonicalize_json(document)
        sealed = (
            protection.windows_protect(plaintext)
            if self.protection_scheme == "DPAPI_CURRENT_USER_V1"
            else plaintext
        )
        protection.publish_private(self.keys / f"{key_id}.key", sealed)
        return key_id

    def _fernet(self, vault_id: str, key_id: str) -> Fernet:
        if not isinstance(key_id, str) or _KEY_ID.fullmatch(key_id) is None:
            raise VaultError("INVALID_KEY_REFERENCE")
        sealed = protection.read_private(self.keys / f"{key_id}.key")
        plaintext = (
            protection.windows_protect(sealed, decrypt=True)
            if self.protection_scheme == "DPAPI_CURRENT_USER_V1"
            else sealed
        )
        document = _record(plaintext)
        key = document.get("key")
        if (
            set(document) != {"format", "vault_id", "key_id", "key", "key_digest"}
            or document["format"] != "qh-credential-key-1"
            or document["vault_id"] != vault_id
            or document["key_id"] != key_id
            or not isinstance(key, str)
            or len(key) != 44
            or not key.isascii()
            or document["key_digest"]
            != "sha256:" + hashlib.sha256(key.encode()).hexdigest()
        ):
            raise VaultError("KEY_INTEGRITY")
        try:
            return Fernet(key.encode("ascii"))
        except ValueError, UnicodeError:
            raise VaultError("KEY_INTEGRITY") from None

    @staticmethod
    def _binding(
        meta: sqlite3.Row, row: sqlite3.Row | dict[str, object], key_id: str
    ) -> JsonRecord:
        return {
            "format": _FORMAT,
            "vault_id": meta["vault_id"],
            "key_id": key_id,
            "provider": cast(str, row["provider"]),
            "account": cast(str, row["account"]),
            "slot": cast(str, row["slot"]),
            "purpose": PURPOSE,
            "revision": cast(int, row["revision"]),
        }

    def _decrypt(self, meta: sqlite3.Row, row: sqlite3.Row) -> bytes:
        try:
            plaintext = self._fernet(meta["vault_id"], row["key_id"]).decrypt(
                row["ciphertext"]
            )
        except InvalidToken:
            raise VaultError("CREDENTIAL_INTEGRITY") from None
        document = _record(plaintext)
        expected = self._binding(meta, row, row["key_id"])
        if (
            set(document) != {*expected, "secret"}
            or any(document.get(key) != value for key, value in expected.items())
            or not isinstance(document["secret"], str)
        ):
            raise VaultError("CREDENTIAL_INTEGRITY")
        try:
            secret = base64.b64decode(document["secret"], validate=True)
        except ValueError:
            raise VaultError("CREDENTIAL_INTEGRITY") from None
        if not 1 <= len(secret) <= MAX_SECRET_BYTES:
            raise VaultError("CREDENTIAL_INTEGRITY")
        return secret

    def _encrypt(
        self,
        meta: sqlite3.Row,
        row: sqlite3.Row | dict[str, object],
        key_id: str,
        secret: bytes,
    ) -> bytes:
        return self._fernet(meta["vault_id"], key_id).encrypt(
            canonicalize_json(
                {
                    **self._binding(meta, row, key_id),
                    "secret": base64.b64encode(secret).decode("ascii"),
                }
            )
        )

    @staticmethod
    def _masked(row: sqlite3.Row) -> JsonRecord:
        return {
            "provider": row["provider"],
            "account": row["account"],
            "slot": row["slot"],
            "purpose": row["purpose"],
            "revision": row["revision"],
            "state": "CONFIGURED" if row["enabled"] else "REVOKED",
            "masked": "********" if row["enabled"] else None,
            "updated_at": row["updated_at"],
            "externally_validated": False,
        }

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        action: str,
        provider: str | None = None,
        account: str | None = None,
        slot: str | None = None,
    ) -> None:
        if (
            db.execute("SELECT COUNT(*) FROM credential_events").fetchone()[0]
            >= MAX_EVENTS
        ):
            raise VaultError("CREDENTIAL_EVENT_LIMIT")
        db.execute(
            "INSERT INTO credential_events(action,provider,account,slot,created_at) VALUES(?,?,?,?,?)",
            (action, provider, account, slot, _stamp()),
        )

    def set_secret(
        self,
        provider: str,
        account: str,
        slot: str,
        secret: bytes,
        *,
        purpose: str = PURPOSE,
    ) -> JsonRecord:
        provider, account, slot = map(_identifier, (provider, account, slot))
        if purpose != PURPOSE:
            raise VaultError("LIVE_CREDENTIAL_SCOPE_FORBIDDEN")
        if not isinstance(secret, bytes) or not 1 <= len(secret) <= MAX_SECRET_BYTES:
            raise VaultError("INVALID_SECRET_SIZE_OR_TYPE")
        with self._transaction() as db:
            meta = self._meta(db)
            if (
                db.execute("SELECT COUNT(*) FROM credential_versions").fetchone()[0]
                >= MAX_VERSIONS
            ):
                raise VaultError("CREDENTIAL_VERSION_LIMIT")
            previous = db.execute(
                "SELECT revision FROM credentials WHERE provider=? AND account=? AND slot=?",
                (provider, account, slot),
            ).fetchone()
            revision = previous[0] + 1 if previous else 1
            values: dict[str, object] = {
                "provider": provider,
                "account": account,
                "slot": slot,
                "revision": revision,
            }
            ciphertext = self._encrypt(meta, values, meta["active_key"], secret)
            stamp = _stamp()
            db.execute(
                "INSERT INTO credential_versions VALUES(?,?,?,?,?,?,?)",
                (
                    provider,
                    account,
                    slot,
                    revision,
                    meta["active_key"],
                    ciphertext,
                    stamp,
                ),
            )
            db.execute(
                "INSERT INTO credentials VALUES(?,?,?,?,?,1,?) ON CONFLICT(provider,account,slot) DO UPDATE SET revision=excluded.revision,enabled=1,updated_at=excluded.updated_at",
                (provider, account, slot, PURPOSE, revision, stamp),
            )
            self._event(db, "SET", provider, account, slot)
            row = db.execute(
                "SELECT * FROM credentials WHERE provider=? AND account=? AND slot=?",
                (provider, account, slot),
            ).fetchone()
            return self._masked(row)

    def list_masked(self) -> list[JsonRecord]:
        with self._transaction() as db:
            self._meta(db)
            return [
                self._masked(row)
                for row in db.execute(
                    "SELECT * FROM credentials ORDER BY provider,account,slot"
                )
            ]

    def revoke(self, provider: str, account: str, slot: str) -> JsonRecord:
        provider, account, slot = map(_identifier, (provider, account, slot))
        with self._transaction() as db:
            self._meta(db)
            row = db.execute(
                "SELECT * FROM credentials WHERE provider=? AND account=? AND slot=?",
                (provider, account, slot),
            ).fetchone()
            if row is None:
                raise VaultError("CREDENTIAL_NOT_CONFIGURED")
            db.execute(
                "UPDATE credentials SET enabled=0,updated_at=? WHERE provider=? AND account=? AND slot=?",
                (_stamp(), provider, account, slot),
            )
            self._event(db, "REVOKE", provider, account, slot)
            row = db.execute(
                "SELECT * FROM credentials WHERE provider=? AND account=? AND slot=?",
                (provider, account, slot),
            ).fetchone()
            return self._masked(row)

    def with_secrets(
        self,
        provider: str,
        account: str,
        slots: Sequence[str],
        consumer: Callable[[dict[str, bytes]], T],
    ) -> T:
        """Run trusted synchronous server code under a serialized use/revoke boundary.

        Consumer results remain internal. Consumers must never echo secret values
        in their results/logs; they are capabilities, never untrusted callbacks.
        """
        provider, account = map(_identifier, (provider, account))
        names = [_identifier(name) for name in slots]
        if not 1 <= len(names) <= 16 or len(names) != len(set(names)):
            raise VaultError("INVALID_SLOT_BATCH")
        failed = False
        with self._transaction() as db:
            meta = self._meta(db)
            values: dict[str, bytes] = {}
            for slot in names:
                row = db.execute(
                    "SELECT v.* FROM credentials c JOIN credential_versions v USING(provider,account,slot,revision) WHERE c.provider=? AND c.account=? AND c.slot=? AND c.enabled=1 AND c.purpose=?",
                    (provider, account, slot, PURPOSE),
                ).fetchone()
                if row is None:
                    raise VaultError("CREDENTIAL_NOT_CONFIGURED")
                values[slot] = self._decrypt(meta, row)
            try:
                result = consumer(values)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise VaultError("ASYNC_CONSUMER_FORBIDDEN")
            except Exception:
                failed = True
            finally:
                values.clear()
            # Raise after leaving except so secret-bearing exception context is
            # not retained in the sanitized VaultError object.
            if failed:
                raise VaultError("CREDENTIAL_CONSUMER_FAILED")
            return result

    def with_secret(
        self, provider: str, account: str, slot: str, consumer: Callable[[bytes], T]
    ) -> T:
        return self.with_secrets(
            provider, account, [slot], lambda values: consumer(values[slot])
        )

    def rotate_master(self) -> JsonRecord:
        """Persist new key first, atomically re-encrypt all versions, retain old keys."""
        with self._transaction() as db:
            meta = self._meta(db)
            rows = db.execute(
                "SELECT * FROM credential_versions ORDER BY provider,account,slot,revision"
            ).fetchall()
            if len(rows) > MAX_VERSIONS:
                raise VaultError("CREDENTIAL_VERSION_LIMIT")
            key_id = self._publish_key(meta["vault_id"])
            for row in rows:
                ciphertext = self._encrypt(meta, row, key_id, self._decrypt(meta, row))
                db.execute(
                    "UPDATE credential_versions SET key_id=?,ciphertext=? WHERE provider=? AND account=? AND slot=? AND revision=?",
                    (
                        key_id,
                        ciphertext,
                        row["provider"],
                        row["account"],
                        row["slot"],
                        row["revision"],
                    ),
                )
            db.execute(
                "UPDATE vault_meta SET active_key=? WHERE singleton=1", (key_id,)
            )
            self._event(db, "ROTATE_MASTER")
            return {
                "key_id": key_id,
                "versions_rotated": len(rows),
                "old_keys_retained": True,
                "protection": self.protection_scheme,
            }
