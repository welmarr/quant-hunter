"""Immutable local artifact storage and byte-faithful raw capture contracts."""

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
    ObjectPublicationError,
    ObjectStoreError,
    StoredObject,
    UnsafeArtifactRootError,
    UnsafeObjectPathError,
)
from quant_hunter.storage.raw import (
    Compression,
    QualityDisposition,
    RawCapture,
    RawCaptureMetadata,
    RetrievalStatus,
    capture_raw_payload,
    verify_raw_capture,
)
from quant_hunter.storage.security import SensitiveMetadataError

__all__ = (
    "ArtifactManifest",
    "ArtifactProducer",
    "ArtifactProvenance",
    "Compression",
    "ImmutableObjectStore",
    "ObjectCorruptionError",
    "ObjectPublicationError",
    "ObjectStoreError",
    "QualityDisposition",
    "RawCapture",
    "RawCaptureMetadata",
    "RetrievalStatus",
    "SensitiveMetadataError",
    "StoredObject",
    "UnsafeArtifactRootError",
    "UnsafeObjectPathError",
    "build_artifact_manifest",
    "capture_raw_payload",
    "publish_artifact_manifest",
    "verify_artifact_binding",
    "verify_raw_capture",
)
