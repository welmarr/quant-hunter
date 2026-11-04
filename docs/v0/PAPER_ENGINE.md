# Bounded persistent local paper engine

This is an operational SQLite wrapper around the reviewed Decimal accounting
book. It implements local/replay bookkeeping and risk admission, not an external
broker connection, a profit result, a scientific approval, or a stage transition.
Item8 remains the sole experiment lifecycle. The engine never allocates research
identifiers, evaluates strategies, selects parameters, or promotes research.

## Supported profile and authority

Only `LOCAL_PAPER` and `REPLAY` are accepted. Holdings are cash-funded long spot;
every instrument's quote currency and the sole cash balance must equal the
account base currency. Equity, FX spot and crypto spot instrument conventions
come from the existing `InstrumentSpec`. A foreign base asset quoted in account
currency is supported; multiple cash/quote currencies are expressly rejected.
Shorts, leverage, derivative execution, live modes and `BROKER_PAPER` are rejected.
The independent accounting module's FX conversion and derivative arithmetic do
not imply that this persistent risk profile supports their execution.

Creation accepts only a pristine, cash-only accounting genesis. No opening
positions can be smuggled into a new account to reset losses. Account inception
equity, high-water mark and maximum drawdown remain in the replayed state; a new
owner-approved account is a distinct audit object, never a continuation with a
reset baseline. There is no edit/delete/reset command for an existing account.

The host supplies a permanent experiment reference, preexisting strategy
references and exact code/environment/configuration digests. The engine checks
their bounded shape and retains exact bytes, but does not claim to have verified
those objects in a registry. Root integration must authenticate the user, enforce
owner/researcher/reader permissions, verify the permanent references and source
snapshot, and bind scientific configuration before invoking this library.
Every account read, process and protocol-audit read checks the supplied owner ID.
Passing an owner ID to a library is not itself authentication.

## Public contract

`PaperEngine(path: Path, *, before_commit=None)` opens a host-selected SQLite file.
The callback is exclusively a test/host fault-injection hook, never user config.

- `create_account(account_id, owner_id, initial_book, RiskLimits, Provenance)`
  retains a canonical typed genesis and its SHA-256 digest.
- `load(account_id, owner_id)` verifies and deterministically replays the journal,
  returning a frozen `PaperSnapshot`; it does not run a worker or create fills.
- `process(account_id, owner_id, command, expected_revision)` applies one command
  or retains its domain rejection. `revision` counts commands; `book.version`
  counts accounting transitions and can differ because risk commands and automatic
  cancellation requests are separate operations.
- `protocol_rejections(account_id, owner_id)` returns verified append-only records
  for stale revisions and conflicting reused command IDs. These protocol failures
  raise `PaperError` while preserving their separate audit transaction; they do
  not consume an economic revision or mutate reservations.

Typed commands are `Admit`, `Match`, `Cancel`, `Mark`, `Kill`, `Health` and
`Reconcile`. Each has an immutable `command_id` and aware `datetime.UTC` time.
An exact duplicate, including its original expected revision and exact Decimal
representation, returns the current state. It never returns an old state or
replays an economic effect. A conflicting repeated ID is refused and audited.
The `EINT.` ID prefix is reserved for internal cancellation events.

`PaperSnapshot.outcomes` retains every accepted/rejected domain command and its
reason. Structurally invalid envelopes, unknown owners, exhausted capacity and
storage errors fail before an economic commit; the host API must retain those
request failures in its operational audit. Capacity failure never overwrites an
older event to make room. Only bounded allowlisted dataclass types, exact Decimal
strings and explicit UTC timestamps are decoded; there is no dynamic import,
pickle, arbitrary SQL request or executable serialized code.

## Atomic reservations, execution and risk

Each mutation uses `BEGIN IMMEDIATE`. Replay, CAS, admission, the new event row,
reservation changes, state digest and journal head commit in one transaction.
Competing writers cannot reserve the same available cash/holdings. A losing CAS
caller must reload and reconsider the intent; retry is never automatic.

Buy reservations cover remaining quantity times an adverse price ceiling rounded
up to the instrument tick, plus the explicit remaining total commission budget.
Sell reservations hold strategy-attributed quantity and reserve their commission
budget in cash. Sale proceeds are not assumed in advance to finance other orders.
Holdings are attributed to the strategy that bought them; one strategy cannot
spend another's units. Pending purchases count towards exposure even before a
fill. Pending sales do not reduce exposure until they actually fill.

Each match is an explicitly supplied local simulated fill. Buy prices use ask,
sell prices use bid, adverse slippage is tick-rounded, and commissions remain a
distinct cash cost. A buy price outside its original ceiling, slippage beyond
the frozen limit or total commission beyond its remaining budget is rejected.
Partial fills consume only their own reservation; cancellation requests retain
the remainder until confirmation. A valid full fill can win a cancel race;
the later cancel acknowledgement records `CANCEL_TOO_LATE`. Restart never
resubmits a pending order, generates a fill or confirms a cancellation.

