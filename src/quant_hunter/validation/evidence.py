"""Immutable scientific-evidence declarations and report envelopes."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.identity import RegistryKind, validate_typed_id
from quant_hunter.provenance.hashing import (
    require_sha256_digest,
    sha256_bytes,
    verify_sha256_bytes,
)
from quant_hunter.validation.temporal import FrozenTemporalValidationBinding

_DECLARATION_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_NORMALIZED_DECIMAL: Final = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:[.][0-9]+)?$")
_INTEGER: Final = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
ATTEMPT_ACCOUNTING_AUTHORITY: Final = "ITEM_8_APPEND_ONLY_EXPERIMENT_REGISTRY"


class ScientificEvidenceError(ValueError):
    """A scientific evidence declaration violates a governed invariant."""


class ScientificEvidenceIntegrityError(RuntimeError):
    """Canonical evidence differs from its typed scientific contract."""


class Applicability(StrEnum):
    """Whether a preregistered scientific requirement must be evaluated."""

    REQUIRED = "REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class BaselineRole(StrEnum):
    """Governed baseline roles, including explicit study-specific additions."""

    NAIVE = "NAIVE"
    SIMPLE = "SIMPLE"
    ESTABLISHED_REFERENCE = "ESTABLISHED_REFERENCE"
    CUSTOM = "CUSTOM"


class StandardMetric(StrEnum):
    """The complete standard reporting inventory from VALIDATION_STANDARD.md."""

    TOTAL_RETURN = "TOTAL_RETURN"
    CAGR = "CAGR"
    ANNUALIZED_VOLATILITY = "ANNUALIZED_VOLATILITY"
    SHARPE = "SHARPE"
    SORTINO = "SORTINO"
    CALMAR = "CALMAR"
    MAXIMUM_DRAWDOWN = "MAXIMUM_DRAWDOWN"
    DRAWDOWN_DURATION = "DRAWDOWN_DURATION"
    TAIL_LOSS = "TAIL_LOSS"
    VAR = "VAR"
    CVAR = "CVAR"
    PROFIT_FACTOR = "PROFIT_FACTOR"
    EXPECTANCY = "EXPECTANCY"
    WIN_RATE = "WIN_RATE"
    LOSS_RATE = "LOSS_RATE"
    AVERAGE_WINNER = "AVERAGE_WINNER"
    AVERAGE_LOSER = "AVERAGE_LOSER"
    PAYOFF_RATIO = "PAYOFF_RATIO"
    TRADES_PER_YEAR = "TRADES_PER_YEAR"
    TURNOVER = "TURNOVER"
    EXPOSURE = "EXPOSURE"
    TRANSACTION_COSTS = "TRANSACTION_COSTS"
    PERFORMANCE_BY_YEAR = "PERFORMANCE_BY_YEAR"
    PERFORMANCE_BY_ASSET = "PERFORMANCE_BY_ASSET"
    PERFORMANCE_BY_SESSION = "PERFORMANCE_BY_SESSION"
    PERFORMANCE_BY_VOLATILITY_REGIME = "PERFORMANCE_BY_VOLATILITY_REGIME"
    PERFORMANCE_BY_MARKET_REGIME = "PERFORMANCE_BY_MARKET_REGIME"
    PROBABILITY_CALIBRATION = "PROBABILITY_CALIBRATION"
    CONFIDENCE_INTERVALS = "CONFIDENCE_INTERVALS"
    PARAMETER_SENSITIVITY = "PARAMETER_SENSITIVITY"
    EXECUTION_COST_SENSITIVITY = "EXECUTION_COST_SENSITIVITY"


class StatisticalMethod(StrEnum):
    """Preregistered statistical and anti-overfitting method vocabulary."""

    CONFIDENCE_INTERVALS = "CONFIDENCE_INTERVALS"
    BOOTSTRAP = "BOOTSTRAP"
    BLOCK_BOOTSTRAP = "BLOCK_BOOTSTRAP"
    MONTE_CARLO = "MONTE_CARLO"
    WHITE_REALITY_CHECK = "WHITE_REALITY_CHECK"
    HANSEN_SPA = "HANSEN_SPA"
    DEFLATED_SHARPE_RATIO = "DEFLATED_SHARPE_RATIO"
    PROBABILITY_OF_BACKTEST_OVERFITTING = "PROBABILITY_OF_BACKTEST_OVERFITTING"
    COMBINATORIALLY_SYMMETRIC_CROSS_VALIDATION = (
        "COMBINATORIALLY_SYMMETRIC_CROSS_VALIDATION"
    )
    MULTIPLE_HYPOTHESIS_CORRECTION = "MULTIPLE_HYPOTHESIS_CORRECTION"
    PARAMETER_STABILITY = "PARAMETER_STABILITY"
    PERFORMANCE_DEGRADATION = "PERFORMANCE_DEGRADATION"
    REGIME_BY_REGIME = "REGIME_BY_REGIME"
    PROBABILITY_CALIBRATION = "PROBABILITY_CALIBRATION"


class RobustnessRequirement(StrEnum):
    """Sample-adequacy and robustness evidence that can be preregistered."""

    MINIMUM_SAMPLE_EVENT_OCCURRENCE_TRADE = "MINIMUM_SAMPLE_EVENT_OCCURRENCE_TRADE"
    EFFECTIVE_SAMPLE_SIZE = "EFFECTIVE_SAMPLE_SIZE"
    START_END_DATE_SENSITIVITY = "START_END_DATE_SENSITIVITY"
    ROLLING_EXPANDING_STABILITY = "ROLLING_EXPANDING_STABILITY"
    PARTITION_DEGRADATION = "PARTITION_DEGRADATION"
    CONCENTRATION_RISK = "CONCENTRATION_RISK"
    PERIOD_STABILITY = "PERIOD_STABILITY"
    INSTRUMENT_STABILITY = "INSTRUMENT_STABILITY"
    SESSION_STABILITY = "SESSION_STABILITY"
    VOLATILITY_REGIME_STABILITY = "VOLATILITY_REGIME_STABILITY"
    MARKET_REGIME_STABILITY = "MARKET_REGIME_STABILITY"
    PARAMETER_NEIGHBORHOOD_SENSITIVITY = "PARAMETER_NEIGHBORHOOD_SENSITIVITY"
    COST_LATENCY_SENSITIVITY = "COST_LATENCY_SENSITIVITY"
    TAIL_BEHAVIOR = "TAIL_BEHAVIOR"
    DRAWDOWN_DURATION = "DRAWDOWN_DURATION"


class ParameterValueKind(StrEnum):
    """Exact configuration value representations; binary floats are absent."""

    TEXT = "TEXT"
    NORMALIZED_DECIMAL = "NORMALIZED_DECIMAL"
    INTEGER = "INTEGER"
    BOOLEAN = "BOOLEAN"


class PartitionRole(StrEnum):
    """Scientific report partition roles."""

    TRAINING_DEVELOPMENT = "TRAINING_DEVELOPMENT"
    VALIDATION = "VALIDATION"
    SEALED_OUT_OF_SAMPLE = "SEALED_OUT_OF_SAMPLE"


class EvidenceOutcome(StrEnum):
    """Outcome vocabulary that retains unfavorable and unfinished evidence."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NULL = "NULL"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    PENDING = "PENDING"


