# Risk Register

## Governance

Review this register at each stage gate and whenever evidence, scope, cost, or controls change. Use permanent IDs; retain closed risks. Link mitigations to decisions, experiments, data sources, and tests. `OPEN` means the risk requires active control, not that work is authorized.

Every operational risk record must include ID, cause and consequence, likelihood, impact/severity, owner, controls, early-warning indicators, linked decisions/experiments/sources/tests, target and next-review dates, residual risk, status, and closure evidence. The summary entries below are the planning baseline; their detailed fields must be assigned during Stage 1B and before its exit gate. Scientific governance owns RISK-001–009, RISK-014–016, and RISK-019; data governance co-owns RISK-004–005, RISK-012, RISK-014, and RISK-019; architecture/security owns RISK-010–011, RISK-015, RISK-017–020, and RISK-022–024; and project budget governance owns RISK-013 and RISK-021. All open risks are next reviewed at Stage 1B closeout.

| ID | Risk | Required controls | Status |
|---|---|---|---|
| RISK-001 | Targeting a requested 75% win rate creates selection bias or fabricated claims. | Treat win rate as descriptive; preregister hypotheses and decision criteria; prioritize expectancy, robustness, calibration, drawdown, costs, sample size, regimes, and OOS evidence. | OPEN |
| RISK-002 | Large model, parameter, pattern, or AI searches create severe multiple-testing exposure. | Record every candidate and variant; use family-aware corrections, Reality Check/SPA/DSR/PBO where appropriate; retain failures. | OPEN |
| RISK-003 | Look-ahead, target leakage, or repeated holdout use invalidates results. | Enforce point-in-time joins, chronological splits, inaccessible sealed OOS data, freeze/release logs, purging and embargo where appropriate. | OPEN |
| RISK-004 | Revised macro data is mistaken for historically available information. | Preserve publication and revision times; use vintage datasets such as ALFRED/FRED or authoritative equivalents; never overwrite vintages. | OPEN |
| RISK-005 | Mutable or weakly traced data prevents reproduction. | Immutable raw storage, checksums, acquisition manifests, transformation lineage, quality reports, and exact dataset-vintage IDs. | OPEN |
| RISK-006 | Idealized prices and fills turn weak signals into attractive backtests. | Model executable bid/ask, spread, commissions, financing/carry, slippage, latency, order types, fills, sessions, gaps, closures, rollover, and cost stress. | OPEN |
| RISK-007 | Regime instability, small samples, or tail events make results unreliable. | Confidence intervals, block/bootstrap and Monte Carlo analysis, regime and instrument decomposition, parameter stability, degradation, and tail-risk reports. | OPEN |
| RISK-008 | Complex models outperform through flexibility rather than information. | Require simpler baselines, ablations, search accounting, stability tests, and cost-adjusted incremental value. | OPEN |
| RISK-009 | Closely related models or patterns receive duplicate ensemble votes. | Track lineage and dependence; cluster correlated evidence; give no extra votes for variants of the same structure. | OPEN |
| RISK-010 | Research code or AI crosses into live execution. | Separate packages, processes, credentials, and approvals; no live trading or live broker credentials in initial stages; no self-promotion. | OPEN |
| RISK-011 | Secrets or licensed data enter Git, logs, fixtures, or dependencies. | Sanitized `.env.example`, secret and dependency scanning before real credentials or connectors, least privilege, redacted logs, and license-aware storage. | OPEN |
| RISK-012 | Data licensing, latency, or indicative pricing makes a study unusable. | Complete source registry fields, prefer primary authoritative sources, record executable-versus-indicative status and limitations. | OPEN |
| RISK-013 | Month-1 spending exceeds USD $400 or creates lock-in. | No purchase without explicit approval; maintain cost estimates; prefer open source and free authoritative data; use expensive AI selectively. | OPEN |
| RISK-014 | Proprietary source data makes a claimed paper reproduction false. | State unavailable inputs and deviations explicitly; label the work an approximation, not a reproduction. | OPEN |
| RISK-015 | Results execute but cannot be independently reconstructed. | Pin code, configuration, environment, seeds, data vintages, and artifacts; require rerun evidence before acceptance. | OPEN |
| RISK-016 | Subjective chart labeling introduces hindsight and confirmation bias. | Require mathematical pattern definitions, registered search spaces, blind/OOS evaluation, and uncertainty estimates. | OPEN |
| RISK-017 | A machine administrator, backup tool, search index, or sync service can bypass or copy the local sealed-data boundary. | Keep the vault outside ordinary roots on encrypted NTFS; use separate identities, allow-only DACLs and SACL audits; protect backups equivalently; test effective denial; invalidate on exposure; migrate to external IAM/WORM if the threat model grows. | OPEN |
| RISK-018 | Concurrent writers, filesystem redirection, or abandoned locks corrupt, fork, or block a registry revision chain. | UUIDv7 IDs, exclusive-create allocation, append-only revisions, prior-digest compare-and-swap, global duplicate/chain checks, stale-writer tests, later registry path/reparse hardening, and tested stale/crash lock recovery before Stage 1B closeout. | OPEN |
| RISK-019 | Canonicalization, floating-point representation, Parquet versions, or row order causes misleading digest drift or false equivalence. | JCS conformance vectors; precision-sensitive strings; separate physical-object, provenance/lineage, and logical-content digests; explicit ordering; pinned environment; fail on mismatch rather than normalizing silently. | OPEN |
| RISK-020 | Python/tool upgrades, unavailable wheels, mutable CI actions, or platform differences break reproducibility or security checks. | CPython 3.14 smoke tests, committed lock, pinned uv/action versions and checksums, Windows security acceptance tests, deliberate upgrade decisions, and retained environment manifests. | OPEN |
| RISK-021 | Unknown pre-existing subscription or API usage makes the apparent Month-1 headroom too high. | Keep headroom `UNKNOWN` and block every paid action until actual invoice/service-period and project-usage values are entered under DEC-0010. | OPEN |
| RISK-022 | The checkout owner differs from the current process identity, so ordinary Git commands block the repository as unsafe. | The verified workaround uses an ephemeral protected config trusting only `D:/quant-hunter`; reverify status/diff for each task. A persistent repository-specific ownership/trust correction requires owner approval. Never use wildcard or silent global trust. | OPEN |
| RISK-023 | The public repository could expose future proprietary quantitative research, licensed data, private results, or operational details. | Stage 1 infrastructure and sanitized documentation may remain public; commit no secrets, private or licensed data, paid-source content, or proprietary research results. Require an explicit visibility and disclosure review before Stage 2, and reassess CI cost immediately if visibility changes. Do not change repository visibility implicitly. | OPEN |
| RISK-024 | Unprotected main-branch changes bypass independent review or required quality gates. | Establish and verify main branch protection as a repository-governance action before Stage 2; retain review and CI evidence for governed changes. | OPEN |

