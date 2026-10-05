"""Fail-closed resource, schema and checkpoint cases for the pure computation layer."""

from dataclasses import replace
from typing import cast

import numpy as np
import pytest
from test_v0_patterns import (
    BASE,
    CONTEXT,
    PROVENANCE,
    STEP,
    frame,
    search_fixture,
    synthetic_hits,
    training_windows,
    window,
)

from quant_hunter.patterns import (
    CausalFrame,
    ClassicalRepresentation,
    FitContext,
    ObservedOutcome,
    PatternError,
    Provenance,
    SearchCancelledError,
    SearchConfig,
    SearchEngine,
    SearchHit,
    align_asof,
    block_permutation_test,
    compare_dtw,
    constrained_dtw,
    fit_clusters,
    fit_cusum,
    fit_hmm,
    fit_sax,
    fit_shapelet,
    geometry,
    outcome_summary,
    recurrence,
    representation_comparison,
    search_blocks,
    stability_and_costs,
)
from quant_hunter.patterns.representations import Normalization
from quant_hunter.patterns.search import SearchProgress


@pytest.mark.parametrize(
    "parameters",
    [
        {"candidate_cap": 0},
        {"max_results": 101},
        {"mode": "UNKNOWN"},
        {"metric": "UNKNOWN"},
        {"normalization": "UNKNOWN"},
        {"maximum_distance": float("nan")},
        {"cost_bps": -1},
        {"max_working_bytes": 2},
        {"horizon": 513},
        {"dtw_radius": True},
    ],
)
def test_search_parameter_resource_contracts(parameters: dict[str, object]) -> None:
    with pytest.raises(PatternError):
        SearchConfig(**parameters)  # type: ignore[arg-type]


def test_invalid_identity_features_integer_times_and_window_geometry() -> None:
    with pytest.raises(PatternError):
        Provenance("", "x", "y", "1m")
    with pytest.raises(PatternError):
        replace(PROVENANCE, features=("close", "close"))
    original = frame([1, 2, 3])
    with pytest.raises(PatternError):
        replace(original, close_ns=original.close_ns.astype(float))
    with pytest.raises(PatternError):
        replace(original, close_ns=np.array([0, 1, 2], dtype=np.int64))
    with pytest.raises(PatternError):
        replace(original, provenance=replace(PROVENANCE, features=("close", "volume")))
    with pytest.raises(PatternError):
        original.known(BASE)
    item = window([1, 2, 3])
    with pytest.raises(PatternError):
        replace(item, end_ns=item.end_ns + 1)
    with pytest.raises(PatternError):
        replace(item, event_group="x" * 201)
    with pytest.raises(PatternError):
        replace(item, values=np.ones((1, 1)))
    with pytest.raises(PatternError):
        CONTEXT.validate(())
    with pytest.raises(PatternError):
        CONTEXT.validate((window([1, 2], offset=600),))


@pytest.mark.parametrize(
    "changes",
    [
        {"cost_bps": float("inf")},
        {"gross_return": -2},
        {"available_ns": BASE},
        {"favorable_close_return": -1},
        {"horizon": 0},
    ],
)
def test_outcome_constructor_rejects_impossible_claims(
    changes: dict[str, object],
) -> None:
    original = ObservedOutcome(1, BASE + STEP, BASE + STEP, 0, 0, 0, 0)
    with pytest.raises(PatternError):
        replace(original, **changes)  # type: ignore[arg-type]


