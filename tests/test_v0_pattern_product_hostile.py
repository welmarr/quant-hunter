"""Hostile serialized checkpoints, metadata and frozen-query bounds."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from test_v0_pattern_corpus import DIGEST, corpus, source
from test_v0_pattern_product import EXPERIMENT_ID, execute, setup

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.config.canonical import parse_json_document
from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.patterns import codec
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.patterns.corpus import CorpusConfig
from quant_hunter.patterns.product import FrozenPatternBinding
from quant_hunter.patterns.search import SearchConfig, SearchEngine


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"unknown": True},
        {"integer": "-00"},
        {"integer": "9" * 20},
        {"integer": "9223372036854775808"},
        {"tuple": False},
        {"tuple": [0] * 4097},
        {"array": "object", "shape": [1], "values": [1]},
        {"array": "int64", "shape": [1], "values": [1.0]},
        {"array": "float64", "shape": [1], "values": [True]},
        {"array": "float64", "shape": [2], "values": [1]},
        {"type": "Path", "fields": {}},
        {"type": "SearchProgress", "fields": {}},
    ],
)
def test_closed_checkpoint_decoder_refuses_ambiguous_or_executable_shapes(
    payload: Any,
) -> None:
    with pytest.raises(PatternError):
        codec._decode(payload)


def test_checkpoint_encoder_refuses_arbitrary_objects_and_array_types() -> None:
    for value in (
        b"unsafe",
        Path("opaque"),
        np.ones(3, dtype=np.float32),
        np.ones((1, 1, 1)),
    ):
        with pytest.raises(PatternError):
            codec._encode(value)
    nested: Any = 1
    for _ in range(18):
        nested = {"tuple": [nested]}
    with pytest.raises(PatternError, match="NESTING"):
        codec._decode(nested)
    assert (
        codec._decode(codec._encode(-1_700_000_000_000_000_000))
        == -1_700_000_000_000_000_000
    )


def test_checkpoint_disk_chain_is_bound_and_budgeted(tmp_path: Path) -> None:
    store, built = corpus(tmp_path)
    query = store.window(built, 188, 220, 2**63 - 1)
    engine = SearchEngine(query, SearchConfig(candidate_cap=256), query.available_ns)
    binding: JsonRecord = {"configuration": DIGEST}
    engine.consume(store.partition(built, 0))
    for arguments in (
        {"next_partition": 2},
        {"next_partition": 1, "remaining_bytes": 0},
        {"next_partition": 1, "previous_total_bytes": -1},
    ):
        with pytest.raises(PatternError):
            codec.save_checkpoint(
                store.objects,
                engine.snapshot(),
                binding,
                **cast(dict[str, Any], arguments),
            )
    first = codec.save_checkpoint(
        store.objects, engine.snapshot(), binding, next_partition=1
    )
    first_size = store.objects.get(first).byte_size
    engine.consume(store.partition(built, 1))
    second = codec.save_checkpoint(
        store.objects,
        engine.snapshot(),
        binding,
        next_partition=2,
        previous_digest=first,
        previous_total_bytes=first_size,
    )
    total = first_size + store.objects.get(second).byte_size
    assert (
        codec.checkpoint_disk_bytes(store.objects, second, binding, limit=total)
        == total
    )
    with pytest.raises(PatternError, match="DISK_BUDGET"):
        codec.checkpoint_disk_bytes(store.objects, second, binding, limit=total - 1)
    original = cast(
        dict[str, Any], parse_json_document(store.objects.read_bytes(second))
    )
    for key, value in (
        ("previous_total_bytes", first_size + 1),
        ("previous_digest", False),
        ("binding", {}),
    ):
        damaged = {**original, key: value}
        altered = store.objects.publish(canonicalize_json(damaged)).digest
        with pytest.raises(PatternError):
            codec.checkpoint_disk_bytes(
                store.objects, altered, binding, limit=10_000_000
            )
    altered = store.objects.publish(
        canonicalize_json({**original, "next_partition": 1})
    ).digest
    with pytest.raises(PatternError, match="PARTITION_COUNTER"):
        codec.load_checkpoint(store.objects, altered, binding)


def test_corrupt_manifest_counters_and_shard_gap_index_fail_closed(
    tmp_path: Path,
) -> None:
    store, built = corpus(tmp_path, gap=39)
    manifest = cast(
        dict[str, Any],
        parse_json_document(store.objects.read_bytes(built.manifest_digest)),
    )
    change: dict[str, Any]
    for change in (
        {"format": "newer"},
        {"partitions": []},
        {"row_count": 219},
        {"parent_snapshots": []},
        {"parent_snapshots": manifest["parent_snapshots"] * 2},
        {"selection_manifest_digest": DIGEST, "calendar_profile_digest": None},
    ):
        with pytest.raises(ValueError):
            store.load(
                store.objects.publish(canonicalize_json({**manifest, **change})).digest
            )
    manifest["gap_count"] = 0
    for part in manifest["partitions"]:
        part["gaps"] = 0
    substituted = store.load(store.objects.publish(canonicalize_json(manifest)).digest)
    with pytest.raises(PatternError, match="GAP_INDEX"):
        store.partition(substituted, 1)


def test_source_limits_nulls_schema_and_profile_are_not_silently_coerced(
    tmp_path: Path,
) -> None:
    import pyarrow as pa  # type: ignore[import-untyped]
    import pyarrow.parquet as pq  # type: ignore[import-untyped]

    from quant_hunter.provenance.hashing import sha256_bytes

    store, _ = corpus(tmp_path)
    selected, raw = source()
    frame = pq.read_table(pa.BufferReader(raw))
    for name, values in (
        ("close", [None] * 220),
        ("close", ["100"] * 220),
        ("close_at", list(range(220))),
    ):
        changed = frame.set_column(
            frame.schema.get_field_index(name), name, pa.array(values)
        )
        output = pa.BufferOutputStream()
        pq.write_table(changed, output)
        encoded = output.getvalue().to_pybytes()
        with pytest.raises(PatternError):
            store.build(
                new_typed_id(RegistryKind.DATASET),
                replace(selected, normalized_digest=sha256_bytes(encoded)),
                encoded,
            )
    with pytest.raises(PatternError, match="ROW_MISMATCH"):
        store.build(
            new_typed_id(RegistryKind.DATASET), replace(selected, row_count=219), raw
        )
    with pytest.raises(PatternError, match="DISK_LIMIT"):
        store.build(
            new_typed_id(RegistryKind.DATASET),
            selected,
            raw,
            config=CorpusConfig(block_rows=37, max_disk_bytes=4096),
        )


def test_prepare_rejects_future_or_outside_query_and_unknown_parameters(
    tmp_path: Path,
) -> None:
    product, built, config, prepared = setup(tmp_path)
    pattern_id = cast(str, prepared.to_record()["pattern_id"])
    change: dict[str, Any]
    for change in (
        {"family": "PAT-99"},
        {"method_parameters_json": '{"execute":"anything"}'},
        {"family": "PAT-06", "method_parameters_json": '{"states":true}'},
    ):
        with pytest.raises(PatternError):
            replace(config, **cast(dict[str, Any], change))
    for change in (
        {"query_start": 1090, "query_stop": 1122},
        {"train_cutoff_ns": config.train_cutoff_ns - 10**14},
        {"candidate_cutoff_ns": config.candidate_cutoff_ns + 1},
        {"family": "PAT-02"},
        {"family": "PAT-11"},
    ):
        with pytest.raises(PatternError):
            product.prepare(
                built.manifest_digest,
                replace(config, **cast(dict[str, Any], change)),
                pattern_id=pattern_id,
                code_revision="a" * 40,
                environment_digest=DIGEST,
            )
    with pytest.raises(PatternError, match="CODE_REVISION"):
        product.prepare(
            built.manifest_digest,
            config,
            pattern_id=pattern_id,
            code_revision="not-code",
            environment_digest=DIGEST,
        )


def test_canonical_experiment_binding_and_disk_stop_survive_resubmission(
    tmp_path: Path,
) -> None:
    product, built, config, prepared = setup(tmp_path)
    wrong = FrozenPatternBinding(
        EXPERIMENT_ID,
        DIGEST,
        DIGEST,
        prepared.digest,
        new_typed_id(RegistryKind.PATTERN),
    )
    with pytest.raises(PatternError, match="REGISTERED_ID_BINDING"):
        product.execute_registered(prepared.digest, binding=wrong)
    limited = product.prepare(
        built.manifest_digest,
        replace(config, max_checkpoint_bytes=4096),
        pattern_id=new_typed_id(RegistryKind.PATTERN),
        code_revision="a" * 40,
        environment_digest=DIGEST,
    )
    with pytest.raises(PatternError, match="CHECKPOINT_BYTE_LIMIT"):
        execute(product, limited)
    results = execute(product, prepared)
    assert results["query_checkpoint_bytes"] > 4096
    assert results["canonical_binding"]["configuration_digest"] != prepared.digest
