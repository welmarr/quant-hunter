# Native owned PatternLab workflow

`web.pattern_access.PatternAccess` connects the reviewed QualityService,
immutable corpus/product modules, canonical registry and existing LabService.
It has no independent scientific lifecycle. SQLite holds private ownership and
operational receipts; Item8 alone freezes, starts and counts each experiment and
retains its outcome. No provider retrieval, broker call, credential or new
dependency is involved.

## Input, ownership and scientific meaning

Only an authenticated owner's own quality selection can become a corpus.
Researchers can operate on their own data; readers can inspect previously owned
objects but cannot mutate them. Every source parent remains referenced by exact
DATASET revision, normalized bytes, quality report, instrument revision and
calendar identity. Materialization verifies actual parent batches after resource
admission. Existing file/parser limits are unchanged; multi-file quality
composition supplies large corpora.

The corpus has a real canonical derived DATASET record. Its physical object is
explicitly a JSON manifest of actual immutable Parquet partitions. Its schema and
logical document fingerprint describe that manifest, not an invented monolithic
Parquet file. The record retains all actual parent DATASET/source IDs, immutable
lineage, code and environment. Gaps remain gaps and quality remains PENDING.

Each prepared configuration allocates a canonical PATTERN before evaluation.
The narrow `SOFTWARE_ONLY` schema profile requires SYNTHETIC, UNVALIDATED and an
explicit missing-validation reason. Validation and sealed dataset IDs are null.
No discovery dataset is reused as a holdout and no fake sealed dataset is created.
Initially unverified historical timing is still blocked for causal PatternLab.

LabService registers its own dataset containing the exact **software input
manifest bytes**. This is not the corpus Parquet. The full actual graph, corpus ID,
parent receipts, normalization, parameters, seed, cutoffs, prepared description
and PATTERN revision are bound in frozen configuration and manifest. The current
Lab adapter does not claim direct EXP.dataset_ids edges to the actual corpus.
Changing any query, configuration or software scenario queues a separately
registered and counted experiment. Reusing a preparation also creates a new EXP.

PAT03/04/05/06/09 additionally allocate an existing-schema `PROPOSED` MOD recipe
during preparation. Its exact canonical revision is bound into the PATTERN
definition and prepared envelope. Each execution or retry allocates a fresh MOD
fit child **before** Lab registration and before any fit; the recipe is never
reused as a fitted identity. Canonical FAM records identify the shared method,
so parameter siblings and refits do not become independent method families.
All unavailable scientific evidence stays UNKNOWN/PENDING; no schema extension
or VALIDATED status is introduced.

The immutable prefit record has no not-yet-existing experiment ID. Its actual
job-to-EXP link is retained in the operational receipt and exact frozen Lab
input/configuration and result. Failed attempts retain these model identities.
Fitted parameters, or an inconclusive method status, are a separate immutable
artifact bound to the exact fit MOD and observed method exposure. The recipe
never acquires parameters by mutation. PAT15's per-window z-normalization and
fixed PAA have no reusable trained parameters; it creates no fictitious model.
An existing preparation cannot execute under changed code/environment identities;
the user must prepare anew. Historical verified result inspection remains allowed.

Every fit record also binds the actual claimed job ID and owner. A FIT from an
earlier execution of the same recipe cannot replace the new execution's FIT.
Model data/source references and code revision are checked against the frozen
recipe/corpus/prepared graph when executing and when reading retained results.

## Operational jobs and restart

`POST /api/patterns/corpora` creates a durable `PATTERN_CORPUS` queued job and
returns 202 immediately. The runtime dispatches it to `execute_corpus_job`.
`POST /api/patterns/jobs` creates a `PATTERN_JOB` from an owned preparation and
the runtime dispatches it to `execute_job`. Both use the existing global queue
bound of eight and actual shared resource-operation admission. A once-only
SQLite receipt prevents duplicate dispatch from evaluating twice. Ownership and
the exact RUNNING job claim are rechecked before work.

The query worker calls LabService.begin_run, binds the EXP to its operational job,
verifies the exact frozen revision/configuration and current RUNNING attempt,
then invokes the reviewed product adapter. Each completed search partition
retains its immutable checkpoint digest and real progress. Completed outputs are
evaluated through LabService; ordinary failures are counted through its existing
failure/recovery path. Raw exception messages are never stored or returned.
Partial objects and registered failed preparations remain retained. There is no
automatic retry or computation replay.

Under the host's single-runtime lease, startup calls `PatternAccess.recover` to
mark unfinished operational receipts INTERRUPTED; existing runtime recovery owns
canonical unfinished EXP finalization and failed job status. Checkpoints remain
inspectable. The current native UI does not resume an unknown/closed attempt:
explicit retry creates a new counted experiment. The reviewed pure product's
exact checkpoint resume remains available to a future separately guarded host
same-attempt continuation, not an authorization supplied by a client digest.

