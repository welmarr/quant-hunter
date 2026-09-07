"""Shared synthetic Item 9 objects for cross-binding tests."""

from __future__ import annotations

from quant_hunter.config import JsonRecord
from quant_hunter.validation import (
    Applicability,
    BaselineDeclaration,
    BaselineRole,
    ChronologicalPartitions,
    FrozenMultipleTestingBinding,
    FrozenTemporalValidationBinding,
    GapEvidence,
    MetricDeclaration,
    ReportingConventions,
    RobustnessDeclaration,
    RobustnessRequirement,
    ScientificEvidencePlan,
    StandardMetric,
    StatisticalMethod,
    StatisticalMethodDeclaration,
    TemporalInterval,
    ValidationFold,
    ValidationPlan,
    ValidationScheme,
    bind_frozen_multiple_testing,
    bind_frozen_temporal_validation,
    build_scientific_evidence_plan,
    build_validation_plan,
)

EXPERIMENT_ID = "EXP-01990f30-7f5e-7b34-9b21-3d74c513c848"
OTHER_EXPERIMENT_ID = "EXP-01990f30-7f5e-7b34-9b21-3d74c513c849"
FAMILY_ID = "FAM-01990f30-7f5e-7b34-9b21-3d74c513d60c"
FROZEN_DIGEST = "sha256:" + "a" * 64
OTHER_FROZEN_DIGEST = "sha256:" + "b" * 64


def interval(start: str, end: str) -> TemporalInterval:
    return TemporalInterval(f"2020-01-{start}T00:00:00Z", f"2020-01-{end}T00:00:00Z")


def chronological_partitions(
    *, sealed_reference: str = "sealed://synthetic/holdout"
) -> ChronologicalPartitions:
    return ChronologicalPartitions(
        training_development=interval("01", "10"),
        validation=interval("10", "20"),
        sealed_out_of_sample=interval("20", "30"),
        sealed_reference=sealed_reference,
    )


def validation_plan(
    *, sealed_reference: str = "sealed://synthetic/holdout"
) -> ValidationPlan:
    partitions = chronological_partitions(sealed_reference=sealed_reference)
    gap = GapEvidence.not_applicable(
        "Synthetic labels have no horizon; applicability remains explicit."
    )
    fold = ValidationFold(
        fold_id="holdout-1",
        sequence=1,
        scheme=ValidationScheme.CHRONOLOGICAL_HOLDOUT,
        training=interval("01", "10"),
        validation=interval("10", "20"),
        purge=gap,
        embargo=gap,
    )
    return build_validation_plan(
        partitions,
        ValidationScheme.CHRONOLOGICAL_HOLDOUT,
        (fold,),
    )


def frozen_record(
    *,
    experiment_id: str = EXPERIMENT_ID,
    partitions: JsonRecord | None = None,
) -> JsonRecord:
    return {
        "experiment_id": experiment_id,
        "lifecycle_status": "FROZEN",
        "research_family_id": FAMILY_ID,
        "partitions": (
            partitions
            if partitions is not None
            else {
                "training": interval("01", "10").document(),
                "validation": interval("10", "20").document(),
                "sealed_out_of_sample": interval("20", "30").document(),
            }
        ),
        "multiple_testing": {
            "family_id": FAMILY_ID,
            "budget": 12,
            "correction_plan": "Holm correction within the registered family.",
        },
        "variants_attempted": 0,
        "variant_accounting": {
            "ai_generated_attempts": 0,
            "failed_attempts": 0,
            "accounting_basis": "Item 8 append-only attempt evidence.",
        },
    }


def temporal_binding(
    *,
    record: JsonRecord | None = None,
    frozen_revision_digest: str = FROZEN_DIGEST,
    plan: ValidationPlan | None = None,
) -> FrozenTemporalValidationBinding:
    return bind_frozen_temporal_validation(
        record if record is not None else frozen_record(),
        frozen_revision_digest,
        plan if plan is not None else validation_plan(),
    )


def multiple_testing_binding(
    *,
    record: JsonRecord | None = None,
    frozen_revision_digest: str = FROZEN_DIGEST,
) -> FrozenMultipleTestingBinding:
    return bind_frozen_multiple_testing(
        record if record is not None else frozen_record(),
        frozen_revision_digest,
        family_id=FAMILY_ID,
        budget=12,
        correction_plan="Holm correction within the registered family.",
    )


def baseline_declarations() -> tuple[BaselineDeclaration, ...]:
    return tuple(
        BaselineDeclaration(
            declaration_id=f"baseline-{role.value.lower()}",
            role=role,
            applicability=Applicability.NOT_APPLICABLE,
            rationale="This synthetic binding test performs no comparison.",
        )
        for role in (
            BaselineRole.NAIVE,
            BaselineRole.SIMPLE,
            BaselineRole.ESTABLISHED_REFERENCE,
        )
    )


def metric_declarations() -> tuple[MetricDeclaration, ...]:
    return tuple(
        MetricDeclaration(
            declaration_id=f"metric-{metric.value.lower().replace('_', '-')}",
            standard_metric=metric,
            applicability=Applicability.NOT_APPLICABLE,
            rationale="This synthetic binding test calculates no metric.",
        )
        for metric in StandardMetric
    )


def method_declarations() -> tuple[StatisticalMethodDeclaration, ...]:
    return tuple(
        StatisticalMethodDeclaration(
            declaration_id=f"method-{method.value.lower().replace('_', '-')}",
            method=method,
            applicability=Applicability.NOT_APPLICABLE,
            rationale="This synthetic binding test runs no statistical method.",
        )
        for method in StatisticalMethod
    )


def robustness_declarations() -> tuple[RobustnessDeclaration, ...]:
    return tuple(
        RobustnessDeclaration(
            declaration_id=f"robustness-{requirement.value.lower().replace('_', '-')}",
            requirement=requirement,
            applicability=Applicability.NOT_APPLICABLE,
            rationale="This synthetic binding test performs no robustness analysis.",
        )
        for requirement in RobustnessRequirement
    )


def reporting_conventions() -> ReportingConventions:
    return ReportingConventions(
        return_frequency="No return is calculated.",
        annualization="No annualization is calculated.",
        risk_free_rate="No risk-free rate is applied.",
        trade_counting="No trades are counted.",
        portfolio_aggregation="No portfolio is aggregated.",
        missing_data_treatment="Required metadata fails closed when missing.",
        confidence_interval_method="No confidence interval is calculated.",
    )


def scientific_evidence_plan(
    *,
    experiment_id: str = EXPERIMENT_ID,
    temporal: FrozenTemporalValidationBinding | None = None,
    multiple_testing: FrozenMultipleTestingBinding | None = None,
    reverse_unordered_inputs: bool = False,
) -> ScientificEvidencePlan:
    baselines = baseline_declarations()
    metrics = metric_declarations()
    methods = method_declarations()
    robustness = robustness_declarations()
    if reverse_unordered_inputs:
        baselines = tuple(reversed(baselines))
        metrics = tuple(reversed(metrics))
        methods = tuple(reversed(methods))
        robustness = tuple(reversed(robustness))
    return build_scientific_evidence_plan(
        experiment_id=experiment_id,
        temporal_validation=temporal if temporal is not None else temporal_binding(),
        baselines=baselines,
        metrics=metrics,
        statistical_methods=methods,
        robustness_requirements=robustness,
        reporting_conventions=reporting_conventions(),
        multiple_testing=(
            multiple_testing
            if multiple_testing is not None
            else multiple_testing_binding()
        ),
    )
