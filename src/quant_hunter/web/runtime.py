"""Connect native operational jobs to immutable Item 8 and synthetic arithmetic."""

from __future__ import annotations

import base64
import hashlib
import platform
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.data_quality import QualityService
from quant_hunter.imports import ImportService
from quant_hunter.lab import LabService
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.notifications.telegram import FixedTelegramHTTPS
from quant_hunter.notifications.types import TelegramPolicy
from quant_hunter.publications import PublicationService
from quant_hunter.simulation import Costs, SimulationConfig, simulate, synthetic_fixture
from quant_hunter.simulation.paper_engine import PaperEngine
from quant_hunter.sources import SourceProbeService
from quant_hunter.sources.equity_probes import EquityProbeService
from quant_hunter.sources.providers import ProviderService
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.web.broker_access import BrokerAccess
from quant_hunter.web.connections import Connections, SourceRouter, default_private_root
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.halt_admission import HaltReadAdmission, ResumeReadAdmission
from quant_hunter.web.historical_access import HistoricalPreviewAccess
from quant_hunter.web.notification_access import NotificationAccess
from quant_hunter.web.notification_projection import NotificationProjection
from quant_hunter.web.paper_access import PaperAccess
from quant_hunter.web.paper_halt import GlobalPaperHalt
from quant_hunter.web.paper_portfolio import PaperPortfolio
from quant_hunter.web.pattern_access import PatternAccess
from quant_hunter.web.publication_access import PublicationAccess
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.state import AccessError, AppState, ResourceBusyError, User
from quant_hunter.web.study_model_ids import StudyModelIds
from quant_hunter.web.validation_access import ValidationAccess


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
    for market in ("EQUITY", "ETF", "FX_SPOT"):
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
        providers = ProviderService(public_probes)
        self.connections = Connections(
            private_root or default_private_root(root),
            repository,
            root,
            EquityProbeService(public_probes),
            provider_service=providers,
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
            SourceRouter(public_probes, self.connections, providers),
            providers,
        )

        self.publications = PublicationAccess(
            self.state,
            PublicationService(
                self.lab.registry,
                self.lab.objects,
                code_revision=code_revision,
                environment_digest=self.lab.environment_digest,
            ),
            capacity=self.data._capacity,
        )
        self.quality = QualityAccess(
            self.state,
            QualityService(
                self.lab.registry,
                self.lab.objects,
                repository / "schemas" / "v1",
                code_revision,
                self.lab.environment_digest,
            ),
            self.data,
            self.instruments,
        )
        self.patterns = PatternAccess(self.state, self.quality, self.lab)
        self.historical = HistoricalPreviewAccess(self.state, self.quality)
        self.validation = ValidationAccess(self.state, self.lab, self.quality)
        self.study_models = StudyModelIds(self.state, self.lab)
        self.paper = PaperAccess(
            self.state,
            self.lab,
            PaperEngine(root / "paper.sqlite3"),
            capacity=self.data._capacity,
        )
        self.paper_halt = GlobalPaperHalt(self.paper)
        self.halt_reads = HaltReadAdmission(self.paper_halt)
        self.paper_halt.read_resource = self.halt_reads.inspection
        self.resume_reads = ResumeReadAdmission(self.paper)
        self.paper.resume_resource = self.resume_reads.inspection
        self.paper_portfolio = PaperPortfolio(
            self.paper, inspection=self.quality.inspection
        )
        self.brokers = BrokerAccess(
            self.state,
            self.paper,
            self.lab.objects,
            private_root or default_private_root(root),
            repository,
            resource=lambda user, _operation: self.quality.inspection(user),
        )
        self._paper_turn = False
        self.notifications = NotificationAccess(
            self.state,
            private_root or default_private_root(root),
            repository,
            resource=self.quality.inspection,
            paper_detail=self.paper_detail,
            policy=TelegramPolicy.REVIEWED_V0_TOKEN_PATH,
            transport=FixedTelegramHTTPS(network_enabled=True),
        )
        self.notification_projection = NotificationProjection(self.notifications)
        self.notification_projection_error: str | None = None
        self._notification_due = 0.0
        self._notification_owner = 0

    def paper_detail(self, user: User, paper_id: str) -> JsonRecord:
        """Verified owned paper projection under shared read admission."""
        with self.quality.inspection(user):
            return self.paper.get(user, paper_id)

    def _project_notifications(self) -> None:
        """Bounded local projection; notification failure never changes research."""
        now = time.monotonic()
        if now < self._notification_due:
            return
        self._notification_due = now + 5.0
        try:
            with self.state.connection() as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM jobs LIMIT 10001)"
                ).fetchone()[0]
                if count > 10000:
                    self.notification_projection_error = "LOCAL_DELIVERY_UNAVAILABLE"
                    return
                row = db.execute(
                    "SELECT DISTINCT owner_id FROM jobs WHERE owner_id>? "
                    "AND status IN ('SUCCEEDED','FAILED','CANCELLED') "
                    "ORDER BY owner_id LIMIT 1",
                    (self._notification_owner,),
                ).fetchone()
            if row is None:
                self._notification_owner = 0
                return
            user = self.state.user(int(row[0]))
            projected = self.notification_projection.sweep(user, limit=100)
            self._notification_owner = user.id
            self.notification_projection_error = (
                "LOCAL_DELIVERY_UNAVAILABLE"
                if projected["local_delivery_unavailable"]
                else None
            )
        except Exception:
            self.notification_projection_error = "LOCAL_DELIVERY_UNAVAILABLE"

    def job_detail(self, user: User, job_id: str) -> JsonRecord:
        """Every public job route uses the same owned evidence verification."""
        job = self.state.job(user, job_id)
        kind = job.config.get("kind")
        if kind in {"PATTERN_JOB", "PATTERN_CORPUS"}:
            return self.patterns.job(user, job_id)
        if kind == "CHRONOLOGICAL_VALIDATION":
            return self.validation.get(user, job_id)
        run: JsonRecord | None = None
        identity_status: str | None = None
        if job.experiment_id:
            with self.quality.inspection(user):
                run = self.lab.get_run(job.experiment_id)
                if kind == "CRP_STUDY":
                    config = cast(JsonRecord, run["configuration"])
                    if "model_registration" in config:
                        run = self.study_models.inspect(user, job)
                        identity_status = "VERIFIED_PREREGISTERED_MODELS"
                    else:
                        identity_status = "LEGACY_WITHOUT_MODEL_PREREGISTRATION"
        return {
            "job": cast(JsonRecord, asdict(job)),
            "run": run,
            "model_identity_status": identity_status,
        }

    def recover(self) -> None:
        """Never rerun an unknown interrupted attempt. Retain failure and require retry."""
        self.data.recover()
        self.publications.recover()
        self.patterns.recover()
        self.paper.recover()
        paper_experiments = self.paper.owned_experiment_ids()
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
            if (
                run["lifecycle_status"] == "RUNNING"
                and run["experiment_id"] not in paper_experiments
            ):
                self.lab.recover_run(str(run["experiment_id"]))

    def _process_paper(self) -> bool:
        try:
            return self.paper_halt.process_one()
        except ResourceBusyError:
            # Capacity is temporary, not failed protective evidence. The worker
            # backs off and retains every task; other failures stay fail-closed.
            return False

    def process_one(self) -> bool:
        self._project_notifications()
        self._paper_turn = not self._paper_turn
        if self._paper_turn and self.paper_halt.has_pending() and self._process_paper():
            return True
        job = self.state.claim()
        if job is None:
            return self._process_paper() if self.paper_halt.has_pending() else False
        experiment_id: str | None = None
        try:
            user = self.state.user(job.owner_id)
            if user.role not in {"owner", "researcher"}:
                raise AccessError("Current researcher role required")
            self.data._capacity()
            if job.config.get("kind") == "PATTERN_CORPUS":
                self.patterns.execute_corpus_job(job)
                return True
            if job.config.get("kind") == "PATTERN_JOB":
                self.patterns.execute_job(job)
                return True
            if job.config.get("kind") == "CHRONOLOGICAL_VALIDATION":
                self.validation.execute_job(job)
                return True
            if job.config.get("kind") == "CRP_STUDY":
                from quant_hunter.web.studies import prepare_job

                base_config, actual_dataset, study_name = prepare_job(job.config)
                study_config, study_dataset = self.study_models.register_study(
                    user, job, base_config, actual_dataset
                )
                experiment_id = self.lab.begin_run(
                    study_config, study_dataset, name=study_name
                )
                self.state.bind(job.id, experiment_id)
                study_result = self.study_models.execute_study(
                    user,
                    self.state.job(user, job.id),
                    experiment_id,
                    study_config,
                    study_dataset,
                )
                self.lab.evaluate_run(experiment_id, study_result)
                self.state.finish(job.id)
                return True
            if "kind" in job.config:
                raise ValueError("Unsupported job kind")
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
