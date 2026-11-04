"""Native runtime scheduling, interruption and complete three-database backup."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest
from test_v0_runtime import REPOSITORY, TEST_REVISION, runner_at

from quant_hunter.config import JsonRecord
from quant_hunter.web import backup
from quant_hunter.web.paper_access import default_paper_config
from quant_hunter.web.runtime import Runtime


def test_paper_runtime_recovery_and_three_database_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "_space", lambda parent, required: None)
    root = tmp_path / "original"
    runner = runner_at(root)
    owner = runner.state.create_user(
        "owner", "synthetic-password-only", "owner", bootstrap=True
    )
    created = runner.paper.create(owner, default_paper_config())
    identity = str(created["id"])
    runner.paper.control(
        owner, identity, "ACTIVATE", expected_revision=int(str(created["revision"]))
    )
    for _ in range(5):
        assert runner.process_one()
    before = runner.paper.get(owner, identity)
    assert before["experiment_id"] and before["status"] == "ACTIVE"
    restarted = runner_at(root)
    restarted.recover()
    paused = restarted.paper.get(owner, identity)
    assert paused["status"] == "PAUSED"
    assert (
        restarted.lab.get_run(str(paused["experiment_id"]))["lifecycle_status"]
        == "RUNNING"
    )
    assert not restarted.process_one()
    archive = tmp_path / "paper.qhbackup"
    manifest = backup.create_backup(root, archive, TEST_REVISION)
    paths = {str(row["path"]) for row in cast(list[JsonRecord], manifest["files"])}
    assert {"application.sqlite3", "paper.sqlite3", "paper-brokers.sqlite3"} <= paths
    restored = tmp_path / "restored"
    backup.restore_backup(archive, restored)
    for name in ("application.sqlite3", "paper.sqlite3", "paper-brokers.sqlite3"):
        assert (root / name).read_bytes() == (restored / name).read_bytes()
    copied = Runtime(restored, REPOSITORY, TEST_REVISION)
    copied.recover()
    retained = copied.paper.get(owner, identity)
    assert retained == paused
    copied.paper.control(
        owner, identity, "RESUME", expected_revision=int(str(retained["revision"]))
    )
    for _ in range(105):
        if not copied.process_one():
            break
    final = copied.paper.get(owner, identity)
    assert final["status"] == "COMPLETED"
    run = copied.lab.get_run(str(final["experiment_id"]))
    assert (
        run["variants_attempted"] == 1 and run["evaluation_outcome"] == "INCONCLUSIVE"
    )


@pytest.mark.parametrize("name", ["paper.sqlite3", "paper-brokers.sqlite3"])
@pytest.mark.parametrize("attack", ["identity", "version", "extra_table"])
def test_backup_refuses_mislabeled_dedicated_databases(
    tmp_path: Path, name: str, attack: str
) -> None:
    runner = runner_at(tmp_path / "runtime")
    database = runner.state.path.parent / name
    with closing(sqlite3.connect(database)) as db, db:
        if attack == "identity":
            db.execute("PRAGMA application_id=0")
        elif attack == "version":
            db.execute("PRAGMA user_version=2")
        else:
            db.execute("CREATE TABLE unreviewed_secret(payload BLOB)")
    archive = tmp_path / "refused.qhbackup"
    with pytest.raises(backup.BackupError, match="identity or schema"):
        backup.create_backup(runner.state.path.parent, archive, TEST_REVISION)
    assert not archive.exists()
