# Ready-to-Post Deferred Issue Drafts

GitHub CLI was unavailable during the 2026-09-11 Item 10B batch, so these
complete drafts were retained for duplicate review and remote creation. They
are operational work items and do not replace their linked repository
authorities.

## `[RISK-018] Investigate Windows registry allocation lock timeout and stale-lock recovery`

### Summary

Investigate the intermittent Windows registry allocation timeout and prove safe
stale, crashed-owner, and orphan-lock recovery before Stage 1B closes.

### Problem

The file-backed registry uses `.allocation.lock` with a default 5.0-second
timeout. One hosted Windows run timed out during concurrent allocation. A rerun
passed, but the cause and recovery behavior remain unresolved.

### Evidence

- Date: 2026-09-07.
- PR: #5, “Stage 1B Item 9 — cross-bind validation authorities.”
- Reviewed head: `d6ff6b26fced3c7750f8a4c68b520b70c0567c77`.
- Workflow: Quality run #30, GitHub Actions run `34143341935`.
- Attempt 1: Ubuntu passed; Windows collected 630 tests and reported 629 passed,
  1 failed.
- Exact failure:
  `tests/test_registry.py::test_concurrent_allocation_is_unique_and_complete`.
- Failure class: `RegistryLockTimeoutError` while 12 allocation workers
  contended for `.allocation.lock` under the 5.0-second configured timeout.
- Windows rerun: 630/630 passed and the workflow concluded successfully.
- Item 10A did not modify `identity/registry.py`.

### Why This Matters

Operational reliability, availability, reproducibility, and registry-history
integrity. A faulty recovery policy could block allocation or corrupt, fork, or
lose permanent identity history.

### Current Understanding

- Confirmed: one Windows timeout occurred under 12-worker contention.
- Confirmed: the rerun passed.
- Confirmed: no registry implementation change explains the rerun.
- Hypotheses: scheduler delay, antivirus/indexer interference, Windows sharing
  behavior, or a real stale/crashed-lock weakness.
- Unknown: root cause, reproducibility, safe stale-owner detection, and whether
  any environmental factor is systemic.

### Why Deferred

Item 10B must not modify registry locking. The governing roadmap assigns this
investigation to the reproducibility audit.

### Target

Stage 1B Item 12 — Reproducibility Audit.

### Proposed Investigation

1. Run repeated Windows concurrent-allocation stress with retained timings and
   worker outcomes.
2. Exercise controlled contention at and below the timeout.
3. Terminate a lock owner and test crashed-owner recovery.
4. Create a controlled orphan `.allocation.lock` and test detection/cleanup.
5. Test stale-lock age and owner evidence without trusting PID reuse alone.
6. Prove cleanup cannot overwrite, fork, truncate, reorder, or lose registry
   history.
7. Compare Windows filesystem and security-product observations with Ubuntu.
8. Retain the final root-cause conclusion and residual uncertainty.

### Proposed Solution

No solution is accepted yet. A narrowly evidenced stale-owner protocol or lock
primitive may be proposed after reproduction. Increasing the timeout alone is
not acceptable closure.

### Acceptance Criteria

- Required controlled stress and stale/crash/orphan cases pass repeatedly on
  Windows.
- Registry histories remain unique, contiguous, canonical, non-forking, and
  complete under every case.
- Timeout semantics are deterministic under controlled contention.
- The observed incident has a supported root-cause classification.
- Any implementation change has hostile regression tests and independent
  review; if unchanged, evidence explains why the incident is credibly
  environmental rather than a correctness defect.

### Regression Evidence Required

Targeted registry concurrency/recovery tests, the complete locked gate on
Windows and Ubuntu, repeated hosted or equivalent Windows stress evidence, and
updated RISK-018/REG-003/Item 12 documentation.

### Relationships

RISK-018; REG-002; REG-003; DEC-0009; PR #5; Quality run #30; Stage 1B Item 12.

### Technical References

- Python `os.open`: https://docs.python.org/3/library/os.html#os.open
- Microsoft `CreateFile`: https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
- Microsoft file locking: https://learn.microsoft.com/windows/win32/fileio/locking-and-unlocking-byte-ranges-in-files

### Closure Evidence

PENDING.

## `[RISK-023] Decide repository visibility, IP and licensed-data policy before Stage 2`

### Summary

Make an explicit repository visibility, intellectual-property, secret, and
licensed-data policy before real data or model expansion.

### Problem

The repository is public. Future algorithms, proprietary research, licensed
data and metadata, provider terms, screenshots, credentials, and derived
artifacts need a deliberate publication and redistribution boundary.

### Evidence

- RISK-023 is `OPEN` in `docs/RISK_REGISTER.md`.
- Current Stage 1 evidence is synthetic and sanitized.
- No decision currently authorizes publication of private research or licensed
  provider content.

### Why This Matters

Security, intellectual property, legal/licensing compliance, cost, and future
scientific reproducibility.

### Current Understanding

