"""Observed horizon distributions, uncertainty and conservative event counting."""

from __future__ import annotations

from math import ceil, sqrt
from statistics import NormalDist

import numpy as np

from quant_hunter.patterns.contracts import PatternError, bounded_int, instant
from quant_hunter.patterns.search import ObservedOutcome, SearchHit, deduplicate


def observed(outcome: ObservedOutcome, decision_ns: int) -> None:
    instant(decision_ns)
    if not 0 < outcome.horizon_end_ns <= outcome.available_ns <= decision_ns:
        raise PatternError(
            "Full outcome horizon and actual availability must precede decision"
        )
    if (
        outcome.horizon < 1
        or not all(
            np.isfinite(value)
            for value in (
                outcome.gross_return,
                outcome.favorable_close_return,
                outcome.adverse_close_return,
                outcome.cost_bps,
            )
        )
        or not 0 <= outcome.cost_bps <= 10_000
    ):
        raise PatternError("Invalid observed outcome")


def outcome_summary(
    hits: tuple[SearchHit, ...],
    *,
    decision_ns: int,
    minimum_events: int = 10,
    resamples: int = 200,
    block_length: int = 2,
    seed: int = 0,
    confidence: float = 0.95,
) -> dict[str, object]:
    """Circular moving-block bootstrap of chronological nonoverlapping events.

    The Wilson interval is separately labelled an IID descriptive approximation;
    neither interval proves independence, calibration or scientific acceptance.
    """
    bounded_int(minimum_events, 2, 4096, "minimum events")
    bounded_int(resamples, 20, 2000, "bootstrap draws")
    bounded_int(seed, 0, 2**32 - 1, "seed")
    if not 0.5 < confidence < 1:
        raise PatternError("Confidence must lie strictly between .5 and 1")
    events = tuple(
        sorted(deduplicate(hits, limit=4096), key=lambda hit: hit.window.end_ns)
    )
    if not events:
        return {
            "method_id": "PAT-12",
            "state": "INSUFFICIENT",
            "event_count": 0,
            "mean_net_return": None,
            "mean_interval": None,
        }
    if len({hit.window.provenance.instrument_id for hit in events}) != 1:
        raise PatternError(
            "Summarize instruments separately; cross-asset independence is unknown"
        )
    if any(hit.outcome is None for hit in events):
        raise PatternError("Every event requires a fully observed outcome")
    outcomes = tuple(hit.outcome for hit in events if hit.outcome is not None)
    if len({outcome.horizon for outcome in outcomes}) != 1:
        raise PatternError("Do not pool different outcome horizons")
    for hit, outcome in zip(events, outcomes, strict=True):
        hit.window.require_known(decision_ns)
        observed(outcome, decision_ns)
        if outcome.horizon_end_ns <= hit.window.end_ns:
            raise PatternError("Outcome must follow the pattern window")
    values = np.array([outcome.net_return for outcome in outcomes])
    count = len(values)
    bounded_int(block_length, 1, count, "bootstrap block length")
    rng = np.random.default_rng(seed)
    means = np.empty(resamples)
    for iteration in range(resamples):
        starts = rng.integers(0, count, size=ceil(count / block_length))
        indices = ((starts[:, None] + np.arange(block_length)) % count).ravel()[:count]
        means[iteration] = values[indices].mean()
    tail = (1 - confidence) / 2
    interval = tuple(float(value) for value in np.quantile(means, [tail, 1 - tail]))
    wins = int((values > 0).sum())
    probability = wins / count
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    denominator = 1 + z**2 / count
    center = (probability + z**2 / (2 * count)) / denominator
    margin = (
        z
        * sqrt(probability * (1 - probability) / count + z**2 / (4 * count**2))
        / denominator
    )
    return {
        "method_id": "PAT-12",
        "state": "DESCRIPTIVE_ONLY" if count >= minimum_events else "INSUFFICIENT",
        "event_count": count,
        "input_hit_count": len(hits),
        "horizon_bars": outcomes[0].horizon,
        "mean_net_return": float(values.mean()),
        "median_net_return": float(np.median(values)),
        "net_quantiles_05_25_50_75_95": tuple(
            float(value) for value in np.quantile(values, [0.05, 0.25, 0.5, 0.75, 0.95])
        ),
        "mean_interval": interval,
        "bootstrap": {
            "method": "CIRCULAR_EVENT_BLOCK",
            "block_length": block_length,
            "resamples": resamples,
            "seed": seed,
            "confidence": confidence,
        },
        "positive_net_fraction": probability,
        "iid_wilson_descriptive_interval": (
            max(0, center - margin),
            min(1, center + margin),
        ),
        "mean_favorable_close_return": float(
            np.mean([outcome.favorable_close_return for outcome in outcomes])
        ),
        "mean_adverse_close_return": float(
            np.mean([outcome.adverse_close_return for outcome in outcomes])
        ),
        "maximum_known_ns": max(outcome.available_ns for outcome in outcomes),
        "limitations": (
            "Intervals do not establish sample independence or out-of-sample calibration.",
            "Closing-mark excursions omit intrabar extremes; no executable fill is implied.",
            "Conditional positive-return frequency is not a future profit probability.",
        ),
    }
