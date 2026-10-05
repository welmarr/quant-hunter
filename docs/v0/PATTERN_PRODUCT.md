# PatternLab corpus and registered-job adapter

This layer uses actual immutable Parquet partitions and all fifteen reviewed
classical methods. It does not implement a competing registry, lifecycle,
authentication system, worker queue or scientific approval. The native host owns
those responsibilities through existing Item8 and its private job/ownership store.
Historical uploads with unverified availability remain ineligible for causal
PatternLab jobs. Initially only `SYNTHETIC_SOFTWARE_ONLY` selected snapshots pass.

## Corpus input and composition

`CorpusStore(ImmutableObjectStore)` publishes through the existing object store.
The host must first authenticate, establish ownership of every selected parent,
verify its canonical record and obtain a `SelectedSnapshot` from QualityService.
No client filepath or URL is accepted by this adapter.

`build(new_dataset_id, selected_snapshot, verified_parquet_bytes, config=...)`
checks the exact normalized digest, row count, UTC time schema and numeric columns,
then publishes bounded partitions. The host allocates the permanent corpus
DATASET identity before this transformation and registers the resulting manifest
as a derived version with its actual parent identities. The adapter never writes
a second registry.

`build_selection(new_dataset_id, PartitionSelection, batches, config=...)` handles
the usable multi-file path. `QualityService.iter_batches(selection_digest)` yields
`(parent_index, RecordBatch)` pairs. Every parent must appear in declared order and
contribute exactly its declared rows. Reordering, duplicates and overlaps fail;
gaps remain gaps. The manifest retains every parent's exact dataset record,
normalized bytes, quality report, instrument revision and bounded calendar
digest, plus the selection manifest and shared calendar rules/profile digest.
Different date-range calendar digests are expected. No invented collective raw
dataset identity substitutes for those references. Batches are combined into
bounded output partitions without materializing the whole corpus.

`build_frames` is a trusted host extension for already verified streaming sources
and explicitly labelled synthetic load fixtures. Frame labels alone do not prove
upstream provenance. The application single-upload route uses `build`; its
multi-file route uses verified QualityService composition. Parser/upload limits
are unchanged; scale is achieved by composition, not by accepting one unlimited
upload.

The manifest is an exact row/time partition index. Each partition records SHA256,
row span, byte size, first/last close, availability bounds and missing-cadence
count. Loading a partition verifies bytes, Arrow schema, row count and these
index facts. A selected window can span files; a missing bar/session gap prevents
it from becoming one continuous window. `time_frame` aligns secondary instruments
by actual close times rather than assuming matching row numbers.

## Preparation and Item8 binding

`PatternProduct(corpora).prepare(corpus_manifest, PatternJobConfig,
pattern_id=..., code_revision=..., environment_digest=...)` performs validation
and publishes an immutable description. It does not fit, search, score or test
outcomes. PATTERN is allocated first. Preparation deliberately does not require
EXP, because the reviewed LabService allocates/freezes EXP when a run begins.

The prepared record includes the exact source/parent manifests, query fingerprint,
expanded method parameters, code/environment, one complete configuration variant,
training row range/stride/cap, maximum considered windows, candidate pool/rerank
limits, cutoff/purge rules, seed and cost assumptions. Root includes this prepared
digest in its actual frozen Lab configuration and input references. Changing a
query, parameter, universe, source version or cutoff is another counted variant.
Individual occurrence windows are not invented as separate strategy identities.

After verifying the canonical frozen definition, its prepared reference and the
current owned RUNNING Item8 attempt, root supplies
`FrozenPatternBinding(experiment_id, experiment_record_digest,
configuration_digest, prepared_digest, pattern_id)` to
`execute_registered(prepared_digest, binding=..., ...)`. The canonical wrapped
Lab configuration digest is distinct from the prepared artifact digest; both are
retained. The binding type validates identity shape, not lifecycle authority.
Execution recomputes the entire pure prepared description and compares its exact
canonical bytes before evaluating anything. This binds repeated parent/scope and
expanded-parameter fields; a coherently rehashed inconsistent description fails.

