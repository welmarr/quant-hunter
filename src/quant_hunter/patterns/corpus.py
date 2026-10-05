"""Immutable bounded Parquet partitions over an already admitted owned snapshot.

No registry, identity allocation, ownership decision or scientific promotion lives
here. The host selects data through QualityService before invoking this adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from typing import Any, cast

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.config.canonical import parse_json_document
from quant_hunter.data_quality import PartitionSelection, SelectedSnapshot
from quant_hunter.identity import RegistryKind, validate_typed_id
from quant_hunter.patterns.contracts import (
    CausalFrame,
    PatternError,
    PatternWindow,
    Provenance,
    SearchCancelledError,
    bounded_int,
)
from quant_hunter.provenance.hashing import require_sha256_digest, sha256_bytes
from quant_hunter.storage import ImmutableObjectStore, ObjectCorruptionError

FORMAT = "qh-pattern-corpus-parquet-v1"
MAX_SHARD_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
Progress = Callable[[dict[str, int | str]], None]


@dataclass(frozen=True, slots=True)
class CorpusConfig:
    block_rows: int = 32_768
    max_rows: int = 10_000_000
    max_disk_bytes: int = 1_073_741_824
    max_shards: int = 2048

    def __post_init__(self) -> None:
        bounded_int(self.block_rows, 2, 65_536, "Parquet partition rows")
        bounded_int(self.max_rows, 2, 50_000_000, "corpus rows")
        bounded_int(self.max_disk_bytes, 4096, 4_294_967_296, "corpus disk bytes")
        bounded_int(self.max_shards, 1, 2048, "Parquet partition count")


DEFAULT_CORPUS_CONFIG = CorpusConfig()


@dataclass(frozen=True, slots=True)
class Partition:
    start_row: int
    rows: int
    digest: str
    byte_size: int
    first_close_ns: int
    last_close_ns: int
    minimum_available_ns: int
    maximum_available_ns: int
    gaps: int

    def to_record(self) -> JsonRecord:
        return {
            key: str(value) if key.endswith("_ns") else value
            for key, value in asdict(self).items()
        }


@dataclass(frozen=True, slots=True)
class Corpus:
    dataset_id: str
    manifest_digest: str
    source_json: str
    config: CorpusConfig
    partitions: tuple[Partition, ...]
    row_count: int
    parquet_bytes: int
    gap_count: int
    parents_json: str
    selection_manifest_digest: str | None
    calendar_profile_digest: str | None

    @property
    def selected(self) -> JsonRecord:
        return cast(JsonRecord, parse_json_document(self.source_json))

    @property
    def provenance(self) -> Provenance:
        record = self.selected
        return Provenance(
            self.dataset_id,
            self.manifest_digest,
            cast(str, record["instrument_id"]),
            f"{record['step_ns']}ns",
            tuple(cast(list[str], record["feature_columns"])),
        )

    @property
    def parents(self) -> list[JsonValue]:
        return cast(list[JsonValue], parse_json_document(self.parents_json))


def _admitted(snapshot: SelectedSnapshot) -> None:
    snapshot.__post_init__()
    if not snapshot.causal_eligible or snapshot.admission != "SYNTHETIC_SOFTWARE_ONLY":
        raise PatternError("CORPUS_CAUSAL_ADMISSION_REQUIRED")
    if snapshot.evidence_mode != "SYNTHETIC":
        raise PatternError("CORPUS_HISTORICAL_TIMING_NOT_GOVERNED")


def _table(frame: CausalFrame) -> Any:
    return pa.table(
        {
            "close_ns": pa.array(frame.close_ns, type=pa.int64()),
            "available_ns": pa.array(frame.available_ns, type=pa.int64()),
            **{
                name: pa.array(frame.values[:, index], type=pa.float64())
                for index, name in enumerate(frame.provenance.features)
            },
        }
    )


def _parquet(frame: CausalFrame) -> bytes:
    stream = pa.BufferOutputStream()
    pq.write_table(
        _table(frame),
        stream,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
        data_page_version="1.0",
        row_group_size=len(frame.values),
    )
    return cast(bytes, stream.getvalue().to_pybytes())


class CorpusStore:
    """Uses the canonical object store; callers supply preallocated dataset IDs.

    Stored manifests are a row/time partition index. Search's bounded PAA pool is
    a per-query candidate index, not a global ANN or exhaustive-search claim.
    """

    def __init__(self, objects: ImmutableObjectStore) -> None:
        self.objects = objects

    def build(
        self,
        dataset_id: str,
        snapshot: SelectedSnapshot,
        parquet: bytes,
        *,
        config: CorpusConfig = DEFAULT_CORPUS_CONFIG,
        progress: Progress | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> Corpus:
        """Verified selected normalized bytes only; never an input filesystem path."""
        _admitted(snapshot)
        if not isinstance(parquet, bytes) or len(parquet) > MAX_SHARD_BYTES:
            raise PatternError("SELECTED_PARQUET_BYTE_LIMIT")
        if sha256_bytes(parquet) != snapshot.normalized_digest:
            raise PatternError("SELECTED_PARQUET_DIGEST_MISMATCH")
        source = pq.ParquetFile(pa.BufferReader(parquet))
        if source.metadata.num_rows != snapshot.row_count:
            raise PatternError("SELECTED_PARQUET_ROW_MISMATCH")
        columns = ("close_at", "available_at", *snapshot.feature_columns)
        for name in ("close_at", "available_at"):
            field = source.schema_arrow.field(name)
            if not pa.types.is_timestamp(field.type) or field.type.tz != "UTC":
                raise PatternError("SELECTED_PARQUET_UTC_REQUIRED")
        for name in snapshot.feature_columns:
            field = source.schema_arrow.field(name)
            if not (
                pa.types.is_integer(field.type)
                or pa.types.is_floating(field.type)
                or pa.types.is_decimal(field.type)
            ):
                raise PatternError("SELECTED_PARQUET_NUMERIC_REQUIRED")
        provenance = Provenance(
            snapshot.dataset_id,
            snapshot.normalized_digest,
            snapshot.instrument_id,
            f"{snapshot.step_ns}ns",
            snapshot.feature_columns,
        )

        def blocks() -> Iterator[CausalFrame]:
            for batch in source.iter_batches(
                batch_size=config.block_rows, columns=columns
            ):
                if any(batch.column(i).null_count for i in range(batch.num_columns)):
                    raise PatternError("SELECTED_PARQUET_NULL")
                values = np.column_stack(
                    [
                        batch.column(name)
                        .cast(pa.float64())
                        .to_numpy(zero_copy_only=False)
                        for name in snapshot.feature_columns
                    ]
                )
                times = [
                    batch.column(name)
                    .cast(pa.timestamp("ns", tz="UTC"))
                    .cast(pa.int64())
                    .to_numpy(zero_copy_only=False)
                    for name in ("close_at", "available_at")
                ]
                yield CausalFrame(
                    values, times[0], times[1], snapshot.step_ns, provenance
                )

        return self.build_frames(
            dataset_id,
            snapshot,
            blocks(),
            config=config,
            progress=progress,
            cancelled=cancelled,
        )

    def build_selection(
        self,
        dataset_id: str,
        selection: PartitionSelection,
        batches: Iterable[tuple[int, Any]],
        *,
        config: CorpusConfig = DEFAULT_CORPUS_CONFIG,
        progress: Progress | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> Corpus:
        """Compose authenticated quality-service batches without a giant input file.

        Parent indices are explicit; every selected parent's rows must appear
        exactly once and in order. The immutable selection preserves each bounded
        calendar digest and the common rules/version profile independently.
        """
        self._verify_selection(selection)
        parents = selection.parent_snapshots
        first = parents[0]
        for parent in parents:
            _admitted(parent)
            if (
                parent.instrument_id,
                parent.instrument_revision_digest,
                parent.step_ns,
                parent.feature_columns,
                parent.evidence_mode,
            ) != (
                selection.instrument_id,
                selection.instrument_revision_digest,
                selection.step_ns,
                selection.feature_columns,
                selection.evidence_mode,
            ):
                raise PatternError("CORPUS_SELECTION_PROFILE")
        provenance = Provenance(
            dataset_id,
            selection.manifest_digest,
            selection.instrument_id,
            f"{selection.step_ns}ns",
            selection.feature_columns,
        )

        def frames() -> Iterator[CausalFrame]:
            index = 0
            consumed = 0
            value_buffer: list[Any] = []
            close_buffer: list[Any] = []
            available_buffer: list[Any] = []
            buffered = 0
            for parent_index, batch in batches:
                if cancelled and cancelled():
                    raise SearchCancelledError(
                        "CORPUS_BUILD_CANCELLED_RETAINED_PARTITIONS"
                    )
                if (
                    type(parent_index) is not int
                    or parent_index not in {index, index + 1}
                    or parent_index >= len(parents)
                ):
                    raise PatternError("CORPUS_PARENT_BATCH_ORDER")
                if parent_index == index + 1:
                    if consumed != parents[index].row_count:
                        raise PatternError("CORPUS_PARENT_ROWS_MISSING")
                    index, consumed = parent_index, 0
                if (
                    not isinstance(batch, pa.RecordBatch)
                    or not 1 <= batch.num_rows <= 65_536
                ):
                    raise PatternError("CORPUS_PARENT_BATCH_BOUND")
                parent = parents[index]
                consumed += batch.num_rows
                if consumed > parent.row_count:
                    raise PatternError("CORPUS_PARENT_EXTRA_ROWS")
                columns = ("close_at", "available_at", *parent.feature_columns)
                if any(batch.column(name).null_count for name in columns):
                    raise PatternError("CORPUS_PARENT_NULL")
                for name in ("close_at", "available_at"):
                    field = batch.schema.field(name)
                    if not pa.types.is_timestamp(field.type) or field.type.tz != "UTC":
                        raise PatternError("CORPUS_PARENT_UTC_REQUIRED")
                for name in parent.feature_columns:
                    field = batch.schema.field(name)
                    if not (
                        pa.types.is_integer(field.type)
                        or pa.types.is_floating(field.type)
                        or pa.types.is_decimal(field.type)
                    ):
                        raise PatternError("CORPUS_PARENT_NUMERIC_REQUIRED")
                values = np.column_stack(
                    [
                        batch.column(name)
                        .cast(pa.float64())
                        .to_numpy(zero_copy_only=False)
                        for name in parent.feature_columns
                    ]
                )
                close = (
                    batch.column("close_at")
                    .cast(pa.timestamp("ns", tz="UTC"))
                    .cast(pa.int64())
                    .to_numpy(zero_copy_only=False)
                )
                available = (
                    batch.column("available_at")
                    .cast(pa.timestamp("ns", tz="UTC"))
                    .cast(pa.int64())
                    .to_numpy(zero_copy_only=False)
                )
                admitted = CausalFrame(
                    values, close, available, selection.step_ns, provenance
                )
                offset = 0
                while offset < len(values):
                    stop = min(len(values), offset + config.block_rows - buffered)
                    value_buffer.append(admitted.values[offset:stop])
                    close_buffer.append(admitted.close_ns[offset:stop])
                    available_buffer.append(admitted.available_ns[offset:stop])
                    buffered += stop - offset
                    offset = stop
                    if buffered == config.block_rows:
                        yield CausalFrame(
                            np.concatenate(value_buffer),
                            np.concatenate(close_buffer),
                            np.concatenate(available_buffer),
                            selection.step_ns,
                            provenance,
                        )
                        value_buffer, close_buffer, available_buffer, buffered = (
                            [],
                            [],
                            [],
                            0,
                        )
            if index != len(parents) - 1 or consumed != parents[-1].row_count:
                raise PatternError("CORPUS_PARENT_ROWS_MISSING")
            if buffered:
                yield CausalFrame(
                    np.concatenate(value_buffer),
                    np.concatenate(close_buffer),
                    np.concatenate(available_buffer),
                    selection.step_ns,
                    provenance,
                )

        return self.build_frames(
            dataset_id,
            first,
            frames(),
            config=config,
            progress=progress,
            cancelled=cancelled,
            _expected_rows=selection.total_rows,
            _parents=parents,
            _selection_digest=selection.manifest_digest,
            _calendar_profile_digest=selection.calendar_profile_digest,
        )

    def build_frames(
        self,
        dataset_id: str,
        snapshot: SelectedSnapshot,
        frames: Iterable[CausalFrame],
        *,
        config: CorpusConfig = DEFAULT_CORPUS_CONFIG,
        progress: Progress | None = None,
        cancelled: Callable[[], bool] | None = None,
        _expected_rows: int | None = None,
        _parents: tuple[SelectedSnapshot, ...] | None = None,
        _selection_digest: str | None = None,
        _calendar_profile_digest: str | None = None,
    ) -> Corpus:
        """Host-verified streaming extension, also used by labelled synthetic load tests.

        The host is responsible for verifying a partitioned source's physical
        graph before supplying this iterator. Frame labels alone are not proof.
        The application upload path always uses build() and its exact-byte check.
        """
        _admitted(snapshot)
        validate_typed_id(dataset_id, RegistryKind.DATASET)
        expected_rows = snapshot.row_count if _expected_rows is None else _expected_rows
        parents = (snapshot,) if _parents is None else _parents
        if (
            dataset_id in {parent.dataset_id for parent in parents}
            or expected_rows > config.max_rows
        ):
            raise PatternError("CORPUS_NEW_ID_OR_ROW_LIMIT")
        expected = Provenance(
            dataset_id if _selection_digest else snapshot.dataset_id,
            _selection_digest or snapshot.normalized_digest,
            snapshot.instrument_id,
            f"{snapshot.step_ns}ns",
            snapshot.feature_columns,
        )
        parts: list[Partition] = []
        rows = total_bytes = gaps = 0
        previous: int | None = None
        for frame in frames:
            if cancelled and cancelled():
                raise SearchCancelledError("CORPUS_BUILD_CANCELLED_RETAINED_PARTITIONS")
            if frame.provenance != expected or frame.step_ns != snapshot.step_ns:
                raise PatternError("CORPUS_SOURCE_BINDING")
            if len(frame.values) > config.block_rows:
                raise PatternError("CORPUS_BLOCK_ROW_LIMIT")
            if rows + len(frame.values) > min(config.max_rows, expected_rows):
                raise PatternError("CORPUS_ROW_LIMIT")
            if len(parts) >= config.max_shards:
                raise PatternError("CORPUS_PARTITION_LIMIT")
            first, last = int(frame.close_ns[0]), int(frame.close_ns[-1])
            if previous is not None and first <= previous:
                raise PatternError("CORPUS_PARTITION_REORDER_OR_DUPLICATION")
            missing = int(np.count_nonzero(np.diff(frame.close_ns) != frame.step_ns))
            missing += int(previous is not None and first - previous != frame.step_ns)
            encoded = _parquet(frame)
            if (
                len(encoded) > MAX_SHARD_BYTES
                or total_bytes + len(encoded) > config.max_disk_bytes
            ):
                raise PatternError("CORPUS_DISK_LIMIT")
            stored = self.objects.publish(encoded)
            parts.append(
                Partition(
                    rows,
                    len(frame.values),
                    stored.digest,
                    stored.byte_size,
                    first,
                    last,
                    int(frame.available_ns.min()),
                    int(frame.available_ns.max()),
                    missing,
                )
            )
            rows += len(frame.values)
            total_bytes += stored.byte_size
            gaps += missing
            previous = last
            if progress:
                progress(
                    {
                        "stage": "CORPUS_PARTITION",
                        "rows": rows,
                        "partitions": len(parts),
                        "parquet_bytes": total_bytes,
                    }
                )
        if rows != expected_rows or not parts:
            raise PatternError("CORPUS_INCOMPLETE_SOURCE")
        manifest: JsonRecord = {
            "format": FORMAT,
            "dataset_id": dataset_id,
            "selected_snapshot": snapshot.to_record(),
            "parent_snapshots": [parent.to_record() for parent in parents],
            "selection_manifest_digest": _selection_digest,
            "calendar_profile_digest": _calendar_profile_digest,
            "configuration": cast(JsonRecord, asdict(config)),
            "partitions": [part.to_record() for part in parts],
            "row_count": rows,
            "parquet_bytes": total_bytes,
            "gap_count": gaps,
            "index_kind": "EXACT_ROW_TIME_PARTITIONS_QUERY_PAA_CANDIDATES",
        }
        raw = canonicalize_json(manifest)
        if (
            len(raw) > MAX_MANIFEST_BYTES
            or total_bytes + len(raw) > config.max_disk_bytes
        ):
            raise PatternError("CORPUS_MANIFEST_DISK_LIMIT")
        return self.load(self.objects.publish(raw).digest)

    def _verify_selection(self, selection: PartitionSelection) -> None:
        selection.to_record()
        if not selection.causal_eligible or selection.evidence_mode != "SYNTHETIC":
            raise PatternError("CORPUS_CAUSAL_ADMISSION_REQUIRED")
        try:
            manifest_bytes = self.objects.read_bytes(selection.manifest_digest)
        except ObjectCorruptionError:
            raise PatternError("CORPUS_SELECTION_MANIFEST_MISSING_OR_CORRUPT") from None
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            raise PatternError("CORPUS_SELECTION_MANIFEST_LIMIT")
        manifest = cast(dict[str, Any], parse_json_document(manifest_bytes))
        if (
            manifest.get("schema_version") != "qh-owned-partition-selection-v1"
            or manifest.get("total_rows") != selection.total_rows
            or canonicalize_json(manifest.get("bounds"))
            != canonicalize_json(selection.bounds)
            or canonicalize_json(manifest.get("parent_snapshots"))
            != canonicalize_json(
                [parent.to_record() for parent in selection.parent_snapshots]
            )
            or manifest.get("calendar_profile_digest")
            != selection.calendar_profile_digest
            or sha256_bytes(canonicalize_json(manifest.get("calendar_profile")))
            != selection.calendar_profile_digest
        ):
            raise PatternError("CORPUS_SELECTION_MANIFEST_BINDING")

    def load(self, digest: str) -> Corpus:
        try:
            return self._load(digest)
        except PatternError:
            raise
        except KeyError, TypeError, ValueError, OverflowError, RecursionError:
            raise PatternError("CORPUS_MANIFEST_INVALID") from None

    def _load(self, digest: str) -> Corpus:
        require_sha256_digest(digest)
        raw = self.objects.read_bytes(digest)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise PatternError("CORPUS_MANIFEST_LIMIT")
        record = cast(dict[str, Any], parse_json_document(raw))
        required = {
            "format",
            "dataset_id",
            "selected_snapshot",
            "configuration",
            "partitions",
            "row_count",
            "parquet_bytes",
            "gap_count",
            "index_kind",
            "parent_snapshots",
            "selection_manifest_digest",
            "calendar_profile_digest",
        }
        if (
            set(record) != required
            or record["format"] != FORMAT
            or record["index_kind"] != "EXACT_ROW_TIME_PARTITIONS_QUERY_PAA_CANDIDATES"
        ):
            raise PatternError("CORPUS_MANIFEST_SCHEMA")
        validate_typed_id(record["dataset_id"], RegistryKind.DATASET)
        selected = dict(record["selected_snapshot"])
        selected["feature_columns"] = tuple(selected["feature_columns"])
        selected["reasons"] = tuple(selected["reasons"])
        source = SelectedSnapshot(**selected)
        _admitted(source)
        if (
            not isinstance(record["parent_snapshots"], list)
            or not 1 <= len(record["parent_snapshots"]) <= 1024
        ):
            raise PatternError("CORPUS_PARENT_COUNT")
        parents: list[SelectedSnapshot] = []
        for parent_record in record["parent_snapshots"]:
            values = dict(parent_record)
            values["feature_columns"] = tuple(values["feature_columns"])
            values["reasons"] = tuple(values["reasons"])
            parent = SelectedSnapshot(**values)
            _admitted(parent)
            if (
                parent.instrument_id,
                parent.instrument_revision_digest,
                parent.step_ns,
                parent.feature_columns,
                parent.evidence_mode,
            ) != (
                source.instrument_id,
                source.instrument_revision_digest,
                source.step_ns,
                source.feature_columns,
                source.evidence_mode,
            ):
                raise PatternError("CORPUS_PARENT_PROFILE")
            parents.append(parent)
        if len({parent.dataset_id for parent in parents}) != len(
            parents
        ) or canonicalize_json(parents[0].to_record()) != canonicalize_json(
            source.to_record()
        ):
            raise PatternError("CORPUS_PARENT_IDENTITY")
        if record["selection_manifest_digest"] is None:
            if len(parents) != 1 or record["calendar_profile_digest"] is not None:
                raise PatternError("CORPUS_SELECTION_BINDING")
        else:
            require_sha256_digest(record["selection_manifest_digest"])
            require_sha256_digest(record["calendar_profile_digest"])
            self._verify_selection(
                PartitionSelection(
                    record["selection_manifest_digest"],
                    sum(parent.row_count for parent in parents),
                    {"start": source.bounds["start"], "end": parents[-1].bounds["end"]},
                    tuple(parents),
                    record["calendar_profile_digest"],
                    source.instrument_id,
                    source.instrument_revision_digest,
                    source.step_ns,
                    source.feature_columns,
                    source.evidence_mode,
                    source.causal_eligible,
                )
            )
        config = CorpusConfig(**record["configuration"])
        if (
            not isinstance(record["partitions"], list)
            or not 1 <= len(record["partitions"]) <= config.max_shards
        ):
            raise PatternError("CORPUS_PARTITION_LIMIT")
        parts: list[Partition] = []
        rows = total = gaps = 0
        previous = 0
        for values in record["partitions"]:
            part = Partition(
                **cast(
                    dict[str, Any],
                    {
                        key: int(value) if key.endswith("_ns") else value
                        for key, value in values.items()
                    },
                )
            )
            require_sha256_digest(part.digest)
            bounded_int(part.rows, 1, config.block_rows, "partition rows")
            bounded_int(part.byte_size, 1, MAX_SHARD_BYTES, "partition bytes")
            if (
                part.start_row != rows
                or not previous < part.first_close_ns <= part.last_close_ns
                or not part.first_close_ns
                <= part.minimum_available_ns
                <= part.maximum_available_ns
                or part.maximum_available_ns < part.last_close_ns
                or not 0 <= part.gaps <= part.rows
            ):
                raise PatternError("CORPUS_PARTITION_INDEX")
            rows += part.rows
            total += part.byte_size
            gaps += part.gaps
            previous = part.last_close_ns
            parts.append(part)
        if (
            rows != record["row_count"]
            or rows != sum(parent.row_count for parent in parents)
            or rows > config.max_rows
            or total != record["parquet_bytes"]
            or total + len(raw) > config.max_disk_bytes
            or gaps != record["gap_count"]
        ):
            raise PatternError("CORPUS_COVERAGE_BINDING")
        return Corpus(
            record["dataset_id"],
            digest,
            canonicalize_json(source.to_record()).decode(),
            config,
            tuple(parts),
            rows,
            total,
            gaps,
            canonicalize_json([parent.to_record() for parent in parents]).decode(),
            record["selection_manifest_digest"],
            record["calendar_profile_digest"],
        )

    def partition(self, corpus: Corpus, index: int) -> CausalFrame:
        bounded_int(index, 0, len(corpus.partitions) - 1, "partition index")
        part = corpus.partitions[index]
        raw = self.objects.read_bytes(part.digest)
        if len(raw) != part.byte_size or len(raw) > MAX_SHARD_BYTES:
            raise PatternError("CORPUS_SHARD_BYTES")
        file = pq.ParquetFile(pa.BufferReader(raw))
        names = ("close_ns", "available_ns", *corpus.provenance.features)
        expected = pa.schema(
            [
                (name, pa.int64() if index < 2 else pa.float64())
                for index, name in enumerate(names)
            ]
        )
        if (
            file.metadata.num_rows != part.rows
            or file.metadata.num_row_groups != 1
            or file.schema_arrow != expected
        ):
            raise PatternError("CORPUS_SHARD_SCHEMA")
        table = file.read(use_threads=False)
        if any(column.null_count for column in table.columns):
            raise PatternError("CORPUS_SHARD_NULL")
        values = np.column_stack(
            [table[name].to_numpy() for name in corpus.provenance.features]
        )
        frame = CausalFrame(
            values,
            table["close_ns"].to_numpy(),
            table["available_ns"].to_numpy(),
            cast(int, corpus.selected["step_ns"]),
            corpus.provenance,
        )
        if (
            int(frame.close_ns[0]) != part.first_close_ns
            or int(frame.close_ns[-1]) != part.last_close_ns
            or int(frame.available_ns.min()) != part.minimum_available_ns
            or int(frame.available_ns.max()) != part.maximum_available_ns
        ):
            raise PatternError("CORPUS_SHARD_INDEX_MISMATCH")
        expected_gaps = int(np.count_nonzero(np.diff(frame.close_ns) != frame.step_ns))
        if index > 0:
            expected_gaps += int(
                part.first_close_ns - corpus.partitions[index - 1].last_close_ns
                != frame.step_ns
            )
        if expected_gaps != part.gaps:
            raise PatternError("CORPUS_SHARD_GAP_INDEX_MISMATCH")
        return frame

    def time_frame(self, corpus: Corpus, start_ns: int, end_ns: int) -> CausalFrame:
        """Bounded inclusive close-time selection for cross-instrument alignment."""
        frames: list[CausalFrame] = []
        total = 0
        if not 0 < start_ns <= end_ns < 2**63:
            raise PatternError("CORPUS_TIME_SELECTION")
        for index, part in enumerate(corpus.partitions):
            if part.first_close_ns > end_ns or part.last_close_ns < start_ns:
                continue
            block = self.partition(corpus, index)
            chosen = (block.close_ns >= start_ns) & (block.close_ns <= end_ns)
            count = int(chosen.sum())
            if not count:
                continue
            total += count
            if total > 4096:
                raise PatternError("CORPUS_TIME_SELECTION_ROW_LIMIT")
            frames.append(
                CausalFrame(
                    block.values[chosen],
                    block.close_ns[chosen],
                    block.available_ns[chosen],
                    block.step_ns,
                    block.provenance,
                )
            )
        if not frames:
            raise PatternError("CORPUS_TIME_SELECTION_EMPTY")
        return CausalFrame(
            np.concatenate([b.values for b in frames]),
            np.concatenate([b.close_ns for b in frames]),
            np.concatenate([b.available_ns for b in frames]),
            cast(int, corpus.selected["step_ns"]),
            corpus.provenance,
        )

    def blocks(
        self, corpus: Corpus, *, start_partition: int = 0
    ) -> Iterator[CausalFrame]:
        bounded_int(start_partition, 0, len(corpus.partitions), "resume partition")
        for index in range(start_partition, len(corpus.partitions)):
            yield self.partition(corpus, index)

    def frame(self, corpus: Corpus, start: int, stop: int) -> CausalFrame:
        bounded_int(start, 0, corpus.row_count - 1, "selection start row")
        bounded_int(
            stop, start + 1, min(corpus.row_count, start + 4096), "selection stop row"
        )
        frames: list[CausalFrame] = []
        for index, part in enumerate(corpus.partitions):
            if part.start_row < stop and part.start_row + part.rows > start:
                block = self.partition(corpus, index)
                lo, hi = (
                    max(0, start - part.start_row),
                    min(part.rows, stop - part.start_row),
                )
                frames.append(
                    CausalFrame(
                        block.values[lo:hi],
                        block.close_ns[lo:hi],
                        block.available_ns[lo:hi],
                        block.step_ns,
                        block.provenance,
                    )
                )
        return CausalFrame(
            np.concatenate([b.values for b in frames]),
            np.concatenate([b.close_ns for b in frames]),
            np.concatenate([b.available_ns for b in frames]),
            cast(int, corpus.selected["step_ns"]),
            corpus.provenance,
        )

    def window(
        self, corpus: Corpus, start: int, stop: int, decision_ns: int
    ) -> PatternWindow:
        frame = self.frame(corpus, start, stop)
        return frame.window(0, len(frame.values), decision_ns=decision_ns)
