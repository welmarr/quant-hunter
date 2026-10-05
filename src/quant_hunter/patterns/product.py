"""Registered-job adapter over real immutable corpora and the classical methods.

Item 8 remains the sole freeze/attempt/terminal authority. The host authenticates,
checks corpus ownership, registers IDs and freezes this exact prepared digest
before execute_registered(). This adapter cannot promote a research object.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, is_dataclass
from itertools import pairwise
from typing import Any, Literal, cast

import numpy as np

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.config.canonical import parse_json_document
from quant_hunter.identity import RegistryKind, validate_typed_id
from quant_hunter.patterns.catalog import METHODS
from quant_hunter.patterns.codec import (
    checkpoint_disk_bytes,
    load_checkpoint,
    save_checkpoint,
)
from quant_hunter.patterns.contracts import (
    CausalFrame,
    FitContext,
    PatternError,
    PatternWindow,
    SearchCancelledError,
    TrainingLabel,
    bounded_int,
    instant,
)
from quant_hunter.patterns.corpus import Corpus, CorpusStore, Progress
from quant_hunter.patterns.diagnostics import (
    align_asof,
    compare_dtw,
    fit_cusum,
    geometry,
    motif_profile,
    recurrence,
    spectra_haar,
)
from quant_hunter.patterns.learned import (
    ClassicalRepresentation,
    fit_clusters,
    fit_hmm,
    fit_sax,
    fit_shapelet,
    representation_comparison,
)
from quant_hunter.patterns.outcomes import outcome_summary
from quant_hunter.patterns.representations import Normalization, normalize
from quant_hunter.patterns.search import (
    ObservedOutcome,
    SearchConfig,
    SearchEngine,
    SearchHit,
    SearchResult,
    deduplicate,
)
from quant_hunter.patterns.validation import block_permutation_test, stability_and_costs
from quant_hunter.provenance.hashing import require_sha256_digest

MAX_PREPARED_BYTES = 2 * 1024 * 1024


def _plain(value: object) -> JsonValue:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _plain(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, np.generic):
        return _plain(value.item())
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    if value is None or type(value) in {str, bool, int, float}:
        return cast(JsonValue, value)
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _plain(item) for key, item in value.items()}
    raise PatternError("PATTERN_RESULT_TYPE")


@dataclass(frozen=True, slots=True)
class PatternJobConfig:
    family: str
    query_start: int
    query_stop: int
    train_start: int
    train_stop: int
    decision_ns: int
    train_cutoff_ns: int
    candidate_cutoff_ns: int
    purge_ns: int = 0
    normalization: Normalization = "Z_WINDOW"
    mode: Literal["EXACT_SMALL", "APPROXIMATE"] = "APPROXIMATE"
    metric: Literal["EUCLIDEAN", "DTW"] = "EUCLIDEAN"
    horizon: int = 4
    cost_bps: float = 7
    maximum_distance: float = 1
    candidate_cap: int = 256
    max_results: int = 20
    paa_segments: int = 8
    dtw_radius: int = 4
    train_window_cap: int = 32
    seed: int = 0
    method_parameters_json: str = "{}"
    secondary_manifest: str | None = None
    max_checkpoint_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.family not in {method.family for method in METHODS}:
            raise PatternError("PATTERN_FAMILY_UNKNOWN")
        bounded_int(self.query_start, 0, 50_000_000, "query start")
        bounded_int(
            self.query_stop, self.query_start + 8, self.query_start + 256, "query stop"
        )
        bounded_int(self.train_start, 0, self.query_start, "train start")
        bounded_int(
            self.train_stop,
            self.train_start + 8,
            min(self.train_start + 4096, self.query_start),
            "train stop",
        )
        for value in (self.decision_ns, self.train_cutoff_ns, self.candidate_cutoff_ns):
            instant(value)
        bounded_int(self.purge_ns, 0, 10**18, "training purge")
        bounded_int(self.horizon, 1, 256, "outcome horizon")
        bounded_int(self.candidate_cap, 1, 256, "product candidate pool")
        bounded_int(
            self.max_results, 1, min(40, self.candidate_cap), "overlay result count"
        )
        bounded_int(self.train_window_cap, 4, 64, "training window cap")
        bounded_int(self.seed, 0, 2**32 - 1, "seed")
        bounded_int(
            self.max_checkpoint_bytes,
            4096,
            1024 * 1024 * 1024,
            "query checkpoint disk bytes",
        )
        if len(self.method_parameters_json) > 4096:
            raise PatternError("METHOD_PARAMETER_BYTES")
        if self.secondary_manifest is not None:
            require_sha256_digest(self.secondary_manifest)
        _parameters(self)

    def to_record(self) -> JsonRecord:
        return cast(JsonRecord, _plain(self))


# Every method has a closed numerical parameter set. Defaults are expanded into
# the prepared record before freeze, so no change hides an extra search variant.
_PARAMETERS: dict[str, dict[str, tuple[int | float, int | float, int | float]]] = {
    "PAT-01": {"stride": (8, 1, 256)},
    "PAT-02": {},
    "PAT-03": {"length": (8, 2, 64), "candidate_cap": (32, 1, 128)},
    "PAT-04": {"alphabet": (4, 2, 16)},
    "PAT-05": {
        "allowance": (0.5, 0.0, 10.0),
        "threshold": (5.0, 0.01, 100.0),
        "scale_floor": (0.000001, 0.000000000001, 1.0),
    },
    "PAT-06": {
        "states": (2, 2, 4),
        "iterations": (12, 1, 30),
        "variance_floor": (0.000001, 0.000000000001, 1.0),
    },
    "PAT-07": {},
    "PAT-08": {
        "radius": (0.5, 0.000001, 100.0),
        "theiler": (1, 0, 254),
        "minimum_line": (2, 2, 256),
    },
    "PAT-09": {"clusters": (2, 1, 8), "radius_factor": (1.25, 1.0, 5.0)},
    "PAT-10": {
        "breakout_fraction": (0.001, 0.0, 0.5),
        "channel_tolerance": (0.01, 0.000001, 0.5),
    },
    "PAT-11": {"maximum_staleness_ns": (0, 0, 86_400_000_000_000)},
    "PAT-12": {
        "minimum_events": (10, 2, 100),
        "resamples": (100, 20, 1000),
        "block_length": (2, 1, 40),
    },
    "PAT-13": {},
    "PAT-14": {
        "periods": (4, 2, 10),
        "permutations": (99, 19, 1000),
        "block_length": (2, 1, 20),
    },
    "PAT-15": {},
}


def _parameters(config: PatternJobConfig) -> dict[str, int | float]:
    supplied = parse_json_document(config.method_parameters_json)
    rules = _PARAMETERS[config.family]
    if not isinstance(supplied, dict) or set(supplied) - set(rules):
        raise PatternError("METHOD_PARAMETERS_UNKNOWN")
    result: dict[str, int | float] = {}
    for key, (default, low, high) in rules.items():
        value = supplied.get(key, default)
        if (
            type(value) not in {int, float}
            or (type(default) is int and type(value) is not int)
            or not np.isfinite(cast(float, value))
            or not low <= cast(float, value) <= high
        ):
            raise PatternError("METHOD_PARAMETER_RANGE")
        result[key] = cast(int | float, value)
    return result


def _summary_parameters(config: PatternJobConfig) -> dict[str, int]:
    if config.family == "PAT-12":
        values = _parameters(config)
        return {
            name: int(values[name])
            for name in ("minimum_events", "resamples", "block_length")
        }
    return {"minimum_events": 10, "resamples": 200, "block_length": 2}


@dataclass(frozen=True, slots=True)
class PreparedPatternJob:
    digest: str
    record_json: str

    def to_record(self) -> JsonRecord:
        return cast(JsonRecord, parse_json_document(self.record_json))


@dataclass(frozen=True, slots=True)
class FrozenPatternBinding:
    """Exact canonical Item8 identities verified by the host, not by this type."""

    experiment_id: str
    experiment_record_digest: str
    configuration_digest: str
    prepared_digest: str
    pattern_id: str

    def __post_init__(self) -> None:
        validate_typed_id(self.experiment_id, RegistryKind.EXPERIMENT)
        validate_typed_id(self.pattern_id, RegistryKind.PATTERN)
        for digest in (
            self.experiment_record_digest,
            self.configuration_digest,
            self.prepared_digest,
        ):
            require_sha256_digest(digest)

    def to_record(self) -> JsonRecord:
        return cast(JsonRecord, asdict(self))


class PatternJobCancelledError(SearchCancelledError):
    def __init__(self, checkpoint_digest: str | None) -> None:
        self.checkpoint_digest = checkpoint_digest
        super().__init__("PATTERN_CANCELLED_COMPLETED_CHECKPOINT_RETAINED")


class PatternProduct:
    def __init__(self, corpora: CorpusStore) -> None:
        self.corpora = corpora

    def prepare(
        self,
        corpus_manifest: str,
        config: PatternJobConfig,
        *,
        pattern_id: str,
        code_revision: str,
        environment_digest: str,
    ) -> PreparedPatternJob:
        """Validate/freeze description only; no fit, search, outcome test or score."""
        record = self._describe(
            corpus_manifest,
            config,
            pattern_id=pattern_id,
            code_revision=code_revision,
            environment_digest=environment_digest,
        )
        raw = canonicalize_json(record)
        if len(raw) > MAX_PREPARED_BYTES:
            raise PatternError("PATTERN_PREPARED_BYTE_LIMIT")
        return PreparedPatternJob(
            self.corpora.objects.publish(raw).digest, raw.decode()
        )

    def _describe(
        self,
        corpus_manifest: str,
        config: PatternJobConfig,
        *,
        pattern_id: str,
        code_revision: str,
        environment_digest: str,
    ) -> JsonRecord:
        """Pure repeatable description; execution rebinds every redundant field."""
        validate_typed_id(pattern_id, RegistryKind.PATTERN)
        require_sha256_digest(environment_digest)
        if len(code_revision) != 40 or any(
            c not in "0123456789abcdef" for c in code_revision
        ):
            raise PatternError("PATTERN_CODE_REVISION")
        config.__post_init__()
        corpus = self.corpora.load(corpus_manifest)
        if config.query_stop > corpus.row_count:
            raise PatternError("PATTERN_QUERY_OUTSIDE_CORPUS")
        query = self.corpora.window(
            corpus, config.query_start, config.query_stop, config.decision_ns
        )
        context = FitContext(config.train_cutoff_ns, query.start_ns, config.purge_ns)
        train = self.corpora.frame(corpus, config.train_start, config.train_stop)
        if (
            int(train.close_ns[-1]) > context.train_cutoff_ns
            or int(train.available_ns.max()) > context.train_cutoff_ns
        ):
            raise PatternError("PATTERN_TRAIN_NOT_KNOWN")
        if config.candidate_cutoff_ns > query.start_ns:
            raise PatternError("PATTERN_CANDIDATE_CUTOFF_AFTER_QUERY")
        if config.family == "PAT-02" and config.metric != "DTW":
            raise PatternError("PAT02_REQUIRES_DTW_METRIC")
        if config.family == "PAT-11" and config.secondary_manifest is None:
            raise PatternError("PAT11_REQUIRES_SECOND_OWNED_CORPUS")
        secondary = None
        if config.secondary_manifest is not None:
            secondary = self.corpora.load(config.secondary_manifest)
            if (
                config.family != "PAT-11"
                or secondary.provenance.instrument_id == corpus.provenance.instrument_id
            ):
                raise PatternError("PAT11_DISTINCT_INSTRUMENT_REQUIRED")
            staleness = int(_parameters(config)["maximum_staleness_ns"])
            self.corpora.time_frame(
                secondary, query.start_ns + query.step_ns - staleness, query.end_ns
            )
        search = self._search_config(config, query, corpus)
        SearchEngine(
            query, search, config.decision_ns
        )  # Parameter/resource validation, no scan.
        length = config.query_stop - config.query_start
        training_stride = (
            length
            + config.horizon
            + (config.purge_ns + query.step_ns - 1) // query.step_ns
        )
        planned_training = max(
            0,
            (config.train_stop - config.train_start - length - config.horizon)
            // training_stride
            + 1,
        )
        parameters = _parameters(config)
        record: JsonRecord = {
            "format": "qh-registered-pattern-job-v1",
            "pattern_id": pattern_id,
            "corpus_manifest": corpus_manifest,
            "secondary_manifest": secondary.manifest_digest if secondary else None,
            "selected_snapshot": corpus.selected,
            "configuration": config.to_record(),
            "parent_snapshots": corpus.parents,
            "selection_manifest_digest": corpus.selection_manifest_digest,
            "calendar_profile_digest": corpus.calendar_profile_digest,
            "secondary_parent_snapshots": secondary.parents if secondary else [],
            "expanded_method_parameters": cast(JsonRecord, parameters),
            "outcome_summary_parameters": cast(JsonRecord, _summary_parameters(config)),
            "query_fingerprint": query.fingerprint,
            "code_revision": code_revision,
            "environment_digest": environment_digest,
            "evidence_mode": "SYNTHETIC",
            "planned_scope": {
                "variant_count": 1,
                "variants": [config.to_record()],
                "corpus_rows": corpus.row_count,
                "partition_count": len(corpus.partitions),
                "maximum_considered_windows": max(
                    0, corpus.row_count - length - config.horizon + 1
                ),
                "training_row_start": config.train_start,
                "training_row_stop": config.train_stop,
                "training_stride_rows": training_stride,
                "training_windows_enumerated": planned_training,
                "training_windows_cap": config.train_window_cap,
                "candidate_pool_cap": config.candidate_cap,
                "exact_rerank_cap": config.candidate_cap,
                "shapelet_subsequence_cap": parameters.get("candidate_cap")
                if config.family == "PAT-03"
                else 0,
                "selection_policy": "FIRST_CHRONOLOGICAL_VALID_TRAIN_WINDOWS;QUERY_PAA_POOL_THEN_EXACT",
                "outcome_availability_cutoff_ns": str(config.decision_ns),
                "candidate_support_cutoff_ns": str(config.candidate_cutoff_ns),
                "no_per_occurrence_strategy_ids": True,
            },
            "scientific_authority": "ITEM8_EXTERNAL;NO_EMPIRICAL_OR_HOST_PASS",
        }
        return record

    @staticmethod
    def _search_config(
        config: PatternJobConfig, query: PatternWindow, corpus: Corpus
    ) -> SearchConfig:
        return SearchConfig(
            mode=config.mode,
            normalization=config.normalization,
            metric=config.metric,
            paa_segments=config.paa_segments,
            candidate_cap=config.candidate_cap,
            max_results=config.max_results,
            dtw_radius=config.dtw_radius,
            horizon=config.horizon,
            cost_bps=config.cost_bps,
            maximum_distance=config.maximum_distance,
            exclusion_ns=query.start_ns - config.candidate_cutoff_ns,
            max_rows=corpus.row_count,
            max_working_bytes=16 * 1024 * 1024,
        )

    def execute_registered(
        self,
        prepared_digest: str,
        *,
        binding: FrozenPatternBinding,
        resume_digest: str | None = None,
        progress: Progress | None = None,
        cancelled: Callable[[], bool] | None = None,
        checkpoint: Callable[[str], None] | None = None,
    ) -> JsonRecord:
        """Host verifies the frozen definition and its owned RUNNING Item8 attempt."""
        binding.__post_init__()
        if binding.prepared_digest != prepared_digest:
            raise PatternError("PATTERN_FROZEN_CONFIG_BINDING")
        raw = self.corpora.objects.read_bytes(prepared_digest)
        if len(raw) > MAX_PREPARED_BYTES:
            raise PatternError("PATTERN_PREPARED_BYTE_LIMIT")
        plan = cast(dict[str, Any], parse_json_document(raw))
        if (
            plan["format"] != "qh-registered-pattern-job-v1"
            or plan["pattern_id"] != binding.pattern_id
        ):
            raise PatternError("PATTERN_REGISTERED_ID_BINDING")
        values = dict(plan["configuration"])
        for key in (
            "decision_ns",
            "train_cutoff_ns",
            "candidate_cutoff_ns",
            "purge_ns",
        ):
            values[key] = int(values[key])
        config = PatternJobConfig(**values)
        expected_plan = self._describe(
            plan["corpus_manifest"],
            config,
            pattern_id=binding.pattern_id,
            code_revision=plan["code_revision"],
            environment_digest=plan["environment_digest"],
        )
        if canonicalize_json(expected_plan) != raw:
            raise PatternError("PATTERN_PREPARED_DESCRIPTION_BINDING")
        corpus = self.corpora.load(plan["corpus_manifest"])
        query = self.corpora.window(
            corpus, config.query_start, config.query_stop, config.decision_ns
        )
        if query.fingerprint != plan["query_fingerprint"] or canonicalize_json(
            corpus.selected
        ) != canonicalize_json(plan["selected_snapshot"]):
            raise PatternError("PATTERN_CORPUS_QUERY_BINDING")
        checkpoint_binding: JsonRecord = {
            "canonical_binding": binding.to_record(),
            "corpus_manifest": corpus.manifest_digest,
            "seed": config.seed,
            "partitions": [part.digest for part in corpus.partitions],
        }
        next_partition = 0
        engine = SearchEngine(
            query, self._search_config(config, query, corpus), config.decision_ns
        )
        if resume_digest is not None:
            engine, next_partition = load_checkpoint(
                self.corpora.objects, resume_digest, checkpoint_binding
            )
            if (
                engine.query.fingerprint != query.fingerprint
                or engine.config != self._search_config(config, query, corpus)
                or engine.decision_ns != config.decision_ns
                or not 0 <= next_partition <= len(corpus.partitions)
                or engine.snapshot().progress.rows
                != sum(part.rows for part in corpus.partitions[:next_partition])
            ):
                raise PatternError("PATTERN_RESUME_COVERAGE")
            self._verify_resume_source(corpus, engine)
        latest = resume_digest
        checkpoint_bytes = (
            checkpoint_disk_bytes(
                self.corpora.objects,
                resume_digest,
                checkpoint_binding,
                limit=config.max_checkpoint_bytes,
            )
            if resume_digest
            else 0
        )
        try:
            for index in range(next_partition, len(corpus.partitions)):
                if cancelled and cancelled():
                    raise PatternJobCancelledError(latest)
                result = engine.consume(
                    self.corpora.partition(corpus, index), cancelled=cancelled
                )
                previous = latest
                latest = save_checkpoint(
                    self.corpora.objects,
                    engine.snapshot(),
                    checkpoint_binding,
                    next_partition=index + 1,
                    previous_digest=previous,
                    previous_total_bytes=checkpoint_bytes,
                    remaining_bytes=config.max_checkpoint_bytes - checkpoint_bytes,
                )
                checkpoint_bytes += self.corpora.objects.get(latest).byte_size
                if checkpoint:
                    checkpoint(latest)
                if progress:
                    progress(
                        {
                            "stage": "PATTERN_SEARCH",
                            "rows": result.rows,
                            "partitions": result.blocks,
                            "eligible_windows": result.eligible_windows,
                            "candidates": result.candidates_retained,
                            "checkpoint_digest": latest,
                            "checkpoint_bytes": checkpoint_bytes,
                        }
                    )
            search = engine.finish(cancelled=cancelled)
        except SearchCancelledError:
            raise PatternJobCancelledError(latest) from None
        if cancelled and cancelled():
            raise PatternJobCancelledError(latest)
        method, method_exposure = self._method(config, corpus, query, search, engine)
        summary_parameters = _summary_parameters(config)
        summary = (
            outcome_summary(
                search.hits,
                decision_ns=config.decision_ns,
                seed=config.seed,
                **summary_parameters,
            )
            if len(search.hits) >= 2 * summary_parameters["block_length"]
            else {
                "method_id": "PAT-12",
                "state": "INSUFFICIENT",
                "event_count": len(search.hits),
                "mean_net_return": None,
                "mean_interval": None,
                "reason": "Need at least two complete fixed bootstrap blocks",
                "bootstrap": summary_parameters,
            }
        )
        outcomes = [hit.outcome.net_return for hit in search.hits if hit.outcome]
        histogram: JsonRecord = {"counts": [], "edges": []}
        if outcomes:
            counts, edges = np.histogram(outcomes, bins=min(10, max(1, len(outcomes))))
            histogram = {"counts": _plain(counts), "edges": _plain(edges)}
        record: JsonRecord = {
            "method_id": config.family,
            "pattern_id": binding.pattern_id,
            "experiment_id": binding.experiment_id,
            "canonical_binding": binding.to_record(),
            "prepared_digest": prepared_digest,
            "corpus_manifest": corpus.manifest_digest,
            "dataset_id": corpus.dataset_id,
            "selected_snapshot": corpus.selected,
            "parent_snapshots": corpus.parents,
            "selection_manifest_digest": corpus.selection_manifest_digest,
            "calendar_profile_digest": corpus.calendar_profile_digest,
            "secondary_parent_snapshots": cast(
                JsonValue, plan["secondary_parent_snapshots"]
            ),
            "configuration": config.to_record(),
            "method_parameters": _plain(_parameters(config)),
            "evidence_mode": "SYNTHETIC",
            "empirical_validation": "MISSING",
            "state": search.state,
            "method": method,
            "outcomes": _plain(summary),
            "query": _overlay(query, config.normalization),
            "occurrences": [_hit(hit, config.normalization) for hit in search.hits],
            "negative_cases": [
                _hit(hit, config.normalization)
                for hit in search.hits
                if hit.outcome and hit.outcome.net_return <= 0
            ],
            "outcome_histogram": histogram,
            "exposure": {
                **cast(JsonRecord, plan["planned_scope"]),
                "rows_visited": search.progress.rows,
                "windows_considered": search.progress.windows_considered,
                "eligible_windows": search.progress.eligible_windows,
                "excluded_windows": search.progress.windows_considered
                - search.progress.eligible_windows,
                "candidate_pool_selected": search.progress.candidates_retained,
                "exact_reranks": search.exact_reranks,
                "deduplicated_events": len(search.hits),
                "method_internal": method_exposure,
            },
            "checkpoint_digest": latest,
            "query_checkpoint_bytes": checkpoint_bytes,
            "maximum_known_ns": str(config.decision_ns),
            "search_mode": config.mode,
            "reusable_parquet_bytes": corpus.parquet_bytes,
            "limitations": [
                *search.limitations,
                "Synthetic software evidence only; no prediction or future-profit probability.",
                "Partition index is exact row/time lookup; query PAA filtering is approximate unless EXACT_SMALL.",
                "Deduplicated events are not a measured independent effective sample size.",
                "Item8 and complete cross-experiment FDR remain governed host responsibilities.",
            ],
        }
        canonicalize_json(
            record
        )  # Reject nonfinite/unrepresentable outputs before host publication.
        return record

    def _verify_resume_source(self, corpus: Corpus, engine: SearchEngine) -> None:
        """Recheck bounded retained candidates/halo against immutable source bytes.

        This is source consistency, not a replay of the historical candidate scan.
        Root still requires its exact registered checkpoint digest/attempt binding.
        """
        snapshot = engine.snapshot()
        rows = snapshot.progress.rows
        span = len(snapshot.query.values) + snapshot.config.horizon
        if not rows:
            return
        if (
            snapshot.corpus != corpus.provenance
            or snapshot.progress.first_close_ns != corpus.partitions[0].first_close_ns
            or snapshot.progress.windows_considered != max(0, rows - span + 1)
        ):
            raise PatternError("PATTERN_RESUME_SOURCE_COVERAGE")
        expected_halo = self.corpora.frame(corpus, max(0, rows - span + 1), rows)
        halo = snapshot.halo
        if halo is None or any(
            not np.array_equal(getattr(halo, name), getattr(expected_halo, name))
            for name in ("values", "close_ns", "available_ns")
        ):
            raise PatternError("PATTERN_RESUME_SOURCE_HALO")
        for _, _, hit in snapshot.candidates:
            if hit.support_end_ns > int(expected_halo.close_ns[-1]):
                raise PatternError("PATTERN_RESUME_SOURCE_CANDIDATE_COVERAGE")
            source = self.corpora.time_frame(
                corpus,
                hit.window.start_ns + hit.window.step_ns,
                hit.support_end_ns,
            )
            if len(source.values) != span:
                raise PatternError("PATTERN_RESUME_SOURCE_CANDIDATE_SPAN")
            source.window(0, span, decision_ns=snapshot.decision_ns)
            window = source.window(
                0, len(hit.window.values), decision_ns=snapshot.decision_ns
            )
            if window.fingerprint != hit.window.fingerprint:
                raise PatternError("PATTERN_RESUME_SOURCE_CANDIDATE_VALUES")
            prices = source.values[len(hit.window.values) - 1 :, 0]
            returns = prices[1:] / prices[0] - 1
            expected_outcome = ObservedOutcome(
                snapshot.config.horizon,
                int(source.close_ns[-1]),
                int(source.available_ns[len(hit.window.values) - 1 :].max()),
                float(returns[-1]),
                float(max(0, returns.max())),
                float(min(0, returns.min())),
                snapshot.config.cost_bps,
            )
            if hit.outcome != expected_outcome:
                raise PatternError("PATTERN_RESUME_SOURCE_OUTCOME")

    def _training(
        self, config: PatternJobConfig, corpus: Corpus, query: PatternWindow
    ) -> tuple[
        CausalFrame, tuple[PatternWindow, ...], tuple[TrainingLabel, ...], JsonRecord
    ]:
        frame = self.corpora.frame(corpus, config.train_start, config.train_stop)
        context = FitContext(config.train_cutoff_ns, query.start_ns, config.purge_ns)
        length = len(query.values)
        stride = (
            length
            + config.horizon
            + (config.purge_ns + query.step_ns - 1) // query.step_ns
        )
        windows: list[PatternWindow] = []
        labels: list[TrainingLabel] = []
        visited = excluded = truncated = 0
        for start in range(0, len(frame.values) - length - config.horizon + 1, stride):
            visited += 1
            if len(windows) >= config.train_window_cap:
                truncated += 1
                continue
            try:
                window = frame.window(
                    start, start + length, decision_ns=context.train_cutoff_ns
                )
                full = frame.window(
                    start,
                    start + length + config.horizon,
                    decision_ns=context.train_cutoff_ns,
                )
                value = int(
                    frame.values[start + length + config.horizon - 1, 0]
                    > frame.values[start + length - 1, 0]
                )
                label = TrainingLabel(value, full.end_ns, full.available_ns)
                label.validate(window, context)
            except PatternError:
                excluded += 1
                continue
            windows.append(window)
            labels.append(label)
        return (
            frame,
            tuple(windows),
            tuple(labels),
            {
                "enumerated": visited,
                "selected": len(windows),
                "excluded": excluded,
                "truncated_by_cap": truncated,
            },
        )

    def _method(
        self,
        config: PatternJobConfig,
        corpus: Corpus,
        query: PatternWindow,
        search: SearchResult,
        engine: SearchEngine,
    ) -> tuple[JsonRecord, JsonRecord]:
        context = FitContext(config.train_cutoff_ns, query.start_ns, config.purge_ns)
        parameters = _parameters(config)
        exposure: JsonRecord = {"fits": 0, "family": config.family}
        try:
            train, windows, labels, training_exposure = self._training(
                config, corpus, query
            )
            exposure["training_window_scope"] = training_exposure
            family = config.family
            result: object
            if family == "PAT-01":
                result = motif_profile(
                    train,
                    context,
                    length=len(query.values),
                    stride=int(parameters["stride"]),
                    max_windows=256,
                )
            elif family == "PAT-02":
                result = {
                    "comparisons": [
                        compare_dtw(
                            query,
                            hit.window,
                            decision_ns=config.decision_ns,
                            radius=config.dtw_radius,
                        )
                        for hit in search.hits
                    ],
                    "state": search.state,
                }
            elif family == "PAT-03":
                exposure["fits"] = 1
                model = fit_shapelet(
                    windows,
                    labels,
                    context,
                    length=int(parameters["length"]),
                    candidate_cap=int(parameters["candidate_cap"]),
                )
                exposure["shapelet_candidates_scored"] = model.candidates_searched
                result = {
                    "model": model,
                    "prediction": model.predict(query, decision_ns=config.decision_ns),
                    "prediction_limit": "Train-label classification, no calibrated probability",
                }
            elif family == "PAT-04":
                exposure["fits"] = 1
                sax = fit_sax(
                    windows,
                    context,
                    segments=config.paa_segments,
                    alphabet=int(parameters["alphabet"]),
                )
                result = {
                    "model": sax,
                    "query_word_and_state": sax.transform(
                        query, decision_ns=config.decision_ns
                    ),
                }
            elif family == "PAT-05":
                exposure["fits"] = 1
                cusum = fit_cusum(train, context, **parameters)
                result = {
                    "model": cusum,
                    "detection": cusum.detect(query, decision_ns=config.decision_ns),
                }
            elif family == "PAT-06":
                exposure["fits"] = 1
                hmm = fit_hmm(
                    train,
                    context,
                    states=int(parameters["states"]),
                    iterations=int(parameters["iterations"]),
                    variance_floor=float(parameters["variance_floor"]),
                )
                result = {
                    "model": hmm,
                    "forward_probabilities": hmm.filter(
                        query, decision_ns=config.decision_ns
                    ),
                    "smoothing_at_inference": False,
                }
            elif family == "PAT-07":
                result = spectra_haar(query, decision_ns=config.decision_ns)
            elif family == "PAT-08":
                result = recurrence(
                    query,
                    decision_ns=config.decision_ns,
                    radius=float(parameters["radius"]),
                    theiler=int(parameters["theiler"]),
                    minimum_line=int(parameters["minimum_line"]),
                )
            elif family == "PAT-09":
                exposure["fits"] = 1
                clusters = fit_clusters(
                    windows,
                    context,
                    clusters=int(parameters["clusters"]),
                    segments=config.paa_segments,
                    radius_factor=float(parameters["radius_factor"]),
                )
                assignment, distance = clusters.assign(
                    query, decision_ns=config.decision_ns
                )
                result = {
                    "model": clusters,
                    "cluster": assignment,
                    "distance": distance,
                    "state": "UNKNOWN" if assignment is None else "ASSIGNED",
                }
            elif family == "PAT-10":
                result = geometry(query, decision_ns=config.decision_ns, **parameters)
            elif family == "PAT-11":
                secondary = self.corpora.load(cast(str, config.secondary_manifest))
                left = self.corpora.frame(corpus, config.query_start, config.query_stop)
                right = self.corpora.time_frame(
                    secondary,
                    query.start_ns
                    + query.step_ns
                    - int(parameters["maximum_staleness_ns"]),
                    query.end_ns,
                )
                result = align_asof(
                    (left, right),
                    decision_ns=config.decision_ns,
                    maximum_staleness_ns=int(parameters["maximum_staleness_ns"]),
                )
            elif family == "PAT-12":
                if len(search.hits) < 2 * int(parameters["block_length"]):
                    raise PatternError("PAT12_INSUFFICIENT_FIXED_BOOTSTRAP_BLOCKS")
                result = outcome_summary(
                    search.hits,
                    decision_ns=config.decision_ns,
                    seed=config.seed,
                    minimum_events=int(parameters["minimum_events"]),
                    resamples=int(parameters["resamples"]),
                    block_length=int(parameters["block_length"]),
                )
            elif family == "PAT-13":
                result = {
                    "state": search.state,
                    "exact_reranks": search.exact_reranks,
                    "mode": search.mode,
                }
            elif family == "PAT-14":
                first = corpus.partitions[0].first_close_ns
                boundaries = np.linspace(
                    first,
                    config.candidate_cutoff_ns,
                    int(parameters["periods"]) + 1,
                    dtype=np.int64,
                )
                periods = tuple((int(a), int(b)) for a, b in pairwise(boundaries))
                stability = stability_and_costs(
                    search.hits,
                    decision_ns=config.decision_ns,
                    periods=periods,
                    eligible_windows=max(1, search.progress.eligible_windows),
                )
                pool = tuple(
                    sorted(
                        deduplicate(
                            tuple(hit for _, _, hit in engine.snapshot().candidates),
                            limit=256,
                        ),
                        key=lambda h: h.window.end_ns,
                    )
                )
                block = int(parameters["block_length"])
                pool = pool[: len(pool) - len(pool) % block]
                threshold = config.maximum_distance**2
                signal = tuple(hit.distance <= threshold for hit in pool)
                null: object = {
                    "state": "INSUFFICIENT",
                    "reason": "Need two preregistered PAA-distance groups and at least eight nonoverlapping known outcomes",
                }
                if len(pool) >= 8 and len(set(signal)) == 2:
                    null = block_permutation_test(
                        signal,
                        tuple(hit.outcome for hit in pool if hit.outcome),
                        decision_ns=config.decision_ns,
                        block_length=block,
                        permutations=int(parameters["permutations"]),
                        seed=config.seed,
                    )
                exposure["null_control_events"] = len(pool)
                result = {
                    "stability": stability,
                    "block_null": null,
                    "FDR": "HOST_COMPLETE_EXPERIMENT_FAMILY_REQUIRED;NO_SINGLE_QUERY_PASS",
                }
            else:
                result = representation_comparison(
                    query,
                    ClassicalRepresentation(context, segments=config.paa_segments),
                    decision_ns=config.decision_ns,
                )
            return {"status": "EXECUTED", "output": _plain(result)}, exposure
        except PatternError as error:
            return {
                "status": "INCONCLUSIVE",
                "reason": str(error),
                "retained": True,
            }, exposure


def _overlay(window: PatternWindow, normalization: Normalization) -> JsonRecord:
    return {
        "fingerprint": window.fingerprint,
        "start_ns": str(window.start_ns),
        "end_ns": str(window.end_ns),
        "available_ns": str(window.available_ns),
        "step_ns": window.step_ns,
        "provenance": _plain(window.provenance),
        "raw_values": window.values.tolist(),
        "normalized_values": normalize(window.values, normalization).tolist(),
        "normalization": normalization,
    }


def _hit(hit: SearchHit, normalization: Normalization) -> JsonRecord:
    return {
        **_overlay(hit.window, normalization),
        "distance": hit.distance,
        "outcome": _plain(hit.outcome),
        "net_return": hit.outcome.net_return if hit.outcome else None,
    }
