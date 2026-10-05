"""Synthetic provider contracts; no real keys, network, prices or performance."""

from __future__ import annotations

import json
import lzma
import struct
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest

from quant_hunter.sources._equity_transport import EquityResponse
from quant_hunter.sources.priority_common import PriorityKey, exact_json, number
from quant_hunter.sources.priority_dukascopy import (
    MAX_DECODED,
    DukascopyDailyImporter,
    DukascopyQuery,
)
from quant_hunter.sources.priority_eodhd import EODHDFileImporter, EODQuery
from quant_hunter.sources.priority_sharadar import SF1Query, SharadarConnector
from quant_hunter.sources.priority_tradingeconomics import (
    CalendarQuery,
    TradingEconomicsConnector,
)
from quant_hunter.sources.priority_transport import (
    SF1_COLUMNS,
    PriorityHTTPS,
    PriorityRequest,
)
from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, SourceError

STAMP = datetime(2026, 10, 5, tzinfo=UTC)
KEY = PriorityKey("fixture-not-a-real-api-key")
DUKA = DukascopyQuery("EURUSD", date(2024, 1, 2), 100000)
EOD = EODQuery("FIXTURE_old.US", "USD", date(2024, 1, 1), date(2024, 1, 31), "DELISTED")
SF1 = SF1Query("FIXTURE", "ARQ", date(2023, 1, 1), date(2024, 12, 31))
CALENDAR = CalendarQuery("United States", date(2024, 1, 2), date(2024, 1, 3))


