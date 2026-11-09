"""Actual product wiring with native persistence and strictly local transports."""

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn, cast

import pytest
from fastapi.testclient import TestClient
from test_v0_archive_files import profile_case
from test_v0_runtime import CONFIG, REPOSITORY, TEST_REVISION
from test_v0_source_schedules import LocalService
from test_v0_web import setup

from quant_hunter.config import JsonRecord
from quant_hunter.paper_brokers.transport import FixedPaperHTTPS
from quant_hunter.web.api import create_app
from quant_hunter.web.runtime import Runtime
from quant_hunter.web.source_schedules import ScheduleError


def test_all_archive_profiles_use_actual_upload_route_and_closed_units_map(
    tmp_path: Path,
) -> None:
    runner = native(tmp_path)
    with TestClient(
        create_app(tmp_path / "runtime", REPOSITORY, data=runner.data)
    ) as client:
        headers = setup(client)
        for name in ("CES", "RTDSM", "PHILLY", "ECB", "FORWARD"):
            source, raw, metadata = profile_case(name)
            payload = {
                "content_base64": base64.b64encode(raw).decode("ascii"),
                "metadata": metadata,
            }
            response = client.post(
                f"/api/sources/{source}/import", headers=headers, json=payload
            )
            assert response.status_code == 201, response.text
            result = response.json()
            assert result["status"] == "SUCCEEDED", result
            assert result["quality"] == "PENDING"
            assert runner.lab.objects.get(result["raw_digest"]).path.read_bytes() == raw
            assert all(
                row["available_at"] is None and row["point_in_time_eligible"] is False
                for row in result["preview"]
            )
        source, raw, metadata = profile_case("RTDSM")
        payload = {
            "content_base64": base64.b64encode(raw).decode("ascii"),
            "metadata": metadata,
        }
        for invalid in (
            {**metadata, "declared_license": {"nested": "forbidden"}},
            {**metadata, "profile": "OTHER"},
            {**metadata, "vintage_units": {}},
            {**metadata, "vintage_units": {str(i): "unit" for i in range(128)}},
            {**metadata, "vintage_units": {"column": {"nested": "forbidden"}}},
        ):
            response = client.post(
                f"/api/sources/{source}/import",
                headers=headers,
                json={**payload, "metadata": invalid},
            )
            assert response.status_code == 422


def native(tmp_path: Path) -> Runtime:
    return Runtime(
        tmp_path / "runtime",
        REPOSITORY,
        TEST_REVISION,
        private_root=tmp_path / "private",
    )


