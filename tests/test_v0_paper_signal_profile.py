"""Opt-in signal intent clocks and actual native cancellation, synthetic only."""

from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from test_v0_paper_workflow import Crash, LocalClient, build, launch

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.simulation import paper_engine as p
from quant_hunter.web import paper_access as module
from quant_hunter.web.paper_access import (
    PaperAccess,
    PaperWorkflowError,
    default_paper_config,
    paper_signal_fields,
    signal_generation_contract,
    signal_paper_config,
    validate_paper_config,
)
from quant_hunter.web.paper_routes import CreatePaper, install_paper_routes
from quant_hunter.web.state import Session, User


def record(value: JsonValue) -> JsonRecord:
    assert isinstance(value, dict)
    return value


def signals(job: JsonRecord) -> list[JsonRecord]:
    value = record(job["report"])["signals"]
    assert isinstance(value, list)
    return [record(item) for item in value]


def commands(access: PaperAccess, identity: str) -> list[p.PaperCommand]:
    with access.engine._connect() as db:
        return [
            cast(p.PaperCommand, p._decode(parse_json_document(bytes(row[0]))))
            for row in db.execute(
                "SELECT payload FROM commands WHERE account_id=? ORDER BY sequence",
                (identity,),
            )
        ]


def started(tmp_path: Path, ttl: int = 60) -> tuple[PaperAccess, User, JsonRecord]:
    access, user = build(tmp_path)
    profile: JsonRecord = {
        "profile": "QH_PAPER_SIGNAL_V1",
        "horizon_bars": 4,
        "ttl_seconds": ttl,
    }
    return access, user, launch(access, user, bars=20, signal_generation=profile)


def first_order(access: PaperAccess, owner: User, job: JsonRecord) -> JsonRecord:
    identity = cast(str, job["id"])
    for _ in range(10):
        assert access.process_one()
        current = access.get(owner, identity)
        if access.engine.load(identity, str(owner.id)).reservations:
            return current
    raise AssertionError("Expected the fixed synthetic cycle's first long intent")


def test_legacy_input_and_fixture_bytes_equal_preserved_preprofile_producer() -> None:
    config = default_paper_config()
    payload = module._instrument_payload("EQUITY")
    instrument: JsonRecord = {
        "digest": "sha256:" + "1" * 64,
        "record": {
            "instrument_id": "INSTRUMENT-SYNTHETIC-ORACLE",
            "instrument": payload["instrument"],
        },
    }
    frozen, raw = module._prepare(config, instrument)
    # Recorded against the preserved pre-change producer, not computed by this test.
    assert hashlib.sha256(canonicalize_json(config)).hexdigest() == (
        "779c89fccece8ea912a83ace48a5ee996f9cfb617e9a780e1fd3b5a815787c27"
    )
    assert hashlib.sha256(canonicalize_json(frozen)).hexdigest() == (
        "cd1eec16e381ad3cec0385140c78b208bb6f573f402e4032c9f41a8d65ff0db2"
    )
    assert hashlib.sha256(raw).hexdigest() == (
        "01345eeedb04bf8627d7d6d5de72223a8ee2d488493a777a696694d6ad510628"
    )
    assert signal_generation_contract(config) is None
    assert paper_signal_fields(frozen, module.START) is None
    assert (
        CreatePaper.model_validate({"configuration": config}).configuration.model_dump()
        == config
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "QH_PAPER_SIGNAL_V1",
        {},
        {"profile": "OTHER", "horizon_bars": 4, "ttl_seconds": 60},
        {"profile": "QH_PAPER_SIGNAL_V1", "horizon_bars": True, "ttl_seconds": 60},
        {"profile": "QH_PAPER_SIGNAL_V1", "horizon_bars": 0, "ttl_seconds": 1},
        {"profile": "QH_PAPER_SIGNAL_V1", "horizon_bars": 101, "ttl_seconds": 60},
        {"profile": "QH_PAPER_SIGNAL_V1", "horizon_bars": 4, "ttl_seconds": True},
        {"profile": "QH_PAPER_SIGNAL_V1", "horizon_bars": 4, "ttl_seconds": 0},
        {"profile": "QH_PAPER_SIGNAL_V1", "horizon_bars": 100, "ttl_seconds": 3601},
        {"profile": "QH_PAPER_SIGNAL_V1", "horizon_bars": 1, "ttl_seconds": 61},
        {
            "profile": "QH_PAPER_SIGNAL_V1",
            "horizon_bars": 4,
            "ttl_seconds": 60,
            "live": True,
        },
    ],
)
def test_closed_opt_in_profile_refuses_ambiguous_or_unbounded_values(
    value: JsonValue,
) -> None:
    with pytest.raises(PaperWorkflowError, match="SIGNAL_GENERATION_CONFIGURATION"):
        validate_paper_config({**default_paper_config(), "signal_generation": value})


