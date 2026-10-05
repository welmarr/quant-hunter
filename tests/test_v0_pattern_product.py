"""All fifteen registered adapter methods execute on real immutable Parquet."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from test_v0_pattern_corpus import DIGEST, source

from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.patterns.corpus import Corpus, CorpusConfig, CorpusStore
from quant_hunter.patterns.product import (
    FrozenPatternBinding,
    PatternJobCancelledError,
    PatternJobConfig,
    PatternProduct,
    PreparedPatternJob,
)
from quant_hunter.storage import ImmutableObjectStore

EXPERIMENT_ID = new_typed_id(RegistryKind.EXPERIMENT)


def setup(
    tmp_path: Path, family: str = "PAT-13", **overrides: Any
) -> tuple[PatternProduct, Corpus, PatternJobConfig, PreparedPatternJob]:
    corpora = CorpusStore(ImmutableObjectStore(tmp_path / "objects"))
    selected, raw = source(1100)
    built = corpora.build(
        new_typed_id(RegistryKind.DATASET),
        selected,
        raw,
        config=CorpusConfig(block_rows=97),
    )
    query = corpora.window(built, 1068, 1100, 2**63 - 1)
    train = corpora.frame(built, 0, 512)
    config = PatternJobConfig(
        family,
        1068,
        1100,
        0,
        512,
        query.available_ns,
        int(train.available_ns[-1]),
        query.start_ns,
        metric="DTW" if family == "PAT-02" else "EUCLIDEAN",
        maximum_distance=1.5,
        **overrides,
    )
    if family == "PAT-11":
        secondary, second_raw = source(1100)
        second = corpora.build(
            new_typed_id(RegistryKind.DATASET),
            secondary,
            second_raw,
            config=CorpusConfig(block_rows=97),
        )
        config = replace(config, secondary_manifest=second.manifest_digest)
    product = PatternProduct(corpora)
    pattern_id = new_typed_id(RegistryKind.PATTERN)
    prepared = product.prepare(
        built.manifest_digest,
        config,
        pattern_id=pattern_id,
        code_revision="a" * 40,
        environment_digest=DIGEST,
    )
    return product, built, config, prepared


def execute(
    product: PatternProduct, prepared: PreparedPatternJob, **kwargs: Any
) -> dict[str, Any]:
    plan = cast(dict[str, Any], prepared.to_record())
    binding = FrozenPatternBinding(
        EXPERIMENT_ID, DIGEST, "sha256:" + "2" * 64, prepared.digest, plan["pattern_id"]
    )
    return cast(
        dict[str, Any],
        product.execute_registered(prepared.digest, binding=binding, **kwargs),
    )


@pytest.mark.parametrize("family", [f"PAT-{index:02}" for index in range(1, 16)])
def test_every_family_actual_registered_result_and_exposure(
    tmp_path: Path, family: str
) -> None:
    product, built, config, prepared = setup(tmp_path, family)
    result = execute(product, prepared)
    assert result["method_id"] == family and result["method"]["status"] == "EXECUTED"
    assert result["exposure"]["variant_count"] == 1
    assert result["exposure"]["rows_visited"] == built.row_count
    assert (
        result["exposure"]["windows_considered"]
        == built.row_count - 32 - config.horizon + 1
    )
    assert (
        result["exposure"]["eligible_windows"] + result["exposure"]["excluded_windows"]
        == result["exposure"]["windows_considered"]
    )
    assert len(result["query"]["raw_values"]) == 32
    assert result["checkpoint_digest"].startswith("sha256:")
    assert result["outcomes"]["event_count"] == len(result["occurrences"])
    assert sum(result["outcome_histogram"]["counts"]) == len(result["occurrences"])
    assert all(item["net_return"] <= 0 for item in result["negative_cases"])
    if family == "PAT-15":
        assert (
            result["method"]["output"]["optional_status"] == "NOT_INSTALLED_UNVALIDATED"
        )


def test_cancelled_immutable_resume_does_not_rescan_prior_partitions(
    tmp_path: Path,
) -> None:
    product, _, _, prepared = setup(tmp_path)
    checkpoints: list[str] = []
    with pytest.raises(PatternJobCancelledError) as cancelled:
        execute(
            product,
            prepared,
            checkpoint=checkpoints.append,
            cancelled=lambda: len(checkpoints) >= 3,
        )
    assert cancelled.value.checkpoint_digest == checkpoints[-1]
    rows: list[dict[str, int | str]] = []
    resumed = execute(
        product, prepared, resume_digest=checkpoints[-1], progress=rows.append
    )
    direct = execute(product, prepared)
    assert rows[0]["partitions"] == 4
    assert resumed["occurrences"] == direct["occurrences"]
    assert resumed["exposure"] == direct["exposure"]
    assert resumed["method"] == direct["method"]


def test_frozen_query_cannot_change_ids_parameters_or_resume_binding(
    tmp_path: Path,
) -> None:
    product, built, config, prepared = setup(tmp_path)
    with pytest.raises(PatternError, match="FROZEN_CONFIG"):
        plan = cast(dict[str, Any], prepared.to_record())
        binding = FrozenPatternBinding(
            EXPERIMENT_ID, DIGEST, DIGEST, DIGEST, plan["pattern_id"]
        )
        product.execute_registered(prepared.digest, binding=binding)
    finished = execute(product, prepared)
    other = product.prepare(
        built.manifest_digest,
        replace(config, seed=1),
        pattern_id=new_typed_id(RegistryKind.PATTERN),
        code_revision="a" * 40,
        environment_digest=DIGEST,
    )
    with pytest.raises(PatternError, match="FROZEN_BINDING"):
        execute(product, other, resume_digest=finished["checkpoint_digest"])


def test_ood_unknown_and_inconclusive_method_are_retained(tmp_path: Path) -> None:
    product, built, config, prepared = setup(tmp_path)
    config = replace(config, maximum_distance=0)
    plan = cast(dict[str, Any], prepared.to_record())
    exact_only = product.prepare(
        built.manifest_digest,
        config,
        pattern_id=plan["pattern_id"],
        code_revision="a" * 40,
        environment_digest=DIGEST,
    )
    result = execute(product, exact_only)
    assert result["state"] == "UNKNOWN" and result["occurrences"] == []
    assert result["outcomes"]["state"] == "INSUFFICIENT"
    bad_shapelet = product.prepare(
        built.manifest_digest,
        replace(config, family="PAT-03", train_stop=80),
        pattern_id=new_typed_id(RegistryKind.PATTERN),
        code_revision="a" * 40,
        environment_digest=DIGEST,
    )
    retained = execute(product, bad_shapelet)
    assert (
        retained["method"]["status"] == "INCONCLUSIVE"
        and retained["method"]["retained"] is True
    )
