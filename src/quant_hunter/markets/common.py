"""Strict shared primitives for bounded market metadata and arithmetic."""

from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from re import fullmatch
from uuid import RFC_4122, UUID


class MarketError(ValueError):
    """Market input is invalid, unsupported, or outside an explicit bound."""


def utc(value: datetime) -> datetime:
    """Require an explicit UTC instant; never infer a local clock or offset."""
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise MarketError("An explicit timezone-aware UTC datetime is required")
    return value


def instrument_id(value: str) -> None:
    """Validate caller-allocated stable identity without creating a registry writer."""
    if not isinstance(value, str) or not fullmatch(
        r"INSTRUMENT-[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        value,
    ):
        raise MarketError("Expected a caller-allocated INSTRUMENT UUIDv7 identity")
    parsed = UUID(value.removeprefix("INSTRUMENT-"))
    if parsed.version != 7 or parsed.variant != RFC_4122:
        raise MarketError("Instrument identity must use RFC 9562 UUIDv7")


def decimal_value(value: Decimal, *, zero: bool = False) -> Decimal:
    """Bound Decimal arithmetic without coercion, floating point, or rounding."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise MarketError("A finite Decimal is required")
    parts = value.as_tuple()
    if len(parts.digits) > 36 or not -12 <= int(parts.exponent) <= 12:
        raise MarketError("Decimal coefficient/exponent exceeds supported precision")
    if value < 0 or (not zero and value == 0) or value >= Decimal("1e18"):
        raise MarketError("Decimal is outside the supported nonnegative range")
    return value


def on_grid(value: Decimal, step: Decimal) -> None:
    """Reject off-grid values; callers must declare a separate rounding policy."""
    with localcontext() as context:
        context.prec = 78
        if value % step:
            raise MarketError("Value is not an exact multiple of its tick/lot")
