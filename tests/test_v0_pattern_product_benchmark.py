"""Opt-in actual Parquet/corpus/checkpoint scale proof, never empirical research.

Run this file --output NEW_D_DIRECTORY. Normal pytest runs the independent small
disk oracle only. Software fixture IDs/digests do not pretend to be Item8 records.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from test_v0_patterns_benchmark import StreamEvidence, _blocks, _motif, _peak_bytes

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.data_quality import PartitionSelection, SelectedSnapshot
from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.markets.calendars import sessions
from quant_hunter.patterns.contracts import CausalFrame
from quant_hunter.patterns.corpus import Corpus, CorpusConfig, CorpusStore
from quant_hunter.patterns.product import (
    FrozenPatternBinding,
    PatternJobCancelledError,
    PatternJobConfig,
    PatternProduct,
)
from quant_hunter.provenance.hashing import sha256_canonical_json
from quant_hunter.storage import ImmutableObjectStore

STEP = 60_000_000_000
SEED = 20261005
RAM_LIMIT = 1024**3
DISK_LIMIT = 512 * 1024**2
CASE_SECONDS = 180
CHILD_SECONDS = 210
type Record = dict[str, Any]


def _iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1e9, UTC).isoformat().replace("+00:00", "Z")


class Guard:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.started = self.last = time.monotonic()

    def __call__(self, record: dict[str, int | str]) -> None:
        elapsed = time.monotonic() - self.started
        peak = _peak_bytes()
        if elapsed > CASE_SECONDS or peak > RAM_LIMIT:
            raise RuntimeError("SYNTHETIC_BENCHMARK_TIME_OR_RAM_CAP")
        if time.monotonic() - self.last >= 5:
            used = sum(
                path.stat().st_size for path in self.root.rglob("*") if path.is_file()
            )
            if used > DISK_LIMIT:
                raise RuntimeError("SYNTHETIC_BENCHMARK_DISK_CAP")
            print(
                json.dumps(
                    {
                        **record,
                        "seconds": round(elapsed, 3),
                        "peak_bytes": peak,
                        "actual_disk_bytes": used,
                    }
                ),
                flush=True,
            )
            self.last = time.monotonic()


def _publish_json(objects: ImmutableObjectStore, record: Record) -> str:
    return objects.publish(canonicalize_json(cast(JsonRecord, record))).digest


def _fixture_parents(
    store: CorpusStore,
    frames: Iterator[CausalFrame],
    *,
    profile: Record,
    guard: Guard,
    evidence: StreamEvidence | None = None,
) -> tuple[PartitionSelection, Record]:
    """Write genuine source Parquet plus explicit software-only graph fixtures."""
    parents: list[SelectedSnapshot] = []
    instrument_id = new_typed_id(RegistryKind.INSTRUMENT)
    instrument_digest = _publish_json(
        store.objects,
        {
            "software_fixture": True,
            "instrument_id": instrument_id,
            "calendar": profile,
            "seed": SEED,
            "authority": "NOT_CANONICAL_REGISTRY_OR_EMPIRICAL_ADMISSION",
        },
    )
    profile_digest = sha256_canonical_json(cast(JsonRecord, profile))
    values_hash, time_hash = sha256(), sha256()
    raw_bytes = 0
    rows = 0
    previous_close: int | None = None
    gaps: list[JsonValue] = []
    for index, frame in enumerate(frames):
        prices = np.round(frame.values[:, 0], 6)
        close = frame.close_ns
        # Read-ahead generation below replaces only the final query with the same
        # planted motif. Every other finite software observation remains causal.
        table = pa.table(
            {
                "close_at": pa.array(close, type=pa.timestamp("ns", tz="UTC")),
                "available_at": pa.array(
                    frame.available_ns, type=pa.timestamp("ns", tz="UTC")
                ),
                "close": pa.array(prices, type=pa.float64()),
            }
        )
        output = pa.BufferOutputStream()
        pq.write_table(
            table,
            output,
            compression="zstd",
            use_dictionary=False,
            row_group_size=len(prices),
            data_page_version="1.0",
        )
        raw = output.getvalue().to_pybytes()
        if len(raw) > 2_000_000 or len(prices) > 100_000:
            raise AssertionError("Each source fixture must fit unchanged upload limits")
        blob = store.objects.publish(raw)
        raw_bytes += blob.byte_size
        if raw_bytes > DISK_LIMIT // 3:
            raise RuntimeError("SYNTHETIC_SOURCE_DISK_CAP")
        bounds: JsonRecord = {
            "start": _iso(int(close[0]) - STEP),
            "end": _iso(int(close[-1])),
        }
        dataset_id = new_typed_id(RegistryKind.DATASET)
        record_digest = _publish_json(
            store.objects,
            {
                "software_fixture": True,
                "dataset_id": dataset_id,
                "normalized_digest": blob.digest,
                "row_count": len(prices),
                "bounds": bounds,
                "source": "DETERMINISTIC_SYNTHETIC_GENERATOR",
            },
        )
        quality_digest = _publish_json(
            store.objects,
            {
                "software_fixture": True,
                "record_digest": record_digest,
                "admission": "SYNTHETIC_SOFTWARE_ONLY",
                "causal_eligible": True,
                "limits": "ISOLATED_SOFTWARE_TEST_ONLY_NOT_QUALITYSERVICE_CERTIFICATION",
            },
        )
        calendar_digest = _publish_json(
            store.objects,
            {
                "software_fixture": True,
                "bounds": bounds,
                "calendar_profile": profile,
                "calendar_profile_digest": profile_digest,
            },
        )
        parents.append(
            SelectedSnapshot(
                dataset_id,
                record_digest,
                blob.digest,
                quality_digest,
                instrument_id,
                instrument_digest,
                calendar_digest,
                len(prices),
                bounds,
                STEP,
                ("close",),
                "SYNTHETIC",
                "SYNTHETIC_SOFTWARE_ONLY",
                True,
                ("SYNTHETIC_SOFTWARE_TEST",),
            )
        )
        if previous_close is not None and int(close[0]) - STEP > previous_close:
            gaps.append(
                {
                    "after_parent": index - 1,
                    "before_parent": index,
                    "start": _iso(previous_close),
                    "end": _iso(int(close[0]) - STEP),
                }
            )
        previous_close = int(close[-1])
        rows += len(prices)
        values_hash.update(prices.astype("<f8").tobytes())
        time_hash.update(close.astype("<i8").tobytes())
        guard({"stage": "WRITE_SOURCE_PARQUET", "rows": rows, "parents": len(parents)})
    bounds = {"start": parents[0].bounds["start"], "end": parents[-1].bounds["end"]}
    manifest: Record = {
        "schema_version": "qh-owned-partition-selection-v1",
        "purpose": "PATTERN_CAUSAL",
        "software_fixture": True,
        "total_rows": rows,
        "bounds": bounds,
        "parent_snapshots": [parent.to_record() for parent in parents],
        "calendar_profile": profile,
        "calendar_profile_digest": profile_digest,
        "boundaries": gaps,
        "no_implicit_continuity": True,
        "no_collective_dataset_identity": True,
        "calendar_rules_evidence": [
            {
                **schedule,
                "limitations": list(cast(tuple[str, ...], schedule["limitations"])),
            }
            for schedule in evidence.schedules
        ]
        if evidence
        else [],
        "limitations": [
            "This test constructs typed fixture references; host authentication, QualityService admission and Item8 registration are tested separately."
        ],
    }
    digest = _publish_json(store.objects, manifest)
    selection = PartitionSelection(
        digest,
        rows,
        bounds,
        tuple(parents),
        profile_digest,
        instrument_id,
        instrument_digest,
        STEP,
        ("close",),
        "SYNTHETIC",
        True,
    )
    return selection, {
        "source_parquet_bytes": raw_bytes,
        "parent_files": len(parents),
        "source_values_sha256": values_hash.hexdigest(),
        "source_times_sha256": time_hash.hexdigest(),
    }


def _read_parents(
    store: CorpusStore, selection: PartitionSelection
) -> Iterator[tuple[int, Any]]:
    for index, parent in enumerate(selection.parent_snapshots):
        # Read and rehash the exact persisted bytes, not the generator arrays.
        raw = store.objects.read_bytes(parent.normalized_digest)
        parquet = pq.ParquetFile(pa.BufferReader(raw))
        if parquet.metadata.num_rows != parent.row_count:
            raise AssertionError("Fixture parent row count differs")
        for batch in parquet.iter_batches(batch_size=4096):
            yield index, batch


def _with_final_query(evidence: StreamEvidence) -> Iterator[CausalFrame]:
    frames = iter(_blocks(evidence))
    pending = next(frames)
    for frame in frames:
        yield pending
        pending = frame
    values = pending.values.copy()
    values[-32:, 0] = _motif()
    yield CausalFrame(
        values, pending.close_ns, pending.available_ns, STEP, pending.provenance
    )


def _execute(
    product: PatternProduct,
    corpus: Corpus,
    config: PatternJobConfig,
    *,
    guard: Guard,
    resume: bool = False,
) -> Record:
    # Deliberate fixtures: never represented as canonically registered EXPs.
    prepared = product.prepare(
        corpus.manifest_digest,
        config,
        pattern_id=new_typed_id(RegistryKind.PATTERN),
        code_revision="a" * 40,
        environment_digest=sha256_canonical_json({"software_fixture": True}),
    )
    binding = FrozenPatternBinding(
        new_typed_id(RegistryKind.EXPERIMENT),
        sha256_canonical_json({"software_fixture": "EXPERIMENT"}),
        sha256_canonical_json(
            {"software_fixture": "WRAPPED_CONFIG", "prepared": prepared.digest}
        ),
        prepared.digest,
        cast(str, prepared.to_record()["pattern_id"]),
    )
    checkpoints: list[str] = []
    resume_digest = None
    if resume:
        try:
            product.execute_registered(
                prepared.digest,
                binding=binding,
                progress=guard,
                checkpoint=checkpoints.append,
                cancelled=lambda: len(checkpoints) >= 2,
            )
        except PatternJobCancelledError as error:
            resume_digest = error.checkpoint_digest
        if not resume_digest or len(checkpoints) != 2:
            raise AssertionError("Expected retained bounded cancellation checkpoint")
    output = cast(
        Record,
        product.execute_registered(
            prepared.digest,
            binding=binding,
            resume_digest=resume_digest,
            progress=guard,
        ),
    )
    output["benchmark_resume_from"] = resume_digest
    return output


def _configuration(
    store: CorpusStore, corpus: Corpus, **changes: Any
) -> PatternJobConfig:
    query = store.window(corpus, corpus.row_count - 32, corpus.row_count, 2**63 - 1)
    # First 128 bars fit inside every measured exchange/FX session.
    train = store.frame(corpus, 0, min(128, corpus.row_count - 32))
    return replace(
        PatternJobConfig(
            "PAT-13",
            corpus.row_count - 32,
            corpus.row_count,
            0,
            len(train.values),
            query.available_ns,
            int(train.available_ns[-1]),
            query.start_ns,
            maximum_distance=1e-10,
            candidate_cap=64,
            seed=SEED,
        ),
        **changes,
    )


def _small_oracle(root: Path) -> Record:
    from quant_hunter.patterns.contracts import Provenance

    guard = Guard(root)
    store = CorpusStore(ImmutableObjectStore(root / "objects"))
    rng = np.random.default_rng(SEED)
    values = np.round(100 + rng.normal(0, 1, 256), 6)
    start = int(datetime(2024, 1, 2, tzinfo=UTC).timestamp()) * 10**9
    closes = start + np.arange(1, 257, dtype=np.int64) * STEP
    provenance = Provenance("SYNTHETIC-software", "fixture", "SYNTHETIC-software", "1m")
    frame = CausalFrame(
        values[:, None], closes, closes + 1_000_000_000, STEP, provenance
    )
    profile = {
        "calendar_id": "SYNTHETIC_CONTINUOUS",
        "anchor": "UTC",
        "timezone": "UTC",
        "timezone_package": "fixture",
        "package": "fixture",
        "package_version": "1",
    }
    selection, disk = _fixture_parents(
        store, iter((frame,)), profile=profile, guard=guard
    )
    corpus = store.build_selection(
        new_typed_id(RegistryKind.DATASET),
        selection,
        _read_parents(store, selection),
        config=CorpusConfig(block_rows=37),
        progress=guard,
    )
    product = PatternProduct(store)
    config = _configuration(
        store,
        corpus,
        mode="EXACT_SMALL",
        normalization="RAW",
        candidate_cap=256,
        maximum_distance=10,
        max_results=4,
    )
    exact = _execute(product, corpus, config, guard=guard, resume=True)
    direct = _execute(product, corpus, config, guard=guard)
    assert exact["occurrences"] == direct["occurrences"]
    assert exact["exposure"] == direct["exposure"]
    query = values[-32:]
    # Independent exhaustive RMS ranking; event support includes 4 outcome bars.
    ranked = sorted(
        (float(np.sqrt(np.mean((values[i : i + 32] - query) ** 2))), i)
        for i in range(256 - 32 - 4 + 1)
        if i + 36 <= 224
    )
    chosen: list[tuple[float, int]] = []
    for distance, index in ranked:
        if all(index + 36 <= old or old + 36 <= index for _, old in chosen):
            chosen.append((distance, index))
        if len(chosen) == 4:
            break
    actual = [
        (row["distance"], (int(row["start_ns"]) - start) // STEP)
        for row in exact["occurrences"]
    ]
    assert [index for _, index in actual] == [index for _, index in chosen]
    np.testing.assert_allclose(
        [distance for distance, _ in actual],
        [distance for distance, _ in chosen],
        atol=1e-12,
    )
    oracle_ids = {index for _, index in chosen}
    approximate: list[Record] = []
    for cap in (4, 16, 64, 256):
        result = _execute(
            product,
            corpus,
            replace(config, mode="APPROXIMATE", candidate_cap=cap),
            guard=guard,
        )
        ids = {(int(row["start_ns"]) - start) // STEP for row in result["occurrences"]}
        approximate.append(
            {
                "candidate_cap": cap,
                "recall_at_4": len(ids & oracle_ids) / len(oracle_ids),
                "false_negatives": sorted(oracle_ids - ids),
                "non_oracle_top4": sorted(ids - oracle_ids),
                "actual_exposure": result["exposure"],
                "checkpoint_bytes": result["query_checkpoint_bytes"],
            }
        )
    unknown = _execute(
        product, corpus, replace(config, maximum_distance=0), guard=guard
    )
    assert unknown["state"] == "UNKNOWN" and unknown["occurrences"] == []
    return {
        "status": "PASS",
        "synthetic_only": True,
        "independent_oracle": chosen,
        "exact": actual,
        "resume_equivalent": True,
        "approximate": approximate,
        "null_zero_distance": "UNKNOWN",
        **disk,
        "corpus_parquet_bytes": corpus.parquet_bytes,
        "peak_process_bytes": _peak_bytes(),
        "seconds": time.monotonic() - guard.started,
    }


def test_disk_exact_oracle_approximate_recall_and_resume(tmp_path: Path) -> None:
    report = _small_oracle(tmp_path)
    assert report["status"] == "PASS" and report["source_parquet_bytes"] > 0
    assert any(row["false_negatives"] for row in report["approximate"])


CASES = {
    "xnys-day": ("XNYS", date(2015, 1, 2), date(2015, 1, 2)),
    "xnys-year": ("XNYS", date(2015, 1, 1), date(2015, 12, 31)),
    "xnys-decade": ("XNYS", date(2015, 1, 1), date(2024, 12, 31)),
    "fx-decade": ("FX_NY_17", date(2015, 1, 1), date(2024, 12, 31)),
}


def _case(name: str, root: Path) -> Record:
    if name == "small-oracle":
        return _small_oracle(root)
    if name == "two-asset-decades":
        started = time.monotonic()
        assets: dict[str, Record] = {}
        for asset in ("xnys-decade", "fx-decade"):
            target = root / asset
            target.mkdir()
            assets[asset] = _case(asset, target)
        disk_bytes = sum(
            path.stat().st_size for path in root.rglob("*") if path.is_file()
        )
        if (
            disk_bytes > DISK_LIMIT
            or _peak_bytes() > RAM_LIMIT
            or time.monotonic() - started > CASE_SECONDS
        ):
            raise RuntimeError("TWO_ASSET_RESOURCE_CAP")
        return {
            "status": "PASS",
            "evidence_mode": "SYNTHETIC",
            "empirical_validation": "MISSING",
            "sequential_assets": assets,
            "query_variant_count": 2,
            "rows": sum(item["rows"] for item in assets.values()),
            "source_parquet_bytes": sum(
                item["source_parquet_bytes"] for item in assets.values()
            ),
            "corpus_parquet_bytes": sum(
                item["corpus_parquet_bytes"] for item in assets.values()
            ),
            "query_checkpoint_bytes": sum(
                item["query_checkpoint_bytes"] for item in assets.values()
            ),
            "actual_total_disk_bytes": disk_bytes,
            "peak_process_bytes": _peak_bytes(),
            "total_seconds": time.monotonic() - started,
            "limitations": [
                "Two actual sequential asset corpora and queries; no cross-asset independence or pooled empirical inference claimed."
            ],
        }
    calendar, start, end = CASES[name]
    guard = Guard(root)
    store = CorpusStore(ImmutableObjectStore(root / "objects"))
    evidence = StreamEvidence(calendar, start, end)
    rules = sessions(calendar, start, min(end, date(start.year, 12, 31))).to_record()
    profile = {
        key: rules[key]
        for key in (
            "calendar_id",
            "anchor",
            "timezone",
            "timezone_package",
            "package",
            "package_version",
        )
    }
    selection, disk = _fixture_parents(
        store,
        _with_final_query(evidence),
        profile=profile,
        guard=guard,
        evidence=evidence,
    )
    generated_seconds = time.monotonic() - guard.started
    build_start = time.monotonic()
    corpus = store.build_selection(
        new_typed_id(RegistryKind.DATASET),
        selection,
        _read_parents(store, selection),
        config=CorpusConfig(block_rows=32768, max_disk_bytes=DISK_LIMIT // 3),
        progress=guard,
    )
    build_seconds = time.monotonic() - build_start
    product = PatternProduct(store)
    config = _configuration(store, corpus)
    query_start = time.monotonic()
    result = _execute(
        product, corpus, config, guard=guard, resume=len(corpus.partitions) > 2
    )
    query_seconds = time.monotonic() - query_start
    planted = set(evidence.planted_start_ns)
    actual = {int(row["start_ns"]) for row in result["occurrences"]}
    expected = {
        stamp
        for stamp in planted
        if stamp + 36 * STEP <= int(result["query"]["start_ns"])
    }
    assert actual == expected, (actual, expected)
    assert result["exposure"]["rows_visited"] == evidence.rows
    result_digest = _publish_json(store.objects, result)
    actual_disk = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    if actual_disk > DISK_LIMIT or _peak_bytes() > RAM_LIMIT:
        raise RuntimeError("SYNTHETIC_BENCHMARK_FINAL_RESOURCE_CAP")
    return {
        "status": "PASS",
        "evidence_mode": "SYNTHETIC",
        "empirical_validation": "MISSING",
        "calendar_id": calendar,
        "label_start": start.isoformat(),
        "label_end": end.isoformat(),
        "actual_bounds": selection.bounds,
        "rows": evidence.rows,
        "sessions": evidence.sessions,
        "calendar_schedules": evidence.schedules,
        "seed": SEED,
        "generator_round_decimals": 6,
        "source_generation_and_write_seconds": generated_seconds,
        "corpus_build_seconds": build_seconds,
        "query_resume_seconds": query_seconds,
        "total_seconds": time.monotonic() - guard.started,
        "peak_process_bytes": _peak_bytes(),
        **disk,
        "corpus_parquet_bytes": corpus.parquet_bytes,
        "corpus_manifest_bytes": store.objects.get(corpus.manifest_digest).byte_size,
        "source_selection_bytes": store.objects.get(
            selection.manifest_digest
        ).byte_size,
        "query_checkpoint_bytes": result["query_checkpoint_bytes"],
        "actual_total_disk_bytes": actual_disk,
        "partition_count": len(corpus.partitions),
        "gap_count": corpus.gap_count,
        "planted_motifs": len(expected),
        "retrieved_planted_motifs": len(actual & expected),
        "planted_motif_recall": len(actual & expected) / len(expected),
        "false_positive_motifs": len(actual - expected),
        "search_configuration": config.to_record(),
        "actual_exposure": result["exposure"],
        "result_digest": result_digest,
        "corpus_manifest_digest": corpus.manifest_digest,
        "selection_manifest_digest": selection.manifest_digest,
        "checkpoint_digest": result["checkpoint_digest"],
        "resumed_from": result["benchmark_resume_from"],
        "limits": {
            "peak_ram_bytes": RAM_LIMIT,
            "disk_bytes": DISK_LIMIT,
            "case_seconds": CASE_SECONDS,
        },
        "limitations": [
            "Synthetic planted-motif recall is not recall over unknown real market patterns.",
            "All partitions are persisted and reread; no network acquisition or scientific Item8 evaluation occurs.",
            "FX_NY_17 is an explicit OTC convention; its holiday behavior is unknown, not a universal exchange calendar.",
            "The exact time/row manifest is reusable; candidate PAA pools/checkpoints are per query, not a global ANN index.",
            "No interpolation or session-gap window is admitted.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--case", choices=["small-oracle", *CASES, "two-asset-decades"], action="append"
    )
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    if os.name == "nt" and root.drive.upper() != "D:":
        raise ValueError("All benchmark outputs must remain on Disk D")
    root.mkdir(parents=True, exist_ok=False)
    if args.child:
        try:
            report = _case(args.case[0], root)
        except Exception as error:
            report = {
                "status": "FAILED",
                "error_type": type(error).__name__,
                "error": str(error),
                "peak_process_bytes": _peak_bytes(),
                "evidence_mode": "SYNTHETIC",
            }
        (root / "result.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "case": args.case[0],
                    "status": report["status"],
                    "report": str(root / "result.json"),
                }
            ),
            flush=True,
        )
        return 0 if report["status"] == "PASS" else 1
    selected = args.case or ["small-oracle", *CASES, "two-asset-decades"]
    reports: dict[str, Record] = {}
    for name in selected:
        try:
            process = subprocess.run(  # noqa: S603 - fixed interpreter/self and closed case enum
                [
                    sys.executable,
                    __file__,
                    "--child",
                    "--case",
                    name,
                    "--output",
                    str(root / name),
                ],
                check=False,
                timeout=CHILD_SECONDS,
            )
            path = root / name / "result.json"
            reports[name] = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.exists()
                else {"status": "FAILED", "exit": process.returncode}
            )
        except subprocess.TimeoutExpired:
            reports[name] = {
                "status": "FAILED",
                "reason": "PARENT_TIMEOUT",
                "seconds_cap": CHILD_SECONDS,
            }
    source_root = Path(__file__).resolve().parents[1]
    files = [
        Path(__file__),
        *(
            source_root / "src/quant_hunter/patterns" / name
            for name in ("corpus.py", "codec.py", "product.py")
        ),
    ]
    summary = {
        "evidence_mode": "SYNTHETIC",
        "empirical_validation": "MISSING",
        "cases": reports,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": version("numpy"),
            "pyarrow": version("pyarrow"),
            "exchange_calendars": version("exchange_calendars"),
            "tzdata": version("tzdata"),
        },
        "source_sha256": {
            str(path.relative_to(source_root)): sha256(path.read_bytes()).hexdigest()
            for path in files
        },
        "authority": "Software-only fixtures. Canonical host registration/authentication/admission are separate integration evidence.",
    }
    (root / "benchmark.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(str(root / "benchmark.json"), flush=True)
    return 0 if all(report["status"] == "PASS" for report in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
