"""Deterministic Parquet and independent derived-data identity contracts."""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Final, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_hunter.config.canonical import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.config.schema import VersionedSchemaCatalog
from quant_hunter.identity.ids import RegistryKind, validate_typed_id
from quant_hunter.provenance.hashing import (
    require_sha256_digest,
    sha256_bytes,
    sha256_canonical_json,
    verify_sha256_bytes,
)
from quant_hunter.storage.manifests import (
    ARTIFACT_MANIFEST_SCHEMA,
    ArtifactManifest,
    ArtifactProducer,
    ArtifactProvenance,
    build_artifact_manifest,
    publish_artifact_manifest,
    verify_artifact_binding,
)
from quant_hunter.storage.objects import ImmutableObjectStore, StoredObject
from quant_hunter.storage.raw import QualityDisposition
from quant_hunter.storage.security import (
    reject_credential_shaped_fields,
    reject_credential_uri,
    reject_secret_text,
)

PYARROW_VERSION: Final = "25.0.1"
LINEAGE_MANIFEST_SCHEMA: Final = "dataset-lineage-manifest.schema.json"
DATASET_SCHEMA: Final = "dataset.schema.json"
FIELD_NAME: Final = re.compile(r"^[a-z][a-z0-9_]*$")
LOGICAL_FRAMING_MAGIC: Final = b"QH-LOGICAL-TABLE\x00\x01"


class DerivedDataError(ValueError):
    """Base error for invalid deterministic derived-data input."""


class UnsupportedLogicalTypeError(DerivedDataError):
    """An Arrow type is outside the explicitly governed logical type set."""


class LogicalDataError(DerivedDataError):
    """A table conflicts with its declared logical schema or value rules."""


class DerivedDataIntegrityError(RuntimeError):
    """Published physical, logical, or lineage evidence does not verify."""


class DatasetBindingError(DerivedDataIntegrityError):
    """A governed dataset record does not bind the supplied derived evidence."""


class OrderingSemantics(StrEnum):
    """Explicit treatment of row or parent order in canonical identity."""

    ORDERED = "ORDERED"
    UNORDERED = "UNORDERED"


class DerivedLayer(StrEnum):
    """Non-raw layers admitted by the Batch 4B.1 derived-data foundation."""

    NORMALIZED = "normalized"
    CURATED = "curated"
    FEATURES = "features"
    EXPERIMENT_SNAPSHOT = "experiment_snapshot"


@dataclass(frozen=True, slots=True)
class ParquetWriterProfile:
    """Every governed PyArrow option that can affect physical output bytes."""

    profile_name: str = "qh-parquet-v1-zstd"
    row_group_size: int = 65_536
    compression: str = "zstd"
    compression_level: int | None = 9
    use_dictionary: bool = False
    write_statistics: bool = False
    parquet_version: str = "2.6"
    data_page_version: str = "2.0"
    data_page_size: int = 65_536
    write_batch_size: int = 1_024
    dictionary_pagesize_limit: int = 1_048_576
    use_byte_stream_split: bool = False
    use_compliant_nested_type: bool = True
    store_schema: bool = True
    write_page_index: bool = False
    write_page_checksum: bool = True
    store_decimal_as_integer: bool = False
    write_time_adjusted_to_utc: bool = False

    def document(self) -> JsonRecord:
        """Return the complete closed writer profile used for identity."""
        _validate_writer_profile(self)
        return {
            "profile_version": "1.0.0",
            "profile_name": self.profile_name,
            "library": "pyarrow",
            "library_version": PYARROW_VERSION,
            "row_group_size": self.row_group_size,
            "compression": self.compression,
            "compression_level": self.compression_level,
            "use_dictionary": self.use_dictionary,
            "write_statistics": self.write_statistics,
            "parquet_version": self.parquet_version,
            "data_page_version": self.data_page_version,
            "data_page_size": self.data_page_size,
            "write_batch_size": self.write_batch_size,
            "dictionary_pagesize_limit": self.dictionary_pagesize_limit,
            "use_byte_stream_split": self.use_byte_stream_split,
            "column_encoding": None,
            "use_deprecated_int96_timestamps": False,
            "timestamp_coercion": None,
            "allow_truncated_timestamps": False,
            "use_compliant_nested_type": self.use_compliant_nested_type,
            "flavor": None,
            "filesystem": None,
            "encryption": None,
            "store_schema": self.store_schema,
            "write_page_index": self.write_page_index,
            "write_page_checksum": self.write_page_checksum,
            "sorting_columns": [],
            "store_decimal_as_integer": self.store_decimal_as_integer,
            "write_time_adjusted_to_utc": self.write_time_adjusted_to_utc,
            "max_rows_per_page": None,
            "bloom_filters": None,
            "metadata_policy": "REJECT_INPUT_WRITE_ARROW_SCHEMA_ONLY",
            "null_policy": "PRESERVE_DECLARED_NULLS",
        }