Active-job polling reads private operational progress only. List pages show
bounded immutable manifest/description summaries. Detailed completed results
reverify exact source receipts, corpus lineage and canonical frozen binding.
Summary listing is not a fresh full data-quality replay.
Detailed corpus/preparation/result inspections and literal previews hold one
shared transient reader reservation. Internal operations reuse their verified
RUNNING reservation; they do not double-count a worker and its linked operation.
Preview returns at most 512 exact selected rows across partition boundaries,
with original indices, actual open/close/availability timestamps and source
feature values. It calculates no outcome and returns no bars outside that range.

If a completed result or successful attempt is retained before operational
finalization fails, canonical recovery preserves that exact outcome and finishes
only the operational receipt. It never recomputes or counts a second attempt.
Persistent persistence/integrity failures remain visible and are not relabeled
as successful completion.

Native corpus materialization is capped at 512 MiB, and each query's retained
checkpoints at 256 MiB. The stricter native admission reserves two GiB beyond the
existing 20 GiB/15% free-space floor and 30 GB runtime budget to allow concurrent
bounded operations. Metadata/result limits remain two MB; no size limit silently
drops provenance. Exhaustion is a retained failure. These are software admission
limits, not HOST_ENFORCED evidence.

## Explicit software controls

All fifteen families accept the same visible scenario vocabulary:

| Scenario | Actual action and interpretation |
|---|---|
| SELECTED | Exact bounded user configuration. No result expectation. |
| BASELINE | Declared reference configuration on an owned synthetic corpus of at least 200 rows. No guaranteed positive result. |
| POSITIVE | Reference configuration restricted to the exact raw SHA256, mapping, scaling, feature order, minute cadence, timestamps and XNYS calendar profile of the tested `qh-quality-demo-v1` two-instrument fixture, with one 240-row parent. It tests a known generated fixture; a match is not market evidence. |
| NULL | Candidate support cutoff is before the corpus's first bar. This is a **NO_ELIGIBLE_PAST temporal negative control**, expected to return UNKNOWN. It is not statistical-null calibration or a false-positive estimate. |
| SENSITIVITY | One fixed family parameter changes from the reference configuration. Both settings are retained separately; nothing chooses the better result. |

The catalogue exposes every change before execution: PAT01 stride16; PAT02 DTW
radius2; PAT03 shapelet length4; PAT04 alphabet6; PAT05 CUSUM threshold8; PAT06
three HMM states; PAT07 query length16; PAT08 recurrence radius0.75; PAT09 cluster
radius factor2; PAT10 breakout fraction0.002; PAT11 staleness60 seconds; PAT12–14
cost27bps versus the reference7bps; PAT15 PAA segments4. Every expanded setting
is in the immutable prepared configuration. The common reference uses the last
32-bar query, first128 training rows, known availability cutoffs, and next4-bar
observed outcomes. Training and query windows cannot bridge missing bars.

### Native feature-projection correction — 2026-10-05

The first native matrix used the complete seven-column OHLC/bid-ask/volume
fixture. The univariate CUSUM and spectrum/Haar methods truthfully returned
INCONCLUSIVE on those inputs. Those retained results are unchanged. The current
adapter explicitly freezes PAT05/PAT07 `feature_index` (default0, close) plus the
source column order and selected column name before MOD/EXP creation. An index
outside the actual schema is rejected, never silently substituted. CUSUM's
training and prediction and Haar's query use that single declared column with
their original timing and provenance. Common occurrence search continues to use
the full declared corpus schema. The selected method input is visible separately
in preparation, frozen config, method exposure and result.

This is a software input-adapter correction, not selection after inspecting
performance. New configurations receive new identities and counted experiments.
The parent integration task owns the corresponding durable decision entry.

All controls execute the real family method plus past-only occurrence search.
An insufficient family fit remains INCONCLUSIVE independently of MATCHES/UNKNOWN
from the common search. PAT15 runs its classical baseline; no deep model is
installed. PAT14's actual block permutation, core injected/no-structure tests,
independent exact search oracle and measured approximate recall are separate
evidence. This native control matrix cannot stand in for historical validation,
sealed evidence, FDR across research experiments, or profitability.

## Root integration API

Construct `PatternAccess(state, quality_access, lab)` with the same object and
registry authorities. Install routes with
`install_pattern_routes(app, authenticated, patterns)`; the host retains local
origin, session, CSRF and ordinary64KiB body enforcement.

