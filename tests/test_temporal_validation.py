"""Synthetic hostile tests for Item 9A temporal-validation contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import NoReturn, cast

import pytest

from quant_hunter.provenance.hashing import DigestMismatchError, sha256_bytes
from quant_hunter.validation import (
    INTERVAL_BOUNDARY_SEMANTICS,
    ChronologicalPartitions,
    GapDisposition,
    GapEvidence,
    TemporalInterval,
    TemporalValidationError,
    TemporalValidationIntegrityError,
    ValidationFold,
    ValidationPlan,
    ValidationScheme,
    build_validation_plan,
)


def interval(start: str, end: str) -> TemporalInterval:
    return TemporalInterval(f"2020-01-{start}T00:00:00Z", f"2020-01-{end}T00:00:00Z")


def partitions(
    *, sealed_reference: str = "sealed://synthetic/holdout"
) -> ChronologicalPartitions:
    return ChronologicalPartitions(
        training_development=interval("01", "10"),
        validation=interval("10", "20"),
        sealed_out_of_sample=interval("20", "30"),
        sealed_reference=sealed_reference,
    )


def not_applicable() -> GapEvidence:
    return GapEvidence.not_applicable(
        "Synthetic labels have no horizon; execution must reassess applicability."
    )


def holdout_fold() -> ValidationFold:
    return ValidationFold(
        fold_id="holdout-1",
        sequence=1,
        scheme=ValidationScheme.CHRONOLOGICAL_HOLDOUT,
        training=interval("01", "10"),
        validation=interval("10", "20"),
        purge=not_applicable(),
        embargo=not_applicable(),
    )


def rolling_folds() -> tuple[ValidationFold, ValidationFold]:
    return (
        ValidationFold(
            fold_id="rolling-1",
            sequence=1,
            scheme=ValidationScheme.ROLLING_WINDOW,
            training=interval("01", "05"),
            validation=interval("10", "12"),
            purge=not_applicable(),
            embargo=not_applicable(),
        ),
        ValidationFold(
            fold_id="rolling-2",
            sequence=2,
            scheme=ValidationScheme.ROLLING_WINDOW,
            training=interval("02", "06"),
            validation=interval("12", "14"),
            purge=not_applicable(),
            embargo=not_applicable(),
        ),
    )


def expanding_folds() -> tuple[ValidationFold, ValidationFold]:
    first, second = rolling_folds()
    return (
        replace(
            first,
            fold_id="expanding-1",
            scheme=ValidationScheme.EXPANDING_WINDOW,
        ),
        replace(
            second,
            fold_id="expanding-2",
            scheme=ValidationScheme.EXPANDING_WINDOW,
            training=interval("01", "06"),
        ),
    )


def test_valid_chronological_partitions_and_holdout_are_canonical() -> None:
    plan = build_validation_plan(
        partitions(), ValidationScheme.CHRONOLOGICAL_HOLDOUT, (holdout_fold(),)
    )

    plan.verify()
    assert plan.document["interval_boundary_semantics"] == INTERVAL_BOUNDARY_SEMANTICS
    assert plan.document["scheme"] == "CHRONOLOGICAL_HOLDOUT"
    assert plan.document["partitions"] == partitions().document()
    assert plan.document["folds"] == [holdout_fold().document()]
    assert (
        build_validation_plan(
            partitions(), ValidationScheme.CHRONOLOGICAL_HOLDOUT, (holdout_fold(),)
        )
        == plan
    )


def test_adjacent_half_open_intervals_do_not_overlap() -> None:
    before = TemporalInterval(
        "2020-01-01T00:00:00.000000001Z",
        "2020-01-01T00:00:00.000000002Z",
    )
    after = TemporalInterval(
        "2020-01-01T00:00:00.000000002Z",
        "2020-01-01T00:00:00.000000003Z",
    )

    assert not before.overlaps(after)
    assert not after.overlaps(before)
    assert before.end == after.start


def test_one_nanosecond_partition_progress_is_preserved() -> None:
    plan_partitions = ChronologicalPartitions(
        TemporalInterval("2020-01-01T00:00:00Z", "2020-01-01T00:00:00.000000001Z"),
        TemporalInterval(
            "2020-01-01T00:00:00.000000001Z",
            "2020-01-01T00:00:00.000000002Z",
        ),
        TemporalInterval(
            "2020-01-01T00:00:00.000000002Z",
            "2020-01-01T00:00:00.000000003Z",
        ),
        "sealed://synthetic/nanosecond",
    )

    assert plan_partitions.validation.start.endswith("000000001Z")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2020-01-02T00:00:00Z", "2020-01-01T00:00:00Z"),
        (
            "2020-01-01T00:00:00.000000000000000002Z",
            "2020-01-01T00:00:00.000000000000000001Z",
        ),
        ("2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z"),
    ],
)
def test_reversed_or_empty_intervals_fail(start: str, end: str) -> None:
    with pytest.raises(TemporalValidationError, match="start < end"):
        TemporalInterval(start, end)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2020-01-01T00:00:00",
        "2020-01-01T00:00:00+00:00",
        "2020-01-01T00:00:00-05:00",
        "2020-13-01T00:00:00Z",
        "2021-02-29T00:00:00Z",
        "not-a-timestamp",
    ],
)
def test_non_utc_malformed_or_invalid_calendar_timestamp_fails(timestamp: str) -> None:
    with pytest.raises(TemporalValidationError):
        TemporalInterval(timestamp, "2022-01-01T00:00:00Z")


def test_non_string_timestamp_fails_closed() -> None:
    with pytest.raises(TemporalValidationError, match="UTC RFC 3339 string"):
        TemporalInterval(cast(str, None), "2022-01-01T00:00:00Z")


def test_top_level_partition_overlap_fails() -> None:
    with pytest.raises(TemporalValidationError, match="overlaps validation"):
        ChronologicalPartitions(
            interval("01", "11"),
            interval("10", "20"),
            interval("20", "30"),
            "sealed://synthetic/holdout",
        )
    with pytest.raises(TemporalValidationError, match="overlaps sealed OOS"):
        ChronologicalPartitions(
            interval("01", "10"),
            interval("10", "21"),
            interval("20", "30"),
            "sealed://synthetic/holdout",
        )


@pytest.mark.parametrize(
    ("scheme", "folds"),
    [
        (ValidationScheme.ROLLING_WINDOW, rolling_folds()),
        (ValidationScheme.EXPANDING_WINDOW, expanding_folds()),
    ],
)
def test_valid_rolling_and_expanding_folds_pass(
    scheme: ValidationScheme, folds: tuple[ValidationFold, ...]
) -> None:
    plan = build_validation_plan(partitions(), scheme, folds)

    assert tuple(fold.sequence for fold in plan.folds) == (1, 2)
    plan.verify()


def test_input_permutation_cannot_change_canonical_fold_chronology() -> None:
    first, second = rolling_folds()

    ordered = build_validation_plan(
        partitions(), ValidationScheme.ROLLING_WINDOW, (first, second)
    )
    permuted = build_validation_plan(
        partitions(), ValidationScheme.ROLLING_WINDOW, (second, first)
    )

    assert ordered == permuted
    assert ordered.canonical_bytes == permuted.canonical_bytes
    assert ordered.digest == permuted.digest


def test_declared_backward_fold_chronology_fails_after_deterministic_sort() -> None:
    first, second = rolling_folds()
    backward = (
        replace(first, validation=interval("12", "14")),
        replace(second, validation=interval("10", "12")),
    )

    with pytest.raises(TemporalValidationError, match="backward or overlap"):
        build_validation_plan(partitions(), ValidationScheme.ROLLING_WINDOW, backward)


def test_fold_that_consumes_sealed_interval_fails() -> None:
    fold = replace(
        holdout_fold(),
        validation=TemporalInterval(
            "2020-01-10T00:00:00Z", "2020-01-20T00:00:00.000000001Z"
        ),
    )

    with pytest.raises(TemporalValidationError, match="consumes sealed OOS"):
        build_validation_plan(
            partitions(), ValidationScheme.CHRONOLOGICAL_HOLDOUT, (fold,)
        )


def test_gap_evidence_that_consumes_sealed_interval_fails() -> None:
    fold = replace(
        holdout_fold(),
        embargo=GapEvidence.excluded(interval("20", "21")),
    )

    with pytest.raises(TemporalValidationError, match="Gap evidence consumes sealed"):
        build_validation_plan(
            partitions(), ValidationScheme.CHRONOLOGICAL_HOLDOUT, (fold,)
        )


def test_training_that_extends_into_validation_fails() -> None:
    with pytest.raises(TemporalValidationError, match="extends into validation"):
        replace(holdout_fold(), training=interval("01", "11"))


@pytest.mark.parametrize(
    "purge",
    [
        GapEvidence.excluded(interval("07", "09")),
        GapEvidence.excluded(interval("09", "11")),
    ],
)
def test_purge_on_wrong_side_or_not_covering_gap_fails(purge: GapEvidence) -> None:
    with pytest.raises(TemporalValidationError, match="pre-validation gap"):
        ValidationFold(
            fold_id="purged-1",
            sequence=1,
            scheme=ValidationScheme.PURGED_TIME_SERIES,
            training=interval("01", "08"),
            validation=interval("10", "12"),
            purge=purge,
            embargo=not_applicable(),
        )


def test_valid_exact_purge_and_embargo_evidence_passes() -> None:
    plan_partitions = ChronologicalPartitions(
        interval("01", "08"),
        interval("10", "16"),
        interval("20", "30"),
        "sealed://synthetic/purged-holdout",
    )
    fold = ValidationFold(
        fold_id="purged-1",
        sequence=1,
        scheme=ValidationScheme.PURGED_TIME_SERIES,
        training=interval("01", "08"),
        validation=interval("10", "12"),
        purge=GapEvidence.excluded(interval("08", "10")),
        embargo=GapEvidence.excluded(interval("12", "13")),
    )

    plan = build_validation_plan(
        plan_partitions, ValidationScheme.PURGED_TIME_SERIES, (fold,)
    )

    assert plan.folds[0].purge.disposition is GapDisposition.EXCLUDED_INTERVAL
    assert plan.folds[0].embargo.interval == interval("12", "13")


def test_contradictory_embargo_evidence_fails() -> None:
    with pytest.raises(TemporalValidationError, match="validation end boundary"):
        replace(
            holdout_fold(),
            embargo=GapEvidence.excluded(interval("19", "21")),
        )


def test_embargo_consumed_by_another_fold_fails() -> None:
    first, second = rolling_folds()
    first = replace(
        first,
        embargo=GapEvidence.excluded(interval("12", "13")),
    )
    second = replace(second, validation=interval("12", "14"))

    with pytest.raises(TemporalValidationError, match="consumed by a fold"):
        build_validation_plan(
            partitions(), ValidationScheme.ROLLING_WINDOW, (first, second)
        )


def test_not_applicable_gap_evidence_requires_explicit_rationale() -> None:
    evidence = not_applicable()
    assert evidence.document()["disposition"] == "NOT_APPLICABLE"

    with pytest.raises(TemporalValidationError, match="rationale"):
        GapEvidence.not_applicable("   ")
    with pytest.raises(TemporalValidationError, match="cannot include"):
        GapEvidence(
            GapDisposition.NOT_APPLICABLE,
            interval=interval("08", "09"),
            rationale="Contradictory evidence.",
        )
    with pytest.raises(TemporalValidationError, match="requires only"):
        GapEvidence(
            GapDisposition.EXCLUDED_INTERVAL,
            interval=interval("08", "09"),
            rationale="Redundant mutable explanation.",
        )


def test_malformed_gap_evidence_fails_closed() -> None:
    with pytest.raises(TemporalValidationError, match="disposition is malformed"):
        GapEvidence(cast(GapDisposition, "EXCLUDED_INTERVAL"), interval("08", "09"))

    evidence = GapEvidence.excluded(interval("08", "09"))
    object.__setattr__(evidence, "interval", None)
    with pytest.raises(TemporalValidationError, match="interval is malformed"):
        evidence.document()


def test_malformed_fold_fields_fail_closed() -> None:
    fold = holdout_fold()
    with pytest.raises(TemporalValidationError, match="unsupported characters"):
        replace(fold, fold_id="contains spaces")
    with pytest.raises(TemporalValidationError, match="positive integer"):
        replace(fold, sequence=cast(int, True))
    with pytest.raises(TemporalValidationError, match="scheme is malformed"):
        replace(fold, scheme=cast(ValidationScheme, "CHRONOLOGICAL_HOLDOUT"))
    with pytest.raises(TemporalValidationError, match="intervals must be explicit"):
        replace(fold, training=cast(TemporalInterval, None))
    with pytest.raises(TemporalValidationError, match="gap evidence must be explicit"):
        replace(fold, purge=cast(GapEvidence, None))


def test_fold_identity_sequence_and_scheme_conflicts_fail() -> None:
    first, second = rolling_folds()
    with pytest.raises(TemporalValidationError, match="identities must be unique"):
        build_validation_plan(
            partitions(),
            ValidationScheme.ROLLING_WINDOW,
            (first, replace(second, fold_id=first.fold_id)),
        )
    with pytest.raises(TemporalValidationError, match="unique and contiguous"):
        build_validation_plan(
            partitions(),
            ValidationScheme.ROLLING_WINDOW,
            (first, replace(second, sequence=3)),
        )
    with pytest.raises(TemporalValidationError, match="match its plan"):
        build_validation_plan(
            partitions(),
            ValidationScheme.ROLLING_WINDOW,
            (first, replace(second, scheme=ValidationScheme.EXPANDING_WINDOW)),
        )
    with pytest.raises(ValueError):
        ValidationScheme("RANDOM_K_FOLD")


def test_purged_scheme_requires_explicit_purge_evidence() -> None:
    fold = replace(
        holdout_fold(),
        scheme=ValidationScheme.PURGED_TIME_SERIES,
        fold_id="purged-1",
    )
    with pytest.raises(TemporalValidationError, match="explicit purge"):
        build_validation_plan(
            partitions(), ValidationScheme.PURGED_TIME_SERIES, (fold,)
        )


def test_scheme_fold_count_constraints_fail() -> None:
    fold = holdout_fold()
    with pytest.raises(TemporalValidationError, match="exactly one fold"):
        build_validation_plan(
            partitions(),
            ValidationScheme.CHRONOLOGICAL_HOLDOUT,
            (fold, replace(fold, fold_id="holdout-2", sequence=2)),
        )

    rolling = replace(fold, scheme=ValidationScheme.ROLLING_WINDOW)
    with pytest.raises(TemporalValidationError, match="require multiple folds"):
        build_validation_plan(partitions(), ValidationScheme.ROLLING_WINDOW, (rolling,))


def test_fold_outside_top_level_training_partition_fails() -> None:
    fold = replace(holdout_fold(), training=interval("02", "10"))
    narrowed = ChronologicalPartitions(
        training_development=interval("03", "10"),
        validation=interval("10", "20"),
        sealed_out_of_sample=interval("20", "30"),
        sealed_reference="sealed://synthetic/narrowed",
    )

    with pytest.raises(TemporalValidationError, match="outside training/development"):
        build_validation_plan(narrowed, ValidationScheme.CHRONOLOGICAL_HOLDOUT, (fold,))


def test_rolling_and_expanding_window_progression_failures() -> None:
    first, second = rolling_folds()
    with pytest.raises(TemporalValidationError, match="windows must advance"):
        build_validation_plan(
            partitions(),
            ValidationScheme.ROLLING_WINDOW,
            (first, replace(second, training=first.training)),
        )

    expanding_first, expanding_second = expanding_folds()
    with pytest.raises(TemporalValidationError, match="must share a start"):
        build_validation_plan(
            partitions(),
            ValidationScheme.EXPANDING_WINDOW,
            (expanding_first, replace(expanding_second, training=interval("02", "06"))),
        )


def test_plan_integrity_rejects_digest_or_typed_field_tampering() -> None:
    plan = build_validation_plan(
        partitions(), ValidationScheme.CHRONOLOGICAL_HOLDOUT, (holdout_fold(),)
    )

    with pytest.raises(DigestMismatchError):
        replace(plan, digest="sha256:" + "f" * 64).verify()
    with pytest.raises(TemporalValidationIntegrityError, match="typed fields"):
        replace(plan, partitions=partitions(sealed_reference="sealed://other")).verify()


def test_plan_document_must_be_a_json_object() -> None:
    canonical_bytes = b"[]"
    malformed = ValidationPlan(
        partitions=partitions(),
        scheme=ValidationScheme.CHRONOLOGICAL_HOLDOUT,
        folds=(holdout_fold(),),
        canonical_bytes=canonical_bytes,
        digest=sha256_bytes(canonical_bytes),
    )

    with pytest.raises(TemporalValidationIntegrityError, match="not a JSON object"):
        _ = malformed.document


def test_builder_requires_typed_nonempty_inputs() -> None:
    fold = holdout_fold()
    with pytest.raises(TemporalValidationError, match="partitions must be explicit"):
        build_validation_plan(
            cast(ChronologicalPartitions, None),
            ValidationScheme.CHRONOLOGICAL_HOLDOUT,
            (fold,),
        )
    with pytest.raises(TemporalValidationError, match="scheme is malformed"):
        build_validation_plan(
            partitions(), cast(ValidationScheme, "CHRONOLOGICAL_HOLDOUT"), (fold,)
        )
    with pytest.raises(TemporalValidationError, match="At least one typed"):
        build_validation_plan(partitions(), ValidationScheme.CHRONOLOGICAL_HOLDOUT, ())
    with pytest.raises(TemporalValidationError, match="At least one typed"):
        build_validation_plan(
            partitions(),
            ValidationScheme.CHRONOLOGICAL_HOLDOUT,
            cast(Sequence[ValidationFold], (object(),)),
        )


def test_partitions_require_typed_intervals_and_reference() -> None:
    with pytest.raises(TemporalValidationError, match="partition must be explicit"):
        ChronologicalPartitions(
            cast(TemporalInterval, None),
            interval("10", "20"),
            interval("20", "30"),
            "sealed://synthetic/holdout",
        )
    with pytest.raises(TemporalValidationError, match="nonempty string"):
        partitions(sealed_reference=" ")


def test_sealed_reference_is_never_opened_listed_statted_read_or_hashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = (tmp_path / "sealed" / "holdout.bin").resolve()

    def reject_filesystem_access(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("validation planning attempted filesystem access")

    monkeypatch.setattr(Path, "open", reject_filesystem_access)
    monkeypatch.setattr(Path, "iterdir", reject_filesystem_access)
    monkeypatch.setattr(Path, "stat", reject_filesystem_access)
    monkeypatch.setattr(Path, "read_bytes", reject_filesystem_access)

    plan = build_validation_plan(
        partitions(sealed_reference=str(sealed)),
        ValidationScheme.CHRONOLOGICAL_HOLDOUT,
        (holdout_fold(),),
    )

    partition_document = plan.document["partitions"]
    assert isinstance(partition_document, dict)
    assert partition_document["sealed_reference"] == str(sealed)
