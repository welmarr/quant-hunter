"""Synthetic experiment preregistration and freeze lifecycle tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.config.canonical import canonicalize_json
from quant_hunter.config.schema import RecordSchemaError
from quant_hunter.experiments import (
    AttemptBudgetExceededError,
    EvaluationOutcome,
    ExperimentDecision,
    ExperimentIntegrityError,
    ExperimentLifecycleService,
    InvalidExperimentTransitionError,
    PreregistrationError,
    RerunResolutionError,
    ResultArtifactReference,
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
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.storage import (
    ImmutableObjectStore,
    ObjectCorruptionError,
    SensitiveMetadataError,
)

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
STARTED_AT = "2026-09-06T12:03:00Z"
ATTEMPT_AT = "2026-09-06T12:04:00Z"
EVALUATED_AT = "2026-09-06T12:05:00Z"
DECIDED_AT = "2026-09-06T12:06:00Z"


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


def frozen_experiment(
    lifecycle: ExperimentLifecycleService,
    payload: JsonRecord | None = None,
    *,
    frozen_at: str = FROZEN_AT,
) -> tuple[str, Revision, Revision]:
    """Create the exact synthetic FROZEN history used by runtime tests."""
    experiment_id, _draft, registered = registered_experiment(lifecycle, payload)
    frozen = lifecycle.freeze(
        experiment_id,
        registered.digest,
        frozen_at=frozen_at,
        data_manifests=data_manifests(payload),
    )
    return experiment_id, registered, frozen.revision


def running_experiment(
    lifecycle: ExperimentLifecycleService,
    payload: JsonRecord | None = None,
    *,
    frozen_at: str = FROZEN_AT,
    started_at: str = STARTED_AT,
) -> tuple[str, Revision, Revision]:
    """Create a verified synthetic RUNNING experiment with zero attempts."""
    experiment_id, _registered, frozen = frozen_experiment(
        lifecycle, payload, frozen_at=frozen_at
    )
    running = lifecycle.start(experiment_id, frozen.digest, started_at=started_at)
    return experiment_id, frozen, running


def revision_payload(revision: Revision) -> JsonRecord:
    """Remove fields owned by RegistryStore before a hostile direct append."""
    return {
        key: deepcopy(value)
        for key, value in revision.record.items()
        if key not in {"experiment_id", "revision", "previous_revision_digest"}
    }


def runtime_payload(*, budget: int = 4) -> JsonRecord:
    """Return a preregistration with room for synthetic runtime attempts."""
    payload = planned_payload()
    multiple_testing = cast(JsonRecord, payload["multiple_testing"])
    multiple_testing["budget"] = budget
    return payload


def evaluated_experiment(
    lifecycle: ExperimentLifecycleService,
    *,
    outcome: EvaluationOutcome = EvaluationOutcome.INCONCLUSIVE,
    result_summary: str = "Synthetic evaluation produced no directional conclusion.",
    failure_modes: tuple[str, ...] = (),
) -> tuple[str, Revision, Revision]:
    """Create a synthetic EVALUATED experiment without an external artifact."""
    experiment_id, _frozen, running = running_experiment(lifecycle, runtime_payload())
    evaluated = lifecycle.evaluate(
        experiment_id,
        running.digest,
        evaluated_at=EVALUATED_AT,
        outcome=outcome,
        result_summary=result_summary,
        no_result_artifact_reason="The synthetic outcome is retained in the revision.",
        failure_modes=failure_modes,
    )
    return experiment_id, running, evaluated


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


def test_valid_frozen_to_running_preserves_frozen_evidence(tmp_path: Path) -> None:
    """RUNNING is an append-only revision over independently verified freeze evidence."""
    lifecycle = service(tmp_path)
    experiment_id, frozen, running = running_experiment(lifecycle)

    assert running.record["lifecycle_status"] == "RUNNING"
    assert running.record["started_at"] == STARTED_AT
    assert running.record["attempt_records"] == []
    assert running.record["variants_attempted"] == 0
    assert (
        running.record["frozen_manifest_digest"]
        == frozen.record["frozen_manifest_digest"]
    )
    assert [
        revision.record["lifecycle_status"]
        for revision in lifecycle.registry.verify_object(experiment_id)
    ] == ["DRAFT", "REGISTERED", "FROZEN", "RUNNING"]


def test_start_rejects_draft_registered_and_repeated_running(tmp_path: Path) -> None:
    """Only the single governed FROZEN to RUNNING lifecycle edge is accepted."""
    lifecycle = service(tmp_path)
    draft = lifecycle.create_draft(
        planned_payload(), created_at=CREATED_AT, uuid_factory=lambda: EXPERIMENT_UUID
    )
    with pytest.raises(InvalidExperimentTransitionError, match="DRAFT to RUNNING"):
        lifecycle.start(draft.object_id, draft.revision.digest, started_at=STARTED_AT)

    registered = lifecycle.register(
        draft.object_id, draft.revision.digest, registered_at=REGISTERED_AT
    )
    with pytest.raises(InvalidExperimentTransitionError, match="REGISTERED to RUNNING"):
        lifecycle.start(draft.object_id, registered.digest, started_at=STARTED_AT)

    frozen = lifecycle.freeze(
        draft.object_id,
        registered.digest,
        frozen_at=FROZEN_AT,
        data_manifests=data_manifests(),
    )
    running = lifecycle.start(
        draft.object_id, frozen.revision.digest, started_at=STARTED_AT
    )
    with pytest.raises(InvalidExperimentTransitionError, match="RUNNING to RUNNING"):
        lifecycle.start(draft.object_id, running.digest, started_at=STARTED_AT)


def test_start_and_attempt_reject_wrong_or_stale_heads(tmp_path: Path) -> None:
    """Both the lifecycle edge and every exposure append retain registry CAS authority."""
    lifecycle = service(tmp_path)
    experiment_id, _registered, frozen = frozen_experiment(lifecycle, runtime_payload())
    with pytest.raises(StaleWriterError, match="current head"):
        lifecycle.start(experiment_id, "sha256:" + "f" * 64, started_at=STARTED_AT)
    running = lifecycle.start(experiment_id, frozen.digest, started_at=STARTED_AT)
    first = lifecycle.record_attempt(
        experiment_id,
        running.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=False,
        failed=False,
        exposure_reason="First synthetic candidate execution.",
    )
    with pytest.raises(StaleWriterError, match="current head"):
        lifecycle.record_attempt(
            experiment_id,
            running.digest,
            recorded_at=ATTEMPT_AT,
            ai_generated=False,
            failed=False,
            exposure_reason="Stale synthetic candidate execution.",
        )
    assert lifecycle.registry.verify_object(experiment_id)[-1] == first


def test_start_rejects_submicrosecond_time_reversal(tmp_path: Path) -> None:
    """FROZEN to RUNNING ordering retains every accepted fractional digit."""
    lifecycle = service(tmp_path)
    experiment_id, _registered, frozen = frozen_experiment(
        lifecycle, frozen_at="2026-09-06T12:02:00.000000900Z"
    )

    with pytest.raises(ExperimentIntegrityError, match="precedes frozen_at"):
        lifecycle.start(
            experiment_id,
            frozen.digest,
            started_at="2026-09-06T12:02:00.000000100Z",
        )


@pytest.mark.parametrize(
    ("frozen_at", "started_at"),
    [
        (
            "2026-09-06T12:02:00.123456789012Z",
            "2026-09-06T12:02:00.123456789012Z",
        ),
        (
            "2026-09-06T12:02:00.000000100Z",
            "2026-09-06T12:02:00.000000101Z",
        ),
    ],
)
def test_start_accepts_exact_equality_and_one_nanosecond_progress(
    tmp_path: Path, frozen_at: str, started_at: str
) -> None:
    """Equality and exact nanosecond progress remain valid lifecycle orderings."""
    lifecycle = service(tmp_path)
    experiment_id, _registered, frozen = frozen_experiment(
        lifecycle, frozen_at=frozen_at
    )

    running = lifecycle.start(experiment_id, frozen.digest, started_at=started_at)

    assert running.record["started_at"] == started_at


def test_start_rejects_corrupt_manifest_and_changed_frozen_science(
    tmp_path: Path,
) -> None:
    """Starting re-verifies immutable bytes and exact REGISTERED science."""
    corrupt_service = service(tmp_path / "corrupt")
    experiment_id, _registered, frozen = frozen_experiment(corrupt_service)
    digest = cast(str, frozen.record["frozen_manifest_digest"])
    stored = corrupt_service.object_store.get(digest)
    stored.path.write_bytes(stored.path.read_bytes() + b" ")
    with pytest.raises(ObjectCorruptionError, match="digest"):
        corrupt_service.start(experiment_id, frozen.digest, started_at=STARTED_AT)

    changed_service = service(tmp_path / "changed")
    changed_id, _registered, changed_frozen = frozen_experiment(changed_service)
    damaged = deepcopy(changed_frozen.record)
    damaged["hypothesis"] = "Changed after registration"
    damaged_bytes = canonicalize_json(damaged)
    changed_frozen.path.write_bytes(damaged_bytes)
    changed_digest = sha256_bytes(damaged_bytes)
    with pytest.raises(ExperimentIntegrityError, match="scientific evidence"):
        changed_service.start(changed_id, changed_digest, started_at=STARTED_AT)


@pytest.mark.parametrize(
    ("ai_generated", "failed", "expected_ai", "expected_failed"),
    [
        (False, False, 0, 0),
        (True, False, 1, 0),
        (False, True, 0, 1),
        (True, True, 1, 1),
    ],
)
def test_attempt_flags_increment_each_applicable_counter_once(
    tmp_path: Path,
    ai_generated: bool,
    failed: bool,
    expected_ai: int,
    expected_failed: int,
) -> None:
    """Ordinary, AI, failed, and AI-failed attempts count total exposure once."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle, runtime_payload())
    variant_digest = "sha256:" + "7" * 64

    revision = lifecycle.record_attempt(
        experiment_id,
        running.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=ai_generated,
        failed=failed,
        exposure_reason="Synthetic search exposure was actually attempted.",
        variant_configuration_digest=variant_digest,
    )

    assert revision.record["variants_attempted"] == 1
    accounting = cast(JsonRecord, revision.record["variant_accounting"])
    assert accounting["ai_generated_attempts"] == expected_ai
    assert accounting["failed_attempts"] == expected_failed
    attempts = cast(list[JsonRecord], revision.record["attempt_records"])
    assert attempts == [
        {
            "attempt_number": 1,
            "experiment_id": experiment_id,
            "recorded_at": ATTEMPT_AT,
            "ai_generated": ai_generated,
            "failed": failed,
            "exposure_reason": "Synthetic search exposure was actually attempted.",
            "variant_configuration_digest": variant_digest,
        }
    ]


