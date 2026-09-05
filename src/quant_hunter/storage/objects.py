"""Local immutable content-addressed storage for exact artifact bytes."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from quant_hunter.provenance.hashing import (
    DigestMismatchError,
    require_sha256_digest,
    sha256_bytes,
)

REPARSE_POINT_ATTRIBUTE: Final = 0x400


class ObjectStoreError(RuntimeError):
    """Base error for authoritative immutable object storage."""


class UnsafeArtifactRootError(ObjectStoreError):
    """The configured artifact root is ambiguous or traverses a link-like path."""


class UnsafeObjectPathError(ObjectStoreError):
    """A caller-supplied descriptor does not identify its derived object path."""


class ObjectCorruptionError(ObjectStoreError):
    """A digest path exists but does not contain the identified exact bytes."""


class ObjectPublicationError(ObjectStoreError):
    """Atomic object publication could not be completed."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Identity and location of one immutable exact-byte object."""

    digest: str
    byte_size: int
    path: Path


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _is_link_like(path: Path) -> bool:
    """Detect symbolic links and Windows reparse points without following them."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(file_attributes & REPARSE_POINT_ATTRIBUTE)


def _existing_components(path: Path) -> tuple[Path, ...]:
    current = Path(path.anchor)
    components: list[Path] = [current]
    for part in path.parts[1:]:
        current /= part
        if not _lexists(current):
            break
        components.append(current)
    return tuple(components)


class ImmutableObjectStore:
    """Publish and verify exact bytes without mutation or deletion operations."""

    def __init__(self, artifact_root: Path) -> None:
        if not artifact_root.is_absolute():
            raise UnsafeArtifactRootError("Artifact root must be an absolute path")
        if ".." in artifact_root.parts:
            raise UnsafeArtifactRootError("Artifact root must not contain traversal")
        if os.name == "nt" and str(artifact_root).startswith("\\\\"):
            raise UnsafeArtifactRootError("Artifact root must be on a local filesystem")
        self._assert_no_link_components(artifact_root)
        try:
            resolved = artifact_root.resolve(strict=False)
        except OSError as error:
            raise UnsafeArtifactRootError("Artifact root cannot be resolved") from error
        if resolved == Path(resolved.anchor):
            raise UnsafeArtifactRootError(
                "Filesystem root is not a valid artifact root"
            )
        self.root = resolved
        self._assert_no_link_components(self.root)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise UnsafeArtifactRootError("Artifact root cannot be created") from error
        self._validate_root()

    @property
    def objects_root(self) -> Path:
        """Return the fixed SHA-256 object namespace below the configured root."""
        return self.root / "objects" / "sha256"

    def object_path(self, digest: str) -> Path:
        """Derive the only authoritative path permitted for a governed digest."""
        require_sha256_digest(digest)
        hexadecimal = digest.removeprefix("sha256:")
        return self.objects_root / hexadecimal[:2] / hexadecimal

    def storage_reference(self, digest: str) -> str:
        """Return a root-independent stable reference for an exact-byte object."""
        path = self.object_path(digest)
        return path.relative_to(self.root).as_posix()

    def is_authoritative_path(self, path: Path) -> bool:
        """Classify only exact derived digest paths as authoritative objects."""
        try:
            relative = path.relative_to(self.objects_root)
        except ValueError:
            return False
        if len(relative.parts) != 2:
            return False
        prefix, hexadecimal = relative.parts
        if len(hexadecimal) != 64 or any(
            character not in "0123456789abcdef" for character in hexadecimal
        ):
            return False
        return prefix == hexadecimal[:2]

    def publish(self, content: bytes) -> StoredObject:
        """Atomically publish exact bytes or verify and reuse an existing object."""
        if not isinstance(content, bytes):
            raise TypeError("Immutable object publication requires bytes")
        digest = sha256_bytes(content)
        final_path = self.object_path(digest)
        self._prepare_parent(final_path.parent)
        if _lexists(final_path):
            return self._inspect_existing(digest, final_path)

        descriptor: int | None = None
        temporary_path: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                dir=final_path.parent,
                prefix=".staging-",
                suffix=".tmp",
            )
            temporary_path = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if sha256_bytes(temporary_path.read_bytes()) != digest:
                raise ObjectPublicationError("Staged bytes failed digest verification")
            self._assert_no_link_components(final_path.parent)
            try:
                self._link_staged(temporary_path, final_path)
            except FileExistsError:
                return self._inspect_existing(digest, final_path)
            except OSError as error:
                raise ObjectPublicationError(
                    "Atomic object finalization failed"
                ) from error
            return self._inspect_existing(digest, final_path)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def get(self, digest: str) -> StoredObject:
        """Return a verified immutable object descriptor."""
        final_path = self.object_path(digest)
        self._validate_root()
        self._assert_safe_object_components(final_path)
        if not _lexists(final_path):
            raise ObjectStoreError(f"Immutable object does not exist: {digest}")
        return self._inspect_existing(digest, final_path)

    def verify(self, stored_object: StoredObject) -> None:
        """Verify descriptor path, size, and exact content identity."""
        if stored_object.byte_size < 0:
            raise ObjectCorruptionError("Stored object byte size cannot be negative")
        expected_path = self.object_path(stored_object.digest)
        if stored_object.path != expected_path:
            raise UnsafeObjectPathError(
                "Stored object path does not match its digest-derived path"
            )
        observed = self._inspect_existing(stored_object.digest, expected_path)
        if observed.byte_size != stored_object.byte_size:
            raise ObjectCorruptionError(
                "Stored object byte size does not match descriptor"
            )

    def read_bytes(self, digest: str) -> bytes:
        """Read exact content only after verifying the digest-derived object."""
        final_path = self.object_path(digest)
        content = self._read_verified(digest, final_path)
        return content

    def _link_staged(self, temporary_path: Path, final_path: Path) -> None:
        os.link(temporary_path, final_path)

    def _prepare_parent(self, directory: Path) -> None:
        self._validate_root()
        self._assert_no_link_components(directory)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ObjectPublicationError(
                "Object directory cannot be created"
            ) from error
        self._assert_no_link_components(directory)
        if not directory.is_dir():
            raise UnsafeObjectPathError("Object parent is not a directory")

    def _inspect_existing(self, digest: str, path: Path) -> StoredObject:
        content = self._read_verified(digest, path)
        return StoredObject(digest=digest, byte_size=len(content), path=path)

    def _read_verified(self, digest: str, path: Path) -> bytes:
        self._validate_root()
        if path != self.object_path(digest):
            raise UnsafeObjectPathError("Object path is not digest-derived")
        self._assert_safe_object_components(path)
        if _is_link_like(path) or not path.is_file():
            raise ObjectCorruptionError("Digest path is not a regular immutable object")
        try:
            content = path.read_bytes()
        except OSError as error:
            raise ObjectCorruptionError("Immutable object cannot be read") from error
        try:
            if sha256_bytes(content) != digest:
                raise DigestMismatchError("stored exact bytes do not match path digest")
        except DigestMismatchError as error:
            raise ObjectCorruptionError(
                "Immutable object bytes do not match their digest path"
            ) from error
        return content

    def _assert_safe_object_components(self, path: Path) -> None:
        try:
            self._assert_no_link_components(path.parent)
        except UnsafeArtifactRootError as error:
            raise UnsafeObjectPathError(
                "Link-like object path component is forbidden"
            ) from error

    def _validate_root(self) -> None:
        self._assert_no_link_components(self.root)
        if not self.root.is_dir():
            raise UnsafeArtifactRootError("Artifact root is not a directory")

    @staticmethod
    def _assert_no_link_components(path: Path) -> None:
        for component in _existing_components(path):
            if _is_link_like(component):
                raise UnsafeArtifactRootError(
                    f"Link-like filesystem component is forbidden: {component}"
                )
