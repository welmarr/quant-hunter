# Quant Hunter Project Status

## CURRENT RESUME STATE

| Field | Value |
|---|---|
| PROJECT | Quant Hunter |
| LAST VERIFIED DATE | 2026-09-11 |
| LAST VERIFIED IMPLEMENTATION MAIN | `20851f262041cda1fe26844032f298b2a1531ffd` |
| CURRENT STAGE | Stage 1B — Foundation Implementation |

The stored SHA is the verified post-merge Item 10A checkpoint. It is not a
substitute for checking current Git. Every resume must obtain the current
branch and HEAD directly from Git, then reconcile this file against that state
and the available review evidence. Do not update this field speculatively with
the future merge SHA of this file's own change.

## COMPLETED

- Stage 0
- Stage 1A
- Stage 1B Items 1–10A

## LAST COMPLETED ITEM

Item 10A — software release core and synthetic security contracts is `COMPLETE /
INDEPENDENT REVIEW PASSED / MERGED / POST-MERGE CI GREEN`. Its reviewed branch
head is `0892bfdb9231053e8896867facb8fc3de47ebf8e`; it is merged on main at
`20851f262041cda1fe26844032f298b2a1531ffd`. Post-merge Quality #36 succeeded on
Ubuntu and Windows with 694 tests on each platform and 90.11% combined
statement/branch coverage on Ubuntu.

## CURRENT ITEM

Item 10B — real Windows host-enforced sealed-OOS boundary is `IMPLEMENTED
TOOLING / HOST EVIDENCE BLOCKED` on
`feature/stage1b-item10b-host-boundary`. The 2026-09-11 read-only Windows
preflight confirmed two local fixed NTFS volumes but ran without elevation and
could not read BitLocker, audit-policy, or backup evidence. It therefore did
not prove an already encrypted eligible volume. No host mutation was permitted.

## PLANNED DECOMPOSITION

Item 10 is planned as:

- **10A — software release core and synthetic security contracts.**
- **10B — real Windows host-enforced boundary.**

Item 10A implements only software and synthetic evidence. Item 10B now provides
the typed host-evidence, conditional release-event, host-release-service, and
inert-by-default Windows script tooling. The live boundary remains blocked
until an elevated rerun proves a fully protected fixed NTFS volume and every
DACL, SACL/audit, effective-identity, indexing, sync, backup, and controlled
release condition. Full Item 10 is not complete.

## AFTER ITEM 10

- Item 11 — Production Separation
- Item 12 — Reproducibility Audit
- Item 13 — Stage 1B Closeout

## OPEN RISKS

- **RISK-017:** the real sealed-OOS host boundary and its residual administrator,
  backup, sync, and indexing exposure remain open. Item 10B code and scripts do
  not replace the missing live evidence.
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
4. Inspect open material GitHub Issues and reconcile them with the repository
   authorities.
5. Read `docs/ROADMAP.md`, `docs/DECISIONS.md`, `docs/RISK_REGISTER.md`, and the
   governing documents for the next item.
6. Reconcile this current-state summary against actual repository and review
   evidence.
7. Stop and reconcile rather than guess if the evidence conflicts.
8. Resume Item 10B from the retained read-only blocker: use a separate elevated
   Windows session to rerun `scripts/windows/item10b_preflight.ps1` against an
   owner-selected, already encrypted fixed NTFS volume. Do not change BitLocker.
9. Complete the required pre-step checkpoint before any later item.

## STATUS UPDATE RULE

Update this file in every merge that materially changes the current stage, item
status, reviewed or merged authority, next authorized work, material open risks,
budget facts, or resume point. Keep it concise and current. Historical reasoning
and evidence belong in Git, `docs/DECISIONS.md`, `docs/RISK_REGISTER.md`,
`docs/DEVELOPMENT.md`, and pull-request records.
