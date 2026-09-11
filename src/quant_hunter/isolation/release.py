"""Synthetic-only sealed-OOS authorization and irreversible exposure contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.identity import RegistryKind, validate_typed_id
from quant_hunter.provenance.hashing import require_sha256_digest
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.storage.security import reject_secret_text

from .ledger import (
    ExposureLedger,
    ExposureLedgerEvent,
    ExposureLedgerIntegrityError,
    UnsupportedEnforcementModeError,
    verify_release_event_digest,
)


class EnforcementMode(StrEnum):
    """Evidence strength vocabulary; Item 10A can produce only synthetic evidence."""

    SYNTHETIC_TEST = "SYNTHETIC_TEST"
    HOST_ENFORCED = "HOST_ENFORCED"


class ExposureFailurePoint(StrEnum):
    """Governed causes that permanently invalidate a pristine exposure claim."""

    PRE_FREEZE_ACCESS = "PRE_FREEZE_ACCESS"
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"
    MISMATCHED_AUTHORITY = "MISMATCHED_AUTHORITY"
    PARTIAL_RELEASE_FAILURE = "PARTIAL_RELEASE_FAILURE"
    OTHER = "OTHER"


class ExposureState(StrEnum):
    """One-way exposure state derived from retained ledger evidence."""

    UNEXPOSED = "UNEXPOSED"
    EXPOSED = "EXPOSED"


class SealedReleaseError(RuntimeError):
    """Release authorization or retained evidence is invalid."""


@dataclass(frozen=True, slots=True)
class SealedBinding:
    """Complete frozen dataset identity set and exact sealed interval."""

    dataset_ids: tuple[str, ...]
    start: str
    end: str

    @classmethod
    def from_record(cls, value: object) -> SealedBinding:
        """Build a typed binding from a governed event record."""
        if not isinstance(value, dict):
            raise SealedReleaseError("Sealed binding is malformed")
        dataset_ids = value.get("dataset_ids")
        partition = value.get("sealed_out_of_sample")
        if (
            not isinstance(dataset_ids, list)
            or any(not isinstance(item, str) for item in dataset_ids)
            or not isinstance(partition, dict)
            or not isinstance(partition.get("start"), str)
            or not isinstance(partition.get("end"), str)
        ):
            raise SealedReleaseError("Sealed binding is malformed")
        return cls(
            tuple(cast(list[str], dataset_ids)),
            cast(str, partition["start"]),
            cast(str, partition["end"]),
        )

    def as_record(self) -> JsonRecord:
        """Return the deterministic canonical binding representation."""
        if not self.dataset_ids or len(set(self.dataset_ids)) != len(self.dataset_ids):
            raise SealedReleaseError(
                "Sealed binding requires distinct dataset identities"
            )
        for dataset_id in self.dataset_ids:
            validate_typed_id(dataset_id, RegistryKind.DATASET)
        if tuple(sorted(self.dataset_ids)) != self.dataset_ids:
            raise SealedReleaseError(
                "Sealed dataset identities must use lexicographic canonical order"
            )
        if not self.start or not self.end:
            raise SealedReleaseError("Sealed partition boundaries must not be empty")
        return {
            "dataset_ids": list(self.dataset_ids),
            "sealed_out_of_sample": {"start": self.start, "end": self.end},
        }


@dataclass(frozen=True, slots=True)
class ReleaseRequest:
    """Caller-supplied evidence that must exactly match Item 8 FROZEN authority."""

    experiment_id: str
    frozen_revision_digest: str
    frozen_manifest_digest: str
    sealed_binding: SealedBinding
    code_revision: str
    configuration_digest: str
    environment_digest: str
    occurred_at: str
    actor: str
    reason: str
    released_artifact_digest: str
    enforcement_mode: EnforcementMode = EnforcementMode.SYNTHETIC_TEST


@dataclass(frozen=True, slots=True)
class ExposureIncidentRequest:
    """Permanent fail-closed evidence that a sealed binding is no longer pristine."""

    experiment_id: str
    sealed_binding: SealedBinding
    occurred_at: str
    actor: str
    reason: str
    failure_point: ExposureFailurePoint
    released_artifact_digest: str | None = None


class _FrozenAuthority(Protocol):
    def verify_release_authority(
        self,
        *,
        experiment_id: str,
        frozen_revision_digest: str,
        frozen_manifest_digest: str,
        dataset_ids: Sequence[str],
        sealed_partition: Mapping[str, JsonValue],
        code_revision: str,
        configuration_digest: str,
        environment_digest: str,
        occurred_at: str,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class VerifiedReleaseEvidence:
    """An event rechecked against its ledger and released immutable artifact."""

    _ledger: ExposureLedger
    _object_store: ImmutableObjectStore
    _event: ExposureLedgerEvent

    @property
    def event_digest(self) -> str:
        return self._event.digest

    @property
    def record(self) -> JsonRecord:
        return deepcopy(self._event.record)

    def verify(self) -> JsonRecord:
        """Reverify chain membership, event identity, mode, and released bytes."""
        event = self._ledger.get_verified(self._event.digest)
        if event.record != self._event.record:
            raise ExposureLedgerIntegrityError(
                "Verified release evidence changed after construction"
            )
        record = event.record
        verify_release_event_digest(record)
        if record.get("event_type") != "AUTHORIZED_RELEASE":
            raise SealedReleaseError("Exposure evidence is not an authorized release")
        if record.get("enforcement_mode") != EnforcementMode.SYNTHETIC_TEST.value:
            raise UnsupportedEnforcementModeError(
                "Item 10A cannot verify HOST_ENFORCED evidence"
            )
        digest = record.get("released_artifact_digest")
        reference = record.get("released_artifact_reference")
        if not isinstance(digest, str) or not isinstance(reference, str):
            raise SealedReleaseError("Released artifact evidence is malformed")
        stored = self._object_store.get(digest)
        if self._object_store.storage_reference(stored.digest) != reference:
            raise SealedReleaseError("Released artifact reference mismatch")
        return deepcopy(record)


class SealedReleaseService:
    """Authorize synthetic releases without accepting or reading a sealed path."""

    def __init__(
        self,
        lifecycle: _FrozenAuthority,
        ledger: ExposureLedger,
        object_store: ImmutableObjectStore,
    ) -> None:
        self.lifecycle = lifecycle
        self.ledger = ledger
        self.object_store = object_store

    def authorize_release(
        self,
        request: ReleaseRequest,
        *,
        expected_ledger_head: str | None,
    ) -> VerifiedReleaseEvidence:
        """Verify exact FROZEN authority and append one irreversible release event."""
        if request.enforcement_mode is not EnforcementMode.SYNTHETIC_TEST:
            raise UnsupportedEnforcementModeError(
                "Item 10A can create only SYNTHETIC_TEST evidence"
            )
        self._validate_text(request.actor, "release actor")
        self._validate_text(request.reason, "release reason")
        binding = request.sealed_binding.as_record()
        self.lifecycle.verify_release_authority(
            experiment_id=request.experiment_id,
            frozen_revision_digest=request.frozen_revision_digest,
            frozen_manifest_digest=request.frozen_manifest_digest,
            dataset_ids=request.sealed_binding.dataset_ids,
            sealed_partition=cast(JsonRecord, binding["sealed_out_of_sample"]),
            code_revision=request.code_revision,
            configuration_digest=request.configuration_digest,
            environment_digest=request.environment_digest,
            occurred_at=request.occurred_at,
        )
        require_sha256_digest(request.released_artifact_digest)
        released = self.object_store.get(request.released_artifact_digest)
        body: JsonRecord = {
            "schema_version": "1.0.0",
            "event_type": "AUTHORIZED_RELEASE",
            "experiment_id": request.experiment_id,
            "frozen_revision_digest": request.frozen_revision_digest,
            "frozen_manifest_digest": request.frozen_manifest_digest,
            "sealed_binding": binding,
            "code_revision": request.code_revision,
            "configuration_digest": request.configuration_digest,
            "environment_digest": request.environment_digest,
            "occurred_at": request.occurred_at,
            "actor": request.actor,
            "reason": request.reason,
            "released_artifact_digest": released.digest,
            "released_artifact_reference": self.object_store.storage_reference(
                released.digest
            ),
            "source_partition_status": ExposureState.EXPOSED.value,
            "enforcement_mode": EnforcementMode.SYNTHETIC_TEST.value,
        }
        event = self.ledger.append_event(
            body, expected_previous_digest=expected_ledger_head
        )
        return self.verify_release(event.digest)

    def verify_release(self, event_digest: str) -> VerifiedReleaseEvidence:
        """Reverify retained release, artifact, and exact current FROZEN authority."""
        event = self.ledger.get_verified(event_digest)
        evidence = VerifiedReleaseEvidence(self.ledger, self.object_store, event)
        record = evidence.verify()
        binding = SealedBinding.from_record(record.get("sealed_binding"))
        self.lifecycle.verify_release_authority(
            experiment_id=cast(str, record["experiment_id"]),
            frozen_revision_digest=cast(str, record["frozen_revision_digest"]),
            frozen_manifest_digest=cast(str, record["frozen_manifest_digest"]),
            dataset_ids=binding.dataset_ids,
            sealed_partition=cast(
                JsonRecord, binding.as_record()["sealed_out_of_sample"]
            ),
            code_revision=cast(str, record["code_revision"]),
            configuration_digest=cast(str, record["configuration_digest"]),
            environment_digest=cast(str, record["environment_digest"]),
            occurred_at=cast(str, record["occurred_at"]),
        )
        return evidence

    def record_accidental_exposure(
        self,
        request: ExposureIncidentRequest,
        *,
        expected_ledger_head: str | None,
    ) -> ExposureLedgerEvent:
        """Permanently record synthetic evidence that confidentiality was lost."""
        validate_typed_id(request.experiment_id, RegistryKind.EXPERIMENT)
        self._validate_text(request.actor, "exposure incident actor")
        self._validate_text(request.reason, "exposure incident reason")
        body: JsonRecord = {
            "schema_version": "1.0.0",
            "event_type": "ACCIDENTAL_EXPOSURE",
            "experiment_id": request.experiment_id,
            "sealed_binding": request.sealed_binding.as_record(),
            "occurred_at": request.occurred_at,
            "actor": request.actor,
            "reason": request.reason,
            "failure_point": request.failure_point.value,
            "source_partition_status": ExposureState.EXPOSED.value,
            "enforcement_mode": EnforcementMode.SYNTHETIC_TEST.value,
            "review_requirement": "INVALIDATION_RISK_DECISION_REVIEW",
        }
        if request.released_artifact_digest is not None:
            require_sha256_digest(request.released_artifact_digest)
            body["released_artifact_digest"] = request.released_artifact_digest
        return self.ledger.append_event(
            body, expected_previous_digest=expected_ledger_head
        )

    def exposure_state(
        self, experiment_id: str, sealed_binding: SealedBinding
    ) -> ExposureState:
        """Derive irreversible state from retained authorized or accidental evidence."""
        event = self.ledger.exposure_for(experiment_id, sealed_binding.as_record())
        return ExposureState.EXPOSED if event is not None else ExposureState.UNEXPOSED

    @staticmethod
    def _validate_text(value: str, context: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise SealedReleaseError(f"{context} must be a nonempty string")
        reject_secret_text(value, context)
