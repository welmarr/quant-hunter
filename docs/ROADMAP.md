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

**Status: IN PROGRESS — ITEMS 1–9 COMPLETE / INDEPENDENT REVIEW PASSED;
ITEM 10A COMPLETE / MERGED / POST-MERGE CI GREEN; ITEM 10B TOOLING MERGED /
LIVE HOST EVIDENCE BLOCKED (2026-09-11).** Batches 1–2
completed items 1–4 below, Batch 3A completed item 5, Batch 3B completed item 6,
Batch 4A completed the immutable-object and byte-faithful raw-capture foundation,
and Batch 4B.1 completed only deterministic Parquet plus the three-digest derived
identity foundation within item 7. Batch 4B.2 completed the implementation portion
of item 7 with synthetic point-in-time selection and normalized/curated integration.
Item 7 is `COMPLETE / INDEPENDENT REVIEW PASSED` at reviewed commit
`952bd3a4a30518d51b6a9dbe679b00f9c28753fd`. Item 8A is `COMPLETE /
INDEPENDENT REVIEW PASSED` at reviewed commit
`79730f9ed54d6fcf9c8b33ad70af6181941c0b5e`. Item 8B is `COMPLETE /
INDEPENDENT REVIEW PASSED` at reviewed commit
`747ae70b9b6d95179271d5770239347e24d6b2bd`. Item 8C and full Item 8 are
`COMPLETE / INDEPENDENT REVIEW PASSED` and merged on main at
`265d5f49e06f841a5e23fdf9ea177670bbfbc1e9`. Item 9A is `COMPLETE /
INDEPENDENT REVIEW PASSED` at reviewed head
`e19c693557fc4debe7a12746ae682e1113e404b1` and merged on main at
`5636ad431b1c660233189a45ebfd6157308df7fa`. Item 9B is `COMPLETE / INDEPENDENT
REVIEW PASSED` at reviewed head
`d828fb498de44df25d9fba908ac9a32868e6fbff`, squash-merged on main at
`26f1a8a5d62651aad9d545725d3200bad4170500`. Items 9A, 9B, and 9C are complete
and independently reviewed. Full Item 9 and its cross-binding are `COMPLETE /
INDEPENDENT REVIEW PASSED` at reviewed head
`d6ff6b26fced3c7750f8a4c68b520b70c0567c77`, merged on main at
`6c9d5ae1eec58faeca53239d832748053387f1bc`. Post-merge Quality #32 passed on
Ubuntu and Windows; Ubuntu ran 630 tests with 90.99% combined statement/branch
coverage. Item 10A implements the software release core and synthetic security
contracts described below and is complete after independent review, merge, and
green post-merge Quality #36. Item 10B is the current authorized, evidence-gated
item; items 11–13 remain unstarted. Execute future work only
through a separate explicit batch authorization:

