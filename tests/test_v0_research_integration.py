"""Real Runtime dispatch and public result routes retain canonical evidence gates."""

from pathlib import Path
from typing import Any

import pytest
from test_v0_publication_workflows import LocalClient
from test_v0_runtime import CONFIG, REPOSITORY, runner_at

from quant_hunter.web.api import create_app
from quant_hunter.web.runtime import Runtime
from quant_hunter.web.state import AccessError, User
from quant_hunter.web.studies import request_config
from quant_hunter.web.validation_jobs import ValidationControls


def client_for(runner: Runtime, user: User) -> LocalClient:
    app = create_app(
        runner.state.path.parent,
        REPOSITORY,
        patterns=runner.patterns,
        validation=runner.validation,
        quality=runner.quality,
        get_job=runner.job_detail,
        paper=runner.paper,
        paper_halt=runner.paper_halt,
    )
    client = LocalClient(app)
    token, session = runner.state.login(user.username, "synthetic-password-only")
    client.cookies.set("qh_session", token)
    client.headers.update({"X-QH-Request": "1", "X-CSRF-Token": session.csrf})
    return client


@pytest.fixture
def research(tmp_path: Path) -> tuple[Runtime, User, dict[str, Any]]:
    runner = runner_at(tmp_path)
    owner = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    dataset = runner.quality.demo(owner)["datasets"][0]  # type: ignore[index]
    assert isinstance(dataset, dict)
    return runner, owner, dataset


def test_corpus_and_pattern_use_actual_worker_and_verified_generic_route(
    research: tuple[Runtime, User, dict[str, Any]],
) -> None:
    runner, owner, dataset = research
    selection = runner.quality.compose(
        owner,
        (
            (
                dataset["dataset_id"],
                dataset["record_digest"],
                dataset["quality_report_digest"],
            ),
        ),
    )
    queued = runner.patterns.enqueue_corpus(owner, str(selection["manifest_digest"]))
    assert runner.process_one()
    detail = runner.job_detail(owner, queued.id)
    assert runner.state.job(owner, queued.id).status == "SUCCEEDED", detail
    corpus = detail["corpus"]
    assert isinstance(corpus, dict)
    prepared = runner.patterns.prepare(
        owner, str(corpus["dataset_id"]), family="PAT-05", scenario="POSITIVE"
    )
    job = runner.patterns.enqueue(owner, str(prepared["prepared_id"]))
    assert runner.process_one()
    assert runner.state.job(owner, job.id).status == "SUCCEEDED"
    client = client_for(runner, owner)
    route = client.get(f"/api/jobs/{job.id}")
    assert route.status_code == 200, route.text
    assert route.json() == runner.patterns.job(owner, job.id)
    run = route.json()["run"]
    assert run["variants_attempted"] == 1
    assert run["evaluation_outcome"] == "INCONCLUSIVE"
    # The generic endpoint must replay the same retained receipt graph.
    with runner.state.connection() as db:
        db.execute(
            "UPDATE pattern_job_receipts SET binding='{}' WHERE job_id=?", (job.id,)
        )
    assert client.get(f"/api/jobs/{job.id}").status_code == 503


def test_validation_dispatch_recovery_and_generic_evidence_gate(
    research: tuple[Runtime, User, dict[str, Any]],
) -> None:
    runner, owner, dataset = research
    job = runner.validation.submit(
        owner,
        dataset["dataset_id"],
        record_digest=dataset["record_digest"],
        quality_report_digest=dataset["quality_report_digest"],
        controls=ValidationControls(evaluation_as_of="2026-10-05T23:00:00Z"),
    )
    assert runner.process_one()
    finished = runner.state.job(owner, job.id)
    assert finished.status == "SUCCEEDED", finished.error
    client = client_for(runner, owner)
    response = client.get(f"/api/jobs/{job.id}")
    assert response.status_code == 200, response.text
    assert response.json() == runner.validation.get(owner, job.id)
    run = response.json()["run"]
    assert run["variants_attempted"] == 1
    assert run["result"]["canonical_models"]
    with runner.state.connection() as db:
        db.execute("UPDATE jobs SET status='RUNNING' WHERE id=?", (job.id,))
    runner.recover()
    assert runner.state.job(owner, job.id).status == "SUCCEEDED"
    assert runner.lab.get_run(str(finished.experiment_id))["variants_attempted"] == 1
    # Removing a referenced report cannot be bypassed through generic job detail.
    runner.lab.objects.get(run["result"]["report_digest"]).path.unlink()
    assert client.get(f"/api/jobs/{job.id}").status_code == 503
    foreign = runner.state.create_user(
        "other", "synthetic-password-only", "researcher", bootstrap=False
    )
    assert client_for(runner, foreign).get(f"/api/jobs/{job.id}").status_code == 403


