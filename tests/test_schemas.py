"""Conformance tests for the versioned JSON Schema foundation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

JsonObject = dict[str, Any]

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRECTORY = ROOT / "schemas" / "v1"
FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "schemas"


def load_object(path: Path) -> JsonObject:
    """Load a JSON object fixture with an explicit checked cast."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return cast(JsonObject, value)


def load_object_list(path: Path) -> list[JsonObject]:
    """Load a list of JSON object fixtures with structural checks."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError(f"Expected a list of JSON objects in {path}")
    return cast(list[JsonObject], value)


SCHEMAS = {
    path.name: load_object(path)
    for path in sorted(SCHEMA_DIRECTORY.glob("*.schema.json"))
}
VALID_OBJECTS = load_object(FIXTURE_DIRECTORY / "valid_objects.json")
INVALID_OBJECTS = load_object_list(FIXTURE_DIRECTORY / "invalid_objects.json")
SCHEMA_REGISTRY = Registry().with_resources(
    [
        (
            cast(str, schema["$id"]),
            Resource.from_contents(schema),
        )
        for schema in SCHEMAS.values()
    ]
)
FORMAT_CHECKER = FormatChecker()


def validator_for(schema_name: str) -> Draft202012Validator:
    """Construct a validator using only the local, versioned schema registry."""
    return Draft202012Validator(
        SCHEMAS[schema_name],
        registry=SCHEMA_REGISTRY,
        format_checker=FORMAT_CHECKER,
    )


def schema_nodes(value: object) -> Iterator[JsonObject]:
    """Yield every object node in a schema for structural policy checks."""
    if isinstance(value, dict):
        node = cast(JsonObject, value)
        yield node
        for child in node.values():
            yield from schema_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from schema_nodes(child)


def test_schema_catalog_is_complete_and_meta_valid() -> None:
    """Every requested v1 object has a valid and unique Draft 2020-12 schema."""
    expected_instance_schemas = {
        "artifact-manifest.schema.json",
        "configuration.schema.json",
        "dataset.schema.json",
        "dataset-lineage-manifest.schema.json",
        "environment-manifest.schema.json",
        "experiment.schema.json",
        "pattern.schema.json",
        "pit-selection-config.schema.json",
        "raw-capture.schema.json",
        "research-backlog.schema.json",
        "research-object.schema.json",
        "sealed-release-event.schema.json",
        "source.schema.json",
    }
    assert set(SCHEMAS) == expected_instance_schemas | {"common.schema.json"}
    assert set(VALID_OBJECTS) == expected_instance_schemas

    schema_ids = []
    for schema in SCHEMAS.values():
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert "/schemas/v1/" in schema["$id"]
        schema_ids.append(schema["$id"])
    assert len(schema_ids) == len(set(schema_ids))

    for schema_name in expected_instance_schemas:
        properties = cast(JsonObject, SCHEMAS[schema_name]["properties"])
        assert properties["schema_version"] == {"const": "1.0.0"}


def test_schemas_do_not_declare_unconstrained_number_fields() -> None:
    """Precision-sensitive values use strings; counts declare integer types."""
    for schema in SCHEMAS.values():
        assert all(node.get("type") != "number" for node in schema_nodes(schema))


@pytest.mark.parametrize(
    ("schema_name", "instance"),
    [(name, instance) for name, instance in VALID_OBJECTS.items()],
    ids=list(VALID_OBJECTS),
)
def test_valid_objects_pass(schema_name: str, instance: JsonObject) -> None:
    """Each compact synthetic object conforms to its declared schema."""
    validator_for(schema_name).validate(instance)


@pytest.mark.parametrize(
    "case",
    INVALID_OBJECTS,
    ids=[cast(str, case["case"]) for case in INVALID_OBJECTS],
)
def test_invalid_objects_fail_for_expected_reason(case: JsonObject) -> None:
    """Mandatory fields, closed shapes, IDs, timestamps, and versions fail."""
    schema_name = cast(str, case["schema"])
    instance = cast(JsonObject, case["instance"])
    expected_validator = cast(str, case["expected_validator"])

    errors = list(validator_for(schema_name).iter_errors(instance))

    assert errors, f"{case['case']} unexpectedly passed"
    assert expected_validator in {error.validator for error in errors}


def test_non_finite_numeric_value_is_rejected() -> None:
    """NaN cannot satisfy an integer field even when supplied in memory."""
    artifact = deepcopy(
        cast(JsonObject, VALID_OBJECTS["artifact-manifest.schema.json"])
    )
    artifact["byte_size"] = float("nan")

    errors = list(validator_for("artifact-manifest.schema.json").iter_errors(artifact))

    assert errors
    assert "type" in {error.validator for error in errors}


BATCH2_FIX_CASES = load_object_list(FIXTURE_DIRECTORY / "batch2_fix_cases.json")


@pytest.mark.parametrize("case", BATCH2_FIX_CASES, ids=lambda case: case["case"])
def test_batch2_required_metadata(case: JsonObject) -> None:
    """Each isolated mutation fails for its declared constraint."""
    instance = deepcopy(VALID_OBJECTS[case["schema"]])
    path = cast(list[str], case["remove"] if "remove" in case else case["set"])
    target = instance
    for key in path[:-1]:
        target = target[key]
    if "remove" in case:
        del target[path[-1]]
    else:
        target[path[-1]] = case["value"]
    errors = list(validator_for(case["schema"]).iter_errors(instance))
    assert case["validator"] in {error.validator for error in errors}


@pytest.mark.parametrize("status", ["FROZEN", "RUNNING", "EVALUATED", "DECIDED"])
def test_completed_experiment_metadata(status: str) -> None:
    """Frozen definitions and later results have concrete, reproducible references."""
    instance = deepcopy(VALID_OBJECTS["experiment.schema.json"])
    instance["lifecycle_status"] = status
    instance["frozen_manifest_digest"] = "sha256:" + "a" * 64
    for field in [
        "feature_definitions",
        "label_definitions",
        "candidate_universe",
        "parameters_considered",
    ]:
        instance[field] = "Fixed synthetic conformance definition."
    instance["baselines"] = ["Synthetic identity baseline"]
    if status in {"EVALUATED", "DECIDED"}:
        instance["sealed_data_release"] = {
            "status": "RELEASED",
            "event_digest": "sha256:" + "b" * 64,
        }
        instance["results"] = "Synthetic conformance result only."
        instance["result_artifact_digests"] = ["sha256:" + "c" * 64]
        instance["result_artifact_locations"] = ["https://example.invalid/result.json"]
        instance["variants_attempted"] = 3
        instance["variant_accounting"]["failed_attempts"] = 1
        instance["variant_accounting"]["ai_generated_attempts"] = 2
    if status == "DECIDED":
        del instance["decision_pending_reason"]
        instance["decision"] = "INCONCLUSIVE"
        instance["reason_for_decision"] = (
            "Synthetic fixture supplies no market evidence."
        )
    validator_for("experiment.schema.json").validate(instance)


@pytest.mark.parametrize(
    ("kind", "prefix"),
    [("RESEARCH_FAMILY", "FAM"), ("MODEL", "MOD"), ("STRATEGY", "STRAT")],
)
def test_research_types_with_implementation(kind: str, prefix: str) -> None:
    """All three types retain identity constraints with implementation evidence."""
    instance = deepcopy(VALID_OBJECTS["research-object.schema.json"])
    instance["object_type"] = kind
    instance["object_id"] = prefix + "-01990f30-7f5e-7b34-9b21-3d74c513c844"
    instance["implementation"] = {
        "exists": True,
        "location": "https://example.invalid/synthetic.py",
        "code_revision": "a" * 40,
    }
    instance["reproduction_outcome"] = "PARTIALLY REPRODUCED"
    validator_for("research-object.schema.json").validate(instance)
