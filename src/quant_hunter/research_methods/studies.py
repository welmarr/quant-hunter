"""Synthetic fixtures and evaluation adapters; Item8 authority belongs to caller.

prepare_study only generates inputs. execute_study is the evaluation boundary
and must only be called by the governed runner after freezing/beginning a run.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from math import isfinite
from typing import cast

import numpy as np

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.config.canonical import (
    CanonicalJsonError,
    canonicalize_json,
    parse_json_document,
)

from . import (
    BookUpdate,
    MacroRelease,
    OOFPrediction,
    TimedRow,
    ValueRelease,
    ecm_forecast,
    fit_cointegration,
    fit_covariance_ensemble,
    fit_garch,
    fit_pca,
    fit_surprise_scale,
    fit_temporal_meta,
    forward_carry,
    fx_cross_section_momentum,
    garch_forecast,
    macro_surprise,
    meta_prediction,
    order_flow_imbalance,
    pca_residual,
    portfolio_net_return,
    time_series_momentum,
    value_momentum,
    variance_scores,
    volatility_managed_exposure,
)

EPOCH = datetime(2020, 1, 1, tzinfo=UTC)
MAX_BYTES = 2_000_000
FORMAT = "v0-synthetic-study-1"
SCENARIOS = ("POSITIVE", "NULL", "SENSITIVITY")
_OBSERVATION_KINDS = {
    "CRP-01": "SYNTHETIC_PRICE_LEVELS",
    "CRP-02": "SYNTHETIC_FX_EXCESS_RETURNS",
    "CRP-03": "UNUSED_TIMELINE_ANCHORS",
    "CRP-04": "SYNTHETIC_PRICE_LEVELS_ALIGNED_THREE_ASSETS",
    "CRP-05": "SYNTHETIC_LEVELS_Y_X",
    "CRP-06": "SYNTHETIC_FACTOR_INPUT_UNITS",
    "CRP-07": "SYNTHETIC_ZERO_MEAN_INNOVATIONS",
    "CRP-08": "SYNTHETIC_FACTOR_RETURNS",
    "CRP-09": "UNUSED_TIMELINE_ANCHORS",
    "CRP-10": "UNUSED_TIMELINE_ANCHORS",
    "ENS-COV": "SYNTHETIC_COMPONENT_RETURNS",
    "META-OOF": "UNUSED_TIMELINE_ANCHORS",
}


class StudyError(ValueError):
    """Bounded synthetic input/configuration is inconsistent."""


@dataclass(frozen=True)
class StudyDefinition:
    study_id: str
    title: str
    variant: str
    paper_url: str
    parameter_name: str
    parameter_default: float
    parameter_min: float
    parameter_max: float
    sensitivity_parameter: float
    implemented_scope: str
    null_behavior: str
    assumptions: tuple[str, ...]
    cost_model: str


_COMMON = (
    "SYNTHETIC mathematical/software evidence only; no empirical or profitability conclusion",
    "One requested variant is one Item8 attempt; no hidden fit/search/retry loop",
    "Fixed fixture seeds and train-only transformations; source inputs retained as exact canonical bytes",
)
_COST = "One later synthetic holding period; explicit one-way turnover cost; no liquidity/borrow/margin realism claim"
_NONE = "No implemented trading rule; costs and investment P&L are not applicable to this mathematical diagnostic"
_DEFINITIONS = (
    StudyDefinition(
        "CRP-01",
        "Time-series momentum",
        "price-sign-rolling-sample-vol-v1",
        "https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2019/09/TimeSeriesMomentum.pdf",
        "target_volatility",
        0.1,
        0.01,
        0.5,
        0.2,
        "Causal signal and one-period synthetic portfolio",
        "Flat prices yield ZERO_VOLATILITY and zero position",
        (
            *_COMMON,
            "Rolling sample SD replaces original volatility estimator; price returns are not futures excess returns",
        ),
        _COST,
    ),
    StudyDefinition(
        "CRP-02",
        "Currency momentum",
        "dated-fx-excess-return-rank-scaled-demo-v1",
        "https://www.bis.org/publications/working-paper-366-currency-momentum-strategies.pdf",
        "gross_exposure",
        1,
        0.25,
        2,
        2,
        "Causal cross-sectional ranks and one-period synthetic portfolio",
        "Equal currency returns give zero centered ranks",
        (
            *_COMMON,
            "Gross-one ranks scaled by explicit exposure; not original six sorted portfolios",
            "Input returns are declared synthetic FX excess returns including financing",
        ),
        _COST,
    ),
    StudyDefinition(
        "CRP-03",
        "Forward carry",
        "spot-normalized-forward-carry-v1",
        "https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2019/04/Carry.pdf",
        "forward_quote",
        1.2,
        0.5,
        2,
        1.3,
        "Carry formula and later synthetic forward settlement payoff",
        "Forward=spot eliminates carry; terminal spot also flat",
        (
            *_COMMON,
            "Domestic per foreign quote; capital normalized by spot; actual terminal spot supplied separately",
        ),
        _COST,
    ),
    StudyDefinition(
        "CRP-04",
        "Value and momentum",
        "pit-book-price-skip-momentum-scaled-demo-v1",
        "https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2019/09/ValueandMomentumEverywhere.pdf",
        "gross_exposure",
        1,
        0.25,
        2,
        2,
        "PIT fundamental ranks and later synthetic portfolio",
        "Equal prices/book values give zero centered ranks",
        (
            *_COMMON,
            "Paper gross-two versus core gross-one, plus explicit demo scale; fixed three-asset universe",
        ),
        _COST,
    ),
    StudyDefinition(
        "CRP-05",
        "Cointegration and error correction",
        "eg-intercept-fixed-adf-lag-ecm-v1",
        "https://users.ssc.wisc.edu/~bhansen/718/EngleGranger1987.pdf",
        "forecast_level_shift",
        0,
        -5,
        5,
        1,
        "Engle-Granger/ADF diagnostics and one next-step ECM forecast",
        "Stationary null fails I(1) eligibility; ECM evaluation raises MethodError",
        (
            *_COMMON,
            "Seed412 common-random-walk fixture; fixed one-lag diagnostics; no pair-search loop or trading thresholds",
        ),
        _NONE,
    ),
    StudyDefinition(
        "CRP-06",
        "PCA factor residual",
        "train-correlation-pca-residual-v1",
        "https://math.nyu.edu/faculty/avellane/AvellanedaLeeStatArb20090616.pdf",
        "query_amplitude",
        1,
        0.5,
        3,
        2,
        "Train-only factor projection and later residual",
        "Query in fitted rank-one span has zero residual",
        (
            *_COMMON,
            "Factor residual only; no OU fit, threshold, position or full strategy",
        ),
        _NONE,
    ),
    StudyDefinition(
        "CRP-07",
        "GARCH variance",
        "zero-mean-garch11-qmle-v1",
        "https://public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf",
        "innovation_scale",
        1,
        0.5,
        3,
        2,
        "Actual constrained QMLE fit and next variance score",
        "Zero innovations raise MethodError; no fabricated successful forecast",
        (
            *_COMMON,
            "Seed809 generator with three fixed volatility blocks; one optimizer run, no retry search",
        ),
        _NONE,
    ),
    StudyDefinition(
        "CRP-08",
        "Volatility-managed exposure",
        "lagged-realized-inverse-variance-capped-v1",
        "https://www.nber.org/system/files/working_papers/w22208/w22208.pdf",
        "variance_scale",
        0.0002,
        0.00005,
        0.001,
        0.0004,
        "Lagged inverse realized variance and later synthetic portfolio",
        "Zero realized variance raises MethodError",
        (
            *_COMMON,
            "Fixed ex-ante scale replaces original full-sample normalization; cap2",
        ),
        _COST,
    ),
    StudyDefinition(
        "CRP-09",
        "Macro surprise",
        "train-first-release-surprise-v1",
        "https://econ.duke.edu/~boller/Published_Papers/aer_03.pdf",
        "announcement_error",
        2,
        -10,
        10,
        4,
        "First-release surprise standardized by training errors",
        "Actual equals known consensus so standardized surprise is zero",
        (
            *_COMMON,
            "Synthetic survey MEDIAN identity bound; training SD is prospective adaptation; no strategy from surprise sign",
        ),
        _NONE,
    ),
    StudyDefinition(
        "CRP-10",
        "Order-flow imbalance",
        "sequenced-l1-ofi-v1",
        "https://arxiv.org/pdf/1011.6402",
        "queue_scale",
        1,
        0.5,
        3,
        2,
        "Actual sequenced-book OFI equation",
        "Unchanged book updates produce zero OFI",
        (
            *_COMMON,
            "Synthetic complete per-stream events; not FI2010, a price-impact fit or execution simulator",
        ),
        _NONE,
    ),
    StudyDefinition(
        "ENS-COV",
        "Covariance ensemble",
        "train-covariance-capped-demo-v1",
        "",
        "weight_cap",
        1,
        0.5,
        1,
        0.6,
        "Train-only minimum variance weights and later component comparison",
        "Equal correlated components remain allocated; zero later returns reveal cost drag",
        (
            *_COMMON,
            "Comparison baseline outside ten CRP paper domains; fixed ridge1e-6",
        ),
        _COST,
    ),
    StudyDefinition(
        "META-OOF",
        "Temporal OOF ridge",
        "temporal-oof-ridge-demo-v1",
        "",
        "ridge",
        1,
        0.1,
        10,
        10,
        "Ridge on declared synthetic temporal OOF inputs, later error comparison",
        "Zero training targets give zero meta forecast",
        (
            *_COMMON,
            "OOF input predictions are synthetic fixture values, not evidence of actual governed upstream fold training",
        ),
        _NONE,
    ),
)


def list_studies() -> tuple[StudyDefinition, ...]:
    return _DEFINITIONS


def _definition(study_id: str) -> StudyDefinition:
    for definition in _DEFINITIONS:
        if definition.study_id == study_id:
            return definition
    raise StudyError("unknown study domain")


def _stamp(day: int, *, hours: int = 0) -> str:
    return (EPOCH + timedelta(days=day, hours=hours)).isoformat().replace("+00:00", "Z")


def _time(value: JsonValue) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 32:
        raise StudyError("explicit UTC Z timestamp required")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise StudyError("invalid UTC timestamp") from None
    if result.tzinfo is not UTC:
        raise StudyError("UTC timestamp required")
    return result


def _record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise StudyError("object required")
    return value


def _list(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list) or len(value) > 4096:
        raise StudyError("bounded array required")
    return value


def _number(value: JsonValue) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or abs(value) > 1e12
    ):
        raise StudyError("finite bounded number required")
    return float(value)


def _vector(value: JsonValue) -> tuple[float, ...]:
    result = tuple(_number(item) for item in _list(value))
    if not 1 <= len(result) <= 64:
        raise StudyError("bounded nonempty vector required")
    return result


def _unread_vector(value: JsonValue) -> tuple[float, ...]:
    """Preserve future numeric payloads for the core's availability-first checks."""
    values = _list(value)
    if not 1 <= len(values) <= 64:
        raise StudyError("bounded nonempty vector required")
    return cast(tuple[float, ...], tuple(values))


