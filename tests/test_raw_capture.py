"""Byte-faithful raw capture, quarantine, and provenance invariants."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.config.schema import RecordSchemaError, VersionedSchemaCatalog
from quant_hunter.provenance import DigestMismatchError, sha256_bytes
from quant_hunter.storage import (
    ArtifactProducer,
    Compression,
    ImmutableObjectStore,
    ObjectCorruptionError,
    QualityDisposition,
    RawCapture,
    RawCaptureMetadata,
    RetrievalStatus,
    SensitiveMetadataError,
    capture_raw_payload,
    verify_raw_capture,
)

SCHEMA_DIRECTORY = Path(__file__).parents[1] / "schemas" / "v1"
SOURCE_ID = "SOURCE-01990f30-7f5e-7b34-9b21-3d74c513c841"
DATASET_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c842"
ENVIRONMENT_DIGEST = "sha256:" + "b" * 64
CONFIGURATION_DIGEST = "sha256:" + "c" * 64


def capture(
    tmp_path: Path,
    *,
    payload: bytes = b"\x00\xffsynthetic provider bytes\r\n",
    ingestion_time: str = "2026-09-05T12:00:00Z",
    native_reference: str = "synthetic-release-1",
    quality: QualityDisposition = QualityDisposition.PENDING,
    request_parameters: JsonRecord | None = None,
    endpoint: str = "https://example.invalid/raw",
    provider: str = "Synthetic Public Provider",
) -> tuple[ImmutableObjectStore, VersionedSchemaCatalog, RawCapture]:
    store = ImmutableObjectStore(tmp_path / "artifacts")
    catalog = VersionedSchemaCatalog(SCHEMA_DIRECTORY)
    result = capture_raw_payload(
        store=store,
        catalog=catalog,
        payload=payload,
        source_id=SOURCE_ID,
        dataset_id=DATASET_ID,
        provider=provider,
        source_endpoint=endpoint,
        request_parameters=request_parameters or {"series": "SYNTHETIC"},
        request_reference="synthetic-request-1",
        media_type="application/octet-stream",
        compression=Compression.NONE,
        ingestion_time=ingestion_time,
        source_native_references=(native_reference,),
        coverage_references=("synthetic-window",),
        retrieval_status=RetrievalStatus.SUCCEEDED,
        quality_disposition=quality,
        warnings=(),
        producer=ArtifactProducer(
            code_revision="a" * 40,
            command="synthetic-capture",
            environment_digest=ENVIRONMENT_DIGEST,
        ),
        configuration_digest=CONFIGURATION_DIGEST,
    )
    return store, catalog, result


def test_raw_payload_is_stored_byte_for_byte_separately_from_metadata(
    tmp_path: Path,
) -> None:
    """Arbitrary provider bytes retain exact physical identity and content."""
    payload = bytes(range(256)) + b"\x00\xff\r\n"
    store, catalog, result = capture(tmp_path, payload=payload)

    assert result.payload.digest == sha256_bytes(payload)
    assert result.payload.byte_size == len(payload)
    assert store.read_bytes(result.payload.digest) == payload
    assert result.metadata.canonical_bytes != payload
    assert result.metadata.document["payload_digest"] == result.payload.digest
    assert result.metadata.document["payload_size"] == len(payload)
    verify_raw_capture(store=store, catalog=catalog, capture=result)


def test_same_payload_deduplicates_with_distinct_capture_provenance(
    tmp_path: Path,
) -> None:
    """Physical deduplication does not collapse distinct provider capture evidence."""
    store, catalog, first = capture(tmp_path, native_reference="provider-v1")
    second = capture_raw_payload(
        store=store,
        catalog=catalog,
        payload=store.read_bytes(first.payload.digest),
        source_id=SOURCE_ID,
        dataset_id=DATASET_ID,
        provider="Synthetic Public Provider",
        source_endpoint="https://example.invalid/raw",
        request_parameters={"series": "SYNTHETIC"},
        request_reference="synthetic-request-2",
        media_type="application/octet-stream",
        compression=Compression.NONE,
        ingestion_time="2026-09-05T12:01:00Z",
        source_native_references=("provider-v2",),
        coverage_references=("synthetic-window",),
        retrieval_status=RetrievalStatus.SUCCEEDED,
        quality_disposition=QualityDisposition.PENDING,
        warnings=("synthetic correction metadata",),
        producer=ArtifactProducer("a" * 40, "synthetic-capture", ENVIRONMENT_DIGEST),
        configuration_digest=CONFIGURATION_DIGEST,
    )

    assert second.payload == first.payload
    assert second.metadata.digest != first.metadata.digest
    assert second.metadata_object.path != first.metadata_object.path
    assert second.metadata.document["source_native_references"] == ["provider-v2"]


def test_provider_correction_is_a_new_raw_object(tmp_path: Path) -> None:
    """A corrected byte creates new evidence and leaves the first capture intact."""
    store, catalog, first = capture(tmp_path, payload=b"provider revision 1")
    second = capture_raw_payload(
        store=store,
        catalog=catalog,
        payload=b"provider revision 2",
        source_id=SOURCE_ID,
        dataset_id=DATASET_ID,
        provider="Synthetic Public Provider",
        source_endpoint="https://example.invalid/raw",
        request_parameters={"series": "SYNTHETIC"},
        request_reference=None,
        media_type="application/octet-stream",
        compression=Compression.UNKNOWN,
        ingestion_time="2026-09-05T12:02:00Z",
        source_native_references=("revision-2",),
        coverage_references=(),
        retrieval_status=RetrievalStatus.PARTIAL,
        quality_disposition=QualityDisposition.QUARANTINED,
        warnings=("synthetic correction",),
        producer=ArtifactProducer("a" * 40, "synthetic-capture", ENVIRONMENT_DIGEST),
    )

    assert first.payload.digest != second.payload.digest
    assert store.read_bytes(first.payload.digest) == b"provider revision 1"
    assert store.read_bytes(second.payload.digest) == b"provider revision 2"


def test_quarantine_preserves_payload_and_never_appears_approved(
    tmp_path: Path,
) -> None:
    """Disposition changes only provenance metadata and cannot rewrite evidence."""
    store, catalog, pending = capture(tmp_path, quality=QualityDisposition.PENDING)
    quarantined = capture_raw_payload(
        store=store,
        catalog=catalog,
        payload=store.read_bytes(pending.payload.digest),
        source_id=SOURCE_ID,
        dataset_id=DATASET_ID,
        provider="Synthetic Public Provider",
        source_endpoint="https://example.invalid/raw",
        request_parameters={"series": "SYNTHETIC"},
        request_reference="quarantine-review",
        media_type="application/octet-stream",
        compression=Compression.NONE,
        ingestion_time="2026-09-05T12:03:00Z",
        source_native_references=("synthetic-release-1",),
        coverage_references=("synthetic-window",),
        retrieval_status=RetrievalStatus.SUCCEEDED,
        quality_disposition=QualityDisposition.QUARANTINED,
        warnings=("synthetic quality concern",),
        producer=ArtifactProducer("a" * 40, "quality-review", ENVIRONMENT_DIGEST),
        configuration_digest=CONFIGURATION_DIGEST,
    )

    assert quarantined.payload == pending.payload
    assert quarantined.metadata.document["quality_disposition"] == "QUARANTINED"
    assert quarantined.metadata.document["quality_disposition"] != "APPROVED"
    assert (
        store.read_bytes(pending.payload.digest)
        == b"\x00\xffsynthetic provider bytes\r\n"
    )


@pytest.mark.parametrize(
    "credential_field",
    ["api_key", "Authorization", "cookie", "client-secret", "access_token"],
)
def test_raw_metadata_rejects_credential_shaped_fields(
    tmp_path: Path, credential_field: str
) -> None:
    """Obvious secret-bearing fields are rejected without persisting metadata."""
    with pytest.raises(SensitiveMetadataError, match="Credential-shaped"):
        capture(
            tmp_path,
            request_parameters={credential_field: "synthetic-secret-value"},
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:password@example.invalid/raw",
        "https://example.invalid/raw?api_key=synthetic-secret-value",
    ],
)
def test_raw_metadata_rejects_credentials_in_endpoint(
    tmp_path: Path, endpoint: str
) -> None:
    """URI userinfo and credential query names cannot enter stored provenance."""
    with pytest.raises(SensitiveMetadataError):
        capture(tmp_path, endpoint=endpoint)


def test_schema_invalid_raw_metadata_fails_before_metadata_publication(
    tmp_path: Path,
) -> None:
    """The existing versioned schema rejects invalid governed capture fields."""
    with pytest.raises(RecordSchemaError, match="provider"):
        capture(tmp_path, provider="")


def test_raw_cross_link_mismatch_is_rejected(tmp_path: Path) -> None:
    """Canonical metadata cannot claim a different physical payload."""
    store, catalog, result = capture(tmp_path)
    document = result.metadata.document
    document["payload_digest"] = "sha256:" + "d" * 64
    canonical_bytes = canonicalize_json(document)
    metadata = RawCaptureMetadata(canonical_bytes, sha256_bytes(canonical_bytes))
    metadata_object = store.publish(canonical_bytes)
    damaged = replace(result, metadata=metadata, metadata_object=metadata_object)

    with pytest.raises(ObjectCorruptionError, match="payload_digest"):
        verify_raw_capture(store=store, catalog=catalog, capture=damaged)


def test_raw_metadata_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    """Changed metadata bytes fail their exact canonical digest contract."""
    store, catalog, result = capture(tmp_path)
    damaged_metadata = replace(
        result.metadata,
        canonical_bytes=result.metadata.canonical_bytes + b" ",
    )
    damaged = replace(result, metadata=damaged_metadata)

    with pytest.raises(DigestMismatchError, match="mismatch"):
        verify_raw_capture(store=store, catalog=catalog, capture=damaged)


def test_raw_metadata_defensive_nonobject_path() -> None:
    """A non-object cannot be interpreted as capture metadata."""
    metadata = RawCaptureMetadata(b"[]", sha256_bytes(b"[]"))
    with pytest.raises(ObjectCorruptionError, match="not a JSON object"):
        _ = metadata.document


def test_raw_capture_rejects_mismatched_stored_sidecar_identities(
    tmp_path: Path,
) -> None:
    """Stored sidecar descriptors must match their canonical in-memory evidence."""
    store, catalog, result = capture(tmp_path)
    wrong_manifest_object = replace(result, artifact_manifest_object=result.payload)
    with pytest.raises(ObjectCorruptionError, match="manifest object identity"):
        verify_raw_capture(store=store, catalog=catalog, capture=wrong_manifest_object)

    wrong_metadata_object = replace(result, metadata_object=result.payload)
    with pytest.raises(ObjectCorruptionError, match="metadata object identity"):
        verify_raw_capture(store=store, catalog=catalog, capture=wrong_metadata_object)


def test_nested_credential_metadata_and_safe_query_branches() -> None:
    """Recursive containers are scanned while ordinary query parameters remain valid."""
    from quant_hunter.storage.security import (
        reject_credential_shaped_fields,
        reject_credential_uri,
    )

    with pytest.raises(SensitiveMetadataError):
        reject_credential_shaped_fields(
            {"outer": {"items": [{"password": "forbidden"}]}}
        )
    reject_credential_uri("https://example.invalid/raw?series=SYNTHETIC")
