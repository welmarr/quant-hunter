"""Closed, bounded canonical JSON checkpoints; no executable deserialization."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from math import prod
from typing import Any, cast

import numpy as np

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.config.canonical import parse_json_document
from quant_hunter.patterns.contracts import (
    CausalFrame,
    PatternError,
    PatternWindow,
    Provenance,
)
from quant_hunter.patterns.search import (
    ObservedOutcome,
    SearchConfig,
    SearchEngine,
    SearchHit,
    SearchProgress,
    SearchSnapshot,
)
from quant_hunter.storage import ImmutableObjectStore

MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024
_TYPES = {
    cls.__name__: cls
    for cls in (
        CausalFrame,
        PatternWindow,
        Provenance,
        ObservedOutcome,
        SearchConfig,
        SearchHit,
        SearchProgress,
        SearchSnapshot,
    )
}


def _encode(value: object) -> JsonValue:
    if type(value) in _TYPES.values() and is_dataclass(value):
        return {
            "type": type(value).__name__,
            "fields": {
                field.name: _encode(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if isinstance(value, np.ndarray):
        if (
            value.dtype not in {np.dtype("float64"), np.dtype("int64")}
            or not 1 <= value.ndim <= 2
            or value.size > 65_536 * 16
        ):
            raise PatternError("CHECKPOINT_ARRAY_BOUND")
        return {
            "array": str(value.dtype),
            "shape": list(value.shape),
            "values": [_encode(item.item()) for item in value.ravel()],
        }
    if isinstance(value, tuple):
        return {"tuple": [_encode(item) for item in value]}
    if type(value) is int and abs(value) > 2**53 - 1:
        return {"integer": str(value)}
    if value is None or type(value) in {str, bool, int, float}:
        return cast(JsonValue, value)
    raise PatternError("CHECKPOINT_TYPE_REFUSED")


def _decode(value: JsonValue, depth: int = 0) -> Any:
    if depth > 16:
        raise PatternError("CHECKPOINT_NESTING_BOUND")
    if value is None or type(value) in {str, bool, int, float}:
        return value
    if not isinstance(value, dict):
        raise PatternError("CHECKPOINT_TYPE_REFUSED")
    if set(value) == {"integer"}:
        encoded = value["integer"]
        if (
            not isinstance(encoded, str)
            or re.fullmatch(r"-?(0|[1-9][0-9]{0,18})", encoded) is None
        ):
            raise PatternError("CHECKPOINT_INTEGER")
        result = int(encoded)
        if abs(result) > 2**63 - 1:
            raise PatternError("CHECKPOINT_INTEGER")
        return result
    if set(value) == {"tuple"}:
        sequence = value["tuple"]
        if not isinstance(sequence, list) or len(sequence) > 4096:
            raise PatternError("CHECKPOINT_TUPLE_BOUND")
        return tuple(_decode(item, depth + 1) for item in sequence)
    if set(value) == {"array", "shape", "values"}:
        shape, values = value["shape"], value["values"]
        if (
            value["array"] not in {"int64", "float64"}
            or not isinstance(shape, list)
            or not 1 <= len(shape) <= 2
            or any(type(size) is not int or not 1 <= size <= 65_536 for size in shape)
            or not isinstance(values, list)
        ):
            raise PatternError("CHECKPOINT_ARRAY_SCHEMA")
        expected = prod(cast(list[int], shape))
        if expected != len(values) or expected > 65_536 * 16:
            raise PatternError("CHECKPOINT_ARRAY_BOUND")
        decoded = [_decode(item, depth + 1) for item in values]
        if any(type(item) not in {int, float} for item in decoded) or (
            value["array"] == "int64" and any(type(item) is not int for item in decoded)
        ):
            raise PatternError("CHECKPOINT_ARRAY_NUMBER")
        return np.array(decoded, dtype=cast(str, value["array"])).reshape(
            cast(list[int], shape)
        )
    if set(value) == {"type", "fields"}:
        name, supplied = value["type"], value["fields"]
        if (
            not isinstance(name, str)
            or name not in _TYPES
            or not isinstance(supplied, dict)
        ):
            raise PatternError("CHECKPOINT_DATACLASS_REFUSED")
        cls = _TYPES[name]
        if set(supplied) != {field.name for field in fields(cls)}:
            raise PatternError("CHECKPOINT_DATACLASS_FIELDS")
        return cls(**{key: _decode(item, depth + 1) for key, item in supplied.items()})
    raise PatternError("CHECKPOINT_TYPE_REFUSED")


def save_checkpoint(
    objects: ImmutableObjectStore,
    snapshot: SearchSnapshot,
    binding: JsonRecord,
    *,
    next_partition: int,
    previous_digest: str | None = None,
    previous_total_bytes: int = 0,
    remaining_bytes: int = 256 * 1024 * 1024,
) -> str:
    # Re-establish core invariants before publishing any resumable candidate pool.
    SearchEngine.resume(snapshot)
    if next_partition != snapshot.progress.blocks:
        raise PatternError("CHECKPOINT_PARTITION_COUNTER")
    if (
        type(previous_total_bytes) is not int
        or previous_total_bytes < 0
        or type(remaining_bytes) is not int
        or remaining_bytes < 0
    ):
        raise PatternError("CHECKPOINT_DISK_BUDGET")
    record: JsonRecord = {
        "format": "qh-pattern-query-checkpoint-v1",
        "binding": binding,
        "next_partition": next_partition,
        "snapshot": _encode(snapshot),
        "previous_digest": previous_digest,
        "previous_total_bytes": previous_total_bytes,
    }
    raw = canonicalize_json(record)
    if len(raw) > min(MAX_CHECKPOINT_BYTES, remaining_bytes):
        raise PatternError("CHECKPOINT_BYTE_LIMIT")
    return objects.publish(raw).digest


def load_checkpoint(
    objects: ImmutableObjectStore,
    digest: str,
    expected_binding: JsonRecord,
) -> tuple[SearchEngine, int]:
    raw = objects.read_bytes(digest)
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise PatternError("CHECKPOINT_BYTE_LIMIT")
    record = parse_json_document(raw)
    if (
        not isinstance(record, dict)
        or set(record)
        != {
            "format",
            "binding",
            "next_partition",
            "snapshot",
            "previous_digest",
            "previous_total_bytes",
        }
        or record["format"] != "qh-pattern-query-checkpoint-v1"
        or canonicalize_json(record["binding"]) != canonicalize_json(expected_binding)
    ):
        raise PatternError("CHECKPOINT_FROZEN_BINDING")
    snapshot = _decode(record["snapshot"])
    if (
        not isinstance(snapshot, SearchSnapshot)
        or type(record["next_partition"]) is not int
        or record["next_partition"] != snapshot.progress.blocks
    ):
        raise PatternError("CHECKPOINT_PARTITION_COUNTER")
    return SearchEngine.resume(snapshot), record["next_partition"]


def checkpoint_disk_bytes(
    objects: ImmutableObjectStore, digest: str, binding: JsonRecord, *, limit: int
) -> int:
    """Verify the immutable checkpoint chain and exact cumulative serialized bytes."""
    current: str | None = digest
    total = 0
    expected_previous_total: int | None = None
    expected_partition: int | None = None
    for _ in range(2048):
        if current is None:
            if expected_previous_total != 0 or expected_partition != 0:
                raise PatternError("CHECKPOINT_CHAIN_BYTES")
            return total
        raw = objects.read_bytes(current)
        total += len(raw)
        if total > limit or len(raw) > MAX_CHECKPOINT_BYTES:
            raise PatternError("CHECKPOINT_DISK_BUDGET")
        record = cast(dict[str, Any], parse_json_document(raw))
        if record.get(
            "format"
        ) != "qh-pattern-query-checkpoint-v1" or canonicalize_json(
            record.get("binding")
        ) != canonicalize_json(binding):
            raise PatternError("CHECKPOINT_FROZEN_BINDING")
        prior = record.get("previous_total_bytes")
        partition = record.get("next_partition")
        if (
            type(prior) is not int
            or prior < 0
            or type(partition) is not int
            or (
                expected_previous_total is not None
                and prior + len(raw) != expected_previous_total
            )
            or (expected_partition is not None and partition != expected_partition)
        ):
            raise PatternError("CHECKPOINT_CHAIN_BYTES")
        previous = record.get("previous_digest")
        if previous is not None and not isinstance(previous, str):
            raise PatternError("CHECKPOINT_CHAIN_DIGEST")
        expected_previous_total, expected_partition = prior, partition - 1
        current = previous
    if current is not None or expected_previous_total != 0 or expected_partition != 0:
        raise PatternError("CHECKPOINT_CHAIN_BOUND")
    return total
