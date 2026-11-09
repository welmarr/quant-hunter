"""Exact opt-in generation fields after real paper/canonical/native verification."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from test_v0_paper_portfolio import record, rows, substitute_report
from test_v0_paper_workflow import SCHEMAS, build, launch

from quant_hunter.config import JsonRecord
from quant_hunter.lab import LabService
from quant_hunter.simulation import paper_engine as p
from quant_hunter.web import paper_access as workflow
from quant_hunter.web.paper_access import PaperAccess
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.signals_access import SignalError, SignalsAccess
from quant_hunter.web.state import AppState, User

Case = tuple[SignalsAccess, PaperAccess, User, str]


@pytest.fixture(scope="module")
def profile_base(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[PaperAccess, User, str]:
    paper, owner = build(tmp_path_factory.mktemp("signal-profile"))
    job = launch(
        paper,
        owner,
        bars=20,
        lookback=1,
        signal_generation={
            "profile": "QH_PAPER_SIGNAL_V1",
            "horizon_bars": 4,
            "ttl_seconds": 60,
        },
    )
    for _ in range(20):
        assert paper.process_one()
    identity = str(job["id"])
    assert paper.get(owner, identity)["status"] == "COMPLETED"
    return paper, owner, identity


@pytest.fixture
def profile_case(tmp_path: Path, profile_base: tuple[PaperAccess, User, str]) -> Case:
    original, owner, identity = profile_base
    root = tmp_path / "copy"
    shutil.copytree(original.state.path.parent, root)
    environment = record(
        json.loads(original.lab.objects.read_bytes(original.lab.environment_digest))
    )
    paper = PaperAccess(
        AppState(root / "application.sqlite3"),
        LabService(root / "research", SCHEMAS, original.lab.code_revision, environment),
        p.PaperEngine(root / "paper.sqlite3"),
    )
    quality = object.__new__(QualityAccess)
    quality.state = paper.state
    with paper.state.connection() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS resource_readers(id TEXT PRIMARY KEY,owner_id INTEGER REFERENCES users(id),created REAL)"
        )
    return (
        SignalsAccess(
            paper,
            inspection=quality.inspection,
            clock=lambda: datetime(2030, 1, 1, tzinfo=UTC),
        ),
        paper,
        owner,
        identity,
    )


def test_actual_profile_clock_horizon_expiry_and_unpromoted_risk(
    profile_case: Case,
) -> None:
    access, paper, owner, identity = profile_case
    before = paper.engine.load(identity, str(owner.id))
    view = access.paper_signals(owner, identity)
    actual = rows(view["signals"])
    assert len(actual) == 20 and view["execution_authority"] == "NONE"
    contract = record(view["signal_generation_contract"])
    assert contract["external_actionable"] is False
    config = record(
        paper.lab.get_run(str(record(view["provenance"])["experiment_id"]))[
            "configuration"
        ]
    )
    for signal in actual:
        generation = record(signal["generation"])
        assert generation == workflow.paper_signal_fields(
            config, datetime.fromisoformat(str(signal["decision_at"]))
        )
        assert signal["generated_clock"] == "SIMULATED_BAR_CLOSE"
        assert record(signal["horizon"])["status"] == "DECLARED_NOT_EVALUATED"
        assert record(signal["horizon"])["value"] == 4
        assert record(signal["horizon"])["outcome_available"] == "NOT_ASSERTED"
        assert record(signal["expiry"])["status"] == "EXPIRED_AT_QUERY"
        assert record(signal["expiry"])["boundary"] == "EXCLUSIVE"
        assert signal["actionable"] is False and signal["confidence"] is None
        assert signal["data_status"] == "STALE_AT_QUERY"
    assert record(actual[-1]["horizon"])["within_fixture"] is False
    assert not any(
        "No frozen forecast" in str(v) for v in cast(list[object], view["limitations"])
    )
    assert paper.engine.load(identity, str(owner.id)) == before


@pytest.mark.parametrize(
    "offset,status",
    [
        (-1, "NOT_YET_GENERATED_AT_QUERY"),
        (59, "WITHIN_DECLARED_TTL_NONACTIONABLE"),
        (60, "EXPIRED_AT_QUERY"),
        (61, "EXPIRED_AT_QUERY"),
    ],
)
def test_expiry_exact_boundary_is_labelled_without_actionability(
    profile_case: Case, offset: int, status: str
) -> None:
    access, _, owner, identity = profile_case
    initial = rows(access.paper_signals(owner, identity)["signals"])[1]
    decision = datetime.fromisoformat(str(initial["decision_at"]))
    access.clock = lambda: decision + timedelta(seconds=offset)
    current = rows(access.paper_signals(owner, identity, limit=1, offset=1)["signals"])[
        0
    ]
    assert record(current["expiry"])["status"] == status
    assert current["data_status"] == "NOT_AVAILABLE_AT_QUERY"
    assert current["actionable"] is False and current["confidence"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("ttl_seconds", 999),
        ("external_actionable", True),
        ("horizon_evaluation", "WIN"),
        ("clock", "LIVE"),
    ],
)
def test_coherent_generation_substitution_never_reaches_display(
    profile_case: Case, key: str, value: str | int | bool
) -> None:
    access, paper, owner, identity = profile_case

    def change(report: JsonRecord) -> None:
        generation = record(rows(report["signals"])[-1]["generation"])
        generation[key] = value

    substitute_report(paper, identity, change)
    with pytest.raises(SignalError):
        access.paper_signals(owner, identity)


def test_verified_generation_cannot_be_removed_or_unknown_keys_added(
    profile_case: Case,
) -> None:
    access, paper, owner, identity = profile_case

    def change(report: JsonRecord) -> None:
        rows(report["signals"])[-1].pop("generation")

    substitute_report(paper, identity, change)
    with pytest.raises(SignalError):
        access.paper_signals(owner, identity)
