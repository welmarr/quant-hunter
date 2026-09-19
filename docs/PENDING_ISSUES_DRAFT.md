# Pending GitHub Issue Drafts — External Review Backlog

This is the sole active repository authority for local Issue drafts. It is a
draft operational backlog only, not an operational GitHub Issue tracker, and it
does not authorize implementation, architecture change, host mutation,
purchase, strategy, merge, or later-stage work. Nova or the owner may create
the corresponding Issues through GitHub only after a fresh duplicate check.
`DEFERRED_ISSUE_DRAFTS.md` is a migration tombstone and must not receive active
drafts.

The GitHub plugin found no open Issues on 2026-09-18. Earlier write attempts in
this batch returned HTTP 403 `Resource not accessible by integration` and
created no Issues. No Issue number or URL is claimed below.

## `[RISK-021] Reconcile Month-1 spend and restore known budget headroom`

### Summary

Reconcile the exact Month-1 project spend, including ChatGPT Pro, so the USD
400 cap and remaining headroom are known from retained evidence.

### Problem

The budget ledger records USD 10 of Codex credits, but the ChatGPT Pro charge,
tax, proration, prior-plan credit, service allocation, renewal terms, aggregate
spend, and remaining headroom are `UNKNOWN`. Governance therefore blocks every
new paid action.

### Evidence

- Review date: 2026-09-18.
- `docs/BUDGET_LEDGER.md` records USD 10 under
  `COST-01a0751b-6555-73d9-961e-78c98ff8405b`.
- ChatGPT Pro is recorded under
  `COST-01a07a57-9662-742d-a1ba-f9f6ab023815` with amount unresolved.
- `docs/PROJECT_STATUS.md` reports aggregate spend and headroom as `UNKNOWN`.
- RISK-013 and RISK-021 remain `OPEN`.

### Why This Matters

Budget control, auditability, procurement safety, and the hard USD 400 cap.

### Current Understanding

- Confirmed: USD 10 of Codex credits was spent and ChatGPT Pro was purchased.
- Unknown: invoice amount, tax, proration/credit, service dates, renewal terms,
  attributable API usage, aggregate spend, and remaining headroom.

### Why Deferred

Only the owner can supply private invoice/account evidence. This documentation
batch cannot infer it.

### Target

Stage 1B Item 13 at latest, and before any new paid commitment.

### Proposed Investigation

Collect invoice and service-period evidence, reconcile taxes and credits,
identify project-attributable usage, and recompute totals under DEC-0010.

### Proposed Solution

Update the existing COST records from owner evidence. Do not impute a value.

### Acceptance Criteria

- Exact charges, service dates, taxes, credits, renewal terms, and allocation
  are recorded or evidenced as not applicable.
- Aggregate spend and remaining headroom are numeric and within USD 400.
- RISK-013, RISK-021, PROJECT_STATUS, and BUDGET_LEDGER agree.
- No purchase is made merely to close the Issue.

### Regression Evidence Required

Budget-ledger consistency review before every later purchase, renewal, usage
increase, and stage gate.

### Relationships

DEC-0010; RISK-013; RISK-021; AGENTS rule 20; Stage 1B Item 13.

### Technical References

Owner invoice/account evidence and the accepted DEC-0010 liability basis.

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

- Review date: 2026-09-18.
- RISK-023 is `OPEN`.
- Current Stage 1 evidence is synthetic and sanitized.
- No decision authorizes publication of private research or licensed content.

### Why This Matters

Security, intellectual property, legal/licensing compliance, cost, and future
scientific reproducibility.

### Current Understanding

- Confirmed: the repository is public and current committed data is synthetic.
- Confirmed: AGENTS forbids secrets, credentials, and private licensed data.
- Unknown: Stage 2 repository split, redistribution terms, derived-research
  disclosure boundary, and screenshot/log policy.

### Why Deferred

No real provider, licensed dataset, or proprietary model is authorized in the
current Stage 1B work.

### Target

Before Stage 2 data or model expansion.

### Proposed Investigation

Inventory future artifact classes and provider obligations; classify source
bytes, metadata, derivatives, research code, outputs, logs, and screenshots;
compare public/private repository and external-storage options.

### Proposed Solution

