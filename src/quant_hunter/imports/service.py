"""Immutable uploaded-data versions using the existing governed data contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.config.canonical import canonicalize_json, parse_json_document
from quant_hunter.config.schema import VersionedSchemaCatalog
from quant_hunter.data import (
    DEFAULT_PARQUET_PROFILE,
    DatasetLineageManifest,
    DerivedDatasetEvidence,
    DerivedLayer,
    OrderingSemantics,
    ParentEvidence,
    deterministic_parquet_bytes,
    logical_content_fingerprint,
    logical_schema_digest,
    logical_schema_document,
    parquet_writer_profile_digest,
    publish_derived_table,
    verify_dataset_record_binding,
    verify_derived_dataset_evidence,
)
from quant_hunter.identity import RegistryKind, RegistryStore, new_typed_id
from quant_hunter.imports.validation import (
    MAX_RAW_BYTES,
    ImportValidationError,
    decode,
    metadata_document,
    text,
)
from quant_hunter.provenance.hashing import require_sha256_digest, sha256_bytes
from quant_hunter.storage import (
    ArtifactManifest,
    ArtifactProducer,
    Compression,
    ImmutableObjectStore,
    ObjectCorruptionError,
    QualityDisposition,
    RawCapture,
    RawCaptureMetadata,
    RetrievalStatus,
    capture_raw_payload,
    verify_raw_capture,
)
from quant_hunter.storage.security import reject_secret_text_values

TRANSFORMATION = "qh-bounded-market-import-v1"
RAW_TRANSFORMATION = "qh-exact-upload-with-declared-decoding-v1"
_COMMAND = "quant-hunter bounded local import"
_ENDPOINT = "upload://local/bytes"
_LIMITATIONS = (
    "Structural validation only; no empirical strategy validation or HOST_ENFORCED authority.",
    "Source, license and availability declarations are supplied by the uploader and unverified.",
    "Opening bid/ask are indicative unless independently reviewed; close is a valuation mark.",
    "No corporate-action, exchange-calendar, completeness, outlier or survivorship certification.",
    "Historical source revision vintages are unknown; confirmatory PIT use is blocked.",
    "Optional high/low must envelope both opening quotes and close under this import contract.",
    "Zero cost describes local ingestion only; upstream acquisition and subscription costs are unknown.",
)


def _stamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise ObjectCorruptionError("Import evidence must be an object")
    return value


def _equal(actual: Mapping[str, JsonValue], expected: Mapping[str, JsonValue]) -> None:
    if any(
        key not in actual or actual[key] != value for key, value in expected.items()
    ):
        raise ObjectCorruptionError(
            "Import evidence disagrees with its registered authority"
        )


def _source(metadata: JsonRecord, created_at: str) -> JsonRecord:
    return {
        "schema_version": "1.0.0",
        "created_at": created_at,
        "reviewed_at": created_at,
        "status": "CANDIDATE",
        "provider": metadata["source_name"],
        "documentation_uri": _ENDPOINT,
        "data_domain": "Uploader-declared market bars",
        "granularity": "Explicit open/close intervals in uploaded observations",
        "historical_depth": "Only the immutable uploaded version; broader coverage UNKNOWN",
        "realtime_availability": "HISTORICAL_ONLY",
        "latency_description": "Uploader-declared availability; no independent latency evidence",
        "cost": {
            "class": "FREE",
            "currency": "USD",
            "monthly_cost": "0",
            "pricing_date": created_at[:10],
        },
        "access": {
            "license": metadata["declared_license"],
            "api_restrictions": "Local bytes only; no provider API",
            "redistribution_restrictions": metadata["declared_restrictions"],
            "retention_constraints": "Declared license requires independent review; no sharing approved",
        },
        "time_semantics": {
            "event_time": "NATIVE",
            "publication_time": "UNKNOWN",
            "ingestion_time": "DERIVED",
            "revision_time": "UNKNOWN",
        },
        "price_nature": "INDICATIVE",
        "reliability": "UNKNOWN; structural checks only",
        "limitations": list(_LIMITATIONS),
        "owner": "local-uploader",
    }


def _normalized(
    table: Any, rows: list[dict[str, object]], created_at: str, mode: str
) -> Any:
    fields = [
        *table.schema,
        pa.field("ingestion_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("revision_time", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("revision_time_status", pa.string(), nullable=False),
    ]
    ingestion = datetime.fromisoformat(created_at)
    values = [
        {
            **row,
            "ingestion_time": ingestion,
            "revision_time": None,
            "revision_time_status": "REQUIRED_UNKNOWN"
            if mode == "HISTORICAL"
            else "NOT_APPLICABLE",
        }
        for row in rows
    ]
    return pa.Table.from_pylist(values, schema=pa.schema(fields))


def _bounds(rows: list[dict[str, object]]) -> JsonRecord:
    return {
        "start": _stamp(cast(datetime, rows[0]["open_at"])),
        "end": _stamp(cast(datetime, rows[-1]["close_at"]) + timedelta(microseconds=1)),
    }


class ImportService:
    """Import local byte payloads; data remains PENDING independent source review.

    The constructor receives existing governed authorities. The caller enforces
    ownership for every dataset before using get/list; this service does not
    grant access or create experiments. Corrections create fresh dataset IDs.
    """

    def __init__(
        self,
        registry: RegistryStore,
        objects: ImmutableObjectStore,
        schema_root: Path,
        code_revision: str,
        environment_digest: str,
    ) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", code_revision) is None:
            raise ImportValidationError("INVALID_CODE_REVISION")
        require_sha256_digest(environment_digest)
        environment = _record(
            parse_json_document(objects.read_bytes(environment_digest))
        )
        if "source_snapshot_digest" in environment:
            objects.get(cast(str, environment["source_snapshot_digest"]))
        self.registry, self.objects = registry, objects
        self.catalog = VersionedSchemaCatalog(schema_root)
        self.code_revision, self.environment_digest = code_revision, environment_digest

    def import_bytes(
        self,
        payload: bytes,
        *,
        file_format: str,
        metadata: Mapping[str, JsonValue],
        corrects_dataset_id: str | None = None,
        correction_reason: str | None = None,
    ) -> JsonRecord:
        """Validate all rows, retain exact raw bytes, then publish a new version."""
        try:
            supplied = metadata_document(metadata)
            table, rows = decode(payload, file_format)
            if (corrects_dataset_id is None) != (correction_reason is None):
                raise ImportValidationError("CORRECTION_REQUIRES_ID_AND_REASON")
            prior: JsonRecord | None = None
            if corrects_dataset_id is not None:
                prior = self.get_dataset(corrects_dataset_id)
                text(correction_reason, maximum=500)
                try:
                    reject_secret_text_values(correction_reason, "correction reason")
                except ValueError:
                    raise ImportValidationError("SENSITIVE_METADATA") from None
                if (
                    _record(prior["metadata"])["instrument"] != supplied["instrument"]
                    or _record(prior["metadata"])["evidence_mode"]
                    != supplied["evidence_mode"]
                ):
                    raise ImportValidationError("CORRECTION_IDENTITY_MISMATCH")
        except ImportValidationError as error:
            self._audit_failure(payload, file_format, error)
            raise
        created_at = _stamp(datetime.now(UTC))
        source = self.registry.allocate(
            RegistryKind.SOURCE, _source(supplied, created_at)
        )
        raw_id = new_typed_id(RegistryKind.DATASET)
        normalized_id = new_typed_id(RegistryKind.DATASET)
        producer = ArtifactProducer(
            self.code_revision, _COMMAND, self.environment_digest
        )
        raw_schema = self.objects.publish(
            canonicalize_json(
                logical_schema_document(table.schema, OrderingSemantics.ORDERED)
            )
        )
        raw_logical = logical_content_fingerprint(
            table, table.schema, OrderingSemantics.ORDERED
        )
        initial_config: JsonRecord = {
            "schema_version": "qh-upload-config-v1",
            "file_format": file_format,
            "metadata": supplied,
            "raw_dataset_id": raw_id,
            "normalized_dataset_id": normalized_id,
            "source_id": source.object_id,
            "source_record_digest": source.revision.digest,
            "code_revision": self.code_revision,
            "environment_digest": self.environment_digest,
            "corrects_dataset_id": corrects_dataset_id,
            "correction_reason": correction_reason,
            "corrects_record_digest": prior["record_digest"] if prior else None,
            "raw_schema_digest": raw_schema.digest,
            "raw_logical_fingerprint": raw_logical,
            "decoder": "Strict UTC and decimal128(38,12); no rounding, sorting or dropping",
        }
        initial = self.objects.publish(canonicalize_json(initial_config))
        capture = capture_raw_payload(
            store=self.objects,
            catalog=self.catalog,
            payload=payload,
            source_id=source.object_id,
            dataset_id=raw_id,
            provider=cast(str, supplied["source_name"]),
            source_endpoint=_ENDPOINT,
            request_parameters={"format": file_format},
            request_reference=f"artifact:{initial.digest}",
            media_type="text/csv"
            if file_format == "CSV"
            else "application/vnd.apache.parquet",
            compression=Compression.NONE if file_format == "CSV" else Compression.OTHER,
            ingestion_time=created_at,
            source_native_references=[
                cast(str, _record(supplied["instrument"])["symbol"])
            ],
            coverage_references=[cast(str, value) for value in _bounds(rows).values()],
            retrieval_status=RetrievalStatus.SUCCEEDED,
            quality_disposition=QualityDisposition.PENDING,
            warnings=list(_LIMITATIONS),
            producer=producer,
            configuration_digest=initial.digest,
        )
        raw_record: JsonRecord = {
            "schema_version": "1.0.0",
            "created_at": created_at,
            "layer": "raw_landing",
            "source_ids": [source.object_id],
            "coverage": _bounds(rows),
            "time_fields": {
                "event_time": "close_at",
                "publication_time": "available_at",
                "ingestion_time": "NOT_APPLICABLE",
                "revision_time": "NOT_APPLICABLE",
            },
            "schema_digest": raw_schema.digest,
            "physical_object_digest": capture.payload.digest,
            "provenance_lineage_digest": capture.metadata.digest,
            "logical_content_fingerprint": raw_logical,
            "provenance": {
                "parent_dataset_ids": [],
                "transformation": RAW_TRANSFORMATION,
                "code_revision": self.code_revision,
                "environment_digest": self.environment_digest,
            },
            "quality_status": "PENDING",
        }
        raw_revision = self.registry.create_initial(
            RegistryKind.DATASET, raw_id, raw_record
        )
        parent = ParentEvidence(
            raw_id,
            raw_revision.digest,
            capture.payload.digest,
            capture.metadata.digest,
            raw_logical,
        )
        configuration = self.objects.publish(
            canonicalize_json(
                {
                    **initial_config,
                    "initial_configuration_digest": initial.digest,
                    "raw_record_digest": raw_revision.digest,
                    "raw_digest": capture.payload.digest,
                    "raw_capture_digest": capture.metadata.digest,
                    "raw_artifact_digest": capture.artifact_manifest.digest,
                }
            )
        )
        normalized = _normalized(
            table, rows, created_at, cast(str, supplied["evidence_mode"])
        )
        evidence = publish_derived_table(
            store=self.objects,
            catalog=self.catalog,
            table=normalized,
            declared_schema=normalized.schema,
            dataset_id=normalized_id,
            layer=DerivedLayer.NORMALIZED,
            row_ordering=OrderingSemantics.ORDERED,
            parent_evidence=[parent],
            parent_ordering=OrderingSemantics.ORDERED,
            transformation_identity=TRANSFORMATION,
            transformation_configuration_digest=configuration.digest,
            created_at=created_at,
            producer=producer,
            source_ids=[source.object_id],
            quality_disposition=QualityDisposition.PENDING,
            references=[
                f"artifact:{capture.metadata.digest}",
                f"artifact:{initial.digest}",
            ],
        )
        normalized_record: JsonRecord = {
            "schema_version": "1.0.0",
            "created_at": created_at,
            "layer": "normalized",
            "source_ids": [source.object_id],
            "coverage": _bounds(rows),
            "time_fields": {
                "event_time": "close_at",
                "publication_time": "available_at",
                "ingestion_time": "ingestion_time",
                "revision_time": "revision_time",
            },
            "schema_digest": evidence.schema_digest,
            "physical_object_digest": evidence.parquet_object.digest,
            "provenance_lineage_digest": evidence.lineage_manifest.digest,
            "logical_content_fingerprint": evidence.logical_content_fingerprint,
            "provenance": {
                "parent_dataset_ids": [raw_id],
                "transformation": TRANSFORMATION,
                "code_revision": self.code_revision,
                "environment_digest": self.environment_digest,
            },
            "quality_status": "PENDING",
        }
        registered = self.registry.create_initial(
            RegistryKind.DATASET, normalized_id, normalized_record
        )
        verify_dataset_record_binding(
            catalog=self.catalog, record=registered.record, evidence=evidence
        )
        return self.get_dataset(normalized_id)

    def _audit_failure(
        self, payload: bytes, file_format: str, error: ImportValidationError
    ) -> None:
        audit: JsonRecord = {
            "schema_version": "qh-import-failure-v1",
            "created_at": _stamp(datetime.now(UTC)),
            "error_code": error.code,
            "file_format": file_format
            if file_format in {"CSV", "PARQUET"}
            else "UNKNOWN",
            "raw_size": len(payload) if isinstance(payload, bytes) else None,
            "raw_digest": sha256_bytes(payload)
            if isinstance(payload, bytes) and len(payload) <= MAX_RAW_BYTES
            else None,
            "raw_retained": False,
        }
        error.audit_digest = self.objects.publish(canonicalize_json(audit)).digest

    def _read(self, digest: str) -> JsonRecord:
        return _record(parse_json_document(self.objects.read_bytes(digest)))

    def get_dataset(self, dataset_id: str) -> JsonRecord:
        """Reverify source/raw/normalized identities and deterministic replay."""
        if not dataset_id.startswith("DATASET-"):
            raise ImportValidationError("INVALID_DATASET_ID")
        revision = self.registry.verify_object(dataset_id)[-1]
        record = revision.record
        provenance = _record(record["provenance"])
        if (
            provenance.get("transformation") != TRANSFORMATION
            or record["layer"] != "normalized"
        ):
            raise ImportValidationError("NOT_AN_IMPORTED_DATASET")
        lineage_digest = cast(str, record["provenance_lineage_digest"])
        lineage_bytes = self.objects.read_bytes(lineage_digest)
        lineage = _record(parse_json_document(lineage_bytes))
        config_digest = cast(
            str, _record(lineage["transformation"])["configuration_digest"]
        )
        config = self._read(config_digest)
        metadata = metadata_document(_record(config["metadata"]))
        initial_digest = cast(str, config["initial_configuration_digest"])
        initial = self._read(initial_digest)
        _equal(config, initial)
        source_id, raw_id = (
            cast(str, config["source_id"]),
            cast(str, config["raw_dataset_id"]),
        )
        source = self.registry.verify_object(source_id)[0]
        raw = self.registry.verify_object(raw_id)[0]
        _equal(
            config,
            {
                "schema_version": "qh-upload-config-v1",
                "normalized_dataset_id": dataset_id,
                "source_record_digest": source.digest,
                "raw_record_digest": raw.digest,
            },
        )
        _equal(source.record, _source(metadata, cast(str, record["created_at"])))
        raw_bytes = self.objects.read_bytes(cast(str, config["raw_digest"]))
        table, rows = decode(raw_bytes, cast(str, config["file_format"]))
        raw_schema_digest = logical_schema_digest(
            table.schema, OrderingSemantics.ORDERED
        )
        raw_logical = logical_content_fingerprint(
            table, table.schema, OrderingSemantics.ORDERED
        )
        self.objects.get(raw_schema_digest)
        _equal(
            config,
            {
                "raw_schema_digest": raw_schema_digest,
                "raw_logical_fingerprint": raw_logical,
            },
        )
        _equal(
            raw.record,
            {
                "created_at": record["created_at"],
                "layer": "raw_landing",
                "source_ids": [source_id],
                "coverage": _bounds(rows),
                "schema_digest": raw_schema_digest,
                "physical_object_digest": config["raw_digest"],
                "provenance_lineage_digest": config["raw_capture_digest"],
                "logical_content_fingerprint": raw_logical,
                "quality_status": "PENDING",
                "time_fields": {
                    "event_time": "close_at",
                    "publication_time": "available_at",
                    "ingestion_time": "NOT_APPLICABLE",
                    "revision_time": "NOT_APPLICABLE",
                },
            },
        )
        _equal(
            _record(raw.record["provenance"]),
            {
                "parent_dataset_ids": [],
                "transformation": RAW_TRANSFORMATION,
                "code_revision": config["code_revision"],
                "environment_digest": config["environment_digest"],
            },
        )
        environment = self._read(cast(str, config["environment_digest"]))
        if "source_snapshot_digest" in environment:
            self.objects.get(cast(str, environment["source_snapshot_digest"]))
        self._verify_capture(config, raw_bytes, cast(str, record["created_at"]), rows)
        normalized = _normalized(
            table,
            rows,
            cast(str, record["created_at"]),
            cast(str, metadata["evidence_mode"]),
        )
        parent = ParentEvidence(
            raw_id,
            raw.digest,
            cast(str, config["raw_digest"]),
            cast(str, config["raw_capture_digest"]),
            raw_logical,
        )
        artifact_digest = cast(str, lineage["physical_artifact_manifest_digest"])
        evidence = DerivedDatasetEvidence(
            dataset_id=dataset_id,
            layer=DerivedLayer.NORMALIZED,
            quality_disposition=QualityDisposition.PENDING,
            row_ordering=OrderingSemantics.ORDERED,
            parent_ordering=OrderingSemantics.ORDERED,
            declared_schema=normalized.schema,
            writer_profile=DEFAULT_PARQUET_PROFILE,
            parent_evidence=(parent,),
            parquet_object=self.objects.get(
                cast(str, record["physical_object_digest"])
            ),
            artifact_manifest=ArtifactManifest(
                self.objects.read_bytes(artifact_digest), artifact_digest
            ),
            artifact_manifest_object=self.objects.get(artifact_digest),
            lineage_manifest=DatasetLineageManifest(lineage_bytes, lineage_digest),
            lineage_manifest_object=self.objects.get(lineage_digest),
            schema_digest=logical_schema_digest(
                normalized.schema, OrderingSemantics.ORDERED
            ),
            logical_content_fingerprint=logical_content_fingerprint(
                normalized, normalized.schema, OrderingSemantics.ORDERED
            ),
            writer_profile_digest=parquet_writer_profile_digest(
                DEFAULT_PARQUET_PROFILE
            ),
        )
        verify_dataset_record_binding(
            catalog=self.catalog, record=record, evidence=evidence
        )
        _equal(
            record,
            {
                "coverage": _bounds(rows),
                "source_ids": [source_id],
                "time_fields": {
                    "event_time": "close_at",
                    "publication_time": "available_at",
                    "ingestion_time": "ingestion_time",
                    "revision_time": "revision_time",
                },
            },
        )
        _equal(
            _record(lineage["producer"]),
            {
                "code_revision": config["code_revision"],
                "environment_digest": config["environment_digest"],
            },
        )
        _equal(
            lineage,
            {
                "references": [
                    f"artifact:{config['raw_capture_digest']}",
                    f"artifact:{initial_digest}",
                ]
            },
        )
        _equal(
            _record(evidence.artifact_manifest.document["producer"]),
            {"command": _COMMAND},
        )
        expected = deterministic_parquet_bytes(
            normalized, normalized.schema, OrderingSemantics.ORDERED
        )
        if self.objects.read_bytes(evidence.parquet_object.digest) != expected:
            raise ObjectCorruptionError(
                "Imported normalized bytes differ from deterministic raw replay"
            )
        verify_derived_dataset_evidence(
            store=self.objects, catalog=self.catalog, evidence=evidence
        )
        if config["corrects_dataset_id"] is not None:
            corrected = self.registry.verify_object(
                cast(str, config["corrects_dataset_id"])
            )[0]
            if corrected.digest != config["corrects_record_digest"]:
                raise ObjectCorruptionError(
                    "Correction reference differs from retained version"
                )
            if (
                corrected.record["layer"] != "normalized"
                or _record(corrected.record["provenance"]).get("transformation")
                != TRANSFORMATION
            ):
                raise ObjectCorruptionError("Correction refers to a foreign dataset")
            prior_lineage = self._read(
                cast(str, corrected.record["provenance_lineage_digest"])
            )
            prior_config = self._read(
                cast(
                    str,
                    _record(prior_lineage["transformation"])["configuration_digest"],
                )
            )
            prior_metadata = metadata_document(_record(prior_config["metadata"]))
            if (
                corrected.record["dataset_id"] == dataset_id
                or prior_config["normalized_dataset_id"]
                != config["corrects_dataset_id"]
                or prior_metadata["instrument"] != metadata["instrument"]
                or prior_metadata["evidence_mode"] != metadata["evidence_mode"]
            ):
                raise ObjectCorruptionError(
                    "Correction identity differs from retained version"
                )
        preview: list[JsonValue] = []
        for row in rows[:20]:
            preview.append(
                {
                    key: _stamp(value) if isinstance(value, datetime) else str(value)
                    for key, value in row.items()
                }
            )
        return {
            "dataset_id": dataset_id,
            "record_digest": revision.digest,
            "source_id": source_id,
            "raw_dataset_id": raw_id,
            "raw_digest": config["raw_digest"],
            "normalized_digest": evidence.parquet_object.digest,
            "lineage_digest": lineage_digest,
            "logical_fingerprint": evidence.logical_content_fingerprint,
            "schema_digest": evidence.schema_digest,
            "configuration_digest": config_digest,
            "raw_capture_digest": config["raw_capture_digest"],
            "file_format": config["file_format"],
            "created_at": record["created_at"],
            "row_count": len(rows),
            "columns": cast(list[JsonValue], table.column_names),
            "bounds": _bounds(rows),
            "metadata": metadata,
            "quality": "STRUCTURAL_PASS_REVIEW_PENDING",
            "availability": "UPLOADER_DECLARED_UNVERIFIED",
            "licensing": "DECLARED_UNVERIFIED",
            "empirically_validated": False,
            "host_enforced": False,
            "corrects_dataset_id": config["corrects_dataset_id"],
            "correction_reason": config["correction_reason"],
            "limitations": list(_LIMITATIONS),
            "preview": preview,
        }

    def _verify_capture(
        self,
        config: JsonRecord,
        raw_bytes: bytes,
        created_at: str,
        rows: list[dict[str, object]],
    ) -> None:
        metadata_digest, artifact_digest = (
            cast(str, config["raw_capture_digest"]),
            cast(str, config["raw_artifact_digest"]),
        )
        capture = RawCapture(
            payload=self.objects.get(sha256_bytes(raw_bytes)),
            artifact_manifest=ArtifactManifest(
                self.objects.read_bytes(artifact_digest), artifact_digest
            ),
            artifact_manifest_object=self.objects.get(artifact_digest),
            metadata=RawCaptureMetadata(
                self.objects.read_bytes(metadata_digest), metadata_digest
            ),
            metadata_object=self.objects.get(metadata_digest),
        )
        verify_raw_capture(store=self.objects, catalog=self.catalog, capture=capture)
        metadata = _record(config["metadata"])
        _equal(
            capture.metadata.document,
            {
                "source_id": config["source_id"],
                "dataset_id": config["raw_dataset_id"],
                "provider": metadata["source_name"],
                "source_endpoint": _ENDPOINT,
                "ingestion_time": created_at,
                "media_type": "text/csv"
                if config["file_format"] == "CSV"
                else "application/vnd.apache.parquet",
                "compression": "NONE" if config["file_format"] == "CSV" else "OTHER",
                "quality_disposition": "PENDING",
                "retrieval_status": "SUCCEEDED",
                "warnings": list(_LIMITATIONS),
                "source_native_references": [_record(metadata["instrument"])["symbol"]],
                "coverage_references": list(_bounds(rows).values()),
                "request": {
                    "parameters": {"format": config["file_format"]},
                    "reference": f"artifact:{config['initial_configuration_digest']}",
                },
            },
        )
        _equal(
            _record(capture.artifact_manifest.document["producer"]),
            {
                "code_revision": config["code_revision"],
                "environment_digest": config["environment_digest"],
                "command": _COMMAND,
            },
        )
        _equal(
            _record(capture.artifact_manifest.document["provenance"]),
            {"configuration_digest": config["initial_configuration_digest"]},
        )

    def list_datasets(self) -> list[JsonRecord]:
        """Return only this importer's verified normalized versions, never other registries."""
        candidates: list[str] = []
        for object_id, revisions in self.registry.verify_all().items():
            if not object_id.startswith("DATASET-"):
                continue
            record = revisions[-1].record
            provenance = record.get("provenance")
            if (
                isinstance(provenance, dict)
                and provenance.get("transformation") == TRANSFORMATION
            ):
                candidates.append(object_id)
        return [self.get_dataset(item) for item in candidates]
