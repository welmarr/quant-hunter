"""Private, bounded offline backups; restore only into a new local directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import struct
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import IO, cast

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.web.lease import RuntimeLease

MAX_TOTAL = 30_000_000_000
MAX_FILE = 64 * 1024**2
MAX_FILES = 50_000
MARKER = "restore.incomplete"


class BackupError(ValueError):
    """A backup or restore is incomplete, unsafe or incompatible."""


def _safe_path(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise BackupError("An absolute local path without traversal is required")
    if str(path).startswith("\\\\") or path == Path(path.anchor):
        raise BackupError("Filesystem roots and network paths are forbidden")
    for component in (*reversed(path.parents), path):
        if os.path.lexists(component):
            info = component.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise BackupError("Links and reparse points are forbidden")
    return path


def _relative(name: str) -> str:
    path = PurePosixPath(name)
    if (
        not name
        or len(name) > 240
        or "\\" in name
        or ":" in name
        or name != path.as_posix()
        or path.is_absolute()
        or any(
            part in ("", ".", "..")
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", part)
            or part.endswith((".", " "))
            or part.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *[f"COM{i}" for i in range(1, 10)],
                *[f"LPT{i}" for i in range(1, 10)],
            }
            for part in path.parts
        )
    ):
        raise BackupError("Invalid archive member path")
    if name != "application.sqlite3" and not (
        name.startswith("research/artifacts/")
        or name.startswith("research/registries/")
    ):
        raise BackupError("Unknown runtime material; backup scope requires review")
    if any(
        word in name.lower() for word in ("secret", "credential", ".env", "master.key")
    ):
        raise BackupError("Secret material requires a separate owner-controlled backup")
    return name


def _space(parent: Path, required: int) -> None:
    usage = shutil.disk_usage(parent)
    if usage.free - required < max(20 * 1024**3, usage.total * 15 // 100):
        raise BackupError("Insufficient disk reserve")
    for root in (parent, *parent.parents):
        if root.name == ".local":
            total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
            if total + required > MAX_TOTAL:
                raise BackupError("Native project data budget would be exceeded")
            break


def _sqlite(path: Path) -> None:
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise BackupError("SQLite integrity check failed")
            if db.execute("SELECT MAX(version) FROM migrations").fetchone()[0] not in (
                1,
                2,
            ):
                raise BackupError("Unsupported application migration")
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise BackupError("Unreadable application database") from exc


def _copy(source: IO[bytes], target: IO[bytes] | None = None) -> tuple[int, str]:
    size, digest = 0, hashlib.sha256()
    while block := source.read(1024 * 1024):
        size += len(block)
        if size > MAX_FILE:
            raise BackupError("Individual file size limit exceeded")
        digest.update(block)
        if target is not None:
            target.write(block)
    return size, "sha256:" + digest.hexdigest()


def create_backup(runtime: Path, archive: Path, code_revision: str) -> JsonRecord:
    """Require a stopped runtime; include private account state, never master keys."""
    _safe_path(runtime)
    _safe_path(archive)
    if not runtime.is_dir() or not (runtime / "application.sqlite3").is_file():
        raise BackupError("An existing initialized runtime is required")
    if archive.is_relative_to(runtime) or runtime.is_relative_to(archive):
        raise BackupError("Archive must be outside the runtime")
    if re.fullmatch(r"[0-9a-f]{40}", code_revision) is None:
        raise BackupError("Exact code revision required")
    if archive.exists() or (runtime / MARKER).exists():
        raise BackupError("Archive exists or runtime restoration is incomplete")
    lease = RuntimeLease(runtime)
    lease.acquire()
    try:
        _sqlite(runtime / "application.sqlite3")
        files: list[Path] = []
        total = 0
        for path in sorted(runtime.rglob("*")):
            _safe_path(path)
            if not path.is_file() or path == runtime / "worker.lock":
                continue
            _relative(path.relative_to(runtime).as_posix())
            size = path.stat().st_size
            total += size
            if size > MAX_FILE or total > MAX_TOTAL or len(files) >= MAX_FILES:
                raise BackupError("Backup size or file-count limit exceeded")
            files.append(path)
        archive.parent.mkdir(parents=True, exist_ok=True)
        _space(archive.parent, total + 16 * 1024**2)
        records: list[JsonRecord] = []
        with archive.open("xb") as output:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
                for path in files:
                    relative = path.relative_to(runtime).as_posix()
                    with (
                        path.open("rb") as source,
                        bundle.open(relative, "w", force_zip64=True) as target,
                    ):
                        size, digest = _copy(source, target)
                    records.append({"path": relative, "size": size, "digest": digest})
                manifest: JsonRecord = {
                    "format": "quant-hunter-private-backup-1",
                    "code_revision": code_revision,
                    "created_at": datetime.now(UTC).isoformat(),
                    "privacy": "PRIVATE: contains local accounts and data; never commit or share",
                    "master_keys": "EXCLUDED; none may be stored in the runtime backup scope",
                    "files": cast(list[JsonValue], records),
                }
                bundle.writestr("manifest.json", canonicalize_json(manifest))
            output.flush()
            os.fsync(output.fileno())
        return manifest
    finally:
        lease.release()


def _manifest(bundle: zipfile.ZipFile, expected_count: int) -> JsonRecord:
    entries = bundle.infolist()
    names = [entry.filename for entry in entries]
    if (
        len(entries) != expected_count
        or len(entries) > MAX_FILES + 1
        or len(names) != len(set(names))
        or names.count("manifest.json") != 1
    ):
        raise BackupError("Invalid archive member count or duplicate names")
    total = 0
    for entry in entries:
        if entry.compress_type != zipfile.ZIP_STORED or entry.flag_bits & 1:
            raise BackupError("Compressed or encrypted archives are unsupported")
        if stat.S_ISLNK(entry.external_attr >> 16) or entry.is_dir():
            raise BackupError("Link/directory archive entries are forbidden")
        total += entry.file_size
        if entry.file_size > MAX_FILE or total > MAX_TOTAL:
            raise BackupError("Restore size limit exceeded")
        if entry.filename != "manifest.json":
            _relative(entry.filename)
    if bundle.getinfo("manifest.json").file_size > 16 * 1024**2:
        raise BackupError("Manifest too large")
    value = parse_json_document(bundle.read("manifest.json"))
    if (
        not isinstance(value, dict)
        or value.get("format") != "quant-hunter-private-backup-1"
    ):
        raise BackupError("Unknown backup format")
    rows = value.get("files")
    if not isinstance(rows, list) or len(rows) != len(entries) - 1:
        raise BackupError("Manifest does not account for every file")
    expected: dict[str, tuple[int, str]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "size", "digest"}:
            raise BackupError("Invalid manifest record")
        name, size, digest = row["path"], row["size"], row["digest"]
        if (
            not isinstance(name, str)
            or type(size) is not int
            or not isinstance(digest, str)
        ):
            raise BackupError("Invalid manifest value")
        _relative(name)
        if name in expected or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise BackupError("Duplicate path or invalid digest")
        expected[name] = size, digest
    if (
        set(expected) != set(names) - {"manifest.json"}
        or "application.sqlite3" not in expected
    ):
        raise BackupError("Missing or unaccounted runtime file")
    for name, identity in expected.items():
        with bundle.open(name) as source:
            if _copy(source) != identity:
                raise BackupError("Backup file digest/size mismatch")
    return value


def _archive_bounds(archive: Path) -> int:
    """Bound ZIP metadata before ZipFile allocates the central-directory index."""
    size = archive.stat().st_size
    if not 22 <= size <= MAX_TOTAL + 32 * 1024**2:
        raise BackupError("Archive size is outside supported bounds")
    with archive.open("rb") as handle:
        handle.seek(-22, 2)
        signature, disk, directory_disk, disk_count, count, length, offset, comment = (
            struct.unpack("<4s4H2LH", handle.read(22))
        )
        if (
            signature != b"PK\x05\x06"
            or disk
            or directory_disk
            or comment
            or disk_count != count
        ):
            raise BackupError("Only single-volume comment-free backups are supported")
        end = size - 22
        if count == 65535 or length == 0xFFFFFFFF or offset == 0xFFFFFFFF:
            if size < 98:
                raise BackupError("Incomplete ZIP64 directory")
            handle.seek(-42, 2)
            locator, locator_disk, position, disks = struct.unpack(
                "<4sLQL", handle.read(20)
            )
            if (
                locator != b"PK\x06\x07"
                or locator_disk
                or disks != 1
                or position + 56 != size - 42
            ):
                raise BackupError("Invalid ZIP64 locator")
            handle.seek(position)
            (
                signature64,
                record_size,
                _made,
                needed,
                disk64,
                directory64,
                disk_count64,
                count64,
                length64,
                offset64,
            ) = struct.unpack("<4sQ2H2L4Q", handle.read(56))
            if (
                signature64 != b"PK\x06\x06"
                or record_size != 44
                or disk64
                or directory64
                or disk_count64 != count64
                or needed > 45
            ):
                raise BackupError("Unsupported ZIP64 directory")
            count, length, offset, end = count64, length64, offset64, position
        if (
            not 1 <= count <= MAX_FILES + 1
            or length > 16 * 1024**2
            or offset + length != end
        ):
            raise BackupError(
                "ZIP directory exceeds bounds or has inconsistent offsets"
            )
        return int(count)


def restore_backup(archive: Path, destination: Path) -> JsonRecord:
    """Verify every byte before publication; retain a failure marker if interrupted."""
    _safe_path(archive)
    _safe_path(destination)
    if os.path.lexists(destination):
        raise BackupError("Restore destination must not already exist")
    if destination.is_relative_to(archive) or archive.is_relative_to(destination):
        raise BackupError("Archive and destination must be distinct")
    expected_count = _archive_bounds(archive)
    with zipfile.ZipFile(archive, "r") as bundle:
        manifest = _manifest(bundle, expected_count)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _space(destination.parent, sum(entry.file_size for entry in bundle.infolist()))
        destination.mkdir()
        lease = RuntimeLease(destination)
        lease.acquire()
        try:
            marker = destination / MARKER
            marker.write_text("Restore not yet verified; do not launch this runtime.\n")
            expected = {
                cast(str, row["path"]): (
                    cast(int, row["size"]),
                    cast(str, row["digest"]),
                )
                for row in cast(list[JsonRecord], manifest["files"])
            }
            for entry in bundle.infolist():
                if entry.filename == "manifest.json":
                    continue
                target = destination.joinpath(*PurePosixPath(entry.filename).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                _safe_path(target)
                with bundle.open(entry) as source, target.open("xb") as output:
                    if _copy(source, output) != expected[entry.filename]:
                        raise BackupError("Restored file digest/size mismatch")
                    output.flush()
                    os.fsync(output.fileno())
            _sqlite(destination / "application.sqlite3")
            marker.unlink()
            return manifest
        finally:
            lease.release()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--runtime", type=Path, required=True)
    create.add_argument("--archive", type=Path, required=True)
    create.add_argument("--code-revision", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = (
        create_backup(args.runtime, args.archive, args.code_revision)
        if args.command == "create"
        else restore_backup(args.archive, args.destination)
    )
    print(
        json.dumps(
            {
                "status": "VERIFIED",
                "files": len(cast(list[JsonValue], result["files"])),
                "format": result["format"],
            }
        )
    )


if __name__ == "__main__":
    main()