Adopt a documented classification and storage/publication policy with explicit
redistribution rules. The final topology remains an owner decision.

### Acceptance Criteria

- An accepted visibility/IP/licensing decision exists.
- Rules cover source bytes, metadata, derivatives, logs, screenshots, and
  generated artifacts.
- Provider-specific redistribution boundaries are recorded before ingestion.
- Repository, architecture, risk, and contributor guidance agree.

### Regression Evidence Required

Secret/license scans, sanitized-fixture tests, documentation review, and a
pre-Stage-2 disclosure checklist.

### Relationships

RISK-011; RISK-023; AGENTS rule 13; `DATA_ARCHITECTURE.md`; Stage 2 gate.

### Technical References

GitHub repository-visibility documentation and future provider license terms.

### Closure Evidence

PENDING.

## `[STAGE-1 EXIT] Run a full synthetic end-to-end tracer experiment`

### Summary

Complete one synthetic experiment through the full governed lifecycle as the
Stage 1 Exit Integration Gate.

### Problem

Lifecycle and V0–V9 components have tests, but no experiment has traversed
`DRAFT → REGISTERED → FROZEN → RUNNING → EVALUATED → DECIDED` as one retained
end-to-end workflow. DEC-0038 accepts the tracer requirement and defers its
execution until after Stage 1B Item 13, without allowing Stage 1 to complete.

### Evidence

- Review date: 2026-09-18.
- `docs/EXPERIMENT_LEDGER.md` states that no experiments are registered.
- Items 8 and 9 implement separately reviewed lifecycle/evidence contracts.
- DEC-0038 records the deferral.
- `docs/ROADMAP.md` records the Stage 1 Exit Integration Gate.

### Why This Matters

Scientific validity, integration assurance, reproducibility, and proof that the
separate controls form one usable process.

### Current Understanding

- Confirmed: the components exist and no complete experiment exists.
- Unknown: cross-component usability, authority, and retention defects that
  isolated tests may not reveal.

### Why Deferred

Finish Stage 1B Items 10B–13 first. Deferral does not waive the Stage 1 exit
integration proof.

### Target

After Stage 1B Item 13 closeout, as the Stage 1 Exit Integration Gate and before
Stage 1 may be declared complete.

### Proposed Investigation

Register one bounded synthetic hypothesis, freeze it, run it, retain attempts
and results, complete V0–V9 dispositions, decide it, and independently
reconstruct the evidence chain.

### Proposed Solution

Reuse existing Stage 1 interfaces and synthetic data. Do not introduce a real
strategy or market data.

### Acceptance Criteria

- One permanent EXP record completes every lifecycle transition.
- Every digest, timestamp, partition, artifact, release reference, result, and
  decision verifies from retained evidence.
- Applicable V0–V9 evidence exists and non-applicability has reasons.
- A clean independent rerun reconstructs the expected evidence.
- Independent review passes before Stage 2 starts.

### Regression Evidence Required

End-to-end and hostile cross-binding tests, the full locked gate, deterministic
rerun evidence, and reconciled governance records.

### Relationships

DEC-0038; REG-008–REG-018; Roadmap Stage 1 Exit Integration Gate; Items 8–13.

### Technical References

`EXPERIMENT_LEDGER.md`, `VALIDATION_STANDARD.md`, and
`RESEARCH_METHODOLOGY.md`.

### Closure Evidence

PENDING.

## `[RISK-017] Complete Item 10B live Windows host-boundary evidence`

### Summary

Complete and independently review the accepted Windows host-enforced OOS
boundary through the separately authorized live capture.

### Problem

Item 10B tooling is merged, including the repository/runtime binding and
operator-diagnostic corrections, but no canonical `HOST_ENFORCED` evidence
exists. The missing proof is the successful owner-gated live capture and
independent evidence review under the accepted design.

### Evidence

- PR #9 merged actual-SID and provider-independent evidence corrections.
- One setup created governed accounts, then rolled back before audit/effective
  identity evidence.
- A later capture failed at repository binding before setup and made no host
  mutation.
- PR #12 merged the governed repository/runtime binding and diagnostic
  sanitization corrections on `main` at
  `e0ba326540b4493f122e384ac7e7d4bcd0ebf6e2`.
