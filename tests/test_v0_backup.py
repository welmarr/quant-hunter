"""Executed private backup recovery and hostile archive regression proofs."""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import stat
import struct
import sys
import warnings
import zipfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import IO, cast

import pytest

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.web import backup
from quant_hunter.web.lease import RuntimeLease
from quant_hunter.web.runtime import Runtime
from quant_hunter.web.state import AppState

CODE = "7346cf4f79ca5897777c0118f8cf4c2292be929e"
PASSWORD = "synthetic-backup-test-only"  # noqa: S105
REPOSITORY = Path(backup.__file__).resolve().parents[3]
ACTUAL_SPACE = backup._space
GIB = 1024**3


@pytest.fixture(autouse=True)
def bounded_test_space(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ordinary fixtures write tiny files. Test the reserve policy separately;
    # never require or consume a spare 20 GiB merely to run this suite in CI.
    monkeypatch.setattr(backup, "_space", lambda parent, required: None)


def runtime_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != "worker.lock"
    }


def initialized(root: Path) -> AppState:
    state = AppState(root / "application.sqlite3")
    objects = ImmutableObjectStore(root / "research" / "artifacts")
    objects.publish(b"\x00exact immutable source observation\xff")
    return state


def saved(tmp_path: Path) -> tuple[Path, Path, JsonRecord]:
    runtime = tmp_path / "runtime"
    initialized(runtime)
    archive = tmp_path / "private.zip"
    manifest = backup.create_backup(runtime, archive, CODE)
    return runtime, archive, manifest


def rows_for(members: list[tuple[str | zipfile.ZipInfo, bytes]]) -> list[JsonValue]:
    return [
        {
            "path": name.filename if isinstance(name, zipfile.ZipInfo) else name,
            "size": len(payload),
            "digest": sha256_bytes(payload),
        }
        for name, payload in members
    ]


def crafted(
    path: Path,
    members: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    manifest: JsonValue | None = None,
    compression: int = zipfile.ZIP_STORED,
) -> Path:
    document: JsonValue = (
        manifest
        if manifest is not None
        else {
            "format": "quant-hunter-private-backup-1",
            "files": rows_for(members),
            "code_revision": CODE,
        }
    )
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:")
        with zipfile.ZipFile(path, "w", compression=compression) as bundle:
            for name, payload in members:
                bundle.writestr(name, payload)
            bundle.writestr("manifest.json", canonicalize_json(document))
    return path


def assert_rejected(archive: Path, destination: Path, match: str | None = None) -> None:
    with pytest.raises(backup.BackupError, match=match):
        backup.restore_backup(archive, destination)
    assert not destination.exists()


def test_real_runtime_round_trip_preserves_accounts_jobs_and_immutable_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    runtime = Runtime(root, REPOSITORY, CODE)
    owner = runtime.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    reader = runtime.state.create_user("reader", PASSWORD, "reader", bootstrap=False)
    token, session = runtime.state.login("owner", PASSWORD)
    job = runtime.state.enqueue(owner, {"market": "EQUITY", "lookback": 5})
    observation = runtime.lab.objects.publish(
        b"immutable synthetic observation\x00\xff"
    )
    before = runtime_files(root)
    archive = tmp_path / "private-runtime.zip"
    manifest = backup.create_backup(root, archive, CODE)
    assert "PRIVATE" in cast(str, manifest["privacy"])
    assert "EXCLUDED" in cast(str, manifest["master_keys"])
    destination = tmp_path / "restored"
    assert backup.restore_backup(archive, destination) == manifest
    assert runtime_files(destination) == before
    assert not (destination / backup.MARKER).exists()
    restored = AppState(destination / "application.sqlite3")
    assert restored.users() == [owner, reader]
    assert restored.session(token) == session
    assert restored.job(owner, job.id) == job
    assert restored.login("owner", PASSWORD)[1].user == owner
    assert (
        ImmutableObjectStore(destination / "research" / "artifacts").read_bytes(
            observation.digest
        )
        == b"immutable synthetic observation\x00\xff"
    )
    assert runtime_files(root) == before
    with zipfile.ZipFile(archive) as bundle:
        assert all(
            entry.compress_type == zipfile.ZIP_STORED for entry in bundle.infolist()
        )
        assert "worker.lock" not in bundle.namelist()


