"""RFC 8785 canonical JSON with strict I-JSON ingestion controls."""

from __future__ import annotations

import json
import re
from math import isfinite
from typing import Any, Final, cast

import rfc8785

type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)
type JsonRecord = dict[str, JsonValue]

MAX_SAFE_INTEGER: Final = (2**53) - 1
ENVIRONMENT_SUBSTITUTION: Final = re.compile(r"[$][{][^{}]+[}]")


class CanonicalJsonError(ValueError):
    """Input cannot be represented as governed RFC 8785 canonical JSON."""


class DuplicateKeyError(CanonicalJsonError):
    """A parsed JSON object contains the same property name more than once."""


class UnresolvedSubstitutionError(CanonicalJsonError):
    """A JSON string still contains an unresolved ``${...}`` token."""


class UnsupportedJsonValueError(CanonicalJsonError):
    """A value is outside the strict I-JSON data model used by the project."""


def _reject_constant(token: str) -> None:
    raise UnsupportedJsonValueError(f"Non-finite JSON number is forbidden: {token}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(f"Duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _validate_string(value: str) -> None:
    if ENVIRONMENT_SUBSTITUTION.search(value) is not None:
        raise UnresolvedSubstitutionError(
            f"Unresolved environment substitution in JSON string: {value!r}"
        )
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise UnsupportedJsonValueError(
            "JSON strings must contain valid Unicode"
        ) from error


def _validate_json_value(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        _validate_string(value)
        return
    if isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise UnsupportedJsonValueError(
                f"Integer outside the interoperable I-JSON range at {path}: {value}"
            )
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise UnsupportedJsonValueError(f"Non-finite number at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise UnsupportedJsonValueError(
                    f"JSON object key is not a string at {path}: {key!r}"
                )
            _validate_string(key)
            _validate_json_value(item, f"{path}.{key}")
        return
    raise UnsupportedJsonValueError(
        f"Unsupported JSON value at {path}: {type(value).__name__}"
    )


def parse_json_document(source: str | bytes) -> JsonValue:
    """Parse one JSON document while rejecting duplicates and non-I-JSON input."""
    try:
        value = json.loads(
            source,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError as error:
        raise CanonicalJsonError("JSON bytes must be valid UTF-8") from error
    except json.JSONDecodeError as error:
        raise CanonicalJsonError("Invalid JSON document") from error
    _validate_json_value(value)
    return cast(JsonValue, value)


def canonicalize_json(value: JsonValue) -> bytes:
    """Return deterministic RFC 8785 JCS UTF-8 bytes for a strict JSON value."""
    _validate_json_value(value)
    try:
        return rfc8785.dumps(value)
    except rfc8785.CanonicalizationError as error:
        raise CanonicalJsonError("RFC 8785 canonicalization failed") from error


def canonicalize_json_text(source: str | bytes) -> bytes:
    """Strictly parse and canonicalize a JSON document."""
    return canonicalize_json(parse_json_document(source))
