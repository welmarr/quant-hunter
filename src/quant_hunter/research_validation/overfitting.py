"""Anti-overfitting statistics for strategy selection.

* Probabilistic Sharpe ratio (PSR) and deflated Sharpe ratio (DSR):
  Bailey & López de Prado (2012, 2014). The DSR asks whether the best Sharpe
  ratio found is still significant once we account for how many trials were
  run, their dispersion, the sample length and the non-normality of returns.
* Probability of backtest overfitting (PBO) by combinatorially symmetric
  cross-validation (CSCV): Bailey, Borwein, López de Prado & Zhu (2017).

All Sharpe ratios here are per period (not annualised), as in the papers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from statistics import NormalDist
from typing import Final

EULER_GAMMA: Final = 0.5772156649015329
_N: Final = NormalDist()


class OverfittingError(ValueError):
    """Inputs cannot support the requested statistic."""


@dataclass(frozen=True, slots=True)
class Moments:
    n: int
    mean: float
    std: float
    skew: float
    kurtosis: float  # non-excess (normal = 3)

    @property
    def sharpe(self) -> float:
        return self.mean / self.std


def moments(returns: Sequence[float]) -> Moments:
    n = len(returns)
    if n < 3:
        raise OverfittingError("at least 3 observations are required")
    mean = math.fsum(returns) / n
    dev = [r - mean for r in returns]
    var = math.fsum(d * d for d in dev) / (n - 1)
    if var <= 0:
        raise OverfittingError("returns have zero variance")
    std = math.sqrt(var)
    m2 = math.fsum(d * d for d in dev) / n
    m3 = math.fsum(d**3 for d in dev) / n
    m4 = math.fsum(d**4 for d in dev) / n
    return Moments(n, mean, std, m3 / m2**1.5, m4 / m2**2)


def probabilistic_sharpe_ratio(
    sharpe: float, benchmark: float, n: int, skew: float, kurtosis: float
) -> float:
    """P(true Sharpe > benchmark) given an observed per-period Sharpe."""
    if n < 2:
        raise OverfittingError("n must be at least 2")
    denom = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if denom <= 0:
        raise OverfittingError("non-positive variance term; check the moments")
    return _N.cdf((sharpe - benchmark) * math.sqrt(n - 1) / math.sqrt(denom))


def expected_max_sharpe(n_trials: int, variance: float) -> float:
    """Expected maximum Sharpe of ``n_trials`` independent zero-skill trials
    whose Sharpe ratios have the given cross-sectional variance."""
    if n_trials < 1:
        raise OverfittingError("n_trials must be at least 1")
    if variance < 0:
        raise OverfittingError("variance must be non-negative")
    if n_trials == 1:
        return 0.0
    a = _N.inv_cdf(1.0 - 1.0 / n_trials)
    b = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(variance) * ((1.0 - EULER_GAMMA) * a + EULER_GAMMA * b)


@dataclass(frozen=True, slots=True)
class DeflatedSharpe:
    sharpe: float
    benchmark: float
    n_trials: int
    dsr: float
    psr_zero: float

    @property
    def passes(self) -> bool:
        return self.dsr >= 0.95


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    n_trials: int,
    trial_sharpe_variance: float,
) -> DeflatedSharpe:
    """DSR of the selected strategy's per-period returns.

    ``n_trials`` counts every variant tried (Hunter's ledger count);
    ``trial_sharpe_variance`` is the variance of the trials' per-period Sharpe
    ratios. A DSR of 0.95 or more is the usual bar.
    """
    m = moments(returns)
    sr_star = expected_max_sharpe(n_trials, trial_sharpe_variance)
    return DeflatedSharpe(
        sharpe=m.sharpe,
        benchmark=sr_star,
        n_trials=n_trials,
        dsr=probabilistic_sharpe_ratio(m.sharpe, sr_star, m.n, m.skew, m.kurtosis),
        psr_zero=probabilistic_sharpe_ratio(m.sharpe, 0.0, m.n, m.skew, m.kurtosis),
    )


@dataclass(frozen=True, slots=True)
class PBOResult:
    pbo: float
    n_splits: int
    logits: tuple[float, ...]
    is_best_oos_sharpe_mean: float
    degradation_slope: float


def _sharpe_from_sums(total: float, squares: float, n: int) -> float:
    mean = total / n
    var = (squares - n * mean * mean) / (n - 1)
    return mean / math.sqrt(var) if var > 0 else 0.0


def probability_of_backtest_overfitting(
    matrix: Sequence[Sequence[float]], *, partitions: int = 16
) -> PBOResult:
    """CSCV PBO. ``matrix[t][j]`` is strategy j's return in period t.

    The rows are cut into ``partitions`` contiguous blocks; every way of using
    half the blocks in-sample and the other half out-of-sample is evaluated.
    PBO is the share of splits where the in-sample winner ranks at or below the
    out-of-sample median.
    """
    if partitions < 2 or partitions % 2:
        raise OverfittingError("partitions must be an even number >= 2")
    t = len(matrix)
    if t < partitions * 2:
        raise OverfittingError("too few observations for the partitions")
    n_strat = len(matrix[0])
    if n_strat < 2 or any(len(row) != n_strat for row in matrix):
        raise OverfittingError("need a rectangular matrix with >= 2 strategies")
    size = t // partitions
    blocks = [range(i * size, (i + 1) * size) for i in range(partitions)]
    sums = [
        [math.fsum(matrix[r][j] for r in b) for j in range(n_strat)] for b in blocks
    ]
    sqs = [
        [math.fsum(matrix[r][j] ** 2 for r in b) for j in range(n_strat)]
        for b in blocks
    ]
    all_idx = frozenset(range(partitions))
    logits: list[float] = []
    is_sr: list[float] = []
    oos_sr: list[float] = []
    n_half = size * partitions // 2
    for chosen in combinations(range(partitions), partitions // 2):
        rest = all_idx.difference(chosen)
        ins = [
            _sharpe_from_sums(
                math.fsum(sums[b][j] for b in chosen),
                math.fsum(sqs[b][j] for b in chosen),
                n_half,
            )
            for j in range(n_strat)
        ]
        outs = [
            _sharpe_from_sums(
                math.fsum(sums[b][j] for b in rest),
                math.fsum(sqs[b][j] for b in rest),
                n_half,
            )
            for j in range(n_strat)
        ]
        best = max(range(n_strat), key=lambda j: ins[j])
        rank = 1.0 + sum(1 for v in outs if v < outs[best])
        rank += 0.5 * (sum(1 for v in outs if v == outs[best]) - 1)
        omega = rank / (n_strat + 1)
        logits.append(math.log(omega / (1 - omega)))
        is_sr.append(ins[best])
        oos_sr.append(outs[best])
    pbo = sum(1 for x in logits if x <= 0) / len(logits)
    mx = math.fsum(is_sr) / len(is_sr)
    my = math.fsum(oos_sr) / len(oos_sr)
    sxx = math.fsum((x - mx) ** 2 for x in is_sr)
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(is_sr, oos_sr, strict=True))
    slope = sxy / sxx if sxx > 0 else 0.0
    return PBOResult(pbo, len(logits), tuple(logits), my, slope)
