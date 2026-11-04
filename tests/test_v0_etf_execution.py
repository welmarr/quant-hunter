"""Cash ETF software oracles; no provider, leverage or empirical approval."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import cast

import pytest
from test_v0_accounting import EQUITY, at, fill, initial, quote, submit, usd

from quant_hunter.config import JsonRecord
from quant_hunter.markets.instruments import InstrumentRevision
from quant_hunter.simulation import accounting as a
from quant_hunter.simulation.engine import (
    Costs,
    Instrument,
    SimulationConfig,
    SimulationError,
    simulate,
    synthetic_fixture,
)
from quant_hunter.web.paper_access import (
    PaperWorkflowError,
    _instrument_payload,
    default_paper_config,
    validate_paper_config,
)
from quant_hunter.web.paper_routes import PaperConfiguration

D = Decimal
ETF = replace(EQUITY, instrument_id="INS-ETF", symbol="SYNTH_ETF", kind="ETF")


def _value(book: a.BookSnapshot, second: int, price: str) -> a.Valuation:
    return a.value_book(
        book,
        (quote(second, price, instrument_id=ETF.instrument_id),),
        (),
        as_of=at(second),
        max_quote_age_seconds=0,
    )


@pytest.mark.parametrize("fee,expected", [("1", "10008"), ("2", "10006")])
def test_etf_independent_four_bar_cash_and_causal_oracle(
    fee: str, expected: str
) -> None:
    instrument, bars = synthetic_fixture("ETF")
    result = simulate(
        bars,
        instrument,
        SimulationConfig(D(10000), D(10), 1, Costs(D(fee), D(0), D(0))),
    )
    assert result.instrument.asset_class == "ETF"
    assert result.instrument.symbol == "SYNTH-ETF"
    assert result.final_cash == result.final_equity == D(expected)
    assert result.final_quantity == 0
    assert [(t.side, t.price, t.quantity) for t in result.trades] == [
        ("BUY", D(100), D(10)),
        ("SELL", D(101), D(10)),
    ]
    assert all(t.filled_at > t.decision_at for t in result.trades)


@pytest.mark.parametrize("fee,expected", [("1", "10008"), ("2", "10006")])
def test_etf_native_accounting_cash_roundtrip(fee: str, expected: str) -> None:
    book = fill(submit(initial(spec=ETF), 0, "BUY", "10"), 1, "10", fee=fee)
    book = fill(
        submit(book, 2, "SELL", "10", "SELL"),
        3,
        "10",
        order_id="SELL",
        price="101",
        fee=fee,
    )
    assert usd(book) == D(expected)
    assert book.positions == ()
    assert book.fills[-1].realized_pnl == D(expected) - 10000


def test_etf_native_separate_spread_slippage_and_partial_fees() -> None:
    book = submit(initial(spec=ETF), 0, "BUY", "10")
    # Ask101 plus10bps rounds adversely to101.11; 10shares cost1011.10 +2fees.
    book = fill(book, 1, "4", price="101", bid="99", slip="10", fee="1")
    book = fill(book, 2, "6", price="101", bid="99", slip="10", fee="1")
    assert usd(book) == D("8986.90")
    assert sum(f.adverse_slippage for f in book.fills) == D("1.10")
    assert sum(f.commission for f in book.fills) == 2
    assert book.positions[0].quantity == 10
    assert book.positions[0].cost_basis == D("1013.10")
    assert _value(book, 2, "99").equity == D("9976.90")


def test_etf_split_preserves_wealth_and_cancels_pending_orders() -> None:
    book = fill(submit(initial(spec=ETF), 0, "BUY", "10"), 1, "10")
    book = submit(book, 2, "BUY", "2", "PENDING")
    before = _value(book, 2, "100")
    split = a.Split(
        event_id="SPLIT",
        expected_version=book.version,
        at=at(3),
        instrument_id=ETF.instrument_id,
        ratio=D(2),
        effective_at=at(3),
        available_at=at(0),
        open_order_policy="CANCEL_OPEN",
    )
    after = a.apply_event(book, split)
    assert before.equity == _value(after, 3, "50").equity == 10000
    assert after.positions[0].quantity == 20
    assert after.positions[0].cost_basis == 1000
    assert after.orders[-1].status == "CANCELED"
    assert usd(after) == usd(book)
    for change, reason in [
        ({"price_basis": "ADJUSTED_TOTAL_RETURN"}, "double count"),
        ({"available_at": at(4)}, "known"),
        ({"ratio": D(".15")}, "fractional"),
    ]:
        with pytest.raises(a.AccountingError, match=reason):
            a.apply_event(book, replace(split, **change))  # type: ignore[arg-type]


def test_etf_dividend_ex_entitlement_survives_sale_until_payment() -> None:
    book = fill(submit(initial(spec=ETF), 0, "BUY", "10"), 1, "10")
    ex = a.Dividend(
        event_id="DIV",
        expected_version=book.version,
        at=at(2),
        dividend_id="DIST-1",
        instrument_id=ETF.instrument_id,
        amount_per_share=D(2),
        ex_at=at(2),
        payment_at=at(5),
        available_at=at(0),
    )
    with pytest.raises(a.AccountingError, match="double count"):
        a.apply_event(book, replace(ex, price_basis="ADJUSTED_TOTAL_RETURN"))
    book = a.apply_event(book, ex)
    value = _value(book, 2, "98")
    assert value.equity == 10000 and value.receivables_value == 20
    assert usd(book) == 9000
    book = fill(
        submit(book, 3, "SELL", "10", "SELL"), 4, "10", order_id="SELL", price="98"
    )
    assert book.positions == () and usd(book) == 9980
    book = a.apply_event(
        book,
        a.PayDividend(
            event_id="PAY",
            expected_version=book.version,
            at=at(5),
            dividend_id="DIST-1",
        ),
    )
    assert usd(book) == 10000 and book.dividends[0].paid


def test_etf_admission_preserves_distinct_canonical_xnys_cash_profile() -> None:
    config = default_paper_config("ETF")
    assert validate_paper_config(config) == config
    assert PaperConfiguration.model_validate(config).market == "ETF"
    payload = _instrument_payload("ETF")
    parsed = InstrumentRevision.from_record(
        {
            **payload,
            "recorded_at": "2024-01-02T14:30:00Z",
            "instrument": {
                **cast(JsonRecord, payload["instrument"]),
                "instrument_id": "INSTRUMENT-019cdef0-1234-7123-8123-0123456789ab",
            },
        }
    ).instrument
    assert parsed.asset_class == "ETF"
    assert parsed.venue == parsed.calendar_id == "XNYS"
    assert parsed.base_currency == parsed.quote_currency == "USD"
    assert parsed.multiplier == 1
    assert parsed.symbols[0].symbol == "SYNTH_ETF"


@pytest.mark.parametrize("kind", ["ETF_LEVERAGED", "ETF_INVERSE", "FUTURE", "PERP"])
def test_unsupported_profiles_are_never_relabelled_etfs(kind: str) -> None:
    with pytest.raises(SimulationError):
        synthetic_fixture(kind)
    with pytest.raises(a.AccountingError, match="UNSUPPORTED"):
        replace(ETF, kind=kind)
    with pytest.raises(PaperWorkflowError, match="UNSUPPORTED"):
        validate_paper_config(default_paper_config(kind))


def test_etf_currency_and_cash_short_constraints_remain_explicit() -> None:
    with pytest.raises(SimulationError, match="must match"):
        Instrument("ETF", "ETF", "EUR", "USD")
    with pytest.raises(a.AccountingError, match="must match"):
        replace(ETF, base_currency="EUR")
    with pytest.raises(a.AccountingError, match="short"):
        fill(submit(initial(spec=ETF), 0, "SELL", "1"), 1, "1")
    with pytest.raises(a.AccountingError, match="cash"):
        fill(submit(initial(spec=ETF), 0, "BUY", "101"), 1, "101")
