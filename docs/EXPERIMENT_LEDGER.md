# Experiment Ledger

## Policy

Every reproduction, hypothesis test, model comparison, parameter search, pattern search, ablation, and AI-generated candidate evaluation must be preregistered under a permanent, non-reusable `EXP-<uuidv7>` identifier allocated under DEC-0009 before results are inspected. Rejected, failed, null, invalidated, and inconclusive experiments remain visible; corrections append a new revision or superseding record rather than erasing history.

The ledger is the authoritative inventory of attempted research. It must support reconstruction of what was known, planned, searched, executed, observed, and decided.

## Required Metadata

Every record must contain:

- experiment ID and creation timestamp;
- study type: exploratory, confirmatory, reproduction, or operational validation;
- hypothesis;
- research family and referenced model, strategy, or pattern IDs;
- academic or institutional basis;
- datasets used and exact dataset vintages;
- data-provenance and source-registry references;
- instruments and sampling frequency;
- feature definitions;
- parameters considered and the declared search space;
- number of variants attempted, including AI-generated variants and failed runs;
- training interval;
- validation interval;
- untouched/sealed interval and its access-release event;
- transaction-cost and execution assumptions;
- results and reproducible artifact locations;
- failure modes;
- statistical tests and multiple-testing family/budget;
- decision and reason for decision;
- source-code commit or immutable code revision;
- exact configuration and immutable configuration hash;
- random seed where applicable;
- environment/configuration identifier; and
- dependencies on earlier experiments; and
- author or generating process.

These fields extend, but do not weaken, the original minimum schema. Unknown values must be marked explicitly with a reason; they may not be silently omitted.

## Lifecycle and Freeze Protocol

Use an auditable lifecycle such as `DRAFT → REGISTERED → FROZEN → RUNNING → EVALUATED → DECIDED`. The decision vocabulary is `CONTINUE_RESEARCH`, `REVISE_NEW_EXPERIMENT`, `REJECT`, `INCONCLUSIVE`, `DEFER`, `INVALIDATED`, or `SUPERSEDED`. `CONTINUE_RESEARCH` authorizes only the next research step; no ledger decision authorizes deployment or live trading.

Before `FROZEN`, record the hypothesis, data partitions, feature/label definitions, candidate universe, parameter/search budget, evaluation metrics, statistical tests, baselines, cost assumptions, and decision criteria. The sealed out-of-sample partition must be technically inaccessible to development workflows during this period. Freezing produces an immutable manifest and SHA-256 fingerprint binding the exact `REGISTERED` registry-revision digest, experiment ID and hypothesis, code revision, configuration, environment, data-manifest references and digests, seeds, search and multiple-testing budget, baselines, and decision criteria. Lifecycle transition timestamps are supplied explicitly by the caller; wall-clock lookup is not authoritative. Ordering preserves every fractional-second digit accepted by the common timestamp schema without floating-point conversion, rounding, or truncation.

Opening sealed data is a one-way, timestamped event. After it is opened, changes inspired by its results require a new experiment ID and a new sealed dataset; the old holdout becomes ordinary research data. Never tune against an already opened holdout while continuing to call it out-of-sample.

The Item 8B runtime authority verifies the complete registry chain, exact
`REGISTERED` predecessor, immutable freeze manifest, and unchanged frozen
science before appending `RUNNING`. `started_at` is caller supplied and must be
at or after `frozen_at` at every fractional digit accepted by the schema. Every
actual search exposure then appends one typed attempt record under registry CAS.
The record identifies its experiment and sequence, exact recording timestamp,
AI and failure flags, reason it counts as exposure, optional immutable variant
configuration digest, and prior-attempt link for a retry. Non-AI covers both
ordinary human and algorithm-generated work. Cumulative total, AI-generated,
and failed counters are reconstructed from the retained attempt records; a
failed AI attempt contributes once to total exposure and once to each applicable
subset counter. Attempt timestamps are nondecreasing, and no append may exceed
the frozen multiple-testing budget.

## Multiple Testing and AI

Count every candidate actually or implicitly searched: parameters, filters, assets, horizons, feature combinations, model prompts, code-generated variants, pattern candidates, retries, and human or AI suggestions. Record the total search exposure even when candidates fail before producing a report. Related variants remain grouped under their research family for correction and ensemble-independence analysis.

## Reproducibility and Retention

A result is not complete until another controlled run can reproduce it from recorded code, configuration, environment, seeds, data vintages, and immutable inputs. Preserve logs and failures needed to diagnose deviations. Never delete a record to make aggregate performance look better.

## Ledger Entries

No experiments are registered yet. Independent review passed Item 8A at commit
`79730f9ed54d6fcf9c8b33ad70af6181941c0b5e`. Item 8B adds only synthetic-tested
`FROZEN → RUNNING` and runtime-attempt accounting; it does not evaluate an
experiment, produce results or decisions, or release sealed data. Documentation
work is not a trading experiment, and no strategy experiment may begin until
Stage 1 controls in `ROADMAP.md` exist and the work is explicitly authorized.
Machine authority is the schema-validated JCS revision chain at
`registries/experiments/<id>/vNNNNNN.json`; generated summaries are
non-authoritative views.
