"""Numerical controls only. Item 8 and scientific gates remain external authority."""

from __future__ import annotations

from itertools import pairwise

import numpy as np

from quant_hunter.patterns.contracts import PatternError, bounded_int
from quant_hunter.patterns.outcomes import observed
from quant_hunter.patterns.search import ObservedOutcome, SearchHit, deduplicate


def fdr_adjust(
    pvalues: tuple[float, ...],
    *,
    searches_total: int,
    arbitrary_dependence: bool = True,
) -> tuple[float, ...]:
    """BY by default; BH only when its dependence assumptions are justified.

    All attempted hypotheses must be represented, including failures assigned
    conservative p=1 by the caller. This count does not replace Item 8 exposure.
    """
    bounded_int(searches_total, 1, 100_000, "total searches")
    if len(pvalues) != searches_total or any(
        not np.isfinite(value) or not 0 <= value <= 1 for value in pvalues
    ):
        raise PatternError("Complete finite p-values for every search are required")
    count = len(pvalues)
    factor = float(np.sum(1 / np.arange(1, count + 1))) if arbitrary_dependence else 1.0
    order = np.argsort(pvalues, kind="stable")
    adjusted = np.empty(count)
    running = 1.0
    for position in range(count - 1, -1, -1):
        index = int(order[position])
        running = min(running, pvalues[index] * count * factor / (position + 1))
        adjusted[index] = running
    return tuple(float(value) for value in adjusted)


def block_permutation_test(
    signal: tuple[bool, ...],
    outcomes: tuple[ObservedOutcome, ...],
    *,
    decision_ns: int,
    block_length: int = 4,
    permutations: int = 199,
    seed: int = 0,
) -> dict[str, object]:
    """Two-sided marked-versus-unmarked mean-return contrast, permuted by blocks."""
    count = len(outcomes)
    if (
        not 8 <= count <= 4096
        or len(signal) != count
        or any(type(item) is not bool for item in signal)
        or len(set(signal)) != 2
    ):
        raise PatternError(
            "Null control needs 8-4096 outcomes and both fixed signal groups"
        )
    bounded_int(block_length, 1, count // 2, "permutation block")
    bounded_int(permutations, 19, 2000, "permutation count")
    bounded_int(seed, 0, 2**32 - 1, "seed")
    if count % block_length:
        raise PatternError("Outcome count must divide into equal permutation blocks")
    if len({outcome.horizon for outcome in outcomes}) != 1 or any(
        a.horizon_end_ns >= b.horizon_end_ns for a, b in pairwise(outcomes)
    ):
        raise PatternError(
            "Null-control outcomes require a common horizon and strict chronology"
        )
    for outcome in outcomes:
        observed(outcome, decision_ns)
    mask = np.array(signal)
    values = np.array([outcome.net_return for outcome in outcomes])
    statistic = abs(float(values[mask].mean() - values[~mask].mean()))
    blocks = values.reshape(-1, block_length)
    rng = np.random.default_rng(seed)
    exceedances = 0
    for _ in range(permutations):
        shuffled = blocks[rng.permutation(len(blocks))].ravel()
        exceedances += (
            abs(float(shuffled[mask].mean() - shuffled[~mask].mean()))
            >= statistic - 1e-15
        )
    return {
        "method_id": "PAT-14",
        "statistic": statistic,
        "pvalue": (exceedances + 1) / (permutations + 1),
        "permutations": permutations,
        "block_length": block_length,
        "seed": seed,
        "limitation": "Exchangeability between blocks is assumed, not proven. Preselect block length and count every tested variant.",
    }


def stability_and_costs(
    hits: tuple[SearchHit, ...],
    *,
    decision_ns: int,
    periods: tuple[tuple[int, int], ...],
    eligible_windows: int,
    multipliers: tuple[float, ...] = (1, 2, 3),
    minimum_per_period: int = 3,
) -> dict[str, object]:
    bounded_int(eligible_windows, 1, 50_000_000, "eligible window count")
    bounded_int(minimum_per_period, 1, 1000, "minimum period events")
    if (
        not 2 <= len(periods) <= 20
        or any(a >= b for a, b in periods)
        or any(left[1] > right[0] for left, right in pairwise(periods))
    ):
        raise PatternError("Stability periods require disjoint chronological intervals")
    if not 1 <= len(multipliers) <= 10 or any(
        not np.isfinite(item) or not 0 <= item <= 10 for item in multipliers
    ):
        raise PatternError("Cost multipliers must be finite and bounded")
    events = deduplicate(hits, limit=4096)
    if len(events) > eligible_windows:
        raise PatternError("Event frequency denominator is inconsistent")
    for hit in events:
        hit.window.require_known(decision_ns)
        if hit.outcome is None:
            raise PatternError("Stability requires observed horizons")
        observed(hit.outcome, decision_ns)
    records: list[dict[str, object]] = []
    for start, end in periods:
        selected = [
            hit.outcome
            for hit in events
            if start <= hit.window.end_ns < end and hit.outcome is not None
        ]
        records.append(
            {
                "start_ns": start,
                "end_ns": end,
                "events": len(selected),
                "state": "DESCRIPTIVE_ONLY"
                if len(selected) >= minimum_per_period
                else "INSUFFICIENT",
                "mean_net": float(np.mean([item.net_return for item in selected]))
                if selected
                else None,
            }
        )
    cost = tuple(
        {
            "multiplier": multiplier,
            "mean_net": float(
                np.mean(
                    [
                        hit.outcome.gross_return
                        - multiplier * hit.outcome.cost_bps / 10_000
                        for hit in events
                        if hit.outcome is not None
                    ]
                )
            )
            if events
            else None,
        }
        for multiplier in multipliers
    )
    return {
        "method_id": "PAT-14",
        "event_count": len(events),
        "eligible_windows": eligible_windows,
        "event_frequency": len(events) / eligible_windows,
        "periods": tuple(records),
        "cost_stress": cost,
        "state": "DESCRIPTIVE_ONLY",
        "limitation": "Frequency/stability/cost diagnostics cannot promote a pattern or substitute for sealed chronological validation.",
    }
