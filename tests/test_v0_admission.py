"""Real SQLite migration, cross-service limits and concurrent reservations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

from quant_hunter.publications import PublicationService
from quant_hunter.web.admission import resource_counts
from quant_hunter.web.data_access import DataAccess, DatasetImporter, SourceProber
from quant_hunter.web.publication_access import PublicationAccess
from quant_hunter.web.state import AccessError, AppState, User

PASSWORD = "synthetic admission fixture password"  # noqa: S105 -- public fixture


@pytest.fixture
def access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[DataAccess, PublicationAccess, User]:
    state = AppState(tmp_path / "application.sqlite3")
    owner = state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    # These tests invoke admission only, never parser/source service methods.
    data = DataAccess(
        state, tmp_path, cast(DatasetImporter, None), cast(SourceProber, None)
    )
    monkeypatch.setattr(data, "_capacity", lambda: None)
    # Only real admission is invoked; no document service operation is claimed.
    publications = PublicationAccess(
        state, cast(PublicationService, None), capacity=lambda: None
    )
    return data, publications, owner


def counts(state: AppState) -> tuple[int, int]:
    with state.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        return resource_counts(db)


def test_linked_job_occupies_one_slot_and_preserves_queue_budget(
    access: tuple[DataAccess, PublicationAccess, User],
) -> None:
    data, publications, owner = access
    jobs = [data.state.enqueue(owner, {}) for _ in range(7)]
    job = data.state.claim()
    assert job is not None and job.id == jobs[0].id
    publication = publications._begin(owner, "REGISTER", None)
    assert counts(data.state) == (2, 8)
    operation = data._begin(owner, "CORPUS", worker_job_id=job.id)
    assert counts(data.state) == (2, 8)
    with pytest.raises(AccessError, match="already"):
        data._begin(owner, "DUPLICATE", worker_job_id=job.id)
    with pytest.raises(AccessError, match="busy"):
        data._begin(owner, "IMPORT")
    with pytest.raises(AccessError, match="busy"):
        publications._begin(owner, "REGISTER", None)
    assert data.state.claim() is None
    with pytest.raises(AccessError, match="Queue"):
        data.state.enqueue(owner, {})
    data._finish(operation)
    assert counts(data.state) == (2, 8)  # Parent still owns its reservation.
    data.state.finish(job.id)
    publications._finish(publication)
    assert counts(data.state) == (0, 6)


@pytest.mark.parametrize("status", ["QUEUED", "SUCCEEDED", "FAILED", "CANCELLED"])
def test_link_requires_owned_running_job(
    access: tuple[DataAccess, PublicationAccess, User], status: str
) -> None:
    data, _, owner = access
    job = data.state.enqueue(owner, {})
    with data.state.connection() as db:
        db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job.id))
    with pytest.raises(AccessError, match="Running owned"):
        data._begin(owner, "CORPUS", worker_job_id=job.id)
    assert data.operations(owner) == []


def test_cross_owner_stale_role_and_missing_links_fail(
    access: tuple[DataAccess, PublicationAccess, User],
) -> None:
    data, publications, owner = access
    other = data.state.create_user("other", PASSWORD, "researcher", bootstrap=False)
    job = data.state.enqueue(owner, {})
    assert data.state.claim()
    for actor, identity in ((other, job.id), (owner, "missing")):
        with pytest.raises(AccessError, match="Running owned"):
            data._begin(actor, "CORPUS", worker_job_id=identity)
    with data.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (owner.id,))
    with pytest.raises(AccessError, match="Researcher"):
        data._begin(owner, "IMPORT")
    with pytest.raises(AccessError, match="Researcher"):
        publications._begin(owner, "REGISTER", None)


def test_terminal_parent_leaves_child_counted_and_recovery_retains_it(
    access: tuple[DataAccess, PublicationAccess, User],
) -> None:
    data, _, owner = access
    job = data.state.enqueue(owner, {})
    assert data.state.claim()
    operation = data._begin(owner, "CORPUS", worker_job_id=job.id)
    data.state.finish(job.id, error="Synthetic interruption")
    assert counts(data.state) == (1, 1)
    data.recover()
    assert counts(data.state) == (0, 0)
    with data.state.connection() as db:
        row = db.execute(
            "SELECT status,worker_job_id FROM data_operations WHERE id=?", (operation,)
        ).fetchone()
    assert tuple(row) == ("INTERRUPTED", job.id)


@pytest.mark.parametrize("status", ["STARTING", "STEPPING", "RECOVERING"])
def test_paper_reservations_bound_both_services_and_worker_claim(
    access: tuple[DataAccess, PublicationAccess, User], status: str
) -> None:
    data, publications, owner = access
    data.state.enqueue(owner, {})
    with data.state.connection() as db:
        db.execute("CREATE TABLE paper_jobs(status TEXT NOT NULL)")
        db.executemany("INSERT INTO paper_jobs VALUES(?)", [(status,), (status,)])
    assert counts(data.state) == (2, 3)
    assert data.state.claim() is None
    with pytest.raises(AccessError, match="busy"):
        data._begin(owner, "IMPORT")
    with pytest.raises(AccessError, match="busy"):
        publications._begin(owner, "REGISTER", None)


def test_paused_paper_sessions_reserve_queue_but_not_active_slots(
    access: tuple[DataAccess, PublicationAccess, User],
) -> None:
    data, publications, owner = access
    with data.state.connection() as db:
        db.execute("CREATE TABLE paper_jobs(status TEXT NOT NULL)")
        db.executemany("INSERT INTO paper_jobs VALUES('PAUSED')", [()] * 8)
    assert counts(data.state) == (0, 8)
    with pytest.raises(AccessError, match="Queue"):
        data.state.enqueue(owner, {})
    with pytest.raises(AccessError, match="Queue"):
        data._begin(owner, "IMPORT")
    with pytest.raises(AccessError, match="Queue"):
        publications._begin(owner, "REGISTER", None)


def test_concurrent_services_and_claim_never_exceed_two(
    access: tuple[DataAccess, PublicationAccess, User],
) -> None:
    data, publications, owner = access
    data.state.enqueue(owner, {})

    def reserve(index: int) -> bool:
        try:
            if index % 3 == 0:
                return data.state.claim() is not None
            if index % 3 == 1:
                data._begin(owner, "IMPORT")
            else:
                publications._begin(owner, "REGISTER", None)
            return True
        except AccessError:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(reserve, range(12))) == 2
    assert counts(data.state)[0] == 2


def test_additive_migration_preserves_old_record_and_is_repeatable(
    tmp_path: Path,
) -> None:
    state = AppState(tmp_path / "application.sqlite3")
    owner = state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    with state.connection() as db:
        db.execute(
            "CREATE TABLE data_operations(id TEXT PRIMARY KEY,owner_id INTEGER,"
            "kind TEXT,catalogue_id TEXT,created REAL,status TEXT,result TEXT,error TEXT)"
        )
        db.execute(
            "INSERT INTO data_operations VALUES('old',?,'IMPORT',NULL,1,'FAILED',NULL,'retained')",
            (owner.id,),
        )
        original = tuple(db.execute("SELECT * FROM data_operations").fetchone())
    DataAccess(state, tmp_path, cast(DatasetImporter, None), cast(SourceProber, None))
    DataAccess(state, tmp_path, cast(DatasetImporter, None), cast(SourceProber, None))
    with state.connection() as db:
        after = tuple(db.execute("SELECT * FROM data_operations").fetchone())
        assert after == (*original, None)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_capacity_scan_runs_outside_write_transaction(
    access: tuple[DataAccess, PublicationAccess, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    data, publications, owner = access
    calls: list[bool] = []

    def capacity() -> None:
        with data.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            calls.append(True)

    monkeypatch.setattr(data, "_capacity", capacity)
    publications.capacity = capacity
    data._begin(owner, "IMPORT")
    publications._begin(owner, "REGISTER", None)
    assert calls == [True, True]


def test_reader_slots_share_limits_and_leased_recovery_reclaims_them(
    access: tuple[DataAccess, PublicationAccess, User],
) -> None:
    data, publications, owner = access
    with data.state.connection() as db:
        db.execute(
            "CREATE TABLE resource_readers(id TEXT PRIMARY KEY,owner_id INTEGER "
            "REFERENCES users(id),created REAL)"
        )
        db.executemany(
            "INSERT INTO resource_readers VALUES(?,?,0)",
            [("reader1", owner.id), ("reader2", owner.id)],
        )
    assert counts(data.state) == (2, 2)
    with pytest.raises(AccessError, match="busy"):
        data._begin(owner, "IMPORT")
    with pytest.raises(AccessError, match="busy"):
        publications._begin(owner, "REGISTER", None)
    data.state.enqueue(owner, {})
    assert data.state.claim() is None
    data.recover()
    assert counts(data.state) == (0, 1)
    assert data.state.claim()
