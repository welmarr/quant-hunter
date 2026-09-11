# Deferred Material Work and GitHub Issue Governance

## Purpose and authority

GitHub Issues are Quant Hunter's operational tracker for material work that is
real but cannot be completed in the current authorized batch. They make an
owner, target, investigation, and closeout test visible across sessions.

Issues do not replace the repository authorities:

- `RISK_REGISTER.md` retains durable scientific, security, operational, and
  budget risk meaning and evidence.
- `DECISIONS.md` records why an architectural, scientific, or governance choice
  was accepted.
- `REGRESSION_GUARD.md` retains invariants and the evidence needed to prevent
  regression.
- `PROJECT_STATUS.md` is the current operational resume point.
- `ROADMAP.md` controls stage and item ordering and gates.

An Issue links actionable work to these records. Closing or editing an Issue
cannot by itself change a risk, decision, invariant, stage, or item status.

## When an Issue is mandatory

Create an Issue when all of these conditions apply:

1. The problem is real, credible, or supported by retained evidence.
2. It is not fully resolved in the current reviewed batch.
3. Future work is required.
4. Losing the finding across sessions would harm scientific validity, security,
   reproducibility, availability, performance, maintainability, cost control,
   legal/licensing compliance, or operational reliability.

Material examples include deferred defects, intermittent CI or host failures,
unresolved security weaknesses, reproducibility debt, architecture debt with a
defined decision point, prerequisites for a later stage, and accepted residual
risk requiring action.

Trivial wording fixes, one-off cleanup, vague ideas, and unsupported wishes do
not require Issues unless evidence makes them material.

## Current-batch blockers

A current-batch correctness or gate failure must be fixed in the current batch,
retested, and independently reviewed. Creating an Issue cannot convert that
failure into a pass. If the authorized batch explicitly permits a blocked
tooling outcome, the implementation may retain that exact blocked status, but
the missing external or host evidence remains a gate and must be tracked.

## Required Issue content

Every material deferred Issue must contain:

- **Summary:** a short, unambiguous description.
- **Problem:** the technical or scientific failure or debt.
- **Evidence:** exact dates, commits, PRs, workflow runs/jobs, tests, errors,
  functions, and reproduction conditions that are actually known.
- **Why This Matters:** one or more explicit impact classes.
- **Current Understanding:** separate confirmed facts, observations,
  hypotheses, and unknowns.
- **Why Deferred:** why the current authorized work cannot resolve it.
- **Target:** an exact Stage, Item, or gate; never only “later.”
- **Proposed Investigation:** concrete steps that test the unknowns.
- **Proposed Solution:** a candidate when known, clearly labeled unvalidated.
- **Acceptance Criteria:** exact evidence required to close.
- **Regression Evidence Required:** tests, hostile scenarios, CI, host proof,
  or documentation needed to prevent recurrence.
- **Relationships:** applicable `RISK-xxx`, `DEC-xxxx`, `REG-xxx`, PR, commit,
  roadmap item, and related Issue links.
- **Technical References:** primary standards or official documentation where
  they materially guide the work.
- **Closure Evidence:** initially `PENDING`; on closure, resolving commits, PR,
  tests, CI or host evidence, governance updates, and residual limitations.

State proposed causes and solutions as hypotheses until evidence validates
them. Never invent evidence to complete a template.

## Duplicate and closure rules

Search open and closed Issues before creating a new one. Update an equivalent
open Issue rather than splitting its evidence across duplicates.

An Issue cannot close because somebody believes it is fixed, an error did not
recur, one rerun passed, a timeout increased, a workaround exists, or related
code changed. Closure requires every stated acceptance criterion and durable
evidence. A partial correction leaves the Issue open with its remaining scope
updated.

When an Issue closes, update its closure evidence and reconcile every affected
risk, decision, regression invariant, project-status statement, and roadmap
gate in the same governed change.
