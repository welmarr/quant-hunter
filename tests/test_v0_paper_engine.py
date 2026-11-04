"""Real local SQLite transactions and independent synthetic money/risk oracles."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest

from quant_hunter.simulation.accounting import (
    CashBalance,
    InstrumentSpec,
    Quote,
    TradingWindow,
    initial_book,
)
from quant_hunter.simulation.paper_engine import (
    Admit,
    Cancel,
    Health,
    Kill,
    Mark,
    Match,
    PaperCommand,
    PaperEngine,
    PaperError,
    PaperSnapshot,
    Provenance,
    Reconcile,
    RiskLimits,
    StrategyBudget,
)

D = Decimal
START = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
SPEC = InstrumentSpec(
    "INS-1",
    "TEST",
    "EQUITY",
    "USD",
    D(1),
    D(".01"),
    (TradingWindow(START, START + timedelta(hours=6)),),
)
PROOF = Provenance(
    "EXP-TEST",
    "sha256:" + "1" * 64,
    "sha256:" + "1" * 64,
    "sha256:" + "1" * 64,
    "SYNTHETIC",
    "LOCAL_PAPER",
)
LIMITS = RiskLimits(
    D(10000),
    D(10000),
    D(10000),
    D(1),
    D(".1"),
    D(1000),
    D(100),
    D(0),
    30,
    20,
    60,
    (StrategyBudget("STR-1", D(10000)), StrategyBudget("STR-2", D(10000))),
)


def at(second: int) -> datetime:
    return START + timedelta(seconds=second)


def quote(second: int, price: str = "100", *, ask: str | None = None) -> Quote:
    return Quote("INS-1", at(second), at(second), D(price), D(ask or price))


def create(path: Path, limits: RiskLimits = LIMITS) -> PaperEngine:
    engine = PaperEngine(path)
    engine.create_account(
        "ACCOUNT",
        "OWNER",
        initial_book("USD", START, (SPEC,), (CashBalance("USD", D(10000)),)),
        limits,
        PROOF,
    )
    return engine


def admit(
    second: int = 1,
    quantity: str = "10",
    *,
    side: str = "BUY",
    order: str = "ORDER-1",
    fee: str = "1",
    price: str = "100",
    strategy: str = "STR-1",
) -> Admit:
    return Admit(
        command_id=f"ADMIT-{order}",
        at=at(second),
        order_id=order,
        strategy_id=strategy,
        instrument_id="INS-1",
        side=side,
        quantity=D(quantity),
        decision_at=at(second),
        quote=quote(second, price),
        commission_budget=D(fee),
    )


def match(
    second: int = 2,
    quantity: str = "10",
    *,
    order: str = "ORDER-1",
    fee: str = "1",
    price: str = "100",
) -> Match:
    return Match(
        command_id=f"MATCH-{second}",
        at=at(second),
        order_id=order,
        quantity=D(quantity),
        quote=quote(second, price),
        commission=D(fee),
        slippage_bps=D(0),
    )


def run(engine: PaperEngine, command: PaperCommand) -> PaperSnapshot:
    state = engine.load("ACCOUNT", "OWNER")
    return engine.process("ACCOUNT", "OWNER", command, state.revision)


def filled(engine: PaperEngine) -> PaperSnapshot:
    assert run(engine, admit()).outcomes[-1].status == "APPLIED"
    result = run(engine, match())
    assert result.outcomes[-1].status == "APPLIED"
    return result


def test_independent_roundtrip_and_exact_restart_replay(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite"
    engine = create(path)
    genesis = engine.load("ACCOUNT", "OWNER")
    assert genesis.book.version == genesis.revision == 0
    state = filled(engine)
    assert state.book.cash[0].amount == D(8999)
    assert state.equity == D(9999)
    run(engine, admit(3, side="SELL", order="SELL", price="101"))
    state = run(engine, match(4, order="SELL", price="101"))
    assert state.book.cash[0].amount == state.equity == D(10008)
    assert not state.book.positions and not state.reservations
    assert state.book.fills[-1].realized_pnl == D(8)
    assert PaperEngine(path).load("ACCOUNT", "OWNER") == state
    assert state.provenance == PROOF and state.limits == LIMITS


def test_partial_fills_reserve_remaining_price_and_total_commission(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    state = run(engine, admit(quantity="10", fee="2"))
    assert state.reservations[0].cash == D(1002)
    state = run(engine, match(quantity="4"))
    assert state.book.cash[0].amount == D(9599)
    assert state.reservations[0].cash == D(601)
    assert state.reservations[0].remaining == D(6)
    state = run(engine, match(3, "6"))
    assert state.book.cash[0].amount == D(8998) and not state.reservations
    assert state.equity == D(9998)


def test_pending_cancel_retains_reservation_fill_race_and_late_ack(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, admit())
    state = run(
        engine, Cancel(command_id="C1", at=at(2), order_id="ORDER-1", action="REQUEST")
    )
    assert state.reservations[0].cash == D(1001)
    state = run(engine, match(3))
    assert state.book.orders[0].status == "FILLED"
    state = run(
        engine, Cancel(command_id="C2", at=at(4), order_id="ORDER-1", action="CONFIRM")
    )
    assert state.book.orders[0].reason == "CANCEL_TOO_LATE"
    assert state.book.cash[0].amount == D(8999)


@pytest.mark.parametrize("action", ["CONFIRM", "REJECT"])
def test_cancel_or_rejection_releases_reservation_and_prevents_late_fill(
    tmp_path: Path, action: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, admit())
    run(
        engine,
        Cancel(command_id="REQUEST", at=at(2), order_id="ORDER-1", action="REQUEST"),
    )
    state = run(
        engine, Cancel(command_id="END", at=at(3), order_id="ORDER-1", action=action)
    )
    assert not state.reservations
    state = run(engine, match(4))
    assert state.outcomes[-1].reason == "NO_OPEN_RESERVATION"
    assert state.book.cash[0].amount == D(10000)


def test_duplicate_old_command_returns_current_state_conflict_and_cas_refused(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    original = admit()
    engine.process("ACCOUNT", "OWNER", original, 0)
    current = run(engine, match())
    assert engine.process("ACCOUNT", "OWNER", original, 0) == current
    with pytest.raises(PaperError, match="CONFLICTING"):
        engine.process("ACCOUNT", "OWNER", replace(original, quantity=D(1)), 0)
    with pytest.raises(PaperError, match="STALE"):
        engine.process("ACCOUNT", "OWNER", admit(3, order="OTHER"), 0)
    assert engine.load("ACCOUNT", "OWNER") == current
    audit = engine.protocol_rejections("ACCOUNT", "OWNER")
    assert tuple(row.reason for row in audit) == (
        "CONFLICTING_COMMAND_ID",
        "STALE_REVISION",
    )
    assert all(row.actual_revision == 2 and row.expected_revision == 0 for row in audit)


def test_two_connections_cannot_reserve_the_same_cash_even_with_cas_retry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "paper.sqlite"
    create(path)
    barrier = Barrier(2)

    def contender(number: int) -> str:
        engine = PaperEngine(path)
        state = engine.load("ACCOUNT", "OWNER")
        barrier.wait(timeout=5)
        command = admit(quantity="60", order=f"ORDER-{number}")
        try:
            result = engine.process("ACCOUNT", "OWNER", command, state.revision)
        except PaperError as error:
            assert str(error) == "STALE_REVISION"
            result = run(engine, command)
        return result.outcomes[-1].status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(contender, (1, 2)))
    assert sorted(outcomes) == ["APPLIED", "REJECTED"]
    state = PaperEngine(path).load("ACCOUNT", "OWNER")
    assert len(state.reservations) == 1 and state.reservations[0].cash == D(6001)
    assert state.revision == 2 and state.book.version == 1


def test_injected_crash_rolls_back_journal_head_and_reservation(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite"
    original = create(path).load("ACCOUNT", "OWNER")

    def crash() -> None:
        raise RuntimeError("injected before commit")

    broken = PaperEngine(path, before_commit=crash)
    with pytest.raises(RuntimeError, match="injected"):
        broken.process("ACCOUNT", "OWNER", admit(), 0)
    restored = PaperEngine(path)
    assert restored.load("ACCOUNT", "OWNER") == original
    state = restored.process("ACCOUNT", "OWNER", admit(), 0)
    assert state.revision == 1 and len(state.reservations) == 1


@pytest.mark.parametrize("owner", ["OTHER", "OWNER-INVALID"])
def test_every_account_read_and_write_is_owner_scoped(
    tmp_path: Path, owner: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    with pytest.raises(PaperError, match="ACCOUNT_NOT_FOUND"):
        engine.load("ACCOUNT", owner)
    with pytest.raises(PaperError, match="ACCOUNT_NOT_FOUND"):
        engine.process("ACCOUNT", owner, admit(), 0)
    assert engine.load("ACCOUNT", "OWNER").revision == 0


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("future", "DECISION_QUOTE_TIMING"),
        ("stale", "STALE_OR_UNAVAILABLE_QUOTE"),
        ("spread", "SPREAD_LIMIT"),
        ("lot", "lot"),
        ("market", "closed"),
        ("strategy", "UNKNOWN_STRATEGY_REFERENCE"),
        ("side", "INVALID_ORDER"),
    ],
)
def test_bad_admissions_are_retained_without_economic_changes(
    tmp_path: Path, kind: str, reason: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    command = admit()
    if kind == "future":
        command = replace(command, quote=quote(2))
    elif kind == "stale":
        command = replace(command, at=at(100), decision_at=at(100))
    elif kind == "spread":
        command = replace(command, quote=quote(1, ask="102"))
    elif kind == "lot":
        command = replace(command, quantity=D(".1"))
    elif kind == "market":
        command = replace(
            command, at=at(22000), decision_at=at(22000), quote=quote(22000)
        )
    elif kind == "strategy":
        command = replace(command, strategy_id="UNKNOWN")
    else:
        command = replace(command, side="SHORT")
    state = run(engine, command)
    assert state.outcomes[-1].status == "REJECTED"
    assert reason in state.outcomes[-1].reason
    assert state.book.version == 0 and not state.reservations
    assert state.book.cash[0].amount == D(10000)
    assert engine.load("ACCOUNT", "OWNER") == state


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("order", "ORDER_NOTIONAL_LIMIT"),
        ("gross", "GROSS_EXPOSURE_LIMIT"),
        ("instrument", "INSTRUMENT_OR_CONCENTRATION_LIMIT"),
        ("concentration", "INSTRUMENT_OR_CONCENTRATION_LIMIT"),
        ("strategy", "STRATEGY_EXPOSURE_LIMIT"),
        ("cash", "INSUFFICIENT_UNRESERVED_CASH"),
    ],
)
def test_independent_risk_budget_rejections(
    tmp_path: Path, kind: str, reason: str
) -> None:
    variants = {
        "order": replace(LIMITS, max_order_notional=D(999)),
        "gross": replace(LIMITS, max_gross_exposure=D(999)),
        "instrument": replace(LIMITS, max_instrument_exposure=D(999)),
        "concentration": replace(LIMITS, max_concentration=D(".09")),
        "strategy": replace(
            LIMITS, strategy_budgets=(StrategyBudget("STR-1", D(999)),)
        ),
        "cash": LIMITS,
    }
    engine = create(tmp_path / "paper.sqlite", variants[kind])
    state = run(engine, admit(quantity="100" if kind == "cash" else "10"))
    assert state.outcomes[-1].reason == reason
    assert not state.book.orders


def test_frequency_window_has_explicit_half_open_boundary(tmp_path: Path) -> None:
    engine = create(tmp_path / "paper.sqlite", replace(LIMITS, max_orders_per_window=1))
    run(engine, admit())
    assert (
        run(engine, admit(60, order="SECOND")).outcomes[-1].reason
        == "ORDER_FREQUENCY_LIMIT"
    )
    assert run(engine, admit(61, order="THIRD")).outcomes[-1].status == "APPLIED"


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("same-time", "strictly"),
        ("price", "FILL_PRICE_OUTSIDE_RESERVATION"),
        ("fee", "FILL_COST_BUDGET"),
        ("slippage", "FILL_COST_BUDGET"),
        ("quantity", "partial-fill quantity"),
    ],
)
def test_local_matches_must_respect_causal_and_reserved_contract(
    tmp_path: Path, kind: str, reason: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, admit())
    command = match()
    if kind == "same-time":
        command = replace(command, at=at(1), quote=quote(1))
    elif kind == "price":
        command = replace(command, quote=quote(2, "101"))
    elif kind == "fee":
        command = replace(command, commission=D(2))
    elif kind == "slippage":
        command = replace(command, slippage_bps=D(1))
    else:
        command = replace(command, quantity=D(11))
    state = run(engine, command)
    assert state.outcomes[-1].status == "REJECTED"
    assert reason in state.outcomes[-1].reason
    assert state.book.cash[0].amount == D(10000) and not state.book.fills
    assert state.reservations[0].cash == D(1001)


def test_kill_requests_cancellation_and_allows_reconciled_reduce_only_sale(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    filled(engine)
    run(engine, admit(3, order="PENDING"))
    state = run(
        engine, Kill(command_id="KILL", at=at(4), enabled=True, reason="OWNER_STOP")
    )
    assert state.killed and state.book.orders[-1].status == "CANCEL_PENDING"
    assert state.reservations[0].cash == D(1001)
    assert run(engine, admit(5, order="BLOCKED")).outcomes[-1].reason == "KILL_ACTIVE"
    state = run(engine, admit(6, "4", side="SELL", order="REDUCE"))
    assert state.outcomes[-1].status == "APPLIED"
    state = run(engine, match(7, "4", order="REDUCE"))
    assert state.book.positions[0].quantity == D(6)
    assert state.killed
    assert PaperEngine(engine.path).load("ACCOUNT", "OWNER") == state


def test_per_strategy_positions_and_pending_sales_cannot_be_reused(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    filled(engine)
    wrong = run(engine, admit(3, side="SELL", order="WRONG", strategy="STR-2"))
    assert wrong.outcomes[-1].reason == "INSUFFICIENT_UNRESERVED_STRATEGY_POSITION"
    run(engine, admit(4, "7", side="SELL", order="SELL1"))
    wrong = run(engine, admit(5, "4", side="SELL", order="SELL2"))
    assert wrong.outcomes[-1].reason == "INSUFFICIENT_UNRESERVED_STRATEGY_POSITION"


def test_reconciliation_mismatch_retains_account_facts_and_persistent_kill(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    previous = filled(engine)
    state = run(
        engine,
        Reconcile(
            command_id="RECON",
            at=at(3),
            cash=D(8998),
            positions=(("INS-1", D(10)),),
            observation_at=at(3),
        ),
    )
    assert state.killed and not state.reconciled and state.book == previous.book
    assert (
        run(engine, admit(4, side="SELL", order="UNSAFE")).outcomes[-1].reason
        == "UNRECONCILED_OR_UNHEALTHY"
    )
    state = run(
        engine, Kill(command_id="RESET", at=at(5), enabled=False, reason="RESET")
    )
    assert state.outcomes[-1].reason == "UNSAFE_KILL_RESET"
    state = run(
        engine,
        Reconcile(
            command_id="CORRECT",
            at=at(6),
            cash=D(8999),
            positions=(("INS-1", D(10)),),
            observation_at=at(6),
        ),
    )
    assert state.reconciled and state.killed
    state = run(
        engine, Kill(command_id="SAFE", at=at(7), enabled=False, reason="RECONCILED")
    )
    assert not state.killed


def test_loss_high_water_never_resets_on_restart_or_out_of_order_mark(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite", replace(LIMITS, max_drawdown=D(".01")))
    filled(engine)
    state = run(engine, Mark(command_id="UP", at=at(3), quotes=(quote(3, "110"),)))
    assert state.high_water == D(10099)
    state = run(engine, Mark(command_id="DOWN", at=at(4), quotes=(quote(4, "90"),)))
    assert state.killed and state.equity == D(9899)
    assert state.max_drawdown == D(200) / D(10099) or abs(
        state.max_drawdown - D(200) / D(10099)
    ) < D("1e-27")
    state = run(engine, Mark(command_id="OLD", at=at(2), quotes=(quote(2, "100"),)))
    assert state.outcomes[-1].reason == "OUT_OF_ORDER" and state.high_water == D(10099)
    assert PaperEngine(engine.path).load("ACCOUNT", "OWNER") == state
    state = run(engine, Kill(command_id="RESET", at=at(5), enabled=False, reason="NO"))
    assert state.killed and state.outcomes[-1].reason == "UNSAFE_KILL_RESET"


def test_rejected_buy_does_not_erase_new_loss_trigger(tmp_path: Path) -> None:
    engine = create(tmp_path / "paper.sqlite", replace(LIMITS, max_loss=D(50)))
    filled(engine)
    state = run(engine, admit(3, order="LOSS", price="90"))
    assert state.killed and state.equity == D(9899)
    assert state.outcomes[-1].status == "REJECTED" and len(state.book.orders) == 1


def test_connector_health_loss_persists_until_explicit_safe_reset(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, admit())
    state = run(engine, Health(command_id="OFFLINE", at=at(2), healthy=False))
    assert (
        state.killed
        and not state.healthy
        and state.book.orders[0].status == "CANCEL_PENDING"
    )
    assert run(engine, match(3)).outcomes[-1].reason == "UNRECONCILED_OR_UNHEALTHY"
    state = run(engine, Health(command_id="ONLINE", at=at(4), healthy=True))
    assert state.killed and state.healthy


@pytest.mark.parametrize("mutation", ["head", "genesis", "journal"])
def test_corruption_or_trigger_bypass_is_detected_by_replay(
    tmp_path: Path, mutation: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, admit())
    with closing(sqlite3.connect(engine.path)) as db, db:
        if mutation == "head":
            db.execute("UPDATE heads SET revision=99")
        elif mutation == "genesis":
            db.execute("DROP TRIGGER accounts_no_update")
            db.execute("UPDATE accounts SET genesis_hash='wrong'")
        else:
            db.execute("DROP TRIGGER commands_no_update")
            db.execute("UPDATE commands SET fingerprint='wrong'")
    with pytest.raises(PaperError, match="INTEGRITY"):
        engine.load("ACCOUNT", "OWNER")


@pytest.mark.parametrize("table", ["accounts", "commands"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_genesis_and_journal_are_sql_immutable(
    tmp_path: Path, table: str, verb: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, admit())
    with (
        closing(sqlite3.connect(engine.path)) as db,
        db,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        statements = {
            ("accounts", "UPDATE"): "UPDATE accounts SET account_id='other'",
            ("commands", "UPDATE"): "UPDATE commands SET account_id='other'",
            ("accounts", "DELETE"): "DELETE FROM accounts",
            ("commands", "DELETE"): "DELETE FROM commands",
        }
        db.execute(statements[table, verb])


@pytest.mark.parametrize("mode", ["BROKER_PAPER", "LIVE", "LIVE_DISABLED", "UNKNOWN"])
def test_no_external_execution_mode_can_be_created(tmp_path: Path, mode: str) -> None:
    engine = PaperEngine(tmp_path / "paper.sqlite")
    with pytest.raises(PaperError, match="UNSUPPORTED_MODE"):
        engine.create_account(
            "A",
            "O",
            initial_book("USD", START, (SPEC,), (CashBalance("USD", D(10000)),)),
            LIMITS,
            replace(PROOF, mode=mode),
        )


def test_multi_currency_and_prepopulated_books_explicitly_unsupported(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    state = filled(engine)
    with pytest.raises(PaperError, match="UNSUPPORTED_INITIAL"):
        engine.create_account("COPY", "OWNER", state.book, LIMITS, PROOF)
    multi = initial_book(
        "USD",
        START,
        (replace(SPEC, quote_currency="EUR"),),
        (CashBalance("USD", D(10000)),),
    )
    with pytest.raises(PaperError, match="MULTI_CURRENCY"):
        engine.create_account("MULTI", "OWNER", multi, LIMITS, PROOF)


def test_kill_reset_requires_reconciliation_after_kill_and_recent_receipt(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, Kill(command_id="STOP", at=at(1), enabled=True, reason="OWNER"))
    failed = run(
        engine, Kill(command_id="RESET", at=at(2), enabled=False, reason="OWNER")
    )
    assert failed.killed and failed.outcomes[-1].reason == "UNSAFE_KILL_RESET"
    run(
        engine,
        Reconcile(
            command_id="MATCHING",
            at=at(3),
            cash=D(10000),
            positions=(),
            observation_at=at(3),
        ),
    )
    failed = run(
        engine, Kill(command_id="STALE", at=at(34), enabled=False, reason="OWNER")
    )
    assert failed.killed and failed.outcomes[-1].reason == "UNSAFE_KILL_RESET"
    run(
        engine,
        Reconcile(
            command_id="FRESH",
            at=at(35),
            cash=D(10000),
            positions=(),
            observation_at=at(35),
        ),
    )
    state = run(
        engine, Kill(command_id="RESUME", at=at(36), enabled=False, reason="OWNER")
    )
    assert not state.killed and state.high_water == D(10000)


def test_marked_exposure_limit_trips_kill_and_can_be_reduced_without_resetting_high_water(
    tmp_path: Path,
) -> None:
    engine = create(
        tmp_path / "paper.sqlite", replace(LIMITS, max_gross_exposure=D(1050))
    )
    filled(engine)
    state = run(engine, Mark(command_id="UP", at=at(3), quotes=(quote(3, "110"),)))
    assert state.killed and state.kill_reason == "EXPOSURE_LIMIT"
    run(engine, admit(4, "1", side="SELL", price="110", order="REDUCE"))
    state = run(engine, match(5, "1", price="110", order="REDUCE"))
    assert state.book.positions[0].quantity == D(9)
    run(
        engine,
        Reconcile(
            command_id="AGREE",
            at=at(6),
            cash=D(9108),
            positions=(("INS-1", D(9)),),
            observation_at=at(6),
        ),
    )
    state = run(
        engine, Kill(command_id="RESUME", at=at(7), enabled=False, reason="OWNER")
    )
    assert not state.killed and state.high_water == D(10099)


def test_sale_fee_reservation_cannot_consume_cash_reserved_for_pending_purchase(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    filled(engine)
    run(engine, admit(3, "89", order="PENDING", fee="90"))
    state = run(engine, admit(4, "1", side="SELL", order="SELL", fee="10"))
    assert state.outcomes[-1].reason == "INSUFFICIENT_UNRESERVED_CASH"
    assert sum((r.cash for r in state.reservations), D(0)) == D(8990)


@pytest.mark.parametrize("kind", ["naive", "reserved", "revision", "id", "oversized"])
def test_protocol_input_bounds_do_not_create_partial_economic_events(
    tmp_path: Path, kind: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    command = admit()
    version = 0
    if kind == "naive":
        command = replace(command, at=command.at.replace(tzinfo=None))
    elif kind == "reserved":
        command = replace(command, command_id="EINT.RESERVED")
    elif kind == "revision":
        version = -1
    elif kind == "id":
        command = replace(command, command_id="bad space")
    else:
        command = replace(command, strategy_id="X" * 140000)
    with pytest.raises(PaperError):
        engine.process("ACCOUNT", "OWNER", command, version)
    assert engine.load("ACCOUNT", "OWNER").revision == 0


@pytest.mark.parametrize(
    "kind", ["decimal", "precision", "ratio", "integer", "empty", "duplicate", "proof"]
)
def test_bad_genesis_risk_and_provenance_are_rejected(
    tmp_path: Path, kind: str
) -> None:
    limits = LIMITS
    proof = PROOF
    if kind == "decimal":
        limits = replace(limits, max_loss=D("NaN"))
    elif kind == "precision":
        limits = replace(limits, max_loss=D("1e-50"))
    elif kind == "ratio":
        limits = replace(limits, max_drawdown=D(2))
    elif kind == "integer":
        limits = replace(limits, max_orders_per_window=0)
    elif kind == "empty":
        limits = replace(limits, strategy_budgets=())
    elif kind == "duplicate":
        limits = replace(limits, strategy_budgets=(StrategyBudget("STR-1", D(1)),) * 2)
    else:
        proof = replace(proof, code_digest="invalid")
    engine = PaperEngine(tmp_path / "paper.sqlite")
    with pytest.raises(PaperError):
        engine.create_account(
            "A",
            "O",
            initial_book("USD", START, (SPEC,), (CashBalance("USD", D(10000)),)),
            limits,
            proof,
        )


@pytest.mark.parametrize("kind", ["old", "changed", "unknown", "duplicate"])
def test_market_observations_cannot_be_rewritten_or_ambiguously_merged(
    tmp_path: Path, kind: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    filled(engine)
    quotes = (
        (quote(1),)
        if kind == "old"
        else (quote(2, "101"),)
        if kind == "changed"
        else (replace(quote(3), instrument_id="UNKNOWN"),)
        if kind == "unknown"
        else (quote(3), quote(3))
    )
    state = run(engine, Mark(command_id="HOSTILE", at=at(3), quotes=quotes))
    assert state.outcomes[-1].status == "REJECTED"
    assert state.equity == D(9999) and state.book.cash[0].amount == D(8999)


@pytest.mark.parametrize("kind", ["old", "duplicate", "zero"])
def test_bad_reconciliation_never_silently_changes_positions(
    tmp_path: Path, kind: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    before = filled(engine)
    command = Reconcile(
        command_id="BAD",
        at=at(3),
        cash=D(8999),
        positions=(("INS-1", D(10)),),
        observation_at=at(3),
    )
    if kind == "old":
        command = replace(command, observation_at=at(0))
    elif kind == "duplicate":
        command = replace(command, positions=command.positions * 2)
    else:
        command = replace(command, positions=(("INS-1", D(0)),))
    state = run(engine, command)
    assert state.outcomes[-1].status == "REJECTED" and state.book == before.book


def test_protocol_audit_is_owner_scoped_and_detects_mutation_and_truncation(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, admit())
    with pytest.raises(PaperError, match="STALE"):
        engine.process("ACCOUNT", "OWNER", admit(2, order="SECOND"), 0)
    with pytest.raises(PaperError, match="ACCOUNT_NOT_FOUND"):
        engine.protocol_rejections("ACCOUNT", "OTHER")
    assert len(engine.protocol_rejections("ACCOUNT", "OWNER")) == 1
    with closing(sqlite3.connect(engine.path)) as db, db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM protocol_rejections")
        db.execute("DROP TRIGGER protocol_no_delete")
        db.execute("DELETE FROM protocol_rejections")
    with pytest.raises(PaperError, match="AUDIT_INTEGRITY"):
        engine.protocol_rejections("ACCOUNT", "OWNER")


def test_capacity_prevents_unbounded_commands_and_audits_without_overwriting_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_hunter.simulation import paper_engine

    engine = create(tmp_path / "paper.sqlite")
    monkeypatch.setattr(paper_engine, "MAX_COMMANDS", 1)
    before = run(engine, admit())
    with pytest.raises(PaperError, match="JOURNAL_CAPACITY"):
        engine.process("ACCOUNT", "OWNER", match(), 1)
    with pytest.raises(PaperError, match="STALE_REVISION"):
        engine.process("ACCOUNT", "OWNER", match(), 0)
    with pytest.raises(PaperError, match="AUDIT_CAPACITY"):
        engine.process("ACCOUNT", "OWNER", match(), 0)
    assert engine.load("ACCOUNT", "OWNER") == before
    assert len(engine.protocol_rejections("ACCOUNT", "OWNER")) == 1


def test_total_journal_byte_capacity_blocks_before_economic_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_hunter.simulation import paper_engine

    engine = create(tmp_path / "paper.sqlite")
    monkeypatch.setattr(paper_engine, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(PaperError, match="JOURNAL_CAPACITY"):
        engine.process("ACCOUNT", "OWNER", admit(), 0)
    assert engine.load("ACCOUNT", "OWNER").revision == 0


def test_duplicate_account_creation_preserves_original_genesis(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite"
    original = create(path).load("ACCOUNT", "OWNER")
    with pytest.raises(PaperError, match="ACCOUNT_EXISTS"):
        create(path)
    assert PaperEngine(path).load("ACCOUNT", "OWNER") == original


@pytest.mark.parametrize("kind", ["foreign", "version", "identity"])
def test_foreign_or_future_database_format_is_not_modified_as_a_paper_ledger(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "other.sqlite"
    if kind != "foreign":
        create(path)
    with closing(sqlite3.connect(path)) as db, db:
        if kind == "foreign":
            db.execute("CREATE TABLE unrelated (id TEXT)")
        elif kind == "version":
            db.execute("PRAGMA user_version=999")
        else:
            db.execute("PRAGMA application_id=100")
    with pytest.raises(PaperError, match="UNSUPPORTED_DATABASE_FORMAT"):
        PaperEngine(path)


def test_tick_rounded_slippage_spread_and_commission_remain_distinct(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite", replace(LIMITS, max_slippage_bps=D(1)))
    command = replace(admit(), quote=quote(1, "99.99", ask="100.01"))
    state = run(engine, command)
    assert state.reservations[0].cash == D("1001.30")
    command_fill = replace(
        match(), quote=quote(2, "99.99", ask="100.01"), slippage_bps=D(1)
    )
    state = run(engine, command_fill)
    fill = state.book.fills[0]
    assert fill.market_price == D("100.01") and fill.price == D("100.03")
    assert fill.adverse_slippage == D(".20") and fill.commission == D(1)
    assert state.book.cash[0].amount == D("8998.70")
    assert state.equity == D("9998.60")


def test_doubled_roundtrip_fee_changes_only_exact_accounting_cost(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, admit(fee="2"))
    run(engine, match(fee="2"))
    run(engine, admit(3, side="SELL", order="SELL", fee="2", price="101"))
    state = run(engine, match(4, order="SELL", fee="2", price="101"))
    assert state.book.cash[0].amount == state.equity == D(10006)


def test_match_quote_requires_effective_and_available_after_decision_without_same_close_fill(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    run(engine, admit())
    command = replace(match(), quote=replace(quote(2), available_at=at(3)))
    state = run(engine, command)
    assert state.outcomes[-1].status == "REJECTED"
    assert not state.book.fills and state.reservations[0].cash == D(1001)


def test_restart_leaves_unfilled_and_cancel_pending_orders_without_automatic_resubmission(
    tmp_path: Path,
) -> None:
    path = tmp_path / "paper.sqlite"
    engine = create(path)
    run(engine, admit())
    pending = run(
        engine,
        Cancel(command_id="REQUEST", at=at(2), order_id="ORDER-1", action="REQUEST"),
    )
    assert pending.book.orders[0].status == "CANCEL_PENDING"
    restarted = PaperEngine(path)
    assert restarted.load("ACCOUNT", "OWNER") == pending
    assert restarted.load("ACCOUNT", "OWNER").book.cash[0].amount == D(10000)
    assert not restarted.load("ACCOUNT", "OWNER").book.fills


def test_account_limit_is_explicit_and_does_not_change_existing_accounts(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    initial = engine.load("ACCOUNT", "OWNER")
    for number in range(31):
        engine.create_account(f"A{number}", "OWNER", initial.book, LIMITS, PROOF)
    with pytest.raises(PaperError, match="ACCOUNT_LIMIT"):
        engine.create_account("OVERFLOW", "OWNER", initial.book, LIMITS, PROOF)
    assert engine.load("ACCOUNT", "OWNER") == initial


def test_admission_concentration_uses_equity_after_reserved_costs(
    tmp_path: Path,
) -> None:
    engine = create(
        tmp_path / "paper.sqlite", replace(LIMITS, max_concentration=D(".1"))
    )
    state = run(engine, admit(fee="1"))
    # 1000/9999 exceeds10%; ignoring the known fee would wrongly pass1000/10000.
    assert state.outcomes[-1].reason == "INSTRUMENT_OR_CONCENTRATION_LIMIT"
    assert not state.reservations and state.book.cash[0].amount == D(10000)


def test_admission_rejects_cost_budget_that_would_itself_cross_loss_limit(
    tmp_path: Path,
) -> None:
    engine = create(tmp_path / "paper.sqlite", replace(LIMITS, max_loss=D(10)))
    state = run(engine, admit(fee="10"))
    assert state.outcomes[-1].reason == "PROSPECTIVE_LOSS_LIMIT"
    assert not state.book.orders and not state.killed


@pytest.mark.parametrize("operation", ["admission", "mark"])
def test_off_tick_quotes_cannot_affect_reservation_valuation_or_kill(
    tmp_path: Path, operation: str
) -> None:
    engine = create(tmp_path / "paper.sqlite")
    if operation == "admission":
        before = engine.load("ACCOUNT", "OWNER")
        state = run(engine, replace(admit(), quote=quote(1, "100.001")))
    else:
        before = filled(engine)
        state = run(
            engine, Mark(command_id="OFFGRID", at=at(3), quotes=(quote(3, "100.001"),))
        )
    assert state.outcomes[-1].reason == "QUOTE_TICK_GRID"
    assert state.book == before.book and state.quotes == before.quotes
    assert state.reservations == before.reservations and state.equity == before.equity
    assert state.high_water == before.high_water and state.killed == before.killed
