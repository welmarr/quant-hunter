"""Independent synthetic numerical/temporal controls, never market evidence."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from numpy.typing import ArrayLike

from quant_hunter.patterns import (
    METHODS,
    CausalFrame,
    ClassicalRepresentation,
    FitContext,
    ObservedOutcome,
    PatternError,
    PatternWindow,
    Provenance,
    SearchCancelledError,
    SearchConfig,
    SearchEngine,
    SearchHit,
    TrainingLabel,
    align_asof,
    block_permutation_test,
    compare_dtw,
    constrained_dtw,
    deduplicate,
    fdr_adjust,
    fit_clusters,
    fit_cusum,
    fit_hmm,
    fit_sax,
    fit_shapelet,
    geometry,
    motif_profile,
    normalize,
    outcome_summary,
    paa,
    recurrence,
    relative_candles,
    representation_comparison,
    search_blocks,
    spectra_haar,
    stability_and_costs,
)
from quant_hunter.patterns.contracts import Floats

BASE = 1_700_000_000_000_000_000
STEP = 60_000_000_000
CONTEXT = FitContext(BASE + 500 * STEP, BASE + 501 * STEP)
PROVENANCE = Provenance("SYNTHETIC-fixture", "version-1", "synthetic-equity", "1m")


def frame(
    values: ArrayLike,
    *,
    offset: int = 0,
    delay: int = 0,
    provenance: Provenance = PROVENANCE,
) -> CausalFrame:
    data = np.asarray(values, dtype=np.float64)
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    close = BASE + (offset + np.arange(1, len(data) + 1, dtype=np.int64)) * STEP
    return CausalFrame(data, close, close + delay * STEP, STEP, provenance)


def window(
    values: ArrayLike, *, offset: int = 0, provenance: Provenance = PROVENANCE
) -> PatternWindow:
    data = frame(values, offset=offset, provenance=provenance)
    return data.window(0, len(data.values), decision_ns=int(data.available_ns[-1]))


def outcome(value: float, index: int = 1, cost: float = 0) -> ObservedOutcome:
    stamp = BASE + (index + 1) * STEP
    return ObservedOutcome(1, stamp, stamp, value, max(0, value), min(0, value), cost)


def test_fifteen_real_catalogue_entries_are_distinct_from_research_ids() -> None:
    import quant_hunter.patterns as patterns

    assert tuple(method.family for method in METHODS) == tuple(
        f"PAT-{index:02}" for index in range(1, 16)
    )
    assert all(callable(getattr(patterns, method.entrypoint)) for method in METHODS)


def test_input_arrays_are_defensively_immutable() -> None:
    values = np.arange(8.0).reshape(-1, 1)
    original = frame(values)
    values[:] = 999
    assert original.values[0, 0] == 0
    with pytest.raises(ValueError):
        original.values.flags.writeable = True
    with pytest.raises(ValueError):
        original.close_ns.flags.writeable = True


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, 1e101])
def test_nonfinite_and_excessive_values_rejected(bad: float) -> None:
    with pytest.raises(PatternError):
        frame([1, bad])


def test_closed_availability_gap_and_prediction_boundaries() -> None:
    data = frame([1, 2, 3, 4], delay=1)
    with pytest.raises(PatternError, match="unavailable"):
        data.window(0, 4, decision_ns=int(data.close_ns[-1]))
    assert len(data.known(int(data.close_ns[-1])).values) == 3
    with pytest.raises(PatternError, match="precede"):
        replace(data, available_ns=data.close_ns - 1)
    with pytest.raises(PatternError, match="distinct"):
        replace(data, close_ns=np.array([BASE + STEP] * 4))
    gapped = replace(
        frame([1, 2, 3]),
        close_ns=np.array([BASE + STEP, BASE + 2 * STEP, BASE + 4 * STEP]),
        available_ns=np.array([BASE + STEP, BASE + 2 * STEP, BASE + 4 * STEP]),
    )
    with pytest.raises(PatternError, match="gaps"):
        gapped.window(0, 3, decision_ns=BASE + 10 * STEP)
    with pytest.raises(PatternError, match="purge"):
        FitContext(BASE + 3 * STEP, BASE + 4 * STEP, STEP)
    with pytest.raises(PatternError, match="before frozen"):
        CONTEXT.prediction(window([1, 2, 3]), BASE + 900 * STEP)
    with pytest.raises(PatternError, match="Training label"):
        TrainingLabel(1, BASE + 4 * STEP, BASE + 501 * STEP).validate(
            window([1, 2, 3]), CONTEXT
        )


@pytest.mark.parametrize(
    "mode", ["RAW", "BASE100", "RETURNS", "LOG_RETURNS", "Z_WINDOW", "CAUSAL_VOL"]
)
def test_normalizations_are_explicit_and_constant_safe(mode: str) -> None:
    result = normalize(np.full((8, 1), 10.0), mode)  # type: ignore[arg-type]
    assert np.isfinite(result).all()
    if mode in {"RETURNS", "LOG_RETURNS", "Z_WINDOW", "CAUSAL_VOL"}:
        assert np.array_equal(result, np.zeros((8, 1)))


def test_representation_arithmetic_and_future_invariance() -> None:
    prices = np.array([[100.0], [110.0], [99.0], [108.0]])
    np.testing.assert_allclose(
        normalize(prices, "RETURNS").ravel(), [0, 0.1, -0.1, 9 / 99]
    )
    np.testing.assert_allclose(paa(prices, 2).ravel(), [105, 103.5])
    np.testing.assert_allclose(
        normalize(prices, "Z_WINDOW"), normalize(prices * 20, "Z_WINDOW")
    )
    changed = np.vstack((prices, [[999.0]]))
    np.testing.assert_allclose(
        normalize(prices, "CAUSAL_VOL"), normalize(changed, "CAUSAL_VOL")[:4]
    )
    candles = np.array([[10, 12, 9, 11], [13, 15, 12, 14]], dtype=float)
    np.testing.assert_allclose(
        relative_candles(candles)[1], [1 / 11, 1 / 11, 1 / 11, 2 / 11]
    )
    with pytest.raises(PatternError):
        relative_candles(np.array([[10, 8, 9, 11]], dtype=float))
    with pytest.raises(PatternError):
        normalize(np.array([[0.0], [1.0]]), "BASE100")
    with pytest.raises(PatternError):
        paa(prices, 3)


def test_dtw_hand_oracle_band_and_budget() -> None:
    left = np.array([[0.0], [1.0]])
    right = np.array([[0.0], [2.0]])
    assert constrained_dtw(left, right, radius=0) == pytest.approx(0.5)
    assert constrained_dtw(left, right, radius=1, abandon_above=0.1) == float("inf")
    with pytest.raises(PatternError, match="budget"):
        constrained_dtw(left, right, radius=1, max_cells=1)
    with pytest.raises(PatternError):
        constrained_dtw(left, np.ones((4, 1)), radius=1)
    a, b = window([1, 2, 3, 4]), window([2, 4, 6, 8])
    assert compare_dtw(a, b, decision_ns=a.available_ns, radius=0)["distance"] == 0


def test_motif_discovery_repetition_and_discord_with_nontrivial_exclusion() -> None:
    values = [1, 2, 1, 3, 2, 4, 2, 6, 1, 1, 1, 9]
    result = motif_profile(frame(values), CONTEXT, length=4, stride=4)
    profile = result["profile"]
    assert isinstance(profile, tuple)
    assert profile[0] == pytest.approx(0, abs=1e-7)
    assert profile[1] == pytest.approx(0, abs=1e-7)
    assert profile[2] > 0.1
    assert result["discord_indices"][0] == 2  # type: ignore[index]
    with pytest.raises(PatternError, match="count"):
        motif_profile(frame(np.arange(100)), CONTEXT, length=4, max_windows=10)


def training_windows() -> tuple[PatternWindow, ...]:
    return tuple(
        window(
            np.arange(1, 9) if index < 3 else [1, 3, 1, 3, 1, 3, 1, 3],
            offset=index * 20,
        )
        for index in range(6)
    )


def test_shapelet_trains_on_available_labels_and_predicts_separate_window() -> None:
    windows = training_windows()
    labels = tuple(
        TrainingLabel(int(index >= 3), item.end_ns + STEP, item.end_ns + STEP)
        for index, item in enumerate(windows)
    )
    model = fit_shapelet(windows, labels, CONTEXT, length=8, candidate_cap=6)
    assert model.gain == pytest.approx(1)
    query = window([1, 3, 1, 3, 1, 3, 1, 3], offset=600)
    assert model.predict(query, decision_ns=query.available_ns)[0] == 1
    assert model.candidates_searched == 6
    with pytest.raises(PatternError, match="Training label"):
        fit_shapelet(
            windows,
            (replace(labels[0], available_ns=BASE + 999 * STEP), *labels[1:]),
            CONTEXT,
            length=8,
        )
    with pytest.raises(PatternError, match="classes"):
        fit_shapelet(
            windows,
            tuple(replace(label, value=0) for label in labels),
            CONTEXT,
            length=8,
        )


def test_sax_train_only_vocabulary_unknown_and_overlap_rejection() -> None:
    windows = tuple(
        window(np.arange(1, 9) if index % 2 else np.arange(8, 0, -1), offset=index * 20)
        for index in range(4)
    )
    model = fit_sax(windows, CONTEXT, segments=4, alphabet=2)
    query = window(np.arange(1, 9), offset=600)
    assert model.transform(query, decision_ns=query.available_ns)[1] == "KNOWN"
    flat = window(np.ones(8), offset=600)
    assert model.transform(flat, decision_ns=flat.available_ns)[1] == "UNKNOWN"
    assert sum(count for _, _, count in model.transitions) == 3
    with pytest.raises(PatternError, match="nonoverlapping"):
        fit_sax((windows[0], windows[0]), CONTEXT, alphabet=2)
    with pytest.raises(PatternError, match="alphabet"):
        fit_sax((window(np.ones(8)),), CONTEXT, alphabet=4)


def test_cusum_and_hmm_inference_prefixes_ignore_future_suffix() -> None:
    training = frame(
        np.r_[np.sin(np.arange(30)) * 0.05, 5 + np.sin(np.arange(30)) * 0.05]
    )
    hmm = fit_hmm(training, CONTEXT, iterations=8)
    assert hmm.means[0, 0] < 0.2 and hmm.means[1, 0] > 4.8
    np.testing.assert_allclose(hmm.transition.sum(axis=1), 1)
    original = window([0, 0.1, 0, 5, 5, 5, 5, 5], offset=600)
    altered = window([0, 0.1, 0, -10, 20, 30, 40, 50], offset=600)
    probabilities = hmm.filter(original, decision_ns=original.available_ns)
    np.testing.assert_allclose(probabilities.sum(axis=1), 1)
    np.testing.assert_array_equal(
        probabilities[:3], hmm.filter(altered, decision_ns=altered.available_ns)[:3]
    )
    assert probabilities[-1, 1] > 0.99
    cusum = fit_cusum(frame(np.zeros(20)), CONTEXT, scale_floor=1, threshold=2)
    a = cusum.detect(original, decision_ns=original.available_ns)
    b = cusum.detect(altered, decision_ns=altered.available_ns)
    assert a["scores"][:3] == b["scores"][:3]  # type: ignore[index]
    assert a["alarms"]


def test_hmm_fit_never_uses_rows_after_training_cutoff() -> None:
    context = FitContext(BASE + 40 * STEP, BASE + 41 * STEP)
    values = np.r_[np.zeros(20), np.full(20, 4.0), np.full(20, 100.0)]
    a = fit_hmm(frame(values), context, iterations=4)
    values[-20:] = -500
    b = fit_hmm(frame(values), context, iterations=4)
    np.testing.assert_array_equal(a.means, b.means)
    np.testing.assert_array_equal(a.transition, b.transition)
    assert a.training_rows == 40


def test_spectrum_frequency_and_haar_energy_oracles() -> None:
    values = np.sin(2 * np.pi * np.arange(16) / 4)
    query = window(values)
    result = spectra_haar(query, decision_ns=query.available_ns)
    power = result["hann_power"]
    assert isinstance(power, tuple)
    assert np.argmax(power) == 4
    details = result["haar_details_fine_to_coarse"]
    assert isinstance(details, tuple)
    approximation = result["haar_approximation"]
    assert isinstance(approximation, float)
    energy = sum(value * value for row in details for value in row) + approximation**2
    assert energy == pytest.approx(float((values**2).sum()))
    with pytest.raises(PatternError):
        query = window(np.ones(7))
        spectra_haar(query, decision_ns=query.available_ns)


def test_recurrence_four_point_hand_oracle() -> None:
    query = window(np.ones(4))
    result = recurrence(query, decision_ns=query.available_ns, theiler=1)
    assert result["recurrence_points"] == 6
    assert result["recurrence_rate"] == 1
    assert result["determinism"] == pytest.approx(4 / 6)
    assert result["laminarity"] == pytest.approx(4 / 6)
    assert result["trapping_time"] == 2


def test_cluster_ood_does_not_force_membership() -> None:
    windows = tuple(
        window(np.arange(8) if index % 2 else -np.arange(8), offset=index * 20)
        for index in range(6)
    )
    model = fit_clusters(windows, CONTEXT, clusters=2, segments=4)
    known = window(np.arange(8), offset=600)
    assert model.assign(known, decision_ns=known.available_ns)[0] is not None
    unknown = window(np.sin(np.arange(8)), offset=600)
    assert model.assign(unknown, decision_ns=unknown.available_ns)[0] is None
    with pytest.raises(PatternError, match="schema"):
        model.assign(
            replace(known, provenance=replace(PROVENANCE, features=("spread",))),
            decision_ns=known.available_ns,
        )


def test_geometric_rules_have_independent_breakout_boundaries() -> None:
    up = window([100, 101, 102, 103, 105])
    result = geometry(up, decision_ns=up.available_ns, breakout_fraction=0.01)
    assert result["state"] == "BREAKOUT_UP"
    assert result["channel_slope_per_bar"] == 1
    assert result["channel_max_relative_residual"] == 0
    flat = window([100] * 5)
    assert geometry(flat, decision_ns=flat.available_ns)["state"] == "NO_BREAKOUT"


def test_multivariate_alignment_excludes_not_yet_available_values() -> None:
    a = frame([10, 11, 12, 13])
    b = frame(
        [20, 21, 22, 23], delay=1, provenance=replace(PROVENANCE, instrument_id="other")
    )
    with pytest.raises(PatternError, match="No contemporaneously"):
        align_asof((a, b), decision_ns=BASE + 5 * STEP)
    result = align_asof((a, b), decision_ns=BASE + 5 * STEP, maximum_staleness_ns=STEP)
    np.testing.assert_array_equal(result.frame.values, [[11, 20], [12, 21], [13, 22]])
    assert result.dropped_anchor_rows == 1
    assert result.frame.provenance.features == ("s0:close", "s1:close")
    assert np.all(result.frame.available_ns == result.frame.close_ns)


def search_fixture() -> tuple[CausalFrame, PatternWindow]:
    values = 100 + np.random.default_rng(7).normal(size=70)
    motif = np.array([100, 101, 100, 103, 101, 104, 102, 105], dtype=float)
    values[8:16] = motif
    values[40:48] = motif
    return frame(values), window(motif, offset=200)


def test_exact_search_matches_independent_brute_force_and_unknown() -> None:
    data, query = search_fixture()
    config = SearchConfig(
        mode="EXACT_SMALL",
        normalization="RAW",
        candidate_cap=100,
        max_results=5,
        maximum_distance=0,
        horizon=2,
    )
    result = search_blocks((data,), query, config, decision_ns=query.available_ns)
    brute = [
        i
        for i in range(len(data.values) - 9)
        if np.sqrt(
            sum(
                (float(data.values[i + j, 0]) - float(query.values[j, 0])) ** 2
                for j in range(8)
            )
            / 8
        )
        == 0
    ]
    assert (
        [int((hit.window.start_ns - BASE) / STEP) for hit in result.hits]
        == brute
        == [8, 40]
    )
    assert result.exact_reranks == 61
    assert all(
        hit.outcome is not None and hit.outcome.available_ns <= query.available_ns
        for hit in result.hits
    )
    far = window(np.arange(200, 208), offset=200)
    assert (
        search_blocks((data,), far, config, decision_ns=far.available_ns).state
        == "UNKNOWN"
    )


def test_block_halo_resume_and_partition_results_are_identical() -> None:
    data, query = search_fixture()
    blocks = tuple(
        CausalFrame(
            data.values[i : i + 7],
            data.close_ns[i : i + 7],
            data.available_ns[i : i + 7],
            STEP,
            PROVENANCE,
        )
        for i in range(0, 70, 7)
    )
    config = SearchConfig(
        mode="EXACT_SMALL",
        normalization="RAW",
        candidate_cap=100,
        max_results=5,
        maximum_distance=0,
        horizon=2,
    )
    continuous = search_blocks((data,), query, config, decision_ns=query.available_ns)
    engine = SearchEngine(query, config, query.available_ns)
    for block in blocks[:4]:
        engine.consume(block)
    engine = SearchEngine.resume(engine.snapshot())
    for block in blocks[4:]:
        engine.consume(block)
    resumed = engine.finish()
    assert [(hit.window.start_ns, hit.distance) for hit in continuous.hits] == [
        (hit.window.start_ns, hit.distance) for hit in resumed.hits
    ]
    assert (
        continuous.progress.eligible_windows == resumed.progress.eligible_windows == 61
    )
    with pytest.raises(SearchCancelledError):
        engine.consume(blocks[0], cancelled=lambda: True)
    assert engine.snapshot().progress == resumed.progress


def test_search_actual_horizon_availability_exclusion_and_budgets() -> None:
    data, query = search_fixture()
    availability = data.available_ns.copy()
    availability[16] = query.available_ns + STEP
    delayed = replace(data, available_ns=availability)
    config = SearchConfig(normalization="RAW", maximum_distance=0, horizon=2)
    result = search_blocks((delayed,), query, config, decision_ns=query.available_ns)
    assert len(result.hits) == 1 and result.hits[0].window.start_ns == BASE + 40 * STEP
    with pytest.raises(PatternError, match="candidate cap"):
        search_blocks(
            (data,),
            query,
            replace(config, mode="EXACT_SMALL", candidate_cap=20),
            decision_ns=query.available_ns,
        )
    with pytest.raises(PatternError, match="row budget"):
        search_blocks(
            (data,), query, replace(config, max_rows=20), decision_ns=query.available_ns
        )
    with pytest.raises(PatternError, match="strictly ordered"):
        search_blocks((data, data), query, config, decision_ns=query.available_ns)
    future = frame(np.arange(100, 140), offset=201)
    assert (
        search_blocks((future,), query, config, decision_ns=query.available_ns).state
        == "UNKNOWN"
    )


def test_cross_family_timeframe_event_dedup_includes_outcome_support() -> None:
    first = window(np.ones(8), offset=0)
    second = window(np.ones(8), offset=9)
    later = window(np.ones(8), offset=30)
    a = SearchHit(
        first, 0, ObservedOutcome(4, BASE + 12 * STEP, BASE + 12 * STEP, 0, 0, 0, 0)
    )
    b = SearchHit(second, 0.1, None)
    c = SearchHit(later, 0.2, None)
    assert deduplicate((b, c, a)) == (a, c)
    economic_a = replace(a, window=replace(a.window, event_group="same-economic-event"))
    economic_c = replace(
        c,
        window=replace(
            c.window,
            event_group="same-economic-event",
            provenance=replace(PROVENANCE, instrument_id="other"),
        ),
    )
    assert deduplicate((economic_a, economic_c)) == (economic_a,)


def synthetic_hits() -> tuple[SearchHit, ...]:
    result = []
    for index, value in enumerate([-0.02, 0.01, 0.03, -0.01, 0.02, 0.01, 0.04, -0.02]):
        item = window(np.ones(4) * 100, offset=index * 10)
        observed_result = ObservedOutcome(
            2,
            item.end_ns + 2 * STEP,
            item.end_ns + 3 * STEP,
            value,
            max(0, value),
            min(0, value),
            10,
        )
        result.append(SearchHit(item, index / 100, observed_result))
    return tuple(result)


def test_outcome_uncertainty_costs_and_timing_are_not_profit_confidence() -> None:
    hits = synthetic_hits()
    decision = BASE + 100 * STEP
    result = outcome_summary(
        hits, decision_ns=decision, minimum_events=10, resamples=40
    )
    assert result["state"] == "INSUFFICIENT"
    assert result["mean_net_return"] == pytest.approx(0.0065)
    assert result["positive_net_fraction"] == 5 / 8
    assert result == outcome_summary(
        hits, decision_ns=decision, minimum_events=10, resamples=40
    )
    with pytest.raises(PatternError, match="actual availability"):
        outcome_summary(hits, decision_ns=hits[-1].outcome.horizon_end_ns)  # type: ignore[union-attr]
    assert outcome_summary((), decision_ns=decision)["mean_net_return"] is None
    costs = stability_and_costs(
        hits,
        decision_ns=decision,
        periods=((BASE, BASE + 40 * STEP), (BASE + 40 * STEP, decision)),
        eligible_windows=80,
    )
    assert costs["event_frequency"] == 0.1
    records = costs["cost_stress"]
    assert isinstance(records, tuple)
    assert records[2]["mean_net"] < records[0]["mean_net"]


def test_null_control_and_fdr_account_every_hypothesis() -> None:
    labels = tuple(index < 8 for index in range(16))
    outcomes = tuple(
        outcome(0.1 if marked else -0.1, index=index + 1)
        for index, marked in enumerate(labels)
    )
    result = block_permutation_test(
        labels,
        outcomes,
        decision_ns=BASE + 30 * STEP,
        block_length=2,
        permutations=199,
        seed=3,
    )
    assert 0 < result["pvalue"] < 0.1  # type: ignore[operator]
    null = tuple(replace(item, gross_return=0) for item in outcomes)
    assert (
        block_permutation_test(
            labels, null, decision_ns=BASE + 30 * STEP, block_length=2, permutations=19
        )["pvalue"]
        == 1
    )
    assert fdr_adjust(
        (0.01, 0.04, 0.03), searches_total=3, arbitrary_dependence=False
    ) == pytest.approx((0.03, 0.04, 0.04))
    assert fdr_adjust((0.01, 0.04, 0.03), searches_total=3)[0] > 0.03
    with pytest.raises(PatternError, match="every search"):
        fdr_adjust((0.01,), searches_total=2)


def test_optional_representation_executes_classical_baseline_without_fake_deep_model() -> (
    None
):
    query = window(np.arange(8), offset=600)
    baseline = ClassicalRepresentation(CONTEXT)
    absent = representation_comparison(query, baseline, decision_ns=query.available_ns)
    assert absent["optional_status"] == "NOT_INSTALLED_UNVALIDATED"
    assert len(absent["baseline_values"]) == 4  # type: ignore[arg-type]

    class ToyRepresentation:
        name = "SYNTHETIC_CONTRACT_TEST_NOT_A_DEEP_MODEL"
        context = CONTEXT

        def encode(self, window: PatternWindow, *, decision_ns: int) -> Floats:
            self.context.prediction(window, decision_ns)
            return np.ones((2, 1))

    used = representation_comparison(
        query, baseline, decision_ns=query.available_ns, optional=ToyRepresentation()
    )
    assert used["optional_status"] == "EXECUTED_UNVALIDATED"
