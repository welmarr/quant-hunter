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

On 2026-09-07, PR #5 (`Stage 1B Item 9 — cross-bind validation
authorities`) at head `d6ff6b26fced3c7750f8a4c68b520b70c0567c77` recorded an
intermittent Windows registry-lock contention incident in Quality run #30,
GitHub Actions run `34143341935`. Attempt 1 passed the Ubuntu quality gate but
failed Windows compatibility in
`tests/test_registry.py::test_concurrent_allocation_is_unique_and_complete`:
one of 12 concurrent allocation workers raised `RegistryLockTimeoutError` while
contending for `.allocation.lock` under the configured five-second registry lock
timeout. The Windows rerun passed all 630 tests and the overall workflow
concluded successfully. That rerun is not closure evidence: the root cause has
not been reproduced or proven resolved, and no registry or lock implementation
change was made. Classify the observation as intermittent contention with an
unresolved root cause and keep RISK-018 `OPEN`. Stage 1B reproducibility and
closeout work must investigate and test this incident even if it never recurs.

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
Item 8C and that reconciliation added USD 0 direct cost. At that review
point, Item 9 remained unstarted.

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
temporal feature dependencies, and sampling structure. At the Item 9A review
point, Items 9B, 9C, and 10 had not started. Item 9A added
USD 0 direct cost; RISK-013 and RISK-021 remain `OPEN` because the ChatGPT Pro
charge and total Month-1 headroom remain unknown pending invoice reconciliation.

## Item 9A/9B Closure and Item 9C Simulation Interfaces

Independent review passed Item 9A at reviewed head
`e19c693557fc4debe7a12746ae682e1113e404b1`, merged on main at
`5636ad431b1c660233189a45ebfd6157308df7fa`; final Ubuntu and Windows CI passed.
Independent review passed Item 9B at reviewed head
`d828fb498de44df25d9fba908ac9a32868e6fbff`, merged on main at
`26f1a8a5d62651aad9d545725d3200bad4170500`; final review and post-merge Ubuntu
and Windows CI passed. Item 9B adds explicit applicability and reason-bearing
omission controls for baselines, metrics, statistical methods, and robustness
requirements. It also
records study-specific conventions, exact numeric evidence, frozen
multiple-testing references, unfavorable outcomes, limitations, failures, and
the authoritative V0–V9 assessments, including V5 search adjustment. The review
fix makes pending observations narrative-only and prevents pending or failed
required evidence from contradicting a validated report, while retaining
negative, null, inconclusive, and failed scientific records. These contracts
further reduce the configuration and evidence-retention portions of RISK-001–003,
RISK-006–008, RISK-010, RISK-011, and RISK-015.

Item 9C adds fail-closed metadata for order-type-cross-validated side-aware
price quality, unambiguous side-rule execution-price authority, exact latency,
reasoned partial-fill assumptions, data capability, costs, sessions/gaps, and
state-consistent future evidence outputs. Standard executable `MARKET` claims
require BUY to ASK and SELL to BID and cannot use `LAST_TRADE` as a direct side
quote; alternate order policies retain explicit rationale requirements.
This reduces silent optimistic-assumption exposure in RISK-001, RISK-002,
RISK-006, RISK-007, RISK-010, and RISK-011 without estimating or validating any
result.

Those risks remain `OPEN`: Item 9B performs no statistical method; Item 9C runs
no simulator and calculates no execution result; and neither contract verifies
external evidence semantics, proves that an experiment executed its plan, or
changes Item 8 authority.
DEC-0028 reduces cross-object identity inconsistency by exactly matching Item 9A
partitions to supplied FROZEN metadata, requiring Item 9B temporal and
multiple-testing bindings to share one experiment and revision, and deriving Item
9C plan digests from verified objects. It does not verify the registry chain,
consume a plan, access sealed contents, or close the underlying risks.
Item 9C is `COMPLETE / INDEPENDENT REVIEW PASSED`. Full Item 9 is `IN PROGRESS /
FULL REVIEW FIX` pending independent re-audit; Item 10 is `NOT STARTED`. Item 9C adds USD 0 direct cost; RISK-013
and RISK-021 remain `OPEN` because the ChatGPT Pro charge and total Month-1
headroom remain unknown pending invoice reconciliation.

## Full Item 9 Closure and Continuity Evidence

The preceding paragraph records the pre-review state. Independent review passed
full Item 9 at reviewed head
`d6ff6b26fced3c7750f8a4c68b520b70c0567c77`, merged on main at
`6c9d5ae1eec58faeca53239d832748053387f1bc`. Post-merge Quality #32 passed on
Ubuntu and Windows; Ubuntu ran 630 tests with 90.99% combined statement/branch
coverage. Full Item 9 is `COMPLETE / INDEPENDENT REVIEW PASSED`; Item 10 remains
`NOT STARTED`.

DEC-0029 makes current project status and prior reviewed invariants durable in
the repository. It changes no risk status. In particular, RISK-018 remains
`OPEN`: the successful PR #5 rerun and later Quality #32 success do not resolve
the intermittent Windows registry-lock incident. Item 12 must investigate it
even if it never occurs again. This documentation/governance change adds USD 0
incremental direct cost and does not start Item 10.

## Item 10A Sealed-OOS Software Evidence

On 2026-09-11, Item 10A implemented the software release core and synthetic
security contracts under DEC-0031. Exact Item 8 FROZEN authority, the complete
canonical dataset-ID set, the exact sealed interval, and immutable released
artifact evidence are bound into RFC 8785/SHA-256 events. The append-only ledger
uses compare-and-swap, exclusive publication, a prior-digest chain, and a
canonical head anchor; hostile tests cover concurrent append, stale heads,
overwrite attempts, corruption, missing/reordered history, and tail truncation.
Authorized and accidental exposure remain irreversibly `EXPOSED`, and released
experiments reject every later Item 8 search attempt while preserving a fixed
zero-new-search evaluation path.

All Item 10A evidence uses synthetic records and immutable synthetic objects.
The research-side API accepts no sealed source path, and hostile tests poison
filesystem read, open, stat, existence, directory-listing, traversal, and hash
operations to detect any prohibited sealed-source dereference. The software
creates and accepts only `SYNTHETIC_TEST`; it cannot claim `HOST_ENFORCED`.

This evidence reduces the software-contract portions of RISK-017 but does not
close it. Item 10B still requires separately authorized Windows identities,
encrypted storage, effective DACL/SACL denial, audit, backup, sync, indexing,
and controlled-release evidence. RISK-018 remains `OPEN`; Item 10A does not
modify `identity/registry.py` or resolve the observed Windows allocation-lock
incident. RISK-023 and RISK-024 also remain `OPEN`. Independent review and
hosted CI are pending. No real sealed data, host mutation, dependency, service,
or infrastructure was used.

### Item 10A pre-independent-review hardening

Builder self-review before independent review found that the first Item 10A ledger scoped exposure to an
experiment and could not reverify retained evidence after lifecycle progression.
DEC-0032 corrects both findings. Exposure now belongs globally to each dataset
and exact half-open interval. Same-dataset exact, subset, superset, partial, and
one-nanosecond overlap across experiments block release; exact adjacency and
different datasets remain independent. Multi-dataset events expose every
component. Later and repeated incidents remain appendable after `EXPOSED`, and
full chain verification rejects an illegally inserted overlapping release.

Prospective authorization still requires a current Item 8 FROZEN head. A
separate historical path verifies the complete append-only lifecycle, exactly
one FROZEN revision and immutable manifest, every exact release binding, and the
retained event digest while RUNNING, EVALUATED, or DECIDED. This correction adds
no host evidence and does not close RISK-017. RISK-018, RISK-023, and RISK-024
also remain `OPEN`; `identity/registry.py` is unchanged.

### Item 10A independent-review writer-authority finding

Nova's independent review of head
`859233574d4d8ea9595e7985f3da82aba252c99a` returned `FAIL`: public
`ExposureLedger.append_event` could accept a raw schema-valid exposure mapping
without exact Item 8 FROZEN verification and, for authorized release, immutable
released-artifact verification. This was a competing supported release and
incident writer even though the high-level service path was correct.

DEC-0033 removes the public raw writer. `SealedReleaseService.authorize_release`
is now the sole supported public release writer, and
`record_accidental_exposure` is the sole supported public incident writer. The
ledger remains the structural append-only persistence and verification layer;
its structural validity alone is not scientific release authorization. Hostile
API-surface, raw mapping, nonexistent-experiment, supported-service, chain, CAS,
overlap, history, and search-termination tests retain this boundary. Python
privacy addresses accidental workflow misuse only and adds no administrator-
resistant host claim.

Item 10A remains `IMPLEMENTED / INDEPENDENT REVIEW PENDING` until the corrective
head is independently re-audited. Item 10B remains `NOT STARTED`. RISK-017,
RISK-018, RISK-023, and RISK-024 remain `OPEN`; no risk is closed by this
software-only correction.

### Item 10A closure and deferred-work tracking

Independent review passed corrected Item 10A head
`0892bfdb9231053e8896867facb8fc3de47ebf8e`, PR #7 merged it on main at
`20851f262041cda1fe26844032f298b2a1531ffd`, and post-merge Quality #36 passed
on Ubuntu and Windows with 694 tests on each. The Ubuntu combined
statement/branch coverage was 90.11%. This closes Item 10A's software-only
review gate but does not close RISK-017 or establish real host isolation.

DEC-0034 makes GitHub Issues the operational tracker for material deferred
work while this register remains the durable risk authority. GitHub CLI was
unavailable during the Item 10B batch, so no Issue number or URL exists yet.
Ready-to-post drafts preserve the exact RISK-018 incident and future work for
RISK-023 and RISK-024; remote creation still requires duplicate review. All
three risks remain `OPEN`.
