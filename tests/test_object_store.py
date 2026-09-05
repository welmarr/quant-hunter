"""Critical invariants for exact-byte immutable object publication."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import quant_hunter.storage.objects as object_module
from quant_hunter.provenance import InvalidDigestError, sha256_bytes
from quant_hunter.storage import (
    ImmutableObjectStore,
    ObjectCorruptionError,
    ObjectPublicationError,
    ObjectStoreError,
    StoredObject,
    UnsafeArtifactRootError,
    UnsafeObjectPathError,
)


def test_content_address_path_is_deterministic_and_stable(tmp_path: Path) -> None:
    """Only the governed digest determines the path and stable reference."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    digest = "sha256:" + "ab" * 32
    expected = store.root / "objects" / "sha256" / "ab" / ("ab" * 32)

    assert store.object_path(digest) == expected
    assert store.object_path(digest) == store.object_path(digest)
    assert store.storage_reference(digest) == f"objects/sha256/ab/{'ab' * 32}"
    assert store.is_authoritative_path(expected)

    with pytest.raises(InvalidDigestError):
        store.object_path("sha256:BAD")


def test_single_publication_preserves_arbitrary_binary_bytes(tmp_path: Path) -> None:
    """No decoding, newline conversion, or metadata is applied to payload bytes."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    content = bytes(range(256)) + b"\x00\xff\r\nsynthetic"

    stored = store.publish(content)

    assert stored.digest == sha256_bytes(content)
    assert stored.byte_size == len(content)
    assert stored.path.read_bytes() == content
    assert store.read_bytes(stored.digest) == content
    store.verify(stored)


def test_identical_content_deduplicates_without_republication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verified exact object is returned without invoking finalization again."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    first = store.publish(b"same exact bytes")

    def forbidden_link(_temporary: Path, _final: Path) -> None:
        raise AssertionError("existing immutable object must not be republished")

    monkeypatch.setattr(store, "_link_staged", forbidden_link)
    second = store.publish(b"same exact bytes")

    assert second == first


def test_one_byte_change_has_a_different_object(tmp_path: Path) -> None:
    """Physical identity changes for a single changed byte."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    first = store.publish(b"abc")
    second = store.publish(b"abd")

    assert first.digest != second.digest
    assert first.path != second.path
    assert first.path.read_bytes() == b"abc"
    assert second.path.read_bytes() == b"abd"


def test_existing_corrupted_digest_path_refuses_overwrite(tmp_path: Path) -> None:
    """Wrong bytes at the expected path are corruption, never an overwrite target."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    content = b"expected synthetic bytes"
    path = store.object_path(sha256_bytes(content))
    path.parent.mkdir(parents=True)
    path.write_bytes(b"corrupt")

    with pytest.raises(ObjectCorruptionError, match="do not match"):
        store.publish(content)

    assert path.read_bytes() == b"corrupt"


def test_failed_publication_cleans_staging_and_preserves_existing_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finalization failure leaves no partial final and cannot damage prior content."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    original = store.publish(b"already durable")
    new_content = b"publication will fail"
    new_path = store.object_path(sha256_bytes(new_content))

    def fail_link(_temporary: Path, _final: Path) -> None:
        raise OSError("synthetic finalization failure")

    monkeypatch.setattr(store, "_link_staged", fail_link)
    with pytest.raises(ObjectPublicationError, match="finalization"):
        store.publish(new_content)

    assert not new_path.exists()
    assert not list(new_path.parent.glob(".staging-*.tmp"))
    assert store.read_bytes(original.digest) == b"already durable"


def test_temporary_files_are_never_authoritative(tmp_path: Path) -> None:
    """Only exact two-level digest paths can identify final objects."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    stored = store.publish(b"complete")
    temporary = stored.path.parent / ".staging-partial.tmp"
    temporary.write_bytes(b"partial")

    assert not store.is_authoritative_path(temporary)
    assert not store.is_authoritative_path(store.objects_root / "aa" / "short")
    assert not store.is_authoritative_path(store.objects_root / "ff" / ("a" * 64))
    assert not store.is_authoritative_path(store.root / "outside")
    assert store.get(stored.digest) == stored


def test_concurrent_identical_publication_converges(tmp_path: Path) -> None:
    """Concurrent writers converge on one complete immutable object."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    content = bytes(range(128)) * 64

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda _: store.publish(content), range(24)))

    assert len({item.path for item in results}) == 1
    assert len({item.digest for item in results}) == 1
    assert results[0].path.read_bytes() == content
    assert not list(results[0].path.parent.glob(".staging-*.tmp"))


def test_concurrent_corrupt_target_fails_safely(tmp_path: Path) -> None:
    """Every contender rejects a pre-existing corrupt digest location."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    content = b"synthetic concurrent content"
    path = store.object_path(sha256_bytes(content))
    path.parent.mkdir(parents=True)
    path.write_bytes(b"conflicting content")

    def publish(_: int) -> str:
        try:
            store.publish(content)
        except ObjectCorruptionError:
            return "CORRUPT"
        return "UNEXPECTED"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(publish, range(16)))

    assert outcomes == ["CORRUPT"] * 16
    assert path.read_bytes() == b"conflicting content"


