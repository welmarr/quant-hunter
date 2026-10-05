"""Real encrypted-vault/API/registry integration using only synthetic HTTP bytes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from quant_hunter.config import JsonRecord, parse_json_document
from quant_hunter.credentials import VaultError
from quant_hunter.imports import ImportService
from quant_hunter.lab import LabService
from quant_hunter.sources._equity_transport import EquityRequest, EquityResponse
from quant_hunter.sources.alpaca_data import AlpacaCredentials, AlpacaDataConnector
from quant_hunter.sources.equity_probes import EquityProbeService, diagnostic_json
from quant_hunter.sources.probes import SourceProbeService
from quant_hunter.sources.sec import SECConnector, SECIdentity
from quant_hunter.sources.transport import SourceError
from quant_hunter.web.api import create_app
from quant_hunter.web.connections import (
    Connections,
    SourceRouter,
    default_private_root,
    validated_config,
)
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.state import AppState

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "synthetic-only-local-password"  # noqa: S105
KEY = "fixture-only-key-0123"
SECRET = "fixture-only-secret-0456"  # noqa: S105
ALPACA: JsonRecord = {
    "key_id": KEY,
    "secret_key": SECRET,
    "credential_source": "PAPER_ACCOUNT",
    "entitlement_confirmed": True,
    "no_incremental_charge": True,
}
SEC: JsonRecord = {
    "organization": "Synthetic Organization",
    "contact_email": "synthetic@example.test",
    "cik": "0000320193",
    "license_confirmed": True,
}


class Transport:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def send(self, request: EquityRequest) -> EquityResponse:
        self.calls += 1
        if self.fail:
            return EquityResponse(429, b'{"message":"fixture quota"}')
        if request.host == "data.sec.gov":
            data: object = {
                "cik": "0000320193",
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000320193-25-000001"],
                        "filingDate": ["2025-02-01"],
                        "reportDate": ["2024-12-31"],
                        "acceptanceDateTime": ["2025-02-01T18:00:00Z"],
                        "form": ["10-K"],
                        "primaryDocument": ["synthetic.htm"],
                    }
                },
            }
        else:
            data = {
                "bars": {
                    "AAPL": [
                        {
                            "t": "2024-01-02T05:00:00Z",
                            "o": 100,
                            "h": 102,
                            "l": 99,
                            "c": 101,
                            "v": 10,
                            "n": 2,
                            "vw": 100.5,
                        }
                    ]
                },
                "next_page_token": None,
            }
        return EquityResponse(200, json.dumps(data).encode())


def services(tmp_path: Path) -> tuple[Connections, DataAccess, LabService, Transport]:
    repository = tmp_path / "application"
    repository.mkdir()
    runtime = tmp_path / "runtime"
    lab = LabService(
        runtime / "research",
        ROOT / "schemas/v1",
        "a" * 40,
        {"purpose": "synthetic connection integration"},
    )
    public = SourceProbeService(
        lab.registry, lab.objects, ROOT / "schemas/v1", "a" * 40, lab.environment_digest
    )
    transport = Transport()

    def factory(source: str, values: JsonRecord) -> SECConnector | AlpacaDataConnector:
        if source == "SRC-01":
            return SECConnector(
                SECIdentity(
                    cast(str, values["organization"]),
                    cast(str, values["contact_email"]),
                ),
                transport,
            )
        return AlpacaDataConnector(
            AlpacaCredentials(
                cast(str, values["key_id"]),
                cast(str, values["secret_key"]),
                cast(str, values["credential_source"]),
            ),
            transport,
        )

    connections = Connections(
        tmp_path / "private",
        repository,
        runtime,
        EquityProbeService(public),
        connector_factory=factory,
    )
    state = AppState(runtime / "application.sqlite3")
    data = DataAccess(
        state,
        runtime,
        ImportService(
            lab.registry,
            lab.objects,
            ROOT / "schemas/v1",
            "a" * 40,
            lab.environment_digest,
        ),
        SourceRouter(public, connections),
    )
    return connections, data, lab, transport


def test_save_mask_revoke_rotate_are_offline_and_outside_backups(
    tmp_path: Path,
) -> None:
    connections, _, _, transport = services(tmp_path)
    assert not connections.status()["initialized"]
    assert not connections.private_root.exists()
    connections.save("SRC-02", ALPACA)
    before = json.dumps(connections.status())
    assert "CONFIGURED" in before and "********" in before
    assert KEY not in before and SECRET not in before
    assert connections.rotate()["versions_rotated"] == 1
    assert connections.probe("SRC-02")["record_count"] == 1
    assert transport.calls == 1
    connections.revoke("SRC-02")
    with pytest.raises(VaultError, match="CREDENTIAL_NOT_CONFIGURED"):
        connections.probe("SRC-02")
    assert transport.calls == 1
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()
            assert KEY.encode() not in path.read_bytes()


@pytest.mark.parametrize("source,config", [("SRC-01", SEC), ("SRC-02", ALPACA)])
def test_configured_probe_registers_before_fetch_and_retains_exact_graph(
    tmp_path: Path, source: str, config: JsonRecord
) -> None:
    connections, _, lab, transport = services(tmp_path)
    connections.save(source, config)
    result = connections.probe(source)
    assert transport.calls == 1 and result["status"] == "SUCCEEDED"
    assert (
        result["evidence_mode"] == "RECORDED_FIXTURE" and result["quality"] == "PENDING"
    )
    assert result["record_count"] == 1
    source_record = lab.registry.verify_object(cast(str, result["source_id"]))[-1]
    dataset = lab.registry.verify_object(cast(str, result["dataset_id"]))[-1]
    assert source_record.record["status"] == "CANDIDATE"
    assert dataset.record["physical_object_digest"] == result["raw_digest"]
    assert dataset.record["source_ids"] == [result["source_id"]]
    lineage = parse_json_document(
        lab.objects.get(cast(str, result["lineage_digest"])).path.read_bytes()
    )
    assert isinstance(lineage, dict)
    assert lineage["environment_digest"] == lab.environment_digest
    assert lineage["source_record_digest"] == source_record.digest
    assert lab.objects.get(cast(str, result["capture_digest"])).byte_size > 0


def test_failed_probe_preserves_candidate_and_sanitized_failure(tmp_path: Path) -> None:
    connections, _, lab, transport = services(tmp_path)
    connections.save("SRC-02", ALPACA)
    transport.fail = True
    result = connections.probe("SRC-02")
    assert result["status"] == "FAILED" and not result["raw_retained"]
    assert result["error_code"] == "RATE_LIMITED"
    assert (
        lab.registry.verify_object(cast(str, result["source_id"]))[-1].record["status"]
        == "CANDIDATE"
    )
    assert "dataset_id" not in result and SECRET not in json.dumps(result)


@pytest.mark.parametrize(
    "source,config",
    [
        ("SRC-02", {**ALPACA, "credential_source": "LIVE_ACCOUNT"}),
        ("SRC-02", {**ALPACA, "no_incremental_charge": False}),
        ("SRC-02", {**ALPACA, "entitlement_confirmed": False}),
        ("SRC-02", {**ALPACA, "url": "https://example.test"}),
        ("SRC-01", {**SEC, "license_confirmed": False}),
        ("SRC-01", {**SEC, "cik": "0000000000"}),
        ("SRC-01", {**SEC, "cik": "٠٠٠٠٣٢٠١٩٣"}),
        ("SRC-01", {**SEC, "contact_email": "private\r\nInjection"}),
        ("SRC-99", {}),
    ],
)
def test_bad_configuration_cannot_create_private_files(
    tmp_path: Path, source: str, config: JsonRecord
) -> None:
    connections, _, _, transport = services(tmp_path)
    with pytest.raises((VaultError, SourceError)):
        connections.save(source, config)
    assert not connections.private_root.exists() and transport.calls == 0


def test_private_path_overlap_empty_rotation_and_unsupported_values(
    tmp_path: Path,
) -> None:
    connections, _, _, _ = services(tmp_path)
    with pytest.raises(VaultError, match="OVERLAPS"):
        Connections(
            tmp_path / "application/private",
            tmp_path / "application",
            tmp_path / "runtime",
            connections.probes,
        )
    for action in (
        connections.rotate,
        lambda: connections.revoke("SRC-01"),
        lambda: connections.probe("SRC-01"),
    ):
        with pytest.raises(VaultError, match="NOT_CONFIGURED"):
            action()
    assert default_private_root(tmp_path / "runtime") != tmp_path / "runtime"
    with pytest.raises(SourceError):
        diagnostic_json(object())
    with pytest.raises(SourceError):
        diagnostic_json({1: "unsupported"})
    with pytest.raises(VaultError):
        validated_config("SRC-01", {})


def test_owner_api_only_no_plaintext_echo_and_reader_probe_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections, data, _, transport = services(tmp_path)
    monkeypatch.setattr(data, "_capacity", lambda: None)
    app = create_app(tmp_path / "runtime", ROOT, data=data, connections=connections)
    with TestClient(app) as client:
        assert client.get("/api/connections").status_code == 401
        first = client.post(
            "/api/setup",
            headers={"X-QH-Request": "1"},
            json={"username": "owner", "password": PASSWORD},
        )
        headers = {"X-QH-Request": "1", "X-CSRF-Token": first.json()["csrf"]}
        assert (
            client.post(
                "/api/connections/SRC-02",
                headers={"X-QH-Request": "1"},
                json={"values": ALPACA},
            ).status_code
            == 403
        )
        saved = client.post(
            "/api/connections/SRC-02", headers=headers, json={"values": ALPACA}
        )
        assert (
            saved.status_code == 200
            and SECRET not in saved.text
            and KEY not in saved.text
        )
        assert transport.calls == 0
        assert (
            client.post("/api/connections/rotate", headers=headers).status_code == 200
        )
        result = client.post("/api/sources/SRC-02/probe", headers=headers)
        assert result.status_code == 200 and result.json()["status"] == "SUCCEEDED"
        assert (
            client.post("/api/connections/SRC-02/revoke", headers=headers).status_code
            == 200
        )
        bad = client.post(
            "/api/connections/SRC-02",
            headers=headers,
            json={"values": {**ALPACA, "secret_key": 2}},
        )
        assert bad.status_code == 422 and SECRET not in bad.text
        for role in ("reader", "researcher"):
            assert (
                client.post(
                    "/api/users",
                    headers=headers,
                    json={"username": role, "password": PASSWORD, "role": role},
                ).status_code
                == 200
            )
        client.post("/api/logout", headers=headers)
        for role in ("reader", "researcher"):
            login = client.post(
                "/api/login",
                headers={"X-QH-Request": "1"},
                json={"username": role, "password": PASSWORD},
            )
            other = {"X-QH-Request": "1", "X-CSRF-Token": login.json()["csrf"]}
            assert client.get("/api/connections").status_code == 403
            for path in (
                "/api/connections/rotate",
                "/api/connections/SRC-02/revoke",
                "/api/sources/SRC-02/probe",
            ):
                assert client.post(path, headers=other).status_code == 403
            assert (
                client.post(
                    "/api/connections/SRC-02", headers=other, json={"values": ALPACA}
                ).status_code
                == 403
            )
            client.post("/api/logout", headers=other)
        assert transport.calls == 1
