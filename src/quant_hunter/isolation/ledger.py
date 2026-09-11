"""Append-only canonical ledger for synthetic sealed-OOS exposure evidence."""

from __future__ import annotations

import os
import re
import tempfile
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

from quant_hunter.config import (
    CanonicalJsonError,
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.config.schema import RecordSchemaError, VersionedSchemaCatalog
from quant_hunter.provenance.hashing import require_sha256_digest, sha256_bytes
from quant_hunter.storage.security import (
    SensitiveMetadataError,
    reject_credential_shaped_fields,
    reject_credential_uri,
    reject_secret_text_values,
)

EVENT_PATTERN: Final = re.compile(r"^event-(?P<number>[0-9]{6})[.]json$")
HEAD_FILE: Final = "head.json"
MANAGED_FIELDS: Final = {"ledger_sequence", "previous_event_digest", "event_digest"}
LOCK_RETRY_SECONDS: Final = 0.01
REPARSE_POINT_ATTRIBUTE: Final = 0x400
SCHEMA_BY_EVENT_TYPE: Final = {
    "AUTHORIZED_RELEASE": "sealed-release-event.schema.json",
    "ACCIDENTAL_EXPOSURE": "sealed-exposure-incident.schema.json",
}
_TIMESTAMP_PATTERN: Final = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:[.](?P<fraction>[0-9]+))?Z$"
)

type _ExactTimestamp = tuple[int, int, int, int, int, int, Decimal]


class ExposureLedgerError(RuntimeError):
    """Base error for sealed exposure-ledger operations."""


class ExposureLedgerIntegrityError(ExposureLedgerError):
    """The exposure ledger is malformed, incomplete, or tampered with."""


class ExposureLedgerStaleWriterError(ExposureLedgerError):
    """A caller attempted to append against an obsolete ledger head."""


class ExposureAlreadyRecordedError(ExposureLedgerError):
    """A sealed experiment/dataset/partition binding is already exposed."""


class ExposureLedgerLockTimeoutError(ExposureLedgerError):
    """The ledger append lock could not be acquired before its deadline."""


class UnsupportedEnforcementModeError(ExposureLedgerError):
    """Item 10A was asked to claim evidence it cannot produce."""


@dataclass(frozen=True, slots=True)
class ExposureLedgerEvent:
    """One verified immutable event in ledger sequence order."""

    sequence: int
    path: Path
    digest: str
    record: JsonRecord


@dataclass(frozen=True, slots=True)
class _ExposureFootprint:
    dataset_id: str
    start: _ExactTimestamp
    end: _ExactTimestamp


def release_event_digest(event: Mapping[str, JsonValue]) -> str:
    """Hash the complete RFC 8785 event body excluding only ``event_digest``."""
    body = deepcopy(dict(event))
    body.pop("event_digest", None)
    return sha256_bytes(canonicalize_json(body))


def verify_release_event_digest(event: Mapping[str, JsonValue]) -> None:
    """Require the stored digest to equal the canonical event-body identity."""
    digest = event.get("event_digest")
    if not isinstance(digest, str):
        raise ExposureLedgerIntegrityError("Exposure event digest is malformed")
    try:
        require_sha256_digest(digest)
    except ValueError as error:
        raise ExposureLedgerIntegrityError(
            "Exposure event digest is malformed"
        ) from error
    if release_event_digest(event) != digest:
        raise ExposureLedgerIntegrityError("Exposure event digest mismatch")


def _reject_floats(value: object) -> None:
    if isinstance(value, float):
        raise ExposureLedgerIntegrityError(
            "Python floats are forbidden in canonical exposure identities"
        )
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_floats(item)
    elif isinstance(value, list):
        for item in value:
            _reject_floats(item)


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & REPARSE_POINT_ATTRIBUTE)


def _existing_components(path: Path) -> Iterator[Path]:
    current = Path(path.anchor)
    yield current
    for part in path.parts[1:]:
        current /= part
        if not os.path.lexists(current):
            return
        yield current


def _assert_no_link_components(path: Path) -> None:
    if any(_is_link_like(component) for component in _existing_components(path)):
        raise ExposureLedgerIntegrityError(
            "Link-like exposure-ledger path component is forbidden"
        )