def test_active_runtime_lease_refuses_backup_without_touching_state(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    initialized(runtime)
    original = runtime_files(runtime)
    lease = RuntimeLease(runtime)
    lease.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another process"):
            backup.create_backup(runtime, tmp_path / "blocked.zip", CODE)
        assert not (tmp_path / "blocked.zip").exists()
        assert runtime_files(runtime) == original
    finally:
        lease.release()


def test_existing_archive_and_destination_are_never_overwritten(tmp_path: Path) -> None:
    runtime, archive, _manifest = saved(tmp_path)
    archive_before = archive.read_bytes()
    with pytest.raises(backup.BackupError, match="exists"):
        backup.create_backup(runtime, archive, CODE)
    assert archive.read_bytes() == archive_before
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep.txt").write_bytes(b"existing work")
    with pytest.raises(backup.BackupError, match="already exist"):
        backup.restore_backup(archive, destination)
    assert (destination / "keep.txt").read_bytes() == b"existing work"


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "research/artifacts/../escape",
        "/absolute",
        "C:/escape",
        "research\\artifacts\\escape",
        "research//artifacts/escape",
        "research/artifacts/CON",
        "research/artifacts/COM1.txt",
        "research/artifacts/trailing.",
        "research/artifacts/a b",
        "research/artifacts/.env",
        "research/artifacts/master.key",
        "unexpected.txt",
        "",
        "research/artifacts/" + "a" * 241,
    ],
)
def test_hostile_archive_paths_never_publish_outside_destination(
    tmp_path: Path, name: str
) -> None:
    if not name:
        with pytest.raises(backup.BackupError):
            backup._relative(name)
        return
    archive = crafted(
        tmp_path / "hostile.zip",
        [("application.sqlite3", b"database"), (name, b"hostile")],
    )
    assert_rejected(archive, tmp_path / "restore")
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("entry_type", ["symlink", "directory"])
def test_link_and_directory_zip_entries_are_rejected(
    tmp_path: Path, entry_type: str
) -> None:
    entry = zipfile.ZipInfo(
        "research/artifacts/link"
        if entry_type == "symlink"
        else "research/artifacts/directory/"
    )
    entry.create_system = 3
    entry.external_attr = (
        (stat.S_IFLNK | 0o777) if entry_type == "symlink" else (stat.S_IFDIR | 0o755)
    ) << 16
    archive = crafted(
        tmp_path / "links.zip", [("application.sqlite3", b"db"), (entry, b"../outside")]
    )
    assert_rejected(archive, tmp_path / "restore", "Link/directory")


@pytest.mark.parametrize(
    "attack",
    [
        "digest",
        "size",
        "duplicate-manifest-path",
        "missing-row",
        "extra-row",
        "bad-type",
        "bad-record",
        "missing-db",
        "unknown-format",
        "list-manifest",
    ],
)
def test_manifest_is_exhaustive_and_matches_actual_bytes(
    tmp_path: Path, attack: str
) -> None:
    members: list[tuple[str | zipfile.ZipInfo, bytes]] = [
        ("application.sqlite3", b"db"),
        ("research/artifacts/item", b"observation"),
    ]
    rows = rows_for(members)
    document: JsonValue = {"format": "quant-hunter-private-backup-1", "files": rows}
    first = cast(JsonRecord, rows[0])
    if attack == "digest":
        first["digest"] = "sha256:" + "0" * 64
    elif attack == "size":
        first["size"] = 999
    elif attack == "duplicate-manifest-path":
        rows[1] = dict(first)
    elif attack == "missing-row":
        rows.pop()
    elif attack == "extra-row":
        rows.append(dict(first))
    elif attack == "bad-type":
        first["size"] = True
    elif attack == "bad-record":
        first["extra"] = "unknown"
    elif attack == "missing-db":
        members[0] = ("research/registries/dataset", b"db")
        first["path"] = "research/registries/dataset"
    elif attack == "unknown-format":
        cast(JsonRecord, document)["format"] = "other"
    else:
        document = []
    assert_rejected(
        crafted(tmp_path / "manifest.zip", members, manifest=document),
        tmp_path / "restore",
    )


