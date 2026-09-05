"""Mandatory validation of governed registry records against versioned schemas."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from quant_hunter.config.canonical import (
    CanonicalJsonError,
    JsonValue,
    parse_json_document,
)
from quant_hunter.identity.ids import RegistryKind

SCHEMA_BY_KIND = {
    RegistryKind.FAMILY: "research-object.schema.json",
    RegistryKind.MODEL: "research-object.schema.json",
    RegistryKind.STRATEGY: "research-object.schema.json",
    RegistryKind.PATTERN: "pattern.schema.json",
    RegistryKind.EXPERIMENT: "experiment.schema.json",
    RegistryKind.SOURCE: "source.schema.json",
    RegistryKind.DATASET: "dataset.schema.json",
    RegistryKind.BACKLOG: "research-backlog.schema.json",
}


class SchemaCatalogError(RuntimeError):
    """The governed versioned schema catalog is absent or invalid."""


class MissingGovernedSchemaError(SchemaCatalogError):
    """A persistent kind has no authoritative schema and must fail closed."""


class RecordSchemaError(ValueError):
    """A governed registry record does not conform to its authoritative schema."""


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        value = parse_json_document(path.read_bytes())
    except (OSError, CanonicalJsonError) as error:
        raise SchemaCatalogError(f"Cannot load governed schema: {path}") from error
    if not isinstance(value, dict):
        raise SchemaCatalogError(f"Governed schema is not a JSON object: {path}")
    return cast(dict[str, Any], value)


class GovernedSchemaValidator:
    """Resolve and apply the existing Draft 2020-12 schema catalog offline."""

    def __init__(self, schema_directory: Path) -> None:
        required_names = set(SCHEMA_BY_KIND.values()) | {"common.schema.json"}
        schemas: dict[str, dict[str, Any]] = {}
        for name in sorted(required_names):
            path = schema_directory / name
            if not path.is_file():
                raise SchemaCatalogError(f"Required governed schema is missing: {path}")
            schema = _load_schema(path)
            Draft202012Validator.check_schema(schema)
            schemas[name] = schema
        registry = Registry().with_resources(
            [
                (
                    cast(str, schema["$id"]),
                    Resource.from_contents(schema),
                )
                for schema in schemas.values()
            ]
        )
        self._validators = {
            name: Draft202012Validator(
                schemas[name],
                registry=registry,
                format_checker=FormatChecker(),
            )
            for name in set(SCHEMA_BY_KIND.values())
        }

    def __call__(self, kind: RegistryKind, record: Mapping[str, JsonValue]) -> None:
        """Validate a governed record or fail closed for an unmapped kind."""
        schema_name = SCHEMA_BY_KIND.get(kind)
        if schema_name is None:
            raise MissingGovernedSchemaError(
                f"No authoritative registry schema exists for {kind.name}"
            )
        try:
            self._validators[schema_name].validate(dict(record))
        except ValidationError as error:
            raise RecordSchemaError(
                f"{kind.name} record failed {schema_name} at "
                f"{error.json_path}: {error.message}"
            ) from error