DEFAULT_PARQUET_PROFILE: Final = ParquetWriterProfile()


@dataclass(frozen=True, slots=True)
class ParentEvidence:
    """All three identities plus registry revision identity for one parent."""

    dataset_id: str
    registry_revision_digest: str
    physical_object_digest: str
    provenance_lineage_digest: str
    logical_content_fingerprint: str

    def document(self) -> JsonRecord:
        validate_typed_id(self.dataset_id, RegistryKind.DATASET)
        for digest in (
            self.registry_revision_digest,
            self.physical_object_digest,
            self.provenance_lineage_digest,
            self.logical_content_fingerprint,
        ):
            require_sha256_digest(digest)
        return {
            "dataset_id": self.dataset_id,
            "registry_revision_digest": self.registry_revision_digest,
            "physical_object_digest": self.physical_object_digest,
            "provenance_lineage_digest": self.provenance_lineage_digest,
            "logical_content_fingerprint": self.logical_content_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class DatasetLineageManifest:
    """Canonical lineage bytes and their provenance identity."""

    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise DerivedDataIntegrityError("Lineage manifest is not a JSON object")
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)


@dataclass(frozen=True, slots=True)
class DerivedDatasetEvidence:
    """Bound physical, logical, artifact, and lineage evidence for one table."""

    dataset_id: str
    layer: DerivedLayer
    quality_disposition: QualityDisposition
    row_ordering: OrderingSemantics
    parent_ordering: OrderingSemantics
    declared_schema: pa.Schema
    writer_profile: ParquetWriterProfile
    parent_evidence: tuple[ParentEvidence, ...]
    parquet_object: StoredObject
    artifact_manifest: ArtifactManifest
    artifact_manifest_object: StoredObject
    lineage_manifest: DatasetLineageManifest
    lineage_manifest_object: StoredObject
    schema_digest: str
    logical_content_fingerprint: str
    writer_profile_digest: str


def _validate_writer_profile(profile: ParquetWriterProfile) -> None:
    if pa.__version__ != PYARROW_VERSION:
        raise DerivedDataError(
            f"Pinned PyArrow {PYARROW_VERSION} required; observed {pa.__version__}"
        )
    if FIELD_NAME.fullmatch(profile.profile_name.replace("-", "_")) is None:
        raise DerivedDataError("Writer profile name is malformed")
    for name, value in (
        ("row_group_size", profile.row_group_size),
        ("data_page_size", profile.data_page_size),
        ("write_batch_size", profile.write_batch_size),
        ("dictionary_pagesize_limit", profile.dictionary_pagesize_limit),
    ):
        if type(value) is not int or value <= 0:
            raise DerivedDataError(f"{name} must be a positive integer")
    for name, value in (
        ("use_dictionary", profile.use_dictionary),
        ("write_statistics", profile.write_statistics),
        ("use_byte_stream_split", profile.use_byte_stream_split),
        ("use_compliant_nested_type", profile.use_compliant_nested_type),
        ("store_schema", profile.store_schema),
        ("write_page_index", profile.write_page_index),
        ("write_page_checksum", profile.write_page_checksum),
        ("store_decimal_as_integer", profile.store_decimal_as_integer),
        ("write_time_adjusted_to_utc", profile.write_time_adjusted_to_utc),
    ):
        if type(value) is not bool:
            raise DerivedDataError(f"{name} must be boolean")
    if profile.compression not in {"NONE", "zstd"}:
        raise DerivedDataError("Only NONE and zstd compression are governed")
    if profile.compression == "NONE":
        if profile.compression_level is not None:
            raise DerivedDataError("Uncompressed profiles cannot declare a level")
    elif (
        type(profile.compression_level) is not int
        or not 1 <= profile.compression_level <= 19
    ):
        raise DerivedDataError("zstd compression level must be between 1 and 19")
    if profile.compression == "zstd" and not pa.Codec.is_available("zstd"):
        raise DerivedDataError("The pinned PyArrow build lacks zstd support")
    if profile.parquet_version != "2.6":
        raise DerivedDataError("The governed Parquet format version is 2.6")
    if profile.data_page_version not in {"1.0", "2.0"}:
        raise DerivedDataError("Unsupported Parquet data page version")


def parquet_writer_profile_digest(profile: ParquetWriterProfile) -> str:
    """Identify every governed physical writer choice using JCS SHA-256."""
    return sha256_canonical_json(profile.document())


