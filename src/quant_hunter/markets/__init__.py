"""Bounded instrument metadata, calendars and causal session aggregation."""

from quant_hunter.markets.aggregation import (
    AggregatedBar,
    AggregationResult,
    ExcludedWindow,
    MinuteBar,
    aggregate_minutes,
)
from quant_hunter.markets.calendars import CalendarSchedule, Session, sessions
from quant_hunter.markets.common import MarketError
from quant_hunter.markets.instruments import (
    ActivityInterval,
    Instrument,
    InstrumentHistory,
    InstrumentRevision,
    MarketCapability,
    SymbolInterval,
    capability,
    require_supported,
)

__all__ = (
    "ActivityInterval",
    "AggregatedBar",
    "AggregationResult",
    "CalendarSchedule",
    "ExcludedWindow",
    "Instrument",
    "InstrumentHistory",
    "InstrumentRevision",
    "MarketCapability",
    "MarketError",
    "MinuteBar",
    "Session",
    "SymbolInterval",
    "aggregate_minutes",
    "capability",
    "require_supported",
    "sessions",
)