- Post-merge Quality #51 passed on that exact commit on Ubuntu and Windows.
- The elevated owner read-only binding proof passed before merge.
- RISK-017 and REG-F03 remain open.
- No canonical `HOST_ENFORCED` authority exists.

### Why This Matters

Sealed-OOS integrity, scientific validity, host security, reproducibility, and
Stage 1B completion.

### Current Understanding

- Confirmed: software/tooling evidence is not live host evidence.
- Confirmed: the accepted design uses actual SIDs, exact-SID 4656 Failure,
  exact-SID 4663 Success, and one governed capture path.
- Confirmed: the remaining current-path proof is the separately authorized live
  capture and independent review.
- Future alternative-isolation ideas remain unaccepted analysis and cannot
  replace the current authority without a separate decision and review.

### Why Deferred

This governance batch cannot execute host mutations or alter the accepted
architecture. The live capture remains separately owner-gated.

### Target

Stage 1B Item 10B before Item 10 closes. Any pivot requires a separate accepted
decision and independent review.

### Proposed Investigation

Run the bounded current design only after separate owner authorization, retain
its complete sanitized evidence, and subject that evidence to independent
review. If architecture is later reopened, compare alternatives under a
separate explicit decision without treating hashing alone as non-access proof.

### Proposed Solution

No new solution is accepted. Continue the current governed path unless a later
decision explicitly changes it.

### Acceptance Criteria

- Complete and independently review `HOST_ENFORCED` evidence under the accepted
  design; or accept a replacement decision covering threat model, invariants,
  tests, roadmap, and evidence.
- No alternative claims that hashing alone proves a file was not read.
- RISK-017, REG-F03, status, roadmap, and decisions agree.

### Regression Evidence Required

Hostile host-authority tests, the full Ubuntu/Windows gate, live sanitized host
evidence for the selected design, independent review, and post-merge evidence
for any implementation change.

### Relationships

RISK-017; REG-F03; DEC-0006; DEC-0035; DEC-0036; PR #9; PR #12; Item 10B.

### Technical References

Microsoft ACL/audit documentation and primary references for any alternative.

### Closure Evidence

PENDING.

## `[RISK-002] Define scalable AI ideation versus registered search accounting`

### Summary

Decide whether and how to separate data-restricted ideation from statistically
counted candidate exposure without weakening multiple-testing controls.

### Problem

Current governance counts every AI prompt, retry, parameterization, and
discarded candidate. External review considers literal prompt-level counting
potentially unworkable at scale and proposes an ideation sandbox before strict
registration. The proposal is an open question, not an accepted relaxation.

### Evidence

- AGENTS rule 5, RISK-002, REG-011, `RESEARCH_METHODOLOGY.md`,
  `VALIDATION_STANDARD.md`, and `EXPERIMENT_LEDGER.md` govern exposure.
- No real AI research pipeline or model search has executed.
- No ideation/registration boundary has been accepted.

### Why This Matters

Scientific validity, selection-bias control, scalability, and honest future
AI-assisted research.

### Current Understanding

- Confirmed: data-informed rejected candidates create search exposure.
- Hypothesis: a data-blind or tightly in-sample sandbox may avoid some empirical
  exposure while preserving provenance.
- Unknown: permitted information, semantic-duplicate counting, and prevention
  of hidden selection.

### Why Deferred

The rule affects methodology and requires a decision before Stage 2 search.

### Target

Before Stage 2 model discovery or any AI-assisted empirical candidate search.

### Proposed Investigation

Define ideation, candidate, empirical exposure, registration, and selection;
model representative workflows; compare candidate- and family-level methods;
test information leakage across the boundary.

### Proposed Solution

No solution is accepted. Preserve full provenance and continue counting every
empirically exposed or selection-relevant candidate.

### Acceptance Criteria

- An accepted decision defines exactly when counting begins.
- The rule cannot hide data-informed failures or repeated holdout use.
- Human and AI work retain equivalent standards.
- Documents, schemas, ledger behavior, risks, and tests agree.
- Independent methodological review passes.

### Regression Evidence Required

Hostile hidden-search, retry/prompt-lineage, and family-accounting cases.

### Relationships

RISK-002; REG-011; AGENTS rule 5; Stage 2.