def encode(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def bi5(data: bytes | None = None) -> bytes:
    if data is None:
        data = struct.pack(">IIIff", 1000, 110002, 110000, 1.25, 2.5) + struct.pack(
            ">IIIff", 1000, 110003, 110001, 0.0, 1.0
        )
    return lzma.compress(data, format=lzma.FORMAT_ALONE)


def eod_rows() -> list[dict[str, object]]:
    return [
        {
            "date": "2024-01-02",
            "open": 100,
            "high": 103,
            "low": 99,
            "close": 102,
            "adjusted_close": 50.5,
            "volume": 2000,
        }
    ]


def sf1_payload(
    day: str = "2024-01-02", cursor: str | None = None
) -> dict[str, object]:
    names = SF1_COLUMNS.split(",")
    return {
        "datatable": {
            "columns": [
                {
                    "name": name,
                    "type": "String"
                    if name in ("ticker", "dimension")
                    else "Date"
                    if name
                    in ("calendardate", "datekey", "reportperiod", "lastupdated")
                    else "BigDecimal(36,14)",
                }
                for name in names
            ],
            "data": [
                [
                    "FIXTURE",
                    "ARQ",
                    "2023-12-31",
                    day,
                    "2023-12-30",
                    "2025-01-01",
                    1000000,
                    None,
                    2000000,
                ]
            ],
        },
        "meta": {"next_cursor_id": cursor},
    }


def sf1_row(payload: dict[str, object]) -> list[object]:
    return cast(
        list[list[object]], cast(dict[str, object], payload["datatable"])["data"]
    )[0]


def calendar_rows() -> list[dict[str, object]]:
    return [
        {
            "CalendarId": "1234",
            "Date": "2024-01-02T13:30:00",
            "Country": "United States",
            "Category": "Fixture employment",
            "Event": "Fixture jobs",
            "Reference": "Dec",
            "ReferenceDate": "2023-12-31T00:00:00",
            "Actual": "178K",
            "Previous": "142K",
            "Revised": "161K",
            "Forecast": "175K",
            "TEForecast": "180K",
            "DateSpan": "0",
            "Importance": 3,
            "LastUpdate": "2024-01-02T13:31:00.123",
            "Currency": "",
            "Unit": "K",
            "Source": "Fixture statistical office",
            "Ticker": "FIXTURE",
        }
    ]


class Fixture:
    def __init__(self, *responses: EquityResponse | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[PriorityRequest] = []

    def send(self, request: PriorityRequest) -> EquityResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_daily_bi5_exact_side_scaling_utc_and_source_specific_volume() -> None:
    importer = DukascopyDailyImporter()
    raw = bi5()
    result = importer.import_bytes(raw, DUKA, STAMP, evidence_mode="RECORDED_FIXTURE")
    first, second = result.records
    assert first.ask == Decimal("1.10002") and first.bid == Decimal("1.10000")
    assert first.timestamp == datetime(2024, 1, 2, 0, 0, 1, tzinfo=UTC)
    assert first.ask_volume_millions == 1.25 and first.bid_volume_millions == 2.5
    assert second.timestamp == first.timestamp and second.sequence == 1
    assert "NOT_GLOBAL" in first.volume_scope and first.available_at is None
    assert not first.point_in_time_eligible and "NOT_FORWARD" in first.instrument_type
    assert result.raw_pages[0].raw == raw and not result.coverage_complete
    assert (
        importer.health().status == "SUCCEEDED"
        and importer.transport_status == "BLOCKED_EXTERNAL"
    )
    assert importer.list_capabilities()
    jpy = importer.normalize(raw, replace(DUKA, pair="USDJPY", point_scale=1000), STAMP)
    assert jpy[0].bid == Decimal("110")


@pytest.mark.parametrize(
    "query",
    [
        replace(DUKA, pair="XAUUSD"),
        replace(DUKA, point_scale=1000),
        replace(DUKA, point_scale=True),
        replace(DUKA, timestamp_basis="UTC_HOUR_MILLISECONDS"),
    ],
)
def test_bi5_rejects_wrong_units_or_timestamp_basis(query: DukascopyQuery) -> None:
    with pytest.raises(SourceError, match="INVALID_DUKASCOPY_CONFIG"):
        DukascopyDailyImporter().normalize(bi5(), query, STAMP)


@pytest.mark.parametrize(
    "offset,value,code",
    [
        (0, b"\xff", "INVALID_LZMA_HEADER"),
        (1, (2**31).to_bytes(4, "little"), "LZMA_DICTIONARY_LIMIT"),
        (5, (MAX_DECODED + 20).to_bytes(8, "little"), "LZMA_OUTPUT_METADATA_LIMIT"),
        (5, (21).to_bytes(8, "little"), "LZMA_OUTPUT_METADATA_LIMIT"),
    ],
)
def test_bi5_rejects_malicious_metadata_before_decoder(
    monkeypatch: pytest.MonkeyPatch, offset: int, value: bytes, code: str
) -> None:
    raw = bytearray(bi5())
    raw[offset : offset + len(value)] = value

    def forbidden(**_: object) -> None:
        pytest.fail("Decoder allocated before metadata rejection")

    monkeypatch.setattr("lzma.LZMADecompressor", forbidden)
    with pytest.raises(SourceError, match=code):
        DukascopyDailyImporter().import_bytes(bytes(raw), DUKA, STAMP)


@pytest.mark.parametrize(
    "case",
    [
        "truncated",
        "trailing",
        "record",
        "empty",
        "dictionary_corrupt",
        "expansion",
        "row_limit",
    ],
)
def test_bi5_compressed_failures_are_bounded(case: str) -> None:
    raw = bi5()
    if case == "truncated":
        raw = raw[:-5]
    elif case == "trailing":
        raw += b"tail"
    elif case == "record":
        raw = bi5(b"x" * 21)
    elif case == "empty":
        raw = bi5(b"")
    elif case == "dictionary_corrupt":
        raw = raw[:13] + b"bad"
    elif case == "expansion":
        raw = bi5(b"x" * (MAX_DECODED + 20))
    elif case == "row_limit":
        raw = bi5(b"x" * (100001 * 20))
    importer = DukascopyDailyImporter()
    with pytest.raises(SourceError):
        importer.import_bytes(raw, DUKA, STAMP)
    assert importer.health().status == "FAILED"


@pytest.mark.parametrize(
    "ms,ask,bid,askv,bidv",
    [
        (86400000, 10, 9, 1, 1),
        (0, 9, 10, 1, 1),
        (0, 10, 0, 1, 1),
        (0, 10, 9, float("nan"), 1),
        (0, 10, 9, 1, -1),
    ],
)
def test_bi5_invalid_quote_records(
    ms: int, ask: int, bid: int, askv: float, bidv: float
) -> None:
    with pytest.raises(SourceError):
        DukascopyDailyImporter().normalize(
            bi5(struct.pack(">IIIff", ms, ask, bid, askv, bidv)), DUKA, STAMP
        )


def test_bi5_unordered_future_and_naive_times_rejected() -> None:
    data = struct.pack(">IIIff", 2, 10, 9, 1, 1) + struct.pack(">IIIff", 1, 10, 9, 1, 1)
    with pytest.raises(SourceError, match="INVALID_TICK_TIME_ORDER"):
        DukascopyDailyImporter().normalize(bi5(data), DUKA, STAMP)
    with pytest.raises(SourceError, match="FUTURE_TICK"):
        DukascopyDailyImporter().normalize(
            bi5(), DUKA, datetime(2024, 1, 1, tzinfo=UTC)
        )
    with pytest.raises(SourceError, match="UTC_RETRIEVAL_REQUIRED"):
        DukascopyDailyImporter().normalize(bi5(), DUKA, STAMP.replace(tzinfo=None))


def test_eod_raw_adjusted_split_volume_and_delisting_declared_only() -> None:
    importer = EODHDFileImporter()
    result = importer.import_bytes(encode(eod_rows()), EOD, STAMP)
    record = result.records[0]
    assert record.close == 102 and record.adjusted_close == Decimal("50.5")
    assert record.split_adjusted_volume == 2000 and record.ohlc_basis == "RAW_AS_TRADED"
    assert (
        record.declared_listing_status == "DELISTED"
        and record.symbol == "FIXTURE_old.US"
    )
    assert (
        record.symbol_binding == "OWNER_DECLARED_NOT_IN_RESPONSE"
        and record.available_at is None
    )
    assert not record.point_in_time_eligible and importer.health().status == "SUCCEEDED"
    assert (
        importer.list_capabilities() and importer.transport_status == "BLOCKED_EXTERNAL"
    )
    rows = eod_rows()
    rows[0]["adjusted_close"] = 49
    newer = importer.import_bytes(encode(rows), EOD, STAMP)
    assert newer.records[0].adjusted_close == 49 and record.adjusted_close == Decimal(
        "50.5"
    )
    assert result.raw_pages[0].digest != newer.raw_pages[0].digest


@pytest.mark.parametrize(
    "field,value",
    [
        ("low", 101),
        ("high", 101),
        ("open", 0),
        ("close", "102"),
        ("volume", True),
        ("volume", -1),
        ("date", "2023-12-31"),
        ("date", "2024-01-02T00:00:00Z"),
        ("api_token", "private"),
    ],
)
def test_eod_rejects_bad_units_schema_prices_and_secrets(
    field: str, value: object
) -> None:
    rows = eod_rows()
    rows[0][field] = value
    importer = EODHDFileImporter()
    with pytest.raises(SourceError):
        importer.import_bytes(encode(rows), EOD, STAMP)
    assert importer.health().status == "FAILED"


def test_eod_duplicate_and_reversed_dates_rejected() -> None:
    with pytest.raises(SourceError, match="EOD_BATCH_MISMATCH"):
        EODHDFileImporter().normalize(encode(eod_rows() * 2), EOD, STAMP)
    rows = eod_rows() * 2
    rows[0] = dict(rows[0], date="2024-01-03")
    with pytest.raises(SourceError, match="EOD_BATCH_MISMATCH"):
        EODHDFileImporter().normalize(encode(rows), EOD, STAMP)


def test_sharadar_header_pagination_dates_and_missing_value() -> None:
    transport = Fixture(
        EquityResponse(200, encode(sf1_payload("2024-02-01", "cursor_a"))),
        EquityResponse(200, encode(sf1_payload())),
    )
    client = SharadarConnector(KEY, transport)
    result = client.test_connection(SF1)
    first = result.records[0]
    assert first.datekey == date(2024, 1, 2) and first.calendardate == date(
        2023, 12, 31
    )
    assert first.reportperiod == date(2023, 12, 30) and first.lastupdated == date(
        2025, 1, 1
    )
    assert (
        first.revenue == 1000000
        and first.netinc is None
        and not first.point_in_time_eligible
    )
    assert first.available_at is None and "UNVERIFIED" in first.financial_unit
    assert len(result.raw_pages) == 2 and result.evidence_mode == "RECORDED_FIXTURE"
    assert parse_qs(urlsplit(transport.requests[1].target).query)[
        "qopts.cursor_id"
    ] == ["cursor_a"]
    assert all(
        KEY.value not in request.target and KEY.value not in repr(request)
        for request in transport.requests
    )
    assert client.health().status == "SUCCEEDED" and client.list_capabilities()


def test_sharadar_column_order_ar_vs_mr_and_retained_revision() -> None:
    payload = sf1_payload()
    table = cast(dict[str, object], payload["datatable"])
    table["columns"] = list(reversed(cast(list[object], table["columns"])))
    table["data"] = [list(reversed(sf1_row(sf1_payload())))]
    old = SharadarConnector().normalize(encode(payload), SF1, STAMP).records[0]
    revised = sf1_payload()
    sf1_row(revised)[1] = "MRQ"
    sf1_row(revised)[3] = "2023-12-30"
    sf1_row(revised)[6] = 1100000
    current = (
        SharadarConnector()
        .normalize(encode(revised), replace(SF1, dimension="MRQ"), STAMP)
        .records[0]
    )
    assert (
        old.revenue == 1000000
        and current.revenue == 1100000
        and old.dimension != current.dimension
    )
    assert current.available_at is None and not current.point_in_time_eligible


@pytest.mark.parametrize(
    "index,value",
    [
        (0, "WRONG"),
        (1, "MRQ"),
        (3, "2025-01-01"),
        (4, "2024-02-01"),
        (5, "2027-01-01"),
        (5, "2023-01-01"),
        (6, True),
        (6, "100"),
    ],
)
def test_sharadar_refuses_unbound_or_temporally_wrong_rows(
    index: int, value: object
) -> None:
    payload = sf1_payload()
    sf1_row(payload)[index] = value
    with pytest.raises(SourceError):
        SharadarConnector().normalize(encode(payload), SF1, STAMP)


@pytest.mark.parametrize(
    "case",
    [
        "loop",
        "limit",
        "duplicate",
        "changed_duplicate",
        "missing_meta",
        "bad_column",
        "missing_column",
        "bad_row",
    ],
)
def test_sharadar_hostile_pagination_and_schema(case: str) -> None:
    first, second = (
        sf1_payload(cursor="cursor_a"),
        sf1_payload("2024-02-01", "cursor_a"),
    )
    query = SF1
    if case == "limit":
        query = replace(SF1, max_pages=1)
    elif case in ("duplicate", "changed_duplicate"):
        second = sf1_payload()
        if case == "changed_duplicate":
            sf1_row(second)[6] = 999
    elif case == "missing_meta":
        first["meta"] = {}
    elif case == "bad_column":
        cast(
            list[dict[str, object]],
            cast(dict[str, object], first["datatable"])["columns"],
        )[0]["type"] = "Date"
    elif case == "missing_column":
        cast(list[object], cast(dict[str, object], first["datatable"])["columns"]).pop()
    elif case == "bad_row":
        sf1_row(first).pop()
    client = SharadarConnector(
        KEY,
        Fixture(
            EquityResponse(200, encode(first)), EquityResponse(200, encode(second))
        ),
    )
    with pytest.raises(SourceError):
        client.fetch_range(query)
    assert client.health().status == "FAILED"


def test_calendar_actual_previous_before_after_consensus_and_schedule_separate() -> (
    None
):
    raw = encode(calendar_rows())
    transport = Fixture(EquityResponse(200, raw))
    client = TradingEconomicsConnector(KEY, transport)
    result = client.test_connection(CALENDAR)
    event = result.records[0]
    assert (
        event.actual,
        event.previous_after_revision,
        event.previous_before_revision,
        event.consensus_forecast,
        event.provider_forecast,
    ) == ("178K", "142K", "161K", "175K", "180K")
    assert event.scheduled_release == datetime(2024, 1, 2, 13, 30, tzinfo=UTC)
    assert (
        event.available_at is None
        and event.consensus_available_at is None
        and not event.point_in_time_eligible
    )
    assert event.provider_last_update == "2024-01-02T13:31:00.123"
    assert "%20" in transport.requests[0].target and KEY.value not in repr(client)
    assert result.raw_pages[0].raw == raw and client.health().status == "SUCCEEDED"
    assert client.list_capabilities()
    changed = calendar_rows()
    changed[0]["Forecast"] = "176K"
    changed[0]["DateSpan"] = "1"
    revised = client.normalize(encode(changed), CALENDAR, STAMP)[0]
    assert revised.consensus_forecast == "176K" and event.consensus_forecast == "175K"
    assert revised.time_precision == "ESTIMATED_SOURCE_SCHEDULE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("Country", "Canada"),
        ("Date", "2024-01-04T13:30:00"),
        ("Date", "2024-01-02T13:30:00-05:00"),
        ("DateSpan", "2"),
        ("Importance", True),
        ("LastUpdate", "bad"),
        ("ReferenceDate", "2023-12-32T00:00:00"),
        ("Actual", 178),
        ("CalendarId", True),
        ("CalendarID", "9876"),
    ],
)
def test_calendar_contract_rejects_wrong_ids_units_dates_and_types(
    field: str, value: object
) -> None:
    rows = calendar_rows()
    rows[0][field] = value
    with pytest.raises(SourceError):
        TradingEconomicsConnector().normalize(encode(rows), CALENDAR, STAMP)


