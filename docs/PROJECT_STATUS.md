# Quant Hunter Project Status

## CURRENT RESUME STATE

| Field | Value |
|---|---|
| PROJECT | Quant Hunter |
| LAST VERIFIED DATE | 2026-09-11 |
| LAST VERIFIED IMPLEMENTATION MAIN | `3d6f5f50e9f7b202498a6d3a2357fcccee2df409` |
| CURRENT STAGE | Stage 1B — Foundation Implementation |

The stored SHA is the verified implementation checkpoint immediately before
the current Item 10A feature branch. It is not a
substitute for checking current Git. Every resume must obtain the current
branch and HEAD directly from Git, then reconcile this file against that state
and the available review evidence. Do not update this field speculatively with
the future merge SHA of this file's own change.

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

## CURRENT ITEM

Item 10A — software release core and synthetic security contracts is
`IMPLEMENTED / INDEPENDENT REVIEW PENDING` on
`feature/stage1b-item10a-sealed-oos-core`. Nova's review of head
`859233574d4d8ea9595e7985f3da82aba252c99a` found a competing public raw
exposure-ledger writer. The corrective work makes `SealedReleaseService` the
sole supported public exposure writer and requires independent re-audit.

## PLANNED DECOMPOSITION

Item 10 is planned as:

- **10A — software release core and synthetic security contracts.**
- **10B — real Windows host-enforced boundary.**

Item 10A implements only software and synthetic evidence. Item 10B is `NOT
STARTED` and remains separately gated; no real Windows host-security mutation is
authorized. The next action is independent re-review of Item 10A, not Item 10B
implementation.

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

For an explicitly authorized Quant Hunter batch, Codex may run the normal
non-destructive Git operations needed for that batch: status, diff, log, fetch,
fast-forward-only pull when needed, branch switch or creation, add, commit,
push, and upstream setup. Command-local author identity is permitted when
needed. This bounded authority does not permit merging into `main` without
owner authorization, force-pushing, hard reset, destructive clean, published
history rewriting, rebasing published reviewed history, branch or tag deletion,
or bypassing failed checks.

The owner remains required for final merge authorization, stage transitions,
host or security mutations, new spending, intentional scientific-invariant
changes, and architecture changes arising from failed independent review.

When a Codex task executes any Git command, its final response must contain
`### Git Actions Executed` and report every successful or failed command on one
line in this exact structure:
`<number>. <exact command> | <READ-ONLY|LOCAL WRITE|REMOTE WRITE> | <purpose> | Result: <concise result>`.

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