def test_duplicate_zip_members_and_compression_are_rejected(tmp_path: Path) -> None:
    duplicate = crafted(
        tmp_path / "duplicate.zip",
        [("application.sqlite3", b"db"), ("application.sqlite3", b"other")],
    )
    assert_rejected(duplicate, tmp_path / "duplicate-restore", "duplicate")
    compressed = crafted(
        tmp_path / "compressed.zip",
        [("application.sqlite3", b"db")],
        compression=zipfile.ZIP_DEFLATED,
    )
    assert_rejected(compressed, tmp_path / "compressed-restore", "Compressed")


@pytest.mark.parametrize("limit", ["MAX_FILE", "MAX_TOTAL", "MAX_FILES"])
def test_create_and_restore_size_caps_apply_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    runtime, archive, _manifest = saved(tmp_path)
    monkeypatch.setattr(backup, limit, 1)
    with pytest.raises(backup.BackupError):
        backup.create_backup(runtime, tmp_path / "limited.zip", CODE)
    assert not (tmp_path / "limited.zip").exists()
    assert_rejected(archive, tmp_path / "restore")


@pytest.mark.parametrize(
    "field,value",
    [
        (1, 1),
        (2, 1),
        (3, 1),
        (4, 1),
        (4, 0),
        (4, 50002),
        (5, 17 * 1024**2),
        (6, 0),
        (7, 1),
    ],
)
def test_eocd_count_volume_and_directory_bounds(
    tmp_path: Path, field: int, value: int
) -> None:
    _runtime, archive, _manifest = saved(tmp_path)
    payload = archive.read_bytes()
    fields = list(struct.unpack("<4s4H2LH", payload[-22:]))
    fields[field] = value
    if field == 4:
        fields[3] = value
    archive.write_bytes(payload[:-22] + struct.pack("<4s4H2LH", *fields))
    assert_rejected(archive, tmp_path / "restore")


def zip64_archive(
    payload: bytes,
    changes: dict[int, int | bytes] | None = None,
    *,
    bad_locator: bool = False,
) -> bytes:
    _sig, _disk, _ddisk, count, _count, length, offset, _comment = struct.unpack(
        "<4s4H2LH", payload[-22:]
    )
    body = payload[:-22]
    values: list[int | bytes] = [
        b"PK\x06\x06",
        44,
        45,
        45,
        0,
        0,
        count,
        count,
        length,
        offset,
    ]
    for index, value in (changes or {}).items():
        values[index] = value
    record = struct.pack("<4sQ2H2L4Q", *values)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, len(body) + int(bad_locator), 1)
    tail = struct.pack(
        "<4s4H2LH", b"PK\x05\x06", 0, 0, 65535, 65535, 0xFFFFFFFF, 0xFFFFFFFF, 0
    )
    return body + record + locator + tail


def test_valid_bounded_zip64_directory_restores_exact_files(tmp_path: Path) -> None:
    runtime, archive, manifest = saved(tmp_path)
    archive.write_bytes(zip64_archive(archive.read_bytes()))
    destination = tmp_path / "restored"
    assert backup.restore_backup(archive, destination) == manifest
    assert runtime_files(runtime) == runtime_files(destination)


@pytest.mark.parametrize(
    "changes,bad_locator",
    [
        ({0: b"BAD!"}, False),
        ({1: 45}, False),
        ({3: 46}, False),
        ({4: 1}, False),
        ({6: 1}, False),
        ({6: 1, 7: 1}, False),
        ({8: 99}, False),
        ({}, True),
    ],
)
def test_zip64_metadata_cannot_bypass_counts_or_bounds(
    tmp_path: Path, changes: dict[int, int | bytes], bad_locator: bool
) -> None:
    _runtime, archive, _manifest = saved(tmp_path)
    archive.write_bytes(
        zip64_archive(archive.read_bytes(), changes, bad_locator=bad_locator)
    )
    assert_rejected(archive, tmp_path / "restore")


def test_truncated_and_too_small_zip64_archives_fail_preflight(tmp_path: Path) -> None:
    archive = tmp_path / "short.zip"
    archive.write_bytes(b"not a zip")
    assert_rejected(archive, tmp_path / "restore")
    archive.write_bytes(
        struct.pack(
            "<4s4H2LH", b"PK\x05\x06", 0, 0, 65535, 65535, 0xFFFFFFFF, 0xFFFFFFFF, 0
        )
    )
    assert_rejected(archive, tmp_path / "restore", "Incomplete ZIP64")


