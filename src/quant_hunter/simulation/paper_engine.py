"""Transactional, owner-scoped local paper ledger; never a broker or research gate."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from pathlib import Path
from typing import cast

from quant_hunter.simulation import accounting as a

ZERO = Decimal(0)
MAX_COMMANDS = 1000
MAX_PAYLOAD = 131_072
MAX_TOTAL_BYTES = 16_777_216
APPLICATION_ID = 0x51485030


class PaperError(ValueError):
    """Bounded local operational rejection, never scientific approval."""


def _id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", value
    ):
        raise PaperError("INVALID_ID")


def _utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is not UTC:
        raise PaperError("UTC_REQUIRED")


def _positive(value: Decimal, *, zero: bool = False) -> None:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < 0
        or (not zero and not value)
    ):
        raise PaperError("INVALID_DECIMAL")
    if (
        len(value.as_tuple().digits) > 18
        or not -18 <= int(value.as_tuple().exponent) <= 18
        or value > Decimal("1e18")
    ):
        raise PaperError("DECIMAL_BOUND")


@dataclass(frozen=True)
class StrategyBudget:
    strategy_id: str
    maximum_exposure: Decimal


@dataclass(frozen=True)
class RiskLimits:
    max_order_notional: Decimal
    max_gross_exposure: Decimal
    max_instrument_exposure: Decimal
    max_concentration: Decimal
    max_drawdown: Decimal
    max_loss: Decimal
    max_spread_bps: Decimal
    max_slippage_bps: Decimal
    max_quote_age_seconds: int
    max_orders_per_window: int
    order_window_seconds: int
    strategy_budgets: tuple[StrategyBudget, ...]

    def validate(self) -> None:
        for value in (
            self.max_order_notional,
            self.max_gross_exposure,
            self.max_instrument_exposure,
            self.max_concentration,
            self.max_drawdown,
            self.max_loss,
        ):
            _positive(value)
        for value in (self.max_spread_bps, self.max_slippage_bps):
            _positive(value, zero=True)
        if (
            self.max_concentration > 1
            or self.max_drawdown > 1
            or self.max_slippage_bps > 1000
            or self.max_spread_bps > 1000
        ):
            raise PaperError("RISK_LIMIT_RANGE")
        for integer_value, bound in (
            (self.max_quote_age_seconds, 86400),
            (self.max_orders_per_window, 1000),
            (self.order_window_seconds, 86400),
        ):
            if type(integer_value) is not int or not 1 <= integer_value <= bound:
                raise PaperError("RISK_LIMIT_RANGE")
        if (
            not isinstance(self.strategy_budgets, tuple)
            or not 1 <= len(self.strategy_budgets) <= 32
        ):
            raise PaperError("STRATEGY_BUDGET_REQUIRED")
        for budget in self.strategy_budgets:
            _id(budget.strategy_id)
            _positive(budget.maximum_exposure)
        if len({b.strategy_id for b in self.strategy_budgets}) != len(
            self.strategy_budgets
        ):
            raise PaperError("DUPLICATE_STRATEGY")


@dataclass(frozen=True)
class Provenance:
    experiment_id: str
    code_digest: str
    environment_digest: str
    configuration_digest: str
    evidence_mode: str
    mode: str

    def validate(self) -> None:
        _id(self.experiment_id)
        for digest in (
            self.code_digest,
            self.environment_digest,
            self.configuration_digest,
        ):
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise PaperError("INVALID_PROVENANCE")
        if self.mode not in {"LOCAL_PAPER", "REPLAY"} or self.evidence_mode not in {
            "SYNTHETIC",
            "RECORDED_FIXTURE",
            "HISTORICAL_REAL",
        }:
            raise PaperError("UNSUPPORTED_MODE")


@dataclass(frozen=True, kw_only=True)
class Command:
    command_id: str
    at: datetime


@dataclass(frozen=True, kw_only=True)
class Admit(Command):
    order_id: str
    strategy_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    decision_at: datetime
    quote: a.Quote
    commission_budget: Decimal


@dataclass(frozen=True, kw_only=True)
class Match(Command):
    order_id: str
    quantity: Decimal
    quote: a.Quote
    commission: Decimal
    slippage_bps: Decimal


@dataclass(frozen=True, kw_only=True)
class Cancel(Command):
    order_id: str
    action: str


@dataclass(frozen=True, kw_only=True)
class Mark(Command):
    quotes: tuple[a.Quote, ...]


@dataclass(frozen=True, kw_only=True)
class Kill(Command):
    enabled: bool
    reason: str


@dataclass(frozen=True, kw_only=True)
class Health(Command):
    healthy: bool


@dataclass(frozen=True, kw_only=True)
class Reconcile(Command):
    cash: Decimal
    positions: tuple[tuple[str, Decimal], ...]
    observation_at: datetime


type PaperCommand = Admit | Match | Cancel | Mark | Kill | Health | Reconcile
COMMAND_TYPES = (Admit, Match, Cancel, Mark, Kill, Health, Reconcile)


@dataclass(frozen=True)
class Reservation:
    order_id: str
    strategy_id: str
    instrument_id: str
    side: str
    remaining: Decimal
    price_ceiling: Decimal
    fee_remaining: Decimal

    @property
    def cash(self) -> Decimal:
        return (
            self.remaining * self.price_ceiling if self.side == "BUY" else ZERO
        ) + self.fee_remaining


@dataclass(frozen=True)
class Holding:
    strategy_id: str
    instrument_id: str
    quantity: Decimal


@dataclass(frozen=True)
class Outcome:
    command_id: str
    status: str
    reason: str


@dataclass(frozen=True)
class ProtocolRejection:
    command_id: str
    at: datetime
    reason: str
    expected_revision: int
    actual_revision: int
    fingerprint: str


@dataclass(frozen=True)
class PaperSnapshot:
    account_id: str
    owner_id: str
    book: a.BookSnapshot
    limits: RiskLimits
    provenance: Provenance
    at: datetime
    inception_equity: Decimal
    equity: Decimal
    high_water: Decimal
    drawdown: Decimal = ZERO
    max_drawdown: Decimal = ZERO
    killed: bool = False
    kill_reason: str = ""
    killed_at: datetime | None = None
    reconciled: bool = True
    reconciled_at: datetime | None = None
    healthy: bool = True
    reservations: tuple[Reservation, ...] = ()
    holdings: tuple[Holding, ...] = ()
    quotes: tuple[a.Quote, ...] = ()
    admissions: tuple[datetime, ...] = ()
    outcomes: tuple[Outcome, ...] = ()
    revision: int = 0
    format_version: str = "v0-local-paper-1"


_TYPES: dict[str, type[object]] = {
    cls.__name__: cls
    for cls in (
        StrategyBudget,
        RiskLimits,
        Provenance,
        Reservation,
        Holding,
        Outcome,
        PaperSnapshot,
        *COMMAND_TYPES,
        a.TradingWindow,
        a.InstrumentSpec,
        a.Quote,
        a.CashBalance,
        a.Position,
        a.Order,
        a.Fill,
        a.DividendReceivable,
        a.Receipt,
        a.CorporateAction,
        a.Liquidation,
        a.BookSnapshot,
    )
}


def _encode(value: object) -> object:
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, datetime):
        _utc(value)
        return {"utc": value.isoformat()}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "type": type(value).__name__,
            "fields": {f.name: _encode(getattr(value, f.name)) for f in fields(value)},
        }
    if value is None or type(value) in (str, int, bool):
        return value
    raise PaperError("UNSUPPORTED_PAYLOAD")


def _decode(value: object) -> object:
    if isinstance(value, list):
        return tuple(_decode(item) for item in value)
    if isinstance(value, dict):
        if set(value) == {"decimal"} and isinstance(value["decimal"], str):
            return Decimal(value["decimal"])
        if set(value) == {"utc"} and isinstance(value["utc"], str):
            at = datetime.fromisoformat(value["utc"])
            _utc(at)
            return at
        if (
            set(value) == {"type", "fields"}
            and value["type"] in _TYPES
            and isinstance(value["fields"], dict)
        ):
            cls = _TYPES[value["type"]]
            return cls(**{key: _decode(item) for key, item in value["fields"].items()})
        raise PaperError("INVALID_STORED_PAYLOAD")
    if value is None or type(value) in (str, int, bool):
        return value
    raise PaperError("INVALID_STORED_PAYLOAD")


def _bytes(value: object) -> bytes:
    encoded = json.dumps(
        _encode(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    limit = 2_097_152 if isinstance(value, PaperSnapshot) else MAX_PAYLOAD
    if len(encoded) > limit:
        raise PaperError("PAYLOAD_LIMIT")
    return encoded


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _cash(state: PaperSnapshot) -> Decimal:
    return state.book.cash[0].amount


def _quote(state: PaperSnapshot, instrument_id: str, at: datetime) -> a.Quote:
    quote = next((q for q in state.quotes if q.instrument_id == instrument_id), None)
    if (
        quote is None
        or not quote.at <= quote.available_at <= at
        or at - quote.at > timedelta(seconds=state.limits.max_quote_age_seconds)
    ):
        raise PaperError("STALE_OR_UNAVAILABLE_QUOTE")
    return quote


def _quotes(
    state: PaperSnapshot, quotes: tuple[a.Quote, ...], at: datetime
) -> PaperSnapshot:
    if (
        not isinstance(quotes, tuple)
        or len(quotes) > len(state.book.instruments)
        or len({q.instrument_id for q in quotes}) != len(quotes)
    ):
        raise PaperError("INVALID_QUOTE_BATCH")
    known = {i.instrument_id: i for i in state.book.instruments}
    merged = {q.instrument_id: q for q in state.quotes}
    for quote in quotes:
        quote.__post_init__()
        if quote.instrument_id not in known:
            raise PaperError("UNKNOWN_INSTRUMENT")
        if (
            quote.bid % known[quote.instrument_id].tick
            or quote.ask % known[quote.instrument_id].tick
        ):
            raise PaperError("QUOTE_TICK_GRID")
        old = merged.get(quote.instrument_id)
        if old is not None and (
            quote.at < old.at or (quote.at == old.at and quote != old)
        ):
            raise PaperError("QUOTE_REVISION_OR_REORDER")
        merged[quote.instrument_id] = quote
    result = replace(state, quotes=tuple(merged[key] for key in sorted(merged)))
    for quote in quotes:
        _quote(result, quote.instrument_id, at)
    return result


def _valuation(state: PaperSnapshot, at: datetime) -> PaperSnapshot:
    for position in state.book.positions:
        _quote(state, position.instrument_id, at)
    valuation = a.value_book(
        state.book,
        state.quotes,
        (),
        as_of=at,
        max_quote_age_seconds=state.limits.max_quote_age_seconds,
    )
    equity = valuation.equity
    high = max(state.high_water, equity)
    drawdown = (high - equity) / high
    result = replace(
        state,
        equity=equity,
        high_water=high,
        drawdown=drawdown,
        max_drawdown=max(drawdown, state.max_drawdown),
    )
    if (
        drawdown >= state.limits.max_drawdown
        or state.inception_equity - equity >= state.limits.max_loss
    ):
        result = replace(result, killed=True, kill_reason="LOSS_LIMIT")
    gross, instruments, strategies = _exposures(result, at)
    if (
        gross > state.limits.max_gross_exposure
        or any(
            value > state.limits.max_instrument_exposure
            or value > equity * state.limits.max_concentration
            for value in instruments.values()
        )
        or any(
            strategies.get(b.strategy_id, ZERO) > b.maximum_exposure
            for b in state.limits.strategy_budgets
        )
    ):
        result = replace(result, killed=True, kill_reason="EXPOSURE_LIMIT")
    return result


def _reservation(state: PaperSnapshot, order_id: str) -> Reservation:
    match = next((r for r in state.reservations if r.order_id == order_id), None)
    if match is None:
        raise PaperError("NO_OPEN_RESERVATION")
    return match


def _book_event(state: PaperSnapshot, event: a.BookEvent) -> PaperSnapshot:
    return replace(state, book=a.apply_event(state.book, event))


def _exposures(
    state: PaperSnapshot, at: datetime
) -> tuple[Decimal, dict[str, Decimal], dict[str, Decimal]]:
    instruments: dict[str, Decimal] = {}
    strategies: dict[str, Decimal] = {}
    for holding in state.holdings:
        exposure = holding.quantity * _quote(state, holding.instrument_id, at).ask
        instruments[holding.instrument_id] = (
            instruments.get(holding.instrument_id, ZERO) + exposure
        )
        strategies[holding.strategy_id] = (
            strategies.get(holding.strategy_id, ZERO) + exposure
        )
    for reserve in state.reservations:
        if reserve.side == "BUY":
            exposure = reserve.remaining * reserve.price_ceiling
            instruments[reserve.instrument_id] = (
                instruments.get(reserve.instrument_id, ZERO) + exposure
            )
            strategies[reserve.strategy_id] = (
                strategies.get(reserve.strategy_id, ZERO) + exposure
            )
    return sum(instruments.values(), ZERO), instruments, strategies


def _admit(state: PaperSnapshot, cmd: Admit) -> PaperSnapshot:
    for identity in (cmd.order_id, cmd.strategy_id, cmd.instrument_id):
        _id(identity)
    _utc(cmd.decision_at)
    _positive(cmd.quantity)
    _positive(cmd.commission_budget, zero=True)
    if cmd.side not in {"BUY", "SELL"} or cmd.quote.instrument_id != cmd.instrument_id:
        raise PaperError("INVALID_ORDER")
    if not state.reconciled or not state.healthy:
        raise PaperError("UNRECONCILED_OR_UNHEALTHY")
    if state.killed and cmd.side != "SELL":
        raise PaperError("KILL_ACTIVE")
    if not cmd.quote.available_at <= cmd.decision_at <= cmd.at:
        raise PaperError("DECISION_QUOTE_TIMING")
    if cmd.strategy_id not in {b.strategy_id for b in state.limits.strategy_budgets}:
        raise PaperError("UNKNOWN_STRATEGY_REFERENCE")
    state = _valuation(_quotes(state, (cmd.quote,), cmd.at), cmd.at)
    if state.killed and cmd.side == "BUY":
        raise PaperError("LOSS_LIMIT")
    quote = _quote(state, cmd.instrument_id, cmd.at)
    if (quote.ask - quote.bid) / quote.bid * 10000 > state.limits.max_spread_bps:
        raise PaperError("SPREAD_LIMIT")
    spec = next(
        i for i in state.book.instruments if i.instrument_id == cmd.instrument_id
    )
    if not spec.is_open(cmd.at):
        raise PaperError("market closed at order admission")
    ceiling = (
        quote.ask * (1 + state.limits.max_slippage_bps / 10000) / spec.tick
    ).to_integral_value(rounding=ROUND_CEILING) * spec.tick
    if cmd.quantity * ceiling > state.limits.max_order_notional:
        raise PaperError("ORDER_NOTIONAL_LIMIT")
    recent = tuple(
        at
        for at in state.admissions
        if cmd.at - at < timedelta(seconds=state.limits.order_window_seconds)
    )
    if len(recent) >= state.limits.max_orders_per_window:
        raise PaperError("ORDER_FREQUENCY_LIMIT")
    reservation = Reservation(
        cmd.order_id,
        cmd.strategy_id,
        cmd.instrument_id,
        cmd.side,
        cmd.quantity,
        ceiling,
        cmd.commission_budget,
    )
    if reservation.cash + sum((r.cash for r in state.reservations), ZERO) > _cash(
        state
    ):
        raise PaperError("INSUFFICIENT_UNRESERVED_CASH")
    if cmd.side == "SELL":
        owned = sum(
            (
                h.quantity
                for h in state.holdings
                if h.strategy_id == cmd.strategy_id
                and h.instrument_id == cmd.instrument_id
            ),
            ZERO,
        )
        reserved = sum(
            (
                r.remaining
                for r in state.reservations
                if r.side == "SELL"
                and r.strategy_id == cmd.strategy_id
                and r.instrument_id == cmd.instrument_id
            ),
            ZERO,
        )
        if cmd.quantity > owned - reserved:
            raise PaperError("INSUFFICIENT_UNRESERVED_STRATEGY_POSITION")
    candidate = replace(state, reservations=(*state.reservations, reservation))
    if cmd.side == "BUY":
        gross, instruments, strategies = _exposures(candidate, cmd.at)
        limits = state.limits
        prospective_equity = (
            state.equity
            - sum((r.fee_remaining for r in candidate.reservations), ZERO)
            - sum(
                (
                    r.remaining
                    * max(
                        ZERO,
                        r.price_ceiling
                        - _quote(candidate, r.instrument_id, cmd.at).bid,
                    )
                    for r in candidate.reservations
                    if r.side == "BUY"
                ),
                ZERO,
            )
        )
        if (
            prospective_equity <= 0
            or (state.high_water - prospective_equity) / state.high_water
            >= limits.max_drawdown
            or state.inception_equity - prospective_equity >= limits.max_loss
        ):
            raise PaperError("PROSPECTIVE_LOSS_LIMIT")
        if gross > limits.max_gross_exposure:
            raise PaperError("GROSS_EXPOSURE_LIMIT")
        if any(
            value > limits.max_instrument_exposure
            or value > prospective_equity * limits.max_concentration
            for value in instruments.values()
        ):
            raise PaperError("INSTRUMENT_OR_CONCENTRATION_LIMIT")
        if any(
            strategies.get(b.strategy_id, ZERO) > b.maximum_exposure
            for b in limits.strategy_budgets
        ):
            raise PaperError("STRATEGY_EXPOSURE_LIMIT")
    event = a.SubmitOrder(
        event_id=cmd.command_id,
        expected_version=state.book.version,
        at=cmd.at,
        order_id=cmd.order_id,
        instrument_id=cmd.instrument_id,
        side=cmd.side,
        quantity=cmd.quantity,
        decision_at=cmd.decision_at,
    )
    return replace(_book_event(candidate, event), admissions=(*recent, cmd.at))


def _match(state: PaperSnapshot, cmd: Match) -> PaperSnapshot:
    reserve = _reservation(state, cmd.order_id)
    if not state.healthy or not state.reconciled:
        raise PaperError("UNRECONCILED_OR_UNHEALTHY")
    _positive(cmd.commission, zero=True)
    _positive(cmd.slippage_bps, zero=True)
    if (
        cmd.commission > reserve.fee_remaining
        or cmd.slippage_bps > state.limits.max_slippage_bps
    ):
        raise PaperError("FILL_COST_BUDGET")
    state = _quotes(state, (cmd.quote,), cmd.at)
    event = a.FillOrder(
        event_id=cmd.command_id,
        expected_version=state.book.version,
        at=cmd.at,
        order_id=cmd.order_id,
        quantity=cmd.quantity,
        quote=cmd.quote,
        commission=cmd.commission,
        slippage_bps=cmd.slippage_bps,
        max_quote_age_seconds=state.limits.max_quote_age_seconds,
    )
    updated = _book_event(state, event)
    fill = updated.book.fills[-1]
    if reserve.side == "BUY" and fill.price > reserve.price_ceiling:
        raise PaperError("FILL_PRICE_OUTSIDE_RESERVATION")
    remaining = reserve.remaining - cmd.quantity
    reservations = tuple(r for r in updated.reservations if r.order_id != cmd.order_id)
    if remaining:
        reservations += (
            replace(
                reserve,
                remaining=remaining,
                fee_remaining=reserve.fee_remaining - cmd.commission,
            ),
        )
    owned = next(
        (
            h.quantity
            for h in state.holdings
            if h.strategy_id == reserve.strategy_id
            and h.instrument_id == reserve.instrument_id
        ),
        ZERO,
    )
    quantity = owned + (cmd.quantity if reserve.side == "BUY" else -cmd.quantity)
    holdings = tuple(
        h
        for h in updated.holdings
        if not (
            h.strategy_id == reserve.strategy_id
            and h.instrument_id == reserve.instrument_id
        )
    )
    if quantity:
        holdings += (Holding(reserve.strategy_id, reserve.instrument_id, quantity),)
    return _valuation(
        replace(updated, reservations=reservations, holdings=holdings), cmd.at
    )


def _cancel(state: PaperSnapshot, cmd: Cancel) -> PaperSnapshot:
    cls: type[a.RequestCancel] | type[a.ConfirmCancel] | type[a.RejectOrder]
    if cmd.action == "REQUEST":
        cls = a.RequestCancel
    elif cmd.action == "CONFIRM":
        cls = a.ConfirmCancel
    elif cmd.action == "REJECT":
        event = a.RejectOrder(
            event_id=cmd.command_id,
            expected_version=state.book.version,
            at=cmd.at,
            order_id=cmd.order_id,
            reason="LOCAL_REJECTION",
        )
        return replace(
            _book_event(state, event),
            reservations=tuple(
                r for r in state.reservations if r.order_id != cmd.order_id
            ),
        )
    else:
        raise PaperError("INVALID_CANCEL_ACTION")
    updated = _book_event(
        state,
        cls(
            event_id=cmd.command_id,
            expected_version=state.book.version,
            at=cmd.at,
            order_id=cmd.order_id,
        ),
    )
    if cmd.action == "CONFIRM":
        updated = replace(
            updated,
            reservations=tuple(
                r for r in state.reservations if r.order_id != cmd.order_id
            ),
        )
    return updated


def _request_cancels(state: PaperSnapshot, cmd: PaperCommand) -> PaperSnapshot:
    for i, order in enumerate(state.book.orders):
        if order.side == "BUY" and order.status in {"OPEN", "PARTIALLY_FILLED"}:
            state = _book_event(
                state,
                a.RequestCancel(
                    event_id=f"EINT.{state.revision + 1}.{i}",
                    expected_version=state.book.version,
                    at=cmd.at,
                    order_id=order.order_id,
                ),
            )
    return state


def _transition(state: PaperSnapshot, cmd: PaperCommand) -> PaperSnapshot:
    if isinstance(cmd, Admit):
        result = _admit(state, cmd)
    elif isinstance(cmd, Match):
        result = _match(state, cmd)
    elif isinstance(cmd, Cancel):
        result = _cancel(state, cmd)
    elif isinstance(cmd, Mark):
        result = _valuation(_quotes(state, cmd.quotes, cmd.at), cmd.at)
    elif isinstance(cmd, Health):
        if type(cmd.healthy) is not bool:
            raise PaperError("INVALID_HEALTH")
        result = replace(state, healthy=cmd.healthy)
        if not cmd.healthy:
            result = replace(result, killed=True, kill_reason="CONNECTOR_UNHEALTHY")
    elif isinstance(cmd, Reconcile):
        _utc(cmd.observation_at)
        _positive(cmd.cash, zero=True)
        if (
            not state.at <= cmd.observation_at <= cmd.at
            or cmd.at - cmd.observation_at
            > timedelta(seconds=state.limits.max_quote_age_seconds)
        ):
            raise PaperError("STALE_RECONCILIATION")
        if not isinstance(cmd.positions, tuple) or len(cmd.positions) > 128:
            raise PaperError("INVALID_RECONCILIATION")
        for identity, quantity in cmd.positions:
            _id(identity)
            _positive(quantity)
        if len({i for i, _ in cmd.positions}) != len(cmd.positions):
            raise PaperError("DUPLICATE_POSITION")
        equal = cmd.cash == _cash(state) and dict(cmd.positions) == {
            p.instrument_id: p.quantity for p in state.book.positions
        }
        result = replace(
            state, reconciled=equal, reconciled_at=cmd.observation_at if equal else None
        )
        if not equal:
            result = replace(result, killed=True, kill_reason="RECONCILIATION_MISMATCH")
    elif isinstance(cmd, Kill):
        if type(cmd.enabled) is not bool:
            raise PaperError("INVALID_KILL")
        _id(cmd.reason)
        result = state
        if not cmd.enabled:
            result = _valuation(replace(state, killed=False, kill_reason=""), cmd.at)
            if (
                not result.reconciled
                or not result.healthy
                or result.reconciled_at is None
                or (
                    result.killed_at is not None
                    and result.reconciled_at < result.killed_at
                )
                or cmd.at - result.reconciled_at
                > timedelta(seconds=result.limits.max_quote_age_seconds)
                or result.killed
                or result.drawdown >= result.limits.max_drawdown
                or result.inception_equity - result.equity >= result.limits.max_loss
            ):
                raise PaperError("UNSAFE_KILL_RESET")
        result = replace(
            result, killed=cmd.enabled, kill_reason=cmd.reason if cmd.enabled else ""
        )
    else:
        raise PaperError("UNSUPPORTED_COMMAND")
    if result.killed:
        result = _request_cancels(result, cmd)
    return result


def _advance(state: PaperSnapshot, cmd: PaperCommand) -> PaperSnapshot:
    with localcontext(a.CONTEXT):
        baseline = state
        try:
            if cmd.at < state.at:
                raise PaperError("OUT_OF_ORDER")
            # Rejected new intents cannot erase fresh loss-limit evidence.
            if (
                isinstance(cmd, Admit)
                and cmd.quote.instrument_id == cmd.instrument_id
                and cmd.quote.available_at <= cmd.decision_at <= cmd.at
            ):
                baseline = _valuation(_quotes(state, (cmd.quote,), cmd.at), cmd.at)
                if baseline.killed:
                    baseline = _request_cancels(baseline, cmd)
            result = _transition(baseline, cmd)
            outcome = Outcome(cmd.command_id, "APPLIED", "")
        except (PaperError, a.AccountingError) as error:
            # All candidates are immutable; a rejected transition cannot leak economic writes.
            result = baseline
            outcome = Outcome(cmd.command_id, "REJECTED", str(error))
        except (TypeError, AttributeError, ArithmeticError) as error:
            result = baseline
            outcome = Outcome(
                cmd.command_id, "REJECTED", f"INVALID_COMMAND_{type(error).__name__}"
            )
        if result.killed and not state.killed:
            result = replace(result, killed_at=cmd.at)
        return replace(
            result,
            at=max(state.at, cmd.at),
            revision=state.revision + 1,
            outcomes=(*state.outcomes, outcome),
        )


class PaperEngine:
    """One bounded SQLite journal; no background thread or external submission path.

    `before_commit` is a host-owned fault-injection hook, never request configuration.
    Strategy/provenance identifiers are caller attestations, not registry validation.
    """

    def __init__(
        self, path: Path, *, before_commit: Callable[[], None] | None = None
    ) -> None:
        self.path = path
        self._before_commit = before_commit
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                    genesis BLOB NOT NULL, genesis_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS heads (
                    account_id TEXT PRIMARY KEY REFERENCES accounts(account_id),
                    revision INTEGER NOT NULL, chain_hash TEXT NOT NULL, state_hash TEXT NOT NULL,
                    audit_revision INTEGER NOT NULL, audit_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands (
                    account_id TEXT NOT NULL REFERENCES accounts(account_id), sequence INTEGER NOT NULL,
                    command_id TEXT NOT NULL, expected_revision INTEGER NOT NULL, payload BLOB NOT NULL,
                    fingerprint TEXT NOT NULL, previous_hash TEXT NOT NULL, chain_hash TEXT NOT NULL,
                    state_hash TEXT NOT NULL, PRIMARY KEY(account_id, sequence), UNIQUE(account_id, command_id));
                CREATE TABLE IF NOT EXISTS protocol_rejections (
                    account_id TEXT NOT NULL REFERENCES accounts(account_id), sequence INTEGER NOT NULL,
                    actual_revision INTEGER NOT NULL, expected_revision INTEGER NOT NULL,
                    payload BLOB NOT NULL, fingerprint TEXT NOT NULL, reason TEXT NOT NULL,
                    previous_hash TEXT NOT NULL, chain_hash TEXT NOT NULL,
                    PRIMARY KEY(account_id, sequence));
                CREATE TRIGGER IF NOT EXISTS accounts_no_update BEFORE UPDATE ON accounts BEGIN SELECT RAISE(ABORT, 'immutable genesis'); END;
                CREATE TRIGGER IF NOT EXISTS accounts_no_delete BEFORE DELETE ON accounts BEGIN SELECT RAISE(ABORT, 'immutable genesis'); END;
                CREATE TRIGGER IF NOT EXISTS commands_no_update BEFORE UPDATE ON commands BEGIN SELECT RAISE(ABORT, 'immutable journal'); END;
                CREATE TRIGGER IF NOT EXISTS commands_no_delete BEFORE DELETE ON commands BEGIN SELECT RAISE(ABORT, 'immutable journal'); END;
                CREATE TRIGGER IF NOT EXISTS protocol_no_update BEFORE UPDATE ON protocol_rejections BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
                CREATE TRIGGER IF NOT EXISTS protocol_no_delete BEFORE DELETE ON protocol_rejections BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self.path.exists() and self.path.stat().st_size > 67_108_864:
            raise PaperError("DATABASE_SIZE_LIMIT")
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            identity = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if (
                identity == 0
                and version == 0
                and not db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchone()
            ):
                db.execute("PRAGMA page_size=4096")
                db.execute("PRAGMA application_id=1363693616")
                db.execute("PRAGMA user_version=1")
            elif identity != APPLICATION_ID or version != 1:
                raise PaperError("UNSUPPORTED_DATABASE_FORMAT")
            if db.execute("PRAGMA page_size").fetchone()[0] != 4096:
                raise PaperError("UNSUPPORTED_DATABASE_PAGE_SIZE")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute("PRAGMA max_page_count=16384")
            with db:
                yield db
        finally:
            db.close()

    def create_account(
        self,
        account_id: str,
        owner_id: str,
        book: a.BookSnapshot,
        limits: RiskLimits,
        provenance: Provenance,
    ) -> PaperSnapshot:
        _id(account_id)
        _id(owner_id)
        limits.validate()
        provenance.validate()
        verified = a.initial_book(
            book.base_currency, book.at, book.instruments, book.cash
        )
        if (
            book != verified
            or len(book.cash) != 1
            or book.cash[0].currency != book.base_currency
            or any(i.quote_currency != book.base_currency for i in book.instruments)
        ):
            raise PaperError("UNSUPPORTED_INITIAL_BOOK_OR_MULTI_CURRENCY")
        cash = book.cash[0].amount
        _positive(cash)
        state = PaperSnapshot(
            account_id,
            owner_id,
            book,
            limits,
            provenance,
            book.at,
            cash,
            cash,
            cash,
            reconciled_at=book.at,
        )
        payload = _bytes(state)
        if len(payload) > MAX_PAYLOAD:
            raise PaperError("GENESIS_SIZE_LIMIT")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT count(*) FROM accounts").fetchone()[0] >= 32:
                raise PaperError("ACCOUNT_LIMIT")
            if db.execute(
                "SELECT 1 FROM accounts WHERE account_id=?", (account_id,)
            ).fetchone():
                raise PaperError("ACCOUNT_EXISTS")
            db.execute(
                "INSERT INTO accounts VALUES(?,?,?,?)",
                (account_id, owner_id, payload, _sha(payload)),
            )
            db.execute(
                "INSERT INTO heads VALUES(?,?,?,?,?,?)",
                (account_id, 0, _sha(payload), _sha(payload), 0, _sha(payload)),
            )
            self._fault()
        return state

    def _load(
        self, db: sqlite3.Connection, account_id: str, owner_id: str
    ) -> PaperSnapshot:
        row = db.execute(
            "SELECT * FROM accounts WHERE account_id=? AND owner_id=?",
            (account_id, owner_id),
        ).fetchone()
        if row is None:
            raise PaperError("ACCOUNT_NOT_FOUND")
        try:
            payload = bytes(row["genesis"])
            state = _decode(json.loads(payload))
            if (
                not isinstance(state, PaperSnapshot)
                or _bytes(state) != payload
                or _sha(payload) != row["genesis_hash"]
                or state.account_id != account_id
                or state.owner_id != owner_id
                or state.format_version != "v0-local-paper-1"
            ):
                raise PaperError("GENESIS_INTEGRITY")
            chain = _sha(payload)
            for entry in db.execute(
                "SELECT * FROM commands WHERE account_id=? ORDER BY sequence",
                (account_id,),
            ):
                raw = bytes(entry["payload"])
                cmd = _decode(json.loads(raw))
                if type(cmd) not in COMMAND_TYPES or _bytes(cmd) != raw:
                    raise PaperError("COMMAND_INTEGRITY")
                cmd = cast(PaperCommand, cmd)
                fingerprint = _sha(
                    str(entry["expected_revision"]).encode() + b":" + raw
                )
                next_chain = _sha(chain.encode() + b":" + fingerprint.encode())
                if (
                    entry["sequence"] != state.revision + 1
                    or entry["expected_revision"] != state.revision
                    or cmd.command_id != entry["command_id"]
                    or entry["fingerprint"] != fingerprint
                    or entry["previous_hash"] != chain
                    or entry["chain_hash"] != next_chain
                ):
                    raise PaperError("JOURNAL_INTEGRITY")
                state = _advance(state, cmd)
                if _sha(_bytes(state)) != entry["state_hash"]:
                    raise PaperError("REPLAY_DIVERGENCE")
                chain = next_chain
            head = db.execute(
                "SELECT * FROM heads WHERE account_id=?", (account_id,)
            ).fetchone()
            if (
                head is None
                or head["revision"] != state.revision
                or head["chain_hash"] != chain
                or head["state_hash"] != _sha(_bytes(state))
            ):
                raise PaperError("HEAD_INTEGRITY")
            return state
        except (
            TypeError,
            KeyError,
            ValueError,
            ArithmeticError,
            RecursionError,
        ) as error:
            raise PaperError("STORED_LEDGER_INTEGRITY") from error

    def load(self, account_id: str, owner_id: str) -> PaperSnapshot:
        _id(account_id)
        _id(owner_id)
        with self._connect() as db:
            db.execute("BEGIN")
            return self._load(db, account_id, owner_id)

    def protocol_rejections(
        self, account_id: str, owner_id: str
    ) -> tuple[ProtocolRejection, ...]:
        """Owner-only append-only audit of CAS/conflicting-ID failures, separate from economic revision."""
        _id(account_id)
        _id(owner_id)
        with self._connect() as db:
            db.execute("BEGIN")
            state = self._load(db, account_id, owner_id)
            previous = db.execute(
                "SELECT genesis_hash FROM accounts WHERE account_id=?", (account_id,)
            ).fetchone()[0]
            results: list[ProtocolRejection] = []
            for row in db.execute(
                "SELECT * FROM protocol_rejections WHERE account_id=? ORDER BY sequence",
                (account_id,),
            ):
                raw = bytes(row["payload"])
                try:
                    command = _decode(json.loads(raw))
                    if type(command) not in COMMAND_TYPES or _bytes(command) != raw:
                        raise PaperError("PROTOCOL_AUDIT_INTEGRITY")
                    command = cast(PaperCommand, command)
                    fingerprint = _sha(
                        str(row["expected_revision"]).encode() + b":" + raw
                    )
                    chain = _sha(
                        f"{previous}:{fingerprint}:{row['actual_revision']}:{row['reason']}".encode()
                    )
                    if (
                        row["sequence"] != len(results) + 1
                        or row["actual_revision"] > state.revision
                        or row["fingerprint"] != fingerprint
                        or row["previous_hash"] != previous
                        or row["chain_hash"] != chain
                    ):
                        raise PaperError("PROTOCOL_AUDIT_INTEGRITY")
                    results.append(
                        ProtocolRejection(
                            command.command_id,
                            command.at,
                            row["reason"],
                            row["expected_revision"],
                            row["actual_revision"],
                            fingerprint,
                        )
                    )
                    previous = chain
                except (
                    TypeError,
                    KeyError,
                    ValueError,
                    ArithmeticError,
                    RecursionError,
                ) as error:
                    raise PaperError("PROTOCOL_AUDIT_INTEGRITY") from error
            head = db.execute(
                "SELECT audit_revision,audit_hash FROM heads WHERE account_id=?",
                (account_id,),
            ).fetchone()
            if head["audit_revision"] != len(results) or head["audit_hash"] != previous:
                raise PaperError("PROTOCOL_AUDIT_INTEGRITY")
            return tuple(results)

    def _reject_protocol(
        self,
        db: sqlite3.Connection,
        state: PaperSnapshot,
        raw: bytes,
        fingerprint: str,
        expected: int,
        reason: str,
    ) -> None:
        prior = db.execute(
            "SELECT sequence, chain_hash FROM protocol_rejections WHERE account_id=? ORDER BY sequence DESC LIMIT 1",
            (state.account_id,),
        ).fetchone()
        sequence = prior["sequence"] + 1 if prior else 1
        if sequence > MAX_COMMANDS:
            raise PaperError("PROTOCOL_AUDIT_CAPACITY")
        self._capacity(db, len(raw))
        previous = (
            prior["chain_hash"]
            if prior
            else db.execute(
                "SELECT genesis_hash FROM accounts WHERE account_id=?",
                (state.account_id,),
            ).fetchone()[0]
        )
        head = db.execute(
            "SELECT audit_revision,audit_hash FROM heads WHERE account_id=?",
            (state.account_id,),
        ).fetchone()
        if head["audit_revision"] != sequence - 1 or head["audit_hash"] != previous:
            raise PaperError("PROTOCOL_AUDIT_INTEGRITY")
        chain = _sha(f"{previous}:{fingerprint}:{state.revision}:{reason}".encode())
        db.execute(
            "INSERT INTO protocol_rejections VALUES(?,?,?,?,?,?,?,?,?)",
            (
                state.account_id,
                sequence,
                state.revision,
                expected,
                raw,
                fingerprint,
                reason,
                previous,
                chain,
            ),
        )
        db.execute(
            "UPDATE heads SET audit_revision=?,audit_hash=? WHERE account_id=?",
            (sequence, chain, state.account_id),
        )
        self._fault()
        # Commit the audit before raising: economic head and reservations never changed.
        db.commit()
        raise PaperError(reason)

    @staticmethod
    def _capacity(db: sqlite3.Connection, additional_bytes: int) -> None:
        used = db.execute(
            "SELECT (SELECT coalesce(sum(length(payload)),0) FROM commands) + (SELECT coalesce(sum(length(payload)),0) FROM protocol_rejections)"
        ).fetchone()[0]
        if used + additional_bytes > MAX_TOTAL_BYTES:
            raise PaperError("JOURNAL_CAPACITY")

    def process(
        self,
        account_id: str,
        owner_id: str,
        command: PaperCommand,
        expected_revision: int,
    ) -> PaperSnapshot:
        _id(account_id)
        _id(owner_id)
        if type(command) not in COMMAND_TYPES:
            raise PaperError("UNSUPPORTED_COMMAND")
        _id(command.command_id)
        if command.command_id.startswith("EINT."):
            raise PaperError("RESERVED_COMMAND_NAMESPACE")
        _utc(command.at)
        if (
            type(expected_revision) is not int
            or not 0 <= expected_revision <= MAX_COMMANDS
        ):
            raise PaperError("INVALID_REVISION")
        raw = _bytes(command)
        fingerprint = _sha(str(expected_revision).encode() + b":" + raw)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._load(db, account_id, owner_id)
            duplicate = db.execute(
                "SELECT fingerprint FROM commands WHERE account_id=? AND command_id=?",
                (account_id, command.command_id),
            ).fetchone()
            if duplicate is not None:
                if duplicate["fingerprint"] != fingerprint:
                    self._reject_protocol(
                        db,
                        state,
                        raw,
                        fingerprint,
                        expected_revision,
                        "CONFLICTING_COMMAND_ID",
                    )
                return state
            if expected_revision != state.revision:
                self._reject_protocol(
                    db, state, raw, fingerprint, expected_revision, "STALE_REVISION"
                )
            if state.revision >= MAX_COMMANDS:
                raise PaperError("JOURNAL_CAPACITY")
            self._capacity(db, len(raw))
            result = _advance(state, command)
            previous = db.execute(
                "SELECT chain_hash FROM heads WHERE account_id=?", (account_id,)
            ).fetchone()[0]
            chain = _sha(previous.encode() + b":" + fingerprint.encode())
            state_hash = _sha(_bytes(result))
            db.execute(
                "INSERT INTO commands VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    account_id,
                    result.revision,
                    command.command_id,
                    expected_revision,
                    raw,
                    fingerprint,
                    previous,
                    chain,
                    state_hash,
                ),
            )
            db.execute(
                "UPDATE heads SET revision=?, chain_hash=?, state_hash=? WHERE account_id=?",
                (result.revision, chain, state_hash, account_id),
            )
            self._fault()
            return result

    def _fault(self) -> None:
        if self._before_commit is not None:
            self._before_commit()
