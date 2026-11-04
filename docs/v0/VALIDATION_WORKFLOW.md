# Owned chronological software workflow

Status: isolated implementation under test and independent review. This is
synthetic software evidence, not empirical validation or a released holdout.

`ValidationAccess(state, lab, quality)` uses existing AppState owned jobs and
LabService's actual Item8 register/freeze/begin/evaluate/fail operations. It creates
no competing attempt ledger. Each request selects exactly one fitted candidate:
TRAIN_MEAN or OLS_LAG_RETURNS. A comparison requires two explicit jobs and two
permanent experiments. Changed controls require another counted attempt; no
automatic model search, fallback, parameter search or interrupted computation
replay exists.

Submission reserves the existing shared resource-operation slot before exact
quality-graph replay/Parquet decoding. It resolves private ownership and exact
dataset/report receipts, freezes a canonical manifest of at most 2 MB, then
enqueues that immutable pointer in the existing queue. Preparation computes
timing intervals only. No return, label, learned normalization or model fit occurs
until the exact claimed RUNNING job has an actual bound Item8 experiment. A crash
after enqueue leaves the same owned queued definition visible; it never creates
an automatic retry. Process termination during evaluation is handled by the
existing runtime recovery over bound and orphaned Item8 attempts.

Execution links its data operation to the actual `worker_job_id`; parent and child
count as one resource, and a competing child is rejected before replay or research
registration. Detailed result reads hold one reader-capable transient reservation
around all quality, Lab and report verification. They do not consume import quota.
An ordinary operational write failure after successful canonical evaluation may
be finalized from that retained result; it does not rerun the mathematics or
invent another attempt. Persistent integrity/storage failures still propagate.

Only SYNTHETIC_SOFTWARE_ONLY causal-admitted normalized data is accepted. Every
execution and result read replays its complete quality graph and compares the
entire prepared description with the exact frozen manifest. Historic metadata or
unknown actual availability is never promoted by this adapter. No client-supplied
numerical rows, filesystem paths or provider calls are accepted.

## Prespecified diagnostic model

Features are the last `lookback` consecutive simple close returns, ending at the
decision bar close. A feature is usable only after all its constituent receipts.
The label is close[t+horizon]/close[t]-1, with actual receipt equal to the maximum
receipt across the full label support. Gapped support is excluded without
imputation. Delayed feature values and labels remain unread placeholders until
their timing permits numerical use; fitting still applies Item9's exact training
receipt and dependency checks.

TRAIN_MEAN predicts the arithmetic mean of only that fold's eligible training
labels. OLS_LAG_RETURNS fits an intercept and the lag-return columns after
centering/scaling each column using only that fold's training mean and population
standard deviation. NumPy's least-squares solver is called with fixed rcond=1e-12;
rank deficiency, scale <=1e-15, nonconvergence or condition >1e10 fails the trial
explicitly. No alternate model is silently selected. These are project-defined
software baselines, not claimed reproductions of a published empirical strategy.
The solver contract and rank/singular-value semantics were read from the
[official NumPy 2.5 documentation](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html)
on 2026-10-05.

Commission and slippage fields declare a one-way diagnostic return hurdle. They
do not represent fills, positions, spread, financing or realized profit. MSE/MAE
score prediction errors; the additional prediction-after-hurdle value is labelled
as such. No equity curve or trading-profit claim is generated.

## Exact chronological conventions

The existing Item9 invariant keeps every training fold inside development and
every validation segment inside validation. With multiple folds the training
prefix expands within development while validation segments advance separately.
This is called EXPANDING_DEVELOPMENT in product explanations; it never retrains
on prior validation outcomes. One fold uses the existing chronological-holdout
scheme. Each requested purge removes that many rows from its development prefix;
the actual full gap to validation is recorded and can be longer for early folds.
The embargo trims each validation segment and records the exact excluded interval.
All final interval ends are capped at the immutable source coverage end, which is
also the start of unused future sealed metadata. No sealed data object is read.

Minimum training/validation counts, lookback, horizon, split row count, fold count,
purge/embargo, model, costs, evaluation-as-of, bootstrap block length, repetitions,
seed, confidence and minimum observations are all frozen. Incomplete validation
segments stay PENDING; insufficient folds stay INCONCLUSIVE without fitting.
The source is capped at 10,000 rows, feature width 16 and five folds. Bootstrap
repetitions are capped at 1,000 under the existing ten-million-element work bound.
The full report, including memberships, exclusions and predictions, is a bounded
immutable object of at most 16 MB; the Item8 result contains its verified digest
and compact summaries.

The fixed noncircular moving-block interval describes mean absolute prediction
error in chronological retained-observation order, not win probability or
profitability. Gaps/overlapping label horizons and nonstationarity remain explicit
assumptions needing validation. The underlying conventions are in
`QUALITY_VALIDATION_DECISION.md`; there is no automatic block selection. No
calibrated preregistered per-trial p-values are available in this workflow, so Holm
validity stays INCONCLUSIVE with no invented adjusted values. The private response
projects aggregate counts from the actual canonical shared-family inventory,
including failures and inconclusive attempts, without exposing other owners'
experiment details. Item9B scientific evidence, empirical proof and the real
HOST_ENFORCED sealed gate remain missing and unclaimed.

## Application contract

`install_validation_routes(app, authenticated, access,
worker_available=...)` installs GET/POST `/api/validations/jobs`, GET
`/api/validations/jobs/{id}`, GET `/{id}/report` and POST `/{id}/cancel` with `{}`.
POST returns the existing queued Job and accepts exact dataset/record/report IDs
plus a closed `controls` object. Default controls are shown by the typed
`ValidationControls` definition; `evaluation_as_of` must be explicit UTC Z.
The normal host 64 KiB request bound is sufficient. Owner/researcher users submit
their own datasets; readers can read their own job results. All mutations use the
host CSRF/authentication boundary. Foreign IDs return a private denial.

`access.get(user, job_id, include_report=False)` returns
`{job, definition, run, report, family_exposure}`. `run` is the
verified existing Lab projection; `report` is null except on the explicit report
route. Runtime dispatch calls `access.execute_job(job)` only for kind
CHRONOLOGICAL_VALIDATION; the adapter handles final job completion itself. Existing
runtime interruption recovery remains authoritative. No UI or host wiring is
included in this isolated slice.

## Permanent models before fitting

The shared `study_model_ids.ModelIdentityBridge` now allocates a PROPOSED recipe
and fresh fit identities for every planned fold before Item8 begin/freeze. Mean
baseline folds each receive an estimator MOD. OLS folds each receive separate
standardizer and estimator MODs. The exact plan, owned job, selected canonical
dataset/source references and original submission bytes are bound into all
records. Actual fitted parameters are retained in the immutable full report and
a separate EXP-linked model artifact; pending/insufficient folds retain null
outputs and their unused permanent IDs. Solver failures preserve the model
records and the failed Item8 attempt.

The Lab input is now an explicit model-aware software input manifest referencing
the original immutable submission, rather than the submission bytes directly.
The user-facing `definition` and submission digest stay unchanged. Report reads
reverify the full model graph; current execution checks the active producer while
historical reads retain the old producer. See `MODEL_IDENTITIES.md` for the exact
API, graph, fit map and proposed durable decision. No OLS, mean, temporal,
bootstrap or multiple-testing calculation is changed by this identity addition.