def test_disk_reserve_policy_is_checked_without_allocating_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _: SimpleNamespace(total=100 * GIB, free=22 * GIB),
    )
    ACTUAL_SPACE(tmp_path, GIB)
    with pytest.raises(backup.BackupError, match="reserve"):
        ACTUAL_SPACE(tmp_path, 3 * GIB)
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _: SimpleNamespace(total=1000 * GIB, free=100 * GIB),
    )
    with pytest.raises(backup.BackupError, match="reserve"):
        ACTUAL_SPACE(tmp_path, 1)


def test_failure_after_extraction_keeps_marker_and_runtime_refuses_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _runtime, archive, _manifest = saved(tmp_path)
    destination = tmp_path / "restore"

    def fail_validation(path: Path) -> None:
        raise backup.BackupError("Injected final SQLite check failure")

    monkeypatch.setattr(backup, "_sqlite", fail_validation)
    with pytest.raises(backup.BackupError, match="SQLite"):
        backup.restore_backup(archive, destination)
    assert (destination / "application.sqlite3").is_file()
    assert (destination / backup.MARKER).is_file()
    with pytest.raises(ValueError, match="restoration is incomplete"):
        Runtime(destination, REPOSITORY, CODE)
    assert (destination / backup.MARKER).is_file()
    lease = RuntimeLease(destination)
    lease.acquire()
    lease.release()


def test_second_pass_bytes_must_match_verified_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _runtime, archive, _manifest = saved(tmp_path)
    original_copy = backup._copy

    def changing_source(
        source: IO[bytes], target: IO[bytes] | None = None
    ) -> tuple[int, str]:
        if target is None:
            return original_copy(source)
        actual = bytearray(source.read())
        actual[0] ^= 1
        return original_copy(io.BytesIO(actual), target)

    monkeypatch.setattr(backup, "_copy", changing_source)
    destination = tmp_path / "restore"
    with pytest.raises(backup.BackupError, match="Restored file digest/size mismatch"):
        backup.restore_backup(archive, destination)
    assert (destination / backup.MARKER).exists()
    with pytest.raises(ValueError, match="incomplete"):
        Runtime(destination, REPOSITORY, CODE)


def test_destination_lease_collision_prevents_any_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _runtime, archive, _manifest = saved(tmp_path)
    original_acquire = RuntimeLease.acquire
    holders: list[RuntimeLease] = []

    def competing_acquire(lease: RuntimeLease) -> None:
        owner = RuntimeLease(lease.path.parent)
        original_acquire(owner)
        holders.append(owner)
        original_acquire(lease)

    monkeypatch.setattr(RuntimeLease, "acquire", competing_acquire)
    destination = tmp_path / "restore"
    try:
        with pytest.raises(RuntimeError, match="Another process"):
            backup.restore_backup(archive, destination)
        assert sorted(path.name for path in destination.iterdir()) == ["worker.lock"]
    finally:
        for holder in holders:
            holder.release()


