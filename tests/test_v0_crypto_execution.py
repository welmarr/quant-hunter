"""Concrete offline crypto execution: real journal, risks and money, no broker."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from quant_hunter.simulation import accounting as a
from quant_hunter.simulation import paper_engine as p
from quant_hunter.simulation.crypto_execution import (
    CryptoExecutionAdapter,
    CryptoExecutionError,
    OfflineCryptoPlugin,
)

D = Decimal
START = datetime(2024, 1, 6, tzinfo=UTC)  # Saturday, explicit synthetic 24h calendar.
SPEC = a.InstrumentSpec(
    "INS-CRYPTO",
    "BTC_USD",
    "CRYPTO_SPOT",
    "USD",
    D(".001"),
    D(".01"),
    (a.TradingWindow(START, START + timedelta(days=1)),),
    "BTC",
)
PROVENANCE = p.Provenance(
    "EXP-SYNTHETIC-CRYPTO",
    "sha256:" + "1" * 64,
    "sha256:" + "2" * 64,
    "sha256:" + "3" * 64,
    "SYNTHETIC",
    "LOCAL_PAPER",
)
LIMITS = p.RiskLimits(
    D(5000),
    D(5000),
    D(5000),
    D(".5"),
    D(".2"),
    D(2000),
    D(10),
    D(5),
    30,
    20,
    60,
    (p.StrategyBudget("STR-SYNTHETIC-CRYPTO", D(5000)),),
)


def at(second: int) -> datetime:
    return START + timedelta(seconds=second)


def quote(second: int, bid: str = "10000", ask: str | None = None) -> a.Quote:
    return a.Quote(SPEC.instrument_id, at(second), at(second), D(bid), D(ask or bid))


def create(
    path: Path, *, spec: a.InstrumentSpec = SPEC, proof: p.Provenance = PROVENANCE
) -> OfflineCryptoPlugin:
    engine = p.PaperEngine(path)
    engine.create_account(
        "CRYPTO-ACCOUNT",
        "OWNER",
        a.initial_book("USD", START, (spec,), (a.CashBalance("USD", D(10000)),)),
        LIMITS,
        proof,
    )
    return OfflineCryptoPlugin(engine, "CRYPTO-ACCOUNT", "OWNER")


def intent(
    *,
    second: int = 1,
    side: str = "BUY",
    order: str = "BUY-1",
    quantity: str = ".1",
    price: str = "10000",
    fee: str = "1",
) -> p.Admit:
    return p.Admit(
        command_id="admit-" + order,
        at=at(second),
        order_id=order,
        strategy_id="STR-SYNTHETIC-CRYPTO",
        instrument_id=SPEC.instrument_id,
        side=side,
        quantity=D(quantity),
        decision_at=at(second),
        quote=quote(second, price),
        commission_budget=D(fee),
    )


def fill(
    *,
    second: int = 2,
    order: str = "BUY-1",
    quantity: str = ".1",
    price: str = "10000",
    fee: str = "1",
    slip: str = "0",
) -> p.Match:
    return p.Match(
        command_id=f"fill-{order}-{second}",
        at=at(second),
        order_id=order,
        quantity=D(quantity),
        quote=quote(second, price),
        commission=D(fee),
        slippage_bps=D(slip),
    )


@pytest.mark.parametrize(("fee", "expected"), [("1", "10008"), ("2", "10006")])
def test_fractional_crypto_roundtrip_independent_cash_oracle(
    tmp_path: Path, fee: str, expected: str
) -> None:
    plugin = create(tmp_path / "crypto.sqlite3")
    assert isinstance(plugin, CryptoExecutionAdapter)
    assert plugin.capabilities().network is False
    assert plugin.capabilities().actual_broker_access == "NOT_IMPLEMENTED"
    first = plugin.submit(intent(fee=fee), expected_revision=0)
    assert first.outcomes[-1].status == "APPLIED"
    bought = plugin.synthetic_execution(fill(fee=fee), expected_revision=1)
    assert bought.book.cash[0].amount == D(9000) - D(fee)
    plugin.submit(
        intent(second=3, side="SELL", order="SELL-1", price="10100", fee=fee),
        expected_revision=2,
    )
    final = plugin.synthetic_execution(
        fill(second=4, order="SELL-1", price="10100", fee=fee), expected_revision=3
    )
    # 10,000 - 0.1*10,000 - fee + 0.1*10,100 - fee.
    assert final.book.cash[0].amount == D(expected)
    assert not plugin.positions()
    assert plugin.get_order("BUY-1").status == "FILLED"
    assert len(plugin.executions()) == 2
    assert len(plugin.events(after_revision=2)) == 2
    assert len(plugin.executions(after_fill=1, limit=1)) == 1


def test_spread_and_slippage_are_separate_actual_costs(tmp_path: Path) -> None:
    plugin = create(tmp_path / "crypto.sqlite3")
    request = replace(intent(), quote=quote(1, "9999", "10001"))
    plugin.submit(request, expected_revision=0)
    event = replace(fill(slip="1"), quote=quote(2, "9999", "10001"))
    result = plugin.synthetic_execution(event, expected_revision=1)
    # Buy ask10001, adverse1bp=1.0001 rounded upward to tick gives10002.01.
    assert result.book.fills[0].price == D("10002.01")
    assert result.book.cash[0].amount == D("8998.799")
    assert result.book.fills[0].adverse_slippage == D(".101")


def test_partial_fill_after_cancel_request_and_confirm_preserves_cash(
    tmp_path: Path,
) -> None:
    plugin = create(tmp_path / "crypto.sqlite3")
    plugin.submit(intent(), expected_revision=0)
    plugin.synthetic_execution(fill(quantity=".04", fee=".4"), expected_revision=1)
    plugin.cancel(
        p.Cancel(
            command_id="cancel-request", at=at(3), order_id="BUY-1", action="REQUEST"
        ),
        expected_revision=2,
    )
    raced = plugin.synthetic_execution(
        fill(second=4, quantity=".02", fee=".2"), expected_revision=3
    )
    assert raced.book.orders[0].filled == D(".06")
    closed = plugin.cancel(
        p.Cancel(
            command_id="cancel-confirm", at=at(5), order_id="BUY-1", action="CONFIRM"
        ),
        expected_revision=4,
    )
    assert closed.book.cash[0].amount == D("9399.4")
    assert plugin.positions()[0].quantity == D(".06")
    assert plugin.get_order("BUY-1").status == "CANCELED"
    assert not closed.reservations


@pytest.mark.parametrize(
    "change",
    [
        "notional",
        "lot",
        "stale",
        "unavailable",
        "spread",
        "foreign_strategy",
        "short",
        "closed",
    ],
)
def test_actual_risk_failures_are_retained_without_economic_changes(
    tmp_path: Path, change: str
) -> None:
    plugin = create(tmp_path / "crypto.sqlite3")
    request = intent()
    if change == "notional":
        request = replace(request, quantity=D(1))
    elif change == "lot":
        request = replace(request, quantity=D(".0001"))
    elif change == "stale":
        request = replace(request, at=at(40), decision_at=at(40))
    elif change == "unavailable":
        request = replace(request, quote=replace(request.quote, available_at=at(2)))
    elif change == "spread":
        request = replace(request, quote=quote(1, "9000", "11000"))
    elif change == "foreign_strategy":
        request = replace(request, strategy_id="STR-UNKNOWN")
    elif change == "short":
        request = replace(request, side="SELL")
    else:
        request = replace(
            request, at=at(86400), decision_at=at(86400), quote=quote(86400)
        )
    result = plugin.submit(request, expected_revision=0)
    assert result.outcomes[-1].status == "REJECTED"
    assert result.book.cash[0].amount == D(10000)
    assert not result.book.fills and not result.reservations
    assert plugin.events()[0].command_id == request.command_id


@pytest.mark.parametrize("order_type", ["LIMIT", "STOP", "MARGIN", "", "market"])
def test_unsupported_orders_and_replacement_have_no_execution_path(
    tmp_path: Path, order_type: str
) -> None:
    plugin = create(tmp_path / "crypto.sqlite3")
    with pytest.raises(CryptoExecutionError, match="UNSUPPORTED_ORDER_TYPE"):
        plugin.submit(intent(), expected_revision=0, order_type=order_type)
    with pytest.raises(CryptoExecutionError, match="REPLACEMENT"):
        plugin.replace()
    assert plugin.account().revision == 0


def test_duplicate_conflicting_and_out_of_order_events(tmp_path: Path) -> None:
    plugin = create(tmp_path / "crypto.sqlite3")
    request = intent()
    plugin.submit(request, expected_revision=0)
    executed = plugin.synthetic_execution(fill(), expected_revision=1)
    assert plugin.submit(request, expected_revision=0) == executed  # no rollback
    with pytest.raises(p.PaperError, match="CONFLICTING_COMMAND_ID"):
        plugin.submit(replace(request, quantity=D(".2")), expected_revision=0)
    with pytest.raises(p.PaperError, match="STALE_REVISION"):
        plugin.submit(intent(order="different"), expected_revision=0)
    rejected = plugin.mark(
        p.Mark(command_id="old", at=at(1), quotes=(quote(1),)), expected_revision=2
    )
    assert rejected.outcomes[-1].status == "REJECTED"
    assert rejected.outcomes[-1].reason == "OUT_OF_ORDER"
    assert rejected.book.cash == executed.book.cash
    assert len(plugin.executions()) == 1


def test_competing_orders_cannot_share_one_risk_revision(tmp_path: Path) -> None:
    plugin = create(tmp_path / "crypto.sqlite3")

    def submit(order: str) -> bool:
        try:
            plugin.submit(intent(order=order, quantity=".4"), expected_revision=0)
            return True
        except p.PaperError as error:
            assert str(error) == "STALE_REVISION"
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, ("one", "two"))) == [False, True]
    assert len(plugin.account().reservations) == 1


class Crash(BaseException):
    pass


def test_restart_after_lost_ack_queries_journal_without_resubmission(
    tmp_path: Path,
) -> None:
    path = tmp_path / "crypto.sqlite3"
    plugin = create(path)

    def crash() -> None:
        raise Crash

    interrupted = OfflineCryptoPlugin(
        p.PaperEngine(path), "CRYPTO-ACCOUNT", "OWNER", after_commit=crash
    )
    with pytest.raises(Crash):
        interrupted.submit(intent(), expected_revision=0)
    restarted = OfflineCryptoPlugin(p.PaperEngine(path), "CRYPTO-ACCOUNT", "OWNER")
    assert restarted.get_order("BUY-1").status == "OPEN"
    assert restarted.account().revision == 1
    assert len(restarted.events()) == 1
    assert plugin.account() == restarted.account()
    reconciled = restarted.reconcile(
        p.Reconcile(
            command_id="reconcile",
            at=at(2),
            cash=D(10000),
            positions=(),
            observation_at=at(2),
        ),
        expected_revision=1,
    )
    assert reconciled.reconciled
    assert len(reconciled.reservations) == 1


def test_native_transaction_rollback_is_not_an_acknowledged_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "crypto.sqlite3"
    create(path)

    def crash() -> None:
        raise Crash

    interrupted = OfflineCryptoPlugin(
        p.PaperEngine(path, before_commit=crash), "CRYPTO-ACCOUNT", "OWNER"
    )
    with pytest.raises(Crash):
        interrupted.submit(intent(), expected_revision=0)
    restarted = OfflineCryptoPlugin(p.PaperEngine(path), "CRYPTO-ACCOUNT", "OWNER")
    assert restarted.account().revision == 0
    with pytest.raises(CryptoExecutionError, match="ORDER_NOT_FOUND"):
        restarted.get_order("BUY-1")


def test_persistent_kill_health_and_reconciliation_refuse_unsafe_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "crypto.sqlite3"
    plugin = create(path)
    plugin.set_health(
        p.Health(command_id="offline", at=at(1), healthy=False), expected_revision=0
    )
    denied = plugin.submit(intent(second=2), expected_revision=1)
    assert denied.outcomes[-1].status == "REJECTED"
    plugin.set_health(
        p.Health(command_id="healthy", at=at(3), healthy=True), expected_revision=2
    )
    plugin.set_kill(
        p.Kill(command_id="kill", at=at(4), enabled=True, reason="LOCAL_FIXTURE_STOP"),
        expected_revision=3,
    )
    restarted = OfflineCryptoPlugin(p.PaperEngine(path), "CRYPTO-ACCOUNT", "OWNER")
    assert restarted.account().killed
    denied = restarted.submit(intent(second=5, order="new"), expected_revision=4)
    assert denied.outcomes[-1].reason == "KILL_ACTIVE"
    mismatch = restarted.reconcile(
        p.Reconcile(
            command_id="drift",
            at=at(6),
            cash=D(9999),
            positions=(),
            observation_at=at(6),
        ),
        expected_revision=5,
    )
    assert not mismatch.reconciled
    reset = restarted.set_kill(
        p.Kill(
            command_id="unsafe-reset", at=at(7), enabled=False, reason="MANUAL_RESET"
        ),
        expected_revision=6,
    )
    assert reset.killed and reset.outcomes[-1].status == "REJECTED"
    restarted.reconcile(
        p.Reconcile(
            command_id="exact",
            at=at(8),
            cash=D(10000),
            positions=(),
            observation_at=at(8),
        ),
        expected_revision=7,
    )
    reset = restarted.set_kill(
        p.Kill(command_id="safe-reset", at=at(8), enabled=False, reason="MANUAL_RESET"),
        expected_revision=8,
    )
    assert not reset.killed
    assert reset.inception_equity == D(10000)


@pytest.mark.parametrize("scope", ["owner", "equity", "historical"])
def test_account_owner_and_mode_are_verified(tmp_path: Path, scope: str) -> None:
    path = tmp_path / "crypto.sqlite3"
    if scope == "owner":
        create(path)
        with pytest.raises(p.PaperError, match="ACCOUNT_NOT_FOUND"):
            OfflineCryptoPlugin(p.PaperEngine(path), "CRYPTO-ACCOUNT", "FOREIGN")
    else:
        with pytest.raises(CryptoExecutionError, match="SYNTHETIC_SPOT_ACCOUNT"):
            create(
                path,
                spec=replace(SPEC, kind="EQUITY") if scope == "equity" else SPEC,
                proof=replace(PROVENANCE, evidence_mode="HISTORICAL_REAL")
                if scope == "historical"
                else PROVENANCE,
            )


@pytest.mark.parametrize(
    ("after", "limit"), [(-1, 1), (True, 1), (1001, 1), (0, 0), (0, 101), (0, True)]
)
def test_event_pages_are_bounded(tmp_path: Path, after: int, limit: int) -> None:
    plugin = create(tmp_path / "crypto.sqlite3")
    with pytest.raises(CryptoExecutionError, match="PAGE_BOUND"):
        plugin.events(after_revision=after, limit=limit)
    with pytest.raises(CryptoExecutionError, match="PAGE_BOUND"):
        plugin.executions(after_fill=after, limit=limit)


def test_closed_command_types_cannot_bypass_risk_admission(tmp_path: Path) -> None:
    plugin = create(tmp_path / "crypto.sqlite3")
    wrong = p.Mark(command_id="wrong", at=at(1), quotes=(quote(1),))
    actions: tuple[Callable[[], p.PaperSnapshot], ...] = (
        lambda: plugin.submit(cast(p.Admit, wrong), expected_revision=0),
        lambda: plugin.synthetic_execution(cast(p.Match, wrong), expected_revision=0),
        lambda: plugin.cancel(cast(p.Cancel, wrong), expected_revision=0),
        lambda: plugin.reconcile(cast(p.Reconcile, wrong), expected_revision=0),
        lambda: plugin.set_kill(cast(p.Kill, wrong), expected_revision=0),
        lambda: plugin.set_health(cast(p.Health, wrong), expected_revision=0),
        lambda: plugin.mark(cast(p.Mark, intent()), expected_revision=0),
    )
    for action in actions:
        with pytest.raises(CryptoExecutionError):
            action()
    assert plugin.account().revision == 0
