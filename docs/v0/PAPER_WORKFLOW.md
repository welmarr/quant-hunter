# Private deterministic paper workflow

This profile advances a real persistent local ledger over explicit synthetic
equity or FX spot quotes. It is a software demonstration, not empirical strategy
validation, a calibrated signal, a broker connection, or a scientific gate pass.
The existing Item8 service owns every experiment and attempted variant.

## Public contract and host integration

PaperAccess receives AppState, LabService, and the reviewed PaperEngine at exactly
the sibling file paper.sqlite3. Its additive paper_jobs, paper_events and
paper_step_receipts tables use application.sqlite3; the native paper ledger keeps
its own required application ID and format. The host must include precisely this
paper.sqlite3 file in private backup/restore verification and hold one runtime
lease before scheduler/recovery calls. The bridge does not modify host security.

The host must also inject `resume_resource(user, paper_id, expected_revision)`.
Its default fails closed. Only RESUME uses this context for its actual current
source/canonical preflight. The context validates the fresh owner/researcher and
exact PAUSED head and borrows that existing queue reservation while respecting
the shared two-active cap. It holds the short proof gate and releases its reader
before the control changes session state. Eight already queued paused sessions
therefore need no invented ninth queue slot just to resume. Root owns the atomic
linked-reader implementation. Offline fixtures explicitly inject a test context;
that fixture is not production resource evidence.

Control and reconciliation responses are freshly owner-verified operational
heads with `status_authority=OPERATIONAL_SESSION` and
`report_verification=NOT_FRESH_ADMISSION`. They do not replay the large canonical
source/report graph after mutation or after a recovery worker releases its slot.
The UI follows with a separately admitted detail GET when needed. ACTIVATE,
PAUSE, KILL, CANCEL and RESET_KILL queue only bounded control metadata; their
actual economic worker still verifies source/configuration under its admitted
slot. RESUME retains its preflight binding check. The cheap response is not a
scientific or native-ledger verification claim.

The API exposes configuration defaults, private session creation/list/detail,
explicit activation, pause/resume/cancel/kill/reset controls, and explicit crash
reconciliation. Every interactive read/write verifies the current SQL identity,
role and session owner. Researchers can activate and control their own local
sessions; readers can only read their own. Another owner cannot read a private
session. This is separate from host-owner-only global kill and external account
authority. CSRF/authentication is injected by the host, and the HTTP wrapper
rejects unknown fields, duplicate JSON keys and bodies over8192 bytes without
echoing request values or raw exceptions.

Creation validates and stores immutable inputs, but allocates no research
attempt. Activation is explicit. The first process_one call generates only
fixtures and canonical instrument metadata, invokes LabService.begin_run to
allocate SOURCE/DATASET/FAM/STRATEGY/EXP and freeze/start Item8, and creates the
pristine cash-only ledger. It computes no signal or return before registration.
Subsequent calls advance at most one bar or one explicit control. Configuration
changes require a new session and count as a new variant once evaluated.

The host's scheduler calls has_pending and process_one; it does not expose a
public arbitrary-step or order-submission endpoint. The host must integrate
paper_jobs with all other admissions: at most8 nonterminal sessions/jobs across
services, and2 active resources. STARTING, STEPPING and RECOVERING use resource
slots. This bridge checks existing jobs/data_operations/publication_operations
under the same short application write transaction; the host must reciprocally
include paper work in their admission checks. No application write transaction
spans experiment registration, fixture generation, ledger execution or network.

## Frozen numerical and temporal profile

The closed editable configuration contains market (EQUITY or FX_SPOT), mode
(LOCAL_PAPER or REPLAY),20–100 bars, lookback1–10, cash, target quantity, maximum
quantity per fill, per-fill commission, adverse slippage and explicit risk limits.
The frozen expanded config records every price scale, bid/ask convention, timing,
calendar digest, instrument revision, fee-budget rule and signal/matching policy.
Seed0 means no random draws. There is no fitting, parameter search or retry.

Synthetic minutes start2024-01-02T14:30:00Z. Each opening quote is followed by
a closing quote at second59; the next bar opens a second later. Effective and
available timestamps are explicit and equal by this declared synthetic policy.
The fixed midpoint tick offsets are0,20,40,10,-20,-30,30,50, repeated. Equity uses
10000 base ticks of0.01; FX uses100000 base ticks of0.00001. Executable bid/ask
are one tick below/above the midpoint. No midpoint is used as an execution price.
These numbers describe generated input data, never a provider observation.

The closed-bar decision compares the current bid with the bid lookback bars
earlier. A positive difference targets the frozen long quantity; otherwise the
target is flat. Warmup targets flat. At most one order is pending. A decision at
a close can fill only at a strictly later opening quote. Each bar matches at
most the frozen fill cap. Every fill pays its own commission, so admission
reserves ceil(order quantity / fill cap) times that commission. Signal reversal
cancels the remaining incompatible order; a rejected match also cancels its
remainder. All local requests and acknowledgments are ledger commands.

The real risk engine enforces cash, position attribution, lot/tick/calendar,
freshness, spread/slippage, exposure/concentration, order count, loss and
drawdown. Failures and rejected commands remain in the report alongside signals.
Known commission and adverse price budgets enter admission. The intraday profile
explicitly assumes zero financing for fully funded long spot. Shorts, leverage,
derivatives, overnight carry, multiple quote-currency cash balances, corporate
actions during these fixtures and external orders are unsupported.

