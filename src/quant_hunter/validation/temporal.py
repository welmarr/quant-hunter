"""Immutable temporal-validation plans and leakage-control invariants."""

from __future__ import annotations

import re
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Final

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.provenance.hashing import sha256_bytes, verify_sha256_bytes

_TIMESTAMP_PATTERN: Final = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?:[.](?P<fraction>[0-9]+))?Z$"
)
_FOLD_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
INTERVAL_BOUNDARY_SEMANTICS: Final = "START_INCLUSIVE_END_EXCLUSIVE"

type _ExactTimestamp = tuple[int, int, int, int, int, int, Decimal]


class TemporalValidationError(ValueError):
    """A temporal-validation configuration violates a governed invariant."""


class TemporalValidationIntegrityError(RuntimeError):
    """Canonical validation-plan evidence is inconsistent or corrupted."""


class ValidationScheme(StrEnum):
    """Time-aware validation schemes authorized for market time series."""

    CHRONOLOGICAL_HOLDOUT = "CHRONOLOGICAL_HOLDOUT"
    ROLLING_WINDOW = "ROLLING_WINDOW"
    EXPANDING_WINDOW = "EXPANDING_WINDOW"
    PURGED_TIME_SERIES = "PURGED_TIME_SERIES"


class GapDisposition(StrEnum):
    """Whether exact exclusion evidence applies to a purge or embargo."""

    EXCLUDED_INTERVAL = "EXCLUDED_INTERVAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _timestamp(value: object, field: str) -> _ExactTimestamp:
    if not isinstance(value, str):
        raise TemporalValidationError(f"{field} must be a UTC RFC 3339 string")
    match = _TIMESTAMP_PATTERN.fullmatch(value)
    if match is None:
        raise TemporalValidationError(
            f"{field} must be an explicit UTC RFC 3339 timestamp"
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
        raise TemporalValidationError(
            f"{field} has an invalid calendar value"
        ) from error
    fraction = match.group("fraction") or "0"
    return (*components, Decimal(f"0.{fraction}"))


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TemporalValidationError(f"{field} must be a nonempty string")
    return value


def _excluded_interval(evidence: GapEvidence, field: str) -> TemporalInterval:
    interval = evidence.interval
    if not isinstance(interval, TemporalInterval):
        raise TemporalValidationError(f"{field} exclusion interval is malformed")
    return interval


@dataclass(frozen=True, slots=True)
class TemporalInterval:
    """A nonempty half-open UTC interval ``[start, end)`` at exact input precision."""

    start: str
    end: str

    def __post_init__(self) -> None:
        if self.start_key >= self.end_key:
            raise TemporalValidationError("Temporal interval must satisfy start < end")

    @property
    def start_key(self) -> _ExactTimestamp:
        return _timestamp(self.start, "interval start")

    @property
    def end_key(self) -> _ExactTimestamp:
        return _timestamp(self.end, "interval end")

    def overlaps(self, other: TemporalInterval) -> bool:
        """Return whether two half-open intervals share any instant."""
        return self.start_key < other.end_key and other.start_key < self.end_key

    def contains(self, other: TemporalInterval) -> bool:
        """Return whether this interval fully contains another half-open interval."""
        return self.start_key <= other.start_key and other.end_key <= self.end_key

    def document(self) -> JsonRecord:
        return {"start": self.start, "end": self.end}


@dataclass(frozen=True, slots=True)
class ChronologicalPartitions:
    """Explicit top-level development, validation, and sealed metadata boundaries."""

    training_development: TemporalInterval
    validation: TemporalInterval
    sealed_out_of_sample: TemporalInterval
    sealed_reference: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(interval, TemporalInterval)
            for interval in (
                self.training_development,
                self.validation,
                self.sealed_out_of_sample,
            )
        ):
            raise TemporalValidationError("Every required partition must be explicit")
        _nonempty(self.sealed_reference, "sealed OOS reference")
        if self.training_development.end_key > self.validation.start_key:
            raise TemporalValidationError("Training/development overlaps validation")
        if self.validation.end_key > self.sealed_out_of_sample.start_key:
            raise TemporalValidationError("Validation overlaps sealed OOS")

    def document(self) -> JsonRecord:
        return {
            "training_development": self.training_development.document(),
            "validation": self.validation.document(),
            "sealed_out_of_sample": self.sealed_out_of_sample.document(),
            "sealed_reference": self.sealed_reference,
        }