def test_retry_appends_another_exposure_without_erasing_failure(tmp_path: Path) -> None:
    """A retry is a new attempt linked to its retained failed predecessor."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle, runtime_payload())
    first = lifecycle.record_attempt(
        experiment_id,
        running.digest,
        recorded_at="2026-09-06T12:04:00.000000100Z",
        ai_generated=False,
        failed=True,
        exposure_reason="Synthetic candidate failed during execution.",
    )
    retry = lifecycle.record_attempt(
        experiment_id,
        first.digest,
        recorded_at="2026-09-06T12:04:00.000000101Z",
        ai_generated=False,
        failed=False,
        exposure_reason="Synthetic retry executed after the retained failure.",
        retry_of_attempt=1,
    )

    assert retry.record["variants_attempted"] == 2
    accounting = cast(JsonRecord, retry.record["variant_accounting"])
    assert accounting["failed_attempts"] == 1
    attempts = cast(list[JsonRecord], retry.record["attempt_records"])
    assert attempts[0]["failed"] is True
    assert attempts[1]["retry_of_attempt"] == 1


def test_concurrent_attempt_writers_cannot_lose_exposure(tmp_path: Path) -> None:
    """One concurrent CAS wins; the stale writer can retry against the retained head."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle, runtime_payload())

    def write(reason: str) -> Revision:
        return lifecycle.record_attempt(
            experiment_id,
            running.digest,
            recorded_at=ATTEMPT_AT,
            ai_generated=False,
            failed=False,
            exposure_reason=reason,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write, f"Concurrent synthetic exposure {index}.")
            for index in range(2)
        ]
    successes: list[Revision] = []
    failures: list[BaseException] = []
    for future in futures:
        try:
            successes.append(future.result())
        except BaseException as error:
            failures.append(error)
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], StaleWriterError)
    head = lifecycle.registry.verify_object(experiment_id)[-1]
    assert head.record["variants_attempted"] == 1

    retried = lifecycle.record_attempt(
        experiment_id,
        head.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=False,
        failed=False,
        exposure_reason="Stale concurrent writer retried as another exposure.",
        retry_of_attempt=1,
    )
    assert retried.record["variants_attempted"] == 2


