"""Deterministic point-in-time eligibility and vintage-selection contracts."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, cast

import pyarrow as pa  # type: ignore[import-untyped]

from quant_hunter.config.canonical import (
    JsonRecord,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.config.schema import VersionedSchemaCatalog
from quant_hunter.data.derived import (
    DerivedDataError,
    DerivedDatasetEvidence,
    DerivedLayer,
    OrderingSemantics,
    ParentEvidence,
    canonical_logical_table_bytes,
    logical_content_fingerprint,
    publish_derived_table,
    verify_derived_dataset_evidence,
)
from quant_hunter.identity.ids import RegistryKind, validate_typed_id
from quant_hunter.provenance.hashing import sha256_bytes, verify_sha256_bytes
from quant_hunter.storage.manifests import ArtifactProducer
from quant_hunter.storage.objects import ImmutableObjectStore, StoredObject
from quant_hunter.storage.raw import QualityDisposition

PIT_CONFIGURATION_SCHEMA: Final = "pit-selection-config.schema.json"
PIT_TRANSFORMATION_IDENTITY: Final = "quant-hunter-pit-selection-v1"
COLUMN_NAME: Final = re.compile(r"^[a-z][a-z0-9_]*$")
NANOSECONDS_PER_SECOND: Final = 1_000_000_000


class PitError(ValueError):
    """Base error for invalid point-in-time selection inputs."""


class PitConfigurationError(PitError):
    """The explicit PIT selection configuration is invalid."""


class PitInputError(PitError):
    """Input rows or their declared Arrow schema cannot support PIT selection."""


class PitAmbiguityError(PitError):
    """Multiple vintages share the same governed winning priority."""


class PitIntegrityError(RuntimeError):
    """Published PIT configuration, audit evidence, or derived data does not bind."""


class AvailabilityMode(StrEnum):
    """Availability boundary applied to every candidate row."""

    PUBLIC = "PUBLIC"
    OPERATIONAL = "OPERATIONAL"


class RevisionTimeStatus(StrEnum):
    """Whether revision_time is applicable and known for one vintage."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    KNOWN = "KNOWN"
    REQUIRED_UNKNOWN = "REQUIRED_UNKNOWN"


class ExclusionReason(StrEnum):
    """Deterministic reasons that a row was not selected."""

    MISSING_PUBLICATION_TIME = "MISSING_PUBLICATION_TIME"
    FUTURE_PUBLICATION = "FUTURE_PUBLICATION"
    MISSING_INGESTION_TIME = "MISSING_INGESTION_TIME"
    FUTURE_INGESTION = "FUTURE_INGESTION"
    MISSING_REVISION_TIME = "MISSING_REVISION_TIME"
    FUTURE_REVISION = "FUTURE_REVISION"
    REVISION_TIME_REQUIRED_UNKNOWN = "REVISION_TIME_REQUIRED_UNKNOWN"
    REVISION_TIME_CONTRADICTS_NOT_APPLICABLE = (
        "REVISION_TIME_CONTRADICTS_NOT_APPLICABLE"
    )
    SUPERSEDED_BY_LATER_ELIGIBLE_VINTAGE = "SUPERSEDED_BY_LATER_ELIGIBLE_VINTAGE"


