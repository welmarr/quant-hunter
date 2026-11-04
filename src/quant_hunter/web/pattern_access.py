"""Private PatternLab products using canonical data, PATTERN and Item 8 authority.

SQLite contains ownership, resource reservations and worker receipts only. It is
never a second scientific registry or a substitute for the frozen experiment.
"""

from __future__ import annotations

import json
import secrets
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.data_quality import PartitionSelection
from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.lab.service import LabService
from quant_hunter.patterns.catalog import METHODS
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.patterns.corpus import Corpus, CorpusConfig, CorpusStore
from quant_hunter.patterns.product import (
    FrozenPatternBinding,
    PatternJobConfig,
    PatternProduct,
    method_profile,
)
from quant_hunter.web.pattern_models import PatternModels
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.state import AccessError, AppState, Job, User

type Scenario = Literal["SELECTED", "BASELINE", "POSITIVE", "NULL", "SENSITIVITY"]
_MIB = 1024 * 1024
_TRANSFORM = "qh-pattern-owned-parquet-corpus-v1"
_MISSING = "No empirical validation dataset or sealed holdout exists for this synthetic software object."
_SCHEMA: JsonRecord = {
    "format": "qh-pattern-corpus-parquet-v1",
    "physical_format": "JSON_MANIFEST_OF_IMMUTABLE_PARQUET_PARTITIONS",
    "bar_time": "close_ns",
    "availability_time": "available_ns",
    "feature_schema": "Exact parent feature_columns; close first",
}
_SCENARIOS: JsonRecord = {
    "SELECTED": "Exact user-selected bounded configuration; no result expectation.",
    "BASELINE": "Reference configuration on selected synthetic data; no positive-result guarantee.",
    "POSITIVE": "Known qh-quality-demo-v1 exact raw fixture only. Inspect measured matches and method status; no scientific pass.",
    "NULL": "No eligible past support: cutoff is before the first bar. Expected UNKNOWN; this is a software negative control, not a statistical permutation null.",
    "SENSITIVITY": "Exactly one declared family parameter changes from the reference configuration; no selection of the better result.",
}
_DEMO_RAW_DIGESTS = frozenset(
    {
        "sha256:522ea44eb0166c0cd0f5e99ea2d29c1419f04c086d88f8c4cc62dd12891f8ee3",
        "sha256:dbd18dc45b3cddbc425ee1cf9c73670ee7c6e6345ffe1281627a31fbbc26511a",
    }
)
_SENSITIVITY: dict[str, JsonRecord] = {
    "PAT-01": {"stride": 16},
    "PAT-02": {"dtw_radius": 2},
    "PAT-03": {"length": 4},
    "PAT-04": {"alphabet": 6},
    "PAT-05": {"threshold": 8.0},
    "PAT-06": {"states": 3},
    "PAT-07": {"query_length": 16},
    "PAT-08": {"radius": 0.75},
    "PAT-09": {"radius_factor": 2.0},
    "PAT-10": {"breakout_fraction": 0.002},
    "PAT-11": {"maximum_staleness_ns": 60_000_000_000},
    "PAT-12": {"cost_bps": 27.0},
    "PAT-13": {"cost_bps": 27.0},
    "PAT-14": {"cost_bps": 27.0},
    "PAT-15": {"paa_segments": 4},
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _stamp(ns: int) -> str:
    if ns % 1000:
        raise PatternError("PATTERN_LAB_MICROSECOND_PROFILE_REQUIRED")
    return (
        (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=ns // 1000))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise PatternError("PATTERN_RECORD_REQUIRED")
    return value


def _config(record: JsonRecord) -> PatternJobConfig:
    values = cast(dict[str, Any], dict(record))
    for key in ("decision_ns", "train_cutoff_ns", "candidate_cutoff_ns", "purge_ns"):
        value = values.get(key, 0)
        if type(value) is int and 0 <= value <= 2**53 - 1:
            continue
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdecimal()
            or len(value) > 19
        ):
            raise PatternError("PATTERN_TIMESTAMP_ENCODING")
        values[key] = int(value)
    return PatternJobConfig(**values)


class PatternAccess:
    """Owned corpus/query products; current host lease remains a precondition."""

    def __init__(
        self, state: AppState, quality: QualityAccess, lab: LabService
    ) -> None:
        if (
            quality.state is not state
            or quality.service.objects is not lab.objects
            or quality.service.registry is not lab.registry
        ):
            raise ValueError("Pattern access requires shared governed stores")
        self.state, self.quality, self.lab = state, quality, lab
        self.corpora = CorpusStore(lab.objects)
        self.product = PatternProduct(self.corpora)
        self.models = PatternModels(state, lab)
        with state.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pattern_corpora (
                    dataset_id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
                    record_digest TEXT NOT NULL, manifest_digest TEXT NOT NULL,
                    selection_digest TEXT NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS pattern_prepared (
                    id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL,
                    envelope_digest TEXT NOT NULL,
                    FOREIGN KEY(owner_id) REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS pattern_job_receipts (
                    job_id TEXT PRIMARY KEY, prepared_id TEXT,
                    status TEXT NOT NULL, operation_id TEXT,
                    checkpoint_digest TEXT, progress TEXT, binding TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(id),
                    FOREIGN KEY(prepared_id) REFERENCES pattern_prepared(id));
            """)
            if "model_binding" not in {
                row[1] for row in db.execute("PRAGMA table_info(pattern_job_receipts)")
            }:
                db.execute(
                    "ALTER TABLE pattern_job_receipts ADD COLUMN model_binding TEXT"
                )

    @staticmethod
    def catalogue() -> JsonRecord:
        return {
            "methods": [cast(JsonValue, asdict(method)) for method in METHODS],
            "scenarios": _SCENARIOS,
            "sensitivity_parameters": cast(JsonRecord, _SENSITIVITY),
            "evidence_mode": "SYNTHETIC",
            "empirical_validation": "MISSING",
            "historical_causal_jobs": "BLOCKED_UNVERIFIED_AVAILABILITY",
            "automatic_promotion": False,
        }

    def _read(self, digest: str) -> JsonRecord:
        if self.lab.objects.get(digest).byte_size > 2_000_000:
            raise PatternError("PATTERN_NATIVE_METADATA_LIMIT")
        return _record(parse_json_document(self.lab.objects.read_bytes(digest)))

    def _resource(
        self, user: User, kind: str, *, worker_job_id: str | None = None
    ) -> str:
        # The shared two-operation slot is acquired first. Reserving two GiB is
        # stricter than both admitted 512 MiB corpora/256 MiB query checkpoints,
        # including metadata and the other data/publication operation's budget.
        operation = self.quality.data._begin(user, kind, worker_job_id=worker_job_id)
        try:
            runtime = self.quality.data.runtime
            usage = shutil.disk_usage(runtime)
            reserve = max(20 * 1024**3, usage.total * 15 // 100)
            budget_root = next(
                (p for p in (runtime, *runtime.parents) if p.name == ".local"), runtime
            )
            total = sum(p.stat().st_size for p in budget_root.rglob("*") if p.is_file())
            if (
                usage.free - 2 * 1024**3 < reserve
                or total + 2 * 1024**3 > 30_000_000_000
            ):
                raise AccessError("Pattern disk reservation unavailable")
        except Exception:
            self.quality.data._finish(operation, error="PatternResourceRefused")
            raise
        return operation

    def _finish(
        self,
        user: User,
        operation: str,
        result: JsonRecord,
        *,
        corpus: tuple[str, str, str, str] | None = None,
        prepared: tuple[str, str] | None = None,
    ) -> None:
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute(
                    "UPDATE data_operations SET status='SUCCEEDED',result=? WHERE id=? AND owner_id=? AND status='RUNNING'",
                    (json.dumps(result, allow_nan=False), operation, user.id),
                ).rowcount
                != 1
            ):
                raise AccessError("Pattern operation interrupted; no ownership granted")
            if corpus:
                db.execute(
                    "INSERT INTO pattern_corpora VALUES(?,?,?,?,?)",
                    (corpus[0], user.id, *corpus[1:]),
                )
            if prepared:
                db.execute(
                    "INSERT INTO pattern_prepared VALUES(?,?,?)",
                    (prepared[0], user.id, prepared[1]),
                )

    def _lineage(self, corpus: Corpus, selection: PartitionSelection) -> JsonRecord:
        return {
            "format": _TRANSFORM,
            "corpus_manifest": corpus.manifest_digest,
            "selection": selection.to_record(),
            "code_revision": self.lab.code_revision,
            "environment_digest": self.lab.environment_digest,
            "normalization": "NONE; exact numeric source columns retained",
            "missing_data_policy": "GAPS_PRESERVED_NO_IMPUTATION",
        }

    def _selection_owner(self, user: User, digest: str) -> None:
        with self.state.connection() as db:
            if not db.execute(
                "SELECT 1 FROM quality_selection_ownership WHERE manifest_digest=? AND owner_id=?",
                (digest, user.id),
            ).fetchone():
                raise AccessError("Pattern source selection unavailable")

    def materialize(
        self,
        user: User,
        selection_digest: str,
        *,
        config: CorpusConfig | None = None,
        progress: Callable[[dict[str, int | str]], None] | None = None,
        operation_started: Callable[[str], None] | None = None,
        worker_job_id: str | None = None,
    ) -> JsonRecord:
        chosen = config or CorpusConfig(max_disk_bytes=512 * _MIB)
        chosen.__post_init__()
        if chosen.max_disk_bytes > 512 * _MIB:
            raise PatternError("PATTERN_NATIVE_CORPUS_DISK_LIMIT")
        # Establish ownership before any content read or identity allocation.
        self._selection_owner(user, selection_digest)
        operation = self._resource(user, "PATTERN_CORPUS", worker_job_id=worker_job_id)
        try:
            if operation_started:
                operation_started(operation)
            selected = self.quality._selection(user, selection_digest)
            identity = new_typed_id(RegistryKind.DATASET)
            corpus = self.corpora.build_selection(
                identity,
                selected,
                self.quality.iter_selection(
                    user, selection_digest, operation_id=operation
                ),
                config=chosen,
                progress=progress,
            )
            sources = sorted(
                {
                    cast(str, source)
                    for parent in selected.parent_snapshots
                    for source in cast(
                        list[JsonValue],
                        self.lab.registry.verify_object(parent.dataset_id)[-1].record[
                            "source_ids"
                        ],
                    )
                }
            )
            schema = self.lab.objects.publish(canonicalize_json(_SCHEMA)).digest
            lineage = self.lab.objects.publish(
                canonicalize_json(self._lineage(corpus, selected))
            ).digest
            record: JsonRecord = {
                "schema_version": "1.0.0",
                "created_at": _now(),
                "layer": "curated",
                "source_ids": cast(list[JsonValue], sources),
                "coverage": selected.bounds,
                "time_fields": {
                    "event_time": "close_ns",
                    "publication_time": "available_ns",
                    "ingestion_time": "NOT_APPLICABLE",
                    "revision_time": "NOT_APPLICABLE",
                },
                "schema_digest": schema,
                "physical_object_digest": corpus.manifest_digest,
                "provenance_lineage_digest": lineage,
                "logical_content_fingerprint": corpus.manifest_digest,
                "provenance": {
                    "parent_dataset_ids": [
                        parent.dataset_id for parent in selected.parent_snapshots
                    ],
                    "transformation": _TRANSFORM,
                    "code_revision": self.lab.code_revision,
                    "environment_digest": self.lab.environment_digest,
                },
                "quality_status": "PENDING",
            }
            revision = self.lab.registry.create_initial(
                RegistryKind.DATASET, identity, record
            )
            result: JsonRecord = {
                "dataset_id": identity,
                "record_digest": revision.digest,
                "manifest_digest": corpus.manifest_digest,
                "selection_digest": selection_digest,
            }
            detail = self._corpus_detail(corpus, revision.digest, selected)
            self._finish(
                user,
                operation,
                result,
                corpus=(
                    identity,
                    revision.digest,
                    corpus.manifest_digest,
                    selection_digest,
                ),
            )
            # The newly built graph was verified while this operation held its
            # resource slot. Do not start a second expensive read after finish.
            return detail
        except Exception:
            self.quality.data._finish(operation, error="PatternCorpusFailure")
            raise

    def _corpus(self, user: User, identity: str) -> tuple[Corpus, JsonRecord]:
        with self.state.connection() as db:
            row = db.execute(
                "SELECT * FROM pattern_corpora WHERE dataset_id=? AND owner_id=?",
                (identity, user.id),
            ).fetchone()
        if row is None:
            raise AccessError("Pattern corpus unavailable")
        revision = self.lab.registry.verify_object(identity)[-1]
        corpus = self.corpora.load(str(row["manifest_digest"]))
        selected = self.quality._selection(user, str(row["selection_digest"]))
        record = revision.record
        parent_sources = sorted(
            {
                cast(str, source)
                for parent in selected.parent_snapshots
                for source in cast(
                    list[JsonValue],
                    self.lab.registry.verify_object(parent.dataset_id)[-1].record[
                        "source_ids"
                    ],
                )
            }
        )
        if (
            revision.digest != row["record_digest"]
            or corpus.dataset_id != identity
            or corpus.selection_manifest_digest != selected.manifest_digest
            or corpus.parents
            != [parent.to_record() for parent in selected.parent_snapshots]
            or corpus.calendar_profile_digest != selected.calendar_profile_digest
            or record["physical_object_digest"] != corpus.manifest_digest
            or record["coverage"] != selected.bounds
            or record["source_ids"] != parent_sources
            or record["logical_content_fingerprint"] != corpus.manifest_digest
            or _record(record["provenance"])["transformation"] != _TRANSFORM
            or _record(record["provenance"])["parent_dataset_ids"]
            != [parent.dataset_id for parent in selected.parent_snapshots]
            or self._read(cast(str, record["schema_digest"])) != _SCHEMA
        ):
            raise PatternError("PATTERN_CORPUS_GRAPH_MISMATCH")
        # Code/environment are retained creation identities, not today's host.
        lineage = self._read(cast(str, record["provenance_lineage_digest"]))
        expected = self._lineage(corpus, selected)
        for key in ("code_revision", "environment_digest"):
            expected[key] = _record(record["provenance"])[key]
        if lineage != expected:
            raise PatternError("PATTERN_CORPUS_LINEAGE_MISMATCH")
        environment = self._read(cast(str, expected["environment_digest"]))
        if "source_snapshot_digest" in environment:
            self.lab.objects.get(cast(str, environment["source_snapshot_digest"]))
        return corpus, self._corpus_detail(corpus, revision.digest, selected)

    @staticmethod
    def _corpus_detail(
        corpus: Corpus, record_digest: str, selected: PartitionSelection
    ) -> JsonRecord:
        return {
            "dataset_id": corpus.dataset_id,
            "record_digest": record_digest,
            "manifest_digest": corpus.manifest_digest,
            "selection_digest": selected.manifest_digest,
            "row_count": corpus.row_count,
            "parquet_bytes": corpus.parquet_bytes,
            "partition_count": len(corpus.partitions),
            "gap_count": corpus.gap_count,
            "parents": corpus.parents,
            "bounds": selected.bounds,
            "feature_columns": list(selected.feature_columns),
            "step_ns": selected.step_ns,
            "evidence_mode": "SYNTHETIC",
            "quality_status": "PENDING",
            "empirical_validation": "MISSING",
            "physical_format": _SCHEMA["physical_format"],
        }

    def corpus(self, user: User, identity: str) -> JsonRecord:
        with self.quality.inspection(user):
            return self._corpus(user, identity)[1]

    def preview(
        self, user: User, identity: str, *, start: int, stop: int
    ) -> JsonRecord:
        """Owned literal bars only; no outcomes or learned transformation."""
        if (
            type(start) is not int
            or type(stop) is not int
            or start < 0
            or not start < stop <= start + 512
        ):
            raise PatternError("PATTERN_PREVIEW_RANGE")
        with self.quality.inspection(user):
            corpus, receipt = self._corpus(user, identity)
            if stop > corpus.row_count:
                raise PatternError("PATTERN_PREVIEW_RANGE")
            frame = self.corpora.frame(corpus, start, stop)
            return {
                "dataset_id": corpus.dataset_id,
                "record_digest": receipt["record_digest"],
                "manifest_digest": corpus.manifest_digest,
                "selection_digest": corpus.selection_manifest_digest,
                "row_start": start,
                "row_stop": stop,
                "instrument_id": corpus.selected["instrument_id"],
                "instrument_revision_digest": corpus.selected[
                    "instrument_revision_digest"
                ],
                "step_ns": frame.step_ns,
                "feature_columns": list(frame.provenance.features),
                "rows": [
                    {
                        "row": start + index,
                        "open_ns": str(int(frame.close_ns[index]) - frame.step_ns),
                        "close_ns": str(int(frame.close_ns[index])),
                        "available_ns": str(int(frame.available_ns[index])),
                        "values": cast(JsonValue, frame.values[index].tolist()),
                    }
                    for index in range(stop - start)
                ],
                "evidence_mode": "SYNTHETIC",
                "inspection": "EXACT_SELECTED_BARS_ONLY; NO_OUTCOME_CALCULATION",
            }

    def _ids(
        self, user: User, kind: Literal["corpus", "prepared"], limit: int, offset: int
    ) -> list[str]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 25
            or type(offset) is not int
            or not 0 <= offset <= 1000
        ):
            raise AccessError("Invalid Pattern page")
        query = (
            "SELECT dataset_id FROM pattern_corpora WHERE owner_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?"
            if kind == "corpus"
            else "SELECT id FROM pattern_prepared WHERE owner_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?"
        )
        with self.state.connection() as db:
            return [str(row[0]) for row in db.execute(query, (user.id, limit, offset))]

    def corpus_list(
        self, user: User, *, limit: int = 10, offset: int = 0
    ) -> list[JsonRecord]:
        summaries: list[JsonRecord] = []
        for identity in self._ids(user, "corpus", limit, offset):
            with self.state.connection() as db:
                row = db.execute(
                    "SELECT * FROM pattern_corpora WHERE dataset_id=? AND owner_id=?",
                    (identity, user.id),
                ).fetchone()
            if row is None:
                raise AccessError("Pattern corpus unavailable")
            head = self.lab.registry.verify_object(identity)[-1]
            corpus = self.corpora.load(str(row["manifest_digest"]))
            if (
                head.digest != row["record_digest"]
                or corpus.dataset_id != identity
                or head.record["physical_object_digest"] != corpus.manifest_digest
            ):
                raise PatternError("PATTERN_CORPUS_GRAPH_MISMATCH")
            summaries.append(
                {
                    "dataset_id": identity,
                    "record_digest": head.digest,
                    "manifest_digest": corpus.manifest_digest,
                    "selection_digest": row["selection_digest"],
                    "row_count": corpus.row_count,
                    "partition_count": len(corpus.partitions),
                    "parquet_bytes": corpus.parquet_bytes,
                    "gap_count": corpus.gap_count,
                    "bounds": head.record["coverage"],
                    "feature_columns": corpus.selected["feature_columns"],
                    "step_ns": corpus.selected["step_ns"],
                    "evidence_mode": "SYNTHETIC",
                    "inspection": "IMMUTABLE_MANIFEST_SUMMARY; detail re-verifies all source parents",
                }
            )
        return summaries

    def scenario_config(
        self,
        corpus: Corpus,
        family: str,
        scenario: Scenario,
        secondary: Corpus | None = None,
    ) -> PatternJobConfig:
        if (
            scenario not in {"BASELINE", "POSITIVE", "NULL", "SENSITIVITY"}
            or corpus.row_count < 200
        ):
            raise PatternError("PATTERN_SCENARIO_REQUIRES_200_ROWS")
        change = _SENSITIVITY.get(family, {}) if scenario == "SENSITIVITY" else {}
        length = int(cast(int, change.get("query_length", 32)))
        query_start = corpus.row_count - length
        query = self.corpora.window(corpus, query_start, corpus.row_count, 2**63 - 1)
        train = self.corpora.frame(corpus, 0, 128)
        first = self.corpora.frame(corpus, 0, 1)
        parameters = {
            k: v
            for k, v in change.items()
            if k not in {"query_length", "dtw_radius", "cost_bps", "paa_segments"}
        }
        return PatternJobConfig(
            family,
            query_start,
            corpus.row_count,
            0,
            128,
            query.available_ns,
            int(train.available_ns.max()),
            int(first.close_ns[0]) - first.step_ns
            if scenario == "NULL"
            else query.start_ns,
            metric="DTW" if family == "PAT-02" else "EUCLIDEAN",
            maximum_distance=1.5,
            cost_bps=float(cast(float, change.get("cost_bps", 7.0))),
            dtw_radius=int(cast(int, change.get("dtw_radius", 4))),
            paa_segments=int(cast(int, change.get("paa_segments", 8))),
            method_parameters_json=json.dumps(parameters),
            secondary_manifest=secondary.manifest_digest if secondary else None,
        )

    def prepare(
        self,
        user: User,
        corpus_id: str,
        *,
        config: PatternJobConfig | None = None,
        family: str | None = None,
        scenario: Scenario = "SELECTED",
        secondary_corpus_id: str | None = None,
    ) -> JsonRecord:
        if user.role not in {"owner", "researcher"}:
            raise AccessError("Researcher role required")
        operation = self._resource(user, "PATTERN_PREPARE")
        try:
            return self._prepare(
                user,
                operation,
                corpus_id,
                config=config,
                family=family,
                scenario=scenario,
                secondary_corpus_id=secondary_corpus_id,
            )
        except Exception:
            self.quality.data._finish(operation, error="PatternPreparationFailure")
            raise

    def _prepare(
        self,
        user: User,
        operation: str,
        corpus_id: str,
        *,
        config: PatternJobConfig | None,
        family: str | None,
        scenario: Scenario,
        secondary_corpus_id: str | None,
    ) -> JsonRecord:
        corpus, corpus_detail = self._corpus(user, corpus_id)
        secondary, secondary_detail = (
            self._corpus(user, secondary_corpus_id)
            if secondary_corpus_id
            else (None, None)
        )
        if scenario not in _SCENARIOS:
            raise PatternError("PATTERN_SCENARIO_UNKNOWN")
        if scenario == "POSITIVE":
            for chosen_corpus in (corpus, secondary):
                if chosen_corpus is None:
                    continue
                parents = chosen_corpus.parents
                if len(parents) != 1 or chosen_corpus.row_count != 240:
                    raise PatternError("PATTERN_POSITIVE_REQUIRES_KNOWN_FIXTURE")
                detail = self.quality.dataset(
                    user,
                    cast(str, _record(parents[0])["dataset_id"]),
                    operation_id=operation,
                )
                if cast(str, detail.get("raw_digest")) not in _DEMO_RAW_DIGESTS:
                    raise PatternError("PATTERN_POSITIVE_REQUIRES_KNOWN_FIXTURE")
                source_config = self._read(cast(str, detail["configuration_digest"]))
                columns = (
                    "open_at",
                    "close_at",
                    "open",
                    "high",
                    "low",
                    "close",
                    "available_at",
                    "open_bid",
                    "open_ask",
                    "volume",
                )
                expected_mapping: JsonRecord = {
                    "columns": {name: name for name in columns},
                    "timezone": "OFFSET_REQUIRED",
                    "price_scale": "1",
                    "price_currency": "USD",
                    "volume_unit": "UNITS",
                    "reject_policy": "REJECT_DATASET",
                    "revision_mode": "SYNTHETIC_NOT_APPLICABLE",
                }
                calendar = self._read(cast(str, detail["calendar_digest"]))
                if (
                    source_config.get("mapping") != expected_mapping
                    or detail["feature_columns"]
                    != [
                        "close",
                        "open",
                        "high",
                        "low",
                        "volume",
                        "open_bid",
                        "open_ask",
                    ]
                    or detail["step_ns"] != 60_000_000_000
                    or _record(detail["bounds"])
                    != {
                        "start": "2025-01-06T14:30:00.000000Z",
                        "end": "2025-01-06T18:30:00.000000Z",
                    }
                    or calendar.get("calendar_id") != "XNYS"
                    or source_config.get("calendar_start") != "2025-01-06"
                    or source_config.get("calendar_end") != "2025-01-06"
                ):
                    raise PatternError("PATTERN_POSITIVE_REQUIRES_TESTED_NORMALIZATION")
        if scenario == "SELECTED":
            if (
                config is None
                or family is not None
                or config.secondary_manifest is not None
            ):
                raise PatternError("PATTERN_SELECTED_CONFIG_REQUIRED")
            chosen = replace(
                config,
                secondary_manifest=secondary.manifest_digest if secondary else None,
            )
        else:
            if config is not None or family is None:
                raise PatternError("PATTERN_SCENARIO_CONFIG_CONFLICT")
            chosen = self.scenario_config(corpus, family, scenario, secondary)
        if chosen.max_checkpoint_bytes > 256 * _MIB:
            raise PatternError("PATTERN_NATIVE_CHECKPOINT_LIMIT")
        pattern_id: str | None = None
        model_recipe: JsonRecord | None = None
        try:
            model_recipe = self.models.recipe(
                user,
                chosen.to_record(),
                corpus_detail,
                secondary_detail,
                method_profile=method_profile(chosen, corpus.provenance.features),
            )
            candidate_count = max(
                1,
                corpus.row_count
                - (chosen.query_stop - chosen.query_start)
                - chosen.horizon
                + 1,
            )
            pattern = self.lab.registry.allocate(
                RegistryKind.PATTERN,
                {
                    "schema_version": "1.0.0",
                    "created_at": _now(),
                    "status": "SOFTWARE_ONLY",
                    "name": f"{chosen.family} {scenario} software configuration",
                    "hypothesis": "Inspect this exact synthetic configuration; no empirical claim.",
                    "algorithm_family": chosen.family,
                    "definition": canonicalize_json(
                        {
                            "configuration": chosen.to_record(),
                            "model_recipe": model_recipe,
                        }
                    ).decode(),
                    "features": list(corpus.provenance.features),
                    "normalization_method": chosen.normalization,
                    "similarity_metric": chosen.metric,
                    "horizons": [f"{chosen.horizon} bars"],
                    "markets": ["SYNTHETIC_SOFTWARE"],
                    "regimes": [],
                    "discovery_dataset_id": corpus_id,
                    "validation_dataset_id": None,
                    "sealed_dataset_id": None,
                    "evidence_mode": "SYNTHETIC",
                    "empirical_validation": "UNVALIDATED",
                    "missing_validation_reason": _MISSING,
                    "candidate_count": candidate_count,
                    "outcome_definition": "Available close-mark horizon return minus frozen basis-point costs; no execution or profit prediction.",
                    "owner": f"local-user-{user.id}",
                },
            )
            pattern_id = pattern.object_id
            prepared = self.product.prepare(
                corpus.manifest_digest,
                chosen,
                pattern_id=pattern.object_id,
                code_revision=self.lab.code_revision,
                environment_digest=self.lab.environment_digest,
            )
            envelope: JsonRecord = {
                "format": "qh-owned-pattern-preparation-v1",
                "pattern_id": pattern.object_id,
                "pattern_record_digest": pattern.revision.digest,
                "model_recipe": model_recipe,
                "prepared_digest": prepared.digest,
                "corpus": corpus_detail,
                "secondary_corpus": secondary_detail,
                "scenario": scenario,
                "scenario_definition": _SCENARIOS[scenario],
                "sensitivity_change": _SENSITIVITY[chosen.family]
                if scenario == "SENSITIVITY"
                else {},
                "configuration": chosen.to_record(),
                "planned_scope": prepared.to_record()["planned_scope"],
                "expanded_method_parameters": prepared.to_record()[
                    "expanded_method_parameters"
                ],
                "method_input_schema": prepared.to_record()["method_input_schema"],
                "evidence_mode": "SYNTHETIC",
                "empirical_validation": "MISSING",
            }
            raw = canonicalize_json(envelope)
            if len(raw) > 2_000_000:
                raise PatternError("PATTERN_NATIVE_METADATA_LIMIT")
            envelope_digest = self.lab.objects.publish(raw).digest
            identity = secrets.token_hex(16)
            self._finish(
                user,
                operation,
                {"prepared_id": identity, "envelope_digest": envelope_digest},
                prepared=(identity, envelope_digest),
            )
            return {
                "prepared_id": identity,
                "envelope_digest": envelope_digest,
                **envelope,
            }
        except Exception:
            self.quality.data._finish(
                operation,
                error="PatternPreparationFailure",
                result={"pattern_id": pattern_id, "model_recipe": model_recipe}
                if pattern_id or model_recipe
                else None,
            )
            raise

    def prepared(self, user: User, identity: str) -> JsonRecord:
        with self.quality.inspection(user):
            return self._prepared(user, identity)

    def _prepared(self, user: User, identity: str) -> JsonRecord:
        with self.state.connection() as db:
            row = db.execute(
                "SELECT envelope_digest FROM pattern_prepared WHERE id=? AND owner_id=?",
                (identity, user.id),
            ).fetchone()
        if row is None:
            raise AccessError("Pattern preparation unavailable")
        envelope = self._read(str(row[0]))
        if envelope.get("format") != "qh-owned-pattern-preparation-v1":
            raise PatternError("PATTERN_PREPARATION_FORMAT")
        corpus = _record(envelope["corpus"])
        if self._corpus(user, cast(str, corpus["dataset_id"]))[1] != corpus:
            raise PatternError("PATTERN_PREPARED_CORPUS_CHANGED")
        secondary = envelope["secondary_corpus"]
        if (
            secondary is not None
            and self._corpus(user, cast(str, _record(secondary)["dataset_id"]))[1]
            != secondary
        ):
            raise PatternError("PATTERN_PREPARED_SECONDARY_CHANGED")
        pattern = self.lab.registry.verify_object(cast(str, envelope["pattern_id"]))[-1]
        chosen = _config(_record(envelope["configuration"]))
        plan = self._read(cast(str, envelope["prepared_digest"]))
        self.models.verify_recipe(
            user,
            envelope["model_recipe"],
            chosen.to_record(),
            corpus,
            secondary,
            code_revision=cast(str, plan["code_revision"]),
            method_profile={
                "expanded_method_parameters": plan["expanded_method_parameters"],
                "method_input_schema": plan["method_input_schema"],
            },
        )
        if (
            pattern.digest != envelope["pattern_record_digest"]
            or pattern.record["status"] != "SOFTWARE_ONLY"
            or pattern.record["discovery_dataset_id"] != corpus["dataset_id"]
            or pattern.record["definition"]
            != canonicalize_json(
                {
                    "configuration": chosen.to_record(),
                    "model_recipe": envelope["model_recipe"],
                }
            ).decode()
        ):
            raise PatternError("PATTERN_PREPARED_REGISTRY_CHANGED")
        if (
            plan["configuration"] != chosen.to_record()
            or plan["pattern_id"] != envelope["pattern_id"]
            or plan["corpus_manifest"] != corpus["manifest_digest"]
            or plan["planned_scope"] != envelope["planned_scope"]
            or plan["expanded_method_parameters"]
            != envelope["expanded_method_parameters"]
            or plan["method_input_schema"] != envelope["method_input_schema"]
            or plan["parent_snapshots"] != corpus["parents"]
            or plan["secondary_parent_snapshots"]
            != (_record(secondary)["parents"] if secondary else [])
        ):
            raise PatternError("PATTERN_PREPARED_GRAPH_MISMATCH")
        return {"prepared_id": identity, "envelope_digest": str(row[0]), **envelope}

    def prepared_list(
        self, user: User, *, limit: int = 10, offset: int = 0
    ) -> list[JsonRecord]:
        summaries: list[JsonRecord] = []
        for identity in self._ids(user, "prepared", limit, offset):
            with self.state.connection() as db:
                row = db.execute(
                    "SELECT envelope_digest FROM pattern_prepared WHERE id=? AND owner_id=?",
                    (identity, user.id),
                ).fetchone()
            if row is None:
                raise AccessError("Pattern preparation unavailable")
            record = self._read(str(row[0]))
            summaries.append(
                {
                    "prepared_id": identity,
                    "envelope_digest": str(row[0]),
                    "pattern_id": record["pattern_id"],
                    "prepared_digest": record["prepared_digest"],
                    "corpus_id": _record(record["corpus"])["dataset_id"],
                    "scenario": record["scenario"],
                    "configuration": record["configuration"],
                    "model_recipe": record["model_recipe"],
                    "planned_scope": record["planned_scope"],
                    "evidence_mode": "SYNTHETIC",
                    "inspection": "IMMUTABLE_DESCRIPTION_SUMMARY; detail re-verifies all source parents",
                }
            )
        return summaries

    def enqueue(self, user: User, prepared_id: str) -> Job:
        # Queue admission performs a cheap private receipt check. Full source
        # replay occurs in the worker only after it holds a resource slot.
        with self.state.connection() as db:
            if not db.execute(
                "SELECT 1 FROM pattern_prepared WHERE id=? AND owner_id=?",
                (prepared_id, user.id),
            ).fetchone():
                raise AccessError("Pattern preparation unavailable")
        return self.state.enqueue(
            user, {"kind": "PATTERN_JOB", "prepared_id": prepared_id}
        )

    def enqueue_corpus(
        self, user: User, selection_digest: str, *, config: CorpusConfig | None = None
    ) -> Job:
        self._selection_owner(user, selection_digest)
        chosen = config or CorpusConfig(max_disk_bytes=512 * _MIB)
        chosen.__post_init__()
        if chosen.max_disk_bytes > 512 * _MIB:
            raise PatternError("PATTERN_NATIVE_CORPUS_DISK_LIMIT")
        return self.state.enqueue(
            user,
            {
                "kind": "PATTERN_CORPUS",
                "selection_digest": selection_digest,
                "block_rows": chosen.block_rows,
                "max_rows": chosen.max_rows,
                "max_disk_bytes": chosen.max_disk_bytes,
                "max_shards": chosen.max_shards,
            },
        )

    def _claim(self, job: Job) -> User:
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job.id,)).fetchone()
            expected = (
                {"kind", "prepared_id"}
                if job.config.get("kind") == "PATTERN_JOB"
                else {
                    "kind",
                    "selection_digest",
                    "block_rows",
                    "max_rows",
                    "max_disk_bytes",
                    "max_shards",
                }
            )
            if (
                row is None
                or self.state._job(row) != job
                or job.status != "RUNNING"
                or job.experiment_id is not None
                or set(job.config) != expected
                or job.config.get("kind") not in {"PATTERN_JOB", "PATTERN_CORPUS"}
            ):
                raise AccessError("Pattern job claim unavailable")
            owner = db.execute(
                "SELECT id,username,role FROM users WHERE id=?", (job.owner_id,)
            ).fetchone()
            if owner is None or owner["role"] not in {"owner", "researcher"}:
                raise AccessError("Pattern job owner unavailable")
            if (
                job.config["kind"] == "PATTERN_JOB"
                and not db.execute(
                    "SELECT 1 FROM pattern_prepared WHERE id=? AND owner_id=?",
                    (job.config["prepared_id"], job.owner_id),
                ).fetchone()
            ):
                raise AccessError("Pattern job preparation unavailable")
            try:
                db.execute(
                    "INSERT INTO pattern_job_receipts(job_id,prepared_id,status) VALUES(?,?,'STARTED')",
                    (job.id, job.config.get("prepared_id")),
                )
            except sqlite3.IntegrityError:
                raise AccessError("Pattern job already started; no replay") from None
            return User(owner["id"], owner["username"], owner["role"])

    def execute_corpus_job(self, job: Job) -> None:
        if job.config.get("kind") != "PATTERN_CORPUS":
            raise AccessError("Not a corpus job")
        user = self._claim(job)

        def started(operation: str) -> None:
            with self.state.connection() as db:
                db.execute(
                    "UPDATE pattern_job_receipts SET operation_id=? WHERE job_id=?",
                    (operation, job.id),
                )

        try:
            config = CorpusConfig(
                **{
                    key: cast(int, job.config[key])
                    for key in (
                        "block_rows",
                        "max_rows",
                        "max_disk_bytes",
                        "max_shards",
                    )
                }
            )
            self.materialize(
                user,
                cast(str, job.config["selection_digest"]),
                config=config,
                progress=lambda values: self._update(job, progress=values),
                operation_started=started,
                worker_job_id=job.id,
            )
            with self.state.connection() as db:
                db.execute(
                    "UPDATE pattern_job_receipts SET status='COMPLETED' WHERE job_id=?",
                    (job.id,),
                )
            self.state.finish(job.id)
        except Exception:
            with self.state.connection() as db:
                db.execute(
                    "UPDATE pattern_job_receipts SET status='FAILED' WHERE job_id=?",
                    (job.id,),
                )
            self.state.finish(
                job.id,
                error="Pattern corpus build failed; immutable partial evidence retained",
            )

    def _update(
        self,
        job: Job,
        *,
        checkpoint: str | None = None,
        progress: dict[str, int | str] | None = None,
    ) -> None:
        with self.state.connection() as db:
            if not db.execute(
                "SELECT 1 FROM jobs WHERE id=? AND owner_id=? AND status='RUNNING'",
                (job.id, job.owner_id),
            ).fetchone():
                raise AccessError("Pattern job no longer RUNNING")
            if checkpoint is not None:
                db.execute(
                    "UPDATE pattern_job_receipts SET checkpoint_digest=? WHERE job_id=? AND status='STARTED'",
                    (checkpoint, job.id),
                )
            if progress is not None:
                db.execute(
                    "UPDATE pattern_job_receipts SET progress=? WHERE job_id=? AND status='STARTED'",
                    (json.dumps(progress), job.id),
                )

    def _lab_config(
        self, prepared: JsonRecord, model_fit: JsonValue = None
    ) -> JsonRecord:
        chosen = _config(_record(prepared["configuration"]))
        corpus = self.corpora.load(
            cast(str, _record(prepared["corpus"])["manifest_digest"])
        )
        train = self.corpora.frame(corpus, chosen.train_start, chosen.train_stop)
        query = self.corpora.window(
            corpus, chosen.query_start, chosen.query_stop, chosen.decision_ns
        )
        return {
            "kind": "PATTERN_JOB",
            "evidence_mode": "SYNTHETIC",
            "random_seed": chosen.seed,
            "dataset_start": _stamp(int(train.close_ns[0]) - train.step_ns),
            "dataset_end": _stamp(max(query.end_ns, chosen.decision_ns) + 1000),
            "training_start": _stamp(int(train.close_ns[0]) - train.step_ns),
            "train_end": _stamp(int(train.close_ns[-1])),
            "training_end_exclusive": _stamp(int(train.close_ns[-1]) + 1000),
            "prepared_id": prepared["prepared_id"],
            "envelope_digest": prepared["envelope_digest"],
            "prepared_digest": prepared["prepared_digest"],
            "pattern_id": prepared["pattern_id"],
            "pattern_record_digest": prepared["pattern_record_digest"],
            "model_recipe": prepared["model_recipe"],
            "model_fit": model_fit,
            "input_graph": {
                "corpus": prepared["corpus"],
                "secondary_corpus": prepared["secondary_corpus"],
            },
            "pattern_configuration": prepared["configuration"],
            "planned_scope": prepared["planned_scope"],
            "expanded_method_parameters": prepared["expanded_method_parameters"],
            "method_input_schema": prepared["method_input_schema"],
            "scenario": prepared["scenario"],
            "scenario_definition": prepared["scenario_definition"],
            "input_format": "SOFTWARE_INPUT_MANIFEST; BAR_DATA_IN_EXACT_REFERENCED_PARQUET_CORPORA",
            "validation_limit": _MISSING,
            "software_method": {
                "implemented_scope": f"{chosen.family}: actual bounded classical method plus past-only occurrence search",
                "source_citations": [
                    "docs/v0/PATTERNLAB.md",
                    "docs/v0/PATTERN_PRODUCT.md",
                ],
                "assumptions": [
                    "Synthetic software evidence only",
                    "No eligible historical causal uploads",
                    "Every query/configuration is one counted AI-generated variant",
                ],
                "cost_model": "Frozen basis-point deduction from closing-mark horizon returns; no fills or portfolio performance",
            },
        }

    def _binding(self, experiment: str, prepared: JsonRecord) -> FrozenPatternBinding:
        revisions = self.lab.registry.verify_object(experiment)
        frozen = [
            row for row in revisions if row.record["lifecycle_status"] == "FROZEN"
        ]
        if len(frozen) != 1:
            raise PatternError("PATTERN_ITEM8_BINDING")
        return FrozenPatternBinding(
            experiment,
            frozen[0].digest,
            cast(str, frozen[0].record["configuration_digest"]),
            cast(str, prepared["prepared_digest"]),
            cast(str, prepared["pattern_id"]),
        )

    @staticmethod
    def _verify_result(
        result: JsonValue, prepared: JsonRecord, binding: FrozenPatternBinding
    ) -> JsonRecord:
        if not isinstance(result, dict):
            raise PatternError("PATTERN_RETAINED_RESULT_GRAPH_MISMATCH")
        corpus = _record(prepared["corpus"])
        configuration = _record(prepared["configuration"])
        expected: JsonRecord = {
            "canonical_binding": binding.to_record(),
            "pattern_id": binding.pattern_id,
            "experiment_id": binding.experiment_id,
            "prepared_digest": binding.prepared_digest,
            "method_id": configuration["family"],
            "method_input_schema": prepared["method_input_schema"],
            "method_parameters": prepared["expanded_method_parameters"],
            "configuration": configuration,
            "dataset_id": corpus["dataset_id"],
            "corpus_manifest": corpus["manifest_digest"],
            "parent_snapshots": corpus["parents"],
            "selection_manifest_digest": corpus["selection_digest"],
            "evidence_mode": "SYNTHETIC",
            "empirical_validation": "MISSING",
        }
        if any(
            key not in result or result[key] != value for key, value in expected.items()
        ):
            raise PatternError("PATTERN_RETAINED_RESULT_GRAPH_MISMATCH")
        return result

    def execute_job(self, job: Job) -> None:
        if job.config.get("kind") != "PATTERN_JOB":
            raise AccessError("Not a Pattern query job")
        user = self._claim(job)
        experiment: str | None = None
        operation: str | None = None
        model_fit: JsonRecord | None = None
        try:
            operation = self._resource(user, "PATTERN_QUERY", worker_job_id=job.id)
            with self.state.connection() as db:
                db.execute(
                    "UPDATE pattern_job_receipts SET operation_id=? WHERE job_id=?",
                    (operation, job.id),
                )
            prepared = self._prepared(user, cast(str, job.config["prepared_id"]))
            plan = self._read(cast(str, prepared["prepared_digest"]))
            if (
                plan["code_revision"] != self.lab.code_revision
                or plan["environment_digest"] != self.lab.environment_digest
            ):
                raise PatternError("PATTERN_PREPARATION_EXECUTION_VERSION_CHANGED")
            model_fit = self.models.fit(user, prepared, job)
            with self.state.connection() as db:
                db.execute(
                    "UPDATE pattern_job_receipts SET operation_id=?,model_binding=? WHERE job_id=?",
                    (operation, json.dumps(model_fit), job.id),
                )
            self.models.verify_fit(user, model_fit, prepared, job.id)
            configuration = self._lab_config(prepared, model_fit)
            manifest = canonicalize_json(
                {
                    "format": "qh-pattern-software-input-manifest-v1",
                    "prepared": prepared,
                    "model_fit": model_fit,
                }
            )
            experiment = self.lab.begin_run(
                configuration,
                manifest,
                name=f"{_record(prepared['configuration'])['family']} {prepared['scenario']} synthetic PatternLab",
            )
            self.state.bind(job.id, experiment)
            if self.state.job(user, job.id).experiment_id != experiment:
                raise AccessError("Pattern job binding interrupted")
            run = self.lab.get_run(experiment)
            if (
                run["lifecycle_status"] != "RUNNING"
                or run["variants_attempted"] != 0
                or run["configuration"] != configuration
            ):
                raise PatternError("PATTERN_ITEM8_BINDING")
            binding = self._binding(experiment, prepared)
            with self.state.connection() as db:
                db.execute(
                    "UPDATE pattern_job_receipts SET binding=? WHERE job_id=?",
                    (json.dumps(binding.to_record()), job.id),
                )
            current = self.state.job(user, job.id)
            if current.status != "RUNNING" or current.experiment_id != experiment:
                raise AccessError("Pattern job no longer owns its active attempt")
            result = self.product.execute_registered(
                binding.prepared_digest,
                binding=binding,
                checkpoint=lambda digest: self._update(job, checkpoint=digest),
                progress=lambda progress: self._update(job, progress=progress),
            )
            self._verify_result(result, prepared, binding)
            result["native_input_graph"] = configuration["input_graph"]
            result["native_scenario"] = prepared["scenario"]
            result["native_scenario_definition"] = prepared["scenario_definition"]
            result["native_input_format"] = configuration["input_format"]
            result["model_recipe"] = prepared["model_recipe"]
            result["model_fit"] = model_fit
            result["model_artifact"] = self.models.artifact(model_fit, result)
            self._verify_models(user, prepared, model_fit, result, job.id)
            self.lab.evaluate_run(experiment, result)
            self._complete_query(user, job, operation, experiment)
        except Exception:
            # Retain one failed attempt before operational finalization. Integrity
            # failure while recovering propagates and cannot be disguised as done.
            if experiment is not None:
                run = self.lab.get_run(experiment)
                if run["lifecycle_status"] == "RUNNING":
                    run = self.lab.recover_run(experiment)
                if (
                    run["lifecycle_status"] == "EVALUATED"
                    and run["evaluation_outcome"] != "FAILED"
                    and operation is not None
                ):
                    # Computation already has immutable canonical evidence.
                    # Retry only operational finalization, never the evaluation.
                    self._verify_result(
                        run["result"], prepared, self._binding(experiment, prepared)
                    )
                    self._verify_models(
                        user, prepared, model_fit, _record(run["result"]), job.id
                    )
                    if run["configuration"] != self._lab_config(prepared, model_fit):
                        raise PatternError(
                            "PATTERN_RETAINED_RUN_GRAPH_MISMATCH"
                        ) from None
                    self._complete_query(user, job, operation, experiment)
                    return
            if operation is not None:
                self.quality.data._finish(operation, error="PatternQueryFailure")
            with self.state.connection() as db:
                db.execute(
                    "UPDATE pattern_job_receipts SET status='FAILED' WHERE job_id=?",
                    (job.id,),
                )
            self.state.finish(
                job.id,
                error="Pattern query failed; immutable evidence and checkpoints retained",
            )

    def _verify_models(
        self,
        user: User,
        prepared: JsonRecord,
        fit: JsonValue,
        result: JsonRecord,
        job_id: str,
    ) -> None:
        self.models.verify_fit(user, fit, prepared, job_id)
        if (
            "model_recipe" not in result
            or result["model_recipe"] != prepared["model_recipe"]
            or "model_fit" not in result
            or result["model_fit"] != fit
            or "model_artifact" not in result
        ):
            raise PatternError("PATTERN_MODEL_RESULT_BINDING")
        self.models.verify_artifact(fit, result["model_artifact"], result)

    def _complete_query(
        self, user: User, job: Job, operation: str, experiment: str
    ) -> None:
        expected: JsonRecord = {"job_id": job.id, "experiment_id": experiment}
        with self.state.connection() as db:
            row = db.execute(
                "SELECT status,result FROM data_operations WHERE id=? AND owner_id=?",
                (operation, user.id),
            ).fetchone()
        if row is not None and row["status"] == "RUNNING":
            self._finish(user, operation, expected)
        elif (
            row is None
            or row["status"] != "SUCCEEDED"
            or parse_json_document(row["result"]) != expected
        ):
            raise AccessError("Pattern completed operation binding unavailable")
        with self.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT status FROM jobs WHERE id=? AND owner_id=? AND experiment_id=?",
                (job.id, user.id, experiment),
            ).fetchone()
            if current is None or current[0] not in {"RUNNING", "SUCCEEDED"}:
                raise AccessError("Pattern completed job binding unavailable")
            db.execute(
                "UPDATE pattern_job_receipts SET status='COMPLETED' WHERE job_id=?",
                (job.id,),
            )
            db.execute(
                "UPDATE jobs SET status='SUCCEEDED',error=NULL WHERE id=?",
                (job.id,),
            )

    def job(self, user: User, identity: str) -> JsonRecord:
        job = self.state.job(user, identity)
        if job.config.get("kind") == "PATTERN_JOB" and job.status not in {
            "QUEUED",
            "RUNNING",
            "CANCELLED",
        }:
            with self.quality.inspection(user):
                return self._job(user, job)
        return self._job(user, job)

    def _job(self, user: User, job: Job) -> JsonRecord:
        identity = job.id
        if job.config.get("kind") == "PATTERN_CORPUS":
            self._selection_owner(user, cast(str, job.config.get("selection_digest")))
            with self.state.connection() as db:
                row = db.execute(
                    "SELECT r.status,r.progress,r.operation_id,d.result FROM pattern_job_receipts r LEFT JOIN data_operations d ON d.id=r.operation_id AND d.owner_id=? WHERE r.job_id=?",
                    (user.id, job.id),
                ).fetchone()
            detail: JsonValue = None
            if row and row["result"]:
                result = _record(parse_json_document(row["result"]))
                detail = self.corpus(user, cast(str, result["dataset_id"]))
            return {
                "job": cast(JsonValue, asdict(job)),
                "run": None,
                "corpus": detail,
                "operation_id": row["operation_id"] if row else None,
                "progress": parse_json_document(row["progress"])
                if row and row["progress"]
                else None,
                "resume_policy": "NO_AUTOMATIC_REPLAY; EXPLICIT_NEW_BUILD_REQUIRED",
            }
        if job.config.get("kind") != "PATTERN_JOB" or set(job.config) != {
            "kind",
            "prepared_id",
        }:
            raise AccessError("Pattern job unavailable")
        with self.state.connection() as db:
            receipt = db.execute(
                "SELECT * FROM pattern_job_receipts WHERE job_id=?", (identity,)
            ).fetchone()
            if not db.execute(
                "SELECT 1 FROM pattern_prepared WHERE id=? AND owner_id=?",
                (job.config["prepared_id"], user.id),
            ).fetchone():
                raise AccessError("Pattern preparation unavailable")
        if job.status in {"QUEUED", "RUNNING", "CANCELLED"}:
            return {
                "job": cast(JsonValue, asdict(job)),
                "run": None,
                "prepared_id": cast(str, job.config["prepared_id"]),
                "checkpoint_digest": receipt["checkpoint_digest"] if receipt else None,
                "progress": parse_json_document(receipt["progress"])
                if receipt and receipt["progress"]
                else None,
                "inspection": "OPERATIONAL_PROGRESS_ONLY; completed result verifies full input graph",
            }
        prepared = self._prepared(user, cast(str, job.config["prepared_id"]))
        run = self.lab.get_run(job.experiment_id) if job.experiment_id else None
        model_fit = (
            parse_json_document(receipt["model_binding"])
            if receipt and receipt["model_binding"]
            else None
        )
        if model_fit is not None or run is not None:
            self.models.verify_fit(user, model_fit, prepared, job.id)
        if run is not None:
            config = _record(run["configuration"])
            if (
                config != self._lab_config(prepared, model_fit)
                or receipt is None
                or receipt["prepared_id"] != prepared["prepared_id"]
            ):
                raise PatternError("PATTERN_RETAINED_RUN_GRAPH_MISMATCH")
            retained_result = run["result"]
            if run["evaluation_outcome"] != "FAILED":
                canonical_binding = self._binding(
                    cast(str, job.experiment_id), prepared
                )
                retained_result = self._verify_result(
                    retained_result, prepared, canonical_binding
                )
                self._verify_models(user, prepared, model_fit, retained_result, job.id)
                binding = _record(parse_json_document(str(receipt["binding"])))
                if (
                    retained_result["canonical_binding"] != binding
                    or binding != canonical_binding.to_record()
                    or binding["experiment_id"] != job.experiment_id
                    or retained_result["native_input_graph"] != config["input_graph"]
                    or retained_result["prepared_digest"] != prepared["prepared_digest"]
                    or retained_result["configuration"] != prepared["configuration"]
                    or retained_result["corpus_manifest"]
                    != _record(prepared["corpus"])["manifest_digest"]
                    or retained_result["parent_snapshots"]
                    != _record(prepared["corpus"])["parents"]
                ):
                    raise PatternError("PATTERN_RETAINED_RESULT_GRAPH_MISMATCH")
        return {
            "job": cast(JsonValue, asdict(job)),
            "run": run,
            "prepared_id": prepared["prepared_id"],
            "model_recipe": prepared["model_recipe"],
            "model_fit": model_fit,
            "checkpoint_digest": receipt["checkpoint_digest"] if receipt else None,
            "progress": parse_json_document(receipt["progress"])
            if receipt and receipt["progress"]
            else None,
            "resume_policy": "NO_AUTOMATIC_REPLAY; INTERRUPTED_ATTEMPTS_REQUIRE_NEW_COUNTED_JOB",
        }

    def recover(self) -> None:
        """Call under the host runtime lease, after stopping prior workers."""
        with self.state.connection() as db:
            db.execute(
                "UPDATE pattern_job_receipts SET status='INTERRUPTED' WHERE status='STARTED'"
            )
