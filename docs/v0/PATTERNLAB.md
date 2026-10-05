# PatternLab pure computation layer

This module implements bounded classical software methods for the authorized V0
mission. It has no file, network, registry, credential, broker, lifecycle or
scientific-promotion capability. Synthetic tests establish arithmetic and causal
software behavior, not market predictability. Application integration must create
permanent PATTERN/EXP identities, preregister all candidate and parameter exposure,
freeze data/partition/configuration identities, and retain failed or null results
through existing Item 8 authorities before running research. `PAT-01` through
`PAT-15` below are catalogue keys, never permanent research-object identifiers.

## Implemented methods

| Family | Concrete implementation | Essential limit |
|---|---|---|
| PAT-01 | Exact small-corpus z-normalized subsequence nearest-neighbor profile, repeated motifs and discord ordering | Retrospective TRAIN discovery; excludes intersecting windows; bounded profile and arithmetic work |
| PAT-02 | Multivariate squared-cost Sakoe-Chiba-band DTW with optional row-minimum abandonment | Explicit radius/cell budget; sqrt(cost/(n+m)), not path-length normalization |
| PAT-03 | Exhaustively scored deterministic bounded shapelet candidates, best binary information-gain split | All candidate windows and label horizons must be available inside TRAIN; rejected searches remain exposures |
| PAT-04 | PAA with training-quantile SAX breakpoints, frozen word vocabulary and counted chronological transitions | Empirical SAX variant; no Gaussian-SAX lower-bound claim; unseen word is UNKNOWN |
| PAT-05 | Training mean/scale, two-sided standardized CUSUM, reset upon threshold crossing | Forward-only detection; allowance, scale floor and threshold explicit |
| PAT-06 | Diagonal Gaussian HMM with bounded Baum-Welch fitting | Backward messages stay inside TRAIN; prediction is forward filtering only; latent states have no automatic economic names |
| PAT-07 | Demeaned Hann-window real Fourier spectrum and orthonormal Haar decomposition | Power-of-two closed windows, no padding; finite-window boundary/leakage effects explicit |
| PAT-08 | Recurrence rate, diagonal determinism, vertical laminarity and trapping time | Window-local z normalization, distance threshold, Theiler exclusion and minimum line lengths explicit |
| PAT-09 | Deterministic farthest-first, alternate k-medoids on window-z PAA | Train-calibrated cluster radii; outliers return None/UNKNOWN, never forced membership |
| PAT-10 | Strict prior-close range breakout and least-squares channel with maximum relative residual | Thresholds are mathematical definitions; close marks are not executable quotes |
| PAT-11 | Availability-aware multivariate backward alignment | Zero staleness means simultaneous observations; nonzero carry bound is explicit; no future nearest join |
| PAT-12 | Deduplicated observed horizon distributions, quantiles, closing-mark excursions and circular event-block bootstrap mean interval | Horizon end and actual availability are separate; insufficient samples remain INSUFFICIENT |
| PAT-13 | Blockwise historical search, PAA candidate reduction and bounded exact Euclidean/DTW reranking | Strictly earlier candidate support plus known complete outcomes; APPROXIMATE and EXACT_SMALL are explicit |
| PAT-14 | Chronological period summaries, event frequency, cost sensitivity, block-permutation null contrast and BH/BY adjustment | BY arbitrary-dependence adjustment is default; numerical diagnostics cannot close scientific validation gates |
| PAT-15 | Executable classical PAA representation baseline and optional representation protocol | No deep model is installed or validated; optional execution remains EXECUTED_UNVALIDATED |

## Input, time and fitting contracts

`Provenance(dataset_id, dataset_version, instrument_id, timeframe, features)`
retains supplied identities. These labels do not establish governed validity.
`CausalFrame(values, close_ns, available_ns, step_ns, provenance)` accepts finite
float64 features and integral UTC nanoseconds. Frames contain at most 65,536 rows
and 16 distinct features. The arrays are defensively copied to immutable
bytes-backed buffers. Actual availability cannot precede a bar close. Missing
observations are not imputed. Invalid values fail closed rather than being
silently discarded. Callers must provide verified upstream vintage semantics;
this numeric layer cannot infer whether a supplied availability claim is true.

`frame.window(start, stop, decision_ns=...)` returns a 2–512-bar
`PatternWindow` only if every bar is closed and actually available. Time spacing
must equal the declared grid, so a gap or session boundary cannot silently enter
a window. Start/end represent the complete support interval. The maximum known
time is retained separately. Content fingerprints are numeric-layer fingerprints,
not canonical registry revision digests, and grant no registry authority.

