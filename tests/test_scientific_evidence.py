"""Synthetic hostile tests for Item 9B scientific evidence contracts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import NoReturn, cast

import pytest

from quant_hunter.config import JsonRecord
from quant_hunter.provenance.hashing import DigestMismatchError, sha256_bytes
from quant_hunter.validation import (
    ATTEMPT_ACCOUNTING_AUTHORITY,
    Applicability,
    BaselineDeclaration,
    BaselineRole,
    EvidenceArtifactReference,
    EvidenceObservation,
    EvidenceOutcome,
    ExactNumericEvidence,
    FrozenMultipleTestingBinding,
    GateAssessment,
    GateStatus,
    MetricDeclaration,
    ParameterValueKind,
    PartitionRole,
    ReportingConventions,
    ReportStatus,
    RobustnessDeclaration,
    RobustnessRequirement,
    ScientificEvidenceError,
    ScientificEvidenceIntegrityError,
    ScientificEvidencePlan,
    ScientificEvidenceReport,
    ScientificParameter,
    StandardMetric,
    StatisticalMethod,
    StatisticalMethodDeclaration,
    ValidationGate,
    bind_frozen_multiple_testing,
    build_scientific_evidence_plan,
    build_scientific_evidence_report,
)

EXPERIMENT_ID = "EXP-01990f30-7f5e-7b34-9b21-3d74c513c848"
FAMILY_ID = "FAM-01990f30-7f5e-7b34-9b21-3d74c513d60c"
OTHER_FAMILY_ID = "FAM-01990f30-7f5e-7b34-9b21-3d74c513c844"
OTHER_EXPERIMENT_ID = "EXP-01990f30-7f5e-7b34-9b21-3d74c513c849"
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def frozen_record() -> JsonRecord:
    return {
        "experiment_id": EXPERIMENT_ID,
        "lifecycle_status": "FROZEN",
        "research_family_id": FAMILY_ID,
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


def multiple_testing_binding() -> FrozenMultipleTestingBinding:
    return bind_frozen_multiple_testing(
        frozen_record(),
        DIGEST,
        family_id=FAMILY_ID,
        budget=12,
        correction_plan="Holm correction within the registered family.",
    )


def baseline_declarations() -> tuple[BaselineDeclaration, ...]:
    required = []
    for role in (BaselineRole.NAIVE, BaselineRole.SIMPLE):
        required.append(
            BaselineDeclaration(
                declaration_id=f"baseline-{role.value.lower()}",
                role=role,
                applicability=Applicability.REQUIRED,
                rationale="Required to determine whether complexity earns its place.",
                description=f"Synthetic {role.value.lower()} comparison.",
                comparison_purpose="Compare evidence under the same partitions.",
                assumptions=("Synthetic inputs are aligned.",),
            )
        )
    return (
        *required,
        BaselineDeclaration(
            declaration_id="baseline-established",
            role=BaselineRole.ESTABLISHED_REFERENCE,
            applicability=Applicability.NOT_APPLICABLE,
            rationale="No established reference exists for this synthetic contract.",
        ),
    )


def metric_declarations() -> tuple[MetricDeclaration, ...]:
    return tuple(
        MetricDeclaration(
            declaration_id=f"metric-{metric.value.lower().replace('_', '-')}",
            standard_metric=metric,
            applicability=(
                Applicability.REQUIRED
                if metric is StandardMetric.TOTAL_RETURN
                else Applicability.NOT_APPLICABLE
            ),
            rationale=(
                "Required synthetic reporting evidence."
                if metric is StandardMetric.TOTAL_RETURN
                else "Not meaningful for this synthetic metadata-only study."
            ),
            description=(
                "Exact synthetic total-return evidence."
                if metric is StandardMetric.TOTAL_RETURN
                else None
            ),
            unit_scale=(
                "decimal return" if metric is StandardMetric.TOTAL_RETURN else None
            ),
        )
        for metric in StandardMetric
    )


def method_declarations() -> tuple[StatisticalMethodDeclaration, ...]:
    return tuple(
        StatisticalMethodDeclaration(
            declaration_id=f"method-{method.value.lower().replace('_', '-')}",
            method=method,
            applicability=(
                Applicability.REQUIRED
                if method is StatisticalMethod.CONFIDENCE_INTERVALS
                else Applicability.NOT_APPLICABLE
            ),
            rationale=(
                "Required to represent uncertainty."
                if method is StatisticalMethod.CONFIDENCE_INTERVALS
                else "Not appropriate to this synthetic metadata-only study."
            ),
            assumptions=(
                ("Dependence is handled by the registered method.",)
                if method is StatisticalMethod.CONFIDENCE_INTERVALS
                else ()
            ),
            configuration=(
                (
                    ScientificParameter(
                        "confidence_level",
                        "0.95",
                        ParameterValueKind.NORMALIZED_DECIMAL,
                        "probability",
                    ),
                )
                if method is StatisticalMethod.CONFIDENCE_INTERVALS
                else ()
            ),
            interpretation_purpose=(
                "Bound uncertainty in the future estimate."
                if method is StatisticalMethod.CONFIDENCE_INTERVALS
                else None
            ),
        )
        for method in StatisticalMethod
    )


def robustness_declarations() -> tuple[RobustnessDeclaration, ...]:
    return tuple(
        RobustnessDeclaration(
            declaration_id=f"robustness-{requirement.value.lower().replace('_', '-')}",
            requirement=requirement,
            applicability=(
                Applicability.REQUIRED
                if requirement
                is RobustnessRequirement.MINIMUM_SAMPLE_EVENT_OCCURRENCE_TRADE
                else Applicability.NOT_APPLICABLE
            ),
            rationale=(
                "A minimum synthetic event count is preregistered."
                if requirement
                is RobustnessRequirement.MINIMUM_SAMPLE_EVENT_OCCURRENCE_TRADE
                else "Not appropriate to this synthetic metadata-only study."
            ),
            assumptions=(
                ("Events are defined before evaluation.",)
                if requirement
                is RobustnessRequirement.MINIMUM_SAMPLE_EVENT_OCCURRENCE_TRADE
                else ()
            ),
            configuration=(
                (
                    ScientificParameter(
                        "minimum_event_count",
                        "30",
                        ParameterValueKind.INTEGER,
                        "events",
                    ),
                )
                if requirement
                is RobustnessRequirement.MINIMUM_SAMPLE_EVENT_OCCURRENCE_TRADE
                else ()
            ),
            interpretation_purpose=(
                "Prevent claims from an undersized event set."
                if requirement
                is RobustnessRequirement.MINIMUM_SAMPLE_EVENT_OCCURRENCE_TRADE
                else None
            ),
        )
        for requirement in RobustnessRequirement
    )


def reporting_conventions() -> ReportingConventions:
    return ReportingConventions(
        return_frequency="Per observation; future evaluator must bind frequency.",
        annualization="Study-specific; no universal factor is assumed.",
        risk_free_rate="Explicit zero only for this synthetic fixture.",
        trade_counting="One completed synthetic event is one trade.",
        portfolio_aggregation="No portfolio; report the single synthetic series.",
        missing_data_treatment="Fail when a required synthetic value is absent.",
        confidence_interval_method="Registered method declaration controls.",
    )


def evidence_plan() -> ScientificEvidencePlan:
    return build_scientific_evidence_plan(
        experiment_id=EXPERIMENT_ID,
        temporal_validation_plan_digest=OTHER_DIGEST,
        baselines=baseline_declarations(),
        metrics=metric_declarations(),
        statistical_methods=method_declarations(),
        robustness_requirements=robustness_declarations(),
        reporting_conventions=reporting_conventions(),
        multiple_testing=multiple_testing_binding(),
    )


type _Declaration = (
    BaselineDeclaration
    | MetricDeclaration
    | StatisticalMethodDeclaration
    | RobustnessDeclaration
)


def observations_for_plan(
    plan: ScientificEvidencePlan,
) -> tuple[
    tuple[EvidenceObservation, ...],
    tuple[EvidenceObservation, ...],
    tuple[EvidenceObservation, ...],
    tuple[EvidenceObservation, ...],
]:
    def observations(
        declarations: tuple[_Declaration, ...],
    ) -> tuple[EvidenceObservation, ...]:
        return tuple(
            EvidenceObservation(
                declaration_id=value.declaration_id,
                outcome=EvidenceOutcome.POSITIVE,
                narrative="Synthetic evidence placeholder supplied by a future evaluator.",
                numeric_value=ExactNumericEvidence("0.125", "decimal ratio"),
            )
            for value in declarations
            if value.applicability is Applicability.REQUIRED
        )

    return (
        observations(plan.baselines),
        observations(plan.metrics),
        observations(plan.statistical_methods),
        observations(plan.robustness_requirements),
    )


def passing_gates() -> tuple[GateAssessment, ...]:
    return tuple(
        GateAssessment(
            gate=gate,
            status=GateStatus.PASS,
            supporting_references=(f"evidence://synthetic/{gate.value.lower()}",),
        )
        for gate in ValidationGate
    )


def evidence_report(
    *,
    outcome: EvidenceOutcome = EvidenceOutcome.POSITIVE,
    report_status: ReportStatus = ReportStatus.VALIDATED,
    gates: tuple[GateAssessment, ...] | None = None,
    partition_role: PartitionRole = PartitionRole.VALIDATION,
    release_reference: str | None = None,
) -> ScientificEvidenceReport:
    plan = evidence_plan()
    baseline, metric, methods, robustness = observations_for_plan(plan)
    return build_scientific_evidence_report(
        plan=plan,
        partition_role=partition_role,
        sealed_release_evidence_reference=release_reference,
        report_status=report_status,
        outcome=outcome,
        baseline_evidence=baseline,
        metric_evidence=metric,
        statistical_method_evidence=methods,
        robustness_evidence=robustness,
        gate_assessments=gates or passing_gates(),
        warnings=("Synthetic warning retained.",),
        limitations=("Synthetic limitation retained.",),
        failures=(
            ("Synthetic failure retained.",)
            if outcome is EvidenceOutcome.FAILED
            else ()
        ),
    )


def test_complete_plan_is_canonical_and_reproducible() -> None:
    first = evidence_plan()
    second = evidence_plan()

    first.verify()
    assert first == second
    assert first.canonical_bytes == second.canonical_bytes
    assert first.digest == second.digest
    assert first.document["plan_type"] == "SCIENTIFIC_EVIDENCE_PLAN"


def test_unordered_declaration_permutations_do_not_change_identity() -> None:
    original = evidence_plan()
    permuted = build_scientific_evidence_plan(
        experiment_id=EXPERIMENT_ID,
        temporal_validation_plan_digest=OTHER_DIGEST,
        baselines=tuple(reversed(baseline_declarations())),
        metrics=tuple(reversed(metric_declarations())),
        statistical_methods=tuple(reversed(method_declarations())),
        robustness_requirements=tuple(reversed(robustness_declarations())),
        reporting_conventions=reporting_conventions(),
        multiple_testing=multiple_testing_binding(),
    )

    assert permuted.canonical_bytes == original.canonical_bytes
    assert permuted.digest == original.digest


def test_duplicate_declaration_identity_fails_across_categories() -> None:
    metrics = list(metric_declarations())
    metrics[0] = replace(
        metrics[0],
        declaration_id=baseline_declarations()[0].declaration_id,
    )

    with pytest.raises(ScientificEvidenceError, match="identities must be unique"):
        build_scientific_evidence_plan(
            experiment_id=EXPERIMENT_ID,
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_declarations(),
            metrics=metrics,
            statistical_methods=method_declarations(),
            robustness_requirements=robustness_declarations(),
            reporting_conventions=reporting_conventions(),
            multiple_testing=multiple_testing_binding(),
        )


def test_not_applicable_requires_nonempty_rationale() -> None:
    with pytest.raises(ScientificEvidenceError, match="rationale"):
        BaselineDeclaration(
            "baseline-established",
            BaselineRole.ESTABLISHED_REFERENCE,
            Applicability.NOT_APPLICABLE,
            " ",
        )


def test_missing_applicability_is_not_treated_as_not_applicable() -> None:
    with pytest.raises(ScientificEvidenceError, match="applicability must be explicit"):
        MetricDeclaration(
            "metric-total-return",
            cast(Applicability, None),
            "Required.",
            standard_metric=StandardMetric.TOTAL_RETURN,
            description="Return.",
            unit_scale="decimal",
        )


def test_custom_metric_cannot_replace_a_standard_declaration() -> None:
    metrics = list(metric_declarations())
    metrics.pop()
    metrics.append(
        MetricDeclaration(
            "metric-custom",
            Applicability.REQUIRED,
            "Study-specific diagnostic.",
            custom_metric="CUSTOM_DIAGNOSTIC",
            description="Synthetic diagnostic.",
            unit_scale="count",
        )
    )

    with pytest.raises(ScientificEvidenceError, match="Every standard metric"):
        build_scientific_evidence_plan(
            experiment_id=EXPERIMENT_ID,
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_declarations(),
            metrics=metrics,
            statistical_methods=method_declarations(),
            robustness_requirements=robustness_declarations(),
            reporting_conventions=reporting_conventions(),
            multiple_testing=multiple_testing_binding(),
        )


@pytest.mark.parametrize("missing_field", ["assumptions", "configuration", "purpose"])
def test_applicable_statistical_method_requires_complete_metadata(
    missing_field: str,
) -> None:
    declaration = method_declarations()[0]
    with pytest.raises(ScientificEvidenceError):
        if missing_field == "assumptions":
            replace(declaration, assumptions=())
        elif missing_field == "configuration":
            replace(declaration, configuration=())
        else:
            replace(declaration, interpretation_purpose=None)


@pytest.mark.parametrize(
    "changes",
    [
        {"family_id": OTHER_FAMILY_ID},
        {"budget": 13},
        {"correction_plan": "No correction."},
    ],
)
def test_multiple_testing_binding_rejects_frozen_contradictions(
    changes: dict[str, object],
) -> None:
    arguments: dict[str, object] = {
        "family_id": FAMILY_ID,
        "budget": 12,
        "correction_plan": "Holm correction within the registered family.",
        **changes,
    }
    with pytest.raises(ScientificEvidenceError, match="contradicts frozen"):
        bind_frozen_multiple_testing(
            frozen_record(),
            DIGEST,
            family_id=cast(str, arguments["family_id"]),
            budget=cast(int, arguments["budget"]),
            correction_plan=cast(str, arguments["correction_plan"]),
        )


def test_multiple_testing_has_no_parallel_attempt_counter() -> None:
    document = evidence_plan().document
    multiple_testing = cast(JsonRecord, document["multiple_testing"])
    encoded = str(document)

    assert multiple_testing["attempt_accounting_authority"] == (
        ATTEMPT_ACCOUNTING_AUTHORITY
    )
    assert "variants_attempted" not in encoded
    assert "ai_generated_attempts" not in encoded
    assert "failed_attempts" not in encoded
    assert multiple_testing["accounting_rules"] == {
        "ai_generated_variants_count": True,
        "failed_and_rejected_attempts_count": True,
        "raw_and_adjusted_inference_are_distinct": True,
        "related_variants_are_independent_evidence": False,
        "selection_retries_count": True,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("variants_attempted", 1),
        ("ai_generated_attempts", 1),
        ("failed_attempts", 1),
    ],
)
def test_item_9b_cannot_reset_or_import_runtime_attempt_counts(
    field: str, value: int
) -> None:
    record = frozen_record()
    if field == "variants_attempted":
        record[field] = value
    else:
        accounting = cast(JsonRecord, record["variant_accounting"])
        accounting[field] = value

    with pytest.raises(ScientificEvidenceError, match="accounting"):
        bind_frozen_multiple_testing(
            record,
            DIGEST,
            family_id=FAMILY_ID,
            budget=12,
            correction_plan="Holm correction within the registered family.",
        )


@pytest.mark.parametrize(
    "outcome",
    [
        EvidenceOutcome.NEGATIVE,
        EvidenceOutcome.NULL,
        EvidenceOutcome.FAILED,
        EvidenceOutcome.INCONCLUSIVE,
    ],
)
def test_unfavorable_evidence_outcomes_are_retained(outcome: EvidenceOutcome) -> None:
    report = evidence_report(
        outcome=outcome,
        report_status=ReportStatus.NOT_VALIDATED,
    )

    assert report.document["outcome"] == outcome.value
    if outcome is EvidenceOutcome.FAILED:
        assert report.document["failures"] == ["Synthetic failure retained."]


@pytest.mark.parametrize("gate_status", [GateStatus.FAIL, GateStatus.PENDING])
def test_validated_report_rejects_failed_or_pending_gate(
    gate_status: GateStatus,
) -> None:
    gates = list(passing_gates())
    gates[2] = GateAssessment(
        gates[2].gate,
        gate_status,
        rationale="Synthetic gate has not passed.",
    )

    with pytest.raises(ScientificEvidenceError, match="Validated status"):
        evidence_report(gates=tuple(gates))


def test_pending_report_evidence_is_distinct_from_not_applicable() -> None:
    gates = list(passing_gates())
    gates[2] = GateAssessment(
        gates[2].gate,
        GateStatus.PENDING,
        rationale="Temporal evidence has not yet been evaluated.",
    )

    report = evidence_report(
        outcome=EvidenceOutcome.PENDING,
        report_status=ReportStatus.NOT_YET_EVALUATED,
        gates=tuple(gates),
    )

    assert report.document["outcome"] == "PENDING"
    assert report.document["status"] == "NOT_YET_EVALUATED"


def test_pass_gate_cannot_be_evidence_free() -> None:
    with pytest.raises(ScientificEvidenceError, match="must not be empty"):
        GateAssessment(ValidationGate.V0_REGISTRATION, GateStatus.PASS)


def test_exact_numeric_evidence_rejects_binary_float_and_non_normalized_text() -> None:
    with pytest.raises(ScientificEvidenceError, match="normalized exact decimal"):
        ExactNumericEvidence(cast(str, 0.125), "ratio")
    with pytest.raises(ScientificEvidenceError, match="normalized exact decimal"):
        ExactNumericEvidence("01.25", "ratio")


def test_sealed_report_metadata_never_accesses_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = (tmp_path / "sealed" / "holdout.bin").resolve()

    def reject_filesystem_access(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("scientific evidence contract accessed sealed contents")

    monkeypatch.setattr(Path, "open", reject_filesystem_access)
    monkeypatch.setattr(Path, "read_bytes", reject_filesystem_access)
    monkeypatch.setattr(Path, "stat", reject_filesystem_access)
    monkeypatch.setattr(Path, "iterdir", reject_filesystem_access)

    report = evidence_report(
        partition_role=PartitionRole.SEALED_OUT_OF_SAMPLE,
        release_reference=str(sealed),
    )

    assert report.document["sealed_release_evidence_reference"] == str(sealed)
    assert report.document["sealed_release_authorization_verified"] is False


def test_sealed_report_requires_release_evidence_reference() -> None:
    with pytest.raises(ScientificEvidenceError, match="release evidence reference"):
        evidence_report(partition_role=PartitionRole.SEALED_OUT_OF_SAMPLE)


def test_artifact_reference_is_recorded_without_verification_claim() -> None:
    reference = EvidenceArtifactReference("artifact://synthetic/evidence", DIGEST)
    observation = EvidenceObservation(
        "metric-total-return",
        EvidenceOutcome.POSITIVE,
        "Synthetic exact evidence.",
        ExactNumericEvidence("0.125", "decimal return"),
        (reference,),
    )

    assert observation.document()["artifact_references"] == [
        {"digest": DIGEST, "reference": "artifact://synthetic/evidence"}
    ]


def test_plan_integrity_rejects_digest_bytes_and_typed_tampering() -> None:
    plan = evidence_plan()
    with pytest.raises(DigestMismatchError):
        replace(plan, digest="sha256:" + "f" * 64).verify()
    with pytest.raises(DigestMismatchError):
        replace(plan, canonical_bytes=plan.canonical_bytes + b" ").verify()
    with pytest.raises(ScientificEvidenceIntegrityError, match="typed fields"):
        replace(plan, temporal_validation_plan_digest=DIGEST).verify()


def test_report_integrity_rejects_digest_and_typed_tampering() -> None:
    report = evidence_report()
    with pytest.raises(DigestMismatchError):
        replace(report, digest="sha256:" + "f" * 64).verify()
    with pytest.raises(ScientificEvidenceIntegrityError, match="typed fields"):
        changed = replace(report, outcome=EvidenceOutcome.NULL)
        changed.verify()


def test_non_object_plan_and_report_canonical_documents_fail() -> None:
    plan = evidence_plan()
    malformed_plan = replace(plan, canonical_bytes=b"[]", digest=sha256_bytes(b"[]"))
    with pytest.raises(ScientificEvidenceIntegrityError, match="not a JSON object"):
        _ = malformed_plan.document

    report = evidence_report()
    malformed_report = replace(
        report,
        canonical_bytes=b"[]",
        digest=sha256_bytes(b"[]"),
    )
    with pytest.raises(ScientificEvidenceIntegrityError, match="not a JSON object"):
        _ = malformed_report.document


def test_scientific_parameter_exact_value_kinds_and_rejections() -> None:
    assert (
        ScientificParameter("label", "synthetic", ParameterValueKind.TEXT).document()[
            "value"
        ]
        == "synthetic"
    )
    assert (
        ScientificParameter("enabled", "true", ParameterValueKind.BOOLEAN).document()[
            "value"
        ]
        == "true"
    )
    assert (
        ScientificParameter("count", "-2", ParameterValueKind.INTEGER).document()[
            "value"
        ]
        == "-2"
    )

    with pytest.raises(ScientificEvidenceError, match="kind must be explicit"):
        ScientificParameter("bad", "value", cast(ParameterValueKind, "TEXT"))
    with pytest.raises(ScientificEvidenceError, match="normalized exact decimal"):
        ScientificParameter(
            "bad", "01.0", ParameterValueKind.NORMALIZED_DECIMAL, "ratio"
        )
    with pytest.raises(ScientificEvidenceError, match="normalized integer"):
        ScientificParameter("bad", "1.0", ParameterValueKind.INTEGER)
    with pytest.raises(ScientificEvidenceError, match="lowercase true or false"):
        ScientificParameter("bad", "True", ParameterValueKind.BOOLEAN)
    with pytest.raises(ScientificEvidenceError, match="unit/scale"):
        ScientificParameter("bad", "1.0", ParameterValueKind.NORMALIZED_DECIMAL, " ")


def test_declaration_text_and_parameter_collections_fail_closed() -> None:
    with pytest.raises(ScientificEvidenceError, match="unsupported characters"):
        replace(baseline_declarations()[0], declaration_id="contains spaces")
    with pytest.raises(ScientificEvidenceError, match="nonempty strings"):
        replace(
            baseline_declarations()[0],
            assumptions=(cast(str, None),),
        )
    with pytest.raises(ScientificEvidenceError, match="duplicates"):
        replace(
            baseline_declarations()[0],
            assumptions=("same", "same"),
        )

    method = method_declarations()[0]
    with pytest.raises(ScientificEvidenceError, match="typed parameters"):
        replace(
            method,
            configuration=(cast(ScientificParameter, object()),),
        )
    setting = ScientificParameter("same", "one", ParameterValueKind.TEXT)
    with pytest.raises(ScientificEvidenceError, match="names must be unique"):
        replace(method, configuration=(setting, setting))


def test_baseline_role_and_custom_role_contracts() -> None:
    with pytest.raises(ScientificEvidenceError, match="role must be explicit"):
        replace(
            baseline_declarations()[0],
            role=cast(BaselineRole, "NAIVE"),
        )
    custom = BaselineDeclaration(
        "baseline-custom",
        BaselineRole.CUSTOM,
        Applicability.REQUIRED,
        "Study-specific comparator is justified.",
        "Synthetic custom comparator.",
        "Test a distinct study-specific claim.",
        ("Synthetic assumption.",),
        "DOMAIN_SPECIFIC",
    )
    assert custom.document()["custom_role"] == "DOMAIN_SPECIFIC"
    with pytest.raises(ScientificEvidenceError, match="custom baseline role"):
        replace(custom, custom_role=" ")
    with pytest.raises(ScientificEvidenceError, match="Only a custom baseline"):
        replace(baseline_declarations()[0], custom_role="NOT_ALLOWED")


def test_metric_identity_and_enum_contracts() -> None:
    metric = metric_declarations()[0]
    with pytest.raises(ScientificEvidenceError, match="exactly one"):
        replace(metric, standard_metric=None)
    with pytest.raises(ScientificEvidenceError, match="exactly one"):
        replace(metric, custom_metric="ALSO_CUSTOM")
    with pytest.raises(ScientificEvidenceError, match="malformed"):
        replace(metric, standard_metric=cast(StandardMetric, "TOTAL_RETURN"))


def test_method_and_robustness_enums_fail_closed() -> None:
    with pytest.raises(ScientificEvidenceError, match="method is malformed"):
        replace(
            method_declarations()[0],
            method=cast(StatisticalMethod, "CONFIDENCE_INTERVALS"),
        )
    with pytest.raises(ScientificEvidenceError, match="requirement is malformed"):
        replace(
            robustness_declarations()[0],
            requirement=cast(
                RobustnessRequirement,
                "MINIMUM_SAMPLE_EVENT_OCCURRENCE_TRADE",
            ),
        )


def test_multiple_testing_binding_rejects_nonfrozen_and_malformed_evidence() -> None:
    record = frozen_record()
    record["lifecycle_status"] = "RUNNING"
    with pytest.raises(ScientificEvidenceError, match="requires FROZEN"):
        bind_frozen_multiple_testing(
            record,
            DIGEST,
            family_id=FAMILY_ID,
            budget=12,
            correction_plan="Holm correction within the registered family.",
        )

    record = frozen_record()
    record["multiple_testing"] = "malformed"
    with pytest.raises(ScientificEvidenceError, match="evidence is malformed"):
        bind_frozen_multiple_testing(
            record,
            DIGEST,
            family_id=FAMILY_ID,
            budget=12,
            correction_plan="Holm correction within the registered family.",
        )

    with pytest.raises(ScientificEvidenceError, match="positive integer"):
        replace(multiple_testing_binding(), budget=cast(int, True))

    record = frozen_record()
    cast(JsonRecord, record["multiple_testing"])["budget"] = True
    with pytest.raises(ScientificEvidenceError, match="evidence is malformed"):
        bind_frozen_multiple_testing(
            record,
            DIGEST,
            family_id=FAMILY_ID,
            budget=12,
            correction_plan="Holm correction within the registered family.",
        )


def test_plan_requires_authoritative_typed_inputs_and_matching_experiment() -> None:
    baseline_values = baseline_declarations()
    metric_values = metric_declarations()
    method_values = method_declarations()
    robustness_values = robustness_declarations()

    with pytest.raises(ScientificEvidenceError, match="identity must be explicit"):
        build_scientific_evidence_plan(
            experiment_id=cast(str, None),
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_values,
            metrics=metric_values,
            statistical_methods=method_values,
            robustness_requirements=robustness_values,
            reporting_conventions=reporting_conventions(),
            multiple_testing=multiple_testing_binding(),
        )
    with pytest.raises(ScientificEvidenceError, match="digest is malformed"):
        build_scientific_evidence_plan(
            experiment_id=EXPERIMENT_ID,
            temporal_validation_plan_digest=cast(str, None),
            baselines=baseline_values,
            metrics=metric_values,
            statistical_methods=method_values,
            robustness_requirements=robustness_values,
            reporting_conventions=reporting_conventions(),
            multiple_testing=multiple_testing_binding(),
        )
    with pytest.raises(ScientificEvidenceError, match="conventions must be explicit"):
        build_scientific_evidence_plan(
            experiment_id=EXPERIMENT_ID,
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_values,
            metrics=metric_values,
            statistical_methods=method_values,
            robustness_requirements=robustness_values,
            reporting_conventions=cast(ReportingConventions, None),
            multiple_testing=multiple_testing_binding(),
        )
    with pytest.raises(ScientificEvidenceError, match="binding is required"):
        build_scientific_evidence_plan(
            experiment_id=EXPERIMENT_ID,
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_values,
            metrics=metric_values,
            statistical_methods=method_values,
            robustness_requirements=robustness_values,
            reporting_conventions=reporting_conventions(),
            multiple_testing=cast(FrozenMultipleTestingBinding, None),
        )
    with pytest.raises(ScientificEvidenceError, match="contradicts its binding"):
        build_scientific_evidence_plan(
            experiment_id=OTHER_EXPERIMENT_ID,
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_values,
            metrics=metric_values,
            statistical_methods=method_values,
            robustness_requirements=robustness_values,
            reporting_conventions=reporting_conventions(),
            multiple_testing=multiple_testing_binding(),
        )


def test_plan_requires_complete_typed_declaration_inventories() -> None:
    with pytest.raises(ScientificEvidenceError, match="typed metric"):
        build_scientific_evidence_plan(
            experiment_id=EXPERIMENT_ID,
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_declarations(),
            metrics=(cast(MetricDeclaration, object()),),
            statistical_methods=method_declarations(),
            robustness_requirements=robustness_declarations(),
            reporting_conventions=reporting_conventions(),
            multiple_testing=multiple_testing_binding(),
        )
    with pytest.raises(ScientificEvidenceError, match="Naive, simple"):
        build_scientific_evidence_plan(
            experiment_id=EXPERIMENT_ID,
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_declarations()[:-1],
            metrics=metric_declarations(),
            statistical_methods=method_declarations(),
            robustness_requirements=robustness_declarations(),
            reporting_conventions=reporting_conventions(),
            multiple_testing=multiple_testing_binding(),
        )
    with pytest.raises(ScientificEvidenceError, match="Every statistical method"):
        build_scientific_evidence_plan(
            experiment_id=EXPERIMENT_ID,
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_declarations(),
            metrics=metric_declarations(),
            statistical_methods=method_declarations()[:-1],
            robustness_requirements=robustness_declarations(),
            reporting_conventions=reporting_conventions(),
            multiple_testing=multiple_testing_binding(),
        )
    with pytest.raises(ScientificEvidenceError, match="Every robustness"):
        build_scientific_evidence_plan(
            experiment_id=EXPERIMENT_ID,
            temporal_validation_plan_digest=OTHER_DIGEST,
            baselines=baseline_declarations(),
            metrics=metric_declarations(),
            statistical_methods=method_declarations(),
            robustness_requirements=robustness_declarations()[:-1],
            reporting_conventions=reporting_conventions(),
            multiple_testing=multiple_testing_binding(),
        )


def test_evidence_observation_and_artifact_reference_fail_closed() -> None:
    observation = EvidenceObservation(
        "metric-total-return",
        EvidenceOutcome.POSITIVE,
        "Synthetic evidence.",
    )
    with pytest.raises(ScientificEvidenceError, match="outcome is malformed"):
        replace(observation, outcome=cast(EvidenceOutcome, "POSITIVE"))
    with pytest.raises(ScientificEvidenceError, match="exact and typed"):
        replace(observation, numeric_value=cast(ExactNumericEvidence, "0.1"))
    with pytest.raises(ScientificEvidenceError, match="references are malformed"):
        replace(
            observation,
            artifact_references=(cast(EvidenceArtifactReference, object()),),
        )
    reference = EvidenceArtifactReference("artifact://synthetic/evidence", DIGEST)
    with pytest.raises(ScientificEvidenceError, match="must be unique"):
        replace(observation, artifact_references=(reference, reference))


def test_gate_assessment_requires_typed_status_and_rationales() -> None:
    passed = passing_gates()[0]
    with pytest.raises(ScientificEvidenceError, match="gate is malformed"):
        replace(passed, gate=cast(ValidationGate, "V0_REGISTRATION"))
    with pytest.raises(ScientificEvidenceError, match="status is malformed"):
        replace(passed, status=cast(GateStatus, "PASS"))
    with pytest.raises(ScientificEvidenceError, match="PASS gate rationale"):
        replace(passed, rationale=" ")
    with pytest.raises(ScientificEvidenceError, match="non-PASS gate rationale"):
        GateAssessment(ValidationGate.V0_REGISTRATION, GateStatus.FAIL)


def test_report_requires_typed_roles_status_outcome_and_release_scope() -> None:
    report = evidence_report()
    with pytest.raises(ScientificEvidenceError, match="plan is required"):
        replace(report, plan=cast(ScientificEvidencePlan, None)).verify()
    with pytest.raises(ScientificEvidenceError, match="partition role"):
        replace(report, partition_role=cast(PartitionRole, "VALIDATION")).verify()
    with pytest.raises(ScientificEvidenceError, match="Only sealed-OOS"):
        replace(
            report, sealed_release_evidence_reference="release://unexpected"
        ).verify()
    with pytest.raises(ScientificEvidenceError, match="Report status"):
        replace(report, report_status=cast(ReportStatus, "VALIDATED")).verify()
    with pytest.raises(ScientificEvidenceError, match="Report outcome"):
        replace(report, outcome=cast(EvidenceOutcome, "POSITIVE")).verify()


def test_report_rejects_missing_duplicate_or_malformed_evidence() -> None:
    report = evidence_report()
    with pytest.raises(ScientificEvidenceError, match="account for every applicable"):
        replace(report, baseline_evidence=()).verify()
    duplicated = (report.baseline_evidence[0], report.baseline_evidence[0])
    with pytest.raises(ScientificEvidenceError, match="identities must be unique"):
        replace(report, baseline_evidence=duplicated).verify()
    with pytest.raises(ScientificEvidenceError, match="typed evidence"):
        replace(
            report,
            metric_evidence=(cast(EvidenceObservation, object()),),
        ).verify()


def test_report_rejects_malformed_or_incomplete_gate_inventory() -> None:
    report = evidence_report()
    with pytest.raises(ScientificEvidenceError, match="must be typed"):
        replace(
            report,
            gate_assessments=(cast(GateAssessment, object()),),
        ).verify()
    with pytest.raises(ScientificEvidenceError, match="Every V0-V9 gate"):
        replace(report, gate_assessments=report.gate_assessments[:-1]).verify()