def test_checkpoint_resume_revalidates_candidates_and_halo() -> None:
    data, query = search_fixture()
    engine = SearchEngine(query, SearchConfig(horizon=2), query.available_ns)
    engine.consume(data)
    snapshot = engine.snapshot()
    assert SearchEngine.resume(snapshot).finish().hits
    with pytest.raises(PatternError, match="counters"):
        SearchEngine.resume(
            replace(
                snapshot, progress=replace(snapshot.progress, candidates_retained=0)
            )
        )
    with pytest.raises(PatternError, match="counters"):
        SearchEngine.resume(
            replace(snapshot, progress=replace(snapshot.progress, rows=1))
        )
    assert snapshot.halo is not None
    with pytest.raises(PatternError, match="halo"):
        SearchEngine.resume(
            replace(
                snapshot,
                halo=replace(
                    snapshot.halo,
                    provenance=replace(PROVENANCE, dataset_version="altered"),
                ),
            )
        )
    first, *rest = snapshot.candidates
    with pytest.raises(PatternError, match="score"):
        SearchEngine.resume(
            replace(snapshot, candidates=((first[0] - 2, first[1], first[2]), *rest))
        )
    with pytest.raises(PatternError, match="identity"):
        SearchEngine.resume(
            replace(snapshot, candidates=((first[0], first[1] - 1, first[2]), *rest))
        )
    with pytest.raises(SearchCancelledError):
        engine.finish(cancelled=lambda: True)


@pytest.mark.parametrize("change", ["missing", "horizon", "cost", "unexpected"])
def test_checkpoint_outcome_is_bound_to_frozen_configuration(change: str) -> None:
    data, query = search_fixture()
    engine = SearchEngine(
        query, SearchConfig(horizon=2, cost_bps=7), query.available_ns
    )
    engine.consume(data)
    snapshot = engine.snapshot()
    score, serial, hit = snapshot.candidates[0]
    assert hit.outcome is not None
    if change == "missing":
        modified = replace(hit, outcome=None)
    elif change == "cost":
        modified = replace(hit, outcome=replace(hit.outcome, cost_bps=999))
    elif change == "horizon":
        modified = replace(
            hit,
            outcome=replace(
                hit.outcome, horizon=1, horizon_end_ns=hit.window.end_ns + STEP
            ),
        )
    else:
        modified = hit
        # Keep all otherwise-valid support/score/counters using the original
        # horizon-2 state; shorten only the now horizon-0 halo to its required size.
        snapshot = replace(snapshot, config=replace(snapshot.config, horizon=0))
        assert snapshot.halo is not None
        halo = snapshot.halo
        size = len(query.values) - 1
        snapshot = replace(
            snapshot,
            halo=replace(
                halo,
                values=halo.values[-size:],
                close_ns=halo.close_ns[-size:],
                available_ns=halo.available_ns[-size:],
            ),
        )
    snapshot = replace(
        snapshot, candidates=((score, serial, modified), *snapshot.candidates[1:])
    )
    with pytest.raises(PatternError, match="outcome"):
        SearchEngine.resume(snapshot)


def test_cusum_rejects_changed_feature_identity_and_sampling_grid() -> None:
    model = fit_cusum(frame(np.zeros(20)), CONTEXT)
    known = window([0, 0, 1, 1], offset=600)
    assert model.detect(known, decision_ns=known.available_ns)
    with pytest.raises(PatternError, match="schema/time grid"):
        model.detect(
            replace(known, provenance=replace(known.provenance, features=("spread",))),
            decision_ns=known.available_ns,
        )
    changed = replace(
        known, step_ns=STEP * 2, start_ns=known.end_ns - len(known.values) * STEP * 2
    )
    with pytest.raises(PatternError, match="schema/time grid"):
        model.detect(changed, decision_ns=known.available_ns)


def test_checkpoint_candidate_must_preserve_corpus_time_grid() -> None:
    data, query = search_fixture()
    engine = SearchEngine(query, SearchConfig(horizon=2), query.available_ns)
    engine.consume(data)
    snapshot = engine.snapshot()
    score, _, hit = snapshot.candidates[0]
    step = STEP // 2
    changed = replace(
        hit.window,
        step_ns=step,
        start_ns=hit.window.end_ns - len(hit.window.values) * step,
    )
    assert hit.outcome is not None
    outcome = replace(hit.outcome, horizon_end_ns=changed.end_ns + 2 * step)
    candidate = (
        score,
        -changed.start_ns - step,
        replace(hit, window=changed, outcome=outcome),
    )
    with pytest.raises(PatternError, match="identity/schema"):
        SearchEngine.resume(
            replace(snapshot, candidates=(candidate, *snapshot.candidates[1:]))
        )