@dataclass(frozen=True, slots=True)
class GapEvidence:
    """Exact excluded interval or explicit rationale that a gap is not applicable."""

    disposition: GapDisposition
    interval: TemporalInterval | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, GapDisposition):
            raise TemporalValidationError("Gap disposition is malformed")
        if self.disposition is GapDisposition.EXCLUDED_INTERVAL:
            if (
                not isinstance(self.interval, TemporalInterval)
                or self.rationale is not None
            ):
                raise TemporalValidationError(
                    "Excluded gap evidence requires only one exact interval"
                )
        elif self.interval is not None:
            raise TemporalValidationError(
                "NOT_APPLICABLE gap evidence cannot include an interval"
            )
        else:
            _nonempty(self.rationale, "NOT_APPLICABLE gap rationale")

    @classmethod
    def excluded(cls, interval: TemporalInterval) -> GapEvidence:
        return cls(GapDisposition.EXCLUDED_INTERVAL, interval=interval)

    @classmethod
    def not_applicable(cls, rationale: str) -> GapEvidence:
        return cls(GapDisposition.NOT_APPLICABLE, rationale=rationale)

    def document(self) -> JsonRecord:
        if self.disposition is GapDisposition.EXCLUDED_INTERVAL:
            interval = _excluded_interval(self, "gap")
            return {
                "disposition": self.disposition.value,
                "interval": interval.document(),
            }
        return {
            "disposition": self.disposition.value,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class ValidationFold:
    """One explicitly sequenced temporal fold with purge and embargo evidence."""

    fold_id: str
    sequence: int
    scheme: ValidationScheme
    training: TemporalInterval
    validation: TemporalInterval
    purge: GapEvidence
    embargo: GapEvidence

    def __post_init__(self) -> None:
        if _FOLD_ID_PATTERN.fullmatch(_nonempty(self.fold_id, "fold identity")) is None:
            raise TemporalValidationError(
                "Fold identity contains unsupported characters"
            )
        if type(self.sequence) is not int or self.sequence < 1:
            raise TemporalValidationError("Fold sequence must be a positive integer")
        if not isinstance(self.scheme, ValidationScheme):
            raise TemporalValidationError("Fold validation scheme is malformed")
        if not isinstance(self.training, TemporalInterval) or not isinstance(
            self.validation, TemporalInterval
        ):
            raise TemporalValidationError("Fold intervals must be explicit")
        if not isinstance(self.purge, GapEvidence) or not isinstance(
            self.embargo, GapEvidence
        ):
            raise TemporalValidationError("Fold gap evidence must be explicit")
        if self.training.end_key > self.validation.start_key:
            raise TemporalValidationError("Fold training extends into validation")
        self._validate_purge()
        self._validate_embargo()

    def _validate_purge(self) -> None:
        if self.purge.disposition is GapDisposition.NOT_APPLICABLE:
            return
        interval = _excluded_interval(self.purge, "purge")
        if (
            interval.start_key != self.training.end_key
            or interval.end_key != self.validation.start_key
        ):
            raise TemporalValidationError(
                "Purge interval must exactly exclude the pre-validation gap"
            )

    def _validate_embargo(self) -> None:
        if self.embargo.disposition is GapDisposition.NOT_APPLICABLE:
            return
        interval = _excluded_interval(self.embargo, "embargo")
        if interval.start_key != self.validation.end_key:
            raise TemporalValidationError(
                "Embargo interval must begin at the validation end boundary"
            )

    def document(self) -> JsonRecord:
        return {
            "fold_id": self.fold_id,
            "sequence": self.sequence,
            "scheme": self.scheme.value,
            "training": self.training.document(),
            "validation": self.validation.document(),
            "purge": self.purge.document(),
            "embargo": self.embargo.document(),
        }


@dataclass(frozen=True, slots=True)
class ValidationPlan:
    """Canonical verified temporal-validation configuration; it performs no split."""

    partitions: ChronologicalPartitions
    scheme: ValidationScheme
    folds: tuple[ValidationFold, ...]
    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise TemporalValidationIntegrityError(
                "Validation plan is not a JSON object"
            )
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)
        _validate_fold_sequence(self.partitions, self.scheme, self.folds)
        expected = _plan_document(self.partitions, self.scheme, self.folds)
        if canonicalize_json(expected) != self.canonical_bytes:
            raise TemporalValidationIntegrityError(
                "Validation plan canonical evidence does not match typed fields"
            )


def _plan_document(
    partitions: ChronologicalPartitions,
    scheme: ValidationScheme,
    folds: tuple[ValidationFold, ...],
) -> JsonRecord:
    fold_values: list[JsonValue] = [fold.document() for fold in folds]
    return {
        "schema_version": "1.0.0",
        "plan_type": "TEMPORAL_VALIDATION_PLAN",
        "interval_boundary_semantics": INTERVAL_BOUNDARY_SEMANTICS,
        "scheme": scheme.value,
        "partitions": partitions.document(),
        "folds": fold_values,
    }


