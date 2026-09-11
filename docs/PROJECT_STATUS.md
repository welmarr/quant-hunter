# Quant Hunter Project Status

## CURRENT RESUME STATE

| Field | Value |
|---|---|
| PROJECT | Quant Hunter |
| LAST VERIFIED DATE | 2026-09-10 |
| AUTHORITATIVE MAIN | `6c9d5ae1eec58faeca53239d832748053387f1bc` |
| CURRENT STAGE | Stage 1B — Foundation Implementation |

## COMPLETED

- Stage 0
- Stage 1A
- Stage 1B Items 1–9

## LAST COMPLETED ITEM

Item 9 — Validation and Simulation Interfaces is `COMPLETE / INDEPENDENT
REVIEW PASSED`. Its final cross-binding reviewed head is
`d6ff6b26fced3c7750f8a4c68b520b70c0567c77`; it is merged on main at
`6c9d5ae1eec58faeca53239d832748053387f1bc`. Post-merge Quality #32 passed on
Ubuntu and Windows. Ubuntu ran 630 tests with 90.99% combined statement/branch
coverage; Windows also succeeded.

## NEXT ROADMAP ITEM

Item 10 — Sealed OOS Boundary.

## PLANNED DECOMPOSITION

Item 10 is planned as:

- **10A — software release core and synthetic security contracts.**
- **10B — real Windows host-enforced boundary.**

Neither 10A nor 10B is started or authorized by this documentation batch.

## AFTER ITEM 10

- Item 11 — Production Separation
- Item 12 — Reproducibility Audit
- Item 13 — Stage 1B Closeout

## OPEN RISKS

- **RISK-017:** the real sealed-OOS host boundary and its residual administrator,
  backup, sync, and indexing exposure remain open.
- **RISK-018:** registry concurrency, filesystem redirection, and stale/crashed
  lock recovery remain open. The intermittent Windows `.allocation.lock`
  timeout observed during PR #5 must be investigated during Item 12 even if it
  never occurs again.
- **RISK-023:** repository visibility, licensed data, and future proprietary
  research disclosure require review before Stage 2.
- **RISK-024:** main branch protection must be established and verified before
  Stage 2.

The complete authoritative risk inventory and evidence are in
`docs/RISK_REGISTER.md`.

## BUDGET

- Month-1 cap: USD 400.
- OpenAI Codex credits: USD 10 `SPENT`.
- ChatGPT Pro: purchased; exact charge, tax, proration, Plus credit, service
  allocation, and renewal terms remain `UNKNOWN`.
- Aggregate Month-1 spend and remaining headroom: `UNKNOWN`.
- No new paid action is authorized.

`docs/BUDGET_LEDGER.md` is the canonical aggregate budget record.

## GIT WORKFLOW

The project owner controls all Git writes. Codex must not pull, push, commit,
merge, rebase, switch, checkout, create or delete branches or tags, reset,
clean, add, or stash unless the owner explicitly changes this policy. Read-only
Git inspection remains permitted.

## RESUME PROTOCOL

A future agent must:

1. Read `AGENTS.md`.
2. Read this file.
3. Verify the current Git HEAD, branch, and worktree.
4. Read `docs/ROADMAP.md`, `docs/DECISIONS.md`, `docs/RISK_REGISTER.md`, and the
   governing documents for the next item.
5. Reconcile this current-state summary against actual repository and review
   evidence.
6. Stop and reconcile rather than guess if the evidence conflicts.
7. Complete the required pre-step checkpoint before implementation.

## STATUS UPDATE RULE

Update this file in every merge that materially changes the current stage, item
status, reviewed or merged authority, next authorized work, material open risks,
budget facts, or resume point. Keep it concise and current. Historical reasoning
and evidence belong in Git, `docs/DECISIONS.md`, `docs/RISK_REGISTER.md`,
`docs/DEVELOPMENT.md`, and pull-request records.
