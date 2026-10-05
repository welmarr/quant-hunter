"""Offline macro contracts: dates/vintages are never silently availability."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest

from quant_hunter.sources._equity_transport import EquityResponse
from quant_hunter.sources.macro_bea import BEANIPAFileImporter, BEANIPAQuery
from quant_hunter.sources.macro_common import (
    decimal_text,
    reject_embedded_credentials,
    validate_macro_batch,
)
from quant_hunter.sources.macro_fred import (
    ALFREDFileImporter,
    ALFREDImportQuery,
    FREDKey,
    FREDReleaseConnector,
    FREDReleaseQuery,
)
from quant_hunter.sources.macro_g17 import G17Connector, G17Query
from quant_hunter.sources.macro_transport import MacroHTTPS, MacroRequest
from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, SourceError

STAMP = datetime(2026, 10, 5, tzinfo=UTC)
G17_QUERY = G17Query(date(2024, 1, 17))
FRED_QUERY = FREDReleaseQuery(13, page_size=2, max_pages=3)
FRED_KEY = FREDKey("fixture" + "0" * 25)
BEA_QUERY = BEANIPAQuery(
    "T10101",
    "A191RL",
    "Percent change, annual rate",
    0,
    date(2023, 1, 1),
    date(2023, 12, 31),
)
ALFRED_QUERY = ALFREDImportQuery(
    "TEST",
    "Index",
    date(2024, 1, 1),
    date(2024, 12, 31),
    date(2023, 1, 1),
    date(2023, 12, 31),
)

# Synthetic values in the documented January-2024 ASCII layout, not empirical data.
G17 = b"""FEDERAL RESERVE STATISTICAL RELEASE
 G.17 (419) For release at 9:15 a.m. (EST)
 January 17, 2024
 Industrial Production and Capacity Utilization:  Summary
 Seasonally adjusted
 | 2017=100 | Percent change
 | 2023 | 2023
 Industrial production | July[r] Aug.[r] Sept.[r] Oct.[r] Nov.[r] Dec.[p] | other
 Total index | 100.0 101.0 102.0 103.0 104.0 105.0 | other
 Previous estimates | 99.0 100.0 101.0 102.0 103.0 | other
 Table 1
