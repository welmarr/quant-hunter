"""Independent-review reproductions retain otherwise-valid frozen/source state."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from test_v0_pattern_composition import composed
from test_v0_pattern_product import execute, setup

from quant_hunter.config import canonicalize_json, parse_json_document
from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.patterns import codec
from quant_hunter.patterns.contracts import CausalFrame, PatternError
from quant_hunter.patterns.corpus import CorpusConfig
from quant_hunter.patterns.product import PreparedPatternJob
from quant_hunter.patterns.search import SearchSnapshot


@pytest.mark.parametrize("block_length", [14, 40])
def test_frozen_bootstrap_blocks_are_never_clipped_to_observed_events(
    tmp_path: Path,
    block_length: int,
) -> None:
    product, _, _, prepared = setup(
        tmp_path,
        "PAT-12",
        method_parameters_json=f'{{"block_length":{block_length}}}',
    )
    result = execute(product, prepared)
    assert result["method_parameters"]["block_length"] == block_length
    assert result["method"]["status"] == "INCONCLUSIVE"
    assert result["method"]["reason"] == "PAT12_INSUFFICIENT_FIXED_BOOTSTRAP_BLOCKS"
    assert "output" not in result["method"]
    assert result["outcomes"]["mean_interval"] is None
    assert result["outcomes"]["bootstrap"]["block_length"] == block_length


@pytest.mark.parametrize(
    "mutation", ["variant", "parents", "parameters", "secondary", "scope", "extra"]
)
def test_rehashed_prepared_description_cannot_change_repeated_fields(
    tmp_path: Path,
    mutation: str,
) -> None:
    product, _, _, prepared = setup(tmp_path)
    plan = cast(dict[str, Any], prepared.to_record())
    if mutation == "variant":
        plan["planned_scope"]["variant_count"] = 0
    elif mutation == "parents":
        plan["parent_snapshots"] = []
    elif mutation == "parameters":
        plan["expanded_method_parameters"] = {"unregistered": 12}
    elif mutation == "secondary":
        plan["secondary_parent_snapshots"] = plan["parent_snapshots"]
    elif mutation == "scope":
        plan["planned_scope"]["maximum_considered_windows"] -= 1
    else:
        plan["unfrozen_annotation"] = True
    raw = canonicalize_json(plan)
    forged = PreparedPatternJob(
        product.corpora.objects.publish(raw).digest, raw.decode()
    )
    with pytest.raises(PatternError, match="PREPARED_DESCRIPTION_BINDING"):
        execute(product, forged)


@pytest.mark.parametrize("mutation", ["missing", "parents", "profile", "bounds"])
def test_rehashed_corpus_reloads_exact_composition_graph(
    tmp_path: Path, mutation: str
) -> None:
    store, selection, batches = composed(tmp_path)
    corpus = store.build_selection(
        new_typed_id(RegistryKind.DATASET),
        selection,
        batches,
        config=CorpusConfig(block_rows=37),
    )
    record = cast(
        dict[str, Any],
        parse_json_document(store.objects.read_bytes(corpus.manifest_digest)),
    )
    if mutation == "missing":
        record["selection_manifest_digest"] = "sha256:" + "f" * 64
    else:
        manifest = cast(
            dict[str, Any],
            parse_json_document(store.objects.read_bytes(selection.manifest_digest)),
        )
        if mutation == "parents":
            manifest["parent_snapshots"] = []
        elif mutation == "profile":
            manifest["calendar_profile"]["anchor"] = "CHANGED"
        else:
            manifest["bounds"]["start"] = manifest["bounds"]["end"]
        record["selection_manifest_digest"] = store.objects.publish(
            canonicalize_json(manifest)
        ).digest
    digest = store.objects.publish(canonicalize_json(record)).digest
    with pytest.raises(PatternError, match="SELECTION_MANIFEST"):
        store.load(digest)


@pytest.mark.parametrize(
    "mutation", ["outcomes", "values", "halo_values", "halo_availability", "chain"]
)
def test_rehashed_checkpoint_must_match_corpus_bytes_and_complete_chain(
    tmp_path: Path,
    mutation: str,
) -> None:
    product, _, _, prepared = setup(tmp_path)
    direct = execute(product, prepared)
    record = cast(
        dict[str, Any],
        parse_json_document(
            product.corpora.objects.read_bytes(direct["checkpoint_digest"])
        ),
    )
    snapshot = cast(SearchSnapshot, codec._decode(record["snapshot"]))
    expected_error = "RESUME_SOURCE"
    if mutation in {"outcomes", "values"}:
        changed = []
        for score, serial, hit in snapshot.candidates:
            assert hit.outcome is not None
            if mutation == "outcomes":
                hit = replace(
                    hit,
                    outcome=replace(
                        hit.outcome,
                        gross_return=0.5,
                        favorable_close_return=0.5,
                        adverse_close_return=0,
                    ),
                )
            else:
                hit = replace(
                    hit, window=replace(hit.window, values=hit.window.values * 2)
                )
            changed.append((score, serial, hit))
        snapshot = replace(snapshot, candidates=tuple(changed))
    elif mutation.startswith("halo"):
        assert snapshot.halo is not None
        halo = snapshot.halo
        values, availability = halo.values.copy(), halo.available_ns.copy()
        if mutation == "halo_values":
            values[0, 0] += 0.01
        else:
            availability[0] += 1
        snapshot = replace(
            snapshot,
            halo=CausalFrame(
                values, halo.close_ns, availability, halo.step_ns, halo.provenance
            ),
        )
    else:
        record["previous_digest"], record["previous_total_bytes"] = None, 0
        expected_error = "CHECKPOINT_CHAIN_BYTES"
    record["snapshot"] = codec._encode(snapshot)
    # Same valid source IDs, frozen binding, cadence, candidate timing and PAA score.
    # Only the specifically named bytes/outcome/chain assertion should reject it.
    forged = product.corpora.objects.publish(canonicalize_json(record)).digest
    with pytest.raises(PatternError, match=expected_error):
        execute(product, prepared, resume_digest=forged)
