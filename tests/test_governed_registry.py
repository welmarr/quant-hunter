"""Governed schema validation and JCS integration for registry writes."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.config.schema import (
    MissingGovernedSchemaError,
    RecordSchemaError,
    SchemaCatalogError,
)
from quant_hunter.identity import RegistryKind, RegistryStore
from quant_hunter.provenance import sha256_bytes

REPOSITORY_ROOT = Path(__file__).parents[1]
SCHEMA_DIRECTORY = REPOSITORY_ROOT / "schemas" / "v1"
VALID_FIXTURES = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "schemas" / "valid_objects.json"
)


def source_payload() -> JsonRecord:
    """Load the existing synthetic source fixture without registry-owned fields."""
    fixtures = cast(dict[str, JsonRecord], json.loads(VALID_FIXTURES.read_text()))
    payload = deepcopy(fixtures["source.schema.json"])
    del payload["source_id"]
    del payload["revision"]
    del payload["previous_revision_digest"]
    return payload


def test_governed_registry_writes_canonical_schema_valid_revisions(
    tmp_path: Path,
) -> None:
    """The authoritative factory applies v1 schemas and writes exact JCS bytes."""
    store = RegistryStore.governed(tmp_path, SCHEMA_DIRECTORY)
    first = store.allocate(RegistryKind.SOURCE, source_payload()).revision
    second_payload = source_payload()
    second_payload["status"] = "REJECTED"
    second = store.append(
        cast(str, first.record["source_id"]), first.digest, second_payload
    )

    assert first.path.read_bytes() == canonicalize_json(first.record)
    assert second.path.read_bytes() == canonicalize_json(second.record)
    assert second.record["previous_revision_digest"] == first.digest
    assert len(store.verify_object(cast(str, first.record["source_id"]))) == 2


def test_schema_invalid_governed_write_is_rejected_before_file_creation(
    tmp_path: Path,
) -> None:
    """A real governed write cannot bypass its existing authoritative schema."""
    store = RegistryStore.governed(tmp_path, SCHEMA_DIRECTORY)
    invalid = source_payload()
    del invalid["provider"]

    with pytest.raises(RecordSchemaError, match="provider"):
        store.allocate(RegistryKind.SOURCE, invalid)

    assert not list(tmp_path.rglob("v000001.json"))


def test_schema_invalid_append_preserves_verified_history(tmp_path: Path) -> None:
    """Rejected schema-invalid updates leave the prior revision as the head."""
    store = RegistryStore.governed(tmp_path, SCHEMA_DIRECTORY)
    first = store.allocate(RegistryKind.SOURCE, source_payload()).revision
    invalid = source_payload()
    invalid["unknown_field"] = "must fail closed"

    with pytest.raises(RecordSchemaError, match="unknown_field"):
        store.append(cast(str, first.record["source_id"]), first.digest, invalid)

    assert len(store.verify_object(cast(str, first.record["source_id"]))) == 1
    assert not first.path.with_name("v000002.json").exists()


def test_kind_without_authoritative_schema_fails_closed(tmp_path: Path) -> None:
    """COST writes remain unavailable until an authoritative schema exists."""
    store = RegistryStore.governed(tmp_path, SCHEMA_DIRECTORY)

    with pytest.raises(MissingGovernedSchemaError, match="COST"):
        store.allocate(RegistryKind.COST, {"schema_version": "1.0.0"})

    assert not list(tmp_path.rglob("v000001.json"))


def test_existing_noncanonical_revision_is_verified_without_rewrite(
    tmp_path: Path,
) -> None:
    """New appends use JCS while exact legacy bytes remain immutable chain input."""
    store = RegistryStore.governed(tmp_path, SCHEMA_DIRECTORY)
    first = store.allocate(RegistryKind.SOURCE, source_payload()).revision
    legacy_bytes = json.dumps(first.record, indent=2).encode("utf-8") + b"\n"
    first.path.write_bytes(legacy_bytes)
    legacy_digest = sha256_bytes(legacy_bytes)

    second_payload = source_payload()
    second_payload["status"] = "DEPRECATED"
    second = store.append(
        cast(str, first.record["source_id"]), legacy_digest, second_payload
    )

    assert first.path.read_bytes() == legacy_bytes
    assert second.record["previous_revision_digest"] == legacy_digest
    assert second.path.read_bytes() == canonicalize_json(second.record)


def test_missing_schema_catalog_fails_during_governed_store_creation(
    tmp_path: Path,
) -> None:
    """An incomplete schema catalog cannot create an authoritative store."""
    with pytest.raises(SchemaCatalogError, match="missing"):
        RegistryStore.governed(tmp_path / "registry", tmp_path / "schemas")


@pytest.mark.parametrize(
    "content",
    [b"{", b"[]", b'{"$id":"first","$id":"duplicate"}'],
)
def test_malformed_or_duplicate_schema_catalog_fails_closed(
    tmp_path: Path, content: bytes
) -> None:
    """Governed schema ingestion uses the same strict JSON parser."""
    schema_directory = tmp_path / "schemas"
    schema_directory.mkdir()
    (schema_directory / "common.schema.json").write_bytes(content)

    with pytest.raises(SchemaCatalogError):
        RegistryStore.governed(tmp_path / "registry", schema_directory)
