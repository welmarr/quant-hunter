# Roadmap

## Stage Gates

Progression is evidence-gated, not calendar-gated. No later stage is authorized by completing an earlier document. Strategy implementation, paper trading, shadow validation, and controlled capital each require separate scope and approval.

## Stage 0 — Documentation Architecture

**Status: COMPLETE (2026-09-04).** The original architecture and independent-review corrections passed documentation-only verification. This status does not authorize Stage 1.

Deliver and cross-link the persistent operating rules, charter, architecture, research methodology, validation standard, data specifications, registries, pattern-lab requirements, decisions, risks, roadmap, and traceability map. Audit the hierarchy against the former master specification.

**Exit gate:** all requirements have a governing home, all required documents exist, links and required rule phrases pass review, and no strategy or Stage 1 code has been introduced.

## Stage 1 — Reproducible Research Foundation

Do not implement the proposed 200 strategies.

### Stage 1A — Foundational Planning

**Status: COMPLETE (2026-09-04).** DEC-0004–DEC-0010 resolve the runtime, environment/lockfile, sealed OOS boundary, canonical configuration/artifact hashing, engineering quality gate, permanent identifier/registry design, and Month-1 accounting policy. `ARCHITECTURE.md` reflects the material consequences. Completion makes the zero-cost implementation plan ready for a separate authorization; it does not authorize Stage 1B.

### Stage 1B — Foundation Implementation

**Status: IN PROGRESS — BATCH 3B COMPLETE (2026-09-05).** Batches 1–2
completed items 1–4 below, Batch 3A completed item 5, and Batch 3B completed
item 6 only. Items 7–13 remain unauthorized and unstarted. Execute future work
only through a separate explicit batch authorization:

1. **Preflight and boundary evidence:** reread governing documents; inventory the host without exposing data; reverify Git through the exact-path ephemeral trust method or an owner-approved persistent repository-specific remedy (never a wildcard); record the repository/CI state and budget facts; verify that a separate encrypted NTFS location, OS identities, ACLs, and auditing are feasible. Obtain explicit host-admin approval before persistent ownership/trust, account, volume, audit-policy, or ACL mutations.
2. **Minimal package scaffold:** create only the `src/quant_hunter` foundation package, `tests`, `schemas`, `registries`, `configs`, and manifest directories; configure CPython 3.14, PEP 621/Hatchling, `.python-version`, pinned uv bootstrap metadata, `.venv` exclusion, and committed `uv.lock`.
3. **Quality gate first:** configure Ruff, strict mypy, pytest, branch coverage, deterministic/offline markers, and the documented `uv run --locked` commands. Add least-privilege, SHA-pinned GitHub Actions only if free hosted CI is confirmed; otherwise retain provider-neutral local gate evidence.
4. **Versioned schemas:** define Draft 2020-12 schemas and conformance fixtures for configurations, artifacts, environments, sources, datasets, model/family/strategy/pattern objects, experiments, backlog items, and release events. Unknown fields and schema upgrades must fail or follow an explicit migration.
5. **Identity and registry core:** implement typed UUIDv7 allocation, exclusive creation, append-only zero-padded revisions, prior-digest compare-and-swap, global duplicate detection, chain verification, and generated non-authoritative indexes. Test concurrent allocation and stale-writer rejection.
6. **Canonicalization and hashing:** implement JCS validation/canonicalization, normalized precision/timestamp conventions, SHA-256 identifiers, standard test vectors, and freeze-manifest construction. Reject duplicate keys, NaN/Infinity, unresolved substitutions, and digest mismatches.
7. **Immutable artifact and point-in-time data contracts:** implement content-addressed objects, atomic publish, sidecars, byte-faithful raw captures, deterministic Parquet-manifest rules, quarantine metadata, and provenance links using synthetic fixtures only. Define the four distinct timestamp types and an as-of eligibility contract; prove future publications/revisions are excluded and prior raw objects cannot be overwritten.
8. **Experiment controls:** implement preregistration lifecycle, multiple-testing counters (including AI variants and failures), freeze transition, immutable freeze digest, release-event reference, result/failure retention, and deterministic `rerun EXP-<uuidv7>` resolution. Do not implement a backtesting engine or strategy.
9. **Validation and simulation interfaces only:** define typed, configuration-driven contracts for chronological splits, purging/embargo, multiple-testing accounting, baselines, metrics, and decision reports. Define backtest inputs/outputs and a pluggable transaction-cost protocol covering bid/ask, spread, commissions, financing/carry, slippage, latency, order/fill behavior, sessions, and gaps. Test interface invariants with synthetic stubs; do not implement strategies, a backtest engine, optimizer, or market simulator.
10. **Sealed OOS boundary:** with approved host changes, create custodian/research identities and allow-only audited ACLs outside repository/cache/index/sync roots. Implement the custodian-only release adapter and hash-chained ledger. With synthetic data, prove research/AI denial before freeze, controlled read-only release after freeze, one-way `EXPOSED` status, and invalidation on boundary failure.
11. **Production separation:** add import/dependency tests proving the research package has no broker, live-order, credential, deployment, or self-promotion capability. Do not create broker adapters or production infrastructure.
12. **Reproducibility audit:** recreate a clean `.venv` from the lock, run all gates, rerun synthetic manifests twice, compare expected digests, inspect secret/license exclusions, and document every failure or environment-specific limitation.
13. **Closeout:** update `README.md`, affected registries/ledgers/risks/decisions, requirement traceability, and the repository tree; report commands and exact results. Do not ingest paid data, build connectors, implement strategies/pattern algorithms/backtesting, or proceed to Stage 2.

