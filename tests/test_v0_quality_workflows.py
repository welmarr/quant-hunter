"""Private quality workflows exercise actual SQLite, governed graphs and Parquet."""

from __future__ import annotations

import base64
import hmac
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from fastapi import FastAPI, HTTPException, Request
from test_v0_data_quality import SCHEMAS, metadata, payload, setup, spec
from test_v0_publication_workflows import LocalClient

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.data_quality import QualityError
from quant_hunter.imports import ImportService
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.quality_routes import install_quality_routes
from quant_hunter.web.state import AccessError, AppState, Session, User


class NoNetwork:
    def probe(self, catalogue_id: str) -> JsonRecord:
        raise AssertionError("Quality routes cannot call external providers")


@dataclass
class Harness:
    access: QualityAccess
    client: LocalClient
    users: dict[str, User]
    sessions: dict[str, tuple[str, str]]
    instrument_id: str
    instrument_digest: str

    def login(self, name: str) -> None:
        token, csrf = self.sessions[name]
        self.client.cookies.set("qh_session", token)
        self.client.headers["x-csrf-token"] = csrf

    def body(self, raw: bytes | None = None) -> dict[str, Any]:
        return {
            "content_base64": base64.b64encode(
                payload() if raw is None else raw
            ).decode(),
            "file_format": "CSV",
            "metadata": metadata(),
            "mapping": spec().to_record(),
            "instrument_id": self.instrument_id,
            "instrument_revision_digest": self.instrument_digest,
            "calendar_start": "2025-01-06",
            "calendar_end": "2025-01-06",
        }

    def upload(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.post(
            "/api/quality/datasets", json=self.body() if body is None else body
        )
        assert response.status_code == 201, response.text
        return cast(dict[str, Any], response.json())

    def direct(self) -> JsonRecord:
        return self.access.import_mapped(
            self.users["owner"],
            payload(),
            file_format="CSV",
            metadata=metadata(),
            mapping=spec(),
            instrument_id=self.instrument_id,
            instrument_revision_digest=self.instrument_digest,
            calendar_start=date(2025, 1, 6),
            calendar_end=date(2025, 1, 6),
        )


@pytest.fixture
def h(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    service, identity, revision = setup(tmp_path)
    state = AppState(tmp_path / "state.sqlite3")
    users, sessions = {}, {}
    for name, role in (
        ("owner", "owner"),
        ("other", "researcher"),
        ("reader", "reader"),
    ):
        users[name] = state.create_user(
            name,
            "synthetic password",
            cast(Literal["owner", "researcher", "reader"], role),
            bootstrap=name == "owner",
        )
        token, session = state.login(name, "synthetic password")
        sessions[name] = token, session.csrf
    importer = ImportService(
        service.registry,
        service.objects,
        SCHEMAS,
        code_revision=service.code_revision,
        environment_digest=service.environment_digest,
    )
    data = DataAccess(state, tmp_path, importer, NoNetwork())
    monkeypatch.setattr(data, "_capacity", lambda: None)
    access = QualityAccess(
        state, service, data, InstrumentRegistry(service.registry, clock=service.clock)
    )
    app = FastAPI()

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        try:
            session = state.session(request.cookies.get("qh_session", ""))
        except AccessError:
            raise HTTPException(401, "Sign in") from None
        if mutation and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), session.csrf
        ):
            raise HTTPException(403, "CSRF")
        if owner and session.user.role != "owner":
            raise HTTPException(403, "Owner required")
        return session

    install_quality_routes(app, authenticated, access)
    result = Harness(access, LocalClient(app), users, sessions, identity, revision)
    result.login("owner")
    return result


def receipt(row: dict[str, Any]) -> dict[str, str]:
    return {
        key: cast(str, row[key])
        for key in ("dataset_id", "record_digest", "quality_report_digest")
    }


def test_private_upload_actual_immutable_bytes_and_restart(h: Harness) -> None:
    row = h.upload()
    assert row["row_count"] == 5 and row["causal_eligible"] is True
    assert row["empirically_validated"] is False
    assert h.access.service.objects.read_bytes(row["raw_digest"]) == payload()
    assert h.client.get(f"/api/quality/datasets/{row['dataset_id']}").json() == row
    assert len(h.client.get("/api/quality/datasets").json()["datasets"]) == 1
    h.login("other")
    assert h.client.get(f"/api/quality/datasets/{row['dataset_id']}").status_code == 403
    assert h.client.get("/api/quality/datasets").json() == {"datasets": []}
    assert h.client.get("/api/quality/operations").json() == {"operations": []}
    restarted = QualityAccess(
        h.access.state, h.access.service, h.access.data, h.access.instruments
    )
    assert restarted.dataset(h.users["owner"], row["dataset_id"]) == row
    with pytest.raises(AccessError):
        h.access.data.owns(h.users["owner"], row["dataset_id"])


