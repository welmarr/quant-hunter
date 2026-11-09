"""Independent descriptive-metric oracles from actual persistent native books."""

from __future__ import annotations

from dataclasses import replace
from decimal import Context, Decimal, Inexact, Rounded, localcontext
from pathlib import Path
from typing import cast

import pytest
from test_v0_paper_engine import LIMITS, admit, at, create, match, quote

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.simulation import accounting as a
from quant_hunter.simulation import paper_engine as p
from quant_hunter.simulation.portfolio_metrics import MetricsError, PaperPerformance

D = Decimal


def _record(metric: PaperPerformance, key: str) -> JsonRecord:
    return cast(JsonRecord, metric.to_record()[key])


def _setup(
    tmp_path: Path, limits: p.RiskLimits = LIMITS
) -> tuple[p.PaperEngine, PaperPerformance]:
    engine = create(tmp_path / "paper.sqlite3", limits)
    return engine, PaperPerformance(engine.load("ACCOUNT", "OWNER"))


def _step(
    engine: p.PaperEngine, metric: PaperPerformance, command: p.PaperCommand
) -> p.PaperSnapshot:
    before = engine.load("ACCOUNT", "OWNER")
    state = engine.process("ACCOUNT", "OWNER", command, before.revision)
    metric.observe(state, command)
    return state


def _roundtrip(
    engine: p.PaperEngine,
    metric: PaperPerformance,
    *,
    start: int = 1,
    exit_price: str = "101",
    fee: str = "1",
    prefix: str = "A",
) -> None:
    _step(engine, metric, admit(start, order=prefix + "-BUY", fee=fee))
    _step(engine, metric, match(start + 1, order=prefix + "-BUY", fee=fee))
    _step(
        engine,
        metric,
        admit(
            start + 2, order=prefix + "-SELL", side="SELL", price=exit_price, fee=fee
        ),
    )
    _step(
        engine,
        metric,
        match(start + 3, order=prefix + "-SELL", price=exit_price, fee=fee),
    )


@pytest.mark.parametrize("fee,net", [("1", "8"), ("2", "6")])
def test_independent_cash_return_addback_and_turnover(
    tmp_path: Path, fee: str, net: str
) -> None:
    engine, metric = _setup(tmp_path)
    _roundtrip(engine, metric, fee=fee)
    result = metric.to_record()
    assert result["recorded_equity"] == str(D(10000) + D(net))
    assert D(cast(str, result["net_return"])) == D(net) / 10000
    assert result["net_pnl"] == net
    gross = _record(metric, "gross_cost_addback")
    assert D(cast(str, gross["pnl"])) == 10
    assert D(cast(str, gross["return"])) == D(".001")
    assert gross["frictionless_counterfactual"] is False
    turnover = _record(metric, "turnover")
    assert D(cast(str, turnover["gross_executed_notional"])) == 2010
    assert D(cast(str, turnover["multiple"])) == D(".201")
    trades = _record(metric, "closed_trades")
    assert trades["count"] == trades["wins"] == 1
    assert trades["losses"] == trades["breakeven"] == 0
    assert trades["profit_factor"] is None
    assert trades["profit_factor_reason"] == "NO_LOSS_DENOMINATOR"
    assert trades["small_sample"] is True
    assert trades["predictive_probability"] is None


def test_partial_fills_are_one_completed_episode_with_all_four_fees(
    tmp_path: Path,
) -> None:
    engine, metric = _setup(tmp_path)
    for command in (
        admit(1, fee="2"),
        match(2, quantity="4"),
        match(3, quantity="6"),
        admit(4, side="SELL", order="SELL", price="101", fee="2"),
        match(5, quantity="3", order="SELL", price="101"),
    ):
        _step(engine, metric, command)
    partial = _record(metric, "closed_trades")
    assert partial["count"] == 0 and partial["open_episode_quantity"] == "7"
    assert partial["win_fraction"] is None
    _step(engine, metric, match(6, quantity="7", order="SELL", price="101"))
    trades = _record(metric, "closed_trades")
    assert trades["count"] == 1 and trades["open_episode_quantity"] == "0"
    assert trades["realized_net_pnl"] == "6"
    assert _record(metric, "execution_costs")["commissions"] == "4"