1. **Preflight and boundary evidence:** reread governing documents; inventory the host without exposing data; reverify Git through the exact-path ephemeral trust method or an owner-approved persistent repository-specific remedy (never a wildcard); record the repository/CI state and budget facts; verify that a separate encrypted NTFS location, OS identities, ACLs, and auditing are feasible. Obtain explicit host-admin approval before persistent ownership/trust, account, volume, audit-policy, or ACL mutations.
2. **Minimal package scaffold:** create only the `src/quant_hunter` foundation package, `tests`, `schemas`, `registries`, `configs`, and manifest directories; configure CPython 3.14, PEP 621/Hatchling, `.python-version`, pinned uv bootstrap metadata, `.venv` exclusion, and committed `uv.lock`.
3. **Quality gate first:** configure Ruff, strict mypy, pytest, branch coverage, deterministic/offline markers, and the documented `uv run --locked` commands. Add least-privilege, SHA-pinned GitHub Actions only if free hosted CI is confirmed; otherwise retain provider-neutral local gate evidence.
4. **Versioned schemas:** define Draft 2020-12 schemas and conformance fixtures for configurations, artifacts, environments, sources, datasets, model/family/strategy/pattern objects, experiments, backlog items, and release events. Unknown fields and schema upgrades must fail or follow an explicit migration.
5. **Identity and registry core:** implement typed UUIDv7 allocation, exclusive creation, append-only zero-padded revisions, prior-digest compare-and-swap, global duplicate detection, chain verification, and generated non-authoritative indexes. Test concurrent allocation and stale-writer rejection.
6. **Canonicalization and hashing:** implement JCS validation/canonicalization, normalized precision/timestamp conventions, SHA-256 identifiers, standard test vectors, and freeze-manifest construction. Reject duplicate keys, NaN/Infinity, unresolved substitutions, and digest mismatches.
7. **Immutable artifact and point-in-time data contracts — COMPLETE / INDEPENDENT REVIEW PASSED:** Batch 4A implements content-addressed exact-byte objects, atomic publication, generic artifact sidecars, byte-faithful raw captures, quarantine metadata, and provenance links using synthetic fixtures only. Batch 4B.1 implements deterministic Parquet writer/schema rules and distinct physical-object, canonical-lineage, and logical-content identities for synthetic derived tables; its independent-review hardening rejects semantically contradictory artifact, lineage, dataset-record, and raw-capture evidence. Batch 4B.2 implements explicit UTC as-of selection, distinct event/publication/ingestion/revision times, PUBLIC and OPERATIONAL eligibility, immutable vintage selection, fail-closed ambiguity and missing-time evidence, and normalized/curated publication through the existing three-identity system. Its review fixes bind the exact five-field parent identity plus input schema/order, complete selected logical content, and deterministic replay of the PIT transformation from exact input. Independent review passed commit `952bd3a4a30518d51b6a9dbe679b00f9c28753fd`. No real data or connector is included.
8. **Experiment controls — COMPLETE / INDEPENDENT REVIEW PASSED:** Item 8A passed independent review at commit `79730f9ed54d6fcf9c8b33ad70af6181941c0b5e`; it implements governed `DRAFT → REGISTERED → FROZEN`, result-free preregistration, exact registered-revision freeze binding, full-precision UTC timestamps, and immutable freeze evidence. Item 8B passed independent review at commit `747ae70b9b6d95179271d5770239347e24d6b2bd`; it implements independently verified `FROZEN → RUNNING` and append-only, budget-bounded attempt accounting. Item 8C passed independent review at PR head `c80ca6d2dffba316239880cf6b3ce33c20ee6b2c`; it implements `RUNNING → EVALUATED → DECIDED`, permanent positive/negative/null/failed/inconclusive evidence, immutable result-object verification, preservation of sealed-release references, and deterministic non-executing rerun-input resolution from verified REGISTERED/FROZEN authority. Full Item 8 is complete and merged on main at `265d5f49e06f841a5e23fdf9ea177670bbfbc1e9`. Sealed-release infrastructure remains separately gated under Item 10.
9. **Validation and simulation interfaces only — COMPLETE / INDEPENDENT REVIEW PASSED:** Items 9A and 9B remain `COMPLETE / INDEPENDENT REVIEW PASSED` at their recorded reviewed and merged revisions. Item 9C is `COMPLETE / INDEPENDENT REVIEW PASSED` at reviewed head `97141bce973258f4393314f4205702eed2f5a67c`, squash-merged on main at `529f401b5b75e9b213067abb00bbaa1c633b7ac8`. Full Item 9 passed independent review at head `d6ff6b26fced3c7750f8a4c68b520b70c0567c77` and was merged on main at `6c9d5ae1eec58faeca53239d832748053387f1bc`. Its metadata-only cross-binding requires a verified Item 9A plan to exactly match supplied Item 8 FROZEN partitions; Item 9B temporal and multiple-testing bindings to identify the same experiment and frozen revision; and Item 9C to derive its Item 9A/9B digests from verified plan objects. It performs no calculation or execution, does not verify a registry chain or Item 10 release, and leaves Item 8 authoritative for lifecycle, attempts, evaluation, and decisions. Do not implement formulas, strategies, a validation or backtest engine, optimizer, splitter, evaluator, order matcher, fill simulator, transaction-cost calculator, broker adapter, or market simulator.
10. **Sealed OOS boundary — 10A COMPLETE / INDEPENDENT REVIEW PASSED / MERGED / POST-MERGE CI GREEN; 10B TOOLING MERGED / LIVE HOST EVIDENCE BLOCKED:** Item 10A adds only the software release core and synthetic security contracts. It verifies exact current Item 8 FROZEN authority for authorization, binds the complete canonical dataset identity set and exact sealed partition, verifies a synthetic immutable released artifact, and writes RFC 8785/SHA-256 events to an append-only CAS and hash-chained exposure ledger. `SealedReleaseService.authorize_release` remains the sole supported `SYNTHETIC_TEST` release writer and `record_accidental_exposure` remains the sole supported incident writer. Item 10B adds a separate typed Windows host-evidence verifier and `WindowsHostReleaseService`; `HOST_ENFORCED` events require the exact canonical host-evidence digest and still use Item 8 authority plus the same private ledger append primitive and global one-way exposure rules. DEC-0036 requires the typed authority to originate from one governed executed preflight/setup/verification flow; raw mappings, JSON documents, and arbitrary report paths cannot be promoted. The same evidence chain separates and binds preflight host observations to effective identity, ACL, SACL/audit, release, and indexing probes. PR #9 closed the software/security correction at final head `8efa0f5d874c3306ea1cd1c5078ddf35c508c305`, merged on main at `27a81e9374e97566789f1a61000312d64b91a563`; final Quality #41 and post-merge Quality #42 passed 783 tests on Ubuntu and Windows with 90.09% combined Ubuntu statement/branch coverage. Governed ACL authority and verification use actual local-user SIDs, research denial requires exact-SID 4656 Audit Failure, custodian performed access requires exact-SID 4663 Audit Success, and pure ACL classification is provider-independent. A fresh elevated owner-host read-only preflight for `D:\QuantHunterOOS` passed with zero blockers on an already protected fixed NTFS volume, while backup configuration remained unreadable residual risk. That preflight is not `HOST_ENFORCED` authority. Item 10B remains gated to a separately authorized successful owner-controlled governed capture rerun proving dedicated identities, inheritance-disabled allow-list ACLs, filesystem auditing, index/sync/backup evidence, controlled release, and effective two-identity checks. BitLocker must not be changed. Item 10 is not complete until live evidence is captured and independently reviewed.
11. **Production separation:** add import/dependency tests proving the research package has no broker, live-order, credential, deployment, or self-promotion capability. Do not create broker adapters or production infrastructure.
12. **Reproducibility audit:** recreate a clean `.venv` from the lock, run all gates, rerun synthetic manifests twice, compare expected digests, inspect secret/license exclusions, and document every failure or environment-specific limitation. Regardless of whether the RISK-018 incident recurs, run repeated Windows concurrent-allocation stress tests; test stale-lock recovery, crashed-lock-owner recovery, and orphan `.allocation.lock` detection and cleanup; prove cleanup cannot corrupt or fork registry history; and test timeout behavior under controlled contention. Retain exact evidence and a root-cause conclusion. Increasing the timeout alone is not root-cause resolution. If implementation remains unchanged, closure evidence must justify why the observed failure is environmental or flaky rather than a registry correctness defect.
13. **Closeout:** update `README.md`, affected registries/ledgers/risks/decisions, requirement traceability, and the repository tree; report commands and exact results. Do not ingest paid data, build connectors, implement strategies/pattern algorithms/backtesting, or proceed to Stage 2.

**Stage 1B implementation exit gate:** all selected quality commands pass; clean locked setup and synthetic reruns reproduce expected digests; registry concurrency/history tests pass; raw mutation fails safely; the research identity cannot discover/read sealed fixtures; release requires a matching frozen manifest and is auditable/one-way; research code has no production authority; no secret or paid commitment exists; documentation and risk evidence match the implementation. RISK-018 cannot be silently ignored or closed because one rerun passed: before closeout, either reproduce and correct the root cause with hostile regression tests, or retain repeated controlled evidence that the implementation remains correct, credibly classify the incident as non-systemic, and document the residual risk. A missing host isolation capability, unknown digest, mutable history, unresolved RISK-018 closeout path, or claimed-but-unrun check fails the gate.

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