- Confirmed: the repository is public and current committed data is synthetic.
- Confirmed: AGENTS forbids committed secrets, credentials, and private licensed
  data.
- Unknown: the desired Stage 2 repository split, provider redistribution terms,
  disclosure boundary for derived research, and screenshot/log policy.

### Why Deferred

No real provider, licensed dataset, or proprietary model is authorized in
Stage 1B Item 10B. The owner must decide the future visibility boundary before
Stage 2 expansion.

### Target

Before Stage 2 data/model expansion.

### Proposed Investigation

Inventory planned artifact classes and provider license obligations; classify
source bytes, metadata, derived tables, research code, model outputs, logs, and
screenshots; compare public/private repository and external object-storage
options; and identify secret-scanning and review gates.

### Proposed Solution

Adopt a documented classification and repository/storage policy with explicit
redistribution rules. The final topology remains an owner decision.

### Acceptance Criteria

- An accepted visibility/IP/licensing decision exists.
- Secret and licensed-data handling rules cover source bytes, metadata,
  derivatives, logs, screenshots, and generated artifacts.
- Provider-specific redistribution boundaries are recorded before ingestion.
- Repository, architecture, risk, and contributor guidance agree.

### Regression Evidence Required

Repository secret/license scans, sanitized-fixture tests, documentation review,
and a pre-Stage-2 disclosure checklist linked to RISK-023.

### Relationships

RISK-011; RISK-023; AGENTS rule 13; `DATA_ARCHITECTURE.md`; Stage 2 gate.

### Technical References

- GitHub repository visibility:
  https://docs.github.com/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility

### Closure Evidence

PENDING.

## `[RISK-024] Protect main and require reviewed Quality checks before Stage 2`

### Summary

Protect `main` so reviewed Quality checks and the intended owner workflow gate
changes before Stage 2.

### Problem

The durable risk record says `main` remains unprotected. Direct unsafe changes
could bypass review or required checks.

### Evidence

- RISK-024 is `OPEN` in `docs/RISK_REGISTER.md`.
- Existing workflow evidence includes passing Ubuntu and Windows Quality jobs,
  but no retained proof of an active branch-protection rule or ruleset.

### Why This Matters

Scientific authority, security, reproducibility, and operational reliability.

### Current Understanding

- Confirmed: reviewed PR and CI practice exists.
- Confirmed: repository documentation does not claim active protection.
- Unknown: the exact GitHub ruleset configuration and the owner exception model
  that best preserve recovery access without enabling unsafe routine pushes.

### Why Deferred

Repository settings are an owner-controlled governance action and are outside
the Item 10B software and local-host boundary.

### Target

Before Stage 2.

### Proposed Investigation

Identify stable Quality job names, inspect current repository rules, define
review and status-check requirements, choose strict/loose update behavior, and
test the owner workflow with a disposable branch and PR.

### Proposed Solution

Create an active branch rule or ruleset for `main` that requires the intended
review and Quality checks and prevents unsafe direct and force pushes. Exact
settings remain subject to owner approval and validation.

### Acceptance Criteria

- Active protection covers `main`.
- Direct unsafe and force pushes are prevented as intended.
- Required reviewed Quality checks are configured with unambiguous job names.
- The owner recovery/merge workflow is tested.
- Sanitized screenshots or API output and the effective rule configuration are
  retained in governance evidence.

### Regression Evidence Required

Ruleset or branch-protection inspection, a controlled workflow test, passing
Quality checks, and reconciled RISK-024/project-status documentation.

### Relationships

RISK-024; DEC-0029; project Git workflow; pre-Stage-2 gate.

### Technical References

- GitHub protected branches:
  https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- GitHub rulesets:
  https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets

### Closure Evidence

PENDING.

## `[DEBT] Resolve RegistryKind.COST schema authority before Stage 1B closeout`

### Summary

Resolve the mismatch between the persistent `COST` identifier kind and the
absence of a governed cost-registry schema mapping.

### Problem

`RegistryKind.COST` exists, but `SCHEMA_BY_KIND` intentionally has no COST
schema. Governed COST writes therefore fail closed while
`docs/BUDGET_LEDGER.md` currently acts as the durable cost authority. The future
authority model is ambiguous.

### Evidence

- `src/quant_hunter/identity/ids.py` defines `RegistryKind.COST`.
- `src/quant_hunter/config/schema.py` has no COST entry in `SCHEMA_BY_KIND`.
- `MissingGovernedSchemaError` rejects a governed write for an unmapped kind.
- Permanent COST IDs already appear in `docs/BUDGET_LEDGER.md`.

### Why This Matters

Reproducibility, maintainability, and budget-governance clarity.

### Current Understanding

- Confirmed: the current path fails closed; there is no silent machine write.
- Confirmed: the Markdown ledger is the present durable authority.
- Unknown: whether Stage 1B should introduce a machine-governed cost registry or
  explicitly remove that expectation.

### Why Deferred

Item 10B must not modify registry schema authority or start closeout work.

### Target

