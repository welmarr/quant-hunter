"""Deterministic Parquet and independent three-digest derived-data tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from quant_hunter.config import JsonRecord
from quant_hunter.config.schema import RecordSchemaError, VersionedSchemaCatalog
from quant_hunter.data import (
    DEFAULT_PARQUET_PROFILE,
    DatasetBindingError,
    DerivedDataError,
    DerivedDataIntegrityError,
    DerivedDatasetEvidence,
    DerivedLayer,
    LogicalDataError,
    OrderingSemantics,
    ParentEvidence,
    ParquetWriterProfile,
    UnsupportedLogicalTypeError,
    build_dataset_lineage_manifest,
    canonical_logical_table_bytes,
    deterministic_parquet_bytes,
    logical_content_fingerprint,
    logical_schema_digest,
    logical_schema_document,
    parquet_writer_profile_digest,
    publish_derived_table,
    verify_dataset_record_binding,
    verify_derived_dataset_evidence,
)
from quant_hunter.provenance import sha256_bytes, sha256_canonical_json
from quant_hunter.storage import (
    ArtifactProducer,
    ImmutableObjectStore,
    ObjectCorruptionError,
    QualityDisposition,
    SensitiveMetadataError,
)

SCHEMA_DIRECTORY = Path(__file__).parents[1] / "schemas" / "v1"
SOURCE_ID = "SOURCE-01990f30-7f5e-7b34-9b21-3d74c513c841"
DATASET_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c842"
PARENT_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c843"
SECOND_PARENT_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c844"
CONFIGURATION_DIGEST = "sha256:" + "c" * 64
ENVIRONMENT_DIGEST = "sha256:" + "b" * 64
CREATED_AT = "2026-09-05T12:00:00Z"


def synthetic_schema() -> pa.Schema:
    """Return an explicit schema spanning the governed logical types."""
    return pa.schema(
        [
            pa.field("instrument", pa.string(), nullable=False),
            pa.field("sequence", pa.int64(), nullable=False),
            pa.field("value", pa.float64(), nullable=False),
            pa.field("amount", pa.decimal128(12, 4), nullable=True),
            pa.field("observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("active", pa.bool_(), nullable=False),
        ]
    )


def synthetic_rows() -> list[dict[str, object]]:
    """Return synthetic rows with no market meaning or external provenance."""
    return [
        {
            "instrument": "SYNTH-A",
            "sequence": 1,
            "value": 1.5,
            "amount": Decimal("12.3400"),
            "observed_at": datetime(2026, 1, 1, 0, 0, 1, 123456, tzinfo=UTC),
            "active": True,
        },
        {
            "instrument": "SYNTH-B",
            "sequence": 2,
            "value": -0.25,
            "amount": None,
            "observed_at": datetime(2026, 1, 1, 0, 0, 2, 654321, tzinfo=UTC),
            "active": False,
        },
        {
            "instrument": "SYNTH-C",
            "sequence": 3,
            "value": 7.0,
            "amount": Decimal("0.0100"),
            "observed_at": datetime(2026, 1, 1, 0, 0, 3, tzinfo=UTC),
            "active": True,
        },
    ]


def synthetic_table(rows: list[dict[str, object]] | None = None) -> pa.Table:
    schema = synthetic_schema()
    return pa.Table.from_pylist(rows or synthetic_rows(), schema=schema)


def parent_evidence(dataset_id: str = PARENT_ID, marker: str = "1") -> ParentEvidence:
    return ParentEvidence(
        dataset_id=dataset_id,
        registry_revision_digest="sha256:" + marker * 64,
        physical_object_digest="sha256:" + "2" * 64,
        provenance_lineage_digest="sha256:" + "3" * 64,
        logical_content_fingerprint="sha256:" + "4" * 64,
    )


def publish(
    tmp_path: Path,
    *,
    table: pa.Table | None = None,
    schema: pa.Schema | None = None,
    row_ordering: OrderingSemantics = OrderingSemantics.ORDERED,
    parent_ordering: OrderingSemantics = OrderingSemantics.ORDERED,
    parents: tuple[ParentEvidence, ...] | None = None,
    profile: ParquetWriterProfile = DEFAULT_PARQUET_PROFILE,
    quality: QualityDisposition = QualityDisposition.APPROVED,
) -> tuple[ImmutableObjectStore, VersionedSchemaCatalog, DerivedDatasetEvidence]:
    store = ImmutableObjectStore(tmp_path / "artifacts")
    catalog = VersionedSchemaCatalog(SCHEMA_DIRECTORY)
    declared_schema = schema or synthetic_schema()
    evidence = publish_derived_table(
        store=store,
        catalog=catalog,
        table=table or synthetic_table(),
        declared_schema=declared_schema,
        dataset_id=DATASET_ID,
        layer=DerivedLayer.NORMALIZED,
        row_ordering=row_ordering,
        parent_evidence=parents or (parent_evidence(),),
        parent_ordering=parent_ordering,
        transformation_identity="synthetic-normalization-v1",
        transformation_configuration_digest=CONFIGURATION_DIGEST,
        created_at=CREATED_AT,
        producer=ArtifactProducer(
            "a" * 40, "synthetic-derived-build", ENVIRONMENT_DIGEST
        ),
        source_ids=(SOURCE_ID,),
        quality_disposition=quality,
        references=("synthetic://derived/lineage",),
        writer_profile=profile,
    )
    return store, catalog, evidence


def dataset_record(evidence: DerivedDatasetEvidence) -> JsonRecord:
    """Build a synthetic existing-vocabulary dataset registry record."""
    return {
        "schema_version": "1.0.0",
        "dataset_id": evidence.dataset_id,
        "revision": 1,
        "previous_revision_digest": None,
        "created_at": CREATED_AT,
        "layer": evidence.layer.value,
        "source_ids": [SOURCE_ID],
        "coverage": {
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-02T00:00:00Z",
        },
        "time_fields": {
            "event_time": "NOT_APPLICABLE",
            "publication_time": "NOT_APPLICABLE",
            "ingestion_time": "NOT_APPLICABLE",
            "revision_time": "NOT_APPLICABLE",
        },
        "schema_digest": evidence.schema_digest,
        "physical_object_digest": evidence.parquet_object.digest,
        "provenance_lineage_digest": evidence.lineage_manifest.digest,
        "logical_content_fingerprint": evidence.logical_content_fingerprint,
        "provenance": {
            "parent_dataset_ids": [
                parent.dataset_id for parent in evidence.parent_evidence
            ],
            "transformation": "synthetic-normalization-v1",
            "code_revision": "a" * 40,
            "environment_digest": ENVIRONMENT_DIGEST,
        },
        "quality_status": evidence.quality_disposition.value,
    }


def rebuild_lineage(
    catalog: VersionedSchemaCatalog,
    evidence: DerivedDatasetEvidence,
    *,
    parents: tuple[ParentEvidence, ...] | None = None,
    parent_ordering: OrderingSemantics | None = None,
    configuration_digest: str = CONFIGURATION_DIGEST,
    producer: ArtifactProducer | None = None,
    profile: ParquetWriterProfile | None = None,
    quality: QualityDisposition | None = None,
    schema_document: JsonRecord | None = None,
    schema_digest: str | None = None,
    logical_fingerprint: str | None = None,
) -> str:
    logical_document = schema_document or logical_schema_document(
        evidence.declared_schema, evidence.row_ordering
    )
    manifest = build_dataset_lineage_manifest(
        catalog=catalog,
        dataset_id=evidence.dataset_id,
        layer=evidence.layer,
        created_at=CREATED_AT,
        physical_object_digest=evidence.parquet_object.digest,
        physical_artifact_manifest_digest=evidence.artifact_manifest.digest,
        schema_document=logical_document,
        schema_digest=schema_digest or sha256_canonical_json(logical_document),
        logical_fingerprint=logical_fingerprint or evidence.logical_content_fingerprint,
        row_ordering=evidence.row_ordering,
        writer_profile=profile or evidence.writer_profile,
        parent_evidence=parents or evidence.parent_evidence,
        parent_ordering=parent_ordering or evidence.parent_ordering,
        transformation_identity="synthetic-normalization-v1",
        transformation_configuration_digest=configuration_digest,
        producer=producer
        or ArtifactProducer("a" * 40, "synthetic", ENVIRONMENT_DIGEST),
        source_ids=(SOURCE_ID,),
        references=("synthetic://derived/lineage",),
        quality_disposition=quality or evidence.quality_disposition,
    )
    return manifest.digest


def test_logical_schema_serialization_is_explicit_and_deterministic() -> None:
    schema = synthetic_schema()

    first = logical_schema_document(schema, OrderingSemantics.ORDERED)
    second = logical_schema_document(schema, OrderingSemantics.ORDERED)

    assert first == second
    assert first["row_ordering"] == "ORDERED"
    fields = first["fields"]
    assert isinstance(fields, list)
    assert all(isinstance(field, dict) for field in fields)
    field_records = cast(list[JsonRecord], fields)
    assert [field["name"] for field in field_records] == [
        "instrument",
        "sequence",
        "value",
        "amount",
        "observed_at",
        "active",
    ]
    amount_type = field_records[3]["type"]
    timestamp_type = field_records[4]["type"]
    assert amount_type == {
        "name": "decimal128",
        "precision": 12,
        "scale": 4,
        "timestamp_unit": None,
        "timezone": None,
    }
    assert timestamp_type == {
        "name": "timestamp",
        "precision": None,
        "scale": None,
        "timestamp_unit": "us",
        "timezone": "UTC",
    }
    assert logical_schema_digest(schema, OrderingSemantics.ORDERED) == (
        logical_schema_digest(schema, OrderingSemantics.ORDERED)
    )
    assert logical_schema_digest(schema, OrderingSemantics.ORDERED) == (
        "sha256:05b4891ead5ca884ec4cb44c5ba3685c37ef8ca1c009a5c84a6524c575f396f3"
    )
    assert logical_schema_digest(schema, OrderingSemantics.ORDERED) != (
        logical_schema_digest(schema, OrderingSemantics.UNORDERED)
    )


def test_writer_profile_is_complete_stable_and_rejects_invalid_options() -> None:
    document = DEFAULT_PARQUET_PROFILE.document()

    assert document["library"] == "pyarrow"
    assert document["library_version"] == "25.0.1"
    assert document["parquet_version"] == "2.6"
    assert document["timestamp_coercion"] is None
    assert document["metadata_policy"] == "REJECT_INPUT_WRITE_ARROW_SCHEMA_ONLY"
    assert parquet_writer_profile_digest(DEFAULT_PARQUET_PROFILE) == (
        parquet_writer_profile_digest(DEFAULT_PARQUET_PROFILE)
    )
    assert parquet_writer_profile_digest(DEFAULT_PARQUET_PROFILE) == (
        "sha256:f6645268358504e54a6c2d0ffea4560e5a624f78a327315921c380767b5c61db"
    )

    invalid_profiles = [
        replace(DEFAULT_PARQUET_PROFILE, row_group_size=0),
        replace(DEFAULT_PARQUET_PROFILE, compression="snappy"),
        replace(DEFAULT_PARQUET_PROFILE, compression="NONE", compression_level=9),
        replace(DEFAULT_PARQUET_PROFILE, compression_level=20),
        replace(DEFAULT_PARQUET_PROFILE, parquet_version="1.0"),
        replace(DEFAULT_PARQUET_PROFILE, data_page_version="3.0"),
        replace(DEFAULT_PARQUET_PROFILE, write_statistics=1),  # type: ignore[arg-type]
    ]
    for profile in invalid_profiles:
        with pytest.raises(DerivedDataError):
            profile.document()


def test_repeated_parquet_write_and_publication_are_exactly_stable(
    tmp_path: Path,
) -> None:
    table = synthetic_table()
    schema = synthetic_schema()

    first_bytes = deterministic_parquet_bytes(table, schema, OrderingSemantics.ORDERED)
    second_bytes = deterministic_parquet_bytes(table, schema, OrderingSemantics.ORDERED)
    first_store, _catalog, first = publish(tmp_path / "first")
    second_store, _catalog, second = publish(tmp_path / "second")

    assert first_bytes == second_bytes
    assert first_bytes.startswith(b"PAR1") and first_bytes.endswith(b"PAR1")
    assert sha256_bytes(first_bytes) == first.parquet_object.digest
    assert first.parquet_object.digest == second.parquet_object.digest
    assert first_store.read_bytes(first.parquet_object.digest) == first_bytes
    assert second_store.read_bytes(second.parquet_object.digest) == second_bytes


def test_different_physical_profiles_preserve_logical_identity(tmp_path: Path) -> None:
    uncompressed = replace(
        DEFAULT_PARQUET_PROFILE,
        profile_name="qh-parquet-v1-uncompressed",
        compression="NONE",
        compression_level=None,
    )
    table = synthetic_table()
    schema = synthetic_schema()
    zstd_bytes = deterministic_parquet_bytes(
        table, schema, OrderingSemantics.ORDERED, DEFAULT_PARQUET_PROFILE
    )
    plain_bytes = deterministic_parquet_bytes(
        table, schema, OrderingSemantics.ORDERED, uncompressed
    )
    _store, _catalog, zstd = publish(tmp_path / "zstd")
    _store, _catalog, plain = publish(tmp_path / "plain", profile=uncompressed)

    assert zstd_bytes != plain_bytes
    assert sha256_bytes(zstd_bytes) != sha256_bytes(plain_bytes)
    assert zstd.logical_content_fingerprint == plain.logical_content_fingerprint
    assert zstd.parquet_object.digest != plain.parquet_object.digest
    assert zstd.lineage_manifest.digest != plain.lineage_manifest.digest


def test_logical_value_schema_order_and_multiplicity_change_identity() -> None:
    schema = synthetic_schema()
    rows = synthetic_rows()
    base = synthetic_table(rows)
    changed_rows = deepcopy(rows)
    changed_rows[0]["value"] = 1.5000000000000002
    changed = synthetic_table(changed_rows)
    permuted = synthetic_table(list(reversed(rows)))
    duplicated = synthetic_table([*rows, deepcopy(rows[0])])
    changed_schema = pa.schema(
        [
            *list(schema)[:-1],
            pa.field("active", pa.bool_(), nullable=True),
        ]
    )
    changed_schema_table = pa.Table.from_pylist(rows, schema=changed_schema)

    ordered = logical_content_fingerprint(base, schema, OrderingSemantics.ORDERED)
    unordered = logical_content_fingerprint(base, schema, OrderingSemantics.UNORDERED)

    assert ordered == (
        "sha256:c831053fa0bf39456c923ceb4efe5df57393c52293f8eb4f67c07d7e87271b58"
    )
    assert unordered == (
        "sha256:b27c9197d2f278754c39c69a2d8c8fc7dce6fcc034199aebc15a59bb5d9000ad"
    )
    assert ordered != logical_content_fingerprint(
        changed, schema, OrderingSemantics.ORDERED
    )
    assert ordered != logical_content_fingerprint(
        changed_schema_table, changed_schema, OrderingSemantics.ORDERED
    )
    assert ordered != logical_content_fingerprint(
        permuted, schema, OrderingSemantics.ORDERED
    )
    assert unordered == logical_content_fingerprint(
        permuted, schema, OrderingSemantics.UNORDERED
    )
    assert unordered != logical_content_fingerprint(
        duplicated, schema, OrderingSemantics.UNORDERED
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_values_are_rejected(value: float) -> None:
    schema = pa.schema([pa.field("value", pa.float64(), nullable=False)])
    table = pa.Table.from_arrays([pa.array([value], type=pa.float64())], schema=schema)

    with pytest.raises(LogicalDataError, match="NaN and Infinity"):
        logical_content_fingerprint(table, schema, OrderingSemantics.ORDERED)
    with pytest.raises(LogicalDataError, match="NaN and Infinity"):
        deterministic_parquet_bytes(table, schema, OrderingSemantics.ORDERED)


@pytest.mark.parametrize(
    "data_type",
    [pa.float32(), pa.binary(), pa.list_(pa.int64()), pa.large_string(), pa.date32()],
)
def test_unsupported_types_are_rejected(data_type: pa.DataType) -> None:
    schema = pa.schema([pa.field("value", data_type)])
    with pytest.raises(UnsupportedLogicalTypeError):
        logical_schema_document(schema, OrderingSemantics.ORDERED)


def test_ambiguous_schema_and_nullability_are_rejected() -> None:
    with pytest.raises(UnsupportedLogicalTypeError, match="UTC timezone"):
        logical_schema_document(
            pa.schema([pa.field("observed_at", pa.timestamp("us"))]),
            OrderingSemantics.ORDERED,
        )
    with pytest.raises(UnsupportedLogicalTypeError, match="scale"):
        logical_schema_document(
            pa.schema([pa.field("amount", pa.decimal128(12, -1))]),
            OrderingSemantics.ORDERED,
        )
    with pytest.raises(LogicalDataError, match="metadata"):
        logical_schema_document(
            pa.schema([pa.field("value", pa.int64())], metadata={b"x": b"y"}),
            OrderingSemantics.ORDERED,
        )
    with pytest.raises(LogicalDataError, match="field metadata"):
        logical_schema_document(
            pa.schema([pa.field("value", pa.int64(), metadata={b"x": b"y"})]),
            OrderingSemantics.ORDERED,
        )
    with pytest.raises(LogicalDataError, match="Duplicate"):
        logical_schema_document(
            pa.schema([pa.field("value", pa.int64()), pa.field("value", pa.int64())]),
            OrderingSemantics.ORDERED,
        )
    with pytest.raises(LogicalDataError, match="at least one"):
        logical_schema_document(pa.schema([]), OrderingSemantics.ORDERED)

    declared = pa.schema([pa.field("value", pa.int64(), nullable=False)])
    inferred = pa.table({"value": [1]})
    with pytest.raises(LogicalDataError, match="explicit declared schema"):
        logical_content_fingerprint(inferred, declared, OrderingSemantics.ORDERED)
    nullable_data = pa.Table.from_arrays(
        [pa.array([None], type=pa.int64())], schema=declared
    )
    with pytest.raises(LogicalDataError, match="Non-nullable"):
        logical_content_fingerprint(nullable_data, declared, OrderingSemantics.ORDERED)


def test_decimal_and_timestamp_values_have_normalized_canonical_forms() -> None:
    schema = pa.schema(
        [
            pa.field("amount", pa.decimal128(8, 4), nullable=False),
            pa.field("observed_at", pa.timestamp("ns", tz="UTC"), nullable=False),
        ]
    )
    table = pa.Table.from_arrays(
        [
            pa.array([Decimal("12.3400")], type=pa.decimal128(8, 4)),
            pa.array([1], type=pa.timestamp("ns", tz="UTC")),
        ],
        schema=schema,
    )

    canonical = canonical_logical_table_bytes(table, schema, OrderingSemantics.ORDERED)

    assert b"D12.3400" in canonical
    assert b"T1970-01-01T00:00:00.000000001Z" in canonical


def test_lineage_digest_is_stable_and_changes_for_every_material_input(
    tmp_path: Path,
) -> None:
    _store, catalog, evidence = publish(tmp_path)
    baseline = rebuild_lineage(catalog, evidence)
    changed_parent = replace(
        parent_evidence(), physical_object_digest="sha256:" + "5" * 64
    )
    changed_arrow_schema = pa.schema(
        [
            pa.field("instrument", pa.string(), nullable=True),
            *list(synthetic_schema())[1:],
        ]
    )
    changed_schema = logical_schema_document(
        changed_arrow_schema, OrderingSemantics.ORDERED
    )
    uncompressed = replace(
        DEFAULT_PARQUET_PROFILE,
        profile_name="qh-parquet-v1-uncompressed",
        compression="NONE",
        compression_level=None,
    )
    variants = [
        rebuild_lineage(catalog, evidence, parents=(changed_parent,)),
        rebuild_lineage(catalog, evidence, configuration_digest="sha256:" + "6" * 64),
        rebuild_lineage(
            catalog,
            evidence,
            producer=ArtifactProducer("d" * 40, "synthetic", ENVIRONMENT_DIGEST),
        ),
        rebuild_lineage(
            catalog,
            evidence,
            producer=ArtifactProducer("a" * 40, "synthetic", "sha256:" + "7" * 64),
        ),
        rebuild_lineage(catalog, evidence, profile=uncompressed),
        rebuild_lineage(catalog, evidence, quality=QualityDisposition.QUARANTINED),
        rebuild_lineage(
            catalog,
            evidence,
            schema_document=changed_schema,
            schema_digest=sha256_canonical_json(changed_schema),
        ),
        rebuild_lineage(catalog, evidence, logical_fingerprint="sha256:" + "8" * 64),
    ]

    assert baseline == evidence.lineage_manifest.digest
    assert baseline == rebuild_lineage(catalog, evidence)
    assert all(variant != baseline for variant in variants)


def test_declared_parent_ordering_controls_lineage_identity(tmp_path: Path) -> None:
    parents = (
        parent_evidence(PARENT_ID, "1"),
        parent_evidence(SECOND_PARENT_ID, "5"),
    )
    _store, catalog, evidence = publish(tmp_path, parents=parents)

    ordered = rebuild_lineage(
        catalog,
        evidence,
        parents=parents,
        parent_ordering=OrderingSemantics.ORDERED,
    )
    ordered_reversed = rebuild_lineage(
        catalog,
        evidence,
        parents=tuple(reversed(parents)),
        parent_ordering=OrderingSemantics.ORDERED,
    )
    unordered = rebuild_lineage(
        catalog,
        evidence,
        parents=parents,
        parent_ordering=OrderingSemantics.UNORDERED,
    )
    unordered_reversed = rebuild_lineage(
        catalog,
        evidence,
        parents=tuple(reversed(parents)),
        parent_ordering=OrderingSemantics.UNORDERED,
    )
    _store, _catalog, published_forward = publish(
        tmp_path / "forward",
        parents=parents,
        parent_ordering=OrderingSemantics.UNORDERED,
    )
    _store, _catalog, published_reversed = publish(
        tmp_path / "reversed",
        parents=tuple(reversed(parents)),
        parent_ordering=OrderingSemantics.UNORDERED,
    )

    assert ordered != ordered_reversed
    assert unordered == unordered_reversed
    assert (
        published_forward.artifact_manifest.digest
        == published_reversed.artifact_manifest.digest
    )
    assert (
        published_forward.lineage_manifest.digest
        == published_reversed.lineage_manifest.digest
    )


def test_published_evidence_is_immutable_and_fails_on_corruption(
    tmp_path: Path,
) -> None:
    store, catalog, evidence = publish(tmp_path)

    assert evidence.parquet_object.digest != evidence.lineage_manifest.digest
    assert evidence.parquet_object.digest != evidence.logical_content_fingerprint
    assert evidence.lineage_manifest.digest != evidence.logical_content_fingerprint
    assert evidence.lineage_manifest_object.digest == evidence.lineage_manifest.digest
    assert "provenance_lineage_digest" not in evidence.lineage_manifest.document
    verify_derived_dataset_evidence(store=store, catalog=catalog, evidence=evidence)

    evidence.parquet_object.path.write_bytes(b"PAR1corruptPAR1")
    with pytest.raises(ObjectCorruptionError):
        verify_derived_dataset_evidence(store=store, catalog=catalog, evidence=evidence)


def test_dataset_schema_binding_requires_all_three_distinct_identities(
    tmp_path: Path,
) -> None:
    _store, catalog, evidence = publish(tmp_path)
    record = dataset_record(evidence)

    verify_dataset_record_binding(catalog=catalog, record=record, evidence=evidence)

    missing_logical = deepcopy(record)
    del missing_logical["logical_content_fingerprint"]
    with pytest.raises(RecordSchemaError):
        verify_dataset_record_binding(
            catalog=catalog, record=missing_logical, evidence=evidence
        )

    wrong_physical = deepcopy(record)
    wrong_physical["physical_object_digest"] = "sha256:" + "9" * 64
    with pytest.raises(DatasetBindingError, match="physical_object_digest"):
        verify_dataset_record_binding(
            catalog=catalog, record=wrong_physical, evidence=evidence
        )

    wrong_provenance = deepcopy(record)
    provenance = wrong_provenance["provenance"]
    assert isinstance(provenance, dict)
    provenance["transformation"] = "different-transform"
    with pytest.raises(DatasetBindingError, match="transformation"):
        verify_dataset_record_binding(
            catalog=catalog, record=wrong_provenance, evidence=evidence
        )

    substituted = replace(
        evidence, logical_content_fingerprint=evidence.parquet_object.digest
    )
    with pytest.raises(DerivedDataIntegrityError, match="must remain distinct"):
        verify_dataset_record_binding(
            catalog=catalog, record=record, evidence=substituted
        )


def test_lineage_rejects_mismatched_schema_and_secret_text(tmp_path: Path) -> None:
    _store, catalog, evidence = publish(tmp_path)
    schema_document = logical_schema_document(
        evidence.declared_schema, OrderingSemantics.UNORDERED
    )

    with pytest.raises(DerivedDataError, match="row ordering"):
        build_dataset_lineage_manifest(
            catalog=catalog,
            dataset_id=evidence.dataset_id,
            layer=evidence.layer,
            created_at=CREATED_AT,
            physical_object_digest=evidence.parquet_object.digest,
            physical_artifact_manifest_digest=evidence.artifact_manifest.digest,
            schema_document=schema_document,
            schema_digest=sha256_canonical_json(schema_document),
            logical_fingerprint=evidence.logical_content_fingerprint,
            row_ordering=OrderingSemantics.ORDERED,
            writer_profile=evidence.writer_profile,
            parent_evidence=evidence.parent_evidence,
            parent_ordering=evidence.parent_ordering,
            transformation_identity="synthetic-normalization-v1",
            transformation_configuration_digest=CONFIGURATION_DIGEST,
            producer=ArtifactProducer("a" * 40, "synthetic", ENVIRONMENT_DIGEST),
            source_ids=(SOURCE_ID,),
            references=(),
            quality_disposition=evidence.quality_disposition,
        )

    with pytest.raises(SensitiveMetadataError):
        publish_derived_table(
            store=ImmutableObjectStore(tmp_path / "secret-artifacts"),
            catalog=catalog,
            table=synthetic_table(),
            declared_schema=synthetic_schema(),
            dataset_id=DATASET_ID,
            layer=DerivedLayer.NORMALIZED,
            row_ordering=OrderingSemantics.ORDERED,
            parent_evidence=(parent_evidence(),),
            parent_ordering=OrderingSemantics.ORDERED,
            transformation_identity="run --token do-not-persist",
            transformation_configuration_digest=CONFIGURATION_DIGEST,
            created_at=CREATED_AT,
            producer=ArtifactProducer("a" * 40, "synthetic", ENVIRONMENT_DIGEST),
            source_ids=(SOURCE_ID,),
            quality_disposition=QualityDisposition.APPROVED,
        )


def test_parent_identity_duplicates_and_manifest_tampering_fail_closed(
    tmp_path: Path,
) -> None:
    store, catalog, evidence = publish(tmp_path)
    duplicate = (parent_evidence(), parent_evidence())

    with pytest.raises(DerivedDataError, match="unique"):
        rebuild_lineage(catalog, evidence, parents=duplicate)

    wrong_profile = replace(
        evidence,
        writer_profile=replace(
            evidence.writer_profile,
            profile_name="qh-parquet-v1-other",
        ),
    )
    with pytest.raises(DerivedDataIntegrityError, match="writer profile"):
        verify_derived_dataset_evidence(
            store=store, catalog=catalog, evidence=wrong_profile
        )
