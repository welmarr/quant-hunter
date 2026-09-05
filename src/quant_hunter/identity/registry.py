"""File-backed append-only registries with narrow revision-chain hashing."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast
from uuid import uuid7

from quant_hunter.identity.ids import (
    RegistryKind,
    UuidFactory,
    kind_for_id,
    new_typed_id,
)

type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)
type JsonRecord = dict[str, JsonValue]
type RecordValidator = Callable[[RegistryKind, Mapping[str, JsonValue]], None]

LOGGER = logging.getLogger(__name__)
REVISION_PATTERN: Final = re.compile(r"^v(?P<number>[0-9]{6})[.]json$")
FIRST_REVISION: Final = "v000001.json"
LOCK_RETRY_SECONDS: Final = 0.005


class RegistryError(RuntimeError):
    """Base class for registry integrity and concurrency failures."""


class ObjectAlreadyExistsError(RegistryError):
    """An identifier has already been allocated."""


class AllocationExhaustedError(RegistryError):
    """Collision retries could not allocate a fresh identifier."""


class StaleWriterError(RegistryError):
    """A writer's expected prior digest is no longer current."""


class RegistryIntegrityError(RegistryError):
    """A registry path, record, or digest chain is malformed."""


class DuplicateIdentifierError(RegistryIntegrityError):
    """One permanent identifier appears in more than one registry location."""


class RegistryLockTimeoutError(RegistryError):
    """A registry filesystem lock could not be acquired in time."""


@dataclass(frozen=True, slots=True)
class Revision:
    """A verified immutable revision and its exact-file digest."""

    number: int
    path: Path
    digest: str
    record: JsonRecord


@dataclass(frozen=True, slots=True)
class Allocation:
    """A successfully allocated identifier and its first revision."""

    object_id: str
    revision: Revision
    attempts: int


