"""Actual retained paper/Item8 journals; these are software, not trading, tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from typing import cast

import pytest
from fastapi import FastAPI, HTTPException, Request
from test_v0_paper_portfolio import (
    baseline,
    record,
    rows,
    substitute_report,
)
from test_v0_paper_portfolio import (
    case as portfolio_case,
)
from test_v0_paper_workflow import LocalClient, control, launch

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.web import signals_access as module
from quant_hunter.web.paper_access import PaperAccess, default_paper_config
from quant_hunter.web.paper_portfolio import PaperPortfolio
from quant_hunter.web.signals_access import (
    SignalChangedError,
    SignalError,
    SignalsAccess,
)
from quant_hunter.web.signals_routes import install_signals_routes
from quant_hunter.web.state import AccessError, ResourceBusyError, Session, User

# Imported fixtures preserve exact executed-source archives and real native
# SQLite histories. No verifier is replaced by a synthetic positive response.
assert baseline and portfolio_case
Case = tuple[SignalsAccess, PaperAccess, User, str]
NOW = datetime(2030, 1, 1, tzinfo=UTC)


@pytest.fixture
def case(portfolio_case: tuple[PaperPortfolio, PaperAccess, User, str]) -> Case:
    portfolio, paper, owner, identity = portfolio_case
    return (
        SignalsAccess(paper, inspection=portfolio.inspection, clock=lambda: NOW),
        paper,
        owner,
        identity,
    )


def test_actual_decisions_formula_provenance_and_no_new_authority(case: Case) -> None:
    access, paper, owner, identity = case
    before = paper.get(owner, identity)
    run_before = paper.lab.get_run(cast(str, before["experiment_id"]))
    native_before = paper.engine.load(identity, str(owner.id))
    result = access.paper_signals(owner, identity)
    signals = rows(result["signals"])
    assert result["total"] == len(signals) == 20
    assert result["workflow_status"] == "COMPLETED"
    assert result["actionable"] is False and result["execution_authority"] == "NONE"
    assert {s["direction"] for s in signals} == {"LONG", "FLAT"}
    assert signals[0]["explanation"] == "WARMUP"
    assert signals[0]["target_quantity"] == "0"
    assert signals[1]["direction"] == "LONG"
    assert signals[1]["target_quantity"] == "10"
    assert signals[1]["decision_at"] == "2024-01-02T14:31:59Z"
    assert record(signals[1]["source_values"]) == {
        "current_bid": "100.39",
        "comparison_bid": "100.19",
    }
    assert record(signals[1]["risk"])["status"] == "APPLIED"
    for index, signal in enumerate(signals):
        assert signal["reference"] == f"{identity}:BAR:{index}"
        assert signal["generated_clock"] == "SIMULATED_DECISION_CLOCK"
        assert signal["data_status"] == "STALE_AT_QUERY"
        assert signal["current_status"] == "SESSION_ENDED"
        assert signal["actionable"] is False and signal["confidence"] is None
        assert signal["horizon"] == {"status": "UNKNOWN_NOT_FROZEN", "value": None}
        assert signal["expiry"] == {"status": "UNKNOWN_NOT_FROZEN", "at": None}
        assert signal["last_required_available_at"] == signal["decision_at"]
        assert module._time(signal["retained_at"]) > module._time(signal["decision_at"])
    provenance = record(result["provenance"])
    bindings = record(run_before["bindings"])
    for key in (
        "strategy_id",
        "source_id",
        "dataset_id",
        "code_revision",
        "configuration_digest",
    ):
        assert provenance[key] == bindings[key]
    assert provenance["experiment_id"] == run_before["experiment_id"]
    assert provenance["model_ids"] == []
    assert "NOT_FITTED" in cast(str, provenance["model_identity_status"])
    assert paper.lab.get_run(cast(str, before["experiment_id"])) == run_before
    assert paper.engine.load(identity, str(owner.id)) == native_before
    assert paper.get(owner, identity) == before


def test_paging_and_empty_created_session(case: Case) -> None:
    access, paper, owner, identity = case
    result = access.paper_signals(owner, identity, limit=2, offset=2)
    assert [s["bar_index"] for s in rows(result["signals"])] == [2, 3]
    assert result["total"] == 20
    assert access.paper_signals(owner, identity, offset=99)["signals"] == []
    created = paper.create(owner, default_paper_config("FX_SPOT"))
    empty = access.paper_signals(owner, cast(str, created["id"]))
    assert empty["total"] == 0 and empty["signals"] == []
    assert empty["availability"] == "NO_RECORDED_DECISIONS"
    listing = access.sessions(owner, limit=1)
    assert listing["total"] == 2 and len(rows(listing["sessions"])) == 1
    assert len(rows(access.sessions(owner, limit=1, offset=1)["sessions"])) == 1
    assert access.sessions(owner, offset=31)["sessions"] == []


@pytest.mark.parametrize(
    "limit,offset", [(0, 0), (26, 0), (True, 0), (1, -1), (1, 100), (1, True)]
)
def test_page_guards(case: Case, limit: int, offset: int) -> None:
    access, _, owner, identity = case
    with pytest.raises(SignalError, match="PAGE_BOUND"):
        access.paper_signals(owner, identity, limit=limit, offset=offset)


def test_ownership_and_current_roles(case: Case) -> None:
    access, paper, owner, identity = case
    other = paper.state.create_user(
        "other", "synthetic other passphrase", "owner", bootstrap=False
    )
    with pytest.raises(AccessError):
        access.paper_signals(other, identity)
    assert access.sessions(other)["sessions"] == []
    with pytest.raises(AccessError):
        access.sessions(replace(owner, username="changed"))
    with paper.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (owner.id,))
    with pytest.raises(AccessError):
        access.paper_signals(owner, identity)
    reader = replace(owner, role="reader")
    assert access.paper_signals(reader, identity)["total"] == 20


def test_one_reservation_precedes_all_heavy_reads_and_is_released(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, paper, owner, identity = case
    original = access.portfolio._get
    counts: list[int] = []

    def checked(user: User, target: str) -> JsonRecord:
        with paper.state.connection() as db:
            counts.append(
                db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0]
            )
        return original(user, target)

    monkeypatch.setattr(access.portfolio, "_get", checked)
    assert access.paper_signals(owner, identity)["total"] == 20
    with access.inspection(owner):
        assert access.paper_signals(owner, identity)["total"] == 20
        with access.inspection(owner):
            with pytest.raises(ResourceBusyError):
                access.paper_signals(owner, identity)
    assert counts == [1, 2]
    with paper.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0] == 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("current_bid", "900"),
        ("target_quantity", "99"),
        ("decision_at", "2031-01-01T00:00:00Z"),
        ("index", True),
        ("explanation", "<script>secret</script>"),
        ("horizon", 5),
    ],
)
def test_coherently_rehashed_retained_signal_refused(
    case: Case, key: str, value: JsonValue
) -> None:
    access, paper, owner, identity = case

    def mutate(report: JsonRecord) -> None:
        rows(report["signals"])[1][key] = value

    substitute_report(paper, identity, mutate)
    with pytest.raises(SignalError):
        access.paper_signals(owner, identity)
    with paper.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0] == 0


def test_actual_active_decisions_then_withdrawal(case: Case) -> None:
    access, paper, owner, _ = case
    job = launch(paper, owner, bars=20, lookback=1)
    identity = cast(str, job["id"])
    for _ in range(3):
        assert paper.process_one()
    result = access.paper_signals(owner, identity)
    assert [s["current_status"] for s in rows(result["signals"])] == [
        "SUPERSEDED_BY_LATER_DECISION",
        "SUPERSEDED_BY_LATER_DECISION",
        "RETAINED_NOT_ACTIONABLE",
    ]
    control(paper, owner, job, "KILL")
    assert all(
        s["current_status"] == "WITHDRAWN_BY_SESSION_CONTROL"
        for s in rows(access.paper_signals(owner, identity)["signals"])
    )


def test_clock_not_available_and_invalid_clock(case: Case) -> None:
    access, _, owner, identity = case
    access.clock = lambda: datetime(2020, 1, 1, tzinfo=UTC)
    assert {
        s["data_status"] for s in rows(access.paper_signals(owner, identity)["signals"])
    } == {"NOT_AVAILABLE_AT_QUERY"}
    access.clock = lambda: datetime(2020, 1, 1)
    with pytest.raises(SignalError, match="CLOCK"):
        access.paper_signals(owner, identity)


def test_head_change_is_explicit_retry_and_failure_sanitized(
    case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    access, _, owner, identity = case
    actual = access.portfolio._history

    def changed(
        user: User, target: str
    ) -> tuple[JsonRecord, str, list[tuple[JsonRecord, str]]]:
        head, digest, events = actual(user, target)
        head["revision"] = cast(int, head["revision"]) + 1
        return head, digest, events

    # _get also uses _history, so switch only after its successful full replay.
    get = access.portfolio._get

    def verified(user: User, target: str) -> JsonRecord:
        value = get(user, target)
        monkeypatch.setattr(access.portfolio, "_history", changed)
        return value

    monkeypatch.setattr(access.portfolio, "_get", verified)
    with pytest.raises(SignalChangedError):
        access.paper_signals(owner, identity)

    def failure(user: User, target: str) -> JsonRecord:
        raise RuntimeError("synthetic-private-marker")

    monkeypatch.setattr(access.portfolio, "_get", failure)
    with pytest.raises(SignalError, match=r"^SIGNAL_EVIDENCE_UNAVAILABLE$"):
        access.paper_signals(owner, identity)


def make_app(access: SignalsAccess | None, user: User) -> LocalClient:
    app = FastAPI()

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        if request.headers.get("authorization") != "synthetic-local-session":
            raise HTTPException(401, "Sign in")
        return Session(user, "synthetic-csrf")

    install_signals_routes(app, authenticated, access)
    return LocalClient(app)


def test_routes_private_readonly_and_page_bounds(case: Case) -> None:
    access, _, owner, identity = case
    with make_app(access, owner) as client:
        assert client.get("/api/signals/paper/sessions").status_code == 401
        client.headers["authorization"] = "synthetic-local-session"
        assert client.get("/api/signals/paper/sessions").status_code == 200
        assert (
            client.get(f"/api/signals/paper/{identity}?limit=2").json()["total"] == 20
        )
        assert client.get(f"/api/signals/paper/{identity}?limit=26").status_code == 422
        assert client.post(f"/api/signals/paper/{identity}").status_code == 405
        assert client.get("/api/signals/paper/missing").status_code == 403
        assert client.get("/api/signals/research/jobs").json()["jobs"] == []
        with access.inspection(owner), access.inspection(owner):
            busy = client.get(f"/api/signals/paper/{identity}")
            assert busy.status_code == 503 and busy.headers["Retry-After"] == "3"


@pytest.mark.parametrize(
    "error,status",
    [
        (SignalChangedError("secret"), 409),
        (SignalError("secret"), 409),
        (RuntimeError("secret"), 503),
    ],
)
def test_route_failure_is_sanitized(
    case: Case, monkeypatch: pytest.MonkeyPatch, error: Exception, status: int
) -> None:
    access, _, owner, identity = case

    def failure(*args: object, **kwargs: object) -> JsonRecord:
        raise error

    monkeypatch.setattr(access, "paper_signals", failure)
    with make_app(access, owner) as client:
        client.headers["authorization"] = "synthetic-local-session"
        response = client.get(f"/api/signals/paper/{identity}")
        assert response.status_code == status and "secret" not in response.text
    with make_app(None, owner) as client:
        client.headers["authorization"] = "synthetic-local-session"
        assert client.get("/api/signals/paper/sessions").status_code == 503


@pytest.mark.parametrize(
    "value", [None, 3, "bad", "2024-01-01", "2024-01-01T12:00:00+01:00", "z" * 41]
)
def test_time_admission_rejects_unknown_or_naive(value: JsonValue) -> None:
    with pytest.raises(SignalError, match="TIME"):
        module._time(value)


def test_shape_and_response_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SignalError, match="RECORD_SHAPE"):
        module._record(None)
    with pytest.raises(SignalError, match="LIST_BOUND"):
        module._rows([{}] * 101)
    with pytest.raises(SignalError, match="LIST_BOUND"):
        module._rows({})
    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 10)
    with pytest.raises(SignalError, match="RESPONSE_BOUND"):
        module._bounded({"bounded": "content"})


def test_signal_presentation_unknown_state_and_timing(case: Case) -> None:
    """Status-only oracle over real retained inputs, without changing their journals."""
    access, paper, owner, identity = case
    verified = access.portfolio.get(owner, identity)
    with paper.state.connection() as db:
        head = paper._load(db, identity)
    run, fixture = paper._binding(head)
    config = record(run["configuration"])
    bars = rows(fixture["bars"])
    report = paper._object(cast(str, head["report_digest"]))
    snapshot = record(report["snapshot"])
    signals = rows(report["signals"])
    admissions = access._admissions(owner, identity, verified)
    retained: JsonRecord = {
        "retained_at": bars[1]["close_at"],
        "first_report_digest": head["report_digest"],
        "first_workflow_revision": head["revision"],
    }
    now = module._time(bars[1]["close_at"])
    result = access._signal(
        1, signals[1], bars, config, head, snapshot, admissions, retained, now, verified
    )
    assert result["data_status"] == "SYNTHETIC_RECEIPTS_WITHIN_FROZEN_QUOTE_AGE"
    assert result["actionable"] is False
    result = access._signal(
        1, signals[1], bars, config, head, None, {}, retained, now, verified
    )
    assert result["current_status"] == "UNVERIFIED_CURRENT_STATE"
    assert record(result["risk"])["status"] == "UNAVAILABLE"
    for changed in (
        {**signals[1], "order_id": 4},
        {**signals[1], "order_id": "unrelated"},
        {**signals[1], "admission_status": "fake"},
    ):
        with pytest.raises(SignalError, match="ORDER_BINDING"):
            access._signal(
                1,
                changed,
                bars,
                config,
                head,
                snapshot,
                admissions,
                retained,
                now,
                verified,
            )
    with pytest.raises(SignalError, match="ORDER_BINDING"):
        access._signal(
            1,
            {**signals[1], "order_id": None},
            bars,
            config,
            head,
            snapshot,
            admissions,
            retained,
            now,
            verified,
        )
    with pytest.raises(SignalError, match="FIELDS"):
        access._signal(
            0,
            {**signals[0], "horizon": 1},
            bars,
            config,
            head,
            snapshot,
            admissions,
            retained,
            now,
            verified,
        )


def test_native_admission_head_and_formula_rejections(case: Case) -> None:
    access, paper, owner, identity = case
    verified = access.portfolio.get(owner, identity)
    with paper.state.connection() as db:
        head = paper._load(db, identity)
    run, fixture = paper._binding(head)
    config = record(run["configuration"])
    bars = rows(fixture["bars"])
    report = paper._object(cast(str, head["report_digest"]))
    signals = rows(report["signals"])
    snapshot = record(report["snapshot"])
    admissions = access._admissions(owner, identity, verified)
    retained: JsonRecord = {"retained_at": bars[1]["close_at"]}
    for changed in ({**signals[1], "current_bid": "99"}, {**signals[1], "index": True}):
        with pytest.raises(SignalError, match="FORMULA_OR_AVAILABILITY"):
            access._signal(
                1,
                changed,
                bars,
                config,
                head,
                snapshot,
                admissions,
                retained,
                NOW,
                verified,
            )
    with pytest.raises(SignalChangedError, match="NATIVE_HEAD_CHANGED"):
        access._admissions(owner, identity, {**verified, "native_head_revision": -1})
    with pytest.raises(SignalError, match="NATIVE_BOUND"):
        access._admissions(owner, "missing", verified)


@pytest.mark.parametrize("overflow", ["count", "individual", "aggregate"])
def test_research_scan_caps_precede_json_filter(
    case: Case,
    monkeypatch: pytest.MonkeyPatch,
    overflow: str,
) -> None:
    access, paper, owner, _ = case
    count = 10_001 if overflow == "count" else 1
    payload = '{"kind":"CRP_STUDY"}'
    if overflow == "individual":
        payload = " " * 16_385
    if overflow == "aggregate":
        monkeypatch.setattr(module, "MAX_TOTAL_CONFIG_BYTES", 10)
    with paper.state.connection() as db:
        db.executemany(
            "INSERT INTO jobs VALUES(?,?,'FAILED',?,NULL,NULL)",
            [(f"nonmatching-{i}", owner.id, payload) for i in range(count)],
        )
    queries: list[str] = []
    original = paper.state.connection

    @contextmanager
    def traced() -> Iterator[Connection]:
        with original() as db:
            db.set_trace_callback(queries.append)
            yield db

    monkeypatch.setattr(paper.state, "connection", traced)
    with pytest.raises(SignalError, match="JOB_SCAN_BOUND"):
        access.research_jobs(owner)
    assert any("LIMIT 10001" in query for query in queries)
    assert not any("json_extract" in query for query in queries)


def test_nonpattern_job_is_not_a_research_observation(case: Case) -> None:
    access, paper, owner, _ = case
    job = paper.state.enqueue(owner, {"kind": "CRP_STUDY"})
    with pytest.raises(AccessError):
        access.research(owner, job.id)
    assert access.research_jobs(owner)["jobs"] == []


def test_actual_pattern_observations_keep_research_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import test_v0_pattern_workflows as pattern_tests
    from test_v0_paper_workflow import SCHEMAS

    from quant_hunter.simulation.paper_engine import PaperEngine

    monkeypatch.setattr(pattern_tests, "SCHEMAS", SCHEMAS)
    h = pattern_tests.make(tmp_path / "research-observations")
    # Reopen the same canonical store with a real current paper source archive.
    # The Pattern helper's minimal environment deliberately contains none.
    import base64

    from quant_hunter.config import canonicalize_json
    from quant_hunter.lab import LabService
    from quant_hunter.web import paper_access as workflow

    package = Path(workflow.__file__).resolve().parents[1]
    archive = h.access.lab.objects.publish(
        canonicalize_json(
            {
                "encoding": "base64-exact-bytes",
                "files": {
                    "src/quant_hunter/" + name: base64.b64encode(
                        (package / name).read_bytes()
                    ).decode("ascii")
                    for name in workflow.SOURCE_FILES
                },
            }
        )
    )
    paper_lab = LabService(
        tmp_path / "research-observations",
        SCHEMAS,
        h.access.lab.code_revision,
        {"source_snapshot_digest": archive.digest},
    )
    paper = PaperAccess(
        h.access.state,
        paper_lab,
        PaperEngine(h.access.state.path.parent / "paper.sqlite3"),
    )
    access = SignalsAccess(
        paper,
        inspection=h.access.quality.inspection,
        patterns=h.access,
        clock=lambda: NOW,
    )
    owner = h.users["owner"]
    prepared = h.prepare("PAT-05")
    job = h.access.enqueue(owner, prepared["prepared_id"])
    assert access.research(owner, job.id)["observations"] is None
    claimed = h.access.state.claim()
    assert claimed is not None and claimed.id == job.id
    h.access.execute_job(claimed)
    before = h.access.job(owner, job.id)
    assert record(before["job"])["status"] == "SUCCEEDED"
    result = access.research(owner, job.id)
    assert result["classification"] == "RESEARCH_OBSERVATIONS_NOT_TRADING_SIGNALS"
    assert result["actionable"] is False and result["confidence"] is None
    assert record(result["observations"])["method_id"] == "PAT-05"
    assert result["model_recipe"] == before["model_recipe"]
    assert result["model_fit"] == before["model_fit"]
    assert result["result_digest"] == record(before["run"])["result_digest"]
    assert h.access.job(owner, job.id) == before
    assert rows(access.research_jobs(owner)["jobs"])[0]["id"] == job.id
    assert access.research_jobs(owner, offset=1)["jobs"] == []
    with pytest.raises(AccessError):
        access.research(h.users["other"], job.id)
    assert access.research_jobs(h.users["other"])["jobs"] == []
    with access.inspection(owner), access.inspection(owner):
        with pytest.raises(ResourceBusyError):
            access.research(owner, job.id)
    with make_app(access, owner) as client:
        client.headers["authorization"] = "synthetic-local-session"
        assert client.get(f"/api/signals/research/jobs/{job.id}").status_code == 200
        assert client.get("/api/signals/research/jobs?limit=0").status_code == 422
    access.patterns = None
    with pytest.raises(SignalError, match="PATTERN_SERVICE_UNAVAILABLE"):
        access.research(owner, job.id)
    access.patterns = h.access
    with monkeypatch.context() as faults:

        def failed_read(*args: object, **kwargs: object) -> JsonRecord:
            raise RuntimeError("synthetic-private-marker")

        faults.setattr(h.access, "_job", failed_read)
        with pytest.raises(SignalError, match=r"^RESEARCH_OBSERVATION_UNAVAILABLE$"):
            access.research(owner, job.id)
    with h.access.state.connection() as db:
        db.execute(
            "UPDATE pattern_prepared SET owner_id=? WHERE id=?",
            (h.users["other"].id, prepared["prepared_id"]),
        )
    with pytest.raises(AccessError):
        access.research(owner, job.id)