def test_calendar_missing_fields_duplicate_truncation_and_future_actual() -> None:
    rows = calendar_rows()
    del rows[0]["Forecast"]
    with pytest.raises(SourceError, match="CALENDAR_MISSING_FIELD"):
        TradingEconomicsConnector().normalize(encode(rows), CALENDAR, STAMP)
    with pytest.raises(SourceError, match="CALENDAR_BATCH_MISMATCH"):
        TradingEconomicsConnector().normalize(
            encode(calendar_rows() * 2), CALENDAR, STAMP
        )
    with pytest.raises(SourceError, match="CALENDAR_ROW_LIMIT_OR_TRUNCATION"):
        TradingEconomicsConnector().normalize(
            encode(calendar_rows() * 1000), CALENDAR, STAMP
        )
    with pytest.raises(SourceError, match="FUTURE_ACTUAL_VALUE"):
        TradingEconomicsConnector().normalize(
            encode(calendar_rows()), CALENDAR, datetime(2024, 1, 1, tzinfo=UTC)
        )


@pytest.mark.parametrize("provider", ["sf1", "calendar"])
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
def test_http_errors_fail_closed_without_payload_logs(
    provider: str, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    transport = Fixture(EquityResponse(status, b"private-provider-message", "10"))
    client = (
        SharadarConnector(KEY, transport)
        if provider == "sf1"
        else TradingEconomicsConnector(KEY, transport)
    )
    with pytest.raises(SourceError) as error:
        if isinstance(client, SharadarConnector):
            client.fetch_range(SF1)
        else:
            client.fetch_range(CALENDAR)
    assert "private-provider-message" not in str(error.value) + caplog.text
    assert client.health().status == "FAILED"


@pytest.mark.parametrize("provider", ["sf1", "calendar"])
@pytest.mark.parametrize(
    "fault",
    [
        "timeout",
        "network",
        "bad_json",
        "duplicate_json",
        "secret_plain",
        "secret_json",
        "secret_url",
        "oversize",
    ],
)
def test_http_faults_and_escaped_secret_reflection(
    provider: str, fault: str, caplog: pytest.LogCaptureFixture
) -> None:
    body = b"{bad"
    if fault == "duplicate_json":
        body = b'{"a":1,"a":2}'
    elif fault == "secret_plain":
        body = encode({"message": KEY.value})
    elif fault == "secret_json":
        body = (
            '{"message":"' + "".join(f"\\u{ord(ch):04x}" for ch in KEY.value) + '"}'
        ).encode()
    elif fault == "secret_url":
        body = encode({"message": "".join(f"%{ord(ch):02X}" for ch in KEY.value)})
    elif fault == "oversize":
        body = b"x" * (MAX_RESPONSE_BYTES + 1)
    response = (
        TimeoutError("private")
        if fault == "timeout"
        else OSError("private")
        if fault == "network"
        else EquityResponse(200, body)
    )
    transport = Fixture(response)
    client = (
        SharadarConnector(KEY, transport)
        if provider == "sf1"
        else TradingEconomicsConnector(KEY, transport)
    )
    with pytest.raises(SourceError) as error:
        if isinstance(client, SharadarConnector):
            client.fetch_range(SF1)
        else:
            client.fetch_range(CALENDAR)
    assert KEY.value not in str(error.value) + caplog.text + repr(client)
    if isinstance(client, SharadarConnector):
        assert not client.last_pages
    else:
        assert client.last_raw is None


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"NaN",
        b"{bad",
        b'{"a":1,"a":2}',
        b'{"api_token":"private"}',
        b'{"url":"https://example.invalid/?c%3Dprivate"}',
    ],
)
def test_exact_json_refuses_malformed_and_credentials(raw: bytes) -> None:
    with pytest.raises(SourceError):
        exact_json(raw)


