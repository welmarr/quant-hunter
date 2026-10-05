"""Actual Parquet partitions and immutable restart evidence, synthetic inputs."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.config.canonical import parse_json_document
from quant_hunter.data_quality import SelectedSnapshot
from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.patterns.codec import load_checkpoint, save_checkpoint
from quant_hunter.patterns.contracts import (
    CausalFrame,
    PatternError,
    SearchCancelledError,
)
from quant_hunter.patterns.corpus import Corpus, CorpusConfig, CorpusStore
from quant_hunter.patterns.search import SearchConfig, SearchEngine
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.storage import ImmutableObjectStore

ORIGIN = datetime(2024, 1, 2, tzinfo=UTC)
STEP = 60_000_000_000
DIGEST = "sha256:" + "1" * 64


def source(
    rows: int = 220, *, gap: int | None = None, offset_minutes: int = 0
) -> tuple[SelectedSnapshot, bytes]:
    prices = 100 + np.sin(np.arange(rows) / 5) + np.arange(rows) / 1000
    times = [
        ORIGIN
        + timedelta(
            minutes=index + 1 + offset_minutes + int(gap is not None and index >= gap)
        )
        for index in range(rows)
    ]
    table = pa.table(
        {
            "close_at": pa.array(times, type=pa.timestamp("us", tz="UTC")),
            "available_at": pa.array(times, type=pa.timestamp("us", tz="UTC")),
            "close": prices,
        }
    )
    output = pa.BufferOutputStream()
    pq.write_table(table, output, use_dictionary=False)
    raw = output.getvalue().to_pybytes()
    selected = SelectedSnapshot(
        new_typed_id(RegistryKind.DATASET),
        DIGEST,
        sha256_bytes(raw),
        DIGEST,
        new_typed_id(RegistryKind.INSTRUMENT),
        DIGEST,
        DIGEST,
        rows,
        {
            "start": (ORIGIN + timedelta(minutes=offset_minutes))
            .isoformat()
            .replace("+00:00", "Z"),
            "end": times[-1].isoformat().replace("+00:00", "Z"),
        },
        STEP,
        ("close",),
        "SYNTHETIC",
        "SYNTHETIC_SOFTWARE_ONLY",
        True,
        (),
    )
    return selected, raw


def corpus(tmp_path: Path, *, gap: int | None = None) -> tuple[CorpusStore, Corpus]:
    store = CorpusStore(ImmutableObjectStore(tmp_path / "objects"))
    selected, raw = source(gap=gap)
    built = store.build(
        new_typed_id(RegistryKind.DATASET),
        selected,
        raw,
        config=CorpusConfig(block_rows=37),
    )
    return store, built


def test_real_partition_index_roundtrip_and_window_crosses_files(
    tmp_path: Path,
) -> None:
    store, built = corpus(tmp_path)
    assert built.row_count == 220 and len(built.partitions) == 6
    assert built.gap_count == 0
    assert sum(part.byte_size for part in built.partitions) == built.parquet_bytes
    assert store.load(built.manifest_digest) == built
    window = store.window(built, 30, 62, 2**63 - 1)
    assert len(window.values) == 32
    np.testing.assert_allclose(
        window.values[:, 0],
        100 + np.sin(np.arange(30, 62) / 5) + np.arange(30, 62) / 1000,
    )
    assert window.provenance.dataset_version == built.manifest_digest


def test_persistent_checkpoint_resume_equals_single_frame_oracle(
    tmp_path: Path,
) -> None:
    store, built = corpus(tmp_path)
    query = store.window(built, 188, 220, 2**63 - 1)
    config = SearchConfig(
        mode="EXACT_SMALL", candidate_cap=256, horizon=4, maximum_distance=5
    )
    engine = SearchEngine(query, config, query.available_ns)
    binding: JsonRecord = {
        "experiment_id": new_typed_id(RegistryKind.EXPERIMENT),
        "corpus": built.manifest_digest,
        "seed": 7,
        "configuration": DIGEST,
    }
    for index in range(3):
        engine.consume(store.partition(built, index))
    digest = save_checkpoint(
        store.objects, engine.snapshot(), binding, next_partition=3
    )
    resumed, next_index = load_checkpoint(store.objects, digest, binding)
    for block in store.blocks(built, start_partition=next_index):
        resumed.consume(block)
    oracle = SearchEngine(query, config, query.available_ns)
    oracle.consume(store.frame(built, 0, built.row_count))
    expected, actual = oracle.finish(), resumed.finish()
    assert actual.progress.eligible_windows == expected.progress.eligible_windows
    assert actual.progress.windows_considered == expected.progress.windows_considered
    assert [(h.window.start_ns, h.distance, h.outcome) for h in actual.hits] == [
        (h.window.start_ns, h.distance, h.outcome) for h in expected.hits
    ]
    assert actual.progress.rows == 220 and actual.progress.blocks == 6
    with pytest.raises(PatternError, match="FROZEN_BINDING"):
        load_checkpoint(store.objects, digest, {**binding, "seed": 8})


def test_gap_preserved_and_no_match_crosses_missing_bar(tmp_path: Path) -> None:
    store, built = corpus(tmp_path, gap=39)
    assert built.gap_count == 1
    with pytest.raises(PatternError, match="missing bars"):
        store.window(built, 30, 62, 2**63 - 1)
    query = store.window(built, 188, 220, 2**63 - 1)
    engine = SearchEngine(
        query,
        SearchConfig(candidate_cap=256, horizon=4, maximum_distance=5),
        query.available_ns,
    )
    for block in store.blocks(built):
        engine.consume(block)
    assert engine.finish().progress.eligible_windows < 188 - 32 - 4 + 1


def test_corpus_rejects_binding_and_resource_changes_before_completion(
    tmp_path: Path,
) -> None:
    store = CorpusStore(ImmutableObjectStore(tmp_path / "objects"))
    selected, raw = source()
    identity = new_typed_id(RegistryKind.DATASET)
    with pytest.raises(PatternError, match="DIGEST_MISMATCH"):
        store.build(identity, selected, raw + b"mutated")
    blocked = replace(
        selected,
        evidence_mode="HISTORICAL",
        admission="HISTORICAL_EXPLORATORY",
        causal_eligible=False,
    )
    with pytest.raises(PatternError, match="ADMISSION_REQUIRED"):
        store.build(identity, blocked, raw)
    with pytest.raises(PatternError, match="ROW_LIMIT"):
        store.build(identity, selected, raw, config=CorpusConfig(max_rows=100))
    with pytest.raises(SearchCancelledError):
        store.build(identity, selected, raw, cancelled=lambda: True)
    with pytest.raises(PatternError, match="PARTITION_LIMIT"):
        store.build(
            identity, selected, raw, config=CorpusConfig(block_rows=37, max_shards=1)
        )


def test_manifest_index_corruption_is_not_silently_trusted(tmp_path: Path) -> None:
    store, built = corpus(tmp_path)
    value = cast(
        dict[str, Any],
        parse_json_document(store.objects.read_bytes(built.manifest_digest)),
    )
    value["partitions"][1]["start_row"] += 1
    bad = store.objects.publish(canonicalize_json(value))
    with pytest.raises(PatternError, match="PARTITION_INDEX"):
        store.load(bad.digest)


def test_streaming_source_cannot_skip_or_duplicate_rows(tmp_path: Path) -> None:
    store, built = corpus(tmp_path)
    selected, _ = source(74)
    first = store.partition(built, 0)
    from quant_hunter.patterns.contracts import Provenance

    proof = Provenance(
        selected.dataset_id,
        selected.normalized_digest,
        selected.instrument_id,
        f"{STEP}ns",
        ("close",),
    )
    frame = CausalFrame(first.values, first.close_ns, first.available_ns, STEP, proof)
    with pytest.raises(PatternError, match="REORDER_OR_DUPLICATION"):
        store.build_frames(
            new_typed_id(RegistryKind.DATASET),
            selected,
            (frame, frame),
            config=CorpusConfig(block_rows=37),
        )
    with pytest.raises(PatternError, match="INCOMPLETE_SOURCE"):
        store.build_frames(
            new_typed_id(RegistryKind.DATASET),
            selected,
            (frame,),
            config=CorpusConfig(block_rows=37),
        )