class ValidationGate(StrEnum):
    """The V0-V9 evidence gates governed by VALIDATION_STANDARD.md."""

    V0_REGISTRATION = "V0_REGISTRATION"
    V1_DATA_PROVENANCE = "V1_DATA_PROVENANCE"
    V2_TEMPORAL_INTEGRITY = "V2_TEMPORAL_INTEGRITY"
    V3_BASELINE = "V3_BASELINE"
    V4_CHRONOLOGICAL_EVIDENCE = "V4_CHRONOLOGICAL_EVIDENCE"
    V5_SEARCH_ADJUSTMENT = "V5_SEARCH_ADJUSTMENT"
    V6_EXECUTION_REALISM = "V6_EXECUTION_REALISM"
    V7_ROBUSTNESS = "V7_ROBUSTNESS"
    V8_REPRODUCIBILITY = "V8_REPRODUCIBILITY"
    V9_REPORTING_AND_DECISION = "V9_REPORTING_AND_DECISION"


class GateStatus(StrEnum):
    """Assessment states for a validation gate."""

    PASS = "PASS"  # noqa: S105 - governed scientific assessment vocabulary
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"


class ReportStatus(StrEnum):
    """Scientific support status without changing experiment lifecycle state."""

    VALIDATED = "VALIDATED"
    NOT_VALIDATED = "NOT_VALIDATED"
    NOT_YET_EVALUATED = "NOT_YET_EVALUATED"


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScientificEvidenceError(f"{field} must be a nonempty string")
    return value


def _declaration_id(value: object) -> str:
    text = _nonempty(value, "declaration identity")
    if _DECLARATION_ID.fullmatch(text) is None:
        raise ScientificEvidenceError(
            "Declaration identity contains unsupported characters"
        )
    return text


def _strings(values: object, field: str, *, required: bool) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ScientificEvidenceError(f"{field} must contain nonempty strings")
    if required and not values:
        raise ScientificEvidenceError(f"{field} must not be empty")
    if len(set(values)) != len(values):
        raise ScientificEvidenceError(f"{field} must not contain duplicates")
    return values


def _applicability(
    value: object,
    rationale: object,
    *,
    required_values: tuple[object, ...],
    field: str,
) -> Applicability:
    if not isinstance(value, Applicability):
        raise ScientificEvidenceError(f"{field} applicability must be explicit")
    _nonempty(rationale, f"{field} rationale")
    if value is Applicability.REQUIRED and any(
        item is None for item in required_values
    ):
        raise ScientificEvidenceError(
            f"Applicable {field} requires complete preregistered metadata"
        )
    return value


@dataclass(frozen=True, slots=True)
class ScientificParameter:
    """One immutable, exact preregistered method or robustness setting."""

    name: str
    value: str
    value_kind: ParameterValueKind
    unit_scale: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.name, "parameter name")
        _nonempty(self.value, "parameter value")
        if not isinstance(self.value_kind, ParameterValueKind):
            raise ScientificEvidenceError("Parameter value kind must be explicit")
        if self.value_kind is ParameterValueKind.NORMALIZED_DECIMAL:
            if _NORMALIZED_DECIMAL.fullmatch(self.value) is None:
                raise ScientificEvidenceError(
                    "Decimal parameter must use normalized exact decimal text"
                )
            _nonempty(self.unit_scale, "decimal parameter unit/scale")
        elif self.value_kind is ParameterValueKind.INTEGER:
            if _INTEGER.fullmatch(self.value) is None:
                raise ScientificEvidenceError(
                    "Integer parameter must use normalized integer text"
                )
        elif self.value_kind is ParameterValueKind.BOOLEAN and self.value not in {
            "true",
            "false",
        }:
            raise ScientificEvidenceError(
                "Boolean parameter must be exact lowercase true or false"
            )
        if self.unit_scale is not None:
            _nonempty(self.unit_scale, "parameter unit/scale")

    def document(self) -> JsonRecord:
        return {
            "name": self.name,
            "value": self.value,
            "value_kind": self.value_kind.value,
            "unit_scale": self.unit_scale,
        }


def _parameters(
    values: object, field: str, *, required: bool
) -> tuple[ScientificParameter, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, ScientificParameter) for value in values
    ):
        raise ScientificEvidenceError(f"{field} must contain typed parameters")
    if required and not values:
        raise ScientificEvidenceError(f"{field} must not be empty")
    names = tuple(value.name for value in values)
    if len(set(names)) != len(names):
        raise ScientificEvidenceError(f"{field} parameter names must be unique")
    return values


