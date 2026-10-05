"""Executed local API authorization, failure and operational persistence proofs."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quant_hunter.web.api import create_app
from quant_hunter.web.state import AccessError, AppState, User
from quant_hunter.web.worker import Worker

PASSWORD = "synthetic-test-password-only"  # noqa: S105


def client_for(tmp_path: Path, *, worker: bool = True) -> TestClient:
    (tmp_path / "repo" / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "repo" / "artifacts" / "status.json").write_text(
        '{"status":"IN_PROGRESS"}'
    )
    return TestClient(
        create_app(
            tmp_path / "runtime",
            tmp_path / "repo",
            process_job=(lambda: False) if worker else None,
            get_run=lambda exp: {"experiment_id": exp},
            fixtures=[{"market": "EQUITY", "mode": "SYNTHETIC"}],
        )
    )


def setup(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/setup",
        headers={"X-QH-Request": "1"},
        json={"username": "owner", "password": PASSWORD},
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    return {"X-QH-Request": "1", "X-CSRF-Token": response.json()["csrf"]}


def test_bootstrap_sessions_and_no_secret_echo(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        assert client.get("/api/session").json()["needs_owner"]
        assert client.get("/api/jobs").status_code == 401
        headers = setup(client)
        assert client.get("/api/session").json()["user"]["role"] == "owner"
        assert (
            client.post(
                "/api/setup",
                headers=headers,
                json={"username": "another", "password": PASSWORD},
            ).status_code
            == 403
        )
        response = client.post(
            "/api/login",
            headers={"X-QH-Request": "1"},
            json={"username": "owner", "password": "secret"},
        )
        assert response.status_code == 422
        assert "secret" not in response.text
        assert PASSWORD not in client.get("/api/users").text
        assert (
            client.post("/api/logout", headers={"X-QH-Request": "1"}).status_code == 403
        )
        assert client.post("/api/logout", headers=headers).status_code == 200
        assert client.get("/api/session").json()["user"] is None
        assert client.get("/api/jobs").status_code == 401
        assert (
            client.post(
                "/api/login",
                headers={"X-QH-Request": "1"},
                json={"username": "owner", "password": PASSWORD},
            ).status_code
            == 200
        )


def test_host_origin_csrf_body_limit_and_headers(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        payload = {"username": "owner", "password": PASSWORD}
        assert client.post("/api/setup", json=payload).status_code == 403
        assert (
            client.post(
                "/api/setup",
                headers={"X-QH-Request": "1", "Origin": "https://evil.example"},
                json=payload,
            ).status_code
            == 403
        )
        assert (
            client.get("/api/session", headers={"Host": "evil.example"}).status_code
            == 400
        )
        assert (
            client.post(
                "/api/login", headers={"X-QH-Request": "1"}, content=b"x" * 65537
            ).status_code
            == 413
        )
        headers = setup(client)
        response = client.get("/api/session")
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert (
            client.post(
                "/api/jobs", headers={**headers, "X-CSRF-Token": "wrong"}, json={}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/jobs", headers=headers, json={"market": "LIVE"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/jobs", headers=headers, json={"lookback": True}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/jobs", headers=headers, json={"quantity": "NaN"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/jobs", headers=headers, json={"extra": "ignored?"}
            ).status_code
            == 422
        )


def test_roles_private_jobs_cancel_and_result(tmp_path: Path) -> None:
    with client_for(tmp_path) as owner:
        headers = setup(owner)
        for name, role in [("reader", "reader"), ("researcher", "researcher")]:
            assert (
                owner.post(
                    "/api/users",
                    headers=headers,
                    json={"username": name, "password": PASSWORD, "role": role},
                ).status_code
                == 200
            )
        queued = owner.post("/api/jobs", headers=headers, json={}).json()
        state = cast(AppState, cast(FastAPI, owner.app).state.store)
        claimed = state.claim()
        assert claimed and claimed.id == queued["id"]
        state.bind(claimed.id, "EXP-test-reference")
        state.finish(claimed.id)
        result = owner.get(f"/api/jobs/{claimed.id}").json()
        assert result["run"]["experiment_id"] == "EXP-test-reference"
        assert result["job"]["status"] == "SUCCEEDED"
        for name in ("reader", "researcher"):
            with client_for(tmp_path) as other:
                login = other.post(
                    "/api/login",
                    headers={"X-QH-Request": "1"},
                    json={"username": name, "password": PASSWORD},
                )
                oh = {"X-QH-Request": "1", "X-CSRF-Token": login.json()["csrf"]}
                assert other.get("/api/jobs").json() == []
                assert other.get(f"/api/jobs/{claimed.id}").status_code == 403
                assert (
                    other.post(f"/api/jobs/{claimed.id}/cancel", headers=oh).status_code
                    == 403
                )
                assert other.get("/api/users").status_code == 403
                assert (
                    other.post(
                        "/api/users",
                        headers=oh,
                        json={
                            "username": "intruder",
                            "password": PASSWORD,
                            "role": "owner",
                        },
                    ).status_code
                    == 403
                )
                submitted = other.post("/api/jobs", headers=oh, json={})
                assert submitted.status_code == (403 if name == "reader" else 202)
                if name == "researcher":
                    assert (
                        other.post(
                            f"/api/jobs/{submitted.json()['id']}/cancel", headers=oh
                        ).status_code
                        == 200
                    )
        assert owner.get("/api/fixtures").json()[0]["mode"] == "SYNTHETIC"
        project = owner.get("/api/project").json()
        assert project["live_trading"] == "DISABLED"
        assert project["worker"] == "RUNNING"


def test_unavailable_worker_is_explicit(tmp_path: Path) -> None:
    with client_for(tmp_path, worker=False) as client:
        headers = setup(client)
        assert client.post("/api/jobs", headers=headers, json={}).status_code == 503
        assert client.get("/api/project").json()["worker"] == "STOPPED"


def test_failed_worker_rejects_new_submissions(tmp_path: Path) -> None:
    def broken() -> bool:
        raise RuntimeError("synthetic worker failure")

    app = create_app(tmp_path / "runtime", tmp_path, process_job=broken)
    with TestClient(app) as client:
        headers = setup(client)
        assert client.post("/api/jobs", headers=headers, json={}).status_code == 503


def test_exceptional_lifespan_stops_worker(tmp_path: Path) -> None:
    app = create_app(tmp_path / "runtime", tmp_path, process_job=lambda: False)

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="synthetic lifespan error"):
            async with app.router.lifespan_context(app):
                assert app.state.worker.alive
                raise RuntimeError("synthetic lifespan error")
        assert not app.state.worker.alive

    asyncio.run(scenario())


def test_operational_queue_is_atomic_and_persistent(tmp_path: Path) -> None:
    state = AppState(tmp_path / "state.sqlite3")
    user = state.create_user("user", PASSWORD, "owner", bootstrap=True)
    jobs = [state.enqueue(user, {"market": "EQUITY"}) for _ in range(8)]
    with pytest.raises(AccessError, match="Queue is full"):
        state.enqueue(user, {})
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = list(pool.map(lambda _: state.claim(), range(10)))
    ids = [job.id for job in claimed if job]
    assert sorted(ids) == sorted(job.id for job in jobs)
    reopened = AppState(state.path)
    assert len(reopened.interrupted()) == 8
    reopened.bind(jobs[0].id, "EXP-reference")
    reopened.finish(jobs[0].id, error="WorkerInterrupted")
    assert reopened.job(user, jobs[0].id).error == "WorkerInterrupted"
    assert reopened.job(user, jobs[0].id).experiment_id == "EXP-reference"
    assert len(reopened.interrupted()) == 7
    with pytest.raises(AccessError):
        reopened.cancel(user, jobs[0].id)
    queued = reopened.enqueue(user, {})
    reopened.cancel(user, queued.id)
    assert reopened.job(user, queued.id).status == "CANCELLED"
    with pytest.raises(AccessError):
        reopened.job(User(user.id + 1, "other", "reader"), jobs[0].id)


def test_password_sessions_expiry_and_login_throttle(tmp_path: Path) -> None:
    state = AppState(tmp_path / "state.sqlite3")
    user = state.create_user("user", PASSWORD, "owner", bootstrap=True)
    with pytest.raises(AccessError):
        state.create_user("user", PASSWORD, "reader", bootstrap=False)
    for _ in range(5):
        with pytest.raises(AccessError, match="Invalid username"):
            state.login("missing", PASSWORD)
    with pytest.raises(AccessError, match="temporarily limited"):
        state.login("missing", PASSWORD)
    token, session = state.login("user", PASSWORD)
    assert state.session(token).user == user
    assert session.csrf
    assert token.encode() not in state.path.read_bytes()
    assert PASSWORD.encode() not in state.path.read_bytes()
    with state.connection() as db:
        db.execute("UPDATE sessions SET expires=0")
        db.execute("UPDATE login_attempts SET since=0")
    with pytest.raises(AccessError, match="Sign in"):
        state.session(token)
    with pytest.raises(AccessError, match="Invalid username"):
        state.login("missing", PASSWORD)


def test_worker_success_stop_and_failure() -> None:
    observed = Event()

    def process() -> bool:
        observed.set()
        return False

    worker = Worker(process)
    worker.start()
    assert observed.wait(2)
    assert bool(worker.alive)
    worker.stop()
    assert not bool(worker.alive)

    def broken() -> bool:
        raise RuntimeError("sensitive upstream payload")

    worker = Worker(broken)
    worker.start()
    deadline = time.monotonic() + 2
    while worker.alive and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    assert worker.failed
