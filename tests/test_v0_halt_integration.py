"""Actual Runtime halt admission, bounded worker backpressure and API authority."""

from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from test_v0_research_integration import client_for
from test_v0_runtime import runner_at

from quant_hunter.config import JsonRecord
from quant_hunter.web.admission import resource_counts
from quant_hunter.web.paper_access import default_paper_config
from quant_hunter.web.runtime import Runtime
from quant_hunter.web.state import AccessError, ResourceBusyError, User
from quant_hunter.web.worker import Worker


def prepared(tmp_path: Path) -> tuple[Runtime, User, str]:
    runner = runner_at(tmp_path)
    owner = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    configuration = default_paper_config()
    configuration["bars"] = 20
    job = runner.paper.create(owner, configuration)
    identity = cast(str, job["id"])
    runner.paper.control(
        owner, identity, "ACTIVATE", expected_revision=cast(int, job["revision"])
    )
    for _ in range(4):
        assert runner.paper.process_one()
    current = runner.paper.get(owner, identity)
    runner.paper.control(
        owner, identity, "PAUSE", expected_revision=cast(int, current["revision"])
    )
    return runner, owner, identity


def counts(runner: Runtime) -> tuple[int, int]:
    with runner.state.connection() as db:
        return resource_counts(db)


def test_verified_halt_reader_borrows_exact_reservation_at_full_queue(
    tmp_path: Path,
) -> None:
    runner, owner, identity = prepared(tmp_path)
    for _ in range(7):
        runner.paper.create(owner, default_paper_config())
    assert counts(runner) == (0, 8)
    runner.paper_halt.halt(owner, expected_revision=0)
    with pytest.raises(ResourceBusyError):
        with runner.quality.inspection(owner):
            pytest.fail("ordinary reader must not bypass full queue")
    with runner.halt_reads.inspection(owner, identity, 1):
        assert counts(runner) == (1, 8)
        with pytest.raises(ResourceBusyError):
            with runner.halt_reads.inspection(owner, identity, 1):
                pytest.fail("duplicate linked reader admitted")
    assert counts(runner) == (0, 8)
    for _ in range(8):
        assert runner.paper_halt.process_one()
    assert runner.paper_halt.status(owner)["counts"] == {
        "pending": 0,
        "protected": 8,
        "blocked": 0,
    }
    runner.paper_halt.clear(owner, expected_revision=1)
    assert counts(runner) == (0, 8)
    assert runner.paper.get(owner, identity)["status"] == "PAUSED"
    assert runner.paper.engine.load(identity, str(owner.id)).killed
    with runner.state.connection() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM resource_paper_links").fetchone()[0] == 0
        )


def test_linked_reader_retains_orphan_stale_count_and_cleans_exception(
    tmp_path: Path,
) -> None:
    runner, owner, identity = prepared(tmp_path)
    runner.paper_halt.halt(owner, expected_revision=0)
    with pytest.raises(RuntimeError, match="synthetic"):
        with runner.halt_reads.inspection(owner, identity, 1):
            assert counts(runner) == (1, 1)
            with runner.state.connection() as db:
                db.execute(
                    "UPDATE resource_paper_links SET workflow_revision=workflow_revision+1"
                )
            assert counts(runner) == (1, 2)
            raise RuntimeError("synthetic")
    assert counts(runner) == (0, 1)
    foreign = runner.state.create_user(
        "foreign", "synthetic-password-only", "researcher", bootstrap=False
    )
    with pytest.raises(AccessError):
        with runner.halt_reads.inspection(foreign, identity, 1):
            pytest.fail("unrelated actor borrowed cross-owner reservation")
    assert counts(runner) == (0, 1)


