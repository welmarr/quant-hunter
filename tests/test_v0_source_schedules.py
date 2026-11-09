"""Durable fixed public collection contracts; all transports are local fixtures."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Literal, cast

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.web.admission import resource_counts
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.source_schedule_routes import install_source_schedule_routes
from quant_hunter.web.source_schedules import (
    ScheduleError,
    SourceSchedules,
    public_profile,
)
from quant_hunter.web.state import AccessError, AppState, Job, Session, User


class Crash(BaseException):
    """Process interruption, deliberately outside ordinary exception recovery."""


class LocalService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.on_probe: Callable[[], None] = lambda: None
        self.result: JsonRecord = {
            "status": "SUCCEEDED",
            "evidence_mode": "RECORDED_FIXTURE",
        }

    def probe(self, catalogue_id: str) -> JsonRecord:
        self.calls.append(catalogue_id)
        self.on_probe()
        return {**self.result, "catalogue_id": catalogue_id}

    def import_bytes(
        self,
        payload: bytes,
        *,
        file_format: Literal["CSV", "PARQUET"],
        metadata: Mapping[str, JsonValue],
        corrects_dataset_id: str | None = None,
        correction_reason: str | None = None,
    ) -> JsonRecord:
        raise AssertionError("A collection cannot import OHLC research data")

    def get_dataset(self, dataset_id: str) -> JsonRecord:
        raise AssertionError("A collection cannot expose an arbitrary dataset")


@dataclass
class Harness:
    data: DataAccess
    backend: LocalService
    schedules: SourceSchedules
    owner: User
    now: list[datetime]

    def create(self, source: str = "SRC-04", runs: int = 3) -> JsonRecord:
        return self.schedules.create(
            self.owner, source, interval_seconds=3600, maximum_runs=runs
        )

    def start(self, source: str = "SRC-04", runs: int = 3) -> JsonRecord:
        head = self.create(source, runs)
        return self.control(head, "ACTIVATE")

    def control(self, head: JsonRecord, action: str) -> JsonRecord:
        return self.schedules.control(
            self.owner,
            str(head["id"]),
            action,
            expected_revision=cast(int, head["revision"]),
        )

    def due(self) -> Job:
        self.now[0] += timedelta(hours=1)
        assert self.schedules.pump_due()
        job = self.data.state.claim()
        assert job is not None
        return job

    def head(self, first: JsonRecord) -> JsonRecord:
        return self.schedules.get(self.owner, str(first["id"]))

    def receipt(self, first: JsonRecord) -> JsonRecord:
        history = self.schedules.history(self.owner, str(first["id"]))
        return cast(JsonRecord, history[-1]["receipt"])


@pytest.fixture
def h(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    state = AppState(tmp_path / "application.sqlite3")
    owner = state.create_user(
        "collector", "fixture-password-never-a-provider-key", "owner", bootstrap=True
    )
    backend = LocalService()
    data = DataAccess(state, tmp_path, backend, backend)
    monkeypatch.setattr(data, "_capacity", lambda: None)
    now = [datetime(2026, 10, 5, tzinfo=UTC)]
    monkeypatch.setattr(
        "quant_hunter.web.data_access.time.time", lambda: now[0].timestamp()
    )
    return Harness(
        data, backend, SourceSchedules(data, clock=lambda: now[0]), owner, now
    )


@pytest.mark.parametrize("source", ["SRC-04", "SRC-06", "SRC-08"])
def test_fixed_profile_occurrence_and_operation_are_durable_before_fetch(
    h: Harness, source: str
) -> None:
    first = h.start(source, runs=1)
    assert first["status"] == "ENABLED" and h.backend.calls == []
    assert h.schedules.pump_due() is False
    job = h.due()

    def inspect() -> None:
        with h.data.state.connection() as db:
            assert resource_counts(db) == (1, 1)
            assert (
                db.execute("SELECT COUNT(*) FROM collection_occurrences").fetchone()[0]
                == 1
            )
            assert (
                db.execute("SELECT COUNT(*) FROM collection_dispatches").fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM collection_operation_links"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute("SELECT worker_job_id FROM data_operations").fetchone()[0]
                == job.id
            )

    h.backend.on_probe = inspect
    h.schedules.execute_job(job)
    assert h.backend.calls == [source]
    assert h.head(first)["status"] == "COMPLETED"
    receipt = h.receipt(first)
    assert receipt["status"] == "SUCCEEDED"
    assert receipt["result_digest"] and receipt["occurrence_digest"]
    assert h.data.state.job(h.owner, job.id).experiment_id is None
    assert h.data.state.job(h.owner, job.id).status == "SUCCEEDED"
    assert h.schedules.pump_due() is False


def test_exact_mission_profiles_are_not_current_or_credential_subscriptions() -> None:
    assert public_profile("SRC-04")["query"] == {
        "series_id": "CES0000000001",
        "start": "2024-01-01",
        "end": "2024-12-31",
        "unit": "thousands of persons",
    }
    assert public_profile("SRC-06")["query"] == {
        "release_date": "2025-01-17",
        "expected_base_year": 2017,
    }
    assert public_profile("SRC-08")["query"] == {
        "series_id": "D.USD.EUR.SP00.A",
        "start": "2024-01-02",
        "end": "2024-01-05",
        "unit": "USD per EUR",
    }
    for source in ("SRC-04", "SRC-06", "SRC-08"):
        assert public_profile(source)["freshness_claim"] is False
        assert public_profile(source)["credentials_required"] is False


@pytest.mark.parametrize(
    ("source", "interval", "runs"),
    [
        ("SRC-07", 3600, 1),
        ("SRC-01", 3600, 1),
        ("SRC-04", 3599, 1),
        ("SRC-04", 604801, 1),
        ("SRC-04", True, 1),
        ("SRC-04", 3600, 0),
        ("SRC-04", 3600, 31),
        ("SRC-04", 3600, True),
    ],
)
def test_closed_schedule_configuration(
    h: Harness, source: str, interval: int, runs: int
) -> None:
    with pytest.raises(ScheduleError):
        h.schedules.create(
            h.owner, source, interval_seconds=interval, maximum_runs=runs
        )
    assert h.schedules.list_schedules(h.owner) == []


def test_owner_checks_are_fresh_private_and_reader_only_after_demotion(
    h: Harness,
) -> None:
    first = h.create()
    other = h.data.state.create_user(
        "other", "synthetic-password", "owner", bootstrap=False
    )
    with pytest.raises(AccessError):
        h.schedules.get(other, str(first["id"]))
    with pytest.raises(AccessError):
        h.schedules.history(other, str(first["id"]))
    assert h.schedules.list_schedules(other) == []
    with h.data.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (h.owner.id,))
    with pytest.raises(AccessError):
        h.control(first, "ACTIVATE")
    reader = replace(h.owner, role="reader")
    assert h.schedules.get(reader, str(first["id"])) == first
    with pytest.raises(AccessError):
        h.schedules.create(reader, "SRC-04", interval_seconds=3600, maximum_runs=1)


def test_owner_demotion_before_due_or_after_claim_never_fetches(h: Harness) -> None:
    first = h.start()
    with h.data.state.connection() as db:
        db.execute("UPDATE users SET role='researcher' WHERE id=?", (h.owner.id,))
    h.now[0] += timedelta(hours=1)
    assert h.schedules.pump_due()
    researcher = replace(h.owner, role="researcher")
    assert (
        h.schedules.get(researcher, str(first["id"]))["reason"]
        == "CURRENT_OWNER_REQUIRED"
    )
    assert h.data.state.claim() is None
    with h.data.state.connection() as db:
        db.execute("UPDATE users SET role='owner' WHERE id=?", (h.owner.id,))
    h.control(h.head(first), "RESUME")
    job = h.due()
    with h.data.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (h.owner.id,))
    h.schedules.execute_job(job)
    assert h.backend.calls == []
    assert h.data.state.job(h.owner, job.id).status == "FAILED"


def test_skip_missed_windows_no_burst_or_automatic_failure_retry(h: Harness) -> None:
    first = h.start()
    h.now[0] += timedelta(hours=10, seconds=7)
    assert h.schedules.pump_due()
    assert h.schedules.pump_due() is False
    history = h.schedules.history(h.owner, str(first["id"]))
    assert cast(JsonRecord, history[0]["occurrence"])["skipped_windows"] == 9
    job = h.data.state.claim()
    assert job is not None
    h.backend.result = {"status": "FAILED", "error_code": "HTTP_429"}
    h.schedules.execute_job(job)
    assert h.head(first)["status"] == "PAUSED"
    h.now[0] += timedelta(days=20)
    assert h.schedules.pump_due() is False
    assert h.backend.calls == ["SRC-04"]
    resumed = h.control(h.head(first), "RESUME")
    assert resumed["next_due_unix"] == int(h.now[0].timestamp()) + 3600


@pytest.mark.parametrize("action", ["PAUSE", "CANCEL", "GENERIC_CANCEL"])
def test_queued_cancellation_has_receipt_and_no_fetch(h: Harness, action: str) -> None:
    first = h.start()
    h.now[0] += timedelta(hours=1)
    assert h.schedules.pump_due()
    head = h.head(first)
    if action == "GENERIC_CANCEL":
        h.data.state.cancel(h.owner, str(head["pending_job_id"]))
        assert h.schedules.pump_due()
    else:
        h.control(head, action)
    assert h.head(first)["pending_job_id"] is None
    assert h.receipt(first)["status"] == "CANCELLED_BEFORE_FETCH"
    assert h.head(first)["last_receipt_digest"] is not None
    assert h.data.state.claim() is None and h.backend.calls == []


@pytest.mark.parametrize("action", ["PAUSE", "CANCEL"])
@pytest.mark.parametrize("runs", [1, 3])
def test_cancellation_during_network_retains_honest_late_result(
    h: Harness, action: str, runs: int
) -> None:
    first = h.start(runs=runs)
    job = h.due()

    def control() -> None:
        h.control(h.head(first), action)

    h.backend.on_probe = control
    h.schedules.execute_job(job)
    assert h.receipt(first)["status"] == "SUCCEEDED"
    assert h.receipt(first)["schedule_status_at_completion"] == (
        "PAUSED" if action == "PAUSE" else "CANCELLED"
    )
    assert h.head(first)["status"] == ("PAUSED" if action == "PAUSE" else "CANCELLED")
    assert h.backend.calls == ["SRC-04"]


def test_pause_after_claim_before_execute_does_not_fetch(h: Harness) -> None:
    first = h.start()
    job = h.due()
    h.control(h.head(first), "PAUSE")
    h.schedules.execute_job(job)
    assert h.backend.calls == []
    assert h.head(first)["status"] == "PAUSED"


@pytest.mark.parametrize(
    "phase",
    [
        "AFTER_DISPATCH_CLAIM",
        "AFTER_OPERATION_LINK",
        "AFTER_PROBE_RETURN",
        "BEFORE_COMPLETION_COMMIT",
    ],
)
def test_crash_and_restart_never_replay_unknown_request(h: Harness, phase: str) -> None:
    first = h.start()
    job = h.due()

    def crash(where: str) -> None:
        if where == phase:
            raise Crash()

    h.schedules.fault = crash
    with pytest.raises(Crash):
        h.schedules.execute_job(job)
    calls = list(h.backend.calls)
    h.data.recover()
    restarted = SourceSchedules(h.data, clock=lambda: h.now[0])
    restarted.recover()
    restarted.recover()
    assert h.backend.calls == calls
    assert restarted.get(h.owner, str(first["id"]))["status"] == "PAUSED"
    receipt = cast(
        JsonRecord, restarted.history(h.owner, str(first["id"]))[0]["receipt"]
    )
    assert receipt["status"] == (
        "SUCCEEDED"
        if phase in {"AFTER_PROBE_RETURN", "BEFORE_COMPLETION_COMMIT"}
        else "UNKNOWN"
    )
    assert receipt["recovered"] is True
    assert restarted.pump_due() is False


def test_atomic_queue_rollback_and_restart_can_queue_once(h: Harness) -> None:
    first = h.start()
    h.now[0] += timedelta(hours=1)

    def crash(phase: str) -> None:
        if phase == "BEFORE_QUEUE_COMMIT":
            raise Crash()

    h.schedules.fault = crash
    with pytest.raises(Crash):
        h.schedules.pump_due()
    assert h.head(first) == first
    assert h.schedules.history(h.owner, str(first["id"])) == []
    h.schedules.fault = lambda _: None
    assert h.schedules.pump_due()
    assert h.schedules.pump_due() is False


def test_concurrent_pumps_and_dispatches_cannot_duplicate_or_finalize_other_request(
    h: Harness,
) -> None:
    first = h.start()
    h.now[0] += timedelta(hours=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: h.schedules.pump_due(), range(2))) == [
            False,
            True,
        ]
    job = h.data.state.claim()
    assert job is not None
    entered, release = Event(), Event()

    def wait() -> None:
        entered.set()
        assert release.wait(5)

    h.backend.on_probe = wait
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(h.schedules.execute_job, job)
        assert entered.wait(5)
        try:
            with pytest.raises(ScheduleError, match="ALREADY_DISPATCHED"):
                h.schedules.execute_job(job)
            assert h.receipt(first) is None
            assert h.data.state.job(h.owner, job.id).status == "RUNNING"
        finally:
            release.set()
        future.result()
    assert h.backend.calls == ["SRC-04"]
    assert h.receipt(first)["status"] == "SUCCEEDED"


def test_queue_cap_and_active_limit_use_shared_existing_reservations(
    h: Harness,
) -> None:
    first = h.start()
    with h.data.state.connection() as db:
        db.executemany(
            "INSERT INTO jobs VALUES(?,?,'QUEUED','{}',NULL,NULL)",
            [(f"other-{i}", h.owner.id) for i in range(8)],
        )
    h.now[0] += timedelta(hours=1)
    assert h.schedules.pump_due() is False
    assert h.head(first) == first
    with h.data.state.connection() as db:
        db.execute("UPDATE jobs SET status='SUCCEEDED' WHERE id='other-0'")
    assert h.schedules.pump_due()
    assert h.data.state.claim() is not None
    assert h.data.state.claim() is not None
    assert h.data.state.claim() is None
    with h.data.state.connection() as db:
        assert resource_counts(db) == (2, 8)


def test_two_workers_and_linked_probe_still_count_as_two(h: Harness) -> None:
    first = h.start()
    job = h.due()
    with h.data.state.connection() as db:
        db.execute(
            "INSERT INTO jobs VALUES('other',?,'RUNNING','{}',NULL,NULL)", (h.owner.id,)
        )

    def inspect() -> None:
        with h.data.state.connection() as db:
            assert resource_counts(db) == (2, 2)

    h.backend.on_probe = inspect
    h.schedules.execute_job(job)
    assert h.receipt(first)["status"] == "SUCCEEDED"


def test_persistent_global_bls_limit_and_per_user_throttle_apply(h: Harness) -> None:
    first = h.start()
    with h.data.state.connection() as db:
        db.executemany(
            "INSERT INTO data_operations(id,owner_id,kind,catalogue_id,created,status) VALUES(?,?,'PROBE','SRC-04',?,'FAILED')",
            [(f"prior{i}", h.owner.id, h.now[0].timestamp()) for i in range(25)],
        )
    h.schedules.execute_job(h.due())
    assert h.backend.calls == []
    assert h.head(first)["status"] == "PAUSED"
    assert h.receipt(first)["status"] == "FAILED"
    second = h.start("SRC-08")
    job = h.due()
    h.data.probe(h.owner, "SRC-08")
    h.schedules.execute_job(job)
    assert h.backend.calls == ["SRC-08"]
    assert h.receipt(second)["status"] == "FAILED"


def test_job_config_and_claim_state_must_be_exact(h: Harness) -> None:
    h.start()
    job = h.due()
    with pytest.raises(ScheduleError, match="JOB_BINDING"):
        h.schedules.execute_job(replace(job, config={**job.config, "occurrence": 2}))
    with pytest.raises(ScheduleError, match="JOB_BINDING"):
        h.schedules.execute_job(replace(job, status="QUEUED"))
    assert h.backend.calls == []


def test_immutable_history_and_result_corruption_are_refused(h: Harness) -> None:
    first = h.start()
    h.schedules.execute_job(h.due())
    with h.data.state.connection() as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE collection_events SET digest='bad'")
        db.execute("UPDATE data_operations SET result='{}'")
    with pytest.raises(ScheduleError, match="RESULT_BINDING"):
        h.schedules.history(h.owner, str(first["id"]))


def test_bounded_results_and_schedule_capacity(h: Harness) -> None:
    first = h.start()
    h.backend.result = {"status": "SUCCEEDED", "oversized": "x" * 64001}
    with pytest.raises(ScheduleError, match="RESULT_BOUND"):
        h.schedules.execute_job(h.due())
    assert h.head(first)["pending_job_id"] is not None
    for _ in range(31):
        h.create()
    with pytest.raises(ScheduleError, match="CAPACITY"):
        h.create()


def test_controls_preserve_completion_and_cancel_headroom(h: Harness) -> None:
    first = h.create()
    for index in range(64):
        first = h.control(first, "ACTIVATE" if index % 2 == 0 else "PAUSE")
    with pytest.raises(ScheduleError, match="HEADROOM"):
        h.control(first, "RESUME")
    assert h.control(first, "CANCEL")["status"] == "CANCELLED"


def test_clock_regression_and_stale_controls_are_not_committed(h: Harness) -> None:
    first = h.start()
    with pytest.raises(ScheduleError, match="STALE"):
        h.schedules.control(h.owner, str(first["id"]), "PAUSE", expected_revision=1)
    h.now[0] -= timedelta(seconds=1)
    with pytest.raises(ScheduleError, match="CLOCK_REGRESSION"):
        h.control(first, "PAUSE")
    assert h.head(first) == first


def test_routes_require_owner_csrf_and_closed_bounded_payload(h: Harness) -> None:
    app = FastAPI()

    def auth(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        if request.headers.get("x-auth") != "owner" or (
            mutation and request.headers.get("x-csrf") != "fixture"
        ):
            raise HTTPException(403, "Denied")
        assert not mutation or owner
        return Session(h.owner, "fixture")

    install_source_schedule_routes(app, auth, h.schedules)
    with TestClient(app) as client:
        payload = {
            "catalogue_id": "SRC-08",
            "interval_seconds": 3600,
            "maximum_runs": 2,
        }
        assert client.post("/api/source-schedules", json=payload).status_code == 403
        headers = {"x-auth": "owner", "x-csrf": "fixture"}
        created = client.post("/api/source-schedules", json=payload, headers=headers)
        assert created.status_code == 200 and created.json()["status"] == "PAUSED"
        identity = created.json()["id"]
        assert (
            client.get("/api/source-schedules/profiles", headers=headers).status_code
            == 200
        )
        assert (
            client.get("/api/source-schedules", headers=headers).json()[0]["id"]
            == identity
        )
        assert (
            client.get(f"/api/source-schedules/{identity}", headers=headers).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/source-schedules/{identity}/history", headers=headers
            ).json()
            == []
        )
        assert (
            client.post(
                f"/api/source-schedules/{identity}/control",
                json={"action": "ACTIVATE", "expected_revision": 1},
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/source-schedules/{identity}/control",
                json={"action": "CANCEL", "expected_revision": 1},
                headers=headers,
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/source-schedules",
                json={**payload, "api_key": "synthetic-secret"},
                headers=headers,
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/source-schedules", content=b"x" * 4097, headers=headers
            ).status_code
            == 413
        )
        assert (
            client.post(
                "/api/source-schedules",
                content=b'{"catalogue_id":"SRC-04","catalogue_id":"SRC-08"}',
                headers=headers,
            ).status_code
            == 400
        )
        assert h.backend.calls == []


@pytest.mark.parametrize("source", ["SRC-04", "SRC-06", "SRC-08"])
def test_actual_fixed_clients_publish_candidate_raw_and_dataset_through_schedule(
    h: Harness, tmp_path: Path, source: str
) -> None:
    from quant_hunter.sources.providers import ProviderService
    from test_v0_sources import CSV_HEADER, CSV_ROW, FixtureTransport, bls_body
    from test_v0_sources_macro import G17
    from test_v0_sources_macro import Fixture as MacroFixture

    from quant_hunter.identity import RegistryStore
    from quant_hunter.sources import (
        BLSConnector,
        ECBConnector,
        Response,
        SourceProbeService,
    )
    from quant_hunter.sources._equity_transport import EquityResponse
    from quant_hunter.sources.macro_g17 import G17Connector
    from quant_hunter.storage import ImmutableObjectStore

    schema_root = Path(__file__).resolve().parents[1] / "schemas/v1"
    registry = RegistryStore.governed(tmp_path / "registry", schema_root)
    objects = ImmutableObjectStore(tmp_path / "objects")
    environment = objects.publish(b'{"purpose":"offline scheduler source proof"}')
    raw = (
        bls_body()
        if source == "SRC-04"
        else (CSV_HEADER + CSV_ROW).encode()
        if source == "SRC-08"
        else G17.replace(b"2024", b"2025").replace(b"2023", b"2024")
    )

    def factory(catalogue_id: str) -> BLSConnector | ECBConnector:
        assert catalogue_id == source
        assert (
            next(iter(registry.verify_all().values()))[-1].record["status"]
            == "CANDIDATE"
        )
        transport = FixtureTransport(Response(200, raw))
        return (
            BLSConnector(transport) if source == "SRC-04" else ECBConnector(transport)
        )

    public = SourceProbeService(
        registry,
        objects,
        schema_root,
        "a" * 40,
        environment.digest,
        connector_factory=factory,
    )

    class Selected:
        def probe(self, catalogue_id: str) -> JsonRecord:
            if catalogue_id == "SRC-06":
                return ProviderService(public).probe(
                    catalogue_id, G17Connector(MacroFixture(EquityResponse(200, raw)))
                )
            return public.probe(catalogue_id)

    h.data.prober = Selected()
    first = h.start(source, runs=1)
    h.schedules.execute_job(h.due())
    receipt = h.receipt(first)
    assert receipt["status"] == "SUCCEEDED"
    with h.data.state.connection() as db:
        result = json.loads(
            db.execute(
                "SELECT result FROM data_operations WHERE id=?",
                (receipt["operation_id"],),
            ).fetchone()[0]
        )
    assert result["quality"] == "PENDING" and result["source_status"] == "CANDIDATE"
    assert result["evidence_mode"] == "RECORDED_FIXTURE"
    assert result["record_count"] == (
        6 if source == "SRC-06" else 2 if source == "SRC-04" else 1
    )
    assert objects.get(result["raw_digest"]).path.read_bytes() == raw
    dataset = registry.verify_object(result["dataset_id"])[-1]
    assert dataset.record["physical_object_digest"] == result["raw_digest"]
    assert h.data.datasets(h.owner) == []


@pytest.mark.parametrize(
    "column,value",
    [
        ("status", "FAILED"),
        ("catalogue_id", "SRC-08"),
        ("kind", "IMPORT"),
        ("worker_job_id", None),
    ],
)
def test_receipt_reloads_bind_actual_operation_state_and_source(
    h: Harness, column: str, value: str | None
) -> None:
    first = h.start()
    h.schedules.execute_job(h.due())
    with h.data.state.connection() as db:
        db.execute(f"UPDATE data_operations SET {column}=?", (value,))  # noqa: S608 -- closed parametrized test field
    with pytest.raises(ScheduleError, match="RECEIPT_BINDING"):
        h.schedules.history(h.owner, str(first["id"]))


def test_restart_preserves_safe_queued_occurrence_and_never_resets_completed_runs(
    h: Harness,
) -> None:
    first = h.start(runs=2)
    h.now[0] += timedelta(hours=1)
    assert h.schedules.pump_due()
    restarted = SourceSchedules(h.data, clock=lambda: h.now[0])
    restarted.recover()
    job = h.data.state.claim()
    assert job is not None
    restarted.execute_job(job)
    h.now[0] += timedelta(hours=1)
    assert restarted.pump_due()
    second = h.data.state.claim()
    assert second is not None and second.id != job.id
    restarted.execute_job(second)
    head = restarted.get(h.owner, str(first["id"]))
    assert head["dispatched"] == 2 and head["status"] == "COMPLETED"
    assert len(restarted.history(h.owner, str(first["id"]))) == 2
    with pytest.raises(ScheduleError, match="TERMINAL"):
        restarted.control(
            h.owner,
            str(first["id"]),
            "RESUME",
            expected_revision=cast(int, head["revision"]),
        )


@pytest.mark.parametrize(
    "attack", ["head", "event", "oversized", "noncanonical", "configuration_digest"]
)
def test_schedule_history_corruption_refuses_read_and_queue(
    h: Harness, attack: str
) -> None:
    first = h.start()
    with h.data.state.connection() as db:
        if attack == "head":
            db.execute("UPDATE collection_heads SET digest='sha256:bad'")
        else:
            db.execute("DROP TRIGGER collection_events_update")
            if attack == "event":
                db.execute(
                    "UPDATE collection_events SET digest='sha256:bad' WHERE revision=1"
                )
            elif attack == "oversized":
                db.execute(
                    "UPDATE collection_events SET payload=? WHERE revision=1",
                    (b"x" * 4097,),
                )
            else:
                raw = bytes(
                    db.execute(
                        "SELECT payload FROM collection_events WHERE revision=1"
                    ).fetchone()[0]
                )
                if attack == "noncanonical":
                    raw += b" "
                else:
                    value = json.loads(raw)
                    value["configuration_digest"] = "sha256:other"
                    raw = canonicalize_json(value)
                db.execute(
                    "UPDATE collection_events SET payload=?,digest=? WHERE revision=1",
                    (raw, "sha256:" + hashlib.sha256(raw).hexdigest()),
                )
    with pytest.raises(ScheduleError):
        h.head(first)
    h.now[0] += timedelta(hours=1)
    with pytest.raises(ScheduleError):
        h.schedules.pump_due()
    assert h.backend.calls == []


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("collection_occurrences", "owner_id", 999),
        ("collection_occurrences", "number", 2),
        ("collection_operation_links", "catalogue_id", "SRC-08"),
        ("collection_receipts", "job_id", "foreign"),
        ("collection_dispatches", "owner_id", 999),
        ("collection_dispatches", "at_unix", 0),
    ],
)
def test_coherently_rehashed_repeated_identity_is_rejected(
    h: Harness, table: str, field: str, value: str | int
) -> None:
    first = h.start()
    h.schedules.execute_job(h.due())
    with h.data.state.connection() as db:
        db.execute(f"DROP TRIGGER {table}_update")
        raw = bytes(db.execute(f"SELECT payload FROM {table}").fetchone()[0])  # noqa: S608
        record = json.loads(raw)
        record[field] = value
        raw = canonicalize_json(record)
        db.execute(
            f"UPDATE {table} SET payload=?,digest=?",  # noqa: S608 -- closed test table
            (raw, "sha256:" + hashlib.sha256(raw).hexdigest()),
        )
    with pytest.raises(ScheduleError, match="BINDING"):
        h.schedules.history(h.owner, str(first["id"]))


def test_missing_dispatch_or_source_result_is_never_verified(h: Harness) -> None:
    first = h.start()
    h.schedules.execute_job(h.due())
    with h.data.state.connection() as db:
        db.execute("DROP TRIGGER collection_dispatches_delete")
        db.execute("DELETE FROM collection_dispatches")
    with pytest.raises(ScheduleError, match="DISPATCH_BINDING"):
        h.schedules.history(h.owner, str(first["id"]))


@pytest.mark.parametrize("result", [None, "[]"])
def test_impossible_success_operation_result_is_retained_unsettled(
    h: Harness, result: str | None
) -> None:
    first = h.start()
    job = h.due()

    def crash(where: str) -> None:
        if where == "AFTER_PROBE_RETURN":
            raise Crash()

    h.schedules.fault = crash
    with pytest.raises(Crash):
        h.schedules.execute_job(job)
    with h.data.state.connection() as db:
        db.execute("UPDATE data_operations SET result=?", (result,))
    restarted = SourceSchedules(h.data, clock=lambda: h.now[0])
    with pytest.raises(ScheduleError, match="RESULT_BINDING"):
        restarted.recover()
    assert h.head(first)["pending_job_id"] == job.id
    assert h.backend.calls == ["SRC-04"]


def test_changed_fixed_profile_does_not_silently_change_existing_schedule(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = h.start()
    job = h.due()
    monkeypatch.setattr(
        "quant_hunter.web.source_schedules.public_profile",
        lambda _: {"query": "a changed implementation default"},
    )
    h.schedules.execute_job(job)
    assert h.receipt(first)["status"] == "FAILED"
    assert h.backend.calls == []


def test_bad_control_pending_resume_and_finalization_replay_are_refused(
    h: Harness,
) -> None:
    first = h.start()
    with pytest.raises(ScheduleError, match="CONTROL_INVALID"):
        h.control(first, "DELETE")
    with pytest.raises(ScheduleError, match="NOT_PAUSED"):
        h.control(first, "RESUME")
    job = h.due()
    paused = h.control(h.head(first), "PAUSE")
    with pytest.raises(ScheduleError, match="PENDING"):
        h.control(paused, "RESUME")
    h.schedules.execute_job(job)
    before = h.head(first)
    h.schedules._complete(job.id)
    assert h.head(first) == before


def test_dispatch_clock_cannot_precede_durable_queue(h: Harness) -> None:
    h.start()
    job = h.due()
    h.now[0] -= timedelta(seconds=1)
    with pytest.raises(ScheduleError, match="CLOCK_REGRESSION"):
        h.schedules.execute_job(job)
    assert h.backend.calls == []


def test_exact_captured_claim_time_is_validated_before_acquisition(h: Harness) -> None:
    h.start()
    job = h.due()
    clock = iter((h.now[0] - timedelta(seconds=1), h.now[0]))
    h.schedules.clock = lambda: next(clock)
    with pytest.raises(ScheduleError, match="CLOCK_REGRESSION"):
        h.schedules.execute_job(job)
    assert h.backend.calls == []
    with h.data.state.connection() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM collection_dispatches").fetchone()[0] == 0
        )
        assert db.execute("SELECT COUNT(*) FROM data_operations").fetchone()[0] == 0
    assert next(clock) == h.now[0]


def test_non_utc_clock_rejected_before_schedule_is_created(h: Harness) -> None:
    bad = SourceSchedules(h.data, clock=lambda: datetime(2026, 10, 5))
    with pytest.raises(ScheduleError, match="UTC_CLOCK_REQUIRED"):
        bad.create(h.owner, "SRC-04", interval_seconds=3600, maximum_runs=1)
    assert h.schedules.list_schedules(h.owner) == []


def test_disabled_route_and_authorization_failures_are_sanitized(h: Harness) -> None:
    app = FastAPI()

    def auth(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        return Session(h.owner, "fixture")

    install_source_schedule_routes(app, auth, None)
    with TestClient(app) as client:
        assert client.get("/api/source-schedules").status_code == 503
    app2 = FastAPI()
    install_source_schedule_routes(app2, auth, h.schedules)
    with TestClient(app2) as client:
        assert client.get("/api/source-schedules/foreign").status_code == 403


@pytest.mark.parametrize(
    "column,value",
    [
        ("owner_id", 999),
        ("config", "{}"),
        ("experiment_id", "EXP-foreign"),
        ("status", "FAILED"),
        ("status", "UNKNOWN"),
    ],
)
def test_historical_receipt_requires_actual_owned_job_record(
    h: Harness, column: str, value: str | int
) -> None:
    first = h.start()
    h.schedules.execute_job(h.due())
    with h.data.state.connection() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute(f"UPDATE jobs SET {column}=?", (value,))  # noqa: S608 -- closed test field
    with pytest.raises(ScheduleError, match="JOB_BINDING"):
        h.schedules.history(h.owner, str(first["id"]))


@pytest.mark.parametrize("job_status", ["FAILED", "SUCCEEDED"])
def test_recovery_cannot_overwrite_a_prior_job_failure_or_invent_missing_success_receipt(
    h: Harness, job_status: str
) -> None:
    first = h.start()
    job = h.due()

    def stop(phase: str) -> None:
        if phase == "AFTER_PROBE_RETURN":
            raise Crash()

    h.schedules.fault = stop
    with pytest.raises(Crash):
        h.schedules.execute_job(job)
    with h.data.state.connection() as db:
        db.execute("UPDATE jobs SET status=? WHERE id=?", (job_status, job.id))
    restarted = SourceSchedules(h.data, clock=lambda: h.now[0])
    if job_status == "FAILED":
        restarted.recover()
        receipt = cast(
            JsonRecord, restarted.history(h.owner, str(first["id"]))[0]["receipt"]
        )
        assert receipt["status"] == "FAILED"
        assert receipt["operation_status"] == "SUCCEEDED" and receipt["result_digest"]
    else:
        with pytest.raises(ScheduleError, match="JOB_BINDING"):
            restarted.recover()
    assert h.backend.calls == ["SRC-04"]