def test_researcher_can_import_reader_cannot_write(h: Harness) -> None:
    h.login("other")
    row = h.upload()
    h.login("reader")
    assert h.client.post("/api/quality/datasets", json=h.body()).status_code == 403
    assert h.client.post("/api/quality/demo", json={}).status_code == 403
    assert h.client.get(f"/api/quality/datasets/{row['dataset_id']}").status_code == 403


def test_auth_and_csrf_no_effects(h: Harness) -> None:
    h.client.cookies.clear()
    assert h.client.get("/api/quality/datasets").status_code == 401
    h.login("owner")
    h.client.headers["x-csrf-token"] = "wrong"
    assert h.client.post("/api/quality/datasets", json=h.body()).status_code == 403
    assert h.access.data.operations(h.users["owner"]) == []


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "secret",
        "huge",
        "path",
        "bool",
        "format",
        "duplicate_mapping",
        "date",
        "base64",
    ],
)
def test_closed_bounded_upload_sanitized(h: Harness, change: str) -> None:
    body = h.body()
    if change == "extra":
        body["surprise"] = "do not echo this"
    elif change == "secret":
        body["metadata"]["source_name"] = "api_key=do-not-echo-secret"
    elif change == "huge":
        body["content_base64"] = "A" * 2_666_672
    elif change == "path":
        body["metadata"]["source_name"] = "../../private"
    elif change == "bool":
        body["mapping"]["price_scale"] = True
    elif change == "format":
        body["file_format"] = "PICKLE"
    elif change == "duplicate_mapping":
        body["mapping"]["columns"]["high"] = "open"
    elif change == "date":
        body["calendar_start"] = "2025-02-30"
    else:
        body["content_base64"] = "!!!!"
    response = h.client.post("/api/quality/datasets", json=body)
    assert response.status_code in (400, 422), response.text
    assert "do-not-echo" not in response.text and "../../" not in response.text
    assert h.access.datasets(h.users["owner"]) == []


def test_stale_instrument_refused(h: Harness) -> None:
    body = h.body()
    body["instrument_revision_digest"] = "sha256:" + "f" * 64
    assert h.client.post("/api/quality/datasets", json=body).status_code == 409
    assert not h.access.data.operations(h.users["owner"])


def test_failed_rows_keep_audit_and_no_ownership(h: Harness) -> None:
    response = h.client.post(
        "/api/quality/datasets",
        json=h.body(payload().replace(b",100,102,99,101,", b",100,1,99,101,")),
    )
    assert response.status_code == 400, response.text
    audit = response.json()["detail"]["audit_digest"]
    assert audit.startswith("sha256:")
    assert h.access.service.objects.read_bytes(audit)
    operation = h.client.get("/api/quality/operations").json()["operations"][0]
    assert operation["status"] == "FAILED" and operation["result"] == {
        "audit_digest": audit
    }
    assert h.access.datasets(h.users["owner"]) == []


def test_aggregate_and_exact_owned_selection(h: Harness) -> None:
    row = h.upload()
    parent = receipt(row)
    aggregate = {k: v for k, v in parent.items() if k != "dataset_id"} | {
        "timeframe": "5m",
        "partial_policy": "DROP",
        "as_of": "2025-01-06T15:00:00Z",
    }
    response = h.client.post(
        f"/api/quality/datasets/{row['dataset_id']}/aggregate", json=aggregate
    )
    assert response.status_code == 201, response.text
    assert (
        response.json()["row_count"] == 1
        and response.json()["dataset_id"] != row["dataset_id"]
    )
    response = h.client.post("/api/quality/selections", json={"parents": [parent]})
    assert response.status_code == 201, response.text
    selected = response.json()
    assert selected["total_rows"] == 5
    assert (
        h.client.get(f"/api/quality/selections/{selected['manifest_digest']}").json()
        == selected
    )
    assert len(h.client.get("/api/quality/selections").json()["selections"]) == 1
    batches = list(
        h.access.iter_selection(h.users["owner"], selected["manifest_digest"])
    )
    assert sum(batch.num_rows for _, batch in batches) == 5
    assert all(index == 0 for index, _ in batches)
    with h.access.state.connection() as db:
        db.execute(
            "DELETE FROM quality_ownership WHERE dataset_id=?", (row["dataset_id"],)
        )
    assert (
        h.client.get(
            f"/api/quality/selections/{selected['manifest_digest']}"
        ).status_code
        == 403
    )


