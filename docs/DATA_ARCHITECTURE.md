# Data Architecture

## Purpose and scope

Quant Hunter treats data as a first-class research component. This document defines the data controls needed to make later research point-in-time correct, traceable, reproducible, and resistant to accidental look-ahead. It is an architecture specification, not authorization to ingest paid data, connect a broker, or implement a trading strategy.

## Non-negotiable rules

1. Raw source data is immutable. Preserve the exact received payload and its metadata; corrections and provider revisions are new records, never overwrites.
2. Every dataset and derived artifact must carry sufficient provenance to reconstruct its origin and transformations.
3. Event time, publication time, ingestion time, and revision time are distinct fields with distinct meanings. They must never be collapsed into one generic timestamp.
4. A research observation may contain only information publicly available by the simulated decision time. Revised macroeconomic values must never be used as though they were historically known.
5. Dataset construction must be deterministic from versioned code, configuration, source snapshots, and schemas.
6. Quality failures must be recorded and quarantined, not silently repaired or dropped.
7. Sealed out-of-sample data must be physically or logically inaccessible to strategy-development workflows until the applicable experiment is frozen under the validation standard.

## Logical data layers

| Layer | Purpose | Mutation policy |
|---|---|---|
| Source registry | Records provenance, access, licensing, price quality, and operational constraints before use | Versioned history; changes are auditable |
| Raw landing | Byte-faithful provider payloads plus request/response metadata and checksums | Append-only and immutable |
| Normalized | Typed, unit- and timezone-consistent records retaining all source timestamps and vintages | Rebuilt as new versions; never overwrites raw data |
| Curated | Point-in-time-correct joins, instrument mappings, continuous-series rules, calendars, and quality-approved research tables | Deterministic, versioned outputs |
| Features | Feature values with definitions, horizons, input lineage, and availability timestamps | Deterministic, versioned outputs |
| Experiment snapshots | Exact manifests of data partitions, vintages, schemas, code commits, and configurations used by an experiment | Permanently referenced by experiment ID |
| Sealed holdout | Untouched validation data governed by access controls and release records | Unavailable to development until freeze criteria are met |

Stage 1 should remain local-first and modular. Prefer open formats that preserve types and support efficient scans, with a simple catalog and manifests. Do not introduce distributed infrastructure until measured scale or reliability needs justify it.

## Time semantics and point-in-time truth

All timestamps must be timezone-aware; normalize storage to UTC while retaining source timezone and calendar metadata when relevant.

| Timestamp | Definition | Research use |
|---|---|---|
| `event_time` | When the market observation or underlying economic event/reference period occurred | Aligns observations to what happened |
| `publication_time` | Earliest time the specific value or release became publicly available | Primary eligibility boundary for historical information sets |
| `ingestion_time` | When Quant Hunter actually received and persisted the payload | Reconstructs operational availability, outages, and latency |
| `revision_time` | When a provider published a changed value for an earlier observation | Separates initial releases from later vintages |

Point-in-time joins must use an explicit as-of time and may select only records whose publication time is not later than that time. Operational simulations must also respect ingestion time. When a timestamp is missing or ambiguous, the record must be flagged and excluded from research that requires that time semantics; agents must not infer a convenient value silently.

### Macroeconomic releases and vintages

- Identify observations by series, reference period, release/vintage, and publication time.
- Preserve initial releases, subsequent revisions, benchmark revisions, and source corrections as separate vintages.
- Build historical views from the vintage available at each simulated decision time, not from a latest-value series.
- Timestamp forecasts and consensus snapshots and require them to predate the associated release.
- Compute an announcement surprise from the actual value first available at release and an eligible prior consensus. Standardization parameters may use only earlier releases.
- Record release-calendar changes, delayed publications, and the source's treatment of embargoes and time zones.
- Research real-time/vintage services such as ALFRED/FRED and equivalent authoritative sources. Confirm vintage semantics before use; availability from a familiar API does not itself prove point-in-time correctness.

## Required data domains

### Market data

Design for:

- bid, ask, midpoint, and spread;
- OHLC bars and tick data;
- volume where it is meaningful, with the volume definition and venue recorded;
- session and trading-calendar metadata;
- futures data where useful, including contract identity and explicit roll/continuous-series methodology; and
- order-book and order-flow data in a later stage.

Derived midpoint and spread values must retain their bid/ask inputs and formula. Every feed must state whether quotes are executable bid/ask observations or indicative prices. Do not use idealized midpoint data as a substitute for executable pricing without labeling the limitation.

### Macroeconomic data

Design for:

- central-bank policy rates and decisions;
- government yields and yield curves;
- inflation, employment, GDP, PMIs, retail sales, and industrial production;
- economic calendars;
- forecast/consensus and actual values;
- revisions and complete vintage history where available; and
- standardized surprises constructed point-in-time.

### Positioning and risk data

Design for CFTC data, volatility indexes, risk-on/risk-off proxies, and other positioning proxies. Record publication delays, reporting periods, transformations, and whether a proxy is directly observed or inferred.

### Cross-asset data

Design for equities, bonds, commodities, currencies, volatility, and relevant futures. Instrument mappings, trading calendars, currency conversions, corporate actions, contract rolls, and asynchronous market hours must be explicit.