@pytest.mark.parametrize(
    "mutation",
    [
        {"variants_attempted": 0},
        {
            "variant_accounting": {
                "ai_generated_attempts": 1,
                "failed_attempts": 0,
                "accounting_basis": (
                    "No attempts; all failed and AI attempts count in total exposure."
                ),
            }
        },
        {
            "attempt_records": [
                {
                    "attempt_number": 1,
                    "experiment_id": str(EXPERIMENT_UUID).join(("EXP-", "")),
                    "recorded_at": ATTEMPT_AT,
                    "ai_generated": False,
                    "failed": False,
                    "exposure_reason": "Substituted historical exposure.",
                }
            ]
        },
    ],
)
def test_counter_reset_or_attempt_substitution_fails(
    tmp_path: Path, mutation: JsonRecord
) -> None:
    """A direct schema-valid revision cannot rewrite cumulative runtime history."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle, runtime_payload())
    first = lifecycle.record_attempt(
        experiment_id,
        running.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=False,
        failed=False,
        exposure_reason="Original synthetic exposure.",
    )
    payload = revision_payload(first)
    payload.update(deepcopy(mutation))
    hostile = lifecycle.registry.append(experiment_id, first.digest, payload)

    with pytest.raises(ExperimentIntegrityError, match=r"counters|append exactly one"):
        lifecycle.record_attempt(
            experiment_id,
            hostile.digest,
            recorded_at=ATTEMPT_AT,
            ai_generated=False,
            failed=False,
            exposure_reason="Attempt after rewritten history.",
        )
    assert lifecycle.registry.verify_object(experiment_id)[-1] == hostile


def test_attempt_beyond_frozen_budget_fails_without_revision(tmp_path: Path) -> None:
    """Failed attempts and retries cannot enlarge the preregistered search budget."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(
        lifecycle, runtime_payload(budget=1)
    )
    first = lifecycle.record_attempt(
        experiment_id,
        running.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=True,
        failed=True,
        exposure_reason="Budgeted synthetic failure.",
    )
    revision_count = len(lifecycle.registry.verify_object(experiment_id))

    with pytest.raises(AttemptBudgetExceededError, match="frozen"):
        lifecycle.record_attempt(
            experiment_id,
            first.digest,
            recorded_at=ATTEMPT_AT,
            ai_generated=False,
            failed=False,
            exposure_reason="Unbudgeted synthetic retry.",
            retry_of_attempt=1,
        )
    assert len(lifecycle.registry.verify_object(experiment_id)) == revision_count
    assert lifecycle.registry.verify_object(experiment_id)[-1] == first


