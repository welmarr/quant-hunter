# Quant Hunter Regression Guard

## Purpose

Passing a new feature's own tests is insufficient. Every governed change must
preserve all applicable independently reviewed scientific, security,
reproducibility, and authority invariants already present in the repository.

The permanent review sequence is:

```text
NEW FEATURE / CHANGE TESTS
    -> HOSTILE / FAILURE TESTS
    -> FULL EXISTING REGRESSION SUITE
    -> CROSS-ITEM INVARIANT REVIEW
    -> CI
    -> INDEPENDENT REVIEW
    -> POST-MERGE CI
```

For every material batch, identify the affected invariant IDs, run their
primary tests plus the full existing gate, inspect cross-item authority and
identity boundaries, and retain the exact evidence. An intentional invariant
change requires an accepted decision and explicit independent review.

## Implemented and Reviewed Invariants

| ID | Invariant | Authority / governing decision | Primary implementation | Primary tests | Regression evidence required | Failure consequence |
|---|---|---|---|---|---|---|
| REG-001 | Raw provider bytes are immutable; corrections never overwrite them. | AGENTS rules 8 and 16; DEC-0015; `DATA_ARCHITECTURE.md` | `storage/objects.py`, `storage/raw.py` | `test_object_store.py`, `test_raw_capture.py` | Exact-byte identity, exclusive publication, correction, corruption, and no-overwrite hostile cases plus full gate | Raw evidence and every dependent result are inadmissible. |
| REG-002 | Persistent registry revision history is append-only. | DEC-0009, DEC-0013, DEC-0014 | `identity/registry.py` | `test_registry.py`, `test_governed_registry.py` | Exclusive `v000001`, contiguous revisions, prior-digest chain, overwrite refusal, and retained-history cases | Registry authority is invalid; stop governed writes. |
| REG-003 | Registry CAS, stale-writer, and concurrency controls cannot silently lose or fork history. | DEC-0009; RISK-018 | `identity/registry.py` | `test_registry.py` | Concurrent allocation/append, collision, stale-writer, duplicate-ID, timeout, and chain verification; Item 12 Windows stress evidence | Stop registry use and treat affected chains as suspect. RISK-018 remains open. |
| REG-004 | RFC 8785 and SHA-256 identities remain deterministic, and exact-byte, canonical-JSON, lineage, and logical digest domains are not conflated. | DEC-0007, DEC-0014, DEC-0016 | `config/canonical.py`, `provenance/hashing.py`, `data/derived.py` | `test_canonical.py`, `test_freeze.py`, `test_derived_data.py` | RFC vectors, duplicate/non-I-JSON rejection, stable/change vectors, and explicit cross-domain inequality | Frozen or immutable identity claims are invalid. |
| REG-005 | Derived data retains distinct physical-object, provenance-lineage, and logical-content identities. | DEC-0016, DEC-0017 | `data/derived.py` | `test_derived_data.py` | Three-identity, contradictory-provenance, ordering, duplicate-multiplicity, and transformation-replay cases | Derived data cannot be admitted as reproducible evidence. |
| REG-006 | PIT selection cannot admit information unavailable at the governed as-of time. | DEC-0018–DEC-0020; `DATA_ARCHITECTURE.md` | `data/pit.py` | `test_pit.py` | Equality/future boundaries, PUBLIC/OPERATIONAL eligibility, missing-time, ambiguity, vintage, and replay cases | Temporal evidence fails V2 and affected research is invalid. |
| REG-007 | `event_time`, `publication_time`, `ingestion_time`, and `revision_time` remain semantically distinct. | DEC-0018; `DATA_ARCHITECTURE.md` | `data/pit.py`, `pit-selection-config.schema.json` | `test_pit.py`, `test_schemas.py` | Four-column binding, time-mode, future/missing/revision contradiction, and configuration identity cases | Historical information-set claims are invalid. |
| REG-008 | An experiment's scientific definition cannot mutate after `FROZEN`. | DEC-0021–DEC-0024; `EXPERIMENT_LEDGER.md` | `experiments/lifecycle.py` | `test_experiment_lifecycle.py` | Exact REGISTERED/FROZEN binding, single-FROZEN, immutable freeze object, and later-revision mutation attacks | Experiment and dependent evidence are invalid. |
| REG-009 | Item 8 remains the sole experiment lifecycle and attempt-accounting authority. | DEC-0023–DEC-0028 | `experiments/lifecycle.py`; Item 9 read-only bindings | `test_experiment_lifecycle.py`, `test_scientific_evidence.py`, `test_simulation_contracts.py` | Lifecycle-transition, cumulative-attempt, authority-label, and no-competing-state-machine cases | Reject the competing record or transition. |
| REG-010 | Failed, negative, null, inconclusive, and rejected evidence cannot be deleted because it is unfavorable. | AGENTS rule 4; DEC-0024, DEC-0026 | `experiments/lifecycle.py`, `validation/evidence.py`, append-only registry | `test_experiment_lifecycle.py`, `test_scientific_evidence.py`, `test_registry.py` | Retained unfavorable outcomes, failed/no-artifact evidence, decision preservation, and append-only history | Scientific record is incomplete and decisions are inadmissible. |
| REG-011 | Every actual search exposure, including AI candidates, failures, and retries, remains subject to multiple-testing accounting. | AGENTS rule 5; DEC-0023, DEC-0026 | `experiments/lifecycle.py`, `validation/evidence.py` | `test_experiment_lifecycle.py`, `test_scientific_evidence.py` | Cumulative total/AI/failed counts, retry links, budget exhaustion, and Item 8 authority cases | V5 cannot pass and further attempts must stop. |
| REG-012 | V5 remains `SEARCH ADJUSTMENT`. | `VALIDATION_STANDARD.md`; DEC-0026 | `validation/evidence.py` | `test_scientific_evidence.py` | Exact V0–V9 vocabulary and report assessment cases | Report vocabulary and validation status are invalid. |
| REG-013 | Items 9A, 9B, and 9C cannot combine incompatible experiment, FROZEN-revision, temporal-plan, or evidence-plan identities. | DEC-0028 | `validation/temporal.py`, `validation/evidence.py`, `backtesting/contracts.py` | `test_simulation_contracts.py` | Cross-experiment, cross-revision, partition, unbound/tampered digest, and unrelated-plan hostile cases | Reject the complete Item 9 evidence chain. |
| REG-014 | Temporal validation remains chronological; random K-fold is not the default. | DEC-0025; `VALIDATION_STANDARD.md` | `validation/temporal.py` | `test_temporal_validation.py` | Half-open intervals, top-level chronology, fold sequence, rolling/expanding/purged, and sealed-overlap cases | V4 evidence is invalid. |
| REG-015 | Standard immediately executable `MARKET` semantics remain BUY→ASK and SELL→BID. | DEC-0027 | `backtesting/contracts.py` | `test_simulation_contracts.py` | Both standard side mappings and reversed/wrong-side hostile cases | Execution-realism plan is invalid. |
| REG-016 | `MIDPOINT`, `LAST_TRADE`, and `INDICATIVE` prices cannot masquerade as immediate executable market-side prices. | DEC-0027 | `backtesting/contracts.py` | `test_simulation_contracts.py` | Midpoint, indicative, last-trade, one-sided-global, and alternate-policy cases | V6 cannot pass from the claim. |
| REG-017 | Missing execution-cost treatment never silently means zero. | AGENTS rule 10; DEC-0027 | `backtesting/contracts.py` | `test_simulation_contracts.py` | Complete cost inventory, applicability/reason, sign convention, and missing-component cases | Cost and simulation plans are invalid. |
| REG-018 | Sealed-OOS references remain metadata-only before an authorized Item 10 release. | DEC-0006, DEC-0025–DEC-0028 | `validation/temporal.py`, `validation/evidence.py`, `backtesting/contracts.py` | `test_temporal_validation.py`, `test_scientific_evidence.py`, `test_simulation_contracts.py` | Patched open/read/stat/list/hash denial cases and explicit unverified-authorization fields | Treat any access as exposure and invalidate affected evidence. |
| REG-019 | Research code has no broker, live-trading, self-promotion, or production authority. | AGENTS rules 11–12; RISK-010 | Governance boundary; narrow absence assertion in Item 9 | `test_simulation_contracts.py` | Current absence scan plus full gate; Item 11 must add package/import/dependency separation proof | `PLANNED / NOT YET ENFORCED` as a complete technical boundary; any discovered authority blocks Stage 1B. |
| REG-020 | The Month-1 USD 400 cap and explicit purchase-approval rule cannot be bypassed. | AGENTS rule 20; DEC-0010; `BUDGET_LEDGER.md` | Governance documents and permanent cost identities | Documentation/budget review | Reconcile every proposed or actual cost; unknown headroom blocks paid action | Reject or stop the purchase and record the attempted commitment. |