@pytest.mark.parametrize(
    "value", [Decimal("1e9999999"), Decimal("1e-13"), Decimal("NaN"), True, "1", 10**25]
)
def test_numeric_precision_bounded_before_expansion(value: object) -> None:
    with pytest.raises(SourceError):
        number(value)


def test_configuration_blocked_and_authority_invariants() -> None:
    with pytest.raises(SourceError, match="API_KEY_NOT_CONFIGURED"):
        SharadarConnector().fetch_range(SF1)
    with pytest.raises(SourceError, match="API_KEY_NOT_CONFIGURED"):
        TradingEconomicsConnector().fetch_range(CALENDAR)
    with pytest.raises(SourceError):
        EODHDFileImporter().validate_config(replace(EOD, currency="usd"))
    with pytest.raises(SourceError):
        EODHDFileImporter().validate_config(
            replace(EOD, declared_listing_status="APPROVED")
        )
    with pytest.raises(SourceError):
        SharadarConnector().validate_config(replace(SF1, max_pages=True))
    with pytest.raises(SourceError):
        TradingEconomicsConnector().validate_config(
            replace(CALENDAR, end=date(2024, 2, 1))
        )
    with pytest.raises(SourceError):
        EODHDFileImporter().import_bytes(
            encode(eod_rows()), EOD, STAMP, evidence_mode="HISTORICAL_REAL"
        )
    event = TradingEconomicsConnector().normalize(
        encode(calendar_rows()), CALENDAR, STAMP
    )[0]
    with pytest.raises(SourceError):
        TradingEconomicsConnector().validate_batch(
            (replace(event, point_in_time_eligible=True),), CALENDAR
        )
    record = SharadarConnector().normalize(encode(sf1_payload()), SF1, STAMP).records[0]
    with pytest.raises(SourceError):
        SharadarConnector().validate_batch(
            (replace(record, point_in_time_eligible=True),), SF1
        )
    tick = DukascopyDailyImporter().normalize(bi5(), DUKA, STAMP)[0]
    with pytest.raises(SourceError):
        DukascopyDailyImporter().validate_batch(
            (replace(tick, point_in_time_eligible=True),), DUKA
        )


