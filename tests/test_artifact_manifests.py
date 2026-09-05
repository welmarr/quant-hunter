"""Schema-governed artifact sidecar tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from quant_hunter.config.schema import RecordSchemaError, VersionedSchemaCatalog
from quant_hunter.identity import IdentityError
from quant_hunter.provenance import DigestMismatchError
from quant_hunter.storage import (
    ArtifactManifest,
    ArtifactProducer,
    ArtifactProvenance,
    ImmutableObjectStore,
    ObjectCorruptionError,
    SensitiveMetadataError,
    StoredObject,
    build_artifact_manifest,
    publish_artifact_manifest,
    verify_artifact_binding,
)

SCHEMA_DIRECTORY = Path(__file__).parents[1] / "schemas" / "v1"
SOURCE_ID = "SOURCE-01990f30-7f5e-7b34-9b21-3d74c513c841"
DATASET_ID = "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c842"
ENVIRONMENT_DIGEST = "sha256:" + "b" * 64
CONFIGURATION_DIGEST = "sha256:" + "c" * 64


def build_manifest(
    tmp_path: Path,
) -> tuple[
    ImmutableObjectStore,
    VersionedSchemaCatalog,
    StoredObject,
    ArtifactManifest,
]:
    store = ImmutableObjectStore(tmp_path / "artifacts")
    catalog = VersionedSchemaCatalog(SCHEMA_DIRECTORY)
    stored = store.publish(b"synthetic report bytes")
    manifest = build_artifact_manifest(
        store=store,
        catalog=catalog,
        stored_object=stored,
        artifact_type="report",
        media_type="application/json",
        created_at="2026-09-05T12:00:00Z",
        producer=ArtifactProducer("a" * 40, "synthetic-command", ENVIRONMENT_DIGEST),
        provenance=ArtifactProvenance(
            source_ids=(SOURCE_ID,),
            dataset_ids=(DATASET_ID,),
            references=("synthetic://provenance/reference",),
            configuration_digest=CONFIGURATION_DIGEST,
        ),
        parent_digests=("sha256:" + "d" * 64,),
    )
    return store, catalog, stored, manifest


def test_manifest_is_canonical_stable_and_publishable(tmp_path: Path) -> None:
    """Equal governed metadata produces equal JCS bytes and sidecar identity."""
    store, catalog, stored, first = build_manifest(tmp_path)
    second = build_artifact_manifest(
        store=store,
        catalog=catalog,
        stored_object=stored,
        artifact_type="report",
        media_type="application/json",
        created_at="2026-09-05T12:00:00Z",
        producer=ArtifactProducer("a" * 40, "synthetic-command", ENVIRONMENT_DIGEST),
        provenance=ArtifactProvenance(
            source_ids=(SOURCE_ID,),
            dataset_ids=(DATASET_ID,),
            references=("synthetic://provenance/reference",),
            configuration_digest=CONFIGURATION_DIGEST,
        ),
        parent_digests=("sha256:" + "d" * 64,),
    )

    assert first == second
    assert first.document["artifact_digest"] == stored.digest
    assert first.document["byte_size"] == stored.byte_size
    verify_artifact_binding(first, stored)
    sidecar = publish_artifact_manifest(store, first)
    assert sidecar.digest == first.digest
    assert store.read_bytes(sidecar.digest) == first.canonical_bytes


def test_manifest_digest_and_object_mismatches_fail(tmp_path: Path) -> None:
    """Sidecars cannot bind a different digest or byte size."""
    _store, _catalog, stored, manifest = build_manifest(tmp_path)
    damaged = replace(manifest, canonical_bytes=manifest.canonical_bytes + b" ")
    with pytest.raises(DigestMismatchError):
        damaged.verify()

    wrong_digest = replace(stored, digest="sha256:" + "e" * 64)
    with pytest.raises(ObjectCorruptionError, match="digest"):
        verify_artifact_binding(manifest, wrong_digest)
    wrong_size = replace(stored, byte_size=stored.byte_size + 1)
    with pytest.raises(ObjectCorruptionError, match="size"):
        verify_artifact_binding(manifest, wrong_size)


def test_manifest_reuses_schema_and_typed_provenance(tmp_path: Path) -> None:
    """Invalid media metadata and wrong typed references fail before publication."""
    store = ImmutableObjectStore(tmp_path / "artifacts")
    catalog = VersionedSchemaCatalog(SCHEMA_DIRECTORY)
    stored = store.publish(b"artifact")
    producer = ArtifactProducer("a" * 40, "synthetic", ENVIRONMENT_DIGEST)

    with pytest.raises(RecordSchemaError, match="media_type"):
        build_artifact_manifest(
            store=store,
            catalog=catalog,
            stored_object=stored,
            artifact_type="report",
            media_type="INVALID MEDIA",
            created_at="2026-09-05T12:00:00Z",
            producer=producer,
            provenance=ArtifactProvenance(),
        )
    with pytest.raises(IdentityError):
        build_artifact_manifest(
            store=store,
            catalog=catalog,
            stored_object=stored,
            artifact_type="report",
            media_type="application/json",
            created_at="2026-09-05T12:00:00Z",
            producer=producer,
            provenance=ArtifactProvenance(source_ids=(DATASET_ID,)),
        )

    with pytest.raises(SensitiveMetadataError):
        build_artifact_manifest(
            store=store,
            catalog=catalog,
            stored_object=stored,
            artifact_type="report",
            media_type="application/json",
            created_at="2026-09-05T12:00:00Z",
            producer=producer,
            provenance=ArtifactProvenance(
                references=("https://example.invalid/report?token=forbidden",)
            ),
        )


def test_manifest_defensive_nonobject_and_publish_mismatch_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed sidecars and unexpected publication identities fail closed."""
    store, _catalog, stored, manifest = build_manifest(tmp_path)
    nonobject = replace(manifest, canonical_bytes=b"[]")
    with pytest.raises(ObjectCorruptionError, match="not a JSON object"):
        _ = nonobject.document

    monkeypatch.setattr(
        store,
        "publish",
        lambda _content: replace(stored, digest="sha256:" + "f" * 64),
    )
    with pytest.raises(ObjectCorruptionError, match="changed unexpectedly"):
        publish_artifact_manifest(store, manifest)
