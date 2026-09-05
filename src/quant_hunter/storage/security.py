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
