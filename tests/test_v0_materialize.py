"""Canonical raw graph, candidate-first acquisition and bounded failure retention."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from quant_hunter.config import JsonRecord, parse_json_document
from quant_hunter.lab import LabService
from quant_hunter.sources.macro_common import raw_page
from quant_hunter.sources.materialize import DiagnosticBatch, DiagnosticMaterializer
from quant_hunter.sources.probes import SourceProbeService
from quant_hunter.sources.transport import SourceError

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2025, 2, 1, tzinfo=UTC)


def setup(tmp_path: Path) -> tuple[DiagnosticMaterializer, LabService]:
    lab = LabService(
        tmp_path / "research",
        ROOT / "schemas/v1",
        "a" * 40,
        {"purpose": "synthetic source graph test"},
    )
    public = SourceProbeService(
        lab.registry, lab.objects, ROOT / "schemas/v1", "a" * 40, lab.environment_digest
    )
    return DiagnosticMaterializer(public), lab


def batch(pages: int = 1) -> DiagnosticBatch:
    return DiagnosticBatch(
        "SRC-06",
        tuple(
            raw_page(f'{{"synthetic_page":{i}}}'.encode(), STAMP) for i in range(pages)
        ),
        1,
        ({"value": "123.4"},),
        "RECORDED_FIXTURE",
        "synthetic-test-v1",
        ("Synthetic bytes only",),
    )


def test_candidate_precedes_fetch_and_every_raw_page_has_its_own_identity(
    tmp_path: Path,
) -> None:
    materializer, lab = setup(tmp_path)
    expected = batch(2)

    def fetch() -> DiagnosticBatch:
        sources = {
            key: value
            for key, value in lab.registry.verify_all().items()
            if key.startswith("SOURCE-")
        }
        assert len(sources) == 1
        assert next(iter(sources.values()))[-1].record["status"] == "CANDIDATE"
        return expected

    result = materializer.run(
        "SRC-06",
        configuration={"release_date": "2025-01-17"},
        start=STAMP,
        end=END,
        endpoint="https://www.federalreserve.gov/releases/g17/",
        evidence_mode="RECORDED_FIXTURE",
        fetch=fetch,
    )
    assert result["status"] == "SUCCEEDED" and result["quality"] == "PENDING"
    datasets = cast(list[JsonRecord], result["datasets"])
    assert len(datasets) == 2 and datasets[0]["dataset_id"] != datasets[1]["dataset_id"]
    for descriptor, page in zip(datasets, expected.pages, strict=True):
        record = lab.registry.verify_object(str(descriptor["dataset_id"]))[-1].record
        assert record["physical_object_digest"] == page.digest
        assert lab.objects.get(page.digest).path.read_bytes() == page.raw
        lineage = cast(
            JsonRecord,
            parse_json_document(
                lab.objects.get(str(descriptor["lineage_digest"])).path.read_bytes()
            ),
        )
        assert lineage["all_raw_digests"] == [p.digest for p in expected.pages]
        assert (
            lineage["diagnostic_summary_digest"] == result["diagnostic_summary_digest"]
        )
    assert result["dataset_id"] == datasets[0]["dataset_id"]


@pytest.mark.parametrize(
    "bad",
    [
        replace(batch(), catalogue_id="SRC-07"),
        replace(batch(), evidence_mode="HISTORICAL_REAL"),
        replace(batch(), pages=()),
        batch(3),
        replace(batch(), record_count=-1),
        replace(batch(), record_count=True),
        replace(batch(), preview=(cast(JsonRecord, {"v": "x"}),) * 11, record_count=11),
        replace(batch(), preview=({"v": "x" * 100_001},)),
        replace(
            batch(), pages=(replace(batch().pages[0], digest="sha256:" + "f" * 64),)
        ),
        replace(
            batch(),
            pages=(
                replace(
                    batch().pages[0], retrieved_at=datetime(2099, 1, 1, tzinfo=UTC)
                ),
            ),
        ),
    ],
)
def test_bad_adapter_output_retains_a_failed_candidate_without_a_dataset(
    tmp_path: Path, bad: DiagnosticBatch
) -> None:
    materializer, lab = setup(tmp_path)
    result = materializer.run(
        "SRC-06",
        configuration={},
        start=STAMP,
        end=END,
        endpoint="https://www.federalreserve.gov/releases/g17/",
        evidence_mode="RECORDED_FIXTURE",
        fetch=lambda: bad,
    )
    assert result["status"] == "FAILED" and result["raw_retained"] is False
    assert lab.objects.get(str(result["capture_digest"]))
    assert not any(key.startswith("DATASET-") for key in lab.registry.verify_all())


def test_provider_error_is_retained_without_response_text(tmp_path: Path) -> None:
    materializer, lab = setup(tmp_path)

    def fail() -> DiagnosticBatch:
        raise SourceError("TIMEOUT")

    result = materializer.run(
        "SRC-06",
        configuration={},
        start=STAMP,
        end=END,
        endpoint="https://www.federalreserve.gov/releases/g17/",
        evidence_mode="RECORDED_FIXTURE",
        fetch=fail,
    )
    assert result["error_code"] == "TIMEOUT"
    assert (
        lab.registry.verify_object(str(result["source_id"]))[-1].record["status"]
        == "CANDIDATE"
    )