### Technical References

Primary multiple-testing, selective-inference, and adaptive-data-analysis
literature selected during investigation.

### Closure Evidence

PENDING.

## `[RISK-024] Protect main and require reviewed Quality checks before Stage 2`

### Summary

Protect `main` so reviewed Quality checks and the owner workflow gate changes.

### Problem

The durable risk record says `main` remains unprotected. Direct changes could
bypass review or required checks.

### Evidence

- RISK-024 is `OPEN`.
- Reviewed PR and Ubuntu/Windows CI practice exists.
- No retained proof of an active branch rule or ruleset exists.

### Why This Matters

Scientific authority, security, reproducibility, and operational reliability.

### Current Understanding

- Confirmed: review/CI practice exists but protection is not evidenced.
- Unknown: exact ruleset and owner recovery exception model.

### Why Deferred

Repository settings are owner-controlled and outside this documentation batch.

### Target

Before Stage 2.

### Proposed Investigation

Identify stable Quality job names, inspect repository rules through GitHub,
define review/status requirements, and test the workflow with a disposable PR.

### Proposed Solution

Create an owner-approved rule or ruleset that requires intended review and
Quality checks and prevents unsafe direct/force pushes.

### Acceptance Criteria

- Active protection covers `main`.
- Unsafe direct and force pushes are prevented.
- Required checks have unambiguous names.
- Owner recovery and merge workflows are tested.
- Effective configuration evidence is retained.

### Regression Evidence Required

Ruleset inspection, controlled workflow test, passing Quality checks, and
reconciled RISK-024/status documentation.

### Relationships

RISK-024; DEC-0029; Git workflow; pre-Stage-2 gate.

### Technical References

GitHub protected-branch and ruleset documentation.

### Closure Evidence

PENDING.

## `[DATA] Specify corporate actions and survivorship-bias handling`

### Summary

Define point-in-time corporate-action and delisting/survivorship handling before
affected equity or cross-asset research.

### Problem

The architecture requires explicit corporate actions and survivorship handling,
but no operational plan defines split/dividend timing, adjustment versions,
delisted securities, universe membership, symbol changes, or mergers.

### Evidence

- `DATA_ARCHITECTURE.md` requires corporate actions to be explicit.
- `VALIDATION_STANDARD.md` requires survivorship issues to be addressed.
- No real connector, instrument master, action dataset, or universe exists.
- RISK-003, RISK-005, RISK-012, and RISK-015 cover related consequences.

### Why This Matters

Point-in-time correctness, scientific validity, and reproducibility.

### Current Understanding

- Confirmed: the general requirement exists and no implementation is authorized.
- Unknown: provider semantics, adjustment policy, delisting-return treatment,
  universe-history source, and cross-provider identity mapping.

### Why Deferred

No real ingestion or equity strategy is in Stage 1B scope.

### Target

Before ingesting affected data or registering an affected experiment.

### Proposed Investigation

Evaluate authoritative sources; define announcement/effective/payment times;
preserve raw actions; version adjusted series; retain delisted instruments;
specify point-in-time universe and instrument lineage.

### Proposed Solution

Adopt an immutable corporate-action event model and point-in-time
instrument/universe model. The exact design remains unvalidated.

### Acceptance Criteria

- An accepted decision defines action types, times, formulas, and versions.
- Delistings and historical universe membership are preserved.
- Raw prices remain immutable and adjusted data has complete lineage.
- Hostile future-action, correction, symbol-reuse, merger, delisting, and
  universe-leakage cases pass.

### Regression Evidence Required

Synthetic action/universe tests, PIT leakage tests, deterministic replay, the
full locked gate, and independent review.

### Relationships

RISK-003; RISK-005; RISK-012; RISK-015; Stage 2 pre-ingestion.

### Technical References

Primary provider/exchange documentation selected with candidate sources.

### Closure Evidence

PENDING.

## `[EXECUTION] Define market-microstructure and execution-simulation plan`

### Summary

Define the future implementation and evidence plan for microstructure and
execution simulation before claims of realistic tradability.

### Problem

Detailed execution-assumption contracts exist, but no executable slippage,
depth, queue, latency, matching, or fill-simulation architecture exists.