def test_profile_frozen_in_strategy_and_experiment_before_any_decision(
    tmp_path: Path,
) -> None:
    access, owner, job = started(tmp_path)
    identity = cast(str, job["id"])
    run = access.lab.get_run(cast(str, job["experiment_id"]))
    config = record(run["configuration"])
    contract = record(config["signal_generation_contract"])
    assert contract == signal_generation_contract(config)
    assert run["lifecycle_status"] == "RUNNING" and run["variants_attempted"] == 0
    assert signals(job) == [] and commands(access, identity) == []
    binding = record(run["bindings"])
    strategy = access.lab.registry.verify_object(cast(str, binding["strategy_id"]))[
        -1
    ].record
    assert strategy["parameters"] == binding["configuration_digest"]
    assert "QH_PAPER_SIGNAL_V1" in cast(str, strategy["mathematical_definition"])
    assert record(job["report"])["signal_generation_contract"] == contract
    assert access.process_one()
    signal = signals(access.get(owner, identity))[0]
    fields = record(signal["generation"])
    assert fields["horizon_end_at"] == "2024-01-02T14:34:59Z"
    assert fields["expires_at"] == "2024-01-02T14:31:59Z"
    assert fields["clock"] == "SIMULATED_BAR_CLOSE"
    assert fields["horizon_evaluation"] == "NOT_EVALUATED"
    assert fields["external_actionable"] is False and fields["confidence"] is None


@pytest.mark.parametrize("ttl", [1, 2, 60, 240])
def test_exclusive_expiry_and_supersession_use_actual_native_cancel(
    tmp_path: Path, ttl: int
) -> None:
    access, owner, job = started(tmp_path, ttl)
    current = first_order(access, owner, job)
    identity = cast(str, job["id"])
    before = access.engine.load(identity, str(owner.id))
    reservation = before.reservations[0]
    intent = signals(current)[-1]
    decision = module._at(intent["decision_at"])
    assert intent["order_id"] == reservation.order_id
    assert before.book.fills == ()
    assert access.process_one()
    after = access.engine.load(identity, str(owner.id))
    observed = [
        command
        for command in commands(access, identity)
        if isinstance(command, p.Match | p.Cancel)
        and command.order_id == reservation.order_id
    ]
    cancels = [command for command in observed if isinstance(command, p.Cancel)]
    matches = [command for command in observed if isinstance(command, p.Match)]
    assert [command.action for command in cancels] == ["REQUEST", "CONFIRM"]
    if ttl == 1:
        assert matches == [] and after.book.fills == ()
        assert cancels[0].at == decision + timedelta(seconds=1)
        assert ".signalexpiry." in cancels[0].command_id
    else:
        assert len(matches) == 1 and observed[0] == matches[0]
        assert matches[0].at == decision + timedelta(seconds=1)
        assert after.book.fills[0].quantity == Decimal(4)
        assert after.book.positions[0].quantity == Decimal(4)
        assert cancels[0].at == decision + timedelta(seconds=60)
        reason = ".signalexpiry." if ttl <= 60 else ".signalsuperseded."
        assert reason in cancels[0].command_id
        assert after.book.fills[0].commission == Decimal(1)
    assert all(res.order_id != reservation.order_id for res in after.reservations)
    order = next(
        order for order in after.book.orders if order.order_id == reservation.order_id
    )
    assert order.status == "CANCELED"
    assert access.engine.load(identity, str(owner.id)) == after
    # A second read does not cancel, fill, allocate or replay another attempt.
    access.get(owner, identity)
    assert access.engine.load(identity, str(owner.id)) == after


