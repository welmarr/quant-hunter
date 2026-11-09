"""Independent OHLC coordinates and exact immutable partition search checks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from test_v0_pattern_corpus import DIGEST, source
from test_v0_pattern_product import execute

from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.patterns.codec import load_checkpoint, save_checkpoint
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.patterns.corpus import Corpus, CorpusConfig, CorpusStore
from quant_hunter.patterns.product import PatternJobConfig, PatternProduct
from quant_hunter.patterns.representations import normalize
from quant_hunter.patterns.search import SearchConfig, SearchEngine
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.storage import ImmutableObjectStore


def built(tmp_path: Path) -> tuple[CorpusStore, Corpus]:
    selected, raw = source(220)
    table = pq.read_table(pa.BufferReader(raw))
    close = table["close"].to_numpy()
    for name, values in [
        ("open", close - 0.1),
        ("high", close + 0.2),
        ("low", close - 0.3),
        ("volume", np.zeros(220)),
    ]:
        table = table.append_column(name, pa.array(values))
    output = pa.BufferOutputStream()
    pq.write_table(table, output, use_dictionary=False)
    payload = output.getvalue().to_pybytes()
    selected = replace(
        selected,
        normalized_digest=sha256_bytes(payload),
        feature_columns=("close", "open", "high", "low", "volume"),
    )
    store = CorpusStore(ImmutableObjectStore(tmp_path / "objects"))
    return store, store.build(
        new_typed_id(RegistryKind.DATASET),
        selected,
        payload,
        config=CorpusConfig(block_rows=37),
    )


def test_independent_relative_coordinates_keep_opening_gap_and_ignore_declared_nonprices() -> (
    None
):
    raw = np.array(
        [[102.0, 100.0, 104.0, 99.0, 0.0], [106.0, 105.0, 108.0, 103.0, 300.0]]
    )
    expected = np.array([[0.02, 0.02, 0.01, 0], [1 / 102, 2 / 102, 2 / 102, 3 / 102]])
    np.testing.assert_allclose(normalize(raw, "RELATIVE_OHLC"), expected, atol=1e-14)
    scaled = raw.copy()
    scaled[:, :4] *= 7
    np.testing.assert_allclose(normalize(scaled, "RELATIVE_OHLC"), expected, atol=1e-14)
    np.testing.assert_array_equal(
        normalize(np.full((8, 4), 100.0), "RELATIVE_OHLC"), np.zeros((8, 4))
    )
    changed = raw.copy()
    changed[1, 1] = 104
    assert not np.array_equal(
        normalize(raw, "RELATIVE_OHLC"), normalize(changed, "RELATIVE_OHLC")
    )


@pytest.mark.parametrize(
    "values",
    [
        np.ones((8, 3)),
        np.zeros((8, 4)),
        np.tile([100.0, 101.0, 100.0, 99.0], (8, 1)),
        np.full((8, 4), np.nan),
    ],
)
def test_bad_shapes_envelopes_and_prices_refuse(values: np.ndarray) -> None:
    with pytest.raises(PatternError):
        normalize(values, "RELATIVE_OHLC")


def test_actual_partition_checkpoint_exact_distances_and_causal_outcomes(
    tmp_path: Path,
) -> None:
    store, corpus = built(tmp_path)
    query = store.window(corpus, 188, 220, 2**63 - 1)
    config = SearchConfig(
        mode="EXACT_SMALL",
        normalization="RELATIVE_OHLC",
        candidate_cap=256,
        horizon=4,
        maximum_distance=2,
    )
    engine = SearchEngine(query, config, query.available_ns)
    for i in range(3):
        engine.consume(store.partition(corpus, i))
    digest = save_checkpoint(
        store.objects,
        engine.snapshot(),
        {"corpus": corpus.manifest_digest},
        next_partition=3,
    )
    resumed, next_index = load_checkpoint(
        store.objects, digest, {"corpus": corpus.manifest_digest}
    )
    for block in store.blocks(corpus, start_partition=next_index):
        resumed.consume(block)
    actual = resumed.finish()
    assert actual.hits and actual.progress.rows == 220
    oracle = SearchEngine(query, config, query.available_ns)
    oracle.consume(store.frame(corpus, 0, 220))
    assert [(h.window.fingerprint, h.distance) for h in actual.hits] == [
        (h.window.fingerprint, h.distance) for h in oracle.finish().hits
    ]
    for hit in actual.hits:
        # Compute coordinates independently of normalize/relative_candles.
        matrices = []
        for window in (query, hit.window):
            c, o, h, low = window.values[:, :4].T
            d = np.r_[o[0], c[:-1]]
            matrices.append(
                np.column_stack(
                    (
                        (c - o) / d,
                        (h - np.maximum(c, o)) / d,
                        (np.minimum(c, o) - low) / d,
                        o / d - 1,
                    )
                )
            )
        assert hit.distance == pytest.approx(
            float(np.sqrt(np.mean((matrices[0] - matrices[1]) ** 2))), abs=1e-14
        )
        assert (
            hit.outcome is not None and hit.outcome.available_ns <= query.available_ns
        )
    with pytest.raises(PatternError, match="declared"):
        SearchEngine(
            replace(
                query,
                provenance=replace(
                    query.provenance,
                    features=("open", "close", "high", "low", "volume"),
                ),
            ),
            config,
            query.available_ns,
        )


def test_registered_product_records_exact_search_projection_and_unchanged_raw_prices(
    tmp_path: Path,
) -> None:
    store, corpus = built(tmp_path)
    query = store.window(corpus, 188, 220, 2**63 - 1)
    train = store.frame(corpus, 0, 128)
    config = PatternJobConfig(
        "PAT-13",
        188,
        220,
        0,
        128,
        query.available_ns,
        int(train.available_ns[-1]),
        query.start_ns,
        normalization="RELATIVE_OHLC",
        maximum_distance=2,
    )
    product = PatternProduct(store)
    prepared = product.prepare(
        corpus.manifest_digest,
        config,
        pattern_id=new_typed_id(RegistryKind.PATTERN),
        code_revision="a" * 40,
        environment_digest=DIGEST,
    )
    plan = prepared.to_record()
    schema = plan["method_input_schema"]
    assert isinstance(schema, dict)
    projection = schema["search_representation"]
    assert isinstance(projection, dict)
    assert projection["omitted_source_columns"] == ["volume"]
    result = execute(product, prepared)
    assert len(result["query"]["raw_values"][0]) == 5
    assert len(result["query"]["normalized_values"][0]) == 4
    assert result["exposure"]["variant_count"] == 1
    assert result["method"]["status"] == "EXECUTED"


@pytest.mark.parametrize("metric", ["EUCLIDEAN", "DTW"])
def test_relative_search_gap_delayed_receipt_and_full_cap_approximation(
    tmp_path: Path, metric: Literal["EUCLIDEAN", "DTW"]
) -> None:
    store, corpus = built(tmp_path)
    original = store.frame(corpus, 0, 220)
    closes = original.close_ns.copy()
    closes[50:] += original.step_ns
    available = closes.copy()
    available[120] = closes[-1] + original.step_ns
    frame = replace(original, close_ns=closes, available_ns=available)
    query = frame.window(188, 220, decision_ns=int(closes[-1]))
    config = SearchConfig(
        mode="EXACT_SMALL",
        normalization="RELATIVE_OHLC",
        metric=metric,
        dtw_radius=0,
        paa_segments=4,
        candidate_cap=256,
        max_results=100,
        horizon=4,
        maximum_distance=2,
    )
    expected_starts = [
        start
        for start in range(220 - 32 - 4 + 1)
        if all(
            int(closes[i + 1] - closes[i]) == frame.step_ns
            for i in range(start, start + 35)
        )
        and int(available[start : start + 36].max()) <= query.available_ns
        and int(closes[start + 31]) < query.start_ns
        and int(closes[start + 35]) <= query.start_ns
    ]
    exact = SearchEngine(query, config, query.available_ns)
    exact.consume(frame)
    full = exact.finish()
    assert full.hits and full.progress.eligible_windows == len(expected_starts)
    chunks = [
        replace(
            frame,
            values=frame.values[start : start + 37],
            close_ns=closes[start : start + 37],
            available_ns=available[start : start + 37],
        )
        for start in range(0, 220, 37)
    ]
    approximate = SearchEngine(
        query, replace(config, mode="APPROXIMATE"), query.available_ns
    )
    for chunk in chunks[:3]:
        approximate.consume(chunk)
    checkpoint = save_checkpoint(
        store.objects,
        approximate.snapshot(),
        {"corpus": corpus.manifest_digest},
        next_partition=3,
    )
    resumed, next_index = load_checkpoint(
        store.objects, checkpoint, {"corpus": corpus.manifest_digest}
    )
    for chunk in chunks[next_index:]:
        resumed.consume(chunk)
    actual = resumed.finish()
    assert actual.progress.eligible_windows == len(expected_starts)
    assert [(hit.window.fingerprint, hit.distance) for hit in actual.hits] == [
        (hit.window.fingerprint, hit.distance) for hit in full.hits
    ]
    for hit in actual.hits:
        start = int(np.flatnonzero(closes == hit.window.start_ns + frame.step_ns)[0])
        assert start in expected_starts
        assert hit.outcome is not None
        assert hit.outcome.gross_return == pytest.approx(
            frame.values[start + 35, 0] / frame.values[start + 31, 0] - 1
        )
    foreign = replace(
        chunks[0],
        provenance=replace(
            chunks[0].provenance,
            features=("close", "high", "open", "low", "volume"),
        ),
    )
    with pytest.raises(PatternError, match="aligned feature"):
        SearchEngine(query, config, query.available_ns).consume(foreign)


def test_relative_projection_does_not_silently_change_declared_family_math(
    tmp_path: Path,
) -> None:
    store, corpus = built(tmp_path)
    query = store.window(corpus, 188, 220, 2**63 - 1)
    train = store.frame(corpus, 0, 128)
    config = PatternJobConfig(
        "PAT-07",
        188,
        220,
        0,
        128,
        query.available_ns,
        int(train.available_ns[-1]),
        query.start_ns,
        normalization="RELATIVE_OHLC",
        maximum_distance=2,
        method_parameters_json='{"feature_index":0}',
    )
    product = PatternProduct(store)
    relative = product.prepare(
        corpus.manifest_digest,
        config,
        pattern_id=new_typed_id(RegistryKind.PATTERN),
        code_revision="a" * 40,
        environment_digest=DIGEST,
    )
    raw = product.prepare(
        corpus.manifest_digest,
        replace(config, normalization="RAW"),
        pattern_id=new_typed_id(RegistryKind.PATTERN),
        code_revision="a" * 40,
        environment_digest=DIGEST,
    )
    raw_schema = raw.to_record()["method_input_schema"]
    assert isinstance(raw_schema, dict) and "search_representation" not in raw_schema
    result, raw_result = execute(product, relative), execute(product, raw)
    assert result["method"] == raw_result["method"]
    assert result["method"]["status"] == "EXECUTED"
    assert result["method"]["output"]["haar_approximation"] == pytest.approx(
        float(query.values[:, 0].sum() / np.sqrt(32)), abs=1e-10
    )
    assert result["query"]["raw_values"] == raw_result["query"]["raw_values"]
    assert (
        result["query"]["normalized_values"] != raw_result["query"]["normalized_values"]
    )
