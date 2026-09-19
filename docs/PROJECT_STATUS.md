# Quant Hunter Project Status

## Current Stage and Item

- **Current stage:** Stage 1B — Foundation Implementation.
- **Current item:** Item 10B.
- **Canonical status:** `TOOLING MERGED / LIVE HOST EVIDENCE BLOCKED`.

## Software State

- Item 10A is complete, independently reviewed, merged, and post-merge CI green.
- PR #12 merged the governed repository/runtime binding correction and the
  operator-diagnostic sanitization corrections into `main` at
  `e0ba326540b4493f122e384ac7e7d4bcd0ebf6e2`.
- Post-merge Quality #51 completed successfully on that exact `main` commit on
  Ubuntu and Windows.
- The elevated owner read-only binding proof passed before PR #12 merged.
- No canonical `HOST_ENFORCED` evidence exists. Software tests, CI, and the
  read-only proof do not replace the separately gated live host evidence.
- BitLocker must not be changed by the Item 10B workflow.

## Open Material Risks

- **RISK-017:** the real sealed-OOS host boundary remains unproven until a
  successful governed live capture is independently reviewed.
- **RISK-018:** registry concurrency and stale/crashed/orphan lock recovery
  remain open for Item 12.
- **RISK-021:** Month-1 aggregate spend and remaining headroom are unknown; no
  paid action is authorized.
- **RISK-023:** repository visibility, intellectual-property, and licensed-data
  policy must be decided before Stage 2.
- **RISK-024:** effective protection of `main` must be established and verified
  before Stage 2.

The complete authoritative inventory and retained evidence are in
`RISK_REGISTER.md`. Local deferred-work drafts are consolidated in
`PENDING_ISSUES_DRAFT.md`; they are not implementation authority and no GitHub
Issue is created merely by their presence.

## Next Durable Technical Gate

The next technical gate is a separately authorized, successful Item 10B live
`HOST_ENFORCED` capture followed by independent evidence review. Item 10 cannot
close and Item 11 cannot begin before that gate passes. The capture must preserve
the accepted exact-SID DACL/SACL authority, 4656 Failure / 4663 Success audit
semantics, provider-independent classification, and DEC-0036 single executed
authority path. It must use only synthetic fixtures and must not change
BitLocker.

After Items 10B–13 close, Stage 1 still requires its exit integration gate: at
least one synthetic end-to-end tracer must complete the governed
`DRAFT → REGISTERED → FROZEN → RUNNING → EVALUATED → DECIDED` lifecycle with
retained evidence and independent review before Stage 1 is complete or Stage 2
can unlock.

## Budget

- Month-1 cap: USD 400.
- OpenAI Codex credits: USD 10 `SPENT`.
- ChatGPT Pro charge details, aggregate Month-1 spend, and remaining headroom:
  `UNKNOWN`.
- No new paid action is authorized.

`BUDGET_LEDGER.md` is the canonical aggregate budget record.

## Resume Protocol

1. Read `../AGENTS.md`, `WORKING_PROTOCOL.md`, this file, and
   `REGRESSION_GUARD.md`.
2. Verify current Git and live GitHub evidence; repository and GitHub evidence
   outrank conversational memory.
3. Inspect open material GitHub Issues and reconcile them with the durable
   authorities and the active local draft backlog.
4. Read `ROADMAP.md`, `DECISIONS.md`, `RISK_REGISTER.md`, and the documents
   governing the next authorized gate.
5. Stop and reconcile any conflict rather than guessing.

## Status Update Rule

Update this snapshot when a governed change materially changes the current
stage, item status, implementation authority, next technical gate, material
risks, budget facts, or resume point. Keep transient branch, open-PR, review-wait,
and comparison-URL state in GitHub rather than this file. Historical reasoning
and evidence belong in Git, `DECISIONS.md`, `RISK_REGISTER.md`,
`DEVELOPMENT.md`, and pull-request records.