## Escalation

Stop and record a decision when a control cannot be satisfied, a sealed dataset may have been exposed, provenance is incomplete, a result depends on unavailable proprietary data, a credential may have leaked, or a purchase is proposed. Scientific or safety controls may not be waived for schedule pressure.

## Batch 3A Evidence

On 2026-09-05, temporary synthetic tests implemented and exercised the
DEC-0009 controls for RISK-018: exclusive typed-ID allocation, collision retry,
append-only revisions, prior-digest compare-and-swap, global duplicate scans,
chain verification, concurrent allocation, and stale-writer rejection. The risk
remains `OPEN` until the wider Stage 1B reproducibility audit and cross-platform
CI evidence are complete. Under DEC-0013, the current revision digest covers
exact stored bytes only.

## Batch 3B Evidence

On 2026-09-05, RFC 8785 primary, UTF-16 property-order, and Appendix B binary64
vectors passed against the pinned `rfc8785` implementation. Local rejection
tests cover duplicate keys, non-finite and unsupported values, unresolved
environment substitutions, malformed digests, content changes, and schema-invalid
registry writes. Exact-byte and canonical-JSON identities are separate, and
new registry revisions use JCS without rewriting historical bytes. RISK-019
remains `OPEN` because deterministic Parquet, row ordering, logical dataset
fingerprints, cross-platform CI, and the wider Stage 1B audit remain incomplete.

## Batch 4A Evidence

On 2026-09-05, synthetic tests exercised exact-byte object identity, exclusive
atomic publication, concurrent deduplication, corruption refusal, staging
cleanup, unsafe-root/traversal/link rejection, manifest/object binding, separate
raw metadata, provider corrections, and quarantine retention. Credential-shaped
request fields and URI credentials are rejected before capture publication.
These controls reduce RISK-005, RISK-011, RISK-018, and the physical-object part
of RISK-019. They remain `OPEN` pending Batch 4B derived-data controls, hosted
cross-platform CI, later secret scanning, and the full Stage 1B audit. The
portable checks reject intermediate link-like components on publication and
authoritative reads, but their check-to-use window does not claim protection
from a machine administrator. Labelled secret-text rejection supplements field
name and URI checks without attempting entropy-based secret discovery.

## Batch 4B.1 Evidence