def _logical_type_document(data_type: pa.DataType) -> JsonRecord:
    type_name: str
    precision: int | None = None
    scale: int | None = None
    timestamp_unit: str | None = None
    timezone: str | None = None
    if pa.types.is_boolean(data_type):
        type_name = "boolean"
    elif pa.types.is_int8(data_type):
        type_name = "int8"
    elif pa.types.is_int16(data_type):
        type_name = "int16"
    elif pa.types.is_int32(data_type):
        type_name = "int32"
    elif pa.types.is_int64(data_type):
        type_name = "int64"
    elif pa.types.is_uint8(data_type):
        type_name = "uint8"
    elif pa.types.is_uint16(data_type):
        type_name = "uint16"
    elif pa.types.is_uint32(data_type):
        type_name = "uint32"
    elif pa.types.is_uint64(data_type):
        type_name = "uint64"
    elif pa.types.is_float64(data_type):
        type_name = "float64"
    elif pa.types.is_string(data_type):
        type_name = "utf8"
    elif pa.types.is_decimal128(data_type):
        decimal_type = cast(pa.Decimal128Type, data_type)
        type_name = "decimal128"
        precision = decimal_type.precision
        scale = decimal_type.scale
        if scale < 0 or scale > precision:
            raise UnsupportedLogicalTypeError(
                "decimal128 requires 0 <= scale <= precision"
            )
    elif pa.types.is_timestamp(data_type):
        timestamp_type = cast(pa.TimestampType, data_type)
        type_name = "timestamp"
        timestamp_unit = timestamp_type.unit
        timezone = timestamp_type.tz
        if timestamp_unit not in {"s", "ms", "us", "ns"} or timezone != "UTC":
            raise UnsupportedLogicalTypeError(
                "Timestamps require an explicit supported unit and UTC timezone"
            )
    else:
        raise UnsupportedLogicalTypeError(
            f"Unsupported logical Arrow type: {data_type}"
        )
    return {
        "name": type_name,
        "precision": precision,
        "scale": scale,
        "timestamp_unit": timestamp_unit,
        "timezone": timezone,
    }


def logical_schema_document(
    schema: pa.Schema, ordering: OrderingSemantics
) -> JsonRecord:
    """Normalize an explicit Arrow schema without inference or metadata ambiguity."""
    if schema.metadata:
        raise LogicalDataError("Logical schema metadata is not governed")
    names: set[str] = set()
    fields: list[JsonValue] = []
    for field in schema:
        if FIELD_NAME.fullmatch(field.name) is None:
            raise LogicalDataError(f"Malformed logical field name: {field.name!r}")
        if field.name in names:
            raise LogicalDataError(f"Duplicate logical field name: {field.name!r}")
        if field.metadata:
            raise LogicalDataError("Logical field metadata is not governed")
        names.add(field.name)
        type_document = _logical_type_document(field.type)
        fields.append(
            {
                "name": field.name,
                "type": type_document,
                "nullable": field.nullable,
            }
        )
    if not fields:
        raise LogicalDataError("Logical schema must contain at least one field")
    return {
        "schema_version": "1.0.0",
        "row_ordering": ordering.value,
        "fields": fields,
    }


def logical_schema_digest(schema: pa.Schema, ordering: OrderingSemantics) -> str:
    """Identify the governed logical schema and declared row semantics."""
    return sha256_canonical_json(logical_schema_document(schema, ordering))


def _frame(content: bytes) -> bytes:
    return len(content).to_bytes(8, byteorder="big", signed=False) + content


def _canonical_decimal(value: Decimal, precision: int, scale: int) -> bytes:
    if not value.is_finite():
        raise LogicalDataError("Non-finite decimal value is forbidden")
    quantum = Decimal(1).scaleb(-scale)
    try:
        with localcontext() as context:
            context.prec = max(precision, len(value.as_tuple().digits), 40)
            normalized = value.quantize(quantum)
    except InvalidOperation as error:
        raise LogicalDataError(
            "Decimal value cannot satisfy its declared scale"
        ) from error
    if normalized != value:
        raise LogicalDataError("Decimal value exceeds its declared scale")
    if normalized == 0:
        normalized = abs(normalized)
    return format(normalized, "f").encode("ascii")


def _canonical_timestamp(ticks: int, unit: str) -> bytes:
    units = {
        "s": (1, 0),
        "ms": (1_000, 3),
        "us": (1_000_000, 6),
        "ns": (1_000_000_000, 9),
    }
    factor, digits = units[unit]
    seconds, remainder = divmod(ticks, factor)
    try:
        instant = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    except OverflowError as error:
        raise LogicalDataError(
            "Timestamp is outside normalized RFC 3339 range"
        ) from error
    base = (
        f"{instant.year:04d}-{instant.month:02d}-{instant.day:02d}T"
        f"{instant.hour:02d}:{instant.minute:02d}:{instant.second:02d}"
    )
    fraction = "" if digits == 0 else f".{remainder:0{digits}d}"
    return f"{base}{fraction}Z".encode("ascii")


