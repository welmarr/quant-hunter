# V0 cash ETF execution profile

ETF is a distinct asset class in the canonical instrument record, synthetic
four-bar fixture, native accounting book and persistent local-paper workflow.
The paper fixture uses symbol `SYNTH_ETF`, XNYS sessions, USD base/quote currency,
one-share lots, a USD 0.01 tick and multiplier one. No provider prices or real
security eligibility are implied. The fixture is an ordinary cash share profile;
it does not model a fund's creation/redemption, tracking error, NAV or underlying
portfolio leverage. Leveraged/inverse ETF and derivative profiles are unsupported.

The existing long-only, cash-funded accounting rules apply: decisions precede
their executable quotes, buys consume ask and sells consume bid, slippage rounds
adversely to tick, and each partial fill pays its explicit commission. Native
risk reservations, order cancellation, kill controls and restart evidence remain
the same mechanisms used for equities. No short, borrowed-cash or live route is
added. The four-bar math fixture still has no exchange-calendar claim; the paper
workflow freezes an actual XNYS calendar snapshot before execution.

ETF split and cash-distribution events use the existing unadjusted-price rules.
A two-for-one split doubles units without changing total cost or cash; open
orders are canceled and unrepresentable fractional-share outcomes are refused.
Cash entitlement is captured at ex-date, valued as a receivable, and paid only at
the declared payment time even if shares were sold afterward. Adjusted-price
double counting, unavailable or retroactive actions are rejected. These are
explicit caller-supplied synthetic events, not historical-action ingestion or
tax treatment. The intraday paper fixture generates no corporate actions.

Independent arithmetic tests cover 10000 -> buy10@100 with fee1 -> sell10@101
with fee1 =10008, doubled fees =10006, separate spread/slippage and per-partial-fill
fees, split neutrality and ex-drop/distribution neutrality. Persistent workflow
tests retain ETF metadata through actual Item8 registration, canonical instrument
binding, causal fills and final INCONCLUSIVE output. These are software evidence,
not empirical performance or source-quality approval.