Required configuration fields are family, query row start/stop, training row
start/stop, decision time, training cutoff and candidate-support cutoff. Options
include purge, normalization, exact/approximate mode, distance, horizon/cost,
PAA/candidate/result/DTW bounds, training cap, seed, closed per-family parameter
JSON and a second owned corpus for PAT11. UTC nanoseconds are strings in canonical
JSON to preserve exactness above the I-JSON safe-integer range.

## Execution and restart

All families run the actual common occurrence search plus their own concrete
classical computation. Methods that cannot fit the selected data retain an
`INCONCLUSIVE` reason; no model or metric is fabricated. PAT15 executes its PAA
baseline and explicitly reports that no deep representation is installed.
Training windows and labels obey availability, purge and chronological bounds.
Future outcomes must be complete and available by the decision; candidate
pattern-plus-outcome support must precede the frozen candidate cutoff.

Search reads one partition at a time. A halo of `window+horizon-1` rows prevents
boundary omissions. The query's PAA candidate pool is a bounded per-query index,
not a global ANN index. APPROXIMATE mode may miss true neighbors; EXACT_SMALL
fails when the candidate cap cannot hold every eligible window. It never silently
substitutes approximation. Returned events suppress overlapping supports; their
count is not a measured independent effective sample size.

After each completed partition a closed, versioned canonical JSON checkpoint
retains query, configuration, candidate values/outcomes, halo, counters, corpus
partition digests and exact Item8 binding. Arrays and timestamp integers have
explicit bounded encodings. There is no pickle, dynamic class import or executable
payload. Resume re-establishes the core candidate schema, score, availability,
cadence and outcome invariants and exact completed-partition row count. It also
rereads each retained candidate's bounded support and the halo from the immutable
corpus, checking exact values, times, availability and recomputed outcomes. Its
immutable previous-checkpoint chain binds serialized byte accounting, consecutive
partition links and the mandatory partition-one genesis. The host additionally
requires the exact checkpoint digest retained by its own attempt authority.

`PatternJobCancelledError.checkpoint_digest` identifies the last completed step.
The host must retain it with cancelled/failed job evidence. Resumption visits the
next partition; completed work is not rescanned. No artifact is overwritten or
deleted to make room. Exhausted disk/row/candidate bounds fail explicitly.

Results include actual raw and normalized query/occurrence arrays, dates,
provenance, distance, complete observed horizon outcomes, negative cases,
histogram/quantiles, method/model diagnostics and UNKNOWN/INSUFFICIENT states.
Exposure includes visited/eligible/excluded windows, candidate pool/rerank count,
deduplicated events and attempted fitting/training scope. Outcome returns deduct
the declared basis-point scenario; they are closing-mark diagnostics, not fills,
portfolio performance or profit probabilities. PAT14 retains block-null
assumptions; complete cross-experiment FDR remains a host research responsibility.

## Bounds and verification

Default partitions are 32,768 rows (maximum 65,536); corpus caps are 10 million rows,
1 GiB Parquet plus manifest and 2,048 partitions, configurable up to 50 million rows
with explicit bounded disk. No shard exceeds 16 MiB; manifests are at most 2 MiB.
Prepared descriptions also allow at most 2 MiB, retaining all partition parents.
Product windows are 8–256 bars, horizons 1–256, candidates at most 256 and overlays
at most 40. Training is at most 4,096 rows and 64 windows. Query scratch is 16 MiB; retained arrays,
Arrow/Python/runtime overhead are additional and whole-process peak is measured
separately in benchmarks. Checkpoints are at most 32 MiB each and default to 256 MiB
cumulative retained bytes per query, with an explicit maximum 1 GiB. These are
software bounds, not `HOST_ENFORCED` claims.

The first focused gate executed 50 tests with warnings treated as errors, including
all 15 methods on real Parquet, partition halos, multi-parent composition, actual
immutable cancellation/resume equivalence, OOD/inconclusive cases and hostile
bindings/serialization/budgets. Combined statement/branch coverage of the three
new modules was 91.52%. Independent review, broader regression, real native product
integration and disk-scale evidence are separate gates. The older pure computation
benchmark is not passed off as Parquet or persistent-index evidence.