def _canonical_cell(value: object, data_type: pa.DataType) -> bytes:
    if value is None:
        return b"N"
    if pa.types.is_boolean(data_type):
        return b"B\x01" if cast(bool, value) else b"B\x00"
    if pa.types.is_integer(data_type):
        return b"I" + str(cast(int, value)).encode("ascii")
    if pa.types.is_float64(data_type):
        number = cast(float, value)
        if not math.isfinite(number):
            raise LogicalDataError("NaN and Infinity are forbidden")
        return b"F" + struct.pack(">d", number)
    if pa.types.is_string(data_type):
        try:
            return b"S" + cast(str, value).encode("utf-8")
        except UnicodeEncodeError as error:
            raise LogicalDataError("String value is not valid Unicode") from error
    if pa.types.is_decimal128(data_type):
        decimal_type = cast(pa.Decimal128Type, data_type)
        return b"D" + _canonical_decimal(
            cast(Decimal, value), decimal_type.precision, decimal_type.scale
        )
    if pa.types.is_timestamp(data_type):
        timestamp_type = cast(pa.TimestampType, data_type)
        return b"T" + _canonical_timestamp(cast(int, value), timestamp_type.unit)
    raise UnsupportedLogicalTypeError(f"Unsupported logical Arrow type: {data_type}")


def _validated_rows(
    table: pa.Table,
    declared_schema: pa.Schema,
    ordering: OrderingSemantics,
) -> tuple[pa.Table, list[bytes]]:
    logical_schema_document(declared_schema, ordering)
    if not table.schema.equals(declared_schema, check_metadata=True):
        raise LogicalDataError("Table schema differs from the explicit declared schema")
    try:
        table.validate(full=True)
    except pa.ArrowInvalid as error:
        raise LogicalDataError("Arrow table validation failed") from error
    combined = table.combine_chunks()
    columns: list[list[object]] = []
    for index, field in enumerate(declared_schema):
        column = combined.column(index)
        if not field.nullable and column.null_count:
            raise LogicalDataError(
                f"Non-nullable logical field contains nulls: {field.name}"
            )
        if pa.types.is_timestamp(field.type):
            columns.append(cast(list[object], column.cast(pa.int64()).to_pylist()))
        else:
            columns.append(cast(list[object], column.to_pylist()))
    rows: list[bytes] = []
    for row_index in range(combined.num_rows):
        row = bytearray()
        for column_index, field in enumerate(declared_schema):
            cell = _canonical_cell(columns[column_index][row_index], field.type)
            row.extend(_frame(cell))
        rows.append(bytes(row))
    if ordering is OrderingSemantics.UNORDERED:
        indexed_rows = sorted(enumerate(rows), key=lambda item: item[1])
        indices = [index for index, _row in indexed_rows]
        rows = [row for _index, row in indexed_rows]
        combined = combined.take(pa.array(indices, type=pa.int64()))
    return combined, rows


def canonical_logical_table_bytes(
    table: pa.Table,
    declared_schema: pa.Schema,
    ordering: OrderingSemantics,
) -> bytes:
    """Frame schema and normalized rows into a platform-independent identity stream."""
    _combined, rows = _validated_rows(table, declared_schema, ordering)
    schema_bytes = canonicalize_json(logical_schema_document(declared_schema, ordering))
    result = bytearray(LOGICAL_FRAMING_MAGIC)
    result.extend(_frame(schema_bytes))
    result.extend(len(rows).to_bytes(8, byteorder="big", signed=False))
    for row in rows:
        result.extend(_frame(row))
    return bytes(result)


def logical_content_fingerprint(
    table: pa.Table,
    declared_schema: pa.Schema,
    ordering: OrderingSemantics,
) -> str:
    """Hash normalized logical schema and rows, independent of Parquet encoding."""
    return sha256_bytes(canonical_logical_table_bytes(table, declared_schema, ordering))


