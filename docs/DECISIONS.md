# Decisions

## Decision Policy

Record decisions that affect architecture, research methodology, statistical validity, data timing, leakage controls, experiment scope, cost modeling, production isolation, security, or spending. Record them before or with the change—never after seeing results merely to justify an outcome. Unresolved assumptions belong here as explicit open questions rather than silent guesses.

Entries are append-only. A later decision may supersede an earlier one but must link to it and preserve its rationale. Changes to frozen experiments also require a new experiment ID under `EXPERIMENT_LEDGER.md`.

## Required Decision Record

```text
ID: DEC-NNNN
Date: YYYY-MM-DD
Status: PROPOSED | ACCEPTED | REJECTED | SUPERSEDED
Scope: architecture | methodology | validation | data | security | cost | operations
Context:
Decision:
Alternatives considered:
Scientific/statistical consequences:
Reproducibility and cost consequences:
References (experiments, models, data sources, code):
Supersedes / superseded by:
Owner and approver:
```

## Decision Log

### DEC-0001 — Split the Master Specification by Authority

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** architecture / governance
- **Context:** The full specification had grown too large for persistent agent instructions.
- **Decision:** Keep invariants and workflow in `AGENTS.md`; move detailed domain requirements into named documents and maintain `REQUIREMENTS_TRACEABILITY.md`.
- **Consequences:** Future changes must update the governing document, relevant cross-references, and traceability map without weakening the invariant rules.

### DEC-0002 — Documentation Before Stage 1

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** operations
- **Decision:** Complete and audit the documentation architecture before any Stage 1 implementation. This decision does not itself authorize Stage 1 or strategy development.
- **Consequences:** The repository remains documentation-only in this milestone.

## Open Decisions Before Scaffolding

- Select and record the supported modern Python version.
- Select and record package/environment management and lockfile tooling.
- Define the physical data store and technical access-control mechanism for sealed holdouts.
- Define canonical configuration serialization, artifact storage, and content hashing.
- Define the initial CI, formatter, linter, type checker, test framework, and coverage policy.
- Define identifier-allocation concurrency and the machine-readable registry formats.

Resolve these through dated decision records before implementation; do not infer them from examples in the architecture documents.
