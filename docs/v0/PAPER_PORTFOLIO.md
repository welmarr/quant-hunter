# One-session paper portfolio inspection

This is a read-only projection of an owned synthetic PaperAccess session and its
existing native PaperEngine journal. It creates no account, command, report,
research object, scientific attempt, approval or network request. The real Item8
experiment remains the scientific authority. Independent sessions each start
with separate capital: the service never combines their balances or performance.

## Integration contract

Construct `PaperPortfolio(paper_access, inspection=quality.inspection)` and call
`install_paper_portfolio_routes(app, authenticated, portfolio)`. The inspection
callback is mandatory and trusted host code; production must supply the real
shared read reservation. One outer reservation encloses each request's heavy
inspection, including lists. No nested resource reservation, import operation or
scientific trial is created. The host supplies actual authentication and should
retain its existing private-response/cache policy.

- `GET /api/paper/portfolio/sessions`: at most32 separate, owned choices. Each
  verifies the retained workflow chain and labels itself
  `VERIFIED_WORKFLOW_CHAIN_ONLY; NOT_FRESH_VALUATION`. It does not open all32
  economic histories or return summed wealth.
- `GET /api/paper/portfolio/sessions/{session_id}`: the selected owned session's
  verified portfolio, report anchors, native command timeline and duration
  diagnostics. Owner, researcher and reader roles can read only their own session.
  Both the passed identity/role and current SQL identity are checked. Another
  owner gains no access to another user's portfolio.

The response includes `availability`, `reason`, `current`, `timeline`,
`drawdown_duration`, `report_anchors`, `producer`, workflow revision/event digest,
experiment ID, native head and last reported native revisions. Every Decimal
is a JSON string; UTC timestamps are strings. Native revisions and counts are
bounded integers. No query parameter selects arbitrary paths, SQL, expressions,
currencies, evidence modes or another owner's account.

`current` is the last immutable **reported** snapshot, not an uncommitted worker
state. If the native journal is ahead, `unreported_native_revisions` explicitly
counts that difference. A latest failure report with no account snapshot leaves
current values unavailable while retaining the verified earlier timeline. Before
initialization, values and durations are unavailable and the timeline is empty.
After actual cash-only initialization, empty positions, zero holdings, zero
reservation and zero drawdown duration are meaningful observed zeros.

## Evidence and bounded replay

The projection verifies all retained workflow events through the selected head
(maximum600), including immutable event hashes, exact owner/session identity,
unchanged original configuration and experiment. Every distinct report is loaded
through the existing immutable store; format, experiment, cursor, evidence mode,
scientific label, snapshot and repeated digest/cursor bindings are checked.
Reports must remain chronological. Cumulative report processing is capped at
64MiB, each report retains the existing2MB object limit, and the final JSON
response is capped at2MB. Cached workflow heads and event lengths are checked
against their existing4096-byte bound before loading or decoding their payloads.
Session enumeration stops at33 and fails if the32-session bound was exceeded.
Native genesis, total payload and command count retain their
existing caps, including at most1,000 commands.

The existing Lab/PaperAccess binding follows the original configuration, data,
instrument revision, code and environment/source archive. Historical inspection
uses the retained producer (`current=False`), not today's executable code identity.
Supported retained `v0-paper-report-1`/native-v1 records remain readable across
producer changes. A missing archive or contradictory old graph is refused; no
compatibility path silently skips verification. Future storage formats require
an explicit compatible reader rather than inferred migration.

Within one native SQLite read transaction, the existing engine `_load` validates
the actual genesis, every command, chain/state hashes and head. The adapter then
uses the unchanged pure `_advance` to recover historical observations through the
last reported revision. This is the engine's existing economic implementation,
not a second accounting or scientific state machine. Each report snapshot must
match the canonical serialization of the real native state at that revision;
report equity, maximum drawdown, commission and adverse slippage must also match.
Timeline entries retain actual command IDs and native state/chain hashes. The
initial point is the real genesis; controls that only change workflow metadata
add no point. Multiple native commands at one timestamp remain distinct events.

These projections intentionally depend on the existing engine's private replay
and PaperAccess binding functions. Changes to those interfaces or storage formats
must rerun the cross-item regression tests; the adapter is not a competing stable
economic API. No source or core edits are required for this first integration.