def deterministic_parquet_bytes(
    table: pa.Table,
    declared_schema: pa.Schema,
    ordering: OrderingSemantics,
    profile: ParquetWriterProfile = DEFAULT_PARQUET_PROFILE,
) -> bytes:
    """Write exact Parquet bytes using only the complete governed profile."""
    profile.document()
    ordered_table, _rows = _validated_rows(table, declared_schema, ordering)
    sink = pa.BufferOutputStream()
    pq.write_table(
        ordered_table,
        sink,
        row_group_size=profile.row_group_size,
        version=profile.parquet_version,
        use_dictionary=profile.use_dictionary,
        compression=profile.compression,
        write_statistics=profile.write_statistics,
        use_deprecated_int96_timestamps=False,
        coerce_timestamps=None,
        allow_truncated_timestamps=False,
        data_page_size=profile.data_page_size,
        flavor=None,
        filesystem=None,
        compression_level=profile.compression_level,
        use_byte_stream_split=profile.use_byte_stream_split,
        column_encoding=None,
        data_page_version=profile.data_page_version,
        use_compliant_nested_type=profile.use_compliant_nested_type,
        encryption_properties=None,
        write_batch_size=profile.write_batch_size,
        dictionary_pagesize_limit=profile.dictionary_pagesize_limit,
        store_schema=profile.store_schema,
        write_page_index=profile.write_page_index,
        write_page_checksum=profile.write_page_checksum,
        sorting_columns=None,
        store_decimal_as_integer=profile.store_decimal_as_integer,
        write_time_adjusted_to_utc=profile.write_time_adjusted_to_utc,
        max_rows_per_page=None,
        bloom_filter_options=None,
    )
    return cast(bytes, sink.getvalue().to_pybytes())


def _normalize_parent_evidence(
    parents: Sequence[ParentEvidence], ordering: OrderingSemantics
) -> tuple[ParentEvidence, ...]:
    normalized = tuple(parents)
    documents = [parent.document() for parent in normalized]
    identities = [parent.dataset_id for parent in parents]
    if len(identities) != len(set(identities)):
        raise DerivedDataError("Parent dataset identities must be unique")
    if ordering is OrderingSemantics.UNORDERED:
        normalized = tuple(
            parent
            for _document, parent in sorted(
                zip(documents, normalized, strict=True),
                key=lambda item: canonicalize_json(item[0]),
            )
        )
    return normalized


def _ordered_parent_documents(
    parents: Sequence[ParentEvidence], ordering: OrderingSemantics
) -> list[JsonValue]:
    return cast(
        list[JsonValue],
        [parent.document() for parent in _normalize_parent_evidence(parents, ordering)],
    )


def _require_distinct_identities(
    physical_digest: str, lineage_digest: str, logical_fingerprint: str
) -> None:
    if len({physical_digest, lineage_digest, logical_fingerprint}) != 3:
        raise DerivedDataIntegrityError(
            "Physical, lineage, and logical identities must remain distinct"
        )


def _require_derived_claim(
    field: str, observed: JsonValue | object, expected: JsonValue | object
) -> None:
    if observed != expected:
        raise DerivedDataIntegrityError(
            f"Derived provenance claim differs across evidence: {field}"
        )


def _require_record_claim(
    field: str, observed: JsonValue | object, expected: JsonValue | object
) -> None:
    if observed != expected:
        raise DatasetBindingError(f"Dataset {field} does not match lineage evidence")


