"""Secret-shaped metadata rejection for persisted storage evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final
from urllib.parse import parse_qsl, urlsplit

from quant_hunter.config.canonical import JsonValue

SENSITIVE_KEY: Final = re.compile(
    r"(?:^|[_-])(?:authorization|cookie|password|passwd|secret|token|credential|"
    r"api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|bearer)"
    r"(?:$|[_-])",
    re.IGNORECASE,
)
_LABEL_PATTERN: Final = (
    r"(?:password|passwd|token|secret|credential|api[-_]?key|access[-_]?key|"
    r"private[-_]?key|client[-_]?secret)"
)
_VALUE_PATTERN: Final = r"""(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)"""
SENSITIVE_TEXT: Final = re.compile(
    r"(?:"
    r"(?P<switch_prefix>--(?:api[-_]?key|token|password)"
    r"(?=\s|=)(?:\s*=\s*|\s+))\S+"
    r"|(?P<authorization_prefix>authorization\s*(?::|=)\s*"
    r"(?:bearer\s+)?)\S+"
    r"|(?P<cookie_prefix>cookie\s*(?::|=)\s*)\S+"
    r"|(?P<bearer_prefix>(?<![A-Za-z0-9_-])bearer\s+)"
    r"[A-Za-z0-9][A-Za-z0-9._~+/=-]*"
    r"|(?P<label_prefix>(?<![A-Za-z0-9_-])"
    + _LABEL_PATTERN
    + r"(?![A-Za-z0-9_-])\s*(?:=|:)\s*)"
    + _VALUE_PATTERN
    + r")",
    re.IGNORECASE,
)


class SensitiveMetadataError(ValueError):
    """Persisted metadata contains a credential-shaped field or URI component."""


def reject_credential_shaped_fields(
    value: Mapping[str, JsonValue], path: str = "$"
) -> None:
    """Reject obvious credential-bearing field names recursively without logging values."""
    for key, item in value.items():
        if SENSITIVE_KEY.search(key) is not None:
            raise SensitiveMetadataError(
                f"Credential-shaped metadata field is forbidden at {path}"
            )
        if isinstance(item, dict):
            reject_credential_shaped_fields(item, f"{path}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                if isinstance(child, dict):
                    reject_credential_shaped_fields(child, f"{path}.{key}[{index}]")


def reject_credential_uri(uri: str) -> None:
    """Reject URI userinfo and credential-shaped query parameter names."""
    parsed = urlsplit(uri)
    if parsed.username is not None or parsed.password is not None:
        raise SensitiveMetadataError("Credential-bearing URI userinfo is forbidden")
    for name, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if SENSITIVE_KEY.search(name) is not None:
            raise SensitiveMetadataError(
                "Credential-shaped URI query parameter is forbidden"
            )


def reject_secret_text(value: str, context: str) -> None:
    """Reject explicit credential labels in free text without exposing the value."""
    if SENSITIVE_TEXT.search(value) is not None:
        raise SensitiveMetadataError(
            f"Labelled credential material is forbidden in {context}"
        )


def redact_secret_text(value: str) -> str:
    """Redact labelled credential values while retaining diagnostic context."""

    def replacement(match: re.Match[str]) -> str:
        for group_name in (
            "switch_prefix",
            "authorization_prefix",
            "cookie_prefix",
            "bearer_prefix",
            "label_prefix",
        ):
            prefix = match.group(group_name)
            if prefix is not None:
                return f"{prefix}[REDACTED]"
        return "[REDACTED]"

    return SENSITIVE_TEXT.sub(replacement, value)


def reject_secret_text_values(
    value: JsonValue | Mapping[str, JsonValue], context: str
) -> None:
    """Recursively inspect string values in persisted metadata containers."""
    if isinstance(value, str):
        reject_secret_text(value, context)
    elif isinstance(value, Mapping):
        for item in value.values():
            reject_secret_text_values(item, context)
    elif isinstance(value, list):
        for item in value:
            reject_secret_text_values(item, context)