### Evidence

- DEC-0027 and Item 9C are metadata-only.
- RISK-006 covers idealized prices and fills.
- CRP-10 is a future Market Microstructure / Order Flow program.
- Roadmap Item 9 prohibited an execution engine.

### Why This Matters

Scientific validity, economic significance, capacity, and prevention of
idealized performance claims.

### Current Understanding

- Confirmed: governed declaration contracts exist and no engine exists.
- Unknown: instruments, data granularity, venue/broker semantics, calibration,
  and justified model complexity.

### Why Deferred

Implementation exceeds Stage 1B and must follow registered Stage 2 research.

### Target

Before CRP-10 or any experiment claims V6 realism beyond an idealized study.

### Proposed Investigation

Select instruments and horizons; map executable data; define order states,
fills, latency, spread/slippage, depth/queue limitations, calibration, cost
stress, and future comparison to paper trading.

### Proposed Solution

Begin with the simplest instrument-appropriate model and add complexity only
after measured value.

### Acceptance Criteria

- An accepted architecture assigns inputs, claims, calibration, and authority.
- Each realism tier has explicit permitted and prohibited claims.
- Synthetic/hand-checkable fill and cost cases exist.
- Insufficient data fails closed or produces an idealized label.

### Regression Evidence Required

Side, order/fill, partial-fill, latency, session/gap, cost, and adverse-market
hostile tests plus full review.

### Relationships

RISK-006; RISK-012; REG-015–REG-017; DEC-0027; CRP-10; Stages 2 and 5.

### Technical References

Primary exchange, broker, and microstructure sources selected for the registered
instrument.

### Closure Evidence

PENDING.

## `[RISK-018] Investigate registry lock timeout and stale-lock recovery`

### Summary

Investigate the intermittent Windows registry timeout and prove safe stale,
crashed-owner, and orphan-lock recovery before Stage 1B closes.

### Problem

The file-backed registry uses `.allocation.lock` with a five-second default
timeout. One hosted Windows run timed out under concurrent allocation; a rerun
passed without an explanatory implementation change.

### Evidence

- Incident date: 2026-09-07.
- PR #5 reviewed head `d6ff6b26fced3c7750f8a4c68b520b70c0567c77`.
- Quality run #30 / Actions run `34143341935`.
- Failure: `test_concurrent_allocation_is_unique_and_complete` with
  `RegistryLockTimeoutError` under 12 workers.
- Rerun passed 630/630.
- RISK-018 and REG-003 remain open.

### Why This Matters

Availability, reproducibility, and registry-history integrity.

### Current Understanding

- Confirmed: one timeout occurred and the rerun passed.
- Hypotheses: scheduling, antivirus/indexer, Windows sharing, or stale/crashed
  lock weakness.
- Unknown: root cause and safe stale-owner detection.

### Why Deferred

Roadmap Item 12 owns this investigation; this batch cannot modify locking.

### Target

Stage 1B Item 12 — Reproducibility Audit.

### Proposed Investigation

Run repeated contention, controlled timeout, crashed-owner, and orphan-lock
scenarios; avoid trusting PID reuse; prove cleanup cannot fork, truncate,
reorder, overwrite, or lose history.

### Proposed Solution

No solution is accepted. Increasing the timeout alone is insufficient.

### Acceptance Criteria

- Stress and stale/crash/orphan cases pass repeatedly on Windows.
- Histories remain unique, contiguous, canonical, non-forking, and complete.
- Timeout semantics are deterministic under controlled contention.
- A supported root-cause classification is retained.
- Any change has hostile tests and independent review.

### Regression Evidence Required

Targeted concurrency/recovery tests, full Windows/Ubuntu locked gate, repeated
Windows stress, and reconciled RISK-018/REG-003/Item 12 records.

### Relationships

RISK-018; REG-002; REG-003; DEC-0009; PR #5; Quality #30; Item 12.

### Technical References

Python `os.open` and Microsoft `CreateFile`/file-locking documentation.

### Closure Evidence

PENDING.

## `[RISK-019] Define float tolerance versus canonical digest policy`

### Summary

Evaluate numeric tolerances without weakening exact canonical identity and
digest verification.

### Problem