def _string(value: JsonValue) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 100
        or not value.isprintable()
    ):
        raise StudyError("bounded identity required")
    return value


def _rows(values: list[list[float]]) -> list[JsonValue]:
    return [
        {"at": _stamp(i), "available_at": _stamp(i), "values": cast(JsonValue, row)}
        for i, row in enumerate(values)
    ]


def _release(index: int, error: float) -> JsonRecord:
    return {
        "indicator": "SYNTHETIC_CPI",
        "unit": "PERCENT",
        "period_end": _stamp(index - 2),
        "published_at": _stamp(index),
        "available_at": _stamp(index),
        "actual": 1 + error,
        "consensus": 1,
        "consensus_at": _stamp(index - 1),
        "first_release": True,
        "consensus_source": "SYNTHETIC_SURVEY",
        "consensus_statistic": "MEDIAN",
    }


def _timestamps(value: JsonValue, *, depth: int = 0) -> list[datetime]:
    if depth > 12:
        raise StudyError("document nesting limit")
    if isinstance(value, dict):
        found: list[datetime] = []
        for key, item in value.items():
            if key in {
                "at",
                "start",
                "end",
                "period_end",
                "label_end",
                "base_training_end",
                "maturity",
            } or key.endswith("_at"):
                found.append(_time(item))
            else:
                found.extend(_timestamps(item, depth=depth + 1))
        return found
    if isinstance(value, list):
        return [
            stamp
            for item in _list(value)
            for stamp in _timestamps(item, depth=depth + 1)
        ]
    return []


