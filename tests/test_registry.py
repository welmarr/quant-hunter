"""Behavioral tests for typed identities and append-only registries."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from quant_hunter.identity import (
    AllocationExhaustedError,
    DuplicateIdentifierError,
    IdentityError,
    JsonRecord,
    JsonValue,
    ObjectAlreadyExistsError,
    RegistryIntegrityError,
    RegistryKind,
    RegistryLockTimeoutError,
    RegistryStore,
    StaleWriterError,
    kind_for_id,
    new_typed_id,
    validate_typed_id,
)

UUID_1 = UUID("01990f30-7f5e-7b34-9b21-3d74c513c841")
UUID_2 = UUID("01990f30-7f5e-7b34-9b21-3d74c513c842")


def synthetic_record(status: str = "PROPOSED") -> JsonRecord:
    """Return an explicitly synthetic, non-research payload."""
    return {
        "schema_version": "synthetic-registry-test",
        "status": status,
        "description": "Synthetic registry-control fixture only",
    }


def sequence_factory(values: list[UUID]) -> Callable[[], UUID]:
    """Return UUIDs in a deterministic order for collision tests."""
    iterator: Iterator[UUID] = iter(values)
    return lambda: next(iterator)


@pytest.mark.parametrize("kind", list(RegistryKind))
def test_typed_uuid7_uses_correct_kind_prefix(kind: RegistryKind) -> None:
    """Every approved kind has a lowercase RFC 9562 UUIDv7 identifier."""
    object_id = new_typed_id(kind, uuid_factory=lambda: UUID_1)

    assert object_id == f"{kind.prefix}-{UUID_1}"
    assert kind_for_id(object_id) is kind
    validate_typed_id(object_id, kind)


def test_identity_rejects_wrong_kind_version_and_unknown_prefix() -> None:
    """Typed identity validation fails closed for malformed identities."""
    family_id = new_typed_id(RegistryKind.FAMILY, uuid_factory=lambda: UUID_1)

    with pytest.raises(IdentityError, match="does not match"):
        validate_typed_id(family_id, RegistryKind.MODEL)
    with pytest.raises(IdentityError, match="UUID factory"):
        new_typed_id(RegistryKind.MODEL, uuid_factory=uuid4)
    with pytest.raises(IdentityError, match="Malformed"):
        kind_for_id("MODEL-not-a-uuid")
    with pytest.raises(IdentityError, match="Unknown"):
        kind_for_id(f"OTHER-{UUID_1}")


def test_unique_allocation_creates_exclusive_first_revisions(tmp_path: Path) -> None:
    """Default allocation creates unique IDs and fixed v000001 paths."""
    store = RegistryStore.for_synthetic_tests(tmp_path)

    allocations = [
        store.allocate(RegistryKind.BACKLOG, synthetic_record()) for _ in range(8)
    ]

    assert len({item.object_id for item in allocations}) == len(allocations)
    for item in allocations:
        assert item.attempts == 1
        assert item.revision.number == 1
        assert item.revision.path.name == "v000001.json"
        assert item.revision.path.parent.name == item.object_id
        assert item.revision.record["previous_revision_digest"] is None


def test_collision_retries_and_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An existing generated ID is logged and replaced by a fresh UUIDv7."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    existing = store.allocate(
        RegistryKind.SOURCE,
        synthetic_record(),
        uuid_factory=lambda: UUID_1,
    )

    allocation = store.allocate(
        RegistryKind.SOURCE,
        synthetic_record(),
        uuid_factory=sequence_factory([UUID_1, UUID_2]),
    )

    assert allocation.attempts == 2
    assert allocation.object_id != existing.object_id
    assert "collision" in caplog.text.lower()


def test_collision_retry_limit_is_enforced(tmp_path: Path) -> None:
    """Repeated collisions stop at the caller's explicit retry bound."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    store.allocate(RegistryKind.COST, synthetic_record(), uuid_factory=lambda: UUID_1)

    with pytest.raises(AllocationExhaustedError, match="after 2 attempts"):
        store.allocate(
            RegistryKind.COST,
            synthetic_record(),
            uuid_factory=lambda: UUID_1,
            max_attempts=2,
        )
    with pytest.raises(ValueError, match="max_attempts"):
        store.allocate(RegistryKind.COST, synthetic_record(), max_attempts=0)


def test_exclusive_first_revision_never_overwrites(tmp_path: Path) -> None:
    """Creating an allocated first revision a second time preserves its bytes."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    object_id = new_typed_id(RegistryKind.DATASET, uuid_factory=lambda: UUID_1)
    original = store.create_initial(RegistryKind.DATASET, object_id, synthetic_record())
    original_bytes = original.path.read_bytes()

    with pytest.raises(ObjectAlreadyExistsError, match="already exists"):
        store.create_initial(
            RegistryKind.DATASET, object_id, synthetic_record("REJECTED")
        )

    assert original.path.read_bytes() == original_bytes


def test_append_is_zero_padded_chained_and_non_overwriting(tmp_path: Path) -> None:
    """Append writes the next file and links it to exact prior file bytes."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    first = store.allocate(RegistryKind.PATTERN, synthetic_record()).revision
    first_bytes = first.path.read_bytes()

    second = store.append(
        cast(str, first.record["pattern_id"]),
        first.digest,
        synthetic_record("REJECTED"),
    )

    assert second.path.name == "v000002.json"
    assert first.digest == f"sha256:{sha256(first_bytes).hexdigest()}"
    assert second.record["previous_revision_digest"] == first.digest
    assert first.path.read_bytes() == first_bytes
    assert [
        item.number
        for item in store.verify_object(cast(str, first.record["pattern_id"]))
    ] == [1, 2]


