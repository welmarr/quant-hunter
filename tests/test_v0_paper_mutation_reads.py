"""Mutation acknowledgements do not perform unadmitted full report inspection."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from test_v0_paper_workflow import Crash, build, control, launch

from quant_hunter.config import JsonRecord
from quant_hunter.web.paper_access import (
    PaperAccess,
    PaperConflictError,
    default_paper_config,
)
from quant_hunter.web.state import User


@pytest.mark.parametrize(
    "action", ["ACTIVATE", "PAUSE", "KILL", "CANCEL", "RESET_KILL"]
)
def test_control_ack_is_owned_verified_metadata_without_report_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    access, owner = build(tmp_path)
    job = (
        access.create(owner, default_paper_config())
        if action == "ACTIVATE"
        else launch(access, owner)
    )
    identity = cast(str, job["id"])
    current = access.get(owner, identity)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("mutation acknowledgement attempted full evidence inspection")

    monkeypatch.setattr(access, "get", forbidden)
    monkeypatch.setattr(access, "_binding", forbidden)
    monkeypatch.setattr(access, "_object", forbidden)
    monkeypatch.setattr(access.engine, "load", forbidden)
    response = access.control(
        owner, identity, action, expected_revision=cast(int, current["revision"])
    )
    assert response["id"] == identity and response["owner_id"] == owner.id
    assert response["status_authority"] == "OPERATIONAL_SESSION"
    assert response["report_verification"] == "NOT_FRESH_ADMISSION"
    assert "report" not in response and "lifecycle_status" not in response
    with access.state.connection() as db:
        assert response["revision"] == access._load(db, identity, owner.id)["revision"]


def test_resume_preserves_actual_current_source_preflight_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    control(access, owner, job, "PAUSE")
    current = access.get(owner, cast(str, job["id"]))
    actual_binding = access._binding
    calls: list[bool] = []

    def binding(
        row: JsonRecord, *, current: bool = False
    ) -> tuple[JsonRecord, JsonRecord]:
        calls.append(current)
        return actual_binding(row, current=current)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("response called the heavy public report reader")

    monkeypatch.setattr(access, "_binding", binding)
    monkeypatch.setattr(access, "get", forbidden)
    response = access.control(
        owner,
        cast(str, job["id"]),
        "RESUME",
        expected_revision=cast(int, current["revision"]),
    )
    assert calls == [True]
    assert response["status"] == "ACTIVE"
    assert "report" not in response


def test_reconcile_releases_worker_slot_without_unadmitted_response_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    current = access.get(owner, identity)
    read = access._object

    def admitted_only(digest: str, *, maximum: int = 2_000_000) -> JsonRecord:
        with access.state.connection() as db:
            assert access._load(db, identity)["status"] == "RECOVERING"
        return read(digest, maximum=maximum)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("reconcile response attempted a second report read")

    monkeypatch.setattr(access, "_object", admitted_only)
    monkeypatch.setattr(access, "get", forbidden)
    response = access.reconcile(
        owner, identity, expected_revision=cast(int, current["revision"])
    )
    assert response["status"] == "PAUSED"
    assert response["status_authority"] == "OPERATIONAL_SESSION"
    assert "report" not in response


def test_resume_preflight_is_fail_closed_without_product_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    control(access, owner, job, "PAUSE")
    unconfigured = PaperAccess(access.state, access.lab, access.engine)
    current = access.operational_head(owner, cast(str, job["id"]))

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("unadmitted resume read source evidence")

    monkeypatch.setattr(unconfigured, "_binding", forbidden)
    with pytest.raises(PaperConflictError, match="RESUME_READ_ADMISSION_REQUIRED"):
        unconfigured.control(
            owner,
            cast(str, job["id"]),
            "RESUME",
            expected_revision=cast(int, current["revision"]),
        )
    assert access.operational_head(owner, cast(str, job["id"])) == current


def test_resume_reader_receives_exact_owner_and_revision_and_releases_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3
    from collections.abc import Iterator
    from contextlib import contextmanager

    access, owner = build(tmp_path)
    job = launch(access, owner)
    control(access, owner, job, "PAUSE")
    identity = cast(str, job["id"])
    current = access.operational_head(owner, identity)
    active = False
    observed: list[str] = []
    read, save = access._binding, access._save

    @contextmanager
    def resource(actor: User, paper_id: str, revision: int) -> Iterator[None]:
        nonlocal active
        assert (
            actor == owner and paper_id == identity and revision == current["revision"]
        )
        with access.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            access._actor(db, actor, mutation=True)
            assert access._load(db, paper_id, actor.id)["revision"] == revision
        active = True
        observed.append("reserved")
        try:
            yield
        finally:
            with access.state.connection() as db:
                assert access._load(db, paper_id)["revision"] == revision
            active = False
            observed.append("released")

    def binding(
        row: JsonRecord, *, current: bool = False
    ) -> tuple[JsonRecord, JsonRecord]:
        assert active
        return read(row, current=current)

    def mutation(
        db: sqlite3.Connection, row: JsonRecord, changes: JsonRecord, event: str
    ) -> JsonRecord:
        assert not active
        observed.append("mutated")
        return save(db, row, changes, event)

    access.resume_resource = resource
    monkeypatch.setattr(access, "_binding", binding)
    monkeypatch.setattr(access, "_save", mutation)
    response = access.control(
        owner, identity, "RESUME", expected_revision=cast(int, current["revision"])
    )
    assert response["status"] == "ACTIVE"
    assert observed == ["reserved", "released", "mutated"]
