# Quant Hunter Project Status

## CURRENT RESUME STATE

| Field | Value |
|---|---|
| PROJECT | Quant Hunter |
| LAST VERIFIED DATE | 2026-09-11 |
| LAST VERIFIED IMPLEMENTATION MAIN | `cf26f4a3c8abd2387649a0baf90d398679ea8ca5` |
| CURRENT STAGE | Stage 1B — Foundation Implementation |

The stored SHA is the verified PR #8 post-merge implementation checkpoint. It is
not a substitute for checking current Git. Every resume must obtain the current
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

Item 10B — real Windows host-enforced sealed-OOS boundary is `TOOLING MERGED /
LIVE HOST EVIDENCE BLOCKED`. PR #8 is merged on main at
`cf26f4a3c8abd2387649a0baf90d398679ea8ca5`; post-merge Quality #39 passed 768
tests on Ubuntu and Windows with 90.20% combined statement/branch coverage on
Ubuntu. Independent review previously failed head
`238a1538888a34635b7f274b451fbd57c980cb0e` because its public report finalizer
could promote caller assertions. DEC-0036 removes that path and binds authority
creation to one executed preflight/setup/verification flow. Independent
re-review confirmed that bypass fixed at
`45611b771951839c96f4f19111ae4d8e7fb6898e`, then failed the Windows audit
evidence semantics: denied research access must use 4656 Audit Failure, while
4663 Audit Success remains the performed-access evidence for the custodian.
Quality #37 passed Windows but failed Ubuntu because the pure classifier used
`Join-Path` on a synthetic Windows `D:` ObjectName. PR #8 corrected that
provider dependency and passed independent review.

The owner then ran an elevated preflight against a separate fixed NTFS target.
It passed with BitLocker On/FullyEncrypted, no path or identity conflict, and no
sync overlap; unreadable backup configuration remains residual risk. The
authorized setup failed closed after creating both governed accounts and before
the audit-policy or effective-identity phases. Security events showed account
creation, enablement, change, and rollback deletion (4720/4722/4738/4726), with
no 4719 audit-policy change and no governed 4656/4663 evidence. Rollback removed
the users and batch-created root, restored File System auditing to No Auditing,
and left BitLocker unchanged. No canonical `HOST_ENFORCED` evidence exists.

A read-only translation probe showed that local `.\qh-*` names are not a
portable ACL authority on the tested host. Branch
`fix/item10b-windows-local-identity` binds DACL/SACL creation and verification to
the actual local-user SIDs, uses well-known SYSTEM/Administrators SIDs, and uses
the runtime machine name only for in-memory effective-login credentials. The
correction awaits independent review and a later owner-controlled live rerun.

## PLANNED DECOMPOSITION

Item 10 is planned as:

- **10A — software release core and synthetic security contracts.**
- **10B — real Windows host-enforced boundary.**

Item 10A implements only software and synthetic evidence. Item 10B now provides
the typed host-evidence, conditional release-event, host-release-service, and
inert-by-default Windows script tooling. Raw mappings and report files have no
supported authority-creation path; retained canonical evidence remains
loadable for audit. The live boundary remains blocked
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
8. Independently review the SID-authority and safe-diagnostic correction on
   `fix/item10b-windows-local-identity`, preserving the 4656 Failure / 4663
   Success semantics and DEC-0036 authority path. After merge and green CI,
   resume Item 10B only in a separately authorized elevated owner session and
   rerun the governed capture workflow against the already protected fixed NTFS
   target. Do not change BitLocker.
9. Complete the required pre-step checkpoint before any later item.

## STATUS UPDATE RULE

Update this file in every merge that materially changes the current stage, item
status, reviewed or merged authority, next authorized work, material open risks,
budget facts, or resume point. Keep it concise and current. Historical reasoning
and evidence belong in Git, `docs/DECISIONS.md`, `docs/RISK_REGISTER.md`,
`docs/DEVELOPMENT.md`, and pull-request records.