def test_native_source_collection_routes_persist_one_job_without_experiment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker_send_attempts: list[bool] = []

    def refuse_broker_send(_self: object, _request: object) -> NoReturn:
        broker_send_attempts.append(True)
        raise AssertionError("Startup/configuration inspection attempted a broker send")

    monkeypatch.setattr(FixedPaperHTTPS, "send", refuse_broker_send)
    runner = native(tmp_path)
    clock = [datetime.now(UTC)]
    runner.source_schedules.clock = lambda: clock[0]
    monkeypatch.setattr(
        "quant_hunter.web.data_access.time.time", lambda: clock[0].timestamp()
    )
    local = LocalService()
    runner.data.prober = local
    with TestClient(
        create_app(
            tmp_path / "runtime",
            REPOSITORY,
            data=runner.data,
            source_schedules=runner.source_schedules,
            signals=runner.signals,
            brokers=runner.brokers,
            collection_error=lambda: runner.collection_error,
        )
    ) as client:
        assert client.get("/api/collection-worker/status").status_code == 401
        headers = setup(client)
        owner = runner.state.user(1)
        assert client.get("/api/signals/paper/sessions").status_code == 200
        assert client.get("/api/signals/research/jobs").status_code == 200
        created = client.post(
            "/api/source-schedules",
            headers=headers,
            json={
                "catalogue_id": "SRC-04",
                "interval_seconds": 3600,
                "maximum_runs": 1,
            },
        )
        assert created.status_code == 200
        head = created.json()
        assert head["status"] == "PAUSED"
        assert not runner.process_one()
        assert local.calls == []
        active = client.post(
            f"/api/source-schedules/{head['id']}/control",
            headers=headers,
            json={"action": "ACTIVATE", "expected_revision": head["revision"]},
        )
        assert active.status_code == 200
        clock[0] += timedelta(hours=1)
        runner._collection_due = 0
        assert runner.process_one()
        history = runner.source_schedules.history(owner, head["id"])
        receipt = cast(JsonRecord, history[0]["receipt"])
        assert receipt["status"] == "SUCCEEDED"
        occurrence = cast(JsonRecord, history[0]["occurrence"])
        job = runner.state.job(owner, str(occurrence["job_id"]))
        assert job.status == "SUCCEEDED" and job.experiment_id is None
        assert runner.lab.list_runs() == []
        assert local.calls == ["SRC-04"]
        status = client.get("/api/collection-worker/status")
        assert status.status_code == 200 and status.json()["error"] is None
        assert status.headers["Cache-Control"] == "no-store"
        assert isinstance(runner.brokers.read_transport, FixedPaperHTTPS)
        assert runner.brokers.read_transport.network_enabled
        # Merely inspecting unconfigured broker settings cannot call its transport.
        assert client.get("/api/paper-brokers/configuration").status_code == 200
        assert local.calls == ["SRC-04"]
    restarted = native(tmp_path)
    restarted.data.prober = local
    restarted.recover()
    assert restarted.source_schedules.get(owner, head["id"])["status"] == "COMPLETED"
    assert not restarted.process_one()
    assert local.calls == ["SRC-04"]
    assert broker_send_attempts == []


def test_collection_pump_failure_does_not_stop_existing_native_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = native(tmp_path)
    owner = runner.state.create_user(
        "owner", "local-test-password-only", "owner", bootstrap=True
    )
    job = runner.state.enqueue(owner, CONFIG)
    original = runner.source_schedules.pump_due

    def failed() -> bool:
        raise ScheduleError("private diagnostic must never be exposed")

    monkeypatch.setattr(runner.source_schedules, "pump_due", failed)
    assert runner.process_one()
    assert runner.collection_error == "COLLECTION_PUMP_UNAVAILABLE"
    assert runner.state.job(owner, job.id).status == "SUCCEEDED"
    monkeypatch.setattr(runner.source_schedules, "pump_due", original)
    runner._collection_due = float("inf")
    assert not runner.process_one()
    assert runner.collection_error == "COLLECTION_PUMP_UNAVAILABLE"
    runner._collection_due = 0
    assert not runner.process_one()
    assert runner.collection_error is None


def test_native_collection_demotion_is_settled_by_source_authority(
    tmp_path: Path,
) -> None:
    runner = native(tmp_path)
    owner = runner.state.create_user(
        "owner", "local-test-password-only", "owner", bootstrap=True
    )
    clock = [datetime.now(UTC)]
    runner.source_schedules.clock = lambda: clock[0]
    local = LocalService()
    runner.data.prober = local
    head = runner.source_schedules.create(
        owner, "SRC-04", interval_seconds=3600, maximum_runs=1
    )
    runner.source_schedules.control(
        owner, str(head["id"]), "ACTIVATE", expected_revision=1
    )
    clock[0] += timedelta(hours=1)
    assert runner.source_schedules.pump_due()
    with runner.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (owner.id,))
    assert runner.process_one()
    current = runner.state.user(owner.id)
    history = runner.source_schedules.history(current, str(head["id"]))
    assert cast(JsonRecord, history[0]["receipt"])["status"] == "FAILED"
    assert runner.source_schedules.get(current, str(head["id"]))["status"] == "PAUSED"
    assert local.calls == [] and runner.lab.list_runs() == []