`FitContext(train_cutoff_ns, validation_start_ns, purge_ns=0)` requires training
plus purge to end strictly before validation. Shapelet labels retain both
`horizon_end_ns` and `available_ns`; all support must fit inside training.
Shapelet/SAX/cluster fitting accepts explicit bounded training-window tuples.
HMM/CUSUM fitting selects only observations available by the training cutoff.
Prediction methods reject windows beginning before the frozen validation boundary.
Model fitting records training fingerprints; future rows are never used for
normalizers, vocabulary, medoids, HMM parameters or detector baselines.

Normalizations are explicit: RAW, BASE100, arithmetic returns, log returns,
window-local z scores, and strictly preceding-return causal volatility scaling.
The first return is zero; causal-volatility output is zero until two earlier
returns exist, and when earlier volatility is zero. Price transformations require
positive prices. Constant z windows map to zero. `relative_candles` uses explicit
open/high/low/close columns and retains body, wicks and opening-gap coordinates
relative to the prior close. It does not adjust splits or corporate actions.
Upstream adapters must distinguish marks, executable bid/ask and adjusted prices.

## Search, event counts and restart

`SearchEngine(query, config, decision_ns)` processes one ordered instrument/grid
stream using `consume(block, cancelled=...)`. `search_blocks` adds progress and
cancellation callbacks for worker integration. A halo of
`query_length + horizon - 1` rows preserves windows crossing block/partition
boundaries. Missing-time boundaries remain excluded. The corpus/version/feature
schema cannot change inside a stream. Multi-instrument or multiscale callers run
explicit streams and combine results using `deduplicate`, retaining every source.

PAA candidate distances filter the stream, retaining at most `candidate_cap`
windows. Exact reranking is limited to that pool. Approximate results may miss
true neighbors and must never be called exhaustive. EXACT_SMALL fails if all
eligible windows cannot fit its declared cap. Query support and outcome support
must precede the query's start minus the exclusion duration; actual outcome
availability must also be no later than the decision. A configured maximum exact
distance permits UNKNOWN when there are no sufficiently close candidates.

Each block step commits its state only after completing successfully. A stopped
worker can retain `engine.snapshot()` and reconstruct with
`SearchEngine.resume(snapshot)` without rescanning earlier blocks. The snapshot
contains parameters, query, bounded candidate pool, halo and coverage counters.
Resume checks temporal eligibility, corpus/halo identity, sampling cadence,
candidate scores, and exact outcome-presence/horizon/cost agreement with the
frozen configuration. CUSUM predictions bind the training feature identity and
sampling cadence as well as the training cutoff.
The application must serialize/version/checksum snapshots and bind them to the
registered immutable corpus; the core adds no competing persistence writer.
Cancellation is checked at block boundaries and between exact reranks.

Best-first deduplication suppresses intersecting pattern-plus-outcome intervals
for the same instrument, including results from different families/timeframes.
Explicit common `event_group` labels can join known cross-asset events. Unknown
cross-asset dependence is not treated as independence. The retained event count
is not a claimed effective independent sample size. Outcome summaries reject
mixed instruments or horizons, preserve zero/negative outcomes, and report
closing-mark rather than intrabar excursions. The separately labelled Wilson
interval is an IID descriptive approximation; block-bootstrap assumptions also
remain unproven until independent research validation. Similarity and historical
positive-return frequency are never displayed as future profit confidence.

## Resource and evidence bounds

Search caps include 50 million scanned rows, at most 4,096 retained candidates,
100 returned events, 128 MiB declared scratch budget, 512-bar windows/horizons,
and at most two million exact DTW reranking cells. The scratch budget excludes
the retained candidate pool and input buffers; benchmark process peak RAM must
therefore be measured separately. Fit profiles cap training windows, features,
candidate counts, HMM states/iterations, profile arithmetic, recurrence matrices
and alignment rows. These are bounded first methods, not claims that every
variant listed in the long-term research specification is implemented.

The initial focused tests cover all fifteen executable catalogue entries,
hand-calculated DTW/Haar/recurrence/cost oracles, discriminative synthetic
shapelets, SAX novelty, HMM train and inference future perturbations, availability
and purge failures, alignment delays, event overlap, actual outcome availability,
checkpoint substitution, partition halos, null results and optional-model absence.
No provider request or real market acquisition is required for synthetic scale
testing.

### Executed synthetic scale evidence, 2026-10-05

The opt-in `tests/test_v0_patterns_benchmark.py` harness completed all five
progressive cases on Windows 11, Python 3.14.7, NumPy 2.5.3,
exchange-calendars 4.13.2 and tzdata 2026.5. Prices are generated software-test
signals with seed 20261005; timestamps come from actual pinned calendar rules.
The NYSE date labels cover 2015-01-01 through 2024-12-31, including holidays and
early closes. The FX schedule is the explicitly named NY17 weekday convention;
its venue-specific holiday truth remains unknown.