def prepare_study(
    study_id: str, scenario: str = "POSITIVE", parameter: float | None = None
) -> tuple[JsonRecord, bytes]:
    """Generate one deterministic input fixture; never fit or evaluate a model."""
    definition = _definition(study_id)
    if scenario not in SCENARIOS:
        raise StudyError("unknown scenario")
    p = _number(
        parameter
        if parameter is not None
        else definition.sensitivity_parameter
        if scenario == "SENSITIVITY"
        else definition.parameter_default
    )
    if not definition.parameter_min <= p <= definition.parameter_max:
        raise StudyError("parameter outside declared study bounds")
    null = scenario == "NULL"
    values: list[list[float]] = [[0.0]] * 4
    inputs: JsonRecord = {}
    target_values: list[float] = [0.01]
    kind = "SIMPLE_RETURNS"
    if study_id == "CRP-01":
        values = [
            [100],
            [100 if null else 110],
            [100 if null else 99],
            [100 if null else 108.9],
        ]
    elif study_id == "CRP-02":
        values = [[0, 0, 0] if null else [0.1, 0, -0.1] for _ in range(4)]
        target_values = [0.02, 0, -0.01]
    elif study_id == "CRP-03":
        inputs = {
            "spot": 1.25,
            "forward": 1.25 if null else p,
            "quoted_at": _stamp(3),
            "available_at": _stamp(3),
            "maturity": _stamp(187),
            "quote_convention": "DOMESTIC_PER_FOREIGN",
        }
        target_values = [1.25 if null else 1.27]
        kind = "TERMINAL_SPOT_DOMESTIC_PER_FOREIGN"
    elif study_id == "CRP-04":
        values = [
            [10, 10, 10],
            [10, 10, 10] if null else [11, 10, 9],
            [10, 10, 10] if null else [12, 10, 8],
        ]
        inputs["fundamentals"] = [
            {
                "asset": i,
                "period_end": _stamp(-2),
                "published_at": _stamp(-1),
                "available_at": _stamp(-1),
                "book_value_per_share": value,
            }
            for i, value in enumerate([10, 10, 10] if null else [24, 10, 4])
        ]
        target_values = [0.02, 0, -0.01]
    elif study_id == "CRP-05":
        rng = np.random.default_rng(801 if null else 412)
        if null:
            values = cast(list[list[float]], rng.normal(size=(100, 2)).tolist())
        else:
            x = np.cumsum(rng.normal(size=300))
            errors = rng.normal(scale=0.3, size=300)
            for i in range(1, 300):
                errors[i] += 0.35 * errors[i - 1]
            values = [
                [float(3 + 1.5 * a + b), float(a)]
                for a, b in zip(x, errors, strict=True)
            ]
        inputs = {
            "query": {
                "at": _stamp(len(values)),
                "available_at": _stamp(len(values)),
                "values": [values[-1][0] + 1 + p, values[-1][1] + 0.5],
            },
            "previous": {
                "at": _stamp(len(values) - 1),
                "available_at": _stamp(len(values) - 1),
                "values": cast(JsonValue, list(values[-1])),
            },
        }
        target_values, kind = [0.5], "DELTA_Y"
    elif study_id == "CRP-06":
        values = [[-2, -4], [-1, -2], [1, 2], [2, 4]]
        inputs["query"] = {
            "at": _stamp(4),
            "available_at": _stamp(4),
            "values": [3 * p, 6 * p] if null else [p, -2 * p],
        }
        target_values, kind = [0], "UNUSED_DIAGNOSTIC_TARGET"
    elif study_id == "CRP-07":
        rng = np.random.default_rng(809)
        values = [
            [0.0] if null else [float(x * p)]
            for x in rng.normal(size=150) * np.repeat([0.01, 0.03, 0.01], 50)
        ]
        target_values, kind = [0.0004 * p * p], "LATER_REALIZED_VARIANCE_PROXY"
    elif study_id == "CRP-08":
        values = [[0], [0]] if null else [[-0.01], [0.01]]
    elif study_id == "CRP-09":
        values = [[0.0]] * 3
        inputs = {
            "releases": [_release(0, -1), _release(1, 0), _release(2, 1)],
            "query_release": _release(3, 0 if null else p),
        }
        target_values, kind = [0], "UNUSED_DIAGNOSTIC_TARGET"
    elif study_id == "CRP-10":
        raw_book = (
            [(100, 10, 103, 20)] * 4
            if null
            else [
                (100, 10, 103, 20),
                (100, 15, 103, 18),
                (101, 7, 103, 18),
                (101, 7, 102, 12),
            ]
        )
        inputs["book"] = [
            {
                "sequence": i,
                "at": _stamp(i),
                "available_at": _stamp(i),
                "bid": bid,
                "bid_size": bid_size * p,
                "ask": ask,
                "ask_size": ask_size * p,
            }
            for i, (bid, bid_size, ask, ask_size) in enumerate(raw_book)
        ]
        target_values, kind = [0], "UNUSED_DIAGNOSTIC_TARGET"
    elif study_id == "ENS-COV":
        values = (
            [[0.01, 0.01], [0.01, 0.01], [-0.01, -0.01], [-0.01, -0.01]]
            if null
            else [[0.01, 0.02], [0.01, -0.02], [-0.01, 0.02], [-0.01, -0.02]]
        )
        target_values = [0, 0] if null else [0.01, 0.02]
    elif study_id == "META-OOF":
        inputs["oof"] = [
            {
                "at": _stamp(i),
                "label_end": _stamp(i, hours=1),
                "label_available_at": _stamp(i, hours=2),
                "base_training_end": _stamp(i - 1),
                "predictions": [float(i)],
                "target": 0 if null else float(2 * i),
            }
            for i in range(4)
        ]
        inputs["query"] = {"at": _stamp(4), "available_at": _stamp(4), "values": [4.0]}
        target_values, kind = [0 if null else 8], "SYNTHETIC_REGRESSION_TARGET"
    last = len(values) - 1
    train_end = _stamp(last, hours=3) if study_id == "META-OOF" else _stamp(last)
    decision_at = _stamp(last + 1)
    target_start = _stamp(last + 2)
    target_end = _stamp(187) if study_id == "CRP-03" else _stamp(last + 4)
    if study_id in {"CRP-05", "CRP-07", "META-OOF"}:
        if study_id == "CRP-07":
            decision_at = (
                (_time(train_end) + timedelta(microseconds=1))
                .isoformat()
                .replace("+00:00", "Z")
            )
        target_start = (
            (_time(decision_at) + timedelta(microseconds=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        target_end = (
            _stamp(last + 1, hours=1)
            if study_id == "META-OOF"
            else _stamp(last + 1)
            if study_id == "CRP-07"
            else _stamp(last + 2)
        )
    target_available = (
        _stamp(last + 1, hours=2) if study_id == "META-OOF" else target_end
    )
    target: JsonRecord = {
        "kind": kind,
        "start": target_start,
        "end": target_end,
        "at": target_end,
        "available_at": target_available,
        "values": cast(JsonValue, target_values),
    }
    payload: JsonRecord = {
        "format_version": FORMAT,
        "study_id": study_id,
        "variant": definition.variant,
        "scenario": scenario,
        "parameter": p,
        "observation_kind": _OBSERVATION_KINDS[study_id],
        "observations": _rows(values),
        "inputs": inputs,
        "target": target,
    }
    times = _timestamps(payload)
    config: JsonRecord = {
        "kind": "CRP_STUDY",
        "format_version": FORMAT,
        "study_id": study_id,
        "variant": definition.variant,
        "scenario": scenario,
        "parameter_name": definition.parameter_name,
        "parameter": p,
        "evidence_mode": "SYNTHETIC",
        "purpose": "MATHEMATICAL_DEMONSTRATION",
        "random_seed": 801
        if study_id == "CRP-05" and scenario == "NULL"
        else 412
        if study_id == "CRP-05"
        else 809
        if study_id == "CRP-07"
        else 0,
        "observation_interval_seconds": 86400
        if study_id in {"CRP-05", "CRP-07"}
        else None,
        "dataset_start": min(times).isoformat().replace("+00:00", "Z"),
        "dataset_end": (max(times) + timedelta(microseconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "training_start": min(times).isoformat().replace("+00:00", "Z"),
        "train_end": train_end,
        "training_end_exclusive": (_time(train_end) + timedelta(microseconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "decision_at": decision_at,
        "target_start": target["start"],
        "target_end": target["end"],
        "target_available_at": target["available_at"],
        "cost_per_unit_turnover": 0.001,
    }
    return config, canonicalize_json(payload)


def _timed(value: JsonValue) -> TimedRow:
    row = _record(value)
    return TimedRow(
        _time(row["at"]), _time(row["available_at"]), _unread_vector(row["values"])
    )


def _macro(value: JsonValue) -> MacroRelease:
    row = _record(value)
    if type(row["first_release"]) is not bool:
        raise StudyError("explicit first-release flag required")
    return MacroRelease(
        _string(row["indicator"]),
        _string(row["unit"]),
        _time(row["period_end"]),
        _time(row["published_at"]),
        _time(row["available_at"]),
        cast(float, row["actual"]),
        cast(float, row["consensus"]),
        _time(row["consensus_at"]),
        row["first_release"],
        _string(row["consensus_source"]),
        _string(row["consensus_statistic"]),
    )


def _json(value: object) -> JsonValue:
    if is_dataclass(value) and not isinstance(value, type):
        return _json(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise StudyError("unsupported result value")


def _query(value: JsonValue, decision: datetime) -> tuple[float, ...]:
    row = _timed(value)
    if not row.at <= row.available_at <= decision:
        raise StudyError("forecast input is not available at decision")
    return row.values


def _portfolio(
    weights: tuple[float, ...], returns: tuple[float, ...], cost: float
) -> JsonRecord:
    zero = tuple(0.0 for _ in weights)
    net, turnover = portfolio_net_return(
        weights, zero, returns, cost_per_unit_turnover=cost
    )
    gross, _ = portfolio_net_return(weights, zero, returns, cost_per_unit_turnover=0)
    return {
        "scope": "ONE_LATER_SYNTHETIC_PERIOD_FROM_CASH",
        "weights": _json(weights),
        "gross_return": gross,
        "turnover_l1": turnover,
        "cost_return": cost * turnover,
        "net_return": net,
        "initial_wealth_index": 1.0,
        "final_wealth_index": 1 + net,
        "numeric_precision": "FLOAT64",
        "closing_trade_assumed": False,
    }


def execute_study(payload_bytes: bytes, config: JsonRecord) -> JsonRecord:
    """Evaluate exactly one frozen variant. Caller must already have begun Item8."""
    try:
        return _execute(payload_bytes, config)
    except (KeyError, TypeError, CanonicalJsonError, RecursionError) as error:
        raise StudyError("malformed synthetic study input") from error


def _execute(payload_bytes: bytes, config: JsonRecord) -> JsonRecord:
    if not isinstance(payload_bytes, bytes) or not 0 < len(payload_bytes) <= MAX_BYTES:
        raise StudyError("bounded exact dataset bytes required")
    payload = _record(parse_json_document(payload_bytes))
    if canonicalize_json(payload) != payload_bytes:
        raise StudyError("dataset must use exact canonical JSON representation")
    study_id = _string(config["study_id"])
    definition = _definition(study_id)
    if (
        config.get("kind") != "CRP_STUDY"
        or config.get("evidence_mode") != "SYNTHETIC"
        or config.get("purpose") != "MATHEMATICAL_DEMONSTRATION"
        or config.get("format_version") != FORMAT
        or payload.get("format_version") != FORMAT
    ):
        raise StudyError("synthetic study authority/format mismatch")
    for name in ("study_id", "variant", "scenario", "parameter"):
        if config.get(name) != payload.get(name):
            raise StudyError("configuration/dataset binding mismatch")
    if (
        config["variant"] != definition.variant
        or config["parameter_name"] != definition.parameter_name
        or config["scenario"] not in SCENARIOS
    ):
        raise StudyError("study definition mismatch")
    p, cost = _number(config["parameter"]), _number(config["cost_per_unit_turnover"])
    expected_seed = (
        801
        if study_id == "CRP-05" and config["scenario"] == "NULL"
        else 412
        if study_id == "CRP-05"
        else 809
        if study_id == "CRP-07"
        else 0
    )
    if (
        type(config.get("random_seed")) is not int
        or config["random_seed"] != expected_seed
    ):
        raise StudyError("fixed generator random_seed mismatch")
    cadence = 86400 if study_id in {"CRP-05", "CRP-07"} else None
    if config.get("observation_interval_seconds") != cadence:
        raise StudyError("fixed observation cadence mismatch")
    if (
        not definition.parameter_min <= p <= definition.parameter_max
        or not 0 <= cost <= 0.1
    ):
        raise StudyError("parameter or cost outside declared bounds")
    start, end = _time(config["dataset_start"]), _time(config["dataset_end"])
    train_end, decision = _time(config["train_end"]), _time(config["decision_at"])
    if (
        not start <= train_end < decision
        or _time(config["training_start"]) != start
        or _time(config["training_end_exclusive"])
        != train_end + timedelta(microseconds=1)
    ):
        raise StudyError("invalid explicit training interval")
    timestamps = _timestamps(payload)
    if (
        not timestamps
        or min(timestamps) != start
        or max(timestamps) + timedelta(microseconds=1) != end
    ):
        raise StudyError("dataset bounds disagree with actual input timestamps")
    target = _record(payload["target"])
    target_start, target_end = _time(target["start"]), _time(target["end"])
    target_available = _time(target["available_at"])
    if (
        not decision < target_start < target_end <= target_available < end
        or _time(target["at"]) != target_end
    ):
        raise StudyError("target horizon/availability not strictly after decision")
    if any(
        config[key] != target[field]
        for key, field in (
            ("target_start", "start"),
            ("target_end", "end"),
            ("target_available_at", "available_at"),
        )
    ):
        raise StudyError("target/configuration binding mismatch")
    rows = [_timed(value) for value in _list(payload["observations"])]
    if cadence is not None:
        usable = [row for row in rows if row.at <= row.available_at <= train_end]
        if not usable or usable[-1].at != train_end:
            raise StudyError("daily forecast requires usable observation at train_end")
        if any(
            right.at - left.at != timedelta(seconds=cadence)
            for left, right in pairwise(usable)
        ):
            raise StudyError("usable training observations require fixed daily cadence")
    expected_columns = (
        3
        if study_id in {"CRP-02", "CRP-04"}
        else 2
        if study_id in {"CRP-05", "CRP-06", "ENS-COV"}
        else 1
    )
    if (
        payload["observation_kind"] != _OBSERVATION_KINDS[study_id]
        or not rows
        or any(len(row.values) != expected_columns for row in rows)
    ):
        raise StudyError("observation units/column contract mismatch")
    inputs = _record(payload["inputs"])
    # Target numbers are read only during evaluation, never in prepare or fitting.
    target_values = _vector(target["values"])
    expected_target_columns = (
        3 if study_id in {"CRP-02", "CRP-04"} else 2 if study_id == "ENS-COV" else 1
    )
    if len(target_values) != expected_target_columns:
        raise StudyError("target dimension mismatch")
    expected_target = {
        "CRP-03": "TERMINAL_SPOT_DOMESTIC_PER_FOREIGN",
        "CRP-05": "DELTA_Y",
        "CRP-06": "UNUSED_DIAGNOSTIC_TARGET",
        "CRP-07": "LATER_REALIZED_VARIANCE_PROXY",
        "CRP-09": "UNUSED_DIAGNOSTIC_TARGET",
        "CRP-10": "UNUSED_DIAGNOSTIC_TARGET",
        "META-OOF": "SYNTHETIC_REGRESSION_TARGET",
    }.get(study_id, "SIMPLE_RETURNS")
    if target["kind"] != expected_target:
        raise StudyError("target units/kind mismatch")
    metrics: JsonRecord = {}
    signal: JsonValue = None
    model: JsonValue = None
    accounting: JsonValue = None
    comparison: JsonValue = None
    if study_id == "CRP-01":
        momentum = time_series_momentum(
            rows,
            as_of=decision,
            lookback=3,
            volatility_window=3,
            periods_per_year=12,
            target_volatility=p,
            exposure_cap=2,
        )
        signal = _json(momentum)
        accounting = _portfolio((momentum.exposure,), target_values, cost)
        metrics = {
            "exposure": momentum.exposure,
            "annualized_volatility": momentum.annualized_volatility,
        }
    elif study_id == "CRP-02":
        weights = tuple(
            p * value
            for value in fx_cross_section_momentum(rows, as_of=decision, lookback=2)
        )
        signal, accounting = _json(weights), _portfolio(weights, target_values, cost)
        metrics = {"gross_exposure": sum(abs(w) for w in weights)}
    elif study_id == "CRP-03":
        spot, forward = _number(inputs["spot"]), _number(inputs["forward"])
        maturity = _time(inputs["maturity"])
        if maturity != target_end or len(target_values) != 1 or target_values[0] <= 0:
            raise StudyError("forward terminal target contract mismatch")
        carry = forward_carry(
            spot,
            forward,
            quoted_at=_time(inputs["quoted_at"]),
            available_at=_time(inputs["available_at"]),
            as_of=decision,
            maturity=maturity,
            quote=_string(inputs["quote_convention"]),
        )
        payoff = (target_values[0] - forward) / spot
        signal, accounting = _json(carry), _portfolio((1,), (payoff,), cost)
        metrics = {
            "horizon_carry": carry.horizon_carry,
            "realized_synthetic_forward_return": payoff,
        }
    elif study_id == "CRP-04":
        fundamentals = []
        for value in _list(inputs["fundamentals"]):
            row = _record(value)
            if type(row["asset"]) is not int:
                raise StudyError("integer asset index required")
            fundamentals.append(
                ValueRelease(
                    row["asset"],
                    _time(row["period_end"]),
                    _time(row["published_at"]),
                    _time(row["available_at"]),
                    cast(float, row["book_value_per_share"]),
                )
            )
        weights = tuple(
            p * value
            for value in value_momentum(
                rows, fundamentals, as_of=decision, lookback=2, skip=0
            )
        )
        signal, accounting = _json(weights), _portfolio(weights, target_values, cost)
        metrics = {"gross_exposure": sum(abs(w) for w in weights)}
    elif study_id == "CRP-05":
        if _time(_record(inputs["previous"])["at"]) >= _time(
            _record(inputs["query"])["at"]
        ):
            raise StudyError("previous ECM levels must precede query levels")
        previous = _timed(inputs["previous"])
        visible_training = [row for row in rows if row.available_at <= train_end]
        if not visible_training or previous != visible_training[-1]:
            raise StudyError(
                "previous ECM levels must match the retained last training observation"
            )
        query_at = _time(_record(inputs["query"])["at"])
        if (
            query_at != decision
            or target_end - query_at != timedelta(days=1)
            or query_at - previous.at != timedelta(days=1)
        ):
            raise StudyError("ECM target must be the next observation delta")
        fitted = fit_cointegration(rows, train_end=train_end, adf_lags=1)
        forecast = ecm_forecast(
            fitted,
            _query(inputs["query"], decision),
            _query(inputs["previous"], decision),
            at=decision,
        )
        model, signal = _json(fitted), forecast
        metrics = {
            "forecast_delta_y": forecast,
            "squared_error": (forecast - target_values[0]) ** 2,
        }
    elif study_id == "CRP-06":
        fitted_pca = fit_pca(rows, train_end=train_end, components=1)
        residual = pca_residual(
            fitted_pca, _query(inputs["query"], decision), at=decision
        )
        model, signal = _json(fitted_pca), _json(residual)
        metrics = {"residual_sum_squares": sum(value * value for value in residual)}
    elif study_id == "CRP-07":
        if decision != train_end + timedelta(
            microseconds=1
        ) or target_end - train_end != timedelta(days=1):
            raise StudyError("GARCH target must be the next innovation period")
        fitted_garch = fit_garch(rows, train_end=train_end)
        forecast = garch_forecast(fitted_garch, at=decision)
        scores = variance_scores((forecast,), target_values)
        model, signal = _json(fitted_garch), forecast
        metrics = {
            "next_variance": forecast,
            "one_observation_mse": scores[0],
            "one_observation_qlike": scores[1],
        }
    elif study_id == "CRP-08":
        exposure = volatility_managed_exposure(
            rows, as_of=decision, window=2, variance_scale=p, exposure_cap=2
        )
        signal, accounting = exposure, _portfolio((exposure,), target_values, cost)
        metrics = {"exposure": exposure}
    elif study_id == "CRP-09":
        fitted_scale = fit_surprise_scale(
            [_macro(value) for value in _list(inputs["releases"])], train_end=train_end
        )
        surprise = macro_surprise(
            fitted_scale, _macro(inputs["query_release"]), as_of=decision
        )
        model, signal = _json(fitted_scale), surprise
        metrics = {"standardized_surprise": surprise}
    elif study_id == "CRP-10":
        book = []
        for value in _list(inputs["book"]):
            row = _record(value)
            if type(row["sequence"]) is not int:
                raise StudyError("integer sequence required")
            book.append(
                BookUpdate(
                    row["sequence"],
                    _time(row["at"]),
                    _time(row["available_at"]),
                    cast(float, row["bid"]),
                    cast(float, row["bid_size"]),
                    cast(float, row["ask"]),
                    cast(float, row["ask_size"]),
                )
            )
        flow = order_flow_imbalance(book, as_of=decision)
        signal = _json(flow)
        metrics = {
            "order_flow_imbalance": flow.total,
            "queue_imbalance": flow.final_queue_imbalance,
        }
    elif study_id == "ENS-COV":
        fitted_ensemble = fit_covariance_ensemble(rows, train_end=train_end, cap=p)
        model, signal = _json(fitted_ensemble), _json(fitted_ensemble.weights)
        accounting = _portfolio(fitted_ensemble.weights, target_values, cost)
        comparison = [
            _portfolio(
                tuple(1.0 if i == j else 0.0 for i in range(len(target_values))),
                target_values,
                cost,
            )
            for j in range(len(target_values))
        ]
        metrics = {"maximum_weight": max(fitted_ensemble.weights)}
    elif study_id == "META-OOF":
        query_at = _time(_record(inputs["query"])["at"])
        if (
            query_at != decision
            or target_end - query_at != timedelta(hours=1)
            or target_available - target_end != timedelta(hours=1)
        ):
            raise StudyError(
                "meta target must preserve the training label horizon and receipt lag"
            )
        oof = []
        for value in _list(inputs["oof"]):
            row = _record(value)
            if _time(row["label_end"]) - _time(row["at"]) != timedelta(
                hours=1
            ) or _time(row["label_available_at"]) - _time(
                row["label_end"]
            ) != timedelta(hours=1):
                raise StudyError("OOF training label horizon or receipt lag mismatch")
            oof.append(
                OOFPrediction(
                    _time(row["at"]),
                    _time(row["label_end"]),
                    _time(row["label_available_at"]),
                    _time(row["base_training_end"]),
                    _unread_vector(row["predictions"]),
                    cast(float, row["target"]),
                )
            )
        fitted_meta = fit_temporal_meta(oof, train_end=train_end, ridge=p)
        query = _query(inputs["query"], decision)
        forecast = meta_prediction(fitted_meta, query, at=decision)
        model, signal = _json(fitted_meta), forecast
        metrics = {
            "forecast": forecast,
            "squared_error": (forecast - target_values[0]) ** 2,
        }
        comparison = {
            "base_prediction": query[0],
            "base_squared_error": (query[0] - target_values[0]) ** 2,
            "observations": 1,
        }
    result: JsonRecord = {
        "kind": "SYNTHETIC_STUDY_RESULT",
        "study_id": study_id,
        "variant": definition.variant,
        "scenario": config["scenario"],
        "evidence_mode": "SYNTHETIC",
        "assessment": "EMPIRICALLY_UNVALIDATED",
        "implemented_scope": definition.implemented_scope,
        "input_digest": "sha256:" + hashlib.sha256(payload_bytes).hexdigest(),
        "config_digest": "sha256:"
        + hashlib.sha256(canonicalize_json(config)).hexdigest(),
        "train_end": config["train_end"],
        "decision_at": config["decision_at"],
        "target_start": config["target_start"],
        "target_end": config["target_end"],
        "signals": signal,
        "fitted_model": model,
        "metrics": metrics,
        "accounting": accounting,
        "comparison": comparison,
        "limitations": [
            *list(definition.assumptions),
            definition.cost_model,
            "One synthetic future observation is not out-of-sample scientific validation or a performance estimate",
        ],
    }
    canonicalize_json(result)
    return result
