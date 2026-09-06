"""Typed experiment preregistration and freeze transitions."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final, cast
from uuid import uuid7

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.identity import (
    Allocation,
    IdentityError,
    RegistryKind,
    RegistryStore,
    Revision,
    StaleWriterError,
    UuidFactory,
    validate_typed_id,
)
from quant_hunter.provenance import (
    DataManifestReference,
    FreezeManifest,
    build_freeze_manifest,
)
from quant_hunter.provenance.hashing import InvalidDigestError, require_sha256_digest
from quant_hunter.storage import ImmutableObjectStore, StoredObject
from quant_hunter.storage.security import reject_secret_text

_TIMESTAMP_PATTERN: Final = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:[.](?P<fraction>[0-9]+))?Z$"
)
_REGISTRY_MANAGED_FIELDS: Final = {
    "experiment_id",
    "revision",
    "previous_revision_digest",
}
_LIFECYCLE_MANAGED_FIELDS: Final = {
    "created_at",
    "registered_at",
    "frozen_at",
    "frozen_manifest_digest",
    "started_at",
    "attempt_records",
    "lifecycle_status",
}
_FROZEN_TRANSITION_FIELDS: Final = {
    "lifecycle_status",
    "frozen_at",
    "frozen_manifest_digest",
}
_RUNTIME_FIELDS: Final = {
    "lifecycle_status",
    "started_at",
    "attempt_records",
    "variants_attempted",
    "variant_accounting",
}
_CONCRETE_PLAN_FIELDS: Final = (
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
)


class ExperimentStatus(StrEnum):
    """The governed experiment lifecycle vocabulary."""

    DRAFT = "DRAFT"
    REGISTERED = "REGISTERED"
    FROZEN = "FROZEN"
    RUNNING = "RUNNING"
    EVALUATED = "EVALUATED"
    DECIDED = "DECIDED"


class ExperimentLifecycleError(RuntimeError):
    """Base class for lifecycle and scientific-integrity failures."""


class InvalidExperimentTransitionError(ExperimentLifecycleError):
    """A requested lifecycle edge is skipped, backward, or repeated."""


class PreregistrationError(ExperimentLifecycleError):
    """A draft is not a complete result-free scientific preregistration."""


class ExperimentIntegrityError(ExperimentLifecycleError):
    """Registry, identity, timestamp, or freeze evidence is inconsistent."""


class AttemptBudgetExceededError(ExperimentLifecycleError):
    """A runtime attempt would exceed the frozen multiple-testing budget."""


@dataclass(frozen=True, slots=True)
class FrozenExperiment:
    """The exact FROZEN revision and its immutable canonical freeze evidence."""

    revision: Revision
    manifest: FreezeManifest
    manifest_object: StoredObject


type _ExactTimestamp = tuple[int, int, int, int, int, int, Decimal]


def _timestamp(value: str, field: str) -> _ExactTimestamp:
    match = _TIMESTAMP_PATTERN.fullmatch(value)
    if match is None:
        raise ExperimentIntegrityError(f"{field} must be a UTC RFC 3339 timestamp")
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    second = int(match.group("second"))
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError as error:
        raise ExperimentIntegrityError(
            f"{field} must be a valid UTC RFC 3339 timestamp"
        ) from error
    fraction = match.group("fraction") or "0"
    return (year, month, day, hour, minute, second, Decimal(f"0.{fraction}"))


def _status(record: Mapping[str, JsonValue]) -> ExperimentStatus:
    value = record.get("lifecycle_status")
    if not isinstance(value, str):
        raise ExperimentIntegrityError("Malformed experiment lifecycle status")
    try:
        return ExperimentStatus(value)
    except ValueError as error:
        raise ExperimentIntegrityError(
            "Malformed experiment lifecycle status"
        ) from error


def _payload(record: Mapping[str, JsonValue]) -> JsonRecord:
    return {
        key: deepcopy(value)
        for key, value in record.items()
        if key not in _REGISTRY_MANAGED_FIELDS
    }


def _without_fields(record: Mapping[str, JsonValue], fields: set[str]) -> JsonRecord:
    return {
        key: deepcopy(value)
        for key, value in record.items()
        if key not in (_REGISTRY_MANAGED_FIELDS | fields)
    }


def _runtime_science(record: Mapping[str, JsonValue]) -> JsonRecord:
    science = _without_fields(record, _RUNTIME_FIELDS)
    accounting = record.get("variant_accounting")
    if not isinstance(accounting, dict):
        raise ExperimentIntegrityError("Runtime variant accounting is malformed")
    science["variant_accounting_basis"] = deepcopy(accounting.get("accounting_basis"))
    return science


def _require_string_list(record: Mapping[str, JsonValue], field: str) -> list[str]:
    value = record.get(field)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise PreregistrationError(f"{field} must be a nonempty explicit plan")
    return cast(list[str], value)


def _require_concrete_plans(record: Mapping[str, JsonValue]) -> None:
    for field in _CONCRETE_PLAN_FIELDS:
        value = record.get(field)
        if isinstance(value, dict):
            raise PreregistrationError(f"{field} must be explicit before registration")
        if isinstance(value, str):
            if not value.strip():
                raise PreregistrationError(
                    f"{field} must be explicit before registration"
                )
            continue
        if isinstance(value, list) and value:
            continue
        raise PreregistrationError(f"{field} must be explicit before registration")


def _require_no_observed_outcomes(record: Mapping[str, JsonValue]) -> None:
    _require_no_final_outcomes(record)
    if record.get("variants_attempted") != 0:
        raise PreregistrationError("Attempted variants must be zero before execution")
    accounting = record.get("variant_accounting")
    if not isinstance(accounting, dict) or any(
        accounting.get(field) != 0
        for field in ("ai_generated_attempts", "failed_attempts")
    ):
        raise PreregistrationError(
            "AI-generated and failed attempt counts must be zero before execution"
        )


def _require_no_final_outcomes(record: Mapping[str, JsonValue]) -> None:
    if isinstance(record.get("results"), str):
        raise PreregistrationError("Observed results are forbidden before execution")
    if isinstance(record.get("result_artifact_locations"), list):
        raise PreregistrationError(
            "Result artifact locations are forbidden before execution"
        )
    if record.get("result_artifact_digests") != []:
        raise PreregistrationError(
            "Result artifact digests are forbidden before execution"
        )
    if "decision" in record:
        raise PreregistrationError("A decision is forbidden before evaluation")
    if isinstance(record.get("reason_for_decision"), str):
        raise PreregistrationError(
            "A reason for decision is forbidden before evaluation"
        )


def _validate_preregistration(record: Mapping[str, JsonValue]) -> None:
    _require_no_observed_outcomes(record)
    _require_concrete_plans(record)
    for field in (
        "dataset_ids",
        "evaluation_metrics",
        "statistical_tests",
        "execution_cost_assumptions",
    ):
        _require_string_list(record, field)

    dataset_ids = set(_require_string_list(record, "dataset_ids"))
    vintages = record.get("dataset_vintages")
    if not isinstance(vintages, list) or not vintages:
        raise PreregistrationError("dataset_vintages must be explicit")
    vintage_dataset_ids: set[str] = set()
    for item in vintages:
        if not isinstance(item, dict):
            raise PreregistrationError("dataset_vintages must be explicit")
        dataset_id = item.get("dataset_id")
        if not isinstance(dataset_id, str):
            raise PreregistrationError("dataset_vintages must identify each dataset")
        vintage_dataset_ids.add(dataset_id)
    if vintage_dataset_ids != dataset_ids:
        raise PreregistrationError(
            "dataset_vintages must account for every exact dataset"
        )

    multiple_testing = record.get("multiple_testing")
    if not isinstance(multiple_testing, dict):
        raise PreregistrationError("multiple_testing must be explicit")
    if multiple_testing.get("family_id") != record.get("research_family_id"):
        raise PreregistrationError(
            "multiple-testing family must match the research family"
        )
    budget = multiple_testing.get("budget")
    variants_planned = record.get("variants_planned")
    if (
        not isinstance(budget, int)
        or isinstance(budget, bool)
        or not isinstance(variants_planned, int)
        or isinstance(variants_planned, bool)
        or budget < variants_planned
    ):
        raise PreregistrationError(
            "multiple-testing budget must cover every planned variant"
        )


def _runtime_budget(record: Mapping[str, JsonValue]) -> int:
    multiple_testing = record.get("multiple_testing")
    if not isinstance(multiple_testing, dict):
        raise ExperimentIntegrityError("Runtime multiple-testing plan is malformed")
    budget = multiple_testing.get("budget")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise ExperimentIntegrityError("Runtime multiple-testing budget is malformed")
    return budget


def _runtime_attempts(
    record: Mapping[str, JsonValue], experiment_id: str
) -> list[JsonRecord]:
    started_at = record.get("started_at")
    if not isinstance(started_at, str):
        raise ExperimentIntegrityError("RUNNING started_at is malformed")
    previous_time = _timestamp(started_at, "started_at")
    values = record.get("attempt_records")
    if not isinstance(values, list):
        raise ExperimentIntegrityError("Runtime attempt evidence is malformed")
    attempts: list[JsonRecord] = []
    allowed_fields = {
        "attempt_number",
        "experiment_id",
        "recorded_at",
        "ai_generated",
        "failed",
        "exposure_reason",
        "variant_configuration_digest",
        "retry_of_attempt",
    }
    for expected_number, value in enumerate(values, start=1):
        if not isinstance(value, dict) or set(value) - allowed_fields:
            raise ExperimentIntegrityError("Runtime attempt evidence is malformed")
        if value.get("attempt_number") != expected_number:
            raise ExperimentIntegrityError("Runtime attempt sequence is malformed")
        if value.get("experiment_id") != experiment_id:
            raise ExperimentIntegrityError("Runtime attempt experiment ID mismatch")
        recorded_at = value.get("recorded_at")
        if not isinstance(recorded_at, str):
            raise ExperimentIntegrityError("Runtime attempt timestamp is malformed")
        recorded_time = _timestamp(recorded_at, "attempt recorded_at")
        if recorded_time < previous_time:
            raise ExperimentIntegrityError("Runtime attempt timestamp moves backward")
        previous_time = recorded_time
        if not isinstance(value.get("ai_generated"), bool) or not isinstance(
            value.get("failed"), bool
        ):
            raise ExperimentIntegrityError("Runtime attempt flags are malformed")
        reason = value.get("exposure_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ExperimentIntegrityError("Runtime attempt exposure reason is missing")
        reject_secret_text(reason, "runtime attempt exposure reason")
        configuration_digest = value.get("variant_configuration_digest")
        if configuration_digest is not None:
            if not isinstance(configuration_digest, str):
                raise ExperimentIntegrityError(
                    "Runtime attempt configuration digest is malformed"
                )
            try:
                require_sha256_digest(configuration_digest)
            except InvalidDigestError as error:
                raise ExperimentIntegrityError(
                    "Runtime attempt configuration digest is malformed"
                ) from error
        retry_of = value.get("retry_of_attempt")
        if retry_of is not None and (
            not isinstance(retry_of, int)
            or isinstance(retry_of, bool)
            or retry_of < 1
            or retry_of >= expected_number
        ):
            raise ExperimentIntegrityError("Runtime retry reference is malformed")
        attempts.append(deepcopy(value))
    return attempts


def _validate_runtime_revision(
    record: Mapping[str, JsonValue], frozen_record: Mapping[str, JsonValue]
) -> list[JsonRecord]:
    if _runtime_science(record) != _runtime_science(frozen_record):
        raise ExperimentIntegrityError("RUNNING revision changed frozen science")
    _require_no_final_outcomes(record)
    experiment_id = record.get("experiment_id")
    if not isinstance(experiment_id, str):
        raise ExperimentIntegrityError("RUNNING experiment ID is malformed")
    attempts = _runtime_attempts(record, experiment_id)
    accounting = record.get("variant_accounting")
    if not isinstance(accounting, dict):
        raise ExperimentIntegrityError("Runtime variant accounting is malformed")
    ai_count = sum(bool(attempt["ai_generated"]) for attempt in attempts)
    failed_count = sum(bool(attempt["failed"]) for attempt in attempts)
    if (
        record.get("variants_attempted") != len(attempts)
        or accounting.get("ai_generated_attempts") != ai_count
        or accounting.get("failed_attempts") != failed_count
    ):
        raise ExperimentIntegrityError("Runtime counters do not match attempt evidence")
    if len(attempts) > _runtime_budget(frozen_record):
        raise ExperimentIntegrityError("Runtime exposure exceeds the frozen budget")
    return attempts


class ExperimentLifecycleService:
    """Apply governed experiment transitions and runtime attempt accounting."""

    def __init__(
        self, registry: RegistryStore, object_store: ImmutableObjectStore
    ) -> None:
        self.registry = registry
        self.object_store = object_store

    def create_draft(
        self,
        record: Mapping[str, JsonValue],
        *,
        created_at: str,
        uuid_factory: UuidFactory = uuid7,
    ) -> Allocation:
        """Allocate an EXP identity and create its explicit-timestamp DRAFT."""
        overlap = (_REGISTRY_MANAGED_FIELDS | _LIFECYCLE_MANAGED_FIELDS).intersection(
            record
        )
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ExperimentIntegrityError(
                f"Lifecycle-managed fields supplied by caller: {names}"
            )
        _timestamp(created_at, "created_at")
        payload = deepcopy(dict(record))
        payload["created_at"] = created_at
        payload["lifecycle_status"] = ExperimentStatus.DRAFT.value
        return self.registry.allocate(
            RegistryKind.EXPERIMENT, payload, uuid_factory=uuid_factory
        )

    def register(
        self,
        experiment_id: str,
        expected_previous_digest: str,
        *,
        registered_at: str,
    ) -> Revision:
        """Append REGISTERED only from a complete, result-free DRAFT."""
        draft = self._head(experiment_id)
        self._require_transition(
            draft, ExperimentStatus.DRAFT, ExperimentStatus.REGISTERED
        )
        if expected_previous_digest != draft.digest:
            raise StaleWriterError(
                f"Expected {expected_previous_digest}, current head is {draft.digest}"
            )
        registered_time = _timestamp(registered_at, "registered_at")
        created_at = draft.record.get("created_at")
        if not isinstance(created_at, str):
            raise ExperimentIntegrityError("Experiment created_at is malformed")
        if registered_time < _timestamp(created_at, "created_at"):
            raise ExperimentIntegrityError("registered_at precedes created_at")
        _validate_preregistration(draft.record)

        payload = _payload(draft.record)
        payload["lifecycle_status"] = ExperimentStatus.REGISTERED.value
        payload["registered_at"] = registered_at
        return self.registry.append(experiment_id, expected_previous_digest, payload)

    def freeze(
        self,
        experiment_id: str,
        expected_previous_digest: str,
        *,
        frozen_at: str,
        data_manifests: Sequence[DataManifestReference],
    ) -> FrozenExperiment:
        """Bind the exact REGISTERED revision and publish immutable freeze bytes."""
        registered = self._head(experiment_id)
        self._require_transition(
            registered, ExperimentStatus.REGISTERED, ExperimentStatus.FROZEN
        )
        if expected_previous_digest != registered.digest:
            raise StaleWriterError(
                f"Expected {expected_previous_digest}, current head is {registered.digest}"
            )
        frozen_time = _timestamp(frozen_at, "frozen_at")
        registered_at = registered.record.get("registered_at")
        if not isinstance(registered_at, str):
            raise ExperimentIntegrityError("Experiment registered_at is malformed")
        if frozen_time < _timestamp(registered_at, "registered_at"):
            raise ExperimentIntegrityError("frozen_at precedes registered_at")
        _validate_preregistration(registered.record)
        manifest = self._build_manifest(registered, data_manifests)
        manifest_object = self.object_store.publish(manifest.canonical_bytes)

        payload = _payload(registered.record)
        payload["lifecycle_status"] = ExperimentStatus.FROZEN.value
        payload["frozen_at"] = frozen_at
        payload["frozen_manifest_digest"] = manifest.digest
        revision = self.registry.append(
            experiment_id, expected_previous_digest, payload
        )
        frozen = FrozenExperiment(revision, manifest, manifest_object)
        self._verify_frozen(frozen, registered=registered)
        return frozen

    def verify_frozen(self, experiment_id: str) -> FrozenExperiment:
        """Verify a FROZEN registry head and its exact immutable manifest."""
        revisions = self._revisions(experiment_id)
        if _status(revisions[-1].record) is not ExperimentStatus.FROZEN:
            raise ExperimentIntegrityError("Experiment head is not FROZEN")
        return self._frozen_from_history(revisions, len(revisions) - 1)

    def start(
        self,
        experiment_id: str,
        expected_previous_digest: str,
        *,
        started_at: str,
    ) -> Revision:
        """Append RUNNING after independently verifying exact frozen evidence."""
        revisions = self._revisions(experiment_id)
        frozen_revision = revisions[-1]
        self._require_transition(
            frozen_revision, ExperimentStatus.FROZEN, ExperimentStatus.RUNNING
        )
        if expected_previous_digest != frozen_revision.digest:
            raise StaleWriterError(
                f"Expected {expected_previous_digest}, current head is "
                f"{frozen_revision.digest}"
            )
        frozen = self._frozen_from_history(revisions, len(revisions) - 1)
        _require_no_observed_outcomes(frozen.revision.record)
        frozen_at = frozen.revision.record.get("frozen_at")
        if not isinstance(frozen_at, str):
            raise ExperimentIntegrityError("Experiment frozen_at is malformed")
        if _timestamp(started_at, "started_at") < _timestamp(frozen_at, "frozen_at"):
            raise ExperimentIntegrityError("started_at precedes frozen_at")

        payload = _payload(frozen.revision.record)
        payload["lifecycle_status"] = ExperimentStatus.RUNNING.value
        payload["started_at"] = started_at
        payload["attempt_records"] = []
        revision = self.registry.append(
            experiment_id, expected_previous_digest, payload
        )
        self._verify_running_history(self._revisions(experiment_id))
        return revision

    def record_attempt(
        self,
        experiment_id: str,
        expected_previous_digest: str,
        *,
        recorded_at: str,
        ai_generated: bool,
        failed: bool,
        exposure_reason: str,
        variant_configuration_digest: str | None = None,
        retry_of_attempt: int | None = None,
    ) -> Revision:
        """Append one auditable search exposure and recompute cumulative counters."""
        revisions = self._revisions(experiment_id)
        head, attempts = self._verify_running_history(revisions)
        if expected_previous_digest != head.digest:
            raise StaleWriterError(
                f"Expected {expected_previous_digest}, current head is {head.digest}"
            )
        if not isinstance(ai_generated, bool) or not isinstance(failed, bool):
            raise ExperimentIntegrityError("Attempt flags must be booleans")
        if not exposure_reason.strip():
            raise ExperimentIntegrityError("Attempt exposure reason must not be empty")
        reject_secret_text(exposure_reason, "runtime attempt exposure reason")
        recorded_time = _timestamp(recorded_at, "recorded_at")
        prior_time = head.record.get("started_at")
        if attempts:
            prior_time = attempts[-1].get("recorded_at")
        if not isinstance(prior_time, str):
            raise ExperimentIntegrityError("Prior runtime timestamp is malformed")
        if recorded_time < _timestamp(prior_time, "prior runtime timestamp"):
            raise ExperimentIntegrityError(
                "recorded_at precedes prior runtime evidence"
            )
        if variant_configuration_digest is not None:
            try:
                require_sha256_digest(variant_configuration_digest)
            except InvalidDigestError as error:
                raise ExperimentIntegrityError(
                    "Attempt configuration digest is malformed"
                ) from error

        attempt_number = len(attempts) + 1
        if retry_of_attempt is not None and (
            not isinstance(retry_of_attempt, int)
            or isinstance(retry_of_attempt, bool)
            or retry_of_attempt < 1
            or retry_of_attempt >= attempt_number
        ):
            raise ExperimentIntegrityError("Retry must reference an earlier attempt")
        budget = _runtime_budget(head.record)
        if attempt_number > budget:
            raise AttemptBudgetExceededError(
                "Attempt would exceed the frozen multiple-testing budget"
            )

        evidence: JsonRecord = {
            "attempt_number": attempt_number,
            "experiment_id": experiment_id,
            "recorded_at": recorded_at,
            "ai_generated": ai_generated,
            "failed": failed,
            "exposure_reason": exposure_reason,
        }
        if variant_configuration_digest is not None:
            evidence["variant_configuration_digest"] = variant_configuration_digest
        if retry_of_attempt is not None:
            evidence["retry_of_attempt"] = retry_of_attempt
        updated_attempts: list[JsonRecord] = [deepcopy(item) for item in attempts]
        updated_attempts.append(evidence)

        payload = _payload(head.record)
        payload["attempt_records"] = cast(list[JsonValue], updated_attempts)
        payload["variants_attempted"] = attempt_number
        accounting = head.record.get("variant_accounting")
        if not isinstance(accounting, dict):
            raise ExperimentIntegrityError("Runtime variant accounting is malformed")
        payload["variant_accounting"] = {
            "ai_generated_attempts": sum(
                bool(item["ai_generated"]) for item in updated_attempts
            ),
            "failed_attempts": sum(bool(item["failed"]) for item in updated_attempts),
            "accounting_basis": deepcopy(accounting.get("accounting_basis")),
        }
        revision = self.registry.append(
            experiment_id, expected_previous_digest, payload
        )
        self._verify_running_history(self._revisions(experiment_id))
        return revision

    def _frozen_from_history(
        self, revisions: tuple[Revision, ...], frozen_index: int
    ) -> FrozenExperiment:
        frozen_revision = revisions[frozen_index]
        if _status(frozen_revision.record) is not ExperimentStatus.FROZEN:
            raise ExperimentIntegrityError("Experiment revision is not FROZEN")
        if frozen_index < 1:
            raise ExperimentIntegrityError(
                "FROZEN experiment lacks REGISTERED revision"
            )
        registered = revisions[frozen_index - 1]
        if _status(registered.record) is not ExperimentStatus.REGISTERED:
            raise ExperimentIntegrityError(
                "FROZEN experiment is not based on a REGISTERED revision"
            )
        digest = frozen_revision.record.get("frozen_manifest_digest")
        if not isinstance(digest, str):
            raise ExperimentIntegrityError("FROZEN manifest digest is malformed")
        stored = self.object_store.get(digest)
        manifest = FreezeManifest(self.object_store.read_bytes(digest), digest)
        frozen = FrozenExperiment(frozen_revision, manifest, stored)
        self._verify_frozen(frozen, registered=registered)
        return frozen

    def _verify_running_history(
        self, revisions: tuple[Revision, ...]
    ) -> tuple[Revision, list[JsonRecord]]:
        frozen_indexes = [
            index
            for index, revision in enumerate(revisions)
            if _status(revision.record) is ExperimentStatus.FROZEN
        ]
        if len(frozen_indexes) != 1:
            raise ExperimentIntegrityError(
                "RUNNING history must contain exactly one FROZEN revision"
            )
        frozen_index = frozen_indexes[0]
        frozen = self._frozen_from_history(revisions, frozen_index)
        frozen_at = frozen.revision.record.get("frozen_at")
        if not isinstance(frozen_at, str):
            raise ExperimentIntegrityError("Experiment frozen_at is malformed")
        running_revisions = revisions[frozen_index + 1 :]
        if not running_revisions or any(
            _status(revision.record) is not ExperimentStatus.RUNNING
            for revision in running_revisions
        ):
            raise ExperimentIntegrityError(
                "Runtime history is not continuously RUNNING"
            )
        previous_attempts: list[JsonRecord] | None = None
        started_at: str | None = None
        for revision in running_revisions:
            revision_started_at = revision.record.get("started_at")
            if not isinstance(revision_started_at, str):
                raise ExperimentIntegrityError("RUNNING started_at is malformed")
            if started_at is None:
                started_at = revision_started_at
                if _timestamp(started_at, "started_at") < _timestamp(
                    frozen_at, "frozen_at"
                ):
                    raise ExperimentIntegrityError("started_at precedes frozen_at")
            elif revision_started_at != started_at:
                raise ExperimentIntegrityError("RUNNING started_at changed")
            attempts = _validate_runtime_revision(
                revision.record, frozen.revision.record
            )
            if previous_attempts is None:
                if attempts:
                    raise ExperimentIntegrityError(
                        "Initial RUNNING revision must have zero attempts"
                    )
            elif (
                len(attempts) != len(previous_attempts) + 1
                or attempts[:-1] != previous_attempts
            ):
                raise ExperimentIntegrityError(
                    "Runtime attempt history must append exactly one attempt"
                )
            previous_attempts = attempts
        return running_revisions[-1], previous_attempts or []

    def _head(self, experiment_id: str) -> Revision:
        return self._revisions(experiment_id)[-1]

    def _revisions(self, experiment_id: str) -> tuple[Revision, ...]:
        try:
            validate_typed_id(experiment_id, RegistryKind.EXPERIMENT)
        except IdentityError as error:
            raise ExperimentIntegrityError("Invalid experiment identifier") from error
        return self.registry.verify_object(experiment_id)

    @staticmethod
    def _require_transition(
        revision: Revision,
        expected: ExperimentStatus,
        target: ExperimentStatus,
    ) -> None:
        actual = _status(revision.record)
        if actual is not expected:
            raise InvalidExperimentTransitionError(
                f"Cannot transition experiment from {actual.value} to {target.value}"
            )

    @staticmethod
    def _registered_data_digests(record: Mapping[str, JsonValue]) -> tuple[str, ...]:
        digests = record.get("provenance_artifact_digests")
        if not isinstance(digests, list) or any(
            not isinstance(digest, str) for digest in digests
        ):
            raise ExperimentIntegrityError(
                "Registered data-manifest digests are malformed"
            )
        return tuple(cast(list[str], digests))

    def _build_manifest(
        self,
        registered: Revision,
        data_manifests: Sequence[DataManifestReference],
    ) -> FreezeManifest:
        record = registered.record
        if tuple(
            item.digest for item in data_manifests
        ) != self._registered_data_digests(record):
            raise ExperimentIntegrityError(
                "Freeze data-manifest digests do not match registered provenance"
            )
        multiple_testing = record.get("multiple_testing")
        if not isinstance(multiple_testing, dict):
            raise ExperimentIntegrityError(
                "Registered multiple-testing plan is malformed"
            )
        hypothesis = record.get("hypothesis")
        configuration_digest = record.get("configuration_digest")
        code_revision = record.get("code_revision")
        environment_digest = record.get("environment_digest")
        baselines = record.get("baselines")
        experiment_id = record.get("experiment_id")
        if not all(
            isinstance(value, str)
            for value in (
                hypothesis,
                configuration_digest,
                code_revision,
                environment_digest,
                experiment_id,
            )
        ) or not isinstance(baselines, list):
            raise ExperimentIntegrityError("Registered freeze inputs are malformed")
        baseline_strings = cast(list[str], baselines)
        seed = record.get("random_seed")
        seeds = [seed] if isinstance(seed, int) and not isinstance(seed, bool) else []
        search_budget: JsonRecord = {
            "search_space": deepcopy(record.get("search_space")),
            "parameters_considered": deepcopy(record.get("parameters_considered")),
            "variants_planned": deepcopy(record.get("variants_planned")),
            "multiple_testing": deepcopy(multiple_testing),
        }
        criteria: JsonRecord = {
            "decision_criteria": deepcopy(record.get("decision_criteria")),
            "evaluation_metrics": deepcopy(record.get("evaluation_metrics")),
            "statistical_tests": deepcopy(record.get("statistical_tests")),
            "execution_cost_assumptions": deepcopy(
                record.get("execution_cost_assumptions")
            ),
        }
        return build_freeze_manifest(
            experiment_id=cast(str, experiment_id),
            registered_revision_digest=registered.digest,
            hypothesis_reference=cast(str, hypothesis),
            configuration_digest=cast(str, configuration_digest),
            code_revision=cast(str, code_revision),
            data_manifests=data_manifests,
            environment_digest=cast(str, environment_digest),
            seeds=seeds,
            search_budget=search_budget,
            criteria=criteria,
            baselines=baseline_strings,
        )

    def _verify_frozen(
        self, frozen: FrozenExperiment, *, registered: Revision | None = None
    ) -> None:
        frozen.manifest.verify()
        self.object_store.verify(frozen.manifest_object)
        if (
            frozen.revision.record.get("frozen_manifest_digest")
            != frozen.manifest.digest
        ):
            raise ExperimentIntegrityError(
                "FROZEN registry revision does not reference its manifest"
            )
        document = frozen.manifest.document
        experiment_id = frozen.revision.record.get("experiment_id")
        if document.get("experiment_id") != experiment_id:
            raise ExperimentIntegrityError("Freeze manifest experiment ID mismatch")
        if registered is not None:
            _validate_preregistration(registered.record)
            if _without_fields(
                frozen.revision.record, _FROZEN_TRANSITION_FIELDS
            ) != _without_fields(registered.record, _FROZEN_TRANSITION_FIELDS):
                raise ExperimentIntegrityError(
                    "FROZEN revision changed registered scientific evidence"
                )
            if document.get("registered_revision_digest") != registered.digest:
                raise ExperimentIntegrityError(
                    "Freeze manifest registered revision mismatch"
                )
            data_values = document.get("data_manifests")
            if not isinstance(data_values, list):
                raise ExperimentIntegrityError("Freeze data manifests are malformed")
            references: list[DataManifestReference] = []
            for value in data_values:
                if not isinstance(value, dict):
                    raise ExperimentIntegrityError(
                        "Freeze data manifests are malformed"
                    )
                reference = value.get("reference")
                digest = value.get("digest")
                if not isinstance(reference, str) or not isinstance(digest, str):
                    raise ExperimentIntegrityError(
                        "Freeze data manifests are malformed"
                    )
                references.append(DataManifestReference(reference, digest))
            expected = self._build_manifest(registered, references)
            if expected != frozen.manifest:
                raise ExperimentIntegrityError(
                    "Freeze manifest does not match the REGISTERED experiment"
                )
