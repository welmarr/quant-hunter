"""CRP09--10: first-release surprises and complete top-of-book event flow."""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .common import MAX_ROWS, MethodError, after, integer, number, utc


@dataclass(frozen=True)
class MacroRelease:
    indicator: str
    unit: str
    period_end: datetime
    published_at: datetime
    available_at: datetime
    actual: float
    consensus: float | None
    consensus_at: datetime | None
    first_release: bool
    consensus_source: str
    consensus_statistic: str


def _surprise(release: MacroRelease, cutoff: datetime) -> float:
    for date in (
        cutoff,
        release.period_end,
        release.published_at,
        release.available_at,
    ):
        utc(date)
    if (
        release.first_release is not True
        or release.consensus is None
        or release.consensus_at is None
    ):
        raise MethodError("first release and historically known consensus required")
    utc(release.consensus_at)
    if not (
        release.period_end <= release.published_at <= release.available_at <= cutoff
        and release.consensus_at < release.published_at
    ):
        raise MethodError("macro release or consensus unavailable at decision time")
    for identity in (release.indicator, release.unit, release.consensus_source):
        if (
            not isinstance(identity, str)
            or not identity.strip()
            or len(identity) > 80
            or not identity.isprintable()
        ):
            raise MethodError("bounded indicator, unit and consensus source required")
    if release.consensus_statistic not in {"MEDIAN", "MEAN"}:
        raise MethodError("explicit consensus statistic MEDIAN or MEAN required")
    return number(release.actual) - number(release.consensus)


@dataclass(frozen=True)
class SurpriseScale:
    train_end: datetime
    indicator: str
    unit: str
    consensus_source: str
    consensus_statistic: str
    standard_deviation: float
    sample_size: int


def fit_surprise_scale(
    releases: Sequence[MacroRelease],
    *,
    train_end: datetime,
) -> SurpriseScale:
    utc(train_end)
    integer(len(releases), 3, MAX_ROWS)
    for release in releases:
        utc(release.available_at)
    selected = [r for r in releases if r.available_at <= train_end]
    if len(selected) < 3:
        raise MethodError("insufficient training first releases")
    identities = {
        (r.indicator, r.unit, r.consensus_source, r.consensus_statistic)
        for r in selected
    }
    if len(identities) != 1 or len({r.period_end for r in selected}) != len(selected):
        raise MethodError("mixed macro/consensus identities or duplicate first release")
    surprises = [_surprise(r, train_end) for r in selected]
    scale = float(np.std(surprises, ddof=1))
    if scale <= 1e-12:
        raise MethodError("surprise scale is unidentifiable")
    return SurpriseScale(
        train_end,
        selected[0].indicator,
        selected[0].unit,
        selected[0].consensus_source,
        selected[0].consensus_statistic,
        scale,
        len(selected),
    )


def macro_surprise(
    model: SurpriseScale,
    release: MacroRelease,
    *,
    as_of: datetime,
) -> float:
    after(model.train_end, release.published_at)
    if (
        release.indicator,
        release.unit,
        release.consensus_source,
        release.consensus_statistic,
    ) != (
        model.indicator,
        model.unit,
        model.consensus_source,
        model.consensus_statistic,
    ):
        raise MethodError("macro and consensus identities must match training scale")
    return _surprise(release, as_of) / model.standard_deviation


@dataclass(frozen=True)
class BookUpdate:
    sequence: int
    at: datetime
    available_at: datetime
    bid: float
    bid_size: float
    ask: float
    ask_size: float


@dataclass(frozen=True)
class OrderFlow:
    event_contributions: tuple[float, ...]
    total: float
    final_queue_imbalance: float
    observations: int


def order_flow_imbalance(
    updates: Sequence[BookUpdate],
    *,
    as_of: datetime,
    data_kind: str = "SEQUENCED_BOOK_UPDATES",
) -> OrderFlow:
    """Cont--Kukanov--Stoikov event equation; first quote initializes state."""
    utc(as_of)
    integer(len(updates), 2, MAX_ROWS)
    if data_kind != "SEQUENCED_BOOK_UPDATES":
        raise MethodError(
            "actual ordered book updates required; FI2010 is not execution data"
        )
    visible: list[BookUpdate] = []
    previous: BookUpdate | None = None
    for update in updates:
        integer(update.sequence, 0, 2**53 - 1)
        utc(update.at)
        utc(update.available_at)
        if update.available_at < update.at:
            raise MethodError("book available before event")
        if previous is not None and (
            update.sequence != previous.sequence + 1
            or update.at < previous.at
            or update.available_at < previous.available_at
        ):
            raise MethodError("book stream gap, duplicate or out-of-order update")
        previous = update
        if update.available_at <= as_of:
            for value in (update.bid, update.ask, update.bid_size, update.ask_size):
                number(value, positive=True)
            if update.bid >= update.ask:
                raise MethodError("locked or crossed book")
            visible.append(update)
    if len(visible) < 2:
        raise MethodError("insufficient visible book updates")
    contributions: list[float] = []
    for old, new in itertools.pairwise(visible):
        value = (
            (new.bid_size if new.bid >= old.bid else 0)
            - (old.bid_size if new.bid <= old.bid else 0)
            - (new.ask_size if new.ask <= old.ask else 0)
            + (old.ask_size if new.ask >= old.ask else 0)
        )
        contributions.append(float(value))
    last = visible[-1]
    imbalance = (last.bid_size - last.ask_size) / (last.bid_size + last.ask_size)
    return OrderFlow(tuple(contributions), sum(contributions), imbalance, len(visible))