External review suggested `math.isclose`-style tolerances for float/hash drift.
Tolerance-based digest comparison would be unsafe, while future scientific
numeric comparisons may legitimately need registered tolerances.

### Evidence

- RISK-019 covers float, Parquet, ordering, and canonicalization drift.
- DEC-0007, DEC-0014, DEC-0016 and REG-004–REG-005 define exact identity.
- Logical float64 values use exact IEEE 754 bytes.
- No real numerical model exists yet.

### Why This Matters

Reproducibility, numerical validity, and prevention of false equivalence.

### Current Understanding

- Confirmed: digests must compare exactly.
- Hypothesis: future numerical assertions may need justified tolerances.
- Unknown: which computations exhibit cross-platform nondeterminism.

### Why Deferred

No digest defect is evidenced; identity changes need an accepted decision.

### Target

Item 12 for current reproducibility and before the first approximate Stage 2
numeric comparison.

### Proposed Investigation

Separate identity from numerical comparison, run cross-platform vectors,
identify nondeterministic operations, and register tolerances only when justified.

### Proposed Solution

Keep digest equality exact. Add versioned scientific tolerance policies only
for numeric assertions if evidence requires them.

### Acceptance Criteria

- Exact identity remains unambiguous.
- Every approximate comparison has units, rationale, and absolute/relative bounds.
- Cross-platform vectors pass and governance agrees.

### Regression Evidence Required

RFC/JCS vectors, float edge and inequality cases, numerical cross-platform
vectors, full locked gate, and independent review.

### Relationships

RISK-019; REG-004; REG-005; DEC-0007; DEC-0014; DEC-0016; Item 12.

### Technical References

RFC 8785, IEEE 754, and relevant numerical-library documentation.

### Closure Evidence

PENDING.

## `[ARCH] Define scaling threshold for file-backed registries`

### Summary

Measure file-backed registry behavior and define a migration trigger before
scale becomes an operational problem.

### Problem

External review predicts JSON/Parquet registries may become inefficient beyond
several thousand experiments. Current scale is near zero, but append,
verification, indexing, and query costs may create future debt.

### Evidence

- Persistent authority uses append-only JCS JSON revisions.
- Generated indexes are non-authoritative.
- No experiment is registered and no scale failure exists.
- RISK-018 governs correctness/concurrency, not large-scale query performance.

### Why This Matters

Maintainability, performance, availability, and authority-preserving migration.

### Current Understanding

- Confirmed: current scale does not justify a database.
- Hypothesis: larger histories may make scans or verification unacceptable.
- Unknown: access patterns, growth, hardware, budgets, and thresholds.

### Why Deferred

Premature migration adds complexity and may create competing authority.

### Target

Stage 3 planning, or earlier when measured thresholds are exceeded.

### Proposed Investigation

Benchmark allocation, append, verification, index rebuild, lookup, backup, and
recovery at synthetic scales; define warning and migration thresholds.

### Proposed Solution

Retain file-backed authority until evidence justifies change. A database should
initially be a rebuildable index unless a later decision says otherwise.

### Acceptance Criteria

- Benchmarks and growth assumptions are retained.
- Explicit thresholds and an authority-preserving migration plan exist.
- IDs, revisions, canonical bytes, chains, and failures survive migration.
- No database becomes scientific authority accidentally.

### Regression Evidence Required

Scale benchmarks, chain equivalence, rebuild/migration and recovery tests, plus
independent review of any authority change.

### Relationships

DEC-0009; REG-002–REG-004; RISK-018; RISK-020; Stage 3.

### Technical References

Official documentation for candidate technologies evaluated later.

### Closure Evidence

PENDING.

## `[SECURITY] Revisit container or sandbox isolation at Item 11`

### Summary

Re-evaluate process/container isolation at Item 11 or before the first real
connector or credential, whichever comes first.

### Problem

External review proposed Docker or comparable isolation. The owner deferred it
because no real data, credential, live connection, or broker capability exists
and current overhead is not justified.

### Evidence

- Current evidence is synthetic and sanitized.
- No connector, broker credential, or live connection exists.
- Item 11 is the production-separation gate.
- DEC-0039 records the owner decision and revisit trigger.

### Why This Matters

