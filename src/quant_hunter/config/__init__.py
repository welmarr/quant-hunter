"""Validated configuration and canonical JSON contracts."""

from quant_hunter.config.canonical import (
    CanonicalJsonError,
    DuplicateKeyError,
    JsonRecord,
    JsonValue,
    UnresolvedSubstitutionError,
    UnsupportedJsonValueError,
    canonicalize_json,
    canonicalize_json_text,
    parse_json_document,
)

__all__ = (
    "CanonicalJsonError",
    "DuplicateKeyError",
    "JsonRecord",
    "JsonValue",
    "UnresolvedSubstitutionError",
    "UnsupportedJsonValueError",
    "canonicalize_json",
    "canonicalize_json_text",
    "parse_json_document",
)