@pytest.mark.parametrize("operation", ["aggregate", "compose", "selected"])
def test_stale_dataset_receipt_blocks_all_use(h: Harness, operation: str) -> None:
    row = h.upload()
    parent = receipt(row) | {"record_digest": "sha256:" + "f" * 64}
    if operation == "compose":
        response = h.client.post("/api/quality/selections", json={"parents": [parent]})
    elif operation == "aggregate":
        body = {k: v for k, v in parent.items() if k != "dataset_id"} | {
            "timeframe": "5m",
            "partial_policy": "DROP",
            "as_of": "2025-01-06T15:00:00Z",
        }
        response = h.client.post(
            f"/api/quality/datasets/{row['dataset_id']}/aggregate", json=body
        )
    else:
        from quant_hunter.identity import StaleWriterError

        with pytest.raises(StaleWriterError):
            h.access.selected(
                h.users["owner"],
                row["dataset_id"],
                record_digest=parent["record_digest"],
                quality_report_digest=parent["quality_report_digest"],
            )
        return
    assert response.status_code == 409


def test_historical_unknown_never_promoted(h: Harness) -> None:
    body = h.body()
    body["metadata"]["evidence_mode"] = "HISTORICAL"
    body["mapping"]["revision_mode"] = "REQUIRED_UNKNOWN"
    row = h.upload(body)
    assert row["causal_eligible"] is False
    assert (
        h.client.post(
            "/api/quality/selections", json={"parents": [receipt(row)]}
        ).status_code
        == 400
    )
    response = h.client.post(
        "/api/quality/selections",
        json={"parents": [receipt(row)], "purpose": "EXPLORATORY_INSPECTION"},
    )
    assert response.status_code == 400 and "DATASET_NOT_ADMISSIBLE" in response.text
    assert h.client.get(f"/api/quality/datasets/{row['dataset_id']}").status_code == 200


def test_cross_user_parent_rejected_before_canonical_write(h: Harness) -> None:
    row = h.upload()
    h.login("other")
    assert (
        h.client.post(
            "/api/quality/selections", json={"parents": [receipt(row)]}
        ).status_code
        == 403
    )
    operations = h.access.data.operations(h.users["other"])
    assert len(operations) == 1 and operations[0]["status"] == "FAILED"
    assert h.access.selections(h.users["other"]) == []


