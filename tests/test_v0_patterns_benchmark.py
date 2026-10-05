"""Opt-in synthetic scale evidence; normal pytest runs only the small oracles.

Execute this file with --output NEW_DIRECTORY for actual calendar-scale runs.
No acquisition, research registration, persistent index or production IO is provided.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import cast

import numpy as np

from quant_hunter.patterns import (
    CausalFrame,
    PatternWindow,
    Provenance,
    SearchCancelledError,
    SearchConfig,
    SearchEngine,
    search_blocks,
)
from quant_hunter.patterns.contracts import Floats

STEP = 60_000_000_000
SEED = 20261005
BLOCK_ROWS = 32768
RAM_LIMIT = 1024**3
SECONDS_LIMIT = 60
type Record = dict[str, object]


def _ns(value: datetime) -> int:
    return int(value.timestamp()) * 1_000_000_000


def _iso(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, UTC).isoformat()


def _motif() -> Floats:
    x = np.arange(32, dtype=np.float64)
    return 100 + 0.03 * x + 0.5 * np.sin(x * 0.61)


def _query(provenance: Provenance) -> PatternWindow:
    start = _ns(datetime(2025, 1, 2, 15, tzinfo=UTC))
    return PatternWindow(
        _motif()[:, None],
        start,
        start + 32 * STEP,
        start + 32 * STEP + 1_000_000_000,
        STEP,
        provenance,
    )


def _peak_bytes() -> int:
    """Whole-process peak working set, including NumPy/calendar dependencies."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        process = kernel.GetCurrentProcess
        process.restype = wintypes.HANDLE
        api = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        api.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not api(process(), ctypes.byref(counters), counters.cb):
            raise OSError("Process peak memory counter unavailable")
        return int(counters.PeakWorkingSetSize)
    else:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)


@dataclass
class StreamEvidence:
    calendar_id: str
    start: date
    end: date
    rows: int = 0
    sessions: int = 0
    planted_start_ns: list[int] = field(default_factory=list)
    schedules: list[Record] = field(default_factory=list)
    value_digest: str = ""
    timestamp_digest: str = ""


def _blocks(evidence: StreamEvidence) -> Iterator[CausalFrame]:
    from quant_hunter.markets.calendars import sessions

    rng = np.random.default_rng(SEED)
    provenance = Provenance(
        f"SYNTHETIC-{evidence.calendar_id}",
        f"seed{SEED}-v1",
        f"SYNTHETIC-{evidence.calendar_id}",
        "1m",
    )
    pending_values = np.empty(0, dtype=np.float64)
    pending_closes = np.empty(0, dtype=np.int64)
    values_hash, times_hash = sha256(), sha256()
    for year in range(evidence.start.year, evidence.end.year + 1):
        start, end = (
            max(evidence.start, date(year, 1, 1)),
            min(evidence.end, date(year, 12, 31)),
        )
        schedule = sessions(evidence.calendar_id, start, end)
        evidence.schedules.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "digest": schedule.digest,
                "sessions": len(schedule.sessions),
                "package": schedule.package,
                "version": schedule.package_version,
                "timezone_version": schedule.timezone_version,
                "limitations": schedule.limitations,
            }
        )
        for index, session in enumerate(schedule.sessions):
            count = int((session.close_at - session.open_at).total_seconds()) // 60
            close = (
                _ns(session.open_at) + np.arange(1, count + 1, dtype=np.int64) * STEP
            )
            # Software test signal. It does not model or assert market-return behavior.
            values = 100 + rng.normal(0, 0.05, size=count).cumsum()
            if index == 0:
                values[40:72] = _motif()
                evidence.planted_start_ns.append(int(close[40]) - STEP)
            evidence.rows += count
            evidence.sessions += 1
            values_hash.update(values.astype("<f8").tobytes())
            times_hash.update(close.astype("<i8").tobytes())
            pending_values = np.concatenate((pending_values, values))
            pending_closes = np.concatenate((pending_closes, close))
            while len(pending_values) >= BLOCK_ROWS:
                stamps = pending_closes[:BLOCK_ROWS]
                yield CausalFrame(
                    pending_values[:BLOCK_ROWS, None],
                    stamps,
                    stamps + 1_000_000_000,
                    STEP,
                    provenance,
                )
                pending_values = pending_values[BLOCK_ROWS:].copy()
                pending_closes = pending_closes[BLOCK_ROWS:].copy()
    if len(pending_values):
        yield CausalFrame(
            pending_values[:, None],
            pending_closes,
            pending_closes + 1_000_000_000,
            STEP,
            provenance,
        )
    evidence.value_digest, evidence.timestamp_digest = (
        values_hash.hexdigest(),
        times_hash.hexdigest(),
    )


