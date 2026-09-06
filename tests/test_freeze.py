"""Deterministic generic freeze-manifest foundation tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.provenance import (
    DataManifestReference,
    DigestMismatchError,
    FreezeManifest,
    build_freeze_manifest,
    sha256_bytes,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def manifest_inputs() -> dict[str, object]:
    """Return deterministic, synthetic DEC-0007 inputs."""
    return {
        "experiment_id": new_typed_id(RegistryKind.EXPERIMENT),
        "registered_revision_digest": "sha256:" + "1" * 64,
        "hypothesis_reference": "registry://synthetic/hypothesis/v000001",
        "configuration_digest": DIGEST_A,
        "code_revision": "d" * 40,
        "data_manifests": [
            DataManifestReference("registry://synthetic/data/manifest-1", DIGEST_B)
        ],
        "environment_digest": DIGEST_C,
        "seeds": [7, 19],
        "search_budget": {"maximum_variants": 4, "family": "synthetic"},
        "criteria": {"primary": "synthetic deterministic assertion"},
        "baselines": ["registry://synthetic/baseline/v000001"],
    }


def test_freeze_manifest_is_deterministic_and_self_verifying() -> None:
    """Equal semantic inputs produce identical canonical bytes and identity."""
    arguments = manifest_inputs()
    first = build_freeze_manifest(**arguments)  # type: ignore[arg-type]
    reordered = dict(arguments)
    reordered["search_budget"] = {
        "family": "synthetic",
        "maximum_variants": 4,
    }
    second = build_freeze_manifest(**reordered)  # type: ignore[arg-type]

    assert first == second
    assert first.digest == sha256_bytes(first.canonical_bytes)
    assert first.document["manifest_type"] == "EXPERIMENT_FREEZE"
    assert first.document is not first.document
    first.verify()


def test_freeze_manifest_change_changes_digest() -> None:
    """A one-value change in governed freeze inputs changes canonical identity."""
    arguments = manifest_inputs()
    original = build_freeze_manifest(**arguments)  # type: ignore[arg-type]
    arguments["seeds"] = [7, 20]
    changed = build_freeze_manifest(**arguments)  # type: ignore[arg-type]

    assert original.digest != changed.digest
    assert original.canonical_bytes != changed.canonical_bytes


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("registered_revision_digest", "sha256:" + "2" * 64),
        ("configuration_digest", "sha256:" + "2" * 64),
        ("code_revision", "e" * 40),
        (
            "data_manifests",
            [DataManifestReference("registry://synthetic/data/manifest-2", DIGEST_B)],
        ),
        ("environment_digest", "sha256:" + "2" * 64),
        ("search_budget", {"maximum_variants": 5, "family": "synthetic"}),
    ],
)
def test_each_material_freeze_binding_changes_identity(
    field: str, value: object
) -> None:
    """Every material registered or reproduction binding affects freeze identity."""
    arguments = manifest_inputs()
    original = build_freeze_manifest(**arguments)  # type: ignore[arg-type]
    arguments[field] = value

    changed = build_freeze_manifest(**arguments)  # type: ignore[arg-type]

    assert changed.digest != original.digest


def test_freeze_manifest_digest_mismatch_is_rejected() -> None:
    """Stored canonical bytes cannot be changed without detection."""
    manifest = build_freeze_manifest(**manifest_inputs())  # type: ignore[arg-type]
    damaged = replace(manifest, canonical_bytes=manifest.canonical_bytes + b" ")

    with pytest.raises(DigestMismatchError, match="mismatch"):
        damaged.verify()

    non_object = FreezeManifest(b"[]", sha256_bytes(b"[]"))
    with pytest.raises(ValueError, match="not a JSON object"):
        _ = non_object.document


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("hypothesis_reference", " ", "hypothesis_reference"),
        ("code_revision", "ABC", "code_revision"),
        ("data_manifests", [], "data_manifests"),
        ("search_budget", {}, "search_budget"),
        ("criteria", {}, "criteria"),
        ("baselines", [], "baselines"),
        ("seeds", [-1], "seeds"),
        ("seeds", [True], "seeds"),
    ],
)
def test_freeze_manifest_rejects_missing_or_invalid_bindings(
    field: str, value: object, message: str
) -> None:
    """Every DEC-0007 binding is present and structurally usable."""
    arguments = manifest_inputs()
    arguments[field] = value

    with pytest.raises(ValueError, match=message):
        build_freeze_manifest(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "data_manifest",
    [
        DataManifestReference("", DIGEST_B),
        DataManifestReference("registry://synthetic/data", "sha256:BAD"),
    ],
)
def test_freeze_manifest_rejects_invalid_data_references(
    data_manifest: DataManifestReference,
) -> None:
    """Each data manifest binds both a location and valid SHA-256 identity."""
    arguments = manifest_inputs()
    arguments["data_manifests"] = [data_manifest]

    with pytest.raises(ValueError):
        build_freeze_manifest(**arguments)  # type: ignore[arg-type]


def test_freeze_manifest_rejects_invalid_baseline_reference() -> None:
    """An empty baseline cannot masquerade as a frozen comparison."""
    arguments = manifest_inputs()
    arguments["baselines"] = [""]

    with pytest.raises(ValueError, match="baseline reference"):
        build_freeze_manifest(**arguments)  # type: ignore[arg-type]
