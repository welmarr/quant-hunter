# Bounded public collection schedules

This operational scheduler implements persistent opt-in collections for the
existing free diagnostic profiles. It starts no thread and grants no research,
credential, broker, source-approval or data-quality authority. An owner creates a
PAUSED schedule and explicitly activates it. Existing immutable source capture
and canonical SOURCE/DATASET registration remain the data authority.

| Catalogue key | Existing fixed request | Meaning |
|---|---|---|
| SRC-04 | BLS CES0000000001, January–December 2024, thousands of persons | Historical diagnostic, current retrieved version; historical publication availability remains UNKNOWN |
| SRC-06 | Federal Reserve G.17 release dated 2025-01-17, expected base 2017 | Specific archived release diagnostic; no invented exact publication timestamp |
| SRC-08 | ECB D.USD.EUR.SP00.A, 2024-01-02 through 2024-01-05, USD per EUR | Historical indicative reference rates, not executable quotes |

These permanent mission catalogue keys are not canonical registry SOURCE IDs.
The profile is explicitly `FIXED_HISTORICAL_DIAGNOSTIC`, with no freshness claim.
Repeated collection retains a new capture and version; it does not turn these
fixed ranges into a current feed or rolling history. No secret, custom URL,
user-selected query, paid source or authenticated source is accepted.

## API and runtime integration

`SourceSchedules(data: DataAccess, *, clock, fault)` uses the existing private
`application.sqlite3`. Public methods are:

- `create(user, catalogue_id, interval_seconds=..., maximum_runs=...)`: current
  owner only, immutable configuration, initially PAUSED.
- `get`, `list_schedules`, `history`: only the currently authenticated user’s own
  records, including after demotion to reader; no other owner’s identifiers.
- `control(user, id, action, expected_revision=...)`: current owner, exact CAS;
  ACTIVATE/RESUME, PAUSE or CANCEL. No deletion or configuration rewrite.
- `pump_due() -> bool`: queue at most one immutable occurrence, or settle one
  already cancelled generic queue job. No HTTP. The caller holds the runtime
  lease and determines fair dispatch with other product work.
- `execute_job(job: Job)`: one actual RUNNING, owner-bound AppState job of kind
  `SOURCE_COLLECTION`. It settles the job itself; notification integration must
  read the resulting actual status, not assume the lack of an exception means
  successful acquisition.
- `recover()`: called under the exclusive runtime lease **after DataAccess
  recovery and before generic orphan job failure**. It never fetches. Safe
  QUEUED occurrences remain queued. Abandoned dispatches become UNKNOWN/PAUSED;
  a completed retained DataAccess result may be adopted, also PAUSED. No unknown
  request is automatically repeated.

`install_source_schedule_routes` exposes `/api/source-schedules`, `/profiles`,
`/{id}`, `/{id}/history` and `/{id}/control`. It requires the host’s existing
session/CSRF callback. Owner-only mutations use closed strict JSON, bounded to
4096 bytes, and sanitized errors. The root Runtime/frontend wiring and its
integration tests are separate from this adapter gate.

The only DataAccess extension is optional `worker_job_id` and
`operation_started(operation_id)` on `probe`. The callback executes after the
real data operation exists and before source acquisition. This connects the
immutable occurrence and dispatch claim to the exact owned PROBE operation;
it reuses the existing worker/data reservation collapse and private source
capture path. Callback failure prevents source acquisition and retains a failed
data operation. No SQLite transaction spans HTTP or source parsing.

## Durability and bounds

Configuration and status changes form an immutable, hashed, append-only event
chain with a CAS head. Occurrences, dispatch claims, operation links and receipts
are immutable. A dispatch claim is committed before acquisition so concurrent
workers cannot issue a second request or finalize each other’s operation. Reads
verify repeated schedule/owner/number/configuration identities and the actual
AppState job's owner, closed configuration and lack of an experiment. Receipt inspection
verifies its occurrence, dispatch and operation link, the actual operation’s
owner/source/kind/status/worker ID, matching terminal job status, and the digest
of its retained result. Recovery preserves a previously recorded job failure
even when its source result was retained successfully. A successful job missing
the atomically committed receipt is refused as contradictory evidence.
This is operational byte/reference verification; canonical source graph
inspection remains the existing source service’s responsibility.

Limits are 32 stored schedules globally, 30 dispatched occurrences per schedule,
intervals from one hour through seven days, 64 normal controls plus final CANCEL,
160 status events, 4096-byte internal records, 64,000-byte operation result
summaries, and at most 30 returned history items per schedule. Each source uses
its existing one-page, 2 MB bounded transport. The standard global limits still
apply: two active resource operations, eight queued/reserved jobs, the existing
disk reserve and runtime budget, 1000 data operations, 25 BLS probes per day and
one probe per minute per user. No special extra resource slot is granted.

Missed schedule windows are counted and skipped; one later occurrence is queued,
not a catch-up burst. Every dispatch consumes an occurrence even when a quota,
authority or provider failure prevents success. Any failure pauses the schedule;
there is no automatic retry loop. An explicit RESUME schedules the next distinct
occurrence one full interval later, within the original run limit. Configuration
cannot change, and changed implementation defaults cause refusal rather than
silently altering an existing schedule’s query.

PAUSE/CANCEL remove a still-QUEUED job and retain CANCELLED_BEFORE_FETCH. Once the
request has been admitted and linked, it cannot be unsent: a late successful
result remains a truthful success receipt while the schedule stays paused or
cancelled. A crash after admission can be ambiguous even if the provider never
received a request; UNKNOWN is retained conservatively. A corrupt record remains
unsettled and fails closed for operator inspection. No orphan blanket exemption
or scientific experiment recovery rule is introduced.

## Validation scope

Tests use injected local responses only, including actual BLS, ECB and G.17
parsers through canonical candidate/raw/DATASET capture. Separate tests exercise
concurrent pumping and dispatch, shared admission, persistent quotas, ownership
and demotion, queued/in-flight cancellation, crash windows, rollback, historical
receipt corruption, missing claims, clock bounds and closed API requests. No
real network request, account, credential, paid use or empirical evaluation is
part of this proof. Root integration, complete regression and independent review
remain required before a product completion claim.