@dataclass(frozen=True, slots=True)
class BaselineDeclaration:
    """Applicable or explicitly inapplicable comparison baseline."""

    declaration_id: str
    role: BaselineRole
    applicability: Applicability
    rationale: str
    description: str | None = None
    comparison_purpose: str | None = None
    assumptions: tuple[str, ...] = ()
    custom_role: str | None = None

    def __post_init__(self) -> None:
        _declaration_id(self.declaration_id)
        if not isinstance(self.role, BaselineRole):
            raise ScientificEvidenceError("Baseline role must be explicit")
        _applicability(
            self.applicability,
            self.rationale,
            required_values=(self.description, self.comparison_purpose),
            field="baseline",
        )
        if self.applicability is Applicability.REQUIRED:
            _nonempty(self.description, "baseline description")
            _nonempty(self.comparison_purpose, "baseline comparison purpose")
            _strings(self.assumptions, "baseline assumptions", required=True)
        else:
            _strings(self.assumptions, "baseline assumptions", required=False)
        if self.role is BaselineRole.CUSTOM:
            _nonempty(self.custom_role, "custom baseline role")
        elif self.custom_role is not None:
            raise ScientificEvidenceError(
                "Only a custom baseline may declare a custom role"
            )

    def document(self) -> JsonRecord:
        assumptions = list[JsonValue](sorted(self.assumptions))
        return {
            "declaration_id": self.declaration_id,
            "role": self.role.value,
            "custom_role": self.custom_role,
            "applicability": self.applicability.value,
            "rationale": self.rationale,
            "description": self.description,
            "comparison_purpose": self.comparison_purpose,
            "assumptions": assumptions,
        }


@dataclass(frozen=True, slots=True)
class MetricDeclaration:
    """Standard or custom metric declaration; no formula is implemented."""

    declaration_id: str
    applicability: Applicability
    rationale: str
    standard_metric: StandardMetric | None = None
    custom_metric: str | None = None
    description: str | None = None
    unit_scale: str | None = None

    def __post_init__(self) -> None:
        _declaration_id(self.declaration_id)
        if (self.standard_metric is None) == (self.custom_metric is None):
            raise ScientificEvidenceError(
                "Metric must identify exactly one standard or custom metric"
            )
        if self.standard_metric is not None and not isinstance(
            self.standard_metric, StandardMetric
        ):
            raise ScientificEvidenceError("Standard metric is malformed")
        if self.custom_metric is not None:
            _nonempty(self.custom_metric, "custom metric name")
        _applicability(
            self.applicability,
            self.rationale,
            required_values=(self.description, self.unit_scale),
            field="metric",
        )
        if self.applicability is Applicability.REQUIRED:
            _nonempty(self.description, "metric description")
            _nonempty(self.unit_scale, "metric unit/scale")

    def document(self) -> JsonRecord:
        return {
            "declaration_id": self.declaration_id,
            "standard_metric": (
                self.standard_metric.value
                if isinstance(self.standard_metric, StandardMetric)
                else None
            ),
            "custom_metric": self.custom_metric,
            "applicability": self.applicability.value,
            "rationale": self.rationale,
            "description": self.description,
            "unit_scale": self.unit_scale,
        }


@dataclass(frozen=True, slots=True)
class StatisticalMethodDeclaration:
    """Applicability and preregistered configuration for one statistical method."""

    declaration_id: str
    method: StatisticalMethod
    applicability: Applicability
    rationale: str
    assumptions: tuple[str, ...] = ()
    configuration: tuple[ScientificParameter, ...] = ()
    interpretation_purpose: str | None = None

    def __post_init__(self) -> None:
        _declaration_id(self.declaration_id)
        if not isinstance(self.method, StatisticalMethod):
            raise ScientificEvidenceError("Statistical method is malformed")
        _applicability(
            self.applicability,
            self.rationale,
            required_values=(self.interpretation_purpose,),
            field="statistical method",
        )
        required = self.applicability is Applicability.REQUIRED
        _strings(self.assumptions, "statistical assumptions", required=required)
        _parameters(
            self.configuration,
            "statistical configuration",
            required=required,
        )
        if required:
            _nonempty(self.interpretation_purpose, "method interpretation purpose")

    def document(self) -> JsonRecord:
        assumptions = list[JsonValue](sorted(self.assumptions))
        configuration: list[JsonValue] = [
            value.document()
            for value in sorted(self.configuration, key=lambda item: item.name)
        ]
        return {
            "declaration_id": self.declaration_id,
            "method": self.method.value,
            "applicability": self.applicability.value,
            "rationale": self.rationale,
            "assumptions": assumptions,
            "configuration": configuration,
            "interpretation_purpose": self.interpretation_purpose,
        }


@dataclass(frozen=True, slots=True)
class RobustnessDeclaration:
    """Applicability and exact preregistration for sample or robustness evidence."""

    declaration_id: str
    requirement: RobustnessRequirement
    applicability: Applicability
    rationale: str
    assumptions: tuple[str, ...] = ()
    configuration: tuple[ScientificParameter, ...] = ()
    interpretation_purpose: str | None = None

    def __post_init__(self) -> None:
        _declaration_id(self.declaration_id)
        if not isinstance(self.requirement, RobustnessRequirement):
            raise ScientificEvidenceError("Robustness requirement is malformed")
        _applicability(
            self.applicability,
            self.rationale,
            required_values=(self.interpretation_purpose,),
            field="robustness requirement",
        )
        required = self.applicability is Applicability.REQUIRED
        _strings(self.assumptions, "robustness assumptions", required=required)
        _parameters(
            self.configuration,
            "robustness configuration",
            required=required,
        )
        if required:
            _nonempty(
                self.interpretation_purpose,
                "robustness interpretation purpose",
            )

    def document(self) -> JsonRecord:
        assumptions = list[JsonValue](sorted(self.assumptions))
        configuration: list[JsonValue] = [
            value.document()
            for value in sorted(self.configuration, key=lambda item: item.name)
        ]
        return {
            "declaration_id": self.declaration_id,
            "requirement": self.requirement.value,
            "applicability": self.applicability.value,
            "rationale": self.rationale,
            "assumptions": assumptions,
            "configuration": configuration,
            "interpretation_purpose": self.interpretation_purpose,
        }


