"""Independent numerical and causal checks for the synthetic V0 arithmetic core."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from typing import cast

import pytest

from quant_hunter.simulation import (
    Bar,
    Costs,
    Instrument,
    SimulationConfig,
    SimulationError,
    simulate,
    synthetic_fixture,
)

D = Decimal


def config(
    fee: str = "1", slippage: str = "0", financing: str = "0"
) -> SimulationConfig:
    return SimulationConfig(
        D("10000"), D("10"), 1, Costs(D(fee), D(slippage), D(financing))
    )


def test_independent_round_trip_cash_oracle_and_drawdown() -> None:
    instrument, bars = synthetic_fixture()
    result = simulate(bars, instrument, config())
    # Hand ledger: 10000 - (10 * 100) - 1 = 8999;
    # then 8999 + (10 * 101) - 1 = 10008. No simulator helper calculates this oracle.
    assert [trade.cash_after for trade in result.trades] == [D("8999"), D("10008")]
    assert [trade.price for trade in result.trades] == [D("100"), D("101")]
    assert [trade.quantity_after for trade in result.trades] == [D("10"), D("0")]
    assert result.final_cash == D("10008")
    assert result.final_quantity == 0
    assert result.final_equity == D("10008")
    assert result.net_pnl == D("8")
    assert result.total_commission == D("2")
    assert result.total_slippage == result.total_spread == result.total_financing == 0
    assert [point.equity for point in result.equity_curve] == [
        D("10000"),
        D("10000"),
        D("9989"),
        D("10008"),
    ]
    assert result.max_drawdown == D("0.0011")
    assert result.data_mode == "SYNTHETIC"
    assert "empirically unvalidated" in result.limitations[0]


def test_doubling_commissions_degrades_same_trades_by_exact_two() -> None:
    instrument, bars = synthetic_fixture()
    normal = simulate(bars, instrument, config())
    doubled = simulate(bars, instrument, config(fee="2"))
    assert doubled.final_cash == D("10006")
    assert doubled.net_pnl == D("6")
    assert normal.net_pnl - doubled.net_pnl == D("2")
    assert [(trade.side, trade.price, trade.quantity) for trade in normal.trades] == [
        (trade.side, trade.price, trade.quantity) for trade in doubled.trades
    ]


def test_spread_is_paid_at_correct_side_and_never_deducted_twice() -> None:
    instrument, source = synthetic_fixture()
    bars = (
        *source[:2],
        replace(source[2], open_bid=D("99.8"), open_ask=D("100.2")),
        replace(source[3], open_bid=D("100.8"), open_ask=D("101.2")),
    )
    result = simulate(bars, instrument, config())
    # Opening midpoints stay 100/101. Buy 1002 + 1, sell 1008 - 1 -> 10004.
    assert [trade.price for trade in result.trades] == [D("100.2"), D("100.8")]
    assert result.final_cash == D("10004")
    assert result.total_spread == D("4")
    assert result.total_slippage == 0


def test_adverse_slippage_has_independent_cash_oracle() -> None:
    instrument, bars = synthetic_fixture()
    result = simulate(bars, instrument, config(slippage="10"))
    # 10 bps: buy 100.1 and sell 100.899. Cash = 10000 - 1001 - 1 + 1008.99 - 1.
    assert [trade.price for trade in result.trades] == [D("100.1"), D("100.899")]
    assert result.total_slippage == D("2.01")
    assert result.final_cash == D("10005.99")
    assert result.total_spread == 0


def test_decisions_fill_strictly_next_open_and_never_same_close() -> None:
    instrument, bars = synthetic_fixture()
    result = simulate(bars, instrument, config())
    assert [(trade.decision_at, trade.filled_at) for trade in result.trades] == [
        (bars[1].close_at, bars[2].open_at),
        (bars[2].close_at, bars[3].open_at),
    ]
    assert all(trade.filled_at > trade.decision_at for trade in result.trades)
    assert [decision.target_quantity for decision in result.decisions] == [0, 10, 0, 10]
    assert len(result.trades) == 2  # The last decision has no future opening quote.


def test_future_mutation_leaves_prior_decisions_and_fills_unchanged() -> None:
    instrument, bars = synthetic_fixture()
    original = simulate(bars, instrument, config())
    changed = simulate(
        (*bars[:-1], replace(bars[-1], close=D("70"))), instrument, config()
    )
    assert changed.decisions[:-1] == original.decisions[:-1]
    assert changed.trades == original.trades
    assert changed.decisions[-1] != original.decisions[-1]


def test_future_open_mutation_changes_fill_but_not_prior_signal() -> None:
    instrument, bars = synthetic_fixture()
    original = simulate(bars, instrument, config())
    changed = simulate(
        (*bars[:2], replace(bars[2], open_bid=D("102"), open_ask=D("102")), bars[3]),
        instrument,
        config(),
    )
    assert original.decisions == changed.decisions
    assert changed.trades[0].price == D("102")
    assert changed.final_cash == D("9988")  # Entry worsened 2 * 10; exit unchanged.


def test_signal_delay_and_neutralization_change_behavior() -> None:
    instrument, bars = synthetic_fixture()
    delayed = simulate(bars, instrument, replace(config(), lookback=2))
    neutral = simulate(bars, instrument, replace(config(), strategy="FLAT"))
    assert delayed.decisions[1].reason == "WARMUP"
    assert delayed.trades == ()  # Price at t2 equals t0, so no delayed buy.
    assert neutral.trades == ()
    assert neutral.final_equity == D("10000")
    assert simulate(bars, instrument, config()).trades  # Positive control.


def test_final_position_is_marked_without_fabricated_liquidation() -> None:
    instrument, bars = synthetic_fixture()
    result = simulate(bars[:3], instrument, config())
    assert len(result.trades) == 1
    assert result.final_quantity == 10
    assert result.final_cash == D("8999")
    assert result.final_equity == D("9989")


def test_financing_accrues_only_for_actual_held_time() -> None:
    instrument, bars = synthetic_fixture()
    # Buy at t2 open=100, mark t2 close=99, then exit next day's opening.
    # Rate .365: 1000 * .001 * 6/24 + 990 * .001 * 18/24 = .25 + .7425.
    result = simulate(bars, instrument, config(financing="0.365"))
    assert result.total_financing == D("0.9925")
    assert result.final_cash == D("10007.0075")
    assert result.equity_curve[2].cash == D("8998.75")
    assert (
        result.trades[-1].cash_after == result.final_cash
    )  # No cost after liquidation.


def test_fx_uses_base_units_and_quote_currency_cash() -> None:
    instrument, bars = synthetic_fixture("FX_SPOT")
    result = simulate(bars, instrument, replace(config(fee="0"), quantity=D("1000")))
    # EUR 1000 costs USD 1103.10 at ask, sells for USD 1103.90 at bid.
    assert result.final_cash == D("10000.8")
    assert result.net_pnl == D("0.8")
    assert result.total_spread == D("0.2")
    assert instrument.base_currency == "EUR"
    with pytest.raises(SimulationError, match="quote currency"):
        simulate(bars, instrument, replace(config(), portfolio_currency="EUR"))


def test_insufficient_cash_is_a_retained_rejection_without_leverage() -> None:
    instrument, bars = synthetic_fixture()
    result = simulate(bars, instrument, replace(config(), initial_cash=D("1000")))
    assert result.final_cash == 1000
    assert result.trades == ()
    assert len(result.rejected_orders) == 1
    assert result.rejected_orders[0].reason == "INSUFFICIENT_CASH"
    assert result.rejected_orders[0].side == "BUY"
    assert result.total_commission == 0


@pytest.mark.parametrize("rate", ["0.1", "1"])
def test_financing_cannot_silently_borrow(rate: str) -> None:
    instrument, bars = synthetic_fixture()
    with pytest.raises(SimulationError, match="financing exceeds cash"):
        simulate(
            bars,
            instrument,
            replace(config(fee="0", financing=rate), initial_cash=D("1000")),
        )


def test_overnight_financing_cannot_silently_borrow_before_sale() -> None:
    instrument, bars = synthetic_fixture()
    # Enough cash for entry plus six hours of finance, insufficient overnight.
    with pytest.raises(SimulationError, match="financing exceeds cash"):
        simulate(
            bars,
            instrument,
            replace(config(fee="0", financing="0.365"), initial_cash=D("1000.3")),
        )


def test_caller_decimal_context_does_not_change_results() -> None:
    instrument, bars = synthetic_fixture()
    settings = config(slippage="10", financing="0.365")
    expected = simulate(bars, instrument, settings)
    with localcontext() as context:
        context.prec = 4
        actual = simulate(bars, instrument, settings)
    assert actual == expected


@pytest.mark.parametrize(
    "invalid", [D("NaN"), D("Infinity"), D("-1"), D("0"), D("1e19"), D("1e-19")]
)
def test_bad_prices_are_rejected(invalid: Decimal) -> None:
    _, bars = synthetic_fixture()
    with pytest.raises(SimulationError):
        replace(bars[0], close=invalid)


def test_float_and_overprecise_inputs_are_rejected() -> None:
    with pytest.raises(SimulationError, match="finite Decimal"):
        Costs(cast(Decimal, 0.1), D("0"), D("0"))
    with pytest.raises(SimulationError, match="precision"):
        Costs(D("0.1234567890123456789"), D("0"), D("0"))


def test_bad_timestamps_and_late_data_are_rejected() -> None:
    _, bars = synthetic_fixture()
    with pytest.raises(SimulationError, match="availability"):
        replace(bars[0], available_at=bars[0].close_at + timedelta(seconds=1))
    with pytest.raises(SimulationError, match="availability"):
        replace(bars[0], available_at=bars[0].open_at)
    with pytest.raises(SimulationError, match="strictly after"):
        replace(bars[0], close_at=bars[0].open_at)
    with pytest.raises(SimulationError, match="UTC"):
        replace(bars[0], open_at=datetime(2025, 1, 1))
    with pytest.raises(SimulationError, match="UTC"):
        replace(
            bars[0], open_at=datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=1)))
        )


def test_crossed_quotes_and_unordered_or_overlapping_bars_are_rejected() -> None:
    instrument, bars = synthetic_fixture()
    with pytest.raises(SimulationError, match="bid"):
        replace(bars[0], open_bid=D("101"))
    for invalid in (
        bars[::-1],
        (bars[0], bars[0]),
        (bars[0], replace(bars[1], open_at=bars[0].close_at)),
    ):
        with pytest.raises(SimulationError, match="ordered"):
            simulate(invalid, instrument, config())


@pytest.mark.parametrize("asset_class", ["FUTURES", "CRYPTO", "FX_FORWARD", ""])
def test_unsupported_instruments_and_fixtures_are_rejected(asset_class: str) -> None:
    with pytest.raises(SimulationError, match="supported"):
        Instrument("X", asset_class, "USD", "USD")
    with pytest.raises(SimulationError, match="unsupported"):
        synthetic_fixture(asset_class)


def test_bad_instrument_identity_and_quantity_steps_are_rejected() -> None:
    with pytest.raises(SimulationError, match="symbol"):
        Instrument("unbounded!", "EQUITY", "USD", "USD")
    with pytest.raises(SimulationError, match="currencies"):
        Instrument("X", "EQUITY", "usd", "USD")
    with pytest.raises(SimulationError, match="must differ"):
        Instrument("X", "FX_SPOT", "USD", "USD")
    instrument, bars = synthetic_fixture()
    with pytest.raises(SimulationError, match="multiple"):
        simulate(bars, replace(instrument, quantity_step=D("3")), config())


@pytest.mark.parametrize("lookback", [0, -1, True])
def test_bad_lookback_is_rejected(lookback: int) -> None:
    with pytest.raises(SimulationError, match="lookback"):
        replace(config(), lookback=lookback)


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_mode", "HISTORICAL_REAL"),
        ("data_mode", "LIVE_READ_ONLY"),
        ("strategy", "ARBITRARY"),
        ("execution_policy", "SAME_CLOSE"),
    ],
)
def test_unsupported_modes_are_rejected(field: str, value: str) -> None:
    with pytest.raises(SimulationError):
        if field == "data_mode":
            replace(config(), data_mode=value)
        elif field == "strategy":
            replace(config(), strategy=value)
        else:
            replace(config(), execution_policy=value)


def test_missing_explicit_costs_invalid_costs_and_empty_input_are_rejected() -> None:
    instrument, bars = synthetic_fixture()
    with pytest.raises(SimulationError, match="explicit Costs"):
        replace(config(), costs=cast(Costs, None))
    with pytest.raises(SimulationError, match="slippage_bps"):
        Costs(D("0"), D("10000"), D("0"))
    with pytest.raises(SimulationError, match="annual_financing_rate"):
        Costs(D("0"), D("0"), D("1.1"))
    with pytest.raises(SimulationError, match="bars are required"):
        simulate((), instrument, config())
    with pytest.raises(SimulationError, match="bars are required"):
        simulate((bars[0],) * 100001, instrument, config())
    with pytest.raises(SimulationError, match="must be a Bar"):
        simulate(cast(tuple[Bar, ...], ("bad",)), instrument, config())


def test_one_bar_is_an_explicit_warmup_without_orders() -> None:
    instrument, bars = synthetic_fixture()
    result = simulate(bars[:1], instrument, config())
    assert result.decisions[0].at.tzinfo is UTC
    assert result.decisions[0].reason == "WARMUP"
    assert result.trades == ()
    assert result.final_equity == 10000
    assert result.max_drawdown == 0
