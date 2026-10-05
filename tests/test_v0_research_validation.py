"""Independent fold-membership, uncertainty and canonical all-trials oracles."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

import quant_hunter
from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.lab import LabService
from quant_hunter.research_validation import (
    BootstrapSpec,
    ObservationTimes,
    ResearchValidationError,
    ResearchValidationService,
    SupervisedRow,
    execute_walk_forward,
    holm_adjust,
    moving_block_mean,
    protocol_document,
    resolve_membership,
)
from quant_hunter.validation import (
    ChronologicalPartitions,
    GapEvidence,
    TemporalInterval,
    ValidationFold,
    ValidationScheme,
    bind_frozen_temporal_validation,
    build_validation_plan,
)

SCHEMAS = Path(quant_hunter.__file__).parents[2] / "schemas" / "v1"
CODE = "7346cf4f79ca5897777c0118f8cf4c2292be929e"


def dt(day: int, hour: int = 0) -> datetime:
    return datetime.fromisoformat(f"2025-01-{day:02}T{hour:02}:00:00Z")


def interval(start: int, end: int) -> TemporalInterval:
    return TemporalInterval(
        dt(start).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        dt(end).isoformat(timespec="microseconds").replace("+00:00", "Z"),
    )


def plan() -> Any:
    partitions = ChronologicalPartitions(
        interval(1, 11),
        interval(11, 21),
        interval(21, 22),
        "sealed://metadata-only/never-open",
    )
    fold = ValidationFold(
        "holdout-1",
        1,
        ValidationScheme.CHRONOLOGICAL_HOLDOUT,
        interval(1, 10),
        interval(11, 20),
        GapEvidence.excluded(interval(10, 11)),
        GapEvidence.excluded(interval(20, 21)),
    )
    return build_validation_plan(
        partitions, ValidationScheme.CHRONOLOGICAL_HOLDOUT, (fold,)
    )


def binding() -> Any:
    value = plan()
    return bind_frozen_temporal_validation(
        {
            "experiment_id": "EXP-01990f30-7f5e-7b34-9b21-3d74c513c848",
            "lifecycle_status": "FROZEN",
            "partitions": {
                "training": interval(1, 11).document(),
                "validation": interval(11, 21).document(),
                "sealed_out_of_sample": interval(21, 22).document(),
            },
        },
        "sha256:" + "a" * 64,
        value,
    )


def row(
    day: int, *, available: datetime | None = None, label: float | None = None
) -> SupervisedRow:
    return SupervisedRow(
        ObservationTimes(
            f"r{day}",
            dt(day),
            dt(day),
            dt(day),
            dt(day),
            dt(day),
            dt(day, 1),
            available or dt(day, 2),
        ),
        (float(day),),
        float(day * 2) if label is None else label,
    )


def fit_linear(x: tuple[tuple[float, ...], ...], y: tuple[float, ...]) -> Any:
    assert all(
        abs(target - 2 * features[0]) < 1e-12
        for features, target in zip(x, y, strict=True)
    )
    return lambda values: 2 * values[0]


def test_positive_train_only_prediction_and_delayed_label_oracle() -> None:
    rows = (
        row(2),
        row(3),
        row(4),
        row(11),
        row(12, available=dt(22), label=float("nan")),
    )
    output = execute_walk_forward(binding(), rows, fit_linear, evaluation_as_of=dt(20))
    fold = cast(list[dict[str, Any]], output["folds"])[0]
    assert fold["training_ids"] == ["r2", "r3", "r4"]
    assert [r["prediction"] for r in fold["predictions"]] == [22, 24]
    assert fold["predictions"][1]["label"] is None
    assert fold["predictions"][1]["outcome_status"] == "PENDING_LABEL_RECEIPT"
    changed = replace(rows[-1], features=(200.0,))
    again = execute_walk_forward(
        binding(), (*rows[:-1], changed), fit_linear, evaluation_as_of=dt(20)
    )
    assert (
        cast(list[dict[str, Any]], again["folds"])[0]["predictions"][0]
        == fold["predictions"][0]
    )
    assert (
        cast(list[dict[str, Any]], again["folds"])[0]["predictions"][1]["prediction"]
        == 400
    )


def test_delayed_training_numeric_nan_is_not_read() -> None:
    delayed = replace(
        row(5, available=dt(12), label=float("nan")), features=(float("nan"),)
    )
    rows = (row(2), row(3), row(4), delayed, row(11))
    output = execute_walk_forward(binding(), rows, fit_linear, evaluation_as_of=dt(20))
    fold = cast(list[dict[str, Any]], output["folds"])[0]
    assert {"row_id": "r5", "reason": "LABEL_NOT_AVAILABLE_AT_FIT"} in fold[
        "exclusions"
    ]
    assert fold["predictions"][0]["prediction"] == 22


def test_actual_feature_purge_and_future_availability_exclusions() -> None:
    affected = replace(row(11).timing, feature_start=dt(10), feature_end=dt(11))
    delayed = replace(row(12).timing, feature_available_at=dt(12, 1))
    result = resolve_membership(plan(), (row(2).timing, affected, delayed))[0]
    assert result.validation_ids == ()
    assert ("r11", "PURGE_DEPENDENCY") in result.exclusions
    assert ("r12", "FEATURE_NOT_AVAILABLE_AT_DECISION") in result.exclusions


def test_sealed_numeric_values_are_never_consumed() -> None:
    with pytest.raises(ResearchValidationError, match="SEALED"):
        execute_walk_forward(
            binding(),
            (row(2), row(21, label=float("nan"))),
            fit_linear,
            evaluation_as_of=dt(23),
        )


def test_insufficient_and_pending_folds_do_not_fit() -> None:
    def forbidden(*args: Any) -> Any:
        pytest.fail("Must not fit an unavailable or insufficient fold")

    output = execute_walk_forward(
        binding(), (row(2), row(11)), forbidden, evaluation_as_of=dt(20)
    )
    assert (
        cast(list[dict[str, Any]], output["folds"])[0]["reason"]
        == "INSUFFICIENT_SAMPLE"
    )
    pending = execute_walk_forward(
        binding(), (row(2), row(3), row(4), row(11)), forbidden, evaluation_as_of=dt(12)
    )
    assert cast(list[dict[str, Any]], pending["folds"])[0]["status"] == "PENDING"


@pytest.mark.parametrize(
    "change",
    [
        lambda t: replace(t, decision_at=t.decision_at.replace(tzinfo=None)),
        lambda t: replace(t, feature_end=t.feature_available_at + timedelta(seconds=1)),
        lambda t: replace(t, label_end=t.label_start),
        lambda t: replace(t, label_available_at=t.label_end - timedelta(seconds=1)),
    ],
)
def test_invalid_timing_is_rejected(change: Any) -> None:
    with pytest.raises(ResearchValidationError):
        change(row(2).timing)


def test_duplicate_unsorted_and_nonfinite_admitted_inputs_fail() -> None:
    with pytest.raises(ResearchValidationError, match="DUPLICATE"):
        resolve_membership(plan(), (row(3).timing, row(2).timing))
    with pytest.raises(ResearchValidationError, match="FEATURE"):
        execute_walk_forward(
            binding(),
            (replace(row(2), features=(float("inf"),)), row(3), row(4), row(11)),
            fit_linear,
            evaluation_as_of=dt(20),
        )


def test_bootstrap_oracle_uses_overlapping_non_circular_blocks() -> None:
    values = tuple(float(x) for x in range(1, 9))
    spec = BootstrapSpec(2, 100, 17, "0.90", 4)
    actual = moving_block_mean(values, spec)
    # Independent index-loop oracle; no slicing/concatenation path reused.
    generator = np.random.Generator(np.random.PCG64(17))
    means: list[float] = []
    for _ in range(100):
        starts = generator.integers(0, 7, size=4)
        means.append(
            sum(values[int(start) + offset] for start in starts for offset in (0, 1))
            / 8
        )
    ordered = sorted(means)

    def quantile(q: float) -> float:
        position = q * 99
        low = int(position)
        return ordered[low] + (position - low) * (
            ordered[min(low + 1, 99)] - ordered[low]
        )

    assert actual["mean"] == 4.5
    assert actual["interval"] == pytest.approx([quantile(0.05), quantile(0.95)])
    assert actual["p_value"] is None
    assert moving_block_mean(values, spec) == actual
    assert moving_block_mean(tuple(x + 10 for x in values), spec)[
        "interval"
    ] == pytest.approx([x + 10 for x in cast(list[float], actual["interval"])])
    assert moving_block_mean((3.0,) * 8, spec)["interval"] == [3.0, 3.0]


def test_bootstrap_is_not_a_constant_success_or_unbounded_allocation() -> None:
    assert (
        moving_block_mean((1.0, 2.0, 3.0), BootstrapSpec(2, 100, 1))["status"]
        == "INCONCLUSIVE"
    )
    with pytest.raises(ResearchValidationError, match="WORK_LIMIT"):
        moving_block_mean((1.0,) * 100_000, BootstrapSpec(2, 1000, 1))
    with pytest.raises(ResearchValidationError, match="INVALID_BOOTSTRAP_VALUE"):
        moving_block_mean((float("nan"),), BootstrapSpec(1, 100, 1))


def test_holm_exact_small_oracle_and_stable_equal_ranks() -> None:
    result = holm_adjust((("d", ".8"), ("b", ".02"), ("a", ".01"), ("c", ".03")))
    values = cast(list[dict[str, Any]], result["values"])
    assert [Decimal(v["adjusted_p_value"]) for v in values] == [
        Decimal(".04"),
        Decimal(".06"),
        Decimal(".06"),
        Decimal(".8"),
    ]
    assert [v["rejected"] for v in values] == [True, False, False, False]
    tied = holm_adjust((("b", ".01"), ("a", ".01")))
    assert [v["trial_id"] for v in cast(list[dict[str, Any]], tied["values"])] == [
        "a",
        "b",
    ]


def test_holm_boundary_is_exact_even_with_hostile_ambient_precision() -> None:
    raw = "0.025000000000000000000000000001"
    with localcontext() as context:
        context.prec = 2
        context.Emin = -2
        context.Emax = 2
        result = holm_adjust((("a", raw), ("b", "0.5")))
    first = cast(list[dict[str, Any]], result["values"])[0]
    assert first["adjusted_p_value"] == "0.050000000000000000000000000002"
    assert first["rejected"] is False


@pytest.mark.parametrize(
    "value", ["nan", "Infinity", "-0.01", "1.1", "1e-999999999", "bad"]
)
def test_invalid_p_values_fail(value: str) -> None:
    with pytest.raises(ResearchValidationError, match="P_VALUE"):
        holm_adjust((("x", value),))


def lab(tmp_path: Path) -> LabService:
    return LabService(tmp_path / "lab", SCHEMAS, CODE, {"synthetic_environment": True})


def config(protocol: JsonRecord) -> JsonRecord:
    return {
        "market": "EQUITY",
        "initial_cash": "10000",
        "quantity": "1",
        "commission_per_order": "1",
        "slippage_bps": "1",
        "lookback": 2,
        "dataset_start": "2025-01-01T00:00:00Z",
        "dataset_end": "2025-01-21T00:00:00Z",
        "chronological_validation": protocol,
    }


def test_actual_item8_frozen_binding_and_changed_protocol_refusal(
    tmp_path: Path,
) -> None:
    runtime = lab(tmp_path)
    protocol = protocol_document(
        plan(), BootstrapSpec(2, 100, 1), minimum_train=3, minimum_validation=1
    )
    identity = runtime.begin_run(
        config(protocol), b'{"synthetic_dataset":"software oracle"}'
    )
    service = ResearchValidationService(runtime.registry, runtime.objects)
    actual = service.bind(identity, plan(), protocol)
    assert actual.experiment_id == identity
    with pytest.raises(ResearchValidationError, match="PROTOCOL_NOT_FROZEN"):
        service.bind(identity, plan(), {**protocol, "minimum_train": 4})
    runtime.fail_run(identity, "Synthetic intentional interruption")
    assert (
        service.bind(identity, plan(), protocol).frozen_revision_digest
        == actual.frozen_revision_digest
    )
    family = cast(
        str, runtime.registry.verify_object(identity)[-1].record["research_family_id"]
    )
    result = service.adjusted_family(family)
    assert cast(dict[str, Any], result["inventory"])["total_attempts"] == 1
    assert cast(dict[str, Any], result["inventory"])["failed_attempts"] == 1
    assert cast(dict[str, Any], result["adjustment"])["adjusted_p_values"] is None


def test_retained_test_result_complete_family_then_failed_trial_blocks(
    tmp_path: Path,
) -> None:
    runtime = lab(tmp_path)
    definition = runtime.objects.publish(
        canonicalize_json(
            {
                "method": "Synthetic independent p-value arithmetic oracle; no empirical calibration"
            }
        )
    )
    protocol = protocol_document(
        plan(),
        BootstrapSpec(2, 100, 1),
        minimum_train=3,
        minimum_validation=1,
        test_definition_digest=definition.digest,
    )
    identity = runtime.begin_run(
        config(protocol), b'{"synthetic_dataset":"software oracle"}'
    )
    service = ResearchValidationService(runtime.registry, runtime.objects)
    frozen = service.bind(identity, plan(), protocol)
    head = runtime.registry.verify_object(identity)[-1]
    runtime.evaluate_run(
        identity,
        {
            "schema_version": "qh-prespecified-trial-tests-v1",
            "experiment_id": identity,
            "frozen_revision_digest": frozen.frozen_revision_digest,
            "tests": [
                {
                    "attempt_number": 1,
                    "variant_configuration_digest": head.record["configuration_digest"],
                    "test_definition_digest": definition.digest,
                    "p_value": "0.03",
                }
            ],
        },
    )
    family = cast(str, head.record["research_family_id"])
    complete = service.adjusted_family(family)
    assert (
        cast(dict[str, Any], complete["adjustment"])["status"]
        == "COMPUTED_SOFTWARE_ONLY"
    )
    failed_id = runtime.begin_run(
        config(protocol), b'{"synthetic_dataset":"failed variant"}'
    )
    runtime.fail_run(failed_id, "Synthetic deliberately failed variant")
    incomplete = service.adjusted_family(family)
    inventory = cast(dict[str, Any], incomplete["inventory"])
    assert (
        inventory["total_attempts"],
        inventory["failed_attempts"],
        inventory["ai_generated_attempts"],
    ) == (2, 1, 2)
    assert cast(dict[str, Any], incomplete["adjustment"])["status"] == "INCONCLUSIVE"
    assert complete["promotion_allowed"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("block_length", 0),
        ("repetitions", 99),
        ("seed", True),
        ("confidence", ".95"),
        ("minimum_observations", 3),
    ],
)
def test_bootstrap_policy_must_be_prespecified_and_bounded(
    field: str, value: Any
) -> None:
    with pytest.raises(ResearchValidationError, match="SPECIFICATION"):
        replace(BootstrapSpec(2, 100, 1), **{field: value})


@pytest.mark.parametrize(
    "values,alpha",
    [
        ((), ".05"),
        ((("a", ".1"), ("a", ".2")), ".05"),
        ((("a", ".1"),), "0"),
        ((("a", ".1"),), "1"),
        ((("", ".1"),), ".05"),
        ((("a", ".1", "unexpected"),), ".05"),
    ],
)
def test_holm_rejects_incomplete_identity_or_invalid_alpha(
    values: Any, alpha: str
) -> None:
    with pytest.raises(ResearchValidationError):
        holm_adjust(values, alpha=alpha)


@pytest.mark.parametrize(
    "change",
    [
        "train_dimension",
        "query_dimension",
        "prediction_nan",
        "train_label_nan",
        "validation_label_nan",
        "threshold",
    ],
)
def test_admitted_learning_inputs_and_outputs_must_be_valid(change: str) -> None:
    rows = (row(2), row(3), row(4), row(11))
    fitter = fit_linear
    minimum = 3
    if change == "train_dimension":
        rows = (replace(rows[0], features=(2.0, 3.0)), *rows[1:])
    elif change == "query_dimension":
        rows = (*rows[:-1], replace(rows[-1], features=(11.0, 12.0)))
    elif change == "prediction_nan":

        def fitter(x: Any, y: Any) -> Any:
            return lambda vector: float("nan")
    elif change == "train_label_nan":
        rows = (replace(rows[0], label=float("nan")), *rows[1:])
    elif change == "validation_label_nan":
        rows = (*rows[:-1], replace(rows[-1], label=float("nan")))
    else:
        minimum = 1
    with pytest.raises(ResearchValidationError):
        execute_walk_forward(
            binding(), rows, fitter, evaluation_as_of=dt(20), minimum_train=minimum
        )


def test_canonical_running_authority_required_for_execution(tmp_path: Path) -> None:
    runtime = lab(tmp_path)
    protocol = protocol_document(
        plan(), BootstrapSpec(2, 100, 1), minimum_train=3, minimum_validation=1
    )
    identity = runtime.begin_run(config(protocol), b'{"synthetic":"oracle"}')
    service = ResearchValidationService(runtime.registry, runtime.objects)
    output = service.execute(
        identity,
        plan(),
        (row(2), row(3), row(4), row(11)),
        fit_linear,
        evaluation_as_of=dt(20),
    )
    assert output["experiment_id"] == identity
    assert output["empirical_status"] == "INCONCLUSIVE"
    runtime.fail_run(identity, "Synthetic stopped computation")
    with pytest.raises(ResearchValidationError, match="REQUIRES_ITEM8_RUNNING"):
        service.execute(
            identity,
            plan(),
            (row(2), row(3), row(4), row(11)),
            fit_linear,
            evaluation_as_of=dt(20),
        )


def scientific_declarations() -> dict[str, Any]:
    from quant_hunter.validation import (
        Applicability,
        BaselineDeclaration,
        BaselineRole,
        MetricDeclaration,
        ReportingConventions,
        RobustnessDeclaration,
        RobustnessRequirement,
        StandardMetric,
        StatisticalMethod,
        StatisticalMethodDeclaration,
    )

    rationale = (
        "Synthetic metadata-binding oracle; no scientific applicability asserted"
    )
    return {
        "baselines": tuple(
            BaselineDeclaration(
                f"b-{role.value.lower()}", role, Applicability.NOT_APPLICABLE, rationale
            )
            for role in BaselineRole
            if role is not BaselineRole.CUSTOM
        ),
        "metrics": tuple(
            MetricDeclaration(
                f"m-{metric.value.lower()}",
                Applicability.NOT_APPLICABLE,
                rationale,
                standard_metric=metric,
            )
            for metric in StandardMetric
        ),
        "statistical_methods": tuple(
            StatisticalMethodDeclaration(
                f"s-{method.value.lower()}",
                method,
                Applicability.NOT_APPLICABLE,
                rationale,
            )
            for method in StatisticalMethod
        ),
        "robustness_requirements": tuple(
            RobustnessDeclaration(
                f"r-{requirement.value.lower()}",
                requirement,
                Applicability.NOT_APPLICABLE,
                rationale,
            )
            for requirement in RobustnessRequirement
        ),
        "reporting_conventions": ReportingConventions(
            *(["Synthetic contract only; not an empirical method"] * 7)
        ),
    }


def test_actual_item9_scientific_plan_cannot_change_frozen_requirements(
    tmp_path: Path,
) -> None:
    from quant_hunter.validation import (
        bind_frozen_multiple_testing,
        build_scientific_evidence_plan,
    )

    runtime = lab(tmp_path)
    declarations = scientific_declarations()
    requirements: JsonRecord = {
        key: (
            value.document()
            if key == "reporting_conventions"
            else [v.document() for v in sorted(value, key=lambda v: v.declaration_id)]
        )
        for key, value in declarations.items()
    }
    protocol = protocol_document(
        plan(), BootstrapSpec(2, 100, 1), minimum_train=3, minimum_validation=1
    )
    identity = runtime.begin_run(
        {**config(protocol), "scientific_requirements": requirements},
        b'{"synthetic":"scientific-contract"}',
    )
    service = ResearchValidationService(runtime.registry, runtime.objects)
    temporal = service.bind(identity, plan(), protocol)
    frozen = next(
        r
        for r in runtime.registry.verify_object(identity)
        if r.digest == temporal.frozen_revision_digest
    )
    authority = cast(dict[str, Any], frozen.record["multiple_testing"])
    multiple = bind_frozen_multiple_testing(
        frozen.record,
        frozen.digest,
        family_id=authority["family_id"],
        budget=authority["budget"],
        correction_plan=authority["correction_plan"],
    )
    actual = build_scientific_evidence_plan(
        experiment_id=identity,
        temporal_validation=temporal,
        multiple_testing=multiple,
        **declarations,
    )
    assert service.bind_scientific_plan(identity, actual) == actual.digest
    assert runtime.objects.read_bytes(actual.digest) == actual.canonical_bytes
    changed_declarations = {
        **declarations,
        "reporting_conventions": replace(
            declarations["reporting_conventions"],
            annualization="Changed after freezing",
        ),
    }
    changed = build_scientific_evidence_plan(
        experiment_id=identity,
        temporal_validation=temporal,
        multiple_testing=multiple,
        **changed_declarations,
    )
    with pytest.raises(ResearchValidationError, match="REQUIREMENTS_NOT_FROZEN"):
        service.bind_scientific_plan(identity, changed)
    changed_multiple = replace(multiple, budget=multiple.budget + 1)
    changed = build_scientific_evidence_plan(
        experiment_id=identity,
        temporal_validation=temporal,
        multiple_testing=changed_multiple,
        **declarations,
    )
    with pytest.raises(ResearchValidationError, match="MULTIPLE_TESTING_BINDING"):
        service.bind_scientific_plan(identity, changed)


@pytest.mark.parametrize(
    "attack",
    [
        "ordinary_result",
        "missing_test",
        "foreign_identity",
        "malformed_tests",
        "duplicate_attempt",
        "foreign_definition",
        "unknown_attempt",
    ],
)
def test_canonical_test_artifacts_cannot_hide_or_rebind_trials(
    tmp_path: Path, attack: str
) -> None:
    runtime = lab(tmp_path)
    definition = runtime.objects.publish(b'{"synthetic":"prespecified oracle"}').digest
    protocol = protocol_document(
        plan(),
        BootstrapSpec(2, 100, 1),
        minimum_train=3,
        minimum_validation=1,
        test_definition_digest=definition,
    )
    identity = runtime.begin_run(config(protocol), b'{"synthetic":"trial"}')
    service = ResearchValidationService(runtime.registry, runtime.objects)
    frozen = service.bind(identity, plan(), protocol)
    head = runtime.registry.verify_object(identity)[-1]
    test: JsonRecord = {
        "attempt_number": 1,
        "variant_configuration_digest": head.record["configuration_digest"],
        "test_definition_digest": definition,
        "p_value": ".03",
    }
    result: JsonRecord = {
        "schema_version": "qh-prespecified-trial-tests-v1",
        "experiment_id": identity,
        "frozen_revision_digest": frozen.frozen_revision_digest,
        "tests": [test],
    }
    if attack == "ordinary_result":
        result = {"diagnostic": "No test performed"}
    elif attack == "missing_test":
        result["tests"] = []
    elif attack == "foreign_identity":
        result["frozen_revision_digest"] = "sha256:" + "a" * 64
    elif attack == "malformed_tests":
        result["tests"] = "not an array"
    elif attack == "duplicate_attempt":
        result["tests"] = [test, test]
    elif attack == "foreign_definition":
        test["test_definition_digest"] = "sha256:" + "a" * 64
    else:
        test["attempt_number"] = 2
    runtime.evaluate_run(identity, result)
    family = cast(str, head.record["research_family_id"])
    if attack in {"ordinary_result", "missing_test"}:
        report = service.adjusted_family(family)
        assert cast(dict[str, Any], report["adjustment"])["status"] == "INCONCLUSIVE"
        assert cast(dict[str, Any], report["inventory"])["total_attempts"] == 1
    else:
        with pytest.raises(ResearchValidationError):
            service.adjusted_family(family)
