"""Real vault/API/source publication with synthetic network and file inputs."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from test_v0_connections import PASSWORD, ROOT, services
from test_v0_providers import RIGHTS
from test_v0_sources_macro import Fixture as MacroFixture
from test_v0_sources_macro import encode, fred_page
from test_v0_sources_priority import Fixture as PriorityFixture
from test_v0_sources_priority import bi5, calendar_rows, sf1_payload, sf1_row

from quant_hunter.config import JsonRecord
from quant_hunter.credentials import VaultError
from quant_hunter.sources._equity_transport import EquityResponse
from quant_hunter.sources.macro_fred import FREDKey, FREDReleaseConnector
from quant_hunter.sources.priority_common import PriorityKey
from quant_hunter.sources.priority_sharadar import SharadarConnector
from quant_hunter.sources.priority_tradingeconomics import TradingEconomicsConnector
from quant_hunter.sources.providers import ProviderService
from quant_hunter.sources.transport import SourceError
from quant_hunter.web.api import create_app
from quant_hunter.web.connections import ConfiguredConnector, configured_connector
from quant_hunter.web.state import AccessError

SOURCES = ("SRC-07", "SRC-18", "SRC-20")


def configuration(source: str) -> JsonRecord:
    return {
        "api_key": "fixture" + "0" * 25
        if source == "SRC-07"
        else "synthetic-fixture-key",
        "entitlement_confirmed": True,
        "no_incremental_charge": True,
    }


@pytest.mark.parametrize("source", SOURCES)
def test_encrypted_provider_routes_only_after_explicit_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    connections, data, lab, _ = services(tmp_path)
    monkeypatch.setattr(data, "_capacity", lambda: None)
    providers = ProviderService(connections.probes.public)
    connections.provider_service = providers
    data.source_importer = providers
    macro = json.loads(fred_page())
    macro["release"]["release_id"] = 10
    sharadar = sf1_payload()
    sf1_row(sharadar)[0] = "AAPL"
    transport = (
        MacroFixture(EquityResponse(200, encode(macro)))
        if source == "SRC-07"
        else PriorityFixture(
            EquityResponse(
                200, encode(sharadar if source == "SRC-18" else calendar_rows())
            )
        )
    )

    def factory(identity: str, values: JsonRecord) -> ConfiguredConnector:
        key = cast(str, values["api_key"])
        if identity == "SRC-07":
            assert isinstance(transport, MacroFixture)
            return FREDReleaseConnector(FREDKey(key), transport)
        assert isinstance(transport, PriorityFixture)
        if identity == "SRC-18":
            return SharadarConnector(PriorityKey(key), transport)
        return TradingEconomicsConnector(PriorityKey(key), transport)

    connections.connector_factory = factory
    owner = data.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    researcher = data.state.create_user(
        "researcher", PASSWORD, "researcher", bootstrap=False
    )
    values = configuration(source)
    connections.save(source, values)
    assert not transport.requests
    with pytest.raises(AccessError, match="Owner role"):
        data.probe(researcher, source)
    assert not transport.requests
    result = data.probe(owner, source)
    assert result["status"] == "SUCCEEDED", result
    assert result["evidence_mode"] == "RECORDED_FIXTURE"
    assert len(transport.requests) == 1
    assert data.operations(researcher) == []
    assert data.datasets(owner) == []
    assert data.operations(owner)[0]["result"] == result
    assert (
        lab.registry.verify_object(str(result["source_id"]))[-1].record["status"]
        == "CANDIDATE"
    )
    assert str(values["api_key"]) not in json.dumps(connections.status())
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert str(values["api_key"]).encode() not in path.read_bytes()
    connections.revoke(source)
    with pytest.raises(VaultError, match="NOT_CONFIGURED"):
        connections.probe(source)


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize(
    "change",
    [
        {"entitlement_confirmed": False},
        {"no_incremental_charge": False},
        {"api_key": "bad\r\nkey"},
        {"url": "https://example.test"},
    ],
)
def test_invalid_provider_settings_never_initialize_vault(
    tmp_path: Path, source: str, change: JsonRecord
) -> None:
    connections, _, _, _ = services(tmp_path)
    with pytest.raises((VaultError, SourceError)):
        connections.save(source, {**configuration(source), **change})
    assert not connections.private_root.exists()


@pytest.mark.parametrize("source", SOURCES)
def test_default_configuration_constructs_header_only_connector(source: str) -> None:
    connector = configured_connector(source, configuration(source))
    assert connector.catalogue_id == source
    assert connector.evidence_mode == "HISTORICAL_REAL"


def test_file_import_api_is_private_bounded_and_retains_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connections, data, _, _ = services(tmp_path)
    monkeypatch.setattr(data, "_capacity", lambda: None)
    data.source_importer = ProviderService(connections.probes.public)
    app = create_app(tmp_path / "runtime", ROOT, data=data, connections=connections)
    content = base64.b64encode(bi5()).decode()
    metadata = {**RIGHTS, "pair": "EURUSD", "day": "2024-01-02", "point_scale": 100000}
    payload = {"content_base64": content, "metadata": metadata}
    with TestClient(app) as client:
        setup = client.post(
            "/api/setup",
            headers={"X-QH-Request": "1"},
            json={"username": "owner", "password": PASSWORD},
        )
        headers = {"X-QH-Request": "1", "X-CSRF-Token": setup.json()["csrf"]}
        assert (
            client.post(
                "/api/sources/SRC-09/import",
                headers={"X-QH-Request": "1"},
                json=payload,
            ).status_code
            == 403
        )
        result = client.post(
            "/api/sources/SRC-09/import", headers=headers, json=payload
        )
        assert result.status_code == 201 and result.json()["quality"] == "PENDING", (
            result.text
        )
        assert result.json()["preview"][0]["available_at"] is None
        assert client.get("/api/datasets").json()["datasets"] == []
        assert (
            client.post(
                "/api/sources/SRC-09/import",
                headers=headers,
                json={**payload, "content_base64": "!"},
            ).status_code
            == 422
        )
        oversized = base64.b64encode(b"x" * 2_000_001).decode()
        assert (
            client.post(
                "/api/sources/SRC-09/import",
                headers=headers,
                json={**payload, "content_base64": oversized},
            ).status_code
            == 413
        )
        bad = client.post(
            "/api/sources/SRC-09/import",
            headers=headers,
            json={**payload, "metadata": {**metadata, "point_scale": 0}},
        )
        assert bad.status_code == 201 and bad.json()["status"] == "FAILED"
        operations = client.get("/api/data-operations").json()["operations"]
        assert (
            operations[0]["status"] == "FAILED"
            and operations[1]["status"] == "SUCCEEDED"
        )
        for role in ("reader", "researcher"):
            client.post(
                "/api/users",
                headers=headers,
                json={"username": role, "password": PASSWORD, "role": role},
            )
        client.post("/api/logout", headers=headers)
        for role in ("reader", "researcher"):
            login = client.post(
                "/api/login",
                headers={"X-QH-Request": "1"},
                json={"username": role, "password": PASSWORD},
            )
            other = {"X-QH-Request": "1", "X-CSRF-Token": login.json()["csrf"]}
            assert client.get("/api/data-operations").json()["operations"] == []
            for source in SOURCES:
                assert (
                    client.post(
                        f"/api/sources/{source}/probe", headers=other
                    ).status_code
                    == 403
                )
                assert (
                    client.post(
                        f"/api/connections/{source}",
                        headers=other,
                        json={"values": configuration(source)},
                    ).status_code
                    == 403
                )
            imported = client.post(
                "/api/sources/SRC-09/import", headers=other, json=payload
            )
            assert imported.status_code == (403 if role == "reader" else 201)
            client.post("/api/logout", headers=other)