On 2026-09-05, synthetic tests separated exact Parquet-byte identity, canonical
lineage identity, and logical table identity. They cover deterministic repeated
writes, different valid physical profiles with equal logical content, schema and
value changes, ordered and unordered row semantics, duplicate multiplicity,
unsupported and non-finite values, explicit decimal/timestamp representation,
complete parent/config/code/environment/quality lineage sensitivity, immutable
publication, and dataset-schema binding. This reduces the derived-identity part
of RISK-019. RISK-019 remains `OPEN` pending hosted Ubuntu comparison, future
environment/version upgrades, and Batch 4B.2 point-in-time and vintage controls.
Independent-review tests additionally rebuild individually schema-valid,
canonically hashed artifact, lineage, dataset, and raw-capture evidence with
contradictory provenance. Cross-binding now rejects mismatched identifiers,
timestamps, producers, sources, parents, references, configuration, physical
identity/size, logical ordering, and quality while retaining published sequence
and deduplication rules. This further reduces RISK-005 and RISK-019 without
changing their `OPEN` status or starting Batch 4B.2.

## Batch 4B.2 Evidence

On 2026-09-06, synthetic hostile tests exercised explicit UTC as-of boundaries,
including equality and one-nanosecond future publication; PUBLIC versus
OPERATIONAL ingestion policy; immutable V1/V2/V3 macro-style vintages; future,
missing, and contradictory publication/ingestion/revision evidence; deterministic
permutation-independent selection; and fail-closed equal-priority ambiguity.
Canonical PIT configuration and audit objects are immutable and referenced by
the existing verified lineage, while the transformation configuration binds all
material selection policy. These controls reduce the item-7 portions of
RISK-003–005 and preserve the three identities under RISK-019. The risks remain
`OPEN` pending real-source assessment, later experiment/sealed controls, hosted
cross-platform independent review, and the full Stage 1B reproducibility audit.

### Batch 4B.2 independent-review fix

The PIT audit now binds the exact parent dataset, registry revision, physical,
lineage, and logical identities together with the declared parent schema and
row-ordering semantics. Selection recomputes the supplied input table's existing
logical fingerprint before applying PIT rules. The audit also binds the complete
selected table through that same governed fingerprint, and publication requires
the exact parent tuple and selected identity. Hostile synthetic evidence with
valid alternate revision, physical, lineage, logical, or selected-content claims
is rejected. This further reduces RISK-003, RISK-005, and RISK-019; item 7 remains
in review-fix status pending independent review.

The final review fix also requires the exact bound input table at publication
and later verification, reruns the unchanged governed PIT transformation, and
compares the complete selected table, exclusions, and selection accounting.
This rejects internally rehashed selected-value forgeries without changing the
temporal eligibility or vintage-selection rules.

The owner also reported a USD 10 non-recurring prepaid Codex-credit purchase on
2026-09-06 and directed that it count against the Month-1 cap. The canonical
budget ledger records it as spent under a permanent COST ID. RISK-013 and
RISK-021 remain `OPEN` because the pre-existing subscription/API baseline and
therefore remaining headroom are still unknown.

The owner reported a separate ChatGPT Pro upgrade on 2026-09-07 for Quant
Hunter ChatGPT/Codex development capacity. Its actual charge, tax,
proration/Plus credit, invoice details, service period, and renewal terms remain
unknown and are recorded under a separate permanent COST ID. RISK-013 and
RISK-021 remain `OPEN`; no charge amount or remaining headroom is inferred.

## Item 7 Closure and Item 8A Evidence

Independent review passed Stage 1B item 7 at commit
`952bd3a4a30518d51b6a9dbe679b00f9c28753fd`. Item 8A adds synthetic hostile
tests for the governed `DRAFT → REGISTERED → FROZEN` lifecycle, exact
registered-revision freeze binding, result-free preregistration, registry CAS,
immutable freeze publication, and non-dereferenced sealed references. These
controls reduce the preregistration and freeze portions of RISK-001, RISK-003,
RISK-004, RISK-006, and RISK-010. Those risks remain `OPEN` pending runtime
attempt accounting, experiment execution/result retention, the sealed OOS
boundary, deterministic rerun resolution, and later Stage 1 gates. Item 8A adds
USD 0 incremental direct cost; RISK-013 and RISK-021 remain `OPEN` because
Month-1 baseline costs and remaining headroom remain unknown.

### Item 8A timestamp-ordering review fix

The Item 8A lifecycle now compares every fractional-second digit accepted by
the common UTC timestamp schema. Synthetic hostile tests cover backward
sub-microsecond and beyond-nanosecond transitions, one-nanosecond progress,
exact equality, and existing second/microsecond inputs. This further reduces
the lifecycle portion of RISK-004 without changing its `OPEN` status or starting
Item 8B.

