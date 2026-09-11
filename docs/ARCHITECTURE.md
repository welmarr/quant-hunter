# Architecture

## Status and Design Goals

Stage 1A planning is complete and Stage 1B is in progress. Batches 1–2 provide
the package shell, locked toolchain, engineering quality gate, and versioned
Draft 2020-12 schemas. Batches 3A–3B implement typed identity, append-only
registry revisions, JCS canonicalization, SHA-256 contracts, governed registry
validation, and generic freeze manifests using synthetic tests only. Batch 4A
adds the immutable exact-byte object store, generic
artifact sidecars, and byte-faithful synthetic raw-capture foundation. Batch 4B.1
adds deterministic Parquet publication and separate physical, lineage, and
logical-content identities for explicitly typed synthetic tables. Batch 4B.2
adds explicit point-in-time selection for synthetic normalized/curated data with
PUBLIC and OPERATIONAL availability policies. Independent review passed item 7
at commit `952bd3a4a30518d51b6a9dbe679b00f9c28753fd`. Independent review passed Item
8A at commit `79730f9ed54d6fcf9c8b33ad70af6181941c0b5e` and Item 8B at commit
`747ae70b9b6d95179271d5770239347e24d6b2bd`. Independent review passed Item 8C
and full Item 8, merged on main at
`265d5f49e06f841a5e23fdf9ea177670bbfbc1e9`.
Item 8C extends the same experiment
authority through `RUNNING → EVALUATED → DECIDED`, storing observed result and
failure evidence in immutable registry revisions, verifying supplied result
objects, and resolving deterministic rerun inputs from REGISTERED/FROZEN
evidence. Item 9A adds immutable temporal-validation configuration contracts
for exact UTC intervals, top-level chronological partitions, explicit time-aware
folds, and purge/embargo evidence. They produce canonical metadata only: they do
not split data, execute research, or access sealed contents. Independent review
passed Item 9A at reviewed head
`e19c693557fc4debe7a12746ae682e1113e404b1`, merged on main at
`5636ad431b1c660233189a45ebfd6157308df7fa`. Item 9B adds immutable scientific
evidence plans and report envelopes. These declare applicability, comparisons,
metrics, methods, robustness, and structural references to Item 8 frozen
multiple-testing authority without running scientific calculations or changing
experiment state. Its V0–V9 assessments use the authoritative gate meanings,
including V5 search adjustment. Pending evidence is narrative-only; pending or
failed required evidence cannot support a validated report. Actual experiment
execution remains absent. Item 9C adds canonical, metadata-only execution and
transaction-cost plans plus simulation input/output evidence envelopes. These
interfaces require explicit BUY/SELL price-side rules for executable pricing,
with side rules as the sole execution-price authority. Standard executable
MARKET assumptions require BUY to ASK and SELL to BID and reject LAST_TRADE as a
direct side quote; explicitly described limit/resting alternatives remain valid.
They also require reasoned partial-fill treatment and coherent pending/failed output states.
DEC-0028 cross-binds these existing authorities without adding runtime behavior:
a typed binding exactly matches Item 9A partitions to supplied Item 8 FROZEN
metadata; Item 9B requires that temporal and multiple-testing bindings identify
the same experiment and frozen revision; and Item 9C derives compact plan digests
from verified Item 9A and 9B objects. These interfaces cannot execute a strategy,
match an order, generate a fill, calculate performance or cost, verify a registry
chain, assess V6, or access sealed contents. Item 10A now adds only the
software release core and synthetic security contracts described under
Isolation and Leakage Controls. Item 10B tooling is merged but live host
evidence is blocked. Executable backtesting, strategies, broker/live
execution, and later-stage systems remain absent.
Full Item 9 is `COMPLETE / INDEPENDENT REVIEW PASSED` at reviewed head
`d6ff6b26fced3c7750f8a4c68b520b70c0567c77`, merged on main at
`6c9d5ae1eec58faeca53239d832748053387f1bc`; post-merge Quality #32 passed on
Ubuntu and Windows. Item 10A is `COMPLETE / INDEPENDENT REVIEW PASSED / MERGED /
POST-MERGE CI GREEN`; Item 10B is `TOOLING MERGED / LIVE HOST EVIDENCE BLOCKED`.
The design must be modular, reproducible, testable, and difficult to misuse.

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
│   ├── backtesting/          # Item 9C metadata-only simulation contracts
│   ├── validation/           # Item 9A temporal and Item 9B evidence contracts
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

