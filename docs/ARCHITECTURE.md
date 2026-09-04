# Architecture

## Status and Design Goals

This is the planned architecture for Stage 1; no application scaffold exists yet. The design must be modular, reproducible, testable, and difficult to misuse. Prefer explicit local components and clean interfaces over premature services, distributed systems, or operational complexity.

Before scaffolding, record the supported Python version and package-management decision in `DECISIONS.md`, then document exact setup, build, test, lint, and run commands in `README.md`. Use modern Python engineering practices. Dockerize only components for which isolation or reproducibility provides a concrete benefit; do not introduce unnecessary distributed infrastructure during Stage 1.

## Planned Repository Layout

```text
quant-hunter/
├── AGENTS.md
├── README.md
├── docs/
├── src/quant_hunter/
│   ├── data/
│   ├── features/
│   ├── experiments/
│   ├── models/
│   ├── backtesting/
│   ├── validation/
│   ├── portfolio/
│   ├── execution_costs/
│   ├── reporting/
│   └── interfaces/
├── tests/
├── configs/
└── .env.example
```

This tree is a design target, not permission to implement it during the documentation phase.

## Required Component Boundaries

Stage 1 architecture must support:

- ingestion connectors and point-in-time acquisition metadata;
- immutable raw storage and versioned normalized datasets;
- data-quality checks and quarantining;
- deterministic feature engineering;
- experiment definitions and an append-only experiment ledger;
- permanent strategy/model and pattern interfaces and registries;
- configuration-driven backtesting;
- statistical validation and multiple-testing accounting;
- portfolio and risk analysis;
- transaction-cost and execution modeling;
- reproducible environments, manifests, seeds, and artifacts;
- reports linked to experiment IDs;
- future paper-trading adapters behind explicit gates; and
- future AI research-agent interfaces without execution authority.

The intended flow is `source → immutable raw → validated/normalized → point-in-time features → registered experiment → backtest → statistical validation → report`. Every derived artifact must point backward to source versions, transformations, code revision, and configuration.

## Isolation and Leakage Controls

Research workflows may read development data only. Sealed out-of-sample partitions require separate paths and access controls and remain inaccessible until an experiment definition is frozen. Release is a recorded event, not a developer convenience. Point-in-time joins must enforce event, publication, ingestion, and revision semantics described in `DATA_ARCHITECTURE.md`.

Research components must not import, invoke, or possess deployment capability. Paper-trading and future production execution are separate adapters, credentials, processes, and authorization boundaries. No live trading or broker credentials are allowed in initial research stages, and no research result may self-promote across a gate.

## Security and Configuration

Configuration must be explicit, validated, and reproducible. When environment configuration is introduced, create a sanitized `.env.example`; keep API, brokerage, and paid-data credentials out of files, logs, fixtures, and Git history. Paper-trading credentials are deferred to a later authorized milestone. Private or license-restricted data must never be committed.

## Contracts with Governance Documents

- Data layers and provenance: `DATA_ARCHITECTURE.md`
- Source approval and licensing: `DATA_SOURCE_REGISTRY.md`
- Model identity: `MODEL_REGISTRY.md`
- Experiment lifecycle: `EXPERIMENT_LEDGER.md`
- Statistical and backtest behavior: `VALIDATION_STANDARD.md`
- Pattern-lab boundaries: `PATTERN_DISCOVERY.md`
- Stage gates and completion evidence: `ROADMAP.md`

Any architectural choice that changes leakage risk, statistical validity, reproducibility, deployment isolation, or cost must be recorded in `DECISIONS.md` before or with the change.