Stage 1B Item 13 at latest.

### Proposed Investigation

Compare the budget ledger's mandatory fields with registry needs, review the
reason COST was included in persistent IDs, and assess the migration and
duplication risks of introducing `cost.schema.json`.

### Proposed Solution

Choose exactly one model: add and test `cost.schema.json` plus the governed
mapping, or accept `docs/BUDGET_LEDGER.md` as the sole durable cost authority
and remove or explicitly constrain misleading machine-write expectations.

### Acceptance Criteria

- One authority model is accepted and documented.
- Governed behavior fails closed with no contradictory dual authority.
- Schema/mapping tests exist if a machine registry is selected.
- Budget, architecture, decision, and traceability documents agree.

### Regression Evidence Required

Governed-registry rejection or acceptance tests, schema catalog tests where
applicable, the locked quality gate, and budget/decision/traceability review.

### Relationships

DEC-0009; DEC-0014; `RegistryKind.COST`; `SCHEMA_BY_KIND`;
`docs/BUDGET_LEDGER.md`; Stage 1B Item 13.

### Technical References

`schemas/v1/`, `src/quant_hunter/config/schema.py`, and
`src/quant_hunter/identity/registry.py`.

### Closure Evidence

PENDING.

## `[ARCH] Decide real-data storage, catalog, connector lifecycle and Instrument Master before ingestion`

### Summary

Choose the physical storage, operational catalog, connector-evolution, source
lifecycle, and instrument-identity architecture before real ingestion.

### Problem

Current immutable, provenance, Parquet, and PIT primitives are scientific
foundations, not a complete real-ingestion architecture. Durable choices are
still needed for storage layout, query indexing, provider changes, licenses,
and cross-provider instrument identity.

### Evidence

- Stage 1 has exact raw-object identity, deterministic derived Parquet,
  canonical JCS manifests, distinct physical/lineage/logical identities, and
  PIT selection contracts.
- No real connector, catalog database, paid feed, instrument master, or cloud
  storage is implemented or authorized.
- `DATA_SOURCE_REGISTRY.md` already requires permanent source identity and
  provider assessment.

### Why This Matters

Scientific validity, reproducibility, availability, performance,
maintainability, cost, and legal/licensing compliance.

### Current Understanding

- Confirmed: scientific authority belongs to immutable bytes and canonical
  manifests, not a mutable query index.
- Confirmed: physical storage location must not define logical dataset identity.
- Candidate architecture, not yet accepted: exact raw object storage;
  partitioned Parquet for normalized, curated, and feature data; DuckDB for
  analytical scans; PostgreSQL as a queryable operational/catalog index rather
  than scientific authority; separated provider connectors and canonical
  normalizers.
- Unknown: measured scale, access patterns, provider constraints, deployment
  topology, and whether either database is justified.

### Why Deferred

Item 10B authorizes no ingestion, connector, database, cloud, or paid service.
The choice needs explicit pre-ingestion evidence and owner approval.

### Target

Stage 1B closeout / Stage 2 pre-ingestion architecture decision.

### Proposed Investigation

1. Measure representative synthetic scan, update, and catalog workloads.
2. Evaluate exact raw-object and partitioned Parquet layouts independently from
   logical dataset identity.
3. Compare DuckDB and PostgreSQL roles without making either scientific
   authority.
4. Define connector versus canonical-normalizer boundaries.
5. Define permanent `SOURCE` IDs and append-only `APPROVED`, `REJECTED`,
   `DEPRECATED`, and `UNAVAILABLE` source revisions.
6. Define auditable provider API, schema, pricing, and license changes while old
   experiments retain exact source/dataset revision bindings.
7. Specify a Global Instrument Master that separates canonical instruments from
   provider symbols.
8. Define license-driven byte purge with retained tombstone metadata.

### Proposed Solution

Evaluate the candidate architecture above, then record an explicit decision
based on measured needs and provider/license constraints. This Issue does not
authorize PostgreSQL, DuckDB, cloud storage, or paid feeds.

### Acceptance Criteria

- An accepted pre-ingestion architecture assigns scientific and operational
  authority explicitly.
- Raw, Parquet, catalog, connector, source-lifecycle, Instrument Master, and
  license-purge boundaries are specified and tested with synthetic evidence.
- Old experiment bindings remain reproducible across provider evolution.
- Cost and license implications are approved before commitment.

### Regression Evidence Required

Synthetic storage/replay tests, source-revision and instrument-mapping hostile
tests, license-purge/tombstone tests, performance measurements, the full locked
gate, and reconciled architecture/risk/decision/roadmap documentation.

### Relationships

RISK-004; RISK-005; RISK-012; RISK-019; `DATA_ARCHITECTURE.md`;
`DATA_SOURCE_REGISTRY.md`; Stage 1B closeout; Stage 2 pre-ingestion gate.

### Technical References

Evaluate official documentation for any selected database, storage system, and
provider only when that option reaches the decision stage.

### Closure Evidence

PENDING.
