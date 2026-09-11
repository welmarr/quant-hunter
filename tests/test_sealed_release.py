"""Hostile synthetic tests for the Stage 1B Item 10A sealed-release core."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from test_experiment_lifecycle import (
    ATTEMPT_AT,
    CREATED_AT,
    DECIDED_AT,
    EVALUATED_AT,
    FROZEN_AT,
    REGISTERED_AT,
    STARTED_AT,
    data_manifests,
    planned_payload,
    registered_experiment,
    runtime_payload,
    service,
)

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.experiments import (
    EvaluationOutcome,
    ExperimentDecision,
    ExperimentIntegrityError,
    ExperimentLifecycleService,
    PostReleaseSearchError,
)
from quant_hunter.identity.registry import RegistryError
from quant_hunter.isolation import (
    EnforcementMode,
    ExposureAlreadyRecordedError,
    ExposureFailurePoint,
    ExposureIncidentRequest,
    ExposureLedger,
    ExposureLedgerError,
    ExposureLedgerIntegrityError,
    ExposureLedgerStaleWriterError,
    ExposureState,
    ReleaseRequest,
    SealedBinding,
    SealedReleaseService,
    UnsupportedEnforcementModeError,
    release_event_digest,
    verify_release_event_digest,
)
from quant_hunter.storage import ObjectStoreError, SensitiveMetadataError

SCHEMA_DIRECTORY = Path(__file__).parents[1] / "schemas" / "v1"
RELEASED_AT = "2026-09-06T12:02:00.000000001Z"
SECOND_EXPERIMENT_ID = "EXP-01990f30-7f5e-7b34-9b21-3d74c513d60b"
FIRST_DATASET_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c842"
SECOND_DATASET_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513d701"
THIRD_DATASET_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513d702"


@dataclass(frozen=True, slots=True)
class ReleaseHarness:
    lifecycle: ExperimentLifecycleService
    ledger: ExposureLedger
    release_service: SealedReleaseService
    experiment_id: str
    frozen_digest: str
    frozen_record: JsonRecord
    binding: SealedBinding
    request: ReleaseRequest


def _multiple_dataset_payload() -> JsonRecord:
    payload = runtime_payload()
    first_dataset = cast(list[str], payload["dataset_ids"])[0]
    payload["dataset_ids"] = cast(
        list[JsonValue], sorted([first_dataset, SECOND_DATASET_ID])
    )
    vintages = cast(list[JsonValue], payload["dataset_vintages"])
    vintages.append(
        {
            "dataset_id": SECOND_DATASET_ID,
            "record_digest": "sha256:" + "7" * 64,
            "vintage": "synthetic-v2",
        }
    )
    return payload


def _payload_for_footprint(
    dataset_ids: tuple[str, ...], start: str, end: str
) -> JsonRecord:
    payload = runtime_payload()
    payload["dataset_ids"] = cast(list[JsonValue], sorted(dataset_ids))
    payload["dataset_vintages"] = cast(
        list[JsonValue],
        [
            {
                "dataset_id": dataset_id,
                "record_digest": "sha256:" + str(index + 3) * 64,
                "vintage": f"synthetic-v{index + 1}",
            }
            for index, dataset_id in enumerate(sorted(dataset_ids))
        ],
    )
    partitions = cast(JsonRecord, payload["partitions"])
    partitions["sealed_out_of_sample"] = {"start": start, "end": end}
    return payload


def _build_harness(
    tmp_path: Path,
    *,
    payload: JsonRecord | None = None,
    experiment_uuid: UUID | None = None,
    ledger: ExposureLedger | None = None,
) -> ReleaseHarness:
    lifecycle = service(tmp_path)
    payload = payload or _multiple_dataset_payload()
    if experiment_uuid is None:
        experiment_id, _draft, registered = registered_experiment(lifecycle, payload)
    else:
        draft = lifecycle.create_draft(
            payload, created_at=CREATED_AT, uuid_factory=lambda: experiment_uuid
        )
        experiment_id = draft.object_id
        registered = lifecycle.register(
            experiment_id, draft.revision.digest, registered_at=REGISTERED_AT
        )
    frozen = lifecycle.freeze(
        experiment_id,
        registered.digest,
        frozen_at=FROZEN_AT,
        data_manifests=data_manifests(payload),
    )
    frozen_record = deepcopy(frozen.revision.record)
    dataset_ids = tuple(sorted(cast(list[str], frozen_record["dataset_ids"])))
    partitions = cast(JsonRecord, frozen_record["partitions"])
    sealed = cast(JsonRecord, partitions["sealed_out_of_sample"])
    binding = SealedBinding(
        dataset_ids,
        cast(str, sealed["start"]),
        cast(str, sealed["end"]),
    )
    ledger = ledger or ExposureLedger(
        (tmp_path / "release-ledger").resolve(), SCHEMA_DIRECTORY
    )
    release_service = SealedReleaseService(lifecycle, ledger, lifecycle.object_store)
    artifact = lifecycle.object_store.publish(b"synthetic released OOS fixture")
    request = ReleaseRequest(
        experiment_id=experiment_id,
        frozen_revision_digest=frozen.revision.digest,
        frozen_manifest_digest=cast(str, frozen_record["frozen_manifest_digest"]),
        sealed_binding=binding,
        code_revision=cast(str, frozen_record["code_revision"]),
        configuration_digest=cast(str, frozen_record["configuration_digest"]),
        environment_digest=cast(str, frozen_record["environment_digest"]),
        occurred_at=RELEASED_AT,
        actor="synthetic-custodian",
        reason="Release the fixed synthetic partition for prespecified evaluation.",
        released_artifact_digest=artifact.digest,
    )
    return ReleaseHarness(
        lifecycle,
        ledger,
        release_service,
        experiment_id,
        frozen.revision.digest,
        frozen_record,
        binding,
        request,
    )


@pytest.fixture
def harness(tmp_path: Path) -> ReleaseHarness:
    return _build_harness(tmp_path)


def _incident(
    *,
    experiment_id: str = SECOND_EXPERIMENT_ID,
    dataset_id: str = THIRD_DATASET_ID,
) -> ExposureIncidentRequest:
    return ExposureIncidentRequest(
        experiment_id=experiment_id,
        sealed_binding=SealedBinding(
            (dataset_id,), "2022-01-01T00:00:00Z", "2022-02-01T00:00:00Z"
        ),
        occurred_at="2026-09-06T12:04:00Z",
        actor="synthetic-observer",
        reason="Synthetic confidentiality loss was observed.",
        failure_point=ExposureFailurePoint.UNAUTHORIZED_ACCESS,
    )


def _write_event(path: Path, record: JsonRecord) -> None:
    path.write_bytes(canonicalize_json(record))


def _replace_request(
    request: ReleaseRequest, field: str, value: object
) -> ReleaseRequest:
    return replace(request, **cast(Any, {field: value}))


def test_exposure_ledger_has_no_public_raw_append_api(
    harness: ReleaseHarness,
) -> None:
    """Structural ledger access cannot manufacture either exposure event type."""
    assert not hasattr(ExposureLedger, "append_event")
    assert not hasattr(harness.ledger, "append_event")


@pytest.mark.parametrize("event_type", ["AUTHORIZED_RELEASE", "ACCIDENTAL_EXPOSURE"])
def test_raw_exposure_event_cannot_use_a_public_ledger_writer(
    harness: ReleaseHarness, event_type: str
) -> None:
    """Arbitrary mappings have no supported public route into the ledger."""
    raw_event: JsonRecord = {
        "schema_version": "1.0.0",
        "event_type": event_type,
        "experiment_id": SECOND_EXPERIMENT_ID,
        "sealed_binding": harness.binding.as_record(),
        "occurred_at": RELEASED_AT,
        "actor": "synthetic-raw-caller",
        "reason": "This synthetic raw write must remain unsupported.",
        "released_artifact_digest": "sha256:" + "a" * 64,
        "released_artifact_reference": "object://sha256/" + "a" * 64,
        "frozen_revision_digest": "sha256:" + "b" * 64,
        "frozen_manifest_digest": "sha256:" + "c" * 64,
        "code_revision": "d" * 40,
        "configuration_digest": "sha256:" + "e" * 64,
        "environment_digest": "sha256:" + "f" * 64,
        "source_partition_status": "EXPOSED",
        "enforcement_mode": "SYNTHETIC_TEST",
    }
    public_writer_name = "append_" + "event"
    with pytest.raises(AttributeError):
        getattr(harness.ledger, public_writer_name)(
            raw_event, expected_previous_digest=None
        )
    assert harness.ledger.verify() == ()


def test_nonexistent_experiment_cannot_authorize_through_supported_writer(
    harness: ReleaseHarness,
) -> None:
    """The sole release writer rejects invented authority before ledger append."""
    request = replace(
        harness.request,
        experiment_id=SECOND_EXPERIMENT_ID,
        frozen_revision_digest="sha256:" + "a" * 64,
        frozen_manifest_digest="sha256:" + "b" * 64,
        released_artifact_digest="sha256:" + "c" * 64,
    )
    with pytest.raises(RegistryError):
        harness.release_service.authorize_release(request, expected_ledger_head=None)
    assert harness.ledger.verify() == ()


def test_empty_ledger_and_genesis_release(harness: ReleaseHarness) -> None:
    """An empty ledger is explicit and the first event has a null prior digest."""
    assert harness.ledger.verify() == ()
    assert harness.ledger.head_digest() is None
    evidence = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    event = evidence.record
    assert event["ledger_sequence"] == 1
    assert event["previous_event_digest"] is None
    assert event["source_partition_status"] == ExposureState.EXPOSED.value
    assert event["sealed_binding"] == harness.binding.as_record()
    binding = event["sealed_binding"]
    assert isinstance(binding, dict)
    dataset_ids = binding["dataset_ids"]
    assert isinstance(dataset_ids, list)
    assert tuple(dataset_ids) == tuple(sorted(harness.binding.dataset_ids))
    assert harness.ledger.head_digest() == evidence.event_digest


@pytest.mark.parametrize("state", ["DRAFT", "REGISTERED"])
def test_release_rejects_pre_frozen_experiment(tmp_path: Path, state: str) -> None:
    """DRAFT and REGISTERED experiments cannot authorize sealed release."""
    lifecycle = service(tmp_path)
    draft = lifecycle.create_draft(planned_payload(), created_at="2026-09-06T12:00:00Z")
    head = draft.revision
    if state == "REGISTERED":
        head = lifecycle.register(
            draft.object_id, draft.revision.digest, registered_at="2026-09-06T12:01:00Z"
        )
    ledger = ExposureLedger((tmp_path / "ledger").resolve(), SCHEMA_DIRECTORY)
    release_service = SealedReleaseService(lifecycle, ledger, lifecycle.object_store)
    artifact = lifecycle.object_store.publish(b"synthetic released bytes")
    payload = planned_payload()
    partition = cast(
        JsonRecord, cast(JsonRecord, payload["partitions"])["sealed_out_of_sample"]
    )
    request = ReleaseRequest(
        experiment_id=draft.object_id,
        frozen_revision_digest=head.digest,
        frozen_manifest_digest="sha256:" + "1" * 64,
        sealed_binding=SealedBinding(
            tuple(cast(list[str], payload["dataset_ids"])),
            cast(str, partition["start"]),
            cast(str, partition["end"]),
        ),
        code_revision=cast(str, payload["code_revision"]),
        configuration_digest=cast(str, payload["configuration_digest"]),
        environment_digest=cast(str, payload["environment_digest"]),
        occurred_at=RELEASED_AT,
        actor="synthetic-custodian",
        reason="Synthetic pre-freeze release must fail.",
        released_artifact_digest=artifact.digest,
    )
    with pytest.raises(ExperimentIntegrityError, match="head is not FROZEN"):
        release_service.authorize_release(request, expected_ledger_head=None)
    assert ledger.verify() == ()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("experiment_id", SECOND_EXPERIMENT_ID, None),
        ("frozen_revision_digest", "sha256:" + "1" * 64, "frozen revision"),
        ("frozen_manifest_digest", "sha256:" + "2" * 64, "freeze manifest"),
        ("code_revision", "b" * 40, "code_revision"),
        ("configuration_digest", "sha256:" + "5" * 64, "configuration_digest"),
        ("environment_digest", "sha256:" + "4" * 64, "environment_digest"),
        (
            "sealed_binding",
            SealedBinding(
                (THIRD_DATASET_ID,),
                "2020-01-03T00:00:00Z",
                "2020-01-03T23:59:59Z",
            ),
            "dataset identities",
        ),
        (
            "sealed_binding",
            SealedBinding(
                (
                    "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c842",
                    SECOND_DATASET_ID,
                ),
                "2020-01-03T00:00:01Z",
                "2020-01-03T23:59:59Z",
            ),
            "sealed partition",
        ),
        ("occurred_at", "2026-09-06T12:01:59.999999999Z", "precedes frozen"),
    ],
)
def test_release_rejects_mixed_or_inexact_frozen_authority(
    harness: ReleaseHarness, field: str, value: object, message: str | None
) -> None:
    """Well-formed evidence from a wrong experiment or frozen input fails closed."""
    request = _replace_request(harness.request, field, value)
    expected: type[BaseException] | tuple[type[BaseException], ...]
    expected = (ExperimentIntegrityError, RegistryError)
    with pytest.raises(expected, match=message):
        harness.release_service.authorize_release(request, expected_ledger_head=None)
    assert harness.ledger.verify() == ()


def test_release_rejects_missing_or_wrong_released_artifact(
    harness: ReleaseHarness,
) -> None:
    """A syntactically valid digest must identify intact released bytes."""
    request = replace(harness.request, released_artifact_digest="sha256:" + "9" * 64)
    with pytest.raises(ObjectStoreError, match="does not exist"):
        harness.release_service.authorize_release(request, expected_ledger_head=None)
    assert harness.ledger.verify() == ()


def test_event_digest_is_deterministic_permutation_stable_and_chained() -> None:
    """RFC 8785 identity excludes only event_digest and includes the prior digest."""
    body: JsonRecord = {
        "schema_version": "1.0.0",
        "event_type": "AUTHORIZED_RELEASE",
        "ledger_sequence": 2,
        "previous_event_digest": "sha256:" + "1" * 64,
        "experiment_id": SECOND_EXPERIMENT_ID,
        "reason": "Synthetic digest vector.",
    }
    permuted = dict(reversed(tuple(body.items())))
    assert release_event_digest(body) == release_event_digest(body)
    assert release_event_digest(body) == release_event_digest(permuted)
    changed_previous = deepcopy(body)
    changed_previous["previous_event_digest"] = "sha256:" + "2" * 64
    assert release_event_digest(changed_previous) != release_event_digest(body)
    with_digest = deepcopy(body)
    with_digest["event_digest"] = release_event_digest(body)
    verify_release_event_digest(with_digest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reason", "Mutated synthetic reason."),
        ("event_digest", "sha256:" + "f" * 64),
        ("previous_event_digest", "sha256:" + "e" * 64),
        ("experiment_id", SECOND_EXPERIMENT_ID),
        ("frozen_revision_digest", "sha256:" + "d" * 64),
        ("frozen_manifest_digest", "sha256:" + "c" * 64),
        (
            "sealed_binding",
            {
                "dataset_ids": [THIRD_DATASET_ID],
                "sealed_out_of_sample": {
                    "start": "2020-01-03T00:00:00Z",
                    "end": "2020-01-03T23:59:59Z",
                },
            },
        ),
        ("occurred_at", "2026-09-06T12:05:00Z"),
        ("released_artifact_digest", "sha256:" + "b" * 64),
        ("enforcement_mode", "HOST_ENFORCED"),
    ],
)
def test_ledger_rejects_every_security_identity_tamper(
    harness: ReleaseHarness, field: str, value: JsonValue
) -> None:
    """Mutation of any security binding invalidates retained release evidence."""
    evidence = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    event = deepcopy(evidence.record)
    event[field] = value
    _write_event(harness.ledger.verify()[0].path, event)
    with pytest.raises(ExposureLedgerError):
        harness.ledger.verify()


def test_valid_chain_append_and_stale_writer_rejection(
    harness: ReleaseHarness,
) -> None:
    """CAS serializes later exposure evidence against the exact accepted head."""
    release = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    with pytest.raises(ExposureLedgerStaleWriterError):
        harness.release_service.record_accidental_exposure(
            _incident(), expected_ledger_head=None
        )
    incident = harness.release_service.record_accidental_exposure(
        _incident(), expected_ledger_head=release.event_digest
    )
    events = harness.ledger.verify()
    assert [event.sequence for event in events] == [1, 2]
    assert incident.record["previous_event_digest"] == release.event_digest


def test_concurrent_competing_append_cannot_fork(tmp_path: Path) -> None:
    """Only one writer can consume an expected head under controlled contention."""
    lifecycle = service(tmp_path)
    ledger = ExposureLedger((tmp_path / "ledger").resolve(), SCHEMA_DIRECTORY)
    release_service = SealedReleaseService(lifecycle, ledger, lifecycle.object_store)
    requests = (
        _incident(dataset_id=SECOND_DATASET_ID),
        _incident(dataset_id=THIRD_DATASET_ID),
    )

    def append(request: ExposureIncidentRequest) -> object:
        try:
            return release_service.record_accidental_exposure(
                request, expected_ledger_head=None
            )
        except ExposureLedgerStaleWriterError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, requests))
    assert (
        sum(isinstance(result, ExposureLedgerStaleWriterError) for result in results)
        == 1
    )
    assert len(ledger.verify()) == 1


def test_missing_reordered_corrupt_and_truncated_history_is_rejected(
    harness: ReleaseHarness,
) -> None:
    """Contiguity, event bytes, order, and the independent head anchor fail closed."""
    release = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    harness.release_service.record_accidental_exposure(
        _incident(), expected_ledger_head=release.event_digest
    )
    paths = [event.path for event in harness.ledger.verify()]
    original = [path.read_bytes() for path in paths]

    paths[0].unlink()
    with pytest.raises(ExposureLedgerIntegrityError, match="noncontiguous"):
        harness.ledger.verify()
    paths[0].write_bytes(original[0])

    temporary = paths[0].with_suffix(".swap")
    paths[0].replace(temporary)
    paths[1].replace(paths[0])
    temporary.replace(paths[1])
    with pytest.raises(ExposureLedgerIntegrityError, match="order"):
        harness.ledger.verify()
    paths[0].write_bytes(original[0])
    paths[1].write_bytes(original[1])

    paths[0].write_bytes(b"{not-json")
    with pytest.raises(ExposureLedgerIntegrityError, match="strict JSON"):
        harness.ledger.verify()
    paths[0].write_bytes(original[0])

    paths[1].unlink()
    with pytest.raises(ExposureLedgerIntegrityError, match="head anchor"):
        harness.ledger.verify()


def test_duplicate_release_is_rejected_without_overwrite(
    harness: ReleaseHarness,
) -> None:
    """The same frozen binding cannot create a second event or overwrite the first."""
    first = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    first_bytes = first._event.path.read_bytes()
    with pytest.raises(ExposureAlreadyRecordedError):
        harness.release_service.authorize_release(
            harness.request, expected_ledger_head=first.event_digest
        )
    assert first._event.path.read_bytes() == first_bytes
    assert harness.ledger.verify() == (first._event,)


def test_accidental_exposure_is_irreversible_and_blocks_pristine_release(
    harness: ReleaseHarness,
) -> None:
    """An incident permanently exposes the binding and cannot be cured by release."""
    incident = harness.release_service.record_accidental_exposure(
        ExposureIncidentRequest(
            experiment_id=harness.experiment_id,
            sealed_binding=harness.binding,
            occurred_at="2026-09-06T12:01:00Z",
            actor="synthetic-observer",
            reason="Synthetic pre-freeze confidentiality loss.",
            failure_point=ExposureFailurePoint.PRE_FREEZE_ACCESS,
        ),
        expected_ledger_head=None,
    )
    assert (
        harness.release_service.exposure_state(harness.binding) is ExposureState.EXPOSED
    )
    assert incident.record["review_requirement"] == "INVALIDATION_RISK_DECISION_REVIEW"
    with pytest.raises(ExposureAlreadyRecordedError):
        harness.release_service.authorize_release(
            harness.request, expected_ledger_head=incident.digest
        )
    assert harness.ledger.verify() == (incident,)


@pytest.mark.parametrize(
    ("exposed_interval", "candidate_interval"),
    [
        (
            ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ),
        (
            ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            ("2025-03-01T00:00:00Z", "2025-06-01T00:00:00Z"),
        ),
        (
            ("2025-03-01T00:00:00Z", "2025-06-01T00:00:00Z"),
            ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ),
        (
            ("2025-01-01T00:00:00Z", "2025-07-01T00:00:00Z"),
            ("2025-06-01T00:00:00Z", "2025-12-01T00:00:00Z"),
        ),
        (
            ("2025-01-01T00:00:00Z", "2025-01-01T00:00:01.000000001Z"),
            ("2025-01-01T00:00:01Z", "2025-01-01T00:00:02Z"),
        ),
    ],
)
def test_global_exposure_rejects_cross_experiment_temporal_overlap(
    tmp_path: Path,
    exposed_interval: tuple[str, str],
    candidate_interval: tuple[str, str],
) -> None:
    """Any same-dataset overlap is exposed regardless of experiment identity."""
    ledger = ExposureLedger((tmp_path / "ledger").resolve(), SCHEMA_DIRECTORY)
    first = _build_harness(
        tmp_path / "first",
        payload=_payload_for_footprint((FIRST_DATASET_ID,), *exposed_interval),
        ledger=ledger,
    )
    second = _build_harness(
        tmp_path / "second",
        payload=_payload_for_footprint((FIRST_DATASET_ID,), *candidate_interval),
        experiment_uuid=UUID(SECOND_EXPERIMENT_ID.removeprefix("EXP-")),
        ledger=ledger,
    )
    release = first.release_service.authorize_release(
        first.request, expected_ledger_head=None
    )
    assert first.experiment_id != second.experiment_id
    assert (
        second.release_service.exposure_state(second.binding) is ExposureState.EXPOSED
    )
    with pytest.raises(ExposureAlreadyRecordedError, match="already EXPOSED"):
        second.release_service.authorize_release(
            second.request, expected_ledger_head=release.event_digest
        )
    assert ledger.verify() == (release._event,)


def test_fractional_adjacency_and_different_dataset_remain_independent(
    tmp_path: Path,
) -> None:
    """Equivalent fractional boundaries are adjacent; other datasets do not conflict."""
    ledger = ExposureLedger((tmp_path / "ledger").resolve(), SCHEMA_DIRECTORY)
    first = _build_harness(
        tmp_path / "first",
        payload=_payload_for_footprint(
            (FIRST_DATASET_ID,),
            "2025-01-01T00:00:00Z",
            "2025-01-01T00:00:01.1Z",
        ),
        ledger=ledger,
    )
    adjacent = _build_harness(
        tmp_path / "adjacent",
        payload=_payload_for_footprint(
            (FIRST_DATASET_ID,),
            "2025-01-01T00:00:01.100000000Z",
            "2025-01-01T00:00:02Z",
        ),
        experiment_uuid=UUID(SECOND_EXPERIMENT_ID.removeprefix("EXP-")),
        ledger=ledger,
    )
    first_release = first.release_service.authorize_release(
        first.request, expected_ledger_head=None
    )
    assert (
        adjacent.release_service.exposure_state(adjacent.binding)
        is ExposureState.UNEXPOSED
    )
    adjacent_release = adjacent.release_service.authorize_release(
        adjacent.request, expected_ledger_head=first_release.event_digest
    )

    independent = SealedBinding(
        (SECOND_DATASET_ID,),
        "2025-01-01T00:00:00Z",
        "2025-01-01T00:00:01.1Z",
    )
    assert (
        adjacent.release_service.exposure_state(independent) is ExposureState.UNEXPOSED
    )
    assert len(ledger.verify()) == 2
    assert (
        adjacent_release.record["previous_event_digest"] == first_release.event_digest
    )


@pytest.mark.parametrize(
    ("exposed_ids", "candidate_ids"),
    [
        ((FIRST_DATASET_ID, SECOND_DATASET_ID), (SECOND_DATASET_ID,)),
        ((FIRST_DATASET_ID,), (FIRST_DATASET_ID, SECOND_DATASET_ID)),
    ],
)
def test_any_overlapping_multi_dataset_component_blocks_release(
    tmp_path: Path,
    exposed_ids: tuple[str, ...],
    candidate_ids: tuple[str, ...],
) -> None:
    """A composite binding is compromised when any one dataset component overlaps."""
    interval = ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    ledger = ExposureLedger((tmp_path / "ledger").resolve(), SCHEMA_DIRECTORY)
    first = _build_harness(
        tmp_path / "first",
        payload=_payload_for_footprint(exposed_ids, *interval),
        ledger=ledger,
    )
    second = _build_harness(
        tmp_path / "second",
        payload=_payload_for_footprint(candidate_ids, *interval),
        experiment_uuid=UUID(SECOND_EXPERIMENT_ID.removeprefix("EXP-")),
        ledger=ledger,
    )
    release = first.release_service.authorize_release(
        first.request, expected_ledger_head=None
    )
    with pytest.raises(ExposureAlreadyRecordedError):
        second.release_service.authorize_release(
            second.request, expected_ledger_head=release.event_digest
        )


def test_cross_experiment_incident_blocks_overlapping_release(tmp_path: Path) -> None:
    """Incident evidence exposes the data footprint globally before authorization."""
    candidate = _build_harness(
        tmp_path,
        payload=_payload_for_footprint(
            (FIRST_DATASET_ID,),
            "2025-03-01T00:00:00Z",
            "2025-06-01T00:00:00Z",
        ),
    )
    incident = candidate.release_service.record_accidental_exposure(
        ExposureIncidentRequest(
            experiment_id=SECOND_EXPERIMENT_ID,
            sealed_binding=SealedBinding(
                (FIRST_DATASET_ID,),
                "2025-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
            occurred_at="2026-09-06T12:01:00Z",
            actor="synthetic-observer",
            reason="Synthetic cross-experiment confidentiality loss.",
            failure_point=ExposureFailurePoint.PRE_FREEZE_ACCESS,
        ),
        expected_ledger_head=None,
    )
    with pytest.raises(ExposureAlreadyRecordedError):
        candidate.release_service.authorize_release(
            candidate.request, expected_ledger_head=incident.digest
        )
    assert candidate.ledger.verify() == (incident,)


def test_incidents_remain_appendable_after_release_and_do_not_restore_pristine(
    tmp_path: Path,
) -> None:
    """Later and repeated incidents remain permanent without another state change."""
    harness = _build_harness(
        tmp_path,
        payload=_payload_for_footprint(
            (FIRST_DATASET_ID,),
            "2025-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    release = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    same = harness.release_service.record_accidental_exposure(
        ExposureIncidentRequest(
            experiment_id=SECOND_EXPERIMENT_ID,
            sealed_binding=harness.binding,
            occurred_at="2026-09-06T12:04:00Z",
            actor="synthetic-observer",
            reason="Synthetic later unauthorized access.",
            failure_point=ExposureFailurePoint.UNAUTHORIZED_ACCESS,
        ),
        expected_ledger_head=release.event_digest,
    )
    subset_binding = SealedBinding(
        (FIRST_DATASET_ID,),
        "2025-03-01T00:00:00Z",
        "2025-06-01T00:00:00Z",
    )
    subset = harness.release_service.record_accidental_exposure(
        ExposureIncidentRequest(
            experiment_id=harness.experiment_id,
            sealed_binding=subset_binding,
            occurred_at="2026-09-06T12:05:00Z",
            actor="synthetic-observer",
            reason="Synthetic overlapping incident evidence.",
            failure_point=ExposureFailurePoint.PARTIAL_RELEASE_FAILURE,
        ),
        expected_ledger_head=same.digest,
    )
    repeated = harness.release_service.record_accidental_exposure(
        ExposureIncidentRequest(
            experiment_id=harness.experiment_id,
            sealed_binding=subset_binding,
            occurred_at="2026-09-06T12:06:00Z",
            actor="synthetic-reviewer",
            reason="Synthetic distinct follow-up incident evidence.",
            failure_point=ExposureFailurePoint.OTHER,
        ),
        expected_ledger_head=subset.digest,
    )
    assert len(harness.ledger.verify()) == 4
    assert (
        harness.release_service.exposure_state(subset_binding) is ExposureState.EXPOSED
    )
    with pytest.raises(ExposureAlreadyRecordedError):
        harness.release_service.authorize_release(
            replace(
                harness.request,
                occurred_at="2026-09-06T12:07:00Z",
            ),
            expected_ledger_head=repeated.digest,
        )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
        ("2025-01-01T00:00:00.000000001Z", "2025-01-01T00:00:00Z"),
    ],
)
def test_empty_or_reversed_exposure_interval_is_rejected(
    harness: ReleaseHarness, start: str, end: str
) -> None:
    """Every exposure footprint is a valid nonempty half-open UTC interval."""
    with pytest.raises(ExposureLedgerIntegrityError, match="half-open"):
        harness.release_service.record_accidental_exposure(
            replace(
                _incident(dataset_id=FIRST_DATASET_ID),
                sealed_binding=SealedBinding((FIRST_DATASET_ID,), start, end),
            ),
            expected_ledger_head=None,
        )


def test_full_verification_rejects_resigned_overlapping_release_history(
    tmp_path: Path,
) -> None:
    """A locally resigned event cannot hide an illegal second state transition."""
    ledger = ExposureLedger((tmp_path / "ledger").resolve(), SCHEMA_DIRECTORY)
    first = _build_harness(
        tmp_path / "first",
        payload=_payload_for_footprint(
            (FIRST_DATASET_ID,),
            "2025-01-01T00:00:00Z",
            "2025-02-01T00:00:00Z",
        ),
        ledger=ledger,
    )
    second = _build_harness(
        tmp_path / "second",
        payload=_payload_for_footprint(
            (FIRST_DATASET_ID,),
            "2025-02-01T00:00:00Z",
            "2025-03-01T00:00:00Z",
        ),
        experiment_uuid=UUID(SECOND_EXPERIMENT_ID.removeprefix("EXP-")),
        ledger=ledger,
    )
    first_release = first.release_service.authorize_release(
        first.request, expected_ledger_head=None
    )
    second_release = second.release_service.authorize_release(
        second.request, expected_ledger_head=first_release.event_digest
    )
    record = second_release.record
    record["sealed_binding"] = first.binding.as_record()
    record["event_digest"] = release_event_digest(record)
    _write_event(second_release._event.path, record)
    head: JsonRecord = {
        "schema_version": "1.0.0",
        "ledger_sequence": 2,
        "event_digest": record["event_digest"],
    }
    (ledger.root / "head.json").write_bytes(canonicalize_json(head))

    with pytest.raises(ExposureLedgerIntegrityError, match="overlapping exposure"):
        ledger.verify()


def test_synthetic_mode_accepted_and_host_enforced_claim_rejected(
    harness: ReleaseHarness,
) -> None:
    """A schema vocabulary entry cannot let Item 10A manufacture host evidence."""
    evidence = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    assert evidence.record["enforcement_mode"] == "SYNTHETIC_TEST"

    other = _build_harness(harness.ledger.root.parent / "host-claim")
    request = replace(other.request, enforcement_mode=EnforcementMode.HOST_ENFORCED)
    with pytest.raises(UnsupportedEnforcementModeError, match="SYNTHETIC_TEST"):
        other.release_service.authorize_release(request, expected_ledger_head=None)
    assert other.ledger.verify() == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor", "Authorization: Bearer synthetic-secret"),
        ("reason", "--token synthetic-secret"),
        ("reason", "Bearer synthetic-secret"),
    ],
)
def test_release_text_rejects_labelled_secrets_without_echo(
    harness: ReleaseHarness, field: str, value: str
) -> None:
    """Obvious credential text is rejected without returning its value."""
    request = _replace_request(harness.request, field, value)
    with pytest.raises(SensitiveMetadataError) as captured:
        harness.release_service.authorize_release(request, expected_ledger_head=None)
    assert "synthetic-secret" not in str(captured.value)


def test_internal_event_storage_rejects_float_host_mode_and_credential_reference(
    harness: ReleaseHarness,
) -> None:
    """The internal storage hook retains its independent structural validation."""
    released = harness.lifecycle.object_store.get(
        harness.request.released_artifact_digest
    )
    event_body: JsonRecord = {
        "schema_version": "1.0.0",
        "event_type": "AUTHORIZED_RELEASE",
        "experiment_id": harness.experiment_id,
        "frozen_revision_digest": harness.request.frozen_revision_digest,
        "frozen_manifest_digest": harness.request.frozen_manifest_digest,
        "sealed_binding": harness.binding.as_record(),
        "code_revision": harness.request.code_revision,
        "configuration_digest": harness.request.configuration_digest,
        "environment_digest": harness.request.environment_digest,
        "occurred_at": harness.request.occurred_at,
        "actor": harness.request.actor,
        "reason": harness.request.reason,
        "released_artifact_digest": released.digest,
        "released_artifact_reference": harness.lifecycle.object_store.storage_reference(
            released.digest
        ),
        "source_partition_status": "EXPOSED",
        "enforcement_mode": "SYNTHETIC_TEST",
    }
    floated = deepcopy(event_body)
    floated["reason"] = cast(JsonValue, 1.5)
    with pytest.raises(ExposureLedgerIntegrityError, match="floats"):
        harness.ledger._append_validated_event(floated, expected_previous_digest=None)
    hosted = deepcopy(event_body)
    hosted["enforcement_mode"] = "HOST_ENFORCED"
    with pytest.raises(UnsupportedEnforcementModeError):
        harness.ledger._append_validated_event(hosted, expected_previous_digest=None)
    credential = deepcopy(event_body)
    credential["released_artifact_reference"] = (
        "https://example.invalid/a?api_key=hidden"
    )
    with pytest.raises(ExposureLedgerIntegrityError) as captured:
        harness.ledger._append_validated_event(
            credential, expected_previous_digest=None
        )
    assert "hidden" not in str(captured.value)


def test_released_lifecycle_retains_reference_stops_search_and_allows_evaluation(
    harness: ReleaseHarness,
) -> None:
    """Retained release verifies through every later Item 8 lifecycle state."""
    frozen_before = deepcopy(harness.frozen_record)
    evidence = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    assert harness.release_service.verify_release(evidence.event_digest) == evidence
    running = harness.lifecycle.start(
        harness.experiment_id,
        harness.frozen_digest,
        started_at=STARTED_AT,
        release_evidence=evidence,
    )
    history = harness.lifecycle.registry.verify_object(harness.experiment_id)
    assert sum(item.record["lifecycle_status"] == "FROZEN" for item in history) == 1
    assert history[2].record == frozen_before
    assert running.record["sealed_data_release"] == {
        "status": "RELEASED",
        "event_digest": evidence.event_digest,
    }
    assert harness.release_service.verify_release(evidence.event_digest) == evidence
    with pytest.raises(ExperimentIntegrityError, match="head is not FROZEN"):
        harness.release_service.authorize_release(
            harness.request, expected_ledger_head=evidence.event_digest
        )
    with pytest.raises(PostReleaseSearchError):
        harness.lifecycle.record_attempt(
            harness.experiment_id,
            running.digest,
            recorded_at=ATTEMPT_AT,
            ai_generated=True,
            failed=False,
            exposure_reason="This forbidden search must not be appended.",
        )
    evaluated = harness.lifecycle.evaluate(
        harness.experiment_id,
        running.digest,
        evaluated_at=EVALUATED_AT,
        outcome=EvaluationOutcome.NULL,
        result_summary="Fixed synthetic evaluation produced a null outcome.",
        no_result_artifact_reason="The synthetic result is retained in the revision.",
    )
    assert evaluated.record["attempt_records"] == []
    assert evaluated.record["variants_attempted"] == 0
    assert (
        evaluated.record["sealed_data_release"] == running.record["sealed_data_release"]
    )
    assert harness.release_service.verify_release(evidence.event_digest) == evidence
    decided = harness.lifecycle.decide(
        harness.experiment_id,
        evaluated.digest,
        decided_at=DECIDED_AT,
        decision=ExperimentDecision.INCONCLUSIVE,
        reason="Synthetic fixed evaluation supports no directional conclusion.",
    )
    assert harness.release_service.verify_release(evidence.event_digest) == evidence
    history = harness.lifecycle.registry.verify_object(harness.experiment_id)
    assert history[-1] == decided
    assert sum(item.record["lifecycle_status"] == "FROZEN" for item in history) == 1


@pytest.mark.parametrize(
    "field",
    ["frozen_revision_digest", "frozen_manifest_digest"],
)
def test_historical_release_verification_rejects_authority_mismatch(
    harness: ReleaseHarness, field: str
) -> None:
    """Retained evidence cannot substitute a different historical authority."""
    evidence = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    running = harness.lifecycle.start(
        harness.experiment_id,
        harness.frozen_digest,
        started_at=STARTED_AT,
        release_evidence=evidence,
    )
    assert running.record["lifecycle_status"] == "RUNNING"
    with pytest.raises(ExperimentIntegrityError, match=r"revision|manifest"):
        harness.lifecycle.verify_historical_release_authority(
            experiment_id=harness.experiment_id,
            frozen_revision_digest=(
                "sha256:" + "d" * 64
                if field == "frozen_revision_digest"
                else harness.request.frozen_revision_digest
            ),
            frozen_manifest_digest=(
                "sha256:" + "d" * 64
                if field == "frozen_manifest_digest"
                else harness.request.frozen_manifest_digest
            ),
            dataset_ids=harness.binding.dataset_ids,
            sealed_partition=cast(
                JsonRecord, harness.binding.as_record()["sealed_out_of_sample"]
            ),
            code_revision=harness.request.code_revision,
            configuration_digest=harness.request.configuration_digest,
            environment_digest=harness.request.environment_digest,
            occurred_at=harness.request.occurred_at,
            release_event_digest=evidence.event_digest,
        )


def test_historical_release_verification_requires_retained_event_digest(
    harness: ReleaseHarness,
) -> None:
    """Post-FROZEN audit evidence must match the exact Item 8 release reference."""
    evidence = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    harness.lifecycle.start(
        harness.experiment_id,
        harness.frozen_digest,
        started_at=STARTED_AT,
        release_evidence=evidence,
    )
    with pytest.raises(ExperimentIntegrityError, match="not retained"):
        harness.lifecycle.verify_historical_release_authority(
            experiment_id=harness.experiment_id,
            frozen_revision_digest=harness.request.frozen_revision_digest,
            frozen_manifest_digest=harness.request.frozen_manifest_digest,
            dataset_ids=harness.binding.dataset_ids,
            sealed_partition=cast(
                JsonRecord, harness.binding.as_record()["sealed_out_of_sample"]
            ),
            code_revision=harness.request.code_revision,
            configuration_digest=harness.request.configuration_digest,
            environment_digest=harness.request.environment_digest,
            occurred_at=harness.request.occurred_at,
            release_event_digest="sha256:" + "e" * 64,
        )


def test_unreleased_experiment_runtime_behavior_is_unchanged(tmp_path: Path) -> None:
    """An unrelated unreleased RUNNING experiment still records governed attempts."""
    lifecycle = service(tmp_path)
    payload = runtime_payload()
    experiment_id, _draft, registered = registered_experiment(lifecycle, payload)
    frozen = lifecycle.freeze(
        experiment_id,
        registered.digest,
        frozen_at=FROZEN_AT,
        data_manifests=data_manifests(payload),
    )
    running = lifecycle.start(
        experiment_id, frozen.revision.digest, started_at=STARTED_AT
    )
    attempted = lifecycle.record_attempt(
        experiment_id,
        running.digest,
        recorded_at=ATTEMPT_AT,
        ai_generated=False,
        failed=True,
        exposure_reason="Synthetic unreleased regression attempt.",
    )
    assert attempted.record["variants_attempted"] == 1


def test_release_authorization_never_dereferences_a_sealed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Research-side release paths touch metadata and released objects only."""
    harness = _build_harness(tmp_path)
    sealed_root = tmp_path / "poisoned-sealed-vault"

    def is_sealed(value: object) -> bool:
        return str(value).startswith(str(sealed_root))

    original_open = cast(Any, builtins.open)
    original_path_open = cast(Any, Path.open)
    original_read_bytes = cast(Any, Path.read_bytes)
    original_stat = cast(Any, Path.stat)
    original_exists = cast(Any, Path.exists)
    original_rglob = cast(Any, Path.rglob)
    original_listdir = cast(Any, os.listdir)
    original_scandir = cast(Any, os.scandir)
    original_sha256 = cast(Any, hashlib.sha256)

    def guarded_open(file: object, *args: Any, **kwargs: Any) -> Any:
        if is_sealed(file):
            raise AssertionError("sealed source open attempted")
        return original_open(file, *args, **kwargs)

    def guarded_path_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if is_sealed(path):
            raise AssertionError("sealed source Path.open attempted")
        return original_path_open(path, *args, **kwargs)

    def guarded_read_bytes(path: Path) -> bytes:
        if is_sealed(path):
            raise AssertionError("sealed source read attempted")
        return cast(bytes, original_read_bytes(path))

    def guarded_stat(path: Path, *args: Any, **kwargs: Any) -> Any:
        if is_sealed(path):
            raise AssertionError("sealed source stat attempted")
        return original_stat(path, *args, **kwargs)

    def guarded_exists(path: Path, *args: Any, **kwargs: Any) -> bool:
        if is_sealed(path):
            raise AssertionError("sealed source exists attempted")
        return bool(original_exists(path, *args, **kwargs))

    def guarded_rglob(path: Path, pattern: str) -> Any:
        if is_sealed(path):
            raise AssertionError("sealed source traversal attempted")
        return original_rglob(path, pattern)

    def guarded_listdir(path: object = ".") -> Any:
        if is_sealed(path):
            raise AssertionError("sealed source list attempted")
        return original_listdir(path)

    def guarded_scandir(path: object = ".") -> Any:
        if is_sealed(path):
            raise AssertionError("sealed source scandir attempted")
        return original_scandir(path)

    def guarded_sha256(data: Any = b"", *args: Any, **kwargs: Any) -> Any:
        if data == b"poisoned sealed bytes":
            raise AssertionError("sealed source hash attempted")
        return original_sha256(data, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(Path, "stat", guarded_stat)
    monkeypatch.setattr(Path, "exists", guarded_exists)
    monkeypatch.setattr(Path, "rglob", guarded_rglob)
    monkeypatch.setattr(os, "listdir", guarded_listdir)
    monkeypatch.setattr(os, "scandir", guarded_scandir)
    monkeypatch.setattr(hashlib, "sha256", guarded_sha256)

    evidence = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    harness.lifecycle.start(
        harness.experiment_id,
        harness.frozen_digest,
        started_at=STARTED_AT,
        release_evidence=evidence,
    )
    assert evidence.event_digest.startswith("sha256:")


def test_duplicate_json_keys_and_noncanonical_event_bytes_fail_closed(
    harness: ReleaseHarness,
) -> None:
    """Ingested ledger bytes must be strict duplicate-free canonical JSON."""
    evidence = harness.release_service.authorize_release(
        harness.request, expected_ledger_head=None
    )
    path = harness.ledger.verify()[0].path
    event_text = json.dumps(
        dict(reversed(tuple(evidence.record.items()))), separators=(",", ":")
    )
    path.write_text(
        '{"event_type":"AUTHORIZED_RELEASE","event_type":"ACCIDENTAL_EXPOSURE"}'
    )
    with pytest.raises(ExposureLedgerIntegrityError, match="strict JSON"):
        harness.ledger.verify()
    path.write_text(event_text, encoding="utf-8")
    with pytest.raises(ExposureLedgerIntegrityError, match="not canonical"):
        harness.ledger.verify()
