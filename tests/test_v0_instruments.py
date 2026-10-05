"""Permanent registry identity, immutable corrections and knowledge-time selection."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.identity import (
    RegistryKind,
    RegistryStore,
    StaleWriterError,
    new_typed_id,
)
from quant_hunter.markets import MarketError
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.web.api import create_app

ROOT = Path(__file__).resolve().parents[1]


def payload() -> JsonRecord:
    document = json.loads(
        (ROOT / "tests/fixtures/schemas/valid_objects.json").read_text()
    )["instrument.schema.json"]
    instrument = document["instrument"]
    del instrument["instrument_id"]
    return {
        "instrument": instrument,
        "reason": "Synthetic metadata contract test",
        "evidence_mode": "SYNTHETIC",
        "source_reference": "test-fixture",
    }


def service(tmp_path: Path) -> InstrumentRegistry:
    return InstrumentRegistry(
        RegistryStore.governed(tmp_path / "registry", ROOT / "schemas/v1"),
        clock=lambda: datetime(2024, 1, 2, tzinfo=UTC),
    )


def test_identity_immutable_ticker_revision_and_historical_knowledge(
    tmp_path: Path,
) -> None:
    instruments = service(tmp_path)
    created = instruments.create(payload())
    first = cast(JsonRecord, created["record"])
    identity = cast(str, first["instrument_id"])
    assert identity.startswith("INSTRUMENT-")
    assert cast(JsonRecord, first["instrument"])["instrument_id"] == identity
    original_bytes = instruments.store.verify_object(identity)[0].path.read_bytes()
    corrected = payload()
    cast(JsonRecord, corrected["instrument"])["symbols"] = [
        {
            "symbol": "TEST",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-02-01T00:00:00Z",
        },
        {"symbol": "NEW", "start": "2024-02-01T00:00:00Z", "end": None},
    ]
    instruments.clock = lambda: datetime(2024, 2, 2, tzinfo=UTC)
    changed = instruments.update(identity, cast(str, created["digest"]), corrected)
    assert changed["revision_count"] == 2 and changed["digest"] != created["digest"]
    assert (
        instruments.store.verify_object(identity)[0].path.read_bytes() == original_bytes
    )
    early = instruments.as_of(
        identity, datetime(2024, 1, 15, tzinfo=UTC), datetime(2024, 2, 3, tzinfo=UTC)
    )
    later = instruments.as_of(
        identity, datetime(2024, 2, 3, tzinfo=UTC), datetime(2024, 2, 3, tzinfo=UTC)
    )
    assert early["symbol"] == "TEST" and later["symbol"] == "NEW"
    assert early["registry_digest"] == created["digest"]
    assert instruments.list() == [changed]
    assert instruments.list(offset=1) == []
    with pytest.raises(MarketError, match="known"):
        instruments.as_of(
            identity, datetime(2023, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)
        )
    instruments.clock = lambda: datetime(2024, 3, 2, tzinfo=UTC)
    with pytest.raises(StaleWriterError):
        instruments.update(identity, cast(str, created["digest"]), corrected)
    assert len(instruments.store.verify_object(identity)) == 2


@pytest.mark.parametrize(
    "case", ["id", "knowledge", "zero_tick", "cross_currency", "unknown_key"]
)
def test_metadata_failures_do_not_publish_a_registry_record(
    tmp_path: Path, case: str
) -> None:
    instruments = service(tmp_path)
    data = payload()
    metadata = cast(JsonRecord, data["instrument"])
    if case == "id":
        metadata["instrument_id"] = new_typed_id(RegistryKind.INSTRUMENT)
    elif case == "knowledge":
        data["recorded_at"] = "1990-01-01T00:00:00Z"
    elif case == "zero_tick":
        metadata["tick_size"] = "0"
    elif case == "cross_currency":
        metadata["base_currency"] = "EUR"
    else:
        metadata["unknown"] = "unreviewed"
    with pytest.raises(MarketError):
        instruments.create(data)
    assert not list(tmp_path.rglob("v*.json"))


def test_valid_hash_cannot_hide_nested_identity_or_time_contradiction(
    tmp_path: Path,
) -> None:
    instruments = service(tmp_path)
    created = instruments.create(payload())
    identity = cast(str, cast(JsonRecord, created["record"])["instrument_id"])
    revision = instruments.store.verify_object(identity)[0]
    malicious = deepcopy(revision.record)
    cast(JsonRecord, malicious["instrument"])["instrument_id"] = new_typed_id(
        RegistryKind.INSTRUMENT
    )
    revision.path.write_bytes(canonicalize_json(malicious))
    with pytest.raises(MarketError, match="identities"):
        instruments.get(identity)


def test_revision_time_order_asset_identity_and_page_limits(tmp_path: Path) -> None:
    instruments = service(tmp_path)
    assert instruments.list() == []
    first = instruments.create(payload())
    identity = cast(str, cast(JsonRecord, first["record"])["instrument_id"])
    with pytest.raises(MarketError, match="knowledge-time"):
        instruments.update(identity, cast(str, first["digest"]), payload())
    altered = payload()
    cast(JsonRecord, altered["instrument"])["asset_class"] = "ETF"
    instruments.clock = lambda: datetime(2024, 2, 1, tzinfo=UTC)
    with pytest.raises(MarketError, match="identity"):
        instruments.update(identity, cast(str, first["digest"]), altered)
    for value in (-1, 0, 51, True):
        with pytest.raises(MarketError):
            instruments.list(limit=value)
    with pytest.raises(MarketError):
        instruments.list(offset=1001)


def test_stable_identity_cannot_change_economic_fx_pair(tmp_path: Path) -> None:
    instruments = service(tmp_path)
    original = payload()
    metadata = cast(JsonRecord, original["instrument"])
    metadata.update(
        asset_class="FX_SPOT",
        venue="OTC_NY_17_CONVENTION",
        base_currency="EUR",
        calendar_id="FX_NY_17",
    )
    metadata["symbols"] = [
        {"symbol": "EUR/USD", "start": "2024-01-01T00:00:00Z", "end": None}
    ]
    first = instruments.create(original)
    identity = cast(str, cast(JsonRecord, first["record"])["instrument_id"])
    instruments.clock = lambda: datetime(2024, 2, 1, tzinfo=UTC)
    changed = deepcopy(original)
    cast(JsonRecord, changed["instrument"])["base_currency"] = "GBP"
    cast(JsonRecord, changed["instrument"])["symbols"] = [
        {"symbol": "GBP/USD", "start": "2024-01-01T00:00:00Z", "end": None}
    ]
    with pytest.raises(MarketError, match="identity"):
        instruments.update(identity, cast(str, first["digest"]), changed)
    assert len(instruments.store.verify_object(identity)) == 1


def test_instrument_api_calendar_oracle_roles_and_revision_conflict(
    tmp_path: Path,
) -> None:
    instruments = service(tmp_path)
    app = create_app(tmp_path / "runtime", ROOT, instruments=instruments)
    password = "synthetic-instrument-test-password"  # noqa: S105
    with TestClient(app) as client:
        assert client.get("/api/instruments").status_code == 401
        created = client.post(
            "/api/setup",
            headers={"X-QH-Request": "1"},
            json={"username": "owner", "password": password},
        )
        headers = {"X-QH-Request": "1", "X-CSRF-Token": created.json()["csrf"]}
        initial = client.post("/api/instruments", headers=headers, json=payload())
        assert initial.status_code == 201
        identity = initial.json()["record"]["instrument_id"]
        assert (
            client.get("/api/instruments").json()["instruments"][0]["digest"]
            == initial.json()["digest"]
        )
        assert client.get(f"/api/instruments/{identity}").status_code == 200
        assert client.get("/api/instruments/invalid").status_code == 422
        schedule = client.get(
            "/api/calendars/XNYS", params={"start": "2025-11-27", "end": "2025-11-28"}
        )
        assert schedule.status_code == 200
        sessions = schedule.json()["schedule"]["sessions"]
        assert len(sessions) == 1 and sessions[0]["label"] == "2025-11-28"
        assert datetime.fromisoformat(sessions[0]["close_at"]) == datetime(
            2025, 11, 28, 18, tzinfo=UTC
        )
        assert (
            client.get(
                "/api/calendars/XNYS",
                params={"start": "1990-01-01", "end": "2025-01-01"},
            ).status_code
            == 422
        )
        query = client.get(
            f"/api/instruments/{identity}/as-of",
            params={
                "knowledge_time": "2024-01-03T00:00:00Z",
                "effective_time": "2024-01-03T00:00:00Z",
            },
        )
        assert query.status_code == 200 and query.json()["symbol"] == "TEST"
        instruments.clock = lambda: datetime(2024, 2, 1, tzinfo=UTC)
        update = {**payload(), "expected_digest": initial.json()["digest"]}
        assert (
            client.post(
                f"/api/instruments/{identity}", headers=headers, json=update
            ).status_code
            == 200
        )
        instruments.clock = lambda: datetime(2024, 3, 1, tzinfo=UTC)
        assert (
            client.post(
                f"/api/instruments/{identity}", headers=headers, json=update
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/users",
                headers=headers,
                json={"username": "reader", "password": password, "role": "reader"},
            ).status_code
            == 200
        )
        client.post("/api/logout", headers=headers)
        reader = client.post(
            "/api/login",
            headers={"X-QH-Request": "1"},
            json={"username": "reader", "password": password},
        )
        other = {"X-QH-Request": "1", "X-CSRF-Token": reader.json()["csrf"]}
        assert client.get("/api/instruments").status_code == 200
        assert (
            client.post("/api/instruments", headers=other, json=payload()).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/instruments/{identity}", headers=other, json=update
            ).status_code
            == 403
        )
