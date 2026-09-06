# Architecture

## Status and Design Goals

Stage 1A planning is complete and Stage 1B is in progress. Batches 1–2 provide
the package shell, locked toolchain, engineering quality gate, and versioned
Draft 2020-12 schemas. Batches 3A–3B implement typed identity, append-only
registry revisions, JCS canonicalization, SHA-256 contracts, governed registry
validation, and generic freeze manifests using synthetic tests only. Data,
experiment-lifecycle, sealed-release, simulation, and trading behavior remain
unimplemented. Batch 4A adds only the immutable exact-byte object store, generic
artifact sidecars, and byte-faithful synthetic raw-capture foundation. Batch 4B.1
adds deterministic Parquet publication and separate physical, lineage, and
logical-content identities for explicitly typed synthetic tables. Batch 4B.2
adds explicit point-in-time selection for synthetic normalized/curated data with
PUBLIC and OPERATIONAL availability policies. Roadmap item 7 is ready for
independent review. The design must be modular,
reproducible, testable, and difficult to misuse.

The foundational choices are recorded in DEC-0004–DEC-0010. Stage 1B must implement those decisions and document exact setup, build, test, lint, and run commands in `README.md`. Dockerize only a component for which measured isolation or reproducibility benefit exceeds the added environment; do not introduce distributed infrastructure during Stage 1.

## Current and Planned Repository Layout

```text
quant-hunter/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .python-version
├── docs/
├── schemas/                  # versioned JSON Schemas
├── registries/               # append-only JCS records and generated indexes
├── artifacts/
│   └── manifests/            # small, reviewable artifact manifests; objects stay outside Git
├── src/quant_hunter/
│   ├── __init__.py           # Batch 1 package/version surface
│   ├── config/               # strict JSON/JCS and governed schema validation
│   ├── identity/             # UUIDv7 allocation and registry revisions
│   ├── provenance/           # SHA-256 and generic freeze-manifest foundation
│   ├── storage/              # exact-byte objects, sidecars, and raw capture
│   ├── isolation/            # sealed-release contract; no embedded credentials
│   ├── data/                 # derived identities, Parquet, and PIT selection
│   ├── features/
│   ├── experiments/
│   ├── models/
│   ├── patterns/
│   ├── backtesting/
│   ├── validation/
│   ├── portfolio/
│   ├── execution_costs/
│   ├── reporting/
│   ├── meta/              # future, not Stage 1
│   └── interfaces/
├── tests/
├── configs/
└── .env.example
```

Only files and directory markers created by an authorized batch are present. The
listed domain packages remain design targets and do not authorize later-batch
implementation.

## Stage 1 Technology Profile

- Runtime: 64-bit standard CPython `>=3.14,<3.15`, pinned to 3.14.7 for the current toolchain; every run records its exact patch/build and platform.
- Project/environment: PEP 621 `pyproject.toml`, Hatchling, uv, committed `uv.lock`, ignored `.venv`, and version/checksum-pinned uv bootstrap.
- Evidence metadata: JSON Schema Draft 2020-12, RFC 8785 JCS, UTF-8, and `sha256:<hex>` digests. Precision-sensitive values are normalized strings.
- Tabular data: deterministic Parquet plus a canonical lineage manifest; explicit UTC as-of selection binds time semantics and immutable vintage policy; raw inputs retain exact provider bytes and byte hashes.
- Persistent IDs: typed UUIDv7 identifiers and append-only per-object JSON revisions under `registries/`.
- Quality gate: Ruff, strict mypy, pytest, branch-aware coverage, and provider-neutral `uv run --locked` commands; hosted CI is conditional on free entitlement.

`DECISIONS.md` is authoritative for alternatives, edge cases, cost consequences, and change control.

## Required Component Boundaries

Stage 1 architecture must support:

- ingestion connectors and point-in-time acquisition metadata;
- immutable raw storage and versioned normalized datasets;
- data-quality checks and quarantining;
- deterministic feature engineering;
- experiment definitions and an append-only experiment ledger;
- permanent strategy/model and pattern interfaces and registries;
- a first-class pattern-discovery research boundary;
- configuration-driven backtesting;
- statistical validation and multiple-testing accounting;
- portfolio and risk analysis;
- transaction-cost and execution modeling;
- reproducible environments, manifests, seeds, and artifacts;
- reports linked to experiment IDs;
- future paper-trading adapters behind explicit gates;
- future AI research-agent interfaces without execution authority; and
- a future dependence-aware Meta Engine interface, without Stage 1 implementation.

The intended flow is `source → immutable raw → validated/normalized → point-in-time features → registered experiment → backtest → statistical validation → report`. Every derived artifact must point backward to source versions, transformations, code revision, and configuration.

### Future Meta Engine

The Quant Hunter Meta Engine is a later-stage, dependence-aware evidence aggregation layer for validated trend, momentum, carry, value, macro, volatility, statistical-arbitrage, microstructure, cross-asset, regime, machine-learning, and pattern families. It is not a strategy quota or a majority-vote shortcut: lineage and correlation must prevent related variants from receiving duplicate influence. Defining this boundary does not authorize its implementation during Stage 1.

## Isolation and Leakage Controls

Research workflows may read development data only. Under DEC-0006, sealed partitions live outside the repository and normal artifact/cache roots on an encrypted NTFS volume. An allow-only DACL grants a dedicated custodian identity access and grants the separate research/AI identity none; SACLs audit access and permission changes. The custodian-only release path verifies the frozen experiment and all bound digests, creates an experiment-specific read-only release, and appends a hash-chained event. Release is one-way and recorded, not a developer convenience. Synthetic data must prove both denial and authorized release before the Stage 1 gate. Point-in-time joins must enforce event, publication, ingestion, and revision semantics described in `DATA_ARCHITECTURE.md`.

Research components must not import, invoke, or possess deployment capability. Paper-trading and future production execution are separate adapters, credentials, processes, and authorization boundaries. No live trading or broker credentials are allowed in initial research stages, and no research result may self-promote across a gate.

## Security and Configuration

Configuration must be explicit, validated, and reproducible. When environment configuration is introduced, create a sanitized `.env.example`; keep API, brokerage, and paid-data credentials out of files, logs, fixtures, and Git history. Paper-trading credentials are deferred to a later authorized milestone. Private or license-restricted data must never be committed.

Immutable artifact objects are content-addressed outside Git at `<artifact-root>/objects/sha256/<first-two>/<digest>` (with the root supplied by validated configuration). Small manifests and schemas may be committed. Configuration cannot point a research process at the sealed vault, and environment variables cannot alter a frozen manifest after hashing. Research code may consume an authorized release but may not hold custodian credentials or alter release records.

## Contracts with Governance Documents

- Data layers and provenance: `DATA_ARCHITECTURE.md`
- Source approval and licensing: `DATA_SOURCE_REGISTRY.md`
- Model identity: `MODEL_REGISTRY.md`
- Experiment lifecycle: `EXPERIMENT_LEDGER.md`
- Statistical and backtest behavior: `VALIDATION_STANDARD.md`
- Pattern-lab boundaries: `PATTERN_DISCOVERY.md`
- Stage gates and completion evidence: `ROADMAP.md`

Any architectural choice that changes leakage risk, statistical validity, reproducibility, deployment isolation, or cost must be recorded in `DECISIONS.md` before or with the change.
