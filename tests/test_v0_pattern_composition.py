"""Multiple bounded parent uploads become one genuinely streamed corpus."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from test_v0_pattern_corpus import DIGEST, STEP, source

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.data_quality import PartitionSelection, QualityError
from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.patterns.corpus import CorpusConfig, CorpusStore
from quant_hunter.provenance.hashing import sha256_canonical_json
from quant_hunter.storage import ImmutableObjectStore


def composed(
    tmp_path: Path, *, offset: int = 92
) -> tuple[CorpusStore, PartitionSelection, list[tuple[int, Any]]]:
    store = CorpusStore(ImmutableObjectStore(tmp_path / "objects"))
    first, raw_a = source(92)
    second, raw_b = source(92, offset_minutes=offset)
    second = replace(
        second, instrument_id=first.instrument_id, calendar_digest="sha256:" + "3" * 64
    )
    profile: JsonRecord = {
        "calendar_id": "SYNTHETIC_CONTINUOUS_TEST",
        "anchor": "UTC",
        "timezone": "UTC",
        "timezone_package": "fixture",
        "package": "fixture",
        "package_version": "1",
    }
    profile_digest = sha256_canonical_json(profile)
    bounds = {"start": first.bounds["start"], "end": second.bounds["end"]}
    manifest: JsonRecord = {
        "schema_version": "qh-owned-partition-selection-v1",
        "total_rows": 184,
        "parent_snapshots": [first.to_record(), second.to_record()],
        "calendar_profile": profile,
        "calendar_profile_digest": profile_digest,
        "bounds": bounds,
    }
    digest = store.objects.publish(canonicalize_json(manifest)).digest
    selection = PartitionSelection(
        digest,
        184,
        bounds,
        (first, second),
        profile_digest,
        first.instrument_id,
        DIGEST,
        STEP,
        ("close",),
        "SYNTHETIC",
        True,
    )
    batches = [
        (index, batch)
        for index, raw in enumerate((raw_a, raw_b))
        for batch in pq.ParquetFile(pa.BufferReader(raw)).iter_batches(batch_size=13)
    ]
    return store, selection, batches


def test_multiple_parent_files_keep_each_identity_and_boundary_windows(
    tmp_path: Path,
) -> None:
    store, selection, batches = composed(tmp_path)
    built = store.build_selection(
        new_typed_id(RegistryKind.DATASET),
        selection,
        batches,
        config=CorpusConfig(block_rows=37),
    )
    assert built.row_count == 184 and len(built.partitions) == 5
    assert built.selection_manifest_digest == selection.manifest_digest
    assert built.calendar_profile_digest == selection.calendar_profile_digest
    assert built.parents == [p.to_record() for p in selection.parent_snapshots]
    assert len(store.window(built, 80, 112, 2**63 - 1).values) == 32
    assert built.gap_count == 0


def test_parent_calendar_ranges_can_differ_but_gap_cannot_be_imputed(
    tmp_path: Path,
) -> None:
    store, selection, batches = composed(tmp_path, offset=94)
    assert (
        selection.parent_snapshots[0].calendar_digest
        != selection.parent_snapshots[1].calendar_digest
    )
    built = store.build_selection(
        new_typed_id(RegistryKind.DATASET),
        selection,
        batches,
        config=CorpusConfig(block_rows=37),
    )
    assert built.gap_count == 1
    with pytest.raises(PatternError, match="missing bars"):
        store.window(built, 80, 112, 2**63 - 1)


@pytest.mark.parametrize("mutation", ["skip", "repeat", "reorder", "overlap"])
def test_parent_coverage_cannot_skip_repeat_reorder_or_overlap(
    tmp_path: Path, mutation: str
) -> None:
    store, selection, batches = composed(
        tmp_path, offset=90 if mutation == "overlap" else 92
    )
    if mutation == "skip":
        batches = batches[1:]
    elif mutation == "repeat":
        batches.insert(1, batches[0])
    elif mutation == "reorder":
        batches = list(reversed(batches))
    with pytest.raises(QualityError if mutation == "overlap" else PatternError):
        store.build_selection(
            new_typed_id(RegistryKind.DATASET),
            selection,
            batches,
            config=CorpusConfig(block_rows=37),
        )


def test_selection_cannot_substitute_parent_or_profile(tmp_path: Path) -> None:
    store, selection, batches = composed(tmp_path)
    changed = replace(selection, calendar_profile_digest=DIGEST)
    with pytest.raises(PatternError, match="MANIFEST_BINDING"):
        store.build_selection(new_typed_id(RegistryKind.DATASET), changed, batches)