@pytest.mark.parametrize(
    "encoded", [b"1e999999999999999999999999", b"1e9999999", b"0." + b"1" * 81]
)
def test_json_exponent_fault_is_sanitized_before_any_decimal_expansion(
    encoded: bytes,
) -> None:
    with pytest.raises(SourceError):
        exact_json(b'{"value":' + encoded + b"}")


def test_most_recent_datekey_must_keep_report_period_meaning() -> None:
    payload = sf1_payload()
    sf1_row(payload)[1] = "MRQ"
    with pytest.raises(SourceError, match="SF1_TEMPORAL_MISMATCH"):
        SharadarConnector().normalize(
            encode(payload), replace(SF1, dimension="MRQ"), STAMP
        )


@pytest.mark.parametrize(
    "host,target",
    [
        ("localhost", "/calendar/country/united%20states/2024-01-02/2024-01-03?f=json"),
        ("api.tradingeconomics.com", "https://evil.invalid/calendar?f=json"),
        (
            "api.tradingeconomics.com",
            "/calendar/country/united%20states/2024-01-02/2024-01-03?f=json&c=private",
        ),
        (
            "api.tradingeconomics.com",
            "/calendar/country/united%20states/2024-01-02/2024-01-03?f=json&f=json",
        ),
        (
            "api.tradingeconomics.com",
            "/calendar/country/united%20states/2024-01-02/2024-02-03?f=json",
        ),
        (
            "api.tradingeconomics.com",
            "/calendar/country/../../2024-01-02/2024-01-03?f=json",
        ),
        ("data.nasdaq.com", "/api/v3/datatables/SHARADAR/SF1.json?api_key=private"),
        ("data.nasdaq.com", "/api/v3/datatables/SHARADAR/TICKERS.json"),
    ],
)
def test_priority_fixed_endpoints_refuse_arbitrary_paths_and_url_secrets(
    host: str, target: str
) -> None:
    with pytest.raises(SourceError):
        PriorityRequest(host, target, KEY)


