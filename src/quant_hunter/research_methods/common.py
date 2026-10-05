"""Bounded mathematical inputs; no data access or research lifecycle authority."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

import numpy as np
from numpy.typing import NDArray

MAX_ROWS = 4096
MAX_COLUMNS = 64
Array = NDArray[np.float64]


class MethodError(ValueError):
    """Invalid, unavailable, degenerate or insufficient mathematical input."""


@dataclass(frozen=True)
class TimedRow:
    """A synchronized vector measured at ``at`` and usable at ``available_at``."""

    at: datetime
    available_at: datetime
    values: tuple[float, ...]


def utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise MethodError("UTC-aware timestamps required")


def number(value: float, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise MethodError("finite numeric input required")
    try:
        result = float(value)
    except OverflowError:
        raise MethodError("numeric value outside finite supported range") from None
    if (
        not isfinite(result)
        or abs(result) > 1e12
        or (result != 0 and abs(result) < 1e-100)
        or (positive and result <= 0)
    ):
        raise MethodError("numeric value outside finite supported range")
    return result


def integer(value: int, lower: int, upper: int) -> None:
    if type(value) is not int or not lower <= value <= upper:
        raise MethodError("integer parameter outside supported bounds")


def vector(values: Sequence[float], *, minimum: int = 1) -> Array:
    if not minimum <= len(values) <= MAX_ROWS:
        raise MethodError("insufficient or excessive sample")
    return np.array([number(x) for x in values], dtype=np.float64)


def history(rows: Sequence[TimedRow], cutoff: datetime, *, minimum: int = 2) -> Array:
    utc(cutoff)
    if not minimum <= len(rows) <= MAX_ROWS:
        raise MethodError("insufficient or excessive sample")
    columns = len(rows[0].values)
    integer(columns, 1, MAX_COLUMNS)
    selected: list[tuple[float, ...]] = []
    previous: datetime | None = None
    previous_available: datetime | None = None
    for row in rows:
        utc(row.at)
        utc(row.available_at)
        if row.available_at < row.at or (previous is not None and row.at <= previous):
            raise MethodError("timestamps must be unique, ordered and causal")
        if previous_available is not None and row.available_at < previous_available:
            raise MethodError("availability must preserve observation order")
        if len(row.values) != columns:
            raise MethodError("inconsistent vector dimension")
        previous = row.at
        previous_available = row.available_at
        if row.available_at <= cutoff:
            selected.append(tuple(number(x) for x in row.values))
    if len(selected) < minimum:
        raise MethodError("insufficient observations available by cutoff")
    return np.array(selected, dtype=np.float64)


def after(training_end: datetime, at: datetime) -> None:
    utc(training_end)
    utc(at)
    if at <= training_end:
        raise MethodError("prediction must follow the training cutoff")


def finite_result(values: Array) -> Array:
    if not bool(np.isfinite(values).all()):
        raise MethodError("nonfinite numerical result")
    return values


def as_tuple(values: Array) -> tuple[float, ...]:
    return tuple(float(x) for x in finite_result(values))


def ranks(values: Array) -> Array:
    """Average ties; centered ranks with gross exposure one (zero for all ties)."""
    rank = np.array(
        [np.sum(values < x) + (np.sum(values == x) - 1) / 2 for x in values],
        dtype=np.float64,
    )
    rank -= rank.mean()
    gross = float(np.abs(rank).sum())
    return rank / gross if gross else rank
