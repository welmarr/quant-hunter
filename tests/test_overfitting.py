from __future__ import annotations

import math
import random

import pytest

from quant_hunter.research_validation.overfitting import (
    OverfittingError,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    moments,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
)


def test_moments_of_normal_sample() -> None:
    rng = random.Random(1)
    m = moments([rng.gauss(0.001, 0.01) for _ in range(20000)])
    assert abs(m.skew) < 0.1
    assert abs(m.kurtosis - 3) < 0.2
    with pytest.raises(OverfittingError):
        moments([1.0, 2.0])
    with pytest.raises(OverfittingError):
        moments([1.0, 1.0, 1.0])


def test_psr_reference_value() -> None:
    # Bailey & Lopez de Prado (2012): SR 0.1/period, n=100, normal -> ~0.84
    psr = probabilistic_sharpe_ratio(0.1, 0.0, 100, 0.0, 3.0)
    assert psr == pytest.approx(0.8389, abs=0.002)
    assert probabilistic_sharpe_ratio(0.0, 0.0, 10, 0.0, 3.0) == pytest.approx(0.5)
    with pytest.raises(OverfittingError):
        probabilistic_sharpe_ratio(0.1, 0.0, 1, 0.0, 3.0)
    with pytest.raises(OverfittingError):
        probabilistic_sharpe_ratio(2.0, 0.0, 10, 5.0, 3.0)


def test_expected_max_sharpe_grows_with_trials() -> None:
    assert expected_max_sharpe(1, 0.01) == 0.0
    small = expected_max_sharpe(10, 0.01)
    large = expected_max_sharpe(1000, 0.01)
    assert 0 < small < large
    # Known approximation: E[max] of 1000 N(0,1) draws is about 3.25.
    assert expected_max_sharpe(1000, 1.0) == pytest.approx(3.25, abs=0.05)
    with pytest.raises(OverfittingError):
        expected_max_sharpe(0, 1.0)
    with pytest.raises(OverfittingError):
        expected_max_sharpe(5, -1.0)


def test_dsr_penalises_many_trials() -> None:
    rng = random.Random(7)
    returns = [rng.gauss(0.0008, 0.01) for _ in range(2520)]
    one = deflated_sharpe_ratio(returns, n_trials=1, trial_sharpe_variance=0.0)
    many = deflated_sharpe_ratio(returns, n_trials=500, trial_sharpe_variance=0.0004)
    assert one.dsr == pytest.approx(one.psr_zero)
    assert many.dsr < one.dsr
    assert many.benchmark > 0
    assert isinstance(many.passes, bool)


def _matrix(skill: float, n_strat: int, t: int, seed: int) -> list[list[float]]:
    rng = random.Random(seed)
    rows = []
    for _ in range(t):
        row = [rng.gauss(0.0, 0.01) for _ in range(n_strat)]
        row[0] += skill
        rows.append(row)
    return rows


def test_pbo_noise_is_near_half_and_skill_is_low() -> None:
    runs = [
        probability_of_backtest_overfitting(_matrix(0.0, 20, 400, s), partitions=8)
        for s in range(1, 7)
    ]
    assert runs[0].n_splits == math.comb(8, 4)
    average = sum(r.pbo for r in runs) / len(runs)
    assert 0.35 <= average <= 0.65
    skill = probability_of_backtest_overfitting(_matrix(0.004, 20, 800, 3), partitions=8)
    assert skill.pbo < 0.1
    assert skill.is_best_oos_sharpe_mean > 0
    assert len(skill.logits) == skill.n_splits


@pytest.mark.parametrize(
    ("matrix", "partitions"),
    [
        ([[0.0, 0.1]] * 40, 3),
        ([[0.0, 0.1]] * 10, 8),
        ([[0.0]] * 40, 4),
        ([[0.0, 0.1], [0.1]] * 20, 4),
    ],
)
def test_pbo_rejects_bad_inputs(matrix: list[list[float]], partitions: int) -> None:
    with pytest.raises(OverfittingError):
        probability_of_backtest_overfitting(matrix, partitions=partitions)


def test_pbo_handles_flat_strategies() -> None:
    flat = [[0.0, 0.0, 0.0] for _ in range(40)]
    result = probability_of_backtest_overfitting(flat, partitions=4)
    assert result.degradation_slope == 0.0