def test_attempt_evidence_rejects_labelled_secret_text(tmp_path: Path) -> None:
    """Runtime exposure reasons cannot persist obvious credential material."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle)

    with pytest.raises(SensitiveMetadataError, match="attempt exposure reason"):
        lifecycle.record_attempt(
            experiment_id,
            running.digest,
            recorded_at=ATTEMPT_AT,
            ai_generated=False,
            failed=True,
            exposure_reason="Authorization: Bearer synthetic-secret-value",
        )
    assert lifecycle.registry.verify_object(experiment_id)[-1] == running


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hypothesis", "Changed synthetic hypothesis"),
        ("dataset_ids", ["DATASET-01990f30-7f5e-7b34-9b21-3d74c513d60e"]),
        (
            "dataset_vintages",
            [
                {
                    "dataset_id": "DATASET-01990f30-7f5e-7b34-9b21-3d74c513d60d",
                    "record_digest": "sha256:" + "b" * 64,
                    "vintage": "changed-v2",
                }
            ],
        ),
        (
            "partitions",
            {
                "training": {"start": CREATED_AT, "end": REGISTERED_AT},
                "validation": {"start": REGISTERED_AT, "end": FROZEN_AT},
                "sealed_out_of_sample": {"start": FROZEN_AT, "end": STARTED_AT},
            },
        ),
        ("feature_definitions", "Changed feature"),
        ("label_definitions", "Changed label"),
        ("candidate_universe", "Changed candidate universe"),
        ("search_space", "Changed search space"),
        ("parameters_considered", "Changed parameters"),
        ("variants_planned", 2),
        (
            "multiple_testing",
            {
                "family_id": "FAM-01990f30-7f5e-7b34-9b21-3d74c513c844",
                "budget": 5,
                "correction_plan": "Changed correction plan.",
            },
        ),
        ("evaluation_metrics", ["changed metric"]),
        ("statistical_tests", ["changed test"]),
        ("baselines", ["changed baseline"]),
        ("execution_cost_assumptions", ["changed cost"]),
        ("decision_criteria", "Changed criterion"),
        ("code_revision", "d" * 40),
        ("configuration_digest", "sha256:" + "d" * 64),
        ("environment_digest", "sha256:" + "d" * 64),
        ("frozen_manifest_digest", "sha256:" + "d" * 64),
    ],
)
def test_runtime_revision_cannot_change_frozen_science(
    tmp_path: Path, field: str, value: JsonValue
) -> None:
    """Every material preregistration and freeze binding remains exact at runtime."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle, runtime_payload())
    payload = revision_payload(running)
    payload[field] = deepcopy(value)
    hostile = lifecycle.registry.append(experiment_id, running.digest, payload)

    with pytest.raises(ExperimentIntegrityError, match="changed frozen science"):
        lifecycle.record_attempt(
            experiment_id,
            hostile.digest,
            recorded_at=ATTEMPT_AT,
            ai_generated=False,
            failed=False,
            exposure_reason="Synthetic attempt after science mutation.",
        )


@pytest.mark.parametrize("field", ["results", "result_artifact_locations", "decision"])
def test_running_schema_rejects_final_results_or_decision(
    tmp_path: Path, field: str
) -> None:
    """RUNNING revisions cannot smuggle later-lifecycle evidence."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle)
    payload = revision_payload(running)
    if field == "results":
        payload[field] = "Premature synthetic result"
    elif field == "result_artifact_locations":
        payload[field] = ["https://example.invalid/premature.json"]
    else:
        del payload["decision_pending_reason"]
        payload["decision"] = "REJECT"
        payload["reason_for_decision"] = "Premature synthetic decision"

    with pytest.raises(RecordSchemaError):
        lifecycle.registry.append(experiment_id, running.digest, payload)
    assert lifecycle.registry.verify_object(experiment_id)[-1] == running


def test_running_and_attempt_accounting_never_read_sealed_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runtime accounting verifies references without dereferencing sealed content."""
    lifecycle = service(tmp_path)
    sealed_path = (tmp_path / "sealed" / "holdout.bin").resolve()
    payload = runtime_payload()
    experiment_id, _registered, frozen = registered_experiment(lifecycle, payload)
    frozen_evidence = lifecycle.freeze(
        experiment_id,
        frozen.digest,
        frozen_at=FROZEN_AT,
        data_manifests=data_manifests(payload, reference=sealed_path.as_uri()),
    )
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == sealed_path:
            raise AssertionError("sealed data was accessed")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    running = lifecycle.start(
        experiment_id, frozen_evidence.revision.digest, started_at=STARTED_AT
    )
    attempted = lifecycle.record_attempt(
        experiment_id,
        running.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=False,
        failed=False,
        exposure_reason="Synthetic attempt without sealed access.",
    )

    assert attempted.record["sealed_data_release"] == {
        "status": "UNRELEASED",
        "reason": "Not evaluated.",
    }
    assert not sealed_path.exists()


def test_valid_running_to_evaluated_retains_exact_runtime_evidence(
    tmp_path: Path,
) -> None:
    """EVALUATED appends observed evidence without changing runtime history."""
    lifecycle = service(tmp_path)
    experiment_id, running, evaluated = evaluated_experiment(lifecycle)

    assert evaluated.record["lifecycle_status"] == "EVALUATED"
    assert evaluated.record["evaluated_at"] == EVALUATED_AT
    assert evaluated.record["evaluation_outcome"] == "INCONCLUSIVE"
    assert evaluated.record["attempt_records"] == running.record["attempt_records"]
    assert (
        evaluated.record["variants_attempted"] == running.record["variants_attempted"]
    )
    assert lifecycle.registry.verify_object(experiment_id)[-1] == evaluated