def test_stale_writer_is_rejected_without_creating_revision(tmp_path: Path) -> None:
    """A stale digest cannot fork or advance the authoritative chain."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    first = store.allocate(RegistryKind.EXPERIMENT, synthetic_record()).revision
    object_id = cast(str, first.record["experiment_id"])
    second = store.append(object_id, first.digest, synthetic_record("FAILED"))

    with pytest.raises(StaleWriterError, match="current head"):
        store.append(object_id, first.digest, synthetic_record("REJECTED"))

    assert second.path.exists()
    assert not second.path.with_name("v000003.json").exists()


def test_concurrent_writers_allow_one_compare_and_swap_winner(tmp_path: Path) -> None:
    """Two writers with one head digest yield one append and one stale writer."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    first = store.allocate(RegistryKind.MODEL, synthetic_record()).revision
    object_id = cast(str, first.record["object_id"])
    barrier = Barrier(2)

    def append(status: str) -> int | str:
        barrier.wait()
        try:
            return store.append(
                object_id, first.digest, synthetic_record(status)
            ).number
        except StaleWriterError:
            return "STALE"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append, ["REJECTED", "FAILED"]))

    assert sorted(outcomes, key=str) == [2, "STALE"]
    assert len(store.verify_object(object_id)) == 2


def test_concurrent_allocation_is_unique_and_complete(tmp_path: Path) -> None:
    """Concurrent allocators serialize safely and leave complete first revisions."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    barrier = Barrier(12)

    def allocate(_: int) -> str:
        barrier.wait()
        return store.allocate(RegistryKind.STRATEGY, synthetic_record()).object_id

    with ThreadPoolExecutor(max_workers=12) as executor:
        object_ids = list(executor.map(allocate, range(12)))

    assert len(set(object_ids)) == 12
    assert set(store.verify_all()) == set(object_ids)


def test_concurrent_initial_creation_has_one_winner(tmp_path: Path) -> None:
    """Exclusive directory creation prevents duplicate first-revision writers."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    object_id = new_typed_id(RegistryKind.FAMILY, uuid_factory=lambda: UUID_1)
    barrier = Barrier(2)

    def create(status: str) -> str:
        barrier.wait()
        try:
            store.create_initial(
                RegistryKind.FAMILY, object_id, synthetic_record(status)
            )
            return "CREATED"
        except ObjectAlreadyExistsError:
            return "EXISTS"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(create, ["REJECTED", "FAILED"]))

    assert sorted(outcomes) == ["CREATED", "EXISTS"]
    assert len(store.verify_object(object_id)) == 1


def test_broken_previous_digest_chain_is_rejected(tmp_path: Path) -> None:
    """Verification detects a revision whose prior digest was altered."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    first = store.allocate(RegistryKind.SOURCE, synthetic_record()).revision
    object_id = cast(str, first.record["source_id"])
    second = store.append(object_id, first.digest, synthetic_record("REJECTED"))
    damaged = deepcopy(second.record)
    damaged["previous_revision_digest"] = "sha256:" + "0" * 64
    second.path.write_text(json.dumps(damaged), encoding="utf-8")

    with pytest.raises(RegistryIntegrityError, match="Broken previous"):
        store.verify_object(object_id)


def test_duplicate_identifier_detection_is_global(tmp_path: Path) -> None:
    """The same full permanent ID in two locations invalidates the registry."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    allocation = store.allocate(RegistryKind.BACKLOG, synthetic_record())
    duplicate = tmp_path / "unexpected-kind" / allocation.object_id
    shutil.copytree(allocation.revision.path.parent, duplicate)

    with pytest.raises(DuplicateIdentifierError, match=allocation.object_id):
        store.verify_all()
    with pytest.raises(DuplicateIdentifierError, match=allocation.object_id):
        store.verify_object(allocation.object_id)