| Route | Contract |
|---|---|
| GET `/api/patterns/catalogue` | Fifteen methods, exact scenario/sensitivity descriptions and scientific limits. |
| GET `/api/patterns/corpora?limit=10&offset=0` | Owned immutable manifest summaries; maximum25 per page. |
| POST `/api/patterns/corpora` | `{selection_digest, options?}`; queued corpus job202. Options are bounded `block_rows`, `max_rows`, `max_disk_bytes`, `max_shards`. |
| GET `/api/patterns/corpora/{dataset_id}` | Exact owned corpus and full verified parent graph. |
| GET `/api/patterns/corpora/{dataset_id}/preview?start=0&stop=240` | At most512 literal indexed bars; exact receipts, instrument revision, step and feature order. No computed outcomes. |
| POST `/api/patterns/prepare` | `{corpus_id, secondary_corpus_id?, scenario, family?, configuration?}`; immutable preparation201. SELECTED requires configuration; other scenarios require family and prohibit custom configuration. |
| GET `/api/patterns/prepared` | Owned description summaries with exact config and planned exposure. |
| GET `/api/patterns/prepared/{id}` | Full owned verified preparation. |
| POST `/api/patterns/jobs` | `{prepared_id}`; ordinary queued job202. |
| GET `/api/patterns/jobs/{id}` | Owned status/progress and, once complete, verified corpus or actual Lab result. |

Nanosecond configuration timestamps are decimal strings in JSON. Clients may
select a second **owned corpus ID** for PAT11; arbitrary secondary artifact
digests, paths and URLs are not accepted. Closed request models reject extra
fields, nonfinite values and out-of-range budgets without reflecting input in
errors. Existing queued-job cancellation remains the runtime's authority.

Preview shape is `{dataset_id, record_digest, manifest_digest, selection_digest,
row_start, row_stop, instrument_id, instrument_revision_digest, step_ns,
feature_columns, rows, evidence_mode, inspection}`. Each row is
`{row, open_ns, close_ns, available_ns, values}`; all timestamps are decimal
strings and values follow the close-first feature order. Gaps remain visible
in their actual timestamps. Prepared responses include `model_recipe` (null for
unlearned methods). Completed query results add `model_recipe`, `model_fit` and
`model_artifact`; an artifact receipt contains model_id, artifact_digest and the
actual EXECUTED/INCONCLUSIVE method status. No artifact means no invented fit.

## Evidence boundary

The native tests use real SQLite, governed schemas/registry, QualityAccess,
immutable source/corpus Parquet and LabService. They do not stub the lifecycle or
return canned results. The first actual PAT13 positive case passed, followed by
the full matrix and hostile checks recorded in the final handoff. Browser proof,
complete root regression, independent review and remote CI remain separate
gates. No actual market observation or external network request is used.

### Frozen native handoff evidence — 2026-10-05

The final native adapter snapshot passed 80 tests with 45 scenario-matrix cases
explicitly deselected, warnings treated as errors, in 722.65 seconds. Combined
statement/branch coverage across `pattern_access`, `pattern_routes` and
`pattern_models` was 90.19%, meeting the 90% gate. This run used the exact source
bytes in the release-reference package and the canonical governed schemas. The
earlier 100-test native run, including the complete fifteen-family by
three-scenario matrix, passed before the MOD/projection additions; it is retained
as preceding-snapshot evidence, not relabeled as the final 125-test suite.

On the final source, the 44 pure product/hostile/composition tests passed in
101.98 seconds. Independent review executed twelve targeted MOD/projection
tests in 107.94 seconds, with warnings treated as errors, and closed the reviewed
binding and projection findings. These focused results do not replace the
integration owner's complete regression or real browser walkthrough.

The retained `native-model-release` disk report passed both the independent
small-corpus oracle/resume check and the two-market synthetic calendar-decade
case. The latter actually wrote, reread and searched 4,734,600 rows: 977,640 XNYS
minute bars and 3,756,960 bars under the explicitly named FX_NY_17 convention.
It took 74.43 seconds with 133,672,960 peak process bytes and 207,705,542 total
disk bytes. The report separates source Parquet (96,235,049 bytes), reusable
corpus Parquet (96,229,539 bytes), and query checkpoints (14,436,687 bytes).
Exact tiny-corpus results matched the independent oracle and resumed results;
approximate recall at four was 0, 0.25, 0.5 and 1 for candidate caps 4, 16, 64 and
256. The failed small-cap retrievals remain evidence, not hidden by the planted
decade fixture's successful retrieval. These are synthetic software and scale
measurements, not market, global nearest-neighbor, or scientific validation.

The final handoff JSON records exact source/test/document hashes, commands and
private local evidence paths. Root integration owns the final all-125 native
test run, complete repository regression, browser evidence, durable decision
entry, commit and remote verification. This delegated slice made no Git or root
frontend changes.
