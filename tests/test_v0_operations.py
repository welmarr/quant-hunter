"""Offline fault evidence against real operational SQLite, never research runs."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from quant_hunter.config import JsonRecord
from quant_hunter.web.admission import resource_counts
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.operations_access import (
    OperationsAccess,
    OperationsUnavailableError,
    WorkerStatus,
    _counts,
    _status_counts,
)
from quant_hunter.web.operations_routes import install_operations_routes
from quant_hunter.web.state import AccessError, AppState, Session


def _object(value: object) -> JsonRecord:
    assert isinstance(value, dict)
    return cast(JsonRecord, value)


def _integer(value: object) -> int:
    assert type(value) is int
    return value


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = AppState(root / "application.sqlite3")
        self.owner = self.state.create_user(
            "owner", "synthetic-password", "owner", bootstrap=True
        )
        self.researcher = self.state.create_user(
            "researcher", "synthetic-password", "researcher", bootstrap=False
        )
        self.reader = self.state.create_user(
            "reader", "synthetic-password", "reader", bootstrap=False
        )
        self.clock = Clock()
        self.worker = WorkerStatus("RUNNING", 1, datetime(2025, 1, 1, tzinfo=UTC))
        self.access = OperationsAccess(
            self.state,
            root,
            worker_status=lambda: self.worker,
            clock=self.clock,
            monotonic=self.clock,
        )
        self.data = DataAccess(
            self.state, root, cast(Any, object()), cast(Any, object())
        )

    def optional_tables(self) -> None:
        with self.state.connection() as db:
            db.executescript("""
                CREATE TABLE resource_readers(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,created REAL NOT NULL);
                CREATE TABLE publication_operations(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,status TEXT NOT NULL);
                CREATE TABLE paper_jobs(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,status TEXT NOT NULL);
            """)


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_private_and_owner_counts_never_read_payloads(h: Harness) -> None:
    h.state.enqueue(h.researcher, {"secret-diagnostic": "DO-NOT-RETURN"})
    h.state.enqueue(h.owner, {"kind": "private-owner-job"})
    own = h.access.status(h.researcher)
    assert _object(_object(own["private"])["components"])["jobs"] == {"QUEUED": 1}
    assert own["global"] is None and own["storage"] == {"visibility": "OWNER_ONLY"}
    assert "DO-NOT-RETURN" not in json.dumps(
        own
    ) and "private-owner-job" not in json.dumps(own)
    admin = h.access.status(h.owner)
    assert _object(_object(admin["global"])["components"])["jobs"] == {"QUEUED": 2}
    assert _object(admin["private"])["reserved_slots"] == 1
    assert _object(admin["global"])["reserved_slots"] == 2
    assert "owner_id" not in json.dumps(admin) and str(h.root) not in json.dumps(admin)


def test_reader_is_read_only_and_receives_own_empty_counts(h: Harness) -> None:
    before = h.state.path.read_bytes()
    value = h.access.status(h.reader)
    assert _object(value["private"])["reserved_slots"] == 0
    assert value["global"] is None
    assert h.state.path.read_bytes() == before


@pytest.mark.parametrize("change", ["role", "username", "delete"])
def test_cached_storage_cannot_substitute_for_current_authority(
    h: Harness, change: str
) -> None:
    h.access.status(h.owner)
    with h.state.connection() as db:
        if change == "delete":
            db.execute("DELETE FROM users WHERE id=?", (h.owner.id,))
        else:
            query = (
                "UPDATE users SET role=? WHERE id=?"
                if change == "role"
                else "UPDATE users SET username=? WHERE id=?"
            )
            db.execute(
                query,
                ("reader" if change == "role" else "renamed", h.owner.id),
            )
    with pytest.raises(AccessError):
        h.access.status(h.owner)


def test_unavailable_database_never_returns_cached_counts_or_creates_file(
    h: Harness,
) -> None:
    h.access.status(h.owner)
    h.state.path.rename(h.root / "saved.sqlite3")
    with pytest.raises(OperationsUnavailableError, match="DATABASE_UNAVAILABLE"):
        h.access.status(h.owner)
    assert not h.state.path.exists()


def test_locked_database_is_bounded_and_recovers_without_changing_work(
    h: Harness,
) -> None:
    job = h.state.enqueue(h.owner, {"kind": "SYNTHETIC"})
    db = sqlite3.connect(h.state.path)
    db.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(OperationsUnavailableError, match="DATABASE_UNAVAILABLE"):
            h.access.status(h.owner)
    finally:
        db.rollback()
        db.close()
    assert _object(_object(h.access.status(h.owner)["private"])["components"])[
        "jobs"
    ] == {"QUEUED": 1}
    assert h.state.job(h.owner, job.id).status == "QUEUED"


def test_linked_operation_consumes_one_slot_and_retains_recovery(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(h.data, "_capacity", lambda: None)
    job = h.state.enqueue(h.researcher, {"kind": "SYNTHETIC"})
    claimed = h.state.claim()
    assert claimed is not None and claimed.id == job.id
    operation = h.data._begin(h.researcher, "IMPORT", worker_job_id=job.id)
    value = _object(h.access.status(h.researcher)["private"])
    assert (
        value["active_slots"],
        value["reserved_slots"],
        value["linked_worker_children"],
    ) == (1, 1, 1)
    with pytest.raises(AccessError, match="already has"):
        h.data._begin(h.researcher, "IMPORT", worker_job_id=job.id)
    h.data.recover()
    h.state.finish(job.id, error="Interrupted; no automatic replay")
    value = _object(h.access.status(h.researcher)["private"])
    assert value["active_slots"] == value["reserved_slots"] == 0
    assert _object(value["components"])["data_operations"] == {"INTERRUPTED": 1}
    assert _object(value["components"])["jobs"] == {"FAILED": 1}
    with h.state.connection() as db:
        assert db.execute("SELECT id FROM data_operations").fetchone()[0] == operation


def test_shared_optional_components_and_orphaned_child_are_exact(h: Harness) -> None:
    h.optional_tables()
    owner_job = h.state.enqueue(h.owner, {"kind": "A"})
    h.state.enqueue(h.researcher, {"kind": "B"})
    with h.state.connection() as db:
        db.execute(
            "INSERT INTO resource_readers VALUES('reader',?,0)", (h.researcher.id,)
        )
        db.execute(
            "INSERT INTO publication_operations VALUES('pub',?,'RUNNING')",
            (h.owner.id,),
        )
        db.execute(
            "INSERT INTO paper_jobs VALUES('paper',?,'PAUSED')", (h.researcher.id,)
        )
        db.execute(
            "INSERT INTO paper_jobs VALUES('finished',?,'COMPLETED')", (h.owner.id,)
        )
        db.execute(
            "INSERT INTO data_operations VALUES('orphan',?,'IMPORT',NULL,0,'RUNNING',NULL,NULL,?)",
            (h.owner.id, owner_job.id),
        )
        expected = resource_counts(db)
    value = h.access.status(h.owner)
    assert (
        (
            _object(value["global"])["active_slots"],
            _object(value["global"])["reserved_slots"],
        )
        == expected
        == (3, 6)
    )
    assert _object(value["private"])["orphaned_active_children"] == 1
    other = _object(h.access.status(h.researcher)["private"])
    assert (other["active_slots"], other["reserved_slots"], other["reader_slots"]) == (
        1,
        3,
        1,
    )


@pytest.mark.parametrize(
    "status,active,reserved",
    [
        ("CREATED", 0, 1),
        ("ACTIVE", 0, 1),
        ("STARTING", 1, 1),
        ("STEPPING", 1, 1),
        ("RECOVERING", 1, 1),
        ("AMBIGUOUS", 0, 1),
        ("FAILED", 0, 0),
        ("CANCELLED", 0, 0),
    ],
)
def test_paper_state_reservations_match_canonical_helper(
    h: Harness, status: str, active: int, reserved: int
) -> None:
    h.optional_tables()
    with h.state.connection() as db:
        db.execute("INSERT INTO paper_jobs VALUES('one',?,?)", (h.owner.id, status))
    value = h.access.status(h.owner)
    for scope in ("private", "global"):
        assert (
            _object(value[scope])["active_slots"],
            _object(value[scope])["reserved_slots"],
        ) == (
            active,
            reserved,
        )


def test_unknown_status_is_sanitized_and_remains_a_paper_reservation(
    h: Harness,
) -> None:
    h.optional_tables()
    with h.state.connection() as db:
        db.execute(
            "INSERT INTO paper_jobs VALUES('one',?,'SECRET-FROM-CORRUPT-STATE')",
            (h.owner.id,),
        )
    value = h.access.status(h.owner)
    assert _object(_object(value["private"])["components"])["paper_jobs"] == {
        "OTHER": 1
    }
    assert _object(value["private"])["reserved_slots"] == 1
    assert "SECRET" not in json.dumps(value)


def test_observation_does_not_duplicate_concurrent_claims(h: Harness) -> None:
    job = h.state.enqueue(h.owner, {"kind": "SYNTHETIC"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: h.state.claim(), range(2)))
    assert [value.id for value in claims if value is not None] == [job.id]
    for _ in range(3):
        assert _object(h.access.status(h.owner)["private"])["active_slots"] == 1
    assert h.state.claim() is None


def test_worker_restart_is_host_observation_without_job_replay(h: Harness) -> None:
    job = h.state.enqueue(h.owner, {"kind": "SYNTHETIC"})
    h.state.claim()
    for state, generation in [("STOPPED", 1), ("RESTARTING", 2), ("RUNNING", 2)]:
        h.worker = WorkerStatus(cast(Any, state), generation)
        value = h.access.status(h.owner)
        assert (
            _object(value["worker"])["state"] == state
            and _object(value["worker"])["generation"] == generation
        )
        assert h.state.job(h.owner, job.id).status == "RUNNING"
    assert h.state.claim() is None


@pytest.mark.parametrize(
    "worker",
    [
        WorkerStatus(cast(Any, "secret")),
        WorkerStatus("RUNNING", -1),
        WorkerStatus("RUNNING", True),
        WorkerStatus("RUNNING", None, datetime(2025, 1, 1)),
    ],
)
def test_malformed_worker_observation_is_unknown_and_sanitized(
    h: Harness, worker: WorkerStatus
) -> None:
    h.worker = worker
    result = _object(h.access.status(h.researcher)["worker"])
    assert result["state"] == "UNKNOWN" and result["generation"] is None
    assert "secret" not in json.dumps(result)


def test_storage_sample_uses_actual_metadata_and_is_private(h: Harness) -> None:
    (h.root / "synthetic.bin").write_bytes(b"x" * 123)
    expected = sum(path.stat().st_size for path in h.root.rglob("*") if path.is_file())
    first = _object(h.access.status(h.owner)["storage"])
    assert (
        first["freshness"] == "LIVE_SAMPLE"
        and _object(first["sample"])["budget_observed_bytes"] == expected
    )
    assert (
        _integer(_object(first["sample"])["required_free_reserve_bytes"])
        >= 20 * 1024**3
    )
    h.clock.value += 5
    second = _object(h.access.status(h.owner)["storage"])
    assert second["freshness"] == "CACHED" and second["sample_age_seconds"] == 5
    assert second["sample"] == first["sample"]
    assert "synthetic.bin" not in json.dumps(second)


def test_stale_storage_is_never_capacity_authority(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _object(h.access.status(h.owner)["storage"])
    h.clock.value += 31

    def fail() -> Any:
        raise PermissionError("private credential path must not escape")

    monkeypatch.setattr(h.access, "_scan_storage", fail)
    stale = _object(h.access.status(h.owner)["storage"])
    assert stale["freshness"] == "STALE" and stale["status"] == "UNKNOWN"
    assert stale["sample"] == first["sample"] and stale["sample_age_seconds"] == 31
    assert "credential" not in json.dumps(stale)
    monkeypatch.setattr(
        h.access,
        "_scan_storage",
        lambda: pytest.fail("failure refresh must be throttled"),
    )
    h.access.status(h.owner)


def test_initial_storage_failure_and_busy_are_unknown(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.access._storage_lock.acquire()
    try:
        assert (
            _object(h.access.status(h.owner)["storage"])["error_code"]
            == "STORAGE_SAMPLE_BUSY"
        )
    finally:
        h.access._storage_lock.release()
    monkeypatch.setattr(
        h.access, "_scan_storage", lambda: (_ for _ in ()).throw(OSError("secret"))
    )
    value = _object(h.access.status(h.owner)["storage"])
    assert (
        value["freshness"] == "UNAVAILABLE"
        and value["status"] == "UNKNOWN"
        and value["sample"] is None
    )


@pytest.mark.parametrize("free,expected", [(1, "RESERVE_LOW"), (90 * 1024**3, "OK")])
def test_storage_reserve_status_is_calculable(
    h: Harness, monkeypatch: pytest.MonkeyPatch, free: int, expected: str
) -> None:
    from collections import namedtuple

    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(
        "quant_hunter.web.operations_access.shutil.disk_usage",
        lambda _: Usage(100 * 1024**3, 0, free),
    )
    assert (
        _object(_object(h.access.status(h.owner)["storage"])["sample"])["status"]
        == expected
    )


def test_scan_time_bound_produces_unknown_not_a_partial_budget(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    times = iter([0.0, 2.1])
    monkeypatch.setattr(h.access, "monotonic", lambda: next(times))
    with pytest.raises(OperationsUnavailableError, match="SCAN_LIMIT"):
        h.access._scan_storage()


def test_allowlist_and_database_corruption_fail_closed(h: Harness) -> None:
    with h.state.connection() as db:
        with pytest.raises(ValueError, match="Unknown"):
            _status_counts(db, "users", h.owner.id)
        db.execute("DROP TABLE jobs")
    with pytest.raises(OperationsUnavailableError, match="DATABASE_UNAVAILABLE"):
        h.access.status(h.owner)


def test_missing_optional_modules_are_absent_not_fabricated(h: Harness) -> None:
    with h.state.connection() as db:
        value = _counts(db, h.owner.id)
    assert set(_object(value["components"])) == {"jobs", "data_operations"}


def test_runtime_relative_path_rejected(h: Harness) -> None:
    with pytest.raises(ValueError, match="Absolute"):
        OperationsAccess(h.state, Path("relative"), worker_status=lambda: h.worker)


def client(
    h: Harness, service: OperationsAccess | None = None, *, absent: bool = False
) -> TestClient:
    app = FastAPI()

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        if request.headers.get("X-Test-Actor") != "owner":
            raise HTTPException(401, "Sign in")
        return Session(h.owner, "not-a-real-session-secret")

    install_operations_routes(
        app, authenticated, None if absent else service or h.access
    )
    return TestClient(app)


def test_actual_routes_are_get_only_and_sanitize_database_failure(h: Harness) -> None:
    with client(h) as http:
        assert http.get("/api/operations/status").status_code == 401
        headers = {"X-Test-Actor": "owner"}
        assert http.get("/api/operations/status", headers=headers).status_code == 200
        assert (
            http.post("/api/operations/status", headers=headers, json={}).status_code
            == 405
        )
        h.state.path.rename(h.root / "old.sqlite3")
        result = http.get("/api/operations/status", headers=headers)
        assert result.status_code == 503 and result.json() == {
            "detail": "DATABASE_UNAVAILABLE"
        }


def test_absent_adapter_and_revoked_user_routes(h: Harness) -> None:
    headers = {"X-Test-Actor": "owner"}
    with client(h, absent=True) as http:
        assert http.get("/api/operations/status", headers=headers).json() == {
            "detail": "OPERATIONS_UNAVAILABLE"
        }
    with h.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (h.owner.id,))
    with client(h) as http:
        assert http.get("/api/operations/status", headers=headers).status_code == 403


def test_storage_cap_and_directory_total_are_calculable(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    (h.root / "nested").mkdir()
    (h.root / "nested" / "bars.parquet").write_bytes(b"fixture")
    monkeypatch.setattr("quant_hunter.web.operations_access._BUDGET", 1)
    value = _object(h.access.status(h.owner)["storage"])
    assert _object(value["sample"])["status"] == "CAP_REACHED"
    assert _object(value["sample"])["budget_observed_bytes"] == sum(
        p.stat().st_size for p in h.root.rglob("*") if p.is_file()
    )


def test_scan_entry_bound_never_reports_partial_bytes(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    (h.root / "one").write_bytes(b"1")
    (h.root / "two").write_bytes(b"2")
    monkeypatch.setattr("quant_hunter.web.operations_access._MAX_ENTRIES", 2)
    with pytest.raises(OperationsUnavailableError, match="SCAN_LIMIT"):
        h.access._scan_storage()


@pytest.mark.parametrize("kind", ["link", "reparse", "special"])
def test_storage_redirection_and_special_files_are_not_followed(
    h: Harness, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    import stat
    from types import SimpleNamespace

    real = Path.lstat
    target = h.root / "redirection"
    target.write_bytes(b"not-read")

    def controlled(path: Path) -> Any:
        if path != target:
            return real(path)
        return SimpleNamespace(
            st_mode={
                "link": stat.S_IFLNK,
                "reparse": stat.S_IFDIR,
                "special": stat.S_IFIFO,
            }[kind],
            st_file_attributes=0x400 if kind == "reparse" else 0,
        )

    monkeypatch.setattr(Path, "lstat", controlled)
    result = _object(h.access.status(h.owner)["storage"])
    assert result["status"] == "UNKNOWN" and result["sample"] is None


def test_storage_scope_is_shared_local_ancestor_without_exposing_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".local" / "runtime"
    root.mkdir(parents=True)
    (root.parent / "other-private-runtime.bin").write_bytes(b"12345")
    h = Harness(root)
    value = _object(_object(h.access.status(h.owner)["storage"])["sample"])
    assert value["budget_observed_bytes"] == h.state.path.stat().st_size + 5
    assert "other-private" not in json.dumps(value)


def test_invalid_disk_numbers_and_bad_worker_callback_are_sanitized(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "quant_hunter.web.operations_access.shutil.disk_usage",
        lambda _: SimpleNamespace(total=0, free=1),
    )
    h.access.worker_status = lambda: (_ for _ in ()).throw(OSError("super-secret-path"))
    value = h.access.status(h.owner)
    assert (
        _object(value["storage"])["status"]
        == _object(value["worker"])["state"]
        == "UNKNOWN"
    )
    assert "super-secret" not in json.dumps(value)


def test_database_progress_limit_does_not_return_partial_counts(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    with h.state.connection() as db:
        db.executemany(
            "INSERT INTO jobs VALUES(?,?,'SUCCEEDED','{}',NULL,NULL)",
            ((str(i), h.owner.id) for i in range(1000)),
        )
    count = 0

    def advancing() -> float:
        nonlocal count
        count += 3
        return float(count)

    monkeypatch.setattr(h.access, "monotonic", advancing)
    with pytest.raises(OperationsUnavailableError, match="DATABASE_UNAVAILABLE"):
        h.access.status(h.owner)


def test_legacy_data_table_without_worker_link_is_supported(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    with h.state.connection() as db:
        db.execute("DROP TABLE data_operations")
        db.execute("CREATE TABLE data_operations(owner_id INTEGER,status TEXT)")
        db.execute("INSERT INTO data_operations VALUES(?,'RUNNING')", (h.owner.id,))
    value = h.access.status(h.owner)
    assert (
        _object(value["private"])["active_slots"]
        == _object(value["global"])["active_slots"]
        == 1
    )
    assert _object(value["private"])["linked_worker_children"] == 0


def test_route_unexpected_error_is_sanitized_and_success_has_no_store(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = {"X-Test-Actor": "owner"}
    with client(h) as http:
        assert (
            http.get("/api/operations/status", headers=headers).headers["Cache-Control"]
            == "no-store"
        )
        monkeypatch.setattr(
            h.access,
            "status",
            lambda _: (_ for _ in ()).throw(RuntimeError("private-token")),
        )
        value = http.get("/api/operations/status", headers=headers)
        assert value.status_code == 503 and "private-token" not in value.text


def test_unknown_unavailable_reason_is_sanitized(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        h.access,
        "status",
        lambda _: (_ for _ in ()).throw(OperationsUnavailableError("private-token")),
    )
    with client(h) as http:
        value = http.get("/api/operations/status", headers={"X-Test-Actor": "owner"})
        assert value.status_code == 503 and value.json() == {
            "detail": "OPERATIONS_UNAVAILABLE"
        }