def _small_comparison() -> Record:
    """Independent dense RMS + overlap oracle, not a comparison to itself."""
    provenance = Provenance("SYNTHETIC-small", "v1", "SYNTHETIC-small", "1m")
    rng = np.random.default_rng(SEED)
    values = 100 + rng.normal(0, 1, 512)
    start = _ns(datetime(2024, 1, 2, 15, tzinfo=UTC))
    close = start + np.arange(1, 513, dtype=np.int64) * STEP
    data = CausalFrame(values[:, None], close, close, STEP, provenance)
    query = _query(provenance)
    raw_query = query.values[:, 0]
    q = (raw_query - raw_query.mean()) / raw_query.std()
    dense: list[tuple[float, int]] = []
    for offset in range(len(values) - 35):
        raw = values[offset : offset + 32]
        z = (raw - raw.mean()) / raw.std()
        distance = float(
            np.sqrt(sum((float(z[i]) - float(q[i])) ** 2 for i in range(32)) / 32)
        )
        dense.append((distance, offset))
    selected: list[tuple[float, int]] = []
    for distance, offset in sorted(dense):
        if all(
            offset + 36 <= previous or previous + 36 <= offset
            for _, previous in selected
        ):
            selected.append((distance, offset))
            if len(selected) == 8:
                break
    config = SearchConfig(
        mode="EXACT_SMALL",
        horizon=4,
        candidate_cap=512,
        max_results=8,
        maximum_distance=2,
        cost_bps=7,
    )
    exact = search_blocks((data,), query, config, decision_ns=query.available_ns)
    expected = [start + offset * STEP for _, offset in selected]
    assert [hit.window.start_ns for hit in exact.hits] == expected
    assert np.allclose(
        [hit.distance for hit in exact.hits],
        [distance for distance, _ in selected],
        rtol=1e-12,
    )
    approximate: list[Record] = []
    for cap in (8, 32, 128):
        trial = SearchConfig(
            horizon=4, candidate_cap=cap, max_results=8, maximum_distance=2, cost_bps=7
        )
        result = search_blocks((data,), query, trial, decision_ns=query.available_ns)
        returned = [hit.window.start_ns for hit in result.hits]
        intersection = set(expected) & set(returned)
        approximate.append(
            {
                "candidate_cap": cap,
                "recall_at_8": len(intersection) / len(expected),
                "false_negatives": len(set(expected) - set(returned)),
                "returned_events": len(returned),
                "exact_reranks": result.exact_reranks,
                "same_order_as_exact": returned == expected,
            }
        )
    unknown = search_blocks(
        (data,),
        query,
        SearchConfig(maximum_distance=1e-10, horizon=4),
        decision_ns=query.available_ns,
    )
    assert unknown.state == "UNKNOWN" and not unknown.hits
    return {
        "status": "PASS",
        "rows": 512,
        "eligible_windows": len(dense),
        "independent_dense_ranking_and_overlap": True,
        "exact_events": len(expected),
        "approximate": approximate,
        "noise_only_control": unknown.state,
        "limitations": "Single seeded tiny corpus; recall is not a general retrieval guarantee.",
    }


def _source_snapshot() -> Record:
    root = Path(__file__).resolve().parents[1]
    paths = [
        *sorted((root / "src/quant_hunter/patterns").glob("*.py")),
        root / "src/quant_hunter/markets/calendars.py",
        Path(__file__).resolve(),
    ]
    return {
        str(path.relative_to(root)).replace("\\", "/"): sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths
    }