"""


def encode(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def fred_page(
    day: str = "2023-01-01",
    *,
    cursor: str | None = None,
    unit: str = "Index",
    updated: str = "2024-02-01T12:00:00Z",
) -> bytes:
    result: dict[str, object] = {
        "release": {"release_id": 13},
        "has_more": cursor is not None,
        "series": [
            {
                "series_id": "TEST",
                "units": unit,
                "frequency": "Monthly",
                "seasonal_adjustment": "Seasonally Adjusted",
                "last_updated": updated,
                "copyright_id": "fixture rights only",
                "observations": [{"date": day, "value": "100.125"}],
            }
        ],
    }
    if cursor is not None:
        result["next_cursor"] = cursor
    return encode(result)


def vintage_payload() -> dict[str, object]:
    return {
        "realtime_start": "2024-01-01",
        "realtime_end": "2024-12-31",
        "observation_start": "2023-01-01",
        "observation_end": "2023-12-31",
        "units": "lin",
        "output_type": 1,
        "order_by": "observation_date",
        "sort_order": "asc",
        "count": 2,
        "offset": 0,
        "limit": 1000,
        "observations": [
            {
                "date": "2023-01-01",
                "realtime_start": "2024-01-01",
                "realtime_end": "2024-02-14",
                "value": "100",
            },
            {
                "date": "2023-01-01",
                "realtime_start": "2024-02-15",
                "realtime_end": "2024-12-31",
                "value": "101",
            },
        ],
    }


METADATA = b'{"seriess":[{"id":"TEST","units":"Index"}]}'


def bea_payload() -> dict[str, object]:
    return {
        "BEAAPI": {
            "Request": {
                "RequestParam": [
                    {"ParameterName": "USERID", "ParameterValue": "[REDACTED]"},
                    {"ParameterName": "METHOD", "ParameterValue": "GETDATA"},
                    {"ParameterName": "DATASETNAME", "ParameterValue": "NIPA"},
                    {"ParameterName": "TABLENAME", "ParameterValue": "T10101"},
                ]
            },
            "Results": {
                "Data": [
                    {
                        "TableName": "T10101",
                        "SeriesCode": "A191RL",
                        "TimePeriod": "2023Q1",
                        "CL_UNIT": "Percent change, annual rate",
                        "UNIT_MULT": "0",
                        "DataValue": "1.5",
                        "METRIC_NAME": "Quantity change",
                    }
                ]
            },
        }
    }


def bea_row(payload: dict[str, object]) -> dict[str, object]:
    root = cast(dict[str, object], payload["BEAAPI"])
    results = cast(dict[str, object], root["Results"])
    return cast(list[dict[str, object]], results["Data"])[0]


class Fixture:
    def __init__(self, *responses: EquityResponse | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[MacroRequest] = []

    def send(self, request: MacroRequest) -> EquityResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_g17_preserves_release_versions_and_stated_time() -> None:
    transport = Fixture(EquityResponse(200, G17))
    client = G17Connector(transport)
    result = client.test_connection(G17_QUERY)
    assert result.evidence_mode == "RECORDED_FIXTURE" and not result.coverage_complete
    assert len(result.observations) == 6 and result.raw_pages[0].raw == G17
    record = result.observations[-1]
    assert record.period_start == date(2023, 12, 1) and record.value == Decimal(105)
    assert record.publication_time == datetime(2024, 1, 17, 14, 15, tzinfo=UTC)
    assert (
        record.vintage == "2024-01-17"
        and record.available_at is None
        and not record.point_in_time_eligible
    )
    assert "PRELIMINARY" in record.quality_flags
    revised = G17.replace(b"January 17, 2024", b"February 15, 2024").replace(
        b"105.0", b"106.0"
    )
    other = client.normalize(revised, G17Query(date(2024, 2, 15)), STAMP)
    assert other[-1].value == 106 and record.value == 105
    assert other[-1].vintage != record.vintage
    assert transport.requests[0].target == "/releases/g17/20240117/g17.txt"
    assert (
        client.health().status == "SUCCEEDED"
        and "DATED_G17_ASCII" in client.list_capabilities()
    )


def test_g17_explicit_edt_and_ambiguous_et() -> None:
    client = G17Connector()
    summer = G17.replace(b"January 17, 2024", b"July 17, 2024").replace(
        b"(EST)", b"(EDT)"
    )
    record = client.normalize(summer, G17Query(date(2024, 7, 17)), STAMP)[0]
    assert record.publication_time == datetime(2024, 7, 17, 13, 15, tzinfo=UTC)
    unknown = client.normalize(G17.replace(b"(EST)", b"(ET)"), G17_QUERY, STAMP)[0]
    assert (
        unknown.publication_time is None
        and "PUBLICATION_TIME_UNKNOWN_AMBIGUOUS_ET" in unknown.quality_flags
    )


@pytest.mark.parametrize(
    "before,after,code",
    [
        (b"(EST)", b"(CET)", "UNSUPPORTED_PUBLICATION_ZONE"),
        (b"2017=100", b"2012=100", "G17_UNIT_MISMATCH"),
        (b"January 17", b"January 18", "RELEASE_DATE_MISMATCH"),
        (b"9:15", b"25:15", "INVALID_RELEASE_DATE_TIME"),
        (b"January", b"Unknown", "INVALID_RELEASE_DATE_TIME"),
        (b"July[r]", b"June[r]", "G17_MONTH_SEQUENCE"),
        (b"July[r]", b"Bogus[r]", "INVALID_MONTH"),
        (b"July[r]", b"July[?]", "UNSUPPORTED_MONTH_HEADER"),
        (b"| 2023 |", b"| 2022 2023 |", "G17_YEAR_SEQUENCE"),
        (b"105.0", b"-1", "INVALID_INDEX_LEVEL"),
        (b"105.0", b"", "G17_VALUE_COUNT"),
        (b"Seasonally adjusted", b"Other", "UNSUPPORTED_SEASONAL_ADJUSTMENT"),
        (b"Total index", b"Different series", "G17_TOTAL_INDEX_REQUIRED"),
    ],
)
def test_g17_rejects_ambiguous_or_contradictory_publication_and_schema(
    before: bytes, after: bytes, code: str
) -> None:
    with pytest.raises(SourceError, match=code):
        G17Connector().normalize(G17.replace(before, after), G17_QUERY, STAMP)


def test_fred_v2_real_header_contract_and_current_not_vintage() -> None:
    first = fred_page(cursor="TEST,2023-01-01")
    second = fred_page("2023-02-01")
    transport = Fixture(EquityResponse(200, first), EquityResponse(200, second))
    client = FREDReleaseConnector(FRED_KEY, transport)
    batch = client.test_connection(FRED_QUERY)
    assert len(batch.observations) == 2 and len(batch.raw_pages) == 2
    assert batch.raw_pages[0].raw == first and batch.evidence_mode == "RECORDED_FIXTURE"
    record = batch.observations[0]
    assert record.value == Decimal("100.125") and record.source_updated_at == datetime(
        2024, 2, 1, 12, tzinfo=UTC
    )
    assert record.publication_time is None and record.vintage == "LATEST_AT_RETRIEVAL"
    assert not record.point_in_time_eligible and record.available_at is None
    request = transport.requests[1]
    assert (
        request.bearer == FRED_KEY.value
        and FRED_KEY.value not in request.target + repr(request) + repr(FRED_KEY)
    )
    params = parse_qs(urlsplit(request.target).query)
    assert params["next_cursor"] == ["TEST,2023-01-01"] and params["limit"] == ["2"]
    assert (
        client.health().status == "SUCCEEDED"
        and "FRED_V2_HEADER_AUTH" in client.list_capabilities()
    )


@pytest.mark.parametrize(
    "second,code",
    [
        (fred_page("2023-02-01", cursor="TEST,2023-01-01"), "PAGINATION_LOOP"),
        (fred_page(), "DUPLICATE_OBSERVATION"),
        (fred_page("2023-02-01", unit="Percent"), "SERIES_CHANGED_DURING_PAGINATION"),
        (
            fred_page("2023-02-01", updated="2024-03-01T12:00:00Z"),
            "SERIES_CHANGED_DURING_PAGINATION",
        ),
    ],
)
def test_fred_pagination_rejects_loops_duplicates_units_and_revision_changes(
    second: bytes, code: str
) -> None:
    transport = Fixture(
        EquityResponse(200, fred_page(cursor="TEST,2023-01-01")),
        EquityResponse(200, second),
    )
    client = FREDReleaseConnector(FRED_KEY, transport)
    with pytest.raises(SourceError, match=code):
        client.fetch_range(FRED_QUERY)
    assert len(transport.requests) == 2 and client.health().status == "FAILED"


def test_fred_page_limit_refuses_partial_success() -> None:
    client = FREDReleaseConnector(
        FRED_KEY, Fixture(EquityResponse(200, fred_page(cursor="TEST,2023-01-01")))
    )
    with pytest.raises(SourceError, match="PAGINATION_LIMIT"):
        client.fetch_range(replace(FRED_QUERY, max_pages=1))


@pytest.mark.parametrize("provider", ["g17", "fred"])
@pytest.mark.parametrize(
    "status,code",
    [
        (401, "ACCESS_DENIED"),
        (403, "ACCESS_DENIED"),
        (404, "NOT_FOUND"),
        (429, "RATE_LIMITED"),
        (500, "HTTP_FAILURE"),
        (302, "REDIRECT_REFUSED"),
    ],
)
def test_http_errors_sanitized_no_retries(
    provider: str, status: int, code: str
) -> None:
    transport = Fixture(EquityResponse(status, b"private-provider-error", "13"))
    with pytest.raises(SourceError, match=code) as caught:
        if provider == "g17":
            G17Connector(transport).fetch_range(G17_QUERY)
        else:
            FREDReleaseConnector(FRED_KEY, transport).fetch_range(FRED_QUERY)
    assert len(transport.requests) == 1 and "private-provider" not in str(caught.value)
    assert caught.value.retry_after_seconds == (13 if status == 429 else None)


@pytest.mark.parametrize("provider", ["g17", "fred"])
@pytest.mark.parametrize(
    "failure,code",
    [(TimeoutError("private"), "TIMEOUT"), (OSError("private"), "NETWORK_FAILURE")],
)
def test_transport_failures_sanitized(
    provider: str, failure: Exception, code: str
) -> None:
    transport = Fixture(failure)
    with pytest.raises(SourceError, match=code):
        if provider == "g17":
            G17Connector(transport).fetch_range(G17_QUERY)
        else:
            FREDReleaseConnector(FRED_KEY, transport).fetch_range(FRED_QUERY)


@pytest.mark.parametrize("encoding", ["raw", "json", "url"])
def test_fred_reflected_credentials_rejected_before_retaining_errors(
    encoding: str, caplog: pytest.LogCaptureFixture
) -> None:
    value = FRED_KEY.value
    reflected = (
        value
        if encoding == "raw"
        else "".join(f"\\u{ord(char):04x}" for char in value)
        if encoding == "json"
        else "".join(f"%{ord(char):02x}" for char in value)
    )
    client = FREDReleaseConnector(
        FRED_KEY,
        Fixture(
            EquityResponse(403, encode({"echo": reflected}).replace(b"\\\\u", b"\\u"))
        ),
    )
    with pytest.raises(SourceError, match="SENSITIVE_RESPONSE_REFUSED") as caught:
        client.fetch_range(FRED_QUERY)
    assert not client.last_pages and value not in caplog.text + str(caught.value)


def test_alfred_retains_old_values_and_closed_realtime_intervals() -> None:
    raw = encode(vintage_payload())
    batch = ALFREDFileImporter().import_bytes(
        raw, METADATA, ALFRED_QUERY, STAMP, evidence_mode="RECORDED_FIXTURE"
    )
    assert [row.value for row in batch.observations] == [Decimal(100), Decimal(101)]
    assert [row.realtime_start for row in batch.observations] == [
        date(2024, 1, 1),
        date(2024, 2, 15),
    ]
    assert all(
        row.available_at is None
        and row.publication_time is None
        and not row.point_in_time_eligible
        for row in batch.observations
    )
    assert batch.raw_pages[0].raw == raw and len(batch.raw_pages) == 2
    assert ALFREDFileImporter.transport_status == "BLOCKED_EXTERNAL"


@pytest.mark.parametrize(
    "kind",
    [
        "overlap",
        "order",
        "missing-page",
        "wrong-range",
        "transform",
        "wrong-series",
        "wrong-unit",
        "secret",
    ],
)
def test_alfred_import_rejects_ambiguous_vintages_and_identity(kind: str) -> None:
    payload = vintage_payload()
    rows = cast(list[dict[str, object]], payload["observations"])
    metadata = METADATA
    if kind == "overlap":
        rows[1]["realtime_start"] = "2024-02-14"
    elif kind == "order":
        rows.reverse()
    elif kind == "missing-page":
        payload["count"] = 3
    elif kind == "wrong-range":
        payload["realtime_end"] = "2025-01-01"
    elif kind == "transform":
        payload["units"] = "pch"
    elif kind == "wrong-series":
        metadata = METADATA.replace(b"TEST", b"OTHER")
    elif kind == "wrong-unit":
        metadata = METADATA.replace(b"Index", b"Percent")
    else:
        payload["api_key"] = "synthetic fixture, not a key"
    with pytest.raises(SourceError):
        ALFREDFileImporter().import_bytes(
            encode(payload), metadata, ALFRED_QUERY, STAMP
        )


def test_bea_import_keeps_scale_and_owner_vintage_claim_separate() -> None:
    raw = encode(bea_payload())
    client = BEANIPAFileImporter()
    first = client.import_bytes(raw, BEA_QUERY, STAMP)
    record = first.observations[0]
    assert record.value == Decimal("1.5") and record.period_start == date(2023, 1, 1)
    assert record.publication_time is None and record.vintage == "LATEST_AT_EXPORT"
    vintage = client.import_bytes(
        raw, replace(BEA_QUERY, declared_vintage=date(2024, 1, 25)), STAMP
    )
    assert (
        vintage.observations[0].vintage == "2024-01-25"
        and not vintage.observations[0].point_in_time_eligible
    )
    revised_payload = bea_payload()
    bea_row(revised_payload)["DataValue"] = "1.7"
    revised = client.import_bytes(
        encode(revised_payload),
        replace(BEA_QUERY, declared_vintage=date(2024, 2, 28)),
        STAMP,
    )
    assert record.value == Decimal("1.5") and revised.observations[0].value == Decimal(
        "1.7"
    )
    assert (
        first.raw_pages[0].raw == raw and client.transport_status == "BLOCKED_EXTERNAL"
    )
    scaled = bea_payload()
    bea_row(scaled)["UNIT_MULT"] = "6"
    bea_row(scaled)["DataValue"] = "1,234.5"
    result = client.import_bytes(
        encode(scaled), replace(BEA_QUERY, unit_multiplier=6), STAMP
    )
    assert (
        result.observations[0].value == Decimal("1234.5")
        and result.observations[0].unit_multiplier == 6
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("SeriesCode", "WRONG"),
        ("TableName", "T10201"),
        ("UNIT_MULT", "6"),
        ("CL_UNIT", "Other"),
        ("TimePeriod", "2023Q5"),
        ("TimePeriod", "0000"),
        ("DataValue", "1,2"),
        ("DataValue", "NaN"),
        ("METRIC_NAME", None),
    ],
)
def test_bea_rejects_wrong_units_series_and_malformed_values(
    field: str, value: object
) -> None:
    payload = bea_payload()
    bea_row(payload)[field] = value
    with pytest.raises(SourceError):
        BEANIPAFileImporter().import_bytes(encode(payload), BEA_QUERY, STAMP)


def test_bea_rejects_unredacted_key_and_duplicate_rows() -> None:
    payload = bea_payload()
    with pytest.raises(SourceError, match="UNREDACTED_BEA_USERID_REFUSED"):
        BEANIPAFileImporter().import_bytes(
            encode(payload).replace(b"[REDACTED]", b"synthetic-unredacted-value"),
            BEA_QUERY,
            STAMP,
        )
    root = cast(dict[str, object], payload["BEAAPI"])
    result = cast(dict[str, object], root["Results"])
    rows = cast(list[dict[str, object]], result["Data"])
    rows.append(dict(rows[0]))
    with pytest.raises(SourceError, match="DUPLICATE_OBSERVATION"):
        BEANIPAFileImporter().import_bytes(encode(payload), BEA_QUERY, STAMP)


def test_bea_refuses_future_selected_period_and_declared_vintage() -> None:
    payload = bea_payload()
    bea_row(payload)["TimePeriod"] = "2030Q1"
    query = replace(BEA_QUERY, start=date(2030, 1, 1), end=date(2030, 12, 31))
    with pytest.raises(SourceError, match="FUTURE_OBSERVATION"):
        BEANIPAFileImporter().import_bytes(encode(payload), query, STAMP)
    with pytest.raises(SourceError, match="FUTURE_DECLARED_VINTAGE"):
        BEANIPAFileImporter().import_bytes(
            encode(bea_payload()),
            replace(BEA_QUERY, declared_vintage=date(2031, 1, 1)),
            STAMP,
        )


def test_bea_same_day_claim_and_future_query_end_are_not_availability() -> None:
    payload = bea_payload()
    bea_row(payload)["TimePeriod"] = "2026Q4"
    query = replace(
        BEA_QUERY,
        start=date(2026, 1, 1),
        end=date(2030, 12, 31),
        declared_vintage=STAMP.date(),
    )
    record = (
        BEANIPAFileImporter()
        .import_bytes(encode(payload), query, STAMP)
        .observations[0]
    )
    assert record.period_start == date(2026, 10, 1)
    assert record.vintage == "2026-10-05"
    assert record.available_at is None and not record.point_in_time_eligible


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("date", "2030-01-01", "FUTURE_OBSERVATION"),
        ("realtime_start", "2030-01-01", "FUTURE_REALTIME_START"),
    ],
)
def test_alfred_refuses_future_actual_observation_or_revision_start(
    field: str, value: str, code: str
) -> None:
    payload = vintage_payload()
    rows = cast(list[dict[str, object]], payload["observations"])
    rows[:] = [rows[0]]
    rows[0][field] = value
    rows[0]["realtime_end"] = "9999-12-31"
    payload["count"] = 1
    payload["realtime_end"] = "9999-12-31"
    payload["observation_end"] = "9999-12-31"
    query = replace(ALFRED_QUERY, realtime_end=date.max, observation_end=date.max)
    with pytest.raises(SourceError, match=code):
        ALFREDFileImporter().import_bytes(encode(payload), METADATA, query, STAMP)


def test_alfred_keeps_open_validity_end_and_future_query_bounds_permissible() -> None:
    payload = vintage_payload()
    rows = cast(list[dict[str, object]], payload["observations"])
    rows[1]["realtime_start"] = STAMP.date().isoformat()
    rows[1]["realtime_end"] = "9999-12-31"
    payload["realtime_end"] = "9999-12-31"
    payload["observation_end"] = "9999-12-31"
    query = replace(ALFRED_QUERY, realtime_end=date.max, observation_end=date.max)
    records = (
        ALFREDFileImporter()
        .import_bytes(encode(payload), METADATA, query, STAMP)
        .observations
    )
    assert [record.value for record in records] == [Decimal(100), Decimal(101)]
    assert records[1].realtime_start == STAMP.date()
    assert records[1].realtime_end == date.max
    assert all(
        record.available_at is None and not record.point_in_time_eligible
        for record in records
    )


@pytest.mark.parametrize(
    "value", ["0.1234567890123", "9" * 39, "1e999", "Infinity", "1.2.3"]
)
def test_decimal_bound_and_nonfinite_rejected(value: str) -> None:
    with pytest.raises(SourceError):
        decimal_text(value)


def test_missing_values_and_invalid_json_never_become_zero() -> None:
    assert decimal_text(".") is None
    for raw in (b"", b"{", b"[]", b'{"x":1,"x":2}', b"\xff"):
        with pytest.raises(SourceError):
            FREDReleaseConnector(FRED_KEY).normalize(raw, FRED_QUERY, STAMP)
        with pytest.raises(SourceError):
            BEANIPAFileImporter().normalize(raw, BEA_QUERY, STAMP)
    missing = fred_page().replace(b'"100.125"', b'"."')
    assert (
        FREDReleaseConnector(FRED_KEY)
        .normalize(missing, FRED_QUERY, STAMP)
        .observations[0]
        .value
        is None
    )
    with pytest.raises(SourceError):
        reject_embedded_credentials({"url": "https://example.test/?api_key=synthetic"})


def test_auth_and_transport_endpoint_restrictions() -> None:
    client = FREDReleaseConnector()
    assert client.health().status == "NOT_CONFIGURED"
    with pytest.raises(SourceError, match="FRED_KEY_NOT_CONFIGURED"):
        client.fetch_range(FRED_QUERY)
    with pytest.raises(SourceError):
        FREDKey("bad")
    for host, target in (
        ("apps.bea.gov", "/api/data"),
        ("api.stlouisfed.org", "/fred/series/observations"),
        ("127.0.0.1", "/"),
        ("www.federalreserve.gov", "/releases/g17/current/g17.txt"),
    ):
        with pytest.raises(SourceError):
            MacroRequest(host, target)
    with pytest.raises(SourceError):
        MacroRequest(
            "api.stlouisfed.org",
            "/fred/v2/release/observations?release_id=13&format=json&limit=2&api_key=x",
            FRED_KEY.value,
        )
    with pytest.raises(SourceError):
        MacroRequest(
            "www.federalreserve.gov", "/releases/g17/20240117/g17.txt", FRED_KEY.value
        )


def test_configuration_timezones_ranges_and_batch_authority() -> None:
    with pytest.raises(SourceError):
        G17Connector().validate_config(G17Query(date(1900, 1, 1)))
    with pytest.raises(SourceError):
        FREDReleaseConnector(FRED_KEY).validate_config(
            replace(FRED_QUERY, page_size=True)
        )
    with pytest.raises(SourceError):
        ALFREDFileImporter().validate_config(
            replace(ALFRED_QUERY, realtime_start=date(2025, 1, 1))
        )
    with pytest.raises(SourceError):
        BEANIPAFileImporter().validate_config(replace(BEA_QUERY, unit_multiplier=15))
    with pytest.raises(SourceError):
        G17Connector().normalize(G17, G17_QUERY, STAMP.replace(tzinfo=None))
    with pytest.raises(SourceError):
        G17Connector().normalize(G17, G17_QUERY, datetime(2024, 1, 17, 12, tzinfo=UTC))
    record = G17Connector().normalize(G17, G17_QUERY, STAMP)[0]
    with pytest.raises(SourceError):
        validate_macro_batch((replace(record, point_in_time_eligible=True),), "SRC-06")
    with pytest.raises(SourceError):
        validate_macro_batch((record,), "SRC-07")


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
        assert method == "GET" and FRED_KEY.value not in target
        self.headers = headers
        if self.failure:
            raise self.failure

    def getresponse(self) -> ResponseDouble:
        return self.response

    def close(self) -> None:
        self.closed = True


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
def test_macro_https_auth_only_header_pinned_ip_and_bounds(
    monkeypatch: pytest.MonkeyPatch, case: str, code: str | None
) -> None:
    headers = (
        {"Content-Encoding": "gzip"}
        if case == "encoding"
        else {"Content-Length": "bad"}
        if case == "length"
        else {}
    )
    body = b"x" * (MAX_RESPONSE_BYTES + 1) if case == "body" else b"{}"
    failure = (
        TimeoutError("private")
        if case == "timeout"
        else OSError("private")
        if case == "network"
        else None
    )
    connection = ConnectionDouble(ResponseDouble(body, headers), failure)
    sock = SocketDouble()

    class TLS:
        def wrap_socket(
            self, raw: SocketDouble, *, server_hostname: str
        ) -> SocketDouble:
            assert raw is sock and server_hostname == "api.stlouisfed.org"
            if case == "tls":
                raise OSError("private")
            return raw

    def connect(address: tuple[str, int], *, timeout: float) -> SocketDouble:
        assert address == ("8.8.8.8", 443) and timeout == 10
        return sock

    monkeypatch.setattr(
        "quant_hunter.sources.macro_transport.public_address", lambda _: "8.8.8.8"
    )
    monkeypatch.setattr("socket.create_connection", connect)
    monkeypatch.setattr("http.client.HTTPSConnection", lambda *_a, **_kw: connection)
    monkeypatch.setattr("ssl.create_default_context", TLS)
    if case == "deadline":
        times = iter([0.0, 11.0])
        monkeypatch.setattr(
            "quant_hunter.sources.macro_transport.time.monotonic", lambda: next(times)
        )
    request = MacroRequest(
        "api.stlouisfed.org",
        "/fred/v2/release/observations?release_id=13&format=json&limit=2",
        FRED_KEY.value,
    )
    if code:
        with pytest.raises(SourceError, match=code):
            MacroHTTPS._send_once(request)
    else:
        assert MacroHTTPS._send_once(request).body == b"{}"
        assert connection.headers["Authorization"] == "Bearer " + FRED_KEY.value
    assert connection.closed
    if case == "tls":
        assert sock.closed


def test_private_dns_refused_before_macro_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *_a, **_kw: [(2, 1, 6, "", ("10.0.0.1", 443))]
    )
    with pytest.raises(SourceError, match="NONPUBLIC_ADDRESS_REFUSED"):
        MacroHTTPS._send_once(
            MacroRequest("www.federalreserve.gov", "/releases/g17/20240117/g17.txt")
        )


@pytest.mark.parametrize("field,value", [("output_type", True), ("offset", False)])
def test_alfred_rejects_boolean_counters(field: str, value: bool) -> None:
    payload = vintage_payload()
    payload[field] = value
    with pytest.raises(SourceError):
        ALFREDFileImporter().normalize(encode(payload), METADATA, ALFRED_QUERY, STAMP)


@pytest.mark.parametrize(
    "embedded",
    [
        {"UserID": "owner-private-fixture"},
        {"ParameterName": "USERID", "ParameterValue": "owner-private-fixture"},
        {"url": "https://example.invalid/?userid%3Downer-private-fixture"},
    ],
)
def test_bea_rejects_nested_credentials_outside_request_metadata(
    embedded: dict[str, str],
) -> None:
    payload = bea_payload()
    payload["extra"] = embedded
    with pytest.raises(SourceError):
        BEANIPAFileImporter().import_bytes(encode(payload), BEA_QUERY, STAMP)


def test_g17_failed_parse_retains_bounded_raw_but_never_oversize() -> None:
    raw = b"provider shape changed"
    client = G17Connector(Fixture(EquityResponse(200, raw)))
    with pytest.raises(SourceError, match="G17_RELEASE_HEADER_REQUIRED"):
        client.fetch_range(G17_QUERY)
    assert client.last_raw == raw and client.last_batch is None
    oversized = G17Connector(
        Fixture(EquityResponse(200, b"x" * (MAX_RESPONSE_BYTES + 1)))
    )
    with pytest.raises(SourceError, match="RESPONSE_TOO_LARGE"):
        oversized.fetch_range(G17_QUERY)
    assert oversized.last_raw is None


@pytest.mark.parametrize(
    "mutation,code",
    [
        ({"release": {"release_id": True}}, "RELEASE_ID_MISMATCH"),
        ({"has_more": 1}, "INVALID_PAGINATION_STATE"),
        ({"has_more": True}, "INVALID_CURSOR"),
        ({"next_cursor": "TEST,2023-01-01"}, "CONTRADICTORY_PAGINATION"),
        ({"has_more": True, "next_cursor": "TEST,2023-02-31"}, "INVALID_DATE"),
        ({"series": {}}, "INVALID_SERIES_SCHEMA"),
    ],
)
def test_fred_rejects_false_identity_and_pagination_contracts(
    mutation: dict[str, object], code: str
) -> None:
    payload = json.loads(fred_page())
    payload.update(mutation)
    with pytest.raises(SourceError, match=code):
        FREDReleaseConnector(FRED_KEY).normalize(encode(payload), FRED_QUERY, STAMP)


def test_g17_year_rollover_keeps_economic_date_separate_from_release() -> None:
    raw = (
        G17.replace(b"January 17, 2024", b"March 15, 2024")
        .replace(b"| 2023 | 2023", b"| 2023 2024 | 2024")
        .replace(
            b"July[r] Aug.[r] Sept.[r] Oct.[r] Nov.[r] Dec.[p]",
            b"Sept.[r] Oct.[r] Nov.[r] Dec.[r] Jan.[r] Feb.[p]",
        )
    )
    records = G17Connector().normalize(raw, G17Query(date(2024, 3, 15)), STAMP)
    assert records[0].period_start == date(2023, 9, 1)
    assert records[-1].period_start == date(2024, 2, 1)
    assert all(record.vintage == "2024-03-15" for record in records)
