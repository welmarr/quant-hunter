"""Incremental bounded candidate search with honest exact/approximate semantics."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from heapq import heappush, heapreplace
from typing import Literal

import numpy as np

from quant_hunter.patterns.contracts import (
    CausalFrame,
    PatternError,
    PatternWindow,
    Provenance,
    SearchCancelledError,
    bounded_int,
    instant,
)
from quant_hunter.patterns.representations import (
    Normalization,
    constrained_dtw,
    euclidean,
    normalize,
    paa,
)


@dataclass(frozen=True, slots=True)
class ObservedOutcome:
    """Closing-mark diagnostics, not executable fill or intrabar excursion claims."""

    horizon: int
    horizon_end_ns: int
    available_ns: int
    gross_return: float
    favorable_close_return: float
    adverse_close_return: float
    cost_bps: float

    def __post_init__(self) -> None:
        bounded_int(self.horizon, 1, 512, "observed horizon")
        instant(self.horizon_end_ns)
        instant(self.available_ns)
        if self.available_ns < self.horizon_end_ns:
            raise PatternError("Outcome availability precedes its horizon end")
        numbers = (
            self.gross_return,
            self.favorable_close_return,
            self.adverse_close_return,
            self.cost_bps,
        )
        if (
            not all(np.isfinite(value) for value in numbers)
            or not 0 <= self.cost_bps <= 10_000
        ):
            raise PatternError("Outcome values and costs must be finite and bounded")
        if not -1 <= self.adverse_close_return <= min(
            0, self.gross_return
        ) or not self.favorable_close_return >= max(0, self.gross_return):
            raise PatternError("Positive-close return and excursion bounds disagree")

    @property
    def net_return(self) -> float:
        return self.gross_return - self.cost_bps / 10_000


@dataclass(frozen=True, slots=True)
class SearchConfig:
    mode: Literal["EXACT_SMALL", "APPROXIMATE"] = "APPROXIMATE"
    normalization: Normalization = "Z_WINDOW"
    metric: Literal["EUCLIDEAN", "DTW"] = "EUCLIDEAN"
    paa_segments: int = 8
    candidate_cap: int = 256
    max_results: int = 20
    dtw_radius: int = 4
    horizon: int = 1
    cost_bps: float = 0
    maximum_distance: float = 1
    exclusion_ns: int = 0
    max_rows: int = 10_000_000
    max_working_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.mode not in {"EXACT_SMALL", "APPROXIMATE"} or self.metric not in {
            "EUCLIDEAN",
            "DTW",
        }:
            raise PatternError("Unknown search mode/metric")
        if self.normalization not in {
            "RAW",
            "BASE100",
            "RETURNS",
            "LOG_RETURNS",
            "Z_WINDOW",
            "CAUSAL_VOL",
        }:
            raise PatternError("Unknown normalization")
        bounded_int(self.paa_segments, 1, 64, "PAA segments")
        bounded_int(self.candidate_cap, 1, 4096, "candidate cap")
        bounded_int(self.max_results, 1, min(100, self.candidate_cap), "result count")
        bounded_int(self.dtw_radius, 0, 128, "DTW radius")
        bounded_int(self.horizon, 0, 512, "outcome horizon")
        bounded_int(self.exclusion_ns, 0, 10**18, "query exclusion")
        bounded_int(self.max_rows, 1, 50_000_000, "scan row cap")
        bounded_int(
            self.max_working_bytes, 1_048_576, 134_217_728, "working memory budget"
        )
        if (
            not np.isfinite(self.maximum_distance)
            or not 0 <= self.maximum_distance <= 1e100
        ):
            raise PatternError("Finite nonnegative match distance required")
        if not np.isfinite(self.cost_bps) or not 0 <= self.cost_bps <= 10_000:
            raise PatternError(
                "Costs must be a finite nonnegative basis-point deduction"
            )


@dataclass(frozen=True, slots=True, eq=False)
class SearchHit:
    window: PatternWindow
    distance: float
    outcome: ObservedOutcome | None

    def __post_init__(self) -> None:
        if not np.isfinite(self.distance) or self.distance < 0:
            raise PatternError("Hit distance must be finite and nonnegative")
        if (
            self.outcome
            and self.outcome.horizon_end_ns
            != self.window.end_ns + self.outcome.horizon * self.window.step_ns
        ):
            raise PatternError("Outcome horizon is inconsistent with window timing")

    @property
    def support_end_ns(self) -> int:
        return self.outcome.horizon_end_ns if self.outcome else self.window.end_ns


def deduplicate(
    hits: tuple[SearchHit, ...], *, limit: int = 100
) -> tuple[SearchHit, ...]:
    """Greedy best-first event support suppression across methods/timeframes.

    Overlap is grouped per instrument. Explicit nonempty event_group labels can
    additionally join cross-asset events. Unknown cross-asset dependence is never
    claimed absent; the resulting count is not a statistical effective sample size.
    """
    bounded_int(limit, 1, 4096, "deduplication limit")
    if len(hits) > 8192:
        raise PatternError("Deduplication requires a bounded candidate set")
    result: list[SearchHit] = []
    for hit in sorted(
        hits,
        key=lambda row: (
            row.distance,
            row.window.start_ns,
            row.window.provenance.instrument_id,
        ),
    ):
        if any(
            (
                hit.window.event_group
                and hit.window.event_group == prior.window.event_group
            )
            or (
                hit.window.provenance.instrument_id
                == prior.window.provenance.instrument_id
                and hit.window.start_ns < prior.support_end_ns
                and prior.window.start_ns < hit.support_end_ns
            )
            for prior in result
        ):
            continue
        result.append(hit)
        if len(result) == limit:
            break
    return tuple(result)


@dataclass(frozen=True, slots=True)
class SearchProgress:
    blocks: int
    rows: int
    windows_considered: int
    eligible_windows: int
    candidates_retained: int
    first_close_ns: int | None
    last_close_ns: int | None


@dataclass(frozen=True, slots=True, eq=False)
class SearchSnapshot:
    query: PatternWindow
    config: SearchConfig
    decision_ns: int
    candidates: tuple[tuple[float, int, SearchHit], ...]
    halo: CausalFrame | None
    progress: SearchProgress
    corpus: Provenance | None


@dataclass(frozen=True, slots=True, eq=False)
class SearchResult:
    method_id: str
    state: Literal["MATCHES", "UNKNOWN"]
    mode: str
    query: PatternWindow
    config: SearchConfig
    decision_ns: int
    hits: tuple[SearchHit, ...]
    progress: SearchProgress
    corpus: Provenance | None
    exact_reranks: int
    limitations: tuple[str, ...] = (
        "Shape distance is not a probability of profit.",
        "Deduplicated event count is not proven independent sample size.",
        "Corpus temporal/provenance declarations need the governed upstream validator.",
        "Costs are explicit mark-return deductions, not a complete execution simulation.",
    )


class SearchEngine:
    """One ordered instrument/timeframe stream. Caller owns checkpoint persistence.

    consume is an atomic block step: cancellation is checked before each block.
    A retained halo of length window+horizon-1 preserves partition-crossing
    windows. Snapshots contain data and parameters only, no live capability.
    """

    def __init__(
        self, query: PatternWindow, config: SearchConfig, decision_ns: int
    ) -> None:
        query.require_known(decision_ns)
        instant(decision_ns)
        if len(query.values) % config.paa_segments:
            raise PatternError(
                "Window length must divide into the configured PAA segments"
            )
        work = config.candidate_cap * len(query.values) * (2 * config.dtw_radius + 1)
        if config.metric == "DTW" and work > 2_000_000:
            raise PatternError(
                "Total exact DTW reranking budget exceeds 2,000,000 cells"
            )
        self.query, self.config, self.decision_ns = query, config, decision_ns
        self._query_values = normalize(query.values, config.normalization)
        self._query_paa = paa(self._query_values, config.paa_segments)
        self._heap: list[tuple[float, int, SearchHit]] = []
        self._halo: CausalFrame | None = None
        self._corpus: Provenance | None = None
        self._progress = SearchProgress(0, 0, 0, 0, 0, None, None)

    @classmethod
    def resume(cls, snapshot: SearchSnapshot) -> SearchEngine:
        engine = cls(snapshot.query, snapshot.config, snapshot.decision_ns)
        if len(snapshot.candidates) > snapshot.config.candidate_cap:
            raise PatternError("Checkpoint candidate limit exceeded")
        if snapshot.progress.candidates_retained != len(snapshot.candidates):
            raise PatternError("Checkpoint counters do not match candidates")
        progress = snapshot.progress
        if bool(progress.rows) != (snapshot.halo is not None) or (
            progress.rows
            and (
                snapshot.corpus is None
                or progress.first_close_ns is None
                or progress.last_close_ns is None
                or progress.first_close_ns > progress.last_close_ns
            )
        ):
            raise PatternError("Checkpoint coverage and halo are incomplete")
        if (
            not 0
            <= len(snapshot.candidates)
            <= progress.eligible_windows
            <= progress.windows_considered
            <= progress.rows
            <= snapshot.config.max_rows
        ):
            raise PatternError("Checkpoint scan counters are inconsistent")
        if (
            snapshot.config.mode == "EXACT_SMALL"
            and len(snapshot.candidates) != progress.eligible_windows
        ):
            raise PatternError("Exact checkpoint omitted an eligible candidate")
        if snapshot.halo is not None and (
            snapshot.halo.provenance != snapshot.corpus
            or snapshot.halo.step_ns != snapshot.query.step_ns
            or len(snapshot.halo.values)
            > len(snapshot.query.values) + snapshot.config.horizon - 1
            or int(snapshot.halo.close_ns[-1]) != progress.last_close_ns
        ):
            raise PatternError("Checkpoint halo does not bind its corpus/coverage")
        for score, serial, hit in snapshot.candidates:
            if (
                hit.window.provenance != snapshot.corpus
                or hit.window.values.shape != snapshot.query.values.shape
                or hit.window.step_ns != snapshot.query.step_ns
                or serial != -hit.window.start_ns - hit.window.step_ns
            ):
                raise PatternError(
                    "Checkpoint candidate identity/schema is inconsistent"
                )
            hit.window.require_known(snapshot.decision_ns)
            if (
                (snapshot.config.horizon == 0 and hit.outcome is not None)
                or (snapshot.config.horizon > 0 and hit.outcome is None)
                or (
                    hit.outcome is not None
                    and (
                        hit.outcome.horizon != snapshot.config.horizon
                        or hit.outcome.cost_bps != snapshot.config.cost_bps
                    )
                )
            ):
                raise PatternError(
                    "Checkpoint outcome differs from frozen configuration"
                )
            if (
                hit.window.end_ns
                >= snapshot.query.start_ns - snapshot.config.exclusion_ns
                or hit.support_end_ns
                > snapshot.query.start_ns - snapshot.config.exclusion_ns
                or (hit.outcome and hit.outcome.available_ns > snapshot.decision_ns)
            ):
                raise PatternError(
                    "Checkpoint candidate violates historical availability"
                )
            expected = float(
                np.mean(
                    (
                        paa(
                            normalize(hit.window.values, snapshot.config.normalization),
                            snapshot.config.paa_segments,
                        )
                        - engine._query_paa
                    )
                    ** 2
                )
            )
            if (
                not np.isfinite(score)
                or score > 0
                or not np.isclose(-score, expected, rtol=1e-12, atol=1e-15)
            ):
                raise PatternError("Checkpoint candidate score does not reproduce")
        engine._heap = list(snapshot.candidates)
        from heapq import heapify

        heapify(engine._heap)
        engine._halo, engine._progress, engine._corpus = (
            snapshot.halo,
            snapshot.progress,
            snapshot.corpus,
        )
        return engine

    def snapshot(self) -> SearchSnapshot:
        return SearchSnapshot(
            self.query,
            self.config,
            self.decision_ns,
            tuple(self._heap),
            self._halo,
            self._progress,
            self._corpus,
        )

    def consume(
        self, block: CausalFrame, *, cancelled: Callable[[], bool] | None = None
    ) -> SearchProgress:
        if cancelled and cancelled():
            raise SearchCancelledError(
                "Search cancelled before consuming the next block"
            )
        config = self.config
        if self._progress.rows + len(block.values) > config.max_rows:
            raise PatternError(
                "Corpus row budget exceeded; last completed snapshot is retained"
            )
        if (
            block.step_ns != self.query.step_ns
            or block.provenance.features != self.query.provenance.features
        ):
            raise PatternError(
                "Search requires an explicitly aligned feature/time grid"
            )
        if self._corpus is not None and block.provenance != self._corpus:
            raise PatternError(
                "A stream cannot silently change corpus/version/instrument"
            )
        if (
            self._progress.last_close_ns is not None
            and int(block.close_ns[0]) <= self._progress.last_close_ns
        ):
            raise PatternError(
                "Blocks must be strictly ordered without duplicated rows"
            )
        span = len(self.query.values) + config.horizon
        if self._halo is None:
            values, closes, available = block.values, block.close_ns, block.available_ns
        else:
            values = np.concatenate((self._halo.values, block.values))
            closes = np.concatenate((self._halo.close_ns, block.close_ns))
            available = np.concatenate((self._halo.available_ns, block.available_ns))
        heap = list(self._heap)  # Commit only after a complete successful block.
        considered = max(0, len(values) - span + 1)
        eligible_count = 0
        length = len(self.query.values)
        batch_size = max(
            1, min(4096, config.max_working_bytes // (span * values.shape[1] * 8 * 8))
        )
        if considered:
            all_windows = np.lib.stride_tricks.sliding_window_view(values, span, axis=0)
            all_availability = np.lib.stride_tricks.sliding_window_view(available, span)
            gaps = np.r_[0, np.cumsum(np.diff(closes) != block.step_ns)]
            for begin in range(0, considered, batch_size):
                stop = min(considered, begin + batch_size)
                indices = np.arange(begin, stop)
                eligible = (
                    (
                        closes[indices + length - 1]
                        < self.query.start_ns - config.exclusion_ns
                    )
                    & (
                        closes[indices + span - 1]
                        <= self.query.start_ns - config.exclusion_ns
                    )
                    & (all_availability[begin:stop].max(axis=1) <= self.decision_ns)
                    & (gaps[indices + span - 1] == gaps[indices])
                )
                indices = indices[eligible]
                eligible_count += len(indices)
                if (
                    config.mode == "EXACT_SMALL"
                    and self._progress.eligible_windows + eligible_count
                    > config.candidate_cap
                ):
                    raise PatternError(
                        "EXACT_SMALL candidate cap exceeded; no approximate claim substituted"
                    )
                if not len(indices):
                    continue
                raw = np.moveaxis(all_windows[indices, :, :length], -1, 1)
                # The common scalable modes avoid a Python loop per corpus window.
                if config.normalization == "Z_WINDOW":
                    std = raw.std(axis=1, keepdims=True)
                    normalized = np.divide(
                        raw - raw.mean(axis=1, keepdims=True),
                        std,
                        out=np.zeros_like(raw),
                        where=std > 1e-12,
                    )
                elif config.normalization == "RAW":
                    normalized = raw
                elif config.normalization == "BASE100":
                    if np.any(raw <= 0):
                        raise PatternError(
                            "Price representations require positive observations"
                        )
                    normalized = 100 * raw / raw[:, :1]
                else:
                    normalized = np.stack(
                        [normalize(row, config.normalization) for row in raw]
                    )
                compressed = normalized.reshape(
                    len(raw),
                    config.paa_segments,
                    length // config.paa_segments,
                    values.shape[1],
                ).mean(axis=2)
                scores = np.mean((compressed - self._query_paa) ** 2, axis=(1, 2))
                for local in np.argsort(scores, kind="stable")[: config.candidate_cap]:
                    index = int(indices[local])
                    serial = int(closes[index])
                    score = float(scores[local])
                    if len(heap) >= config.candidate_cap and (score, serial) >= (
                        -heap[0][0],
                        -heap[0][1],
                    ):
                        continue
                    window = PatternWindow(
                        values[index : index + length],
                        serial - block.step_ns,
                        int(closes[index + length - 1]),
                        int(available[index : index + length].max()),
                        block.step_ns,
                        block.provenance,
                    )
                    outcome = None
                    if config.horizon:
                        # First feature must explicitly be a positive close mark.
                        if block.provenance.features[0] != "close":
                            raise PatternError(
                                "Outcome horizon requires close as the first feature"
                            )
                        prices = values[index + length - 1 : index + span, 0]
                        if np.any(prices <= 0):
                            raise PatternError(
                                "Observed returns require positive close marks"
                            )
                        returns = prices[1:] / prices[0] - 1
                        outcome = ObservedOutcome(
                            config.horizon,
                            int(closes[index + span - 1]),
                            int(available[index + length - 1 : index + span].max()),
                            float(returns[-1]),
                            float(max(0, returns.max())),
                            float(min(0, returns.min())),
                            config.cost_bps,
                        )
                    hit = SearchHit(window, score, outcome)
                    item = (-score, -serial, hit)
                    if len(heap) < config.candidate_cap:
                        heappush(heap, item)
                    else:
                        heapreplace(heap, item)
        halo_length = min(span - 1, len(values))
        halo = CausalFrame(
            values[-halo_length:],
            closes[-halo_length:],
            available[-halo_length:],
            block.step_ns,
            block.provenance,
        )
        self._heap, self._halo, self._corpus = heap, halo, block.provenance
        self._progress = SearchProgress(
            self._progress.blocks + 1,
            self._progress.rows + len(block.values),
            self._progress.windows_considered + considered,
            self._progress.eligible_windows + eligible_count,
            len(heap),
            self._progress.first_close_ns or int(block.close_ns[0]),
            int(block.close_ns[-1]),
        )
        return self._progress

    def finish(self, *, cancelled: Callable[[], bool] | None = None) -> SearchResult:
        exact: list[SearchHit] = []
        for _, _, hit in self._heap:
            if cancelled and cancelled():
                raise SearchCancelledError(
                    "Cancelled during bounded reranking; scan checkpoint unchanged"
                )
            transformed = normalize(hit.window.values, self.config.normalization)
            distance = (
                euclidean(self._query_values, transformed)
                if self.config.metric == "EUCLIDEAN"
                else constrained_dtw(
                    self._query_values, transformed, radius=self.config.dtw_radius
                )
            )
            if distance <= self.config.maximum_distance:
                exact.append(SearchHit(hit.window, distance, hit.outcome))
        hits = deduplicate(tuple(exact), limit=self.config.max_results)
        return SearchResult(
            "PAT-13",
            "MATCHES" if hits else "UNKNOWN",
            self.config.mode,
            self.query,
            self.config,
            self.decision_ns,
            hits,
            self._progress,
            self._corpus,
            len(self._heap),
        )


def search_blocks(
    blocks: Iterable[CausalFrame],
    query: PatternWindow,
    config: SearchConfig,
    *,
    decision_ns: int,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[SearchProgress], None] | None = None,
) -> SearchResult:
    engine = SearchEngine(query, config, decision_ns)
    for block in blocks:
        update = engine.consume(block, cancelled=cancelled)
        if progress:
            progress(update)
    return engine.finish(cancelled=cancelled)