def test_evaluate_rejects_pre_running_and_repeated_states(tmp_path: Path) -> None:
    """Only RUNNING may transition once to EVALUATED."""
    draft_service = service(tmp_path / "draft")
    draft = draft_service.create_draft(
        planned_payload(), created_at=CREATED_AT, uuid_factory=lambda: EXPERIMENT_UUID
    )
    with pytest.raises(InvalidExperimentTransitionError, match="DRAFT to EVALUATED"):
        draft_service.evaluate(
            draft.object_id,
            draft.revision.digest,
            evaluated_at=EVALUATED_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Synthetic null outcome.",
            no_result_artifact_reason="No artifact applies.",
        )

    registered_service = service(tmp_path / "registered")
    registered_id, _draft, registered = registered_experiment(registered_service)
    with pytest.raises(
        InvalidExperimentTransitionError, match="REGISTERED to EVALUATED"
    ):
        registered_service.evaluate(
            registered_id,
            registered.digest,
            evaluated_at=EVALUATED_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Synthetic null outcome.",
            no_result_artifact_reason="No artifact applies.",
        )

    frozen_service = service(tmp_path / "frozen")
    frozen_id, _registered, frozen = frozen_experiment(frozen_service)
    with pytest.raises(InvalidExperimentTransitionError, match="FROZEN to EVALUATED"):
        frozen_service.evaluate(
            frozen_id,
            frozen.digest,
            evaluated_at=EVALUATED_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Synthetic null outcome.",
            no_result_artifact_reason="No artifact applies.",
        )

    evaluated_service = service(tmp_path / "evaluated")
    evaluated_id, _running, evaluated = evaluated_experiment(evaluated_service)
    with pytest.raises(
        InvalidExperimentTransitionError, match="EVALUATED to EVALUATED"
    ):
        evaluated_service.evaluate(
            evaluated_id,
            evaluated.digest,
            evaluated_at=EVALUATED_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Repeated synthetic evaluation.",
            no_result_artifact_reason="No artifact applies.",
        )


def test_evaluate_rejects_wrong_or_stale_cas_head(tmp_path: Path) -> None:
    """Observed evidence cannot append unless the caller owns the runtime head."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle, runtime_payload())

    with pytest.raises(StaleWriterError, match="current head"):
        lifecycle.evaluate(
            experiment_id,
            "sha256:" + "f" * 64,
            evaluated_at=EVALUATED_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Synthetic null outcome.",
            no_result_artifact_reason="No artifact applies.",
        )
    attempted = lifecycle.record_attempt(
        experiment_id,
        running.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=False,
        failed=False,
        exposure_reason="Synthetic attempt advances the CAS head.",
    )
    with pytest.raises(StaleWriterError, match="current head"):
        lifecycle.evaluate(
            experiment_id,
            running.digest,
            evaluated_at=EVALUATED_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Synthetic null outcome.",
            no_result_artifact_reason="No artifact applies.",
        )
    assert lifecycle.registry.verify_object(experiment_id)[-1] == attempted


def test_evaluate_rejects_time_before_start_or_last_attempt(tmp_path: Path) -> None:
    """Evaluation follows the latest governed runtime timestamp."""
    no_attempt_service = service(tmp_path / "no-attempt")
    no_attempt_id, _frozen, running = running_experiment(no_attempt_service)
    with pytest.raises(ExperimentIntegrityError, match="latest runtime"):
        no_attempt_service.evaluate(
            no_attempt_id,
            running.digest,
            evaluated_at=FROZEN_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Synthetic null outcome.",
            no_result_artifact_reason="No artifact applies.",
        )

    attempt_service = service(tmp_path / "attempt")
    attempt_id, _frozen, attempt_running = running_experiment(
        attempt_service, runtime_payload()
    )
    attempted = attempt_service.record_attempt(
        attempt_id,
        attempt_running.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=False,
        failed=False,
        exposure_reason="Synthetic runtime exposure.",
    )
    with pytest.raises(ExperimentIntegrityError, match="latest runtime"):
        attempt_service.evaluate(
            attempt_id,
            attempted.digest,
            evaluated_at=STARTED_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Synthetic null outcome.",
            no_result_artifact_reason="No artifact applies.",
        )


def test_evaluate_rejects_submicrosecond_reversal(tmp_path: Path) -> None:
    """Evaluation ordering preserves fractional precision below microseconds."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(
        lifecycle, started_at="2026-09-06T12:03:00.000000900Z"
    )

    with pytest.raises(ExperimentIntegrityError, match="latest runtime"):
        lifecycle.evaluate(
            experiment_id,
            running.digest,
            evaluated_at="2026-09-06T12:03:00.000000100Z",
            outcome=EvaluationOutcome.NULL,
            result_summary="Synthetic null outcome.",
            no_result_artifact_reason="No artifact applies.",
        )