def test_demoted_queued_actor_cannot_compute_or_enqueue_with_stale_authority(
    tmp_path: Path,
) -> None:
    runner = runner_at(tmp_path)
    owner = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    job = runner.state.enqueue(owner, CONFIG)
    with runner.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (owner.id,))
    with pytest.raises(AccessError):
        runner.state.enqueue(owner, CONFIG)
    assert runner.process_one()
    failed = runner.state.job(owner, job.id)
    assert failed.status == "FAILED" and failed.experiment_id is None
    assert runner.lab.list_runs() == []


def test_stopped_worker_rejects_pattern_queues_before_any_side_effect(
    research: tuple[Runtime, User, dict[str, Any]],
) -> None:
    runner, owner, _ = research
    client = client_for(runner, owner)
    assert (
        client.post(
            "/api/patterns/corpora", json={"selection_digest": "sha256:" + "0" * 64}
        ).status_code
        == 503
    )
    assert (
        client.post("/api/patterns/jobs", json={"prepared_id": "0" * 32}).status_code
        == 503
    )
    assert runner.state.jobs(owner) == []


@pytest.mark.parametrize("kind", ["backtest", "study"])
def test_capacity_refusal_precedes_direct_research_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    runner = runner_at(tmp_path)
    owner = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    job = runner.state.enqueue(
        owner, CONFIG if kind == "backtest" else request_config("CRP-01", "POSITIVE")
    )
    before = {
        path.relative_to(runner.state.path.parent).as_posix(): path.read_bytes()
        for path in (runner.state.path.parent / "research").rglob("*")
        if path.is_file()
    }

    def reject() -> None:
        raise AccessError("Synthetic known capacity refusal")

    monkeypatch.setattr(runner.data, "_capacity", reject)
    assert runner.process_one()
    assert runner.state.job(owner, job.id).status == "FAILED"
    after = {
        path.relative_to(runner.state.path.parent).as_posix(): path.read_bytes()
        for path in (runner.state.path.parent / "research").rglob("*")
        if path.is_file()
    }
    assert after == before
    assert runner.lab.list_runs() == []


def test_busy_validation_reads_are_retryable_and_foreign_reads_remain_denied(
    research: tuple[Runtime, User, dict[str, Any]],
) -> None:
    runner, owner, dataset = research
    job = runner.validation.submit(
        owner,
        dataset["dataset_id"],
        record_digest=dataset["record_digest"],
        quality_report_digest=dataset["quality_report_digest"],
        controls=ValidationControls(evaluation_as_of="2026-10-05T23:00:00Z"),
    )
    client = client_for(runner, owner)
    foreign = runner.state.create_user(
        "other", "synthetic-password-only", "reader", bootstrap=False
    )
    foreign_client = client_for(runner, foreign)
    with runner.quality.inspection(owner), runner.quality.inspection(owner):
        for prefix in ("/api/validations/jobs/", "/api/jobs/"):
            response = client.get(prefix + job.id)
            assert response.status_code == 503
            assert response.headers["Retry-After"] == "3"
            assert foreign_client.get(prefix + job.id).status_code == 403
    response = client.get("/api/validations/jobs/" + job.id)
    assert response.status_code == 200
    assert response.json()["job"]["status"] == "QUEUED"
    assert runner.lab.list_runs() == []


def test_paper_read_routes_use_actual_shared_capacity_and_release(
    tmp_path: Path,
) -> None:
    from quant_hunter.web.paper_access import default_paper_config

    runner = runner_at(tmp_path)
    owner = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    job = runner.paper.create(owner, default_paper_config())
    client = client_for(runner, owner)
    with runner.quality.inspection(owner), runner.quality.inspection(owner):
        for path in ("/api/paper/sessions", "/api/paper/sessions/" + str(job["id"])):
            response = client.get(path)
            assert response.status_code == 503
            assert response.headers["Retry-After"] == "3"
    assert client.get("/api/paper/sessions/" + str(job["id"])).status_code == 200
    assert len(client.get("/api/paper/sessions").json()) == 1
    with runner.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0] == 0
    assert runner.lab.list_runs() == []
