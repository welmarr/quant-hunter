"""Pure, bounded local-paper accounting; no persistence or execution authority.

Cash-funded long spot holdings only. Derivative helpers below are separate
arithmetic contracts, not margin, settlement, liquidation or roll engines.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    localcontext,
)

ZERO = Decimal(0)
ONE = Decimal(1)
CONTEXT = Context(prec=38, rounding=ROUND_HALF_EVEN)
OPEN = {"OPEN", "PARTIALLY_FILLED", "CANCEL_PENDING"}
MAX_EVENTS = 10_000


class AccountingError(ValueError):
    """Unsupported, unavailable or inconsistent accounting transition."""


def _id(value: str) -> None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", value) is None
    ):
        raise AccountingError("invalid bounded identifier")


def _currency(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3,8}", value) is None:
        raise AccountingError("invalid currency")


def _utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is not UTC:
        raise AccountingError("datetime.UTC required")


def _number(value: Decimal, *, positive: bool = False, signed: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise AccountingError("finite Decimal required")
    exponent = value.as_tuple().exponent
    if (
        not isinstance(exponent, int)
        or not -18 <= exponent <= 18
        or len(value.as_tuple().digits) > 18
        or value.copy_abs() > Decimal("1e18")
        or (not signed and value < 0)
        or (positive and value <= 0)
    ):
        raise AccountingError("Decimal outside supported input bounds")


def _result(value: Decimal) -> Decimal:
    exponent = value.as_tuple().exponent
    if (
        not value.is_finite()
        or value.copy_abs() > Decimal("1e30")
        or not isinstance(exponent, int)
        or not -76 <= exponent <= 38
        or len(value.as_tuple().digits) > 38
    ):
        raise AccountingError("accounting result outside supported bounds")
    return value


@dataclass(frozen=True)
class TradingWindow:
    opens: datetime
    closes: datetime

    def __post_init__(self) -> None:
        _utc(self.opens)
        _utc(self.closes)
        if self.opens >= self.closes:
            raise AccountingError("empty trading window")


@dataclass(frozen=True)
class InstrumentSpec:
    instrument_id: str
    symbol: str
    kind: str
    quote_currency: str
    lot: Decimal
    tick: Decimal
    sessions: tuple[TradingWindow, ...]
    base_currency: str | None = None

    def __post_init__(self) -> None:
        _id(self.instrument_id)
        _id(self.symbol)
        _currency(self.quote_currency)
        if self.kind not in {"EQUITY", "FX_SPOT", "CRYPTO_SPOT"}:
            raise AccountingError(
                "UNSUPPORTED: derivative, short and leverage execution"
            )
        if self.base_currency is not None:
            _currency(self.base_currency)
        if self.kind != "EQUITY" and (
            self.base_currency is None or self.base_currency == self.quote_currency
        ):
            raise AccountingError("distinct spot base and quote currencies required")
        _number(self.lot, positive=True)
        _number(self.tick, positive=True)
        if not isinstance(self.sessions, tuple) or not 1 <= len(self.sessions) <= 2048:
            raise AccountingError("explicit bounded trading calendar required")
        for i, session in enumerate(self.sessions):
            session.__post_init__()
            if i and session.opens < self.sessions[i - 1].closes:
                raise AccountingError("unordered or overlapping trading windows")

    def is_open(self, at: datetime) -> bool:
        return any(session.opens <= at < session.closes for session in self.sessions)


@dataclass(frozen=True)
class Quote:
    instrument_id: str
    at: datetime
    available_at: datetime
    bid: Decimal
    ask: Decimal
    price_basis: str = "UNADJUSTED"

    def __post_init__(self) -> None:
        _id(self.instrument_id)
        _utc(self.at)
        _utc(self.available_at)
        _number(self.bid, positive=True)
        _number(self.ask, positive=True)
        if self.available_at < self.at or self.bid > self.ask:
            raise AccountingError("invalid quote timing or spread")
        if self.price_basis != "UNADJUSTED":
            raise AccountingError(
                "adjusted/indicative/mid prices are not executable quotes"
            )


@dataclass(frozen=True)
class FXQuote:
    base_currency: str
    quote_currency: str
    at: datetime
    available_at: datetime
    bid: Decimal
    ask: Decimal

    def __post_init__(self) -> None:
        _currency(self.base_currency)
        _currency(self.quote_currency)
        _utc(self.at)
        _utc(self.available_at)
        _number(self.bid, positive=True)
        _number(self.ask, positive=True)
        if (
            self.base_currency == self.quote_currency
            or self.bid > self.ask
            or self.available_at < self.at
        ):
            raise AccountingError("invalid directed FX quote")


@dataclass(frozen=True)
class CashBalance:
    currency: str
    amount: Decimal


@dataclass(frozen=True)
class Position:
    instrument_id: str
    quantity: Decimal
    cost_basis: Decimal


@dataclass(frozen=True)
class Order:
    order_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    filled: Decimal
    decision_at: datetime
    submitted_at: datetime
    status: str
    reason: str | None = None
    cancel_requested_at: datetime | None = None


@dataclass(frozen=True)
class Fill:
    event_id: str
    order_id: str
    at: datetime
    quantity: Decimal
    market_price: Decimal
    price: Decimal
    commission: Decimal
    adverse_slippage: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True)
class DividendReceivable:
    dividend_id: str
    instrument_id: str
    quantity: Decimal
    amount: Decimal
    ex_at: datetime
    payment_at: datetime
    paid: bool = False


@dataclass(frozen=True)
class Receipt:
    event_id: str
    digest: str


@dataclass(frozen=True)
class CorporateAction:
    action_id: str
    instrument_id: str
    kind: str
    at: datetime


@dataclass(frozen=True)
class Liquidation:
    event_id: str
    instrument_id: str
    quantity: Decimal
    proceeds: Decimal
    commission: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True)
class BookSnapshot:
    base_currency: str
    at: datetime
    instruments: tuple[InstrumentSpec, ...]
    cash: tuple[CashBalance, ...]
    positions: tuple[Position, ...] = ()
    orders: tuple[Order, ...] = ()
    fills: tuple[Fill, ...] = ()
    dividends: tuple[DividendReceivable, ...] = ()
    delisted: tuple[str, ...] = ()
    corporate_actions: tuple[CorporateAction, ...] = ()
    liquidations: tuple[Liquidation, ...] = ()
    receipts: tuple[Receipt, ...] = ()
    version: int = 0
    format_version: str = "v0-spot-accounting-1"


@dataclass(frozen=True, kw_only=True)
class Event:
    event_id: str
    expected_version: int
    at: datetime


@dataclass(frozen=True, kw_only=True)
class SubmitOrder(Event):
    order_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    decision_at: datetime
    order_type: str = "MARKET"


@dataclass(frozen=True, kw_only=True)
class FillOrder(Event):
    order_id: str
    quantity: Decimal
    quote: Quote
    commission: Decimal
    slippage_bps: Decimal
    max_quote_age_seconds: int


@dataclass(frozen=True, kw_only=True)
class RequestCancel(Event):
    order_id: str


@dataclass(frozen=True, kw_only=True)
class ConfirmCancel(Event):
    order_id: str


@dataclass(frozen=True, kw_only=True)
class RejectOrder(Event):
    order_id: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class Split(Event):
    instrument_id: str
    ratio: Decimal
    effective_at: datetime
    available_at: datetime
    open_order_policy: str
    price_basis: str = "UNADJUSTED"


@dataclass(frozen=True, kw_only=True)
class Dividend(Event):
    dividend_id: str
    instrument_id: str
    amount_per_share: Decimal
    ex_at: datetime
    payment_at: datetime
    available_at: datetime
    price_basis: str = "UNADJUSTED"


@dataclass(frozen=True, kw_only=True)
class PayDividend(Event):
    dividend_id: str


@dataclass(frozen=True, kw_only=True)
class CashLiquidation(Event):
    instrument_id: str
    quantity: Decimal
    cash_per_unit: Decimal
    commission: Decimal
    available_at: datetime
    delist: bool


@dataclass(frozen=True, kw_only=True)
class FinancingCharge(Event):
    currency: str
    amount: Decimal
    period_start: datetime
    period_end: datetime
    treatment: str


@dataclass(frozen=True, kw_only=True)
class ConvertCash(Event):
    from_currency: str
    to_currency: str
    amount: Decimal
    quote: FXQuote
    commission_in_target: Decimal
    max_quote_age_seconds: int


type BookEvent = (
    SubmitOrder
    | FillOrder
    | RequestCancel
    | ConfirmCancel
    | RejectOrder
    | Split
    | Dividend
    | PayDividend
    | CashLiquidation
    | FinancingCharge
    | ConvertCash
)
_EVENT_TYPES = (
    SubmitOrder,
    FillOrder,
    RequestCancel,
    ConfirmCancel,
    RejectOrder,
    Split,
    Dividend,
    PayDividend,
    CashLiquidation,
    FinancingCharge,
    ConvertCash,
)


def _encode(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "type": type(value).__name__,
            **{f.name: _encode(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def event_digest(event: BookEvent) -> str:
    """Exact typed payload identity, including Decimal representation and CAS version."""
    if type(event) not in _EVENT_TYPES:
        raise AccountingError("unsupported event type")
    encoded = json.dumps(
        _encode(event),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    if len(encoded) > 16_384:
        raise AccountingError("oversized event")
    return "sha256:" + hashlib.sha256(encoded.encode("ascii")).hexdigest()


def initial_book(
    base_currency: str,
    at: datetime,
    instruments: tuple[InstrumentSpec, ...],
    cash: tuple[CashBalance, ...],
) -> BookSnapshot:
    _currency(base_currency)
    _utc(at)
    if not isinstance(instruments, tuple) or not 1 <= len(instruments) <= 128:
        raise AccountingError("bounded instrument tuple required")
    for instrument in instruments:
        instrument.__post_init__()
    if len({i.instrument_id for i in instruments}) != len(instruments):
        raise AccountingError("duplicate instrument identity")
    if not isinstance(cash, tuple) or not 1 <= len(cash) <= 32:
        raise AccountingError("bounded cash tuple required")
    for balance in cash:
        _currency(balance.currency)
        _number(balance.amount)
    if len({c.currency for c in cash}) != len(cash):
        raise AccountingError("duplicate currency balance")
    return BookSnapshot(
        base_currency, at, instruments, tuple(sorted(cash, key=lambda c: c.currency))
    )


def _instrument(book: BookSnapshot, instrument_id: str) -> InstrumentSpec:
    for instrument in book.instruments:
        if instrument.instrument_id == instrument_id:
            return instrument
    raise AccountingError("unknown instrument")


def _position(book: BookSnapshot, instrument_id: str) -> Position:
    return next(
        (p for p in book.positions if p.instrument_id == instrument_id),
        Position(instrument_id, ZERO, ZERO),
    )


def _positions(book: BookSnapshot, position: Position) -> BookSnapshot:
    retained = tuple(
        p for p in book.positions if p.instrument_id != position.instrument_id
    )
    if position.quantity:
        retained += (position,)
    return replace(
        book, positions=tuple(sorted(retained, key=lambda p: p.instrument_id))
    )


def _cash(book: BookSnapshot, currency: str, change: Decimal) -> BookSnapshot:
    amount = (
        next((c.amount for c in book.cash if c.currency == currency), ZERO) + change
    )
    _result(amount)
    if amount < 0:
        raise AccountingError("insufficient cash; leverage unsupported")
    retained = (
        *(c for c in book.cash if c.currency != currency),
        CashBalance(currency, amount),
    )
    if len(retained) > 32:
        raise AccountingError("currency count exceeded")
    return replace(book, cash=tuple(sorted(retained, key=lambda c: c.currency)))


def _order(book: BookSnapshot, order_id: str) -> Order:
    for order in book.orders:
        if order.order_id == order_id:
            return order
    raise AccountingError("unknown order")


def _orders(book: BookSnapshot, order: Order) -> BookSnapshot:
    return replace(
        book,
        orders=tuple(order if o.order_id == order.order_id else o for o in book.orders),
    )


def _fresh(at: datetime, available: datetime, now: datetime, seconds: int) -> None:
    _utc(now)
    if type(seconds) is not int or not 0 <= seconds <= 86400:
        raise AccountingError("bounded explicit quote age required")
    if not at <= available <= now or now - at > timedelta(seconds=seconds):
        raise AccountingError("unavailable or stale quote")


def _corporate(
    book: BookSnapshot,
    event: Split | Dividend,
    effective: datetime,
    available: datetime,
    basis: str,
) -> None:
    _utc(effective)
    _utc(available)
    if basis != "UNADJUSTED":
        raise AccountingError(
            "corporate action with adjusted prices would double count"
        )
    if available > event.at or effective != event.at:
        raise AccountingError(
            "corporate action must be known at its effective event; no retroactive rewrite"
        )
    relevant = {
        order.order_id
        for order in book.orders
        if order.instrument_id == event.instrument_id
    }
    if any(
        order.instrument_id == event.instrument_id and order.submitted_at >= effective
        for order in book.orders
    ) or any(fill.order_id in relevant and fill.at >= effective for fill in book.fills):
        raise AccountingError(
            "corporate action must precede this instrument's ex-time orders and fills"
        )


def _cancel_instrument(
    book: BookSnapshot, instrument_id: str, reason: str
) -> BookSnapshot:
    return replace(
        book,
        orders=tuple(
            replace(o, status="CANCELED", reason=reason)
            if o.instrument_id == instrument_id and o.status in OPEN
            else o
            for o in book.orders
        ),
    )


def _after_action(book: BookSnapshot, quote: Quote) -> None:
    if any(
        action.instrument_id == quote.instrument_id and quote.at < action.at
        for action in book.corporate_actions
    ):
        raise AccountingError("quote predates corporate-action price basis")


def _dispose(
    book: BookSnapshot, spec: InstrumentSpec, quantity: Decimal, proceeds: Decimal
) -> tuple[BookSnapshot, Decimal]:
    position = _position(book, spec.instrument_id)
    if quantity > position.quantity:
        raise AccountingError("insufficient position; short sale unsupported")
    allocated = (
        position.cost_basis
        if quantity == position.quantity
        else position.cost_basis * quantity / position.quantity
    )
    book = _positions(
        book,
        Position(
            spec.instrument_id,
            position.quantity - quantity,
            position.cost_basis - allocated,
        ),
    )
    return _cash(book, spec.quote_currency, proceeds), proceeds - allocated


def _transition(book: BookSnapshot, event: BookEvent) -> BookSnapshot:
    if isinstance(event, SubmitOrder):
        _id(event.order_id)
        _utc(event.decision_at)
        _number(event.quantity, positive=True)
        spec = _instrument(book, event.instrument_id)
        if event.order_type != "MARKET" or event.side not in {"BUY", "SELL"}:
            raise AccountingError("UNSUPPORTED order type or side")
        if event.decision_at > event.at or event.quantity % spec.lot:
            raise AccountingError("invalid decision timing or lot size")
        if any(o.order_id == event.order_id for o in book.orders):
            raise AccountingError("order identity already exists")
        reason = (
            "DELISTED"
            if event.instrument_id in book.delisted
            else "MARKET_CLOSED"
            if not spec.is_open(event.at)
            else None
        )
        order = Order(
            event.order_id,
            event.instrument_id,
            event.side,
            event.quantity,
            ZERO,
            event.decision_at,
            event.at,
            "REJECTED" if reason else "OPEN",
            reason,
        )
        return replace(book, orders=(*book.orders, order))
    if isinstance(event, FillOrder):
        order = _order(book, event.order_id)
        spec = _instrument(book, order.instrument_id)
        event.quote.__post_init__()
        _after_action(book, event.quote)
        _number(event.quantity, positive=True)
        _number(event.commission)
        _number(event.slippage_bps)
        _fresh(
            event.quote.at,
            event.quote.available_at,
            event.at,
            event.max_quote_age_seconds,
        )
        if (
            order.status not in OPEN
            or not spec.is_open(event.at)
            or order.instrument_id in book.delisted
        ):
            raise AccountingError("order not fillable")
        if (
            event.quote.instrument_id != order.instrument_id
            or event.quote.at <= order.decision_at
            or event.at <= order.submitted_at
        ):
            raise AccountingError(
                "fill must use strictly later, matching market information"
            )
        if event.quantity % spec.lot or event.quantity > order.quantity - order.filled:
            raise AccountingError("invalid partial-fill quantity")
        if (
            event.quote.bid % spec.tick
            or event.quote.ask % spec.tick
            or event.slippage_bps >= 10000
        ):
            raise AccountingError("invalid quote tick or slippage")
        market = event.quote.ask if order.side == "BUY" else event.quote.bid
        adverse = market * event.slippage_bps / Decimal(10000)
        unrounded = market + adverse if order.side == "BUY" else market - adverse
        rounding = ROUND_CEILING if order.side == "BUY" else ROUND_FLOOR
        price = (unrounded / spec.tick).to_integral_value(rounding=rounding) * spec.tick
        if price <= 0:
            raise AccountingError("nonpositive execution price")
        realized = ZERO
        if order.side == "BUY":
            position = _position(book, spec.instrument_id)
            cost = _result(price * event.quantity + event.commission)
            book = _cash(book, spec.quote_currency, -cost)
            book = _positions(
                book,
                Position(
                    spec.instrument_id,
                    _result(position.quantity + event.quantity),
                    _result(position.cost_basis + cost),
                ),
            )
        else:
            book, realized = _dispose(
                book,
                spec,
                event.quantity,
                _result(price * event.quantity - event.commission),
            )
        filled = order.filled + event.quantity
        status = (
            "FILLED"
            if filled == order.quantity
            else "CANCEL_PENDING"
            if order.status == "CANCEL_PENDING"
            else "PARTIALLY_FILLED"
        )
        book = _orders(book, replace(order, filled=filled, status=status))
        fill = Fill(
            event.event_id,
            event.order_id,
            event.at,
            event.quantity,
            market,
            price,
            event.commission,
            abs(price - market) * event.quantity,
            realized,
        )
        return replace(book, fills=(*book.fills, fill))
    if isinstance(event, (RequestCancel, ConfirmCancel, RejectOrder)):
        order = _order(book, event.order_id)
        if isinstance(event, RequestCancel):
            if order.status not in {"OPEN", "PARTIALLY_FILLED"}:
                raise AccountingError("order cannot request cancel")
            return _orders(
                book,
                replace(order, status="CANCEL_PENDING", cancel_requested_at=event.at),
            )
        if isinstance(event, ConfirmCancel):
            if order.cancel_requested_at is None:
                raise AccountingError("cancel was not requested")
            if order.status == "FILLED":
                return _orders(book, replace(order, reason="CANCEL_TOO_LATE"))
            if order.status != "CANCEL_PENDING":
                raise AccountingError("cancel was not pending")
            return _orders(book, replace(order, status="CANCELED"))
        _id(event.reason)
        if order.status not in OPEN:
            raise AccountingError("terminal order cannot be rejected")
        return _orders(book, replace(order, status="REJECTED", reason=event.reason))
    if isinstance(event, Split):
        spec = _instrument(book, event.instrument_id)
        _corporate(
            book, event, event.effective_at, event.available_at, event.price_basis
        )
        _number(event.ratio, positive=True)
        if spec.kind != "EQUITY" or event.open_order_policy != "CANCEL_OPEN":
            raise AccountingError(
                "unsupported split instrument or order adjustment policy"
            )
        if any(
            action.instrument_id == spec.instrument_id
            and action.kind == "SPLIT"
            and action.at == event.at
            for action in book.corporate_actions
        ):
            raise AccountingError("split already applied at this effective time")
        position = _position(book, spec.instrument_id)
        quantity = _result(position.quantity * event.ratio)
        if quantity % spec.lot:
            raise AccountingError(
                "fractional split holding requires explicit cash-in-lieu support"
            )
        book = _positions(book, replace(position, quantity=quantity))
        book = _cancel_instrument(book, spec.instrument_id, "SPLIT_CANCEL_POLICY")
        return replace(
            book,
            corporate_actions=(
                *book.corporate_actions,
                CorporateAction(event.event_id, spec.instrument_id, "SPLIT", event.at),
            ),
        )
    if isinstance(event, Dividend):
        _id(event.dividend_id)
        spec = _instrument(book, event.instrument_id)
        _corporate(book, event, event.ex_at, event.available_at, event.price_basis)
        _utc(event.payment_at)
        _number(event.amount_per_share)
        if spec.kind != "EQUITY" or event.payment_at < event.ex_at:
            raise AccountingError("unsupported dividend or payment before ex-date")
        if any(d.dividend_id == event.dividend_id for d in book.dividends):
            raise AccountingError("dividend entitlement already recorded")
        quantity = _position(book, spec.instrument_id).quantity
        dividend = DividendReceivable(
            event.dividend_id,
            spec.instrument_id,
            quantity,
            _result(quantity * event.amount_per_share),
            event.ex_at,
            event.payment_at,
        )
        return replace(
            book,
            dividends=(*book.dividends, dividend),
            corporate_actions=(
                *book.corporate_actions,
                CorporateAction(
                    event.dividend_id, spec.instrument_id, "DIVIDEND", event.at
                ),
            ),
        )
    if isinstance(event, PayDividend):
        payable = next(
            (d for d in book.dividends if d.dividend_id == event.dividend_id), None
        )
        if payable is None or payable.paid or event.at < payable.payment_at:
            raise AccountingError("dividend missing, already paid or not payable yet")
        spec = _instrument(book, payable.instrument_id)
        book = _cash(book, spec.quote_currency, payable.amount)
        return replace(
            book,
            dividends=tuple(
                replace(d, paid=True) if d.dividend_id == event.dividend_id else d
                for d in book.dividends
            ),
        )
    if isinstance(event, CashLiquidation):
        spec = _instrument(book, event.instrument_id)
        _utc(event.available_at)
        _number(event.quantity, positive=True)
        _number(event.cash_per_unit)
        _number(event.commission)
        if (
            type(event.delist) is not bool
            or event.available_at > event.at
            or event.quantity % spec.lot
        ):
            raise AccountingError("invalid or unavailable liquidation")
        position = _position(book, spec.instrument_id)
        if event.delist and event.quantity != position.quantity:
            raise AccountingError("delisting must account for all remaining units")
        proceeds = _result(event.quantity * event.cash_per_unit - event.commission)
        book, pnl = _dispose(book, spec, event.quantity, proceeds)
        book = replace(
            book,
            liquidations=(
                *book.liquidations,
                Liquidation(
                    event.event_id,
                    spec.instrument_id,
                    event.quantity,
                    proceeds,
                    event.commission,
                    pnl,
                ),
            ),
        )
        book = _cancel_instrument(book, spec.instrument_id, "LIQUIDATION_CANCEL_POLICY")
        if event.delist:
            book = replace(
                book, delisted=tuple(sorted(set((*book.delisted, spec.instrument_id))))
            )
        return book
    if isinstance(event, FinancingCharge):
        _currency(event.currency)
        _number(event.amount)
        _utc(event.period_start)
        _utc(event.period_end)
        if (
            not event.period_start < event.period_end <= event.at
            or event.treatment != "EXPLICIT_SPOT_FINANCING_CHARGE"
        ):
            raise AccountingError(
                "explicit completed-period spot financing treatment required"
            )
        return _cash(book, event.currency, -event.amount)
    if isinstance(event, ConvertCash):
        _number(event.amount, positive=True)
        _number(event.commission_in_target)
        amount = convert_value(
            event.amount,
            event.from_currency,
            event.to_currency,
            event.quote,
            as_of=event.at,
            max_quote_age_seconds=event.max_quote_age_seconds,
        )
        if amount < event.commission_in_target:
            raise AccountingError("conversion proceeds below commission")
        book = _cash(book, event.from_currency, -event.amount)
        return _cash(book, event.to_currency, amount - event.commission_in_target)
    raise AccountingError("unsupported event")


def apply_event(book: BookSnapshot, event: BookEvent) -> BookSnapshot:
    """Atomic pure transition. Caller owns serialized durable CAS publication.

    An exact old event returns the CURRENT snapshot, never the historical state.
    Failed validation raises without changing the frozen input snapshot.
    """
    _id(event.event_id)
    _utc(event.at)
    digest = event_digest(event)
    prior = next((r for r in book.receipts if r.event_id == event.event_id), None)
    if prior is not None:
        if prior.digest != digest:
            raise AccountingError("conflicting event identity reuse")
        return book
    if book.format_version != "v0-spot-accounting-1" or book.version != len(
        book.receipts
    ):
        raise AccountingError("unsupported or inconsistent snapshot version")
    if (
        type(event.expected_version) is not int
        or event.expected_version != book.version
    ):
        raise AccountingError("stale snapshot version")
    if book.version >= MAX_EVENTS or event.at < book.at:
        raise AccountingError("event limit or unordered event")
    with localcontext(CONTEXT):
        updated = _transition(book, event)
        return replace(
            updated,
            at=event.at,
            receipts=(*book.receipts, Receipt(event.event_id, digest)),
            version=book.version + 1,
        )


def convert_value(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    quote: FXQuote,
    *,
    as_of: datetime,
    max_quote_age_seconds: int,
) -> Decimal:
    """Liquidation value: sell assets at bid, buy liabilities at ask; invert sides."""
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise AccountingError("finite Decimal amount required")
    _result(amount)
    _currency(from_currency)
    _currency(to_currency)
    quote.__post_init__()
    _fresh(quote.at, quote.available_at, as_of, max_quote_age_seconds)
    with localcontext(CONTEXT):
        if (from_currency, to_currency) == (quote.base_currency, quote.quote_currency):
            return _result(amount * (quote.bid if amount >= 0 else quote.ask))
        if (from_currency, to_currency) == (quote.quote_currency, quote.base_currency):
            return _result(amount / (quote.ask if amount >= 0 else quote.bid))
    raise AccountingError("FX quote does not bind requested directed currencies")


@dataclass(frozen=True)
class Valuation:
    at: datetime
    base_currency: str
    cash_value: Decimal
    holdings_value: Decimal
    receivables_value: Decimal
    equity: Decimal


def value_book(
    book: BookSnapshot,
    marks: tuple[Quote, ...],
    fx_quotes: tuple[FXQuote, ...],
    *,
    as_of: datetime,
    max_quote_age_seconds: int,
) -> Valuation:
    """Conservative executable-side marks; excludes hypothetical disposal fees."""
    _utc(as_of)
    if as_of < book.at or len(marks) > 128 or len(fx_quotes) > 32:
        raise AccountingError("invalid valuation time or input bounds")
    if len({q.instrument_id for q in marks}) != len(marks):
        raise AccountingError("ambiguous instrument quote")

    def base(amount: Decimal, currency: str) -> Decimal:
        if currency == book.base_currency:
            return amount
        matches = [
            q
            for q in fx_quotes
            if {q.base_currency, q.quote_currency} == {currency, book.base_currency}
        ]
        if len(matches) != 1:
            raise AccountingError("missing or ambiguous FX quote")
        return convert_value(
            amount,
            currency,
            book.base_currency,
            matches[0],
            as_of=as_of,
            max_quote_age_seconds=max_quote_age_seconds,
        )

    with localcontext(CONTEXT):
        cash = sum((base(c.amount, c.currency) for c in book.cash), ZERO)
        holdings = ZERO
        for position in book.positions:
            spec = _instrument(book, position.instrument_id)
            quote = next(
                (q for q in marks if q.instrument_id == position.instrument_id), None
            )
            if quote is None:
                raise AccountingError("missing holding quote")
            quote.__post_init__()
            _after_action(book, quote)
            _fresh(quote.at, quote.available_at, as_of, max_quote_age_seconds)
            holdings += base(position.quantity * quote.bid, spec.quote_currency)
        receivables = sum(
            (
                base(d.amount, _instrument(book, d.instrument_id).quote_currency)
                for d in book.dividends
                if not d.paid
            ),
            ZERO,
        )
        return Valuation(
            as_of,
            book.base_currency,
            _result(cash),
            _result(holdings),
            _result(receivables),
            _result(cash + holdings + receivables),
        )


@dataclass(frozen=True)
class LinearDerivative:
    contract_id: str
    kind: str
    quote_currency: str
    multiplier: Decimal
    quantity_unit: str = "CONTRACTS"

    def __post_init__(self) -> None:
        _id(self.contract_id)
        _currency(self.quote_currency)
        _number(self.multiplier, positive=True)
        if self.kind not in {"FUTURE", "PERP"} or self.quantity_unit != "CONTRACTS":
            raise AccountingError(
                "only linear quote-settled derivative arithmetic supported"
            )


def futures_pnl(
    contract: LinearDerivative, quantity: Decimal, entry: Decimal, exit: Decimal
) -> Decimal:
    contract.__post_init__()
    _number(quantity, signed=True)
    _number(entry, signed=True)
    _number(exit, signed=True)
    if contract.kind != "FUTURE":
        raise AccountingError("futures contract required")
    with localcontext(CONTEXT):
        return _result(quantity * contract.multiplier * (exit - entry))


def perp_funding(
    contract: LinearDerivative,
    quantity: Decimal,
    mark: Decimal,
    rate: Decimal,
    *,
    convention: str,
) -> Decimal:
    """Single-period quote-currency cash flow; positive rate means longs pay."""
    contract.__post_init__()
    _number(quantity, signed=True)
    _number(mark, positive=True)
    _number(rate, signed=True)
    if contract.kind != "PERP" or abs(rate) > 1 or convention != "POSITIVE_LONG_PAYS":
        raise AccountingError("explicit linear perp funding convention required")
    with localcontext(CONTEXT):
        return _result(-quantity * contract.multiplier * mark * rate)