def _revision_digest(content: bytes) -> str:
    """Hash exact revision-file bytes for registry chaining only."""
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _encode_record(record: Mapping[str, JsonValue]) -> bytes:
    """Serialize a registry record; this is deliberately not RFC 8785 JCS."""
    try:
        text = json.dumps(
            record,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
    except (TypeError, ValueError) as error:
        raise RegistryIntegrityError(
            "Registry records must contain finite JSON"
        ) from error
    return f"{text}\n".encode()


def _decode_record(content: bytes, path: Path) -> JsonRecord:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryIntegrityError(f"Invalid UTF-8 JSON revision: {path}") from error
    if not isinstance(value, dict):
        raise RegistryIntegrityError(f"Revision is not a JSON object: {path}")
    return cast(JsonRecord, value)


def _exclusive_write(path: Path, content: bytes) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ObjectAlreadyExistsError(f"Refusing to overwrite {path}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


@contextmanager
def _exclusive_lock(path: Path, timeout_seconds: float) -> Iterator[None]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError as error:
            if time.monotonic() >= deadline:
                raise RegistryLockTimeoutError(
                    f"Timed out acquiring registry lock {path}"
                ) from error
            time.sleep(LOCK_RETRY_SECONDS)
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


class RegistryStore:
    """Manage typed objects as append-only revision files below one root."""

    def __init__(
        self,
        root: Path,
        *,
        validator: RecordValidator | None = None,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        if lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be positive")
        self.root = root
        self.validator = validator
        self.lock_timeout_seconds = lock_timeout_seconds

    def allocate(
        self,
        kind: RegistryKind,
        record: Mapping[str, JsonValue],
        *,
        uuid_factory: UuidFactory = uuid7,
        max_attempts: int = 16,
    ) -> Allocation:
        """Allocate an ID and exclusive-create its first immutable revision."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".allocation.lock"
        with _exclusive_lock(lock_path, self.lock_timeout_seconds):
            for attempt in range(1, max_attempts + 1):
                object_id = new_typed_id(kind, uuid_factory=uuid_factory)
                if self._locations_for_id(object_id):
                    LOGGER.warning("Registry ID collision for %s; retrying", object_id)
                    continue
                try:
                    revision = self.create_initial(kind, object_id, record)
                except ObjectAlreadyExistsError:
                    LOGGER.warning("Registry ID collision for %s; retrying", object_id)
                    continue
                return Allocation(object_id, revision, attempt)
        raise AllocationExhaustedError(
            f"Could not allocate {kind.name} after {max_attempts} attempts"
        )

    def create_initial(
        self,
        kind: RegistryKind,
        object_id: str,
        record: Mapping[str, JsonValue],
    ) -> Revision:
        """Exclusive-create ``v000001.json`` for an already selected UUIDv7."""
        self._require_id_kind(kind, object_id)
        object_directory = self._object_directory(kind, object_id)
        try:
            object_directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise ObjectAlreadyExistsError(
                f"Identifier already exists: {object_id}"
            ) from error
        try:
            complete_record = self._managed_record(kind, object_id, 1, None, record)
            self._validate(kind, complete_record)
            content = _encode_record(complete_record)
            path = object_directory / FIRST_REVISION
            _exclusive_write(path, content)
            return Revision(1, path, _revision_digest(content), complete_record)
        except Exception:
            try:
                object_directory.rmdir()
            except OSError:
                pass
            raise

    def append(
        self,
        object_id: str,
        expected_previous_digest: str,
        record: Mapping[str, JsonValue],
    ) -> Revision:
        """Append exactly one revision if the caller still owns the chain head."""
        kind = kind_for_id(object_id)
        object_directory = self._require_unique_location(object_id, kind)
        lock_path = object_directory / ".revision.lock"
        with _exclusive_lock(lock_path, self.lock_timeout_seconds):
            revisions = self._verify_object_unlocked(kind, object_id, object_directory)
            previous = revisions[-1]
            if previous.digest != expected_previous_digest:
                raise StaleWriterError(
                    f"Expected {expected_previous_digest}, current head is {previous.digest}"
                )
            next_number = previous.number + 1
            if next_number > 999_999:
                raise RegistryIntegrityError("Six-digit revision namespace exhausted")
            complete_record = self._managed_record(
                kind, object_id, next_number, previous.digest, record
            )
            self._validate(kind, complete_record)
            content = _encode_record(complete_record)
            path = object_directory / f"v{next_number:06d}.json"
            _exclusive_write(path, content)
            return Revision(
                next_number, path, _revision_digest(content), complete_record
            )

    def verify_object(self, object_id: str) -> tuple[Revision, ...]:
        """Verify identity, contiguity, and all exact-file digest links."""
        kind = kind_for_id(object_id)
        object_directory = self._require_unique_location(object_id, kind)
        with _exclusive_lock(
            object_directory / ".revision.lock", self.lock_timeout_seconds
        ):
            return self._verify_object_unlocked(kind, object_id, object_directory)

    def verify_all(self) -> dict[str, tuple[Revision, ...]]:
        """Reject duplicate IDs and verify every authoritative object chain."""
        self.root.mkdir(parents=True, exist_ok=True)
        with _exclusive_lock(self.root / ".allocation.lock", self.lock_timeout_seconds):
            locations = self._all_locations()
            duplicates = {
                key: value for key, value in locations.items() if len(value) != 1
            }
            if duplicates:
                names = ", ".join(sorted(duplicates))
                raise DuplicateIdentifierError(
                    f"Duplicate registry identifiers: {names}"
                )
            verified: dict[str, tuple[Revision, ...]] = {}
            for object_id in sorted(locations):
                verified[object_id] = self.verify_object(object_id)
            return verified

    def rebuild_index(self, path: Path | None = None) -> Path:
        """Replace a disposable, explicitly non-authoritative JSON index."""
        verified = self.verify_all()
        output = path if path is not None else self.root / "generated-index.json"
        entries: list[JsonValue] = []
        for object_id, revisions in verified.items():
            head = revisions[-1]
            entries.append(
                {
                    "object_id": object_id,
                    "kind": kind_for_id(object_id).name,
                    "latest_revision": head.number,
                    "latest_revision_digest": head.digest,
                }
            )
        content = _encode_record(
            {
                "authoritative": False,
                "generated_from_registry": True,
                "entries": entries,
            }
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(f"{output.suffix}.{os.getpid()}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, output)
        return output

    def _verify_object_unlocked(
        self, kind: RegistryKind, object_id: str, object_directory: Path
    ) -> tuple[Revision, ...]:
        paths = sorted(path for path in object_directory.iterdir() if path.is_file())
        revision_paths = [
            path for path in paths if REVISION_PATTERN.fullmatch(path.name)
        ]
        unknown = [
            path.name
            for path in paths
            if path.name != ".revision.lock"
            and REVISION_PATTERN.fullmatch(path.name) is None
        ]
        if unknown:
            raise RegistryIntegrityError(
                f"Unexpected authoritative object files in {object_directory}: {unknown}"
            )
        if not revision_paths:
            raise RegistryIntegrityError(f"Object has no revisions: {object_id}")
        revisions: list[Revision] = []
        expected_previous: str | None = None
        for expected_number, path in enumerate(revision_paths, start=1):
            match = REVISION_PATTERN.fullmatch(path.name)
            if match is None or int(match.group("number")) != expected_number:
                raise RegistryIntegrityError(
                    f"Non-contiguous revision sequence for {object_id} at {path.name}"
                )
            content = path.read_bytes()
            record = _decode_record(content, path)
            if record.get(kind.id_field) != object_id:
                raise RegistryIntegrityError(f"Revision identity mismatch: {path}")
            if record.get("revision") != expected_number:
                raise RegistryIntegrityError(f"Revision number mismatch: {path}")
            if record.get("previous_revision_digest") != expected_previous:
                raise RegistryIntegrityError(f"Broken previous-revision digest: {path}")
            self._validate(kind, record)
            digest = _revision_digest(content)
            revisions.append(Revision(expected_number, path, digest, record))
            expected_previous = digest
        return tuple(revisions)

    def _managed_record(
        self,
        kind: RegistryKind,
        object_id: str,
        revision: int,
        previous_digest: str | None,
        record: Mapping[str, JsonValue],
    ) -> JsonRecord:
        managed = {kind.id_field, "revision", "previous_revision_digest"}
        overlap = managed.intersection(record)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise RegistryIntegrityError(
                f"Registry-managed fields supplied by caller: {names}"
            )
        complete = deepcopy(dict(record))
        complete[kind.id_field] = object_id
        complete["revision"] = revision
        complete["previous_revision_digest"] = previous_digest
        return complete

    def _validate(self, kind: RegistryKind, record: Mapping[str, JsonValue]) -> None:
        _encode_record(record)
        if self.validator is not None:
            self.validator(kind, record)

    def _require_id_kind(self, kind: RegistryKind, object_id: str) -> None:
        actual = kind_for_id(object_id)
        if actual is not kind:
            raise RegistryIntegrityError(
                f"Identifier kind {actual.name} cannot be stored as {kind.name}"
            )

    def _object_directory(self, kind: RegistryKind, object_id: str) -> Path:
        return self.root / kind.directory / object_id

    def _locations_for_id(self, object_id: str) -> list[Path]:
        return self._all_locations().get(object_id, [])

    def _require_unique_location(self, object_id: str, kind: RegistryKind) -> Path:
        locations = self._locations_for_id(object_id)
        if not locations:
            raise RegistryIntegrityError(f"Unknown registry identifier: {object_id}")
        if len(locations) != 1:
            raise DuplicateIdentifierError(
                f"Duplicate registry identifier: {object_id}"
            )
        expected = self._object_directory(kind, object_id)
        if locations[0] != expected:
            raise RegistryIntegrityError(
                f"Identifier {object_id} is stored under the wrong registry kind"
            )
        return expected

    def _all_locations(self) -> dict[str, list[Path]]:
        locations: dict[str, list[Path]] = {}
        if not self.root.exists():
            return locations
        for kind_directory in sorted(
            path for path in self.root.iterdir() if path.is_dir()
        ):
            for object_directory in sorted(
                path for path in kind_directory.iterdir() if path.is_dir()
            ):
                locations.setdefault(object_directory.name, []).append(object_directory)
        return locations