@dataclass(frozen=True, slots=True)
class ReportingConventions:
    """Study-specific conventions needed to interpret declared evidence."""

    return_frequency: str
    annualization: str
    risk_free_rate: str
    trade_counting: str
    portfolio_aggregation: str
    missing_data_treatment: str
    confidence_interval_method: str

    def __post_init__(self) -> None:
        for field, value in (
            ("return frequency", self.return_frequency),
            ("annualization", self.annualization),
            ("risk-free-rate", self.risk_free_rate),
            ("trade counting", self.trade_counting),
            ("portfolio aggregation", self.portfolio_aggregation),
            ("missing-data treatment", self.missing_data_treatment),
            ("confidence-interval method", self.confidence_interval_method),
        ):
            _nonempty(value, field)

    def document(self) -> JsonRecord:
        return {
            "return_frequency": self.return_frequency,
            "annualization": self.annualization,
            "risk_free_rate": self.risk_free_rate,
            "trade_counting": self.trade_counting,
            "portfolio_aggregation": self.portfolio_aggregation,
            "missing_data_treatment": self.missing_data_treatment,
            "confidence_interval_method": self.confidence_interval_method,
        }


@dataclass(frozen=True, slots=True)
class FrozenMultipleTestingBinding:
    """A structural reference to Item 8 frozen multiple-testing authority."""

    experiment_id: str
    frozen_revision_digest: str
    family_id: str
    budget: int
    correction_plan: str

    def __post_init__(self) -> None:
        self._validate_shape()

    def _validate_shape(self) -> None:
        validate_typed_id(self.experiment_id, RegistryKind.EXPERIMENT)
        require_sha256_digest(self.frozen_revision_digest)
        validate_typed_id(self.family_id, RegistryKind.FAMILY)
        if type(self.budget) is not int or self.budget < 1:
            raise ScientificEvidenceError(
                "Frozen multiple-testing budget must be a positive integer"
            )
        _nonempty(self.correction_plan, "frozen correction plan")

    def document(self) -> JsonRecord:
        return {
            "experiment_id": self.experiment_id,
            "frozen_revision_digest": self.frozen_revision_digest,
            "family_id": self.family_id,
            "budget": self.budget,
            "correction_plan": self.correction_plan,
            "attempt_accounting_authority": ATTEMPT_ACCOUNTING_AUTHORITY,
            "accounting_rules": {
                "ai_generated_variants_count": True,
                "failed_and_rejected_attempts_count": True,
                "selection_retries_count": True,
                "related_variants_are_independent_evidence": False,
                "raw_and_adjusted_inference_are_distinct": True,
            },
        }


def bind_frozen_multiple_testing(
    frozen_record: Mapping[str, JsonValue],
    frozen_revision_digest: str,
    *,
    family_id: str,
    budget: int,
    correction_plan: str,
) -> FrozenMultipleTestingBinding:
    """Cross-check a frozen record without duplicating Item 8 attempt counters."""
    if frozen_record.get("lifecycle_status") != "FROZEN":
        raise ScientificEvidenceError("Multiple-testing binding requires FROZEN input")
    experiment_id = frozen_record.get("experiment_id")
    research_family_id = frozen_record.get("research_family_id")
    multiple_testing = frozen_record.get("multiple_testing")
    if (
        not isinstance(experiment_id, str)
        or not isinstance(research_family_id, str)
        or not isinstance(multiple_testing, dict)
    ):
        raise ScientificEvidenceError("Frozen multiple-testing evidence is malformed")
    validate_typed_id(experiment_id, RegistryKind.EXPERIMENT)
    validate_typed_id(research_family_id, RegistryKind.FAMILY)
    require_sha256_digest(frozen_revision_digest)
    frozen_family = multiple_testing.get("family_id")
    frozen_budget = multiple_testing.get("budget")
    frozen_correction = multiple_testing.get("correction_plan")
    if (
        frozen_family != research_family_id
        or not isinstance(frozen_budget, int)
        or isinstance(frozen_budget, bool)
        or frozen_budget < 1
        or not isinstance(frozen_correction, str)
        or not frozen_correction.strip()
    ):
        raise ScientificEvidenceError("Frozen multiple-testing evidence is malformed")
    if frozen_record.get("variants_attempted") != 0:
        raise ScientificEvidenceError(
            "FROZEN attempt accounting must remain Item 8 zero"
        )
    accounting = frozen_record.get("variant_accounting")
    if not isinstance(accounting, dict) or any(
        accounting.get(key) != 0 for key in ("ai_generated_attempts", "failed_attempts")
    ):
        raise ScientificEvidenceError(
            "FROZEN subset accounting must remain Item 8 zero"
        )
    if (
        family_id != frozen_family
        or type(budget) is not int
        or budget != frozen_budget
        or correction_plan != frozen_correction
    ):
        raise ScientificEvidenceError(
            "Scientific evidence contradicts frozen multiple-testing authority"
        )
    return FrozenMultipleTestingBinding(
        experiment_id,
        frozen_revision_digest,
        research_family_id,
        frozen_budget,
        frozen_correction,
    )


def _ids(values: Sequence[object]) -> tuple[str, ...]:
    identities = tuple(getattr(value, "declaration_id", None) for value in values)
    if any(not isinstance(value, str) for value in identities):
        raise ScientificEvidenceError("Every declaration must have a stable identity")
    string_ids = tuple(value for value in identities if isinstance(value, str))
    if len(set(string_ids)) != len(string_ids):
        raise ScientificEvidenceError("Declaration identities must be unique")
    return string_ids


