"""Real Item8/SQLite replay contracts; fixtures are synthetic, with no network."""

from __future__ import annotations

import asyncio
import base64
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.lab import LabService
from quant_hunter.simulation import accounting as a
from quant_hunter.simulation import paper_engine as p
from quant_hunter.simulation.paper_engine import PaperEngine
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.web import paper_access as module
from quant_hunter.web.paper_access import (
    PaperAccess,
    PaperConflictError,
    PaperWorkflowError,
    default_paper_config,
    validate_paper_config,
)
from quant_hunter.web.state import AccessError, AppState, User


class LocalClient:
    """Synchronous test adapter over actual offline ASGI; no Starlette legacy client."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.headers: dict[str, str] = {}

    def __enter__(self) -> LocalClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: object = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        async def call() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://offline.test",
            ) as client:
                return await client.request(
                    method, url, headers=self.headers, json=json, content=content
                )

        return asyncio.run(call())

    def get(self, url: str) -> httpx.Response:
        return self._request("GET", url)

    def post(
        self, url: str, *, json: object = None, content: bytes | None = None
    ) -> httpx.Response:
        return self._request("POST", url, json=json, content=content)


SCHEMAS = Path(__file__).parents[1] / "schemas" / "v1"
REVISION = "7346cf4f79ca5897777c0118f8cf4c2292be929e"


def build(tmp_path: Path) -> tuple[PaperAccess, User]:
    state = AppState(tmp_path / "application.sqlite3")
    user = state.create_user(
        "owner", "synthetic test passphrase", "owner", bootstrap=True
    )
    objects = ImmutableObjectStore(tmp_path / "research" / "artifacts")
    package = Path(module.__file__).resolve().parents[1]
    files: JsonRecord = {
        "src/quant_hunter/" + name: base64.b64encode(
            (package / name).read_bytes()
        ).decode("ascii")
        for name in module.SOURCE_FILES
    }
    snapshot = objects.publish(
        canonicalize_json({"encoding": "base64-exact-bytes", "files": files})
    )
    lab = LabService(
        tmp_path / "research",
        SCHEMAS,
        REVISION,
        {"source_snapshot_digest": snapshot.digest},
    )
    access = PaperAccess(
        state,
        lab,
        PaperEngine(tmp_path / "paper.sqlite3"),
        resume_resource=lambda user, paper_id, revision: nullcontext(),
    )
    return access, user


def control(
    access: PaperAccess, user: User, job: JsonRecord, action: str
) -> JsonRecord:
    fresh = access.get(user, cast(str, job["id"]))
    return access.control(
        user,
        cast(str, job["id"]),
        action,
        expected_revision=cast(int, fresh["revision"]),
    )


def launch(
    access: PaperAccess, user: User, market: str = "EQUITY", **changes: JsonValue
) -> JsonRecord:
    job = access.create(user, {**default_paper_config(market), **changes})
    control(access, user, job, "ACTIVATE")
    assert access.process_one()
    job = access.get(user, cast(str, job["id"]))
    assert job["status"] == "ACTIVE"
    assert job["cursor"] == 0
    return job


@pytest.mark.parametrize("market", ["EQUITY", "ETF", "FX_SPOT"])
def test_complete_real_lifecycle_and_causal_fills(tmp_path: Path, market: str) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner, market, bars=20)
    experiment_id = cast(str, job["experiment_id"])
    run = access.lab.get_run(experiment_id)
    assert run["lifecycle_status"] == "RUNNING"
    assert run["variants_attempted"] == 0
    for index in range(20):
        if market == "EQUITY" and index == 19:

            def crash(phase: str) -> None:
                if phase == "AFTER_FINALIZATION":
                    raise Crash

            access.fault = crash
            with pytest.raises(Crash):
                access.process_one()
            access.fault = lambda phase: None
            access.recover()
        else:
            assert access.process_one()
        job = access.get(owner, cast(str, job["id"]))
        assert job["cursor"] == index + 1
    assert job["status"] == "COMPLETED"
    assert not access.process_one()
    report = cast(JsonRecord, job["report"])
    snapshot = access.engine.load(cast(str, job["id"]), str(owner.id))
    assert snapshot.book.instruments[0].kind == market
    if market == "ETF":
        assert snapshot.book.instruments[0].symbol == "SYNTH_ETF"
        assert snapshot.book.instruments[0].quote_currency == "USD"
    assert snapshot.book.fills
    orders = {order.order_id: order for order in snapshot.book.orders}
    assert all(
        fill.at > orders[fill.order_id].decision_at for fill in snapshot.book.fills
    )
    assert all(
        order.status not in {"OPEN", "PARTIALLY_FILLED", "CANCEL_PENDING"}
        for order in snapshot.book.orders
    )
    assert report["equity"] == str(snapshot.equity)
    run = access.lab.get_run(experiment_id)
    assert run["evaluation_outcome"] == "INCONCLUSIVE"
    assert run["variants_attempted"] == 1
    assert run["result_digest"] == job["report_digest"]
    assert len(access.lab.registry.verify_all()) == 6


@pytest.mark.parametrize("market", ["EQUITY", "ETF", "FX_SPOT"])
def test_execution_snapshot_binds_actual_paused_risk_reservation(
    tmp_path: Path, market: str
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner, market, lookback=1)
    assert access.process_one() and access.process_one()
    paused = control(access, owner, job, "PAUSE")
    context, snapshot = access.execution_snapshot(
        owner, cast(str, job["id"]), expected_revision=cast(int, paused["revision"])
    )
    assert context["network_order_authority"] is False
    assert context["experiment_id"] == job["experiment_id"]
    assert snapshot.reservations[0].strategy_id == context["strategy_id"]
    assert snapshot.reservations[0].remaining > 0
    assert snapshot.book.fills == ()
    assert access.engine.load(cast(str, job["id"]), str(owner.id)) == snapshot
    assert (
        access.lab.get_run(cast(str, job["experiment_id"]))["variants_attempted"] == 0
    )
    with pytest.raises(PaperConflictError, match="PAUSED"):
        access.execution_snapshot(
            owner,
            cast(str, job["id"]),
            expected_revision=cast(int, paused["revision"]) - 1,
        )
    control(access, owner, paused, "RESUME")
    with pytest.raises(PaperConflictError, match="PAUSED"):
        access.execution_snapshot(
            owner, cast(str, job["id"]), expected_revision=cast(int, paused["revision"])
        )


def test_execution_snapshot_refuses_empty_foreign_and_unjournalled_state(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner, lookback=1)
    paused = control(access, owner, job, "PAUSE")
    with pytest.raises(PaperConflictError, match="ACTIVE_RISK"):
        access.execution_snapshot(
            owner, cast(str, job["id"]), expected_revision=cast(int, paused["revision"])
        )
    other = access.state.create_user(
        "other", "synthetic other password", "owner", bootstrap=False
    )
    with pytest.raises(AccessError):
        access.execution_snapshot(
            other, cast(str, job["id"]), expected_revision=cast(int, paused["revision"])
        )
    control(access, owner, paused, "RESUME")
    assert access.process_one() and access.process_one()
    paused = control(access, owner, job, "PAUSE")
    snapshot = access.engine.load(cast(str, job["id"]), str(owner.id))
    access.engine.process(
        snapshot.account_id,
        str(owner.id),
        p.Kill(
            command_id="independent-kill",
            at=snapshot.at,
            enabled=True,
            reason="OWNER_REQUEST",
        ),
        expected_revision=snapshot.revision,
    )
    with pytest.raises(PaperConflictError, match="UNJOURNALLED"):
        access.execution_snapshot(
            owner, cast(str, job["id"]), expected_revision=cast(int, paused["revision"])
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": "not accepted"},
        {"market": "FX"},
        {"market": []},
        {"mode": "LIVE"},
        {"bars": True},
        {"bars": 19},
        {"bars": 101},
        {"lookback": 0},
        {"initial_cash": "0"},
        {"initial_cash": "1000001"},
        {"quantity": "NaN"},
        {"quantity": "1.1"},
        {"quantity": 10},
        {"max_fill_quantity": "11"},
        {"slippage_bps": "1001"},
        {"max_concentration": "1.1"},
        {"max_drawdown": "0"},
        {"commission_per_fill": "-1"},
        {"max_orders_per_window": 0},
    ],
)
def test_closed_bounded_configuration(changes: JsonRecord) -> None:
    with pytest.raises(PaperWorkflowError):
        validate_paper_config({**default_paper_config(), **changes})


def test_create_is_not_research_or_execution_and_cancel_needs_no_attempt(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    assert access.lab.list_runs() == []
    assert not access.has_pending()
    assert not access.process_one()
    cancelled = control(access, owner, job, "CANCEL")
    assert cancelled["status"] == "CANCELLED"
    assert access.lab.list_runs() == []
    assert access.owned_experiment_ids() == frozenset()


def test_reader_foreign_owner_forged_role_and_stale_revision(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    reader = access.state.create_user(
        "reader", "synthetic reader password", "reader", bootstrap=False
    )
    researcher = access.state.create_user(
        "researcher", "synthetic researcher password", "researcher", bootstrap=False
    )
    job = access.create(researcher, default_paper_config())
    identity = cast(str, job["id"])
    assert access.list_sessions(owner) == []
    for user in (owner, reader):
        with pytest.raises(AccessError):
            access.get(user, identity)
    with pytest.raises(AccessError):
        access.create(reader, default_paper_config())
    with pytest.raises(AccessError):
        access.create(User(reader.id, reader.username, "owner"), default_paper_config())
    active = control(access, researcher, job, "ACTIVATE")
    assert active["status"] == "ACTIVE"
    with pytest.raises(PaperConflictError, match="STALE"):
        access.control(
            researcher, identity, "PAUSE", expected_revision=cast(int, job["revision"])
        )
    assert control(access, researcher, active, "PAUSE")["status"] == "PAUSED"
    assert control(access, researcher, active, "RESUME")["status"] == "ACTIVE"


def test_clean_restart_pauses_and_unknown_orphan_still_fails(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    assert access.process_one()
    config: JsonRecord = {
        "dataset_start": "2024-01-01T00:00:00Z",
        "dataset_end": "2024-01-02T00:00:00Z",
    }
    orphan = access.lab.begin_run(config, b'{"synthetic":true}')
    access.recover()
    owned = access.owned_experiment_ids()
    for run in access.lab.list_runs():
        if run["lifecycle_status"] == "RUNNING" and run["experiment_id"] not in owned:
            access.lab.recover_run(cast(str, run["experiment_id"]))
    fresh = access.get(owner, cast(str, job["id"]))
    assert fresh["status"] == "PAUSED"
    assert fresh["cursor"] == 1
    assert (
        access.lab.get_run(cast(str, job["experiment_id"]))["lifecycle_status"]
        == "RUNNING"
    )
    assert access.lab.get_run(orphan)["evaluation_outcome"] == "FAILED"
    assert not access.process_one()
    control(access, owner, fresh, "RESUME")
    assert access.process_one()
    assert access.get(owner, cast(str, job["id"]))["cursor"] == 2


class Crash(BaseException):
    pass


@pytest.mark.parametrize(
    "phase,effect", [("CLAIMED", False), ("AFTER_STEP_RECEIPT", True)]
)
def test_exact_crash_reconciliation_requires_explicit_resume(
    tmp_path: Path, phase: str, effect: bool
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)

    def crash(at: str) -> None:
        if at == phase:
            raise Crash

    access.fault = crash
    with pytest.raises(Crash):
        access.process_one()
    access.fault = lambda phase: None
    access.recover()
    fresh = access.get(owner, cast(str, job["id"]))
    assert fresh["status"] == "AMBIGUOUS"
    assert not access.process_one()
    result = access.reconcile(
        owner, cast(str, job["id"]), expected_revision=cast(int, fresh["revision"])
    )
    assert result["status"] == "PAUSED"
    assert result["cursor"] == int(effect)
    assert not access.process_one()
    control(access, owner, result, "RESUME")
    assert access.process_one()
    assert access.get(owner, cast(str, job["id"]))["cursor"] == int(effect) + 1


def test_partial_step_is_not_replayed_and_cancellation_counts_failed_attempt(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)

    def crash(phase: str) -> None:
        if phase == "AFTER_ENGINE_COMMAND":
            raise Crash

    access.fault = crash
    with pytest.raises(Crash):
        access.process_one()
    access.fault = lambda phase: None
    access.recover()
    fresh = access.get(owner, cast(str, job["id"]))
    with pytest.raises(PaperConflictError, match="PARTIAL_STEP"):
        access.reconcile(
            owner, cast(str, job["id"]), expected_revision=cast(int, fresh["revision"])
        )
    assert access.engine.load(cast(str, job["id"]), str(owner.id)).revision == 1
    control(access, owner, fresh, "CANCEL")
    assert access.process_one()
    final = access.get(owner, cast(str, job["id"]))
    assert final["status"] == "CANCELLED"
    assert final["report_digest"]
    run = access.lab.get_run(cast(str, job["experiment_id"]))
    assert run["evaluation_outcome"] == "FAILED"
    assert run["variants_attempted"] == 1
    assert access.engine.load(cast(str, job["id"]), str(owner.id)).revision == 2


def test_pending_pause_concurrent_worker_cannot_duplicate_bar(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    entered, release = Event(), Event()

    def block(phase: str) -> None:
        if phase == "CLAIMED":
            entered.set()
            assert release.wait(10)

    access.fault = block
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(access.process_one)
        assert entered.wait(10)
        assert not access.process_one()
        paused = control(access, owner, job, "PAUSE")
        assert paused["requested"] == "PAUSE"
        release.set()
        assert future.result()
    final = access.get(owner, cast(str, job["id"]))
    assert final["status"] == "PAUSED"
    assert final["cursor"] == 1
    assert access.engine.load(cast(str, job["id"]), str(owner.id)).revision == 2


def test_partial_fill_budget_and_independent_cash_oracle(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner, lookback=1)
    # First signal is at bar1 close (100.39/100.41), then buy4 at bar2 open.
    assert access.process_one()
    assert access.process_one()
    before = access.engine.load(cast(str, job["id"]), str(owner.id))
    assert before.reservations[0].fee_remaining == Decimal(3)
    assert before.reservations[0].remaining == Decimal(10)
    assert access.process_one()
    after = access.engine.load(cast(str, job["id"]), str(owner.id))
    assert after.book.fills[0].price == Decimal("100.43")
    assert after.book.fills[0].quantity == Decimal(4)
    assert after.book.cash[0].amount == Decimal("9597.28")
    assert after.equity == Decimal("9997.64")  # 9597.28 + 4 * 100.09
    assert after.book.fills[0].commission == Decimal(1)
    assert after.book.fills[0].adverse_slippage == Decimal("0.08")
    # Falling closed quote cancels the unfilled buy before admitting reduce-only sell.
    assert after.reservations[0].side == "SELL"
    assert after.reservations[0].fee_remaining == Decimal(1)


def test_risk_rejection_is_visible_in_report_and_signal(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner, lookback=1, max_order_notional="1")
    assert access.process_one()
    assert access.process_one()
    report = cast(JsonRecord, access.get(owner, cast(str, job["id"]))["report"])
    assert report["engine_rejections"]
    assert report["first_rejected_reason"]
    assert (
        cast(JsonRecord, cast(list[JsonValue], report["signals"])[1])[
            "admission_status"
        ]
        == "REJECTED"
    )
    assert not access.engine.load(cast(str, job["id"]), str(owner.id)).book.fills


def test_kill_reset_and_loss_baseline_are_persistent(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    assert access.process_one()
    control(access, owner, job, "KILL")
    assert access.process_one()
    killed = access.get(owner, cast(str, job["id"]))
    assert killed["status"] == "PAUSED"
    snapshot = access.engine.load(cast(str, job["id"]), str(owner.id))
    assert snapshot.killed
    baseline = snapshot.inception_equity
    control(access, owner, killed, "RESET_KILL")
    assert access.process_one()
    snapshot = access.engine.load(cast(str, job["id"]), str(owner.id))
    assert not snapshot.killed
    assert snapshot.inception_equity == baseline == Decimal(10000)
    assert snapshot.reconciled_at == snapshot.at


def test_immutable_operational_chain_and_head_detection(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    with access.state.connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM paper_events")
        db.execute("UPDATE paper_jobs SET status='ACTIVE'")
    with pytest.raises(PaperWorkflowError, match="HEAD_INTEGRITY"):
        access.get(owner, cast(str, job["id"]))


def test_cross_service_queue_and_worker_capacity(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    with access.state.connection() as db:
        db.executemany(
            "INSERT INTO jobs VALUES(?,?,?,'{}',NULL,NULL)",
            [(str(index), owner.id, "QUEUED") for index in range(7)],
        )
    with pytest.raises(PaperConflictError, match="SHARED_QUEUE"):
        access.create(owner, default_paper_config())
    control(access, owner, job, "ACTIVATE")
    with access.state.connection() as db:
        db.execute("UPDATE jobs SET status='RUNNING' WHERE id IN ('0','1')")
    assert not access.process_one()
    assert access.lab.list_runs() == []


def test_reconciliation_uses_shared_slots_without_changing_denied_head(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)

    def crash(phase: str) -> None:
        if phase == "CLAIMED":
            raise Crash

    access.fault = crash
    with pytest.raises(Crash):
        access.process_one()
    access.fault = lambda phase: None
    access.recover()
    identity = cast(str, job["id"])
    before = access.get(owner, identity)
    assert before["status"] == "AMBIGUOUS"
    checked: list[bool] = []

    def capacity() -> None:
        # A second writer proves the host callback runs outside the claim lock.
        with access.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
        checked.append(True)

    access.capacity = capacity
    with access.state.connection() as db:
        db.execute("CREATE TABLE data_operations (status TEXT NOT NULL)")
        db.execute("CREATE TABLE publication_operations (status TEXT NOT NULL)")
        db.execute("INSERT INTO data_operations VALUES('RUNNING')")
        db.execute("INSERT INTO publication_operations VALUES('RUNNING')")
    with pytest.raises(PaperConflictError, match="SHARED_RESOURCE_LIMIT"):
        access.reconcile(
            owner, identity, expected_revision=cast(int, before["revision"])
        )
    assert checked == [True]
    assert access.get(owner, identity) == before
    with access.state.connection() as db:
        db.execute("UPDATE publication_operations SET status='SUCCEEDED'")
    after = access.reconcile(
        owner, identity, expected_revision=cast(int, before["revision"])
    )
    assert after["status"] == "PAUSED"
    assert checked == [True, True]


def test_sanitized_failure_is_retained_without_retry(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)

    def failure(phase: str) -> None:
        if phase == "AFTER_ENGINE_COMMAND":
            raise RuntimeError("password=must-never-be-retained")

    access.fault = failure
    assert access.process_one()
    result = access.get(owner, cast(str, job["id"]))
    assert result["status"] == "FAILED"
    assert "must-never" not in str(result)
    assert cast(JsonRecord, result["report"])["snapshot"]
    assert (
        access.lab.get_run(cast(str, job["experiment_id"]))["evaluation_outcome"]
        == "FAILED"
    )
    assert not access.process_one()


def test_exact_genesis_risk_binding_refuses_injected_wider_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    original = access.engine.create_account

    def changed(
        account_id: str,
        owner_id: str,
        book: a.BookSnapshot,
        limits: p.RiskLimits,
        provenance: p.Provenance,
    ) -> p.PaperSnapshot:
        return original(
            account_id,
            owner_id,
            book,
            replace(limits, max_loss=Decimal(9999)),
            provenance,
        )

    monkeypatch.setattr(access.engine, "create_account", changed)
    job = access.create(owner, default_paper_config())
    control(access, owner, job, "ACTIVATE")
    assert access.process_one()
    result = access.get(owner, cast(str, job["id"]))
    assert result["status"] == "FAILED"
    assert (
        access.lab.get_run(cast(str, result["experiment_id"]))["evaluation_outcome"]
        == "FAILED"
    )


def test_out_of_workflow_engine_change_cannot_enter_next_result(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    identity = cast(str, job["id"])
    snapshot = access.engine.load(identity, str(owner.id))
    access.engine.process(
        identity,
        str(owner.id),
        p.Kill(
            command_id="EXTERNAL",
            at=snapshot.at,
            enabled=True,
            reason="OUTSIDE_WORKFLOW",
        ),
        snapshot.revision,
    )
    assert access.process_one()
    result = access.get(owner, identity)
    assert result["status"] == "FAILED"
    assert result["cursor"] == 0


@pytest.mark.parametrize("phase", ["AFTER_BEGIN_RUN", "AFTER_ACCOUNT"])
def test_initialization_crash_retains_orphan_or_bound_attempt_without_replay(
    tmp_path: Path, phase: str
) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    control(access, owner, job, "ACTIVATE")

    def crash(at: str) -> None:
        if at == phase:
            raise Crash

    access.fault = crash
    with pytest.raises(Crash):
        access.process_one()
    access.fault = lambda phase: None
    access.recover()
    assert not access.process_one()
    owned = access.owned_experiment_ids()
    for run in access.lab.list_runs():
        if run["experiment_id"] not in owned:
            access.lab.recover_run(cast(str, run["experiment_id"]))
    control(access, owner, job, "CANCEL")
    if phase == "AFTER_ACCOUNT":
        assert access.process_one()
    final = access.get(owner, cast(str, job["id"]))
    assert final["status"] == "CANCELLED"
    assert len(access.lab.list_runs()) == 1
    assert access.lab.list_runs()[0]["evaluation_outcome"] == "FAILED"


@pytest.mark.parametrize(
    "mutation", ["missing", "encoding", "file", "base64", "changed"]
)
def test_source_snapshot_is_exact_execution_authority(
    tmp_path: Path, mutation: str
) -> None:
    access, _ = build(tmp_path)
    if mutation == "missing":
        environment: JsonRecord = {}
    else:
        snapshot = access._object(access._source_digest)
        files = cast(JsonRecord, snapshot["files"])
        first = "src/quant_hunter/" + module.SOURCE_FILES[0]
        if mutation == "encoding":
            snapshot["encoding"] = "hashes-only"
        elif mutation == "file":
            files.pop(first)
        elif mutation == "base64":
            files[first] = "@@@"
        else:
            files[first] = base64.b64encode(b"wrong code").decode()
        environment = {
            "source_snapshot_digest": access.lab.objects.publish(
                canonicalize_json(snapshot)
            ).digest
        }
    digest = access.lab.objects.publish(canonicalize_json(environment)).digest
    with pytest.raises(PaperWorkflowError):
        access._source(digest, current=True)


def test_global_capacity_and_audit_bounds_fail_without_lost_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    with monkeypatch.context() as patch:
        patch.setattr(module, "MAX_JOBS", 1)
        with pytest.raises(PaperConflictError, match="LIFETIME"):
            access.create(owner, default_paper_config())
    with monkeypatch.context() as patch:
        patch.setattr(module, "MAX_EVENTS", 1)
        with pytest.raises(PaperConflictError, match="EVENT_LIMIT"):
            control(access, owner, job, "CANCEL")
    with monkeypatch.context() as patch:
        patch.setattr(module, "MAX_AUDIT_BYTES", 1)
        with pytest.raises(PaperConflictError, match="CAPACITY"):
            control(access, owner, job, "ACTIVATE")
    assert access.get(owner, cast(str, job["id"]))["status"] == "CREATED"


def test_rejected_and_reconfigured_roles_keep_private_reads(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    with access.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (owner.id,))
    with pytest.raises(AccessError):
        access.get(owner, cast(str, job["id"]))
    reader = User(owner.id, owner.username, "reader")
    assert access.get(reader, cast(str, job["id"]))["status"] == "CREATED"
    with pytest.raises(AccessError):
        control(access, reader, job, "ACTIVATE")


def test_route_auth_csrf_closed_input_and_private_ownership(tmp_path: Path) -> None:
    from fastapi import FastAPI, HTTPException, Request

    from quant_hunter.web.paper_routes import install_paper_routes
    from quant_hunter.web.state import Session

    access, owner = build(tmp_path)
    other = access.state.create_user(
        "second", "synthetic second password", "researcher", bootstrap=False
    )
    current = [owner]

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        if request.headers.get("x-test-auth") != "yes":
            raise HTTPException(401, "Authentication required")
        if mutation and request.headers.get("x-test-csrf") != "fixture":
            raise HTTPException(403, "CSRF required")
        return Session(current[0], "fixture")

    app = FastAPI()
    install_paper_routes(app, authenticated, access, inspection=lambda _: nullcontext())
    with LocalClient(app) as client:
        assert client.get("/api/paper/configuration").status_code == 401
        client.headers["x-test-auth"] = "yes"
        assert client.get("/api/paper/configuration").json()["network_enabled"] is False
        body = {"configuration": default_paper_config()}
        assert client.post("/api/paper/sessions", json=body).status_code == 403
        client.headers["x-test-csrf"] = "fixture"
        result = client.post("/api/paper/sessions", json=body)
        assert result.status_code == 200
        job = result.json()
        endpoint = "/api/paper/sessions/" + job["id"]
        assert len(client.get("/api/paper/sessions").json()) == 1
        assert (
            client.post(
                endpoint + "/control",
                json={"action": "ACTIVATE", "expected_revision": job["revision"]},
            ).status_code
            == 200
        )
        assert (
            client.post(
                endpoint + "/control",
                json={"action": "PAUSE", "expected_revision": job["revision"]},
            ).status_code
            == 409
        )
        assert (
            client.post(
                endpoint + "/reconcile", json={"expected_revision": 2}
            ).status_code
            == 409
        )
        current[0] = other
        assert client.get(endpoint).status_code == 403
        assert client.get("/api/paper/sessions").json() == []
        secret = "password=must-not-echo"  # noqa: S105 -- deliberately synthetic
        invalid = client.post(
            "/api/paper/sessions",
            json={"configuration": {**default_paper_config(), "secret": secret}},
        )
        assert invalid.status_code == 400 and secret not in invalid.text
        assert (
            client.post("/api/paper/sessions", content=b"x" * 8193).status_code == 413
        )
        assert (
            client.post(
                "/api/paper/sessions", content=b'{"configuration":1,"configuration":2}'
            ).status_code
            == 400
        )


def test_disabled_routes_and_fixed_error_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import FastAPI

    from quant_hunter.web.paper_routes import install_paper_routes
    from quant_hunter.web.state import Session

    access, owner = build(tmp_path)
    owner_user = owner
    for service in (None, access):
        app = FastAPI()
        install_paper_routes(
            app,
            lambda request, mutation=False, owner=False: Session(owner_user, "fixture"),
            service,
        )
        if service is not None:

            def failure(user: User) -> list[JsonRecord]:
                raise RuntimeError("synthetic-secret-never-echo")

            monkeypatch.setattr(service, "list_sessions", failure)
        with LocalClient(app) as client:
            response = client.get("/api/paper/sessions")
            assert response.status_code == 503
            assert "synthetic-secret" not in response.text


@pytest.mark.parametrize("after_attempt", [False, True])
def test_cancel_canonical_finalization_crash_counts_once(
    tmp_path: Path, after_attempt: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    control(access, owner, job, "CANCEL")
    if after_attempt:
        finish = access.lab._finish_attempt

        def crash_finish(experiment_id: str) -> JsonRecord:
            raise Crash

        monkeypatch.setattr(access.lab, "_finish_attempt", crash_finish)
    else:

        def crash(phase: str) -> None:
            if phase == "AFTER_FINALIZATION":
                raise Crash

        access.fault = crash
    with pytest.raises(Crash):
        access.process_one()
    access.fault = lambda phase: None
    if after_attempt:
        monkeypatch.setattr(access.lab, "_finish_attempt", finish)
    access.recover()
    final = access.get(owner, cast(str, job["id"]))
    assert final["status"] == "CANCELLED"
    assert (
        access.lab.get_run(cast(str, job["experiment_id"]))["variants_attempted"] == 1
    )
    assert not access.process_one()


def test_capacity_callback_runs_outside_application_write_transaction(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)

    def capacity() -> None:
        with access.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("SELECT 1")

    access.capacity = capacity
    assert access.create(owner, default_paper_config())["status"] == "CREATED"


def test_cancel_ordinary_postfinalization_error_preserves_canonical_outcome(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    control(access, owner, job, "CANCEL")

    def failure(phase: str) -> None:
        if phase == "AFTER_FINALIZATION":
            raise OSError("synthetic disk failure")

    access.fault = failure
    assert access.process_one()
    assert access.get(owner, cast(str, job["id"]))["status"] == "CANCELLED"
    assert access.lab.get_run(cast(str, job["experiment_id"]))["failure_modes"] == [
        "PaperCancelled"
    ]


@pytest.mark.parametrize(
    "action", ["ACTIVATE", "RESUME", "KILL", "RESET_KILL", "PAUSE"]
)
def test_invalid_created_controls_are_refused(tmp_path: Path, action: str) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    if action == "ACTIVATE":
        job = control(access, owner, job, "ACTIVATE")
    with pytest.raises(PaperConflictError):
        control(access, owner, job, action)


def test_invalid_control_envelope_and_terminal_state(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    identity = cast(str, job["id"])
    with pytest.raises(PaperWorkflowError, match="UNSUPPORTED_CONTROL"):
        access.control(owner, identity, "EXTERNAL", expected_revision=1)
    with pytest.raises(PaperWorkflowError, match="REVISION_REQUIRED"):
        access.control(owner, identity, "ACTIVATE", expected_revision=True)
    cancelled = control(access, owner, job, "CANCEL")
    with pytest.raises(PaperConflictError, match="CONTROL_NOT_AVAILABLE"):
        control(access, owner, cancelled, "ACTIVATE")
    with pytest.raises(PaperConflictError, match="RECONCILIATION_NOT_AVAILABLE"):
        access.reconcile(
            owner, identity, expected_revision=cast(int, cancelled["revision"])
        )


def test_concurrent_admissions_share_final_queue_slot(tmp_path: Path) -> None:
    from threading import Barrier

    access, owner = build(tmp_path)
    for _ in range(7):
        access.create(owner, default_paper_config())
    barrier = Barrier(2)

    def create() -> str:
        barrier.wait(5)
        try:
            access.create(owner, default_paper_config())
            return "CREATED"
        except PaperConflictError:
            return "REFUSED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(create), pool.submit(create)
        assert sorted((first.result(), second.result())) == ["CREATED", "REFUSED"]
    assert len(access.list_sessions(owner)) == 8
    assert all("report" not in row for row in access.list_sessions(owner))


def test_sql_audit_payload_tampering_is_detected(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    with access.state.connection() as db:
        db.execute("DROP TRIGGER paper_event_update")
        db.execute("UPDATE paper_events SET digest='sha256:bad'")
    with pytest.raises(PaperWorkflowError, match="CHAIN_INTEGRITY"):
        access.get(owner, cast(str, job["id"]))


def test_bounded_evidence_decoders_reject_invalid_and_noncanonical_input() -> None:
    with pytest.raises(PaperWorkflowError, match="EVIDENCE_SIZE"):
        module._decode(b"")
    with pytest.raises(PaperWorkflowError, match="NONCANONICAL"):
        module._decode(b'{ "a": 1 }')
    with pytest.raises(PaperWorkflowError, match="RECORD"):
        module._decode(b"[]")
    with pytest.raises(PaperWorkflowError, match="EVIDENCE_TYPE"):
        module._json(object())
    with pytest.raises(PaperWorkflowError, match="UTC"):
        module._at("2024-01-01T00:00:00")


def test_dedicated_paper_path_and_object_bounds(tmp_path: Path) -> None:
    access, _ = build(tmp_path)
    with pytest.raises(PaperWorkflowError, match="DEDICATED"):
        PaperAccess(access.state, access.lab, PaperEngine(tmp_path / "wrong.sqlite3"))
    object_ = access.lab.objects.publish(b'{"a":1}')
    with pytest.raises(PaperWorkflowError, match="EVIDENCE_SIZE"):
        access._object(object_.digest, maximum=2)


def test_audit_reservations_protect_existing_admissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    first = access.create(owner, default_paper_config())
    bound = 2 * module.MAX_EVENTS * module.MAX_EVENT_BYTES - module.MAX_EVENT_BYTES
    monkeypatch.setattr(module, "MAX_AUDIT_BYTES", bound)
    with pytest.raises(PaperConflictError, match="AUDIT_RESERVATION"):
        access.create(owner, default_paper_config())
    assert control(access, owner, first, "ACTIVATE")["status"] == "ACTIVE"
    assert access.process_one()
    assert access.get(owner, cast(str, first["id"]))["status"] == "ACTIVE"


def test_event_headroom_retains_failed_attempt_before_exhaustion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    identity = cast(str, job["id"])
    current = access.get(owner, identity)
    monkeypatch.setattr(
        module,
        "MAX_EVENTS",
        cast(int, current["revision"]) + module.FINALIZATION_HEADROOM,
    )
    with pytest.raises(PaperConflictError, match="FINALIZATION_CAPACITY"):
        control(access, owner, current, "PAUSE")
    assert access.process_one()
    final = access.get(owner, identity)
    assert final["status"] == "FAILED" and final["error"] == "PaperEventCapacity"
    assert final["cursor"] == 0 and final["report_digest"]
    assert (
        access.lab.get_run(cast(str, job["experiment_id"]))["evaluation_outcome"]
        == "FAILED"
    )
    assert cast(int, final["revision"]) < module.MAX_EVENTS


def test_repeated_recovery_is_readonly_for_already_paused_sessions(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    access.recover()
    first = access.get(owner, cast(str, job["id"]))
    access.recover()
    assert access.get(owner, cast(str, job["id"])) == first


@pytest.mark.parametrize("ambiguous", [False, True])
def test_pending_kill_survives_restart_without_replaying_uncertain_bar(
    tmp_path: Path, ambiguous: bool
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    if ambiguous:

        def crash(phase: str) -> None:
            if phase == "CLAIMED":
                control(access, owner, job, "KILL")
                raise Crash

        access.fault = crash
        with pytest.raises(Crash):
            access.process_one()
        access.fault = lambda phase: None
    else:
        control(access, owner, job, "KILL")
    access.recover()
    fresh = access.get(owner, cast(str, job["id"]))
    assert fresh["requested"] == "KILL"
    if ambiguous:
        assert not access.has_pending() and not access.process_one()
        fresh = access.reconcile(
            owner, cast(str, job["id"]), expected_revision=cast(int, fresh["revision"])
        )
    assert access.has_pending()
    assert access.process_one()
    final = access.get(owner, cast(str, job["id"]))
    assert final["status"] == "PAUSED" and final["cursor"] == 0
    assert access.engine.load(cast(str, job["id"]), str(owner.id)).killed


def test_control_capacity_preserves_final_cancellation_slot(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    for index in range(63):
        action = "ACTIVATE" if index == 0 else "PAUSE" if index % 2 else "RESUME"
        job = control(access, owner, job, action)
    with pytest.raises(PaperConflictError, match="CONTROL_NOT_AVAILABLE"):
        control(access, owner, job, "PAUSE")
    final = control(access, owner, job, "CANCEL")
    assert final["status"] == "CANCELLED" and final["controls"] == 64
    assert access.lab.list_runs() == []
