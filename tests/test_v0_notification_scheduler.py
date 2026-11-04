"""Independent runtime scheduling regressions; no real credentials or network."""

from pathlib import Path

import pytest
from test_v0_runtime import runner_at

from quant_hunter.config import JsonRecord
from quant_hunter.web.runtime import Runtime
from quant_hunter.web.state import User


def terminal(runner: Runtime, user: User, identity: int = 1) -> None:
    with runner.state.connection() as db:
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,NULL,NULL)",
            (f"{identity:032x}", user.id, "FAILED", "{}"),
        )


def test_handled_projection_failure_is_exposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = runner_at(tmp_path)
    user = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    terminal(runner, user)
    monkeypatch.setattr(
        runner.notification_projection,
        "sweep",
        lambda *a, **k: {"local_delivery_unavailable": True},
    )
    runner._project_notifications()
    assert runner.notification_projection_error == "LOCAL_DELIVERY_UNAVAILABLE"
    assert runner._notification_owner == user.id
    assert runner.lab.list_runs() == []


def test_scheduler_rejects_overglobalbound_before_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = runner_at(tmp_path)
    user = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    with runner.state.connection() as db:
        db.executemany(
            "INSERT INTO jobs VALUES(?,?,?,?,NULL,NULL)",
            [(f"{i:032x}", user.id, "FAILED", "{}") for i in range(10001)],
        )
    monkeypatch.setattr(
        runner.notification_projection,
        "sweep",
        lambda *a, **k: pytest.fail("must refuse before projector"),
    )
    runner._project_notifications()
    assert runner.notification_projection_error == "LOCAL_DELIVERY_UNAVAILABLE"
    assert runner._notification_owner == 0
    assert runner.lab.list_runs() == []


def test_periodic_projection_pages_one_owner_and_never_sends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = runner_at(tmp_path)
    owner = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    reader = runner.state.create_user(
        "reader", "synthetic-password-only", "reader", bootstrap=False
    )
    terminal(runner, owner)
    terminal(runner, reader, 2)
    monkeypatch.setattr(
        runner.notifications, "send", lambda *a, **k: pytest.fail("no send")
    )
    monkeypatch.setattr(runner.notifications, "_vault", lambda: pytest.fail("no vault"))
    seen = []
    actual = runner.notification_projection.sweep

    def observed(user: User, *, limit: int) -> JsonRecord:
        seen.append((user.id, limit))
        return actual(user, limit=limit)

    monkeypatch.setattr(runner.notification_projection, "sweep", observed)
    runner._project_notifications()
    runner._project_notifications()
    assert seen == [(owner.id, 100)]
    runner._notification_due = 0
    runner._project_notifications()
    assert seen == [(owner.id, 100), (reader.id, 100)]
    assert (
        len(runner.notifications.inbox(owner))
        == len(runner.notifications.inbox(reader))
        == 1
    )
    assert runner.notification_projection_error is None
    assert runner.lab.list_runs() == []
    assert all(
        job.status == "FAILED"
        for job in runner.state.jobs(owner) + runner.state.jobs(reader)
    )