def test_shared_active_slots_and_capacity(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with h.access.state.connection() as db:
        db.execute("CREATE TABLE publication_operations(status TEXT)")
        db.execute("INSERT INTO publication_operations VALUES('RUNNING')")
    held = h.access.data._begin(h.users["other"], "IMPORT")
    assert h.client.post("/api/quality/datasets", json=h.body()).status_code == 403
    h.access.data._finish(held, error="synthetic interruption")

    def full() -> None:
        raise AccessError("capacity blocked")

    monkeypatch.setattr(h.access.data, "_capacity", full)
    assert h.client.post("/api/quality/datasets", json=h.body()).status_code == 403


def test_interruption_after_publication_never_grants_or_replays(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = h.access.service.ingest_mapped
    published = []

    def interrupted(*args: Any, **kwargs: Any) -> JsonRecord:
        result = original(*args, **kwargs)
        published.append(result)
        raise KeyboardInterrupt

    monkeypatch.setattr(h.access.service, "ingest_mapped", interrupted)
    with pytest.raises(KeyboardInterrupt):
        h.direct()
    assert h.access.data.operations(h.users["owner"])[0]["status"] == "RUNNING"
    h.access.data.recover()
    assert h.access.data.operations(h.users["owner"])[0]["status"] == "INTERRUPTED"
    assert h.access.datasets(h.users["owner"]) == []
    assert h.access.service.get_dataset(cast(str, published[0]["dataset_id"]))


def test_finish_cannot_claim_interrupted_operation(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = h.access.service.ingest_mapped

    def interrupted(*args: Any, **kwargs: Any) -> JsonRecord:
        result = original(*args, **kwargs)
        h.access.data.recover()
        return result

    monkeypatch.setattr(h.access.service, "ingest_mapped", interrupted)
    response = h.client.post("/api/quality/datasets", json=h.body())
    assert response.status_code == 403
    assert h.access.datasets(h.users["owner"]) == []
    assert h.access.data.operations(h.users["owner"])[0]["status"] == "INTERRUPTED"


def test_selection_replay_detects_coherent_mutation(h: Harness) -> None:
    row = h.upload()
    selected = h.client.post(
        "/api/quality/selections", json={"parents": [receipt(row)]}
    ).json()
    from quant_hunter.config import parse_json_document

    document = cast(
        JsonRecord,
        parse_json_document(
            h.access.service.objects.read_bytes(selected["manifest_digest"])
        ),
    )
    document["total_rows"] = 999
    replacement = h.access.service.objects.publish(canonicalize_json(document)).digest
    with h.access.state.connection() as db:
        db.execute(
            "INSERT INTO quality_selection_ownership VALUES(?,?)",
            (replacement, h.users["owner"].id),
        )
    response = h.client.get(f"/api/quality/selections/{replacement}")
    assert response.status_code == 400 and "REPLAY_MISMATCH" in response.text


def test_explicit_demo_creates_two_real_private_canonical_datasets(h: Harness) -> None:
    response = h.client.post("/api/quality/demo", json={})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["evidence_mode"] == "SYNTHETIC"
    assert result["generator"]["empirically_validated"] is False
    rows = result["datasets"]
    assert len(rows) == 2 and len({row["instrument_id"] for row in rows}) == 2
    for row in rows:
        assert row["row_count"] == 240 and row["causal_eligible"] is True
        selected, raw = h.access.selected(
            h.users["owner"],
            row["dataset_id"],
            record_digest=row["record_digest"],
            quality_report_digest=row["quality_report_digest"],
        )
        assert selected.row_count == 240 and raw.startswith(b"PAR1")
    h.login("other")
    assert h.client.post("/api/quality/demo", json={}).status_code == 403
    assert h.client.get("/api/quality/datasets").json() == {"datasets": []}


def test_real_parquet_upload_and_reimport_retains_versions(h: Harness) -> None:
    import pyarrow as pa  # type: ignore[import-untyped]
    import pyarrow.csv as pc  # type: ignore[import-untyped]
    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    table = pc.read_csv(pa.BufferReader(payload()))
    output = pa.BufferOutputStream()
    pq.write_table(table, output, compression="NONE", use_dictionary=False)
    raw = output.getvalue().to_pybytes()
    body = h.body(raw)
    body["file_format"] = "PARQUET"
    first, second = h.upload(body), h.upload(body)
    assert first["dataset_id"] != second["dataset_id"]
    assert first["raw_digest"] == second["raw_digest"]
    assert h.access.service.objects.read_bytes(first["raw_digest"]) == raw
    assert h.client.get(f"/api/quality/datasets/{first['dataset_id']}").json() == first


def test_composed_sequential_uploads_and_overlap_rejection(h: Harness) -> None:
    first = h.upload()
    raw = payload()
    for minute in range(35, 29, -1):
        raw = raw.replace(f"14:{minute:02}:".encode(), f"14:{minute + 5:02}:".encode())
    second = h.upload(h.body(raw))
    response = h.client.post(
        "/api/quality/selections", json={"parents": [receipt(first), receipt(second)]}
    )
    assert response.status_code == 201, response.text
    selection = response.json()
    assert selection["total_rows"] == 10
    batches = list(
        h.access.iter_selection(h.users["owner"], selection["manifest_digest"])
    )
    assert [index for index, _ in batches] == [0, 1]
    assert (
        h.client.post(
            "/api/quality/selections",
            json={"parents": [receipt(second), receipt(first)]},
        ).status_code
        == 400
    )
    assert (
        h.client.post(
            "/api/quality/selections",
            json={"parents": [receipt(first), receipt(first)]},
        ).status_code
        == 400
    )


def test_reader_owned_reads_and_no_inherited_write_authority(h: Harness) -> None:
    row = h.upload()
    with h.access.state.connection() as db:
        db.execute(
            "UPDATE quality_ownership SET owner_id=? WHERE dataset_id=?",
            (h.users["reader"].id, row["dataset_id"]),
        )
    h.login("reader")
    assert h.client.get(f"/api/quality/datasets/{row['dataset_id']}").status_code == 200
    assert (
        h.client.post(
            "/api/quality/selections", json={"parents": [receipt(row)]}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("as_of", ["2025-01-06T15:00:00.0", "invalid-date-00000000000"])
def test_aggregation_requires_explicit_valid_instant(h: Harness, as_of: str) -> None:
    row = h.upload()
    body = {
        key: value for key, value in receipt(row).items() if key != "dataset_id"
    } | {"timeframe": "5m", "partial_policy": "DROP", "as_of": as_of}
    response = h.client.post(
        f"/api/quality/datasets/{row['dataset_id']}/aggregate", json=body
    )
    assert response.status_code == 400 and "INVALID_AS_OF" in response.text


def test_failed_internal_operation_sanitizes_messages(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(*args: Any, **kwargs: Any) -> JsonRecord:
        raise RuntimeError("synthetic-secret-must-not-echo")

    monkeypatch.setattr(h.access.service, "ingest_mapped", failed)
    response = h.client.post("/api/quality/datasets", json=h.body())
    assert response.status_code == 503 and "synthetic-secret" not in response.text
    operation = h.access.data.operations(h.users["owner"])[0]
    assert (
        operation["status"] == "FAILED"
        and operation["error"] == "QUALITY_OPERATION_FAILED"
    )


def test_unavailable_service_still_authenticates(h: Harness) -> None:
    app = FastAPI()

    def auth(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        return h.access.state.session(h.sessions["owner"][0])

    install_quality_routes(app, auth, None)
    assert LocalClient(app).get("/api/quality/datasets").status_code == 503


def test_exact_report_tampering_refuses_verified_read(h: Harness) -> None:
    row = h.upload()
    target = h.access.service.objects.object_path(row["quality_report_digest"])
    target.write_bytes(b"untrusted changed report")
    assert h.client.get(f"/api/quality/datasets/{row['dataset_id']}").status_code == 503


def test_ownership_and_operation_finish_rollback_together(h: Harness) -> None:
    row = h.upload()
    owner = h.users["owner"]
    operation = h.access.data._begin(owner, "QUALITY_IMPORT")
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        h.access._finish(owner, operation, row, dataset_ids=(row["dataset_id"],))
    assert h.access.data.operations(owner)[0]["status"] == "RUNNING"
    assert len(h.access.datasets(owner)) == 1


def test_declared_restrictions_are_bound_not_dropped(h: Harness) -> None:
    body = h.body()
    body["metadata"]["declared_restrictions"] = "Synthetic local test only"
    row = h.upload(body)
    assert row["metadata"]["declared_restrictions"] == "Synthetic local test only"


def test_demo_exact_bytes_ignore_ambient_decimal_context(h: Harness) -> None:
    from decimal import Context, Inexact, Rounded, localcontext

    first = h.access.demo(h.users["owner"])
    with localcontext(Context(prec=2, Emin=-2, Emax=2, traps=[Inexact, Rounded])):
        second = h.access.demo(h.users["owner"])
    first_rows = cast(list[JsonRecord], first["datasets"])
    second_rows = cast(list[JsonRecord], second["datasets"])
    assert [row["raw_digest"] for row in first_rows] == [
        row["raw_digest"] for row in second_rows
    ]
    raw = h.access.service.objects.read_bytes(cast(str, second_rows[0]["raw_digest"]))
    assert b",99.88," in raw


@pytest.mark.parametrize("operation", ["compose", "aggregate"])
def test_heavy_receipt_verification_requires_resource_slot(
    h: Harness, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    row = h.upload()
    h.access.data._begin(h.users["owner"], "IMPORT")
    h.access.data._begin(h.users["other"], "IMPORT")

    def forbidden(*args: Any, **kwargs: Any) -> JsonRecord:
        pytest.fail("Expensive immutable graph replay ran outside shared admission")

    monkeypatch.setattr(h.access, "_receipt", forbidden)
    if operation == "compose":
        response = h.client.post(
            "/api/quality/selections", json={"parents": [receipt(row)]}
        )
    else:
        body = {
            key: value for key, value in receipt(row).items() if key != "dataset_id"
        } | {
            "timeframe": "5m",
            "partial_policy": "DROP",
            "as_of": "2025-01-06T15:00:00Z",
        }
        response = h.client.post(
            f"/api/quality/datasets/{row['dataset_id']}/aggregate", json=body
        )
    assert response.status_code == 403


@pytest.mark.parametrize("attribute", ["registry", "objects"])
def test_mismatched_governed_import_stores_are_refused(
    h: Harness, monkeypatch: pytest.MonkeyPatch, attribute: str
) -> None:
    monkeypatch.setattr(h.access.data.importer, attribute, object())
    with pytest.raises(ValueError, match="shared governed"):
        QualityAccess(
            h.access.state, h.access.service, h.access.data, h.access.instruments
        )


def test_current_metadata_old_cutoff_is_retained_then_current_cutoff_succeeds(
    h: Harness,
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    h.access.service.clock = lambda: datetime.now(UTC)
    h.access.instruments.clock = h.access.service.clock
    rows = cast(list[JsonRecord], h.access.demo(h.users["owner"])["datasets"])
    row = cast(dict[str, Any], rows[0])
    body = {
        key: value for key, value in receipt(row).items() if key != "dataset_id"
    } | {"timeframe": "5m", "partial_policy": "DROP", "as_of": "2025-01-06T19:00:00Z"}
    response = h.client.post(
        f"/api/quality/datasets/{row['dataset_id']}/aggregate", json=body
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]["code"]
        == "INSTRUMENT_METADATA_NOT_AVAILABLE_AT_AS_OF"
    )
    operation = h.access.data.operations(h.users["owner"])[0]
    assert (
        operation["status"] == "FAILED"
        and operation["error"] == "INSTRUMENT_METADATA_NOT_AVAILABLE_AT_AS_OF"
    )
    assert len(h.access.datasets(h.users["owner"])) == 2
    body["as_of"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    response = h.client.post(
        f"/api/quality/datasets/{row['dataset_id']}/aggregate", json=body
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert (
        result["row_count"] == 48
        and result["evidence_mode"] == "SYNTHETIC"
        and result["causal_eligible"] is True
    )
    assert result["quality"]["as_of"] == body["as_of"]
    table = pq.read_table(
        pa.BufferReader(
            h.access.service.objects.read_bytes(result["normalized_digest"])
        )
    )
    assert table["available_at"][0].as_py() == datetime(2025, 1, 6, 14, 35, tzinfo=UTC)
    assert table["ingestion_time"][0].as_py() == datetime.fromisoformat(body["as_of"])


def test_lists_use_bounded_immutable_metadata_without_decoding_or_fresh_admission(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = h.upload()
    selection = h.access.compose(
        h.users["owner"], (cast(tuple[str, str, str], tuple(receipt(row).values())),)
    )

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Listing performed expensive data replay")

    monkeypatch.setattr(h.access.service, "get_dataset", forbidden)
    monkeypatch.setattr(h.access, "_selection", forbidden)
    datasets = h.access.datasets(h.users["owner"])
    selected = h.access.selections(h.users["owner"])
    assert len(datasets) == len(selected) == 1
    assert datasets[0]["record_digest"] == row["record_digest"]
    assert datasets[0]["row_count"] == 5
    assert datasets[0]["admission"] == "NOT_FRESH_ADMISSION"
    assert datasets[0]["reported_admission"] == row["admission"]
    assert selected[0]["manifest_digest"] == selection["manifest_digest"]
    assert selected[0]["parent_snapshots"] == selection["parent_snapshots"]
    assert all(item["causal_eligible"] is False for item in datasets + selected)
    assert all(
        "NOT_FRESH_ADMISSION" in cast(str, item["inspection"])
        for item in datasets + selected
    )


def test_summary_does_not_claim_missing_raw_is_verified_but_metadata_must_exist(
    h: Harness,
) -> None:
    row = h.upload()
    h.access.service.objects.get(row["raw_digest"]).path.unlink()
    assert h.access.datasets(h.users["owner"])[0]["admission"] == "NOT_FRESH_ADMISSION"
    assert h.client.get(f"/api/quality/datasets/{row['dataset_id']}").status_code == 503
    h.access.service.objects.get(row["configuration_digest"]).path.unlink()
    assert h.client.get("/api/quality/datasets").status_code == 503


def test_reader_inspection_uses_shared_slots_without_consuming_import_quota(
    h: Harness,
) -> None:
    row = h.upload()
    user = replace(h.users["owner"], role="reader")
    with h.access.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (user.id,))
        before = db.execute("SELECT COUNT(*) FROM data_operations").fetchone()[0]
    assert (
        h.access.dataset(user, row["dataset_id"])["record_digest"]
        == row["record_digest"]
    )
    with h.access.inspection(user):
        with h.access.inspection(h.users["other"]):
            with pytest.raises(AccessError, match="busy"):
                h.access.dataset(user, row["dataset_id"])
            with pytest.raises(AccessError, match="busy"):
                h.access.data._begin(h.users["other"], "IMPORT")
            assert h.access.state.claim() is None
    with h.access.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0] == 0
        assert (
            db.execute("SELECT COUNT(*) FROM data_operations").fetchone()[0] == before
        )


def test_expensive_reads_reject_before_replay_with_two_actual_operations(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = h.upload()
    selection = h.access.compose(
        h.users["owner"], (cast(tuple[str, str, str], tuple(receipt(row).values())),)
    )
    first = h.access.data._begin(h.users["owner"], "FIRST")
    second = h.access.data._begin(h.users["other"], "SECOND")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Read replay started outside resource bound")

    monkeypatch.setattr(h.access.service, "get_dataset", forbidden)
    monkeypatch.setattr(h.access, "_selection", forbidden)
    with pytest.raises(AccessError, match="busy"):
        h.access.dataset(h.users["owner"], row["dataset_id"])
    with pytest.raises(AccessError, match="busy"):
        h.access.selected(
            h.users["owner"],
            row["dataset_id"],
            record_digest=row["record_digest"],
            quality_report_digest=row["quality_report_digest"],
        )
    with pytest.raises(AccessError, match="busy"):
        h.access.selection(h.users["owner"], cast(str, selection["manifest_digest"]))
    with pytest.raises(AccessError, match="busy"):
        next(
            h.access.iter_selection(
                h.users["owner"], cast(str, selection["manifest_digest"])
            )
        )
    h.access.data._finish(first)
    h.access.data._finish(second)


def test_operation_bypass_requires_actual_owned_running_reservation(h: Harness) -> None:
    row = h.upload()
    own = h.access.data._begin(h.users["owner"], "FIRST")
    foreign = h.access.data._begin(h.users["other"], "SECOND")
    assert (
        h.access.dataset(h.users["owner"], row["dataset_id"], operation_id=own)[
            "dataset_id"
        ]
        == row["dataset_id"]
    )
    for invalid in (foreign, "untrusted-client-string"):
        with pytest.raises(AccessError, match="Active owned"):
            h.access.dataset(h.users["owner"], row["dataset_id"], operation_id=invalid)
    h.access.data._finish(own)
    with pytest.raises(AccessError, match="Active owned"):
        h.access.dataset(h.users["owner"], row["dataset_id"], operation_id=own)
    h.access.data._finish(foreign)


def test_reader_reservation_releases_on_exception_and_generator_close(
    h: Harness,
) -> None:
    row = h.upload()
    selected = h.access.compose(
        h.users["owner"], (cast(tuple[str, str, str], tuple(receipt(row).values())),)
    )
    with pytest.raises(KeyboardInterrupt):
        with h.access.inspection(h.users["owner"]):
            raise KeyboardInterrupt
    stream = h.access.iter_selection(
        h.users["owner"], cast(str, selected["manifest_digest"])
    )
    next(stream)
    with h.access.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0] == 1
    cast(Any, stream).close()
    with h.access.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["dataset", "selection"])
@pytest.mark.parametrize("single_oversized", [True, False])
def test_summary_page_limit_fails_closed_without_truncated_pagination(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    single_oversized: bool,
) -> None:
    import quant_hunter.web.quality_access as module

    first = h.upload()
    second = h.upload()
    if kind == "selection":
        for row in (first, second):
            h.access.compose(
                h.users["owner"],
                (cast(tuple[str, str, str], tuple(receipt(row).values())),),
            )
    original = canonicalize_json

    def oversized(value: Any) -> bytes:
        if isinstance(value, dict) and "inspection" in value:
            return b"x" * (2_000_001 if single_oversized else 1_000_001)
        return original(value)

    monkeypatch.setattr(module, "canonicalize_json", oversized)
    listing = h.access.datasets if kind == "dataset" else h.access.selections
    with pytest.raises(QualityError, match="SUMMARY_PAGE_LIMIT"):
        listing(h.users["owner"], limit=1 if single_oversized else 2)
    if not single_oversized:
        assert len(listing(h.users["owner"], limit=1, offset=0)) == 1
        assert len(listing(h.users["owner"], limit=1, offset=1)) == 1