@dataclass(frozen=True, slots=True, order=True)
class UtcInstant:
    """Exact UTC instant represented as signed nanoseconds from Unix epoch."""

    epoch_nanoseconds: int

    def __post_init__(self) -> None:
        if type(self.epoch_nanoseconds) is not int:
            raise PitConfigurationError("UTC epoch nanoseconds must be an integer")
        _ = self.rfc3339

    @classmethod
    def from_datetime(cls, value: datetime) -> UtcInstant:
        """Create an exact microsecond-resolution instant without local conversion."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise PitConfigurationError("as_of must be timezone-aware UTC")
        if value.utcoffset() != timedelta(0):
            raise PitConfigurationError("as_of must use UTC, not a local offset")
        utc_value = value.astimezone(UTC)
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        delta = utc_value - epoch
        nanoseconds = (
            delta.days * 86_400 * NANOSECONDS_PER_SECOND
            + delta.seconds * NANOSECONDS_PER_SECOND
            + delta.microseconds * 1_000
        )
        return cls(nanoseconds)

    @property
    def rfc3339(self) -> str:
        """Return a fixed nine-digit UTC representation with no locale dependence."""
        seconds, remainder = divmod(self.epoch_nanoseconds, NANOSECONDS_PER_SECOND)
        try:
            instant = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
        except OverflowError as error:
            raise PitConfigurationError(
                "UTC instant is outside RFC 3339 range"
            ) from error
        return (
            f"{instant.year:04d}-{instant.month:02d}-{instant.day:02d}T"
            f"{instant.hour:02d}:{instant.minute:02d}:{instant.second:02d}."
            f"{remainder:09d}Z"
        )


@dataclass(frozen=True, slots=True)
class TemporalColumns:
    """Distinct columns preserving all four authoritative time concepts."""

    event_time: str
    publication_time: str
    ingestion_time: str
    revision_time: str
    revision_time_status: str

    def document(self) -> JsonRecord:
        return {
            "event_time": self.event_time,
            "publication_time": self.publication_time,
            "ingestion_time": self.ingestion_time,
            "revision_time": self.revision_time,
            "revision_time_status": self.revision_time_status,
        }


@dataclass(frozen=True, slots=True)
class PitSelectionConfiguration:
    """Schema-governed canonical configuration for one explicit as-of query."""

    input_dataset_id: str
    as_of: UtcInstant
    availability_mode: AvailabilityMode
    observation_key_columns: tuple[str, ...]
    vintage_id_column: str
    temporal_columns: TemporalColumns
    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise PitIntegrityError("PIT configuration is not a JSON object")
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)
        document = self.document
        expected: JsonRecord = {
            "schema_version": "1.0.0",
            "input_dataset_id": self.input_dataset_id,
            "as_of": self.as_of.rfc3339,
            "as_of_epoch_nanoseconds": str(self.as_of.epoch_nanoseconds),
            "availability_mode": self.availability_mode.value,
            "observation_key_columns": list(self.observation_key_columns),
            "vintage_id_column": self.vintage_id_column,
            "temporal_columns": self.temporal_columns.document(),
            "revision_status_values": {
                "not_applicable": RevisionTimeStatus.NOT_APPLICABLE.value,
                "known": RevisionTimeStatus.KNOWN.value,
                "required_unknown": RevisionTimeStatus.REQUIRED_UNKNOWN.value,
            },
            "public_eligibility_rule": (
                "PUBLICATION_AND_APPLICABLE_REVISION_NOT_AFTER_AS_OF"
            ),
            "operational_eligibility_rule": (
                "PUBLIC_RULES_AND_INGESTION_NOT_AFTER_AS_OF"
            ),
            "vintage_selection_rule": ("LATEST_ELIGIBLE_PUBLIC_AVAILABILITY_BOUNDARY"),
            "ambiguity_policy": "FAIL_CLOSED",
            "output_ordering": "CANONICAL_OBSERVATION_KEY",
        }
        for field, expected_value in expected.items():
            if document.get(field) != expected_value:
                raise PitIntegrityError(
                    f"PIT configuration {field} does not match typed evidence"
                )
        if document != expected:
            raise PitIntegrityError("PIT configuration contains unbound evidence")


@dataclass(frozen=True, slots=True)
class PitExclusion:
    """Auditable disposition for one unselected immutable vintage row."""

    observation_key_digest: str
    vintage_id: str
    reasons: tuple[ExclusionReason, ...]
    selected_vintage_id: str | None = None

    def document(self) -> JsonRecord:
        return {
            "observation_key_digest": self.observation_key_digest,
            "vintage_id": self.vintage_id,
            "reasons": [reason.value for reason in self.reasons],
            "selected_vintage_id": self.selected_vintage_id,
        }


@dataclass(frozen=True, slots=True)
class PitSelectionResult:
    """Deterministic selected table plus explicit exclusion evidence."""

    configuration: PitSelectionConfiguration
    selected_table: pa.Table
    selected_vintage_ids: tuple[str, ...]
    exclusions: tuple[PitExclusion, ...]
    input_row_count: int
    audit_canonical_bytes: bytes
    audit_digest: str

    @property
    def audit_document(self) -> JsonRecord:
        value = parse_json_document(self.audit_canonical_bytes)
        if not isinstance(value, dict):
            raise PitIntegrityError("PIT audit evidence is not a JSON object")
        return value

    def verify(self) -> None:
        self.configuration.verify()
        verify_sha256_bytes(self.audit_canonical_bytes, self.audit_digest)
        expected: JsonRecord = {
            "schema_version": "1.0.0",
            "configuration_digest": self.configuration.digest,
            "input_dataset_id": self.configuration.input_dataset_id,
            "as_of": self.configuration.as_of.rfc3339,
            "availability_mode": self.configuration.availability_mode.value,
            "input_row_count": self.input_row_count,
            "selected_vintage_ids": list(self.selected_vintage_ids),
            "exclusions": [exclusion.document() for exclusion in self.exclusions],
        }
        document = self.audit_document
        for field, expected_value in expected.items():
            if document.get(field) != expected_value:
                raise PitIntegrityError(
                    f"PIT audit {field} does not match typed selection evidence"
                )
        if document != expected:
            raise PitIntegrityError("PIT audit contains unbound evidence")
        observed_vintage_ids = _string_values(
            self.selected_table,
            self.configuration.vintage_id_column,
            "selected vintage identity",
        )
        if tuple(observed_vintage_ids) != self.selected_vintage_ids:
            raise PitIntegrityError("PIT selected table and vintage identities differ")
        excluded_vintage_ids = [exclusion.vintage_id for exclusion in self.exclusions]
        all_vintage_ids = [*observed_vintage_ids, *excluded_vintage_ids]
        if len(all_vintage_ids) != self.input_row_count or len(all_vintage_ids) != len(
            set(all_vintage_ids)
        ):
            raise PitIntegrityError(
                "PIT selection does not account for each input vintage"
            )
        key_bytes, _key_digests = _observation_keys(
            self.selected_table, self.configuration.observation_key_columns
        )
        if key_bytes != sorted(key_bytes):
            raise PitIntegrityError("PIT selected rows are not canonically key ordered")


@dataclass(frozen=True, slots=True)
class PublishedPitDataset:
    """PIT result integrated with immutable configuration and derived evidence."""

    selection: PitSelectionResult
    configuration_object: StoredObject
    audit_object: StoredObject
    derived_evidence: DerivedDatasetEvidence


@dataclass(frozen=True, slots=True)
class _Candidate:
    row_index: int
    key_bytes: bytes
    key_digest: str
    vintage_id: str
    availability_boundary_ns: int


def _coerce_as_of(value: datetime | UtcInstant) -> UtcInstant:
    if isinstance(value, UtcInstant):
        return value
    if isinstance(value, datetime):
        return UtcInstant.from_datetime(value)
    raise PitConfigurationError("as_of must be an explicit datetime or UtcInstant")


def _validate_column_name(value: str, role: str) -> None:
    if COLUMN_NAME.fullmatch(value) is None:
        raise PitConfigurationError(f"Malformed {role} column name")


def build_pit_selection_configuration(
    *,
    catalog: VersionedSchemaCatalog,
    input_dataset_id: str,
    as_of: datetime | UtcInstant,
    availability_mode: AvailabilityMode,
    observation_key_columns: Sequence[str],
    vintage_id_column: str,
    temporal_columns: TemporalColumns,
) -> PitSelectionConfiguration:
    """Build the complete canonical policy required for deterministic PIT selection."""
    validate_typed_id(input_dataset_id, RegistryKind.DATASET)
    instant = _coerce_as_of(as_of)
    key_columns = tuple(observation_key_columns)
    if not key_columns or len(key_columns) != len(set(key_columns)):
        raise PitConfigurationError(
            "Observation key columns must be nonempty and unique"
        )
    for name in key_columns:
        _validate_column_name(name, "observation key")
    _validate_column_name(vintage_id_column, "vintage identity")
    temporal_names = tuple(temporal_columns.document().values())
    if any(not isinstance(name, str) for name in temporal_names):
        raise PitConfigurationError("Temporal column names must be strings")
    typed_temporal_names = cast(tuple[str, ...], temporal_names)
    for name in typed_temporal_names:
        _validate_column_name(name, "temporal")
    if len(typed_temporal_names) != len(set(typed_temporal_names)):
        raise PitConfigurationError(
            "The four time concepts and revision status must be distinct"
        )
    forbidden_key_columns = {
        vintage_id_column,
        temporal_columns.publication_time,
        temporal_columns.ingestion_time,
        temporal_columns.revision_time,
        temporal_columns.revision_time_status,
    }
    if forbidden_key_columns.intersection(key_columns):
        raise PitConfigurationError(
            "Observation keys cannot contain vintage or availability-control columns"
        )
    if vintage_id_column in typed_temporal_names:
        raise PitConfigurationError(
            "Vintage identity must be distinct from temporal columns"
        )
    document: JsonRecord = {
        "schema_version": "1.0.0",
        "input_dataset_id": input_dataset_id,
        "as_of": instant.rfc3339,
        "as_of_epoch_nanoseconds": str(instant.epoch_nanoseconds),
        "availability_mode": availability_mode.value,
        "observation_key_columns": list(key_columns),
        "vintage_id_column": vintage_id_column,
        "temporal_columns": temporal_columns.document(),
        "revision_status_values": {
            "not_applicable": RevisionTimeStatus.NOT_APPLICABLE.value,
            "known": RevisionTimeStatus.KNOWN.value,
            "required_unknown": RevisionTimeStatus.REQUIRED_UNKNOWN.value,
        },
        "public_eligibility_rule": (
            "PUBLICATION_AND_APPLICABLE_REVISION_NOT_AFTER_AS_OF"
        ),
        "operational_eligibility_rule": ("PUBLIC_RULES_AND_INGESTION_NOT_AFTER_AS_OF"),
        "vintage_selection_rule": ("LATEST_ELIGIBLE_PUBLIC_AVAILABILITY_BOUNDARY"),
        "ambiguity_policy": "FAIL_CLOSED",
        "output_ordering": "CANONICAL_OBSERVATION_KEY",
    }
    catalog.validate(PIT_CONFIGURATION_SCHEMA, document)
    canonical_bytes = canonicalize_json(document)
    configuration = PitSelectionConfiguration(
        input_dataset_id=input_dataset_id,
        as_of=instant,
        availability_mode=availability_mode,
        observation_key_columns=key_columns,
        vintage_id_column=vintage_id_column,
        temporal_columns=temporal_columns,
        canonical_bytes=canonical_bytes,
        digest=sha256_bytes(canonical_bytes),
    )
    configuration.verify()
    return configuration


def _require_timestamp_column(schema: pa.Schema, name: str) -> pa.TimestampType:
    try:
        field = schema.field(name)
    except KeyError as error:
        raise PitInputError(f"Missing required temporal column: {name}") from error
    if not pa.types.is_timestamp(field.type):
        raise PitInputError(f"Temporal column must use an Arrow timestamp: {name}")
    timestamp_type = cast(pa.TimestampType, field.type)
    if timestamp_type.unit not in {"s", "ms", "us", "ns"}:
        raise PitInputError(f"Unsupported timestamp unit for temporal column: {name}")
    if timestamp_type.tz != "UTC":
        raise PitInputError(f"Temporal column must use explicit UTC timezone: {name}")
    return timestamp_type


def _timestamp_values_ns(
    table: pa.Table, name: str, timestamp_type: pa.TimestampType
) -> list[int | None]:
    multipliers = {
        "s": NANOSECONDS_PER_SECOND,
        "ms": 1_000_000,
        "us": 1_000,
        "ns": 1,
    }
    ticks = table.column(name).combine_chunks().cast(pa.int64()).to_pylist()
    multiplier = multipliers[timestamp_type.unit]
    return [None if value is None else cast(int, value) * multiplier for value in ticks]


def _string_values(table: pa.Table, name: str, role: str) -> list[str]:
    try:
        field = table.schema.field(name)
    except KeyError as error:
        raise PitInputError(f"Missing required {role} column: {name}") from error
    if not pa.types.is_string(field.type):
        raise PitInputError(f"{role.capitalize()} column must use Arrow UTF-8: {name}")
    values = table.column(name).combine_chunks().to_pylist()
    if any(not isinstance(value, str) or not value for value in values):
        raise PitInputError(f"{role.capitalize()} values must be nonempty strings")
    return cast(list[str], values)


def _observation_keys(
    table: pa.Table, columns: tuple[str, ...]
) -> tuple[list[bytes], list[str]]:
    try:
        key_table = table.select(columns)
    except KeyError as error:
        raise PitInputError("An observation key column is missing") from error
    if any(
        key_table.column(index).null_count for index in range(key_table.num_columns)
    ):
        raise PitInputError("Observation key values cannot be null")
    key_bytes = [
        canonical_logical_table_bytes(
            key_table.slice(index, 1), key_table.schema, OrderingSemantics.ORDERED
        )
        for index in range(key_table.num_rows)
    ]
    return key_bytes, [sha256_bytes(value) for value in key_bytes]


def _row_reasons(
    *,
    publication_ns: int | None,
    ingestion_ns: int | None,
    revision_ns: int | None,
    revision_status: RevisionTimeStatus,
    mode: AvailabilityMode,
    as_of_ns: int,
) -> tuple[ExclusionReason, ...]:
    reasons: list[ExclusionReason] = []
    if publication_ns is None:
        reasons.append(ExclusionReason.MISSING_PUBLICATION_TIME)
    elif publication_ns > as_of_ns:
        reasons.append(ExclusionReason.FUTURE_PUBLICATION)
    if revision_status is RevisionTimeStatus.NOT_APPLICABLE:
        if revision_ns is not None:
            reasons.append(ExclusionReason.REVISION_TIME_CONTRADICTS_NOT_APPLICABLE)
    elif revision_status is RevisionTimeStatus.KNOWN:
        if revision_ns is None:
            reasons.append(ExclusionReason.MISSING_REVISION_TIME)
        elif revision_ns > as_of_ns:
            reasons.append(ExclusionReason.FUTURE_REVISION)
    else:
        reasons.append(ExclusionReason.REVISION_TIME_REQUIRED_UNKNOWN)
    if mode is AvailabilityMode.OPERATIONAL:
        if ingestion_ns is None:
            reasons.append(ExclusionReason.MISSING_INGESTION_TIME)
        elif ingestion_ns > as_of_ns:
            reasons.append(ExclusionReason.FUTURE_INGESTION)
    return tuple(reasons)


def select_point_in_time(
    *, table: pa.Table, configuration: PitSelectionConfiguration
) -> PitSelectionResult:
    """Select the latest unambiguous eligible vintage for each observation key."""
    configuration.verify()
    temporal = configuration.temporal_columns
    timestamp_types = {
        name: _require_timestamp_column(table.schema, name)
        for name in (
            temporal.event_time,
            temporal.publication_time,
            temporal.ingestion_time,
            temporal.revision_time,
        )
    }
    try:
        canonical_logical_table_bytes(table, table.schema, OrderingSemantics.UNORDERED)
    except DerivedDataError as error:
        raise PitInputError(
            "Input table violates the governed logical schema"
        ) from error
    time_values = {
        name: _timestamp_values_ns(table, name, timestamp_type)
        for name, timestamp_type in timestamp_types.items()
    }
    vintage_ids = _string_values(
        table, configuration.vintage_id_column, "vintage identity"
    )
    if len(vintage_ids) != len(set(vintage_ids)):
        raise PitInputError("Vintage identities must be globally unique")
    status_values = _string_values(
        table, temporal.revision_time_status, "revision status"
    )
    try:
        revision_statuses = [RevisionTimeStatus(value) for value in status_values]
    except ValueError as error:
        raise PitInputError("Revision status contains an unsupported value") from error
    key_bytes, key_digests = _observation_keys(
        table, configuration.observation_key_columns
    )

    candidates: dict[bytes, list[_Candidate]] = defaultdict(list)
    exclusions_with_keys: list[tuple[bytes, PitExclusion]] = []
    as_of_ns = configuration.as_of.epoch_nanoseconds
    for index, vintage_id in enumerate(vintage_ids):
        publication_ns = time_values[temporal.publication_time][index]
        ingestion_ns = time_values[temporal.ingestion_time][index]
        revision_ns = time_values[temporal.revision_time][index]
        revision_status = revision_statuses[index]
        reasons = _row_reasons(
            publication_ns=publication_ns,
            ingestion_ns=ingestion_ns,
            revision_ns=revision_ns,
            revision_status=revision_status,
            mode=configuration.availability_mode,
            as_of_ns=as_of_ns,
        )
        if reasons:
            exclusions_with_keys.append(
                (
                    key_bytes[index],
                    PitExclusion(key_digests[index], vintage_id, reasons),
                )
            )
            continue
        boundary = cast(int, publication_ns)
        if revision_status is RevisionTimeStatus.KNOWN:
            boundary = max(boundary, cast(int, revision_ns))
        candidates[key_bytes[index]].append(
            _Candidate(
                index, key_bytes[index], key_digests[index], vintage_id, boundary
            )
        )

    selected: list[_Candidate] = []
    for key in sorted(candidates):
        observation_candidates = candidates[key]
        winning_boundary = max(
            candidate.availability_boundary_ns for candidate in observation_candidates
        )
        winners = [
            candidate
            for candidate in observation_candidates
            if candidate.availability_boundary_ns == winning_boundary
        ]
        if len(winners) != 1:
            diagnostic_ids = ",".join(
                sorted(candidate.vintage_id for candidate in winners)
            )
            raise PitAmbiguityError(
                "Ambiguous eligible vintages for observation "
                f"{winners[0].key_digest}: {diagnostic_ids}"
            )
        winner = winners[0]
        selected.append(winner)
        for candidate in observation_candidates:
            if candidate is winner:
                continue
            exclusions_with_keys.append(
                (
                    candidate.key_bytes,
                    PitExclusion(
                        candidate.key_digest,
                        candidate.vintage_id,
                        (ExclusionReason.SUPERSEDED_BY_LATER_ELIGIBLE_VINTAGE,),
                        selected_vintage_id=winner.vintage_id,
                    ),
                )
            )

    selected_indices = [candidate.row_index for candidate in selected]
    if selected_indices:
        selected_table = table.take(pa.array(selected_indices, type=pa.int64()))
    else:
        selected_table = table.slice(0, 0)
    exclusions_with_keys.sort(
        key=lambda item: (
            item[0],
            item[1].vintage_id,
            tuple(reason.value for reason in item[1].reasons),
        )
    )
    exclusions = tuple(exclusion for _key, exclusion in exclusions_with_keys)
    selected_vintage_ids = tuple(candidate.vintage_id for candidate in selected)
    audit_document: JsonRecord = {
        "schema_version": "1.0.0",
        "configuration_digest": configuration.digest,
        "input_dataset_id": configuration.input_dataset_id,
        "as_of": configuration.as_of.rfc3339,
        "availability_mode": configuration.availability_mode.value,
        "input_row_count": table.num_rows,
        "selected_vintage_ids": list(selected_vintage_ids),
        "exclusions": [exclusion.document() for exclusion in exclusions],
    }
    audit_bytes = canonicalize_json(audit_document)
    result = PitSelectionResult(
        configuration=configuration,
        selected_table=selected_table,
        selected_vintage_ids=selected_vintage_ids,
        exclusions=exclusions,
        input_row_count=table.num_rows,
        audit_canonical_bytes=audit_bytes,
        audit_digest=sha256_bytes(audit_bytes),
    )
    result.verify()
    return result


def publish_pit_selection(
    *,
    store: ImmutableObjectStore,
    catalog: VersionedSchemaCatalog,
    selection: PitSelectionResult,
    output_dataset_id: str,
    layer: DerivedLayer,
    parent_evidence: Sequence[ParentEvidence],
    created_at: str,
    producer: ArtifactProducer,
    source_ids: Sequence[str],
    quality_disposition: QualityDisposition,
    references: Sequence[str] = (),
) -> PublishedPitDataset:
    """Publish a normalized or curated PIT result through the three identities."""
    selection.verify()
    catalog.validate(PIT_CONFIGURATION_SCHEMA, selection.configuration.document)
    if layer not in {DerivedLayer.NORMALIZED, DerivedLayer.CURATED}:
        raise PitConfigurationError(
            "PIT publication supports normalized or curated layers"
        )
    parents = tuple(parent_evidence)
    if len(parents) != 1 or parents[0].dataset_id != (
        selection.configuration.input_dataset_id
    ):
        raise PitConfigurationError(
            "PIT publication requires exactly its configured input dataset parent"
        )
    configuration_object = store.publish(selection.configuration.canonical_bytes)
    audit_object = store.publish(selection.audit_canonical_bytes)
    if configuration_object.digest != selection.configuration.digest:
        raise PitIntegrityError("Published PIT configuration identity mismatch")
    if audit_object.digest != selection.audit_digest:
        raise PitIntegrityError("Published PIT audit identity mismatch")
    evidence_references = tuple(
        dict.fromkeys(
            (
                *references,
                store.storage_reference(configuration_object.digest),
                store.storage_reference(audit_object.digest),
            )
        )
    )
    derived_evidence = publish_derived_table(
        store=store,
        catalog=catalog,
        table=selection.selected_table,
        declared_schema=selection.selected_table.schema,
        dataset_id=output_dataset_id,
        layer=layer,
        row_ordering=OrderingSemantics.UNORDERED,
        parent_evidence=parents,
        parent_ordering=OrderingSemantics.ORDERED,
        transformation_identity=PIT_TRANSFORMATION_IDENTITY,
        transformation_configuration_digest=selection.configuration.digest,
        created_at=created_at,
        producer=producer,
        source_ids=source_ids,
        quality_disposition=quality_disposition,
        references=evidence_references,
    )
    published = PublishedPitDataset(
        selection=selection,
        configuration_object=configuration_object,
        audit_object=audit_object,
        derived_evidence=derived_evidence,
    )
    verify_published_pit_dataset(store=store, catalog=catalog, published=published)
    return published


def verify_published_pit_dataset(
    *,
    store: ImmutableObjectStore,
    catalog: VersionedSchemaCatalog,
    published: PublishedPitDataset,
) -> None:
    """Verify PIT configuration/audit objects and their derived lineage binding."""
    published.selection.verify()
    store.verify(published.configuration_object)
    store.verify(published.audit_object)
    if (
        published.configuration_object.digest
        != published.selection.configuration.digest
    ):
        raise PitIntegrityError("PIT configuration object does not match selection")
    if published.audit_object.digest != published.selection.audit_digest:
        raise PitIntegrityError("PIT audit object does not match selection")
    catalog.validate(
        PIT_CONFIGURATION_SCHEMA, published.selection.configuration.document
    )
    evidence = published.derived_evidence
    verify_derived_dataset_evidence(store=store, catalog=catalog, evidence=evidence)
    if len(evidence.parent_evidence) != 1 or evidence.parent_evidence[0].dataset_id != (
        published.selection.configuration.input_dataset_id
    ):
        raise PitIntegrityError("PIT input dataset parent binding mismatch")
    expected_logical = logical_content_fingerprint(
        published.selection.selected_table,
        published.selection.selected_table.schema,
        OrderingSemantics.UNORDERED,
    )
    if evidence.logical_content_fingerprint != expected_logical:
        raise PitIntegrityError("PIT selected logical content does not match evidence")
    lineage = evidence.lineage_manifest.document
    transformation = lineage.get("transformation")
    if not isinstance(transformation, dict):
        raise PitIntegrityError("PIT lineage transformation is malformed")
    if transformation.get("identity") != PIT_TRANSFORMATION_IDENTITY:
        raise PitIntegrityError("PIT lineage transformation identity mismatch")
    if transformation.get("configuration_digest") != (
        published.selection.configuration.digest
    ):
        raise PitIntegrityError("PIT lineage configuration digest mismatch")
    references = lineage.get("references")
    if not isinstance(references, list):
        raise PitIntegrityError("PIT lineage references are malformed")
    required_references = {
        store.storage_reference(published.configuration_object.digest),
        store.storage_reference(published.audit_object.digest),
    }
    if not required_references.issubset(set(cast(list[str], references))):
        raise PitIntegrityError("PIT configuration or audit reference is missing")