def test_busy_halt_read_backs_off_without_terminating_actual_worker(
    tmp_path: Path,
) -> None:
    runner, owner, _ = prepared(tmp_path)
    runner.paper_halt.halt(owner, expected_revision=0)
    observed = Event()

    def process() -> bool:
        result = runner.process_one()
        observed.set()
        return result

    worker = Worker(process)
    with runner.quality.inspection(owner), runner.quality.inspection(owner):
        worker.start()
        try:
            assert observed.wait(10)
            assert worker.alive and not worker.failed
            assert runner.paper_halt.status(owner)["counts"] == {
                "pending": 1,
                "protected": 0,
                "blocked": 0,
            }
        except BaseException:
            worker.stop()
            raise
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = cast(JsonRecord, runner.paper_halt.status(owner)["counts"])
            if status["protected"] == 1:
                break
            time.sleep(0.05)
        assert status == {"pending": 0, "protected": 1, "blocked": 0}
        assert worker.alive and not worker.failed
    finally:
        worker.stop()
    assert counts(runner) == (0, 1)


def test_halt_routes_owner_csrf_cas_and_private_reader_projection(
    tmp_path: Path,
) -> None:
    runner = runner_at(tmp_path)
    owner = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    reader = runner.state.create_user(
        "reader", "synthetic-password-only", "reader", bootstrap=False
    )
    client, readonly = client_for(runner, owner), client_for(runner, reader)
    assert client.get("/api/paper/halt").json()["revision"] == 0
    assert (
        readonly.post("/api/paper/halt", json={"expected_revision": 0}).status_code
        == 403
    )
    assert (
        client.post("/api/paper/halt", json={"expected_revision": 0}).status_code == 200
    )
    private = readonly.get("/api/paper/halt").json()
    assert private["halted"] is True and "counts" not in private
    assert (
        client.post("/api/paper/halt/clear", json={"expected_revision": 0}).status_code
        == 409
    )
    assert (
        client.post("/api/paper/halt/clear", json={"expected_revision": 1}).status_code
        == 200
    )
    client.headers.pop("X-CSRF-Token")
    assert (
        client.post("/api/paper/halt", json={"expected_revision": 2}).status_code == 403
    )
    assert runner.paper_halt.status(owner)["revision"] == 2


def test_owned_resume_preflight_borrows_at_eight_and_releases_before_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, owner, identity = prepared(tmp_path)
    for _ in range(7):
        runner.paper.create(owner, default_paper_config())
    before = runner.paper.operational_head(owner, identity)
    real = runner.paper._binding
    observed: list[tuple[int, int]] = []

    def binding(
        row: JsonRecord, *, current: bool = False
    ) -> tuple[JsonRecord, JsonRecord]:
        if current:
            observed.append(counts(runner))
        return real(row, current=current)

    monkeypatch.setattr(runner.paper, "_binding", binding)
    response = runner.paper.control(
        owner, identity, "RESUME", expected_revision=cast(int, before["revision"])
    )
    assert observed == [(1, 8)]
    assert response["status"] == "ACTIVE"
    assert response["report_verification"] == "NOT_FRESH_ADMISSION"
    assert "report" not in response
    assert counts(runner) == (0, 8)
    with runner.state.connection() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM resource_resume_links").fetchone()[0] == 0
        )


def test_duplicate_cross_kind_links_never_subtract_same_paper_twice(
    tmp_path: Path,
) -> None:
    runner, owner, identity = prepared(tmp_path)
    runner.paper_halt.halt(owner, expected_revision=0)
    with runner.halt_reads.inspection(owner, identity, 1):
        with runner.state.connection() as db:
            revision = db.execute(
                "SELECT revision FROM paper_jobs WHERE id=?", (identity,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO resource_readers VALUES('synthetic-second',?,0)",
                (owner.id,),
            )
            db.execute(
                "INSERT INTO resource_resume_links VALUES('synthetic-second',?,?,?)",
                (identity, owner.id, revision),
            )
        assert counts(runner) == (2, 2)
        with runner.state.connection() as db:
            db.execute("DELETE FROM resource_readers WHERE id='synthetic-second'")
    assert counts(runner) == (0, 1)
