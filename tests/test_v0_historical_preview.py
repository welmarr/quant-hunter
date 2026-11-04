"""Chart-only historical declarations use real governed graphs, never market data."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import httpx
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
import test_v0_data_quality as fixtures
from fastapi import FastAPI, HTTPException, Request

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.data_quality import QualityError
from quant_hunter.imports import ImportService
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.historical_access import HistoricalPreviewAccess, _rows
from quant_hunter.web.historical_routes import install_historical_routes
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.state import AccessError, AppState, Session, User


def _object(value: object) -> JsonRecord:
    assert isinstance(value, dict)
    return cast(JsonRecord, value)


class NoNetwork:
    def probe(self, catalogue_id: str) -> JsonRecord:
        raise AssertionError("No chart may retrieve provider data")


@dataclass
class Harness:
    access: HistoricalPreviewAccess
    users: dict[str, User]
    sessions: dict[str, tuple[str, str]]
    app: FastAPI
    historical: dict[str, Any]
    blocked: dict[str, Any]
    synthetic: dict[str, Any]
    gaps: dict[str, Any]

    def body(
        self, data: dict[str, Any] | None = None, *, start: int = 0, stop: int = 3
    ) -> dict[str, Any]:
        row = self.historical if data is None else data
        return {
            **{
                key: row[key]
                for key in ("dataset_id", "record_digest", "quality_report_digest")
            },
            "start": start,
            "stop": stop,
        }

    def inspect(self, **kwargs: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.access.inspect(self.users["owner"], **self.body(**kwargs)),
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        name: str = "owner",
        csrf: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        token, protection = self.sessions.get(name, ("", ""))

        async def request() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(self.app),
                base_url="http://testserver",
                cookies={"qh_session": token},
                headers={"x-csrf-token": protection if csrf else "wrong"},
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(request())


@pytest.fixture(scope="module")
def h(tmp_path_factory: pytest.TempPathFactory) -> Harness:
    root = tmp_path_factory.mktemp("historical-chart")
    schemas = Path(os.environ.get("QH_HISTORICAL_SCHEMA_ROOT", str(fixtures.SCHEMAS)))
    original = fixtures.SCHEMAS
    fixtures.SCHEMAS = schemas
    try:
        service, instrument, revision = fixtures.setup(root)
    finally:
        fixtures.SCHEMAS = original
    state = AppState(root / "state.sqlite3")
    users, sessions = {}, {}
    for name, role in (
        ("owner", "owner"),
        ("other", "researcher"),
        ("reader", "reader"),
    ):
        users[name] = state.create_user(
            name,
            "synthetic-password",
            cast(Literal["owner", "researcher", "reader"], role),
            bootstrap=name == "owner",
        )
        token, session = state.login(name, "synthetic-password")
        sessions[name] = token, session.csrf
    importer = ImportService(
        service.registry,
        service.objects,
        schemas,
        code_revision=service.code_revision,
        environment_digest=service.environment_digest,
    )
    data = DataAccess(state, root, importer, NoNetwork())
    # Isolate deterministic admission tests from machine capacity.
    data._capacity = lambda: None  # type: ignore[method-assign]
    quality = QualityAccess(
        state, service, data, InstrumentRegistry(service.registry, clock=service.clock)
    )

    def make(mode: str, *, known: bool = True, gaps: bool = False) -> dict[str, Any]:
        count = 780 if gaps else 5
        opens = [
            datetime(2025, 1, 6, 14, 30, tzinfo=UTC) + timedelta(minutes=i)
            for i in range(min(count, 390))
        ]
        if gaps:
            opens += [
                datetime(2025, 1, 7, 14, 30, tzinfo=UTC) + timedelta(minutes=i)
                for i in range(390)
            ]
        raw = ",".join(fixtures.NAMES) + (",revision_time" if known else "") + "\n"

        def stamp(value: datetime) -> str:
            return value.isoformat().replace("+00:00", "Z")

        for opening in opens:
            close = opening + timedelta(minutes=1)
            raw += (
                f"{stamp(opening)},{stamp(close)},100,102,99,101,{stamp(close)},2"
                + (f",{stamp(close)}" if known else "")
                + "\n"
            )
        mapping = fixtures.spec()
        mapping = (
            replace(
                mapping,
                columns=(*mapping.columns, ("revision_time", "revision_time"))
                if known
                else mapping.columns,
                revision_mode="KNOWN" if known else "REQUIRED_UNKNOWN",
            )
            if mode == "HISTORICAL"
            else mapping
        )
        if mode == "SYNTHETIC":
            raw = fixtures.payload().decode()
        result = quality.import_mapped(
            users["owner"],
            raw.encode(),
            file_format="CSV",
            metadata=fixtures.metadata(mode),
            mapping=mapping,
            instrument_id=instrument,
            instrument_revision_digest=revision,
            calendar_start=date(2025, 1, 6),
            calendar_end=date(2025, 1, 7) if gaps else date(2025, 1, 6),
        )
        return cast(dict[str, Any], result)

    historical, blocked, synthetic, gaps = (
        make("HISTORICAL"),
        make("HISTORICAL", known=False),
        make("SYNTHETIC"),
        make("HISTORICAL", gaps=True),
    )
    access = HistoricalPreviewAccess(state, quality)
    app = FastAPI()

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        try:
            value = state.session(request.cookies.get("qh_session", ""))
        except AccessError:
            raise HTTPException(401, "Sign in") from None
        if mutation and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), value.csrf
        ):
            raise HTTPException(403, "CSRF")
        return value

    install_historical_routes(app, authenticated, access)
    return Harness(access, users, sessions, app, historical, blocked, synthetic, gaps)


def test_actual_literal_prices_times_and_receipt_hash(h: Harness) -> None:
    result = h.inspect()
    assert _object(result["snapshot"])["admission"] == "HISTORICAL_EXPLORATORY"
    assert _object(result["snapshot"])["causal_eligible"] is False
    assert result["causal_research"] == "BLOCKED"
    assert _object(result["mapping"])["revision_mode"] == "KNOWN"
    assert result["feature_columns"] == ["close", "open", "high", "low", "volume"]
    assert result["rows"][0] == {
        "row": 0,
        "source_row": 1,
        "open_ns": "1736173800000000000",
        "close_ns": "1736173860000000000",
        "available_ns": "1736173860000000000",
        "revision_ns": "1736173860000000000",
        "ingestion_ns": "1767225600000000000",
        "revision_time_status": "KNOWN",
        "gap_before_ns": None,
        "values": [
            "101.000000000000",
            "100.000000000000",
            "102.000000000000",
            "99.000000000000",
            "2.000000000000",
        ],
    }
    retained = h.access.get(h.users["owner"], result["inspection_id"])
    assert retained["status"] == "PREPARED"
    digest = result.pop("inspection_receipt_digest")
    assert retained["receipt_digest"] == digest
    assert (
        _object(retained["receipt"])["response_digest"]
        == "sha256:" + hashlib.sha256(canonicalize_json(result)).hexdigest()
    )
    assert "rows" not in _object(retained["receipt"])


def test_calendar_session_gap_is_preserved_without_an_extra_bar(h: Harness) -> None:
    result = h.inspect(data=h.gaps, start=389, stop=392)
    assert [row["row"] for row in result["rows"]] == [389, 390, 391]
    assert _object(result["rows"][1])["gap_before_ns"] == str(
        17 * 3600_000_000_000 + 30 * 60_000_000_000
    )
    assert _object(result["rows"][2])["gap_before_ns"] is None


def test_chart_creates_no_research_identity_or_job(h: Harness) -> None:
    root = h.access.quality.service.registry.root
    before = {str(p): p.read_bytes() for p in root.rglob("*.json")}
    h.inspect()
    assert {str(p): p.read_bytes() for p in root.rglob("*.json")} == before
    assert h.access.state.jobs(h.users["owner"]) == []


@pytest.mark.parametrize("name", ["other", "reader"])
def test_foreign_dataset_is_denied_before_graph_read(
    h: Harness, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(
        h.access.quality, "_receipt", lambda *a: pytest.fail("foreign graph read")
    )
    before = h.access.list(h.users[name])
    with pytest.raises(AccessError):
        h.access.inspect(h.users[name], **h.body())
    assert h.access.list(h.users[name]) == before


def test_owned_reader_may_inspect_but_cannot_promote_causal_eligibility(
    h: Harness,
) -> None:
    with h.access.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (h.users["owner"].id,))
    try:
        reader = replace(h.users["owner"], role="reader")
        result = h.access.inspect(reader, **h.body())
        assert _object(result["snapshot"])["causal_eligible"] is False
    finally:
        with h.access.state.connection() as db:
            db.execute(
                "UPDATE users SET role='owner' WHERE id=?", (h.users["owner"].id,)
            )


@pytest.mark.parametrize(
    "field,value",
    [("start", -1), ("start", True), ("stop", 0), ("stop", 513), ("stop", 100_001)],
)
def test_ranges_rejected_before_retained_read(
    h: Harness, field: str, value: Any
) -> None:
    body = h.body()
    body[field] = value
    with pytest.raises(QualityError, match="INSPECTION_RANGE"):
        h.access.inspect(h.users["owner"], **body)


def test_bound_beyond_actual_rows_is_failed_and_retained(h: Harness) -> None:
    with pytest.raises(QualityError, match="INSPECTION_RANGE"):
        h.access.inspect(h.users["owner"], **h.body(stop=6))
    latest = h.access.list(h.users["owner"], limit=1)[0]
    assert latest["status"] == "FAILED" and latest["error_code"] == "INSPECTION_RANGE"


@pytest.mark.parametrize(
    "which,code",
    [
        ("blocked", "DATASET_NOT_ADMISSIBLE"),
        ("synthetic", "HISTORICAL_CHART_ONLY_PROFILE_REQUIRED"),
    ],
)
def test_existing_stronger_quality_profile_is_not_bypassed(
    h: Harness, which: str, code: str
) -> None:
    with pytest.raises(QualityError, match=code):
        h.access.inspect(h.users["owner"], **h.body(getattr(h, which)))
    assert _object(h.access.list(h.users["owner"], limit=1)[0])["error_code"] == code


def test_causal_selection_remains_blocked_after_chart_view(h: Harness) -> None:
    h.inspect()
    with pytest.raises(QualityError, match="DATASET_NOT_ADMISSIBLE"):
        h.access.quality.selected(
            h.users["owner"],
            **{
                key: h.historical[key]
                for key in ("dataset_id", "record_digest", "quality_report_digest")
            },
        )


def test_shared_reader_reservation_precedes_heavy_replay(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with h.access.state.connection() as db:
        db.executemany(
            "INSERT INTO resource_readers VALUES(?,?,0)",
            [("busy1", h.users["other"].id), ("busy2", h.users["other"].id)],
        )
    try:
        monkeypatch.setattr(
            h.access.quality,
            "_receipt",
            lambda *a: pytest.fail("replay before admission"),
        )
        with pytest.raises(AccessError, match="resources busy"):
            h.inspect()
    finally:
        with h.access.state.connection() as db:
            db.execute("DELETE FROM resource_readers WHERE id IN ('busy1','busy2')")


def test_capacity_failure_leaves_no_source_inspection(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = h.access.list(h.users["owner"], limit=50)
    monkeypatch.setattr(
        h.access.quality.data,
        "_capacity",
        lambda: (_ for _ in ()).throw(AccessError("no capacity")),
    )
    with pytest.raises(AccessError):
        h.inspect()
    assert h.access.list(h.users["owner"], limit=50) == before


def test_unknown_graph_failure_has_sanitized_retained_audit(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        h.access.quality,
        "_receipt",
        lambda *a: (_ for _ in ()).throw(RuntimeError("secret-path")),
    )
    with pytest.raises(QualityError, match="INSPECTION_FAILED"):
        h.inspect()
    retained = h.access.get(
        h.users["owner"],
        cast(
            str, _object(h.access.list(h.users["owner"], limit=1)[0])["inspection_id"]
        ),
    )
    assert retained["status"] == "FAILED" and "secret-path" not in str(retained)


def test_stale_receipt_is_retained_and_cannot_be_reinterpreted(h: Harness) -> None:
    body = h.body()
    body["record_digest"] = "sha256:" + "0" * 64
    response = h.request("POST", "/api/quality/inspections", json=body)
    assert response.status_code == 409
    assert (
        _object(h.access.list(h.users["owner"], limit=1)[0])["error_code"]
        == "STALE_DATASET_SELECTION"
    )


def test_interrupted_audit_is_not_replayed_on_restart(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = h.access._begin(h.users["owner"], h.body())
    restarted = HistoricalPreviewAccess(h.access.state, h.access.quality)
    monkeypatch.setattr(
        h.access.quality, "_receipt", lambda *a: pytest.fail("audit read replay")
    )
    assert restarted.get(h.users["owner"], identity)["status"] == "STARTED"


def test_audit_identity_and_terminal_status_cannot_be_overwritten(h: Harness) -> None:
    identity = h.inspect()["inspection_id"]
    with h.access.state.connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE historical_inspections SET request='{}' WHERE id=?", (identity,)
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE historical_inspections SET status='FAILED' WHERE id=?",
                (identity,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM historical_inspections WHERE id=?", (identity,))


def test_private_audit_page_and_receipt_identity(h: Harness) -> None:
    first, second = h.inspect(), h.inspect()
    assert (
        _object(h.access.list(h.users["owner"], limit=1)[0])["inspection_id"]
        == second["inspection_id"]
    )
    assert (
        _object(h.access.list(h.users["owner"], limit=1, offset=1)[0])["inspection_id"]
        == first["inspection_id"]
    )
    assert h.access.list(h.users["other"]) == []
    with pytest.raises(AccessError):
        h.access.get(h.users["other"], first["inspection_id"])


def test_route_auth_csrf_closed_inputs_and_no_store(h: Harness) -> None:
    body = h.body()
    assert (
        h.request(
            "POST", "/api/quality/inspections", json=body, name="absent"
        ).status_code
        == 401
    )
    assert (
        h.request("POST", "/api/quality/inspections", json=body, csrf=False).status_code
        == 403
    )
    assert (
        h.request(
            "POST", "/api/quality/inspections", json={**body, "path": "secret"}
        ).status_code
        == 422
    )
    response = h.request("POST", "/api/quality/inspections", json=body)
    assert (
        response.status_code == 201 and response.headers["cache-control"] == "no-store"
    )
    identity = response.json()["inspection_id"]
    assert (
        h.request("GET", f"/api/quality/inspections/{identity}").json()["status"]
        == "PREPARED"
    )
    assert (
        _object(
            h.request("GET", "/api/quality/inspections?limit=1").json()["inspections"][
                0
            ]
        )["inspection_id"]
        == identity
    )


def test_null_declared_times_remain_null_in_literal_codec(h: Harness) -> None:
    snapshot, payload = h.access.quality.service.select(
        h.historical["dataset_id"],
        expected_record_digest=h.historical["record_digest"],
        expected_report_digest=h.historical["quality_report_digest"],
        purpose="EXPLORATORY_INSPECTION",
    )
    table = pq.read_table(pa.BufferReader(payload))
    for name in ("available_at", "revision_time"):
        table = table.set_column(
            table.schema.get_field_index(name),
            table.schema.field(name),
            pa.array([None] * table.num_rows, type=table.schema.field(name).type),
        )
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    rows = _rows(sink.getvalue().to_pybytes(), snapshot, 1, 2)
    assert (
        _object(rows[0])["available_ns"] is None
        and _object(rows[0])["revision_ns"] is None
    )
    # Codec test only: the public selector rejects unknown timing before this stage.


def test_exact_512_row_window_is_bounded_and_source_unchanged(h: Harness) -> None:
    before = h.access.quality.service.objects.read_bytes(h.gaps["normalized_digest"])
    result = h.inspect(data=h.gaps, start=250, stop=762)
    assert len(result["rows"]) == 512
    assert (
        _object(result["rows"][0])["row"] == 250
        and _object(result["rows"][-1])["row"] == 761
    )
    assert (
        h.access.quality.service.objects.read_bytes(h.gaps["normalized_digest"])
        == before
    )


def test_audit_quota_precedes_full_graph_read(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("quant_hunter.web.historical_access._MAX_INSPECTIONS", 0)
    monkeypatch.setattr(
        h.access.quality,
        "_receipt",
        lambda *a: pytest.fail("graph before audit admission"),
    )
    with pytest.raises(AccessError, match="audit capacity"):
        h.inspect()


@pytest.mark.parametrize("page", [(0, 0), (51, 0), (25, -1), (25, 10000), (True, 0)])
def test_invalid_audit_page_is_rejected(h: Harness, page: tuple[int, int]) -> None:
    with pytest.raises(AccessError, match="Invalid inspection page"):
        h.access.list(h.users["owner"], limit=page[0], offset=page[1])


def test_stale_actor_and_mismatched_store_refused(h: Harness, tmp_path: Path) -> None:
    with pytest.raises(AccessError):
        h.access.list(replace(h.users["owner"], username="changed"))
    with pytest.raises(ValueError, match="shared state"):
        HistoricalPreviewAccess(AppState(tmp_path / "other.sqlite3"), h.access.quality)


@pytest.mark.parametrize(
    "field", ["inspection_id", "owner_id", "purpose", "disposition", "snapshot"]
)
def test_rehashed_wrong_audit_binding_is_rejected(h: Harness, field: str) -> None:
    good = h.inspect()
    request = h.body()
    identity = h.access._begin(h.users["owner"], request)
    receipt = cast(
        dict[str, Any], h.access.get(h.users["owner"], good["inspection_id"])["receipt"]
    )
    receipt["inspection_id"] = identity
    receipt[field] = (
        {**receipt["snapshot"], "dataset_id": h.synthetic["dataset_id"]}
        if field == "snapshot"
        else "wrong"
    )
    record = h.access.quality.service.objects.publish(canonicalize_json(receipt))
    with h.access.state.connection() as db:
        db.execute(
            "UPDATE historical_inspections SET status='PREPARED',receipt_digest=? WHERE id=?",
            (record.digest, identity),
        )
    with pytest.raises(QualityError, match="RECEIPT_BINDING"):
        h.access.get(h.users["owner"], identity)


def test_prepared_status_without_receipt_is_not_presented_as_valid(h: Harness) -> None:
    identity = h.access._begin(h.users["owner"], h.body())
    with h.access.state.connection() as db:
        db.execute(
            "UPDATE historical_inspections SET status='PREPARED' WHERE id=?",
            (identity,),
        )
    with pytest.raises(QualityError, match="RECEIPT_BINDING"):
        h.access.get(h.users["owner"], identity)


def test_block_decoder_skips_and_slices_exact_indices(h: Harness) -> None:
    snapshot, payload = h.access.quality.service.select(
        h.historical["dataset_id"],
        expected_record_digest=h.historical["record_digest"],
        expected_report_digest=h.historical["quality_report_digest"],
        purpose="EXPLORATORY_INSPECTION",
    )
    # Codec-only generated table: source identity is not offered to the public API.
    table = pa.concat_tables([pq.read_table(pa.BufferReader(payload))] * 1000)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    result = _rows(
        sink.getvalue().to_pybytes(), replace(snapshot, row_count=5000), 4097, 4100
    )
    assert [_object(row)["row"] for row in result] == [4097, 4098, 4099]
    assert [_object(row)["source_row"] for row in result] == [3, 4, 5]


@pytest.mark.parametrize(
    "change,code",
    [("count", "ROW_BINDING"), ("columns", "COLUMNS"), ("prices", "PRICE_SCHEMA")],
)
def test_literal_decoder_rejects_inconsistent_metadata(
    h: Harness, change: str, code: str
) -> None:
    snapshot, payload = h.access.quality.service.select(
        h.historical["dataset_id"],
        expected_record_digest=h.historical["record_digest"],
        expected_report_digest=h.historical["quality_report_digest"],
        purpose="EXPLORATORY_INSPECTION",
    )
    table = pq.read_table(pa.BufferReader(payload))
    if change == "count":
        table = table.slice(0, 1)
    elif change == "columns":
        table = table.drop(["revision_time"])
    else:
        table = table.set_column(
            table.schema.get_field_index("close"),
            "close",
            pa.array(["invalid"] * table.num_rows),
        )
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    with pytest.raises(QualityError, match=code):
        _rows(sink.getvalue().to_pybytes(), snapshot, 0, 1)


def test_routes_sanitize_corrupt_evidence_and_invalid_quality_reason(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        h.access,
        "inspect",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret-path")),
    )
    response = h.request("POST", "/api/quality/inspections", json=h.body())
    assert response.status_code == 503 and "secret" not in response.text
    monkeypatch.setattr(
        h.access,
        "inspect",
        lambda *a, **k: (_ for _ in ()).throw(QualityError("unsafe private-value")),
    )
    response = h.request("POST", "/api/quality/inspections", json=h.body())
    assert response.status_code == 400 and response.json() == {
        "detail": "INSPECTION_FAILED"
    }


def test_absent_route_service_is_unavailable(h: Harness) -> None:
    app = FastAPI()

    def actor(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        return Session(h.users["owner"], "synthetic")

    install_historical_routes(app, actor, None)
    temporary = replace(h, app=app)
    assert temporary.request("GET", "/api/quality/inspections").status_code == 503