REG-019 is only partially evidenced today and is deliberately labeled
`PLANNED / NOT YET ENFORCED` until Item 11 establishes the technical
production-import boundary. REG-020 is a reviewed governance invariant rather
than an automated spending system.

## Item 10A Implemented and Reviewed Invariants

These software protections passed independent review at head
`0892bfdb9231053e8896867facb8fc3de47ebf8e`, merged on main at
`20851f262041cda1fe26844032f298b2a1531ffd`, and passed post-merge Quality #36.
They are software authority and synthetic evidence, not real host isolation.

| ID | Status | Invariant | Governing authority | Required future evidence | Failure consequence |
|---|---|---|---|---|---|
| REG-F01 | `COMPLETE / INDEPENDENT REVIEW PASSED — SOFTWARE ONLY` | Exposure belongs globally to each underlying dataset and half-open time interval. Any same-dataset overlap is one-way `EXPOSED` across experiments and can never be resealed; adjacent intervals do not overlap. `SealedReleaseService` is the sole supported public exposure writer; the ledger exposes structural read/verification operations but no public raw append authority. | DEC-0006; DEC-0031–DEC-0033; Roadmap Item 10A | `isolation/ledger.py`, `isolation/release.py`; public-API absence, raw release/incident bypass, nonexistent experiment, supported service writers, cross-experiment reuse, subset/superset/partial overlap, exact fractional adjacency, one-nanosecond overlap, multi-dataset component overlap, release-then-incident retention, repeat-release, chain, CAS, and immutable-state tests in `test_sealed_release.py` | Invalidate affected experiments and stop release. |
| REG-F02 | `COMPLETE / INDEPENDENT REVIEW PASSED — SOFTWARE ONLY` | Viewing sealed results terminates search/tuning for that experiment; changes require a new experiment and genuinely untouched evidence where possible. | `EXPERIMENT_LEDGER.md`; `VALIDATION_STANDARD.md`; DEC-0031; DEC-0032 | `experiments/lifecycle.py`; release-reference retention, post-release attempt rejection, single-FROZEN, zero-attempt fixed evaluation, and FROZEN/RUNNING/EVALUATED/DECIDED historical release-verification tests in `test_sealed_release.py` | Later result is exploratory or invalid, never confirmatory. |

