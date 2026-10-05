"""Causal minute-to-session-bar aggregation with explicit exclusion evidence."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from quant_hunter.markets.calendars import CalendarSchedule
from quant_hunter.markets.common import (
    MarketError,
    decimal_value,
    instrument_id,
    on_grid,
    utc,
)
from quant_hunter.markets.instruments import InstrumentRevision
from quant_hunter.provenance.hashing import sha256_canonical_json

TIMEFRAMES = {"1m": 1, "5m": 5, "1h": 60, "5h": 300}
MAX_MINUTES = 100_000
PARTIAL_POLICIES = ("DROP", "INCLUDE_CLOSED_SHORT_SESSION_TAIL")


@dataclass(frozen=True, slots=True)
class MinuteBar:
    """One closed minute of OHLC marks, with separate optional opening bid/ask."""

    instrument_id: str
    symbol: str
    open_at: datetime
    close_at: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    open_bid: Decimal | None = None
    open_ask: Decimal | None = None

    def __post_init__(self) -> None:
        instrument_id(self.instrument_id)
        utc(self.open_at)
        utc(self.close_at)
        utc(self.available_at)
        if self.open_at.second or self.open_at.microsecond:
            raise MarketError("Source minute must open on a whole-minute boundary")
        if self.close_at - self.open_at != timedelta(minutes=1):
            raise MarketError("Source input must contain exactly one-minute bars")
        if self.available_at < self.close_at:
            raise MarketError("Complete minute cannot be available before close")
        for price in (self.open, self.high, self.low, self.close):
            decimal_value(price)
        if self.low > min(self.open, self.close) or self.high < max(
            self.open, self.close
        ):
            raise MarketError("OHLC range is inconsistent")
        if self.volume is not None:
            decimal_value(self.volume, zero=True)
        if (self.open_bid is None) != (self.open_ask is None):
            raise MarketError("Opening bid and ask must be supplied together")
        if self.open_bid is not None and self.open_ask is not None:
            decimal_value(self.open_bid)
            decimal_value(self.open_ask)
            if self.open_bid > self.open_ask:
                raise MarketError("Crossed opening bid/ask")


@dataclass(frozen=True, slots=True)
class AggregatedBar:
    instrument_id: str
    symbol: str
    session: str
    open_at: datetime
    close_at: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    open_bid: Decimal | None
    open_ask: Decimal | None
    source_count: int
    short_session_tail: bool


@dataclass(frozen=True, slots=True)
class ExcludedWindow:
    session: str
    open_at: datetime
    close_at: datetime
    reason: str
    expected_minutes: int
    observed_minutes: int


@dataclass(frozen=True, slots=True)
class AggregationResult:
    bars: tuple[AggregatedBar, ...]
    exclusions: tuple[ExcludedWindow, ...]
    configuration_digest: str
    instrument_revision_digest: str
    calendar_digest: str
    timeframe: str
    partial_policy: str
    as_of: datetime
    anchor: str = "SESSION_OPEN"


def aggregate_minutes(
    bars: tuple[MinuteBar, ...],
    revision: InstrumentRevision,
    schedule: CalendarSchedule,
    *,
    as_of: datetime,
    timeframe: str,
    partial_policy: str,
) -> AggregationResult:
    """Reject invalid input; emit only fully populated, closed and available windows.

    Partition callers must supply complete sessions, not arbitrary row chunks.
    No price adjustment, imputation, interpolation, or learned transform is applied.
    """
    utc(as_of)
    if timeframe not in TIMEFRAMES or partial_policy not in PARTIAL_POLICIES:
        raise MarketError(
            "Explicit supported timeframe and partial policy are required"
        )
    if not isinstance(bars, tuple) or len(bars) > MAX_MINUTES:
        raise MarketError(
            "Source requires an immutable tuple of at most 100000 minutes"
        )
    if revision.recorded_at > as_of:
        raise MarketError("Instrument metadata is unavailable at the aggregation as-of")
    instrument = revision.instrument
    if schedule.calendar_id != instrument.calendar_id:
        raise MarketError("Instrument and calendar identities disagree")
    expected_total = sum(
        int((session.close_at - session.open_at).total_seconds() // 60)
        for session in schedule.sessions
    )
    if expected_total > MAX_MINUTES:
        raise MarketError(
            "Schedule exceeds 100000 source-minute bound; partition by session"
        )
    indexed: dict[datetime, MinuteBar] = {}
    session_index = 0
    for row in bars:
        if indexed and row.open_at <= next(reversed(indexed)):
            raise MarketError(
                "Source minutes must be strictly chronological and unique"
            )
        if row.instrument_id != instrument.instrument_id:
            raise MarketError("Input minute belongs to another stable instrument")
        if row.symbol != instrument.symbol_at(row.open_at):
            raise MarketError(
                "Input symbol disagrees with historical instrument metadata"
            )
        if not any(
            interval.symbol == row.symbol
            and interval.start <= row.open_at
            and (interval.end is None or row.close_at <= interval.end)
            for interval in instrument.symbols
        ):
            raise MarketError("Source minute crosses a historical symbol boundary")
        if not any(
            interval.start <= row.open_at
            and (interval.end is None or row.close_at <= interval.end)
            for interval in instrument.activity
        ):
            raise MarketError("Source minute crosses an instrument activity boundary")
        for price in (row.open, row.high, row.low, row.close):
            on_grid(price, instrument.tick_size)
        if row.volume is not None:
            on_grid(row.volume, Decimal(1).scaleb(-instrument.quantity_precision))
        if row.open_bid is not None and row.open_ask is not None:
            instrument.validate_quote(row.open_bid, row.open_ask)
        while session_index < len(schedule.sessions) and (
            row.open_at >= schedule.sessions[session_index].close_at
        ):
            session_index += 1
        if session_index == len(schedule.sessions):
            raise MarketError("Source minute is outside the supplied sessions")
        session = schedule.sessions[session_index]
        if row.open_at < session.open_at or row.close_at > session.close_at:
            raise MarketError("Source minute crosses a session or falls in a closure")
        indexed[row.open_at] = row
    emitted: list[AggregatedBar] = []
    excluded: list[ExcludedWindow] = []
    duration = timedelta(minutes=TIMEFRAMES[timeframe])
    for session in schedule.sessions:
        start = session.open_at
        while start < session.close_at:
            end = min(start + duration, session.close_at)
            count = int((end - start).total_seconds() // 60)
            short = end - start < duration
            constituents = tuple(
                indexed[point]
                for minute in range(count)
                if (point := start + timedelta(minutes=minute)) in indexed
            )
            reason = (
                "NOT_CLOSED"
                if end > as_of
                else "SHORT_SESSION_TAIL_DROPPED"
                if short and partial_policy == "DROP"
                else "MISSING_MINUTES"
                if len(constituents) != count
                else "UNAVAILABLE_MINUTES"
                if any(row.available_at > as_of for row in constituents)
                else "SYMBOL_CHANGE_WITHIN_WINDOW"
                if len({row.symbol for row in constituents}) != 1
                else None
            )
            if reason:
                excluded.append(
                    ExcludedWindow(
                        session.label.isoformat(),
                        start,
                        end,
                        reason,
                        count,
                        len(constituents),
                    )
                )
            else:
                first, last = constituents[0], constituents[-1]
                with localcontext() as context:
                    context.prec = 78
                    volume = (
                        None
                        if any(row.volume is None for row in constituents)
                        else sum(
                            (
                                row.volume
                                for row in constituents
                                if row.volume is not None
                            ),
                            Decimal(0),
                        )
                    )
                emitted.append(
                    AggregatedBar(
                        instrument.instrument_id,
                        first.symbol,
                        session.label.isoformat(),
                        start,
                        end,
                        max(row.available_at for row in constituents),
                        first.open,
                        max(row.high for row in constituents),
                        min(row.low for row in constituents),
                        last.close,
                        volume,
                        first.open_bid,
                        first.open_ask,
                        count,
                        short,
                    )
                )
            start = end
    instrument_digest = revision.digest
    calendar_digest = schedule.digest
    configuration = sha256_canonical_json(
        {
            "algorithm": "qh-session-minute-aggregation-v1",
            "timeframe": timeframe,
            "partial_policy": partial_policy,
            "anchor": schedule.anchor,
            "as_of": as_of.isoformat(),
            "instrument_revision_digest": instrument_digest,
            "calendar_digest": calendar_digest,
            "missing_policy": "EXCLUDE_WINDOW",
            "volume_policy": "UNKNOWN_IF_ANY_UNKNOWN",
            "ohlc_semantics": "MARK_NOT_EXECUTABLE",
        }
    )
    return AggregationResult(
        tuple(emitted),
        tuple(excluded),
        configuration,
        instrument_digest,
        calendar_digest,
        timeframe,
        partial_policy,
        as_of,
    )
