"""Synthetic byte-faithful raw capture and separate provenance metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from quant_hunter.config.canonical import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.config.schema import VersionedSchemaCatalog
from quant_hunter.identity.ids import RegistryKind, validate_typed_id
from quant_hunter.provenance.hashing import sha256_bytes, verify_sha256_bytes
from quant_hunter.storage.manifests import (
    ArtifactManifest,
    ArtifactProducer,
    ArtifactProvenance,
    build_artifact_manifest,
    publish_artifact_manifest,
    verify_artifact_binding,
)
from quant_hunter.storage.objects import (
    ImmutableObjectStore,
    ObjectCorruptionError,
    StoredObject,
)
from quant_hunter.storage.security import (
    reject_credential_shaped_fields,
    reject_credential_uri,
)

RAW_CAPTURE_SCHEMA = "raw-capture.schema.json"


class RetrievalStatus(StrEnum):
    """Outcome of obtaining a provider payload, without quality approval."""

    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class QualityDisposition(StrEnum):
    """Recorded raw quality state; quarantined and rejected bytes remain evidence."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class Compression(StrEnum):
    """Known transport or payload compression without decoding the raw bytes."""

    NONE = "NONE"
    GZIP = "GZIP"
    ZIP = "ZIP"
    BZIP2 = "BZIP2"
    XZ = "XZ"
    ZSTANDARD = "ZSTANDARD"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RawCaptureMetadata:
    """Immutable canonical capture metadata stored separately from raw bytes."""

    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise ObjectCorruptionError("Raw capture metadata is not a JSON object")
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)


@dataclass(frozen=True, slots=True)
class RawCapture:
    """Separate immutable payload, artifact sidecar, and capture metadata objects."""

    payload: StoredObject
    artifact_manifest: ArtifactManifest
    artifact_manifest_object: StoredObject
    metadata: RawCaptureMetadata
    metadata_object: StoredObject


def capture_raw_payload(
    *,
    store: ImmutableObjectStore,
    catalog: VersionedSchemaCatalog,
    payload: bytes,
    source_id: str,
    dataset_id: str,
    provider: str,
    source_endpoint: str,
    request_parameters: Mapping[str, JsonValue],
    request_reference: str | None,
    media_type: str,
    compression: Compression,
    ingestion_time: str,
    source_native_references: Sequence[str],
    coverage_references: Sequence[str],
    retrieval_status: RetrievalStatus,
    quality_disposition: QualityDisposition,
    warnings: Sequence[str],
    producer: ArtifactProducer,
    configuration_digest: str | None = None,
) -> RawCapture:
    """Persist exact received bytes and independent governed provenance metadata."""
    validate_typed_id(source_id, RegistryKind.SOURCE)
    validate_typed_id(dataset_id, RegistryKind.DATASET)
    reject_credential_uri(source_endpoint)
    if request_reference is not None:
        reject_credential_uri(request_reference)
    parameter_record = dict(request_parameters)
    reject_credential_shaped_fields(parameter_record)

    stored_payload = store.publish(payload)
    provenance_references = [source_endpoint]
    if request_reference is not None:
        provenance_references.append(request_reference)
    artifact_manifest = build_artifact_manifest(
        store=store,
        catalog=catalog,
        stored_object=stored_payload,
        artifact_type="dataset",
        media_type=media_type,
        created_at=ingestion_time,
        producer=producer,
        provenance=ArtifactProvenance(
            source_ids=(source_id,),
            dataset_ids=(dataset_id,),
            references=tuple(dict.fromkeys(provenance_references)),
            configuration_digest=configuration_digest,
        ),
    )
    artifact_manifest_object = publish_artifact_manifest(store, artifact_manifest)

    source_reference_values: list[JsonValue] = list(source_native_references)
    coverage_reference_values: list[JsonValue] = list(coverage_references)
    warning_values: list[JsonValue] = list(warnings)
    document: JsonRecord = {
        "schema_version": "1.0.0",
        "source_id": source_id,
        "dataset_id": dataset_id,
        "provider": provider,
        "source_endpoint": source_endpoint,
        "request": {
            "parameters": parameter_record,
            "reference": request_reference,
        },
        "payload_digest": stored_payload.digest,
        "payload_size": stored_payload.byte_size,
        "storage_reference": store.storage_reference(stored_payload.digest),
        "media_type": media_type,
        "compression": compression.value,
        "ingestion_time": ingestion_time,
        "source_native_references": source_reference_values,
        "coverage_references": coverage_reference_values,
        "retrieval_status": retrieval_status.value,
        "quality_disposition": quality_disposition.value,
        "warnings": warning_values,
        "artifact_manifest_digest": artifact_manifest.digest,
    }
    catalog.validate(RAW_CAPTURE_SCHEMA, document)
    canonical_bytes = canonicalize_json(document)
    metadata = RawCaptureMetadata(canonical_bytes, sha256_bytes(canonical_bytes))
    metadata.verify()
    metadata_object = store.publish(canonical_bytes)
    capture = RawCapture(
        payload=stored_payload,
        artifact_manifest=artifact_manifest,
        artifact_manifest_object=artifact_manifest_object,
        metadata=metadata,
        metadata_object=metadata_object,
    )
    verify_raw_capture(store=store, catalog=catalog, capture=capture)
    return capture


def verify_raw_capture(
    *,
    store: ImmutableObjectStore,
    catalog: VersionedSchemaCatalog,
    capture: RawCapture,
) -> None:
    """Verify every exact-byte and canonical link in a raw capture."""
    store.verify(capture.payload)
    store.verify(capture.artifact_manifest_object)
    store.verify(capture.metadata_object)
    capture.artifact_manifest.verify()
    capture.metadata.verify()
    verify_artifact_binding(capture.artifact_manifest, capture.payload)
    document = capture.metadata.document
    catalog.validate(RAW_CAPTURE_SCHEMA, document)
    expected = {
        "payload_digest": capture.payload.digest,
        "payload_size": capture.payload.byte_size,
        "storage_reference": store.storage_reference(capture.payload.digest),
        "artifact_manifest_digest": capture.artifact_manifest.digest,
    }
    for field, value in expected.items():
        if document.get(field) != value:
            raise ObjectCorruptionError(f"Raw capture {field} does not match evidence")
    if capture.artifact_manifest_object.digest != capture.artifact_manifest.digest:
        raise ObjectCorruptionError("Artifact manifest object identity mismatch")
    if capture.metadata_object.digest != capture.metadata.digest:
        raise ObjectCorruptionError("Raw capture metadata object identity mismatch")