def test_actual_win_loss_breakeven_denominators_and_no_win_probability(
    tmp_path: Path,
) -> None:
    engine, metric = _setup(tmp_path)
    _roundtrip(engine, metric, prefix="WIN")
    _roundtrip(engine, metric, start=5, exit_price="99", prefix="LOSS")
    _roundtrip(engine, metric, start=9, exit_price="100", fee="0", prefix="FLAT")
    trades = _record(metric, "closed_trades")
    assert [trades[k] for k in ("count", "wins", "losses", "breakeven")] == [3, 1, 1, 1]
    with localcontext(Context(prec=38)):
        assert D(cast(str, trades["win_fraction"])) == D(1) / 3
        assert D(cast(str, trades["profit_factor"])) == D(8) / 12
        assert D(cast(str, trades["average_win_loss_ratio"])) == D(8) / 12
    assert trades["realized_net_pnl"] == "-4"
    assert trades["uncertainty"] == "NOT_ESTIMATED_DEPENDENT_SYNTHETIC_SAMPLE"
    assert trades["predictive_probability"] is None
    assert _record(metric, "turnover")["multiple"] == "0.6"


def test_spread_slippage_costs_are_not_subtracted_twice(tmp_path: Path) -> None:
    limits = replace(LIMITS, max_spread_bps=D(500), max_slippage_bps=D(20))
    engine, metric = _setup(tmp_path, limits)
    _step(engine, metric, replace(admit(1), quote=quote(1, "99", ask="101")))
    _step(
        engine,
        metric,
        replace(match(2), quote=quote(2, "99", ask="101"), slippage_bps=D(10)),
    )
    result = metric.to_record()
    # Cash8987.90 + bid value990 =9977.90. Addback: fee1 + slip1.10 + halfspread10.
    assert D(cast(str, result["net_pnl"])) == D("-22.10")
    costs = _record(metric, "execution_costs")
    assert D(cast(str, costs["commissions"])) == 1
    assert D(cast(str, costs["adverse_slippage"])) == D("1.10")
    assert D(cast(str, costs["half_spread_reference"])) == 10
    assert D(cast(str, _record(metric, "gross_cost_addback")["pnl"])) == -10
    assert _record(metric, "closed_trades")["count"] == 0


def _volatility_book(tmp_path: Path) -> tuple[p.PaperEngine, PaperPerformance]:
    engine, metric = _setup(tmp_path)
    _step(engine, metric, admit(1, quantity="100", fee="0"))
    _step(engine, metric, match(2, quantity="100", fee="0"))
    return engine, metric


def test_close_sample_volatility_independent_oracle_ignores_intermediate_commands(
    tmp_path: Path,
) -> None:
    engine, metric = _volatility_book(tmp_path)
    for second, price in ((59, "100"), (90, "109"), (119, "110"), (179, "99")):
        _step(
            engine,
            metric,
            p.Mark(
                command_id=f"MARK-{second}",
                at=at(second),
                quotes=(quote(second, price),),
            ),
        )
    sample = _record(metric, "sampled_volatility")
    assert sample["status"] == "AVAILABLE"
    assert sample["sample_count"] == 3 and sample["return_count"] == 2
    with localcontext(Context(prec=38)):
        # (0.1,-0.1), mean0, sample variance0.02.
        assert D(cast(str, sample["standard_deviation"])) == D(".02").sqrt()
    assert sample["interval_seconds"] == 60 and sample["ddof"] == 1
    assert sample["annualization"] is None


@pytest.mark.parametrize(
    "failure", ["missing", "duplicate", "rejected", "stale_quote", "trailing"]
)
def test_invalid_or_missing_close_observations_do_not_become_volatility(
    tmp_path: Path, failure: str
) -> None:
    engine, metric = _volatility_book(tmp_path)
    _step(engine, metric, p.Mark(command_id="FIRST", at=at(59), quotes=(quote(59),)))
    command: p.PaperCommand
    if failure == "missing":
        command = p.Mark(command_id="GAP", at=at(179), quotes=(quote(179),))
    elif failure == "duplicate":
        command = p.Mark(command_id="DUP", at=at(59), quotes=(quote(59),))
    elif failure == "trailing":
        command = p.Health(command_id="LATER", at=at(119), healthy=False)
    else:
        command = p.Mark(
            command_id="BAD",
            at=at(119),
            quotes=(quote(118 if failure == "stale_quote" else 1),),
        )
    _step(engine, metric, command)
    result = _record(metric, "sampled_volatility")
    assert result["status"] == "UNAVAILABLE" and result["standard_deviation"] is None
    assert result["reason"] in {
        "MISSING_REPEATED_OR_REJECTED_CLOSE_MARK",
        "CLOSE_QUOTE_NOT_CONTEMPORANEOUS",
    }
    if failure == "duplicate":
        _step(
            engine,
            metric,
            p.Mark(command_id="LATER_VALID", at=at(119), quotes=(quote(119),)),
        )
        assert _record(metric, "sampled_volatility")["standard_deviation"] is None


