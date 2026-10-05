"""Explicit window-local representations; none silently fits a full corpus."""

from __future__ import annotations

from typing import Literal

import numpy as np

from quant_hunter.patterns.contracts import Floats, PatternError, bounded_int, freeze

type Normalization = Literal[
    "RAW", "BASE100", "RETURNS", "LOG_RETURNS", "Z_WINDOW", "CAUSAL_VOL"
]


def normalize(values: Floats, mode: Normalization) -> Floats:
    x = freeze(values)
    if mode == "RAW":
        return x
    if mode == "Z_WINDOW":
        std = x.std(axis=0)
        return freeze(
            np.divide(x - x.mean(axis=0), std, out=np.zeros_like(x), where=std > 1e-12)
        )
    if mode not in {"BASE100", "RETURNS", "LOG_RETURNS", "CAUSAL_VOL"}:
        raise PatternError("Unknown explicit normalization")
    if np.any(x <= 0):
        raise PatternError(
            "Price-based representations require strictly positive prices"
        )
    if mode == "BASE100":
        return freeze(100 * x / x[0])
    returns = np.zeros_like(x)
    returns[1:] = (
        np.log(x[1:] / x[:-1]) if mode == "LOG_RETURNS" else x[1:] / x[:-1] - 1
    )
    if mode == "CAUSAL_VOL":
        # Scale each return with strictly earlier window returns, never its future.
        result = np.zeros_like(x)
        if len(x) >= 4:
            counts = np.arange(2, len(x) - 1)[:, None]
            sums = np.cumsum(returns, axis=0)[2:-1]
            squares = np.cumsum(returns**2, axis=0)[2:-1]
            volatility = np.sqrt(np.maximum(0, squares / counts - (sums / counts) ** 2))
            result[3:] = np.divide(
                returns[3:],
                volatility,
                out=np.zeros_like(returns[3:]),
                where=volatility > 1e-12,
            )
        return freeze(result)
    return freeze(returns)


def paa(values: Floats, segments: int) -> Floats:
    """Equal-count PAA; divisibility is required, never hidden unequal bin weights."""
    x = freeze(values)
    bounded_int(segments, 1, len(x), "PAA segments")
    if len(x) % segments:
        raise PatternError("PAA window length must be divisible by segment count")
    return freeze(x.reshape(segments, len(x) // segments, x.shape[1]).mean(axis=1))


def relative_candles(ohlc: Floats) -> Floats:
    """Columns open/high/low/close -> body, upper/lower wick and opening gap.

    All coordinates divide by the previous close (first row uses its own open).
    This preserves gap information; it does not adjust splits/corporate actions.
    """
    x = freeze(ohlc)
    if x.shape[1] != 4 or np.any(x <= 0):
        raise PatternError("Four positive OHLC columns required")
    opening, high, low, close = x.T
    if (
        np.any(high < np.maximum(opening, close))
        or np.any(low > np.minimum(opening, close))
        or np.any(low > high)
    ):
        raise PatternError("OHLC envelopes are inconsistent")
    denominator = np.r_[opening[0], close[:-1]]
    return freeze(
        np.column_stack(
            (
                (close - opening) / denominator,
                (high - np.maximum(opening, close)) / denominator,
                (np.minimum(opening, close) - low) / denominator,
                opening / denominator - 1,
            )
        )
    )


def euclidean(left: Floats, right: Floats) -> float:
    if left.shape != right.shape:
        raise PatternError("Exact distance requires equal window/feature shapes")
    return float(np.sqrt(np.mean((left - right) ** 2)))


def constrained_dtw(
    left: Floats,
    right: Floats,
    *,
    radius: int,
    max_cells: int = 200_000,
    abandon_above: float | None = None,
) -> float:
    """Sakoe-Chiba band, squared feature-mean costs, fixed n+m scale.

    Returned sqrt(cost/(n+m)) is not path-length-normalized. An abandoned search
    returns infinity, a rejection bound rather than an exact distance.
    """
    a, b = freeze(left), freeze(right)
    n, m = len(a), len(b)
    bounded_int(radius, 0, 128, "DTW band")
    bounded_int(max_cells, 1, 2_000_000, "DTW cell budget")
    if n > 512 or m > 512 or a.shape[1] != b.shape[1] or abs(n - m) > radius:
        raise PatternError("DTW shape or band is incompatible")
    cells = sum(min(m, i + radius) - max(1, i - radius) + 1 for i in range(1, n + 1))
    if cells > max_cells:
        raise PatternError("DTW work exceeds the declared cell budget")
    if abandon_above is not None and (
        not np.isfinite(abandon_above) or abandon_above < 0
    ):
        raise PatternError("DTW abandonment threshold must be finite and nonnegative")
    previous = np.full(m + 1, np.inf)
    previous[0] = 0
    threshold = np.inf if abandon_above is None else abandon_above**2 * (n + m)
    for i in range(1, n + 1):
        current = np.full(m + 1, np.inf)
        for j in range(max(1, i - radius), min(m, i + radius) + 1):
            cost = float(np.mean((a[i - 1] - b[j - 1]) ** 2))
            current[j] = cost + min(previous[j], current[j - 1], previous[j - 1])
        if float(current.min()) > threshold:
            return float("inf")
        previous = current
    return float(np.sqrt(previous[m] / (n + m)))