### Alternative data

Alternative data is deferred until evidence justifies its incremental value, provenance and legality are understood, and its cost fits the approved budget. Novelty alone is not justification.

## Provenance and versioning

At minimum, each raw capture or dataset version must record:

- permanent `DATASET-<uuidv7>` identifier, permanent source identifier, and provider;
- source endpoint, request parameters, and documentation reference where applicable;
- instruments/series, coverage, granularity, and source-native identifiers;
- event, publication, ingestion, and revision timestamps when applicable;
- payload checksum, byte size, format, compression, and storage location;
- provider vintage or release identifier;
- schema and units;
- license/access classification and applicable redistribution restrictions;
- retrieval status, warnings, and quality disposition; and
- creation timestamp.

Each normalized, curated, or feature dataset must additionally record parent dataset versions and checksums, transformation/configuration version, source-code commit, schema version, dependency environment, and deterministic build identifier. Manual corrections require an explicit correction record with reason and lineage; they must not alter the raw capture.

Every experiment must reference an immutable dataset manifest containing the exact dataset versions and vintages used. Re-running that manifest from the same inputs must reproduce the same records, or fail loudly with an auditable explanation.

Under DEC-0007, metadata manifests are schema-validated JCS JSON and use SHA-256 identities. Raw objects are identified by exact received bytes. A later data-foundation batch must record three distinct digests for derived Parquet data: (1) a physical-object digest over the exact file bytes, (2) a provenance/lineage digest over the canonical manifest and ordered parent evidence, and (3) a logical-content fingerprint over the normalized logical schema and canonical row content using the declared order or unordered semantics. The logical fingerprint identifies equivalent rows across different valid Parquet encodings; it never substitutes for byte identity or lineage. Transformation configuration, code revision, environment, and quality disposition remain part of lineage. This three-digest contract is specified here but is not implemented in Batch 1.

## Quality controls

Quality checks must be automated where practical and produce versioned reports. They should include:

- schema, type, unit, precision, and allowed-value validation;
- checksum and completeness verification;
- duplicate, missing, stale, out-of-order, and conflicting-record detection;
- timestamp ordering and timezone/calendar validation;
- bid/ask consistency, nonnegative spread checks, and OHLC invariants;
- gap, outlier, price-jump, and suspicious-zero checks without automatic deletion;
- session-boundary, market-closure, daylight-saving, and weekend handling;
- futures expiry and roll validation where applicable;
- macro release/revision chronology and vintage completeness; and
- cross-source reconciliation where an authoritative comparator exists.

Suspect records enter quarantine with reason codes. Imputation, filtering, winsorization, outlier handling, resampling, roll adjustment, and timezone conversion are transformations with versioned parameters, never invisible cleanup.

## Interfaces and access boundaries

- Ingestion writes only to raw landing and cannot mutate prior captures.
- Transformation jobs read versioned inputs and publish new versioned outputs.
- Research code reads approved curated data and experiment manifests; it must not write into raw storage.
- Development workflows receive only their declared train/validation intervals. Sealed intervals are exposed only through the documented freeze-and-release process.
- Future paper-trading and production adapters must be separate from research storage and permissions. Research code must not be capable of self-promotion or live execution.
- Credentials are supplied outside Git through approved secret management. No API, broker, or paid-data credential may appear in data files, manifests, logs, notebooks, fixtures, or repository history.

### Stage 1 sealed-holdout profile

The sealed vault is a configured path outside the repository, worktrees, ordinary artifact/cache roots, indexing, and consumer-sync locations. It must be on an encrypted NTFS volume. An inheritance-disabled, allow-only DACL grants the dedicated `qh-oos-custodian` identity the minimum required rights; the `qh-research` identity used by development, notebooks, agents, and reports has no read, list, traverse, write, ownership, or ACL-change permission. Equivalent protections apply to backups. SACL auditing records access and permission changes.

Only a custodian-run release command may expose data. Before release it verifies an `EXP-<uuidv7>` record at `FROZEN`, the intended sealed dataset/partition, and the bound code, configuration, environment, and manifest digests. It then exclusive-creates an immutable, read-only experiment release and a JCS/SHA-256 event containing actor, UTC time, reason, previous-event digest, and every relevant identifier/digest. The source partition is permanently labeled `EXPOSED`; it is never re-sealed. Any unauthorized or pre-freeze exposure invalidates affected experiments and must be recorded in the experiment ledger, risk register, and decision log.

Tests use synthetic fixtures and two effective identities. A same-account path convention, configuration toggle, hidden folder, or shared archive password does not satisfy this boundary. Administrators remain outside the Stage 1 accidental/workflow-access threat model, so privileged-account use must be minimized and audited.

## Stage 1 Data-Domain Prerequisites

The data domain is ready for the Stage 1 gate only when the project has documented schemas for the four timestamps, provenance and dataset manifests; an immutable raw-data convention; deterministic normalized/curated build conventions; quality and quarantine rules; vintage-aware macro handling; source-registry linkage; and a sealed-holdout access design. These are necessary, not sufficient, conditions; `ROADMAP.md` owns the complete Stage 1 gate. Stage 1 may use small authoritative free samples, but must not purchase data or start live trading.