def _run_stream(calendar: str, start: date, end: date) -> Record:
    started = time.perf_counter()
    evidence = StreamEvidence(calendar, start, end)
    provenance = Provenance(
        f"SYNTHETIC-{calendar}", f"seed{SEED}-v1", f"SYNTHETIC-{calendar}", "1m"
    )
    query = _query(provenance)
    config = SearchConfig(
        horizon=4,
        cost_bps=7,
        candidate_cap=256,
        max_results=20,
        maximum_distance=1e-10,
        max_working_bytes=16 * 1024**2,
        max_rows=5_000_000,
    )
    engine = SearchEngine(query, config, query.available_ns)
    resumed_at = 0
    checkpoint_bytes = 0
    last_notice = started
    for block in _blocks(evidence):
        if time.perf_counter() - started > SECONDS_LIMIT or _peak_bytes() > RAM_LIMIT:
            raise RuntimeError(
                "Synthetic benchmark time/RAM bound exceeded; no complete result"
            )
        if engine.snapshot().progress.blocks == 1:
            snapshot = engine.snapshot()
            try:
                engine.consume(block, cancelled=lambda: True)
            except SearchCancelledError:
                assert engine.snapshot().progress == snapshot.progress
            else:
                raise AssertionError("Cancellation was ignored")
            engine = SearchEngine.resume(snapshot)
            resumed_at = snapshot.progress.rows
            checkpoint_bytes = sum(
                hit.window.values.nbytes for _, _, hit in snapshot.candidates
            )
            if snapshot.halo is not None:
                checkpoint_bytes += (
                    snapshot.halo.values.nbytes
                    + snapshot.halo.close_ns.nbytes
                    + snapshot.halo.available_ns.nbytes
                )
        progress = engine.consume(block)
        if time.perf_counter() - last_notice >= 5:
            print(
                json.dumps(
                    {
                        "progress": calendar,
                        "rows": progress.rows,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                        "peak_working_set_bytes": _peak_bytes(),
                    }
                ),
                flush=True,
            )
            last_notice = time.perf_counter()
    result = engine.finish()
    elapsed = time.perf_counter() - started
    returned = {hit.window.start_ns for hit in result.hits}
    expected = set(evidence.planted_start_ns)
    assert returned == expected
    assert result.progress.rows == evidence.rows
    assert elapsed <= SECONDS_LIMIT and _peak_bytes() <= RAM_LIMIT
    return {
        "status": "PASS",
        "calendar": calendar,
        "label_start": start.isoformat(),
        "label_end": end.isoformat(),
        "first_close_utc": _iso(result.progress.first_close_ns),
        "last_close_utc": _iso(result.progress.last_close_ns),
        "sessions": evidence.sessions,
        "rows": evidence.rows,
        "elapsed_seconds": elapsed,
        "rows_per_second": evidence.rows / elapsed,
        "peak_working_set_bytes": _peak_bytes(),
        "search_progress": asdict(result.progress),
        "candidate_cap": config.candidate_cap,
        "exact_reranks": result.exact_reranks,
        "normalization": config.normalization,
        "window_bars": 32,
        "outcome_horizon_bars": 4,
        "cost_bps": config.cost_bps,
        "paa_segments": config.paa_segments,
        "planted_events": len(expected),
        "returned_events": len(returned),
        "planted_event_recall": 1,
        "cancel_resume_after_rows": resumed_at,
        "checkpoint_array_payload_bytes": checkpoint_bytes,
        "synthetic_price_sha256": evidence.value_digest,
        "close_timestamp_sha256": evidence.timestamp_digest,
        "calendars": evidence.schedules,
        "scratch_budget_bytes": config.max_working_bytes,
        "generated_stream_input_disk_bytes": 0,
        "persisted_index_bytes": 0,
        "limitations": [
            "Generated in memory; not a Parquet IO or persistent-index benchmark.",
            "Exact planted-motif retrieval is not general nearest-neighbor recall.",
            "FX uses named weekday NY17 convention; actual venue holidays are unknown.",
            "Checkpoint array bytes exclude Python object/string overhead; total process peak is measured.",
            "No empirical market observations, performance claims or research-authority allocation.",
        ],
    }


