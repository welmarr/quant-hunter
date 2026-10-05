"""Ownership, restart, resource and admission tests; parsing has separate tests."""

from __future__ import annotations

import base64
import shutil
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.web.api import create_app
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.state import AccessError, AppState

PASSWORD = "synthetic-test-password-only"  # noqa: S105


class TestDataService:
    """Controlled service transport; not a claimed parser or live source proof."""

    __test__ = False

    def __init__(self) -> None:
        self.records: dict[str, JsonRecord] = {}
        self.calls = 0
        self.fail = False

    def import_bytes(
        self,
        payload: bytes,
        *,
        file_format: Literal["CSV", "PARQUET"],
        metadata: Mapping[str, JsonValue],
        corrects_dataset_id: str | None = None,
        correction_reason: str | None = None,
    ) -> JsonRecord:
        self.calls += 1
        if self.fail:
            raise ValueError("untrusted-secret-shaped-error")
        identity = f"DATASET-test-{self.calls}"
        result: JsonRecord = {
            "dataset_id": identity,
            "row_count": 2,
            "metadata": dict(metadata),
        }
        self.records[identity] = result
        return result

    def get_dataset(self, dataset_id: str) -> JsonRecord:
        return self.records[dataset_id]

    def probe(self, catalogue_id: str) -> JsonRecord:
        self.calls += 1
        if self.fail:
            raise ValueError("untrusted-secret-shaped-error")
        return {"catalogue_id": catalogue_id, "evidence_mode": "RECORDED_FIXTURE"}


def services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[DataAccess, TestDataService]:
    state = AppState(tmp_path / "application.sqlite3")
    backend = TestDataService()
    service = DataAccess(state, tmp_path, backend, backend)
    monkeypatch.setattr(service, "_capacity", lambda: None)
    return service, backend


def test_ownership_failed_operation_and_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, backend = services(tmp_path, monkeypatch)
    owner = service.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    researcher = service.state.create_user(
        "researcher", PASSWORD, "researcher", bootstrap=False
    )
    first = service.import_data(owner, b"rows", file_format="CSV", metadata={})
    identity = str(first["dataset_id"])
    assert service.dataset(owner, identity) == first
    assert service.datasets(researcher) == []
    with pytest.raises(AccessError, match="unavailable"):
        service.dataset(researcher, identity)
    with pytest.raises(AccessError, match="unavailable"):
        service.import_data(
            researcher,
            b"rows",
            file_format="CSV",
            metadata={},
            corrects_dataset_id=identity,
        )
    second = service.import_data(
        owner,
        b"corrected",
        file_format="CSV",
        metadata={},
        corrects_dataset_id=identity,
        correction_reason="test",
    )
    assert first["dataset_id"] != second["dataset_id"]
    assert len(service.datasets(owner)) == 2
    assert service.dataset_count(owner) == 2
    assert service.dataset_count(researcher) == 0
    assert service.datasets(owner, limit=1, offset=0) == [second]
    assert service.datasets(owner, limit=1, offset=1) == [first]
    assert service.datasets(owner, offset=2) == []
    with pytest.raises(AccessError, match="page"):
        service.datasets(owner, limit=100)
    backend.fail = True
    with pytest.raises(ValueError):
        service.import_data(owner, b"bad", file_format="CSV", metadata={})
    assert service.operations(owner)[0]["status"] == "FAILED"
    assert service.operations(owner)[0]["error"] == "ValueError"
    assert "secret" not in str(service.operations(owner))
    assert len(service.datasets(owner)) == 2
    assert service.operations(researcher) == []


def test_probe_quotas_are_global_persistent_and_count_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, backend = services(tmp_path, monkeypatch)
    owner = service.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    researcher = service.state.create_user(
        "researcher", PASSWORD, "researcher", bootstrap=False
    )
    clock = [1_000_000.0]
    monkeypatch.setattr("quant_hunter.web.data_access.time.time", lambda: clock[0])
    for _ in range(24):
        service.probe(owner, "SRC-04")
        clock[0] += 61
    backend.fail = True
    with pytest.raises(ValueError):
        service.probe(researcher, "SRC-04")
    restarted = DataAccess(service.state, tmp_path, backend, backend)
    monkeypatch.setattr(restarted, "_capacity", lambda: None)
    clock[0] += 61
    with pytest.raises(AccessError, match="25 probes"):
        restarted.probe(owner, "SRC-04")
    assert backend.calls == 25
    backend.fail = False
    restarted.probe(owner, "SRC-08")
    with pytest.raises(AccessError, match="one per minute"):
        restarted.probe(owner, "SRC-08")
    clock[0] += 86401
    restarted.probe(owner, "SRC-04")


def test_interrupted_operations_are_retained_never_replayed_and_admission_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, backend = services(tmp_path, monkeypatch)
    owner = service.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    service._begin(owner, "IMPORT")
    service._begin(owner, "IMPORT")
    with pytest.raises(AccessError, match="busy"):
        service.import_data(owner, b"rows", file_format="CSV", metadata={})
    restarted = DataAccess(service.state, tmp_path, backend, backend)
    restarted.recover()
    assert {op["status"] for op in restarted.operations(owner)} == {"INTERRUPTED"}
    assert backend.calls == 0
    with service.state.connection() as db:
        db.executemany(
            "INSERT INTO data_operations VALUES(?,?,'IMPORT',NULL,0,'FAILED',NULL,NULL)",
            [(f"synthetic-op-{n}", owner.id) for n in range(998)],
        )
    with pytest.raises(AccessError, match="quota reached"):
        service.import_data(owner, b"rows", file_format="CSV", metadata={})