Security, least privilege, credential isolation, reproducibility, and operating
complexity.

### Current Understanding

- Confirmed: no isolation boundary is implemented or claimed.
- Hypothesis: it becomes valuable with sensitive assets or network authority.
- Unknown: future topology, privileges, secret manager, and measured benefit.

### Why Deferred

Owner decision: current risk does not justify overhead. Deferral ends at the
first trigger.

### Target

Item 11, or before any real connector or broker credential.

### Proposed Investigation

Define assets and threat model; compare OS identities, virtual environments,
containers, VMs, and separate hosts; measure security and reproducibility costs.

### Proposed Solution

No technology is accepted. Select the least complex boundary satisfying the
future threat model.

### Acceptance Criteria

- The control is reconsidered at the trigger.
- An accepted decision records alternatives, costs, and selected boundary.
- No real credential or connection precedes that decision.
- Import, dependency, network, filesystem, and secret controls prove separation.

### Regression Evidence Required

Prohibited import/dependency tests, secret scans, applicable boundary tests,
full locked gate, and independent review.

### Relationships

DEC-0039; RISK-010; RISK-011; REG-019; REG-F04; Item 11.

### Technical References

Official platform documentation selected during comparison.

### Closure Evidence

PENDING.

## `[DEBT] Resolve RegistryKind.COST schema authority before Stage 1B closeout`

### Summary

Resolve the mismatch between the persistent `COST` identifier kind and the
absence of a governed cost-registry schema mapping.

### Problem

`RegistryKind.COST` exists, but `SCHEMA_BY_KIND` intentionally has no COST
schema. Governed COST writes therefore fail closed while `BUDGET_LEDGER.md`
acts as the durable cost authority. The future authority model is ambiguous.

### Evidence

- `src/quant_hunter/identity/ids.py` defines `RegistryKind.COST`.
- `src/quant_hunter/config/schema.py` has no COST entry in `SCHEMA_BY_KIND`.
- `MissingGovernedSchemaError` rejects a governed write for an unmapped kind.
- Permanent COST IDs already appear in `BUDGET_LEDGER.md`.

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

Compare the budget ledger's mandatory fields with registry needs, review why
COST was included in persistent IDs, and assess the migration and duplication
risks of introducing `cost.schema.json`.

### Proposed Solution

Choose exactly one model: add and test `cost.schema.json` plus the governed
mapping, or accept `BUDGET_LEDGER.md` as the sole durable cost authority and
remove or explicitly constrain misleading machine-write expectations.

### Acceptance Criteria

- One authority model is accepted and documented.
- Governed behavior fails closed with no contradictory dual authority.
- Schema/mapping tests exist if a machine registry is selected.
- Budget, architecture, decision, and traceability documents agree.

### Regression Evidence Required

Governed-registry rejection or acceptance tests, schema-catalog tests where
applicable, the locked quality gate, and budget/decision/traceability review.

### Relationships

DEC-0009; DEC-0014; `RegistryKind.COST`; `SCHEMA_BY_KIND`;
`BUDGET_LEDGER.md`; Stage 1B Item 13.

### Technical References

`schemas/v1/`, `src/quant_hunter/config/schema.py`, and
`src/quant_hunter/identity/registry.py`.

### Closure Evidence

PENDING.

## `[ARCH] Decide real-data storage, catalog, connector lifecycle and Instrument Master before ingestion`

### Summary

Choose the physical storage, operational catalog, connector-evolution,
source-lifecycle, and instrument-identity architecture before real ingestion.

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
- `DATA_SOURCE_REGISTRY.md` requires permanent source identity and provider
  assessment.

### Why This Matters

Scientific validity, reproducibility, availability, performance,
maintainability, cost, and legal/licensing compliance.

### Current Understanding

- Confirmed: scientific authority belongs to immutable bytes and canonical
  manifests, not a mutable query index.
- Confirmed: physical storage location must not define logical dataset identity.
- Candidate architecture, not accepted: exact raw-object storage; partitioned
  Parquet for normalized, curated, and feature data; DuckDB for analytical
  scans; PostgreSQL as a queryable operational/catalog index rather than
  scientific authority; separated provider connectors and canonical normalizers.
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
based on measured needs and provider/license constraints. This draft does not
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