CASES: dict[str, tuple[tuple[str, date, date], ...]] = {
    "xnys_day": (("XNYS", date(2015, 1, 2), date(2015, 1, 2)),),
    "xnys_year": (("XNYS", date(2015, 1, 1), date(2015, 12, 31)),),
    "xnys_ten_year": (("XNYS", date(2015, 1, 1), date(2024, 12, 31)),),
    "fx_ten_year": (("FX_NY_17", date(2015, 1, 1), date(2024, 12, 31)),),
    "two_market_ten_year": (
        ("XNYS", date(2015, 1, 1), date(2024, 12, 31)),
        ("FX_NY_17", date(2015, 1, 1), date(2024, 12, 31)),
    ),
}


def test_benchmark_independent_small_recall_oracle() -> None:
    result = _small_comparison()
    assert result["eligible_windows"] == 477


def test_benchmark_generator_uses_actual_calendar_with_declared_synthetic_prices() -> (
    None
):
    evidence = StreamEvidence("XNYS", date(2024, 11, 29), date(2024, 11, 29))
    blocks = tuple(_blocks(evidence))
    assert len(blocks) == 1 and evidence.rows == 210
    assert _iso(int(blocks[0].close_ns[-1])) == "2024-11-29T18:00:00+00:00"
    assert evidence.planted_start_ns and len(evidence.value_digest) == 64


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=tuple(CASES))
    args = parser.parse_args()
    output = cast(Path, args.output).resolve()
    if args.case:
        began = time.perf_counter()
        streams = [_run_stream(*spec) for spec in CASES[args.case]]
        record = {
            "case": args.case,
            "evidence_mode": "SYNTHETIC",
            "status": "PASS",
            "streams": streams,
            "total_elapsed_seconds": time.perf_counter() - began,
            "peak_working_set_bytes": _peak_bytes(),
        }
        with (output / f"{args.case}.json").open("x", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
        print(
            json.dumps(
                {
                    "completed": args.case,
                    "rows": sum(cast(int, item["rows"]) for item in streams),
                    "seconds": record["total_elapsed_seconds"],
                    "peak_bytes": _peak_bytes(),
                }
            ),
            flush=True,
        )
        return
    output.mkdir(parents=True, exist_ok=False)
    report: Record = {
        "evidence_mode": "SYNTHETIC",
        "status": "RUNNING",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "code_reference": os.environ.get(
            "QH_PATTERN_CODE_REFERENCE",
            "uncommitted isolated source; see exact SHA-256 snapshots",
        ),
        "source_sha256": _source_snapshot(),
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": version("numpy"),
        "exchange_calendars": version("exchange-calendars"),
        "tzdata": version("tzdata"),
        "process_ram_limit_bytes": RAM_LIMIT,
        "seconds_limit_per_stream": SECONDS_LIMIT,
        "block_rows": BLOCK_ROWS,
        "small_exact_comparison": _small_comparison(),
        "scope": "Single process per case, sequential streams; pure computation synthetic scale only.",
    }
    completed: list[object] = []
    failures: list[Record] = []
    for case in CASES:
        try:
            # Fixed local Python executable and this known source file; no shell.
            subprocess.run(  # noqa: S603 - fixed interpreter/source, no shell
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--output",
                    str(output),
                    "--case",
                    case,
                ],
                check=True,
                timeout=150,
            )
            completed.append(
                json.loads((output / f"{case}.json").read_text(encoding="utf-8"))
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            failures.append({"case": case, "error": type(exc).__name__})
            break
    report["cases"], report["failures"] = completed, failures
    report["status"] = "FAILED" if failures else "PASS"
    report["case_evidence_disk_bytes"] = sum(
        path.stat().st_size for path in output.glob("*.json")
    )
    with (output / "benchmark.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(
        json.dumps(
            {"status": report["status"], "report": str(output / "benchmark.json")}
        ),
        flush=True,
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    _main()