## Future Required Invariants

These requirements are not implemented and must not be cited as current
protection.

| ID | Status | Invariant | Governing authority | Required future evidence | Failure consequence |
|---|---|---|---|---|---|
| REG-F03 | `TOOLING MERGED / LIVE HOST EVIDENCE BLOCKED` | A `HOST_ENFORCED` release requires typed canonical evidence created by one governed executed Windows preflight/setup/verification flow, exact Item 8 FROZEN authority, the verified release root and artifact, and the same global one-way exposure ledger. Raw mappings, JSON documents, and arbitrary report files cannot create authority. Governed DACL/SACL authority and its verification bind to actual local-user SIDs, plus well-known SYSTEM and Administrators SIDs; effective login uses a runtime machine-qualified name without persisting it. The real Windows research identity must be unable to list, read, create, write, delete, own, or change ACLs on the sealed vault before release. Denial audit evidence requires a 4656 Audit Failure from that exact research SID; performed custodian activity requires a 4663 Audit Success from that exact custodian SID in the same verification window. Display names are diagnostic only. | DEC-0006; DEC-0035–DEC-0036; RISK-017; Roadmap Item 10B | Hostile schema/service/raw-promotion/audit-classification tests and inert-by-default scripts exist. The first owner-controlled elevated setup failed before audit/effective probes and rolled back completely. Still required: independent review of the audit-event SID-binding follow-up, then a successful elevated rerun proving exact preflight binding, effective two-identity SID-based DACL/SACL, exact-SID live audit events, backup/sync/index evidence, denial, and controlled release on the already encrypted fixed NTFS volume. | Item 10 and Stage 1B cannot pass. |
| REG-F04 | `PLANNED / NOT YET ENFORCED` | Package and dependency boundaries prevent research code from importing broker, live-order, credential, deployment, or self-promotion capability. | RISK-010; Roadmap Item 11 | Dedicated import/dependency graph and prohibited-entry-point tests | Item 11 and Stage 1B cannot pass. |

## Maintenance Rule

Update this catalog whenever a reviewed change creates, strengthens, supersedes,
or intentionally changes an invariant. Keep historical reasoning in
`docs/DECISIONS.md` and risk observations in `docs/RISK_REGISTER.md`. Do not
weaken an invariant silently or mark a future invariant implemented based only
on a schema, configuration flag, mocked path, or passing feature-specific test.