def _is_regular_lock_file(path: Path) -> bool:
    try:
        return path.is_file() and not _is_link_like(path)
    except OSError:
        return False


@contextmanager
def _exclusive_lock(path: Path, timeout_seconds: float) -> Iterator[None]:
    deadline = time.monotonic() + timeout_seconds
    unconfirmed_windows_contention = False
    while True:
        observed_windows_lock = os.name == "nt" and _is_regular_lock_file(path)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError as error:
            unconfirmed_windows_contention = False
            if time.monotonic() >= deadline:
                raise ExposureLedgerLockTimeoutError(
                    "Timed out acquiring exposure-ledger lock"
                ) from error
            time.sleep(LOCK_RETRY_SECONDS)
        except PermissionError as error:
            if os.name != "nt":
                raise
            confirmed = observed_windows_lock or _is_regular_lock_file(path)
            if not confirmed:
                if unconfirmed_windows_contention:
                    raise
                unconfirmed_windows_contention = True
                continue
            unconfirmed_windows_contention = False
            if time.monotonic() >= deadline:
                raise ExposureLedgerLockTimeoutError(
                    "Timed out acquiring exposure-ledger lock"
                ) from error
            time.sleep(LOCK_RETRY_SECONDS)
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


def _exclusive_publish(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".event-staging-", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError as error:
            raise ExposureLedgerIntegrityError(
                "Refusing to overwrite an exposure-ledger event"
            ) from error
        except OSError as error:
            raise ExposureLedgerIntegrityError(
                "Atomic exposure-event publication failed"
            ) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _publish_head(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=".head-staging-", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except OSError as error:
        raise ExposureLedgerIntegrityError(
            "Exposure-ledger head publication failed"
        ) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _timestamp(value: object, field: str) -> _ExactTimestamp:
    if not isinstance(value, str):
        raise ExposureLedgerIntegrityError(
            f"{field} must be an exact UTC RFC 3339 timestamp"
        )
    match = _TIMESTAMP_PATTERN.fullmatch(value)
    if match is None:
        raise ExposureLedgerIntegrityError(
            f"{field} must be an exact UTC RFC 3339 timestamp"
        )
    components = (
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second")),
    )
    try:
        datetime(*components)
    except ValueError as error:
        raise ExposureLedgerIntegrityError(
            f"{field} must be a valid UTC RFC 3339 timestamp"
        ) from error
    fraction = match.group("fraction") or "0"
    return (*components, Decimal(f"0.{fraction}"))


def _binding_footprints(binding: object) -> tuple[_ExposureFootprint, ...]:
    if not isinstance(binding, dict):
        raise ExposureLedgerIntegrityError("Exposure binding is malformed")
    dataset_ids = binding.get("dataset_ids")
    interval = binding.get("sealed_out_of_sample")
    if (
        not isinstance(dataset_ids, list)
        or not dataset_ids
        or any(not isinstance(item, str) for item in dataset_ids)
        or len(set(dataset_ids)) != len(dataset_ids)
        or dataset_ids != sorted(dataset_ids)
        or not isinstance(interval, dict)
    ):
        raise ExposureLedgerIntegrityError("Exposure binding is malformed")
    start = _timestamp(interval.get("start"), "Exposure interval start")
    end = _timestamp(interval.get("end"), "Exposure interval end")
    if start >= end:
        raise ExposureLedgerIntegrityError(
            "Exposure interval must use a nonempty half-open [start, end) range"
        )
    return tuple(
        _ExposureFootprint(dataset_id, start, end) for dataset_id in dataset_ids
    )


def _footprints_overlap(
    left: tuple[_ExposureFootprint, ...],
    right: tuple[_ExposureFootprint, ...],
) -> bool:
    return any(
        left_item.dataset_id == right_item.dataset_id
        and left_item.start < right_item.end
        and right_item.start < left_item.end
        for left_item in left
        for right_item in right
    )


def _event_footprints(event: Mapping[str, JsonValue]) -> tuple[_ExposureFootprint, ...]:
    return _binding_footprints(event.get("sealed_binding"))


class ExposureLedger:
    """Publish and verify one non-forking chain of sealed exposure events."""

    def __init__(
        self,
        root: Path,
        schema_directory: Path,
        *,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        if not root.is_absolute() or root == Path(root.anchor):
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger root must be an absolute non-root path"
            )
        if lock_timeout_seconds <= 0:
            raise ValueError("lock_timeout_seconds must be positive")
        _assert_no_link_components(root)
        root.mkdir(parents=True, exist_ok=True)
        _assert_no_link_components(root)
        if not root.is_dir():
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger root is not a directory"
            )
        self.root = root.resolve()
        self.lock_timeout_seconds = lock_timeout_seconds
        self._schemas = VersionedSchemaCatalog(schema_directory)

    def verify(self) -> tuple[ExposureLedgerEvent, ...]:
        """Verify contiguity, schemas, canonical identities, and every chain link."""
        self._validate_root()
        with _exclusive_lock(
            self.root / ".release-ledger.lock", self.lock_timeout_seconds
        ):
            return self._verify_unlocked()

    def head_digest(self) -> str | None:
        """Return the verified head digest, or ``None`` for an empty ledger."""
        events = self.verify()
        return events[-1].digest if events else None

    def append_event(
        self,
        event_body: Mapping[str, JsonValue],
        *,
        expected_previous_digest: str | None,
    ) -> ExposureLedgerEvent:
        """Append one event with compare-and-swap and one-way binding enforcement."""
        if MANAGED_FIELDS.intersection(event_body):
            raise ExposureLedgerIntegrityError(
                "Caller supplied exposure-ledger managed fields"
            )
        self._validate_root()
        with _exclusive_lock(
            self.root / ".release-ledger.lock", self.lock_timeout_seconds
        ):
            events = self._verify_unlocked()
            current_head = events[-1].digest if events else None
            if expected_previous_digest != current_head:
                raise ExposureLedgerStaleWriterError(
                    "Expected exposure-ledger head does not match current head"
                )
            if len(events) >= 999_999:
                raise ExposureLedgerIntegrityError(
                    "Six-digit exposure-ledger namespace exhausted"
                )
            record = deepcopy(dict(event_body))
            record["ledger_sequence"] = len(events) + 1
            record["previous_event_digest"] = current_head
            record["event_digest"] = release_event_digest(record)
            self._validate_record(record)
            footprints = _event_footprints(record)
            if record.get("event_type") == "AUTHORIZED_RELEASE" and any(
                _footprints_overlap(footprints, _event_footprints(event.record))
                for event in events
            ):
                raise ExposureAlreadyRecordedError(
                    "The requested dataset/time footprint is already EXPOSED"
                )
            content = canonicalize_json(record)
            path = self.root / f"event-{len(events) + 1:06d}.json"
            _exclusive_publish(path, content)
            event = self._read_event(path, len(events) + 1, current_head)
            head: JsonRecord = {
                "schema_version": "1.0.0",
                "ledger_sequence": event.sequence,
                "event_digest": event.digest,
            }
            _publish_head(self.root / HEAD_FILE, canonicalize_json(head))
            return event

    def get_verified(self, event_digest: str) -> ExposureLedgerEvent:
        """Return one event only after verifying the complete ledger chain."""
        require_sha256_digest(event_digest)
        for event in self.verify():
            if event.digest == event_digest:
                return event
        raise ExposureLedgerIntegrityError("Exposure event is absent from the ledger")

    def exposure_for(
        self, sealed_binding: Mapping[str, JsonValue]
    ) -> ExposureLedgerEvent | None:
        """Return evidence overlapping any component of a global data footprint."""
        footprints = _binding_footprints(sealed_binding)
        return next(
            (
                event
                for event in self.verify()
                if _footprints_overlap(footprints, _event_footprints(event.record))
            ),
            None,
        )

    def _verify_unlocked(self) -> tuple[ExposureLedgerEvent, ...]:
        paths: list[tuple[int, Path]] = []
        for path in self.root.iterdir():
            if path.name.startswith((".event-staging-", ".head-staging-")):
                raise ExposureLedgerIntegrityError(
                    "Abandoned exposure-ledger staging file detected"
                )
            if path.name == HEAD_FILE:
                continue
            if path.suffix != ".json":
                continue
            match = EVENT_PATTERN.fullmatch(path.name)
            if match is None:
                raise ExposureLedgerIntegrityError(
                    "Unexpected JSON file in exposure ledger"
                )
            paths.append((int(match.group("number")), path))
        paths.sort()
        previous: str | None = None
        events: list[ExposureLedgerEvent] = []
        prior_footprints: list[tuple[_ExposureFootprint, ...]] = []
        for expected, (number, path) in enumerate(paths, start=1):
            if number != expected:
                raise ExposureLedgerIntegrityError(
                    "Exposure-ledger event sequence is missing or noncontiguous"
                )
            event = self._read_event(path, expected, previous)
            footprints = _event_footprints(event.record)
            if event.record.get("event_type") == "AUTHORIZED_RELEASE" and any(
                _footprints_overlap(footprints, prior) for prior in prior_footprints
            ):
                raise ExposureLedgerIntegrityError(
                    "Authorized release follows prior overlapping exposure"
                )
            prior_footprints.append(footprints)
            events.append(event)
            previous = event.digest
        self._verify_head(events)
        return tuple(events)

    def _verify_head(self, events: list[ExposureLedgerEvent]) -> None:
        path = self.root / HEAD_FILE
        if not events:
            if os.path.lexists(path):
                raise ExposureLedgerIntegrityError(
                    "Empty exposure ledger has a stale head anchor"
                )
            return
        if _is_link_like(path) or not path.is_file():
            raise ExposureLedgerIntegrityError(
                "Nonempty exposure ledger lacks a regular head anchor"
            )
        try:
            content = path.read_bytes()
            value = parse_json_document(content)
        except (OSError, CanonicalJsonError) as error:
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger head anchor is malformed"
            ) from error
        expected: JsonRecord = {
            "schema_version": "1.0.0",
            "ledger_sequence": events[-1].sequence,
            "event_digest": events[-1].digest,
        }
        if value != expected or content != canonicalize_json(expected):
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger head anchor does not match retained history"
            )

    def _read_event(
        self, path: Path, expected_sequence: int, expected_previous: str | None
    ) -> ExposureLedgerEvent:
        if _is_link_like(path) or not path.is_file():
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger event is not a regular file"
            )
        try:
            content = path.read_bytes()
            value = parse_json_document(content)
        except (OSError, CanonicalJsonError) as error:
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger event is not valid strict JSON"
            ) from error
        if not isinstance(value, dict):
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger event is not a JSON object"
            )
        record = value
        self._validate_record(record)
        if content != canonicalize_json(record):
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger event bytes are not canonical"
            )
        if record.get("ledger_sequence") != expected_sequence:
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger event order does not match its filename"
            )
        if record.get("previous_event_digest") != expected_previous:
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger previous-event digest mismatch"
            )
        verify_release_event_digest(record)
        digest = cast(str, record["event_digest"])
        return ExposureLedgerEvent(expected_sequence, path, digest, record)

    def _validate_record(self, record: Mapping[str, JsonValue]) -> None:
        event_type = record.get("event_type")
        if not isinstance(event_type, str) or event_type not in SCHEMA_BY_EVENT_TYPE:
            raise ExposureLedgerIntegrityError("Exposure event type is unsupported")
        if record.get("enforcement_mode") != "SYNTHETIC_TEST":
            raise UnsupportedEnforcementModeError(
                "Item 10A cannot create or accept HOST_ENFORCED evidence"
            )
        _reject_floats(record)
        try:
            reject_credential_shaped_fields(record)
            reject_secret_text_values(record, "sealed exposure event")
            artifact_reference = record.get("released_artifact_reference")
            if isinstance(artifact_reference, str):
                reject_credential_uri(artifact_reference)
            self._schemas.validate(SCHEMA_BY_EVENT_TYPE[event_type], record)
            _event_footprints(record)
        except (RecordSchemaError, SensitiveMetadataError) as error:
            raise ExposureLedgerIntegrityError(
                "Exposure event failed governed validation"
            ) from error

    def _validate_root(self) -> None:
        _assert_no_link_components(self.root)
        if not self.root.is_dir():
            raise ExposureLedgerIntegrityError(
                "Exposure-ledger root is not a directory"
            )
