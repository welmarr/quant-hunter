"""Offline protocol, schema, temporal and endpoint-boundary proofs for sources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from quant_hunter.config import canonicalize_json, parse_json_document
from quant_hunter.identity import RegistryStore
from quant_hunter.sources import (
    BLSConnector,
    ECBConnector,
    HTTPSPublicTransport,
    Request,
    Response,
    SourceError,
    SourceProbeService,
    SourceQuery,
    default_query,
    list_sources,
)
from quant_hunter.sources.transport import (
    MAX_RESPONSE_BYTES,
    checked_body,
    public_address,
)
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.storage.objects import ObjectStoreError

STAMP = datetime(2026, 10, 5, tzinfo=UTC)
BLS_QUERY = default_query("SRC-04")
ECB_QUERY = default_query("SRC-08")
CSV_HEADER = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
)
CSV_ROW = "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-01-02,1.0956\n"


def bls_body(*, rows: list[dict[str, object]] | None = None) -> bytes:
    data = (
        rows
        if rows is not None
        else [
            {
                "year": "2024",
                "period": "M02",
                "value": "157823",
                "footnotes": [{"code": "P"}],
            },
            {"year": "2024", "period": "M01", "value": "157585", "footnotes": [{}]},
        ]
    )
    return json.dumps(
        {
            "status": "REQUEST_SUCCEEDED",
            "message": [],
            "Results": {"series": [{"seriesID": "CES0000000001", "data": data}]},
        }
    ).encode()


class FixtureTransport:
    def __init__(self, response: Response | Exception) -> None:
        self.response = response
        self.requests: list[Request] = []

    def send(self, request: Request) -> Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_catalogue_has_exact_mission_keys_and_no_fake_connections() -> None:
    catalog = list_sources()
    assert [source.catalogue_id for source in catalog] == [
        f"SRC-{number:02d}" for number in range(1, 23)
    ]
    assert len({source.catalogue_id for source in catalog}) == 22
    ready = [
        source.catalogue_id for source in catalog if source.status == "READY_TO_TEST"
    ]
    assert ready == ["SRC-04", "SRC-06", "SRC-08"]
    assert all(source.documentation_url.startswith("https://") for source in catalog)
    assert all(source.license_notes and source.pit_notes for source in catalog)
    assert all(source.coverage_verified.startswith("NONE") for source in catalog)
    assert all(
        source.implementation_status == "NOT_IMPLEMENTED"
        for source in catalog
        if not source.capabilities
    )
    assert BLSConnector().health().status == "UNTESTED"
    assert ECBConnector().health().status == "UNTESTED"
    with pytest.raises(SourceError, match="NOT_IMPLEMENTED"):
        default_query("SRC-07")


def test_bls_fetch_preserves_exact_bytes_and_latest_not_pit_semantics() -> None:
    raw = bls_body()
    transport = FixtureTransport(Response(200, raw))
    connector = BLSConnector(transport)
    result = connector.test_connection(BLS_QUERY)
    assert result.raw == raw
    assert result.sha256 == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert result.evidence_mode == "RECORDED_FIXTURE"
    assert result.coverage_complete is False
    assert [row.period for row in result.observations] == ["2024-01", "2024-02"]
    assert [row.value for row in result.observations] == [
        Decimal("157585"),
        Decimal("157823"),
    ]
    assert "PRELIMINARY" in result.observations[1].quality_flags
    assert all(not row.point_in_time_eligible for row in result.observations)
    assert all(
        row.publication_time is None and row.revision_time is None
        for row in result.observations
    )
    assert all(row.ingestion_time == result.retrieved_at for row in result.observations)
    assert connector.health().status == "SUCCEEDED"
    assert "LATEST_VALUES_ONLY" in connector.list_capabilities()
    assert len(transport.requests) == 1
    sent = transport.requests[0]
    assert sent.host == "api.bls.gov"
    assert sent.method == "POST"
    assert json.loads(sent.body or b"") == {
        "seriesid": [BLS_QUERY.series_id],
        "startyear": "2024",
        "endyear": "2024",
    }


def test_bls_month_filter_annual_omission_and_missing_value_not_zero() -> None:
    raw = bls_body(
        rows=[
            {"year": "2024", "period": "M01", "value": "12", "footnotes": []},
            {"year": "2024", "period": "M02", "value": "-", "footnotes": []},
            {"year": "2024", "period": "M13", "value": "100", "footnotes": []},
        ]
    )
    query = replace(BLS_QUERY, start=date(2024, 2, 1))
    rows = BLSConnector().normalize(raw, query, STAMP)
    assert len(rows) == 1 and rows[0].value is None
    assert "MISSING_VALUE" in rows[0].quality_flags
    payload = json.loads(raw)
    payload["Results"] = [payload["Results"]]
    assert BLSConnector().normalize(json.dumps(payload).encode(), query, STAMP) == rows


def test_ecb_reference_rate_units_and_executable_limit() -> None:
    raw = (CSV_HEADER + CSV_ROW).encode()
    transport = FixtureTransport(Response(200, raw))
    connector = ECBConnector(transport)
    result = connector.fetch_range(ECB_QUERY)
    item = result.observations[0]
    assert item.value == Decimal("1.0956")
    assert item.unit == "USD per EUR"
    assert item.price_nature == "INDICATIVE_REFERENCE"
    assert "NOT_EXECUTABLE" in item.quality_flags
    assert item.publication_time is None
    assert item.period_start == date(2024, 1, 2)
    assert item.ingestion_time.date() != item.period_start
    assert (
        transport.requests[0].target
        == "/service/data/EXR/D.USD.EUR.SP00.A?startPeriod=2024-01-02&endPeriod=2024-01-05&format=csvdata"
    )


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "ACCESS_DENIED"),
        (403, "ACCESS_DENIED"),
        (404, "NOT_FOUND"),
        (429, "RATE_LIMITED"),
        (500, "HTTP_FAILURE"),
        (503, "HTTP_FAILURE"),
        (301, "REDIRECT_REFUSED"),
        (302, "REDIRECT_REFUSED"),
        (204, "HTTP_FAILURE"),
    ],
)
def test_http_errors_never_retry_or_echo_provider_bodies(
    status: int, code: str
) -> None:
    transport = FixtureTransport(
        Response(status, b"private provider diagnostic", "120")
    )
    connector = BLSConnector(transport)
    with pytest.raises(SourceError, match=code) as error:
        connector.fetch_range(BLS_QUERY)
    assert "private" not in str(error.value)
    assert connector.health().last_error == code
    assert len(transport.requests) == 1
    assert error.value.retry_after_seconds == (120 if status == 429 else None)


@pytest.mark.parametrize(
    "retry", [None, "Wed, 21 Oct 2015 07:28:00 GMT", "not-a-delay", "999999999999"]
)
def test_unrecognized_retry_after_does_not_become_an_automatic_retry(
    retry: str | None,
) -> None:
    with pytest.raises(SourceError) as error:
        checked_body(Response(429, b"", retry))
    assert error.value.retry_after_seconds is None


@pytest.mark.parametrize(
    "failure,code",
    [(TimeoutError("sensitive"), "TIMEOUT"), (OSError("sensitive"), "NETWORK_FAILURE")],
)
def test_transport_failures_are_sanitized(failure: Exception, code: str) -> None:
    connector = ECBConnector(FixtureTransport(failure))
    with pytest.raises(SourceError, match=code) as error:
        connector.fetch_range(ECB_QUERY)
    assert "sensitive" not in str(error.value)
    assert connector.health().status == "FAILED"


@pytest.mark.parametrize(
    "body,code",
    [(b"", "EMPTY_RESPONSE"), (b"x" * (MAX_RESPONSE_BYTES + 1), "RESPONSE_TOO_LARGE")],
    ids=["empty", "over-limit"],
)
def test_bounded_response_policy_applies_to_injected_transport(
    body: bytes, code: str
) -> None:
    with pytest.raises(SourceError, match=code):
        BLSConnector(FixtureTransport(Response(200, body))).fetch_range(BLS_QUERY)


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"not-json", "INVALID_JSON"),
        (b"\xff", "INVALID_ENCODING"),
        (b"[]", "INVALID_SCHEMA"),
        (b'{"status":"REQUEST_SUCCEEDED","status":"x"}', "DUPLICATE_JSON_KEY"),
        (b'{"status":"REQUEST_FAILED"}', "PROVIDER_REJECTED_REQUEST"),
    ],
)
def test_bad_bls_documents_fail_closed(raw: bytes, code: str) -> None:
    with pytest.raises(SourceError, match=code):
        BLSConnector().normalize(raw, BLS_QUERY, STAMP)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("year", "0000", "OBSERVATION_OUTSIDE_RANGE"),
        ("year", "2023", "OBSERVATION_OUTSIDE_RANGE"),
        ("year", "bad", "INVALID_PERIOD"),
        ("period", "Q01", "UNSUPPORTED_BLS_FREQUENCY"),
        ("value", "NaN", "INVALID_NUMERIC_VALUE"),
        ("value", "Infinity", "INVALID_NUMERIC_VALUE"),
        ("value", "1e999", "INVALID_NUMERIC_VALUE"),
        ("value", "broken", "INVALID_NUMERIC_VALUE"),
        ("value", 1, "INVALID_NUMERIC_VALUE"),
        ("footnotes", {}, "INVALID_SCHEMA"),
    ],
)
def test_bad_bls_observations_fail_closed(field: str, value: object, code: str) -> None:
    row: dict[str, object] = {
        "year": "2024",
        "period": "M01",
        "value": "12",
        "footnotes": [],
    }
    row[field] = value
    with pytest.raises(SourceError, match=code):
        BLSConnector().normalize(bls_body(rows=[row]), BLS_QUERY, STAMP)


def test_missing_contradictory_and_duplicate_bls_rows_are_rejected() -> None:
    connector = BLSConnector()
    with pytest.raises(SourceError, match="NO_OBSERVATIONS"):
        connector.normalize(bls_body(rows=[]), BLS_QUERY, STAMP)
    payload = json.loads(bls_body())
    payload["Results"]["series"][0]["seriesID"] = "FOREIGN"
    with pytest.raises(SourceError, match="CONTRADICTORY_SERIES"):
        connector.normalize(json.dumps(payload).encode(), BLS_QUERY, STAMP)
    payload = json.loads(bls_body())
    payload["message"] = ["returned truncated response"]
    with pytest.raises(SourceError, match="PROVIDER_WARNING"):
        connector.normalize(json.dumps(payload).encode(), BLS_QUERY, STAMP)
    row: dict[str, object] = {
        "year": "2024",
        "period": "M01",
        "value": "12",
        "footnotes": [],
    }
    with pytest.raises(SourceError, match="DUPLICATE"):
        connector.normalize(bls_body(rows=[row, row]), BLS_QUERY, STAMP)
    with pytest.raises(SourceError, match="INVALID_SCHEMA"):
        connector.normalize(bls_body(rows=[row] * 131), BLS_QUERY, STAMP)


@pytest.mark.parametrize(
    "raw,code",
    [
        ("TIME_PERIOD,OBS_VALUE\n2024-01-02,1\n", "INVALID_CSV_SCHEMA"),
        (CSV_HEADER, "NO_OBSERVATIONS"),
        (CSV_HEADER + CSV_ROW + CSV_ROW, "DUPLICATE"),
        (CSV_HEADER + CSV_ROW.replace("2024-01-02", "2024-01-01"), "OUTSIDE_RANGE"),
        (CSV_HEADER + CSV_ROW.replace("2024-01-02", "2024-02-31"), "INVALID_PERIOD"),
        (CSV_HEADER + CSV_ROW.replace("USD", "GBP"), "CONTRADICTORY_SERIES"),
        (CSV_HEADER + CSV_ROW.replace("1.0956", "0"), "INVALID_REFERENCE_RATE"),
        (CSV_HEADER + CSV_ROW.replace("1.0956", "NaN"), "INVALID_NUMERIC_VALUE"),
        (CSV_HEADER + CSV_ROW.replace("1.0956\n", "1.0956,extra\n"), "INVALID_CSV_ROW"),
    ],
)
def test_ecb_schema_and_temporal_contradictions_fail_closed(
    raw: str, code: str
) -> None:
    with pytest.raises(SourceError, match=code):
        ECBConnector().normalize(raw.encode(), ECB_QUERY, STAMP)


def test_ecb_missing_rate_is_not_zero_and_units_cannot_be_reversed() -> None:
    rows = ECBConnector().normalize(
        (CSV_HEADER + CSV_ROW.replace("1.0956", "")).encode(), ECB_QUERY, STAMP
    )
    assert rows[0].value is None and "MISSING_VALUE" in rows[0].quality_flags
    with pytest.raises(SourceError, match="UNIT_MISMATCH"):
        ECBConnector().validate_config(replace(ECB_QUERY, unit="EUR per USD"))


def test_range_series_units_and_timestamp_bounds() -> None:
    with pytest.raises(SourceError, match="INVALID_DATE_RANGE"):
        SourceQuery("x", date(2025, 1, 1), date(2024, 1, 1), "unit")
    with pytest.raises(SourceError, match="UNIT_DECLARATION"):
        replace(BLS_QUERY, unit="")
    with pytest.raises(SourceError, match="TEN_YEARS"):
        BLSConnector().validate_config(replace(BLS_QUERY, start=date(2014, 1, 1)))
    with pytest.raises(SourceError, match="366_DAYS"):
        ECBConnector().validate_config(replace(ECB_QUERY, end=date(2025, 1, 5)))
    for connector, query in [(BLSConnector(), BLS_QUERY), (ECBConnector(), ECB_QUERY)]:
        with pytest.raises(SourceError, match=r"INVALID_.*_SERIES"):
            connector.validate_config(
                replace(query, series_id="../../private?secret=value")
            )
        with pytest.raises(SourceError, match="UTC"):
            connector.normalize(b"ignored", query, datetime(2024, 1, 1))


@pytest.mark.parametrize(
    "host,target,method",
    [
        ("127.0.0.1", "/", "GET"),
        ("169.254.169.254", "/latest/meta-data", "GET"),
        ("api.bls.gov.evil.example", "/publicAPI/v1/timeseries/data/", "POST"),
        (
            "api.bls.gov",
            "/publicAPI/v1/timeseries/data/?registrationkey=secret",
            "POST",
        ),
        ("data-api.ecb.europa.eu", "//evil.example", "GET"),
    ],
)
def test_transport_refuses_arbitrary_hosts_paths_and_secrets_in_urls(
    host: str, target: str, method: str
) -> None:
    with pytest.raises(SourceError, match="ENDPOINT_NOT_ALLOWED"):
        Request(method, host, target, b"{}" if method == "POST" else None)


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:127.0.0.1"]
)
def test_dns_private_addresses_are_refused(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *_args, **_kwargs: [(2, 1, 6, "", (address, 443))]
    )
    with pytest.raises(SourceError, match="NONPUBLIC"):
        public_address("api.bls.gov")


def test_dns_is_pinned_and_dns_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    assert public_address("api.bls.gov") == "8.8.8.8"
    monkeypatch.setattr("socket.getaddrinfo", lambda *_args, **_kwargs: [])
    with pytest.raises(SourceError, match="DNS_UNAVAILABLE"):
        HTTPSPublicTransport._send_once(
            Request(
                "POST",
                "api.bls.gov",
                "/publicAPI/v1/timeseries/data/",
                b'{"seriesid":["CES0000000001"],"startyear":"2024","endyear":"2024"}',
            )
        )


def test_batch_refuses_invented_availability_and_foreign_series() -> None:
    connector = ECBConnector()
    rows = connector.normalize((CSV_HEADER + CSV_ROW).encode(), ECB_QUERY, STAMP)
    with pytest.raises(SourceError, match="UNSUPPORTED_AVAILABILITY"):
        connector.validate_batch(
            (replace(rows[0], publication_time=STAMP - timedelta(days=10)),), ECB_QUERY
        )
    with pytest.raises(SourceError, match="CONTRADICTORY_SERIES"):
        connector.validate_batch((replace(rows[0], series_id="FOREIGN"),), ECB_QUERY)
    with pytest.raises(SourceError, match="TOO_MANY"):
        connector.validate_batch(rows * 4001, ECB_QUERY)
    assert cast(object, rows[0].value) != 0


def test_probe_registers_candidate_before_fetch_and_retains_existing_raw_capture(
    tmp_path: Path,
) -> None:
    schema_root = Path(__file__).resolve().parents[1] / "schemas" / "v1"
    registry = RegistryStore.governed(tmp_path / "registry", schema_root)
    objects = ImmutableObjectStore(tmp_path / "objects")
    environment = objects.publish(b'{"purpose":"source fixture tests"}')
    raw = (CSV_HEADER + CSV_ROW).encode()

    def factory(catalogue_id: str) -> ECBConnector:
        assert catalogue_id == "SRC-08"
        records = registry.verify_all()
        assert len(records) == 1
        source = next(iter(records.values()))[-1]
        assert source.record["status"] == "CANDIDATE"
        assert source.record["provider"] == "ECB Data Portal"
        return ECBConnector(FixtureTransport(Response(200, raw)))

    service = SourceProbeService(
        registry,
        objects,
        schema_root,
        "a" * 40,
        environment.digest,
        connector_factory=factory,
    )
    result = service.probe("SRC-08")
    assert result["status"] == "SUCCEEDED"
    assert result["evidence_mode"] == "RECORDED_FIXTURE"
    assert result["quality"] == "PENDING"
    assert result["source_status"] == "CANDIDATE"
    assert result["source_id"] != "SRC-08"
    assert len(registry.verify_all()) == 2
    assert objects.get(cast(str, result["raw_digest"])).path.read_bytes() == raw
    capture = cast(
        dict[str, object],
        parse_json_document(
            objects.get(cast(str, result["capture_digest"])).path.read_bytes()
        ),
    )
    assert capture["source_id"] == result["source_id"]
    assert capture["dataset_id"] == result["dataset_id"]
    assert capture["payload_digest"] == result["raw_digest"]
    assert capture["quality_disposition"] == "PENDING"
    dataset = registry.verify_object(cast(str, result["dataset_id"]))[-1]
    assert dataset.record["physical_object_digest"] == result["raw_digest"]
    assert dataset.record["provenance_lineage_digest"] == result["lineage_digest"]
    assert result["record_count"] == 1


def test_probe_failure_keeps_candidate_and_raw_evidence_without_claiming_dataset_approval(
    tmp_path: Path,
) -> None:
    schema_root = Path(__file__).resolve().parents[1] / "schemas" / "v1"
    registry = RegistryStore.governed(tmp_path / "registry", schema_root)
    objects = ImmutableObjectStore(tmp_path / "objects")
    environment = objects.publish(b"{}")
    service = SourceProbeService(
        registry,
        objects,
        schema_root,
        "a" * 40,
        environment.digest,
        connector_factory=lambda _: BLSConnector(
            FixtureTransport(Response(200, b"wrong-schema"))
        ),
    )
    result = service.probe("SRC-04")
    assert result["status"] == "FAILED" and result["error_code"] == "INVALID_JSON"
    assert result["quality"] == "QUARANTINED"
    assert (
        objects.get(cast(str, result["raw_digest"])).path.read_bytes()
        == b"wrong-schema"
    )
    assert len(registry.verify_all()) == 1
    assert (
        registry.verify_object(cast(str, result["source_id"]))[-1].record["status"]
        == "CANDIDATE"
    )
    assert "dataset_id" not in result
    assert objects.get(cast(str, result["capture_digest"]))
    with pytest.raises(SourceError, match="NOT_IMPLEMENTED"):
        service.probe("SRC-01")
    assert len(registry.verify_all()) == 1


def test_transport_cannot_send_undeclared_or_credential_fields() -> None:
    for body in (
        b"{}",
        b'{"seriesid":["A"],"startyear":"2024","endyear":"2024","registrationkey":"secret"}',
        b"not-json",
    ):
        with pytest.raises(SourceError, match="REQUEST_NOT_ALLOWED"):
            Request("POST", "api.bls.gov", "/publicAPI/v1/timeseries/data/", body)


class FakeSocket:
    def __init__(self) -> None:
        self.closed = False
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)

    def close(self) -> None:
        self.closed = True


class FakeResponse:
    status = 200

    def __init__(
        self, body: bytes, headers: dict[str, str], error: Exception | None = None
    ) -> None:
        self.body, self.headers, self.error = body, headers, error

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def read1(self, amount: int) -> bytes:
        if self.error:
            raise self.error
        chunk, self.body = self.body[:amount], self.body[amount:]
        return chunk


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.sock: FakeSocket | None = None
        self.closed = False
        self.requests: list[tuple[str, str]] = []

    def request(
        self, method: str, target: str, *, body: bytes | None, headers: dict[str, str]
    ) -> None:
        assert headers["Accept-Encoding"] == "identity"
        assert body is not None
        self.requests.append((method, target))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    "case,expected",
    [
        ("success", None),
        ("encoding", "ENCODED_RESPONSE_REFUSED"),
        ("bad-length", "RESPONSE_TOO_LARGE"),
        ("large-header", "RESPONSE_TOO_LARGE"),
        ("large-body", "RESPONSE_TOO_LARGE"),
        ("timeout", "TIMEOUT"),
        ("network", "NETWORK_FAILURE"),
        ("deadline", "TIMEOUT"),
        ("tls", "NETWORK_FAILURE"),
    ],
)
def test_native_transport_bounds_pins_tls_and_closes_connections(
    monkeypatch: pytest.MonkeyPatch, case: str, expected: str | None
) -> None:
    socket = FakeSocket()
    headers: dict[str, str] = {}
    if case == "encoding":
        headers["Content-Encoding"] = "gzip"
    if case in ("bad-length", "large-header"):
        headers["Content-Length"] = (
            "broken" if case == "bad-length" else str(MAX_RESPONSE_BYTES + 1)
        )
    body = b"x" * (MAX_RESPONSE_BYTES + 1) if case == "large-body" else b"{}"
    error = (
        TimeoutError("private")
        if case == "timeout"
        else OSError("private")
        if case == "network"
        else None
    )
    response = FakeResponse(body, headers, error)
    connection = FakeConnection(response)

    class TLS:
        def wrap_socket(self, raw: FakeSocket, *, server_hostname: str) -> FakeSocket:
            assert raw is socket and server_hostname == "api.bls.gov"
            if case == "tls":
                raise OSError("private TLS diagnostic")
            return raw

    def connect(address: tuple[str, int], *, timeout: float) -> FakeSocket:
        assert address == ("8.8.8.8", 443) and timeout == 10
        return socket

    monkeypatch.setattr(
        "quant_hunter.sources.transport.public_address", lambda _: "8.8.8.8"
    )
    monkeypatch.setattr(
        "http.client.HTTPSConnection", lambda *_args, **_kwargs: connection
    )
    monkeypatch.setattr("socket.create_connection", connect)
    monkeypatch.setattr("ssl.create_default_context", TLS)
    if case == "deadline":
        ticks = iter([0.0, 11.0])
        monkeypatch.setattr(
            "quant_hunter.sources.transport.time.monotonic", lambda: next(ticks)
        )
    request = Request(
        "POST",
        "api.bls.gov",
        "/publicAPI/v1/timeseries/data/",
        b'{"seriesid":["CES0000000001"],"startyear":"2024","endyear":"2024"}',
    )
    if expected:
        with pytest.raises(SourceError, match=expected) as captured:
            HTTPSPublicTransport._send_once(request)
        assert "private" not in str(captured.value)
    else:
        result = HTTPSPublicTransport._send_once(request)
        assert result.body == b"{}" and result.status == 200
        assert socket.timeouts and max(socket.timeouts) <= 10
    assert connection.closed
    if case == "tls":
        assert socket.closed


def test_probe_refuses_missing_execution_snapshot_before_network(
    tmp_path: Path,
) -> None:
    schemas = Path(__file__).resolve().parents[1] / "schemas" / "v1"
    registry = RegistryStore.governed(tmp_path / "registry", schemas)
    objects = ImmutableObjectStore(tmp_path / "objects")
    snapshot = objects.publish(b"immutable source snapshot")
    environment = objects.publish(
        canonicalize_json({"source_snapshot_digest": snapshot.digest})
    )
    service = SourceProbeService(
        registry, objects, schemas, "a" * 40, environment.digest
    )
    snapshot.path.unlink()
    with pytest.raises(ObjectStoreError):
        service.probe("SRC-08")
    assert registry.verify_all() == {}


def test_failed_probe_never_retains_over_limit_injected_response(
    tmp_path: Path,
) -> None:
    schemas = Path(__file__).resolve().parents[1] / "schemas" / "v1"
    registry = RegistryStore.governed(tmp_path / "registry", schemas)
    objects = ImmutableObjectStore(tmp_path / "objects")
    environment = objects.publish(b"{}")
    oversized = b"x" * (MAX_RESPONSE_BYTES + 1)
    service = SourceProbeService(
        registry,
        objects,
        schemas,
        "a" * 40,
        environment.digest,
        connector_factory=lambda _: ECBConnector(
            FixtureTransport(Response(200, oversized))
        ),
    )
    result = service.probe("SRC-08")
    assert result["status"] == "FAILED" and result["error_code"] == "RESPONSE_TOO_LARGE"
    assert result["raw_digest"] is None and result["raw_retained"] is False
    with pytest.raises(ObjectStoreError):
        objects.get("sha256:" + hashlib.sha256(oversized).hexdigest())


@pytest.mark.parametrize("multiplier", ["2", "-1", "", "NaN", "0.0"])
def test_ecb_rejects_nonzero_or_malformed_unit_multiplier(multiplier: str) -> None:
    raw = (
        CSV_HEADER.rstrip("\n")
        + ",UNIT_MULT\n"
        + CSV_ROW.rstrip("\n")
        + ","
        + multiplier
        + "\n"
    ).encode()
    with pytest.raises(SourceError, match="UNSUPPORTED_UNIT_MULTIPLIER"):
        ECBConnector().normalize(raw, ECB_QUERY, STAMP)


@pytest.mark.parametrize("status", ["A", "E", "P", "UNKNOWN_CODE", ""])
def test_ecb_preserves_provider_status_without_quality_approval(status: str) -> None:
    raw = (
        CSV_HEADER.rstrip("\n")
        + ",UNIT_MULT,UNIT,OBS_STATUS\n"
        + CSV_ROW.rstrip("\n")
        + ",0,USD,"
        + status
        + "\n"
    ).encode()
    observation = ECBConnector().normalize(raw, ECB_QUERY, STAMP)[0]
    expected = "ECB_OBS_STATUS_" + status if status else "ECB_OBS_STATUS_UNKNOWN"
    assert expected in observation.quality_flags
    assert "UNIT_MULTIPLIER_NOT_PROVIDED" not in observation.quality_flags
    assert not observation.point_in_time_eligible
    assert observation.value == Decimal("1.0956")


@pytest.mark.parametrize(
    ("column", "value", "error"),
    [
        ("UNIT", "JPY", "ECB_UNIT_MISMATCH"),
        ("OBS_STATUS", "x" * 13, "INVALID_OBSERVATION_STATUS"),
    ],
)
def test_ecb_rejects_contradictory_units_and_unbounded_status(
    column: str, value: str, error: str
) -> None:
    raw = (
        CSV_HEADER.rstrip("\n")
        + ","
        + column
        + "\n"
        + CSV_ROW.rstrip("\n")
        + ","
        + value
        + "\n"
    ).encode()
    with pytest.raises(SourceError, match=error):
        ECBConnector().normalize(raw, ECB_QUERY, STAMP)


def test_bls_keeps_other_footnote_codes_visible() -> None:
    raw = bls_body(
        rows=[
            {
                "year": "2024",
                "period": "M01",
                "value": "10",
                "footnotes": [{"code": "R"}, {"code": "P"}, {"code": "R"}],
            }
        ]
    )
    observation = BLSConnector().normalize(raw, BLS_QUERY, STAMP)[0]
    assert "PRELIMINARY" in observation.quality_flags
    assert observation.quality_flags.count("BLS_FOOTNOTE_R") == 1
    bad = raw.replace(b'"R"', b'"long_unknown_status"')
    with pytest.raises(SourceError, match="INVALID_FOOTNOTE_CODE"):
        BLSConnector().normalize(bad, BLS_QUERY, STAMP)


def test_bls_transport_rejects_duplicate_request_keys() -> None:
    with pytest.raises(SourceError, match="REQUEST_NOT_ALLOWED"):
        Request(
            "POST",
            "api.bls.gov",
            "/publicAPI/v1/timeseries/data/",
            b'{"seriesid":["CES0000000001"],"startyear":"2023",'
            b'"startyear":"2024","endyear":"2024"}',
        )