def test_sqlite_corruption_and_unknown_migrations_refuse_backup(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    initialized(root)
    with closing(sqlite3.connect(root / "application.sqlite3")) as db, db:
        db.execute("INSERT INTO migrations VALUES (99)")
    with pytest.raises(backup.BackupError, match="migration"):
        backup.create_backup(root, tmp_path / "unknown.zip", CODE)
    (root / "application.sqlite3").write_bytes(b"corrupt database")
    with pytest.raises(backup.BackupError, match="Unreadable"):
        backup.create_backup(root, tmp_path / "corrupt.zip", CODE)


def test_path_and_runtime_preconditions_are_checked_before_writes(
    tmp_path: Path,
) -> None:
    for path in (
        Path("relative"),
        Path(tmp_path.anchor),
        tmp_path / ".." / "escape",
        Path(r"\\server\share\backup.zip"),
    ):
        with pytest.raises(backup.BackupError):
            backup._safe_path(path)
    with pytest.raises(backup.BackupError, match="initialized"):
        backup.create_backup(tmp_path / "missing", tmp_path / "missing.zip", CODE)
    runtime = tmp_path / "runtime"
    initialized(runtime)
    with pytest.raises(backup.BackupError, match="outside"):
        backup.create_backup(runtime, runtime / "inside.zip", CODE)
    with pytest.raises(backup.BackupError, match="revision"):
        backup.create_backup(runtime, tmp_path / "invalid.zip", "main")
    (runtime / backup.MARKER).write_text("incomplete")
    with pytest.raises(backup.BackupError, match="incomplete"):
        backup.create_backup(runtime, tmp_path / "incomplete.zip", CODE)


def test_runtime_secret_material_is_rejected_without_archiving(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    initialized(runtime)
    (runtime / "research" / "artifacts" / "master.key").write_bytes(b"test-only-secret")
    archive = tmp_path / "blocked.zip"
    with pytest.raises(backup.BackupError, match="Secret material"):
        backup.create_backup(runtime, archive, CODE)
    assert not archive.exists()


def test_cli_create_and_restore_emit_only_operational_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = tmp_path / "runtime"
    initialized(runtime)
    archive = tmp_path / "cli.zip"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup",
            "create",
            "--runtime",
            str(runtime),
            "--archive",
            str(archive),
            "--code-revision",
            CODE,
        ],
    )
    backup.main()
    created = json.loads(capsys.readouterr().out)
    assert created == {
        "status": "VERIFIED",
        "files": 2,
        "format": "quant-hunter-private-backup-1",
    }
    destination = tmp_path / "restored"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup",
            "restore",
            "--archive",
            str(archive),
            "--destination",
            str(destination),
        ],
    )
    backup.main()
    assert json.loads(capsys.readouterr().out) == created
    assert runtime_files(destination) == runtime_files(runtime)


def test_disk_low_prevents_archive_and_destination_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, archive, _manifest = saved(tmp_path)
    monkeypatch.setattr(backup, "_space", ACTUAL_SPACE)
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _: SimpleNamespace(total=100 * GIB, free=GIB)
    )
    with pytest.raises(backup.BackupError, match="reserve"):
        backup.create_backup(runtime, tmp_path / "disk-low.zip", CODE)
    assert not (tmp_path / "disk-low.zip").exists()
    assert_rejected(archive, tmp_path / "restore", "reserve")


def test_source_growth_during_copy_fails_size_bound_and_leaves_no_usable_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    initialized(runtime)
    database = runtime / "application.sqlite3"
    original_size = database.stat().st_size
    monkeypatch.setattr(backup, "MAX_FILE", original_size)

    def concurrent_growth(parent: Path, required: int) -> None:
        with database.open("ab") as output:
            output.write(b"concurrent unexpected growth")

    monkeypatch.setattr(backup, "_space", concurrent_growth)
    archive = tmp_path / "partial.zip"
    with pytest.raises(backup.BackupError, match="Individual file size"):
        backup.create_backup(runtime, archive, CODE)
    assert archive.is_file()
    assert_rejected(archive, tmp_path / "restore")


def test_existing_reparse_component_is_rejected_before_filesystem_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "component"
    directory.mkdir()
    original = Path.lstat

    def reparse_info(path: Path) -> object:
        if path == directory:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path)

    monkeypatch.setattr(Path, "lstat", reparse_info)
    with pytest.raises(backup.BackupError, match="reparse"):
        backup._safe_path(directory / "new.zip")
    assert not (directory / "new.zip").exists()


def test_local_mission_budget_counts_retained_material_without_allocating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / ".local"
    target = local / "backups"
    target.mkdir(parents=True)
    retained = local / "retained.bin"
    retained.write_bytes(b"x")
    original_stat = Path.stat

    def counted_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        result = original_stat(path, follow_symlinks=follow_symlinks)
        if path == retained:
            values = list(result)
            values[6] = 29_999_999_995
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", counted_stat)
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _: SimpleNamespace(total=1000 * GIB, free=900 * GIB),
    )
    assert backup.MAX_TOTAL == 30_000_000_000
    ACTUAL_SPACE(target, 5)
    with pytest.raises(backup.BackupError, match="project data budget"):
        ACTUAL_SPACE(target, 6)
    # The same guard applies when the destination parent is .local itself.
    with pytest.raises(backup.BackupError, match="project data budget"):
        ACTUAL_SPACE(local, 6)
    assert retained.read_bytes() == b"x"
