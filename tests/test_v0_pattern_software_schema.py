"""Synthetic Pattern identities cannot invent holdouts or validated authority."""

from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from quant_hunter.config import JsonRecord, JsonValue, parse_json_document
from quant_hunter.config.schema import RecordSchemaError, VersionedSchemaCatalog

ROOT = Path(__file__).parents[1]
FIXTURES = cast(
    JsonRecord,
    parse_json_document(
        (ROOT / "tests/fixtures/schemas/valid_objects.json").read_bytes()
    ),
)


@pytest.fixture(scope="module")
def catalog() -> VersionedSchemaCatalog:
    return VersionedSchemaCatalog(ROOT / "schemas/v1")


def software_pattern() -> JsonRecord:
    value = deepcopy(cast(JsonRecord, FIXTURES["pattern.schema.json"]))
    value.update(
        status="SOFTWARE_ONLY",
        evidence_mode="SYNTHETIC",
        empirical_validation="UNVALIDATED",
        validation_dataset_id=None,
        sealed_dataset_id=None,
        missing_validation_reason="Software fixture only; no scientific validation or sealed-data access.",
    )
    return value


def test_software_identity_requires_no_fabricated_holdout(
    catalog: VersionedSchemaCatalog,
) -> None:
    value = software_pattern()
    catalog.validate("pattern.schema.json", value)
    original = cast(JsonRecord, FIXTURES["pattern.schema.json"])
    assert value["discovery_dataset_id"] == original["discovery_dataset_id"]
    assert value["validation_dataset_id"] is value["sealed_dataset_id"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "VALIDATED"),
        ("status", "RESEARCH"),
        ("evidence_mode", "HISTORICAL"),
        ("empirical_validation", "VALIDATED"),
        ("missing_validation_reason", ""),
        ("missing_validation_reason", " \t\n"),
        ("missing_validation_reason", "x" * 2001),
        ("discovery_dataset_id", None),
        ("discovery_dataset_id", "DATASET-made-up"),
    ],
)
def test_software_profile_rejects_conflicting_authority(
    catalog: VersionedSchemaCatalog, field: str, value: JsonValue
) -> None:
    record = software_pattern()
    record[field] = value
    with pytest.raises(RecordSchemaError):
        catalog.validate("pattern.schema.json", record)


@pytest.mark.parametrize(
    "field", ["evidence_mode", "empirical_validation", "missing_validation_reason"]
)
def test_software_disclosures_cannot_be_omitted(
    catalog: VersionedSchemaCatalog, field: str
) -> None:
    value = software_pattern()
    del value[field]
    with pytest.raises(RecordSchemaError):
        catalog.validate("pattern.schema.json", value)


@pytest.mark.parametrize("field", ["validation_dataset_id", "sealed_dataset_id"])
def test_software_profile_cannot_claim_a_sealed_or_validated_dataset(
    catalog: VersionedSchemaCatalog, field: str
) -> None:
    value = software_pattern()
    value[field] = value["discovery_dataset_id"]
    with pytest.raises(RecordSchemaError):
        catalog.validate("pattern.schema.json", value)


@pytest.mark.parametrize(
    "status", ["PROPOSED", "RESEARCH", "VALIDATED", "REJECTED", "RETIRED", "SUPERSEDED"]
)
def test_legacy_profile_preserves_dataset_requirements(
    catalog: VersionedSchemaCatalog, status: str
) -> None:
    original = deepcopy(cast(JsonRecord, FIXTURES["pattern.schema.json"]))
    original["status"] = status
    catalog.validate("pattern.schema.json", original)
    for field in ("validation_dataset_id", "sealed_dataset_id"):
        value = deepcopy(original)
        value[field] = None
        with pytest.raises(RecordSchemaError):
            catalog.validate("pattern.schema.json", value)
    for field in ("evidence_mode", "empirical_validation", "missing_validation_reason"):
        value = deepcopy(original)
        value[field] = software_pattern()[field]
        with pytest.raises(RecordSchemaError):
            catalog.validate("pattern.schema.json", value)


def test_revision_chain_requirements_are_unchanged(
    catalog: VersionedSchemaCatalog,
) -> None:
    value = software_pattern()
    value["revision"] = 2
    value["previous_revision_digest"] = None
    with pytest.raises(RecordSchemaError):
        catalog.validate("pattern.schema.json", value)
    value["previous_revision_digest"] = "sha256:" + "a" * 64
    catalog.validate("pattern.schema.json", value)
