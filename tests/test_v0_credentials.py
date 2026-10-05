"""Synthetic-only secret storage, tamper, concurrency and crash recovery proofs."""

from __future__ import annotations

import base64
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import cast

import pytest

from quant_hunter.credentials import CredentialVault, VaultError, protection
from quant_hunter.credentials import vault as vault_module
from quant_hunter.credentials.vault import MAX_SECRET_BYTES, PURPOSE

SECRET = b"synthetic-test-value-NOT-A-REAL-KEY-938485"
OTHER = b"second-synthetic-test-value-748284"


def vault(tmp_path: Path) -> CredentialVault:
    return CredentialVault(tmp_path / "private", tmp_path / "application")


def persisted(storage: CredentialVault) -> bytes:
    return b"".join(
        path.read_bytes() for path in storage.private_root.rglob("*") if path.is_file()
    )


def sql(
    storage: CredentialVault, statement: str, arguments: tuple[object, ...] = ()
) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(storage.database)) as db, db:
        return cast(
            list[tuple[object, ...]], db.execute(statement, arguments).fetchall()
        )


def test_set_mask_use_restart_and_no_plaintext_persistence(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    storage = vault(tmp_path)
    result = storage.set_secret("alpaca", "paper", "api_key", SECRET)
    assert result["masked"] == "********"
    assert result["purpose"] == PURPOSE
    assert result["externally_validated"] is False
    assert storage.list_masked() == [result]
    assert storage.with_secret(
        "alpaca", "paper", "api_key", lambda value: {"matches": value == SECRET}
    ) == {"matches": True}
    assert vault(tmp_path).with_secret(
        "alpaca", "paper", "api_key", lambda value: value == SECRET
    )
    assert SECRET not in persisted(storage)
    assert base64.b64encode(SECRET) not in persisted(storage)
    assert (
        SECRET.decode()
        not in repr(storage) + repr(result) + caplog.text + capsys.readouterr().out
    )
    assert not storage.application_root.exists()


def test_versions_revocation_and_reconfiguration_are_explicit(tmp_path: Path) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    assert storage.set_secret("alpaca", "paper", "api_key", OTHER)["revision"] == 2
    assert len(sql(storage, "SELECT * FROM credential_versions")) == 2
    revoked = storage.revoke("alpaca", "paper", "api_key")
    assert revoked["state"] == "REVOKED" and revoked["masked"] is None
    with pytest.raises(VaultError, match="NOT_CONFIGURED"):
        storage.with_secret("alpaca", "paper", "api_key", lambda value: value == OTHER)
    assert storage.set_secret("alpaca", "paper", "api_key", SECRET)["revision"] == 3
    assert vault(tmp_path).with_secret(
        "alpaca", "paper", "api_key", lambda value: value == SECRET
    )
    assert [
        row[0]
        for row in sql(
            storage, "SELECT action FROM credential_events ORDER BY sequence"
        )
    ] == ["SET", "SET", "REVOKE", "SET"]


def test_master_rotation_retains_keys_and_reencrypts_every_version(
    tmp_path: Path,
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    storage.set_secret("alpaca", "paper", "api_key", OTHER)
    storage.set_secret("fred", "research", "api_key", SECRET)
    storage.revoke("fred", "research", "api_key")
    old_keys = {path.name: path.read_bytes() for path in storage.keys.iterdir()}
    previous = sql(
        storage,
        "SELECT ciphertext FROM credential_versions ORDER BY provider,account,slot,revision",
    )
    result = storage.rotate_master()
    assert result["versions_rotated"] == 3 and result["old_keys_retained"] is True
    assert len(list(storage.keys.iterdir())) == len(old_keys) + 1
    assert all(
        (storage.keys / name).read_bytes() == data for name, data in old_keys.items()
    )
    assert previous != sql(
        storage,
        "SELECT ciphertext FROM credential_versions ORDER BY provider,account,slot,revision",
    )
    assert sql(storage, "SELECT DISTINCT key_id FROM credential_versions") == [
        (result["key_id"],)
    ]
    assert vault(tmp_path).with_secret(
        "alpaca", "paper", "api_key", lambda value: value == OTHER
    )
    with pytest.raises(VaultError, match="NOT_CONFIGURED"):
        storage.with_secret("fred", "research", "api_key", lambda value: True)


def test_batch_credentials_and_consumer_errors_never_echo_secret(
    tmp_path: Path,
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    storage.set_secret("alpaca", "paper", "api_secret", OTHER)
    assert storage.with_secrets(
        "alpaca",
        "paper",
        ["api_key", "api_secret"],
        lambda values: {
            "ok": values["api_key"] == SECRET and values["api_secret"] == OTHER
        },
    ) == {"ok": True}

    def broken(value: bytes) -> None:
        raise RuntimeError(value.decode())

    with pytest.raises(VaultError, match="CONSUMER_FAILED") as caught:
        storage.with_secret("alpaca", "paper", "api_key", broken)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert SECRET.decode() not in "".join(traceback.format_exception(caught.value))
    assert storage.with_secret(
        "alpaca", "paper", "api_key", lambda value: value == SECRET
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "../source"),
        ("account", "paper/live"),
        ("slot", "token=secret"),
        ("provider", "https://source.invalid"),
        ("account", "production"),
        ("slot", "live-token"),
        ("slot", ""),
    ],
)
def test_unsafe_or_live_slot_identity_rejected(
    tmp_path: Path, field: str, value: str
) -> None:
    storage = vault(tmp_path)
    args = {"provider": "alpaca", "account": "paper", "slot": "api_key"}
    args[field] = value
    with pytest.raises(VaultError):
        storage.set_secret(**args, secret=SECRET)
    assert storage.list_masked() == []


@pytest.mark.parametrize(
    "secret",
    [b"", b"x" * (MAX_SECRET_BYTES + 1), "plaintext", None],
    ids=["empty", "size", "text", "none"],
)
def test_secret_input_and_purpose_are_bounded(tmp_path: Path, secret: object) -> None:
    storage = vault(tmp_path)
    with pytest.raises(VaultError, match="SIZE_OR_TYPE"):
        storage.set_secret("alpaca", "paper", "api_key", cast(bytes, secret))
    with pytest.raises(VaultError, match="LIVE"):
        storage.set_secret("alpaca", "paper", "api_key", SECRET, purpose="LIVE")
    assert SECRET not in persisted(storage)


@pytest.mark.parametrize(
    "slots", [[], ["api_key", "api_key"], [f"slot{i}" for i in range(17)]]
)
def test_internal_batch_requires_distinct_bounded_slots(
    tmp_path: Path, slots: list[str]
) -> None:
    with pytest.raises(VaultError, match="INVALID_SLOT_BATCH"):
        vault(tmp_path).with_secrets("alpaca", "paper", slots, lambda value: None)


def test_missing_slot_does_not_call_consumer(tmp_path: Path) -> None:
    storage = vault(tmp_path)
    called: list[object] = []
    with pytest.raises(VaultError, match="NOT_CONFIGURED"):
        storage.with_secret("alpaca", "paper", "api_key", called.append)
    with pytest.raises(VaultError, match="NOT_CONFIGURED"):
        storage.revoke("alpaca", "paper", "api_key")
    assert called == []


@pytest.mark.parametrize("kind", ["tamper", "swap", "revision"])
def test_ciphertext_integrity_binds_slot_and_revision(
    tmp_path: Path, kind: str
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    storage.set_secret("alpaca", "paper", "api_key", OTHER)
    storage.set_secret("alpaca", "paper", "api_secret", SECRET)
    replacement: object
    if kind == "tamper":
        replacement = b"invalid-token"
    elif kind == "swap":
        replacement = sql(
            storage,
            "SELECT ciphertext FROM credential_versions WHERE slot='api_secret'",
        )[0][0]
    else:
        replacement = sql(
            storage,
            "SELECT ciphertext FROM credential_versions WHERE slot='api_key' AND revision=1",
        )[0][0]
    sql(
        storage,
        "UPDATE credential_versions SET ciphertext=? WHERE slot='api_key' AND revision=2",
        (replacement,),
    )
    with pytest.raises(VaultError, match="INTEGRITY"):
        storage.with_secret("alpaca", "paper", "api_key", lambda value: None)


@pytest.mark.parametrize("kind", ["missing", "corrupt", "foreign"])
def test_master_key_never_silently_replaced(tmp_path: Path, kind: str) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    key = next(storage.keys.iterdir())
    if kind == "missing":
        key.unlink()
    elif kind == "corrupt":
        key.write_bytes(b"corrupt-protected-key")
    else:
        other = vault(tmp_path / "other")
        key.write_bytes(next(other.keys.iterdir()).read_bytes())
    before = {path.name for path in storage.keys.iterdir()}
    with pytest.raises((VaultError, OSError)):
        vault(tmp_path)
    assert {path.name for path in storage.keys.iterdir()} == before


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE vault_meta SET schema_version=99",
        "UPDATE vault_meta SET protection='UNKNOWN'",
        "UPDATE vault_meta SET active_key='../key'",
        "DELETE FROM vault_meta",
    ],
)
def test_metadata_loss_or_future_schema_cannot_reinitialize_existing_secrets(
    tmp_path: Path, statement: str
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    before = {path.name for path in storage.keys.iterdir()}
    sql(storage, statement)
    with pytest.raises(VaultError):
        vault(tmp_path)
    assert {path.name for path in storage.keys.iterdir()} == before


def test_rotation_failure_rolls_back_ciphertexts_and_retains_orphan_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    storage.set_secret("alpaca", "paper", "api_secret", OTHER)
    before = sql(storage, "SELECT * FROM credential_versions ORDER BY slot")
    original = storage._encrypt
    attempts = 0

    def failing_encrypt(
        meta: sqlite3.Row,
        row: sqlite3.Row | dict[str, object],
        key_id: str,
        value: bytes,
    ) -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise OSError("synthetic interruption")
        return original(meta, row, key_id, value)

    monkeypatch.setattr(storage, "_encrypt", failing_encrypt)
    with pytest.raises(OSError, match="interruption"):
        storage.rotate_master()
    assert sql(storage, "SELECT * FROM credential_versions ORDER BY slot") == before
    assert len(list(storage.keys.iterdir())) == 2
    assert vault(tmp_path).with_secret(
        "alpaca", "paper", "api_key", lambda value: value == SECRET
    )


def test_parallel_writers_allocate_exact_monotonic_revisions(tmp_path: Path) -> None:
    storage = vault(tmp_path)

    def write(index: int) -> int:
        return cast(
            int,
            vault(tmp_path).set_secret(
                "alpaca", "paper", "api_key", f"synthetic-{index}".encode()
            )["revision"],
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        revisions = sorted(pool.map(write, range(12)))
    assert revisions == list(range(1, 13))
    assert sql(storage, "SELECT COUNT(*) FROM credential_versions") == [(12,)]


def run_child(
    storage: CredentialVault, source: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed test interpreter/code, no shell or external requests
        [
            sys.executable,
            "-c",
            source,
            str(storage.private_root),
            str(storage.application_root),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_process_death_midrotation_recovers_previous_complete_generation(
    tmp_path: Path,
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    storage.set_secret("alpaca", "paper", "api_secret", OTHER)
    before = sql(storage, "SELECT * FROM credential_versions ORDER BY slot")
    result = run_child(
        storage,
        """
import os, sys
from pathlib import Path
from quant_hunter.credentials import CredentialVault
vault=CredentialVault(Path(sys.argv[1]),Path(sys.argv[2]))
original=vault._encrypt
attempts=0
def interrupted(*args):
    global attempts
    attempts+=1
    if attempts==2: os._exit(83)
    return original(*args)
vault._encrypt=interrupted
vault.rotate_master()
""",
    )
    assert result.returncode == 83, result.stderr
    reopened = vault(tmp_path)
    assert sql(reopened, "SELECT * FROM credential_versions ORDER BY slot") == before
    assert len(list(reopened.keys.iterdir())) == 2
    assert reopened.with_secrets(
        "alpaca",
        "paper",
        ["api_key", "api_secret"],
        lambda values: values["api_key"] == SECRET and values["api_secret"] == OTHER,
    )


def test_separate_process_updates_are_persisted_and_locked(tmp_path: Path) -> None:
    storage = vault(tmp_path)
    source = """
import sys
from pathlib import Path
from quant_hunter.credentials import CredentialVault
vault=CredentialVault(Path(sys.argv[1]),Path(sys.argv[2]))
for index in range(3): vault.set_secret('alpaca','paper','api_key',b'synthetic-child-only')
"""
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run_child(storage, source), range(2)))
    assert all(result.returncode == 0 for result in results), [
        result.stderr for result in results
    ]
    assert sql(
        storage, "SELECT revision FROM credential_versions ORDER BY revision"
    ) == [(number,) for number in range(1, 7)]


def test_competing_commit_can_remove_optional_journal_during_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    journal = storage.database.with_name(storage.database.name + "-journal")
    journal.write_bytes(b"")
    original = protection.permissions
    removed = False

    def concurrent_commit(path: Path, *, directory: bool) -> None:
        nonlocal removed
        if path == journal and not removed:
            journal.unlink()
            removed = True
        original(path, directory=directory)

    monkeypatch.setattr(protection, "permissions", concurrent_commit)
    assert storage.with_secret("alpaca", "paper", "api_key", lambda x: x == SECRET)
    assert removed
    storage.set_secret("alpaca", "paper", "api_key", OTHER)
    assert vault(tmp_path).with_secret(
        "alpaca", "paper", "api_key", lambda x: x == OTHER
    )


def test_existing_sidecar_cannot_hide_behind_missing_file_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = vault(tmp_path)
    journal = storage.database.with_name(storage.database.name + "-journal")
    journal.write_bytes(b"retained-invalid-sidecar")
    original = protection.permissions

    def cannot_inspect(path: Path, *, directory: bool) -> None:
        if path == journal:
            raise FileNotFoundError("simulated path race while sidecar remains")
        original(path, directory=directory)

    monkeypatch.setattr(protection, "permissions", cannot_inspect)
    with pytest.raises(FileNotFoundError, match="simulated path race"):
        storage.list_masked()
    assert journal.read_bytes() == b"retained-invalid-sidecar"


def test_recreated_optional_journal_is_revalidated_before_database_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    journal = storage.database.with_name(storage.database.name + "-journal")
    original = protection.permissions
    checks = 0

    def recreated(path: Path, *, directory: bool) -> None:
        nonlocal checks
        if path == journal:
            checks += 1
            if checks == 1:
                # The first writer's missing lstat has completed, while a new
                # writer already created the next private journal at this name.
                protection.publish_private(journal, b"")
                raise FileNotFoundError("journal disappeared before replacement")
        original(path, directory=directory)

    monkeypatch.setattr(protection, "permissions", recreated)
    assert storage.list_masked()[0]["revision"] == 1
    assert checks >= 2
    assert storage.with_secret(
        "alpaca", "paper", "api_key", lambda value: value == SECRET
    )


def test_recreated_optional_journal_does_not_skip_type_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = vault(tmp_path)
    journal = storage.database.with_name(storage.database.name + "-journal")
    original = protection.permissions
    checks = 0

    def replaced(path: Path, *, directory: bool) -> None:
        nonlocal checks
        if path == journal:
            checks += 1
            if checks == 1:
                journal.mkdir()
                raise FileNotFoundError("unsafe replacement after disappearing file")
        original(path, directory=directory)

    monkeypatch.setattr(protection, "permissions", replaced)
    with pytest.raises(VaultError, match="PRIVATE_PATH_TYPE"):
        storage.list_masked()
    assert checks == 2
    assert journal.is_dir()


def test_invalid_sidecar_type_still_fails_before_database_access(
    tmp_path: Path,
) -> None:
    storage = vault(tmp_path)
    journal = storage.database.with_name(storage.database.name + "-journal")
    journal.mkdir()
    with pytest.raises(VaultError, match="PRIVATE_PATH_TYPE"):
        storage.list_masked()
    assert journal.is_dir()


def test_private_root_cannot_overlap_runtime_or_traverse(tmp_path: Path) -> None:
    for private, application in [
        (tmp_path / "app" / "keys", tmp_path / "app"),
        (tmp_path / "app", tmp_path / "app" / "runtime"),
        (tmp_path / "app", tmp_path / "app"),
        (Path("relative"), tmp_path / "app"),
        (tmp_path / ".." / "private", tmp_path / "app"),
    ]:
        with pytest.raises(VaultError):
            CredentialVault(private, application)


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows DPAPI execution")
def test_real_current_user_dpapi_roundtrip_and_tamper() -> None:
    encrypted = protection.windows_protect(SECRET)
    assert SECRET not in encrypted
    assert protection.windows_protect(encrypted, decrypt=True) == SECRET
    with pytest.raises(VaultError, match="DPAPI_FAILED"):
        protection.windows_protect(b"not-a-dpapi-blob", decrypt=True)


def test_platform_selection_and_dpapi_bounds_are_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(protection, "_platform", lambda: "win32")
    for payload in (b"", b"x" * 65537):
        with pytest.raises(VaultError, match="SIZE"):
            protection.windows_protect(payload)
    monkeypatch.setattr(protection, "_platform", lambda: "linux")
    assert protection.scheme() == "POSIX_PRIVATE_FILE_V1"
    with pytest.raises(VaultError, match="UNAVAILABLE"):
        protection.windows_protect(SECRET)
    monkeypatch.setattr(protection, "_platform", lambda: "unknown")
    with pytest.raises(VaultError, match="UNSUPPORTED"):
        protection.scheme()


def test_linux_private_modes_are_checked_without_chmod_existing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "private-file"
    path.write_bytes(b"synthetic")
    original = Path.lstat
    mode, owner, links = 0o600, 41, 1

    def mocked(path_arg: Path) -> object:
        if path_arg == path:
            return SimpleNamespace(
                st_mode=stat.S_IFREG | mode, st_uid=owner, st_nlink=links
            )
        return original(path_arg)

    monkeypatch.setattr(Path, "lstat", mocked)
    monkeypatch.setattr(protection, "_platform", lambda: "linux")
    monkeypatch.setattr(os, "getuid", lambda: 41, raising=False)
    protection.permissions(path, directory=False)
    for policy in ((0o644, 41, 1), (0o600, 42, 1), (0o600, 41, 2)):
        mode, owner, links = policy
        with pytest.raises(VaultError):
            protection.permissions(path, directory=False)
    assert path.read_bytes() == b"synthetic"


def test_reparse_paths_and_key_size_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = vault(tmp_path)
    key = next(storage.keys.iterdir())
    original = Path.lstat

    def linked(path: Path) -> object:
        if path == storage.keys:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path)

    with monkeypatch.context() as context:
        context.setattr(Path, "lstat", linked)
        with pytest.raises(VaultError, match="LINK"):
            storage.list_masked()
    key.write_bytes(b"x" * 65537)
    with pytest.raises(VaultError, match="FILE_SIZE"):
        storage.list_masked()


@pytest.mark.skipif(sys.platform != "linux", reason="Actual POSIX file modes")
def test_actual_linux_files_are_private(tmp_path: Path) -> None:
    storage = vault(tmp_path)
    storage.set_secret("fred", "research", "api_key", SECRET)
    assert stat.S_IMODE(storage.private_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(storage.keys.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in storage.private_root.rglob("*")
        if path.is_file()
    )


def test_competing_revoke_waits_for_admitted_consumer(tmp_path: Path) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    entered, release, attempted, revoked = Event(), Event(), Event(), Event()

    def consume(value: bytes) -> bool:
        entered.set()
        assert release.wait(5)
        return value == SECRET

    def revoke() -> None:
        attempted.set()
        vault(tmp_path).revoke("alpaca", "paper", "api_key")
        revoked.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        use = pool.submit(storage.with_secret, "alpaca", "paper", "api_key", consume)
        assert entered.wait(5)
        mutation = pool.submit(revoke)
        try:
            assert attempted.wait(5)
            assert not revoked.wait(0.1)
        finally:
            release.set()
        assert use.result(timeout=5)
        mutation.result(timeout=5)
    assert revoked.is_set()
    with pytest.raises(VaultError, match="NOT_CONFIGURED"):
        storage.with_secret("alpaca", "paper", "api_key", lambda value: None)


@pytest.mark.parametrize(
    "limit,operation",
    [("MAX_VERSIONS", "set"), ("MAX_KEY_FILES", "rotate"), ("MAX_EVENTS", "revoke")],
)
def test_history_admission_stops_without_deleting_or_mutating_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str, operation: str
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    before = sql(storage, "SELECT * FROM credential_versions")
    monkeypatch.setattr(vault_module, limit, 1)
    with pytest.raises(VaultError, match="LIMIT"):
        if operation == "set":
            storage.set_secret("alpaca", "paper", "api_key", OTHER)
        elif operation == "rotate":
            storage.rotate_master()
        else:
            storage.revoke("alpaca", "paper", "api_key")
    assert sql(storage, "SELECT * FROM credential_versions") == before
    assert len(list(storage.keys.iterdir())) == 1
    assert storage.with_secret(
        "alpaca", "paper", "api_key", lambda value: value == SECRET
    )


def test_async_consumers_are_rejected_without_unawaited_coroutines(
    tmp_path: Path,
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)

    async def async_consumer(value: bytes) -> bool:
        return value == SECRET

    with pytest.raises(VaultError, match="CONSUMER_FAILED"):
        _ = storage.with_secret("alpaca", "paper", "api_key", async_consumer)


def test_separate_owner_recovery_copy_keeps_same_vault_identity(tmp_path: Path) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    storage.rotate_master()
    recovered_path = tmp_path / "owner-private-recovery"
    shutil.copytree(storage.private_root, recovered_path)
    recovered = CredentialVault(recovered_path, tmp_path / "restored-application")
    assert recovered.list_masked() == storage.list_masked()
    assert recovered.with_secret(
        "alpaca", "paper", "api_key", lambda value: value == SECRET
    )
    assert {path.name for path in recovered.keys.iterdir()} == {
        path.name for path in storage.keys.iterdir()
    }


@pytest.mark.parametrize("payload", [b"not-json-synthetic-sensitive-text", b"[]"])
def test_invalid_authenticated_envelopes_do_not_retain_secret_exception_context(
    tmp_path: Path, payload: bytes
) -> None:
    storage = vault(tmp_path)
    storage.set_secret("alpaca", "paper", "api_key", SECRET)
    vault_id, key_id = sql(storage, "SELECT vault_id,active_key FROM vault_meta")[0]
    token = storage._fernet(cast(str, vault_id), cast(str, key_id)).encrypt(payload)
    sql(storage, "UPDATE credential_versions SET ciphertext=?", (token,))
    with pytest.raises(VaultError, match="INTEGRITY") as caught:
        storage.with_secret("alpaca", "paper", "api_key", lambda value: None)
    assert caught.value.__context__ is None
    assert payload.decode() not in "".join(traceback.format_exception(caught.value))