def test_genesis_and_constant_returns_have_explicit_different_sample_status(
    tmp_path: Path,
) -> None:
    engine, metric = _setup(tmp_path)
    assert _record(metric, "sampled_volatility")["standard_deviation"] is None
    for second in (59, 119, 179):
        _step(
            engine,
            metric,
            p.Mark(command_id=f"M{second}", at=at(second), quotes=(quote(second),)),
        )
    sample = _record(metric, "sampled_volatility")
    assert (
        sample["status"] == "AVAILABLE"
        and D(cast(str, sample["standard_deviation"])) == 0
    )
    assert _record(metric, "closed_trades")["win_fraction"] is None


def test_unsupported_corporate_attribution_keeps_recorded_equity_not_fake_trade_zeros(
    tmp_path: Path,
) -> None:
    engine, metric = _setup(tmp_path)
    command = p.Mark(command_id="M", at=at(1), quotes=(quote(1),))
    state = engine.process("ACCOUNT", "OWNER", command, 0)
    # Pure adapter contract for a future verified action-bearing native producer.
    state = replace(
        state,
        book=replace(
            state.book,
            corporate_actions=(a.CorporateAction("SPLIT", "INS-1", "SPLIT", at(1)),),
        ),
    )
    metric.observe(state, command)
    result = metric.to_record()
    assert result["recorded_equity"] == "10000"
    trade = _record(metric, "closed_trades")
    assert trade["status"] == "UNAVAILABLE"
    assert trade["count"] is trade["wins"] is trade["win_fraction"] is None


def test_replay_projection_binds_identity_order_and_atomic_refusals(
    tmp_path: Path,
) -> None:
    engine, metric = _setup(tmp_path)
    command = admit()
    state = engine.process("ACCOUNT", "OWNER", command, 0)
    original = metric.to_record()
    for changed in (
        replace(state, owner_id="OTHER"),
        replace(state, account_id="OTHER"),
        replace(state, revision=2),
        replace(state, inception_equity=D(1)),
        replace(state, equity=D("NaN")),
        replace(state, at=at(-1)),
    ):
        with pytest.raises(MetricsError):
            metric.observe(changed, command)
        assert metric.to_record() == original
    metric.observe(state, command)
    with pytest.raises(MetricsError, match="BINDING"):
        metric.observe(state, command)


def test_denied_match_retained_as_rejection_not_trade(tmp_path: Path) -> None:
    engine, metric = _setup(tmp_path)
    state = _step(engine, metric, match())
    assert state.outcomes[-1].status == "REJECTED"
    assert metric.to_record()["rejected_commands"] == 1
    assert _record(metric, "closed_trades")["count"] == 0
    assert _record(metric, "turnover")["multiple"] == "0"


def test_projection_is_identical_under_hostile_decimal_context(tmp_path: Path) -> None:
    engine, reference = _setup(tmp_path)
    hostile = PaperPerformance(engine.load("ACCOUNT", "OWNER"))
    for command in (
        admit(),
        match(),
        admit(3, side="SELL", order="SELL", price="101"),
        match(4, order="SELL", price="101"),
    ):
        state = _step(engine, reference, command)
        with localcontext(Context(prec=2, Emin=-2, Emax=2)) as context:
            context.traps[Inexact] = context.traps[Rounded] = True
            hostile.observe(state, command)
            raw = canonicalize_json(hostile.to_record())
        assert raw == canonicalize_json(reference.to_record())


@pytest.mark.parametrize(
    "interval,offset", [(0, 0), (True, 0), (60, 60), (60, -1), (86401, 0)]
)
def test_invalid_sampling_configuration_rejected(
    tmp_path: Path, interval: int, offset: int
) -> None:
    engine = create(tmp_path / "paper.sqlite3")
    with pytest.raises(MetricsError, match="SAMPLING"):
        PaperPerformance(
            engine.load("ACCOUNT", "OWNER"),
            interval_seconds=interval,
            close_offset_seconds=offset,
        )