Independent review reproduced inconsistent rehashed descriptions, composition
references and checkpoint outcomes, a truncated byte-accounting chain, and a
PAT12 bootstrap block setting silently clipped to observed event count. These
are corrected with targeted hostile regressions. Frozen bootstrap length is
preserved; fewer than two full blocks makes the method inconclusive and emits no
bootstrap interval. Composition manifests are dereferenced and rebound on every
corpus load. The first large FX disk run also exposed an insufficient prepared
metadata cap; its failure is retained rather than dropping parent provenance.

The corrected combined old/new Pattern gate passed 137 tests with `-W error`.
The three new modules reached 91.55% combined statement/branch coverage. Ruff and
strict mypy passed on all nine new source/test files. Independent review closed
the five material consistency findings through reread and independently executed
reproductions. These results do not replace native authentication, operational
job recovery, canonical Item8 integration, or the complete project regression.

## Native integration and control exposure

`PatternJobConfig` and `_PARAMETERS` in `product.py` are the authoritative closed
configuration schema. The result's `method.status=EXECUTED` means computation
occurred; it is never a scientific pass. `state` describes the common occurrence
search (`MATCHES` or `UNKNOWN`). `method` can independently be `INCONCLUSIVE`.
Results contain exact canonical binding/prepared/corpus digests, complete parents,
configuration, expanded method parameters, query/occurrence raw and normalized
arrays, timing/provenance, distances, complete observed outcomes, negative cases,
histogram, descriptive uncertainty, actual search/fit exposure and limitations.

Every family uses the shared actual past-only occurrence search. The additional
family computation and currently measured software oracle are listed below.
Sensitivity settings are supported inputs, not claims that a complete native
registered sensitivity study has already run.

| Family | Actual additional output | Existing software oracle/control | Configurable sensitivity |
|---|---|---|---|
| PAT-01 | Training-segment motif profile and discord | Repeated motif/discord with exclusion | Training stride, query window, normalization |
| PAT-02 | Constrained DTW comparisons on retained occurrences | Hand distance/band oracle; work budget | DTW radius, maximum distance |
| PAT-03 | Train-only shapelet, selected threshold, classification | Available-label fitting and holdout prediction; schema refusal | Shapelet length and candidate cap |
| PAT-04 | Fitted SAX quantiles/vocabulary and query word/state | Train vocabulary; unseen word UNKNOWN; overlap refusal | Alphabet and PAA segments |
| PAT-05 | Train-normalized CUSUM model and forward detections | Future-suffix invariance; feature/cadence binding | Allowance, threshold, scale floor |
| PAT-06 | Train-fitted HMM and forward filtered probabilities | Training cutoff; prefix unaffected by future suffix | States, iterations, variance floor |
| PAT-07 | Hann spectrum and Haar summaries | Known frequency and energy oracles | Query window and source selection |
| PAT-08 | Recurrence statistics | Four-point independently calculable oracle | Radius, Theiler exclusion, minimum line |
| PAT-09 | Fitted medoid clusters, query assignment/distance or UNKNOWN | Explicit out-of-distribution rejection | Cluster count, radius factor, PAA segments |
| PAT-10 | Explicit geometric rule diagnostics | Independent breakout boundaries | Breakout fraction and channel tolerance |
| PAT-11 | Actual close-time/as-of alignment of two owned instruments | Not-yet-available values excluded | Secondary corpus, maximum staleness |
| PAT-12 | Observed outcome distribution with fixed block bootstrap | Cost/timing oracles; insufficient fixed-block regression | Minimum events, resamples, block length, horizon/cost |
| PAT-13 | Search state, exact reranks and exact/approximate mode | Independent disk brute-force ranking; measured approximate recall and false negatives; UNKNOWN null | Candidate cap, normalization, distance, horizon/cost |
| PAT-14 | Period stability/cost diagnostics and block-permutation null when eligible | Known null/FDR arithmetic; explicit insufficient group/sample result | Periods, permutations and block length |
| PAT-15 | Executed classical PAA representation comparison contract | Baseline succeeds without an invented deep model | PAA segments; optional learned model remains uninstalled/unvalidated |

