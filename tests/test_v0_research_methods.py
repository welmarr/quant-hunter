"""Independent numerical and causal oracles; all vectors are SYNTHETIC."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import log, sqrt
from statistics import stdev
from types import SimpleNamespace

import numpy as np
import pytest

from quant_hunter.research_methods import (
    BookUpdate,
    MacroRelease,
    MethodError,
    OOFPrediction,
    TimedRow,
    ValueRelease,
    ecm_forecast,
    ensemble,
    ensemble_prediction,
    ewma_variances,
    fit_cointegration,
    fit_covariance_ensemble,
    fit_garch,
    fit_pca,
    fit_surprise_scale,
    fit_temporal_meta,
    forward_carry,
    fx_cross_section_momentum,
    garch_forecast,
    garch_variances,
    inverse_volatility_weights,
    macro_surprise,
    meta_prediction,
    order_flow_imbalance,
    pca_residual,
    portfolio_net_return,
    rolling_inverse_volatility,
    time_series_momentum,
    value_momentum,
    variance_scores,
    volatility,
    volatility_managed_exposure,
)
from quant_hunter.research_methods.common import (
    finite_result,
    history,
    integer,
    number,
    vector,
)

BASE = datetime(2020, 1, 1, tzinfo=UTC)


def day(index: int) -> datetime:
    return BASE + timedelta(days=index)


def rows(data: Sequence[Sequence[float]]) -> list[TimedRow]:
    return [TimedRow(day(i), day(i), tuple(row)) for i, row in enumerate(data)]


def test_crp01_independent_return_and_sample_volatility_oracle() -> None:
    data = rows([[100], [110], [99], [108.9]])
    result = time_series_momentum(
        data,
        as_of=day(3),
        lookback=3,
        volatility_window=3,
        periods_per_year=12,
        target_volatility=0.1,
    )
    oracle = stdev([0.1, -0.1, 0.1]) * sqrt(12)
    assert result.momentum == pytest.approx(0.089)
    assert result.annualized_volatility == pytest.approx(oracle)
    assert result.exposure == pytest.approx(0.1 / oracle)
    assert (
        time_series_momentum(
            rows([[10], [10], [10]]), as_of=day(2), lookback=2, volatility_window=2
        ).status
        == "ZERO_VOLATILITY"
    )
    negative = time_series_momentum(
        rows([[100], [80], [90]]),
        as_of=day(2),
        lookback=2,
        volatility_window=2,
        exposure_cap=0.01,
    )
    assert negative.exposure == -0.01
    assert (
        time_series_momentum(
            [*data, TimedRow(day(4), day(4), (100000000.0,))],
            as_of=day(3),
            lookback=3,
            volatility_window=3,
            periods_per_year=12,
            target_volatility=0.1,
        )
        == result
    )


@pytest.mark.parametrize("data", [[[0], [2], [3]], [[1, 2], [2, 3], [3, 4]]])
def test_crp01_rejects_invalid_prices(data: list[list[float]]) -> None:
    with pytest.raises(MethodError):
        time_series_momentum(rows(data), as_of=day(2), lookback=2, volatility_window=2)


def test_crp02_dated_cross_section_ties_null_and_perturbation() -> None:
    data = rows([[0.1, 0, -0.1], [0.1, 0, -0.1], [9, -0.9, 0.2]])
    assert fx_cross_section_momentum(data, as_of=day(1), lookback=2) == (0.5, 0, -0.5)
    assert fx_cross_section_momentum(
        rows([[0.1, 0.1, 0.1]]), as_of=day(0), lookback=1
    ) == (0, 0, 0)
    assert fx_cross_section_momentum(rows([[0, 0, 1]]), as_of=day(0), lookback=1) == (
        -0.25,
        -0.25,
        0.5,
    )
    assert fx_cross_section_momentum(data, as_of=day(2), lookback=1) != (0.5, 0, -0.5)
    with pytest.raises(MethodError, match="insufficient"):
        fx_cross_section_momentum(
            [
                replace(data[0], available_at=day(3)),
                replace(data[1], available_at=day(3)),
            ],
            as_of=day(1),
            lookback=2,
        )


@pytest.mark.parametrize("values", [[-1, 0], [11, 0], [0.1]])
def test_crp02_invalid_returns(values: list[float]) -> None:
    with pytest.raises(MethodError):
        fx_cross_section_momentum(rows([values]), as_of=day(0), lookback=1)


def test_crp02_compounding_bound() -> None:
    with pytest.raises(MethodError, match="overflow"):
        fx_cross_section_momentum(rows([[9, 0]] * 400), as_of=day(399), lookback=400)


def carry(forward: float, **changes: object) -> object:
    # Public test helper remains strictly typed through explicit calls below.
    assert not changes
    return forward_carry(
        1.25,
        forward,
        quoted_at=day(0),
        available_at=day(0),
        as_of=day(1),
        maturity=day(30),
    )


def test_crp03_payoff_orientation_not_forward_premium() -> None:
    result = forward_carry(
        1.25,
        1.20,
        quoted_at=day(0),
        available_at=day(0),
        as_of=day(1),
        maturity=day(30),
    )
    assert result.horizon_carry == pytest.approx(0.04)
    assert result.annualized_carry == pytest.approx(0.04 * 365.25 / 30)
    assert carry(1.25) != carry(1.20)
    assert (
        forward_carry(
            1.25,
            1.30,
            quoted_at=day(0),
            available_at=day(0),
            as_of=day(1),
            maturity=day(30),
        ).horizon_carry
        < 0
    )


@pytest.mark.parametrize(
    "available,asof,maturity,quote",
    [
        (day(3), day(1), day(30), "DOMESTIC_PER_FOREIGN"),
        (day(0), day(30), day(30), "DOMESTIC_PER_FOREIGN"),
        (day(0), day(1), day(30), "FOREIGN_PER_DOMESTIC"),
    ],
)
def test_crp03_rejects_unknown_or_expired_quote(
    available: datetime, asof: datetime, maturity: datetime, quote: str
) -> None:
    with pytest.raises(MethodError):
        forward_carry(
            1,
            1,
            quoted_at=day(0),
            available_at=available,
            as_of=asof,
            maturity=maturity,
            quote=quote,
        )


def releases() -> list[ValueRelease]:
    return [
        ValueRelease(i, day(-4), day(-2), day(-1), value)
        for i, value in enumerate([40, 20, 10])
    ]


def test_crp04_rank_oracle_and_publication_time() -> None:
    prices = rows([[10, 10, 10], [11, 10, 9], [12, 10, 8], [15, 10, 5]])
    fundamentals = releases()
    assert value_momentum(prices, fundamentals, as_of=day(2), lookback=2, skip=0) == (
        0.5,
        0,
        -0.5,
    )
    future = ValueRelease(2, day(0), day(3), day(3), 1e6)
    assert value_momentum(
        prices, [*fundamentals, future], as_of=day(2), lookback=2, skip=0
    ) == (0.5, 0, -0.5)
    assert value_momentum(
        prices, [*fundamentals, future], as_of=day(3), lookback=2, skip=0
    ) != (0.5, 0, -0.5)
    null = rows([[10, 10, 10]] * 3)
    equal = [replace(r, book_value_per_share=10) for r in fundamentals]
    assert value_momentum(null, equal, as_of=day(2), lookback=1) == (0, 0, 0)
    delayed = [replace(r, available_at=day(4)) for r in fundamentals]
    with pytest.raises(MethodError, match="unavailable"):
        value_momentum(prices, delayed, as_of=day(2), lookback=1)


@pytest.mark.parametrize(
    "kind", ["duplicate", "reversed", "missing", "negative", "price"]
)
def test_crp04_hostile_fundamentals(kind: str) -> None:
    fundamentals, prices = releases(), rows([[10, 10, 10]] * 3)
    if kind == "duplicate":
        fundamentals.append(fundamentals[0])
    elif kind == "reversed":
        fundamentals[0] = replace(fundamentals[0], published_at=day(-5))
    elif kind == "missing":
        fundamentals.pop()
    elif kind == "negative":
        fundamentals[0] = replace(fundamentals[0], book_value_per_share=-1)
    else:
        prices[0] = replace(prices[0], values=(0, 1, 2))
    with pytest.raises(MethodError):
        value_momentum(prices, fundamentals, as_of=day(2), lookback=1)


def cointegrated() -> list[TimedRow]:
    rng = np.random.default_rng(412)
    x = np.cumsum(rng.normal(size=300))
    error = rng.normal(scale=0.3, size=300)
    for i in range(1, 300):
        error[i] += 0.35 * error[i - 1]
    return rows(
        [[float(3 + 1.5 * a + b), float(a)] for a, b in zip(x, error, strict=True)]
    )


def test_crp05_manual_ols_and_residual_adf_t_oracle() -> None:
    data = cointegrated()
    model = fit_cointegration(data, train_end=day(299))
    x = [row.values[1] for row in data]
    y = [row.values[0] for row in data]
    xmean, ymean = sum(x) / len(x), sum(y) / len(y)
    beta = sum((a - xmean) * (b - ymean) for a, b in zip(x, y, strict=True)) / sum(
        (a - xmean) ** 2 for a in x
    )
    intercept = ymean - beta * xmean
    assert model.hedge_ratio == pytest.approx(beta)
    assert model.intercept == pytest.approx(intercept)
    residual = np.array([b - intercept - beta * a for a, b in zip(x, y, strict=True)])
    delta = np.diff(residual)
    # Independent fixed-lag residual DF regression: no intercept after EG residuals.
    design = np.column_stack((residual[1:-1], delta[:-1]))
    inverse = np.linalg.inv(design.T @ design)
    coefficients = inverse @ design.T @ delta[1:]
    errors = delta[1:] - design @ coefficients
    standard_error = sqrt(float(errors @ errors) / (len(errors) - 2) * inverse[0, 0])
    assert model.statistic == pytest.approx(coefficients[0] / standard_error, rel=1e-9)
    assert model.eligible and model.pvalue < 0.01
    known, prior = (8.0, 3.0), (7.0, 2.5)
    features = (1, 8 - model.intercept - model.hedge_ratio * 3, 1, 0.5)
    assert ecm_forecast(model, known, prior, at=day(300)) == pytest.approx(
        sum(a * b for a, b in zip(features, model.ecm_coefficients, strict=True))
    )
    extended = [*data, TimedRow(day(300), day(300), (1000000000.0, -1000000000.0))]
    assert fit_cointegration(extended, train_end=day(299)) == model
    assert ecm_forecast(model, (10, 3), prior, at=day(300)) != ecm_forecast(
        model, known, prior, at=day(300)
    )


def test_crp05_stationary_null_and_forecast_rejection() -> None:
    rng = np.random.default_rng(801)
    data = rows(rng.normal(size=(100, 2)).tolist())
    model = fit_cointegration(data, train_end=day(99))
    assert not model.eligible
    with pytest.raises(MethodError, match="diagnostics"):
        ecm_forecast(model, (1, 2), (0, 1), at=day(100))
    good = fit_cointegration(cointegrated(), train_end=day(299))
    with pytest.raises(MethodError, match="two synchronized"):
        ecm_forecast(good, [1], [1], at=day(300))


@pytest.mark.parametrize(
    "data", [[[1, 1]] * 50, [[i, 2 * i] for i in range(50)], [[i] for i in range(50)]]
)
def test_crp05_degenerate_and_insufficient(data: list[list[float]]) -> None:
    with pytest.raises(MethodError):
        fit_cointegration(rows(data), train_end=day(49))


def test_crp05_significance_must_be_fixed_supported_level() -> None:
    with pytest.raises(MethodError):
        fit_cointegration(cointegrated(), train_end=day(299), significance=0.2)


def test_crp06_known_rank_one_projection_and_no_future_fit() -> None:
    data = rows([[-2, -4], [-1, -2], [1, 2], [2, 4]])
    model = fit_pca(data, train_end=day(3))
    assert model.explained_variance == pytest.approx((1,))
    assert pca_residual(model, (3, 6), at=day(4)) == pytest.approx((0, 0), abs=1e-14)
    assert pca_residual(model, (1, -2), at=day(4)) == pytest.approx((1, -2))
    assert (
        fit_pca([*data, TimedRow(day(4), day(4), (999, -444))], train_end=day(3))
        == model
    )
    with pytest.raises(MethodError, match="dimension"):
        pca_residual(model, (1,), at=day(4))
    with pytest.raises(MethodError, match="constant"):
        fit_pca(rows([[1, i] for i in range(4)]), train_end=day(3))


def test_crp07_scalar_recursion_and_score_oracles() -> None:
    assert ewma_variances([1, 2, 0], initial_variance=2, decay=0.5) == (
        2,
        1.5,
        2.75,
        1.375,
    )
    assert ewma_variances([0, 0], initial_variance=2, decay=0.5) == (2, 1, 0.5)
    assert garch_variances(
        [1, 2, 0], omega=0.1, alpha=0.2, beta=0.5, initial_variance=2
    ) == pytest.approx((2, 1.3, 1.55, 0.875))
    assert variance_scores([1, 2], [1, 4]) == pytest.approx((2, (3 + log(2)) / 2))
    assert variance_scores([1, 1], [1, 1])[0] == 0
    assert ewma_variances([1, 2, 99], initial_variance=2, decay=0.5)[:3] == (
        2,
        1.5,
        2.75,
    )


def volatility_rows() -> list[TimedRow]:
    rng = np.random.default_rng(809)
    return rows(
        [[float(x)] for x in rng.normal(size=150) * np.repeat([0.01, 0.03, 0.01], 50)]
    )


def test_crp07_fit_convergence_likelihood_and_scale_oracle() -> None:
    data = volatility_rows()
    fitted = fit_garch(data, train_end=day(149))
    assert fitted.converged and 0 < fitted.iterations <= 300
    assert fitted.omega > 0 and 0 <= fitted.alpha + fitted.beta < 1
    raw = [row.values[0] for row in data]
    h = sum(x * x for x in raw) / len(raw)
    log_likelihood = 0.0
    for x in raw:
        log_likelihood += 0.5 * (log(2 * np.pi * h) + x * x / h)
        h = fitted.omega + fitted.alpha * x * x + fitted.beta * h
    assert fitted.next_variance == pytest.approx(h)
    assert fitted.negative_log_likelihood == pytest.approx(log_likelihood)
    assert garch_forecast(fitted, at=day(150)) == pytest.approx(h)
    assert garch_forecast(fitted, at=day(150), horizon=2) == pytest.approx(
        fitted.omega + (fitted.alpha + fitted.beta) * h
    )
    scaled = fit_garch(
        [replace(row, values=(row.values[0] * 3,)) for row in data], train_end=day(149)
    )
    assert scaled.next_variance == pytest.approx(fitted.next_variance * 9, rel=1e-4)
    assert (
        fit_garch([*data, TimedRow(day(150), day(150), (99,))], train_end=day(149))
        == fitted
    )
    with pytest.raises(MethodError, match="converge"):
        garch_forecast(replace(fitted, converged=False), at=day(150))


def test_crp07_failed_optimizer_does_not_fabricate_forecast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        volatility, "minimize", lambda *a, **k: SimpleNamespace(success=False)
    )
    with pytest.raises(MethodError, match="GARCH_DID_NOT_CONVERGE"):
        fit_garch(volatility_rows(), train_end=day(149))


@pytest.mark.parametrize(
    "call",
    [
        lambda: ewma_variances([1], initial_variance=1, decay=1),
        lambda: garch_variances([1], omega=1, alpha=0.5, beta=0.5, initial_variance=1),
        lambda: fit_garch(rows([[0]] * 40), train_end=day(39)),
        lambda: fit_garch(rows([[1, 2]] * 40), train_end=day(39)),
        lambda: variance_scores([0], [1]),
        lambda: variance_scores([1], [-1]),
        lambda: variance_scores([1, 2], [1]),
    ],
)
def test_crp07_invalid_models_and_scores(call: Callable[[], object]) -> None:
    with pytest.raises(MethodError):
        call()


def test_crp08_waterfill_and_cost_accounting_oracle() -> None:
    assert inverse_volatility_weights([0.1, 0.2, 0.4]) == pytest.approx(
        (4 / 7, 2 / 7, 1 / 7)
    )
    assert inverse_volatility_weights([0.1, 0.2, 0.4], cap=0.5) == pytest.approx(
        (0.5, 1 / 3, 1 / 6)
    )
    assert inverse_volatility_weights([1, 1, 1]) == pytest.approx((1 / 3,) * 3)
    first, turnover = portfolio_net_return(
        [0.5, 0.5], [1, 0], [0.1, -0.02], cost_per_unit_turnover=0.001
    )
    double, _ = portfolio_net_return(
        [0.5, 0.5], [1, 0], [0.1, -0.02], cost_per_unit_turnover=0.002
    )
    assert (
        turnover == 1
        and first == pytest.approx(0.039)
        and double == pytest.approx(0.038)
    )
    assert portfolio_net_return(
        [0.5, 0.5], [0.5, 0.5], [0, 0], cost_per_unit_turnover=0.1
    ) == (0, 0)


@pytest.mark.parametrize(
    "call",
    [
        lambda: inverse_volatility_weights([0, 1]),
        lambda: inverse_volatility_weights([1, 2], cap=0.4),
        lambda: inverse_volatility_weights([1, 2], cap=2),
        lambda: portfolio_net_return([1], [1, 2], [0], cost_per_unit_turnover=0),
        lambda: portfolio_net_return([1], [1], [-2], cost_per_unit_turnover=0),
    ],
)
def test_crp08_invalid_risk_and_cost_inputs(call: Callable[[], object]) -> None:
    with pytest.raises(MethodError):
        call()


def macro(index: int, surprise: float) -> MacroRelease:
    return MacroRelease(
        "CPI",
        "PERCENT",
        day(index - 2),
        day(index),
        day(index),
        surprise + 1,
        1,
        day(index - 1),
        True,
        "SYNTHETIC_SURVEY",
        "MEDIAN",
    )


def test_crp09_independent_surprise_scale_and_delayed_publication() -> None:
    data = [macro(0, -1), macro(1, 0), macro(2, 1)]
    model = fit_surprise_scale(data, train_end=day(2))
    assert model.standard_deviation == 1
    assert macro_surprise(model, macro(3, 2), as_of=day(3)) == 2
    assert macro_surprise(model, macro(3, 0), as_of=day(3)) == 0
    assert fit_surprise_scale([*data, macro(3, 999)], train_end=day(2)) == model
    with pytest.raises(MethodError, match="unavailable"):
        macro_surprise(model, replace(macro(3, 2), available_at=day(4)), as_of=day(3))
    assert (
        macro_surprise(model, replace(macro(3, 2), available_at=day(4)), as_of=day(4))
        == 2
    )


@pytest.mark.parametrize(
    "kind", ["revised", "consensus", "late", "unit", "period", "name"]
)
def test_crp09_unknown_information_never_imputed(kind: str) -> None:
    model = fit_surprise_scale(
        [macro(0, -1), macro(1, 0), macro(2, 1)], train_end=day(2)
    )
    event = macro(3, 2)
    if kind == "revised":
        event = replace(event, first_release=False)
    elif kind == "consensus":
        event = replace(event, consensus=None)
    elif kind == "late":
        event = replace(event, consensus_at=day(3))
    elif kind == "unit":
        event = replace(event, unit="LEVEL")
    elif kind == "period":
        event = replace(event, period_end=day(4))
    else:
        event = replace(event, indicator="")
    with pytest.raises(MethodError):
        macro_surprise(model, event, as_of=day(3))


@pytest.mark.parametrize(
    "data",
    [
        [macro(0, 0), macro(1, 0), macro(2, 0)],
        [macro(0, 0), macro(0, 1), macro(2, 2)],
        [macro(0, 0), macro(1, 1), replace(macro(2, 2), unit="LEVEL")],
        [macro(4, 0), macro(5, 1), macro(6, 2)],
    ],
)
def test_crp09_training_nulls_and_missing_samples(data: list[MacroRelease]) -> None:
    with pytest.raises(MethodError):
        fit_surprise_scale(data, train_end=day(2))


@pytest.mark.parametrize("field", ["source", "statistic"])
def test_crp09_consensus_provenance_bound_to_training_scale(field: str) -> None:
    data = [macro(0, -1), macro(1, 0), macro(2, 1)]
    model = fit_surprise_scale(data, train_end=day(2))
    changed = (
        replace(macro(3, 2), consensus_source="DIFFERENT_SURVEY")
        if field == "source"
        else replace(macro(3, 2), consensus_statistic="MEAN")
    )
    with pytest.raises(MethodError, match="identities"):
        macro_surprise(model, changed, as_of=day(3))
    with pytest.raises(MethodError, match="identities"):
        fit_surprise_scale([*data, changed], train_end=day(3))
    # A consistently declared mean is a different, explicit generic variant.
    other = [
        replace(item, consensus_source="DIFFERENT_SURVEY", consensus_statistic="MEAN")
        for item in data
    ]
    variant = fit_surprise_scale(other, train_end=day(2))
    assert variant.consensus_statistic == "MEAN"
    assert variant.consensus_source == "DIFFERENT_SURVEY"
    assert variant.standard_deviation == model.standard_deviation


@pytest.mark.parametrize("kind", ["blank", "long", "control", "statistic", "naive"])
def test_crp09_invalid_provenance_and_timestamp_fail_safely(kind: str) -> None:
    data = [macro(0, -1), macro(1, 0), macro(2, 1)]
    if kind == "blank":
        data = [replace(item, consensus_source=" ") for item in data]
    elif kind == "long":
        data = [replace(item, consensus_source="x" * 81) for item in data]
    elif kind == "control":
        data = [replace(item, consensus_source="SURVEY\nOTHER") for item in data]
    elif kind == "statistic":
        data = [replace(item, consensus_statistic="UNKNOWN") for item in data]
    else:
        data.append(
            replace(macro(10, float("nan")), available_at=day(10).replace(tzinfo=None))
        )
    with pytest.raises(MethodError):
        fit_surprise_scale(data, train_end=day(2))


def test_crp09_unavailable_invalid_numbers_leave_training_unchanged() -> None:
    data = [macro(0, -1), macro(1, 0), macro(2, 1)]
    model = fit_surprise_scale(data, train_end=day(2))
    delayed = replace(
        macro(3, 0), available_at=day(10), actual=float("nan"), consensus=float("inf")
    )
    assert fit_surprise_scale([*data, delayed], train_end=day(5)) == replace(
        model, train_end=day(5)
    )
    with pytest.raises(MethodError):
        fit_surprise_scale([*data, delayed], train_end=day(10))


def books() -> list[BookUpdate]:
    return [
        BookUpdate(0, day(0), day(0), 100, 10, 103, 20),
        BookUpdate(1, day(1), day(1), 100, 15, 103, 18),
        BookUpdate(2, day(2), day(2), 101, 7, 103, 18),
        BookUpdate(3, day(3), day(3), 101, 7, 102, 12),
    ]


def test_crp10_event_oracle_and_causality() -> None:
    result = order_flow_imbalance(books(), as_of=day(3))
    assert result.event_contributions == (7, 7, -12)
    assert result.total == 2
    assert result.final_queue_imbalance == pytest.approx(-5 / 19)
    assert order_flow_imbalance(books(), as_of=day(1)).total == 7
    unchanged = [
        books()[0],
        replace(books()[0], sequence=1, at=day(1), available_at=day(1)),
    ]
    assert order_flow_imbalance(unchanged, as_of=day(1)).total == 0
    perturbed = books()
    perturbed[-1] = replace(perturbed[-1], ask_size=100)
    assert order_flow_imbalance(perturbed, as_of=day(1)) == order_flow_imbalance(
        books(), as_of=day(1)
    )
    assert order_flow_imbalance(perturbed, as_of=day(3)).total == -86


@pytest.mark.parametrize(
    "kind",
    [
        "gap",
        "duplicate",
        "crossed",
        "negative",
        "time",
        "availability",
        "future",
        "fi2010",
    ],
)
def test_crp10_rejects_non_event_or_incomplete_books(kind: str) -> None:
    data, data_kind, asof = books(), "SEQUENCED_BOOK_UPDATES", day(3)
    if kind == "gap":
        data.pop(1)
    elif kind == "duplicate":
        data[1] = replace(data[1], sequence=0)
    elif kind == "crossed":
        data[1] = replace(data[1], bid=104)
    elif kind == "negative":
        data[1] = replace(data[1], bid_size=-1)
    elif kind == "time":
        data[1] = replace(data[1], at=day(-1))
    elif kind == "availability":
        data[1] = replace(data[1], available_at=day(0))
    elif kind == "future":
        asof = day(0)
    else:
        data_kind = "FI2010"
    with pytest.raises(MethodError):
        order_flow_imbalance(data, as_of=asof, data_kind=data_kind)


def test_ensemble_covariance_closed_form_and_oof_ridge_oracle() -> None:
    data = rows([[1, 2], [1, -2], [-1, 2], [-1, -2]])
    model = fit_covariance_ensemble(data, train_end=day(3), ridge=1e-6)
    a, b = 4 / 3 + 1e-6, 16 / 3 + 1e-6
    assert model.weights == pytest.approx((b / (a + b), a / (a + b)), abs=1e-6)
    assert ensemble_prediction(model, (1, 0), at=day(4)) == pytest.approx(
        model.weights[0]
    )
    assert (
        max(fit_covariance_ensemble(data, train_end=day(3), cap=0.6).weights)
        <= 0.6 + 1e-10
    )
    predictions = [
        OOFPrediction(day(i), day(i), day(i), day(i - 1), (float(i),), float(2 * i))
        for i in range(4)
    ]
    meta = fit_temporal_meta(predictions, train_end=day(3), ridge=1)
    # Centered x SS=5, sample variance=5/3. Standardized ridge shrinks slope to 1.5.
    assert meta_prediction(meta, [4], at=day(4)) == pytest.approx(6.75)
    assert (
        fit_temporal_meta(
            [*predictions, OOFPrediction(day(4), day(4), day(4), day(3), (999,), -999)],
            train_end=day(3),
        )
        == meta
    )
    null = [replace(row, predictions=(0,), target=0) for row in predictions]
    assert (
        meta_prediction(fit_temporal_meta(null, train_end=day(3)), [1], at=day(4)) == 0
    )
    with pytest.raises(MethodError, match="in-sample"):
        fit_temporal_meta(
            [replace(row, base_training_end=row.at) for row in predictions],
            train_end=day(3),
        )
    with pytest.raises(MethodError, match="dimension"):
        meta_prediction(meta, [1, 2], at=day(4))
    with pytest.raises(MethodError, match="dimension"):
        ensemble_prediction(model, [1], at=day(4))


def test_ensemble_failed_optimizer_and_impossible_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = rows([[1, 2], [2, 1], [0, 0], [1, 1]])
    with pytest.raises(MethodError, match="infeasible"):
        fit_covariance_ensemble(data, train_end=day(3), cap=0.4)
    monkeypatch.setattr(
        ensemble, "minimize", lambda *a, **k: SimpleNamespace(success=False)
    )
    with pytest.raises(MethodError, match="failed"):
        fit_covariance_ensemble(data, train_end=day(3))


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), 1e13, 1e-200, True]
)
def test_numeric_hostility(value: float) -> None:
    with pytest.raises(MethodError):
        number(value)


@pytest.mark.parametrize(
    "kind",
    [
        "naive",
        "duplicate",
        "dimension",
        "available",
        "reordered",
        "empty",
        "wide",
        "too_many",
    ],
)
def test_common_timing_and_resource_bounds(kind: str) -> None:
    data = rows([[1], [2]])
    if kind == "naive":
        data[0] = replace(data[0], at=datetime(2020, 1, 1))
    elif kind == "duplicate":
        data[1] = data[0]
    elif kind == "dimension":
        data[1] = replace(data[1], values=(1, 2))
    elif kind == "available":
        data[1] = replace(data[1], available_at=day(0))
    elif kind == "reordered":
        data[0] = replace(data[0], available_at=day(3))
    elif kind == "empty":
        data = []
    elif kind == "wide":
        data = rows([[1] * 65] * 2)
    else:
        data = rows([[1]] * 4097)
    with pytest.raises(MethodError):
        history(data, day(2))


def test_common_insufficient_vector_integer_and_result() -> None:
    with pytest.raises(MethodError):
        vector([])
    with pytest.raises(MethodError):
        integer(True, 0, 2)
    with pytest.raises(MethodError):
        finite_result(np.array([float("inf")]))
    model = fit_pca(rows([[-2, -4], [-1, -2], [1, 2], [2, 4]]), train_end=day(3))
    with pytest.raises(MethodError, match="follow"):
        pca_residual(model, (1, 2), at=day(3))


def test_available_at_filters_training_not_just_event_timestamp() -> None:
    original = cointegrated()
    changed = [*original, TimedRow(day(300), day(400), (float("nan"), float("inf")))]
    assert fit_cointegration(changed, train_end=day(301)) == fit_cointegration(
        original, train_end=day(301)
    )
    with pytest.raises(MethodError, match="finite"):
        fit_cointegration(changed, train_end=day(400))
    prices = rows([[100], [110], [99]])
    extension = [*prices, TimedRow(day(3), day(5), (float("nan"),))]
    assert time_series_momentum(
        extension, as_of=day(4), lookback=2, volatility_window=2
    ) == time_series_momentum(prices, as_of=day(4), lookback=2, volatility_window=2)
    with pytest.raises(MethodError):
        time_series_momentum(extension, as_of=day(5), lookback=2, volatility_window=2)
    pca_data = rows([[-2, -4], [-1, -2], [1, 2], [2, 4]])
    delayed = [*pca_data, TimedRow(day(4), day(6), (float("nan"), 999))]
    assert fit_pca(delayed, train_end=day(5)) == fit_pca(pca_data, train_end=day(5))
    raw = volatility_rows()
    delayed_vol = [*raw, TimedRow(day(150), day(160), (float("nan"),))]
    assert fit_garch(delayed_vol, train_end=day(159)) == fit_garch(
        raw, train_end=day(159)
    )


def test_causal_rolling_allocation_oracle_and_null() -> None:
    data = rows([[-1, -2, -4], [0, 0, 0], [1, 2, 4], [999, -999, 99]])
    assert rolling_inverse_volatility(
        data, as_of=day(2), window=3, cap=0.5
    ) == pytest.approx((0.5, 1 / 3, 1 / 6))
    assert rolling_inverse_volatility(
        data, as_of=day(3), window=3, cap=0.5
    ) != rolling_inverse_volatility(data, as_of=day(2), window=3, cap=0.5)
    with pytest.raises(MethodError):
        rolling_inverse_volatility(rows([[0, 0]] * 3), as_of=day(2), window=3)


def test_cointegration_near_collinear_and_deterministic_trend_unknown() -> None:
    data = cointegrated()
    near = [
        replace(row, values=(row.values[1] * 1e6 + row.values[0], row.values[1]))
        for row in data
    ]
    with pytest.raises(MethodError, match="near-exact"):
        fit_cointegration(near, train_end=day(299))
    deterministic = rows([[float(i), float(i + (-1) ** i)] for i in range(50)])
    with pytest.raises(MethodError, match="first differences"):
        fit_cointegration(deterministic, train_end=day(49))


def test_fx_negative_log_return_ranking_does_not_underflow_to_false_tie() -> None:
    assert fx_cross_section_momentum(
        rows([[-0.5, -0.6]] * 1500), as_of=day(1499), lookback=1500
    ) == (0.5, -0.5)


def test_actual_garch_iteration_limit_is_not_success() -> None:
    with pytest.raises(MethodError, match="GARCH_DID_NOT_CONVERGE"):
        fit_garch(volatility_rows(), train_end=day(149), max_iterations=1)


def test_crp08_moreira_muir_inverse_variance_not_inverse_volatility() -> None:
    data = rows([[-0.01], [0.01], [-0.02], [0.02]])
    exposure = volatility_managed_exposure(
        data, as_of=day(1), window=2, variance_scale=0.0002, exposure_cap=2
    )
    increased_vol = volatility_managed_exposure(
        data, as_of=day(3), window=2, variance_scale=0.0002, exposure_cap=2
    )
    assert exposure == pytest.approx(1)
    # Doubling volatility quarters exposure, unlike the inverse-vol comparison.
    assert increased_vol == pytest.approx(0.25)
    assert (
        volatility_managed_exposure(
            data, as_of=day(1), window=2, variance_scale=0.0002, exposure_cap=0.6
        )
        == 0.6
    )
    positive, _ = portfolio_net_return(
        [exposure], [0], [0.01], cost_per_unit_turnover=0.001
    )
    assert positive == pytest.approx(0.009)
    delayed = [*data[:2], TimedRow(day(2), day(10), (float("nan"),))]
    assert (
        volatility_managed_exposure(
            delayed, as_of=day(3), window=2, variance_scale=0.0002, exposure_cap=2
        )
        == exposure
    )
    with pytest.raises(MethodError, match="unidentifiable"):
        volatility_managed_exposure(
            rows([[0], [0]]),
            as_of=day(1),
            window=2,
            variance_scale=0.001,
            exposure_cap=2,
        )
    with pytest.raises(MethodError, match="one lagged"):
        volatility_managed_exposure(
            rows([[1, 2], [2, 1]]),
            as_of=day(1),
            window=2,
            variance_scale=0.001,
            exposure_cap=2,
        )


def test_independent_random_walk_null_not_declared_cointegrated() -> None:
    rng = np.random.default_rng(501)
    independent = rows(np.cumsum(rng.normal(size=(300, 2)), axis=0).tolist())
    model = fit_cointegration(independent, train_end=day(299))
    assert model.pvalue > 0.05 and not model.eligible


def test_pca_tied_component_boundary_is_unknown_not_arbitrary_signal() -> None:
    with pytest.raises(MethodError, match="not identifiable"):
        fit_pca(rows([[1, 1], [1, -1], [-1, 1], [-1, -1]]), train_end=day(3))


def test_oversized_integer_fails_structurally() -> None:
    with pytest.raises(MethodError, match="finite"):
        number(10**1000)


def test_meta_label_end_is_not_label_availability() -> None:
    data = [
        OOFPrediction(day(i), day(i), day(i), day(i - 1), (float(i),), float(2 * i))
        for i in range(4)
    ]
    delayed = OOFPrediction(
        day(4), day(4), day(10), day(3), (float("inf"),), float("nan")
    )
    assert fit_temporal_meta([*data, delayed], train_end=day(5)) == fit_temporal_meta(
        data, train_end=day(5)
    )
    with pytest.raises(MethodError, match="finite"):
        fit_temporal_meta([*data, delayed], train_end=day(10))
    with pytest.raises(MethodError, match="horizon"):
        fit_temporal_meta(
            [*data, replace(delayed, label_available_at=day(3))], train_end=day(5)
        )
    visible = replace(delayed, predictions=(4,), target=20)
    assert (
        fit_temporal_meta([*data, visible], train_end=day(10)).coefficients
        != fit_temporal_meta(data, train_end=day(10)).coefficients
    )


def test_meta_ineffective_ridge_on_duplicate_columns_fails_closed() -> None:
    data = [
        OOFPrediction(
            day(i), day(i), day(i), day(i - 1), (float(i), float(i)), float(2 * i)
        )
        for i in range(4)
    ]
    with pytest.raises(MethodError, match="unidentifiable"):
        fit_temporal_meta(data, train_end=day(3), ridge=1e-100)
    regularized = fit_temporal_meta(data, train_end=day(3), ridge=1)
    assert regularized.coefficients[0] == pytest.approx(regularized.coefficients[1])
    assert meta_prediction(regularized, (4, 4), at=day(4)) == pytest.approx(51 / 7)
