"""Real Item 8, SQLite and arithmetic integration, including restart windows."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import pytest

from quant_hunter.web.lease import RuntimeLease
from quant_hunter.web.runtime import Runtime, fixture_catalog, json_value
from quant_hunter.web.worker import Worker

REPOSITORY = Path(__file__).parents[1]
TEST_REVISION = "c43d7c7" + "0" * 33  # Synthetic test identity, not a release claim.
CONFIG: dict[str, str | int] = {
    "market": "EQUITY",
    "initial_cash": "10000",
    "quantity": "10",
    "lookback": 1,
    "commission": "1",
    "slippage_bps": "0",
    "annual_financing_rate": "0",
}


def runner_at(path: Path) -> Runtime:
    return Runtime(path, REPOSITORY, TEST_REVISION)


def test_real_default_job_freezes_then_computes_oracle(tmp_path: Path) -> None:
    runner = runner_at(tmp_path)
    user = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    job = runner.state.enqueue(user, CONFIG)
    assert runner.process_one()
    finished = runner.state.job(user, job.id)
    assert finished.status == "SUCCEEDED"
    assert finished.experiment_id
    run = runner.lab.get_run(finished.experiment_id)
    result = run["result"]
    assert isinstance(result, dict)
    summary = result["summary"]
    assert isinstance(summary, dict)
    assert summary["final_cash"] == "10008"
    assert summary["trade_count"] == 2
    assert run["lifecycle_status"] == "EVALUATED"
    assert run["evaluation_outcome"] == "INCONCLUSIVE"
    assert run["decision"] is None
    assert run["variants_attempted"] == 1
    assert not runner.process_one()
    restarted = runner_at(tmp_path)
    restarted.recover()
    assert restarted.state.job(user, job.id).status == "SUCCEEDED"
    assert (
        restarted.lab.get_run(finished.experiment_id)["result_digest"]
        == run["result_digest"]
    )


def test_failure_retained_then_queue_can_progress(tmp_path: Path) -> None:
    runner = runner_at(tmp_path)
    user = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    job = runner.state.enqueue(user, {**CONFIG, "quantity": "0"})
    assert runner.process_one()
    failed = runner.state.job(user, job.id)
    assert failed.status == "FAILED"
    assert failed.experiment_id
    run = runner.lab.get_run(failed.experiment_id)
    assert run["evaluation_outcome"] == "FAILED"
    assert run["variants_attempted"] == 1
    next_job = runner.state.enqueue(user, {**CONFIG, "market": "FX_SPOT"})
    assert runner.process_one()
    assert runner.state.job(user, next_job.id).status == "SUCCEEDED"


def test_restart_before_and_after_experiment_binding(tmp_path: Path) -> None:
    runner = runner_at(tmp_path)
    user = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    job = runner.state.enqueue(user, CONFIG)
    assert runner.state.claim()
    config = {
        **CONFIG,
        "dataset_start": "2020-01-01T00:00:00Z",
        "dataset_end": "2020-01-05T00:00:00Z",
    }
    orphan = runner.lab.begin_run(
        config, b'{"fixture":"interrupted synthetic control"}'
    )
    runner_at(tmp_path).recover()
    assert runner.state.job(user, job.id).status == "FAILED"
    assert runner.lab.get_run(orphan)["evaluation_outcome"] == "FAILED"
    assert runner.lab.get_run(orphan)["variants_attempted"] == 1
    job2 = runner.state.enqueue(user, CONFIG)
    assert runner.state.claim()
    bound = runner.lab.begin_run(config, b'{"fixture":"second synthetic control"}')
    runner.state.bind(job2.id, bound)
    runner_at(tmp_path).recover()
    assert runner.state.job(user, job2.id).status == "FAILED"
    assert runner.lab.get_run(bound)["variants_attempted"] == 1


def test_restart_preserves_evaluation_before_job_finish(tmp_path: Path) -> None:
    runner = runner_at(tmp_path)
    user = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    job = runner.state.enqueue(user, CONFIG)
    assert runner.process_one()
    before = runner.state.job(user, job.id)
    assert before.experiment_id
    with runner.state.connection() as db:
        db.execute("UPDATE jobs SET status='RUNNING' WHERE id=?", (job.id,))
    runner_at(tmp_path).recover()
    assert runner.state.job(user, job.id).status == "SUCCEEDED"
    assert runner.lab.get_run(before.experiment_id)["variants_attempted"] == 1


def test_runtime_lease_and_serialization(tmp_path: Path) -> None:
    first, second = RuntimeLease(tmp_path), RuntimeLease(tmp_path)
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already held"):
            first.acquire()
        with pytest.raises(RuntimeError, match="Another process"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()
    second.release()
    assert fixture_catalog()[1]["market"] == "FX_SPOT"
    with pytest.raises(ValueError):
        json_value({1: "bad key"})
    with pytest.raises(ValueError):
        json_value(object())


def test_source_snapshot_cannot_claim_another_checkout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="actually imported runtime"):
        Runtime(tmp_path / "runtime", tmp_path / "unrelated-checkout", TEST_REVISION)
    assert not (tmp_path / "runtime").exists()


def test_shutdown_waits_for_outstanding_writes() -> None:
    entered, release, stopped = Event(), Event(), Event()

    def work() -> bool:
        entered.set()
        release.wait(3)
        return True

    worker = Worker(work)
    worker.start()
    assert entered.wait(2)

    def stop() -> None:
        worker.stop()
        stopped.set()

    stopper = Thread(target=stop)
    stopper.start()
    assert not stopped.wait(0.05)
    release.set()
    assert stopped.wait(2)
    stopper.join()