def _validate_plan_inputs(
    experiment_id: object,
    temporal_validation_plan_digest: object,
    temporal_validation: object,
    baselines: tuple[BaselineDeclaration, ...],
    metrics: tuple[MetricDeclaration, ...],
    methods: tuple[StatisticalMethodDeclaration, ...],
    robustness: tuple[RobustnessDeclaration, ...],
    conventions: object,
    binding: object,
) -> None:
    if not isinstance(experiment_id, str):
        raise ScientificEvidenceError("Experiment identity must be explicit")
    validate_typed_id(experiment_id, RegistryKind.EXPERIMENT)
    if not isinstance(temporal_validation_plan_digest, str):
        raise ScientificEvidenceError("Temporal validation plan digest is malformed")
    require_sha256_digest(temporal_validation_plan_digest)
    if not isinstance(temporal_validation, FrozenTemporalValidationBinding):
        raise ScientificEvidenceError("Frozen temporal-validation binding is required")
    temporal_validation.verify()
    if temporal_validation.experiment_id != experiment_id:
        raise ScientificEvidenceError(
            "Evidence plan experiment contradicts its temporal binding"
        )
    if (
        temporal_validation_plan_digest
        != temporal_validation.temporal_validation_plan_digest
    ):
        raise ScientificEvidenceError(
            "Evidence plan temporal digest contradicts its temporal binding"
        )
    if not isinstance(conventions, ReportingConventions):
        raise ScientificEvidenceError("Reporting conventions must be explicit")
    if not isinstance(binding, FrozenMultipleTestingBinding):
        raise ScientificEvidenceError("Frozen multiple-testing binding is required")
    binding._validate_shape()
    if binding.experiment_id != experiment_id:
        raise ScientificEvidenceError(
            "Evidence plan experiment contradicts its multiple-testing binding"
        )
    if binding.experiment_id != temporal_validation.experiment_id:
        raise ScientificEvidenceError(
            "Temporal and multiple-testing bindings reference different experiments"
        )
    if binding.frozen_revision_digest != temporal_validation.frozen_revision_digest:
        raise ScientificEvidenceError(
            "Temporal and multiple-testing bindings reference different frozen revisions"
        )
    typed_groups: tuple[tuple[Sequence[object], type[object], str], ...] = (
        (baselines, BaselineDeclaration, "baseline"),
        (metrics, MetricDeclaration, "metric"),
        (methods, StatisticalMethodDeclaration, "statistical method"),
        (robustness, RobustnessDeclaration, "robustness"),
    )
    for values, expected_type, label in typed_groups:
        if not values or any(not isinstance(value, expected_type) for value in values):
            raise ScientificEvidenceError(
                f"Complete typed {label} declarations required"
            )
    all_values: tuple[object, ...] = (*baselines, *metrics, *methods, *robustness)
    _ids(all_values)

    core_baselines = tuple(
        value.role for value in baselines if value.role is not BaselineRole.CUSTOM
    )
    required_baselines = (
        BaselineRole.NAIVE,
        BaselineRole.SIMPLE,
        BaselineRole.ESTABLISHED_REFERENCE,
    )
    if len(core_baselines) != len(set(core_baselines)) or set(core_baselines) != set(
        required_baselines
    ):
        raise ScientificEvidenceError(
            "Naive, simple, and established baselines each require applicability"
        )
    standard_metrics = tuple(
        value.standard_metric
        for value in metrics
        if isinstance(value.standard_metric, StandardMetric)
    )
    if len(standard_metrics) != len(set(standard_metrics)) or set(
        standard_metrics
    ) != set(StandardMetric):
        raise ScientificEvidenceError(
            "Every standard metric requires an explicit applicability declaration"
        )
    method_values = tuple(value.method for value in methods)
    if len(method_values) != len(set(method_values)) or set(method_values) != set(
        StatisticalMethod
    ):
        raise ScientificEvidenceError(
            "Every statistical method requires an applicability declaration"
        )
    robustness_values = tuple(value.requirement for value in robustness)
    if len(robustness_values) != len(set(robustness_values)) or set(
        robustness_values
    ) != set(RobustnessRequirement):
        raise ScientificEvidenceError(
            "Every robustness requirement requires an applicability declaration"
        )


def _plan_document(
    experiment_id: str,
    temporal_validation_plan_digest: str,
    temporal_validation: FrozenTemporalValidationBinding,
    baselines: tuple[BaselineDeclaration, ...],
    metrics: tuple[MetricDeclaration, ...],
    methods: tuple[StatisticalMethodDeclaration, ...],
    robustness: tuple[RobustnessDeclaration, ...],
    conventions: ReportingConventions,
    binding: FrozenMultipleTestingBinding,
) -> JsonRecord:
    baseline_values: list[JsonValue] = [value.document() for value in baselines]
    metric_values: list[JsonValue] = [value.document() for value in metrics]
    method_values: list[JsonValue] = [value.document() for value in methods]
    robustness_values: list[JsonValue] = [value.document() for value in robustness]
    return {
        "schema_version": "1.0.0",
        "plan_type": "SCIENTIFIC_EVIDENCE_PLAN",
        "experiment_id": experiment_id,
        "temporal_validation_plan_digest": temporal_validation_plan_digest,
        "temporal_validation": temporal_validation.document(),
        "multiple_testing": binding.document(),
        "reporting_conventions": conventions.document(),
        "baselines": baseline_values,
        "metrics": metric_values,
        "statistical_methods": method_values,
        "robustness_requirements": robustness_values,
    }