There is no automatic native positive/null/sensitivity scenario catalogue in this
adapter. The host must expose registered explicit configurations/fixtures and
count every scenario or parameter change separately. The table records software
test evidence, not completed historical validation or a passed native control
campaign. Full cross-experiment FDR, sealed holdouts, empirical quality admission,
model promotion and optional deep training are not supplied by this layer.

## Actual disk-scale evidence

The final retained run is
`D:/quant-hunter/.local/v0-pattern-product-proof/disk-release/benchmark.json`.
It records exact source hashes, Python 3.14.7, NumPy 2.5.3, PyArrow 25.0.1, pinned
calendar/timezone versions, all calendar schedule digests, bounds, seeds, corpus
and result digests. Source, corpus, and query checkpoints are actual files read
back through the immutable object store. Each source file stays below the existing
2,000,000-byte / 100,000-row intake bounds; the FX decade retains 115 source parents.
The source selection and corpus manifests preserve every parent. No acquisition
or credential was used. Calendar metadata is read from actual pinned rule output.

| Actual case | Rows | Total seconds | Peak process bytes | Source Parquet bytes | Corpus Parquet bytes | Query checkpoint bytes |
|---|---:|---:|---:|---:|---:|---:|
| NYSE day | 390 | 1.57 | 114,515,968 | 8,660 | 8,622 | 91,611 |
| NYSE year | 97,920 | 2.24 | 127,975,424 | 2,007,844 | 2,007,730 | 278,469 |
| NYSE 2015–2024 labels | 977,640 | 16.64 | 130,813,952 | 20,115,168 | 20,114,028 | 2,837,300 |
| FX NY 17:00 2015–2024 labels | 3,756,960 | 29.27 | 127,057,920 | 76,119,881 | 76,115,511 | 11,599,387 |
| Both decades, actual sequential corpora/queries | 4,734,600 | 49.71 | 135,426,048 | 96,235,049 | 96,229,539 | 14,436,687 |

Total time includes generation, source publication, corpus materialization, query,
checkpoint cancellation/resumption and result retention. Two-asset disk usage was
207,704,648 bytes including metadata/results, below the 512 MiB case cap. Whole
process peak stayed below 1 GiB. Progress records are emitted at approximately
five-second boundaries; the cooperative case cap is 180 seconds and the parent
process deadline is 210 seconds. These are measured local software limits, not
host-enforcement guarantees or cloud cost predictions. New outputs require a
fresh directory; failures and prior valid runs remain retained.

The independent 256-row disk oracle verifies exhaustive RMS ranking, overlap
suppression and direct-versus-resumed equality. Its approximate recall@4 measured
0%, 25%, 50%, and 100% at candidate caps 4, 16, 64, and 256. Exact false-negative
indices remain in the report. A zero-distance negative control returned UNKNOWN.
Each decade recovered its ten exactly planted software motifs with zero extra
matches at the frozen threshold. That constructed recall is not general market
pattern recall or a profitability claim. All values are generated; actual dates
come from pinned calendars. The FX convention has unknown venue holidays and is
not a universal exchange calendar. Raw coverage bounds, including overnight FX
opening dates, are recorded separately from session labels.

Reproduction from this checkout (TEMP/TMP and caches must already point to D):

```powershell
$env:PYTHONPATH='D:/quant-hunter/.tools/v0-worktrees/ui/src'
$env:PYTHONDONTWRITEBYTECODE='1'
& D:/quant-hunter/.venv/Scripts/python.exe tests/test_v0_pattern_product_benchmark.py --output D:/quant-hunter/.local/v0-pattern-product-proof/NEW_DIRECTORY
```

The harness uses explicit synthetic typed fixture records and separately labelled
placeholder canonical binding evidence. It does not claim to execute host Item8
registration, quality certification, authentication or a native browser workflow.
The final source hashes in its report identify the code actually measured.
Historical/provider acquisition cost remains UNKNOWN; this offline run incurred
no new purchase or API acquisition. Larger universes, learned representations and
other frequencies require separately measured/registered work, not extrapolated
performance promises.
