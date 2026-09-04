# Roadmap

## Stage Gates

Progression is evidence-gated, not calendar-gated. No later stage is authorized by completing an earlier document. Strategy implementation, paper trading, shadow validation, and controlled capital each require separate scope and approval.

## Stage 0 — Documentation Architecture

**Status: COMPLETE (2026-09-04).** The original architecture and independent-review corrections passed documentation-only verification. This status does not authorize Stage 1.

Deliver and cross-link the persistent operating rules, charter, architecture, research methodology, validation standard, data specifications, registries, pattern-lab requirements, decisions, risks, roadmap, and traceability map. Audit the hierarchy against the former master specification.

**Exit gate:** all requirements have a governing home, all required documents exist, links and required rule phrases pass review, and no strategy or Stage 1 code has been introduced.

## Stage 1 — Reproducible Research Foundation

Do not implement the proposed 200 strategies. After explicit authorization, perform the following ordered work:

1. Reinspect the repository and governing documents.
2. Refine `AGENTS.md` only if an invariant or navigation rule changed.
3. Review and approve the full Stage 1 architecture; resolve open decisions.
4. Maintain the project documentation structure and traceability.
5. Select the supported Python version and package manager, then create the minimal project scaffold.
6. Create machine-readable experiment, model, pattern, and data-registry schemas with permanent IDs.
7. Research and populate legitimate data sources; do not purchase anything without explicit approval.
8. Create validation interfaces, sealed-holdout controls, test scaffolding, and reproducibility checks.
9. Prioritize implementation work and update this roadmap.
10. Record every unresolved assumption in `DECISIONS.md` rather than silently guessing.

After planning, implement only the foundational infrastructure necessary for Stage 1. Use tests, and run every documented test and linter. Do not claim success simply because code executes.

**Exit gate:** Quant Hunter is a reproducible quantitative-research laboratory in which it is difficult to accidentally fool ourselves. Evidence must demonstrate immutable/provenanced data, frozen experiments, inaccessible sealed OOS data, realistic backtest interfaces, multiple-testing accounting, registries, deterministic reruns, tests, and security/deployment separation.

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
