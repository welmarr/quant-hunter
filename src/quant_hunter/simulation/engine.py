"""Deterministic, cash-funded, single-instrument synthetic execution.

This arithmetic core does not register, freeze, or authorize experiments. Its
caller must use the existing Item 8 authority before evaluating a research object.
Prices are assumed synthetic opening quotes and unadjusted closing marks. The
closed-bar observation must be available at its close; late data is rejected.
Each close creates a long/flat momentum target, executable only at the *next*
opening quote strictly after that decision. The last target remains unfilled.

Full fills, no volume constraints, no corporate actions and no exchange calendar
are deliberate synthetic assumptions, never evidence of realistic execution.
Amounts use Decimal with a fixed 38-digit ROUND_HALF_EVEN arithmetic context;
cash is not prematurely rounded to cents. Financing is simple ACT/365, charged
on marked long notional during the time it is held, with no interest on cash.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from itertools import pairwise
from typing import Final

_ZERO: Final = Decimal("0")
_CONTEXT: Final = Context(prec=38, rounding=ROUND_HALF_EVEN)
_YEAR_MICROSECONDS: Final = Decimal(365 * 86400 * 1_000_000)
_LIMIT: Final = Decimal("1e18")
_LIMITATIONS: Final = (
    "SYNTHETIC: software demonstration; empirically unvalidated.",
    "Assumed opening bid/ask quotes, full fills and unlimited synthetic liquidity.",
    "No exchange calendar, corporate actions, tax, borrow, leverage or cash interest.",
    "Quote-currency cash-funded holdings only; FX units are base-currency units.",
    "Explicit commission and adverse slippage; financing is simple long ACT/365.",
    "Close marks are valuation inputs, never assumed executable quotes.",
    "Final positions are marked, not automatically liquidated.",
)


class SimulationError(ValueError):
    """Unsupported or invalid synthetic simulation input."""


def _decimal(value: Decimal, name: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise SimulationError(f"{name} must be a finite Decimal")
    if value < 0 or value > _LIMIT or (positive and value == 0):
        raise SimulationError(f"{name} is outside the supported nonnegative range")
    exponent = value.as_tuple().exponent
    if (
        not isinstance(exponent, int)
        or len(value.as_tuple().digits) > 18
        or exponent < -18
    ):
        raise SimulationError(f"{name} exceeds the supported 18-digit input precision")


def _utc(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is not UTC:
        raise SimulationError(f"{name} must use datetime.UTC")


@dataclass(frozen=True)
class Instrument:
    """Synthetic instrument; FX prices mean quote currency per one base unit."""

    symbol: str
    asset_class: str
    base_currency: str
    quote_currency: str
    quantity_step: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z0-9._/-]{1,32}", self.symbol):
            raise SimulationError("symbol must be a bounded uppercase identifier")
        if self.asset_class not in {"EQUITY", "FX_SPOT"}:
            raise SimulationError("only synthetic EQUITY and FX_SPOT are supported")
        if any(
            re.fullmatch(r"[A-Z]{3}", currency) is None
            for currency in (self.base_currency, self.quote_currency)
        ):
            raise SimulationError("currencies must be three-letter uppercase codes")
        if self.asset_class == "FX_SPOT" and self.base_currency == self.quote_currency:
            raise SimulationError("FX base and quote currencies must differ")
        _decimal(self.quantity_step, "quantity_step", positive=True)


@dataclass(frozen=True)
class Bar:
    """Synthetic opening quotes and a close mark observable at close_at."""

    open_at: datetime
    close_at: datetime
    available_at: datetime
    open_bid: Decimal
    open_ask: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        for name in ("open_at", "close_at", "available_at"):
            _utc(getattr(self, name), name)
        if self.close_at <= self.open_at:
            raise SimulationError("close_at must be strictly after open_at")
        if self.available_at != self.close_at:
            raise SimulationError(
                "closed-bar availability must equal close_at; late data unsupported"
            )
        for name in ("open_bid", "open_ask", "close"):
            _decimal(getattr(self, name), name, positive=True)
        if self.open_bid > self.open_ask:
            raise SimulationError("opening bid must not exceed ask")


@dataclass(frozen=True)
class Costs:
    """All costs explicit; zero means the caller deliberately assumed zero."""

    commission_per_fill: Decimal
    slippage_bps: Decimal
    annual_financing_rate: Decimal

    def __post_init__(self) -> None:
        for name in ("commission_per_fill", "slippage_bps", "annual_financing_rate"):
            _decimal(getattr(self, name), name)
        if self.slippage_bps >= 10000:
            raise SimulationError("slippage_bps must be less than 10000")
        if self.annual_financing_rate > 1:
            raise SimulationError("annual_financing_rate must be between zero and one")


@dataclass(frozen=True)
class SimulationConfig:
    initial_cash: Decimal
    quantity: Decimal
    lookback: int
    costs: Costs
    portfolio_currency: str = "USD"
    data_mode: str = "SYNTHETIC"
    strategy: str = "MOMENTUM"
    execution_policy: str = "NEXT_BAR_OPEN"

    def __post_init__(self) -> None:
        _decimal(self.initial_cash, "initial_cash", positive=True)
        _decimal(self.quantity, "quantity", positive=True)
        if type(self.lookback) is not int or self.lookback < 1:
            raise SimulationError("lookback must be a positive integer")
        if not isinstance(self.costs, Costs):
            raise SimulationError("explicit Costs are required")
        if self.data_mode != "SYNTHETIC":
            raise SimulationError("this engine only accepts SYNTHETIC evidence")
        if self.strategy not in {"MOMENTUM", "FLAT"}:
            raise SimulationError("unsupported strategy")
        if self.execution_policy != "NEXT_BAR_OPEN":
            raise SimulationError("only NEXT_BAR_OPEN execution is supported")


@dataclass(frozen=True)
class Decision:
    at: datetime
    target_quantity: Decimal
    reason: str


@dataclass(frozen=True)
class Trade:
    decision_at: datetime
    filled_at: datetime
    side: str
    quantity: Decimal
    quote_price: Decimal
    price: Decimal
    commission: Decimal
    slippage_cost: Decimal
    spread_cost: Decimal
    cash_after: Decimal
    quantity_after: Decimal


@dataclass(frozen=True)
class RejectedOrder:
    decision_at: datetime
    attempted_at: datetime
    side: str
    quantity: Decimal
    reason: str


@dataclass(frozen=True)
class EquityPoint:
    at: datetime
    cash: Decimal
    quantity: Decimal
    mark: Decimal
    position_value: Decimal
    equity: Decimal
    drawdown: Decimal


@dataclass(frozen=True)
class SimulationResult:
    instrument: Instrument
    config: SimulationConfig
    decisions: tuple[Decision, ...]
    trades: tuple[Trade, ...]
    rejected_orders: tuple[RejectedOrder, ...]
    equity_curve: tuple[EquityPoint, ...]
    final_cash: Decimal
    final_quantity: Decimal
    final_equity: Decimal
    net_pnl: Decimal
    total_commission: Decimal
    total_slippage: Decimal
    total_spread: Decimal
    total_financing: Decimal
    max_drawdown: Decimal
    data_mode: str = "SYNTHETIC"
    limitations: tuple[str, ...] = _LIMITATIONS


def _financing(
    quantity: Decimal, mark: Decimal, start: datetime, end: datetime, rate: Decimal
) -> Decimal:
    elapsed = end - start
    micros = (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds
    return quantity * mark * rate * Decimal(micros) / _YEAR_MICROSECONDS


def simulate(
    bars: Sequence[Bar], instrument: Instrument, config: SimulationConfig
) -> SimulationResult:
    """Run one bounded synthetic demonstration with no external side effects.

    The instrument must be valued in the portfolio currency. Quantity changes
    are whole supported increments. Orders that would borrow cash are retained
    as rejections. Financing exceeding cash aborts rather than assuming borrowing.
    The caller supplies provenance and governed experiment registration separately.
    """
    bars = tuple(bars)
    if not bars or len(bars) > 100_000:
        raise SimulationError("between 1 and 100000 bars are required")
    if any(not isinstance(bar, Bar) for bar in bars):
        raise SimulationError("every observation must be a Bar")
    if config.portfolio_currency != instrument.quote_currency:
        raise SimulationError("portfolio currency must equal instrument quote currency")
    for previous, current in pairwise(bars):
        if current.open_at <= previous.close_at:
            raise SimulationError(
                "bars must be ordered, nonoverlapping and open after prior close"
            )
    with localcontext(_CONTEXT):
        if config.quantity % instrument.quantity_step:
            raise SimulationError("quantity must be an exact multiple of quantity_step")
        return _simulate(bars, instrument, config)


def _simulate(
    bars: tuple[Bar, ...], instrument: Instrument, config: SimulationConfig
) -> SimulationResult:
    cash, quantity = config.initial_cash, _ZERO
    commission = slippage = spread = financing = _ZERO
    peak = config.initial_cash
    decisions: list[Decision] = []
    trades: list[Trade] = []
    rejected: list[RejectedOrder] = []
    curve: list[EquityPoint] = []
    for index, bar in enumerate(bars):
        if index:
            previous = bars[index - 1]
            charge = _financing(
                quantity,
                previous.close,
                previous.close_at,
                bar.open_at,
                config.costs.annual_financing_rate,
            )
            cash -= charge
            financing += charge
            if cash < 0:
                raise SimulationError(
                    "financing exceeds cash; borrowing is unsupported"
                )
            decision = decisions[-1]
            delta = decision.target_quantity - quantity
            if delta:
                side = "BUY" if delta > 0 else "SELL"
                amount = abs(delta)
                quote = bar.open_ask if delta > 0 else bar.open_bid
                slip_per_unit = quote * config.costs.slippage_bps / Decimal("10000")
                price = quote + slip_per_unit if delta > 0 else quote - slip_per_unit
                next_cash = cash - delta * price - config.costs.commission_per_fill
                if next_cash < 0:
                    rejected.append(
                        RejectedOrder(
                            decision.at,
                            bar.open_at,
                            side,
                            amount,
                            "INSUFFICIENT_CASH",
                        )
                    )
                else:
                    cash = next_cash
                    quantity += delta
                    spread_cost = amount * (bar.open_ask - bar.open_bid) / 2
                    slippage_cost = amount * slip_per_unit
                    commission += config.costs.commission_per_fill
                    slippage += slippage_cost
                    spread += spread_cost
                    trades.append(
                        Trade(
                            decision.at,
                            bar.open_at,
                            side,
                            amount,
                            quote,
                            price,
                            config.costs.commission_per_fill,
                            slippage_cost,
                            spread_cost,
                            cash,
                            quantity,
                        )
                    )
        charge = _financing(
            quantity,
            (bar.open_bid + bar.open_ask) / 2,
            bar.open_at,
            bar.close_at,
            config.costs.annual_financing_rate,
        )
        cash -= charge
        financing += charge
        if cash < 0:
            raise SimulationError("financing exceeds cash; borrowing is unsupported")
        position_value = quantity * bar.close
        equity = cash + position_value
        peak = max(peak, equity)
        curve.append(
            EquityPoint(
                bar.close_at,
                cash,
                quantity,
                bar.close,
                position_value,
                equity,
                (peak - equity) / peak,
            )
        )
        target = _ZERO
        reason = "FLAT_BASELINE" if config.strategy == "FLAT" else "WARMUP"
        if config.strategy == "MOMENTUM" and index >= config.lookback:
            increasing = bar.close > bars[index - config.lookback].close
            target = config.quantity if increasing else _ZERO
            reason = "POSITIVE_MOMENTUM" if increasing else "NONPOSITIVE_MOMENTUM"
        decisions.append(Decision(bar.close_at, target, reason))
    final = curve[-1]
    return SimulationResult(
        instrument,
        config,
        tuple(decisions),
        tuple(trades),
        tuple(rejected),
        tuple(curve),
        cash,
        quantity,
        final.equity,
        final.equity - config.initial_cash,
        commission,
        slippage,
        spread,
        financing,
        max(point.drawdown for point in curve),
    )


def synthetic_fixture(
    asset_class: str = "EQUITY",
) -> tuple[Instrument, tuple[Bar, ...]]:
    """Small invented data, intentionally containing profitable and adverse moves.

    The equity case supports the independent cash oracle: rising closes cause
    10 units to buy at the following open of 100; falling closes cause an exit at
    the following open of 101. One-unit commissions leave 10008 from 10000.
    The FX case has a nonzero explicit spread, EUR units and USD valuation.
    """
    if asset_class == "EQUITY":
        instrument = Instrument("SYNTH-EQUITY", "EQUITY", "USD", "USD")
        rows = (
            ("99", "99", "99"),
            ("99", "99", "100"),
            ("100", "100", "99"),
            ("101", "101", "101"),
        )
    elif asset_class == "FX_SPOT":
        instrument = Instrument("EUR/USD", "FX_SPOT", "EUR", "USD")
        rows = (
            ("1.0999", "1.1001", "1.1000"),
            ("1.1009", "1.1011", "1.1020"),
            ("1.1029", "1.1031", "1.1010"),
            ("1.1039", "1.1041", "1.1040"),
        )
    else:
        raise SimulationError("unsupported synthetic fixture asset class")
    start = datetime(2025, 1, 6, 14, 30, tzinfo=UTC)
    bars = tuple(
        Bar(
            start + timedelta(days=index),
            start + timedelta(days=index, hours=6),
            start + timedelta(days=index, hours=6),
            Decimal(bid),
            Decimal(ask),
            Decimal(close),
        )
        for index, (bid, ask, close) in enumerate(rows)
    )
    return instrument, bars