@pytest.mark.parametrize(
    "mode", ["RAW", "BASE100", "RETURNS", "LOG_RETURNS", "Z_WINDOW", "CAUSAL_VOL"]
)
def test_blocked_search_normalizations_keep_partition_parity(mode: str) -> None:
    data, query = search_fixture()
    config = SearchConfig(
        normalization=cast(Normalization, mode),
        candidate_cap=32,
        horizon=0,
        max_results=3,
    )
    whole = search_blocks((data,), query, config, decision_ns=query.available_ns)
    parts = tuple(
        CausalFrame(
            data.values[start : start + 10],
            data.close_ns[start : start + 10],
            data.available_ns[start : start + 10],
            STEP,
            PROVENANCE,
        )
        for start in range(0, 70, 10)
    )
    split = search_blocks(parts, query, config, decision_ns=query.available_ns)
    assert [(hit.window.start_ns, hit.distance) for hit in whole.hits] == [
        (hit.window.start_ns, hit.distance) for hit in split.hits
    ]


def test_dtw_reranking_and_progress_are_executed_and_bounded() -> None:
    data, query = search_fixture()
    updates: list[SearchProgress] = []
    result = search_blocks(
        (data,),
        query,
        SearchConfig(metric="DTW", candidate_cap=16, max_results=2),
        decision_ns=query.available_ns,
        progress=updates.append,
    )
    assert len(updates) == 1 and updates[0].rows == 70
    assert result.exact_reranks == 16 and result.hits[0].distance == 0
    with pytest.raises(PatternError, match="budget"):
        SearchEngine(
            window(np.arange(512)),
            SearchConfig(metric="DTW", candidate_cap=4096, dtw_radius=128),
            BASE + 600 * STEP,
        )
    with pytest.raises(PatternError):
        SearchEngine(window(np.arange(7)), SearchConfig(), BASE + 10 * STEP)
    with pytest.raises(PatternError):
        constrained_dtw(np.ones((2, 1)), np.ones((2, 1)), radius=0, abandon_above=-1)


def test_corpus_binding_and_outcome_feature_semantics() -> None:
    data, query = search_fixture()
    engine = SearchEngine(query, SearchConfig(), query.available_ns)
    engine.consume(data)
    future_block = frame(
        np.ones(8),
        offset=100,
        provenance=replace(PROVENANCE, dataset_version="different"),
    )
    with pytest.raises(PatternError, match="silently change"):
        engine.consume(future_block)
    with pytest.raises(PatternError, match="feature/time"):
        engine.consume(
            replace(future_block, provenance=replace(PROVENANCE, features=("spread",)))
        )
    quote_data = replace(data, provenance=replace(PROVENANCE, features=("spread",)))
    quote_query = replace(query, provenance=quote_data.provenance)
    with pytest.raises(PatternError, match="first feature"):
        search_blocks(
            (quote_data,), quote_query, SearchConfig(), decision_ns=query.available_ns
        )
    with pytest.raises(PatternError):
        SearchHit(query, -1, None)
    with pytest.raises(PatternError, match="horizon"):
        SearchHit(
            query,
            0,
            ObservedOutcome(
                1, query.end_ns + 2 * STEP, query.end_ns + 2 * STEP, 0, 0, 0, 0
            ),
        )