@pytest.mark.parametrize(
    "changed", ["revision", "zero", "negative", "huge", "precision", "not_synthetic"]
)
def test_genesis_and_numeric_bounds_are_not_inferred(
    tmp_path: Path, changed: str
) -> None:
    engine = create(tmp_path / "paper.sqlite3")
    genesis = engine.load("ACCOUNT", "OWNER")
    if changed == "revision":
        genesis = replace(genesis, revision=1)
    elif changed == "not_synthetic":
        genesis = replace(
            genesis, provenance=replace(genesis.provenance, evidence_mode="HISTORICAL")
        )
    else:
        value = {
            "zero": D(0),
            "negative": D(-1),
            "huge": D("1e31"),
            "precision": D("1e-77"),
        }[changed]
        genesis = replace(genesis, inception_equity=value)
    with pytest.raises(MetricsError):
        PaperPerformance(genesis)


def test_mixed_currency_aggregation_is_unavailable_not_a_sum(tmp_path: Path) -> None:
    engine = create(tmp_path / "paper.sqlite3")
    genesis = engine.load("ACCOUNT", "OWNER")
    alternate = replace(
        genesis, book=replace(genesis.book, cash=(a.CashBalance("EUR", D(10000)),))
    )
    metric = PaperPerformance(alternate)
    for name in ("gross_cost_addback", "execution_costs", "turnover", "closed_trades"):
        assert _record(metric, name)["status"] == "UNAVAILABLE"
    assert _record(metric, "execution_costs")["commissions"] is None
    assert _record(metric, "turnover")["gross_executed_notional"] is None
    assert metric.to_record()["recorded_equity"] == "10000"


@pytest.mark.parametrize(
    "changed", ["missing_fill", "commission", "price", "quote", "order", "short"]
)
def test_fill_economic_contradictions_refuse_atomically(
    tmp_path: Path, changed: str
) -> None:
    engine, metric = _setup(tmp_path)
    _step(engine, metric, admit())
    command = match()
    state = engine.process("ACCOUNT", "OWNER", command, 1)
    fill = state.book.fills[-1]
    if changed == "missing_fill":
        state = replace(state, book=replace(state.book, fills=()))
    elif changed == "quote":
        command = replace(command, quote=quote(2, "99"))
    elif changed == "order":
        state = replace(state, book=replace(state.book, orders=()))
    elif changed == "short":
        state = replace(
            state,
            book=replace(
                state.book, orders=(replace(state.book.orders[0], side="SELL"),)
            ),
        )
    else:
        fill = (
            replace(fill, commission=D(-1))
            if changed == "commission"
            else replace(fill, price=D(99))
        )
        state = replace(state, book=replace(state.book, fills=(fill,)))
    before = metric.to_record()
    with pytest.raises(MetricsError):
        metric.observe(state, command)
    assert metric.to_record() == before


def test_corporate_history_never_contributes_guessed_episode_pnl(
    tmp_path: Path,
) -> None:
    engine, metric = _setup(tmp_path)
    _step(engine, metric, admit())
    command = match()
    state = engine.process("ACCOUNT", "OWNER", command, 1)
    state = replace(
        state,
        book=replace(
            state.book,
            corporate_actions=(a.CorporateAction("SPLIT", "INS-1", "SPLIT", at(0)),),
        ),
    )
    metric.observe(state, command)
    assert _record(metric, "closed_trades")["realized_net_pnl"] is None
    assert _record(metric, "execution_costs")["commissions"] == "1"
    assert metric.to_record()["recorded_equity"] == "9999"


def test_nonpositive_sample_preserves_equity_but_refuses_return_volatility(
    tmp_path: Path,
) -> None:
    engine, metric = _setup(tmp_path)
    command = p.Mark(command_id="M", at=at(59), quotes=(quote(59),))
    state = engine.process("ACCOUNT", "OWNER", command, 0)
    metric.observe(replace(state, equity=D(0)), command)
    assert metric.to_record()["recorded_equity"] == "0"
    assert _record(metric, "sampled_volatility")["status"] == "UNAVAILABLE"
    assert (
        _record(metric, "sampled_volatility")["reason"] == "NONPOSITIVE_SAMPLED_EQUITY"
    )
