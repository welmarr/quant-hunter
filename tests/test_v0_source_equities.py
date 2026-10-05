"""Offline SEC/Alpaca contracts; identities and credentials are synthetic."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest

from quant_hunter.sources._equity_transport import (
    EquityHTTPS,
    EquityRequest,
    EquityResponse,
    json_object,
    number,
    receive,
)
from quant_hunter.sources.alpaca_data import (
    AlpacaBarQuery,
    AlpacaCredentials,
    AlpacaDataConnector,
)
from quant_hunter.sources.sec import (
    SECConnector,
    SECFact,
    SECFiling,
    SECIdentity,
    SECQuery,
)
from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, SourceError


@pytest.mark.parametrize(
    "raw",
    [
        b'{"unused":1e999999999999999999999999}',
        b'{"unused":1e-999999999999999999999999}',
    ],
)
def test_json_decimal_overflow_is_a_sanitized_source_failure(raw: bytes) -> None:
    with pytest.raises(SourceError, match="INVALID_JSON") as error:
        json_object(raw)
    assert "unused" not in str(error.value)


STAMP = datetime(2026, 10, 5, tzinfo=UTC)
IDENTITY = SECIdentity("Synthetic Test Organization", "synthetic@example.test")
# Explicit test-only values, not service credentials.
CREDENTIALS = AlpacaCredentials(
    "fixture-paper-key", "fixture-paper-secret", "PAPER_ACCOUNT"
)
SEC_QUERY = SECQuery("0000000123", date(2024, 1, 1), date(2024, 12, 31))
FACT_QUERY = replace(
    SEC_QUERY, resource="company_concept", taxonomy="us-gaap", concept="Assets"
)
BAR_QUERY = AlpacaBarQuery(
    "TEST", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 5, tzinfo=UTC), "iex"
)


def encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def submissions() -> dict[str, object]:
    return {
        "cik": "0000000123",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000999-24-000001", "0000000999-24-000002"],
                "filingDate": ["2024-02-01", "2024-03-01"],
                "reportDate": ["2023-12-31", "2023-12-31"],
                "acceptanceDateTime": [
                    "2024-01-31T22:40:00.000Z",
                    "2024-03-01T18:00:00Z",
                ],
                "form": ["10-K", "10-K/A"],
                "primaryDocument": ["form10k.htm", "amendment.htm"],
            },
            "files": [{"name": "CIK0000000123-submissions-001.json"}],
        },
    }


def facts() -> dict[str, object]:
    return {
        "cik": 123,
        "taxonomy": "us-gaap",
        "tag": "Assets",
        "units": {
            "USD": [
                {
                    "end": "2023-12-31",
                    "val": 100,
                    "accn": "0000000999-24-000001",
                    "fy": 2023,
                    "fp": "FY",
                    "form": "10-K",
                    "filed": "2024-02-01",
                },
                {
                    "end": "2023-12-31",
                    "val": 110,
                    "accn": "0000000999-24-000002",
                    "fy": 2023,
                    "fp": "FY",
                    "form": "10-K/A",
                    "filed": "2024-03-01",
                },
            ],
            "EUR": [
                {
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                    "val": 95.25,
                    "accn": "0000000999-24-000001",
                    "form": "10-K",
                    "filed": "2024-02-01",
                    "frame": "CY2023",
                }
            ],
        },
    }


def bar(day: int = 2) -> dict[str, object]:
    return {
        "t": f"2024-01-{day:02d}T05:00:00Z",
        "o": 100.25,
        "h": 102,
        "l": 99,
        "c": 101.5,
        "v": 250,
        "n": 8,
        "vw": 100.75,
    }


def bars(
    *, rows: list[dict[str, object]] | None = None, next_page: str | None = None
) -> bytes:
    return encoded(
        {
            "bars": {"TEST": [bar()] if rows is None else rows},
            "next_page_token": next_page,
        }
    )


class Fixture:
    def __init__(self, *responses: EquityResponse | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[EquityRequest] = []

    def send(self, request: EquityRequest) -> EquityResponse:
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize("encoding", ["unicode", "percent"])
def test_escaped_secret_reflection_never_becomes_raw_evidence(encoding: str) -> None:
    secret = CREDENTIALS.secret_key
    reflected = (
        "".join(f"\\u{ord(character):04x}" for character in secret)
        if encoding == "unicode"
        else "".join(f"%{ord(character):02x}" for character in secret)
    )
    raw = ('{"echo":"' + reflected + '"}').encode()
    client = AlpacaDataConnector(CREDENTIALS, Fixture(EquityResponse(401, raw)))
    with pytest.raises(SourceError, match="SENSITIVE_RESPONSE_REFUSED"):
        client.fetch_range(BAR_QUERY)
    assert client.last_pages == ()


@pytest.mark.parametrize("value", ["1e-1000000", "0e1000000", "1.0000000000001"])
def test_numeric_encoding_cannot_expand_without_bound(value: str) -> None:
    with pytest.raises(SourceError, match="UNSUPPORTED_NUMBER_PRECISION"):
        number(Decimal(value))


def test_hostile_transport_body_limit_precedes_reflection_decode() -> None:
    request = AlpacaDataConnector(CREDENTIALS)._request(BAR_QUERY, None)
    with pytest.raises(SourceError, match="RESPONSE_TOO_LARGE"):
        receive(Fixture(EquityResponse(200, b"x" * (MAX_RESPONSE_BYTES + 1))), request)


def test_sec_preserves_accession_amendment_and_distinct_times() -> None:
    raw = encoded(submissions())
    transport = Fixture(EquityResponse(200, raw))
    client = SECConnector(IDENTITY, transport)
    result = client.test_connection(SEC_QUERY)
    original, amendment = result.records
    assert isinstance(original, SECFiling) and isinstance(amendment, SECFiling)
    assert original.accession == "0000000999-24-000001"  # Agent CIK can differ.
    assert original.acceptance_time == datetime(2024, 1, 31, 22, 40, tzinfo=UTC)
    assert original.filing_date == date(2024, 2, 1)
    assert not original.is_amendment and amendment.is_amendment
    assert original.publication_time is None and not original.point_in_time_eligible
    assert result.raw_pages[0].raw == raw
    assert result.raw_pages[0].digest == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert result.evidence_mode == "RECORDED_FIXTURE" and not result.coverage_complete
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.target == "/submissions/CIK0000000123.json"
    assert request.user_agent == IDENTITY.user_agent() and request.key_id is None
    assert client.health().status == "SUCCEEDED"
    assert "RECENT_SUBMISSIONS" in client.list_capabilities()


def test_sec_facts_keeps_every_revision_unit_and_filing_date() -> None:
    transport = Fixture(EquityResponse(200, encoded(facts())))
    result = SECConnector(IDENTITY, transport).fetch_range(FACT_QUERY)
    originals = [record for record in result.records if isinstance(record, SECFact)]
    assert [record.value for record in originals] == [
        Decimal(100),
        Decimal(110),
        Decimal("95.25"),
    ]
    assert [record.unit for record in originals] == ["USD", "USD", "EUR"]
    assert (
        originals[1].is_amendment
        and originals[0].filing_date != originals[1].filing_date
    )
    assert all(
        record.acceptance_time is None and record.publication_time is None
        for record in originals
    )
    assert (
        transport.requests[0].target
        == "/api/xbrl/companyconcept/CIK0000000123/us-gaap/Assets.json"
    )
    limited = SECConnector(IDENTITY).normalize(
        encoded(facts()), replace(FACT_QUERY, end=date(2024, 2, 15)), STAMP
    )
    assert len(limited) == 2


def test_sec_empty_results_and_missing_acceptance_do_not_invent_times() -> None:
    payload = submissions()
    recent = cast(
        dict[str, object], cast(dict[str, object], payload["filings"])["recent"]
    )
    recent["acceptanceDateTime"] = [None, ""]
    recent["reportDate"] = ["", ""]
    result = SECConnector(IDENTITY).normalize(encoded(payload), SEC_QUERY, STAMP)
    assert all(
        isinstance(record, SECFiling)
        and record.acceptance_time is None
        and record.report_date is None
        for record in result
    )
    assert (
        SECConnector(IDENTITY).normalize(
            encoded(payload), replace(SEC_QUERY, end=date(2024, 1, 2)), STAMP
        )
        == ()
    )


@pytest.mark.parametrize("kind", ["sec", "alpaca"])
@pytest.mark.parametrize(
    "status,code",
    [
        (401, "ACCESS_DENIED"),
        (403, "ACCESS_DENIED"),
        (404, "NOT_FOUND"),
        (429, "RATE_LIMITED"),
        (500, "HTTP_FAILURE"),
        (503, "HTTP_FAILURE"),
        (302, "REDIRECT_REFUSED"),
    ],
)
def test_http_failures_are_sanitized_and_never_retried(
    kind: str, status: int, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    transport = Fixture(EquityResponse(status, b"provider-private-message", "17"))
    with pytest.raises(SourceError, match=code) as caught:
        if kind == "sec":
            SECConnector(IDENTITY, transport).fetch_range(SEC_QUERY)
        else:
            AlpacaDataConnector(CREDENTIALS, transport).fetch_range(BAR_QUERY)
    assert caught.value.retry_after_seconds == (17 if status == 429 else None)
    assert "provider-private" not in str(caught.value) + caplog.text
    assert len(transport.requests) == 1


@pytest.mark.parametrize("kind", ["sec", "alpaca"])
@pytest.mark.parametrize(
    "failure,code",
    [
        (TimeoutError("sensitive-detail"), "TIMEOUT"),
        (OSError("sensitive-detail"), "NETWORK_FAILURE"),
    ],
)
def test_network_failures_update_health_without_exception_details(
    kind: str, failure: Exception, code: str
) -> None:
    transport = Fixture(failure)
    if kind == "sec":
        client = SECConnector(IDENTITY, transport)
        with pytest.raises(SourceError, match=code) as caught:
            client.fetch_range(SEC_QUERY)
        assert client.health().status == "FAILED"
    else:
        other = AlpacaDataConnector(CREDENTIALS, transport)
        with pytest.raises(SourceError, match=code) as caught:
            other.fetch_range(BAR_QUERY)
        assert other.health().status == "FAILED"
    assert "sensitive-detail" not in str(caught.value)


@pytest.mark.parametrize(
    "raw", [b"", b"{", b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"{}"]
)
def test_bad_json_missing_fields_and_nonfinite_rejected(raw: bytes) -> None:
    with pytest.raises(SourceError):
        SECConnector(IDENTITY).normalize(raw, SEC_QUERY, STAMP)
    with pytest.raises(SourceError):
        AlpacaDataConnector(CREDENTIALS).normalize(raw, BAR_QUERY, STAMP)


@pytest.mark.parametrize(
    "field,value",
    [
        ("accessionNumber", ["bad", "bad"]),
        ("filingDate", ["2024-99-01", "2024-03-01"]),
        ("acceptanceDateTime", ["2024-01-31T17:40:00", ""]),
        ("primaryDocument", ["../secret", "amendment.htm"]),
        ("form", ["10-K"]),
        ("reportDate", None),
    ],
)
def test_sec_rejects_malformed_columns(field: str, value: object) -> None:
    payload = submissions()
    recent = cast(
        dict[str, object], cast(dict[str, object], payload["filings"])["recent"]
    )
    recent[field] = value
    with pytest.raises(SourceError):
        SECConnector(IDENTITY).normalize(encoded(payload), SEC_QUERY, STAMP)


def test_sec_duplicate_accession_and_contradictory_identity_fail() -> None:
    payload = submissions()
    recent = cast(
        dict[str, object], cast(dict[str, object], payload["filings"])["recent"]
    )
    recent["accessionNumber"] = ["0000000999-24-000001"] * 2
    with pytest.raises(SourceError, match="DUPLICATE_ACCESSION"):
        SECConnector(IDENTITY).normalize(encoded(payload), SEC_QUERY, STAMP)
    payload = submissions()
    payload["cik"] = True
    with pytest.raises(SourceError, match="CONTRADICTORY_CIK"):
        SECConnector(IDENTITY).normalize(encoded(payload), SEC_QUERY, STAMP)
    payload = facts()
    payload["taxonomy"] = "wrong"
    with pytest.raises(SourceError, match="CONTRADICTORY_CONCEPT"):
        SECConnector(IDENTITY).normalize(encoded(payload), FACT_QUERY, STAMP)


@pytest.mark.parametrize(
    "field,value",
    [
        ("val", True),
        ("val", "100"),
        ("val", 1e30),
        ("fy", True),
        ("fp", "bad value"),
        ("frame", "bad value"),
        ("start", "2024-12-31"),
        ("accn", "bad"),
        ("filed", None),
    ],
)
def test_sec_facts_rejects_invalid_numeric_period_and_identity(
    field: str, value: object
) -> None:
    payload = facts()
    units = cast(dict[str, list[dict[str, object]]], payload["units"])
    units["USD"][0][field] = value
    with pytest.raises(SourceError):
        SECConnector(IDENTITY).normalize(encoded(payload), FACT_QUERY, STAMP)


def test_sec_duplicate_fact_not_resolved_by_selecting_one_value() -> None:
    payload = facts()
    units = cast(dict[str, list[dict[str, object]]], payload["units"])
    units["USD"].append({**units["USD"][0], "val": 999})
    with pytest.raises(SourceError, match="DUPLICATE_OR_CONTRADICTORY_FACT"):
        SECConnector(IDENTITY).normalize(encoded(payload), FACT_QUERY, STAMP)


def test_alpaca_paginates_boundedly_preserving_raw_feed_and_utc() -> None:
    first, second = bars(next_page="page-two=="), bars(rows=[bar(3)])
    transport = Fixture(EquityResponse(200, first), EquityResponse(200, second))
    client = AlpacaDataConnector(CREDENTIALS, transport)
    result = client.test_connection(BAR_QUERY)
    assert [record.timestamp.day for record in result.records] == [2, 3]
    assert [page.raw for page in result.raw_pages] == [first, second]
    assert result.evidence_mode == "RECORDED_FIXTURE"
    assert result.pagination_exhausted and not result.coverage_complete
    assert result.records[0].open == Decimal("100.25")
    assert (
        result.records[0].available_at is None
        and not result.records[0].point_in_time_eligible
    )
    assert "IEX_SINGLE_VENUE_PARTIAL_COVERAGE" in result.records[0].quality_flags
    request = transport.requests[-1]
    params = parse_qs(urlsplit(request.target).query)
    assert params["feed"] == ["iex"] and params["adjustment"] == ["raw"]
    assert params["asof"] == ["-"] and params["page_token"] == ["page-two=="]
    assert (
        CREDENTIALS.key_id not in request.target
        and CREDENTIALS.secret_key not in request.target
    )
    assert (
        request.key_id == CREDENTIALS.key_id and client.health().status == "SUCCEEDED"
    )
    assert "NO_ORDERS_NO_BROKER_HOST" in client.list_capabilities()


def test_alpaca_sip_requires_explicit_caller_authorization_and_no_fallback() -> None:
    transport = Fixture(EquityResponse(200, bars()))
    query = replace(BAR_QUERY, feed="sip")
    with pytest.raises(SourceError, match="FEED_NOT_AUTHORIZED"):
        AlpacaDataConnector(CREDENTIALS, transport).fetch_range(query)
    assert not transport.requests
    record = (
        AlpacaDataConnector(CREDENTIALS, transport, allowed_feeds=("sip",))
        .fetch_range(query)
        .records[0]
    )
    assert (
        record.feed == "sip"
        and "SIP_ENTITLEMENT_AND_COVERAGE_NOT_CERTIFIED" in record.quality_flags
    )


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("loop", "PAGINATION_LOOP"),
        ("limit", "PAGINATION_LIMIT"),
        ("duplicate", "DUPLICATE_OR_UNORDERED_BAR"),
        ("descending", "DUPLICATE_OR_UNORDERED_BAR"),
    ],
)
def test_alpaca_pagination_attacks_cannot_loop_or_repeat_rows(
    scenario: str, code: str
) -> None:
    responses = [EquityResponse(200, bars(next_page="token-one"))]
    if scenario == "loop":
        responses.append(
            EquityResponse(200, bars(rows=[bar(3)], next_page="token-one"))
        )
    elif scenario == "duplicate":
        responses.append(EquityResponse(200, bars()))
    elif scenario == "descending":
        responses = [EquityResponse(200, bars(rows=[bar(3), bar(2)]))]
    transport = Fixture(*responses)
    client = AlpacaDataConnector(CREDENTIALS, transport)
    query = replace(BAR_QUERY, max_pages=1) if scenario == "limit" else BAR_QUERY
    with pytest.raises(SourceError, match=code):
        client.fetch_range(query)
    assert len(transport.requests) <= 2 and client.health().status == "FAILED"
    assert len(client.last_pages) == len(transport.requests)


@pytest.mark.parametrize(
    "field,value",
    [
        ("h", 98),
        ("l", 105),
        ("o", 0),
        ("c", None),
        ("v", -1),
        ("n", True),
        ("n", 1.5),
        ("vw", 0),
        ("t", "2024-01-02T05:00:00"),
        ("t", "2024-01-02T05:00:00.000000001Z"),
        ("t", "2024-01-09T05:00:00Z"),
    ],
)
def test_alpaca_invalid_ohlc_timing_and_counts_fail(field: str, value: object) -> None:
    row = bar()
    row[field] = value
    with pytest.raises(SourceError):
        AlpacaDataConnector(CREDENTIALS).normalize(bars(rows=[row]), BAR_QUERY, STAMP)


def test_alpaca_empty_and_null_vwap_are_explicit() -> None:
    client = AlpacaDataConnector(CREDENTIALS)
    assert (
        client.normalize(
            b'{"bars":{},"next_page_token":null}', BAR_QUERY, STAMP
        ).records
        == ()
    )
    row = bar()
    row["vw"] = None
    row["t"] = "2024-01-02T05:00:00.000000000Z"
    assert client.normalize(bars(rows=[row]), BAR_QUERY, STAMP).records[0].vwap is None
    with pytest.raises(SourceError, match="CONTRADICTORY_SYMBOL"):
        client.normalize(bars().replace(b'"TEST"', b'"OTHER"'), BAR_QUERY, STAMP)
    with pytest.raises(SourceError, match="INVALID_PAGE_TOKEN"):
        client.normalize(bars(next_page="http://127.0.0.1"), BAR_QUERY, STAMP)


def test_credentials_contact_response_and_errors_are_not_logged_or_repr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = AlpacaDataConnector(CREDENTIALS)._request(BAR_QUERY, None)
    assert CREDENTIALS.key_id not in repr(CREDENTIALS) + repr(request)
    assert CREDENTIALS.secret_key not in repr(CREDENTIALS) + repr(request)
    assert IDENTITY.contact_email not in repr(IDENTITY)
    reflected = EquityResponse(401, encoded({"echo": CREDENTIALS.secret_key}))
    assert CREDENTIALS.secret_key not in repr(reflected)
    client = AlpacaDataConnector(CREDENTIALS, Fixture(reflected))
    with pytest.raises(SourceError, match="SENSITIVE_RESPONSE_REFUSED") as caught:
        client.fetch_range(BAR_QUERY)
    assert CREDENTIALS.secret_key not in str(caught.value) + caplog.text
    assert client.last_pages == ()


def test_unconfigured_and_live_account_credentials_block_before_network() -> None:
    transport = Fixture()
    sec, alpaca = (
        SECConnector(transport=transport),
        AlpacaDataConnector(transport=transport),
    )
    assert sec.health().status == alpaca.health().status == "NOT_CONFIGURED"
    with pytest.raises(SourceError, match="NOT_CONFIGURED"):
        sec.fetch_range(SEC_QUERY)
    with pytest.raises(SourceError, match="NOT_CONFIGURED"):
        alpaca.fetch_range(BAR_QUERY)
    with pytest.raises(SourceError, match="PAPER_OR_READ_ONLY"):
        AlpacaCredentials("fixture-key", "fixture-secret", "LIVE_ACCOUNT")
    with pytest.raises(SourceError, match="SEC_CONTACT"):
        SECIdentity("Fixture organization", "contact-missing")
    assert not transport.requests


@pytest.mark.parametrize(
    "changes",
    [
        {"cik": "123"},
        {"cik": "0000000000"},
        {"start": date(2025, 1, 1)},
        {"resource": "companyfacts"},
        {"taxonomy": "us-gaap"},
    ],
)
def test_sec_invalid_configuration_rejected(changes: dict[str, object]) -> None:
    query = replace(SEC_QUERY)
    for key, value in changes.items():
        object.__setattr__(query, key, value)  # Deliberately hostile runtime types.
    with pytest.raises(SourceError):
        SECConnector(IDENTITY).validate_config(query)


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "../x"},
        {"feed": "auto"},
        {"timeframe": "5Hour"},
        {"start": datetime(2024, 1, 1)},
        {"end": datetime(2027, 1, 1, tzinfo=UTC)},
        {"page_size": True},
        {"max_pages": 6},
    ],
)
def test_alpaca_invalid_configuration_rejected(changes: dict[str, object]) -> None:
    query = replace(BAR_QUERY)
    for key, value in changes.items():
        object.__setattr__(query, key, value)  # Deliberately hostile runtime types.
    with pytest.raises(SourceError):
        AlpacaDataConnector(CREDENTIALS).validate_config(query)


@pytest.mark.parametrize(
    "host,target",
    [
        ("api.alpaca.markets", "/v2/orders"),
        ("paper-api.alpaca.markets", "/v2/orders"),
        ("127.0.0.1", "/"),
        ("data.sec.gov", "/submissions/../../secret"),
        ("data.sec.gov", "https://data.sec.gov/submissions/CIK0000000123.json"),
    ],
)
def test_transport_cannot_reach_broker_or_arbitrary_endpoints(
    host: str, target: str
) -> None:
    with pytest.raises(SourceError):
        EquityRequest(host, target, "Synthetic Test synthetic@example.test")


def test_transport_rejects_extra_auth_query_and_header_injection() -> None:
    request = AlpacaDataConnector(CREDENTIALS)._request(BAR_QUERY, None)
    for target in (
        request.target + "&api_key=secret",
        request.target + "&feed=sip",
        request.target + "#fragment",
    ):
        with pytest.raises(SourceError):
            replace(request, target=target)
    injected = "fixture\r\nInjected: true"
    with pytest.raises(SourceError):
        replace(request, secret_key=injected)
    with pytest.raises(SourceError):
        replace(request, user_agent="fixture\r\nInjected: true")
    with pytest.raises(SourceError, match="SEC_AUTHENTICATION_REFUSED"):
        EquityRequest(
            "data.sec.gov",
            "/submissions/CIK0000000123.json",
            IDENTITY.user_agent(),
            "fixture-key",
            "fixture-secret",
        )


def test_injected_oversized_response_rejected_before_retention() -> None:
    client = AlpacaDataConnector(
        CREDENTIALS, Fixture(EquityResponse(200, b"x" * (MAX_RESPONSE_BYTES + 1)))
    )
    with pytest.raises(SourceError, match="RESPONSE_TOO_LARGE"):
        client.fetch_range(BAR_QUERY)
    assert not client.last_pages


class FakeSocket:
    def __init__(self) -> None:
        self.closed = False
        self.timeouts: list[float] = []

    def close(self) -> None:
        self.closed = True

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class FakeHTTPResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = 200
        self.body = body
        self.headers = headers or {}

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def read1(self, length: int) -> bytes:
        result, self.body = self.body[:length], self.body[length:]
        return result


class FakeConnection:
    def __init__(
        self, response: FakeHTTPResponse, failure: Exception | None = None
    ) -> None:
        self.sock: FakeSocket | None = None
        self.response = response
        self.failure = failure
        self.closed = False
        self.headers: dict[str, str] = {}

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        assert method == "GET" and target.startswith("/v2/stocks/bars?")
        self.headers = headers
        if self.failure:
            raise self.failure

    def getresponse(self) -> FakeHTTPResponse:
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
def test_https_pins_official_ip_uses_only_auth_headers_and_bounds_response(
    monkeypatch: pytest.MonkeyPatch, case: str, code: str | None
) -> None:
    headers = (
        {"Content-Encoding": "gzip"}
        if case == "encoding"
        else {"Content-Length": "not-a-number"}
        if case == "length"
        else {}
    )
    body = b"x" * (MAX_RESPONSE_BYTES + 1) if case == "body" else b"{}"
    failure = (
        TimeoutError("sensitive")
        if case == "timeout"
        else OSError("sensitive")
        if case == "network"
        else None
    )
    connection = FakeConnection(FakeHTTPResponse(body, headers), failure)
    sock = FakeSocket()

    class TLS:
        def wrap_socket(self, raw: FakeSocket, *, server_hostname: str) -> FakeSocket:
            assert raw is sock and server_hostname == "data.alpaca.markets"
            if case == "tls":
                raise OSError("sensitive")
            return raw

    def connect(address: tuple[str, int], *, timeout: float) -> FakeSocket:
        assert address == ("8.8.8.8", 443) and timeout == 10
        return sock

    monkeypatch.setattr(
        "quant_hunter.sources._equity_transport.public_address", lambda _: "8.8.8.8"
    )
    monkeypatch.setattr("http.client.HTTPSConnection", lambda *_a, **_kw: connection)
    monkeypatch.setattr("socket.create_connection", connect)
    monkeypatch.setattr("ssl.create_default_context", TLS)
    if case == "deadline":
        ticks = iter([0.0, 11.0])
        monkeypatch.setattr(
            "quant_hunter.sources._equity_transport.time.monotonic", lambda: next(ticks)
        )
    request = AlpacaDataConnector(CREDENTIALS)._request(BAR_QUERY, None)
    if code:
        with pytest.raises(SourceError, match=code) as caught:
            EquityHTTPS._send_once(request)
        assert "sensitive" not in str(caught.value)
    else:
        response = EquityHTTPS._send_once(request)
        assert response.body == b"{}" and max(sock.timeouts) <= 10
        assert connection.headers["APCA-API-KEY-ID"] == CREDENTIALS.key_id
        assert connection.headers["APCA-API-SECRET-KEY"] == CREDENTIALS.secret_key
        assert connection.headers["Accept-Encoding"] == "identity"
    assert connection.closed
    if case == "tls":
        assert sock.closed


def test_https_private_dns_response_fails_before_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *_a, **_kw: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    request = AlpacaDataConnector(CREDENTIALS)._request(BAR_QUERY, None)
    with pytest.raises(SourceError, match="NONPUBLIC_ADDRESS_REFUSED"):
        EquityHTTPS._send_once(request)
