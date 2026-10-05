"""Independent small arithmetic/time oracles; no provider price data or broker calls."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid7

import pytest

from quant_hunter.config import JsonRecord
from quant_hunter.markets import (
    ActivityInterval,
    AggregationResult,
    CalendarSchedule,
    Instrument,
    InstrumentHistory,
    InstrumentRevision,
    MarketError,
    MinuteBar,
    Session,
    SymbolInterval,
    aggregate_minutes,
    capability,
    require_supported,
    sessions,
)

D = Decimal


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def instrument(asset: str = "EQUITY") -> Instrument:
    start = instant("2020-01-01T00:00:00Z")
    fx = asset == "FX_SPOT"
    return Instrument(
        f"INSTRUMENT-{uuid7()}",
        asset,
        "OTC_NY_17_CONVENTION" if fx else "XNYS",
        "EUR" if fx else "USD",
        "USD",
        4 if fx else 2,
        0,
        D(1),
        D("0.0001") if fx else D("0.01"),
        D(1),
        "America/New_York",
        "FX_NY_17" if fx else "XNYS",
        (ActivityInterval(start),),
        (SymbolInterval("EUR/USD" if fx else "OLD", start),),
    )


def revision(item: Instrument | None = None) -> InstrumentRevision:
    return InstrumentRevision(
        item or instrument(), instant("2020-01-02T00:00:00Z"), "Synthetic oracle"
    )


@pytest.fixture(scope="module")
def regular() -> CalendarSchedule:
    return sessions("XNYS", date(2025, 1, 6), date(2025, 1, 6))


def minute_rows(
    item: Instrument, session: Session, count: int | None = None
) -> tuple[MinuteBar, ...]:
    count = (
        count
        if count is not None
        else int((session.close_at - session.open_at).total_seconds() // 60)
    )
    return tuple(
        MinuteBar(
            item.instrument_id,
            item.symbol_at(session.open_at),
            session.open_at + timedelta(minutes=index),
            session.open_at + timedelta(minutes=index + 1),
            session.open_at + timedelta(minutes=index + 1),
            D(100 + index),
            D(102 + index),
            D(99 + index),
            D(101 + index),
            D(2),
            D("99.99") + index,
            D("100.01") + index,
        )
        for index in range(count)
    )


def aggregate(
    rows: tuple[MinuteBar, ...],
    snapshot: InstrumentRevision,
    schedule: CalendarSchedule,
    timeframe: str = "5h",
    *,
    as_of: datetime | None = None,
    policy: str = "DROP",
) -> AggregationResult:
    return aggregate_minutes(
        rows,
        snapshot,
        schedule,
        as_of=as_of or schedule.sessions[-1].close_at,
        timeframe=timeframe,
        partial_policy=policy,
    )


def test_symbol_history_is_distinct_from_ticker_and_knowledge_time() -> None:
    old = revision()
    history = InstrumentHistory((old,))
    effective = instant("2025-01-01T00:00:00Z")
    corrected = replace(
        old.instrument,
        symbols=(
            SymbolInterval("OLD", old.instrument.symbols[0].start, effective),
            SymbolInterval("NEW", effective),
        ),
    )
    later = history.append(
        corrected,
        instant("2025-02-01T00:00:00Z"),
        "Received correction",
        expected_latest_digest=old.digest,
    )
    assert len(history.revisions) == 1
    assert later.revisions[0] is old
    assert (
        later.as_of(instant("2025-01-31T23:59:59Z"), effective).symbol_at(effective)
        == "OLD"
    )
    assert (
        later.as_of(instant("2025-02-01T00:00:00Z"), effective).symbol_at(effective)
        == "NEW"
    )
    assert (
        later.as_of(
            instant("2025-02-01T00:00:00Z"), effective - timedelta(seconds=1)
        ).symbol_at(effective - timedelta(seconds=1))
        == "OLD"
    )
    with pytest.raises(FrozenInstanceError):
        old.instrument.status = "DELISTED"  # type: ignore[misc]
    with pytest.raises(MarketError, match="Stale"):
        history.append(corrected, effective, "reason", expected_latest_digest="bad")
    with pytest.raises(MarketError, match="known"):
        history.as_of(instant("2019-01-01T00:00:00Z"), effective)


def test_metadata_roundtrip_and_fingerprint() -> None:
    original = revision()
    record = original.to_record()
    assert cast(str, record["recorded_at"]).endswith("Z")
    assert InstrumentRevision.from_record(record) == original
    assert InstrumentRevision.from_record(record).digest == original.digest
    assert replace(original, reason="New declaration").digest != original.digest
    assert not {
        "version",
        "previous_digest",
        "revision",
        "previous_revision_digest",
    } & set(record)


@pytest.mark.parametrize(
    "change",
    [
        {"instrument_id": "OLD"},
        {"instrument_id": "INSTRUMENT-00000000-0000-4000-8000-000000000000"},
        {"asset_class": "FUTURES"},
        {"asset_class": "CRYPTO_SPOT"},
        {"asset_class": "UNKNOWN"},
        {"venue": "OTHER"},
        {"venue": "../XNYS"},
        {"base_currency": "us"},
        {"quote_currency": "EUR"},
        {"price_precision": True},
        {"price_precision": 13},
        {"quantity_precision": -1},
        {"tick_size": D("0.001")},
        {"tick_size": D("NaN")},
        {"lot_size": D("0.5")},
        {"multiplier": D(10)},
        {"timezone": "UTC"},
        {"calendar_id": "24/7"},
        {"status": "READY"},
        {"activity": ()},
        {"symbols": ()},
        {"tick_size": D("1e-13")},
        {"lot_size": D("1e18")},
        {"multiplier": D(0)},
    ],
)
def test_invalid_instrument_fields_fail(change: dict[str, object]) -> None:
    with pytest.raises(MarketError):
        replace(instrument(), **cast(Any, change))


def test_fx_and_etf_contracts() -> None:
    assert instrument("ETF").asset_class == "ETF"
    fx = instrument("FX_SPOT")
    fx.validate_quote(D("1.2345"), D("1.2346"), D(1000))
    with pytest.raises(MarketError):
        replace(fx, base_currency="USD")
    with pytest.raises(MarketError):
        replace(fx, venue="ANY_FX")
    with pytest.raises(MarketError):
        replace(fx, symbols=(SymbolInterval("USD/EUR", fx.activity[0].start),))


@pytest.mark.parametrize(
    "bid,ask,quantity",
    [
        ("2", "1", "1"),
        ("0", "1", "1"),
        ("1.001", "2", "1"),
        ("1", "2", "0.5"),
        ("1", "Infinity", "1"),
        ("1", "2", "-1"),
    ],
)
def test_invalid_quotes_and_lot_precision(bid: str, ask: str, quantity: str) -> None:
    with pytest.raises(MarketError):
        instrument().validate_quote(D(bid), D(ask), D(quantity))


def test_intervals_gaps_delisting_and_invalid_histories() -> None:
    item = instrument()
    start = item.activity[0].start
    boundary = instant("2025-01-01T00:00:00Z")
    inactive = replace(
        item,
        activity=(ActivityInterval(start, boundary),),
        symbols=(SymbolInterval("OLD", start, boundary),),
        status="DELISTED",
    )
    assert inactive.symbol_at(boundary - timedelta(seconds=1)) == "OLD"
    with pytest.raises(MarketError):
        inactive.symbol_at(boundary)
    with pytest.raises(MarketError):
        ActivityInterval(start, start)
    with pytest.raises(MarketError):
        SymbolInterval("bad symbol", start)
    with pytest.raises(MarketError):
        replace(item, activity=(ActivityInterval(start), ActivityInterval(boundary)))
    with pytest.raises(MarketError):
        replace(item, symbols=(SymbolInterval("OLD", start - timedelta(days=1)),))
    gap = replace(item, symbols=(SymbolInterval("OLD", boundary),))
    with pytest.raises(MarketError, match="unknown"):
        gap.symbol_at(start)
    snap = revision(item)
    for invalid in (
        (),
        (snap, snap),
        (snap, replace(snap, instrument=instrument(), recorded_at=boundary)),
    ):
        with pytest.raises(MarketError):
            InstrumentHistory(invalid)


@pytest.mark.parametrize(
    "change",
    [
        {"reason": ""},
        {"source_reference": ""},
        {"evidence_mode": "VERIFIED"},
        {"recorded_at": datetime(2025, 1, 1)},
    ],
)
def test_revision_validation(change: dict[str, object]) -> None:
    with pytest.raises(MarketError):
        replace(revision(), **cast(Any, change))


@pytest.mark.parametrize(
    "field,value",
    [
        ("recorded_at", "2025-01-01T00:00:00+00:00"),
        ("recorded_at", "2025-99-01T00:00:00Z"),
        ("recorded_at", "2025-01-01T00:00:00.000000001Z"),
        ("reason", 3),
        ("instrument", {}),
        ("unexpected", "extra"),
    ],
)
def test_parser_rejects_malformed_metadata(field: str, value: object) -> None:
    data = revision().to_record()
    data[field] = value  # type: ignore[assignment]
    with pytest.raises(MarketError):
        InstrumentRevision.from_record(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("lot_size", "1e2"),
        ("price_precision", True),
        ("activity", "bad"),
        ("activity", []),
        ("symbols", []),
        ("tick_size", "-1"),
        ("symbol", "extra"),
    ],
)
def test_parser_rejects_malformed_instrument(field: str, value: object) -> None:
    data = revision().to_record()
    cast(JsonRecord, data["instrument"])[field] = value  # type: ignore[assignment]
    with pytest.raises(MarketError):
        InstrumentRevision.from_record(data)


@pytest.mark.parametrize(
    "day,opening,closing",
    [
        ("2025-03-07", "2025-03-07T14:30:00Z", "2025-03-07T21:00:00Z"),
        ("2025-03-10", "2025-03-10T13:30:00Z", "2025-03-10T20:00:00Z"),
        ("2025-10-31", "2025-10-31T13:30:00Z", "2025-10-31T20:00:00Z"),
        ("2025-11-03", "2025-11-03T14:30:00Z", "2025-11-03T21:00:00Z"),
        ("2025-11-28", "2025-11-28T14:30:00Z", "2025-11-28T18:00:00Z"),
    ],
)
def test_xnys_dst_and_early_close_oracles(day: str, opening: str, closing: str) -> None:
    schedule = sessions("XNYS", date.fromisoformat(day), date.fromisoformat(day))
    assert [(row.open_at, row.close_at) for row in schedule.sessions] == [
        (instant(opening), instant(closing))
    ]
    assert schedule.package_version == "4.13.2"
    assert schedule.timezone_version == "2026.5"
    assert schedule.digest.startswith("sha256:")


@pytest.mark.parametrize(
    "day", ["2025-01-01", "2025-07-04", "2025-11-27", "2025-11-29"]
)
def test_xnys_holidays_and_weekend(day: str) -> None:
    assert (
        sessions("XNYS", date.fromisoformat(day), date.fromisoformat(day)).sessions
        == ()
    )


def test_fx_weekend_and_dst_convention() -> None:
    spring = sessions("FX_NY_17", date(2025, 3, 7), date(2025, 3, 10))
    assert len(spring.sessions) == 2
    assert spring.sessions[0].close_at == instant("2025-03-07T22:00:00Z")
    assert spring.sessions[1].open_at == instant("2025-03-09T21:00:00Z")
    assert spring.sessions[1].close_at == instant("2025-03-10T21:00:00Z")
    fall = sessions("FX_NY_17", date(2025, 11, 3), date(2025, 11, 3))
    assert fall.sessions[0].open_at == instant("2025-11-02T22:00:00Z")
    assert "UNKNOWN" in " ".join(spring.limitations)


@pytest.mark.parametrize(
    "start,end",
    [
        (date(1999, 1, 1), date(1999, 1, 1)),
        (date(2036, 1, 1), date(2036, 1, 1)),
        (date(2025, 1, 2), date(2025, 1, 1)),
        (date(2020, 1, 1), date(2021, 1, 1)),
    ],
)
def test_calendar_bounds(start: date, end: date) -> None:
    with pytest.raises(MarketError):
        sessions("XNYS", start, end)


def test_five_hour_and_closed_ninety_minute_tail(regular: CalendarSchedule) -> None:
    snap = revision()
    rows = minute_rows(snap.instrument, regular.sessions[0])
    dropped = aggregate(rows, snap, regular)
    assert len(dropped.bars) == 1
    first = dropped.bars[0]
    assert (first.open, first.high, first.low, first.close, first.volume) == (
        D(100),
        D(401),
        D(99),
        D(400),
        D(600),
    )
    assert (first.open_at, first.close_at) == (
        instant("2025-01-06T14:30:00Z"),
        instant("2025-01-06T19:30:00Z"),
    )
    assert dropped.exclusions[0].reason == "SHORT_SESSION_TAIL_DROPPED"
    included = aggregate(
        rows, snap, regular, policy="INCLUDE_CLOSED_SHORT_SESSION_TAIL"
    )
    assert [row.source_count for row in included.bars] == [300, 90]
    assert included.bars[1].short_session_tail
    assert included.bars[1].close_at == regular.sessions[0].close_at
    assert included.configuration_digest != dropped.configuration_digest


@pytest.mark.parametrize("timeframe,count", [("1m", 390), ("5m", 78), ("1h", 6)])
def test_supported_timeframes(
    regular: CalendarSchedule, timeframe: str, count: int
) -> None:
    snap = revision()
    result = aggregate(
        minute_rows(snap.instrument, regular.sessions[0]), snap, regular, timeframe
    )
    assert len(result.bars) == count
    assert all(bar.available_at >= bar.close_at for bar in result.bars)


def test_incomplete_gap_late_availability_and_unknown_volume(
    regular: CalendarSchedule,
) -> None:
    snap = revision()
    rows = minute_rows(snap.instrument, regular.sessions[0], 5)
    time = rows[-1].close_at
    complete = aggregate(rows, snap, regular, "5m", as_of=time)
    assert len(complete.bars) == 1
    assert not aggregate(
        rows, snap, regular, "5m", as_of=time - timedelta(microseconds=1)
    ).bars
    gap = aggregate(rows[:2] + rows[3:], snap, regular, "5m", as_of=time)
    assert not gap.bars and gap.exclusions[0].reason == "MISSING_MINUTES"
    late = (replace(rows[0], available_at=time + timedelta(seconds=1)), *rows[1:])
    assert (
        aggregate(late, snap, regular, "5m", as_of=time).exclusions[0].reason
        == "UNAVAILABLE_MINUTES"
    )
    assert (
        len(
            aggregate(late, snap, regular, "5m", as_of=time + timedelta(seconds=1)).bars
        )
        == 1
    )
    unknown = (replace(rows[0], volume=None), *rows[1:])
    assert aggregate(unknown, snap, regular, "5m", as_of=time).bars[0].volume is None


def test_future_perturbation_cannot_change_prior_bars(
    regular: CalendarSchedule,
) -> None:
    snap = revision()
    rows = minute_rows(snap.instrument, regular.sessions[0], 10)
    changed = rows[:5] + tuple(
        replace(
            row, open=D(999), high=D(1000), low=D(998), close=D(999), volume=D(10000)
        )
        for row in rows[5:]
    )
    cutoff = rows[4].close_at
    assert (
        aggregate(rows, snap, regular, "5m", as_of=cutoff).bars
        == aggregate(changed, snap, regular, "5m", as_of=cutoff).bars
    )


def test_no_session_crossover() -> None:
    schedule = sessions("XNYS", date(2025, 1, 6), date(2025, 1, 7))
    snap = revision()
    rows = tuple(
        row
        for session in schedule.sessions
        for row in minute_rows(snap.instrument, session)
    )
    result = aggregate(rows, snap, schedule, policy="INCLUDE_CLOSED_SHORT_SESSION_TAIL")
    assert len(result.bars) == 4
    assert [row.source_count for row in result.bars] == [300, 90, 300, 90]
    assert result.bars[1].close_at < result.bars[2].open_at


@pytest.mark.parametrize(
    "change",
    [
        {"open": D(0)},
        {"high": D(50)},
        {"low": D(200)},
        {"volume": D(-1)},
        {"open_bid": None},
        {"open_bid": D(200)},
        {"open": D("1e-13")},
        {"open_at": datetime(2025, 1, 6)},
    ],
)
def test_invalid_minute_values(
    regular: CalendarSchedule, change: dict[str, object]
) -> None:
    row = minute_rows(instrument(), regular.sessions[0], 1)[0]
    with pytest.raises(MarketError):
        replace(row, **cast(Any, change))


def test_aggregation_rejects_invalid_contracts(regular: CalendarSchedule) -> None:
    snap = revision()
    rows = minute_rows(snap.instrument, regular.sessions[0], 2)
    for values in (
        rows[::-1],
        (rows[0], rows[0]),
        (replace(rows[0], symbol="NEW"),),
        (replace(rows[0], instrument_id=instrument().instrument_id),),
        (replace(rows[0], open=D("100.001")),),
    ):
        with pytest.raises(MarketError):
            aggregate(values, snap, regular)
    for timeframe, policy in (("1d", "DROP"), ("5m", "GUESS")):
        with pytest.raises(MarketError):
            aggregate(rows, snap, regular, timeframe, policy=policy)
    with pytest.raises(MarketError):
        aggregate(
            rows, replace(snap, recorded_at=instant("2030-01-01T00:00:00Z")), regular
        )
    with pytest.raises(MarketError):
        aggregate(rows, snap, replace(regular, calendar_id="FX_NY_17"))
    with pytest.raises(MarketError):
        aggregate(
            (
                replace(
                    rows[0],
                    open_at=rows[0].open_at - timedelta(minutes=1),
                    close_at=rows[0].open_at,
                ),
            ),
            snap,
            regular,
        )


@pytest.mark.parametrize(
    "asset,required",
    [("CRYPTO_SPOT", "24x7_calendar"), ("CRYPTO_PERP", "funding"), ("FUTURES", "roll")],
)
def test_unimplemented_market_plugin_contract(asset: str, required: str) -> None:
    contract = capability(asset)
    assert not contract.implemented
    assert required in contract.required_contracts
    with pytest.raises(MarketError, match="not implemented"):
        require_supported(asset)


def test_calendar_record_and_invalid_snapshots(regular: CalendarSchedule) -> None:
    record = regular.to_record()
    assert record["anchor"] == "SESSION_OPEN"
    assert record["timezone_package"] == "tzdata==2026.5"
    row = regular.sessions[0]
    for change in (
        {"anchor": "MIDNIGHT"},
        {"calendar_id": "UNIVERSAL_FX"},
        {"sessions": (row, row)},
        {"start": regular.start + timedelta(days=1)},
        {"sessions": (replace(row, label=regular.start - timedelta(days=1)),)},
    ):
        with pytest.raises(MarketError):
            replace(regular, **cast(Any, change))
    for session_change in (
        {"label": "bad"},
        {"close_at": row.open_at},
        {"close_at": row.open_at + timedelta(days=2)},
        {"close_at": row.close_at + timedelta(seconds=1)},
    ):
        with pytest.raises(MarketError):
            replace(row, **cast(Any, session_change))
    with pytest.raises(MarketError):
        sessions("CRYPTO_24_7", regular.start, regular.end)
    with pytest.raises(MarketError):
        sessions("XNYS", cast(date, "2025-01-01"), regular.end)


def test_dependency_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import quant_hunter.markets.calendars as calendar_module

    monkeypatch.setattr(calendar_module, "version", lambda name: "wrong")
    with pytest.raises(MarketError, match="timezone package"):
        sessions("XNYS", date(2025, 1, 6), date(2025, 1, 6))
    monkeypatch.setattr(
        calendar_module,
        "version",
        lambda name: "2026.5" if name == "tzdata" else "wrong",
    )
    with pytest.raises(MarketError, match="Exchange calendar package"):
        sessions("XNYS", date(2025, 1, 6), date(2025, 1, 6))


def test_minute_boundaries_and_resource_guards(regular: CalendarSchedule) -> None:
    snap = revision()
    row = minute_rows(snap.instrument, regular.sessions[0], 1)[0]
    for change in (
        {"open_at": row.open_at + timedelta(seconds=1)},
        {"close_at": row.open_at + timedelta(minutes=2)},
        {"available_at": row.open_at},
    ):
        with pytest.raises(MarketError):
            replace(row, **cast(Any, change))
    with pytest.raises(MarketError, match="100000"):
        aggregate((row,) * 100001, snap, regular)
    fx = revision(instrument("FX_SPOT"))
    large = sessions("FX_NY_17", date(2025, 1, 1), date(2025, 5, 1))
    with pytest.raises(MarketError, match="100000"):
        aggregate((), fx, large)
    after = replace(
        row,
        open_at=regular.sessions[0].close_at,
        close_at=regular.sessions[0].close_at + timedelta(minutes=1),
        available_at=regular.sessions[0].close_at + timedelta(minutes=1),
    )
    with pytest.raises(MarketError, match="outside"):
        aggregate((after,), snap, regular)


def test_symbol_change_inside_window_is_not_merged(regular: CalendarSchedule) -> None:
    original = instrument()
    change = regular.sessions[0].open_at + timedelta(minutes=2)
    renamed = replace(
        original,
        symbols=(
            SymbolInterval("OLD", original.activity[0].start, change),
            SymbolInterval("NEW", change),
        ),
    )
    rows = minute_rows(original, regular.sessions[0], 5)
    rows = rows[:2] + tuple(replace(row, symbol="NEW") for row in rows[2:])
    output = aggregate(rows, revision(renamed), regular, "5m", as_of=rows[-1].close_at)
    assert not output.bars
    assert output.exclusions[0].reason == "SYMBOL_CHANGE_WITHIN_WINDOW"
    subminute = change - timedelta(seconds=30)
    malformed = replace(
        original,
        symbols=(
            SymbolInterval("OLD", original.activity[0].start, subminute),
            SymbolInterval("NEW", subminute),
        ),
    )
    with pytest.raises(MarketError, match="symbol boundary"):
        aggregate(rows[:2], revision(malformed), regular, "5m")


def test_early_close_aggregation_and_fx_daily_boundaries() -> None:
    early = sessions("XNYS", date(2025, 11, 28), date(2025, 11, 28))
    snap = revision()
    rows = minute_rows(snap.instrument, early.sessions[0])
    assert not aggregate(rows, snap, early).bars
    output = aggregate(rows, snap, early, policy="INCLUDE_CLOSED_SHORT_SESSION_TAIL")
    assert len(output.bars) == 1 and output.bars[0].source_count == 210
    assert output.bars[0].available_at == instant("2025-11-28T18:00:00Z")
    fx = revision(instrument("FX_SPOT"))
    schedule = sessions("FX_NY_17", date(2025, 3, 7), date(2025, 3, 10))
    fx_rows = tuple(
        row
        for session in schedule.sessions
        for row in minute_rows(fx.instrument, session)
    )
    output = aggregate(
        fx_rows, fx, schedule, policy="INCLUDE_CLOSED_SHORT_SESSION_TAIL"
    )
    assert [bar.source_count for bar in output.bars] == [300, 300, 300, 300, 240] * 2
    assert output.bars[4].close_at == instant("2025-03-07T22:00:00Z")
    assert output.bars[5].open_at == instant("2025-03-09T21:00:00Z")


def test_unknown_quotes_remain_unknown_and_decimal_serialization(
    regular: CalendarSchedule,
) -> None:
    item = replace(instrument(), multiplier=D("1.0000"))
    snapshot = revision(item)
    assert cast(JsonRecord, snapshot.to_record()["instrument"])["multiplier"] == "1"
    row = replace(
        minute_rows(item, regular.sessions[0], 1)[0], open_bid=None, open_ask=None
    )
    output = aggregate((row,), snapshot, regular, "1m")
    assert output.bars[0].open_bid is None and output.bars[0].open_ask is None