@pytest.mark.parametrize(
    ("started_at", "evaluated_at"),
    [
        (
            "2026-09-06T12:03:00.123456789012Z",
            "2026-09-06T12:03:00.123456789012Z",
        ),
        (
            "2026-09-06T12:03:00.000000100Z",
            "2026-09-06T12:03:00.000000101Z",
        ),
    ],
)
def test_evaluate_accepts_equality_and_one_nanosecond_progress(
    tmp_path: Path, started_at: str, evaluated_at: str
) -> None:
    """Exact equality and one-nanosecond progress are valid evaluation times."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(
        lifecycle, started_at=started_at
    )

    evaluated = lifecycle.evaluate(
        experiment_id,
        running.digest,
        evaluated_at=evaluated_at,
        outcome=EvaluationOutcome.NULL,
        result_summary="Synthetic null outcome.",
        no_result_artifact_reason="No external artifact applies.",
    )
    assert evaluated.record["evaluated_at"] == evaluated_at


def test_evaluation_rejects_corrupted_freeze_evidence(tmp_path: Path) -> None:
    """The transition re-verifies immutable freeze bytes before recording results."""
    lifecycle = service(tmp_path)
    experiment_id, frozen, running = running_experiment(lifecycle)
    digest = cast(str, frozen.record["frozen_manifest_digest"])
    stored = lifecycle.object_store.get(digest)
    stored.path.write_bytes(stored.path.read_bytes() + b" ")

    with pytest.raises(ObjectCorruptionError, match="digest"):
        lifecycle.evaluate(
            experiment_id,
            running.digest,
            evaluated_at=EVALUATED_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Synthetic null outcome.",
            no_result_artifact_reason="No artifact applies.",
        )


def test_evaluation_rejects_rewritten_attempt_history_or_counters(
    tmp_path: Path,
) -> None:
    """A schema-valid counter rewrite cannot become evaluated evidence."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle, runtime_payload())
    attempted = lifecycle.record_attempt(
        experiment_id,
        running.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=True,
        failed=True,
        exposure_reason="Retained synthetic failed AI attempt.",
    )
    payload = revision_payload(attempted)
    payload["variants_attempted"] = 0
    hostile = lifecycle.registry.append(experiment_id, attempted.digest, payload)

    with pytest.raises(ExperimentIntegrityError, match="counters"):
        lifecycle.evaluate(
            experiment_id,
            hostile.digest,
            evaluated_at=EVALUATED_AT,
            outcome=EvaluationOutcome.FAILED,
            result_summary="Synthetic execution failed.",
            no_result_artifact_reason="Failure is retained in the revision.",
            failure_modes=("Synthetic controlled failure.",),
        )


