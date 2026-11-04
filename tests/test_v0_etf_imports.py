"""Cash ETF imports retain their actual governed asset class and quality gates."""

from copy import deepcopy
from typing import Any, cast

import pytest
from test_v0_quality_workflows import Harness

from quant_hunter.config import JsonRecord
from quant_hunter.imports.validation import ImportValidationError, metadata_document

pytest_plugins = ("test_v0_quality_workflows",)


def etf_body(h: Harness) -> dict[str, Any]:
    source = h.access.service.registry.verify_object(h.instrument_id)[-1].record
    instrument = deepcopy(cast(JsonRecord, source["instrument"]))
    instrument.pop("instrument_id")
    instrument["asset_class"] = "ETF"
    registered = h.access.instruments.create(
        {
            "instrument": instrument,
            "reason": "Synthetic cash ETF integration oracle",
            "evidence_mode": "SYNTHETIC",
            "source_reference": "SELF_GENERATED_TEST_ONLY",
        }
    )
    body = h.body()
    body["instrument_id"] = cast(JsonRecord, registered["record"])["instrument_id"]
    body["instrument_revision_digest"] = registered["digest"]
    body["metadata"]["instrument"]["asset_class"] = "ETF"
    return body


def test_actual_etf_upload_keeps_exact_registry_identity_and_raw_bytes(
    h: Harness,
) -> None:
    body = etf_body(h)
    response = h.client.post("/api/quality/datasets", json=body)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["row_count"] == 5 and row["causal_eligible"] is True
    assert row["empirically_validated"] is False
    assert row["instrument_id"] == body["instrument_id"]
    assert row["metadata"]["instrument"]["asset_class"] == "ETF"
    import base64

    assert h.access.service.objects.read_bytes(row["raw_digest"]) == base64.b64decode(
        body["content_base64"]
    )
    assert h.client.get("/api/quality/datasets/" + row["dataset_id"]).status_code == 200


def test_etf_cannot_silently_be_relabelled_equity(h: Harness) -> None:
    body = etf_body(h)
    body["metadata"]["instrument"]["asset_class"] = "EQUITY"
    assert h.client.post("/api/quality/datasets", json=body).status_code == 400


@pytest.mark.parametrize("change", [{"base_currency": "EUR"}, {"symbol": "EUR/USD"}])
def test_cash_etf_import_rejects_fx_currency_or_symbol_semantics(
    change: JsonRecord,
) -> None:
    value: JsonRecord = {
        "source_name": "Synthetic ETF",
        "declared_license": "Generated oracle",
        "evidence_mode": "SYNTHETIC",
        "instrument": {
            "asset_class": "ETF",
            "symbol": "SYNTH_ETF",
            "base_currency": "USD",
            "quote_currency": "USD",
            **change,
        },
    }
    with pytest.raises(ImportValidationError):
        metadata_document(value)
