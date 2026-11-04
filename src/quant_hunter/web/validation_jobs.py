"""Frozen chronological software definitions and trusted train-only computations."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from decimal import Context, Decimal, InvalidOperation, localcontext
from typing import Any, cast

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.data_quality import SelectedSnapshot
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.research_validation import (
    BootstrapSpec,
    ObservationTimes,
    ResearchValidationError,
    ResearchValidationService,
    SupervisedRow,
    moving_block_mean,
    protocol_document,
)
from quant_hunter.research_validation.temporal import Predictor
from quant_hunter.validation import (
    ChronologicalPartitions,
    GapEvidence,
    TemporalInterval,
    ValidationFold,
    ValidationPlan,
    ValidationScheme,
    build_validation_plan,
)

PROFILE = "qh-owned-chronological-software-v1"
MAX_ROWS = 10_000
MAX_MANIFEST = 2_000_000
MAX_REPORT = 16_000_000
OLS_RCOND = 1e-12
OLS_MAX_CONDITION = 1e10


def stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def instant(value: str) -> datetime:
    if (
        not isinstance(value, str)
        or not 20 <= len(value) <= 32
        or not value.endswith("Z")
    ):
        raise ResearchValidationError("VALIDATION_UTC_REQUIRED")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ResearchValidationError("VALIDATION_UTC_REQUIRED") from None
    if result.utcoffset() != timedelta(0):
        raise ResearchValidationError("VALIDATION_UTC_REQUIRED")
    return result


def cost_number(value: str) -> float:
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        raise ResearchValidationError("INVALID_DIAGNOSTIC_COST")
    try:
        with localcontext(Context(prec=64)):
            amount = Decimal(value)
            if not amount.is_finite() or not 0 <= amount <= 1000:
                raise ValueError
            return float(amount)
    except InvalidOperation, ValueError, OverflowError:
        raise ResearchValidationError("INVALID_DIAGNOSTIC_COST") from None


@dataclass(frozen=True, slots=True)
class ValidationControls:
    evaluation_as_of: str
    model: str = "TRAIN_MEAN"
    lookback: int = 4
    horizon: int = 1
    training_rows: int = 120
    folds: int = 2
    purge_bars: int = 2
    embargo_bars: int = 1
    minimum_train: int = 20
    minimum_validation: int = 10
    commission_bps: str = "0"
    slippage_bps: str = "0"
    block_length: int = 2
    repetitions: int = 200
    seed: int = 0
    confidence: str = "0.95"
    minimum_observations: int = 20

    def __post_init__(self) -> None:
        bounds = {
            "lookback": (1, 16),
            "horizon": (1, 120),
            "training_rows": (4, MAX_ROWS - 2),
            "folds": (1, 5),
            "purge_bars": (0, 120),
            "embargo_bars": (0, 120),
            "minimum_train": (2, MAX_ROWS),
            "minimum_validation": (1, MAX_ROWS),
            "repetitions": (100, 1000),
            "minimum_observations": (4, MAX_ROWS),
        }
        if self.model not in {"TRAIN_MEAN", "OLS_LAG_RETURNS"} or any(
            type(getattr(self, key)) is not int or not low <= getattr(self, key) <= high
            for key, (low, high) in bounds.items()
        ):
            raise ResearchValidationError("INVALID_VALIDATION_CONTROLS")
        instant(self.evaluation_as_of)
        cost_number(self.commission_bps)
        cost_number(self.slippage_bps)
        self.bootstrap().__post_init__()

    def bootstrap(self) -> BootstrapSpec:
        return BootstrapSpec(
            self.block_length,
            self.repetitions,
            self.seed,
            self.confidence,
            self.minimum_observations,
        )

    def to_record(self) -> JsonRecord:
        self.__post_init__()
        return {"profile": PROFILE, **cast(JsonRecord, asdict(self))}

    @classmethod
    def from_record(cls, record: JsonRecord) -> ValidationControls:
        if (
            set(record) != {"profile", *(field.name for field in fields(cls))}
            or record["profile"] != PROFILE
        ):
            raise ResearchValidationError("INVALID_VALIDATION_CONTROLS")
        return cls(
            **cast(
                Any, {key: value for key, value in record.items() if key != "profile"}
            )
        )


def table(snapshot: SelectedSnapshot, raw: bytes) -> Any:
    snapshot.to_record()
    if (
        snapshot.evidence_mode != "SYNTHETIC"
        or not snapshot.causal_eligible
        or snapshot.admission != "SYNTHETIC_SOFTWARE_ONLY"
    ):
        raise ResearchValidationError("VALIDATION_SYNTHETIC_CAUSAL_ADMISSION_REQUIRED")
    if (
        not 4 <= snapshot.row_count <= MAX_ROWS
        or sha256_bytes(raw) != snapshot.normalized_digest
    ):
        raise ResearchValidationError("VALIDATION_DATASET_BOUND_OR_HASH")
    # Caller already verified QualityService's bounded fixed-width graph. No
    # arbitrary upload bytes are admitted directly to this trusted adapter.
    result = pq.read_table(pa.BufferReader(raw))
    if result.num_rows != snapshot.row_count or not {
        "close",
        "close_at",
        "available_at",
    } <= set(result.column_names):
        raise ResearchValidationError("VALIDATION_SOURCE_SCHEMA")
    return result


def prepare(
    snapshot: SelectedSnapshot, raw: bytes, controls: ValidationControls
) -> tuple[JsonRecord, ValidationPlan]:
    """Describe immutable timing only; no returns, labels, normalization or fitting."""
    source = table(snapshot, raw)
    controls.__post_init__()
    closes = cast(list[datetime], source.column("close_at").to_pylist())
    count = len(closes)
    if (
        controls.training_rows >= count
        or controls.training_rows // controls.folds <= controls.purge_bars
        or (count - controls.training_rows) // controls.folds <= controls.embargo_bars
    ):
        raise ResearchValidationError("VALIDATION_INTERVALS_TOO_SMALL")
    start, end = (
        instant(cast(str, snapshot.bounds["start"])),
        instant(cast(str, snapshot.bounds["end"])),
    )
    middle = closes[controls.training_rows - 1] + timedelta(microseconds=1)
    try:
        partitions = ChronologicalPartitions(
            TemporalInterval(stamp(start), stamp(middle)),
            TemporalInterval(stamp(middle), stamp(end)),
            TemporalInterval(stamp(end), stamp(end + timedelta(days=1))),
            "V0_METADATA_ONLY_NEVER_OPEN",
        )
    except OverflowError:
        raise ResearchValidationError("VALIDATION_INTERVAL_OVERFLOW") from None
    scheme = (
        ValidationScheme.CHRONOLOGICAL_HOLDOUT
        if controls.folds == 1
        else ValidationScheme.EXPANDING_WINDOW
    )
    folds: list[ValidationFold] = []
    remaining = count - controls.training_rows
    for index in range(controls.folds):
        training_count = (
            controls.training_rows * (index + 1) // controls.folds - controls.purge_bars
        )
        train_end = closes[training_count - 1] + timedelta(microseconds=1)
        segment_start = controls.training_rows + remaining * index // controls.folds
        segment_stop = (
            controls.training_rows + remaining * (index + 1) // controls.folds
        )
        valid_start = (
            middle
            if index == 0
            else closes[segment_start - 1] + timedelta(microseconds=1)
        )
        valid_end = min(
            end,
            closes[segment_stop - controls.embargo_bars - 1]
            + timedelta(microseconds=1),
        )
        embargo_end = min(end, closes[segment_stop - 1] + timedelta(microseconds=1))
        purge = (
            GapEvidence.excluded(TemporalInterval(stamp(train_end), stamp(valid_start)))
            if train_end < valid_start
            else GapEvidence.not_applicable(
                "Zero declared purge and coincident training/validation boundaries"
            )
        )
        embargo = (
            GapEvidence.excluded(TemporalInterval(stamp(valid_end), stamp(embargo_end)))
            if controls.embargo_bars
            else GapEvidence.not_applicable(
                "Explicit zero-bar embargo; actual feature/label dependencies still checked"
            )
        )
        folds.append(
            ValidationFold(
                f"fold-{index + 1}",
                index + 1,
                scheme,
                TemporalInterval(stamp(start), stamp(train_end)),
                TemporalInterval(stamp(valid_start), stamp(valid_end)),
                purge,
                embargo,
            )
        )
    plan = build_validation_plan(partitions, scheme, folds)
    protocol = protocol_document(
        plan,
        controls.bootstrap(),
        minimum_train=controls.minimum_train,
        minimum_validation=controls.minimum_validation,
    )
    config: JsonRecord = {
        "kind": "CHRONOLOGICAL_VALIDATION",
        "evidence_mode": "SYNTHETIC",
        "dataset_start": stamp(start),
        "dataset_end": stamp(end),
        "training_start": stamp(start),
        "train_end": stamp(middle - timedelta(microseconds=1)),
        "training_end_exclusive": stamp(middle),
        "random_seed": controls.seed,
        "controls": controls.to_record(),
        "selected_snapshot": snapshot.to_record(),
        "chronological_validation": protocol,
        "software_method": {
            "implemented_scope": f"{controls.model} on lagged close returns; expanding development prefixes with strictly later validation segments",
            "source_citations": [
                "https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html"
            ],
            "assumptions": [
                "Synthetic causal-quality bytes only; no historical validation claim",
                "Each fold trains only within development; prior validation outcomes are never reused",
                "One explicitly selected fitted model per actual Item8 attempt; comparison baseline requires another attempt",
                f"OLS rcond={OLS_RCOND}, maximum condition={OLS_MAX_CONDITION}; rank failure is retained, no fallback",
            ],
            "cost_model": "Commission/slippage are explicit one-way diagnostic return hurdles only; no fill, position, execution or realized PnL claim",
        },
    }
    manifest: JsonRecord = {
        "profile": PROFILE,
        "selected_snapshot": snapshot.to_record(),
        "configuration": config,
        "row_count": count,
        "plan_digest": plan.digest,
        "feature_recipe": "lookback consecutive close-to-close simple returns ending at decision close",
        "label_recipe": "close[t+horizon]/close[t]-1; actual receipt=max availability across full label support",
        "decision_time": "bar close; unavailable features excluded, never shifted backward",
        "normalization": "train-fold mean and population scale only for OLS; no global transform",
        "planned_fitted_candidates": 1,
    }
    if len(canonicalize_json(manifest)) > MAX_MANIFEST:
        raise ResearchValidationError("VALIDATION_MANIFEST_LIMIT")
    return manifest, plan


def observations(
    snapshot: SelectedSnapshot, raw: bytes, controls: ValidationControls
) -> tuple[tuple[SupervisedRow, ...], list[JsonValue]]:
    source = table(snapshot, raw)
    prices = source.column("close").to_pylist()
    closes = cast(list[datetime], source.column("close_at").to_pylist())
    available = cast(list[datetime], source.column("available_at").to_pylist())
    step = timedelta(microseconds=snapshot.step_ns // 1000)
    rows: list[SupervisedRow] = []
    exclusions: list[JsonValue] = []
    for index in range(len(prices)):
        identity = f"row-{index}"
        if index < controls.lookback or index + controls.horizon >= len(prices):
            exclusions.append(
                {"row_id": identity, "reason": "INSUFFICIENT_FEATURE_OR_LABEL_SUPPORT"}
            )
            continue
        begin, end = index - controls.lookback, index + controls.horizon
        if any(closes[j] - closes[j - 1] != step for j in range(begin + 1, end + 1)):
            exclusions.append(
                {"row_id": identity, "reason": "NONCONTIGUOUS_SUPPORT_NO_IMPUTATION"}
            )
            continue
        timing = ObservationTimes(
            identity,
            closes[index],
            closes[begin],
            closes[index],
            max(available[begin : index + 1]),
            closes[index],
            closes[end],
            max(available[index : end + 1]),
        )
        features = (float("nan"),) * controls.lookback
        label = float("nan")
        if timing.feature_available_at <= timing.decision_at:
            history = [float(value) for value in prices[begin : index + 1]]
            if any(
                not math.isfinite(value) or not 0 < value <= 1e30 for value in history
            ):
                raise ResearchValidationError("VALIDATION_PRICE_RANGE")
            features = tuple(
                history[j] / history[j - 1] - 1 for j in range(1, controls.lookback + 1)
            )
            # A delayed label stays an unread placeholder; membership/scoring
            # must establish actual receipt before numerical use.
            if timing.label_available_at <= instant(controls.evaluation_as_of):
                final = float(prices[end])
                if not math.isfinite(final) or not 0 < final <= 1e30:
                    raise ResearchValidationError("VALIDATION_PRICE_RANGE")
                label = final / history[-1] - 1
        rows.append(SupervisedRow(timing, features, label))
    if not rows:
        raise ResearchValidationError("VALIDATION_NO_SUPPORTED_ROWS")
    return tuple(rows), exclusions


def fit_model(
    model: str, features: tuple[tuple[float, ...], ...], labels: tuple[float, ...]
) -> FittedPredictor:
    x, y = np.asarray(features, dtype=float), np.asarray(labels, dtype=float)
    if (
        x.ndim != 2
        or y.ndim != 1
        or not 2 <= len(y) <= MAX_ROWS
        or x.shape[0] != len(y)
        or not 1 <= x.shape[1] <= 16
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
    ):
        raise ResearchValidationError("VALIDATION_TRAIN_SHAPE")
    if model == "TRAIN_MEAN":
        mean = float(y.mean())
        return FittedPredictor(
            lambda features: mean,
            {"model": model, "mean": mean, "training_count": len(y)},
        )
    if model != "OLS_LAG_RETURNS":
        raise ResearchValidationError("INVALID_VALIDATION_MODEL")
    center, scale = x.mean(axis=0), x.std(axis=0, ddof=0)
    if not np.isfinite(scale).all() or np.any(scale <= 1e-15):
        raise ResearchValidationError("OLS_DEGENERATE_FEATURE")
    design = np.column_stack((np.ones(len(y)), (x - center) / scale))
    try:
        coefficients, _, rank, singular = np.linalg.lstsq(design, y, rcond=OLS_RCOND)
    except np.linalg.LinAlgError:
        raise ResearchValidationError("OLS_SOLVER_FAILED") from None
    if (
        rank != design.shape[1]
        or not np.isfinite(coefficients).all()
        or singular[-1] <= 0
        or singular[0] / singular[-1] > OLS_MAX_CONDITION
    ):
        raise ResearchValidationError("OLS_RANK_OR_CONDITION")

    def predict(features: tuple[float, ...]) -> float:
        return float(np.r_[1.0, (np.asarray(features) - center) / scale] @ coefficients)

    return FittedPredictor(
        predict,
        {
            "model": model,
            "means": center.tolist(),
            "scales": scale.tolist(),
            "coefficients": coefficients.tolist(),
            "training_count": len(y),
            "rcond": OLS_RCOND,
            "maximum_condition": OLS_MAX_CONDITION,
        },
    )


@dataclass(frozen=True)
class FittedPredictor:
    predict: Callable[[tuple[float, ...]], float]
    parameters: JsonRecord

    def __call__(self, features: tuple[float, ...]) -> float:
        return self.predict(features)


def fit_plan(controls: ValidationControls) -> tuple[str, ...]:
    roles = (
        ("standardizer", "estimator")
        if controls.model == "OLS_LAG_RETURNS"
        else ("estimator",)
    )
    return tuple(
        f"fold-{index + 1}:{role}" for index in range(controls.folds) for role in roles
    )


def fit_outputs(report: JsonRecord, controls: ValidationControls) -> JsonRecord:
    output: JsonRecord = {}
    folds = cast(list[JsonRecord], report["folds"])
    if [fold.get("fold_id") for fold in folds] != [
        f"fold-{i + 1}" for i in range(controls.folds)
    ]:
        raise ResearchValidationError("VALIDATION_FIT_ARTIFACT_BINDING")
    for fold in folds:
        key = cast(str, fold["fold_id"])
        parameters = fold.get("fitted_parameters")
        if (parameters is not None) != (fold["status"] == "COMPUTED_SOFTWARE_ONLY"):
            raise ResearchValidationError("VALIDATION_FIT_ARTIFACT_BINDING")
        if parameters is None:
            output[f"{key}:estimator"] = None
            if controls.model == "OLS_LAG_RETURNS":
                output[f"{key}:standardizer"] = None
            continue
        if (
            not isinstance(parameters, dict)
            or parameters.get("model") != controls.model
        ):
            raise ResearchValidationError("VALIDATION_FIT_ARTIFACT_BINDING")
        output[f"{key}:estimator"] = parameters
        if controls.model == "OLS_LAG_RETURNS":
            output[f"{key}:standardizer"] = {
                name: parameters[name] for name in ("means", "scales", "training_count")
            }
    if set(output) != set(fit_plan(controls)):
        raise ResearchValidationError("VALIDATION_FIT_ARTIFACT_BINDING")
    return output


def execute(
    service: ResearchValidationService,
    experiment_id: str,
    snapshot: SelectedSnapshot,
    raw: bytes,
    controls: ValidationControls,
    plan: ValidationPlan,
) -> tuple[JsonRecord, JsonRecord]:
    """Caller must have registered/bound a current actual Item8 RUNNING attempt."""
    if (
        service.registry.verify_object(experiment_id)[-1].record["lifecycle_status"]
        != "RUNNING"
    ):
        raise ResearchValidationError("EXECUTION_REQUIRES_ITEM8_RUNNING")
    rows, excluded = observations(snapshot, raw, controls)
    fitted_parameters: list[JsonRecord] = []

    def fit(x: tuple[tuple[float, ...], ...], y: tuple[float, ...]) -> Predictor:
        model = fit_model(controls.model, x, y)
        fitted_parameters.append(model.parameters)
        return model

    report = service.execute(
        experiment_id,
        plan,
        rows,
        fit,
        evaluation_as_of=instant(controls.evaluation_as_of),
    )
    report["source_support_exclusions"] = excluded
    report["selected_snapshot"] = snapshot.to_record()
    report["controls"] = controls.to_record()
    summaries: list[JsonValue] = []
    all_errors: list[float] = []
    hurdle = (
        cost_number(controls.commission_bps) + cost_number(controls.slippage_bps)
    ) / 10_000
    retained_fits = iter(fitted_parameters)
    if len(fitted_parameters) != sum(
        fold["status"] == "COMPUTED_SOFTWARE_ONLY"
        for fold in cast(list[JsonRecord], report["folds"])
    ):
        raise ResearchValidationError("VALIDATION_FIT_ARTIFACT_BINDING")
    for fold in cast(list[JsonRecord], report["folds"]):
        fold["fitted_parameters"] = (
            next(retained_fits) if fold["status"] == "COMPUTED_SOFTWARE_ONLY" else None
        )
        predictions = cast(list[JsonRecord], fold["predictions"])
        errors = [
            float(cast(float, row["prediction"])) - float(cast(float, row["label"]))
            for row in predictions
            if row["label"] is not None
        ]
        for row in predictions:
            row["prediction_after_diagnostic_hurdle"] = (
                float(cast(float, row["prediction"])) - hurdle
            )
        all_errors.extend(errors)
        summaries.append(
            {
                "fold_id": fold["fold_id"],
                "status": fold["status"],
                "reason": fold["reason"],
                "training_count": len(cast(list[JsonValue], fold["training_ids"])),
                "validation_count": len(cast(list[JsonValue], fold["validation_ids"])),
                "excluded_count": len(cast(list[JsonValue], fold["exclusions"])),
                "scored_count": len(errors),
                "pending_label_count": len(predictions) - len(errors),
                "mse": sum(value * value for value in errors) / len(errors)
                if errors
                else None,
                "mae": sum(abs(value) for value in errors) / len(errors)
                if errors
                else None,
            }
        )
    uncertainty: JsonRecord = (
        moving_block_mean(
            tuple(abs(value) for value in all_errors), controls.bootstrap()
        )
        if all_errors
        else {
            "status": "INCONCLUSIVE",
            "reason": "NO_AVAILABLE_VALIDATION_LABELS",
            "interval": None,
            "p_value": None,
        }
    )
    summary: JsonRecord = {
        "profile": PROFILE,
        "evidence_mode": "SYNTHETIC",
        "empirical_status": "INCONCLUSIVE",
        "host_enforced": False,
        "missing_scientific_gates": [
            "ITEM9B_SCIENTIFIC_EVIDENCE_PLAN",
            "CALIBRATED_PER_TRIAL_TESTS",
            "HISTORICAL_EMPIRICAL_VALIDATION",
            "HOST_ENFORCED_SEALED_GATE",
        ],
        "model": controls.model,
        "selected_snapshot": snapshot.to_record(),
        "controls": controls.to_record(),
        "folds": summaries,
        "uncertainty_of_mean_absolute_error": uncertainty,
        "multiple_testing": {
            "status": "INCONCLUSIVE",
            "reason": "No preregistered calibrated per-trial test statistics; no adjusted p-values",
            "adjusted_p_values": None,
        },
        "source_support_exclusion_count": len(excluded),
        "limitations": [
            "Synthetic software output only; no empirical validation or promotion",
            "Prediction error and declared cost hurdles are not simulated trading profit",
            "Every model/parameter choice is a new registered candidate",
            "Purge/embargo are exact recorded intervals; early expanding prefixes may have a larger gap than requested minimum bars",
            "Overlapping return horizons create dependence; fixed block bootstrap assumptions still need validation",
        ],
    }
    if len(canonicalize_json(report)) > MAX_REPORT:
        raise ResearchValidationError("VALIDATION_REPORT_LIMIT")
    return summary, report
