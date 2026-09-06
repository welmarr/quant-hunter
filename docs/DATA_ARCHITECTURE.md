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

Point-in-time joins must use an explicit as-of time and may select only records whose publication time is not later than that time. Equality is eligible. Operational simulations must also respect ingestion time. When a timestamp is missing or ambiguous, the record must be flagged and excluded from research that requires that time semantics; agents must not infer a convenient value silently.

Batch 4B.2 implements these semantics for synthetic normalized and curated
tables. Every selection configuration names distinct Arrow columns for all four
concepts, requires an exact timezone-aware UTC `as_of`, and records the same
instant as fixed nine-digit RFC 3339 plus signed epoch nanoseconds. `PUBLIC`
reconstructs publicly knowable information: publication and any applicable
revision must be no later than `as_of`. `OPERATIONAL` applies those rules and
also requires ingestion no later than `as_of`. Event time aligns what the record
describes; it does not determine public availability and may legitimately be
after `as_of` for schedules, forecasts, and future-event metadata.

Initial observations declare revision time `NOT_APPLICABLE`. Revisions declare
it `KNOWN`; both their publication and revision times must be eligible, and the
later of those two instants sets selection priority without replacing either
source field. `REQUIRED_UNKNOWN` is excluded explicitly. Within a caller-declared
generic observation key, the latest eligible vintage wins. Equal winning
priorities from distinct vintages are ambiguous and fail closed. Missing
publication, missing operational ingestion, missing known revision time, future
availability, and contradictory revision evidence produce deterministic reason
codes. No row is silently imputed or selected by input position, file order, or
vintage-name ordering.

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

Under DEC-0007, metadata manifests are schema-validated JCS JSON and use SHA-256 identities. Raw objects are identified by exact received bytes. Batch 4A implements exact-byte object publication, generic artifact sidecars, and separate raw-capture metadata. Batch 4B.1 records three strictly distinct identities for derived Parquet data:

1. `physical_object_digest` is SHA-256 over the exact final Parquet bytes. It identifies one physical encoding and cannot claim equivalence across writer profiles, Arrow versions, or platforms.
2. `provenance_lineage_digest` is SHA-256 over the RFC 8785 JCS bytes of the versioned lineage manifest. That closed manifest includes the physical object and artifact-sidecar digests, complete parent dataset/revision/physical/lineage/logical identities under declared parent ordering, transformation and configuration identity, code revision, environment digest, full logical schema and its digest, row ordering, the complete writer profile and its digest, source/reference provenance, creation time, and quality disposition. It excludes its own digest, avoiding circular hashing.
3. `logical_content_fingerprint` is SHA-256 over a versioned binary framing of the JCS logical-schema document and every normalized logical row. Eight-byte unsigned big-endian lengths frame the schema, rows, and cells; the row count and type tags are explicit. Integers use ASCII decimal, finite float64 values use big-endian IEEE 754 bytes, UTF-8 strings retain exact code points, decimal128 values use declared-scale strings, and UTC timestamps use fixed-unit RFC 3339 strings. Null and Boolean values have dedicated tags. `ORDERED` retains rows; `UNORDERED` sorts framed rows bytewise while retaining duplicate multiplicity. The fingerprint has no Parquet metadata, Python `repr`, locale, native newline, pickle, or built-in `hash()` dependency.

The logical schema orders fields and records normalized type, nullability,
decimal precision/scale, UTC timestamp unit/timezone, and row-order semantics.
Batch 4B.1 supports Boolean, signed and unsigned 8/16/32/64-bit integers,
float64, UTF-8, decimal128 with nonnegative scale no greater than precision, and
UTC timestamps at second, millisecond, microsecond, or nanosecond units. It
rejects inferred-schema mismatch, ambiguous metadata, unsupported/nested types,
invalid nulls, NaN, and Infinity. Logical equivalence never substitutes for
physical identity or lineage.

The `qh-parquet-v1-zstd` profile pins PyArrow 25.0.1, Parquet 2.6, data pages
2.0, 65,536-row groups, Zstandard level 9, disabled dictionary/statistics/byte
stream split/page index/decimal-integer storage/time adjustment, enabled page
checksums and Arrow-schema storage, explicit page/batch/dictionary sizes, no
timestamp coercion or truncation, and no custom metadata, flavor, filesystem,
encryption, sorting, bloom filter, column encoding, or row-per-page override.
Input schema metadata is rejected. Identical input, declared ordering, profile,
and pinned environment must reproduce exact bytes or fail. Different valid
profiles may produce different physical digests while retaining one logical
fingerprint. Cross-version, cross-library, and unverified cross-platform exact
byte equality are not claimed.

Independent-review hardening requires immutable evidence to agree semantically,
not merely verify in isolation. A derived dataset record, its canonical lineage,
and its physical artifact sidecar must agree on every shared identifier,
timestamp, producer, source, parent, reference, configuration, physical-object,
schema, logical-content, ordering, and quality claim. Parent and reference
sequences retain their governed order; deduplication is applied only where the
publication contract already specifies it. Raw-capture metadata and its artifact
sidecar likewise agree on source, dataset, ingestion time, endpoint/request
references, payload identity and size, media type, and sidecar identity. A field
owned by only one representation is bound through that representation's
canonical digest rather than copied into another schema. These checks do not
change any of the three identity definitions.

The PIT configuration canonically binds the input dataset, exact `as_of`, mode,
observation and vintage identities, temporal columns, revision states,
eligibility/selection rules, ambiguity policy, and output ordering. Its digest
is the derived transformation-configuration identity. Canonical audit evidence
binds the exact parent dataset ID, registry revision, physical object, lineage,
logical-content fingerprint, declared input schema digest, and parent row-order
semantics. Selection verifies the supplied input table against that logical
parent identity. The same audit binds the complete selected logical schema and
values through the existing logical-content fingerprint under the declared
output ordering, then accounts for selected and excluded vintage IDs. Both
immutable objects are referenced by the existing lineage manifest. Published selections use the
existing deterministic Parquet, artifact sidecar, canonical lineage, immutable
object store, parent evidence, and physical/lineage/logical identities. A mode
or `as_of` change therefore changes configuration and lineage even when the
selected logical rows, and correctly their logical fingerprint, remain equal.
The contract is a focused deterministic selection boundary, not an ingestion
connector, general query engine, or instrument master.

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
