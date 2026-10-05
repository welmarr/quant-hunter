# V0 accounting core and independent oracles

`simulation/accounting.py` is a deterministic, pure transition core for bounded
local-paper accounting. It does not fetch data, create an account, hold secrets,
persist state, place broker orders, register experiments or grant scientific
authority. All test prices and events are **SYNTHETIC**. A passing arithmetic test
is not empirical execution evidence, an operational readiness claim, or a stage
promotion. The original four-bar engine and its conventions remain unchanged.

## Implemented contract

`initial_book(base_currency, at, instruments, cash)` creates a frozen
`BookSnapshot`. Instrument IDs are distinct from symbols. Every `InstrumentSpec`
supplies a quote currency, lot, tick and explicit, nonoverlapping UTC
`TradingWindow` intervals. FX/crypto spot also supplies a distinct base currency.
The calendar is caller-provided evidence; no exchange holiday calendar is
invented or certified. Session intervals are half-open: open is included, close
is excluded. Quantity admission requires an exact lot multiple. Unsupported
short, leverage and derivative execution fail explicitly.

`apply_event(book, event)` returns a new frozen snapshot or raises
`AccountingError` without changing the original. Events require a bounded
`event_id`, `expected_version` and `datetime.UTC` timestamp. New events are ordered
by timestamp and admitted only against the current snapshot version. Equal
timestamps use the supplied event order, with an additional corporate-action
precedence rule below. The core retains the typed event's SHA-256 digest and
increments the version exactly once. Exact duplicate replay returns the **current**
snapshot, including all later events; it never rolls back to an older result.
Conflicting identity reuse and stale compare-and-swap versions are rejected.

Digest identity includes the event type, all fields, expected version, UTC
timestamp strings and exact Decimal string representation. Thus `1` and `1.0`
are distinct payloads even when economically equal. This operational digest is
not a canonical registry ID, RFC8785 identity or scientific evidence digest.
The root integration must retain actual event payloads, exact code/configuration
and a verified initial snapshot in its immutable journal. Dataclass construction
and an arbitrary caller-supplied snapshot do not authenticate account truth.

The retained snapshot contains currency balances, positions with quote-currency
cost basis, orders, fills, dividend entitlements/payments, corporate-action
markers, liquidation records, delisted IDs and event receipts. Transitions use
Decimal precision38 with HALF_EVEN, independent of the caller's decimal context.
Inputs allow at most18 digits and exponents−18 through18; numerical results are
bounded to38 digits, exponents−76 through38 and magnitude1e30. No cash rounding
to cents or silent quantity rounding occurs. Currency settlement precision,
taxation and an explicit cash-in-lieu policy remain separate required work.

The bounded profile permits128 instruments,32 currency balances,2,048 session
windows per instrument and10,000 accepted events. This is an in-memory arithmetic
profile, not a scalable persistent ledger. Root must implement durable atomic
event/snapshot publication, independent integrity/replay checks, serialized risk
reservations, restart recovery, reconciliation and kill-switch policy before
claiming a working continuous execution service. Immutable Python records do not
replace those controls or the canonical Item8 experiment lifecycle.

## Orders, fills, costs and valuation

Supported events are `SubmitOrder`, `FillOrder`, `RequestCancel`, `ConfirmCancel`,
`RejectOrder`, `Split`, `Dividend`, `PayDividend`, `CashLiquidation`,
`FinancingCharge` and `ConvertCash`. Market orders are the only implemented order
type. Closed-market and delisted admission produces a retained `REJECTED` order.
Malformed, unsupported or unsafe transitions raise; root must retain their failed
attempts separately because a rejected transition cannot publish a new book.

BUY uses ask; SELL uses bid. A fill quote must be strictly later than its order's
decision, and the fill event strictly later than submission. Quote availability
must be causal and no later than execution; quote age has an explicit bound up
to86,400 seconds. Both quote prices must satisfy the instrument tick. Adverse
slippage is an explicit basis-point parameter. Executions round adversely to a
tick—up for buys, down for sells. The fill records quoted market side, execution
price, slippage amount, commission and realized P&L. Spread is already reflected
in cash through bid/ask and is never subtracted again. A commission is charged
per supplied fill, so splitting an order can change fixed per-fill costs.

Partial fills preserve remaining quantity. A fill may arrive while cancellation
is pending; an incomplete fill keeps `CANCEL_PENDING`. A full fill wins the race,
and a later genuine cancellation acknowledgement records `CANCEL_TOO_LATE`
without reversing cash or inventory. A cancellation acknowledgement requires a
prior request. After cancellation is confirmed, further fills fail. This is a
chronological local-paper policy; delayed/out-of-order external venue reports
require separate reconciliation and cannot be silently discarded as harmless.

Positions are long and fully cash-funded in their quote currency. Buys include
commission in cost basis; partial sales allocate average cost proportionally,
with the final sale taking the exact remaining basis. Cash cannot go negative.
Concurrent pending orders do not reserve cash here: the root atomic admission
layer must do that. Each actual fill still checks current cash/inventory and
cannot overspend or oversell. Fill sizes are explicit inputs, with no claim of
available volume, queue priority, market impact or empirical liquidity.

`value_book(book, marks, fx_quotes, as_of=..., max_quote_age_seconds=...)` returns
cash, holdings, unpaid receivables and equity in the portfolio base currency.
It marks long holdings at fresh executable bid, excludes hypothetical disposal
commissions, and rejects missing/ambiguous FX or instrument quotes. This is a
conservative executable-side valuation convention, not an assertion that all
holdings could simultaneously liquidate at displayed size. Final positions are
not automatically sold.