def test_reader_and_unimplemented_probe_do_not_reach_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, backend = services(tmp_path, monkeypatch)
    service.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    reader = service.state.create_user("reader", PASSWORD, "reader", bootstrap=False)
    with pytest.raises(AccessError, match="Researcher"):
        service.probe(reader, "SRC-04")
    with pytest.raises(AccessError, match="Researcher"):
        service.import_data(reader, b"rows", file_format="CSV", metadata={})
    with pytest.raises(AccessError, match="not implemented"):
        service.probe(reader, "SRC-01")
    assert backend.calls == 0


def test_disk_reserve_and_runtime_cap_are_simulated_not_real_disk_filling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = AppState(tmp_path / "application.sqlite3")
    backend = TestDataService()
    service = DataAccess(state, tmp_path, backend, backend)
    gib = 1024**3
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=100 * gib, free=20 * gib, used=80 * gib),
    )
    with pytest.raises(AccessError, match="reserve"):
        service._capacity()
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=100 * gib, free=50 * gib, used=50 * gib),
    )
    service._capacity()
    fake = SimpleNamespace(
        is_file=lambda: True, stat=lambda: SimpleNamespace(st_size=30 * gib)
    )
    monkeypatch.setattr(Path, "rglob", lambda *args: [fake])
    with pytest.raises(AccessError, match="size limit"):
        service._capacity()


def test_api_import_validation_errors_and_cross_account_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, backend = services(tmp_path, monkeypatch)
    app = create_app(
        tmp_path, tmp_path, data=service, sources=[{"catalogue_id": "SRC-04"}]
    )
    payload = {
        "file_format": "CSV",
        "content_base64": base64.b64encode(b"rows").decode(),
        "metadata": {
            "source_name": "test",
            "declared_license": "synthetic",
            "evidence_mode": "SYNTHETIC",
            "instrument": {
                "symbol": "TEST",
                "asset_class": "EQUITY",
                "base_currency": "USD",
                "quote_currency": "USD",
            },
        },
    }
    with TestClient(app) as client:
        response = client.post(
            "/api/setup",
            headers={"X-QH-Request": "1"},
            json={"username": "owner", "password": PASSWORD},
        )
        headers = {"X-QH-Request": "1", "X-CSRF-Token": response.json()["csrf"]}
        assert (
            client.get("/api/sources").json()["sources"][0]["catalogue_id"] == "SRC-04"
        )
        result = client.post("/api/datasets", headers=headers, json=payload)
        assert result.status_code == 201
        identity = result.json()["dataset_id"]
        assert client.get(f"/api/datasets/{identity}").status_code == 200
        assert len(client.get("/api/datasets").json()["datasets"]) == 1
        assert (
            client.post(
                "/api/datasets",
                headers=headers,
                json={**payload, "content_base64": "bad@"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/datasets",
                headers=headers,
                json={**payload, "content_base64": "="},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/datasets",
                headers=headers,
                json={
                    **payload,
                    "content_base64": base64.b64encode(b"x" * 2_000_001).decode(),
                },
            ).status_code
            == 413
        )
        assert (
            client.post(
                "/api/datasets", headers={"X-QH-Request": "1"}, json=payload
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/datasets", headers=headers, content=b"x" * 3_000_001
            ).status_code
            == 413
        )
        backend.fail = True
        response = client.post("/api/datasets", headers=headers, json=payload)
        assert response.status_code == 422 and "untrusted-secret" not in response.text
        assert (
            client.get("/api/data-operations").json()["operations"][0]["error"]
            == "ValueError"
        )
        response = client.post("/api/sources/SRC-08/probe", headers=headers)
        assert response.status_code == 422 and "untrusted-secret" not in response.text
        assert (
            client.post("/api/sources/SRC-99/probe", headers=headers).status_code == 403
        )
        service.state.create_user("reader", PASSWORD, "reader", bootstrap=False)
        response = client.post(
            "/api/login",
            headers={"X-QH-Request": "1"},
            json={"username": "reader", "password": PASSWORD},
        )
        reader_headers = {"X-QH-Request": "1", "X-CSRF-Token": response.json()["csrf"]}
        assert client.get("/api/datasets").json()["datasets"] == []
        assert client.get("/api/datasets?limit=51").status_code == 422
        assert client.get("/api/datasets?offset=-1").status_code == 422
        assert client.get(f"/api/datasets/{identity}").status_code == 403
        assert (
            client.post(
                "/api/datasets", headers=reader_headers, json=payload
            ).status_code
            == 403
        )


def test_retained_provider_failure_is_not_a_successful_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, backend = services(tmp_path, monkeypatch)
    owner = service.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    monkeypatch.setattr(
        backend,
        "probe",
        lambda _: {
            "status": "FAILED",
            "error_code": "ACCESS_DENIED",
            "capture_digest": "sha256:" + "1" * 64,
        },
    )
    result = service.probe(owner, "SRC-04")
    assert result["status"] == "FAILED"
    operation = service.operations(owner)[0]
    assert operation["status"] == "FAILED"
    assert operation["error"] == "ACCESS_DENIED"
    assert operation["result"] == result


def test_unavailable_data_service_is_visible(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path, tmp_path)) as client:
        response = client.post(
            "/api/setup",
            headers={"X-QH-Request": "1"},
            json={"username": "owner", "password": PASSWORD},
        )
        headers = {"X-QH-Request": "1", "X-CSRF-Token": response.json()["csrf"]}
        assert client.get("/api/datasets").status_code == 503
        assert (
            client.post("/api/sources/SRC-04/probe", headers=headers).status_code == 503
        )