def test_full_replay_counts_one_attempt_and_last_horizon_remains_unevaluated(
    tmp_path: Path,
) -> None:
    access, owner, job = started(tmp_path, 240)
    for _ in range(20):
        assert access.process_one()
    final = access.get(owner, cast(str, job["id"]))
    assert final["status"] == "COMPLETED"
    fields = record(signals(final)[-1]["generation"])
    assert fields["horizon_within_fixture"] is False
    assert fields["horizon_evaluation"] == "NOT_EVALUATED"
    run = access.lab.get_run(cast(str, job["experiment_id"]))
    assert (
        run["variants_attempted"] == 1 and run["evaluation_outcome"] == "INCONCLUSIVE"
    )
    assert access.process_one() is False


@pytest.mark.parametrize("attack", ["expiry", "missing", "report", "confidence"])
def test_coherently_rehashed_generation_claims_are_rejected(
    tmp_path: Path, attack: str
) -> None:
    access, owner, job = started(tmp_path)
    assert access.process_one()
    identity = cast(str, job["id"])
    current = access.get(owner, identity)
    report = record(parse_json_document(canonicalize_json(current["report"])))
    signal = record(cast(list[JsonValue], report["signals"])[0])
    if attack == "expiry":
        record(signal["generation"])["expires_at"] = "2024-01-02T15:00:00Z"
    elif attack == "confidence":
        record(signal["generation"])["confidence"] = "0.75"
    elif attack == "missing":
        del signal["generation"]
    else:
        record(report["signal_generation_contract"])["ttl_seconds"] = 2
    digest = access.lab.objects.publish(canonicalize_json(report)).digest
    with access.state.connection() as db:
        head = access._load(db, identity, owner.id)
        access._save(db, head, {"report_digest": digest}, "SYNTHETIC_REHASH_ATTACK")
    with pytest.raises(PaperWorkflowError, match="SIGNAL_REPORT_BINDING"):
        access.get(owner, identity)


@pytest.mark.parametrize("prospective", [False, True])
def test_old_producer_inspection_retains_profile_and_legacy_remains_unknown(
    tmp_path: Path, prospective: bool
) -> None:
    if prospective:
        access, owner, job = started(tmp_path)
    else:
        access, owner = build(tmp_path)
        job = launch(access, owner, bars=20)
    assert access.process_one()
    identity = cast(str, job["id"])
    before = access.get(owner, identity)
    assert ("signal_generation_contract" in record(before["report"])) == prospective
    assert all(("generation" in item) == prospective for item in signals(before))
    access.lab.code_revision = "0" * 40
    access.lab.environment_digest = access.lab.objects.publish(
        b'{"new_environment":true}'
    ).digest
    assert access.get(owner, identity) == before


