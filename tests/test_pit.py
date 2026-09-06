"""Point-in-time eligibility, revision, and immutable integration invariants."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from quant_hunter.config import canonicalize_json
from quant_hunter.config.schema import RecordSchemaError, VersionedSchemaCatalog
from quant_hunter.data import (
    PIT_SELECTED_ROW_ORDERING,
    PIT_TRANSFORMATION_IDENTITY,
    AvailabilityMode,
    DerivedLayer,
    ExclusionReason,
    OrderingSemantics,
    ParentEvidence,
    PitAmbiguityError,
    PitConfigurationError,
    PitExclusion,
    PitInputError,
    PitInputEvidence,
    PitIntegrityError,
    PitSelectionConfiguration,
    PitSelectionResult,
    PublishedPitDataset,
    RevisionTimeStatus,
    TemporalColumns,
    UtcInstant,
    build_pit_input_evidence,
    build_pit_selection_configuration,
    logical_content_fingerprint,
    logical_schema_digest,
    publish_derived_table,
    publish_pit_selection,
    select_point_in_time,
    verify_published_pit_dataset,
)
from quant_hunter.provenance import sha256_bytes
from quant_hunter.storage import (
    ArtifactProducer,
    ImmutableObjectStore,
    QualityDisposition,
)

SCHEMA_DIRECTORY = Path(__file__).parents[1] / "schemas" / "v1"
INPUT_DATASET_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c851"
OUTPUT_DATASET_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c852"
SECOND_OUTPUT_DATASET_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c853"
SOURCE_ID = "SOURCE-01990f30-7f5e-7b34-9b21-3d74c513c854"
CONFIG_DIGEST = "sha256:" + "c" * 64
ENVIRONMENT_DIGEST = "sha256:" + "e" * 64
TEMPORAL_COLUMNS = TemporalColumns(
    event_time="event_time",
    publication_time="publication_time",
    ingestion_time="ingestion_time",
    revision_time="revision_time",
    revision_time_status="revision_time_status",
)
TIMESTAMP_TYPE = pa.timestamp("ns", tz="UTC")


def row(
    vintage_id: str,
    value: int,
    *,
    series: str = "SYNTH-MACRO",
    period: str = "2026-Q1",
    event_time: int | None = 1_000,
    publication_time: int | None = 100,
    ingestion_time: int | None = 100,
    revision_time: int | None = None,
    revision_status: RevisionTimeStatus = RevisionTimeStatus.NOT_APPLICABLE,
) -> dict[str, object]:
    return {
        "series": series,
        "period": period,
        "vintage_id": vintage_id,
        "value": value,
        "event_time": event_time,
        "publication_time": publication_time,
        "ingestion_time": ingestion_time,
        "revision_time": revision_time,
        "revision_time_status": revision_status.value,
    }


def table_from_rows(
    rows: list[dict[str, object]],
    *,
    timestamp_type: pa.TimestampType = TIMESTAMP_TYPE,
) -> pa.Table:
    schema = pa.schema(
        [
            pa.field("series", pa.string(), nullable=False),
            pa.field("period", pa.string(), nullable=False),
            pa.field("vintage_id", pa.string(), nullable=False),
            pa.field("value", pa.int64(), nullable=False),
            pa.field("event_time", timestamp_type),
            pa.field("publication_time", timestamp_type),
            pa.field("ingestion_time", timestamp_type),
            pa.field("revision_time", timestamp_type),
            pa.field("revision_time_status", pa.string(), nullable=False),
        ]
    )
    columns = [
        pa.array([item[field.name] for item in rows], type=field.type)
        for field in schema
    ]
    return pa.Table.from_arrays(columns, schema=schema)


def catalog() -> VersionedSchemaCatalog:
    return VersionedSchemaCatalog(SCHEMA_DIRECTORY)


def typed_configuration(
    *,
    as_of: int = 150,
    mode: AvailabilityMode = AvailabilityMode.PUBLIC,
    keys: tuple[str, ...] = ("series", "period"),
    temporal: TemporalColumns = TEMPORAL_COLUMNS,
) -> PitSelectionConfiguration:
    return build_pit_selection_configuration(
        catalog=catalog(),
        input_dataset_id=INPUT_DATASET_ID,
        as_of=UtcInstant(as_of),
        availability_mode=mode,
        observation_key_columns=keys,
        vintage_id_column="vintage_id",
        temporal_columns=temporal,
    )


def select(
    rows: list[dict[str, object]],
    *,
    as_of: int = 150,
    mode: AvailabilityMode = AvailabilityMode.PUBLIC,
) -> PitSelectionResult:
    table = table_from_rows(rows)
    return select_point_in_time(
        table=table,
        configuration=typed_configuration(as_of=as_of, mode=mode),
        input_evidence=input_evidence(table),
    )


def parent(table: pa.Table) -> ParentEvidence:
    return ParentEvidence(
        dataset_id=INPUT_DATASET_ID,
        registry_revision_digest="sha256:" + "1" * 64,
        physical_object_digest="sha256:" + "2" * 64,
        provenance_lineage_digest="sha256:" + "3" * 64,
        logical_content_fingerprint=logical_content_fingerprint(
            table, table.schema, OrderingSemantics.UNORDERED
        ),
    )


def input_evidence(table: pa.Table) -> PitInputEvidence:
    return build_pit_input_evidence(
        table=table,
        parent_evidence=parent(table),
        declared_schema=table.schema,
        row_ordering=OrderingSemantics.UNORDERED,
    )


def publish(
    tmp_path: Path,
    selection: PitSelectionResult,
    *,
    output_dataset_id: str = OUTPUT_DATASET_ID,
    layer: DerivedLayer = DerivedLayer.CURATED,
) -> tuple[ImmutableObjectStore, VersionedSchemaCatalog, PublishedPitDataset]:
    store = ImmutableObjectStore(tmp_path / "artifacts")
    schema_catalog = catalog()
    published = publish_pit_selection(
        store=store,
        catalog=schema_catalog,
        selection=selection,
        output_dataset_id=output_dataset_id,
        layer=layer,
        parent_evidence=(selection.input_evidence.parent,),
        created_at="2026-09-05T12:00:00Z",
        producer=ArtifactProducer(
            "a" * 40, "synthetic-pit-selection", ENVIRONMENT_DIGEST
        ),
        source_ids=(SOURCE_ID,),
        quality_disposition=QualityDisposition.APPROVED,
        references=("synthetic://pit/selection",),
    )
    return store, schema_catalog, published


def alternate_published_evidence(
    tmp_path: Path,
    selection: PitSelectionResult,
    *,
    table: pa.Table | None = None,
    parent_evidence: ParentEvidence | None = None,
) -> tuple[ImmutableObjectStore, VersionedSchemaCatalog, PublishedPitDataset]:
    store = ImmutableObjectStore(tmp_path / "artifacts")
    schema_catalog = catalog()
    configuration_object = store.publish(selection.configuration.canonical_bytes)
    audit_object = store.publish(selection.audit_canonical_bytes)
    selected_table = selection.selected_table if table is None else table
    derived = publish_derived_table(
        store=store,
        catalog=schema_catalog,
        table=selected_table,
        declared_schema=selected_table.schema,
        dataset_id=OUTPUT_DATASET_ID,
        layer=DerivedLayer.CURATED,
        row_ordering=PIT_SELECTED_ROW_ORDERING,
        parent_evidence=(
            selection.input_evidence.parent
            if parent_evidence is None
            else parent_evidence,
        ),
        parent_ordering=OrderingSemantics.ORDERED,
        transformation_identity=PIT_TRANSFORMATION_IDENTITY,
        transformation_configuration_digest=selection.configuration.digest,
        created_at="2026-09-06T12:00:00Z",
        producer=ArtifactProducer(
            "a" * 40, "synthetic-pit-selection", ENVIRONMENT_DIGEST
        ),
        source_ids=(SOURCE_ID,),
        quality_disposition=QualityDisposition.APPROVED,
        references=(
            store.storage_reference(configuration_object.digest),
            store.storage_reference(audit_object.digest),
        ),
    )
    return (
        store,
        schema_catalog,
        PublishedPitDataset(selection, configuration_object, audit_object, derived),
    )


def selected_values(result: PitSelectionResult) -> list[int]:
    return cast(list[int], result.selected_table.column("value").to_pylist())


def exclusion_reasons(
    result: PitSelectionResult,
) -> dict[str, tuple[ExclusionReason, ...]]:
    return {item.vintage_id: item.reasons for item in result.exclusions}


def test_configuration_requires_explicit_exact_utc_as_of() -> None:
    instant = UtcInstant(1)
    config = typed_configuration(as_of=1)

    assert instant.rfc3339 == "1970-01-01T00:00:00.000000001Z"
    assert config.document["as_of"] == instant.rfc3339
    assert config.document["as_of_epoch_nanoseconds"] == "1"
    assert config.digest == typed_configuration(as_of=1).digest

    from_datetime = build_pit_selection_configuration(
        catalog=catalog(),
        input_dataset_id=INPUT_DATASET_ID,
        as_of=datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=1),
        availability_mode=AvailabilityMode.PUBLIC,
        observation_key_columns=("series", "period"),
        vintage_id_column="vintage_id",
        temporal_columns=TEMPORAL_COLUMNS,
    )
    assert from_datetime.as_of.epoch_nanoseconds == 1_000


@pytest.mark.parametrize(
    "as_of",
    [datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))],
)
def test_naive_or_non_utc_as_of_fails(as_of: datetime) -> None:
    with pytest.raises(PitConfigurationError, match="UTC"):
        build_pit_selection_configuration(
            catalog=catalog(),
            input_dataset_id=INPUT_DATASET_ID,
            as_of=as_of,
            availability_mode=AvailabilityMode.PUBLIC,
            observation_key_columns=("series", "period"),
            vintage_id_column="vintage_id",
            temporal_columns=TEMPORAL_COLUMNS,
        )


def test_utc_instant_and_as_of_types_fail_closed() -> None:
    with pytest.raises(PitConfigurationError, match="integer"):
        UtcInstant("1")  # type: ignore[arg-type]
    with pytest.raises(PitConfigurationError, match="outside RFC 3339"):
        UtcInstant(10**40)
    with pytest.raises(PitConfigurationError, match="explicit datetime"):
        build_pit_selection_configuration(
            catalog=catalog(),
            input_dataset_id=INPUT_DATASET_ID,
            as_of="now",  # type: ignore[arg-type]
            availability_mode=AvailabilityMode.PUBLIC,
            observation_key_columns=("series", "period"),
            vintage_id_column="vintage_id",
            temporal_columns=TEMPORAL_COLUMNS,
        )


def test_configuration_typed_fields_are_bound_to_canonical_document() -> None:
    config = typed_configuration()
    contradictory = replace(
        config,
        input_dataset_id="DATASET-01990f30-7f5e-7b34-9b21-3d74c513c857",
    )
    with pytest.raises(PitIntegrityError, match="typed evidence"):
        contradictory.verify()

    nonobject = replace(config, canonical_bytes=b"[]", digest=sha256_bytes(b"[]"))
    with pytest.raises(PitIntegrityError, match="not a JSON object"):
        nonobject.verify()

    extra_document = config.document
    extra_document["unbound"] = True
    extra_bytes = canonicalize_json(extra_document)
    extra = replace(
        config, canonical_bytes=extra_bytes, digest=sha256_bytes(extra_bytes)
    )
    with pytest.raises(PitIntegrityError, match="unbound evidence"):
        extra.verify()


@pytest.mark.parametrize(
    ("keys", "temporal"),
    [
        ((), TEMPORAL_COLUMNS),
        (("series", "series"), TEMPORAL_COLUMNS),
        (("publication_time",), TEMPORAL_COLUMNS),
        (
            ("series",),
            replace(TEMPORAL_COLUMNS, revision_time="publication_time"),
        ),
    ],
)
def test_configuration_rejects_ambiguous_column_contracts(
    keys: tuple[str, ...], temporal: TemporalColumns
) -> None:
    with pytest.raises(PitConfigurationError):
        typed_configuration(keys=keys, temporal=temporal)


def test_configuration_rejects_malformed_and_overlapping_vintage_column() -> None:
    with pytest.raises(PitConfigurationError, match="Malformed"):
        typed_configuration(keys=("Invalid-Column",))
    with pytest.raises(PitConfigurationError, match="distinct from temporal"):
        build_pit_selection_configuration(
            catalog=catalog(),
            input_dataset_id=INPUT_DATASET_ID,
            as_of=UtcInstant(150),
            availability_mode=AvailabilityMode.PUBLIC,
            observation_key_columns=("series",),
            vintage_id_column="publication_time",
            temporal_columns=TEMPORAL_COLUMNS,
        )


def test_configuration_schema_rejects_unknown_policy() -> None:
    document = typed_configuration().document
    document["ambiguity_policy"] = "PICK_FIRST"

    with pytest.raises(RecordSchemaError):
        catalog().validate("pit-selection-config.schema.json", document)


def test_publication_exact_boundary_and_one_nanosecond_future() -> None:
    result = select(
        [
            row("V-AT", 1, period="AT", publication_time=150),
            row("V-FUTURE", 2, period="FUTURE", publication_time=151),
        ],
        as_of=150,
    )

    assert result.selected_vintage_ids == ("V-AT",)
    assert exclusion_reasons(result)["V-FUTURE"] == (
        ExclusionReason.FUTURE_PUBLICATION,
    )


@pytest.mark.parametrize(
    ("unit", "as_of_nanoseconds"),
    [("s", 1_000_000_000), ("ms", 1_000_000), ("us", 1_000), ("ns", 1)],
)
def test_supported_timestamp_units_preserve_exact_boundary(
    unit: str, as_of_nanoseconds: int
) -> None:
    timestamp_type = pa.timestamp(unit, tz="UTC")
    table = table_from_rows(
        [row("V1", 1, event_time=1, publication_time=1, ingestion_time=1)],
        timestamp_type=timestamp_type,
    )
    result = select_point_in_time(
        table=table,
        configuration=typed_configuration(as_of=as_of_nanoseconds),
        input_evidence=input_evidence(table),
    )

    assert selected_values(result) == [1]


def test_public_and_operational_availability_are_explicitly_distinct() -> None:
    rows = [row("V1", 1, publication_time=100, ingestion_time=200)]

    public = select(rows, as_of=150, mode=AvailabilityMode.PUBLIC)
    operational_early = select(rows, as_of=150, mode=AvailabilityMode.OPERATIONAL)
    operational_at_ingestion = select(
        rows, as_of=200, mode=AvailabilityMode.OPERATIONAL
    )
    operational_early_again = select(rows, as_of=150, mode=AvailabilityMode.OPERATIONAL)

    assert selected_values(public) == [1]
    assert selected_values(operational_early) == []
    assert exclusion_reasons(operational_early)["V1"] == (
        ExclusionReason.FUTURE_INGESTION,
    )
    assert selected_values(operational_at_ingestion) == [1]
    assert operational_early_again.audit_digest == operational_early.audit_digest


def test_macro_v1_v2_v3_vintage_selection_reconstructs_history() -> None:
    rows = [
        row("V1", 10, publication_time=100, ingestion_time=100),
        row(
            "V2",
            20,
            publication_time=100,
            ingestion_time=205,
            revision_time=200,
            revision_status=RevisionTimeStatus.KNOWN,
        ),
        row(
            "V3",
            30,
            publication_time=100,
            ingestion_time=305,
            revision_time=300,
            revision_status=RevisionTimeStatus.KNOWN,
        ),
    ]

    before_v2 = select(rows, as_of=150)
    at_v2 = select(rows, as_of=200)
    between_v2_v3 = select(rows, as_of=250)
    at_v3 = select(rows, as_of=300)
    early_again = select(rows, as_of=150)

    assert selected_values(before_v2) == [10]
    assert selected_values(at_v2) == [20]
    assert selected_values(between_v2_v3) == [20]
    assert selected_values(at_v3) == [30]
    assert selected_values(early_again) == [10]
    assert early_again.audit_digest == before_v2.audit_digest
    assert ExclusionReason.FUTURE_REVISION in exclusion_reasons(before_v2)["V2"]
    assert exclusion_reasons(at_v2)["V1"] == (
        ExclusionReason.SUPERSEDED_BY_LATER_ELIGIBLE_VINTAGE,
    )


def test_public_revision_requires_publication_and_revision_boundaries() -> None:
    result = select(
        [
            row(
                "REV-FUTURE-PUB",
                1,
                period="A",
                publication_time=151,
                revision_time=100,
                revision_status=RevisionTimeStatus.KNOWN,
            ),
            row(
                "REV-FUTURE-REV",
                2,
                period="B",
                publication_time=100,
                revision_time=151,
                revision_status=RevisionTimeStatus.KNOWN,
            ),
        ],
        as_of=150,
    )

    reasons = exclusion_reasons(result)
    assert reasons["REV-FUTURE-PUB"] == (ExclusionReason.FUTURE_PUBLICATION,)
    assert reasons["REV-FUTURE-REV"] == (ExclusionReason.FUTURE_REVISION,)


def test_missing_and_inconsistent_times_have_explicit_dispositions() -> None:
    rows = [
        row("MISSING-PUB", 1, period="A", publication_time=None),
        row("MISSING-INGEST", 2, period="B", ingestion_time=None),
        row(
            "UNKNOWN-REV",
            3,
            period="C",
            revision_status=RevisionTimeStatus.REQUIRED_UNKNOWN,
        ),
        row(
            "MISSING-REV",
            4,
            period="D",
            revision_status=RevisionTimeStatus.KNOWN,
        ),
        row(
            "CONTRADICTORY-REV",
            5,
            period="E",
            revision_time=100,
            revision_status=RevisionTimeStatus.NOT_APPLICABLE,
        ),
    ]

    public = select(rows, mode=AvailabilityMode.PUBLIC)
    operational = select(rows, mode=AvailabilityMode.OPERATIONAL)
    public_reasons = exclusion_reasons(public)
    operational_reasons = exclusion_reasons(operational)

    assert selected_values(public) == [2]
    assert public_reasons["MISSING-PUB"] == (ExclusionReason.MISSING_PUBLICATION_TIME,)
    assert public_reasons["UNKNOWN-REV"] == (
        ExclusionReason.REVISION_TIME_REQUIRED_UNKNOWN,
    )
    assert public_reasons["MISSING-REV"] == (ExclusionReason.MISSING_REVISION_TIME,)
    assert public_reasons["CONTRADICTORY-REV"] == (
        ExclusionReason.REVISION_TIME_CONTRADICTS_NOT_APPLICABLE,
    )
    assert (
        ExclusionReason.MISSING_INGESTION_TIME in operational_reasons["MISSING-INGEST"]
    )


def test_future_event_is_not_used_as_public_knowledge_boundary() -> None:
    result = select(
        [row("SCHEDULE-V1", 1, event_time=1_000, publication_time=100)],
        as_of=150,
    )

    assert selected_values(result) == [1]


def test_input_permutation_does_not_change_pit_result() -> None:
    rows = [
        row("A1", 1, series="A", period="1", publication_time=100),
        row("B1", 2, series="B", period="1", publication_time=110),
        row(
            "A2",
            3,
            series="A",
            period="1",
            publication_time=100,
            revision_time=120,
            revision_status=RevisionTimeStatus.KNOWN,
        ),
    ]
    config = typed_configuration(as_of=150)
    forward_table = table_from_rows(rows)
    reverse_table = table_from_rows(list(reversed(rows)))
    forward = select_point_in_time(
        table=forward_table,
        configuration=config,
        input_evidence=input_evidence(forward_table),
    )
    reversed_result = select_point_in_time(
        table=reverse_table,
        configuration=config,
        input_evidence=input_evidence(reverse_table),
    )

    assert forward.selected_vintage_ids == reversed_result.selected_vintage_ids
    assert forward.audit_canonical_bytes == reversed_result.audit_canonical_bytes
    assert logical_content_fingerprint(
        forward.selected_table,
        forward.selected_table.schema,
        OrderingSemantics.UNORDERED,
    ) == logical_content_fingerprint(
        reversed_result.selected_table,
        reversed_result.selected_table.schema,
        OrderingSemantics.UNORDERED,
    )


def test_same_priority_competing_vintages_fail_closed() -> None:
    rows = [
        row("V1", 1, publication_time=100),
        row("V2", 2, publication_time=100),
    ]

    with pytest.raises(PitAmbiguityError, match="Ambiguous eligible vintages"):
        select(rows)


@pytest.mark.parametrize(
    "rows",
    [
        [row("DUP", 1, period="A"), row("DUP", 2, period="B")],
        [row("", 1)],
    ],
)
def test_vintage_identity_must_be_explicit_and_unique(
    rows: list[dict[str, object]],
) -> None:
    with pytest.raises(PitInputError, match="Vintage"):
        select(rows)


def test_unsupported_revision_status_fails_closed() -> None:
    invalid = row("V1", 1)
    invalid["revision_time_status"] = "MAYBE"

    with pytest.raises(PitInputError, match="Revision status"):
        select([invalid])


@pytest.mark.parametrize(
    "timestamp_type",
    [pa.timestamp("ns"), pa.timestamp("ns", tz="America/New_York")],
)
def test_temporal_arrow_columns_require_explicit_utc(
    timestamp_type: pa.TimestampType,
) -> None:
    table = table_from_rows([row("V1", 1)], timestamp_type=timestamp_type)

    with pytest.raises(PitInputError, match="UTC timezone"):
        select_point_in_time(
            table=table,
            configuration=typed_configuration(),
            input_evidence=input_evidence(table_from_rows([row("V1", 1)])),
        )


def test_missing_or_non_timestamp_temporal_column_fails_closed() -> None:
    base = table_from_rows([row("V1", 1)])
    missing = base.drop(["publication_time"])
    with pytest.raises(PitInputError, match="Missing required temporal"):
        select_point_in_time(
            table=missing,
            configuration=typed_configuration(),
            input_evidence=input_evidence(base),
        )

    index = base.schema.get_field_index("publication_time")
    wrong_type = base.set_column(
        index, "publication_time", pa.array([100], type=pa.int64())
    )
    with pytest.raises(PitInputError, match="Arrow timestamp"):
        select_point_in_time(
            table=wrong_type,
            configuration=typed_configuration(),
            input_evidence=input_evidence(base),
        )


def test_missing_or_non_string_identity_columns_fail_closed() -> None:
    base = table_from_rows([row("V1", 1)])
    for column in ("vintage_id", "revision_time_status"):
        with pytest.raises(PitInputError, match="Missing required"):
            select_point_in_time(
                table=base.drop([column]),
                configuration=typed_configuration(),
                input_evidence=input_evidence(base.drop([column])),
            )
    index = base.schema.get_field_index("vintage_id")
    wrong_type = base.set_column(index, "vintage_id", pa.array([1], type=pa.int64()))
    with pytest.raises(PitInputError, match="Arrow UTF-8"):
        select_point_in_time(
            table=wrong_type,
            configuration=typed_configuration(),
            input_evidence=input_evidence(wrong_type),
        )


def test_unsupported_input_logical_type_fails_closed() -> None:
    table = table_from_rows([row("V1", 1)]).append_column(
        "unsupported", pa.array([1.0], type=pa.float32())
    )

    with pytest.raises(PitInputError, match="governed logical schema"):
        select_point_in_time(
            table=table,
            configuration=typed_configuration(),
            input_evidence=input_evidence(table_from_rows([row("V1", 1)])),
        )


def test_observation_key_cannot_be_missing_or_null() -> None:
    missing_table = table_from_rows([row("V1", 1)]).drop(["period"])
    with pytest.raises(PitInputError, match="key column is missing"):
        select_point_in_time(
            table=missing_table,
            configuration=typed_configuration(),
            input_evidence=input_evidence(missing_table),
        )

    nullable_row = row("V1", 1)
    nullable_row["period"] = None
    schema = table_from_rows([row("V1", 1)]).schema.set(
        1, pa.field("period", pa.string(), nullable=True)
    )
    arrays = [pa.array([nullable_row[field.name]], type=field.type) for field in schema]
    nullable_table = pa.Table.from_arrays(arrays, schema=schema)
    with pytest.raises(PitInputError, match="cannot be null"):
        select_point_in_time(
            table=nullable_table,
            configuration=typed_configuration(),
            input_evidence=input_evidence(nullable_table),
        )


def test_empty_input_produces_deterministic_empty_result() -> None:
    empty = table_from_rows([])
    result = select_point_in_time(
        table=empty,
        configuration=typed_configuration(),
        input_evidence=input_evidence(empty),
    )

    assert result.input_row_count == 0
    assert result.selected_table.num_rows == 0
    assert result.exclusions == ()


def test_selection_audit_is_bound_to_typed_result() -> None:
    result = select([row("V1", 1)])
    contradictory = replace(result, selected_vintage_ids=("OTHER",))

    with pytest.raises(PitIntegrityError, match="typed selection evidence"):
        contradictory.verify()

    nonobject = replace(
        result,
        audit_canonical_bytes=b"[]",
        audit_digest=sha256_bytes(b"[]"),
    )
    with pytest.raises(PitIntegrityError, match="not a JSON object"):
        nonobject.verify()

    extra_document = result.audit_document
    extra_document["unbound"] = True
    extra_bytes = canonicalize_json(extra_document)
    extra = replace(
        result,
        audit_canonical_bytes=extra_bytes,
        audit_digest=sha256_bytes(extra_bytes),
    )
    with pytest.raises(PitIntegrityError, match="unbound evidence"):
        extra.verify()

    input_document = cast(dict[str, object], result.audit_document["input_evidence"])
    assert input_document["parent"] == result.input_evidence.parent.document()
    assert (
        result.audit_document["selected_logical_content_fingerprint"]
        == result.selected_logical_content_fingerprint
    )


def test_selection_result_binds_table_accounting_and_canonical_order() -> None:
    result = select(
        [
            row("V-Z", 1, series="Z-SERIES"),
            row("V-A", 2, series="A-SERIES"),
        ]
    )
    wrong_table = replace(result, selected_table=result.selected_table.slice(0, 1))
    with pytest.raises(PitIntegrityError, match="logical content fingerprint"):
        wrong_table.verify()

    duplicate_exclusion = replace(
        result,
        exclusions=(
            *result.exclusions,
            PitExclusion(
                observation_key_digest="sha256:" + "0" * 64,
                vintage_id=result.selected_vintage_ids[0],
                reasons=(ExclusionReason.FUTURE_PUBLICATION,),
            ),
        ),
    )
    duplicate_document = duplicate_exclusion.audit_document
    duplicate_document["exclusions"] = [
        exclusion.document() for exclusion in duplicate_exclusion.exclusions
    ]
    duplicate_bytes = canonicalize_json(duplicate_document)
    duplicate_exclusion = replace(
        duplicate_exclusion,
        audit_canonical_bytes=duplicate_bytes,
        audit_digest=sha256_bytes(duplicate_bytes),
    )
    with pytest.raises(PitIntegrityError, match="account for each input vintage"):
        duplicate_exclusion.verify()

    reverse_indices = pa.array([1, 0], type=pa.int64())
    reversed_result = replace(
        result,
        selected_table=result.selected_table.take(reverse_indices),
        selected_vintage_ids=tuple(reversed(result.selected_vintage_ids)),
    )
    reversed_document = reversed_result.audit_document
    reversed_document["selected_vintage_ids"] = list(
        reversed_result.selected_vintage_ids
    )
    reversed_bytes = canonicalize_json(reversed_document)
    reversed_result = replace(
        reversed_result,
        audit_canonical_bytes=reversed_bytes,
        audit_digest=sha256_bytes(reversed_bytes),
    )
    with pytest.raises(PitIntegrityError, match="canonically key ordered"):
        reversed_result.verify()


def test_selection_rejects_table_unrelated_to_bound_input_evidence() -> None:
    table_a = table_from_rows([row("V1", 1)])
    table_b = table_from_rows([row("V1", 999)])

    with pytest.raises(PitIntegrityError, match="does not match parent logical"):
        select_point_in_time(
            table=table_b,
            configuration=typed_configuration(),
            input_evidence=input_evidence(table_a),
        )


def test_input_evidence_binds_declared_schema_and_parent_ordering() -> None:
    table = table_from_rows([row("B", 2, series="B"), row("A", 1, series="A")])
    evidence = input_evidence(table)

    wrong_schema_digest = replace(evidence, schema_digest="sha256:" + "5" * 64)
    with pytest.raises(PitIntegrityError, match="schema digest mismatch"):
        wrong_schema_digest.verify()

    ordered = replace(
        evidence,
        row_ordering=OrderingSemantics.ORDERED,
        schema_digest=logical_schema_digest(table.schema, OrderingSemantics.ORDERED),
    )
    with pytest.raises(PitIntegrityError, match="does not match parent logical"):
        ordered.verify_table(table)


def test_selected_value_tampering_fails_result_and_publication(tmp_path: Path) -> None:
    result = select([row("V1", 1)])
    value_index = result.selected_table.schema.get_field_index("value")
    changed_table = result.selected_table.set_column(
        value_index, "value", pa.array([999], type=pa.int64())
    )
    damaged = replace(result, selected_table=changed_table)

    with pytest.raises(PitIntegrityError, match="logical content fingerprint"):
        damaged.verify()
    with pytest.raises(PitIntegrityError, match="logical content fingerprint"):
        publish(tmp_path, damaged)


def test_as_of_and_policy_change_lineage_but_not_equal_logical_content(
    tmp_path: Path,
) -> None:
    rows = [row("V1", 1, publication_time=100, ingestion_time=100)]
    early = select(rows, as_of=150, mode=AvailabilityMode.PUBLIC)
    later = select(rows, as_of=160, mode=AvailabilityMode.PUBLIC)
    operational = select(rows, as_of=160, mode=AvailabilityMode.OPERATIONAL)
    _store, _catalog, early_published = publish(tmp_path / "early", early)
    _store, _catalog, later_published = publish(
        tmp_path / "later", later, output_dataset_id=SECOND_OUTPUT_DATASET_ID
    )
    _store, _catalog, operational_published = publish(
        tmp_path / "operational",
        operational,
        output_dataset_id="DATASET-01990f30-7f5e-7b34-9b21-3d74c513c855",
    )

    assert early.configuration.digest != later.configuration.digest
    assert later.configuration.digest != operational.configuration.digest
    assert (
        early_published.derived_evidence.logical_content_fingerprint
        == later_published.derived_evidence.logical_content_fingerprint
        == operational_published.derived_evidence.logical_content_fingerprint
    )
    assert (
        early_published.derived_evidence.lineage_manifest.digest
        != later_published.derived_evidence.lineage_manifest.digest
    )
    assert (
        later_published.derived_evidence.lineage_manifest.digest
        != operational_published.derived_evidence.lineage_manifest.digest
    )


def test_published_early_vintage_is_not_retroactively_changed(
    tmp_path: Path,
) -> None:
    rows = [
        row("V1", 10, publication_time=100),
        row(
            "V2",
            20,
            publication_time=100,
            revision_time=200,
            revision_status=RevisionTimeStatus.KNOWN,
        ),
    ]
    early = select(rows, as_of=150)
    later = select(rows, as_of=200)
    store, schema_catalog, early_published = publish(tmp_path, early)
    early_bytes = store.read_bytes(
        early_published.derived_evidence.parquet_object.digest
    )
    later_published = publish_pit_selection(
        store=store,
        catalog=schema_catalog,
        selection=later,
        output_dataset_id=SECOND_OUTPUT_DATASET_ID,
        layer=DerivedLayer.CURATED,
        parent_evidence=(later.input_evidence.parent,),
        created_at="2026-09-05T12:01:00Z",
        producer=ArtifactProducer(
            "a" * 40, "synthetic-pit-selection", ENVIRONMENT_DIGEST
        ),
        source_ids=(SOURCE_ID,),
        quality_disposition=QualityDisposition.APPROVED,
    )

    assert selected_values(early_published.selection) == [10]
    assert selected_values(later_published.selection) == [20]
    assert (
        store.read_bytes(early_published.derived_evidence.parquet_object.digest)
        == early_bytes
    )
    verify_published_pit_dataset(
        store=store, catalog=schema_catalog, published=early_published
    )


def test_pit_publication_requires_exact_parent_and_supported_layer(
    tmp_path: Path,
) -> None:
    selection = select([row("V1", 1)])
    wrong_parent = replace(
        selection.input_evidence.parent,
        dataset_id="DATASET-01990f30-7f5e-7b34-9b21-3d74c513c856",
    )
    store = ImmutableObjectStore(tmp_path / "artifacts")
    schema_catalog = catalog()
    producer = ArtifactProducer("a" * 40, "synthetic-pit-selection", ENVIRONMENT_DIGEST)
    with pytest.raises(PitConfigurationError, match="normalized or curated"):
        publish_pit_selection(
            store=store,
            catalog=schema_catalog,
            selection=selection,
            output_dataset_id=OUTPUT_DATASET_ID,
            layer=DerivedLayer.FEATURES,
            parent_evidence=(selection.input_evidence.parent,),
            created_at="2026-09-05T12:00:00Z",
            producer=producer,
            source_ids=(SOURCE_ID,),
            quality_disposition=QualityDisposition.APPROVED,
        )
    with pytest.raises(PitConfigurationError, match="exact input evidence"):
        publish_pit_selection(
            store=store,
            catalog=schema_catalog,
            selection=selection,
            output_dataset_id=OUTPUT_DATASET_ID,
            layer=DerivedLayer.NORMALIZED,
            parent_evidence=(wrong_parent,),
            created_at="2026-09-05T12:00:00Z",
            producer=producer,
            source_ids=(SOURCE_ID,),
            quality_disposition=QualityDisposition.APPROVED,
        )


def _assert_parent_identity_rejected(
    tmp_path: Path, wrong_parent: ParentEvidence
) -> None:
    selection = select([row("V1", 1)])
    store = ImmutableObjectStore(tmp_path / "artifacts")
    with pytest.raises(PitConfigurationError, match="exact input evidence"):
        publish_pit_selection(
            store=store,
            catalog=catalog(),
            selection=selection,
            output_dataset_id=OUTPUT_DATASET_ID,
            layer=DerivedLayer.NORMALIZED,
            parent_evidence=(wrong_parent,),
            created_at="2026-09-06T12:00:00Z",
            producer=ArtifactProducer(
                "a" * 40, "synthetic-pit-selection", ENVIRONMENT_DIGEST
            ),
            source_ids=(SOURCE_ID,),
            quality_disposition=QualityDisposition.APPROVED,
        )


def test_pit_publication_rejects_wrong_parent_revision(tmp_path: Path) -> None:
    exact = select([row("V1", 1)]).input_evidence.parent
    _assert_parent_identity_rejected(
        tmp_path, replace(exact, registry_revision_digest="sha256:" + "5" * 64)
    )


def test_pit_publication_rejects_wrong_parent_physical_object(tmp_path: Path) -> None:
    exact = select([row("V1", 1)]).input_evidence.parent
    _assert_parent_identity_rejected(
        tmp_path, replace(exact, physical_object_digest="sha256:" + "5" * 64)
    )


def test_pit_publication_rejects_wrong_parent_lineage(tmp_path: Path) -> None:
    exact = select([row("V1", 1)]).input_evidence.parent
    _assert_parent_identity_rejected(
        tmp_path, replace(exact, provenance_lineage_digest="sha256:" + "5" * 64)
    )


def test_pit_publication_rejects_wrong_parent_logical_content(tmp_path: Path) -> None:
    exact = select([row("V1", 1)]).input_evidence.parent
    _assert_parent_identity_rejected(
        tmp_path, replace(exact, logical_content_fingerprint="sha256:" + "5" * 64)
    )


def test_pit_verifier_rejects_valid_evidence_for_different_exact_parent(
    tmp_path: Path,
) -> None:
    selection = select([row("V1", 1)])
    exact = selection.input_evidence.parent
    wrong_parents = (
        replace(exact, registry_revision_digest="sha256:" + "5" * 64),
        replace(exact, physical_object_digest="sha256:" + "5" * 64),
        replace(exact, provenance_lineage_digest="sha256:" + "5" * 64),
        replace(exact, logical_content_fingerprint="sha256:" + "5" * 64),
    )
    for index, wrong_parent in enumerate(wrong_parents):
        store, schema_catalog, published = alternate_published_evidence(
            tmp_path / str(index), selection, parent_evidence=wrong_parent
        )
        with pytest.raises(PitIntegrityError, match="parent binding mismatch"):
            verify_published_pit_dataset(
                store=store, catalog=schema_catalog, published=published
            )


def test_pit_verifier_rejects_valid_evidence_for_different_selected_content(
    tmp_path: Path,
) -> None:
    selection = select([row("V1", 1)])
    value_index = selection.selected_table.schema.get_field_index("value")
    changed_table = selection.selected_table.set_column(
        value_index, "value", pa.array([999], type=pa.int64())
    )
    store, schema_catalog, published = alternate_published_evidence(
        tmp_path, selection, table=changed_table
    )

    with pytest.raises(PitIntegrityError, match="logical content does not match"):
        verify_published_pit_dataset(
            store=store, catalog=schema_catalog, published=published
        )


def test_published_pit_configuration_identity_is_verified(tmp_path: Path) -> None:
    store, schema_catalog, published = publish(tmp_path, select([row("V1", 1)]))
    damaged = replace(published, configuration_object=published.audit_object)

    with pytest.raises(PitIntegrityError, match="configuration object"):
        verify_published_pit_dataset(
            store=store, catalog=schema_catalog, published=damaged
        )