def _validated_derived_manifest_documents(
    *,
    catalog: VersionedSchemaCatalog,
    evidence: DerivedDatasetEvidence,
) -> tuple[JsonRecord, JsonRecord]:
    """Validate each manifest and require agreement on every shared claim."""
    evidence.artifact_manifest.verify()
    evidence.lineage_manifest.verify()
    verify_artifact_binding(evidence.artifact_manifest, evidence.parquet_object)
    if evidence.artifact_manifest_object.digest != evidence.artifact_manifest.digest:
        raise DerivedDataIntegrityError("Physical artifact sidecar identity mismatch")
    if evidence.lineage_manifest_object.digest != evidence.lineage_manifest.digest:
        raise DerivedDataIntegrityError("Lineage object identity mismatch")

    artifact_document = evidence.artifact_manifest.document
    lineage_document = evidence.lineage_manifest.document
    catalog.validate(ARTIFACT_MANIFEST_SCHEMA, artifact_document)
    catalog.validate(LINEAGE_MANIFEST_SCHEMA, lineage_document)

    if lineage_document.get("logical_schema") != logical_schema_document(
        evidence.declared_schema, evidence.row_ordering
    ):
        raise DerivedDataIntegrityError(
            "Lineage logical schema does not match evidence"
        )
    if lineage_document.get("writer_profile") != evidence.writer_profile.document():
        raise DerivedDataIntegrityError(
            "Lineage writer profile does not match evidence"
        )
    parent_documents = _ordered_parent_documents(
        evidence.parent_evidence, evidence.parent_ordering
    )
    if lineage_document.get("parent_evidence") != parent_documents:
        raise DerivedDataIntegrityError(
            "Lineage parent evidence does not match evidence"
        )
    if lineage_document.get("parent_ordering") != evidence.parent_ordering.value:
        raise DerivedDataIntegrityError(
            "Lineage parent ordering does not match evidence"
        )
    expected_lineage = {
        "dataset_id": evidence.dataset_id,
        "layer": evidence.layer.value,
        "physical_object_digest": evidence.parquet_object.digest,
        "physical_artifact_manifest_digest": evidence.artifact_manifest.digest,
        "schema_digest": evidence.schema_digest,
        "logical_content_fingerprint": evidence.logical_content_fingerprint,
        "row_ordering": evidence.row_ordering.value,
        "writer_profile_digest": evidence.writer_profile_digest,
        "quality_disposition": evidence.quality_disposition.value,
    }
    for field, expected in expected_lineage.items():
        _require_derived_claim(field, lineage_document.get(field), expected)

    artifact_producer = artifact_document.get("producer")
    artifact_provenance = artifact_document.get("provenance")
    lineage_producer = lineage_document.get("producer")
    transformation = lineage_document.get("transformation")
    if not all(
        isinstance(value, dict)
        for value in (
            artifact_producer,
            artifact_provenance,
            lineage_producer,
            transformation,
        )
    ):
        raise DerivedDataIntegrityError("Derived provenance metadata is malformed")
    artifact_producer = cast(JsonRecord, artifact_producer)
    artifact_provenance = cast(JsonRecord, artifact_provenance)
    lineage_producer = cast(JsonRecord, lineage_producer)
    transformation = cast(JsonRecord, transformation)
    parent_dataset_ids = [parent.dataset_id for parent in evidence.parent_evidence]
    parent_physical_digests = list(
        dict.fromkeys(
            parent.physical_object_digest for parent in evidence.parent_evidence
        )
    )
    shared_claims: tuple[tuple[str, JsonValue | object, JsonValue | object], ...] = (
        (
            "physical_object_digest",
            artifact_document.get("artifact_digest"),
            lineage_document.get("physical_object_digest"),
        ),
        (
            "created_at",
            artifact_document.get("created_at"),
            lineage_document.get("created_at"),
        ),
        (
            "producer.code_revision",
            artifact_producer.get("code_revision"),
            lineage_producer.get("code_revision"),
        ),
        (
            "producer.environment_digest",
            artifact_producer.get("environment_digest"),
            lineage_producer.get("environment_digest"),
        ),
        (
            "source_ids",
            artifact_provenance.get("source_ids"),
            lineage_document.get("source_ids"),
        ),
        (
            "parent_dataset_ids",
            artifact_provenance.get("dataset_ids"),
            parent_dataset_ids,
        ),
        (
            "parent_physical_digests",
            artifact_document.get("parent_digests"),
            parent_physical_digests,
        ),
        (
            "references",
            artifact_provenance.get("references"),
            lineage_document.get("references"),
        ),
        (
            "transformation.configuration_digest",
            artifact_provenance.get("configuration_digest"),
            transformation.get("configuration_digest"),
        ),
    )
    for field, artifact_value, lineage_value in shared_claims:
        _require_derived_claim(field, artifact_value, lineage_value)
    return artifact_document, lineage_document


