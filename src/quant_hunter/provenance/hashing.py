"""Separate exact-byte and canonical-JSON SHA-256 contracts."""

from __future__ import annotations

import hashlib
import re
from typing import Final

from quant_hunter.config.canonical import JsonValue, canonicalize_json

DIGEST_PATTERN: Final = re.compile(r"^sha256:[0-9a-f]{64}$")


class InvalidDigestError(ValueError):
    """A digest does not match the governed textual contract."""


class DigestMismatchError(ValueError):
    """Observed content does not match its declared SHA-256 digest."""


def require_sha256_digest(digest: str) -> None:
    """Require ``sha256:<64 lowercase hex>`` without normalizing it."""
    if DIGEST_PATTERN.fullmatch(digest) is None:
        raise InvalidDigestError(f"Invalid SHA-256 digest: {digest!r}")


def sha256_bytes(content: bytes) -> str:
    """Identify exact bytes without parsing or canonicalization."""
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def sha256_canonical_json(value: JsonValue) -> str:
    """Identify the RFC 8785 canonical representation of a JSON value."""
    return sha256_bytes(canonicalize_json(value))


def verify_sha256_bytes(content: bytes, expected_digest: str) -> None:
    """Verify exact bytes against a governed digest."""
    require_sha256_digest(expected_digest)
    actual_digest = sha256_bytes(content)
    if actual_digest != expected_digest:
        raise DigestMismatchError(
            f"SHA-256 mismatch: expected {expected_digest}, observed {actual_digest}"
        )


def verify_canonical_json_digest(value: JsonValue, expected_digest: str) -> None:
    """Verify a JSON value against its canonical-representation digest."""
    require_sha256_digest(expected_digest)
    actual_digest = sha256_canonical_json(value)
    if actual_digest != expected_digest:
        raise DigestMismatchError(
            f"Canonical SHA-256 mismatch: expected {expected_digest}, "
            f"observed {actual_digest}"
        )