def test_route_opt_in_is_closed_and_absence_not_retrofitted(tmp_path: Path) -> None:
    access, _owner = build(tmp_path)
    app = FastAPI()
    install_paper_routes(
        app,
        lambda request, mutation=False, owner=False: Session(
            access.state.user(1), "fixture"
        ),
        access,
        inspection=lambda user: nullcontext(),
    )
    with LocalClient(app) as client:
        defaults = client.get("/api/paper/configuration").json()
        assert "signal_generation" not in defaults["defaults"]["EQUITY"]
        assert defaults["opt_in_signal_defaults"]["EQUITY"] == signal_paper_config()
        first = client.post(
            "/api/paper/sessions", json={"configuration": default_paper_config()}
        )
        assert first.status_code == 200
        assert "signal_generation" not in first.json()["configuration"]
        second = client.post(
            "/api/paper/sessions", json={"configuration": signal_paper_config()}
        )
        assert second.status_code == 200
        assert second.json()["configuration"] == signal_paper_config()
        for profile in (
            None,
            {"profile": "QH_PAPER_SIGNAL_V1", "horizon_bars": 1, "ttl_seconds": 61},
        ):
            refused = client.post(
                "/api/paper/sessions",
                json={
                    "configuration": {
                        **default_paper_config(),
                        "signal_generation": profile,
                    }
                },
            )
            assert refused.status_code == 400
    with access.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM paper_jobs").fetchone()[0] == 2


def test_generation_clock_and_contract_refuse_unbound_fields() -> None:
    config = signal_paper_config()
    with pytest.raises(PaperWorkflowError, match="GENERATION_BINDING"):
        paper_signal_fields(config, datetime(2024, 1, 2, tzinfo=UTC))
    frozen = {
        **config,
        "signal_generation_contract": signal_generation_contract(config),
        "dataset_end": "2024-01-02T15:00:00Z",
    }
    with pytest.raises(PaperWorkflowError, match="DECISION_CLOCK"):
        paper_signal_fields(frozen, datetime(2024, 1, 2))
    with pytest.raises(PaperWorkflowError, match="WITHOUT_PROFILE"):
        paper_signal_fields({"signal_generation_contract": {}}, module.START)


@pytest.mark.parametrize("committed", [2, 3])
def test_expiry_cancel_crash_is_retained_without_retrying_or_filling(
    tmp_path: Path, committed: int
) -> None:
    access, owner, job = started(tmp_path, 1)
    prior = first_order(access, owner, job)
    identity = cast(str, job["id"])
    count = 0

    def crash(phase: str) -> None:
        nonlocal count
        if phase == "AFTER_ENGINE_COMMAND":
            count += 1
            if count == committed:
                raise Crash

    access.fault = crash
    with pytest.raises(Crash):
        access.process_one()
    access.fault = lambda phase: None
    native = access.engine.load(identity, str(owner.id))
    assert native.book.fills == ()
    access.recover()
    current = access.get(owner, identity)
    assert current["status"] == "AMBIGUOUS"
    assert current["cursor"] == prior["cursor"]
    assert signals(current) == signals(prior)
    assert access.process_one() is False
    assert access.engine.load(identity, str(owner.id)) == native


def test_rejected_native_cancel_cannot_fall_through_to_expired_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, owner, job = started(tmp_path, 1)
    prior = first_order(access, owner, job)
    identity = cast(str, job["id"])
    process = access.engine.process

    def reject_cancel(
        account_id: str,
        owner_id: str,
        command: p.PaperCommand,
        expected_revision: int,
    ) -> p.PaperSnapshot:
        if isinstance(command, p.Cancel):
            command = replace(command, action="INVALID_SYNTHETIC_FAULT")
        return process(account_id, owner_id, command, expected_revision)

    monkeypatch.setattr(access.engine, "process", reject_cancel)
    assert access.process_one()
    current = access.get(owner, identity)
    assert current["status"] == "FAILED"
    assert current["cursor"] == prior["cursor"]
    native = access.engine.load(identity, str(owner.id))
    assert native.book.fills == () and native.reservations
    assert native.outcomes[-1].status == "REJECTED"
    assert not any(
        isinstance(command, p.Match) for command in commands(access, identity)
    )
    run = access.lab.get_run(cast(str, current["experiment_id"]))
    assert run["variants_attempted"] == 1 and run["evaluation_outcome"] == "FAILED"
