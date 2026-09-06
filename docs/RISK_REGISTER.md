# Risk Register

## Governance

Review this register at each stage gate and whenever evidence, scope, cost, or controls change. Use permanent IDs; retain closed risks. Link mitigations to decisions, experiments, data sources, and tests. `OPEN` means the risk requires active control, not that work is authorized.

Every operational risk record must include ID, cause and consequence, likelihood, impact/severity, owner, controls, early-warning indicators, linked decisions/experiments/sources/tests, target and next-review dates, residual risk, status, and closure evidence. The summary entries below are the planning baseline; their detailed fields must be assigned during Stage 1B and before its exit gate. Scientific governance owns RISK-001–009, RISK-014–016, and RISK-019; data governance co-owns RISK-004–005, RISK-012, RISK-014, and RISK-019; architecture/security owns RISK-010–011, RISK-015, RISK-017–020, RISK-022, and RISK-023; and project budget governance owns RISK-013 and RISK-021. All open risks are next reviewed at Stage 1B closeout.

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
| RISK-011 | Secrets or licensed data enter Git, logs, or fixtures. | Sanitized `.env.example`, secret scanning when implemented, least privilege, redacted logs, and license-aware storage. | OPEN |
| RISK-012 | Data licensing, latency, or indicative pricing makes a study unusable. | Complete source registry fields, prefer primary authoritative sources, record executable-versus-indicative status and limitations. | OPEN |
| RISK-013 | Month-1 spending exceeds USD $400 or creates lock-in. | No purchase without explicit approval; maintain cost estimates; prefer open source and free authoritative data; use expensive AI selectively. | OPEN |
| RISK-014 | Proprietary source data makes a claimed paper reproduction false. | State unavailable inputs and deviations explicitly; label the work an approximation, not a reproduction. | OPEN |
| RISK-015 | Results execute but cannot be independently reconstructed. | Pin code, configuration, environment, seeds, data vintages, and artifacts; require rerun evidence before acceptance. | OPEN |
| RISK-016 | Subjective chart labeling introduces hindsight and confirmation bias. | Require mathematical pattern definitions, registered search spaces, blind/OOS evaluation, and uncertainty estimates. | OPEN |
| RISK-017 | A machine administrator, backup tool, search index, or sync service can bypass or copy the local sealed-data boundary. | Keep the vault outside ordinary roots on encrypted NTFS; use separate identities, allow-only DACLs and SACL audits; protect backups equivalently; test effective denial; invalidate on exposure; migrate to external IAM/WORM if the threat model grows. | OPEN |
| RISK-018 | Concurrent writers collide, overwrite history, or fork a registry revision chain. | UUIDv7 IDs, exclusive-create allocation, append-only revisions, prior-digest compare-and-swap, global duplicate/chain checks, and stale-writer tests. | OPEN |
| RISK-019 | Canonicalization, floating-point representation, Parquet versions, or row order causes misleading digest drift or false equivalence. | JCS conformance vectors; precision-sensitive strings; separate physical-object, provenance/lineage, and logical-content digests; explicit ordering; pinned environment; fail on mismatch rather than normalizing silently. | OPEN |
| RISK-020 | Python/tool upgrades, unavailable wheels, mutable CI actions, or platform differences break reproducibility or security checks. | CPython 3.14 smoke tests, committed lock, pinned uv/action versions and checksums, Windows security acceptance tests, deliberate upgrade decisions, and retained environment manifests. | OPEN |
| RISK-021 | Unknown pre-existing subscription or API usage makes the apparent Month-1 headroom too high. | Keep headroom `UNKNOWN` and block every paid action until actual invoice/service-period and project-usage values are entered under DEC-0010. | OPEN |
| RISK-022 | The checkout owner differs from the current process identity, so ordinary Git commands block the repository as unsafe. | The verified workaround uses an ephemeral protected config trusting only `D:/quant-hunter`; reverify status/diff for each task. A persistent repository-specific ownership/trust correction requires owner approval. Never use wildcard or silent global trust. | OPEN |
| RISK-023 | The public repository could expose future proprietary quantitative research, licensed data, private results, or operational details. | Stage 1 infrastructure and sanitized documentation may remain public; commit no secrets, private or licensed data, paid-source content, or proprietary research results. Require an explicit visibility and disclosure review before Stage 2, and reassess CI cost immediately if visibility changes. Do not change repository visibility implicitly. | OPEN |

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
