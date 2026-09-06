"""Generic deterministic experiment freeze-manifest construction."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Final

from quant_hunter.config.canonical import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.identity.ids import RegistryKind, validate_typed_id
from quant_hunter.provenance.hashing import (
    require_sha256_digest,
    sha256_bytes,
    verify_sha256_bytes,
)

GIT_REVISION_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class DataManifestReference:
    """A stable data-manifest location paired with its verified digest identity."""

    reference: str
    digest: str


@dataclass(frozen=True, slots=True)
class FreezeManifest:
    """Immutable canonical bytes and digest for a generic freeze definition."""

    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        """Return a fresh parsed copy so callers cannot mutate the frozen bytes."""
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise ValueError("Freeze manifest canonical bytes are not a JSON object")
        return value

    def verify(self) -> None:
        """Fail if the canonical bytes no longer match the recorded digest."""
        verify_sha256_bytes(self.canonical_bytes, self.digest)


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def build_freeze_manifest(
    *,
    experiment_id: str,
    registered_revision_digest: str,
    hypothesis_reference: str,
    configuration_digest: str,
    code_revision: str,
    data_manifests: Sequence[DataManifestReference],
    environment_digest: str,
    seeds: Sequence[int],
    search_budget: Mapping[str, JsonValue],
    criteria: Mapping[str, JsonValue],
    baselines: Sequence[str],
) -> FreezeManifest:
    """Build the deterministic fields required by DEC-0007, without lifecycle I/O."""
    validate_typed_id(experiment_id, RegistryKind.EXPERIMENT)
    require_sha256_digest(registered_revision_digest)
    _require_nonempty(hypothesis_reference, "hypothesis_reference")
    require_sha256_digest(configuration_digest)
    require_sha256_digest(environment_digest)
    if GIT_REVISION_PATTERN.fullmatch(code_revision) is None:
        raise ValueError("code_revision must be 40 lowercase hexadecimal characters")
    if not data_manifests:
        raise ValueError("data_manifests must contain at least one reference")
    if not search_budget:
        raise ValueError("search_budget must not be empty")
    if not criteria:
        raise ValueError("criteria must not be empty")
    if not baselines:
        raise ValueError("baselines must contain at least one reference")

    data_references: list[JsonValue] = []
    for item in data_manifests:
        _require_nonempty(item.reference, "data manifest reference")
        require_sha256_digest(item.digest)
        data_references.append({"digest": item.digest, "reference": item.reference})
    seed_values: list[JsonValue] = []
    for seed in seeds:
        if isinstance(seed, bool) or seed < 0:
            raise ValueError("seeds must be nonnegative integers")
        seed_values.append(seed)
    baseline_values: list[JsonValue] = []
    for baseline in baselines:
        _require_nonempty(baseline, "baseline reference")
        baseline_values.append(baseline)

    document: JsonRecord = {
        "schema_version": "1.0.0",
        "manifest_type": "EXPERIMENT_FREEZE",
        "experiment_id": experiment_id,
        "registered_revision_digest": registered_revision_digest,
        "hypothesis_reference": hypothesis_reference,
        "configuration_digest": configuration_digest,
        "code_revision": code_revision,
        "data_manifests": data_references,
        "environment_digest": environment_digest,
        "seeds": seed_values,
        "search_budget": deepcopy(dict(search_budget)),
        "criteria": deepcopy(dict(criteria)),
        "baselines": baseline_values,
    }
    canonical_bytes = canonicalize_json(document)
    manifest = FreezeManifest(canonical_bytes, sha256_bytes(canonical_bytes))
    manifest.verify()
    return manifest
