"""RFC 8785 canonicalization and separate SHA-256 contract tests."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, cast

import pytest
import rfc8785

from quant_hunter.config import (
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
from quant_hunter.provenance import (
    DigestMismatchError,
    InvalidDigestError,
    sha256_bytes,
    sha256_canonical_json,
    verify_canonical_json_digest,
    verify_sha256_bytes,
)

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "jcs"


def test_rfc8785_primary_serialization_vector() -> None:
    """RFC 8785 section 3.2.2 canonicalizes its full example exactly."""
    source = r"""{
      "numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],
      "string": "\u20ac$\u000F\u000aA'\u0042\u0022\u005c\\\"\/",
      "literals": [null, true, false]
    }"""
    expected = bytes.fromhex(
        "7b226c69746572616c73223a5b6e756c6c2c747275652c66616c73655d2c"
        "226e756d62657273223a5b3333333333333333332e333333333333332c3165"
        "2b33302c342e352c302e3030322c31652d32375d2c22737472696e67223a22"
        "e282ac245c75303030665c6e4127425c225c5c5c5c5c222f227d"
    )

    assert canonicalize_json_text(source) == expected


def test_rfc8785_utf16_property_order_vector() -> None:
    """RFC 8785 section 3.2.3 ordering follows UTF-16 code units."""
    value: JsonRecord = {
        "\u20ac": "Euro Sign",
        "\r": "Carriage Return",
        "\ufb33": "Hebrew Letter Dalet With Dagesh",
        "1": "One",
        "😀": "Emoji: Grinning Face",
        "\u0080": "Control",
        "ö": "Latin Small Letter O With Diaeresis",
    }

    ordered = json.loads(
        canonicalize_json(value),
        object_pairs_hook=lambda pairs: [key for key, _ in pairs],
    )

    assert ordered == ["\r", "1", "\u0080", "ö", "€", "😀", "דּ"]


def test_rfc8785_appendix_b_number_vectors() -> None:
    """Official finite binary64 vectors use ECMAScript-compatible formatting."""
    vectors = cast(
        list[list[str]],
        json.loads(
            (FIXTURE_DIRECTORY / "rfc8785_number_vectors.json").read_text(
                encoding="utf-8"
            )
        ),
    )

    for ieee_hex, expected in vectors:
        value = struct.unpack(">d", bytes.fromhex(ieee_hex))[0]
        assert canonicalize_json(value) == expected.encode("ascii")


def test_string_escaping_and_unicode_are_deterministic() -> None:
    """Control characters escape minimally while Unicode remains UTF-8."""
    value: JsonRecord = {"é": 'line\n\t\b\f\r"\\/', "€": "😀"}

    assert canonicalize_json(value) == (
        '{"é":"line\\n\\t\\b\\f\\r\\"\\\\/","€":"😀"}'.encode()
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_numbers_are_rejected(value: float) -> None:
    """NaN and both infinities are outside I-JSON and JCS."""
    with pytest.raises(UnsupportedJsonValueError, match="Non-finite"):
        canonicalize_json(value)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_number_tokens_are_rejected_at_ingestion(token: str) -> None:
    """Python's permissive non-finite JSON extensions cannot enter the pipeline."""
    with pytest.raises(UnsupportedJsonValueError, match="Non-finite"):
        parse_json_document(f'{{"value":{token}}}')


def test_duplicate_keys_are_rejected_at_every_object_depth() -> None:
    """Duplicate object properties fail before canonicalization can hide them."""
    with pytest.raises(DuplicateKeyError, match="Duplicate JSON object key"):
        canonicalize_json_text('{"outer":{"same":1,"same":2}}')


@pytest.mark.parametrize(
    "value",
    [
        {"token": "${UNRESOLVED}"},
        {"${KEY}": "value"},
    ],
)
def test_unresolved_environment_substitutions_are_rejected(
    value: dict[str, str],
) -> None:
    """Environment placeholders must be resolved before canonical identity."""
    with pytest.raises(UnresolvedSubstitutionError, match="Unresolved"):
        canonicalize_json(cast(JsonValue, value))


@pytest.mark.parametrize(
    "value",
    [
        ("tuple",),
        {1: "non-string key"},
        2**53,
        -(2**53),
        "\ud800",
    ],
)
def test_unsupported_non_ijson_values_are_rejected(value: object) -> None:
    """The in-memory API rejects types and values outside the project data model."""
    with pytest.raises(UnsupportedJsonValueError):
        canonicalize_json(cast(Any, value))


def test_invalid_json_and_utf8_are_reported_as_canonical_errors() -> None:
    """Malformed syntax and invalid UTF-8 cannot reach identity generation."""
    with pytest.raises(CanonicalJsonError, match="Invalid JSON"):
        canonicalize_json_text("{")
    with pytest.raises(CanonicalJsonError, match="valid UTF-8"):
        canonicalize_json_text(b"\xff")


def test_dependency_canonicalization_error_is_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dependency failures do not leak a second public exception contract."""

    def fail(_: object) -> bytes:
        raise rfc8785.CanonicalizationError("synthetic dependency failure")

    monkeypatch.setattr(rfc8785, "dumps", fail)
    with pytest.raises(CanonicalJsonError, match="canonicalization failed"):
        canonicalize_json({"valid": True})


def test_exact_byte_and_canonical_json_hashing_are_distinct() -> None:
    """Exact bytes retain formatting identity while equivalent JSON canonicalizes."""
    compact = b'{"a":1,"b":2}'
    spaced = b'{ "b": 2, "a": 1 }'
    first = cast(JsonRecord, parse_json_document(compact))
    second = cast(JsonRecord, parse_json_document(spaced))

    assert sha256_bytes(compact) != sha256_bytes(spaced)
    assert sha256_canonical_json(first) == sha256_canonical_json(second)
    assert sha256_bytes(b"") == (
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_canonical_digest_is_stable_and_content_sensitive() -> None:
    """Insertion order does not matter, while one changed value changes identity."""
    left: JsonRecord = {"z": [1, True], "a": "same"}
    reordered: JsonRecord = {"a": "same", "z": [1, True]}
    changed: JsonRecord = {"a": "same", "z": [1, False]}
    digest = sha256_canonical_json(left)

    assert digest == sha256_canonical_json(reordered)
    assert digest != sha256_canonical_json(changed)
    verify_canonical_json_digest(reordered, digest)


def test_hash_verification_rejects_mismatch_and_malformed_digest() -> None:
    """Verification never normalizes malformed or mismatched digest claims."""
    digest = sha256_bytes(b"expected")
    verify_sha256_bytes(b"expected", digest)

    with pytest.raises(DigestMismatchError, match="mismatch"):
        verify_sha256_bytes(b"changed", digest)
    with pytest.raises(InvalidDigestError, match="Invalid"):
        verify_sha256_bytes(b"expected", digest.upper())
    with pytest.raises(DigestMismatchError, match="Canonical SHA-256 mismatch"):
        verify_canonical_json_digest({"changed": True}, digest)