@dataclass(frozen=True, slots=True)
class ScientificEvidencePlan:
    """Canonical preregistered scientific requirements; performs no evaluation."""

    experiment_id: str
    temporal_validation_plan_digest: str
    temporal_validation: FrozenTemporalValidationBinding
    baselines: tuple[BaselineDeclaration, ...]
    metrics: tuple[MetricDeclaration, ...]
    statistical_methods: tuple[StatisticalMethodDeclaration, ...]
    robustness_requirements: tuple[RobustnessDeclaration, ...]
    reporting_conventions: ReportingConventions
    multiple_testing: FrozenMultipleTestingBinding
    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise ScientificEvidenceIntegrityError(
                "Scientific evidence plan is not a JSON object"
            )
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)
        _validate_plan_inputs(
            self.experiment_id,
            self.temporal_validation_plan_digest,
            self.temporal_validation,
            self.baselines,
            self.metrics,
            self.statistical_methods,
            self.robustness_requirements,
            self.reporting_conventions,
            self.multiple_testing,
        )
        expected = _plan_document(
            self.experiment_id,
            self.temporal_validation_plan_digest,
            self.temporal_validation,
            self.baselines,
            self.metrics,
            self.statistical_methods,
            self.robustness_requirements,
            self.reporting_conventions,
            self.multiple_testing,
        )
        if canonicalize_json(expected) != self.canonical_bytes:
            raise ScientificEvidenceIntegrityError(
                "Scientific evidence plan differs from typed fields"
            )


def build_scientific_evidence_plan(
    *,
    experiment_id: str,
    temporal_validation: FrozenTemporalValidationBinding,
    baselines: Sequence[BaselineDeclaration],
    metrics: Sequence[MetricDeclaration],
    statistical_methods: Sequence[StatisticalMethodDeclaration],
    robustness_requirements: Sequence[RobustnessDeclaration],
    reporting_conventions: ReportingConventions,
    multiple_testing: FrozenMultipleTestingBinding,
) -> ScientificEvidencePlan:
    """Build deterministic metadata without executing any scientific method."""
    baseline_values = tuple(baselines)
    metric_values = tuple(metrics)
    method_values = tuple(statistical_methods)
    robustness_values = tuple(robustness_requirements)
    if not isinstance(temporal_validation, FrozenTemporalValidationBinding):
        raise ScientificEvidenceError("Frozen temporal-validation binding is required")
    temporal_validation_plan_digest = (
        temporal_validation.temporal_validation_plan_digest
    )
    _validate_plan_inputs(
        experiment_id,
        temporal_validation_plan_digest,
        temporal_validation,
        baseline_values,
        metric_values,
        method_values,
        robustness_values,
        reporting_conventions,
        multiple_testing,
    )
    ordered_baselines = tuple(
        sorted(baseline_values, key=lambda value: value.declaration_id)
    )
    ordered_metrics = tuple(
        sorted(metric_values, key=lambda value: value.declaration_id)
    )
    ordered_methods = tuple(
        sorted(method_values, key=lambda value: value.declaration_id)
    )
    ordered_robustness = tuple(
        sorted(robustness_values, key=lambda value: value.declaration_id)
    )
    document = _plan_document(
        experiment_id,
        temporal_validation_plan_digest,
        temporal_validation,
        ordered_baselines,
        ordered_metrics,
        ordered_methods,
        ordered_robustness,
        reporting_conventions,
        multiple_testing,
    )
    canonical_bytes = canonicalize_json(document)
    plan = ScientificEvidencePlan(
        experiment_id,
        temporal_validation_plan_digest,
        temporal_validation,
        ordered_baselines,
        ordered_metrics,
        ordered_methods,
        ordered_robustness,
        reporting_conventions,
        multiple_testing,
        canonical_bytes,
        sha256_bytes(canonical_bytes),
    )
    plan.verify()
    return plan


@dataclass(frozen=True, slots=True)
class ExactNumericEvidence:
    """Canonical numeric evidence represented without binary floating point."""

    value: str
    unit_scale: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or _NORMALIZED_DECIMAL.fullmatch(self.value) is None
        ):
            raise ScientificEvidenceError(
                "Numeric evidence must use normalized exact decimal text"
            )
        _nonempty(self.unit_scale, "numeric evidence unit/scale")

    def document(self) -> JsonRecord:
        return {"value": self.value, "unit_scale": self.unit_scale}


@dataclass(frozen=True, slots=True)
class EvidenceArtifactReference:
    """An immutable reference claim; Item 9B does not verify referenced bytes."""

    reference: str
    digest: str

    def __post_init__(self) -> None:
        _nonempty(self.reference, "evidence artifact reference")
        require_sha256_digest(self.digest)

    def document(self) -> JsonRecord:
        return {"reference": self.reference, "digest": self.digest}


@dataclass(frozen=True, slots=True)
class EvidenceObservation:
    """Future evaluator evidence for one applicable declaration."""

    declaration_id: str
    outcome: EvidenceOutcome
    narrative: str
    numeric_value: ExactNumericEvidence | None = None
    artifact_references: tuple[EvidenceArtifactReference, ...] = ()

    def __post_init__(self) -> None:
        _declaration_id(self.declaration_id)
        if not isinstance(self.outcome, EvidenceOutcome):
            raise ScientificEvidenceError("Evidence outcome is malformed")
        _nonempty(self.narrative, "evidence narrative")
        if self.numeric_value is not None and not isinstance(
            self.numeric_value, ExactNumericEvidence
        ):
            raise ScientificEvidenceError("Numeric evidence must be exact and typed")
        if any(
            not isinstance(value, EvidenceArtifactReference)
            for value in self.artifact_references
        ):
            raise ScientificEvidenceError("Artifact evidence references are malformed")
        pairs = tuple(
            (value.reference, value.digest) for value in self.artifact_references
        )
        if len(set(pairs)) != len(pairs):
            raise ScientificEvidenceError("Artifact evidence references must be unique")
        if self.outcome is EvidenceOutcome.PENDING:
            if self.numeric_value is not None:
                raise ScientificEvidenceError(
                    "PENDING evidence cannot contain numeric evidence"
                )
            if self.artifact_references:
                raise ScientificEvidenceError(
                    "PENDING evidence cannot contain artifact references"
                )

    def document(self) -> JsonRecord:
        references: list[JsonValue] = [
            value.document()
            for value in sorted(
                self.artifact_references,
                key=lambda item: (item.reference, item.digest),
            )
        ]
        return {
            "declaration_id": self.declaration_id,
            "outcome": self.outcome.value,
            "narrative": self.narrative,
            "numeric_value": (
                self.numeric_value.document()
                if isinstance(self.numeric_value, ExactNumericEvidence)
                else None
            ),
            "artifact_references": references,
        }