class SocketDouble:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def settimeout(self, value: float) -> None:
        assert 0 < value <= 10


class ResponseDouble:
    status = 200

    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self.body, self.headers = body, headers

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def read1(self, limit: int) -> bytes:
        value, self.body = self.body[:limit], self.body[limit:]
        return value


class ConnectionDouble:
    def __init__(self, response: ResponseDouble, failure: Exception | None) -> None:
        self.response, self.failure = response, failure
        self.sock: SocketDouble | None = None
        self.closed = False
        self.headers: dict[str, str] = {}

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        assert method == "GET" and KEY.value not in target
        self.headers = headers
        if self.failure:
            raise self.failure

    def getresponse(self) -> ResponseDouble:
        return self.response

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("provider", ["calendar", "sf1"])
@pytest.mark.parametrize(
    "case,code",
    [
        ("success", None),
        ("encoding", "ENCODED_RESPONSE_REFUSED"),
        ("length", "RESPONSE_TOO_LARGE"),
        ("body", "RESPONSE_TOO_LARGE"),
        ("timeout", "TIMEOUT"),
        ("network", "NETWORK_FAILURE"),
        ("tls", "NETWORK_FAILURE"),
        ("deadline", "TIMEOUT"),
    ],
)
def test_native_priority_transport_tls_auth_headers_and_limits(
    monkeypatch: pytest.MonkeyPatch, provider: str, case: str, code: str | None
) -> None:
    transport = Fixture(
        EquityResponse(
            200, encode(sf1_payload() if provider == "sf1" else calendar_rows())
        )
    )
    if provider == "sf1":
        SharadarConnector(KEY, transport).fetch_range(SF1)
    else:
        TradingEconomicsConnector(KEY, transport).fetch_range(CALENDAR)
    request = transport.requests[0]
    headers = (
        {"Content-Encoding": "gzip"}
        if case == "encoding"
        else {"Content-Length": "huge"}
        if case == "length"
        else {}
    )
    failure = (
        TimeoutError("private")
        if case == "timeout"
        else OSError("private")
        if case == "network"
        else None
    )
    connection = ConnectionDouble(
        ResponseDouble(
            b"x" * (MAX_RESPONSE_BYTES + 1) if case == "body" else b"{}", headers
        ),
        failure,
    )
    sock = SocketDouble()

    class TLS:
        def wrap_socket(
            self, raw: SocketDouble, *, server_hostname: str
        ) -> SocketDouble:
            assert raw is sock and server_hostname == request.host
            if case == "tls":
                raise OSError("private")
            return raw

    def connect(address: tuple[str, int], *, timeout: float) -> SocketDouble:
        assert address == ("8.8.8.8", 443) and timeout == 10
        return sock

    monkeypatch.setattr(
        "quant_hunter.sources.priority_transport.public_address", lambda _: "8.8.8.8"
    )
    monkeypatch.setattr("socket.create_connection", connect)
    monkeypatch.setattr("http.client.HTTPSConnection", lambda *_a, **_kw: connection)
    monkeypatch.setattr("ssl.create_default_context", TLS)
    if case == "deadline":
        times = iter([0.0, 11.0])
        monkeypatch.setattr(
            "quant_hunter.sources.priority_transport.time.monotonic",
            lambda: next(times),
        )
    if code:
        with pytest.raises(SourceError, match=code):
            PriorityHTTPS._send_once(request)
    else:
        assert PriorityHTTPS._send_once(request).body == b"{}"
        assert (
            connection.headers[
                "Authorization" if provider == "calendar" else "X-Api-Token"
            ]
            == KEY.value
        )
        assert "Bearer" not in connection.headers.get("Authorization", "")
    assert connection.closed
    if case == "tls":
        assert sock.closed


def test_priority_private_dns_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *_a, **_kw: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    request = PriorityRequest(
        "api.tradingeconomics.com",
        "/calendar/country/united%20states/2024-01-02/2024-01-03?f=json",
        KEY,
    )
    with pytest.raises(SourceError, match="NONPUBLIC_ADDRESS_REFUSED"):
        PriorityHTTPS._send_once(request)
