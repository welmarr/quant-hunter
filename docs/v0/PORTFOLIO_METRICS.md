# Descriptive metrics from verified paper replay

`simulation.portfolio_metrics.PaperPerformance` is a pure, incremental projection.
It cannot read a file, publish a result, create a research attempt, submit a
command, access a credential or send a request. Its caller must first verify the
native journal, original source/configuration/instrument identities and immutable
reported revision using the existing portfolio reader. This module's internal
shape/sequence checks are not a replacement for that authority.

Construct `PaperPerformance(genesis, interval_seconds=60,
close_offset_seconds=59)` from the real revision-zero native state. During the
existing verified replay call `observe(snapshot, command)` once for each exact
successor, and finally `to_record()`. Do not feed unreported later native states.
The projection accepts at most the native 1000-command bound, retains at most that
many return/episode observations and uses the accounting context's precision38
independently of ambient Decimal precision, exponent limits or traps. A refused
observation leaves its projection state unchanged. All output Decimal values are
JSON strings; unavailable quantities are null with an explicit reason.

The `v0-paper-performance-1` format and
`CASH_EPISODES_CLOSE_SAMPLE_COST_ADDBACK_V1` algorithm identify the reader's math.
Root integration should retain the executing projection source identity alongside
the original economic producer. The original Item8 result, source archive and
native journal are unchanged. Historical supported native-v1 producers remain
inspectable; new diagnostics are not retrospectively preregistered research
criteria or a rewrite of their original results.

## Return and cost conventions

Net P&L is last recorded engine equity minus positive inception equity; net
return divides by that inception capital. This closed native paper profile has
no external deposits or withdrawals. After a control, recorded equity may carry
an earlier valuation: the host's separate current valuation must retain its
freshness status. These returns do not invent an executable terminal liquidation.

`gross_cost_addback` adds actual fill commissions, actual adverse price slippage
and the contemporaneous half-spread reference to net P&L. It preserves exactly
the actual fills, quantities, cash path and final bid marks. It is **not** a
frictionless counterfactual rerun: costs can affect cash/risk admission and which
fills occurred. Slippage and spread already enter executed prices and are never
subtracted a second time. Half-spread means filled quantity times (ask-bid)/2,
with midpoint used solely as an attribution reference, never an executable price.
This does not add back hypothetical liquidation, fund expenses, tax or borrowing.

Turnover is the sum of absolute executed quantity times executed price divided by
inception capital. Both purchases and sales count, with no halving. This fixed
capital convention differs from a turnover measure divided by average equity;
the output states the exact basis. Incompatible instrument/currency profiles
leave cost and turnover aggregations unavailable instead of summing unlike units.

## Sampling and completed trades

Volatility uses simple close-to-close recorded-equity returns at the frozen
inception + offset + n*interval grid. Each included observation must come from a
successful native Mark with contemporaneous effective and available quotes for
every instrument. Intermediate opens, fills, admissions and controls are not
additional samples. Missing, repeated, rejected, stale-quote or nonpositive
close marks make volatility unavailable; no gap filling or opportunistic
segmentation occurs. At least three close marks (two returns) are needed for a
sample standard deviation with ddof1. A constant valid sequence has zero
volatility. The period is explicit in seconds and annualization is absent.

Closed-trade statistics refer to complete long cash **flat-to-flat episodes**.
Each partial purchase/sale contributes its actual executed cashflow and fee.
Scaling in or out stays within that episode until units return to exactly zero;
an unfinished holding is reported separately and is not a closed win. Positive,
negative and zero net episode cashflows are wins, losses and breakeven episodes.
The descriptive win fraction includes all completed episodes in its denominator.
Profit factor divides total positive episode P&L by absolute total negative P&L;
the average-win/loss ratio divides their respective means. Missing denominators
produce null, never infinity or a fabricated zero. Corporate-action histories
leave episode attribution unavailable while retaining recorded equity; this
initial projection does not reconstruct action-adjusted trade lots.

The fewer-than30 episode flag is a display warning, not a sufficiency rule.
Trades are dependent and synthetic: no binomial interval, calibrated win
probability or confidence in future profitability is implied.
`uncertainty=NOT_ESTIMATED_DEPENDENT_SYNTHETIC_SAMPLE` and
`predictive_probability=null` make that limitation explicit. Sharpe, Sortino,
CAGR and annualized volatility are not invented from this short intraday fixture.

## Software evidence

Tests use the actual SQLite PaperEngine and independent cash arithmetic. The
10000→10008 roundtrip gives net return0.0008 and commission addback gross0.001;
doubled fees yield10006 with the same gross addback. Four partial fill fees produce
one completed episode with net6. A spread/slippage example preserves the terminal
bid mark, demonstrating that addback is not a frictionless portfolio. Actual
sample returns(0.1,-0.1) give sample variance0.02. Additional cases cover missing
or stale samples, rejected commands, open trades, zero denominators, incompatible
profiles, sequence/identity faults and hostile Decimal contexts. These software
oracles do not validate a strategy empirically or satisfy a scientific gate.

Final author gate:36tests passed with warnings treated as errors in3.06s;
98.91% combined statement/branch coverage, Ruff format/check and strict mypy
passed for both Python files. The earlier21-test gate passed its arithmetic
checks but failed the required90% coverage threshold at88.04%; the subsequent
hostile cases closed that gap. A test-only obsolete Health keyword and a test
typing error were corrected without changing native economics. Independent peer
execution, root's actual portfolio wiring and the full integration gate remain
separate evidence.