@dataclass(frozen=True, slots=True)
class GateAssessment:
    """One explicit V0-V9 assessment with reason or supporting evidence."""

    gate: ValidationGate
    status: GateStatus
    rationale: str | None = None
    supporting_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.gate, ValidationGate):
            raise ScientificEvidenceError("Validation gate is malformed")
        if not isinstance(self.status, GateStatus):
            raise ScientificEvidenceError("Gate status is malformed")
        _strings(
            self.supporting_references,
            "gate supporting references",
            required=self.status is GateStatus.PASS,
        )
        if self.status is GateStatus.PASS:
            if self.rationale is not None:
                _nonempty(self.rationale, "PASS gate rationale")
        else:
            _nonempty(self.rationale, "non-PASS gate rationale")

    def document(self) -> JsonRecord:
        references = list[JsonValue](sorted(self.supporting_references))
        return {
            "gate": self.gate.value,
            "status": self.status.value,
            "rationale": self.rationale,
            "supporting_references": references,
        }


def _observations(
    values: tuple[EvidenceObservation, ...],
    required_ids: set[str],
    field: str,
) -> None:
    if any(not isinstance(value, EvidenceObservation) for value in values):
        raise ScientificEvidenceError(f"{field} must contain typed evidence")
    observed_ids = tuple(value.declaration_id for value in values)
    if len(set(observed_ids)) != len(observed_ids):
        raise ScientificEvidenceError(f"{field} identities must be unique")
    if set(observed_ids) != required_ids:
        raise ScientificEvidenceError(
            f"{field} must account for every applicable declaration"
        )


def _required_ids(
    values: Sequence[
        BaselineDeclaration
        | MetricDeclaration
        | StatisticalMethodDeclaration
        | RobustnessDeclaration
    ],
) -> set[str]:
    return {
        value.declaration_id
        for value in values
        if value.applicability is Applicability.REQUIRED
    }


def _normalized_texts(values: object, field: str) -> tuple[str, ...]:
    return tuple(sorted(_strings(values, field, required=False)))


def _validate_report_inputs(
    plan: object,
    partition_role: object,
    sealed_release_evidence_reference: object,
    report_status: object,
    outcome: object,
    baseline_evidence: tuple[EvidenceObservation, ...],
    metric_evidence: tuple[EvidenceObservation, ...],
    statistical_method_evidence: tuple[EvidenceObservation, ...],
    robustness_evidence: tuple[EvidenceObservation, ...],
    gate_assessments: tuple[GateAssessment, ...],
    warnings: tuple[str, ...],
    limitations: tuple[str, ...],
    failures: tuple[str, ...],
) -> None:
    if not isinstance(plan, ScientificEvidencePlan):
        raise ScientificEvidenceError("A verified scientific evidence plan is required")
    plan.verify()
    if not isinstance(partition_role, PartitionRole):
        raise ScientificEvidenceError("Report partition role is malformed")
    if partition_role is PartitionRole.SEALED_OUT_OF_SAMPLE:
        _nonempty(
            sealed_release_evidence_reference,
            "sealed release evidence reference",
        )
    elif sealed_release_evidence_reference is not None:
        raise ScientificEvidenceError(
            "Only sealed-OOS reports may declare release evidence"
        )
    if not isinstance(report_status, ReportStatus):
        raise ScientificEvidenceError("Report status is malformed")
    if not isinstance(outcome, EvidenceOutcome):
        raise ScientificEvidenceError("Report outcome is malformed")
    if (report_status is ReportStatus.NOT_YET_EVALUATED) is not (
        outcome is EvidenceOutcome.PENDING
    ):
        raise ScientificEvidenceError(
            "NOT_YET_EVALUATED status and PENDING report outcome must occur together"
        )
    _observations(
        baseline_evidence,
        _required_ids(plan.baselines),
        "baseline evidence",
    )
    _observations(
        metric_evidence,
        _required_ids(plan.metrics),
        "metric evidence",
    )
    _observations(
        statistical_method_evidence,
        _required_ids(plan.statistical_methods),
        "statistical-method evidence",
    )
    _observations(
        robustness_evidence,
        _required_ids(plan.robustness_requirements),
        "robustness evidence",
    )
    if any(not isinstance(value, GateAssessment) for value in gate_assessments):
        raise ScientificEvidenceError("Gate assessments must be typed")
    gates = tuple(value.gate for value in gate_assessments)
    if len(gates) != len(set(gates)) or set(gates) != set(ValidationGate):
        raise ScientificEvidenceError("Every V0-V9 gate must be assessed exactly once")
    if report_status is ReportStatus.VALIDATED:
        if any(
            value.status in {GateStatus.FAIL, GateStatus.PENDING}
            for value in gate_assessments
        ):
            raise ScientificEvidenceError(
                "Validated status is forbidden with a FAIL or PENDING gate"
            )
        required_evidence = (
            *baseline_evidence,
            *metric_evidence,
            *statistical_method_evidence,
            *robustness_evidence,
        )
        if any(
            value.outcome in {EvidenceOutcome.PENDING, EvidenceOutcome.FAILED}
            for value in required_evidence
        ):
            raise ScientificEvidenceError(
                "Validated status requires every required evidence item to be completed"
            )
        if outcome is EvidenceOutcome.FAILED:
            raise ScientificEvidenceError(
                "Validated status is forbidden with a FAILED report outcome"
            )
    _strings(warnings, "report warnings", required=False)
    _strings(limitations, "report limitations", required=False)
    _strings(failures, "report failures", required=outcome is EvidenceOutcome.FAILED)


def _observation_documents(
    values: tuple[EvidenceObservation, ...],
) -> list[JsonValue]:
    return [
        value.document()
        for value in sorted(values, key=lambda item: item.declaration_id)
    ]


