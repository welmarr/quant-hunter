"""Synthetic experiment preregistration and freeze lifecycle tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.experiments import (
    ExperimentIntegrityError,
    ExperimentLifecycleService,
    InvalidExperimentTransitionError,
    PreregistrationError,
)
from quant_hunter.identity import (
    RegistryIntegrityError,
    RegistryKind,
    RegistryStore,
    Revision,
    StaleWriterError,
    new_typed_id,
)
from quant_hunter.provenance import DataManifestReference
from quant_hunter.storage import ImmutableObjectStore, ObjectCorruptionError

REPOSITORY_ROOT = Path(__file__).parents[1]
SCHEMA_DIRECTORY = REPOSITORY_ROOT / "schemas" / "v1"
VALID_FIXTURES = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "schemas" / "valid_objects.json"
)
EXPERIMENT_UUID = UUID("01990f30-7f5e-7b34-9b21-3d74c513d60a")
SECOND_EXPERIMENT_UUID = UUID("01990f30-7f5e-7b34-9b21-3d74c513d60b")
CREATED_AT = "2026-09-06T12:00:00Z"
REGISTERED_AT = "2026-09-06T12:01:00Z"
FROZEN_AT = "2026-09-06T12:02:00Z"


def planned_payload() -> JsonRecord:
    """Return a complete result-free synthetic preregistration payload."""
    fixtures = cast(dict[str, JsonRecord], json.loads(VALID_FIXTURES.read_text()))
    payload = deepcopy(fixtures["experiment.schema.json"])
    for field in (
        "experiment_id",
        "revision",
        "previous_revision_digest",
        "created_at",
        "lifecycle_status",
    ):
        del payload[field]
    payload.update(
        {
            "academic_institutional_basis": "Synthetic methodological basis",
            "source_registry_ids": ["SOURCE-01990f30-7f5e-7b34-9b21-3d74c513c841"],
            "provenance_artifact_digests": ["sha256:" + "2" * 64],
            "instruments": ["SYNTHETIC-1"],
            "sampling_frequency": "one day",
            "feature_definitions": "Identity transformation of synthetic value",
            "label_definitions": "Positive when synthetic value is greater than zero",
            "candidate_universe": "One declared synthetic candidate",
            "parameters_considered": "fixed parameter value 1",
            "baselines": ["constant-zero synthetic baseline"],
            "statistical_tests": ["exact synthetic assertion"],
            "results": {"status": "PENDING", "reason": "No execution has occurred."},
            "result_artifact_locations": {
                "status": "PENDING",
                "reason": "No execution has occurred.",
            },
            "reason_for_decision": {
                "status": "PENDING",
                "reason": "No evaluation has occurred.",
            },
            "decision_pending_reason": "No evaluation has occurred.",
        }
    )
    return payload


def service(tmp_path: Path) -> ExperimentLifecycleService:
    """Create the authoritative registry and immutable object test boundary."""
    return ExperimentLifecycleService(
        RegistryStore.governed(tmp_path / "registries", SCHEMA_DIRECTORY),
        ImmutableObjectStore((tmp_path / "artifacts").resolve()),
    )


def data_manifests(
    payload: JsonRecord | None = None,
    *,
    reference: str = "registry://synthetic/data/v1",
) -> list[DataManifestReference]:
    """Match the exact registered synthetic provenance-manifest digest."""
    record = payload or planned_payload()
    digests = cast(list[str], record["provenance_artifact_digests"])
    return [DataManifestReference(reference, digest) for digest in digests]


def registered_experiment(
    lifecycle: ExperimentLifecycleService,
    payload: JsonRecord | None = None,
) -> tuple[str, Revision, Revision]:
    """Create a DRAFT and transition it to REGISTERED."""
    draft = lifecycle.create_draft(
        payload or planned_payload(),
        created_at=CREATED_AT,
        uuid_factory=lambda: EXPERIMENT_UUID,
    )
    registered = lifecycle.register(
        draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
    )
    return draft.object_id, draft.revision, registered


def test_valid_draft_registered_frozen_chain(tmp_path: Path) -> None:
    """The authorized lifecycle appends three governed immutable revisions."""
    lifecycle = service(tmp_path)
    experiment_id, draft, registered = registered_experiment(lifecycle)

    frozen = lifecycle.freeze(
        experiment_id,
        registered.digest,
        frozen_at=FROZEN_AT,
        data_manifests=data_manifests(),
    )

    assert draft.record["lifecycle_status"] == "DRAFT"
    assert registered.record["lifecycle_status"] == "REGISTERED"
    assert frozen.revision.record["lifecycle_status"] == "FROZEN"
    assert frozen.revision.record["frozen_manifest_digest"] == frozen.manifest.digest
    assert frozen.manifest.document["registered_revision_digest"] == registered.digest
    assert frozen.manifest_object.digest == frozen.manifest.digest
    lifecycle_fields = {
        "revision",
        "previous_revision_digest",
        "lifecycle_status",
        "frozen_at",
        "frozen_manifest_digest",
    }
    assert {
        key: value
        for key, value in frozen.revision.record.items()
        if key not in lifecycle_fields
    } == {
        key: value
        for key, value in registered.record.items()
        if key not in lifecycle_fields
    }
    assert [
        revision.number for revision in lifecycle.registry.verify_object(experiment_id)
    ] == [
        1,
        2,
        3,
    ]
    assert lifecycle.verify_frozen(experiment_id) == frozen


def test_stale_writer_and_wrong_prior_digest_are_rejected(tmp_path: Path) -> None:
    """Lifecycle transitions preserve registry compare-and-swap authority."""
    lifecycle = service(tmp_path)
    draft_allocation = lifecycle.create_draft(
        planned_payload(),
        created_at=CREATED_AT,
        uuid_factory=lambda: EXPERIMENT_UUID,
    )
    experiment_id = draft_allocation.object_id
    draft = draft_allocation.revision

    with pytest.raises(StaleWriterError, match="current head"):
        lifecycle.register(
            experiment_id, "sha256:" + "f" * 64, registered_at=REGISTERED_AT
        )
    registered = lifecycle.register(
        experiment_id, draft.digest, registered_at=REGISTERED_AT
    )

    with pytest.raises(StaleWriterError, match="current head"):
        lifecycle.freeze(
            experiment_id,
            draft.digest,
            frozen_at=FROZEN_AT,
            data_manifests=data_manifests(),
        )
    with pytest.raises(StaleWriterError, match="current head"):
        lifecycle.freeze(
            experiment_id,
            "sha256:" + "f" * 64,
            frozen_at=FROZEN_AT,
            data_manifests=data_manifests(),
        )
    assert lifecycle.registry.verify_object(experiment_id)[-1] == registered


def test_skipped_backward_and_repeated_transitions_are_rejected(
    tmp_path: Path,
) -> None:
    """DRAFT cannot freeze and FROZEN cannot register or freeze again."""
    lifecycle = service(tmp_path)
    draft = lifecycle.create_draft(
        planned_payload(),
        created_at=CREATED_AT,
        uuid_factory=lambda: EXPERIMENT_UUID,
    )
    with pytest.raises(InvalidExperimentTransitionError, match="DRAFT to FROZEN"):
        lifecycle.freeze(
            draft.object_id,
            draft.revision.digest,
            frozen_at=FROZEN_AT,
            data_manifests=data_manifests(),
        )

    registered = lifecycle.register(
        draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
    )
    frozen = lifecycle.freeze(
        draft.object_id,
        registered.digest,
        frozen_at=FROZEN_AT,
        data_manifests=data_manifests(),
    )
    with pytest.raises(InvalidExperimentTransitionError, match="FROZEN to REGISTERED"):
        lifecycle.register(
            draft.object_id, frozen.revision.digest, registered_at=FROZEN_AT
        )
    with pytest.raises(InvalidExperimentTransitionError, match="FROZEN to FROZEN"):
        lifecycle.freeze(
            draft.object_id,
            frozen.revision.digest,
            frozen_at=FROZEN_AT,
            data_manifests=data_manifests(),
        )


def test_registration_rejects_observed_results(tmp_path: Path) -> None:
    """A result-bearing DRAFT cannot be relabelled as preregistered."""
    lifecycle = service(tmp_path)
    payload = planned_payload()
    payload["results"] = "observed synthetic outcome"
    draft = lifecycle.create_draft(
        payload, created_at=CREATED_AT, uuid_factory=lambda: EXPERIMENT_UUID
    )

    with pytest.raises(PreregistrationError, match="Observed results"):
        lifecycle.register(
            draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "result_artifact_locations",
            ["https://example.invalid/observed.json"],
            "Result artifact locations",
        ),
        ("result_artifact_digests", ["sha256:" + "8" * 64], "digests"),
        ("reason_for_decision", "premature observed reason", "reason for decision"),
        ("variants_attempted", 1, "Attempted variants"),
        (
            "variant_accounting",
            {
                "ai_generated_attempts": 1,
                "failed_attempts": 0,
                "accounting_basis": "One premature synthetic attempt.",
            },
            "AI-generated",
        ),
    ],
)
def test_registration_rejects_other_observed_evidence(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    """All outcome and attempt evidence remains empty before execution."""
    lifecycle = service(tmp_path)
    payload = planned_payload()
    payload[field] = cast(JsonValue, value)
    draft = lifecycle.create_draft(
        payload, created_at=CREATED_AT, uuid_factory=lambda: EXPERIMENT_UUID
    )

    with pytest.raises(PreregistrationError, match=message):
        lifecycle.register(
            draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
        )


def test_registration_rejects_placeholder_plans_and_decision(tmp_path: Path) -> None:
    """Scientific plans must be explicit and decisions cannot predate evaluation."""
    lifecycle = service(tmp_path)
    pending = planned_payload()
    pending["feature_definitions"] = {
        "status": "PENDING",
        "reason": "Would otherwise be silently deferred.",
    }
    draft = lifecycle.create_draft(
        pending, created_at=CREATED_AT, uuid_factory=lambda: EXPERIMENT_UUID
    )
    with pytest.raises(PreregistrationError, match="feature_definitions"):
        lifecycle.register(
            draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
        )

    decided = planned_payload()
    del decided["decision_pending_reason"]
    decided["decision"] = "DEFER"
    decided["reason_for_decision"] = "Synthetic premature decision"
    second = lifecycle.create_draft(
        decided,
        created_at=CREATED_AT,
        uuid_factory=lambda: SECOND_EXPERIMENT_UUID,
    )
    with pytest.raises(PreregistrationError, match="decision"):
        lifecycle.register(
            second.object_id, second.revision.digest, registered_at=REGISTERED_AT
        )


@pytest.mark.parametrize(
    "field",
    [
        "academic_institutional_basis",
        "source_registry_ids",
        "provenance_artifact_digests",
        "instruments",
        "sampling_frequency",
        "feature_definitions",
        "label_definitions",
        "candidate_universe",
        "parameters_considered",
        "baselines",
    ],
)
def test_registration_rejects_each_unresolved_material_plan(
    tmp_path: Path, field: str
) -> None:
    """UNKNOWN or PENDING cannot stand in for a material preregistration plan."""
    lifecycle = service(tmp_path)
    payload = planned_payload()
    payload[field] = {
        "status": "PENDING",
        "reason": "The planned value has not been declared.",
    }
    draft = lifecycle.create_draft(
        payload, created_at=CREATED_AT, uuid_factory=lambda: EXPERIMENT_UUID
    )

    with pytest.raises(PreregistrationError, match=field):
        lifecycle.register(
            draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"statistical_tests": []}, "statistical_tests"),
        ({"execution_cost_assumptions": []}, "execution_cost_assumptions"),
        (
            {
                "multiple_testing": {
                    "family_id": "FAM-01990f30-7f5e-7b34-9b21-3d74c513d60c",
                    "budget": 1,
                    "correction_plan": "One synthetic comparison.",
                }
            },
            "research family",
        ),
        ({"variants_planned": 2}, "cover every planned variant"),
        (
            {
                "dataset_vintages": [
                    {
                        "dataset_id": "DATASET-01990f30-7f5e-7b34-9b21-3d74c513d60d",
                        "record_digest": "sha256:" + "a" * 64,
                        "vintage": "substituted-v1",
                    }
                ]
            },
            "account for every exact dataset",
        ),
    ],
)
def test_registration_rejects_incomplete_or_inconsistent_plans(
    tmp_path: Path, mutation: JsonRecord, message: str
) -> None:
    """Required plans and cross-field scientific accounting agree."""
    lifecycle = service(tmp_path)
    payload = planned_payload()
    payload.update(deepcopy(mutation))
    draft = lifecycle.create_draft(
        payload, created_at=CREATED_AT, uuid_factory=lambda: EXPERIMENT_UUID
    )

    with pytest.raises(PreregistrationError, match=message):
        lifecycle.register(
            draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
        )


def test_lifecycle_owns_fields_and_requires_ordered_explicit_timestamps(
    tmp_path: Path,
) -> None:
    """Callers supply valid times but cannot inject lifecycle state or reverse time."""
    lifecycle = service(tmp_path)
    with pytest.raises(ExperimentIntegrityError, match="Lifecycle-managed"):
        lifecycle.create_draft(
            {**planned_payload(), "lifecycle_status": "REGISTERED"},
            created_at=CREATED_AT,
        )
    with pytest.raises(ExperimentIntegrityError, match="UTC RFC 3339"):
        lifecycle.create_draft(planned_payload(), created_at="2026-09-06 12:00:00")
    with pytest.raises(ExperimentIntegrityError, match="UTC RFC 3339"):
        lifecycle.create_draft(
            planned_payload(), created_at="2026-09-06T12:00:00-04:00"
        )
    with pytest.raises(ExperimentIntegrityError, match="valid UTC"):
        lifecycle.create_draft(planned_payload(), created_at="2026-99-99T12:00:00Z")

    draft = lifecycle.create_draft(
        planned_payload(),
        created_at=CREATED_AT,
        uuid_factory=lambda: EXPERIMENT_UUID,
    )
    with pytest.raises(ExperimentIntegrityError, match="precedes created_at"):
        lifecycle.register(
            draft.object_id,
            draft.revision.digest,
            registered_at="2026-09-06T11:59:59Z",
        )
    registered = lifecycle.register(
        draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
    )
    with pytest.raises(ExperimentIntegrityError, match="precedes registered_at"):
        lifecycle.freeze(
            draft.object_id,
            registered.digest,
            frozen_at=CREATED_AT,
            data_manifests=data_manifests(),
        )


@pytest.mark.parametrize(
    ("created_at", "registered_at"),
    [
        (
            "2026-09-06T12:00:00.000000900Z",
            "2026-09-06T12:00:00.000000100Z",
        ),
        (
            "2026-09-06T12:00:00.000000000009Z",
            "2026-09-06T12:00:00.000000000001Z",
        ),
    ],
)
def test_registration_rejects_reversed_full_fractional_precision(
    tmp_path: Path, created_at: str, registered_at: str
) -> None:
    """Sub-microsecond and beyond-nanosecond ordering is never truncated."""
    lifecycle = service(tmp_path)
    draft = lifecycle.create_draft(
        planned_payload(),
        created_at=created_at,
        uuid_factory=lambda: EXPERIMENT_UUID,
    )

    with pytest.raises(ExperimentIntegrityError, match="precedes created_at"):
        lifecycle.register(
            draft.object_id,
            draft.revision.digest,
            registered_at=registered_at,
        )


def test_freeze_rejects_reversed_submicrosecond_precision(tmp_path: Path) -> None:
    """A FROZEN timestamp cannot move backward within one microsecond."""
    lifecycle = service(tmp_path)
    draft = lifecycle.create_draft(
        planned_payload(),
        created_at="2026-09-06T12:00:00Z",
        uuid_factory=lambda: EXPERIMENT_UUID,
    )
    registered = lifecycle.register(
        draft.object_id,
        draft.revision.digest,
        registered_at="2026-09-06T12:00:00.000000900Z",
    )

    with pytest.raises(ExperimentIntegrityError, match="precedes registered_at"):
        lifecycle.freeze(
            draft.object_id,
            registered.digest,
            frozen_at="2026-09-06T12:00:00.000000100Z",
            data_manifests=data_manifests(),
        )


@pytest.mark.parametrize(
    ("created_at", "registered_at", "frozen_at"),
    [
        (
            "2026-09-06T12:00:00.000000100Z",
            "2026-09-06T12:00:00.000000101Z",
            "2026-09-06T12:00:00.000000102Z",
        ),
        (
            "2026-09-06T12:00:00.123456789012Z",
            "2026-09-06T12:00:00.123456789012Z",
            "2026-09-06T12:00:00.123456789012Z",
        ),
        (CREATED_AT, REGISTERED_AT, FROZEN_AT),
        (
            "2026-09-06T12:00:00.000001Z",
            "2026-09-06T12:00:00.000002Z",
            "2026-09-06T12:00:00.000003Z",
        ),
    ],
)
def test_full_precision_forward_equality_and_existing_timestamps_are_valid(
    tmp_path: Path, created_at: str, registered_at: str, frozen_at: str
) -> None:
    """One-nanosecond progress, equality, seconds, and microseconds remain valid."""
    lifecycle = service(tmp_path)
    draft = lifecycle.create_draft(
        planned_payload(),
        created_at=created_at,
        uuid_factory=lambda: EXPERIMENT_UUID,
    )
    registered = lifecycle.register(
        draft.object_id,
        draft.revision.digest,
        registered_at=registered_at,
    )
    frozen = lifecycle.freeze(
        draft.object_id,
        registered.digest,
        frozen_at=frozen_at,
        data_manifests=data_manifests(),
    )

    assert frozen.revision.record["frozen_at"] == frozen_at


def test_freeze_rejects_registered_record_with_observed_results(
    tmp_path: Path,
) -> None:
    """Freeze independently refuses outcome-bearing REGISTERED evidence."""
    lifecycle = service(tmp_path)
    payload = planned_payload()
    payload["created_at"] = CREATED_AT
    payload["registered_at"] = REGISTERED_AT
    payload["lifecycle_status"] = "REGISTERED"
    payload["results"] = "observed synthetic outcome"
    registered = lifecycle.registry.allocate(
        RegistryKind.EXPERIMENT,
        payload,
        uuid_factory=lambda: EXPERIMENT_UUID,
    )

    with pytest.raises(PreregistrationError, match="Observed results"):
        lifecycle.freeze(
            registered.object_id,
            registered.revision.digest,
            frozen_at=FROZEN_AT,
            data_manifests=data_manifests(),
        )


def test_freeze_rejects_data_not_bound_by_registration(tmp_path: Path) -> None:
    """Freeze cannot substitute a data-manifest digest after preregistration."""
    lifecycle = service(tmp_path)
    experiment_id, _draft, registered = registered_experiment(lifecycle)

    with pytest.raises(ExperimentIntegrityError, match="registered provenance"):
        lifecycle.freeze(
            experiment_id,
            registered.digest,
            frozen_at=FROZEN_AT,
            data_manifests=[
                DataManifestReference(
                    "registry://synthetic/data/substitute", "sha256:" + "9" * 64
                )
            ],
        )


def test_wrong_experiment_id_and_record_identity_are_rejected(tmp_path: Path) -> None:
    """The service cannot cross kind or accept a mismatched registry record ID."""
    lifecycle = service(tmp_path)
    draft = lifecycle.create_draft(
        planned_payload(),
        created_at=CREATED_AT,
        uuid_factory=lambda: EXPERIMENT_UUID,
    )
    wrong_kind = new_typed_id(
        RegistryKind.DATASET, uuid_factory=lambda: SECOND_EXPERIMENT_UUID
    )
    with pytest.raises(ExperimentIntegrityError, match="Invalid experiment"):
        lifecycle.register(
            wrong_kind, draft.revision.digest, registered_at=REGISTERED_AT
        )

    damaged = deepcopy(draft.revision.record)
    damaged["experiment_id"] = new_typed_id(
        RegistryKind.EXPERIMENT, uuid_factory=lambda: SECOND_EXPERIMENT_UUID
    )
    draft.revision.path.write_bytes(
        json.dumps(damaged, separators=(",", ":")).encode("utf-8")
    )
    with pytest.raises(RegistryIntegrityError, match="identity mismatch"):
        lifecycle.register(
            draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
        )


def test_malformed_lifecycle_state_fails_closed(tmp_path: Path) -> None:
    """Even an isolated low-level registry cannot smuggle an unknown state."""
    registry = RegistryStore.for_synthetic_tests(tmp_path / "registries")
    lifecycle = ExperimentLifecycleService(
        registry, ImmutableObjectStore((tmp_path / "artifacts").resolve())
    )
    allocation = registry.allocate(
        RegistryKind.EXPERIMENT,
        {"lifecycle_status": "UNKNOWN_STATE"},
        uuid_factory=lambda: EXPERIMENT_UUID,
    )

    with pytest.raises(ExperimentIntegrityError, match="Malformed"):
        lifecycle.register(
            allocation.object_id,
            allocation.revision.digest,
            registered_at=REGISTERED_AT,
        )

    numeric = registry.allocate(
        RegistryKind.EXPERIMENT,
        {"lifecycle_status": 7},
        uuid_factory=lambda: SECOND_EXPERIMENT_UUID,
    )
    with pytest.raises(ExperimentIntegrityError, match="Malformed"):
        lifecycle.register(
            numeric.object_id, numeric.revision.digest, registered_at=REGISTERED_AT
        )


def test_malformed_lifecycle_timestamps_fail_closed_in_low_level_records(
    tmp_path: Path,
) -> None:
    """The service distrusts timestamp shapes even behind an isolated test store."""
    registry = RegistryStore.for_synthetic_tests(tmp_path / "registries")
    lifecycle = ExperimentLifecycleService(
        registry, ImmutableObjectStore((tmp_path / "artifacts").resolve())
    )
    draft = registry.allocate(
        RegistryKind.EXPERIMENT,
        {"lifecycle_status": "DRAFT", "created_at": 7},
    )
    with pytest.raises(ExperimentIntegrityError, match="created_at is malformed"):
        lifecycle.register(
            draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
        )

    registered = registry.allocate(
        RegistryKind.EXPERIMENT,
        {"lifecycle_status": "REGISTERED", "registered_at": 7},
    )
    with pytest.raises(ExperimentIntegrityError, match="registered_at is malformed"):
        lifecycle.freeze(
            registered.object_id,
            registered.revision.digest,
            frozen_at=FROZEN_AT,
            data_manifests=[],
        )


def test_verify_frozen_rejects_incomplete_low_level_history(tmp_path: Path) -> None:
    """FROZEN verification requires the exact REGISTERED predecessor and digest."""
    registry = RegistryStore.for_synthetic_tests(tmp_path / "registries")
    lifecycle = ExperimentLifecycleService(
        registry, ImmutableObjectStore((tmp_path / "artifacts").resolve())
    )
    registered = registry.allocate(
        RegistryKind.EXPERIMENT, {"lifecycle_status": "REGISTERED"}
    )
    with pytest.raises(ExperimentIntegrityError, match="head is not FROZEN"):
        lifecycle.verify_frozen(registered.object_id)

    lone_frozen = registry.allocate(
        RegistryKind.EXPERIMENT, {"lifecycle_status": "FROZEN"}
    )
    with pytest.raises(ExperimentIntegrityError, match="lacks REGISTERED"):
        lifecycle.verify_frozen(lone_frozen.object_id)

    draft = registry.allocate(RegistryKind.EXPERIMENT, {"lifecycle_status": "DRAFT"})
    wrong_predecessor = registry.append(
        draft.object_id,
        draft.revision.digest,
        {"lifecycle_status": "FROZEN"},
    )
    with pytest.raises(ExperimentIntegrityError, match="not based on a REGISTERED"):
        lifecycle.verify_frozen(draft.object_id)

    malformed_registered = registry.allocate(
        RegistryKind.EXPERIMENT, {"lifecycle_status": "REGISTERED"}
    )
    registry.append(
        malformed_registered.object_id,
        malformed_registered.revision.digest,
        {"lifecycle_status": "FROZEN", "frozen_manifest_digest": 7},
    )
    with pytest.raises(ExperimentIntegrityError, match="manifest digest is malformed"):
        lifecycle.verify_frozen(malformed_registered.object_id)

    assert wrong_predecessor.number == 2


def test_freeze_manifest_tampering_and_overwrite_are_rejected(tmp_path: Path) -> None:
    """Changed freeze bytes cannot verify or replace their digest-addressed object."""
    lifecycle = service(tmp_path)
    experiment_id, _draft, registered = registered_experiment(lifecycle)
    frozen = lifecycle.freeze(
        experiment_id,
        registered.digest,
        frozen_at=FROZEN_AT,
        data_manifests=data_manifests(),
    )
    original = frozen.manifest.canonical_bytes
    damaged = original + b" "
    frozen.manifest_object.path.write_bytes(damaged)

    with pytest.raises(ObjectCorruptionError, match="digest"):
        lifecycle.verify_frozen(experiment_id)
    with pytest.raises(ObjectCorruptionError, match="digest"):
        lifecycle.object_store.publish(original)
    assert frozen.manifest_object.path.read_bytes() == damaged


def test_freeze_does_not_read_or_release_sealed_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sealed reference is bound as metadata and never dereferenced by freeze."""
    lifecycle = service(tmp_path)
    experiment_id, _draft, registered = registered_experiment(lifecycle)
    sealed_path = (tmp_path / "sealed" / "holdout.bin").resolve()
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == sealed_path:
            raise AssertionError("sealed data was accessed")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    frozen = lifecycle.freeze(
        experiment_id,
        registered.digest,
        frozen_at=FROZEN_AT,
        data_manifests=data_manifests(reference=sealed_path.as_uri()),
    )

    assert frozen.manifest.document["data_manifests"] == [
        {
            "digest": cast(list[str], planned_payload()["provenance_artifact_digests"])[
                0
            ],
            "reference": sealed_path.as_uri(),
        }
    ]
    assert not sealed_path.exists()
