"""Execute row membership under verified Item9 plans without lifecycle authority."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.validation import (
    FrozenTemporalValidationBinding,
    TemporalInterval,
    ValidationPlan,
)
from quant_hunter.validation.temporal import _timestamp


class ResearchValidationError(ValueError):
    pass


def utc(value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ResearchValidationError("UTC_TIMESTAMP_REQUIRED")


def instant(value: datetime) -> str:
    utc(value)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def in_interval(at: datetime, interval: TemporalInterval) -> bool:
    # Reuse Item9's exact boundary comparison; never truncate accepted plan fractions.
    point = _timestamp(instant(at), "observation")
    return interval.start_key <= point < interval.end_key


def at_or_before(at: datetime, boundary: str) -> bool:
    point = _timestamp(instant(at), "observation")
    other = _timestamp(boundary, "boundary")
    return point <= other


@dataclass(frozen=True, slots=True)
class ObservationTimes:
    row_id: str
    decision_at: datetime
    feature_start: datetime
    feature_end: datetime
    feature_available_at: datetime
    label_start: datetime
    label_end: datetime
    label_available_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.row_id, str)
            or not 1 <= len(self.row_id) <= 80
            or not self.row_id.isascii()
        ):
            raise ResearchValidationError("INVALID_ROW_ID")
        for value in (
            self.decision_at,
            self.feature_start,
            self.feature_end,
            self.feature_available_at,
            self.label_start,
            self.label_end,
            self.label_available_at,
        ):
            utc(value)
        if (
            self.feature_start > self.feature_end
            or self.feature_end > self.feature_available_at
            or self.label_start < self.decision_at
            or self.label_end <= self.label_start
            or self.label_available_at < self.label_end
        ):
            raise ResearchValidationError("INVALID_OBSERVATION_TIMING")


@dataclass(frozen=True, slots=True)
class SupervisedRow:
    timing: ObservationTimes
    features: tuple[float, ...]
    label: float


@dataclass(frozen=True, slots=True)
class FoldMembership:
    fold_id: str
    training_ids: tuple[str, ...]
    validation_ids: tuple[str, ...]
    exclusions: tuple[tuple[str, str], ...]

    def to_record(self) -> JsonRecord:
        return {
            "fold_id": self.fold_id,
            "training_ids": list(self.training_ids),
            "validation_ids": list(self.validation_ids),
            "exclusions": [
                {"row_id": row, "reason": reason} for row, reason in self.exclusions
            ],
        }


def resolve_membership(
    plan: ValidationPlan, observations: tuple[ObservationTimes, ...]
) -> tuple[FoldMembership, ...]:
    """Purge actual dependencies; embargo is fold-local exactly as Item9 declares."""
    plan.verify()
    if (
        not isinstance(observations, tuple)
        or not 1 <= len(observations) <= 100_000
        or len(plan.folds) > 100
        or len(observations) * len(plan.folds) > 2_000_000
    ):
        raise ResearchValidationError("MEMBERSHIP_RESOURCE_LIMIT")
    seen: set[str] = set()
    previous: datetime | None = None
    for row in observations:
        row.__post_init__()
        if row.row_id in seen or (previous is not None and row.decision_at <= previous):
            raise ResearchValidationError("DUPLICATE_OR_UNSORTED_OBSERVATIONS")
        seen.add(row.row_id)
        previous = row.decision_at
        if in_interval(
            row.decision_at, plan.partitions.sealed_out_of_sample
        ) or not at_or_before(
            row.label_end, plan.partitions.sealed_out_of_sample.start
        ):
            # Only timestamps are inspected; numeric values are never examined.
            raise ResearchValidationError("SEALED_OBSERVATION_SUPPLIED")
    result: list[FoldMembership] = []
    for fold in plan.folds:
        training, validation, exclusions = [], [], []
        for row in observations:
            reason: str | None = None
            train, valid = (
                in_interval(row.decision_at, fold.training),
                in_interval(row.decision_at, fold.validation),
            )
            if not train and not valid:
                reason = "OUTSIDE_FOLD"
            elif row.feature_available_at > row.decision_at:
                reason = "FEATURE_NOT_AVAILABLE_AT_DECISION"
            elif train:
                if not at_or_before(row.label_available_at, fold.training.end):
                    reason = "LABEL_NOT_AVAILABLE_AT_FIT"
                elif not at_or_before(row.label_end, fold.training.end):
                    reason = "LABEL_CROSSES_TRAIN_END"
                elif not at_or_before(row.feature_available_at, fold.training.end):
                    reason = "FEATURE_NOT_AVAILABLE_AT_FIT"
            else:
                if not at_or_before(row.label_end, fold.validation.end):
                    reason = "LABEL_CROSSES_VALIDATION_END"
            # Labels are half-open [start,end); feature dependencies include their
            # final observation. A boundary equal to a purge start is excluded.
            if reason is None:
                feature = (
                    TemporalInterval(
                        instant(row.feature_start), instant(row.feature_end)
                    )
                    if row.feature_start < row.feature_end
                    else None
                )
                label = TemporalInterval(
                    instant(row.label_start), instant(row.label_end)
                )
                for name, gap in (
                    ("PURGE_DEPENDENCY", fold.purge),
                    ("EMBARGO_DEPENDENCY", fold.embargo),
                ):
                    if gap.interval is not None and (
                        label.overlaps(gap.interval)
                        or (feature is not None and feature.overlaps(gap.interval))
                        or in_interval(row.feature_end, gap.interval)
                    ):
                        reason = name
                        break
            if reason:
                exclusions.append((row.row_id, reason))
            elif train:
                training.append(row.row_id)
            else:
                validation.append(row.row_id)
        result.append(
            FoldMembership(
                fold.fold_id, tuple(training), tuple(validation), tuple(exclusions)
            )
        )
    return tuple(result)


class Predictor(Protocol):
    def __call__(self, features: tuple[float, ...]) -> float: ...


def _features(values: tuple[float, ...]) -> tuple[float, ...]:
    if (
        not isinstance(values, tuple)
        or not 1 <= len(values) <= 64
        or any(
            type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 1e50
            for v in values
        )
    ):
        raise ResearchValidationError("INVALID_FEATURE_VECTOR")
    return tuple(float(v) for v in values)


def _number(value: float) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or abs(value) > 1e50:
        raise ResearchValidationError("INVALID_NUMERIC_RESULT")
    return float(value)


def execute_walk_forward(
    binding: FrozenTemporalValidationBinding,
    rows: tuple[SupervisedRow, ...],
    fit: Callable[[tuple[tuple[float, ...], ...], tuple[float, ...]], Predictor],
    *,
    evaluation_as_of: datetime,
    minimum_train: int = 3,
    minimum_validation: int = 1,
) -> JsonRecord:
    """Trusted callback receives only eligible training features/labels, then one query.

    The caller must register/count the candidate in Item8 before invocation. This
    function grants no filesystem, source client, holdout release or promotion.
    """
    binding.verify()
    utc(evaluation_as_of)
    if (
        type(minimum_train) is not int
        or not 2 <= minimum_train <= 100_000
        or type(minimum_validation) is not int
        or not 1 <= minimum_validation <= 100_000
    ):
        raise ResearchValidationError("INVALID_SAMPLE_THRESHOLDS")
    members = resolve_membership(
        binding.validation_plan, tuple(row.timing for row in rows)
    )
    indexed = {row.timing.row_id: row for row in rows}
    outputs: list[JsonValue] = []
    for fold, membership in zip(binding.validation_plan.folds, members, strict=True):
        if fold.validation.end_key > _timestamp(
            instant(evaluation_as_of), "evaluation"
        ):
            outputs.append(
                {
                    **membership.to_record(),
                    "status": "PENDING",
                    "reason": "VALIDATION_NOT_CLOSED",
                    "predictions": [],
                }
            )
            continue
        if (
            len(membership.training_ids) < minimum_train
            or len(membership.validation_ids) < minimum_validation
        ):
            outputs.append(
                {
                    **membership.to_record(),
                    "status": "INCONCLUSIVE",
                    "reason": "INSUFFICIENT_SAMPLE",
                    "predictions": [],
                }
            )
            continue
        x = tuple(_features(indexed[key].features) for key in membership.training_ids)
        if len({len(vector) for vector in x}) != 1:
            raise ResearchValidationError("FEATURE_DIMENSION_MISMATCH")
        y = tuple(_number(indexed[key].label) for key in membership.training_ids)
        model = fit(x, y)
        predictions: list[JsonValue] = []
        for key in membership.validation_ids:
            row = indexed[key]
            vector = _features(row.features)
            if len(vector) != len(x[0]):
                raise ResearchValidationError("FEATURE_DIMENSION_MISMATCH")
            prediction = _number(model(vector))
            label = (
                _number(row.label)
                if row.timing.label_available_at <= evaluation_as_of
                else None
            )
            predictions.append(
                {
                    "row_id": key,
                    "decision_at": instant(row.timing.decision_at),
                    "prediction": prediction,
                    "label": label,
                    "outcome_status": "AVAILABLE"
                    if label is not None
                    else "PENDING_LABEL_RECEIPT",
                }
            )
        outputs.append(
            {
                **membership.to_record(),
                "status": "COMPUTED_SOFTWARE_ONLY",
                "reason": None,
                "predictions": predictions,
            }
        )
    return {
        "schema_version": "qh-chronological-execution-v1",
        "experiment_id": binding.experiment_id,
        "frozen_revision_digest": binding.frozen_revision_digest,
        "temporal_plan_digest": binding.temporal_validation_plan_digest,
        "evaluation_as_of": instant(evaluation_as_of),
        "folds": outputs,
        "empirical_status": "INCONCLUSIVE",
        "host_enforced": False,
        "attempt_accounting_authority": "ITEM_8_EXPERIMENT_LIFECYCLE",
        "limitations": cast(
            list[JsonValue],
            [
                "Membership is relative to supplied verified observation timing; source truth remains a separate gate.",
                "Each fold fits independently; callbacks must implement training-only transforms and receive no validation labels.",
                "Existing Item9 keeps all fold training within development and validation within its declared validation partition.",
                "No sealed interval was opened; fold-local embargo is not a global cross-fold blackout.",
            ],
        ),
    }