def test_learning_rejects_schema_changed_queries_and_degenerate_training() -> None:
    query = window(np.arange(8), offset=600)
    incompatible = replace(query, provenance=replace(PROVENANCE, features=("spread",)))
    with pytest.raises(PatternError, match="schema"):
        fit_hmm(frame(np.arange(30)), CONTEXT, iterations=1).filter(
            incompatible, decision_ns=query.available_ns
        )
    with pytest.raises(PatternError):
        fit_sax((window(np.arange(8)),), CONTEXT, alphabet=2).transform(
            incompatible, decision_ns=query.available_ns
        )
    with pytest.raises(PatternError):
        fit_clusters((window(np.arange(8)),), CONTEXT, clusters=2)
    with pytest.raises(PatternError):
        fit_clusters((window(np.arange(8)),), CONTEXT, clusters=1, radius_factor=0)
    with pytest.raises(PatternError):
        fit_shapelet(training_windows(), (), CONTEXT, length=8)
    with pytest.raises(PatternError):
        fit_hmm(frame(np.arange(4)), CONTEXT)
    with pytest.raises(PatternError):
        fit_hmm(frame(np.arange(30)), CONTEXT, variance_floor=0)
    with pytest.raises(PatternError):
        fit_cusum(frame(np.arange(3)), CONTEXT)
    with pytest.raises(PatternError):
        fit_cusum(frame(np.arange(8)), CONTEXT, threshold=0)


def test_diagnostics_reject_incompatible_support_and_invalid_parameters() -> None:
    query = window(np.arange(1, 9))
    with pytest.raises(PatternError):
        compare_dtw(
            query,
            replace(query, provenance=replace(PROVENANCE, features=("other",))),
            decision_ns=query.available_ns,
        )
    with pytest.raises(PatternError):
        recurrence(query, decision_ns=query.available_ns, radius=0)
    with pytest.raises(PatternError):
        geometry(query, decision_ns=query.available_ns, channel_tolerance=-1)
    with pytest.raises(PatternError):
        geometry(window([1, 2, 3]), decision_ns=query.available_ns)
    with pytest.raises(PatternError):
        align_asof((frame([1, 2]),), decision_ns=query.available_ns)


def test_outcome_stratification_and_no_pooled_missing_horizons() -> None:
    hits = synthetic_hits()
    assert (
        outcome_summary(hits, decision_ns=BASE + 100 * STEP, minimum_events=2)["state"]
        == "DESCRIPTIVE_ONLY"
    )
    with pytest.raises(PatternError, match="separately"):
        outcome_summary(
            (
                hits[0],
                replace(
                    hits[1],
                    window=replace(
                        hits[1].window,
                        provenance=replace(PROVENANCE, instrument_id="other"),
                    ),
                ),
            ),
            decision_ns=BASE + 100 * STEP,
        )
    with pytest.raises(PatternError, match="fully observed"):
        outcome_summary(
            (replace(hits[0], outcome=None),), decision_ns=BASE + 100 * STEP
        )
    with pytest.raises(PatternError):
        outcome_summary(hits, decision_ns=BASE + 100 * STEP, confidence=1)
    with pytest.raises(PatternError):
        block_permutation_test((True,), (), decision_ns=BASE + 100 * STEP)
    with pytest.raises(PatternError):
        stability_and_costs(
            hits,
            decision_ns=BASE + 100 * STEP,
            periods=((BASE, BASE + STEP),),
            eligible_windows=20,
        )
    with pytest.raises(PatternError):
        stability_and_costs(
            hits,
            decision_ns=BASE + 100 * STEP,
            periods=((BASE, BASE + STEP), (BASE + STEP, BASE + 2 * STEP)),
            eligible_windows=1,
        )


def test_optional_representation_requires_same_training_boundary() -> None:
    query = window(np.arange(8), offset=600)
    baseline = ClassicalRepresentation(CONTEXT)

    class Incompatible:
        name = "SYNTHETIC_ONLY"
        context = FitContext(BASE + 10 * STEP, BASE + 11 * STEP)

        def encode(self, window: object, *, decision_ns: int) -> np.ndarray:
            return np.ones((2, 1))

    with pytest.raises(PatternError, match="same training"):
        representation_comparison(
            query, baseline, decision_ns=query.available_ns, optional=Incompatible()
        )
