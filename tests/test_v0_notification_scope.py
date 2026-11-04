"""Purpose migration preserves legacy ciphertexts; fixtures contain no real keys."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from quant_hunter.credentials import CredentialVault, VaultError
from quant_hunter.credentials.vault import NOTIFICATIONS_ONLY, PURPOSE

SECRET = b"synthetic-notification-profile-no-real-credential"


def test_scope_less_legacy_upgrade_preserves_ciphertext_and_key_bytes(
    tmp_path: Path,
) -> None:
    private, application = tmp_path / "private", tmp_path / "application"
    legacy = CredentialVault(private, application)
    legacy.set_secret("alpaca", "paper", "key", SECRET)
    keys = {p.name: p.read_bytes() for p in legacy.keys.iterdir()}
    with closing(sqlite3.connect(legacy.database)) as db, db:
        before = db.execute("SELECT * FROM credential_versions").fetchall()
        history = db.execute("SELECT * FROM credential_events").fetchall()
        db.execute("DROP TABLE vault_scope")
    reopened = CredentialVault(private, application)
    assert reopened.with_secret("alpaca", "paper", "key", lambda value: value == SECRET)
    assert keys == {p.name: p.read_bytes() for p in reopened.keys.iterdir()}
    with closing(sqlite3.connect(legacy.database)) as db:
        assert before == db.execute("SELECT * FROM credential_versions").fetchall()
        assert history == db.execute("SELECT * FROM credential_events").fetchall()
        assert db.execute("SELECT purpose FROM vault_scope").fetchone() == (PURPOSE,)
    with pytest.raises(VaultError, match="PURPOSE_MISMATCH"):
        CredentialVault(private, application, purpose=NOTIFICATIONS_ONLY)


@pytest.mark.parametrize("populated", [False, True])
def test_legacy_scope_cannot_be_relabelled_on_first_upgrade(
    tmp_path: Path, populated: bool
) -> None:
    storage = CredentialVault(tmp_path / "private", tmp_path / "app")
    if populated:
        storage.set_secret("alpaca", "paper", "key", SECRET)
    with closing(sqlite3.connect(storage.database)) as db, db:
        db.execute("DROP TABLE vault_scope")
    with pytest.raises(VaultError, match="PURPOSE_MISMATCH"):
        CredentialVault(
            storage.private_root, storage.application_root, purpose=NOTIFICATIONS_ONLY
        )
    assert (
        CredentialVault(storage.private_root, storage.application_root).purpose
        == PURPOSE
    )


def test_notification_namespace_requires_explicit_write_purpose_and_binds_rotation(
    tmp_path: Path,
) -> None:
    storage = CredentialVault(
        tmp_path / "private", tmp_path / "app", purpose=NOTIFICATIONS_ONLY
    )
    with pytest.raises(VaultError, match="SCOPE_FORBIDDEN"):
        storage.set_secret("TELEGRAM", "owner", "profile", SECRET)
    metadata = storage.set_secret(
        "TELEGRAM", "owner", "profile", SECRET, purpose=NOTIFICATIONS_ONLY
    )
    assert metadata["purpose"] == NOTIFICATIONS_ONLY
    assert SECRET not in storage.database.read_bytes()
    storage.rotate_master()
    reopened = CredentialVault(
        storage.private_root, storage.application_root, purpose=NOTIFICATIONS_ONLY
    )
    assert reopened.with_secret(
        "TELEGRAM", "owner", "profile", lambda value: value == SECRET
    )
    with pytest.raises(VaultError, match="PURPOSE_MISMATCH"):
        CredentialVault(storage.private_root, storage.application_root)
    reopened.revoke("TELEGRAM", "owner", "profile")
    with pytest.raises(VaultError, match="NOT_CONFIGURED"):
        reopened.with_secret("TELEGRAM", "owner", "profile", lambda value: None)


def test_scope_tamper_is_refused_before_secret_use_or_rotation(tmp_path: Path) -> None:
    storage = CredentialVault(
        tmp_path / "private", tmp_path / "app", purpose=NOTIFICATIONS_ONLY
    )
    storage.set_secret(
        "TELEGRAM", "owner", "profile", SECRET, purpose=NOTIFICATIONS_ONLY
    )
    with closing(sqlite3.connect(storage.database)) as db, db:
        db.execute("UPDATE vault_scope SET purpose=?", (PURPOSE,))
    for action in (storage.list_masked, storage.rotate_master):
        with pytest.raises(VaultError, match="PURPOSE_MISMATCH"):
            action()
    # Even changing in-memory expected scope cannot decrypt a differently bound envelope.
    storage.purpose = PURPOSE
    with closing(sqlite3.connect(storage.database)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM credential_versions").fetchone()
        meta = db.execute("SELECT * FROM vault_meta").fetchone()
        with pytest.raises(VaultError, match="INTEGRITY"):
            storage._decrypt(meta, row)


@pytest.mark.parametrize("purpose", ["LIVE", "notification", "", "READ_ONLY"])
def test_unknown_scope_is_refused_without_creating_private_files(
    tmp_path: Path, purpose: str
) -> None:
    private = tmp_path / "private"
    with pytest.raises(VaultError, match="SCOPE_FORBIDDEN"):
        CredentialVault(private, tmp_path / "app", purpose=purpose)
    assert not private.exists()