def test_descriptor_rejects_unsafe_paths_and_wrong_sizes(tmp_path: Path) -> None:
    """Callers cannot redirect verification outside the digest-derived namespace."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    stored = store.publish(b"descriptor target")

    with pytest.raises(UnsafeObjectPathError, match="digest-derived"):
        store.verify(
            StoredObject(stored.digest, stored.byte_size, tmp_path / "outside")
        )
    with pytest.raises(ObjectCorruptionError, match="size"):
        store.verify(StoredObject(stored.digest, stored.byte_size + 1, stored.path))
    with pytest.raises(ObjectCorruptionError, match="negative"):
        store.verify(StoredObject(stored.digest, -1, stored.path))


def test_missing_and_non_regular_object_paths_fail_closed(tmp_path: Path) -> None:
    """Missing paths and directories cannot masquerade as immutable objects."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    digest = "sha256:" + "c" * 64
    with pytest.raises(ObjectStoreError, match="does not exist"):
        store.get(digest)

    path = store.object_path(digest)
    path.mkdir(parents=True)
    with pytest.raises(ObjectCorruptionError, match="regular"):
        store.get(digest)


def test_artifact_root_rejects_relative_traversal_and_link_like_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ambiguous roots and reparse/symlink components fail before publication."""
    with pytest.raises(UnsafeArtifactRootError, match="absolute"):
        ImmutableObjectStore(Path("relative-artifacts"))
    with pytest.raises(UnsafeArtifactRootError, match="traversal"):
        ImmutableObjectStore(tmp_path / "parent" / ".." / "artifacts")
    with pytest.raises(UnsafeArtifactRootError, match="Filesystem root"):
        ImmutableObjectStore(Path(tmp_path.anchor))
    if os.name == "nt":
        with pytest.raises(UnsafeArtifactRootError, match="local filesystem"):
            ImmutableObjectStore(Path(r"\\synthetic-server\share\artifacts"))

    unsafe = tmp_path / "link-like"
    unsafe.mkdir()
    original = object_module._is_link_like
    monkeypatch.setattr(
        object_module,
        "_is_link_like",
        lambda path: path == unsafe or original(path),
    )
    with pytest.raises(UnsafeArtifactRootError, match="Link-like"):
        ImmutableObjectStore(unsafe / "artifacts")


def test_link_like_object_namespace_is_rejected_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reparse-like object directory cannot redirect writes outside the root."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    unsafe = store.root / "objects"
    unsafe.mkdir()
    original = object_module._is_link_like
    monkeypatch.setattr(
        object_module,
        "_is_link_like",
        lambda path: path == unsafe or original(path),
    )

    with pytest.raises(UnsafeArtifactRootError, match="Link-like"):
        store.publish(b"must not escape")

    assert not (unsafe / "sha256").exists()


@pytest.mark.parametrize("operation", ["get", "read", "verify"])
def test_authoritative_reads_reject_intermediate_link_like_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Every authoritative read rejects a link-like digest-prefix directory."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    stored = store.publish(b"synthetic intermediate-link target")
    unsafe = stored.path.parent
    original = object_module._is_link_like
    monkeypatch.setattr(
        object_module,
        "_is_link_like",
        lambda path: path == unsafe or original(path),
    )

    with pytest.raises(UnsafeObjectPathError, match="Link-like"):
        if operation == "get":
            store.get(stored.digest)
        elif operation == "read":
            store.read_bytes(stored.digest)
        else:
            store.verify(stored)


def test_publication_requires_exact_bytes(tmp_path: Path) -> None:
    """Mutable bytearray input is rejected rather than copied implicitly."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    with pytest.raises(TypeError, match="requires bytes"):
        store.publish(bytearray(b"mutable"))  # type: ignore[arg-type]


def test_missing_link_probe_and_unreadable_object_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing probes are harmless while read errors are reported as corruption."""
    assert not object_module._is_link_like(tmp_path / "missing")
    store = ImmutableObjectStore(tmp_path / "artifacts")
    stored = store.publish(b"unreadable simulation")
    original_read = Path.read_bytes

    def fail_read(path: Path) -> bytes:
        if path == stored.path:
            raise OSError("synthetic read failure")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(ObjectCorruptionError, match="cannot be read"):
        store.get(stored.digest)


def test_staged_digest_mismatch_is_cleaned_without_final_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A changed staging file cannot be promoted under the intended digest."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    content = b"staged verification"
    final_path = store.object_path(sha256_bytes(content))
    original_read = Path.read_bytes

    def alter_staging(path: Path) -> bytes:
        if path.name.startswith(".staging-"):
            return b"different staged bytes"
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", alter_staging)
    with pytest.raises(ObjectPublicationError, match="Staged bytes"):
        store.publish(content)

    assert not final_path.exists()
    assert not list(final_path.parent.glob(".staging-*.tmp"))


def test_root_and_parent_filesystem_failures_are_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalidated roots and uncreatable object directories never accept bytes."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    store.root.rmdir()
    store.root.write_text("not a directory", encoding="utf-8")
    with pytest.raises(UnsafeArtifactRootError, match="not a directory"):
        store.get("sha256:" + "a" * 64)

    valid_store = ImmutableObjectStore(tmp_path / "valid-artifacts")
    original_mkdir = Path.mkdir

    def fail_object_directory(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path != valid_store.root:
            raise OSError("synthetic mkdir failure")
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", fail_object_directory)
    with pytest.raises(ObjectPublicationError, match="cannot be created"):
        valid_store.publish(b"cannot create parent")


def test_private_reader_rejects_non_derived_path(tmp_path: Path) -> None:
    """Even internal reads cannot be redirected to a caller-selected location."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    digest = "sha256:" + "a" * 64
    with pytest.raises(UnsafeObjectPathError, match="digest-derived"):
        store._read_verified(digest, tmp_path / "outside")
