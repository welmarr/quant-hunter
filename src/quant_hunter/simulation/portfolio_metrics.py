"""Bounded descriptive metrics over caller-verified native replay observations.

This module neither loads nor verifies a journal and grants no research/execution
authority. The host must provide the exact genesis and each already verified
command/state pair through its last immutable reported revision.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, localcontext

from quant_hunter.config import JsonRecord
from quant_hunter.simulation import accounting as a
from quant_hunter.simulation import paper_engine as p

ZERO = Decimal(0)


class MetricsError(ValueError):
    """An invalid, inconsistent or unsupported bounded projection input."""


def _number(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise MetricsError("INVALID_METRIC_NUMBER")
    exponent = value.as_tuple().exponent
    if (
        not isinstance(exponent, int)
        or not -76 <= exponent <= 38
        or len(value.as_tuple().digits) > 76
        or value.copy_abs() > Decimal("1e30")
    ):
        raise MetricsError("METRIC_NUMBER_BOUND")


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class _Totals:
    commission: Decimal = ZERO
    slippage: Decimal = ZERO
    half_spread: Decimal = ZERO
    notional: Decimal = ZERO
    quantity: Decimal = ZERO
    episode_cashflow: Decimal = ZERO
    closed_pnls: tuple[Decimal, ...] = ()
    marks: tuple[tuple[datetime, Decimal], ...] = ()
    returns: tuple[Decimal, ...] = ()
    volatility_reason: str | None = None
    trade_reason: str | None = None
    cost_reason: str | None = None
    rejected_commands: int = 0


class PaperPerformance:
    """Incremental single-currency long cash metrics; O(MAX_COMMANDS) storage.

    Sampling configuration is frozen by the caller, never inferred from results.
    Close marks lie at inception + close_offset_seconds + n*interval_seconds.
    Rejecting a close, skipping a close or repeating it makes volatility
    unavailable; missing observations are never interpolated or annualized.
    """

    def __init__(
        self,
        genesis: p.PaperSnapshot,
        *,
        interval_seconds: int = 60,
        close_offset_seconds: int = 59,
    ) -> None:
        if (
            type(interval_seconds) is not int
            or not 1 <= interval_seconds <= 86400
            or type(close_offset_seconds) is not int
            or not 0 <= close_offset_seconds < interval_seconds
        ):
            raise MetricsError("INVALID_FROZEN_SAMPLING")
        if (
            not isinstance(genesis, p.PaperSnapshot)
            or genesis.revision != 0
            or genesis.outcomes
            or genesis.book.fills
            or genesis.provenance.evidence_mode != "SYNTHETIC"
        ):
            raise MetricsError("EXACT_SYNTHETIC_GENESIS_REQUIRED")
        _number(genesis.inception_equity)
        _number(genesis.equity)
        if genesis.inception_equity <= 0:
            raise MetricsError("POSITIVE_INCEPTION_CAPITAL_REQUIRED")
        a._utc(genesis.at)
        self.genesis = genesis
        self._last = genesis
        self.interval_seconds = interval_seconds
        self.close_offset_seconds = close_offset_seconds
        reason = None
        if (
            len(genesis.book.instruments) != 1
            or any(
                instrument.quote_currency != genesis.book.base_currency
                for instrument in genesis.book.instruments
            )
            or any(c.currency != genesis.book.base_currency for c in genesis.book.cash)
        ):
            reason = "UNSUPPORTED_MULTI_INSTRUMENT_OR_CURRENCY_PROFILE"
        self._totals = _Totals(
            trade_reason=reason
            or ("NONEMPTY_GENESIS_HOLDINGS" if genesis.book.positions else None),
            cost_reason=reason,
        )

    def observe(self, snapshot: p.PaperSnapshot, command: p.PaperCommand) -> None:
        """Consume one verified successor atomically; failure changes no metric state."""
        if (
            type(command) not in p.COMMAND_TYPES
            or not isinstance(snapshot, p.PaperSnapshot)
            or snapshot.revision != self._last.revision + 1
            or snapshot.revision > p.MAX_COMMANDS
            or len(snapshot.outcomes) != snapshot.revision
            or snapshot.outcomes[:-1] != self._last.outcomes
            or snapshot.outcomes[-1].command_id != command.command_id
            or snapshot.outcomes[-1].status not in {"APPLIED", "REJECTED"}
            or snapshot.account_id != self.genesis.account_id
            or snapshot.owner_id != self.genesis.owner_id
            or snapshot.provenance != self.genesis.provenance
            or snapshot.inception_equity != self.genesis.inception_equity
            or snapshot.book.instruments != self.genesis.book.instruments
            or snapshot.book.base_currency != self.genesis.book.base_currency
            or snapshot.at < self._last.at
            or snapshot.book.fills[: len(self._last.book.fills)]
            != self._last.book.fills
        ):
            raise MetricsError("REPLAY_OBSERVATION_BINDING")
        a._utc(snapshot.at)
        a._utc(command.at)
        _number(snapshot.equity)
        with localcontext(a.CONTEXT):
            updated = self._observe(snapshot, command)
        self._last, self._totals = snapshot, updated

    def _observe(self, snapshot: p.PaperSnapshot, command: p.PaperCommand) -> _Totals:
        totals = self._totals
        applied = snapshot.outcomes[-1].status == "APPLIED"
        if not applied:
            totals = replace(totals, rejected_commands=totals.rejected_commands + 1)
        if (
            snapshot.book.corporate_actions
            or snapshot.book.dividends
            or snapshot.book.liquidations
        ):
            totals = replace(
                totals, trade_reason="CORPORATE_ACTION_TRADE_ATTRIBUTION_UNAVAILABLE"
            )
        added = snapshot.book.fills[len(self._last.book.fills) :]
        if len(added) != (1 if isinstance(command, p.Match) and applied else 0):
            raise MetricsError("FILL_COMMAND_BINDING")
        if added:
            totals = self._fill(totals, snapshot, command, added[0])
        if isinstance(command, p.Mark):
            totals = self._mark(totals, snapshot, command, applied)
        return totals

    def _fill(
        self,
        totals: _Totals,
        snapshot: p.PaperSnapshot,
        command: p.PaperCommand,
        fill: a.Fill,
    ) -> _Totals:
        if not isinstance(command, p.Match):
            raise MetricsError("FILL_COMMAND_BINDING")
        order = next(
            (o for o in snapshot.book.orders if o.order_id == fill.order_id), None
        )
        for value in (
            fill.quantity,
            fill.price,
            fill.market_price,
            fill.commission,
            fill.adverse_slippage,
            command.quote.bid,
            command.quote.ask,
        ):
            _number(value)
        if (
            order is None
            or order.side not in {"BUY", "SELL"}
            or fill.order_id != command.order_id
            or fill.at != command.at
            or fill.quantity != command.quantity
            or fill.commission != command.commission
            or fill.quantity <= 0
            or fill.price <= 0
            or fill.commission < 0
            or fill.adverse_slippage < 0
            or command.quote.bid <= 0
            or command.quote.ask < command.quote.bid
            or command.quote.instrument_id != order.instrument_id
            or fill.market_price
            != (command.quote.ask if order.side == "BUY" else command.quote.bid)
            or fill.adverse_slippage
            != abs(fill.price - fill.market_price) * fill.quantity
        ):
            raise MetricsError("FILL_ECONOMIC_BINDING")
        notional = fill.quantity * fill.price
        updated = replace(
            totals,
            commission=totals.commission + fill.commission,
            slippage=totals.slippage + fill.adverse_slippage,
            half_spread=totals.half_spread
            + fill.quantity * (command.quote.ask - command.quote.bid) / 2,
            notional=totals.notional + notional,
        )
        if updated.trade_reason is not None:
            return updated
        quantity = totals.quantity + (
            fill.quantity if order.side == "BUY" else -fill.quantity
        )
        if quantity < 0:
            raise MetricsError("UNSUPPORTED_SHORT_TRADE")
        cashflow = totals.episode_cashflow + (
            -notional - fill.commission
            if order.side == "BUY"
            else notional - fill.commission
        )
        return replace(
            updated,
            quantity=quantity,
            episode_cashflow=cashflow if quantity else ZERO,
            closed_pnls=totals.closed_pnls + ((cashflow,) if quantity == 0 else ()),
        )

    def _mark(
        self, totals: _Totals, snapshot: p.PaperSnapshot, command: p.Mark, applied: bool
    ) -> _Totals:
        delta = command.at - self.genesis.at
        micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
        offset = self.close_offset_seconds * 1_000_000
        interval = self.interval_seconds * 1_000_000
        if micros < offset or (micros - offset) % interval:
            return totals
        sample_index = (micros - offset) // interval
        if not applied or sample_index != len(totals.marks):
            return replace(
                totals, volatility_reason="MISSING_REPEATED_OR_REJECTED_CLOSE_MARK"
            )
        if totals.volatility_reason:
            return totals
        if any(
            not any(
                quote.instrument_id == instrument.instrument_id
                and quote.at == command.at
                and quote.available_at <= command.at
                for quote in command.quotes
            )
            for instrument in snapshot.book.instruments
        ):
            return replace(totals, volatility_reason="CLOSE_QUOTE_NOT_CONTEMPORANEOUS")
        if snapshot.equity <= 0:
            return replace(totals, volatility_reason="NONPOSITIVE_SAMPLED_EQUITY")
        returns = totals.returns
        if totals.marks:
            returns += (snapshot.equity / totals.marks[-1][1] - 1,)
        return replace(
            totals,
            marks=(*totals.marks, (command.at, snapshot.equity)),
            returns=returns,
        )

    def to_record(self) -> JsonRecord:
        """Return descriptive values; unavailable quantities are null with reasons."""
        with localcontext(a.CONTEXT):
            return self._record()

    def _record(self) -> JsonRecord:
        totals, state = self._totals, self._last
        initial = self.genesis.inception_equity
        pnl = state.equity - initial
        costs = totals.commission + totals.slippage + totals.half_spread
        count = len(totals.returns)
        elapsed = state.at - self.genesis.at
        micros = (
            elapsed.days * 86400 + elapsed.seconds
        ) * 1_000_000 + elapsed.microseconds
        due_samples = max(
            0,
            (micros - self.close_offset_seconds * 1_000_000)
            // (self.interval_seconds * 1_000_000)
            + 1,
        )
        vol_reason = (
            totals.volatility_reason
            or (
                "MISSING_REPEATED_OR_REJECTED_CLOSE_MARK"
                if due_samples != len(totals.marks)
                else None
            )
            or ("AT_LEAST_TWO_CLOSE_TO_CLOSE_RETURNS_REQUIRED" if count < 2 else None)
        )
        volatility = None
        if vol_reason is None:
            mean = sum(totals.returns, ZERO) / count
            volatility = (
                sum(((r - mean) ** 2 for r in totals.returns), ZERO) / (count - 1)
            ).sqrt()
        wins = [v for v in totals.closed_pnls if v > 0]
        losses = [v for v in totals.closed_pnls if v < 0]
        trade_count = len(totals.closed_pnls)
        profit_factor = sum(wins, ZERO) / -sum(losses, ZERO) if losses else None
        payoff = (
            (sum(wins, ZERO) / len(wins)) / (-sum(losses, ZERO) / len(losses))
            if wins and losses
            else None
        )
        trade_available = totals.trade_reason is None
        return {
            "format": "v0-paper-performance-1",
            "algorithm_id": "CASH_EPISODES_CLOSE_SAMPLE_COST_ADDBACK_V1",
            "evidence_mode": "SYNTHETIC",
            "input_authority": "CALLER_VERIFIED_NATIVE_REPLAY_REQUIRED",
            "engine_revision": state.revision,
            "at": _stamp(state.at),
            "recorded_equity": str(state.equity),
            "net_pnl": str(pnl),
            "net_return": str(pnl / initial),
            "return_basis": "RECORDED_NATIVE_EQUITY_OVER_INCEPTION_CAPITAL_NO_EXTERNAL_FLOWS",
            "gross_cost_addback": {
                "status": "AVAILABLE" if totals.cost_reason is None else "UNAVAILABLE",
                "reason": totals.cost_reason,
                "pnl": str(pnl + costs) if totals.cost_reason is None else None,
                "return": str((pnl + costs) / initial)
                if totals.cost_reason is None
                else None,
                "basis": "ADD_BACK_FILL_COMMISSIONS_ADVERSE_SLIPPAGE_AND_HALF_SPREAD_REFERENCE_ON_IDENTICAL_FILLS_AND_MARKS",
                "frictionless_counterfactual": False,
            },
            "execution_costs": {
                "status": "AVAILABLE" if totals.cost_reason is None else "UNAVAILABLE",
                "reason": totals.cost_reason,
                "commissions": str(totals.commission)
                if totals.cost_reason is None
                else None,
                "adverse_slippage": str(totals.slippage)
                if totals.cost_reason is None
                else None,
                "half_spread_reference": str(totals.half_spread)
                if totals.cost_reason is None
                else None,
                "basis": "FEES_SEPARATE;_SLIPPAGE_AND_SPREAD_ALREADY_IN_EXECUTED_PRICES_NOT_SUBTRACTED_AGAIN",
            },
            "turnover": {
                "status": "AVAILABLE" if totals.cost_reason is None else "UNAVAILABLE",
                "reason": totals.cost_reason,
                "gross_executed_notional": str(totals.notional)
                if totals.cost_reason is None
                else None,
                "multiple": str(totals.notional / initial)
                if totals.cost_reason is None
                else None,
                "basis": "SUM_ABSOLUTE_EXECUTED_NOTIONAL_OVER_INCEPTION_CAPITAL_BOTH_SIDES_NO_HALVING",
            },
            "sampled_volatility": {
                "status": "AVAILABLE" if vol_reason is None else "UNAVAILABLE",
                "reason": vol_reason,
                "standard_deviation": str(volatility)
                if volatility is not None
                else None,
                "sample_count": len(totals.marks),
                "return_count": count,
                "interval_seconds": self.interval_seconds,
                "close_offset_seconds": self.close_offset_seconds,
                "ddof": 1,
                "basis": "EQUALLY_SPACED_SUCCESSFUL_CLOSE_MARK_SIMPLE_RETURNS",
                "annualization": None,
            },
            "closed_trades": {
                "status": "AVAILABLE" if trade_available else "UNAVAILABLE",
                "reason": totals.trade_reason,
                "basis": "COMPLETE_FLAT_TO_FLAT_LONG_CASH_EPISODES_ALL_PARTIAL_FILL_COSTS",
                "count": trade_count if trade_available else None,
                "wins": len(wins) if trade_available else None,
                "losses": len(losses) if trade_available else None,
                "breakeven": trade_count - len(wins) - len(losses)
                if trade_available
                else None,
                "win_fraction": str(Decimal(len(wins)) / trade_count)
                if trade_available and trade_count
                else None,
                "win_fraction_reason": None
                if trade_available and trade_count
                else totals.trade_reason or "NO_CLOSED_TRADES",
                "profit_factor": str(profit_factor)
                if trade_available and profit_factor is not None
                else None,
                "profit_factor_reason": totals.trade_reason
                or (None if losses else "NO_LOSS_DENOMINATOR"),
                "average_win_loss_ratio": str(payoff)
                if trade_available and payoff is not None
                else None,
                "average_win_loss_reason": totals.trade_reason
                or (None if wins and losses else "BOTH_WINS_AND_LOSSES_REQUIRED"),
                "realized_net_pnl": str(sum(totals.closed_pnls, ZERO))
                if trade_available
                else None,
                "open_episode_quantity": str(totals.quantity)
                if trade_available
                else None,
                "small_sample": trade_count < 30 if trade_available else None,
                "uncertainty": "NOT_ESTIMATED_DEPENDENT_SYNTHETIC_SAMPLE",
                "predictive_probability": None,
            },
            "rejected_commands": totals.rejected_commands,
            "limitations": [
                "Descriptive synthetic software diagnostics, not empirical performance or scientific approval",
                "Recorded marks may be stale after controls; host current valuation separately checks freshness",
                "Gross addback preserves actual fills and terminal bid marks; it is not a rerun without costs",
                "No annualization, Sharpe, Sortino, CAGR or dependent-trade confidence interval is invented",
                "The small-sample flag at fewer than30 episodes is a display warning, not a sufficiency threshold",
            ],
        }
