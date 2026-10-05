"""Reviewed provider parsers through canonical, private diagnostic publication."""

import json
from pathlib import Path
from typing import cast

import pytest
from test_v0_materialize import setup
from test_v0_sources_macro import (
    G17,
    METADATA,
    bea_payload,
    encode,
    fred_page,
    vintage_payload,
)
from test_v0_sources_macro import Fixture as MacroFixture
from test_v0_sources_priority import Fixture as PriorityFixture
from test_v0_sources_priority import bi5, calendar_rows, eod_rows, sf1_payload, sf1_row

from quant_hunter.config import JsonRecord
from quant_hunter.sources._equity_transport import EquityResponse
from quant_hunter.sources.macro_fred import FREDKey, FREDReleaseConnector
from quant_hunter.sources.macro_g17 import G17Connector
from quant_hunter.sources.priority_common import PriorityKey
from quant_hunter.sources.priority_sharadar import SharadarConnector
from quant_hunter.sources.priority_tradingeconomics import TradingEconomicsConnector
from quant_hunter.sources.providers import ProviderConnector, ProviderService
from quant_hunter.sources.transport import SourceError

RIGHTS: JsonRecord = {
    "declared_license": "Synthetic fixture, no provider rights claimed",
    "license_confirmed": True,
}


@pytest.mark.parametrize("source", ["SRC-06", "SRC-07", "SRC-18", "SRC-20"])
def test_actual_adapter_to_immutable_probe_graph(tmp_path: Path, source: str) -> None:
    materializer, lab = setup(tmp_path)
    service = ProviderService(materializer.public)
    client: ProviderConnector
    if source == "SRC-06":
        payload = G17.replace(b"2024", b"2025").replace(b"2023", b"2024")
        client = G17Connector(MacroFixture(EquityResponse(200, payload)))
        expected_count = 6
    elif source == "SRC-07":
        document = json.loads(fred_page())
        document["release"]["release_id"] = 10
        payload = encode(document)
        client = FREDReleaseConnector(
            FREDKey("fixture" + "0" * 25), MacroFixture(EquityResponse(200, payload))
        )
        expected_count = 1
    elif source == "SRC-18":
        document = sf1_payload()
        sf1_row(document)[0] = "AAPL"
        payload = encode(document)
        client = SharadarConnector(
            PriorityKey("synthetic-test-key"),
            PriorityFixture(EquityResponse(200, payload)),
        )
        expected_count = 1
    else:
        payload = encode(calendar_rows())
        client = TradingEconomicsConnector(
            PriorityKey("synthetic-test-key"),
            PriorityFixture(EquityResponse(200, payload)),
        )
        expected_count = 1
    result = service.probe(source, client)
    assert result["status"] == "SUCCEEDED", result
    assert result["record_count"] == expected_count
    assert result["evidence_mode"] == "RECORDED_FIXTURE"
    assert lab.objects.get(str(result["raw_digest"])).path.read_bytes() == payload
    assert result["quality"] == "PENDING" and result["source_status"] == "CANDIDATE"
    preview = cast(list[JsonRecord], result["preview"])
    assert preview[0]["available_at"] is None


@pytest.mark.parametrize("source", ["SRC-05", "SRC-07", "SRC-09", "SRC-19"])
def test_owner_file_inputs_keep_original_bytes_and_temporal_uncertainty(
    tmp_path: Path, source: str
) -> None:
    materializer, lab = setup(tmp_path)
    service = ProviderService(materializer.public)
    metadata: JsonRecord = dict(RIGHTS)
    extra = None
    if source == "SRC-05":
        payload = encode(bea_payload())
        metadata.update(
            table="T10101",
            series_id="A191RL",
            unit="Percent change, annual rate",
            unit_multiplier=0,
            start="2023-01-01",
            end="2023-12-31",
            vintage=None,
        )
    elif source == "SRC-07":
        payload, extra = encode(vintage_payload()), METADATA
        metadata.update(
            series_id="TEST",
            unit="Index",
            start="2023-01-01",
            end="2023-12-31",
            realtime_start="2024-01-01",
            realtime_end="2024-12-31",
        )
    elif source == "SRC-09":
        payload = bi5()
        metadata.update(pair="EURUSD", day="2024-01-02", point_scale=100000)
    else:
        payload = encode(eod_rows())
        metadata.update(
            symbol="FIXTURE_old.US",
            currency="USD",
            start="2024-01-01",
            end="2024-01-31",
            listing_status="DELISTED",
        )
    result = service.import_file(source, payload, metadata, series_metadata=extra)
    assert result["status"] == "SUCCEEDED", result
    assert (
        result["evidence_mode"] == "OWNER_SUPPLIED" and result["quality"] == "PENDING"
    )
    assert lab.objects.get(str(result["raw_digest"])).path.read_bytes() == payload
    preview = cast(list[JsonRecord], result["preview"])
    assert preview[0]["available_at"] is None
    if source == "SRC-09":
        assert (
            preview[0]["bid"] == "1.1" and preview[0]["ask_volume_millions"] == "1.25"
        )
    if extra is not None:
        datasets = cast(list[JsonRecord], result["datasets"])
        assert len(datasets) == 2
        assert (
            lab.objects.get(str(datasets[1]["raw_digest"])).path.read_bytes() == extra
        )


@pytest.mark.parametrize(
    "metadata",
    [{}, {**RIGHTS, "license_confirmed": False}, {**RIGHTS, "unexpected": "x"}],
)
def test_import_declarations_are_required_before_source_allocation(
    tmp_path: Path, metadata: JsonRecord
) -> None:
    materializer, lab = setup(tmp_path)
    with pytest.raises(SourceError):
        ProviderService(materializer.public).import_file("SRC-19", b"[]", metadata)
    assert not lab.registry.verify_all()


def test_configured_provider_never_falls_back_to_public_client(tmp_path: Path) -> None:
    materializer, lab = setup(tmp_path)
    with pytest.raises(SourceError, match="CONFIGURATION_REQUIRED"):
        ProviderService(materializer.public).probe("SRC-07")
    assert not lab.registry.verify_all()