**Stage 1B implementation exit gate:** all selected quality commands pass; clean locked setup and synthetic reruns reproduce expected digests; registry concurrency/history tests pass; raw mutation fails safely; the research identity cannot discover/read sealed fixtures; release requires a matching frozen manifest and is auditable/one-way; research code has no production authority; no secret or paid commitment exists; documentation and risk evidence match the implementation. A missing host isolation capability, unknown digest, mutable history, or claimed-but-unrun check fails the gate.

**Stage 1 exit gate:** Quant Hunter is a reproducible quantitative-research laboratory in which it is difficult to accidentally fool ourselves. Evidence must demonstrate immutable/provenanced data, frozen experiments, inaccessible sealed OOS data, realistic future backtest interfaces, multiple-testing accounting, registries, deterministic reruns, tests, and security/deployment separation.

## Stage 2 — Algorithm Discovery, Canonical Implementation, and Pattern Lab

Stage 2 may begin only after the Stage 1 controls and exit gate are satisfied.

### Stage 2A — Algorithm Discovery Program

Systematically search authoritative quantitative-finance literature for established algorithms and research methods. Prioritize sources in this order:

1. peer-reviewed academic research;
2. NBER, SSRN, universities, and similar serious research repositories;
3. BIS, central banks, regulators, and public institutions;
4. major quantitative-finance journals;
5. institutional research where accessible;
6. authoritative quantitative-finance books; and
7. reputable open-source implementations only as secondary implementation references.

Register every candidate before empirical evaluation. `MODEL_REGISTRY.md` owns permanent research/model identity and the canonical record; `EXPERIMENT_LEDGER.md` owns each empirical evaluation. Preserve the candidate's family, source, mathematical formulation, required data, horizon, assumptions, known weaknesses, transaction-cost sensitivity, evidence quality, replication evidence, known failures or decay, FX applicability, and data availability and cost. Keep the catalog open to additional algorithms supported by credible evidence.

### Stage 2B — Canonical Implementation

Implement only registered algorithms. Each implementation must:

- follow the mathematical source as closely as reasonably possible;
- contain tests and declare assumptions;
- use point-in-time data and realistic costs where applicable;
- be reproducible from configuration;
- receive permanent IDs and record meaningful variants; and
- avoid silent parameter optimization.

Apply `RESEARCH_METHODOLOGY.md` and `VALIDATION_STANDARD.md`. Record an honest implementation outcome as `REPRODUCED`, `PARTIALLY REPRODUCED`, or `NOT REPRODUCIBLE WITH AVAILABLE DATA`. Never claim exact reproduction when important source data, universes, forecasts, feeds, or implementation details are unavailable.

### Stage 2C — Canonical Research Set

The required initial program remains the ten canonical areas defined in `RESEARCH_METHODOLOGY.md`:

1. Time-Series Momentum
2. Currency Momentum
3. FX Carry
4. Value + Momentum
5. Cointegration / Error Correction
6. PCA / Statistical Arbitrage
7. Volatility Forecasting / GARCH
8. Volatility Management
9. Macroeconomic Announcement Surprises
10. Market Microstructure / Order Flow

Their detailed study dossiers, limitations, and validation rules remain normative and are not duplicated here. Failed, partial, and non-reproducible studies remain permanent results.

