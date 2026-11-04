"""Actual private SQLite inbox recovery; synthetic jobs and zero external sends."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import cast

import pytest

from quant_hunter.config import JsonRecord, parse_json_document
from quant_hunter.notifications.types import NotificationError, canonical, digest
from quant_hunter.web.notification_access import NotificationAccess
from quant_hunter.web.notification_projection import (
    MAX_COUNTER,
    NotificationProjection,
    ProjectionError,
    _Head,
)
from quant_hunter.web.state import AccessError, AppState, User


def build(tmp_path: Path) -> tuple[NotificationProjection, User]:
    state = AppState(tmp_path / "runtime" / "app.sqlite3")
    user = state.create_user("owner", "synthetic password", "owner", bootstrap=True)
    access = NotificationAccess(
        state,
        tmp_path / "private",
        tmp_path / "application",
        clock=lambda: datetime(2026, 10, 5, tzinfo=UTC),
    )
    return NotificationProjection(access), user


def jobs(
    projection: NotificationProjection,
    user: User,
    count: int,
    status: str = "FAILED",
    *,
    start: int = 1,
) -> list[str]:
    identities = [f"{i:032x}" for i in range(start, start + count)]
    with projection.state.connection() as db:
        db.executemany(
            "INSERT INTO jobs VALUES(?,?,?,?,NULL,NULL)",
            [(identity, user.id, status, "{}") for identity in identities],
        )
    return identities


def count(projection: NotificationProjection, table: str = "qhn_events") -> int:
    queries = {
        "qhn_events": "SELECT count(*) FROM qhn_events",
        "qhn_audit": "SELECT count(*) FROM qhn_audit",
        "qhn_projection": "SELECT count(*) FROM qhn_projection",
        "qhn_attempts": "SELECT count(*) FROM qhn_attempts",
    }
    with projection.state.connection() as db:
        return cast(int, db.execute(queries[table]).fetchone()[0])


def test_oldest_terminal_jobs_paginate_without_starvation_and_do_not_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, user = build(tmp_path)
    ids = jobs(projection, user, 205)
    with projection.state.connection() as db:
        before = [tuple(row) for row in db.execute("SELECT * FROM jobs ORDER BY id")]
    monkeypatch.setattr(
        projection.access, "send", lambda *a, **k: pytest.fail("no send")
    )
    monkeypatch.setattr(projection.access, "_vault", lambda: pytest.fail("no vault"))
    first = projection.sweep(user)
    assert first["scanned"] == first["projected"] == 100
    assert first["cursor"] == ids[99] and first["cycle_complete"] is False
    restarted = NotificationProjection(projection.access)
    second, third = restarted.sweep(user), restarted.sweep(user)
    assert second["cursor"] == ids[199]
    assert third["scanned"] == 5 and third["cycle_complete"] is True
    assert count(projection) == count(projection, "qhn_audit") == 205
    assert restarted.sweep(user)["cycle"] == 2
    assert count(projection) == 205 and count(projection, "qhn_attempts") == 0
    assert not projection.access.private_root.exists()
    with projection.state.connection() as db:
        assert before == [
            tuple(row) for row in db.execute("SELECT * FROM jobs ORDER BY id")
        ]


def test_pending_old_job_and_new_key_behind_cursor_are_revisited(
    tmp_path: Path,
) -> None:
    projection, user = build(tmp_path)
    first = jobs(projection, user, 1, "RUNNING", start=10)[0]
    jobs(projection, user, 1, "SUCCEEDED", start=20)
    assert projection.sweep(user)["projected"] == 1
    with projection.state.connection() as db:
        db.execute("UPDATE jobs SET status='FAILED' WHERE id=?", (first,))
    jobs(projection, user, 1, "CANCELLED", start=1)
    result = projection.sweep(user)
    assert result["projected"] == 3 and result["cycle_complete"] is True
    assert count(projection) == 3
    bodies = [
        str(cast(JsonRecord, row["event"])["body"])
        for row in projection.access.inbox(user)
    ]
    assert any(first in body and "FAILED" in body for body in bodies)


class Crash(BaseException):
    """A process interruption is not a handled delivery failure."""


def test_crash_after_publish_before_cursor_is_idempotent_on_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, user = build(tmp_path)
    identity = jobs(projection, user, 1)[0]
    save = projection._save

    def crash(actor: User, old: _Head, new: _Head) -> bool:
        if new.cursor == identity:
            raise Crash
        return save(actor, old, new)

    monkeypatch.setattr(projection, "_save", crash)
    with pytest.raises(Crash):
        projection.sweep(user)
    assert count(projection) == 1 and projection.status(user)["cursor"] == ""
    restart = NotificationProjection(projection.access)
    assert restart.sweep(user)["cycle_complete"] is True
    assert count(projection) == count(projection, "qhn_audit") == 1


def test_concurrent_sweeps_cannot_duplicate_or_regress_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, user = build(tmp_path)
    identities = jobs(projection, user, 3, "RUNNING")
    projection.sweep(user, limit=1)
    with projection.state.connection() as db:
        db.execute("UPDATE jobs SET status='FAILED' WHERE id>?", (identities[0],))
    barrier, original = Barrier(2), projection.access.record_job

    def concurrent(actor: User, identity: str) -> JsonRecord:
        barrier.wait(timeout=10)
        return original(actor, identity)

    monkeypatch.setattr(projection.access, "record_job", concurrent)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: projection.sweep(user, limit=1), range(2)))
    assert all(result["local_delivery_unavailable"] is False for result in results)
    assert projection.status(user)["cursor"] == identities[1]
    assert count(projection) == count(projection, "qhn_audit") == 1
    monkeypatch.setattr(projection.access, "record_job", original)
    assert projection.sweep(user)["cursor"] == identities[2]
    assert count(projection) == 2


@pytest.mark.parametrize(
    "error,code",
    [
        (NotificationError("INBOX_CAPACITY"), "INBOX_CAPACITY"),
        (NotificationError("INBOX_INTEGRITY"), "INBOX_INTEGRITY"),
        (NotificationError("CLOCK_MOVED_BACKWARDS"), "LOCAL_DELIVERY_REFUSED"),
        (
            RuntimeError("synthetic-secret-must-not-be-retained"),
            "LOCAL_DELIVERY_UNAVAILABLE",
        ),
    ],
)
def test_failure_stops_cursor_and_retains_bounded_receipt_then_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, code: str
) -> None:
    projection, user = build(tmp_path)
    identities = jobs(projection, user, 3)
    original = projection.access.record_job

    def fail(actor: User, identity: str) -> JsonRecord:
        if identity == identities[1]:
            raise error
        return original(actor, identity)

    monkeypatch.setattr(projection.access, "record_job", fail)
    result = projection.sweep(user)
    assert result["cursor"] == identities[0] and result["scanned"] == 1
    assert (
        result["failure_code"] == code and result["failure_receipt_persisted"] is True
    )
    assert count(projection) == 1
    first = projection.status(user)
    assert projection.sweep(user)["cursor"] == identities[0]
    assert projection.status(user) == first
    assert count(projection, "qhn_projection") == 1
    monkeypatch.setattr(projection.access, "record_job", original)
    good = projection.sweep(user)
    assert (
        good["cycle_complete"] is True and good["local_delivery_unavailable"] is False
    )
    assert good["first_failure"] == good["last_failure"] == first["last_failure"]
    assert "synthetic-secret-must-not-be-retained" not in repr(good)
    assert (
        b"synthetic-secret-must-not-be-retained"
        not in projection.state.path.read_bytes()
    )


def test_real_inbox_corruption_is_not_skipped_or_reported_delivered(
    tmp_path: Path,
) -> None:
    projection, user = build(tmp_path)
    jobs(projection, user, 1)
    projection.sweep(user)
    with projection.state.connection() as db:
        db.execute("DROP TRIGGER qhn_events_UPDATE")
        db.execute("UPDATE qhn_events SET payload=?", (b"corrupt",))
    result = projection.sweep(user)
    assert result["failure_code"] == "INBOX_INTEGRITY" and result["cursor"] == ""
    assert result["projected"] == 0 and count(projection) == 1


def test_global_job_bound_stops_without_hiding_or_deleting_jobs(tmp_path: Path) -> None:
    projection, user = build(tmp_path)
    jobs(projection, user, 10_001)
    result = projection.sweep(user)
    assert result["failure_code"] == "JOB_CAPACITY"
    assert result["cursor"] == "" and count(projection) == 0
    assert projection.status(user)["local_delivery_unavailable"] is True
    with projection.state.connection() as db:
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 10_001


def test_current_identity_private_ownership_and_reader_projection(
    tmp_path: Path,
) -> None:
    projection, user = build(tmp_path)
    other = projection.state.create_user(
        "other", "synthetic password", "reader", bootstrap=False
    )
    jobs(projection, user, 2)
    jobs(projection, other, 1, "CANCELLED", start=30)
    assert projection.sweep(other)["projected"] == 1
    assert len(projection.access.inbox(other)) == 1
    assert projection.status(user)["status"] == "NOT_STARTED"
    forged = User(user.id, other.username, "reader")
    for action in (projection.sweep, projection.status):
        with pytest.raises(AccessError):
            action(forged)
    with projection.state.connection() as db:
        db.execute("UPDATE users SET role='researcher' WHERE id=?", (user.id,))
    with pytest.raises(AccessError):
        projection.sweep(user)
    assert count(projection) == 1


@pytest.mark.parametrize("limit", [0, -1, 101, True, "10", 1.5])
def test_closed_page_bounds_before_any_projection(
    tmp_path: Path, limit: object
) -> None:
    projection, user = build(tmp_path)
    with pytest.raises(ValueError, match="page limit"):
        projection.sweep(user, limit=limit)  # type: ignore[arg-type]
    assert count(projection, "qhn_projection") == 0


def test_missing_anchor_and_coherent_foreign_cursor_fail_closed(tmp_path: Path) -> None:
    projection, user = build(tmp_path)
    identities = jobs(projection, user, 2)
    projection.sweep(user, limit=1)
    with projection.state.connection() as db:
        head = projection._head(db, user)
        value = asdict(head)
        value["cursor"] = "f" * 32
        value["ceiling"] = "f" * 32
        raw = canonical(value)
        db.execute("UPDATE qhn_projection SET payload=?,digest=?", (raw, digest(raw)))
    result = projection.sweep(user)
    assert result["failure_code"] == "PROJECTION_INTEGRITY"
    assert count(projection) == 1 and result["projected"] == 0
    assert identities[1] not in str(projection.access.inbox(user))


def test_unavailable_database_exposes_fixed_unpersisted_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, user = build(tmp_path)

    @contextmanager
    def unavailable() -> Iterator[sqlite3.Connection]:
        if projection.state.path.exists():
            raise sqlite3.OperationalError("synthetic-sensitive-path")
        with sqlite3.connect(":memory:") as db:
            yield db

    monkeypatch.setattr(projection.state, "connection", unavailable)
    result = projection.sweep(user)
    assert result["local_delivery_unavailable"] is True
    assert result["failure_code"] == "PROJECTION_STORAGE_UNAVAILABLE"
    assert result["failure_receipt_persisted"] is False
    assert "synthetic-sensitive-path" not in repr(result)


def test_empty_and_invalid_job_states_do_not_generate_notifications(
    tmp_path: Path,
) -> None:
    projection, user = build(tmp_path)
    assert projection.sweep(user)["cycle_complete"] is True
    jobs(projection, user, 1, "INVALID")
    result = projection.sweep(user)
    assert result["failure_code"] == "PROJECTION_INTEGRITY" and count(projection) == 0


def test_callback_without_retained_event_cannot_advance_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, user = build(tmp_path)
    jobs(projection, user, 1)
    monkeypatch.setattr(projection.access, "record_job", lambda *a: {})
    result = projection.sweep(user)
    assert result["local_delivery_unavailable"] is True and result["cursor"] == ""
    assert result["projected"] == 0 and count(projection) == 0


def test_retained_event_cannot_rebind_another_experiment(tmp_path: Path) -> None:
    projection, user = build(tmp_path)
    identity = jobs(projection, user, 1)[0]
    projection.sweep(user)
    with projection.state.connection() as db:
        db.execute(
            "UPDATE jobs SET experiment_id='EXP-different' WHERE id=?", (identity,)
        )
    result = projection.sweep(user)
    assert result["failure_code"] == "PROJECTION_INTEGRITY" and result["cursor"] == ""


@pytest.mark.parametrize(
    "mutation",
    [
        {"owner_id": 999},
        {"revision": True},
        {"cursor": "f" * 32},
        {"last_failure": {"code": "arbitrary-private-error", "cycle": 1, "cursor": ""}},
        {"first_failure": {"code": "INBOX_CAPACITY", "cycle": 1, "cursor": ""}},
        {"unavailable": True},
        {
            "first_failure": {"code": "INBOX_CAPACITY", "cycle": 900, "cursor": ""},
            "last_failure": {"code": "INBOX_CAPACITY", "cycle": 900, "cursor": ""},
        },
        {"injected": "unknown authority"},
    ],
)
def test_coherently_rehashed_cursor_metadata_is_closed_and_owner_bound(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    projection, user = build(tmp_path)
    jobs(projection, user, 2)
    projection.sweep(user, limit=1)
    with projection.state.connection() as db:
        value = {**asdict(projection._head(db, user)), **mutation}
        raw = canonical(value)
        db.execute("UPDATE qhn_projection SET payload=?,digest=?", (raw, digest(raw)))
    result = projection.sweep(user)
    assert result["failure_code"] == "PROJECTION_INTEGRITY"
    assert result["failure_receipt_persisted"] is False and count(projection) == 1


@pytest.mark.parametrize("raw", [b"not-json", b"[]", b"x" * 4097])
def test_corrupt_cursor_payload_never_claims_saved_failure(
    tmp_path: Path, raw: bytes
) -> None:
    projection, user = build(tmp_path)
    projection.sweep(user)
    with projection.state.connection() as db:
        db.execute("UPDATE qhn_projection SET payload=?,digest=?", (raw, digest(raw)))
    result = projection.status(user)
    assert result["failure_code"] == "PROJECTION_INTEGRITY"
    assert result["failure_receipt_persisted"] is False


@pytest.mark.parametrize("field", ["cycle", "revision"])
def test_counter_exhaustion_never_wraps_or_loses_retained_work(
    tmp_path: Path, field: str
) -> None:
    projection, user = build(tmp_path)
    jobs(projection, user, 1)
    projection.sweep(user)
    with projection.state.connection() as db:
        value = asdict(projection._head(db, user))
        value[field] = MAX_COUNTER
        raw = canonical(value)
        db.execute("UPDATE qhn_projection SET payload=?,digest=?", (raw, digest(raw)))
    result = projection.sweep(user)
    assert result["failure_code"] == "PROJECTION_CAPACITY" and count(projection) == 1


def test_empty_recovery_preserves_receipt_and_conflicting_start_does_no_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection, user = build(tmp_path)
    failed = projection._unavailable(user, RuntimeError("not persisted text"))
    assert failed["failure_receipt_persisted"] is True
    recovered = projection.sweep(user)
    assert recovered["local_delivery_unavailable"] is False
    assert recovered["last_failure"] == failed["last_failure"]
    jobs(projection, user, 1)
    monkeypatch.setattr(projection, "_save", lambda *a: False)
    assert projection.sweep(user)["projected"] == 0 and count(projection) == 0


def test_shared_store_mismatch_is_refused(tmp_path: Path) -> None:
    projection, _ = build(tmp_path)
    projection.access.store.path = tmp_path / "foreign.sqlite3"
    with pytest.raises(ProjectionError, match="INTEGRITY"):
        NotificationProjection(projection.access)


@pytest.mark.parametrize("field", ["notification_id", "title"])
def test_existing_notice_cannot_substitute_payload_identity_or_title(
    tmp_path: Path, field: str
) -> None:
    projection, user = build(tmp_path)
    jobs(projection, user, 2)
    projection.sweep(user)
    with projection.state.connection() as db:
        notices = db.execute(
            "SELECT event_id,payload FROM qhn_events ORDER BY sequence"
        ).fetchall()
        value = cast(JsonRecord, parse_json_document(notices[0]["payload"]))
        value[field] = (
            notices[1]["event_id"]
            if field == "notification_id"
            else "False status claim"
        )
        raw = canonical(value)
        db.execute("DROP TRIGGER qhn_events_UPDATE")
        db.execute(
            "UPDATE qhn_events SET payload=?,payload_digest=? WHERE event_id=?",
            (raw, digest(raw), notices[0]["event_id"]),
        )
    result = projection.sweep(user)
    assert result["failure_code"] == "PROJECTION_INTEGRITY"
    assert result["cursor"] == "" and result["projected"] == 0
    assert count(projection) == 2