### Item 8A closure and Item 8B runtime-attempt evidence

Independent review passed Item 8A at commit
`79730f9ed54d6fcf9c8b33ad70af6181941c0b5e`. Item 8B adds synthetic hostile
coverage for the independently verified `FROZEN → RUNNING` edge, exact
caller-supplied start-time ordering, append-only attempt evidence, AI and failed
subset counts, retry exposure, registry CAS conflicts, and the frozen
multiple-testing budget. Every runtime revision is checked against the exact
frozen science and cumulative attempt history, reducing the current Stage 1B
portions of RISK-001, RISK-002, RISK-003, RISK-008, and RISK-011. These risks
remain `OPEN` pending evaluation/result controls, sealed-release integration,
real research use, and the remaining Stage 1 gates. Item 8B adds USD 0 direct
cost. Item 8C and Item 9 remain unstarted.

### Item 8B closure and Item 8C retained evidence

Independent review passed Item 8B at commit
`747ae70b9b6d95179271d5770239347e24d6b2bd`. Item 8C adds synthetic hostile
coverage for `RUNNING → EVALUATED → DECIDED`, full-precision timestamp order,
immutable result-object verification, explicit failed/no-artifact outcomes,
preservation of frozen and attempt evidence, release-reference retention, and
deterministic rerun resolution from verified freeze inputs. These controls
further reduce the current Stage 1B portions of RISK-001–003, RISK-005,
RISK-008, RISK-011, and RISK-015. Independent review passed Item 8C and full
Item 8 at PR head `c80ca6d2dffba316239880cf6b3ce33c20ee6b2c`. The listed risks remain
`OPEN` pending Item 9 validation/simulation interfaces, Item 10 sealed-release
infrastructure, real experiments, reproducibility closeout, and later research
stages. Registry filesystem/reparse hardening and stale/crash lock recovery also
remain Stage 1B audit work under RISK-018. Main branch protection remains a
repository-governance action under RISK-024 before Stage 2; the public/private
and licensing review remains required under RISK-023; and secret/dependency
scanning remains required under RISK-011 before real credentials or connectors.
Item 8C and this reconciliation add USD 0 direct cost. Item 9 remains unstarted.

## Item 9A Temporal-Validation Evidence

Full Item 8 passed independent review and is merged on main at
`265d5f49e06f841a5e23fdf9ea177670bbfbc1e9`. Item 9A adds synthetic hostile
coverage for exact UTC half-open intervals, chronological top-level partitions,
explicit fold ordering, time-aware scheme vocabulary, purge and embargo
evidence, deterministic canonical plan identity, and metadata-only sealed-OOS
references. These controls further reduce the configuration portions of
RISK-001, RISK-003, RISK-004, RISK-006, and RISK-010.

Those risks remain `OPEN`. Purge and embargo evidence applies only to its
declared fold and creates no inferred global exclusion across other folds. The
contracts do not inspect labels or features, resolve actual dataset membership,
derive a sufficient purge/embargo interval, bind an executed experiment to a
plan, run validation, or enforce the Item 10 access boundary. Effective training
exclusions and gap sizing must later follow the registered label horizon,
temporal feature dependencies, and sampling structure. Item 9B, Item 9C, and
Item 10 are not started. Item 9A adds
USD 0 direct cost; RISK-013 and RISK-021 remain `OPEN` because the ChatGPT Pro
charge and total Month-1 headroom remain unknown pending invoice reconciliation.

## Item 9A Closure and Item 9B Scientific-Evidence Contracts

Independent review passed Item 9A at reviewed head
`e19c693557fc4debe7a12746ae682e1113e404b1`, merged on main at
`5636ad431b1c660233189a45ebfd6157308df7fa`; final Ubuntu and Windows CI passed.
Item 9B adds explicit applicability and reason-bearing omission controls for
baselines, metrics, statistical methods, and robustness requirements. It also
records study-specific conventions, exact numeric evidence, frozen
multiple-testing references, unfavorable outcomes, limitations, failures, and
V0–V9 assessments. These contracts further reduce the configuration and
evidence-retention portions of RISK-001–003, RISK-006–008, RISK-010, RISK-011,
and RISK-015.

Those risks remain `OPEN`: Item 9B performs no statistical method, does not
verify semantic correctness of artifact or release references, does not prove
that an experiment executed its plan, and does not change Item 8 authority.
Item 9C and Item 10 are not started. Item 9B adds USD 0 direct cost; RISK-013
and RISK-021 remain `OPEN` because the ChatGPT Pro charge and total Month-1
headroom remain unknown pending invoice reconciliation.