def _report_document(
    plan: ScientificEvidencePlan,
    partition_role: PartitionRole,
    sealed_release_evidence_reference: str | None,
    report_status: ReportStatus,
    outcome: EvidenceOutcome,
    baseline_evidence: tuple[EvidenceObservation, ...],
    metric_evidence: tuple[EvidenceObservation, ...],
    statistical_method_evidence: tuple[EvidenceObservation, ...],
    robustness_evidence: tuple[EvidenceObservation, ...],
    gate_assessments: tuple[GateAssessment, ...],
    warnings: tuple[str, ...],
    limitations: tuple[str, ...],
    failures: tuple[str, ...],
) -> JsonRecord:
    gate_values: list[JsonValue] = [
        value.document()
        for value in sorted(gate_assessments, key=lambda item: item.gate.value)
    ]
    return {
        "schema_version": "1.0.0",
        "report_type": "SCIENTIFIC_EVIDENCE_REPORT",
        "experiment_id": plan.experiment_id,
        "evidence_plan_digest": plan.digest,
        "partition_role": partition_role.value,
        "sealed_release_evidence_reference": sealed_release_evidence_reference,
        "sealed_release_authorization_verified": False,
        "status": report_status.value,
        "outcome": outcome.value,
        "baseline_evidence": _observation_documents(baseline_evidence),
        "metric_evidence": _observation_documents(metric_evidence),
        "statistical_method_evidence": _observation_documents(
            statistical_method_evidence
        ),
        "robustness_evidence": _observation_documents(robustness_evidence),
        "gate_assessments": gate_values,
        "warnings": list(sorted(warnings)),
        "limitations": list(sorted(limitations)),
        "failures": list(sorted(failures)),
        "decision_authority": "ITEM_8_EXPERIMENT_LIFECYCLE",
    }


@dataclass(frozen=True, slots=True)
class ScientificEvidenceReport:
    """Canonical decision-support evidence; never an experiment decision."""

    plan: ScientificEvidencePlan
    partition_role: PartitionRole
    sealed_release_evidence_reference: str | None
    report_status: ReportStatus
    outcome: EvidenceOutcome
    baseline_evidence: tuple[EvidenceObservation, ...]
    metric_evidence: tuple[EvidenceObservation, ...]
    statistical_method_evidence: tuple[EvidenceObservation, ...]
    robustness_evidence: tuple[EvidenceObservation, ...]
    gate_assessments: tuple[GateAssessment, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    failures: tuple[str, ...]
    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise ScientificEvidenceIntegrityError(
                "Scientific evidence report is not a JSON object"
            )
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)
        _validate_report_inputs(
            self.plan,
            self.partition_role,
            self.sealed_release_evidence_reference,
            self.report_status,
            self.outcome,
            self.baseline_evidence,
            self.metric_evidence,
            self.statistical_method_evidence,
            self.robustness_evidence,
            self.gate_assessments,
            self.warnings,
            self.limitations,
            self.failures,
        )
        expected = _report_document(
            self.plan,
            self.partition_role,
            self.sealed_release_evidence_reference,
            self.report_status,
            self.outcome,
            self.baseline_evidence,
            self.metric_evidence,
            self.statistical_method_evidence,
            self.robustness_evidence,
            self.gate_assessments,
            self.warnings,
            self.limitations,
            self.failures,
        )
        if canonicalize_json(expected) != self.canonical_bytes:
            raise ScientificEvidenceIntegrityError(
                "Scientific evidence report differs from typed fields"
            )


def build_scientific_evidence_report(
    *,
    plan: ScientificEvidencePlan,
    partition_role: PartitionRole,
    sealed_release_evidence_reference: str | None,
    report_status: ReportStatus,
    outcome: EvidenceOutcome,
    baseline_evidence: Sequence[EvidenceObservation],
    metric_evidence: Sequence[EvidenceObservation],
    statistical_method_evidence: Sequence[EvidenceObservation],
    robustness_evidence: Sequence[EvidenceObservation],
    gate_assessments: Sequence[GateAssessment],
    warnings: Sequence[str] = (),
    limitations: Sequence[str] = (),
    failures: Sequence[str] = (),
) -> ScientificEvidenceReport:
    """Construct a deterministic report envelope without evaluating evidence."""
    baseline_values = tuple(baseline_evidence)
    metric_values = tuple(metric_evidence)
    method_values = tuple(statistical_method_evidence)
    robustness_values = tuple(robustness_evidence)
    gate_values = tuple(gate_assessments)
    warning_values = _normalized_texts(tuple(warnings), "report warnings")
    limitation_values = _normalized_texts(tuple(limitations), "report limitations")
    failure_values = _normalized_texts(tuple(failures), "report failures")
    _validate_report_inputs(
        plan,
        partition_role,
        sealed_release_evidence_reference,
        report_status,
        outcome,
        baseline_values,
        metric_values,
        method_values,
        robustness_values,
        gate_values,
        warning_values,
        limitation_values,
        failure_values,
    )
    document = _report_document(
        plan,
        partition_role,
        sealed_release_evidence_reference,
        report_status,
        outcome,
        baseline_values,
        metric_values,
        method_values,
        robustness_values,
        gate_values,
        warning_values,
        limitation_values,
        failure_values,
    )
    canonical_bytes = canonicalize_json(document)
    report = ScientificEvidenceReport(
        plan,
        partition_role,
        sealed_release_evidence_reference,
        report_status,
        outcome,
        tuple(sorted(baseline_values, key=lambda value: value.declaration_id)),
        tuple(sorted(metric_values, key=lambda value: value.declaration_id)),
        tuple(sorted(method_values, key=lambda value: value.declaration_id)),
        tuple(sorted(robustness_values, key=lambda value: value.declaration_id)),
        tuple(sorted(gate_values, key=lambda value: value.gate.value)),
        warning_values,
        limitation_values,
        failure_values,
        canonical_bytes,
        sha256_bytes(canonical_bytes),
    )
    report.verify()
    return report
