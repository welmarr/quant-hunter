"""Schema-governed JCS sidecars for immutable exact-byte artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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
    verify_sha256_bytes,
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

ARTIFACT_MANIFEST_SCHEMA = "artifact-manifest.schema.json"


@dataclass(frozen=True, slots=True)
class ArtifactProducer:
    """Reproducible creation metadata required by the artifact schema."""

    code_revision: str
    command: str
    environment_digest: str


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    """Backward links from an artifact to sources, datasets, and configuration."""

    source_ids: Sequence[str] = ()
    dataset_ids: Sequence[str] = ()
    references: Sequence[str] = ()
    configuration_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Immutable canonical sidecar bytes and their SHA-256 identity."""

    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise ObjectCorruptionError("Artifact manifest is not a JSON object")
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)


def build_artifact_manifest(
    *,
    store: ImmutableObjectStore,
    catalog: VersionedSchemaCatalog,
    stored_object: StoredObject,
    artifact_type: str,
    media_type: str,
    created_at: str,
    producer: ArtifactProducer,
    provenance: ArtifactProvenance,
    parent_digests: Sequence[str] = (),
) -> ArtifactManifest:
    """Build and validate a canonical sidecar for one immutable physical object."""
    store.verify(stored_object)
    require_sha256_digest(stored_object.digest)
    require_sha256_digest(producer.environment_digest)
    if provenance.configuration_digest is not None:
        require_sha256_digest(provenance.configuration_digest)
    for source_id in provenance.source_ids:
        validate_typed_id(source_id, RegistryKind.SOURCE)
    for dataset_id in provenance.dataset_ids:
        validate_typed_id(dataset_id, RegistryKind.DATASET)
    parent_values: list[JsonValue] = []
    for digest in parent_digests:
        require_sha256_digest(digest)
        parent_values.append(digest)
    source_values: list[JsonValue] = list(provenance.source_ids)
    dataset_values: list[JsonValue] = list(provenance.dataset_ids)
    reference_values: list[JsonValue] = list(provenance.references)
    document: JsonRecord = {
        "schema_version": "1.0.0",
        "artifact_digest": stored_object.digest,
        "artifact_type": artifact_type,
        "media_type": media_type,
        "byte_size": stored_object.byte_size,
        "created_at": created_at,
        "producer": {
            "code_revision": producer.code_revision,
            "command": producer.command,
            "environment_digest": producer.environment_digest,
        },
        "provenance": {
            "source_ids": source_values,
            "dataset_ids": dataset_values,
            "references": reference_values,
            "configuration_digest": provenance.configuration_digest,
        },
        "parent_digests": parent_values,
    }
    reject_credential_shaped_fields(document)
    for reference in provenance.references:
        reject_credential_uri(reference)
    catalog.validate(ARTIFACT_MANIFEST_SCHEMA, document)
    canonical_bytes = canonicalize_json(document)
    manifest = ArtifactManifest(canonical_bytes, sha256_bytes(canonical_bytes))
    manifest.verify()
    return manifest


def verify_artifact_binding(
    manifest: ArtifactManifest, stored_object: StoredObject
) -> None:
    """Require a manifest to identify the supplied exact physical object."""
    manifest.verify()
    document = manifest.document
    if document.get("artifact_digest") != stored_object.digest:
        raise ObjectCorruptionError("Manifest digest does not match physical object")
    if document.get("byte_size") != stored_object.byte_size:
        raise ObjectCorruptionError("Manifest size does not match physical object")


def publish_artifact_manifest(
    store: ImmutableObjectStore, manifest: ArtifactManifest
) -> StoredObject:
    """Publish canonical sidecar bytes in the same immutable object namespace."""
    manifest.verify()
    stored = store.publish(manifest.canonical_bytes)
    if stored.digest != manifest.digest:
        raise ObjectCorruptionError("Published manifest digest changed unexpectedly")
    return stored