def build_dataset_lineage_manifest(
    *,
    catalog: VersionedSchemaCatalog,
    dataset_id: str,
    layer: DerivedLayer,
    created_at: str,
    physical_object_digest: str,
    physical_artifact_manifest_digest: str,
    schema_document: Mapping[str, JsonValue],
    schema_digest: str,
    logical_fingerprint: str,
    row_ordering: OrderingSemantics,
    writer_profile: ParquetWriterProfile,
    parent_evidence: Sequence[ParentEvidence],
    parent_ordering: OrderingSemantics,
    transformation_identity: str,
    transformation_configuration_digest: str,
    producer: ArtifactProducer,
    source_ids: Sequence[str],
    references: Sequence[str],
    quality_disposition: QualityDisposition,
) -> DatasetLineageManifest:
    """Build the non-circular canonical provenance identity for a derived table."""
    validate_typed_id(dataset_id, RegistryKind.DATASET)
    for source_id in source_ids:
        validate_typed_id(source_id, RegistryKind.SOURCE)
    for digest in (
        physical_object_digest,
        physical_artifact_manifest_digest,
        schema_digest,
        logical_fingerprint,
        transformation_configuration_digest,
        producer.environment_digest,
    ):
        require_sha256_digest(digest)
    normalized_schema = dict(schema_document)
    if sha256_canonical_json(normalized_schema) != schema_digest:
        raise DerivedDataError("Logical schema digest does not match its document")
    if normalized_schema.get("row_ordering") != row_ordering.value:
        raise DerivedDataError("Logical schema row ordering does not match lineage")
    profile_document = writer_profile.document()
    profile_digest = sha256_canonical_json(profile_document)
    reject_secret_text(transformation_identity, "transformation identity")
    for reference in references:
        reject_credential_uri(reference)
        reject_secret_text(reference, "lineage reference")
    parent_values = _ordered_parent_documents(parent_evidence, parent_ordering)
    source_values: list[JsonValue] = list(source_ids)
    reference_values: list[JsonValue] = list(references)
    document: JsonRecord = {
        "schema_version": "1.0.0",
        "dataset_id": dataset_id,
        "layer": layer.value,
        "created_at": created_at,
        "physical_object_digest": physical_object_digest,
        "physical_artifact_manifest_digest": physical_artifact_manifest_digest,
        "logical_schema": normalized_schema,
        "schema_digest": schema_digest,
        "logical_content_fingerprint": logical_fingerprint,
        "row_ordering": row_ordering.value,
        "writer_profile": profile_document,
        "writer_profile_digest": profile_digest,
        "parent_ordering": parent_ordering.value,
        "parent_evidence": parent_values,
        "transformation": {
            "identity": transformation_identity,
            "configuration_digest": transformation_configuration_digest,
        },
        "producer": {
            "code_revision": producer.code_revision,
            "environment_digest": producer.environment_digest,
        },
        "source_ids": source_values,
        "references": reference_values,
        "quality_disposition": quality_disposition.value,
    }
    reject_credential_shaped_fields(document)
    catalog.validate(LINEAGE_MANIFEST_SCHEMA, document)
    canonical_bytes = canonicalize_json(document)
    manifest = DatasetLineageManifest(canonical_bytes, sha256_bytes(canonical_bytes))
    manifest.verify()
    return manifest


def publish_derived_table(
    *,
    store: ImmutableObjectStore,
    catalog: VersionedSchemaCatalog,
    table: pa.Table,
    declared_schema: pa.Schema,
    dataset_id: str,
    layer: DerivedLayer,
    row_ordering: OrderingSemantics,
    parent_evidence: Sequence[ParentEvidence],
    parent_ordering: OrderingSemantics,
    transformation_identity: str,
    transformation_configuration_digest: str,
    created_at: str,
    producer: ArtifactProducer,
    source_ids: Sequence[str],
    quality_disposition: QualityDisposition,
    references: Sequence[str] = (),
    writer_profile: ParquetWriterProfile = DEFAULT_PARQUET_PROFILE,
) -> DerivedDatasetEvidence:
    """Publish Parquet, physical sidecar, and canonical lineage as immutable objects."""
    validate_typed_id(dataset_id, RegistryKind.DATASET)
    normalized_parents = _normalize_parent_evidence(parent_evidence, parent_ordering)
    reject_secret_text(transformation_identity, "transformation identity")
    schema_document = logical_schema_document(declared_schema, row_ordering)
    schema_digest = sha256_canonical_json(schema_document)
    fingerprint = logical_content_fingerprint(table, declared_schema, row_ordering)
    parquet_bytes = deterministic_parquet_bytes(
        table, declared_schema, row_ordering, writer_profile
    )
    parquet_object = store.publish(parquet_bytes)
    parent_ids = tuple(parent.dataset_id for parent in normalized_parents)
    parent_digests = tuple(
        dict.fromkeys(parent.physical_object_digest for parent in normalized_parents)
    )
    artifact_manifest = build_artifact_manifest(
        store=store,
        catalog=catalog,
        stored_object=parquet_object,
        artifact_type="dataset",
        media_type="application/vnd.apache.parquet",
        created_at=created_at,
        producer=producer,
        provenance=ArtifactProvenance(
            source_ids=tuple(source_ids),
            dataset_ids=parent_ids,
            references=tuple(references),
            configuration_digest=transformation_configuration_digest,
        ),
        parent_digests=parent_digests,
    )
    artifact_manifest_object = publish_artifact_manifest(store, artifact_manifest)
    lineage_manifest = build_dataset_lineage_manifest(
        catalog=catalog,
        dataset_id=dataset_id,
        layer=layer,
        created_at=created_at,
        physical_object_digest=parquet_object.digest,
        physical_artifact_manifest_digest=artifact_manifest.digest,
        schema_document=schema_document,
        schema_digest=schema_digest,
        logical_fingerprint=fingerprint,
        row_ordering=row_ordering,
        writer_profile=writer_profile,
        parent_evidence=normalized_parents,
        parent_ordering=parent_ordering,
        transformation_identity=transformation_identity,
        transformation_configuration_digest=transformation_configuration_digest,
        producer=producer,
        source_ids=source_ids,
        references=references,
        quality_disposition=quality_disposition,
    )
    lineage_object = store.publish(lineage_manifest.canonical_bytes)
    evidence = DerivedDatasetEvidence(
        dataset_id=dataset_id,
        layer=layer,
        quality_disposition=quality_disposition,
        row_ordering=row_ordering,
        parent_ordering=parent_ordering,
        declared_schema=declared_schema,
        writer_profile=writer_profile,
        parent_evidence=normalized_parents,
        parquet_object=parquet_object,
        artifact_manifest=artifact_manifest,
        artifact_manifest_object=artifact_manifest_object,
        lineage_manifest=lineage_manifest,
        lineage_manifest_object=lineage_object,
        schema_digest=schema_digest,
        logical_content_fingerprint=fingerprint,
        writer_profile_digest=parquet_writer_profile_digest(writer_profile),
    )
    _require_distinct_identities(
        evidence.parquet_object.digest,
        evidence.lineage_manifest.digest,
        evidence.logical_content_fingerprint,
    )
    verify_derived_dataset_evidence(store=store, catalog=catalog, evidence=evidence)
    return evidence