Admission checks explicit calendar, tick/lot rules, causal quote availability,
quote freshness, maximum bid/ask spread, cash/held-unit availability, maximum
order notional, gross/instrument/strategy exposure, concentration and order count
in the configured half-open rolling window. Limits are mandatory input, not
investment recommendations. All values use the existing 38-digit Decimal context.
Admission concentration uses equity after all pending commission budgets and
known worst-case spread/slippage losses; those prospective costs must also remain
inside loss/drawdown limits. A known entry cost cannot be ignored until after fill.
There are no hidden borrow, funding, tax or liquidity assumptions.

A decision quote must be available by `decision_at`, with decision no later than
admission. An executable fill's quote effective time must be strictly after the
decision; the fill must be after admission. Quote receipt must precede the fill,
and stale quotes fail. Same-time quote revisions and older quote replacements
are refused. A mark needs fresh quotes for every held instrument. Valuation uses
bid for long holdings and preserves cash; it invents neither a closing trade nor
an exit fee. Slippage/fills/commissions are model inputs, not measured execution.

Exposure-limit breaches observed by valuation, drawdown from the persistent high
water and loss from inception trip the persistent kill switch. A rejected buy
cannot erase fresh valuation evidence of a loss limit. The kill switch requests
cancellation of exposure-increasing open buys and stops new buys. Those requests
retain reservations and permit bounded in-flight fill/cancel races. Reconciled,
healthy, fresh reduce-only sales remain possible within size and fee limits;
existing pending sales remain reserved. There is no external cancellation claim.

`Health(False)` persists an unhealthy status and kill. Restoration of health does
not automatically clear kill. Reconciliation compares timestamped external/local
simulation assertions with exact ledger cash and units; a discrepancy retains
the book and sets unreconciled/kill. It never overwrites positions to hide drift.
Clearing kill requires a matching reconciliation at or after kill activation,
a receipt within the freshness limit, healthy status, fresh valuation and current
loss/exposure limits satisfied. It cannot reset inception/high-water history.
An unreconciled or unhealthy account admits no new intent, including a sale whose
true available quantity is uncertain. Existing audit facts remain readable.

## Persistence and resource bounds

The database has a dedicated application ID, schema version1 and 4096-byte pages.
Unrelated/future-format databases fail closed. SQLite uses rollback-journal mode,
`synchronous=FULL`, foreign keys, memory-only temporary SQL storage and explicit
connection closure. Durable claims remain subject to the host filesystem/storage
honoring SQLite flushes; these tests do not simulate physical hardware failures.
All task files, temporary files and proof outputs are on Disk D.

Genesis and event/audit rows have SQL triggers refusing update/delete. Commands
have exact payload fingerprints and a previous-hash chain; each replayed state
is checked against its stored digest and final head. Protocol rejections have a
separate chain and head. A changed digest, missing head or replay disagreement
fails closed. This detects accidental/inconsistent mutation; a privileged host
attacker rewriting all database bytes, hashes and triggers is outside this
integrity boundary. The host should retain immutable external checkpoint evidence
when cross-host or adversarial tamper evidence is required.

Bounds are32 accounts,1000 commands and1000 protocol failures per account,
128KiB per command/genesis,2MiB per derived snapshot,16MiB total command/audit
payloads and16384 database pages (64MiB). The transient rollback journal resides
beside the database and can add disk usage during a transaction. Replaying each
bounded account is intentionally simple; no claim of unbounded/high-frequency
scalability is made. Hitting a bound requires explicit host handling and preserved
history, never silent rotation or replay with a new loss baseline.

## Independent arithmetic and failure evidence

The actual persistent roundtrip oracle is10000 cash, buy10@100 fee1, sell10@101
fee1, final10008. Doubling both fees gives10006. A partial buy4@100 fee1 of a
ten-unit order with total fee budget2 leaves cash9599 and a remaining reservation
of601; the final six-unit fill leaves cash8998. At bid99.99/ask100.01 with1bp
adverse slippage and0.01 tick, a ten-unit purchase executes at100.03: market
spread, adverse slippage0.20 and commission1 remain separate; cash8998.70 and
bid-marked equity9998.60 follow independently.

Tests use real temporary SQLite files, two concurrent competing writers, a
before-commit exception, repeated engine reopen, exact duplicate/conflicting
commands, partial fill/cancel races, journal/head corruption, immutable SQL rows,
owner mismatches, stale/delayed/revised quotes, calendar/lot/cost/budget breaches,
per-strategy ownership, fresh reconciliation and persistent drawdown/kill history.
Initial testing exposed a missing admission market-open check and unclosed test
fixture database connections; both were corrected before the passing gate.
Independent review additionally found that admission/mark quotes could be off
the instrument tick grid. The common quote path now rejects such observations
before reservation, valuation, high-water or kill state can change.

The isolated final author gate passed85 paper-engine tests and the combined190
paper/accounting/legacy simulation tests with warnings treated as errors. The new
engine has95.24% combined statement/branch coverage; Ruff check/format and strict
mypy passed. These are software-contract results; independent review and the
root's broader integration/CI evidence remain distinct requirements.

The scope does not yet journal splits/dividends, financing, cash conversion,
derivatives, multiple currencies, streaming connector state or a background
scheduler. The reviewed pure accounting helpers do not authorize silently
calling such events around this journal. Root API/UI/worker/lease integration,
source and permanent-ID validation, complete regression/CI and independent review
remain required integration gates. This module makes no empirical performance,
market-ready execution or professional certification claim.