def test_rejected_and_failed_history_remains_immutable(tmp_path: Path) -> None:
    """Later outcomes cannot erase rejected or failed synthetic revisions."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    first = store.allocate(
        RegistryKind.EXPERIMENT, synthetic_record("REJECTED")
    ).revision
    object_id = cast(str, first.record["experiment_id"])
    first_bytes = first.path.read_bytes()
    second = store.append(object_id, first.digest, synthetic_record("FAILED"))
    second_bytes = second.path.read_bytes()
    store.append(object_id, second.digest, synthetic_record("INCONCLUSIVE"))

    revisions = store.verify_object(object_id)
    assert [item.record["status"] for item in revisions] == [
        "REJECTED",
        "FAILED",
        "INCONCLUSIVE",
    ]
    assert first.path.read_bytes() == first_bytes
    assert second.path.read_bytes() == second_bytes


def test_generated_index_is_disposable_and_non_authoritative(tmp_path: Path) -> None:
    """Generated views identify themselves as non-authoritative and rebuild."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    allocation = store.allocate(RegistryKind.COST, synthetic_record())

    index_path = store.rebuild_index()
    first_bytes = index_path.read_bytes()
    first_index = cast(dict[str, Any], json.loads(first_bytes))
    index_path.unlink()
    rebuilt_path = store.rebuild_index()

    assert first_index["authoritative"] is False
    assert first_index["generated_from_registry"] is True
    assert first_index["entries"][0]["object_id"] == allocation.object_id
    assert rebuilt_path.read_bytes() == first_bytes


def test_record_validation_and_managed_fields_fail_before_write(tmp_path: Path) -> None:
    """Injected schema validation and managed envelope ownership are enforced."""
    validations: list[RegistryKind] = []

    def validator(kind: RegistryKind, record: Mapping[str, JsonValue]) -> None:
        validations.append(kind)
        if record.get("status") == "INVALID":
            raise RegistryIntegrityError("synthetic validation failure")

    store = RegistryStore.for_synthetic_tests(tmp_path, validator=validator)
    allocation = store.allocate(RegistryKind.DATASET, synthetic_record())
    assert validations == [RegistryKind.DATASET]

    with pytest.raises(RegistryIntegrityError, match="managed fields"):
        store.append(
            allocation.object_id,
            allocation.revision.digest,
            {**synthetic_record(), "revision": 2},
        )
    with pytest.raises(RegistryIntegrityError, match="validation failure"):
        store.append(
            allocation.object_id,
            allocation.revision.digest,
            synthetic_record("INVALID"),
        )
    assert len(store.verify_object(allocation.object_id)) == 1


def test_integrity_errors_cover_wrong_location_sequence_and_content(
    tmp_path: Path,
) -> None:
    """Malformed locations, gaps, envelopes, and JSON all fail closed."""
    store = RegistryStore.for_synthetic_tests(tmp_path)
    allocation = store.allocate(RegistryKind.BACKLOG, synthetic_record())
    object_id = allocation.object_id
    object_directory = allocation.revision.path.parent

    allocation.revision.path.rename(object_directory / "v000002.json")
    with pytest.raises(RegistryIntegrityError, match="Non-contiguous"):
        store.verify_object(object_id)
    (object_directory / "v000002.json").rename(allocation.revision.path)

    original = allocation.revision.path.read_bytes()
    bad_record = json.loads(original)
    bad_record["backlog_id"] = new_typed_id(
        RegistryKind.BACKLOG, uuid_factory=lambda: UUID_2
    )
    allocation.revision.path.write_text(json.dumps(bad_record), encoding="utf-8")
    with pytest.raises(RegistryIntegrityError, match="identity mismatch"):
        store.verify_object(object_id)

    allocation.revision.path.write_bytes(b"not-json")
    with pytest.raises(RegistryIntegrityError, match="Invalid UTF-8 JSON"):
        store.verify_object(object_id)


def test_unknown_empty_object_and_lock_timeout_fail_closed(tmp_path: Path) -> None:
    """Absent, incomplete, and locked objects cannot be treated as valid chains."""
    store = RegistryStore.for_synthetic_tests(tmp_path, lock_timeout_seconds=0.01)
    unknown = new_typed_id(RegistryKind.COST, uuid_factory=lambda: UUID_1)
    with pytest.raises(RegistryIntegrityError, match="Unknown"):
        store.verify_object(unknown)

    empty = tmp_path / RegistryKind.COST.directory / unknown
    empty.mkdir(parents=True)
    with pytest.raises(RegistryIntegrityError, match="no revisions"):
        store.verify_object(unknown)

    lock_path = empty / ".revision.lock"
    lock_path.write_text("held", encoding="utf-8")
    with pytest.raises(RegistryLockTimeoutError, match="Timed out"):
        store.verify_object(unknown)
    lock_path.unlink()


def test_registry_configuration_and_non_json_values_are_rejected(
    tmp_path: Path,
) -> None:
    """Invalid configuration and non-finite JSON cannot enter the registry."""
    with pytest.raises(TypeError, match=r"RegistryStore[.]governed"):
        RegistryStore(tmp_path, validator=lambda _kind, _record: None)
    with pytest.raises(ValueError, match="lock_timeout_seconds"):
        RegistryStore.for_synthetic_tests(tmp_path, lock_timeout_seconds=0)
    store = RegistryStore.for_synthetic_tests(tmp_path)
    bad = synthetic_record()
    bad["value"] = float("nan")
    with pytest.raises(RegistryIntegrityError, match="valid I-JSON"):
        store.allocate(RegistryKind.FAMILY, bad)