def test_positive_result_artifact_is_verified_and_retained(tmp_path: Path) -> None:
    """Positive evidence references existing immutable result bytes exactly."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle)
    stored = lifecycle.object_store.publish(b"synthetic positive result evidence")
    reference = ResultArtifactReference(
        "https://example.invalid/results/positive.json", stored.digest
    )

    evaluated = lifecycle.evaluate(
        experiment_id,
        running.digest,
        evaluated_at=EVALUATED_AT,
        outcome=EvaluationOutcome.POSITIVE,
        result_summary="Synthetic metric satisfied its declared criterion.",
        result_artifacts=(reference,),
    )

    assert evaluated.record["results"] == (
        "Synthetic metric satisfied its declared criterion."
    )
    assert evaluated.record["result_artifact_digests"] == [stored.digest]
    assert evaluated.record["result_artifact_locations"] == [reference.location]


def test_evaluation_rejects_corrupt_result_artifact(tmp_path: Path) -> None:
    """A supplied result digest must still identify intact immutable object bytes."""
    lifecycle = service(tmp_path)
    experiment_id, _frozen, running = running_experiment(lifecycle)
    stored = lifecycle.object_store.publish(b"synthetic result bytes")
    stored.path.write_bytes(b"corrupted synthetic result bytes")

    with pytest.raises(ObjectCorruptionError, match="digest"):
        lifecycle.evaluate(
            experiment_id,
            running.digest,
            evaluated_at=EVALUATED_AT,
            outcome=EvaluationOutcome.POSITIVE,
            result_summary="Synthetic positive result.",
            result_artifacts=(
                ResultArtifactReference(
                    "https://example.invalid/results/corrupt.json", stored.digest
                ),
            ),
        )
    assert lifecycle.registry.verify_object(experiment_id)[-1] == running


def test_failed_outcome_without_success_artifact_is_retained(tmp_path: Path) -> None:
    """Failure remains permanent even when no successful artifact exists."""
    lifecycle = service(tmp_path)
    experiment_id, running, evaluated = evaluated_experiment(
        lifecycle,
        outcome=EvaluationOutcome.FAILED,
        result_summary="Synthetic evaluation stopped with no successful result.",
        failure_modes=("Synthetic process exited before producing a candidate.",),
    )

    assert evaluated.record["evaluation_outcome"] == "FAILED"
    assert evaluated.record["failure_modes"] == [
        "Synthetic process exited before producing a candidate."
    ]
    assert evaluated.record["result_artifact_digests"] == []
    assert (
        cast(JsonRecord, evaluated.record["result_artifact_locations"])["status"]
        == "NOT_APPLICABLE"
    )
    assert lifecycle.registry.verify_object(experiment_id)[-2] == running


def test_evaluated_evidence_cannot_change_frozen_science(tmp_path: Path) -> None:
    """A hostile EVALUATED revision cannot carry changed preregistration evidence."""
    lifecycle = service(tmp_path)
    experiment_id, _running, evaluated = evaluated_experiment(lifecycle)
    payload = revision_payload(evaluated)
    payload["hypothesis"] = "Rewritten after observing the synthetic result"
    payload["lifecycle_status"] = "DECIDED"
    payload["decided_at"] = DECIDED_AT
    payload["decision"] = "REJECT"
    payload["reason_for_decision"] = "Synthetic hostile decision."
    del payload["decision_pending_reason"]
    hostile = lifecycle.registry.append(experiment_id, evaluated.digest, payload)

    with pytest.raises(ExperimentIntegrityError, match="changed observed or frozen"):
        lifecycle.resolve_rerun(experiment_id)
    assert lifecycle.registry.verify_object(experiment_id)[-1] == hostile


def test_valid_evaluated_to_decided_preserves_all_evidence(tmp_path: Path) -> None:
    """A governed decision appends reason and time without rewriting observations."""
    lifecycle = service(tmp_path)
    experiment_id, _running, evaluated = evaluated_experiment(lifecycle)

    decided = lifecycle.decide(
        experiment_id,
        evaluated.digest,
        decided_at=DECIDED_AT,
        decision=ExperimentDecision.INCONCLUSIVE,
        reason="Synthetic evidence does not support a directional conclusion.",
    )

    assert decided.record["lifecycle_status"] == "DECIDED"
    assert decided.record["decision"] == "INCONCLUSIVE"
    assert decided.record["decided_at"] == DECIDED_AT
    assert decided.record["results"] == evaluated.record["results"]
    assert decided.record["failure_modes"] == evaluated.record["failure_modes"]
    assert decided.record["attempt_records"] == evaluated.record["attempt_records"]
    assert (
        decided.record["sealed_data_release"] == evaluated.record["sealed_data_release"]
    )


def test_decision_rejects_backward_time_invalid_value_and_reason(
    tmp_path: Path,
) -> None:
    """Decision time, vocabulary, and explicit reasoning all fail closed."""
    lifecycle = service(tmp_path)
    experiment_id, _running, evaluated = evaluated_experiment(lifecycle)
    with pytest.raises(ExperimentIntegrityError, match="precedes evaluated_at"):
        lifecycle.decide(
            experiment_id,
            evaluated.digest,
            decided_at=STARTED_AT,
            decision=ExperimentDecision.REJECT,
            reason="Synthetic rejection.",
        )
    with pytest.raises(ExperimentIntegrityError, match="decision is malformed"):
        lifecycle.decide(
            experiment_id,
            evaluated.digest,
            decided_at=DECIDED_AT,
            decision="ACCEPT_FOR_TRADING",
            reason="Invalid synthetic decision.",
        )
    with pytest.raises(ExperimentIntegrityError, match="nonempty"):
        lifecycle.decide(
            experiment_id,
            evaluated.digest,
            decided_at=DECIDED_AT,
            decision=ExperimentDecision.DEFER,
            reason="   ",
        )
    assert lifecycle.registry.verify_object(experiment_id)[-1] == evaluated


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("results", "Rewritten observed result"),
        ("failure_modes", ["Invented later failure"]),
        ("variants_attempted", 1),
        (
            "attempt_records",
            [
                {
                    "attempt_number": 1,
                    "experiment_id": f"EXP-{EXPERIMENT_UUID}",
                    "recorded_at": ATTEMPT_AT,
                    "ai_generated": False,
                    "failed": False,
                    "exposure_reason": "Invented later attempt.",
                }
            ],
        ),
        ("hypothesis", "Rewritten frozen hypothesis"),
        ("configuration_digest", "sha256:" + "e" * 64),
        ("sealed_data_release", {"status": "UNRELEASED", "reason": "Rewritten"}),
    ],
)
def test_decided_revision_cannot_rewrite_prior_evidence(
    tmp_path: Path, field: str, value: JsonValue
) -> None:
    """Decision verification rejects observed, attempt, science, or release rewrites."""
    lifecycle = service(tmp_path)
    experiment_id, _running, evaluated = evaluated_experiment(lifecycle)
    payload = revision_payload(evaluated)
    payload["lifecycle_status"] = "DECIDED"
    payload["decided_at"] = DECIDED_AT
    payload["decision"] = "REJECT"
    payload["reason_for_decision"] = "Synthetic hostile decision."
    payload.pop("decision_pending_reason", None)
    payload[field] = deepcopy(value)
    hostile = lifecycle.registry.append(experiment_id, evaluated.digest, payload)

    with pytest.raises(ExperimentIntegrityError, match="changed observed or frozen"):
        lifecycle.resolve_rerun(experiment_id)
    assert lifecycle.registry.verify_object(experiment_id)[-1] == hostile


def test_decided_cannot_repeat_or_transition_backward(tmp_path: Path) -> None:
    """A terminal decision cannot be repeated or relabelled as evaluation."""
    lifecycle = service(tmp_path)
    experiment_id, _running, evaluated = evaluated_experiment(lifecycle)
    decided = lifecycle.decide(
        experiment_id,
        evaluated.digest,
        decided_at=DECIDED_AT,
        decision=ExperimentDecision.DEFER,
        reason="Synthetic research is deferred.",
    )

    with pytest.raises(InvalidExperimentTransitionError, match="DECIDED to DECIDED"):
        lifecycle.decide(
            experiment_id,
            decided.digest,
            decided_at=DECIDED_AT,
            decision=ExperimentDecision.REJECT,
            reason="Repeated synthetic decision.",
        )
    with pytest.raises(InvalidExperimentTransitionError, match="DECIDED to EVALUATED"):
        lifecycle.evaluate(
            experiment_id,
            decided.digest,
            evaluated_at=DECIDED_AT,
            outcome=EvaluationOutcome.NULL,
            result_summary="Backward synthetic evaluation.",
            no_result_artifact_reason="No artifact applies.",
        )


def test_rerun_resolution_is_stable_and_excludes_results_and_decisions(
    tmp_path: Path,
) -> None:
    """Lifecycle outcomes never become deterministic rerun input parameters."""
    lifecycle = service(tmp_path)
    experiment_id, _registered, frozen = frozen_experiment(lifecycle)
    frozen_resolution = lifecycle.resolve_rerun(experiment_id)
    assert lifecycle.resolve_rerun(experiment_id) == frozen_resolution

    running = lifecycle.start(experiment_id, frozen.digest, started_at=STARTED_AT)
    evaluated = lifecycle.evaluate(
        experiment_id,
        running.digest,
        evaluated_at=EVALUATED_AT,
        outcome=EvaluationOutcome.NEGATIVE,
        result_summary="Synthetic observed result that is not a rerun input.",
        no_result_artifact_reason="The result is retained in the registry revision.",
        failure_modes=("Synthetic criterion was not met.",),
    )
    lifecycle.decide(
        experiment_id,
        evaluated.digest,
        decided_at=DECIDED_AT,
        decision=ExperimentDecision.REJECT,
        reason="Synthetic observed evidence did not satisfy the criterion.",
    )
    decided_resolution = lifecycle.resolve_rerun(experiment_id)

    assert decided_resolution == frozen_resolution
    assert decided_resolution.digest == sha256_bytes(decided_resolution.canonical_bytes)
    document = decided_resolution.document
    assert (
        document["registered_revision_digest"]
        == frozen_resolution.document["registered_revision_digest"]
    )
    assert "results" not in document
    assert "decision" not in document


def test_rerun_resolution_rejects_incomplete_and_corrupt_registered_history(
    tmp_path: Path,
) -> None:
    """Resolution requires FROZEN authority and an intact REGISTERED chain link."""
    draft_service = service(tmp_path / "draft")
    draft = draft_service.create_draft(
        planned_payload(), created_at=CREATED_AT, uuid_factory=lambda: EXPERIMENT_UUID
    )
    with pytest.raises(RerunResolutionError, match="FROZEN or later"):
        draft_service.resolve_rerun(draft.object_id)

    corrupt_service = service(tmp_path / "corrupt")
    experiment_id, registered, _frozen = frozen_experiment(corrupt_service)
    damaged = deepcopy(registered.record)
    damaged["configuration_digest"] = "sha256:" + "e" * 64
    registered.path.write_bytes(canonicalize_json(damaged))
    with pytest.raises(RegistryIntegrityError, match="previous-revision"):
        corrupt_service.resolve_rerun(experiment_id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("configuration_digest", "sha256:" + "d" * 64),
        ("environment_digest", "sha256:" + "d" * 64),
        ("provenance_artifact_digests", ["sha256:" + "d" * 64]),
    ],
)
def test_rerun_resolution_rejects_changed_frozen_input_evidence(
    tmp_path: Path, field: str, value: JsonValue
) -> None:
    """Configuration, environment, and data bindings must match REGISTERED evidence."""
    lifecycle = service(tmp_path)
    experiment_id, _registered, frozen = frozen_experiment(lifecycle)
    damaged = deepcopy(frozen.record)
    damaged[field] = deepcopy(value)
    frozen.path.write_bytes(canonicalize_json(damaged))

    with pytest.raises(ExperimentIntegrityError, match="scientific evidence"):
        lifecycle.resolve_rerun(experiment_id)


def test_rerun_resolution_rejects_corrupt_freeze_object(tmp_path: Path) -> None:
    """Resolution fails if the immutable freeze manifest bytes no longer verify."""
    lifecycle = service(tmp_path)
    experiment_id, _registered, frozen = frozen_experiment(lifecycle)
    digest = cast(str, frozen.record["frozen_manifest_digest"])
    stored = lifecycle.object_store.get(digest)
    stored.path.write_bytes(stored.path.read_bytes() + b" ")

    with pytest.raises(ObjectCorruptionError, match="digest"):
        lifecycle.resolve_rerun(experiment_id)


def test_evaluation_decision_and_rerun_never_read_sealed_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 8C preserves release metadata without dereferencing sealed content."""
    lifecycle = service(tmp_path)
    sealed_path = (tmp_path / "sealed" / "holdout.bin").resolve()
    payload = runtime_payload()
    experiment_id, _draft, registered = registered_experiment(lifecycle, payload)
    frozen = lifecycle.freeze(
        experiment_id,
        registered.digest,
        frozen_at=FROZEN_AT,
        data_manifests=data_manifests(payload, reference=sealed_path.as_uri()),
    )
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == sealed_path:
            raise AssertionError("sealed data was accessed")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    running = lifecycle.start(
        experiment_id, frozen.revision.digest, started_at=STARTED_AT
    )
    evaluated = lifecycle.evaluate(
        experiment_id,
        running.digest,
        evaluated_at=EVALUATED_AT,
        outcome=EvaluationOutcome.NULL,
        result_summary="Synthetic result retained without sealed content.",
        no_result_artifact_reason="No external artifact applies.",
    )
    lifecycle.decide(
        experiment_id,
        evaluated.digest,
        decided_at=DECIDED_AT,
        decision=ExperimentDecision.INCONCLUSIVE,
        reason="Synthetic evidence is inconclusive.",
    )
    resolution = lifecycle.resolve_rerun(experiment_id)

    assert resolution.document["data_manifests"] == [
        {
            "digest": cast(list[str], payload["provenance_artifact_digests"])[0],
            "reference": sealed_path.as_uri(),
        }
    ]
    assert not sealed_path.exists()