def _validate_fold_sequence(
    partitions: ChronologicalPartitions,
    scheme: ValidationScheme,
    folds: tuple[ValidationFold, ...],
) -> None:
    expected_sequences = tuple(range(1, len(folds) + 1))
    if tuple(fold.sequence for fold in folds) != expected_sequences:
        raise TemporalValidationError("Fold sequences must be unique and contiguous")
    if len({fold.fold_id for fold in folds}) != len(folds):
        raise TemporalValidationError("Fold identities must be unique")
    if any(fold.scheme is not scheme for fold in folds):
        raise TemporalValidationError("Every fold scheme must match its plan")
    if scheme is ValidationScheme.CHRONOLOGICAL_HOLDOUT and len(folds) != 1:
        raise TemporalValidationError("Chronological holdout requires exactly one fold")
    if (
        scheme in {ValidationScheme.ROLLING_WINDOW, ValidationScheme.EXPANDING_WINDOW}
        and len(folds) < 2
    ):
        raise TemporalValidationError(
            "Rolling and expanding plans require multiple folds"
        )
    if scheme is ValidationScheme.PURGED_TIME_SERIES and any(
        fold.purge.disposition is not GapDisposition.EXCLUDED_INTERVAL for fold in folds
    ):
        raise TemporalValidationError(
            "Purged validation requires explicit purge evidence"
        )

    for fold in folds:
        if fold.training.overlaps(
            partitions.sealed_out_of_sample
        ) or fold.validation.overlaps(partitions.sealed_out_of_sample):
            raise TemporalValidationError("Fold consumes sealed OOS")
        if not partitions.training_development.contains(fold.training):
            raise TemporalValidationError(
                "Fold training lies outside training/development"
            )
        if not partitions.validation.contains(fold.validation):
            raise TemporalValidationError("Fold validation lies outside validation")
        for evidence in (fold.purge, fold.embargo):
            if evidence.interval is not None and evidence.interval.overlaps(
                partitions.sealed_out_of_sample
            ):
                raise TemporalValidationError("Gap evidence consumes sealed OOS")
    for previous, current in pairwise(folds):
        if previous.validation.end_key > current.validation.start_key:
            raise TemporalValidationError("Validation folds run backward or overlap")
        if scheme is ValidationScheme.ROLLING_WINDOW and not (
            previous.training.start_key < current.training.start_key
            and previous.training.end_key < current.training.end_key
        ):
            raise TemporalValidationError("Rolling training windows must advance")
        if scheme is ValidationScheme.EXPANDING_WINDOW and not (
            previous.training.start_key == current.training.start_key
            and previous.training.end_key < current.training.end_key
        ):
            raise TemporalValidationError(
                "Expanding training windows must share a start"
            )

    included_intervals = tuple(
        interval for fold in folds for interval in (fold.training, fold.validation)
    )
    for fold in folds:
        for evidence in (fold.purge, fold.embargo):
            if evidence.interval is not None and any(
                evidence.interval.overlaps(included) for included in included_intervals
            ):
                raise TemporalValidationError(
                    "Excluded purge or embargo interval is consumed by a fold"
                )


def build_validation_plan(
    partitions: ChronologicalPartitions,
    scheme: ValidationScheme,
    folds: Sequence[ValidationFold],
) -> ValidationPlan:
    """Validate, order, and canonically identify a metadata-only validation plan."""
    if not isinstance(partitions, ChronologicalPartitions):
        raise TemporalValidationError("Chronological partitions must be explicit")
    if not isinstance(scheme, ValidationScheme):
        raise TemporalValidationError("Validation scheme is malformed")
    supplied = tuple(folds)
    if not supplied or any(not isinstance(fold, ValidationFold) for fold in supplied):
        raise TemporalValidationError("At least one typed validation fold is required")
    ordered = tuple(sorted(supplied, key=lambda fold: fold.sequence))
    _validate_fold_sequence(partitions, scheme, ordered)
    document = _plan_document(partitions, scheme, ordered)
    canonical_bytes = canonicalize_json(deepcopy(document))
    plan = ValidationPlan(
        partitions=partitions,
        scheme=scheme,
        folds=ordered,
        canonical_bytes=canonical_bytes,
        digest=sha256_bytes(canonical_bytes),
    )
    plan.verify()
    return plan