Item 10A implements the software side of that future release path without
creating the host boundary. The release service accepts no sealed source path.
It starts from Item 8 `verify_frozen`, exactly binds the experiment, one FROZEN
revision and manifest, code/configuration/environment identities, the complete
lexicographically ordered dataset-ID set, and the exact sealed interval. It
verifies only a synthetic released object already published through the
immutable object-store contract. Its append-only exposure ledger uses
zero-padded exclusive event publication, compare-and-swap against the verified
head, an RFC 8785/SHA-256 chain, and a separate canonical head anchor so missing
or truncated tail history fails closed. Exposure is global to every dataset and
exact half-open interval component, regardless of experiment: subset, superset,
and partial same-dataset overlap are already exposed, while exact adjacency is
not. Authorized release requires every component to be pristine. Accidental
incidents remain appendable after exposure so adverse history is never lost.
The later Item 8 `RUNNING` revision retains the release-event digest and permits
only a fixed evaluation with zero new search attempts. Retained release evidence
uses the verified historical Item 8 FROZEN revision after the lifecycle advances.
`SealedReleaseService.authorize_release` is the sole supported public release
writer, and `record_accidental_exposure` is the sole supported public incident
writer. `ExposureLedger` remains public for structural reads and verification,
but its validated append hook is internal. A structurally valid ledger event is
not sufficient scientific release authority: authorized release also requires
the service's exact Item 8 FROZEN and immutable released-artifact verification.

Item 10A continues to produce and accept only `SYNTHETIC_TEST` evidence. Item
10B adds a separate `WindowsHostBoundaryVerifier` and
`WindowsHostReleaseService`. A host event requires a typed evidence object
loaded from an exclusively published, schema-valid RFC 8785 record whose
SHA-256 digest excludes only its own digest field. That record binds sanitized
vault and release-location fingerprints, verified encryption, DACL, SACL/audit,
identity-denial, custodian-release, release-read-only, index, sync, backup, and
explicit limitation evidence. The host service rechecks the effective custodian
identity, the configured release-object root, exact Item 8 FROZEN authority,
immutable artifact, event digest, and global exposure history. Generic
`SealedReleaseService` cannot create or verify host evidence.

The Windows scripts are read-only at preflight and inert unless setup or
rollback receives an explicit `-Apply`. They are designed to create only the
two governed local test identities and a synthetic fixture after every hard
gate passes, apply inheritance-disabled allow-list ACLs and narrow filesystem
auditing, run effective-identity probes with in-memory authentication material,
and disable the test logons afterward when no approved secret manager exists.
The first elevated owner-controlled preflight passed on an already encrypted
fixed NTFS target, but setup failed after account creation and before audit or
effective-identity verification. Rollback removed the batch resources, restored
the original audit policy, and left BitLocker unchanged; no `HOST_ENFORCED`
evidence exists. Governed ACL construction and verification therefore use each
created local user's actual SID and well-known SYSTEM/Administrators SIDs.
Runtime machine qualification is confined to in-memory effective-login
credentials and is not scientific evidence. Host paths reject existing
symlink/reparse components before evidence reads and publication. Filesystem
checks still have an unavoidable check/use window; the design does not claim
resistance to an administrator who can replace paths, data, or trust anchors
during that window. As with other local append-only files, the software ledger
detects later changes at verification time.

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