`FinancingCharge` requires an explicit amount, currency, completed start/end
period and `EXPLICIT_SPOT_FINANCING_CHARGE` treatment. It debits available cash;
there is no implicit zero financing, automatic rate accrual, borrowing, tax or
cash interest. The caller must bind each relevant cost treatment and assumptions
to the governed simulation configuration. The standalone core's existence does
not satisfy a missing Item9C/V6 cost inventory or realism assessment.

## Corporate actions and directed FX

A split requires a positive exact Decimal ratio, known availability by its
effective event, unadjusted price basis and explicit `CANCEL_OPEN` order policy.
The quantity is multiplied and total cost basis preserved. Open local orders are
canceled, not silently rescaled. Fractional lot results fail until an explicit
cash-in-lieu policy exists. A second split at the same instrument/effective time
is refused, including under a different event ID. A split never credits cash.

The `Dividend` event runs at the ex-date event, snapshots held-share entitlement
and creates a receivable. `PayDividend` can transfer it to cash only at or after
the separately declared payment time. Selling after ex-date preserves the
entitlement; buying after ex-date does not enlarge it. Reusing a dividend ID
cannot create or pay the entitlement twice. No withholding, reclaim, stock
dividend or return-of-capital treatment is implemented.

Corporate actions must precede their instrument's orders and fills at the same
effective timestamp. An action learned after its effective event cannot be
retroactively inserted. Post-action fills and valuation reject pre-action quotes,
even if those quotes would otherwise satisfy the freshness limit. Adjusted-price
corporate actions are refused to prevent dividend/split double counting.
If multiple different actions share one effective time, their supplied ordering
and amount/share basis must be explicitly bound by the caller to source evidence.
This core does not infer a combined split/dividend convention.

`CashLiquidation` disposes of an explicit supported lot quantity against declared
cash recovery and fee, retains realized P&L, and cancels open instrument orders.
It may be partial; a delisting flag requires all remaining quantity accounted for.
An explicit zero recovery records an actual loss, never a missing-data imputation.
Delisting blocks future order admission. Receivables already earned remain owned.
The provider's recovery, timing and rights remain unverified caller inputs.

`FXQuote` is always quote currency per unit base currency with separate bid/ask.
`convert_value` converts positive assets by selling the source currency and
negative liabilities by buying the owed source currency. Direct conversion uses
bid for an asset and ask for a liability. Inverse conversion divides by ask for
an asset and by bid for a liability. It rejects unrelated currency pairs, future
availability and stale quotes. No midpoint or arbitrary cross-rate is assumed.
`ConvertCash` moves an explicit positive funded amount between currencies and
charges a separate target-currency fee; valuation alone never changes balances.

## Separate derivative arithmetic, explicitly incomplete execution

`LinearDerivative` names a contract, quote currency, kind, contract quantity
unit and positive multiplier. `futures_pnl` computes signed contracts×multiplier×
(exit−entry), including negative futures prices. `perp_funding` computes a single
period's quote-currency cash flow as −signed contracts×multiplier×mark×rate under
the explicit `POSITIVE_LONG_PAYS` convention. Negative funding rates reverse the
cash flow. Inverse/coin-settled conventions and mixed contract kinds are refused.

These functions do **not** implement a futures/perp position book, margin,
expiry/delivery rules, variation settlement, rolling, perpetual funding schedules,
liquidation mechanics or broker capability. They do not grant derivatives access
to the spot book. Those mission capabilities remain **UNSUPPORTED**, requiring
their own implementation, empirical inputs and tests. They must not be marked
operational merely because the scalar oracles below pass.

## Independently calculated synthetic oracles

| Case | Calculation outside the implementation | Expected result |
|---|---|---|
| Minimal cash | 10,000−10×100−1+10×101−1 |10,008 cash; net8 |
| Double commissions | 10,000−1,000−2+1,010−2 |10,006 cash; net6 |
| Spread only, same fees | Buy10@100.10 ask; sell10@100.90 bid; fees1+1 |10,006 cash |
| Ten-bp adverse slippage | Buy100→100.10; sell101→100.899→100.89 adverse tick;10 units;fees1+1 |10,005.90 cash;slippage1+1.10 |
| Partial purchase/sale | Buy4@100+fee1 and6@102+fee1:cost1,014; sell5@110−fee1:proceeds549;allocated cost507 |cash9,535;remaining basis507;realized42 |
| Split2:1 | Cash9,000+10×100 before; cash9,000+20×50 after |wealth10,000;no cash created |
| Dividend ex-drop | Cash9,000+10×98+receivable10×2 |wealth10,000;receivable20, then cash20 at payment |
| FX direct sides | EUR100×USD/EUR1.1 bid; liability EUR−100×1.2 ask |USD110 asset;USD−120 liability |
| FX inverse sides | USD120÷1.2 ask; liability USD−110÷1.1 bid |EUR100 asset;EUR−100 liability |
| Futures multiplier |2 contracts×50 USD/point×(4,001.25−4,000) |USD125 gross;short reverses sign |
| Perp funding |−2 contracts×20,000 USD×0.0001 |USD−4 long cash flow;+4 for short |
| Partial liquidation |After10@100, sell4 for105 each−fee1:cash9,419;remaining6×105 |wealth10,049;realized19;remaining basis600 |

Local focused evidence:66 accounting tests plus39 unchanged legacy simulation
tests passed (105 total), with93.64% combined statement/branch coverage of the
new accounting module and clean strict mypy. Final Ruff and independent-review
results are separate recorded checks. The tests include positive and rejection
paths, context independence, split/dividend double-count guards, quote-basis
changes, ex-date ordering, exact duplicate/conflicting/stale events, cancellation
races, partial delisting refusal, wrong units/conventions, missing/stale data,
nonfinite values and unsupported modes. Root full-suite/CI and final independent
review remain integration gates. No Git, network, account, purchase or dependency
change was performed for this accounting slice.
