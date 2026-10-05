"""Connect native operational jobs to immutable Item 8 and synthetic arithmetic."""

from __future__ import annotations

import base64
import hashlib
import platform
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.imports import ImportService
from quant_hunter.lab import LabService
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.simulation import Costs, SimulationConfig, simulate, synthetic_fixture
from quant_hunter.sources import SourceProbeService
from quant_hunter.sources.equity_probes import EquityProbeService
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.web.connections import Connections, SourceRouter, default_private_root
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.state import AppState


def json_value(value: object) -> JsonValue:
    """Lossless decimal/timestamp evidence; unsupported objects fail closed."""
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Evidence keys must be text")
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [json_value(item) for item in value]
    raise ValueError("Unsupported evidence value")


def fixture_catalog() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for market in ("EQUITY", "FX_SPOT"):
        instrument, bars = synthetic_fixture(market)
        records.append(
            {
                "market": market,
                "symbol": instrument.symbol,
                "bar_count": len(bars),
                "start": json_value(bars[0].open_at),
                "end": json_value(bars[-1].close_at),
                "mode": "SYNTHETIC",
            }
        )
    return records


class Runtime:
    """One process/worker owns this runtime under the CLI's runtime lease."""

    def __init__(
        self,
        root: Path,
        repository: Path,
        code_revision: str,
        *,
        private_root: Path | None = None,
    ) -> None:
        if (root / "restore.incomplete").exists():
            raise ValueError("Runtime restoration is incomplete; do not launch")
        expected_module = repository / "src" / "quant_hunter" / "web" / "runtime.py"
        if expected_module.resolve() != Path(__file__).resolve():
            raise ValueError("Repository must contain the actually imported runtime")
        self.state = AppState(root / "application.sqlite3")
        source_files = (
            sorted((repository / "src").rglob("*.py"))
            + sorted((repository / "schemas").rglob("*.json"))
            + [repository / "pyproject.toml", repository / "uv.lock"]
        )
        # Preserve actual code bytes as immutable evidence, including dirty dev work.
        snapshot = {
            p.relative_to(repository).as_posix(): base64.b64encode(
                p.read_bytes()
            ).decode("ascii")
            for p in source_files
        }
        objects = ImmutableObjectStore(root / "research" / "artifacts")
        source_object = objects.publish(
            canonicalize_json(
                {"encoding": "base64-exact-bytes", "files": json_value(snapshot)}
            )
        )
        environment: JsonRecord = {
            "python": sys.version,
            "platform": platform.platform(),
            "source_snapshot_digest": source_object.digest,
            "uv_lock_digest": "sha256:"
            + hashlib.sha256((repository / "uv.lock").read_bytes()).hexdigest(),
            "code_revision_semantics": "Git parent plus immutable actual source snapshot; snapshot is execution authority for uncommitted changes",
            "software_mode": "SYNTHETIC",
        }
        self.lab = LabService(
            root / "research", repository / "schemas" / "v1", code_revision, environment
        )
        self.instruments = InstrumentRegistry(self.lab.registry)
        public_probes = SourceProbeService(
            self.lab.registry,
            self.lab.objects,
            repository / "schemas" / "v1",
            code_revision,
            self.lab.environment_digest,
        )
        self.connections = Connections(
            private_root or default_private_root(root),
            repository,
            root,
            EquityProbeService(public_probes),
        )
        self.data = DataAccess(
            self.state,
            root,
            ImportService(
                self.lab.registry,
                self.lab.objects,
                repository / "schemas" / "v1",
                code_revision,
                self.lab.environment_digest,
            ),
            SourceRouter(public_probes, self.connections),
        )

    def recover(self) -> None:
        """Never rerun an unknown interrupted attempt. Retain failure and require retry."""
        self.data.recover()
        for job in self.state.interrupted():
            if job.experiment_id:
                run = self.lab.recover_run(job.experiment_id)
                if run["lifecycle_status"] == "EVALUATED":
                    self.state.finish(
                        job.id,
                        error="ComputationFailed"
                        if run["evaluation_outcome"] == "FAILED"
                        else None,
                    )
                    continue
            self.state.finish(
                job.id,
                error="WorkerInterrupted; retained, never automatically replayed",
            )
        # An interruption between begin_run and job.bind can leave an orphan.
        for run in self.lab.list_runs():
            if run["lifecycle_status"] == "RUNNING":
                self.lab.recover_run(str(run["experiment_id"]))

    def process_one(self) -> bool:
        job = self.state.claim()
        if job is None:
            return False
        experiment_id: str | None = None
        try:
            instrument, bars = synthetic_fixture(str(job.config["market"]))
            config: JsonRecord = dict(job.config)
            config["dataset_start"] = json_value(bars[0].open_at)
            config["dataset_end"] = json_value(
                bars[-1].close_at + timedelta(microseconds=1)
            )
            config["evidence_mode"] = "SYNTHETIC"
            config["execution_policy"] = "NEXT_BAR_OPEN"
            config["strategy"] = "Causal long/flat momentum; no optimization"
            dataset = canonicalize_json(
                json_value(
                    {
                        "instrument": asdict(instrument),
                        "bars": [asdict(bar) for bar in bars],
                    }
                )
            )
            experiment_id = self.lab.begin_run(
                config,
                dataset,
                name=f"Synthetic {instrument.symbol} momentum accounting",
            )
            self.state.bind(job.id, experiment_id)
            settings = SimulationConfig(
                Decimal(str(config["initial_cash"])),
                Decimal(str(config["quantity"])),
                int(str(config["lookback"])),
                Costs(
                    Decimal(str(config["commission"])),
                    Decimal(str(config["slippage_bps"])),
                    Decimal(str(config["annual_financing_rate"])),
                ),
            )
            result = simulate(bars, instrument, settings)
            evidence = cast(JsonRecord, json_value(asdict(result)))
            evidence["summary"] = {
                "initial_cash": str(settings.initial_cash),
                "final_cash": str(result.final_cash),
                "final_equity": str(result.final_equity),
                "total_pnl": str(result.net_pnl),
                "return_pct": str(result.net_pnl / settings.initial_cash * 100),
                "trade_count": len(result.trades),
                "max_drawdown_pct": str(result.max_drawdown * 100),
            }
            evidence["equity_curve"] = [
                cast(JsonRecord, json_value({**asdict(point), "timestamp": point.at}))
                for point in result.equity_curve
            ]
            evidence["trades"] = [
                cast(
                    JsonRecord,
                    json_value(
                        {
                            **asdict(trade),
                            "timestamp": trade.filled_at,
                            "symbol": instrument.symbol,
                        }
                    ),
                )
                for trade in result.trades
            ]
            evidence["metadata"] = {
                "mode": "SYNTHETIC",
                "market": instrument.asset_class,
                "symbol": instrument.symbol,
                "experiment_id": experiment_id,
            }
            self.lab.evaluate_run(experiment_id, evidence)
            self.state.finish(job.id)
        except Exception as exc:
            error: str | None = type(exc).__name__
            if experiment_id:
                run = self.lab.get_run(experiment_id)
                if (
                    run["lifecycle_status"] == "RUNNING"
                    and run["variants_attempted"] == 0
                ):
                    self.lab.fail_run(experiment_id, type(exc).__name__)
                else:
                    run = self.lab.recover_run(experiment_id)
                    if run["evaluation_outcome"] != "FAILED":
                        error = None
            self.state.finish(job.id, error=error)
        return True