### Stage 2D — Pattern Discovery and Structural Recognition Laboratory

After Stage 1 controls exist, implement and research the classical families governed by `PATTERN_DISCOVERY.md`: Matrix Profile and motif discovery; anomaly/discord detection; Dynamic Time Warping and variants; shapelets; SAX and symbolic sequences; change-point detection; Hidden Markov and switching-state models; Fourier, wavelet, and spectral methods where appropriate; recurrence analysis; trajectory clustering; systematic geometric pattern recognition; multivariate pattern discovery; and nearest-historical-state research.

Pattern candidates are registered research objects, not trade signals. The Pattern Lab exit gate requires evidence that:

- several classical discovery families are operational;
- discovered patterns receive permanent IDs;
- candidate-search volume is recorded;
- false-discovery and multiple-testing controls are applied;
- sealed out-of-sample controls are enforced;
- results are reproducible;
- stability can be evaluated across regimes and instruments; and
- attractive but statistically unsupported patterns can be rejected.

## Stage 3 — Evidence-Governed Model Expansion

### Stage 3A — Algorithm Expansion

Expand toward approximately 200 or more serious models only through evidence-supported, defensible differences in mathematical formulations, horizons, normalizations, representations, risk transformations, regime-conditioned versions, cost-aware versions, cross-asset versions, and multivariate versions. This is a long-term research direction, not a quota. Parameter changes alone are neither independent evidence nor independent votes; they remain variants and count toward multiple-testing exposure.

### Stage 3B — Evidence Families

Govern models by evidence family so a family with many related implementations cannot receive duplicate ensemble votes. Example families include trend/momentum, carry, value, volatility, macro, statistical arbitrage, market microstructure, pattern discovery, cross-asset, regime, and machine learning. `MODEL_REGISTRY.md` owns the canonical taxonomy, lineage, and independence rules.

### Stage 3C — Automated Research Pipeline

The future pipeline is:

```text
candidate discovery/proposal
-> registration
-> research-source verification
-> data-requirement assessment
-> implementation
-> tests
-> experiment execution
-> transaction-cost evaluation
-> chronological validation
-> multiple-testing adjustment
-> regime/stability analysis
-> reproducible report
-> scientific decision
```

Model candidates use the lifecycle statuses in `MODEL_REGISTRY.md`; empirical runs use the lifecycle and decision outcomes in `EXPERIMENT_LEDGER.md`. Do not create an incompatible pipeline-only status vocabulary. Automation may produce evidence and a scientific decision, but it must never promote work automatically to paper trading or production.

### Stage 3D — Research Backlog

Maintain a permanent, provenance-linked backlog of algorithms not yet implemented, papers not yet reproduced, interesting anomalies, missing datasets, promising pattern methods, rejected ideas that may be revisited only under legitimately new evidence, methods requiring expensive data, and methods requiring higher-frequency infrastructure. Retain rejection reasons and prerequisites. Backlog inclusion is not evidence or authorization; it may later become an input to AI research agents.

## Stage 4 — Ensembles, Meta-Models, and AI Research

Study dependence-aware ensembles and meta-models. AI may assist literature review, hypotheses, critique, anomaly detection, and candidate code; all variants count toward multiple testing. Pattern and related-family models do not receive duplicate votes.

An AI research agent that helped create or modify a hypothesis must not access the sealed out-of-sample dataset used to evaluate that hypothesis before the experiment is frozen. Any change informed by sealed results requires a new experiment ID and, where scientifically possible, genuinely untouched evidence; without new untouched evidence, the changed result remains exploratory. AI has no trade-execution authority and cannot promote work to paper trading or production.

## Stage 5 — Paper Trading

Introduce paper-only adapters and credentials behind a separate boundary and authorization. Compare simulated assumptions with observed spreads, slippage, latency, fills, data arrival, and operational failure modes.

## Stage 6 — Shadow Validation

Run forward, non-capital validation without strategy-development access to future observations. Require stability, reproducibility, calibration, and risk review before any further proposal.

## Stage 7 — Controlled Capital

This stage is only eventual. It requires explicit approval, independent risk and security review, production isolation, monitoring, kill controls, and a new decision record. Nothing in the current repository authorizes live trading.

## Required Completion Report for Implementation Milestones

Report the repository tree, architecture summary, files created, commands and tests executed, test results, major design decisions, data sources identified, major risks, unimplemented scope, and recommended next milestone. Report failures and limitations with the same prominence as successes.
