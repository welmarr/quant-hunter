"""Independent synthetic accounting oracles; no empirical execution claims."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from quant_hunter.simulation.accounting import (
    AccountingError,
    BookSnapshot,
    CashBalance,
    CashLiquidation,
    ConfirmCancel,
    ConvertCash,
    Dividend,
    FillOrder,
    FinancingCharge,
    FXQuote,
    InstrumentSpec,
    LinearDerivative,
    PayDividend,
    Quote,
    RejectOrder,
    RequestCancel,
    Split,
    SubmitOrder,
    TradingWindow,
    apply_event,
    convert_value,
    event_digest,
    futures_pnl,
    initial_book,
    perp_funding,
    value_book,
)

D = Decimal
START = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
SESSION = TradingWindow(START, START + timedelta(hours=6))
EQUITY = InstrumentSpec(
    "INS-EQUITY", "TEST", "EQUITY", "USD", D(1), D(".01"), (SESSION,)
)


def at(second: int) -> datetime:
    return START + timedelta(seconds=second)


def initial(*, spec: InstrumentSpec = EQUITY) -> BookSnapshot:
    return initial_book("USD", at(0), (spec,), (CashBalance("USD", D(10000)),))


def quote(
    second: int,
    bid: str = "100",
    ask: str | None = None,
    *,
    instrument_id: str = "INS-EQUITY",
) -> Quote:
    return Quote(instrument_id, at(second), at(second), D(bid), D(ask or bid))


def submit(
    book: BookSnapshot, second: int, side: str, quantity: str, order_id: str = "ORDER-1"
) -> BookSnapshot:
    return apply_event(
        book,
        SubmitOrder(
            event_id=f"EVENT-{book.version}",
            expected_version=book.version,
            at=at(second),
            order_id=order_id,
            instrument_id=book.instruments[0].instrument_id,
            side=side,
            quantity=D(quantity),
            decision_at=at(second),
        ),
    )


def fill(
    book: BookSnapshot,
    second: int,
    quantity: str,
    *,
    order_id: str = "ORDER-1",
    price: str = "100",
    bid: str | None = None,
    fee: str = "0",
    slip: str = "0",
) -> BookSnapshot:
    return apply_event(
        book,
        FillOrder(
            event_id=f"EVENT-{book.version}",
            expected_version=book.version,
            at=at(second),
            order_id=order_id,
            quantity=D(quantity),
            quote=quote(
                second,
                bid or price,
                price,
                instrument_id=book.instruments[0].instrument_id,
            ),
            commission=D(fee),
            slippage_bps=D(slip),
            max_quote_age_seconds=0,
        ),
    )


def held(quantity: str = "10", *, fee: str = "0") -> BookSnapshot:
    return fill(submit(initial(), 0, "BUY", quantity), 1, quantity, fee=fee)


def usd(book: BookSnapshot) -> Decimal:
    return next(c.amount for c in book.cash if c.currency == "USD")


def equity(book: BookSnapshot, second: int, price: str) -> Decimal:
    return value_book(
        book, (quote(second, price),), (), as_of=at(second), max_quote_age_seconds=0
    ).equity


@pytest.mark.parametrize("fee,expected", [("1", "10008"), ("2", "10006")])
def test_minimal_independent_cash_oracle(fee: str, expected: str) -> None:
    book = held(fee=fee)
    assert usd(book) == D(10000) - D(1000) - D(fee)
    book = fill(
        submit(book, 2, "SELL", "10", "SELL"),
        3,
        "10",
        order_id="SELL",
        price="101",
        fee=fee,
    )
    assert usd(book) == D(expected) and book.positions == ()
    assert book.fills[-1].realized_pnl == D(expected) - D(10000)
    assert equity(book, 3, "101") == D(expected)


def test_spread_and_slippage_have_separate_hand_calculated_effects() -> None:
    # 10*(100.10 ask) +1; sale 10*(100.90 bid)-1 =>10006.
    book = fill(
        submit(initial(), 0, "BUY", "10"), 1, "10", price="100.10", bid="99.90", fee="1"
    )
    book = fill(
        submit(book, 2, "SELL", "10", "SELL"),
        3,
        "10",
        order_id="SELL",
        price="101.10",
        bid="100.90",
        fee="1",
    )
    assert usd(book) == D(10006)
    assert all(f.adverse_slippage == 0 for f in book.fills)
    # Ten basis points:100→100.10;101→100.899 rounds adversely to100.89.
    slipped = fill(submit(initial(), 0, "BUY", "10"), 1, "10", fee="1", slip="10")
    slipped = fill(
        submit(slipped, 2, "SELL", "10", "SELL"),
        3,
        "10",
        order_id="SELL",
        price="101",
        fee="1",
        slip="10",
    )
    assert usd(slipped) == D("10005.90")
    assert [f.adverse_slippage for f in slipped.fills] == [D(1), D("1.10")]


def test_partial_fills_average_cost_and_partial_disposal() -> None:
    book = submit(initial(), 0, "BUY", "10")
    book = fill(book, 1, "4", fee="1")
    assert (
        book.orders[0].status == "PARTIALLY_FILLED"
        and book.positions[0].cost_basis == 401
    )
    book = fill(book, 2, "6", price="102", fee="1")
    assert book.orders[0].status == "FILLED"
    # Cost1014; sell5@110 fee1 =>549 proceeds, cost507, realized42.
    book = fill(
        submit(book, 3, "SELL", "5", "SELL"),
        4,
        "5",
        order_id="SELL",
        price="110",
        fee="1",
    )
    assert usd(book) == 9535
    assert book.positions[0].quantity == 5 and book.positions[0].cost_basis == 507
    assert book.fills[-1].realized_pnl == 42


def test_partial_fill_during_cancel_pending_then_cancel_remainder() -> None:
    book = fill(submit(initial(), 0, "BUY", "10"), 1, "4")
    book = apply_event(
        book,
        RequestCancel(
            event_id="CANCEL", expected_version=2, at=at(2), order_id="ORDER-1"
        ),
    )
    book = fill(book, 3, "2")
    assert book.orders[0].status == "CANCEL_PENDING" and book.orders[0].filled == 6
    book = apply_event(
        book,
        ConfirmCancel(event_id="ACK", expected_version=4, at=at(4), order_id="ORDER-1"),
    )
    assert book.orders[0].status == "CANCELED" and usd(book) == 9400
    with pytest.raises(AccountingError, match="not fillable"):
        fill(book, 5, "4")


def test_full_fill_wins_cancel_race_without_rollback() -> None:
    book = submit(initial(), 0, "BUY", "10")
    book = apply_event(
        book,
        RequestCancel(
            event_id="CANCEL", expected_version=1, at=at(1), order_id="ORDER-1"
        ),
    )
    book = fill(book, 2, "10")
    book = apply_event(
        book,
        ConfirmCancel(event_id="ACK", expected_version=3, at=at(3), order_id="ORDER-1"),
    )
    assert (
        book.orders[0].status == "FILLED" and book.orders[0].reason == "CANCEL_TOO_LATE"
    )
    assert usd(book) == 9000 and book.positions[0].quantity == 10


def test_exact_old_replay_keeps_current_state_conflict_and_stale_cas_fail() -> None:
    event = SubmitOrder(
        event_id="A",
        expected_version=0,
        at=at(0),
        order_id="BUY",
        instrument_id=EQUITY.instrument_id,
        side="BUY",
        quantity=D(10),
        decision_at=at(0),
    )
    first = apply_event(initial(), event)
    current = fill(first, 1, "10", order_id="BUY")
    assert apply_event(current, event) is current
    assert event_digest(event) == event_digest(replace(event))
    with pytest.raises(AccountingError, match="conflicting"):
        apply_event(current, replace(event, quantity=D(11)))
    with pytest.raises(AccountingError, match="stale"):
        apply_event(current, replace(event, event_id="B", order_id="OTHER"))
    assert current.version == 2 and usd(current) == 9000


def test_split_two_for_one_preserves_wealth_and_cancels_open_orders() -> None:
    book = submit(held(), 2, "BUY", "2", "PENDING")
    before = equity(book, 2, "100")
    event = Split(
        event_id="SPLIT",
        expected_version=3,
        at=at(3),
        instrument_id=EQUITY.instrument_id,
        ratio=D(2),
        effective_at=at(3),
        available_at=at(0),
        open_order_policy="CANCEL_OPEN",
    )
    after = apply_event(book, event)
    assert before == equity(after, 3, "50") == 10000
    assert after.positions[0].quantity == 20 and after.positions[0].cost_basis == 1000
    assert after.orders[-1].status == "CANCELED"
    assert usd(after) == usd(book)
    with pytest.raises(AccountingError, match="already applied"):
        apply_event(after, replace(event, event_id="SECOND", expected_version=4))
    with pytest.raises(AccountingError, match="predates"):
        value_book(after, (quote(2, "100"),), (), as_of=at(3), max_quote_age_seconds=10)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"price_basis": "ADJUSTED_TOTAL_RETURN"}, "double count"),
        ({"available_at": at(4)}, "known"),
        ({"effective_at": at(2)}, "retroactive"),
        ({"ratio": D(".15")}, "fractional"),
        ({"open_order_policy": "SCALE_ORDERS"}, "unsupported"),
    ],
)
def test_split_unsupported_or_ambiguous_treatment_rejected(
    change: dict[str, object], code: str
) -> None:
    book = held()
    event = Split(
        event_id="SPLIT",
        expected_version=2,
        at=at(3),
        instrument_id=EQUITY.instrument_id,
        ratio=D(2),
        effective_at=at(3),
        available_at=at(0),
        open_order_policy="CANCEL_OPEN",
    )
    with pytest.raises(AccountingError, match=code):
        apply_event(book, replace(event, **change))  # type: ignore[arg-type]
    assert book.positions[0].quantity == 10


def dividend(book: BookSnapshot) -> BookSnapshot:
    return apply_event(
        book,
        Dividend(
            event_id="DIV",
            expected_version=book.version,
            at=at(2),
            dividend_id="DIV-1",
            instrument_id=EQUITY.instrument_id,
            amount_per_share=D(2),
            ex_at=at(2),
            payment_at=at(5),
            available_at=at(0),
        ),
    )


def test_dividend_ex_drop_receivable_and_later_cash_payment_preserve_wealth() -> None:
    before = held()
    book = dividend(before)
    valuation = value_book(
        book, (quote(2, "98"),), (), as_of=at(2), max_quote_age_seconds=0
    )
    assert equity(before, 1, "100") == valuation.equity == 10000
    assert valuation.receivables_value == 20 and usd(book) == 9000
    # Sell after ex-date: entitlement belongs to the old holding, not pay-date qty.
    book = fill(
        submit(book, 3, "SELL", "10", "SELL"), 4, "10", order_id="SELL", price="98"
    )
    assert book.positions == () and usd(book) == 9980
    book = apply_event(
        book,
        PayDividend(event_id="PAY", expected_version=5, at=at(5), dividend_id="DIV-1"),
    )
    assert usd(book) == 10000 and book.dividends[0].paid
    assert (
        value_book(book, (), (), as_of=at(5), max_quote_age_seconds=0).receivables_value
        == 0
    )
    with pytest.raises(AccountingError, match="already paid"):
        apply_event(
            book,
            PayDividend(
                event_id="DOUBLE", expected_version=6, at=at(6), dividend_id="DIV-1"
            ),
        )


def test_dividend_payment_cannot_arrive_early_or_duplicate_entitlement() -> None:
    book = dividend(held())
    with pytest.raises(AccountingError, match="not payable"):
        apply_event(
            book,
            PayDividend(
                event_id="EARLY", expected_version=3, at=at(3), dividend_id="DIV-1"
            ),
        )
    event = Dividend(
        event_id="DUP",
        expected_version=3,
        at=at(2),
        dividend_id="DIV-1",
        instrument_id=EQUITY.instrument_id,
        amount_per_share=D(2),
        ex_at=at(2),
        payment_at=at(5),
        available_at=at(0),
    )
    with pytest.raises(AccountingError, match="already recorded"):
        apply_event(book, event)


@pytest.mark.parametrize(
    "amount,source,target,expected",
    [
        ("100", "EUR", "USD", "110"),
        ("-100", "EUR", "USD", "-120"),
        ("120", "USD", "EUR", "100"),
        ("-110", "USD", "EUR", "-100"),
    ],
)
def test_directed_fx_assets_liabilities_and_inverse_have_correct_sides(
    amount: str, source: str, target: str, expected: str
) -> None:
    rate = FXQuote("EUR", "USD", at(0), at(0), D("1.1"), D("1.2"))
    assert convert_value(
        D(amount), source, target, rate, as_of=at(0), max_quote_age_seconds=0
    ) == D(expected)


def test_conversion_changes_each_cash_balance_once_with_explicit_fee() -> None:
    book = initial()
    rate = FXQuote("EUR", "USD", at(1), at(1), D("1.1"), D("1.2"))
    event = ConvertCash(
        event_id="FX",
        expected_version=0,
        at=at(1),
        from_currency="USD",
        to_currency="EUR",
        amount=D(120),
        quote=rate,
        commission_in_target=D(1),
        max_quote_age_seconds=0,
    )
    book = apply_event(book, event)
    assert usd(book) == 9880
    assert next(c.amount for c in book.cash if c.currency == "EUR") == 99
    # Immediate liquidation loses bid/ask roundtrip and conversion fee:99*1.1+9880.
    assert value_book(
        book, (), (rate,), as_of=at(1), max_quote_age_seconds=0
    ).equity == D("9988.9")
    assert apply_event(book, event) is book


def test_partial_liquidation_and_full_delisting_preserve_cash_and_cost_basis() -> None:
    book = held()
    event = CashLiquidation(
        event_id="PART",
        expected_version=2,
        at=at(2),
        instrument_id=EQUITY.instrument_id,
        quantity=D(4),
        cash_per_unit=D(105),
        commission=D(1),
        available_at=at(2),
        delist=False,
    )
    book = apply_event(book, event)
    assert usd(book) == 9419 and book.positions[0].quantity == 6
    assert (
        book.positions[0].cost_basis == 600 and book.liquidations[0].realized_pnl == 19
    )
    assert equity(book, 2, "105") == 10049
    book = apply_event(
        book,
        replace(
            event,
            event_id="END",
            expected_version=3,
            at=at(3),
            quantity=D(6),
            cash_per_unit=D(90),
            commission=D(0),
            delist=True,
        ),
    )
    assert (
        usd(book) == 9959
        and book.positions == ()
        and book.delisted == (EQUITY.instrument_id,)
    )
    rejected = submit(book, 4, "BUY", "1", "AFTER")
    assert (
        rejected.orders[-1].status == "REJECTED"
        and rejected.orders[-1].reason == "DELISTED"
    )


def test_futures_multiplier_and_perp_funding_independent_oracles() -> None:
    future = LinearDerivative("FUT-2024", "FUTURE", "USD", D(50))
    # Two contracts *50 USD/point *1.25 points =125 USD; negative prices allowed.
    assert futures_pnl(future, D(2), D(4000), D("4001.25")) == 125
    assert futures_pnl(future, D(-2), D(4000), D("4001.25")) == -125
    assert futures_pnl(future, D(2), D(-10), D(-9)) == 100
    perp = LinearDerivative("PERP-LINEAR", "PERP", "USD", D(1))
    # Two contracts *20,000 USD *0.0001: long pays4, short receives4.
    assert (
        perp_funding(perp, D(2), D(20000), D(".0001"), convention="POSITIVE_LONG_PAYS")
        == -4
    )
    assert (
        perp_funding(perp, D(-2), D(20000), D(".0001"), convention="POSITIVE_LONG_PAYS")
        == 4
    )
    assert (
        perp_funding(perp, D(2), D(20000), D("-.0001"), convention="POSITIVE_LONG_PAYS")
        == 4
    )
    with pytest.raises(AccountingError, match="UNSUPPORTED"):
        replace(EQUITY, kind="FUTURE")


def test_calendar_boundary_is_half_open_and_fill_cannot_use_same_decision_close() -> (
    None
):
    closed = submit(initial(), 21600, "BUY", "1")
    assert closed.orders[0].reason == "MARKET_CLOSED"
    opened = submit(initial(), 0, "BUY", "1")
    with pytest.raises(AccountingError, match="strictly later"):
        fill(opened, 0, "1")
    assert fill(opened, 1, "1").positions[0].quantity == 1


@pytest.mark.parametrize(
    "kind",
    [
        "oversell",
        "overbuy",
        "overfill",
        "lot",
        "tick",
        "stale",
        "future",
        "wrong-instrument",
        "unknown",
        "cancel",
        "zero",
        "nan",
    ],
)
def test_bad_fill_rejected_without_mutating_book(kind: str) -> None:
    spec = replace(EQUITY, lot=D(2)) if kind == "lot" else EQUITY
    book = submit(
        initial(spec=spec),
        0,
        "SELL" if kind == "oversell" else "BUY",
        "200" if kind == "overbuy" else "10",
    )
    event = FillOrder(
        event_id="F",
        expected_version=1,
        at=at(2),
        order_id="ORDER-1",
        quantity=D(10),
        quote=quote(2),
        commission=D(0),
        slippage_bps=D(0),
        max_quote_age_seconds=0,
    )
    if kind == "overbuy":
        event = replace(event, quantity=D(200))
    elif kind == "overfill":
        event = replace(event, quantity=D(11))
    elif kind == "lot":
        event = replace(event, quantity=D(1))
    elif kind == "tick":
        event = replace(event, quote=quote(2, "100.001"))
    elif kind == "stale":
        event = replace(event, quote=quote(1))
    elif kind == "future":
        event = replace(event, quote=quote(3))
    elif kind == "wrong-instrument":
        event = replace(event, quote=quote(2, instrument_id="OTHER"))
    elif kind == "unknown":
        event = replace(event, order_id="MISSING")
    elif kind == "cancel":
        book = apply_event(
            book,
            RejectOrder(
                event_id="R",
                expected_version=1,
                at=at(1),
                order_id="ORDER-1",
                reason="LOCAL_REJECT",
            ),
        )
        event = replace(event, expected_version=2)
    elif kind == "zero":
        event = replace(event, quantity=D(0))
    elif kind == "nan":
        event = replace(event, commission=D("NaN"))
    with pytest.raises(AccountingError):
        apply_event(book, event)
    assert usd(book) == 10000 and book.positions == () and book.fills == ()


def test_financing_explicit_cash_charge_and_future_period_refusal() -> None:
    book = held()
    event = FinancingCharge(
        event_id="FIN",
        expected_version=2,
        at=at(10),
        currency="USD",
        amount=D("1.25"),
        period_start=at(1),
        period_end=at(10),
        treatment="EXPLICIT_SPOT_FINANCING_CHARGE",
    )
    assert usd(apply_event(book, event)) == D("8998.75")
    with pytest.raises(AccountingError, match="completed-period"):
        apply_event(book, replace(event, period_end=at(11)))


def test_decimal_context_does_not_change_transitions_or_valuation() -> None:
    baseline = fill(
        submit(initial(), 0, "BUY", "10"), 1, "10", price="100.01", fee="1", slip="7"
    )
    with localcontext() as context:
        context.prec = 4
        changed = fill(
            submit(initial(), 0, "BUY", "10"),
            1,
            "10",
            price="100.01",
            fee="1",
            slip="7",
        )
        assert changed == baseline
        assert equity(changed, 1, "100.01") == D("9998.2")


@pytest.mark.parametrize(
    "quantity", [D("NaN"), D("Infinity"), D("1e-19"), D("1e99"), D(-1)]
)
def test_numerical_input_boundaries(quantity: Decimal) -> None:
    event = SubmitOrder(
        event_id="A",
        expected_version=0,
        at=at(0),
        order_id="A",
        instrument_id=EQUITY.instrument_id,
        side="BUY",
        quantity=quantity,
        decision_at=at(0),
    )
    with pytest.raises(AccountingError):
        apply_event(initial(), event)


@pytest.mark.parametrize(
    "change",
    [
        {"order_type": "LIMIT"},
        {"side": "SHORT"},
        {"decision_at": at(1)},
        {"quantity": D(".5")},
        {"order_id": "bad/name"},
        {"expected_version": True},
        {"at": at(-1)},
    ],
)
def test_invalid_order_admission_and_versions(change: dict[str, object]) -> None:
    event = SubmitOrder(
        event_id="A",
        expected_version=0,
        at=at(0),
        order_id="A",
        instrument_id=EQUITY.instrument_id,
        side="BUY",
        quantity=D(1),
        decision_at=at(0),
    )
    with pytest.raises(AccountingError):
        apply_event(initial(), replace(event, **change))  # type: ignore[arg-type]


def test_unknown_fx_pair_stale_fx_and_duplicate_quotes_fail() -> None:
    rate = FXQuote("EUR", "USD", at(0), at(0), D("1.1"), D("1.2"))
    with pytest.raises(AccountingError, match="directed"):
        convert_value(D(1), "JPY", "USD", rate, as_of=at(0), max_quote_age_seconds=0)
    with pytest.raises(AccountingError, match="stale"):
        convert_value(D(1), "EUR", "USD", rate, as_of=at(1), max_quote_age_seconds=0)
    book = initial_book("USD", at(0), (EQUITY,), (CashBalance("EUR", D(10)),))
    with pytest.raises(AccountingError, match="ambiguous"):
        value_book(book, (), (rate, rate), as_of=at(0), max_quote_age_seconds=0)
    with pytest.raises(AccountingError, match="missing"):
        value_book(held(), (), (), as_of=at(1), max_quote_age_seconds=0)


def test_input_definitions_reject_timezone_calendar_and_adjusted_quotes() -> None:
    with pytest.raises(AccountingError):
        TradingWindow(START.replace(tzinfo=None), at(1))
    with pytest.raises(AccountingError):
        TradingWindow(at(2), at(1))
    with pytest.raises(AccountingError):
        replace(EQUITY, sessions=(SESSION, SESSION))
    with pytest.raises(AccountingError):
        replace(EQUITY, kind="FX_SPOT")
    with pytest.raises(AccountingError):
        replace(quote(1), price_basis="ADJUSTED_TOTAL_RETURN")
    with pytest.raises(AccountingError):
        replace(quote(1), ask=D(99))
    with pytest.raises(AccountingError):
        initial_book("USD", START, (EQUITY, EQUITY), (CashBalance("USD", D(1)),))


def test_corporate_action_must_precede_same_instrument_ex_time_execution() -> None:
    book = submit(held(), 2, "BUY", "2", "EX-DATE")
    book = fill(book, 3, "2", order_id="EX-DATE", price="98")
    event = Dividend(
        event_id="TOO-LATE",
        expected_version=4,
        at=at(3),
        dividend_id="DIV",
        instrument_id=EQUITY.instrument_id,
        amount_per_share=D(2),
        ex_at=at(3),
        payment_at=at(4),
        available_at=at(0),
    )
    with pytest.raises(AccountingError, match="must precede"):
        apply_event(book, event)
    assert book.positions[0].quantity == 12 and not book.dividends


def test_buy_after_ex_date_receives_no_existing_dividend_entitlement() -> None:
    book = dividend(held())
    book = fill(
        submit(book, 2, "BUY", "10", "EX-BUY"), 3, "10", order_id="EX-BUY", price="98"
    )
    assert book.positions[0].quantity == 20
    book = apply_event(
        book,
        PayDividend(event_id="PAY", expected_version=5, at=at(5), dividend_id="DIV-1"),
    )
    assert book.dividends[0].quantity == 10 and book.dividends[0].amount == 20
    assert usd(book) == 8040


def test_post_split_fill_cannot_use_still_fresh_pre_split_quote() -> None:
    book = held()
    book = apply_event(
        book,
        Split(
            event_id="S",
            expected_version=2,
            at=at(3),
            instrument_id=EQUITY.instrument_id,
            ratio=D(2),
            effective_at=at(3),
            available_at=at(0),
            open_order_policy="CANCEL_OPEN",
        ),
    )
    book = apply_event(
        book,
        SubmitOrder(
            event_id="B",
            expected_version=3,
            at=at(3),
            order_id="B",
            instrument_id=EQUITY.instrument_id,
            side="BUY",
            quantity=D(1),
            decision_at=at(1),
        ),
    )
    event = FillOrder(
        event_id="F",
        expected_version=4,
        at=at(4),
        order_id="B",
        quantity=D(1),
        quote=quote(2, "100"),
        commission=D(0),
        slippage_bps=D(0),
        max_quote_age_seconds=10,
    )
    with pytest.raises(AccountingError, match="predates"):
        apply_event(book, event)


def test_filled_order_cannot_receive_invented_cancel_acknowledgement() -> None:
    book = held()
    with pytest.raises(AccountingError, match="not requested"):
        apply_event(
            book,
            ConfirmCancel(
                event_id="ACK", expected_version=2, at=at(2), order_id="ORDER-1"
            ),
        )


def test_decimal_context_rounds_fractional_fx_deterministically() -> None:
    rate = FXQuote("EUR", "USD", at(0), at(0), D(3), D(3))
    with localcontext() as context:
        context.prec = 4
        converted = convert_value(
            D(1), "USD", "EUR", rate, as_of=at(0), max_quote_age_seconds=0
        )
    assert str(converted) == "0." + "3" * 38


def test_conflicting_distinct_instrument_quotes_do_not_value_holdings() -> None:
    book = held()
    with pytest.raises(AccountingError, match="ambiguous"):
        value_book(book, (quote(1), quote(1)), (), as_of=at(1), max_quote_age_seconds=0)
    with pytest.raises(AccountingError, match="time"):
        value_book(book, (quote(1),), (), as_of=at(0), max_quote_age_seconds=0)


@pytest.mark.parametrize("kind", ["quantity", "future", "partial-delist"])
def test_cash_liquidation_never_invents_or_retrofits_units(kind: str) -> None:
    book = held()
    event = CashLiquidation(
        event_id="C",
        expected_version=2,
        at=at(2),
        instrument_id=EQUITY.instrument_id,
        quantity=D(11) if kind == "quantity" else D(4),
        cash_per_unit=D(0),
        commission=D(0),
        available_at=at(3) if kind == "future" else at(2),
        delist=kind == "partial-delist",
    )
    with pytest.raises(AccountingError):
        apply_event(book, event)
    assert book.positions[0].quantity == 10


def test_zero_recovery_delisting_records_actual_loss_not_missing_zero_imputation() -> (
    None
):
    book = held()
    event = CashLiquidation(
        event_id="C",
        expected_version=2,
        at=at(2),
        instrument_id=EQUITY.instrument_id,
        quantity=D(10),
        cash_per_unit=D(0),
        commission=D(0),
        available_at=at(2),
        delist=True,
    )
    result = apply_event(book, event)
    assert result.positions == () and usd(result) == 9000
    assert result.liquidations[0].realized_pnl == -1000


@pytest.mark.parametrize(
    "kind", ["perp-pnl", "future-funding", "unknown-sign", "inverse", "funding-rate"]
)
def test_derivative_helpers_refuse_mixed_conventions(kind: str) -> None:
    future = LinearDerivative("FUT", "FUTURE", "USD", D(50))
    perp = LinearDerivative("PERP", "PERP", "USD", D(1))
    with pytest.raises(AccountingError):
        if kind == "perp-pnl":
            futures_pnl(perp, D(1), D(100), D(101))
        elif kind == "future-funding":
            perp_funding(
                future, D(1), D(100), D(".01"), convention="POSITIVE_LONG_PAYS"
            )
        elif kind == "inverse":
            replace(perp, kind="INVERSE_PERP")
        else:
            perp_funding(
                perp,
                D(1),
                D(100),
                D(2) if kind == "funding-rate" else D(".01"),
                convention="UNKNOWN"
                if kind == "unknown-sign"
                else "POSITIVE_LONG_PAYS",
            )