def verify_derived_dataset_evidence(
    *,
    store: ImmutableObjectStore,
    catalog: VersionedSchemaCatalog,
    evidence: DerivedDatasetEvidence,
) -> None:
    """Verify all identities and decode Parquet to recheck its logical binding."""
    _require_distinct_identities(
        evidence.parquet_object.digest,
        evidence.lineage_manifest.digest,
        evidence.logical_content_fingerprint,
    )
    for stored in (
        evidence.parquet_object,
        evidence.artifact_manifest_object,
        evidence.lineage_manifest_object,
    ):
        store.verify(stored)
    _validated_derived_manifest_documents(catalog=catalog, evidence=evidence)
    parquet_bytes = store.read_bytes(evidence.parquet_object.digest)
    try:
        observed_table = pq.read_table(pa.BufferReader(parquet_bytes))
    except (pa.ArrowInvalid, OSError) as error:
        raise DerivedDataIntegrityError(
            "Published Parquet cannot be decoded"
        ) from error
    observed_fingerprint = logical_content_fingerprint(
        observed_table, evidence.declared_schema, evidence.row_ordering
    )
    if observed_fingerprint != evidence.logical_content_fingerprint:
        raise DerivedDataIntegrityError("Parquet logical fingerprint mismatch")
    if (
        logical_schema_digest(evidence.declared_schema, evidence.row_ordering)
        != evidence.schema_digest
    ):
        raise DerivedDataIntegrityError("Logical schema digest mismatch")
    if (
        parquet_writer_profile_digest(evidence.writer_profile)
        != evidence.writer_profile_digest
    ):
        raise DerivedDataIntegrityError("Writer profile digest mismatch")


def verify_dataset_record_binding(
    *,
    catalog: VersionedSchemaCatalog,
    record: Mapping[str, JsonValue],
    evidence: DerivedDatasetEvidence,
) -> None:
    """Bind the existing v1 dataset vocabulary to all three derived identities."""
    catalog.validate(DATASET_SCHEMA, record)
    _require_distinct_identities(
        evidence.parquet_object.digest,
        evidence.lineage_manifest.digest,
        evidence.logical_content_fingerprint,
    )
    _artifact_document, lineage = _validated_derived_manifest_documents(
        catalog=catalog, evidence=evidence
    )
    expected = {
        "dataset_id": evidence.dataset_id,
        "created_at": lineage.get("created_at"),
        "layer": evidence.layer.value,
        "source_ids": lineage.get("source_ids"),
        "schema_digest": evidence.schema_digest,
        "physical_object_digest": evidence.parquet_object.digest,
        "provenance_lineage_digest": evidence.lineage_manifest.digest,
        "logical_content_fingerprint": evidence.logical_content_fingerprint,
        "quality_status": evidence.quality_disposition.value,
    }
    for field, expected_value in expected.items():
        _require_record_claim(field, record.get(field), expected_value)
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        raise DatasetBindingError("Dataset provenance is not an object")
    transformation = lineage.get("transformation")
    producer = lineage.get("producer")
    if not isinstance(transformation, dict) or not isinstance(producer, dict):
        raise DerivedDataIntegrityError("Lineage production metadata is malformed")
    expected_provenance: dict[str, JsonValue] = {
        "parent_dataset_ids": [
            parent.dataset_id for parent in evidence.parent_evidence
        ],
        "transformation": transformation.get("identity"),
        "code_revision": producer.get("code_revision"),
        "environment_digest": producer.get("environment_digest"),
    }
    for field, provenance_value in expected_provenance.items():
        _require_record_claim(
            f"provenance {field}", provenance.get(field), provenance_value
        )
