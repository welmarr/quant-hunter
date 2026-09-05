"""Offline validation against the authoritative versioned schema catalog."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker, SchemaError, ValidationError
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


class VersionedSchemaCatalog:
    """Load and validate the complete local Draft 2020-12 schema catalog."""

    def __init__(self, schema_directory: Path) -> None:
        paths = sorted(schema_directory.glob("*.schema.json"))
        if not paths:
            raise SchemaCatalogError(
                f"Required governed schemas are missing: {schema_directory}"
            )
        schemas: dict[str, dict[str, Any]] = {}
        schema_ids: set[str] = set()
        for path in paths:
            schema = _load_schema(path)
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise SchemaCatalogError(f"Invalid governed schema: {path}") from error
            schema_id = schema.get("$id")
            if not isinstance(schema_id, str) or schema_id in schema_ids:
                raise SchemaCatalogError(
                    f"Governed schema has a missing or duplicate $id: {path}"
                )
            schema_ids.add(schema_id)
            schemas[path.name] = schema
        if "common.schema.json" not in schemas:
            raise SchemaCatalogError(
                f"Required governed schema is missing: {schema_directory / 'common.schema.json'}"
            )
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
                schema,
                registry=registry,
                format_checker=FormatChecker(),
            )
            for name, schema in schemas.items()
            if name != "common.schema.json"
        }

    def validate(self, schema_name: str, document: Mapping[str, JsonValue]) -> None:
        """Validate one document or fail closed for an unknown schema name."""
        validator = self._validators.get(schema_name)
        if validator is None:
            raise MissingGovernedSchemaError(
                f"No authoritative schema named {schema_name!r}"
            )
        try:
            validator.validate(dict(document))
        except ValidationError as error:
            raise RecordSchemaError(
                f"Document failed {schema_name} at {error.json_path}: {error.message}"
            ) from error


class GovernedSchemaValidator:
    """Resolve and apply the existing Draft 2020-12 schema catalog offline."""

    def __init__(self, schema_directory: Path) -> None:
        self._catalog = VersionedSchemaCatalog(schema_directory)

    def __call__(self, kind: RegistryKind, record: Mapping[str, JsonValue]) -> None:
        """Validate a governed record or fail closed for an unmapped kind."""
        schema_name = SCHEMA_BY_KIND.get(kind)
        if schema_name is None:
            raise MissingGovernedSchemaError(
                f"No authoritative registry schema exists for {kind.name}"
            )
        self._catalog.validate(schema_name, record)
