# Retained Signals and research observations

This product slice reads owned existing evidence. It has no trading, fitting,
experiment-allocation, strategy-promotion or acquisition authority. V0-078,
V0-190 and V0-194 motivate the inspection view; they do not justify inventing
missing forecast contracts in old paper experiments.

## Scientific boundary

The legacy paper profile freezes a deterministic close-bid/lagged-close-bid
long/flat rule, actual source/instrument/calendar versions, next-open execution,
fees, risk limits and quote-age checks. It does **not** freeze a forecast horizon,
signal lifetime, prediction probability or calibrated confidence. Every returned
legacy decision therefore has `actionable: false`, `confidence: null`, and
`horizon.status` / `expiry.status` equal to `UNKNOWN_NOT_FROZEN`. The 3,600-second
order admission window is not a signal expiry. The 60-second quote freshness
limit is not a forecast lifetime. Existing receipts are never retrofitted.

`generated_at` and `decision_at` use the actual simulated bar-close clock and
are marked `SIMULATED_DECISION_CLOCK` for legacy records, or the exact frozen
`SIMULATED_BAR_CLOSE` for the opt-in profile below. `retained_at` is the earliest actual
workflow event retaining that decision. The trusted host supplies the query
clock, returned as `observed_at`. A source receipt or retention time after that
clock yields `NOT_AVAILABLE_AT_QUERY`; a receipt beyond the frozen quote age
yields `STALE_AT_QUERY`. Current historical synthetic fixture decisions are
stale at ordinary wall time. None of these states produces live observations.

Canonical provenance contains the exact strategy, source, input dataset,
instrument revision, calendar, configuration, code, environment and experiment
identities/digests. The simple paper rule fits no learned parameters, so model
IDs remain empty with `NOT_FITTED` rather than inventing a model. Provenance is
shared by all decisions on the returned page and each decision retains its
first report/revision anchor. The stable `PAPER-…:BAR:n` reference is a derived
observation address, not a new research-object identity.

Risk admission reflects the actual historical native command outcome and the
order status in the reported snapshot. It is not a new risk authorization.
Common risk context names that snapshot and any newer unreported native
revisions. Withdrawn session controls, uncertain/unreported state, ended
sessions, superseded decisions and the latest retained decision are distinct.
Missing failure snapshots yield unavailable risk and uncertain current state.

Pattern results use a separate `RESEARCH_OBSERVATIONS_NOT_TRADING_SIGNALS`
classification. They retain exact verified configuration, EXP/MOD recipe/fit
bindings, outcomes, negative cases and candidate exposure. Shape similarity is
not probability of profit. A frozen outcome horizon is not a signal expiry.
The reader does not introduce historical empirical research eligibility.

## Verification and bounds

`SignalsAccess(paper, inspection=quality.inspection, patterns=patterns)` uses
one shared inspection reservation around each heavy request. It calls the
already-admitted internal Portfolio projection, preserving its complete
canonical/source/report/native journal verification and pure replay. It then
verifies every retained signal prefix, recomputes the exact frozen causal rule,
and binds recorded order IDs/outcomes to actual native admission commands.
Coherent hash rewrites cannot manufacture a different bid, direction, timing,
risk outcome or forecast field. Concurrent head changes are explicit retry
conflicts, never silently combined states.

Each session remains bounded by the existing 100 bars, 600 workflow events,
1,000 native commands and 64 MiB cumulative report budget. Native and report
verification passes are sequential; no full unbounded corpus is loaded. The
Signals pass rereads bounded reports/native commands after the Portfolio pass;
it does not claim only one physical I/O pass. Responses cap at 2,000,000 bytes.
Sessions cap at 32. Pages contain at most 25 rows. Pattern operational lists
expose owned job ID/status/EXP metadata, not unverified result contents.
Before JSON filtering, the same read transaction checks at most 10,001 global
job rows and refuses more than 10,000 retained jobs, configurations above
16,384 bytes, or more than 32 MiB of aggregate configuration bytes. The page
limit alone is not presented as a bound on historical-job filtering. A limit
failure does not discard retained jobs; inspection fails closed until a separate
reviewed scalable metadata index/pagination design is available.

Identity/role are checked against current persisted users. Owners cannot read
another account's session or research result. Readers may inspect their own
existing evidence. No new journal, competing lifecycle, filesystem path input
or provider request is introduced. Transient inspection reservations are the
only existing operational resource writes made by reads. Host private/no-store
HTTP middleware and authentication remain required.

