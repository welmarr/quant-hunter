# Decisions

## Decision Policy

Record decisions that affect architecture, research methodology, statistical validity, data timing, leakage controls, experiment scope, cost modeling, production isolation, security, or spending. Record them before or with the change—never after seeing results merely to justify an outcome. Unresolved assumptions belong here as explicit open questions rather than silent guesses.

Entries are append-only. A later decision may supersede an earlier one but must link to it and preserve its rationale. Changes to frozen experiments also require a new experiment ID under `EXPERIMENT_LEDGER.md`.

## Required Decision Record

```text
ID: DEC-NNNN
Date: YYYY-MM-DD
Status: PROPOSED | ACCEPTED | REJECTED | SUPERSEDED
Scope: architecture | governance | methodology | validation | data | security | cost | operations
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
- **Alternatives considered:** Retain the entire specification in `AGENTS.md`, or split it without a traceability map. Both increase drift or persistent-context cost.
- **Scientific/statistical consequences:** Invariants remain prominent while detailed standards have explicit authorities; no evidence standard is relaxed.
- **Reproducibility and cost consequences:** Cross-document auditing becomes possible; no purchase or implementation cost is introduced.
- **References:** `AGENTS.md`, `README.md`, `REQUIREMENTS_TRACEABILITY.md`, and all domain documents created by this decision.
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through the explicit documentation-refactor request dated 2026-09-04.

### DEC-0002 — Documentation Before Stage 1

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** operations
- **Context:** The existing master specification required a research foundation before strategy work, and the refactor request prohibited Stage 1 until documentation architecture was complete.
- **Decision:** Complete and audit the documentation architecture before any Stage 1 implementation. This decision does not itself authorize Stage 1 or strategy development.
- **Alternatives considered:** Scaffold Stage 1 concurrently, or begin strategy code. Both violate the requested gate and increase the risk of designing controls after results exist.
- **Scientific/statistical consequences:** Validation, data, registry, and leakage requirements precede research computation.
- **Reproducibility and cost consequences:** The repository remains documentation-only; no dependency, data, service, or infrastructure spending is introduced.
- **References:** `AGENTS.md`, `PROJECT_CHARTER.md`, `ROADMAP.md`, `VALIDATION_STANDARD.md`.
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through the explicit documentation-refactor request dated 2026-09-04.

## Open Decisions Before Scaffolding

- Select and record the supported modern Python version.
- Select and record package/environment management and lockfile tooling.
- Define the physical data store and technical access-control mechanism for sealed holdouts.
- Define canonical configuration serialization, artifact storage, and content hashing.
- Define the initial CI, formatter, linter, type checker, test framework, and coverage policy.
- Define identifier-allocation concurrency and the machine-readable registry formats.
- Define the exact Month-1 budget window and treatment of pre-existing subscriptions; until resolved, do not assume unrecorded budget headroom.

Resolve these through dated decision records before implementation; do not infer them from examples in the architecture documents.