Canonical instrument metadata and its exact immutable revision are retained,
including EUR/USD for FX. The accounting symbol EUR_USD is an explicitly frozen
alias required by the reviewed accounting identifier grammar. Pinned XNYS rules
and the documented OTC New York17:00 convention supply actual windows. Their
current versioned rules are not asserted to be historical publication vintages.
Synthetic metadata recorded today is never described as historically known.

At the end, outstanding orders are locally cancelled and existing holdings
remain valued at bid. There is no fabricated final liquidation or exit fee.
Reports distinguish equity from cash and preserve full orders, fills,
reservations, engine outcomes, signal explanations, costs and maximum drawdown.
The workflow also records completed-bar counts, modeled timestamps and measured
worker elapsed time.

## Exact authority and failure recovery

The Item8 manifest binds exact config/data/code/environment and permanent
strategy references. Environment evidence must contain a base64-exact-bytes
source snapshot with the actually executing replay/accounting/lifecycle/market
modules. The bridge verifies those bytes before starting or resuming computation.
The account's complete instrument specification, calendar, frozen risk limits,
inception equity and provenance must match those canonical objects. A ledger
change outside this workflow is detected before another bar is accepted.

Application events are append-only canonical bytes with a chained digest and a
verified head. Original configuration and ownership remain in that chain.
This detects inconsistent/accidental mutation; it is not protection against a
privileged host rewriting all tables, hashes, objects and triggers together.

Before economic work, the bridge claims a step and records its exact starting
ledger revision/state digest. Economic commands commit in the separate durable
ledger. On completion it publishes a report and immutable receipt containing
the resulting state digest and exact command IDs, then commits the application
cursor. These are deliberately separate transactions; no false cross-database
atomicity claim is made.

At startup, recover pauses clean sessions. In-flight work becomes AMBIGUOUS and
cannot automatically run again. Explicit reconcile may accept only an unchanged
starting state or a durable completed receipt whose complete state and command
IDs match the verified engine. Even then, execution stays paused until explicit
resume. A partly committed step without that receipt cannot resume; cancellation
retains its actual partial ledger and fails the existing research attempt.
Controls arriving during a bar remain pending until that bounded bar completes.

The runtime must invoke paper recovery under its lease before generic orphan
recovery. Only owned_experiment_ids, derived from verified private job and
canonical bindings, may be excluded from that generic walk. An unrelated RUNNING
experiment must still fail through LabService.recover_run. A crash after begin_run
but before the private pointer commits leaves such an orphan; it is never
rediscovered by a user-supplied mapping or silently re-evaluated.

Cancellation before registration remains an operational CANCELLED record with
no unnecessary attempt. Cancellation/failure after registration retains partial
output objects linked by the operational row and finalizes the actual Item8
attempt FAILED. Successful completion calls evaluate_run exactly once and stays
INCONCLUSIVE. A crash after canonical finalization can recover its exact receipt
without adding a second attempt. No separate scientific lifecycle, promotion,
sealed release or experiment approval is introduced.

## Bounds and evidence

The profile allows32 lifetime sessions, matching the native ledger's32-account
bound,64 controls/session (the final slot is reserved for cancellation) and600 operational events/session. Immutable operational
payloads are at most4KiB each and24MiB cumulatively; ordinary retained reports
are at most2MB. Admission reserves worst-case remaining audit bytes for every existing session before accepting a new one. Finalization keeps12 operational events of headroom; approaching the event limit stops computation and retains a FAILED attempt with its partial report. Repeated recovery of an already paused or ambiguous session is read-only. Pending protective controls survive restart but cannot bypass ambiguous-step reconciliation. The100-bar/one-order policy keeps commands within the existing
1000-command/account budget. Exhaustion fails closed without rotation, deletion,
new loss baselines or hidden resubmission. The host's cumulative disk/download
policy remains an additional admission requirement.

Explicit reconciliation checks that host admission policy outside the SQLite
write transaction, then atomically reserves one of the same two shared active
resources as replay/data/publication work. A denied claim leaves the ambiguous
head and revision unchanged; no verification computation starts first.

The independent partial-fill oracle is: initial10000, prior close bid100.39 /
ask100.41, next-open buy4 with1bp adverse tick-rounded price100.43 and fee1,
cash9597.28. At subsequent close bid100.09, equity is9997.64. The ten-unit order
reserves3 total commission units for three potential partial fills; after signal
reversal the actual four-unit sale reserves1. These are synthetic accounting
oracles, not investment results.

Focused author tests exercise real canonical Item8 histories, causal equity/FX
completion, this arithmetic, concurrent claims and controls, private ownership,
role changes, resource/admission limits, source/genesis mismatches, immutable
events, sanitized failures and several crash boundaries. Independent review,
root integration, complete existing regression, host launch and governed CI
remain separate gates; the module does not claim those gates from focused tests.

## Read-only execution reservation contract

`execution_snapshot(owner, paper_id, expected_revision=...)` returns a verified
context and the exact native `PaperSnapshot` for the offline broker protocol
adapter. It requires an owned paused session with no pending/inflight control,
the actual current RUNNING Item8 binding, an unchanged retained/native snapshot,
one active risk reservation, permanent strategy/instrument identity, matching
remaining order quantity/side, a valid calendar and causal fresh quote, healthy
reconciled state and no kill. It rechecks workflow and native revisions after
verification. No reservation, economic fill, network order authority or new
research attempt is created. Callers must admit the shared resource first and
recheck the same snapshot before accepting a current protocol result.

`execution_receipt(owner, paper_id, workflow_revision=...)` verifies the session
chain and retrieves the exact original paused event/report and retained Lab
graph. This is historical inspection: the current session may have resumed or
finished. It rejects a proof whose otherwise consistent snapshot/report was
never recorded by that session at that revision.