## Integration

Install `install_signals_routes(app, authenticated, access)` after creating the
same PaperAccess, PatternAccess and shared QualityAccess used by the runtime.
The adapter never calls their mutation methods.

| Read route under `/api/signals` | Response |
| --- | --- |
| `/paper/sessions?limit=25&offset=0` | `sessions,total,limit,offset,inspection`; offset 0–31 |
| `/paper/{id}?limit=25&offset=0` | session/head/time, total/page, signals, common provenance, risk context, limitations; offset 0–99 |
| `/research/jobs?limit=25&offset=0` | owned operational jobs, has_more, classification; offset 0–9999 |
| `/research/jobs/{id}` | actual verified Pattern result projection, EXP/MOD/configuration bindings, research-only classification |

Authentication failure is delegated to the host; ownership denial is 403.
Shared capacity refusal is 503 with `Retry-After: 3`. Changed/evidence-invalid
sources return sanitized 409. Unexpected operational faults return sanitized
503. There are no Signals POST, order, mutation or recommendation endpoints.

The ignored `signals-ui.ts` integration draft uses existing safe DOM text
helpers, independent request generations, page/account guards, bounded pages
and explicit retry controls. Root owns production frontend wiring and browser
evidence; the draft is not a claim of delivered browser functionality.

## Opt-in prospective replay profile

The separately reviewed `QH_PAPER_SIGNAL_V1` new-session profile freezes a
declared horizon and intent expiry before Item8 and native execution; see
`PAPER_SIGNAL_PROFILE.md`. After the same full owned graph/native replay, this
reader calls its exact pure `signal_generation_contract` and
`paper_signal_fields` helpers and verifies repeated generation fields. It does
not generate the profile or retrofit it onto a legacy record.

Opted-in responses add the verified `signal_generation_contract` and per-signal
`generation` record. Horizon status is DECLARED_NOT_EVALUATED, with exact bar
count, end time and whether that time is inside the fixture. That boolean never
asserts target availability. Expiry supplies its exclusive boundary and
NOT_YET_GENERATED_AT_QUERY, WITHIN_DECLARED_TTL_NONACTIONABLE or EXPIRED_AT_QUERY.
These compare UTC query time to the frozen simulated timestamps. They do not
claim a wall-clock cancellation worker or that already filled positions vanished.
Legacy responses keep the exact original UNKNOWN_NOT_FROZEN shapes. Every
profile remains synthetic, nonactionable and without a calibrated probability.

## Verification evidence

The frozen author gate passed 37 tests with warnings treated as errors in
197.47 seconds, with 98.66% combined branch/statement coverage of both new
modules. Ruff check/format and strict mypy passed for both modules and tests.
Independent governance review executed seven selected real-store tests with
warnings treated as errors (30 deselected), passing in 127.44 seconds. These
covered formula/provenance/no new authority, fresh ownership, shared reservation,
actual learned Pattern results and all three SQL scan caps. The reported scan
bound finding is closed; this review certifies only the legacy read-only scope.
The ignored UI draft typechecked with strict TypeScript and
`noUncheckedIndexedAccess` against the current application helpers. It has not
been integrated or browser-executed by this agent. Independent correction
review evidence is retained separately in the handoff.
Tests use actual owned SQLite paper journals, immutable Item8 objects and one
actual registered learned Pattern run. Synthetic test evidence is not empirical
validation. Root remains responsible for full regression, runtime integration,
browser proof, decisions/traceability reconciliation and source-control backup.

The optional profile compatibility gate passed47 tests (the unchanged37 legacy
cases plus10 new actual-store cases), warnings as errors, in248.30 seconds.
Combined branch/statement coverage was98.14%; strict mypy and Ruff passed the
changed adapter and new tests, and the standalone UI draft passed strict
TypeScript/noUncheckedIndexedAccess/noUnused checks. Its actual profile fixture
exercises a fully recorded20-bar native session, exact expiry equality,
unevaluated beyond-fixture horizon, unchanged economic state on read and
coherently rehashed generation substitutions/removal. The first new fixture
incorrectly requested four bars below the existing20-bar minimum; those10 setup
errors are retained in `signals-profile-first.xml`, while its37 legacy tests
passed. The corrected final run uses a dedicated coverage data file; the first
parallel run shared a coverage filename and its combined percentage is not
usable slice evidence. No production bound was loosened to fix the fixture.
Optional compatibility independent review and integrated browser proof are
recorded separately; the legacy peer pass does not certify this new branch.
