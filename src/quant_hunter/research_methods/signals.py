"""CRP01--04: causal momentum, forward carry, and PIT value/momentum."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import sqrt

import numpy as np

from .common import (
    MAX_ROWS,
    MethodError,
    TimedRow,
    as_tuple,
    history,
    integer,
    number,
    ranks,
    utc,
)


@dataclass(frozen=True)
class MomentumSignal:
    momentum: float
    annualized_volatility: float
    exposure: float
    status: str


def time_series_momentum(
    prices: Sequence[TimedRow],
    *,
    as_of: datetime,
    lookback: int,
    volatility_window: int,
    periods_per_year: int = 252,
    target_volatility: float = 0.1,
    exposure_cap: float = 2.0,
) -> MomentumSignal:
    """Sign of past price return, scaled by lagged sample volatility."""
    integer(lookback, 1, MAX_ROWS - 1)
    integer(volatility_window, 2, MAX_ROWS - 1)
    integer(periods_per_year, 1, 1_000_000)
    target = number(target_volatility, positive=True)
    cap = number(exposure_cap, positive=True)
    data = history(prices, as_of, minimum=max(lookback, volatility_window) + 1)
    if data.shape[1] != 1 or bool((data <= 0).any()):
        raise MethodError("one positive price series required")
    levels = data[:, 0]
    momentum = float(levels[-1] / levels[-lookback - 1] - 1)
    returns = levels[-volatility_window:] / levels[-volatility_window - 1 : -1] - 1
    volatility = float(np.std(returns, ddof=1)) * sqrt(periods_per_year)
    if volatility <= 1e-12:
        return MomentumSignal(momentum, volatility, 0.0, "ZERO_VOLATILITY")
    return MomentumSignal(
        momentum,
        volatility,
        float(np.sign(momentum)) * min(cap, target / volatility),
        "COMPUTED",
    )


def fx_cross_section_momentum(
    excess_returns: Sequence[TimedRow],
    *,
    as_of: datetime,
    lookback: int,
) -> tuple[float, ...]:
    """Synchronized dated FX excess returns; centered cumulative-return ranks."""
    integer(lookback, 1, MAX_ROWS)
    data = history(excess_returns, as_of, minimum=lookback)[-lookback:]
    if data.shape[1] < 2 or bool((data <= -1).any()) or bool((data > 10).any()):
        raise MethodError("at least two currencies and bounded simple returns required")
    logs = np.log1p(data).sum(axis=0)
    if bool((logs > 700).any()):
        raise MethodError("return compounding overflow")
    # expm1 is monotone: rank log gross returns directly, avoiding underflow ties.
    return as_tuple(ranks(logs))


@dataclass(frozen=True)
class CarrySignal:
    horizon_carry: float
    annualized_carry: float
    tenor_years: float


def forward_carry(
    spot: float,
    forward: float,
    *,
    quoted_at: datetime,
    available_at: datetime,
    as_of: datetime,
    maturity: datetime,
    quote: str = "DOMESTIC_PER_FOREIGN",
) -> CarrySignal:
    """Long foreign forward payoff under unchanged spot, normalized by spot."""
    for date in (quoted_at, available_at, as_of, maturity):
        utc(date)
    if not quoted_at <= available_at <= as_of < maturity:
        raise MethodError("quote unavailable or forward expired")
    if quote != "DOMESTIC_PER_FOREIGN":
        raise MethodError(
            "explicit domestic currency per foreign currency quote required"
        )
    spot, forward = number(spot, positive=True), number(forward, positive=True)
    tenor = (maturity - quoted_at).total_seconds() / (365.25 * 86400)
    carry = (spot - forward) / spot
    return CarrySignal(carry, carry / tenor, tenor)


@dataclass(frozen=True)
class ValueRelease:
    asset: int
    period_end: datetime
    published_at: datetime
    available_at: datetime
    book_value_per_share: float


def value_momentum(
    prices: Sequence[TimedRow],
    releases: Sequence[ValueRelease],
    *,
    as_of: datetime,
    lookback: int,
    skip: int = 1,
) -> tuple[float, ...]:
    """50/50 centered book/price and skip-period momentum rank portfolios."""
    integer(lookback, 1, MAX_ROWS - 1)
    integer(skip, 0, MAX_ROWS - lookback - 1)
    data = history(prices, as_of, minimum=lookback + skip + 1)
    if data.shape[1] < 2 or bool((data <= 0).any()):
        raise MethodError("positive multi-asset price history required")
    integer(len(releases), 1, MAX_ROWS)
    chosen: dict[int, ValueRelease] = {}
    seen: set[tuple[int, datetime, datetime]] = set()
    for release in releases:
        integer(release.asset, 0, data.shape[1] - 1)
        for date in (release.period_end, release.published_at, release.available_at):
            utc(date)
        if not release.period_end <= release.published_at <= release.available_at:
            raise MethodError("fundamental release timing invalid")
        key = (release.asset, release.period_end, release.published_at)
        if key in seen:
            raise MethodError("ambiguous duplicate fundamental release")
        seen.add(key)
        if release.available_at <= as_of:
            number(release.book_value_per_share, positive=True)
            old = chosen.get(release.asset)
            if old is None or (release.period_end, release.published_at) > (
                old.period_end,
                old.published_at,
            ):
                chosen[release.asset] = release
    if len(chosen) != data.shape[1]:
        raise MethodError("point-in-time book value unavailable for an asset")
    value = np.array(
        [chosen[i].book_value_per_share for i in range(data.shape[1])], dtype=np.float64
    )
    value /= data[-1]
    momentum = data[-skip - 1] / data[-skip - lookback - 1] - 1
    return as_tuple((ranks(value) + ranks(momentum)) / 2)
