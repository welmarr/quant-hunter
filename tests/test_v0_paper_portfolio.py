"""Real owned paper journals; no network, synthetic cash is not empirical evidence."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI, HTTPException, Request
from test_v0_paper_workflow import SCHEMAS, LocalClient, build, control, launch

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.lab import LabService
from quant_hunter.simulation import accounting as a
from quant_hunter.simulation import paper_engine as p
from quant_hunter.web import paper_access as workflow
from quant_hunter.web import paper_portfolio as module
from quant_hunter.web.paper_access import PaperAccess, default_paper_config
from quant_hunter.web.paper_portfolio import PaperPortfolio, PortfolioError
from quant_hunter.web.paper_portfolio_routes import install_paper_portfolio_routes
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.state import AccessError, AppState, Session, User


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> tuple[PaperAccess, User, str]:
    access, owner = build(tmp_path_factory.mktemp("portfolio-base"))
    job = launch(access, owner, bars=20, lookback=1)
    for _ in range(20):
        assert access.process_one()
    assert access.get(owner, cast(str, job["id"]))["status"] == "COMPLETED"
    return access, owner, cast(str, job["id"])


@pytest.fixture
def case(
    tmp_path: Path, baseline: tuple[PaperAccess, User, str]
) -> tuple[PaperPortfolio, PaperAccess, User, str]:
    base, owner, identity = baseline
    root = tmp_path / "copied"
    shutil.copytree(base.state.path.parent, root)
    environment = workflow._record(
        json.loads(base.lab.objects.read_bytes(base.lab.environment_digest))
    )
    lab = LabService(
        root / "research",
        SCHEMAS,
        base.lab.code_revision,
        environment,
    )
    access = PaperAccess(
        AppState(root / "application.sqlite3"),
        lab,
        p.PaperEngine(root / "paper.sqlite3"),
    )
    # The exact production reader context only depends on AppState. No quality
    # dataset/import fixture or fabricated scientific authority is needed here.
    quality = object.__new__(QualityAccess)
    quality.state = access.state
    with access.state.connection() as db:
        db.execute(
            "CREATE TABLE resource_readers(id TEXT PRIMARY KEY,owner_id INTEGER REFERENCES users(id),created REAL)"
        )
    return (
        PaperPortfolio(access, inspection=quality.inspection),
        access,
        owner,
        identity,
    )


def record(value: JsonValue) -> JsonRecord:
    assert isinstance(value, dict)
    return value


def rows(value: JsonValue) -> list[JsonRecord]:
    assert isinstance(value, list)
    return [record(v) for v in value]


def rewrite_events(access: PaperAccess, identity: str, mutate: object) -> None:
    """Coherently rehash hostile workflow bytes so graph checks do actual work."""
    from collections.abc import Callable

    action = cast(Callable[[JsonRecord], None], mutate)
    with access.state.connection() as db:
        db.execute("DROP TRIGGER paper_events_update") if db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='paper_events_update'"
        ).fetchone() else None
        for trigger in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='paper_events'"
        ).fetchall():
            db.execute('DROP TRIGGER "' + str(trigger[0]).replace('"', '""') + '"')
        previous = ""
        last: JsonRecord = {}
        raw = b""
        for item in db.execute(
            "SELECT sequence,payload FROM paper_events WHERE job_id=? ORDER BY sequence",
            (identity,),
        ).fetchall():
            last = workflow._decode(bytes(item[1]))
            action(last)
            raw = canonicalize_json(last)
            digest = workflow._hash(previous.encode() + raw)
            db.execute(
                "UPDATE paper_events SET payload=?,previous=?,digest=? WHERE job_id=? AND sequence=?",
                (raw, previous, digest, identity, item[0]),
            )
            previous = digest
        db.execute(
            "UPDATE paper_jobs SET payload=?,digest=?,revision=?,status=?,experiment_id=? WHERE id=?",
            (
                raw,
                previous,
                last["revision"],
                last["status"],
                last["experiment_id"],
                identity,
            ),
        )


def substitute_report(access: PaperAccess, identity: str, mutate: object) -> None:
    from collections.abc import Callable

    action = cast(Callable[[JsonRecord], None], mutate)
    with access.state.connection() as db:
        head = access._load(db, identity)
    old = cast(str, head["report_digest"])
    report = access._object(old)
    action(report)
    new = access.lab.objects.publish(canonicalize_json(report)).digest

    def replace_digest(event: JsonRecord) -> None:
        if event["report_digest"] == old:
            event["report_digest"] = new

    rewrite_events(access, identity, replace_digest)


def test_actual_equity_cash_positions_and_independent_duration_oracle(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, identity = case
    before = access.lab.get_run(cast(str, access.get(owner, identity)["experiment_id"]))
    result = portfolio.get(owner, identity)
    current = record(result["current"])
    native = access.engine.load(identity, str(owner.id))
    assert current["recorded_equity"] == str(native.equity)
    assert current["cash_balances"] == [
        {"currency": c.currency, "amount": str(c.amount)} for c in native.book.cash
    ]
    assert current["commissions"] == str(
        sum((f.commission for f in native.book.fills), Decimal(0))
    )
    quotes = {q.instrument_id: q for q in native.quotes}
    with localcontext(a.CONTEXT):
        values = [
            position.quantity * quotes[position.instrument_id].bid
            for position in native.book.positions
        ]
        assert record(current["valuation"])["holdings_value"] == str(
            sum(values, Decimal(0))
        )
        assert current["largest_position_fraction_of_equity"] == str(
            max((v / native.equity for v in values), default=Decimal(0))
        )
    timeline = rows(result["timeline"])
    assert len(timeline) == native.revision + 1
    assert [v["engine_revision"] for v in timeline] == list(range(native.revision + 1))
    assert timeline[0]["command_id"] is None
    from datetime import datetime

    high = Decimal(cast(str, timeline[0]["equity"]))
    peak = datetime.fromisoformat(cast(str, timeline[0]["at"]))
    maximum = duration = 0
    for item in timeline:
        at = datetime.fromisoformat(cast(str, item["at"]))
        equity = Decimal(cast(str, item["equity"]))
        if equity < high:
            duration = int((at - peak).total_seconds())
            maximum = max(maximum, duration)
        else:
            if duration:
                maximum = max(maximum, int((at - peak).total_seconds()))
            duration = 0
            high, peak = equity, at
    durations = record(result["drawdown_duration"])
    assert Decimal(cast(str, durations["current_seconds"])) == duration
    assert Decimal(cast(str, durations["maximum_seconds"])) == maximum
    assert result["scientific_disposition"] == "INCONCLUSIVE"
    assert result["unreported_native_revisions"] == 0
    assert access.lab.get_run(cast(str, result["experiment_id"])) == before
    with access.state.connection() as db:
        assert db.execute("SELECT count(*) FROM resource_readers").fetchone()[0] == 0


def test_uninitialized_is_unavailable_and_independent_sessions_are_not_summed(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, identity = case
    new = access.create(owner, default_paper_config())
    result = portfolio.get(owner, cast(str, new["id"]))
    assert result["availability"] == "UNAVAILABLE" and result["current"] is None
    assert result["timeline"] == [] and result["drawdown_duration"] is None
    choices = portfolio.list_sessions(owner)
    assert {r["id"] for r in choices} == {identity, new["id"]}
    assert all("equity" not in r and "current" not in r for r in choices)


def test_initialized_cash_only_has_meaningful_zeros(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, _ = case
    job = launch(access, owner)
    result = portfolio.get(owner, cast(str, job["id"]))
    current = record(result["current"])
    assert current["positions"] == []
    assert current["largest_position_fraction_of_equity"] == "0"
    assert current["reserved_buy_cash"] == "0"
    assert record(result["drawdown_duration"])["maximum_seconds"] == "0"
    assert len(rows(result["timeline"])) == 1


def test_foreign_stale_and_reader_identity_before_heavy_replay(
    case: tuple[PaperPortfolio, PaperAccess, User, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    portfolio, access, owner, identity = case
    other = access.state.create_user(
        "other", "synthetic long passphrase", "owner", bootstrap=False
    )

    def forbidden() -> None:
        pytest.fail("foreign actor reached the heavy source replay")

    monkeypatch.setattr(access.lab, "get_run", lambda _: forbidden())
    with pytest.raises(AccessError):
        portfolio.get(other, identity)
    with pytest.raises(AccessError):
        portfolio.get(replace(owner, role="reader"), identity)
    monkeypatch.undo()
    with access.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (owner.id,))
    reader = replace(owner, role="reader")
    assert portfolio.get(reader, identity)["availability"] == "AVAILABLE"


@pytest.mark.parametrize("operation", ["get", "list"])
def test_two_existing_readers_block_before_replay(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    portfolio, access, owner, identity = case
    with access.state.connection() as db:
        db.executemany(
            "INSERT INTO resource_readers VALUES(?,?,0)",
            [("a", owner.id), ("b", owner.id)],
        )
    monkeypatch.setattr(
        access, "_load", lambda *_: pytest.fail("read replay before admission")
    )
    with pytest.raises(AccessError, match="busy"):
        portfolio.get(
            owner, identity
        ) if operation == "get" else portfolio.list_sessions(owner)


@pytest.mark.parametrize(
    "field,value",
    [
        ("equity", "1"),
        ("commissions", "999"),
        ("max_drawdown", "1"),
        ("adverse_slippage", "5"),
        ("completed_bars", 19),
        ("job_id", "PAPER-other"),
        ("evidence_mode", "HISTORICAL"),
        ("format", "future"),
        ("scientific_disposition", "VALIDATED"),
    ],
)
def test_coherent_report_rehash_cannot_change_recorded_facts(
    case: tuple[PaperPortfolio, PaperAccess, User, str], field: str, value: JsonValue
) -> None:
    portfolio, access, owner, identity = case
    substitute_report(access, identity, lambda report: report.__setitem__(field, value))
    with pytest.raises(PortfolioError):
        portfolio.get(owner, identity)


def test_coherent_snapshot_rehash_cannot_change_cash(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, identity = case

    def changed(report: JsonRecord) -> None:
        record(rows(record(record(report["snapshot"])["book"])["cash"])[0])[
            "amount"
        ] = "1"

    substitute_report(access, identity, changed)
    with pytest.raises(PortfolioError, match="DIVERGENCE"):
        portfolio.get(owner, identity)


def test_existing_report_repeated_cursor_and_source_archive_are_reverified(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, identity = case

    def change_last(event: JsonRecord) -> None:
        if event["last_event"] == "WORK_ELAPSED" and event["status"] == "COMPLETED":
            event["cursor"] = 19

    rewrite_events(access, identity, change_last)
    # The concrete producer may label its final timing event differently.
    with access.state.connection() as db:
        current = access._load(db, identity)
        access._save(db, current, {"cursor": 19}, "HOSTILE_DUPLICATE_REPORT")
    with pytest.raises(PortfolioError, match="REPEATED_REPORT_BINDING"):
        portfolio.get(owner, identity)


def test_old_producer_remains_readable_and_source_loss_fails(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, identity = case
    access.lab.code_revision = "0" * 40
    access.lab.environment_digest = access.lab.objects.publish(
        b'{"new_environment":true}'
    ).digest
    result = portfolio.get(owner, identity)
    assert record(result["producer"])["code_revision"] != access.lab.code_revision
    environment = access._object(
        cast(str, record(result["producer"])["environment_digest"])
    )
    target = access.lab.objects.get(cast(str, environment["source_snapshot_digest"]))
    target.path.unlink()
    with pytest.raises(PortfolioError):
        portfolio.get(owner, identity)


def test_no_fake_point_for_control_or_unreported_native_commands(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, _ = case
    job = launch(access, owner, lookback=1)
    identity = cast(str, job["id"])
    access.process_one()
    first = portfolio.get(owner, identity)
    control(access, owner, job, "PAUSE")
    assert portfolio.get(owner, identity)["timeline"] == first["timeline"]
    native = access.engine.load(identity, str(owner.id))
    access.engine.process(
        identity,
        str(owner.id),
        p.Kill(
            command_id="unreported-kill",
            at=native.at,
            enabled=True,
            reason="OWNER_KILL",
        ),
        expected_revision=native.revision,
    )
    after = portfolio.get(owner, identity)
    assert after["timeline"] == first["timeline"]
    assert after["unreported_native_revisions"] == 1


def test_latest_failure_without_snapshot_does_not_display_stale_current(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, identity = case
    with access.state.connection() as db:
        head = access._load(db, identity)
    digest = access._report(
        head, None, [], cast(int, head["cursor"]), error="SyntheticFault"
    )
    with access.state.connection() as db:
        access._save(db, head, {"report_digest": digest}, "RETAINED_FAILURE")
    result = portfolio.get(owner, identity)
    assert result["availability"] == "UNAVAILABLE" and result["current"] is None
    assert result["timeline"]


def test_stale_marks_and_nonpositive_equity_are_unavailable_not_zero(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, _ = case
    job = launch(access, owner, lookback=1)
    identity = cast(str, job["id"])
    for _ in range(3):
        assert access.process_one()
    state = access.engine.load(identity, str(owner.id))
    assert state.book.positions
    actual = record(portfolio.get(owner, identity)["current"])
    quotes = {quote.instrument_id: quote for quote in state.quotes}
    with localcontext(a.CONTEXT):
        expected = sum(
            (
                position.quantity * quotes[position.instrument_id].bid
                for position in state.book.positions
            ),
            Decimal(0),
        )
        assert record(actual["valuation"])["holdings_value"] == str(expected)
        assert actual["largest_position_fraction_of_equity"] == str(
            expected / state.equity
        )
        assert actual["reserved_buy_cash"] == str(
            sum(
                (
                    reservation.cash
                    for reservation in state.reservations
                    if reservation.side == "BUY"
                ),
                Decimal(0),
            )
        )
    metrics = module._metrics(replace(state, at=state.at + timedelta(days=1)))
    assert metrics["valuation_status"] == "UNAVAILABLE"
    assert metrics["largest_position_fraction_of_equity"] is None
    assert all(p["bid_marked_value"] is None for p in rows(metrics["positions"]))
    empty = replace(
        state,
        book=replace(
            state.book, cash=(a.CashBalance("USD", Decimal(0)),), positions=()
        ),
        reservations=(),
    )
    assert module._metrics(empty)["largest_position_fraction_of_equity"] is None


def test_decimal_context_is_local(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, _, owner, identity = case
    expected = portfolio.get(owner, identity)
    with localcontext(Context(prec=2)):
        assert portfolio.get(owner, identity) == expected


@pytest.mark.parametrize("limit", ["MAX_REPORT_BYTES", "MAX_RESPONSE_BYTES"])
def test_bounded_output_and_processing(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
) -> None:
    portfolio, _, owner, identity = case
    monkeypatch.setattr(module, limit, 1)
    with pytest.raises(PortfolioError):
        portfolio.get(owner, identity)


def test_routes_are_private_read_only_and_sanitize_failures(
    case: tuple[PaperPortfolio, PaperAccess, User, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    portfolio, access, actor, identity = case

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        if request.headers.get("x-synthetic-auth") != "yes":
            raise HTTPException(401, "Authentication required")
        assert not mutation and not owner
        return Session(case[2], "synthetic-csrf")

    app = FastAPI()
    install_paper_portfolio_routes(app, authenticated, portfolio)
    with LocalClient(app) as client:
        assert client.get("/api/paper/portfolio/sessions").status_code == 401
        client.headers["x-synthetic-auth"] = "yes"
        assert client.get("/api/paper/portfolio/sessions").status_code == 200
        assert (
            client.get(f"/api/paper/portfolio/sessions/{identity}").status_code == 200
        )
        assert (
            client.post(f"/api/paper/portfolio/sessions/{identity}").status_code == 405
        )
        assert client.get("/api/paper/portfolio/sessions/foreign").status_code == 403
        with access.state.connection() as db:
            db.executemany(
                "INSERT INTO resource_readers VALUES(?,?,0)",
                [("occupied-a", actor.id), ("occupied-b", actor.id)],
            )
        response = client.get(f"/api/paper/portfolio/sessions/{identity}")
        assert response.status_code == 503 and response.headers["Retry-After"] == "3"
        with access.state.connection() as db:
            db.execute("DELETE FROM resource_readers")

        def fault(*_: object) -> JsonRecord:
            raise RuntimeError("synthetic-secret-must-not-escape")

        monkeypatch.setattr(portfolio, "get", fault)
        response = client.get(f"/api/paper/portfolio/sessions/{identity}")
        assert response.status_code == 503 and "synthetic-secret" not in response.text

        def evidence_fault(*_: object) -> JsonRecord:
            raise PortfolioError("fixed")

        monkeypatch.setattr(portfolio, "get", evidence_fault)
        assert (
            client.get(f"/api/paper/portfolio/sessions/{identity}").status_code == 409
        )
    unavailable = FastAPI()
    install_paper_portfolio_routes(unavailable, authenticated, None)
    with LocalClient(unavailable) as client:
        client.headers["x-synthetic-auth"] = "yes"
        assert client.get("/api/paper/portfolio/sessions").status_code == 503


def test_callback_is_required_and_one_outer_reservation_released_on_error(
    case: tuple[PaperPortfolio, PaperAccess, User, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, access, owner, identity = case
    calls: list[str] = []

    @contextmanager
    def inspection(user: User) -> Iterator[None]:
        assert user == owner
        calls.append("enter")
        try:
            yield
        finally:
            calls.append("exit")

    portfolio = PaperPortfolio(access, inspection=inspection)
    monkeypatch.setattr(
        access, "_binding", lambda _: (_ for _ in ()).throw(ValueError("secret"))
    )
    with pytest.raises(PortfolioError, match="EVIDENCE_UNAVAILABLE"):
        portfolio.get(owner, identity)
    assert calls == ["enter", "exit"]


@pytest.mark.parametrize("snapshot", [None, [], {"revision": True}, {"revision": -1}])
def test_missing_or_malformed_snapshot_is_not_a_zero_portfolio(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
    snapshot: JsonValue,
) -> None:
    portfolio, access, owner, identity = case
    substitute_report(
        access, identity, lambda report: report.__setitem__("snapshot", snapshot)
    )
    with pytest.raises(PortfolioError):
        portfolio.get(owner, identity)


def test_changed_historical_configuration_cannot_hide_behind_valid_current_head(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, identity = case

    def changed(event: JsonRecord) -> None:
        if event["revision"] == 1:
            record(event["configuration"])["initial_cash"] = "1"

    rewrite_events(access, identity, changed)
    with pytest.raises(PortfolioError, match="EVENT_IDENTITY"):
        portfolio.get(owner, identity)


def test_retained_report_head_rollback_is_refused(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
) -> None:
    portfolio, access, owner, identity = case
    with access.state.connection() as db:
        head = access._load(db, identity)
        first = next(
            workflow._decode(bytes(row[0]))
            for row in db.execute(
                "SELECT payload FROM paper_events WHERE job_id=? ORDER BY sequence",
                (identity,),
            )
            if workflow._decode(bytes(row[0]))["report_digest"] is not None
        )
        access._save(
            db,
            head,
            {"report_digest": first["report_digest"], "cursor": first["cursor"]},
            "HOSTILE_REPORT_ROLLBACK",
        )
    with pytest.raises(PortfolioError, match="REPORT_ROLLBACK"):
        portfolio.get(owner, identity)


@pytest.mark.parametrize("bound", ["MAX_TOTAL_BYTES", "MAX_PAYLOAD"])
def test_native_input_budget_precedes_replay(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
) -> None:
    portfolio, access, owner, identity = case
    monkeypatch.setattr(p, bound, 1)
    monkeypatch.setattr(
        access.engine, "_load", lambda *_: pytest.fail("unbounded native replay")
    )
    with pytest.raises(PortfolioError, match="BOUND"):
        portfolio.get(owner, identity)


def test_33_owned_session_choices_are_refused_before_chain_replay(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio, access, owner, _ = case
    with access.state.connection() as db:
        for i in range(32):
            db.execute(
                "INSERT INTO paper_jobs VALUES(?,?,?,NULL,?,?,?)",
                (f"PAPER-bound-{i}", owner.id, "COMPLETED", b"{}", "", 0),
            )
    monkeypatch.setattr(
        access, "_load", lambda *_: pytest.fail("unbounded choice replay")
    )
    with pytest.raises(PortfolioError, match="SESSION_BOUND"):
        portfolio.list_sessions(owner)


def test_other_valid_native_genesis_does_not_match_owned_report_graph(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
    tmp_path: Path,
) -> None:
    portfolio, access, owner, identity = case
    original = access.engine.load(identity, str(owner.id))
    replacement = p.PaperEngine(tmp_path / "other-native.sqlite3")
    replacement.create_account(
        identity,
        str(owner.id),
        a.initial_book(
            "USD",
            workflow.START,
            original.book.instruments,
            (a.CashBalance("USD", original.inception_equity + 1),),
        ),
        original.limits,
        original.provenance,
    )
    access.engine = replacement
    with pytest.raises(PortfolioError, match="NATIVE_BINDING"):
        portfolio.get(owner, identity)


@pytest.mark.parametrize("target", ["head_bytes", "event_bytes", "event_count"])
@pytest.mark.parametrize("operation", ["get", "list"])
def test_workflow_bounds_precede_untrusted_payload_loading(
    case: tuple[PaperPortfolio, PaperAccess, User, str],
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    operation: str,
) -> None:
    portfolio, access, owner, identity = case
    with access.state.connection() as db:
        if target == "head_bytes":
            db.execute(
                "UPDATE paper_jobs SET payload=? WHERE id=?", (b" " * 4097, identity)
            )
        elif target == "event_bytes":
            db.execute(
                "INSERT INTO paper_events VALUES(?,?,?,?,?)",
                (identity, 599, b" " * 4097, "", ""),
            )
        else:
            last = db.execute(
                "SELECT max(sequence) FROM paper_events WHERE job_id=?", (identity,)
            ).fetchone()[0]
            db.executemany(
                "INSERT INTO paper_events VALUES(?,?,?,?,?)",
                [(identity, i, b"{}", "", "") for i in range(last + 1, 602)],
            )
    monkeypatch.setattr(
        access, "_load", lambda *_: pytest.fail("untrusted payload parsed before bound")
    )
    with pytest.raises(PortfolioError, match="EVENT_BOUND"):
        portfolio.get(
            owner, identity
        ) if operation == "get" else portfolio.list_sessions(owner)