| Case | Rows consumed | Wall seconds | Peak process working set, bytes |
|---|---:|---:|---:|
| One XNYS session | 390 | 0.774 | 105,574,400 |
| One XNYS calendar year | 97,920 | 0.996 | 113,061,888 |
| Ten XNYS calendar years | 977,640 | 3.700 | 116,871,168 |
| Ten FX NY17 convention years | 3,756,960 | 4.220 | 56,197,120 |
| Both ten-year streams, sequential | 4,734,600 | 8.816 | 119,640,064 |

Each case runs in a fresh subprocess. The two-market case processes two
separate instrument streams sequentially, without claiming cross-asset
independence. The configured limits were 60 seconds per stream and 1 GiB peak
process RAM; maximum measured peak was about 114.1 MiB. Search blocks contain at
most 32,768 rows, with a 32-bar window, four-bar closing-mark outcome, 7 bps
declared cost deduction, window z-normalization, eight PAA segments, a 256-window
candidate cap, and 16 MiB scratch budget. All yearly planted exact motifs were
recovered. Completed blocks were canceled/reconstructed once and scanning
continued without rescanning prior rows. The separate small partition oracle
compares complete and resumed rankings.

A 512-row independent dense RMS/overlap oracle exactly matched all eight
EXACT_SMALL ranked events across 477 eligible windows. On that same seeded
corpus, approximate candidate caps 8, 32 and 128 produced recall@8 of 0%, 25%
and 100%, with 8, 6 and 0 false negatives respectively. The cap-8 result returned
only three non-overlapping events. A separate noise-only exact-match control
returned UNKNOWN with zero matches. These observations demonstrate why a small
candidate cap cannot guarantee global nearest-neighbor recall. The harness PASS
status means its declared mechanical assertions completed; it is neither a
general retrieval-quality certification nor evidence of a profitable pattern.

The local evidence is `.local/v0-pattern-proof/scale-first/benchmark.json` plus
five case JSON records. It includes exact source SHA-256 snapshots, environment,
actual timestamp bounds, annual calendar digests, generated value/timestamp
digests, candidate/coverage counts, and per-case measurements. It explicitly
references an uncommitted source snapshot, not a fabricated final Git commit.
Inputs were generated in memory: input-dataset disk bytes and persistent-index
bytes are zero. This is not a Parquet ingestion, disk-index, multi-query service
or empirical-data benchmark. Reproduce without overwriting prior evidence:

```powershell
python -m pytest tests/test_v0_patterns.py tests/test_v0_patterns_hostile.py tests/test_v0_patterns_benchmark.py -q -W error
python tests/test_v0_patterns_benchmark.py --output .local/v0-pattern-proof/new-run
```

The parent task owns full-repository regression, independent review, application
integration, decision/risk reconciliation and Git evidence. Focused core tests
alone do not establish full V0 acceptance or any scientific gate.

## Primary method references

Consulted 2026-10-05. Implementations are independently written bounded variants:

- [UCR Matrix Profile research](https://www.cs.ucr.edu/~eamonn/MatrixProfile.html),
  [exact subsequence motifs](https://www.cs.ucr.edu/~eamonn/exact_motif/), and
  [constrained-DTW lower-bound research](https://www.cs.ucr.edu/~eamonn/LB_Keogh.htm).
  This core does not claim to implement STOMP, SCAMP or LB_Keogh indexing.
- [SAX authors' paper](https://www.cs.ucr.edu/~eamonn/SAX.pdf); this module's
  empirical training quantiles deliberately differ from Gaussian SAX breakpoints.
- [Ye and Keogh shapelet paper](https://doi.org/10.1007/s10618-010-0179-5).
- [NIST CUSUM handbook](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm).
- [Murphy HMM toolbox and references](https://www.cs.ubc.ca/~murphyk/Bayes/PreMIT/hmm.html).
- [NumPy real FFT documentation](https://numpy.org/doc/stable/reference/generated/numpy.fft.rfft.html).
- [Marwan recurrence-quantification definitions](https://www.recurrence-plot.tk/rqa.php).
- [Schubert and Rousseeuw k-medoids research](https://arxiv.org/abs/1810.05691);
  this module uses the bounded alternate algorithm, not FasterPAM.
- [Benjamini and Hochberg original FDR paper](https://www.stat.purdue.edu/~doerge/BIOINFORM.D/FALL06/Benjamini%20and%20Y%20FDR.pdf).
  Dependence assumptions and complete search exposure remain mandatory.
