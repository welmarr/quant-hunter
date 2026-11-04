"""Real persistent local halt, protective commands and host race contracts."""

from __future__ import annotations

import base64
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from test_v0_paper_workflow import Crash, build, control, launch

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.simulation import accounting as a
from quant_hunter.web import paper_halt as module
from quant_hunter.web.paper_access import (
    PaperAccess,
    PaperConflictError,
    PaperWorkflowError,
    default_paper_config,
)
from quant_hunter.web.paper_halt import GlobalPaperHalt, HaltError
from quant_hunter.web.state import AccessError, User


def gate(access: PaperAccess) -> GlobalPaperHalt:
    return GlobalPaperHalt(
        access, read_resource=lambda actor, paper_id, revision: nullcontext()
    )


def test_empty_stop_clear_cas_permissions_and_aggregate_privacy(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    halt = gate(access)
    researcher = access.state.create_user(
        "researcher", "synthetic password", "researcher", bootstrap=False
    )
    reader = access.state.create_user(
        "reader", "synthetic password", "reader", bootstrap=False
    )
    assert halt.status(reader) == {
        "halted": False,
        "revision": 0,
        "scope": "LOCAL_PAPER_ONLY",
        "automatic_resume": False,
    }
    for actor in (researcher, reader, User(owner.id, owner.username, "reader")):
        with pytest.raises(AccessError):
            halt.halt(actor, expected_revision=0)
    for revision in (-1, True):
        with pytest.raises(HaltError, match="STALE"):
            halt.halt(owner, expected_revision=revision)
    result = halt.halt(owner, expected_revision=0)
    assert result["counts"] == {"pending": 0, "protected": 0, "blocked": 0}
    assert halt.status(researcher)["halted"] is True
    with pytest.raises(HaltError, match="ALREADY"):
        halt.halt(owner, expected_revision=1)
    with pytest.raises(HaltError, match="STALE"):
        halt.clear(owner, expected_revision=0)
    assert halt.clear(owner, expected_revision=1)["revision"] == 2


def test_not_started_is_protected_without_allocating_experiment(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    control(access, owner, job, "ACTIVATE")
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    assert not access.process_one()
    assert halt.has_pending()
    assert halt.process_one()
    fresh = access.get(owner, cast(str, job["id"]))
    assert fresh["status"] == "CREATED"
    assert access.lab.list_runs() == []
    assert not halt.has_pending()
    assert not halt.process_one()
    with pytest.raises(PaperConflictError, match="GLOBAL_PAPER_HALTED"):
        control(access, owner, fresh, "ACTIVATE")
    halt.clear(owner, expected_revision=1)
    assert access.get(owner, cast(str, job["id"]))["status"] == "CREATED"
    assert not halt.process_one()
    control(access, owner, fresh, "ACTIVATE")
    assert halt.process_one()


@pytest.mark.parametrize("market", ["EQUITY", "FX_SPOT"])
def test_native_kill_cancel_preserves_economic_and_drawdown_baselines(
    tmp_path: Path, market: str
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner, market, lookback=1)
    for _ in range(3):
        assert access.process_one()
    identity = cast(str, job["id"])
    before = access.engine.load(identity, str(owner.id))
    assert before.book.positions and before.reservations
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    with pytest.raises(PaperConflictError):
        halt.clear(owner, expected_revision=1)
    assert halt.process_one()
    after = access.engine.load(identity, str(owner.id))
    assert after.killed and not after.reservations
    assert not any(order.status in a.OPEN for order in after.book.orders)
    assert (
        after.book.cash,
        after.book.positions,
        after.book.fills,
        after.inception_equity,
        after.high_water,
        after.max_drawdown,
    ) == (
        before.book.cash,
        before.book.positions,
        before.book.fills,
        before.inception_equity,
        before.high_water,
        before.max_drawdown,
    )
    assert halt.status(owner)["counts"] == {"pending": 0, "protected": 1, "blocked": 0}
    for action in ("RESUME", "RESET_KILL"):
        with pytest.raises(PaperConflictError, match="GLOBAL_PAPER_HALTED"):
            control(access, owner, job, action)
    halt.clear(owner, expected_revision=1)
    assert access.get(owner, identity)["status"] == "PAUSED"
    assert access.engine.load(identity, str(owner.id)).killed
    assert not halt.process_one()
    control(access, owner, job, "RESET_KILL")
    assert halt.process_one()
    assert not access.engine.load(identity, str(owner.id)).killed
    assert access.get(owner, identity)["status"] == "PAUSED"
    assert (
        access.lab.get_run(cast(str, job["experiment_id"]))["variants_attempted"] == 0
    )


def test_foreign_sessions_only_appear_as_aggregate_counts(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    other = access.state.create_user(
        "other", "synthetic password", "researcher", bootstrap=False
    )
    job = access.create(other, default_paper_config())
    halt = gate(access)
    serialized = canonicalize_json(halt.halt(owner, expected_revision=0))
    assert str(job["id"]).encode() not in serialized and b"other" not in serialized
    assert b"owner_id" not in serialized
    assert halt.process_one()
    with pytest.raises(AccessError):
        access.get(owner, cast(str, job["id"]))
    with pytest.raises(HaltError, match="PERSISTED"):
        access.protective_halt_step(cast(str, job["id"]), 3)
    with pytest.raises(HaltError, match="PERSISTED"):
        access.protective_halt_step("PAPER-" + "0" * 32, 1)


def test_stop_waits_current_bar_then_prevents_new_step_across_instances(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    entered, release, stopped = Event(), Event(), Event()
    halt, second = gate(access), gate(access)

    def block(phase: str) -> None:
        if phase == "CLAIMED":
            entered.set()
            assert release.wait(15)

    def stop() -> JsonRecord:
        result = second.halt(owner, expected_revision=0)
        stopped.set()
        return result

    access.fault = block
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(halt.process_one)
        assert entered.wait(15)
        stopping = pool.submit(stop)
        assert not stopped.wait(0.05)
        assert not access.process_one()
        release.set()
        assert running.result(timeout=15)
        assert stopping.result(timeout=15)["halted"] is True
    access.fault = lambda phase: None
    assert access.get(owner, cast(str, job["id"]))["cursor"] == 1
    assert not access.process_one()
    assert halt.process_one()
    assert access.get(owner, cast(str, job["id"]))["cursor"] == 1


@pytest.mark.parametrize("action", ["ACTIVATE", "RESUME", "RESET_KILL"])
def test_control_waiting_on_stop_barrier_rechecks_persistent_state(
    tmp_path: Path, action: str
) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    halt = gate(access)
    ready = Event()

    def attempt() -> JsonRecord:
        ready.set()
        return access.control(
            owner,
            cast(str, job["id"]),
            action,
            expected_revision=cast(int, job["revision"]),
        )

    with module.gate_lock(access.state.path), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(attempt)
        assert ready.wait(5)
        halt.halt(owner, expected_revision=0)
        # Release the gate before executor waits for completion.
        module.gate_lock(access.state.path).release()
        try:
            with pytest.raises(PaperConflictError, match="GLOBAL_PAPER_HALTED"):
                future.result(timeout=10)
        finally:
            module.gate_lock(access.state.path).acquire()


def test_restart_honors_halt_and_receipts_without_resubmitting_commands(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    assert halt.process_one()
    before = access.engine.load(cast(str, job["id"]), str(owner.id))
    restarted = PaperAccess(access.state, access.lab, access.engine)
    restarted.recover()
    restored = gate(restarted)
    assert restored.status(owner)["halted"] is True
    assert not restored.process_one()
    assert access.engine.load(cast(str, job["id"]), str(owner.id)) == before
    assert restored.clear(owner, expected_revision=1)["halted"] is False


@pytest.mark.parametrize(
    "phase", ["CLAIMED", "AFTER_ENGINE_COMMAND", "AFTER_STEP_RECEIPT"]
)
def test_crash_stays_blocked_until_exact_reconciliation_or_cancel(
    tmp_path: Path, phase: str
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)

    def crash(current: str) -> None:
        if current == phase:
            raise Crash

    access.fault = crash
    with pytest.raises(Crash):
        halt.process_one()
    access.fault = lambda current: None
    access.recover()
    before = access.engine.load(cast(str, job["id"]), str(owner.id))
    assert halt.process_one()
    assert halt.status(owner)["counts"] == {"pending": 0, "protected": 0, "blocked": 1}
    assert not halt.process_one()
    assert access.engine.load(cast(str, job["id"]), str(owner.id)) == before
    with pytest.raises(PaperConflictError):
        halt.clear(owner, expected_revision=1)
    fresh = access.get(owner, cast(str, job["id"]))
    if phase == "AFTER_ENGINE_COMMAND":
        with pytest.raises(PaperConflictError, match="PARTIAL_STEP"):
            access.reconcile(
                owner,
                cast(str, job["id"]),
                expected_revision=cast(int, fresh["revision"]),
            )
        control(access, owner, job, "CANCEL")
        assert halt.process_one()
    else:
        access.reconcile(
            owner, cast(str, job["id"]), expected_revision=cast(int, fresh["revision"])
        )
        assert halt.process_one()
    # A cancelled ambiguous session is terminal; retained accounting is not erased.
    while halt.has_pending():
        assert halt.process_one()
    halt.clear(owner, expected_revision=1)


def test_shared_busy_slots_do_not_run_protection_or_churn_receipts(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    before = access.engine.load(cast(str, job["id"]), str(owner.id))
    with access.state.connection() as db:
        db.executemany(
            "INSERT INTO jobs VALUES(?,?,?,'{}',NULL,NULL)",
            [("a", owner.id, "RUNNING"), ("b", owner.id, "RUNNING")],
        )
    assert not halt.process_one()
    assert not halt.process_one()
    assert access.engine.load(cast(str, job["id"]), str(owner.id)) == before
    with access.state.connection() as db:
        assert db.execute("SELECT count(*) FROM qhp_halt_receipts").fetchone()[0] == 0
        db.execute("UPDATE jobs SET status='COMPLETE'")
    assert halt.process_one()


def test_missing_host_read_admission_fails_closed(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    control(access, owner, job, "PAUSE")
    halt = GlobalPaperHalt(access)
    halt.halt(owner, expected_revision=0)
    with pytest.raises(HaltError, match="ADMISSION"):
        halt.process_one()
    with pytest.raises(HaltError, match="ADMISSION"):
        halt.clear(owner, expected_revision=1)


def test_pending_reset_is_replaced_by_protection_and_cancel_remains_allowed(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    control(access, owner, job, "RESET_KILL")
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    assert halt.process_one()
    assert access.engine.load(cast(str, job["id"]), str(owner.id)).killed
    control(access, owner, job, "CANCEL")
    assert halt.process_one()
    assert access.get(owner, cast(str, job["id"]))["status"] == "CANCELLED"
    halt.clear(owner, expected_revision=1)


def test_immutable_and_corrupt_halt_chains_fail_closed(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    with access.state.connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM qhp_halt_events")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE qhp_halt_events SET digest='forged'")
        db.execute("DROP TRIGGER qhp_halt_update")
        db.execute("UPDATE qhp_halt_events SET digest='forged'")
    for operation in (
        lambda: halt.status(owner),
        access.process_one,
        lambda: gate(access),
    ):
        with pytest.raises(HaltError, match="CHAIN"):
            operation()


def test_last_global_control_slot_is_reserved_for_persistent_halt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    monkeypatch.setattr(module, "MAX_CONTROLS", 3)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    halt.clear(owner, expected_revision=1)
    halt.halt(owner, expected_revision=2)
    with pytest.raises(HaltError, match="CAPACITY"):
        halt.clear(owner, expected_revision=3)
    assert gate(access).status(owner)["halted"] is True


def test_clear_rechecks_current_role_and_receipt_after_read_reservation(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    launch(access, owner)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    halt.process_one()

    def revoke(actor: User, paper_id: str, revision: int) -> nullcontext[None]:
        with access.state.connection() as db:
            db.execute("UPDATE users SET role='reader' WHERE id=?", (owner.id,))
        return nullcontext()

    halt.read_resource = revoke
    with pytest.raises(AccessError):
        halt.clear(owner, expected_revision=1)
    assert halt.status(User(owner.id, owner.username, "reader"))["halted"] is True


def test_lost_protection_receipt_after_commit_is_adopted_without_new_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)

    def crash(_: JsonRecord) -> None:
        raise Crash

    monkeypatch.setattr(halt, "_save_receipt", crash)
    with pytest.raises(Crash):
        halt.process_one()
    before = access.engine.load(cast(str, job["id"]), str(owner.id))
    access.recover()
    restored = gate(access)
    assert restored.process_one()
    assert access.engine.load(cast(str, job["id"]), str(owner.id)) == before
    restored.clear(owner, expected_revision=1)


def test_clear_history_is_bound_to_exact_retained_proof(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    access.create(owner, default_paper_config())
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    assert halt.process_one()
    halt.clear(owner, expected_revision=1)
    with access.state.connection() as db:
        raw = db.execute(
            "SELECT payload FROM qhp_halt_events WHERE revision=2"
        ).fetchone()[0]
        assert b"receipt_digest" in raw
        db.execute("DROP TRIGGER qhp_halt_receipt_delete")
        db.execute("DELETE FROM qhp_halt_receipts")
    with pytest.raises(HaltError, match="CLEAR_PROOF_MISSING"):
        halt.status(owner)
    with pytest.raises(HaltError, match="CLEAR_PROOF_MISSING"):
        access.process_one()


def test_cancel_between_clear_proof_and_final_commit_is_detected(
    tmp_path: Path,
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    access, owner = build(tmp_path)
    job = launch(access, owner)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    halt.process_one()

    @contextmanager
    def reservation(actor: User, paper_id: str, revision: int) -> Iterator[None]:
        with access.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")  # Proof work must not hold the write lock.
        yield
        control(access, owner, job, "CANCEL")

    halt.read_resource = reservation
    with pytest.raises(HaltError, match="STALE_PROOF"):
        halt.clear(owner, expected_revision=1)
    assert halt.status(owner)["halted"] is True
    halt.read_resource = lambda actor, paper_id, revision: nullcontext()
    assert halt.process_one()
    halt.clear(owner, expected_revision=1)


@pytest.mark.parametrize(
    "mutation", ["timestamp", "owner", "task", "duplicate", "proofs"]
)
def test_coherently_rehashed_invalid_control_payload_is_rejected(
    tmp_path: Path, mutation: str
) -> None:
    access, owner = build(tmp_path)
    access.create(owner, default_paper_config())
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    with access.state.connection() as db:
        raw = bytes(db.execute("SELECT payload FROM qhp_halt_events").fetchone()[0])
        item = module._decode(raw, module.MAX_EVENT_BYTES)
        if mutation == "timestamp":
            item["at"] = "invalid+00:00"
        elif mutation == "owner":
            item["owner_id"] = True
        elif mutation == "task":
            item["tasks"] = [
                {"job_id": "PAPER-bad", "owner_id": owner.id, "workflow_revision": 1}
            ]
        elif mutation == "duplicate":
            item["tasks"] = cast(list[JsonValue], item["tasks"]) * 2
        else:
            item["proofs"] = ["forged"]
        raw = canonicalize_json(item)
        db.execute("DROP TRIGGER qhp_halt_update")
        db.execute(
            "UPDATE qhp_halt_events SET payload=?,digest=?", (raw, module._hash(raw))
        )
    with pytest.raises(HaltError):
        halt.status(owner)


@pytest.mark.parametrize("raw", [b"", b"[]", b"{} ", b"{", b"x" * 20000])
def test_bounded_canonical_decoder(raw: bytes) -> None:
    with pytest.raises(HaltError):
        module._decode(raw, module.MAX_EVENT_BYTES)


def test_receipt_immutability_integrity_and_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    assert halt.process_one()
    proof = access.protection_receipt(cast(str, job["id"]), 1)
    halt._save_receipt(proof)  # Exact replay does not consume another receipt.
    with access.state.connection() as db:
        assert db.execute("SELECT count(*) FROM qhp_halt_receipts").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE qhp_halt_receipts SET digest='forged'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM qhp_halt_receipts")
    control(access, owner, job, "CANCEL")
    monkeypatch.setattr(module, "MAX_RECEIPTS", 1)
    with pytest.raises(HaltError, match="RECEIPT_CAPACITY"):
        halt.process_one()
    assert halt.status(owner)["halted"] is True
    monkeypatch.setattr(module, "MAX_RECEIPTS", 8)
    with access.state.connection() as db:
        db.execute("DROP TRIGGER qhp_halt_receipt_update")
        db.execute("UPDATE qhp_halt_receipts SET digest='forged'")
    with pytest.raises(HaltError, match="RECEIPT_INTEGRITY"):
        halt.status(owner)


def test_unretained_but_safe_proof_cannot_clear(tmp_path: Path) -> None:
    access, owner = build(tmp_path)
    access.create(owner, default_paper_config())
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    with pytest.raises(HaltError, match="RECEIPT_REQUIRED"):
        halt.clear(owner, expected_revision=1)


def test_event_task_and_proof_size_caps_preserve_halt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    halt = gate(access)
    monkeypatch.setattr(module, "MAX_TASKS", 0)
    with pytest.raises(HaltError, match="TASK_CAPACITY"):
        halt.halt(owner, expected_revision=0)
    monkeypatch.setattr(module, "MAX_TASKS", 32)
    monkeypatch.setattr(module, "MAX_EVENT_BYTES", 10)
    with pytest.raises(HaltError, match="EVENT_CAPACITY"):
        halt.halt(owner, expected_revision=0)
    monkeypatch.setattr(module, "MAX_EVENT_BYTES", 16384)
    halt.halt(owner, expected_revision=0)
    proof = access.protection_receipt(cast(str, job["id"]), 1)
    monkeypatch.setattr(module, "MAX_RECEIPT_BYTES", 10)
    with pytest.raises(HaltError, match="RECEIPT_SIZE"):
        halt._save_receipt(proof)
    assert halt.status(owner)["halted"] is True


def test_protective_event_headroom_failure_remains_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_hunter.web import paper_access

    access, owner = build(tmp_path)
    job = launch(access, owner)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    fresh = access.get(owner, cast(str, job["id"]))
    monkeypatch.setattr(paper_access, "MAX_EVENTS", cast(int, fresh["revision"]) + 5)
    assert halt.process_one()
    assert halt.status(owner)["counts"] == {"pending": 0, "protected": 0, "blocked": 1}
    assert not halt.process_one()
    assert not access.engine.load(cast(str, job["id"]), str(owner.id)).killed


@pytest.mark.parametrize("producer", ["old", "new", "malformed"])
def test_source_dependency_matches_retained_producer_without_weakening_current_execution(
    tmp_path: Path,
    producer: str,
) -> None:
    from quant_hunter.web import paper_access

    access, _ = build(tmp_path)
    package = Path(paper_access.__file__).resolve().parents[1]
    files: JsonRecord = {
        "src/quant_hunter/" + name: base64.b64encode(
            (package / name).read_bytes()
        ).decode("ascii")
        for name in paper_access.SOURCE_FILES
        if name != "web/paper_halt.py"
    }
    key = "src/quant_hunter/web/paper_access.py"
    if producer == "old":
        # Explicit synthetic pre-halt producer metadata; no experiment is executed.
        files[key] = base64.b64encode(
            b'"""Synthetic retained pre-halt producer fixture."""\n'
        ).decode("ascii")
    elif producer == "malformed":
        files[key] = "not-valid-base64"
    source = access.lab.objects.publish(
        canonicalize_json({"encoding": "base64-exact-bytes", "files": files})
    )
    environment = access.lab.objects.publish(
        canonicalize_json({"source_snapshot_digest": source.digest})
    )
    if producer == "old":
        assert access._source(environment.digest, current=False) == source.digest
    else:
        with pytest.raises(
            PaperWorkflowError, match=r"SOURCE_ENCODING|SOURCE_FILE_MISSING"
        ):
            access._source(environment.digest, current=False)
    with pytest.raises(
        PaperWorkflowError,
        match=r"SOURCE_ENCODING|SOURCE_FILE_MISSING|EXECUTING_SOURCE_MISMATCH",
    ):
        access._source(environment.digest, current=True)


def test_trusted_per_task_reader_uses_actual_actor_and_releases_before_commands(
    tmp_path: Path,
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    access, issuer = build(tmp_path)
    owner = access.state.create_user(
        "paper-owner", "synthetic password", "researcher", bootstrap=False
    )
    job = launch(access, owner)
    control(access, owner, job, "PAUSE")
    halt = gate(access)
    halt.halt(issuer, expected_revision=0)
    calls: list[JsonRecord] = []
    active = False

    @contextmanager
    def reader(actor: User, paper_id: str, revision: int) -> Iterator[None]:
        nonlocal active
        assert actor == issuer
        with access.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            binding = halt.authorize_reader(db, actor, paper_id, revision)
        assert binding["paper_owner_id"] == owner.id
        assert binding["reader_owner_id"] == issuer.id
        assert binding["paper_job_id"] == job["id"]
        assert binding["halt_revision"] == 1
        assert str(binding["halt_digest"]).startswith("sha256:")
        calls.append(binding)
        active = True
        try:
            yield
        finally:
            active = False

    def fault(phase: str) -> None:
        if phase in {"CLAIMED", "AFTER_ENGINE_COMMAND"}:
            assert not active

    halt.read_resource = reader
    access.fault = fault
    assert halt.process_one()
    assert (
        len(calls) == 2
    )  # First observed not killed; second proves actual protection.
    halt.clear(issuer, expected_revision=1)
    assert len(calls) == 3


def test_retained_halt_authority_survives_demotion_but_clear_requires_current_owner(
    tmp_path: Path,
) -> None:
    access, issuer = build(tmp_path)
    job = launch(access, issuer)
    halt = gate(access)
    halt.halt(issuer, expected_revision=0)
    successor = access.state.create_user(
        "new-owner", "synthetic password", "owner", bootstrap=False
    )
    with access.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (issuer.id,))
    observed: list[User] = []

    def reader(actor: User, paper_id: str, revision: int) -> nullcontext[None]:
        with access.state.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            halt.authorize_reader(db, actor, paper_id, revision)
        observed.append(actor)
        return nullcontext()

    halt.read_resource = reader
    assert halt.process_one()
    assert observed == [User(issuer.id, issuer.username, "reader")]
    assert access.engine.load(cast(str, job["id"]), str(issuer.id)).killed
    with pytest.raises(AccessError):
        halt.clear(User(issuer.id, issuer.username, "reader"), expected_revision=1)
    halt.clear(successor, expected_revision=1)
    assert observed[-1] == successor


def test_trusted_reader_refuses_ordinary_foreign_stale_and_nonreserved_links(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = launch(access, owner)
    other = access.state.create_user(
        "ordinary", "synthetic password", "researcher", bootstrap=False
    )
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    identity = cast(str, job["id"])
    with access.state.connection() as db:
        with pytest.raises(HaltError, match="TRANSACTION"):
            halt.authorize_reader(db, owner, identity, 1)
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(HaltError, match="RESERVATION"):
            halt.authorize_reader(
                db, owner, identity, 1
            )  # ACTIVE cannot borrow a reader slot.
        with pytest.raises(HaltError, match="PERSISTED"):
            halt.authorize_reader(db, owner, identity, 2)
        with pytest.raises(AccessError):
            halt.authorize_reader(db, other, identity, 1)
        with pytest.raises(AccessError):
            halt.authorize_reader(
                db, User(owner.id, owner.username, "reader"), identity, 1
            )
    halt.process_one()
    control(access, owner, job, "CANCEL")
    with access.state.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(HaltError, match="RESERVATION"):
            halt.authorize_reader(
                db, owner, identity, 1
            )  # Pending control is not a stable read.
    halt.process_one()
    with access.state.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(HaltError, match="RESERVATION"):
            halt.authorize_reader(
                db, owner, identity, 1
            )  # Terminal has no queue reservation.
    halt.clear(owner, expected_revision=1)
    with access.state.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(HaltError, match="PERSISTED"):
            halt.authorize_reader(db, owner, identity, 1)


def test_operational_only_proofs_do_not_borrow_a_reader_or_terminal_queue(
    tmp_path: Path,
) -> None:
    access, owner = build(tmp_path)
    job = access.create(owner, default_paper_config())
    halt = GlobalPaperHalt(access)  # Unconfigured heavy reader remains fail-closed.
    halt.halt(owner, expected_revision=0)
    assert halt.process_one()  # Input-only CREATED proof needs no native/source read.
    control(access, owner, job, "CANCEL")
    assert halt.process_one()
    halt.clear(owner, expected_revision=1)
    assert access.lab.list_runs() == []


@pytest.mark.parametrize("action", ["PAUSE", "CANCEL", "KILL"])
def test_all_controls_wait_for_linked_proof_release_without_losing_requests(
    tmp_path: Path, action: str
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    access, owner = build(tmp_path)
    job = launch(access, owner)
    halt = gate(access)
    halt.halt(owner, expected_revision=0)
    halt.process_one()
    identity = cast(str, job["id"])
    before = access.get(owner, identity)
    entered, release, attempted, completed = Event(), Event(), Event(), Event()

    @contextmanager
    def reader(actor: User, paper_id: str, revision: int) -> Iterator[None]:
        with module.proof_lock(access.state.path):
            with access.state.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                binding = halt.authorize_reader(db, actor, paper_id, revision)
            entered.set()
            assert release.wait(15)
            with access.state.connection() as db:
                assert (
                    access._load(db, identity)["revision"]
                    == binding["workflow_revision"]
                )
            yield

    def request() -> JsonRecord:
        attempted.set()
        try:
            return access.control(
                owner, identity, action, expected_revision=cast(int, before["revision"])
            )
        finally:
            completed.set()

    halt.read_resource = reader
    with ThreadPoolExecutor(max_workers=2) as pool:
        clearing = pool.submit(halt.clear, owner, expected_revision=1)
        assert entered.wait(15)
        requesting = pool.submit(request)
        assert attempted.wait(5)
        assert not completed.wait(0.05)
        release.set()
        if action == "PAUSE":
            with pytest.raises(PaperConflictError, match="INVALID_CONTROL_STATE"):
                requesting.result(timeout=15)  # Already PAUSED, no request lost.
        else:
            assert requesting.result(timeout=15)["requested"] == action
        try:
            clearing.result(timeout=15)
        except HaltError as error:
            assert str(error) == "HALT_STALE_PROOF"
    if action != "PAUSE":
        assert access.get(owner, identity)["requested"] == action
