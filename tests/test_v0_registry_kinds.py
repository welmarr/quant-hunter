"""All canonical kinds may be generic references without widening typed fields."""

from copy import deepcopy
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator, ValidationError

from quant_hunter.config import JsonRecord, parse_json_document
from quant_hunter.config.schema import RecordSchemaError, VersionedSchemaCatalog
from quant_hunter.identity import RegistryKind, new_typed_id

ROOT = Path(__file__).parents[1]
SCHEMAS = ROOT / "schemas" / "v1"
FIXTURES = cast(
    JsonRecord,
    parse_json_document(
        (ROOT / "tests" / "fixtures" / "schemas" / "valid_objects.json").read_bytes()
    ),
)
COMMON = cast(
    JsonRecord, parse_json_document((SCHEMAS / "common.schema.json").read_bytes())
)
CANONICAL_UUID = UUID("019947a8-7920-7000-8000-000000000001")


def definition(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": COMMON["$defs"]})


@pytest.fixture(scope="module")
def catalog() -> VersionedSchemaCatalog:
    return VersionedSchemaCatalog(SCHEMAS)


@pytest.mark.parametrize("kind", list(RegistryKind), ids=lambda kind: kind.name)
def test_every_registry_kind_is_a_generic_object_identity(kind: RegistryKind) -> None:
    # Derive from the runtime enum: future additions cannot silently be omitted.
    identity = new_typed_id(kind, uuid_factory=lambda: CANONICAL_UUID)
    definition("any_object_id").validate(identity)


@pytest.mark.parametrize(
    "schema,field",
    [
        ("experiment.schema.json", "referenced_object_ids"),
        ("research-backlog.schema.json", "related_object_ids"),
    ],
)
def test_valid_paper_links_are_canonical_generic_references(
    catalog: VersionedSchemaCatalog, schema: str, field: str
) -> None:
    paper = cast(JsonRecord, FIXTURES["publication.schema.json"])
    catalog.validate("publication.schema.json", paper)
    value = deepcopy(cast(JsonRecord, FIXTURES[schema]))
    value[field] = [paper["paper_id"]]
    catalog.validate(schema, value)


@pytest.mark.parametrize(
    "identity",
    [
        "PAPER-019947a8-7920-4000-8000-000000000001",
        "PAPER-019947a8-7920-7000-0000-000000000001",
        "PAPER-019947A8-7920-7000-8000-000000000001",
        "PAPERS-019947a8-7920-7000-8000-000000000001",
        "PAPER-019947a8-7920-7000-8000-000000000001-extra",
        "PAPER-short",
    ],
)
@pytest.mark.parametrize(
    "schema,field",
    [
        ("publication.schema.json", "paper_id"),
        ("experiment.schema.json", "referenced_object_ids"),
        ("research-backlog.schema.json", "related_object_ids"),
    ],
)
def test_malformed_paper_identity_rejected_in_every_consumer(
    catalog: VersionedSchemaCatalog, schema: str, field: str, identity: str
) -> None:
    value = deepcopy(cast(JsonRecord, FIXTURES[schema]))
    value[field] = identity if field == "paper_id" else [identity]
    with pytest.raises(RecordSchemaError):
        catalog.validate(schema, value)


@pytest.mark.parametrize("prefix", ["PAPER", "INSTRUMENT"])
def test_document_and_instrument_are_not_research_object_kinds(prefix: str) -> None:
    with pytest.raises(ValidationError):
        definition("research_object_id").validate(f"{prefix}-{CANONICAL_UUID}")


@pytest.mark.parametrize("prefix", ["FAM", "MOD", "STRAT"])
def test_original_research_object_kinds_still_validate(prefix: str) -> None:
    definition("research_object_id").validate(f"{prefix}-{CANONICAL_UUID}")


def test_generic_lineage_reference_semantics_are_unchanged(
    catalog: VersionedSchemaCatalog,
) -> None:
    paper = cast(JsonRecord, FIXTURES["publication.schema.json"])["paper_id"]
    artifact = deepcopy(cast(JsonRecord, FIXTURES["artifact-manifest.schema.json"]))
    provenance = cast(JsonRecord, artifact["provenance"])
    provenance["references"] = [paper]
    catalog.validate("artifact-manifest.schema.json", artifact)
    lineage = deepcopy(
        cast(JsonRecord, FIXTURES["dataset-lineage-manifest.schema.json"])
    )
    lineage["references"] = [paper]
    catalog.validate("dataset-lineage-manifest.schema.json", lineage)
    provenance["source_ids"] = [paper]
    with pytest.raises(RecordSchemaError):
        catalog.validate("artifact-manifest.schema.json", artifact)