## Display conventions and limitations

The existing accounting `value_book` provides bid-side long holdings, actual cash,
unpaid receivables and total equity at the recorded timestamp. Positions include
quantity, cost basis, quote/availability times and bid-marked value. A position's
concentration is its bid-marked value divided by strictly positive contemporaneous
valued equity; the maximum is zero for an actual empty portfolio with positive
cash. Stale/missing marks or nonpositive equity make concentration unavailable,
not zero. The current workflow is single-USD cash-funded spot; no FX conversion
rate, short exposure, financing model or liquidation fee is invented.

Buy reservation cash is shown separately from marked holdings. Available cash
after buy reservations is an accounting diagnostic, not a broker buying-power
claim. Reservations and their fee budgets use native Decimal values. Commission
and adverse slippage remain distinct actual fill costs. Arithmetic runs under
the accounting module's fixed Decimal context regardless of the caller's global
precision or traps.

Timeline equity is **recorded native equity**. Some controls retain the previous
mark; the current valuation separately reports quote freshness and can be
unavailable even when the prior native equity is recorded. No interpolated,
daily-resampled or wall-clock mark is fabricated.

Duration uses the timestamps of actual native command observations. At a recorded
equity equal to or above the previous high water, the latest observed peak time
resets. Below that peak, current duration is elapsed UTC seconds since the last
observed peak; maximum duration also includes the recovery endpoint of completed
episodes. An unfinished episode is explicitly right-censored at the final
reported observation. This does not establish an unobserved intraperiod path or
continue the clock to the current real-world time. It is a synthetic operational
diagnostic, not an empirical drawdown statistic or research acceptance criterion.

Proposed durable decision note for integration: adopt these display conventions
without changing the scientific validation rules, native valuation, risk limits,
model identities or lifecycle. No historical performance or profitability claim
follows from passing the software tests.

## Verification and integration follow-up

Tests use actual Item8, immutable artifacts, SQLite workflow events and native
commands. Independent arithmetic checks actual holdings/cash/concentration and
duration; defenses include coherent rehashes, substituted valid native genesis,
historical source loss, foreign/stale roles, reader access, occupied resources,
report rollback, malformed snapshots, numeric-context mutation and byte/count
bounds. Routes are authenticated, read-only and sanitize errors.

The first test run retained a test-only obsolete user-creation keyword error.
The next run retained25passes and one incorrect test assumption that the final
20-bar fixture still held positions, with88.19% coverage. That scenario ends
flat. The correction verifies a real earlier three-bar holding and independently
tests stale marks there; production economics were unchanged. A subsequent test
fixture reached the real eight-session queue cap before the intended32-history
cap; making those hostile surplus rows terminal correctly isolates the latter.
An interrupted evidence run also retained4passes and32setup errors when root
source changed during archival construction; the source-mismatch guard correctly
refused it. Final verification used an isolated exact source copy.

Final frozen author gate:42tests pass with warnings treated as errors,137.28s,
98.03% combined statement/branch coverage across both new modules. Ruff and
strict mypy pass for the two modules and test file. All160 captured support/source
Python hashes remained unchanged. Independent peer review read the full source
and executed7targeted real-store cases,35deselected,62.66s with warnings as errors:
held positions/stale marks, coherently changed snapshot, retained old producer
and lost source archive, unreported commands, occupied shared readers and route
privacy/resource classification. No remaining material finding in that scope.
The host's complete regression, browser integration, private restoration and
exact CI remain root integration responsibilities; this focused gate does not
substitute for them or establish empirical validation.

Existing `paper_routes` session list/detail lacked shared read admission at initial
inspection. Root subsequently added required inspection to both routes and wired
the production quality reader. Capacity is now503 with `Retry-After: 3`, separately
from403 ownership refusals; the new portfolio routes use the same convention.
Control/reconcile response/preflight reads need their separate root/author audit:
protective controls should remain queueable without an unadmitted heavy response.
Internal workers/broker/protective-halt callers already have their own admitted
contexts and must not receive accidental nested reservations. This module does
not edit those existing call sites.
