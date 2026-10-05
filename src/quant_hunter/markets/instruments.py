"""Immutable instrument snapshots and knowledge-time version chains, without I/O."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from re import fullmatch
from typing import cast

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.markets.common import (
    MarketError,
    decimal_value,
    instrument_id,
    on_grid,
    utc,
)
from quant_hunter.provenance.hashing import sha256_canonical_json

SUPPORTED_ASSETS = ("EQUITY", "ETF", "FX_SPOT")


@dataclass(frozen=True, slots=True)
class ActivityInterval:
    """Effective activity is half-open; end=None means no declared closing date."""

    start: datetime
    end: datetime | None = None

    def __post_init__(self) -> None:
        utc(self.start)
        if self.end is not None and utc(self.end) <= self.start:
            raise MarketError("Activity interval must have positive duration")

    def contains(self, instant: datetime) -> bool:
        return self.start <= utc(instant) and (self.end is None or instant < self.end)


@dataclass(frozen=True, slots=True)
class SymbolInterval:
    """A symbol identifies this instrument only during the declared interval."""

    symbol: str
    start: datetime
    end: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not fullmatch(
            r"[A-Z0-9][A-Z0-9._/-]{0,31}", self.symbol
        ):
            raise MarketError("Unsupported instrument symbol")
        ActivityInterval(self.start, self.end)


def _ordered(intervals: tuple[ActivityInterval | SymbolInterval, ...]) -> None:
    if not isinstance(intervals, tuple) or not 1 <= len(intervals) <= 128:
        raise MarketError("Intervals require an immutable bounded nonempty tuple")
    for previous, current in pairwise(intervals):
        if previous.end is None or current.start < previous.end:
            raise MarketError("Intervals must be ordered and cannot overlap")


@dataclass(frozen=True, slots=True)
class Instrument:
    """A validated metadata assertion, not a vendor-verified security master."""

    instrument_id: str
    asset_class: str
    venue: str
    base_currency: str
    quote_currency: str
    price_precision: int
    quantity_precision: int
    lot_size: Decimal
    tick_size: Decimal
    multiplier: Decimal
    timezone: str
    calendar_id: str
    activity: tuple[ActivityInterval, ...]
    symbols: tuple[SymbolInterval, ...]
    status: str = "ACTIVE"

    def __post_init__(self) -> None:
        instrument_id(self.instrument_id)
        require_supported(self.asset_class)
        if not isinstance(self.venue, str) or not fullmatch(
            r"[A-Z0-9][A-Z0-9_-]{0,39}", self.venue
        ):
            raise MarketError("An explicit venue/convention name is required")
        for currency in (self.base_currency, self.quote_currency):
            if not isinstance(currency, str) or not fullmatch(r"[A-Z]{3}", currency):
                raise MarketError("Currencies must use explicit three-letter codes")
        for precision in (self.price_precision, self.quantity_precision):
            if type(precision) is not int or not 0 <= precision <= 12:
                raise MarketError("Precision must be an integer from zero to twelve")
        decimal_value(self.lot_size)
        decimal_value(self.tick_size)
        decimal_value(self.multiplier)
        on_grid(self.tick_size, Decimal(1).scaleb(-self.price_precision))
        on_grid(self.lot_size, Decimal(1).scaleb(-self.quantity_precision))
        if self.timezone != "America/New_York":
            raise MarketError("Only the explicit New York timezone is supported")
        expected = "FX_NY_17" if self.asset_class == "FX_SPOT" else "XNYS"
        if self.calendar_id != expected:
            raise MarketError("Calendar is incompatible with this market profile")
        if self.asset_class == "FX_SPOT":
            if self.base_currency == self.quote_currency:
                raise MarketError("Spot FX base and quote currencies must differ")
            if self.venue != "OTC_NY_17_CONVENTION":
                raise MarketError("FX requires the named OTC New York convention")
            if any(
                row.symbol != f"{self.base_currency}/{self.quote_currency}"
                for row in self.symbols
            ):
                raise MarketError("Spot FX symbols must preserve base/quote direction")
        elif self.venue != "XNYS" or self.base_currency != self.quote_currency:
            raise MarketError("This equity/ETF profile requires XNYS and one currency")
        if self.multiplier != 1:
            raise MarketError("Cash equity/ETF/spot profiles require multiplier one")
        if self.status not in {"ACTIVE", "INACTIVE", "DELISTED"}:
            raise MarketError("Unsupported instrument status")
        _ordered(self.activity)
        _ordered(self.symbols)
        for symbol in self.symbols:
            if not any(
                active.start <= symbol.start
                and (
                    active.end is None
                    or (symbol.end is not None and symbol.end <= active.end)
                )
                for active in self.activity
            ):
                raise MarketError(
                    "Symbol interval must lie inside one activity interval"
                )

    def symbol_at(self, instant: datetime) -> str:
        """Resolve effective symbol from this known snapshot; never use latest blindly."""
        utc(instant)
        if not any(interval.contains(instant) for interval in self.activity):
            raise MarketError("Instrument is not active at the effective instant")
        for row in self.symbols:
            if row.start <= instant and (row.end is None or instant < row.end):
                return row.symbol
        raise MarketError("Historical symbol is unknown at the effective instant")

    def validate_quote(
        self, bid: Decimal, ask: Decimal, quantity: Decimal | None = None
    ) -> None:
        """Check positive, ordered, tick-aligned quotes and optional exact lot size."""
        for price in (bid, ask):
            decimal_value(price)
            on_grid(price, self.tick_size)
        if bid > ask:
            raise MarketError("Crossed bid/ask quotes are invalid")
        if quantity is not None:
            decimal_value(quantity)
            on_grid(quantity, self.lot_size)


def _json(value: object) -> JsonValue:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, tuple | list):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if value is None or isinstance(value, str | bool | int):
        return value
    raise MarketError("Unsupported metadata serialization value")


@dataclass(frozen=True, slots=True)
class InstrumentRevision:
    """A serializable immutable version; existing governed persistence owns storage."""

    instrument: Instrument
    recorded_at: datetime
    reason: str
    evidence_mode: str = "SYNTHETIC"
    source_reference: str = "SYNTHETIC_TEST_ONLY"

    def __post_init__(self) -> None:
        utc(self.recorded_at)
        if self.evidence_mode not in {"SYNTHETIC", "HISTORICAL_DECLARED"}:
            raise MarketError("Unsupported metadata evidence mode")
        if (
            not isinstance(self.source_reference, str)
            or not 1 <= len(self.source_reference.strip()) <= 1000
        ):
            raise MarketError("A bounded metadata source reference is required")
        if not isinstance(self.reason, str) or not 1 <= len(self.reason.strip()) <= 500:
            raise MarketError("A bounded version reason is required")

    def to_record(self) -> JsonRecord:
        """Keep knowledge and effective times separate in the canonical payload."""
        return cast(JsonRecord, _json(asdict(self)))

    @classmethod
    def from_record(cls, value: JsonRecord) -> InstrumentRevision:
        """Parse only the payload; RegistryStore independently verifies its envelope."""
        record = _keys(
            value,
            {
                "instrument",
                "recorded_at",
                "reason",
                "evidence_mode",
                "source_reference",
            },
        )
        data = _keys(
            record["instrument"],
            {
                "instrument_id",
                "asset_class",
                "venue",
                "base_currency",
                "quote_currency",
                "price_precision",
                "quantity_precision",
                "lot_size",
                "tick_size",
                "multiplier",
                "timezone",
                "calendar_id",
                "activity",
                "symbols",
                "status",
            },
        )
        if not isinstance(data["activity"], list) or not isinstance(
            data["symbols"], list
        ):
            raise MarketError("Activity and symbols must be bounded arrays")
        if (
            not 1 <= len(data["activity"]) <= 128
            or not 1 <= len(data["symbols"]) <= 128
        ):
            raise MarketError("Interval arrays exceed bounds")
        activity: list[ActivityInterval] = []
        symbols: list[SymbolInterval] = []
        for item in data["activity"]:
            interval = _keys(item, {"start", "end"})
            activity.append(
                ActivityInterval(_timestamp(interval["start"]), _end(interval["end"]))
            )
        for item in data["symbols"]:
            interval = _keys(item, {"symbol", "start", "end"})
            symbols.append(
                SymbolInterval(
                    _text(interval["symbol"]),
                    _timestamp(interval["start"]),
                    _end(interval["end"]),
                )
            )
        instrument = Instrument(
            _text(data["instrument_id"]),
            _text(data["asset_class"]),
            _text(data["venue"]),
            _text(data["base_currency"]),
            _text(data["quote_currency"]),
            _integer(data["price_precision"]),
            _integer(data["quantity_precision"]),
            _decimal(data["lot_size"]),
            _decimal(data["tick_size"]),
            _decimal(data["multiplier"]),
            _text(data["timezone"]),
            _text(data["calendar_id"]),
            tuple(activity),
            tuple(symbols),
            _text(data["status"]),
        )
        return cls(
            instrument,
            _timestamp(record["recorded_at"]),
            _text(record["reason"]),
            _text(record["evidence_mode"]),
            _text(record["source_reference"]),
        )

    @property
    def digest(self) -> str:
        """Metadata payload fingerprint, never the persistent registry chain digest."""
        return sha256_canonical_json(self.to_record())


@dataclass(frozen=True, slots=True)
class InstrumentHistory:
    """Append returns a new value; it never overwrites earlier snapshots."""

    revisions: tuple[InstrumentRevision, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.revisions, tuple) or not 1 <= len(self.revisions) <= 128:
            raise MarketError("History requires one to 128 immutable revisions")
        initial = self.revisions[0].instrument
        for number, revision in enumerate(self.revisions, start=1):
            previous = self.revisions[number - 2] if number > 1 else None
            if (
                revision.instrument.instrument_id != initial.instrument_id
                or revision.instrument.asset_class != initial.asset_class
                or revision.instrument.base_currency != initial.base_currency
                or revision.instrument.quote_currency != initial.quote_currency
                or (
                    previous is not None
                    and revision.recorded_at <= previous.recorded_at
                )
            ):
                raise MarketError(
                    "Instrument history identity or knowledge-time mismatch"
                )

    def append(
        self,
        instrument: Instrument,
        recorded_at: datetime,
        reason: str,
        *,
        expected_latest_digest: str,
        evidence_mode: str | None = None,
        source_reference: str | None = None,
    ) -> InstrumentHistory:
        previous = self.revisions[-1]
        if expected_latest_digest != previous.digest:
            raise MarketError("Stale instrument history writer")
        revision = InstrumentRevision(
            instrument,
            recorded_at,
            reason,
            evidence_mode if evidence_mode is not None else previous.evidence_mode,
            source_reference
            if source_reference is not None
            else previous.source_reference,
        )
        return InstrumentHistory((*self.revisions, revision))

    def as_of(self, knowledge_time: datetime, effective_time: datetime) -> Instrument:
        utc(knowledge_time)
        utc(effective_time)
        for revision in reversed(self.revisions):
            if revision.recorded_at <= knowledge_time:
                revision.instrument.symbol_at(effective_time)
                return revision.instrument
        raise MarketError("No instrument metadata was known at this knowledge time")


def _keys(value: JsonValue, keys: set[str]) -> JsonRecord:
    if not isinstance(value, dict) or set(value) != keys:
        raise MarketError("Metadata record has missing or unknown fields")
    return value


def _text(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise MarketError("Metadata text must be a string")
    return value


def _integer(value: JsonValue) -> int:
    if type(value) is not int:
        raise MarketError("Metadata precision must be an integer")
    return value


def _timestamp(value: JsonValue) -> datetime:
    text = _text(value)
    if not fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z", text
    ):
        raise MarketError(
            "Metadata timestamp requires UTC Z, at most microsecond precision"
        )
    try:
        return utc(datetime.fromisoformat(text))
    except ValueError as error:
        raise MarketError("Metadata timestamp is invalid") from error


def _end(value: JsonValue) -> datetime | None:
    return None if value is None else _timestamp(value)


def _decimal(value: JsonValue) -> Decimal:
    text = _text(value)
    if len(text) > 40 or not fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        raise MarketError("Metadata quantity requires a bounded fixed decimal string")
    return decimal_value(Decimal(text))


@dataclass(frozen=True, slots=True)
class MarketCapability:
    """Extension contract does not grant broker, funding, or roll functionality."""

    asset_class: str
    implemented: bool
    required_contracts: tuple[str, ...]
    reason: str


def capability(asset_class: str) -> MarketCapability:
    if asset_class in SUPPORTED_ASSETS:
        return MarketCapability(asset_class, True, (), "Bounded cash market metadata")
    contracts = {
        "CRYPTO_SPOT": ("venue", "24x7_calendar", "fee_currency", "quantity_rules"),
        "CRYPTO_PERP": ("venue", "24x7_calendar", "funding", "margin", "liquidation"),
        "FUTURES": (
            "contract_id",
            "expiry",
            "last_trade",
            "delivery",
            "settlement",
            "roll",
        ),
    }
    if asset_class not in contracts:
        raise MarketError("Unknown asset class")
    return MarketCapability(
        asset_class,
        False,
        contracts[asset_class],
        "Plugin contract only; not implemented",
    )


def require_supported(asset_class: str) -> None:
    if not capability(asset_class).implemented:
        raise MarketError(
            "Market plugin is not implemented; no approximation permitted"
        )
