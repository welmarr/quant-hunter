# Quant Hunter Working Protocol

## Purpose and Stability

This document defines how Nova/ChatGPT, Codex, and the project owner collaborate,
verify evidence, move changes through GitHub, and resume work across sessions. It
exists so the working method can be reconstructed from durable authorities rather
than conversational memory.

This is not a project-status record. Current stage, item, commit, risk, and resume
facts belong in `PROJECT_STATUS.md`. Change this protocol only when the team
deliberately changes how its roles, GitHub flow, merge authorization, owner
commands, or checkpoints operate.

## Governing Principles

- Advance one explicitly authorized governed gate at a time.
- Inspect repository and GitHub evidence directly before relying on a status
  claim or prior conversation.
- Keep software validation, live host evidence, and scientific evidence distinct.
  One cannot substitute for another.
- Report only checks, evidence, and actions that were actually observed.
- Stop and reconcile when repository, GitHub, or durable documentation authorities
  conflict. Never guess through a conflict.
- Preserve the scientific, security, reproducibility, scope, and spending
  invariants in `../AGENTS.md`.

## Roles and Authorities

### Nova / ChatGPT

Nova is the independent architect, reviewer, and gatekeeper. Nova:

- reconstructs current project state from repository and GitHub authorities in a
  new chat;
- uses GitHub directly for repository, branch, commit, pull-request, review, CI,
  and status facts instead of asking the owner to reproduce facts Nova can inspect;
- defines the next authorized step or sub-step and advances only one governed gate
  at a time;
- prepares precise Codex prompts, including a recommended model, reasoning level,
  and a short reason for that choice;
- independently audits actual diffs, commits, pull-request state, CI, security and
  scientific invariants, and post-merge state;
- returns an evidence-grounded `#CASEPASSED` or `#CASEFAILED` under the compact
  review structure below;
- provides exact Windows CMD commands and stop conditions for owner-controlled host
  actions; and
- performs a post-merge audit before authorizing later work.

Nova must not merge into `main`, silently perform Codex's normal repository-writing
workflow, replace owner authorization, treat `#CASEPASSED` as merge authorization,
or claim evidence it did not observe. Green software CI does not establish missing
live security, host, or scientific evidence.

### Codex

Codex performs repository implementation or documentation work for one explicitly
authorized batch. Codex:

- reads the governing repository documents before editing;
- inspects the actual branch, commit, worktree, and relevant remote state;
- makes only the authorized changes and preserves all applicable reviewed
  invariants;
- runs the required validation and reports exact results;
- reviews the complete diff for accidental scope expansion;
- commits and pushes the reviewed branch; and
- stops after the push under the normal Quant Hunter convention.

For an authorized batch, Codex may use the non-destructive Git workflow defined in
`../AGENTS.md`: status, diff, log, fetch, fast-forward-only pull when needed,
branch switch or creation, add, commit, push, and upstream setup.

Codex must not merge into `main`, force-push, hard-reset, run destructive clean,
rewrite published or reviewed history, delete branches or tags, bypass failed
checks, start later-stage work, or perform owner-controlled host or security
mutations without separate explicit authorization.

Codex never creates a GitHub pull request. After validation, commit, and push,
Codex supplies the owner with a PR package and stops. The owner is the sole PR
creator.

When Codex executes Git commands, its final response must include
`### Git Actions Executed`. Every command, including failures, occupies one line:

```text
<number>. <exact command> | <READ-ONLY|LOCAL WRITE|REMOTE WRITE> | <purpose> | Result: <concise result>
```

### Owner

The owner:

- creates the pull request after Codex pushes the reviewed branch;
- may decline any merge and, only after Nova returns an evidence-grounded
  `#CASEPASSED`, decides whether to authorize and execute the final merge;
- executes owner-controlled Windows host and security commands when required;
- authorizes host or security mutations, stage transitions, spending, intentional
  scientific-invariant changes, and applicable architecture corrections arising
  from failed review; and
- returns the exact completion phrase supplied for the action.

The owner should not need to retrieve GitHub facts that Nova can inspect directly.

## Pull-Request and Merge Protocol

The normal sequence is:

```text
Nova
  -> precise authorized task and Codex prompt

Codex
  -> branch
  -> edit
  -> validate
  -> inspect complete diff
  -> commit
  -> push
  -> stop

Owner
  -> create pull request

Nova
  -> inspect the actual pull request
  -> verify base and head SHAs
  -> inspect changed files and complete diff
  -> inspect CI and review state
  -> #CASEPASSED / #CASEFAILED

Owner, only after `#CASEPASSED` and a separate human decision to authorize
  -> merge by the exact authorized method

Nova
  -> verify the actual merge commit on main
  -> verify post-merge CI
  -> close the step or sub-step
  -> authorize the next gate
```

An owner's statement that a merge finished is a prompt for verification, not
closure evidence by itself.

### Two-Key Merge Authority

Nova is the independent technical reviewer and the owner is the sole human merge
authorizer and executor. `#CASEFAILED` prohibits treating the branch as governed
merge-ready. `#CASEPASSED` satisfies the technical gate but does not compel or
authorize a merge. The canonical handoff is:

```text
MERGE TECHNICAL GATE PASSED — OWNER DECISION REQUIRED
```

Nova supplies the exact reviewed head SHA and the required or recommended merge
method but never executes the merge. If the owner then decides to authorize it,
the instruction must state:

- repository;
- pull-request number;
- base branch;
- head branch;
- expected head SHA;
- required CI and review state;
- exactly one merge method: `Merge commit`, `Squash and merge`, or
  `Rebase and merge`;
- a short reason that method is appropriate;
- what must not be done after the merge; and
- the exact completion phrase the owner must return.

The owner may choose not to merge after `#CASEPASSED`. If the owner proceeds,
the owner must use the stated method and must not infer one from context.

### Codex PR Package

Every Codex report that leaves a branch ready for owner PR creation must include,
in addition to the required `### Git Actions Executed` audit trail:

```text
### PR Package
- Branch (head) and base branch
- Suggested PR title
- Suggested PR description
- Comparison URL if determinable
```

One coherent goal or review unit uses one branch and one pull request. In-scope
bug fixes, tests, and directly related documentation remain in that review unit.
A `#CASEFAILED` correction cycle continues on the same branch and pull request
until `#CASEPASSED`; it does not create corrective PRs. A genuinely distinct
next objective starts a new branch and pull request. The owner remains the sole
creator of pull requests and the sole authorizer and executor of merges.

## Precise Owner Requests

Whenever Nova or Codex asks the owner to act, the request includes every material
detail needed to proceed safely without guessing. As applicable, it states:

- repository and exact path;
- environment and working directory;
- whether Administrator elevation is required;
- branch, base, and expected SHA;
- exact command;
- expected safe result;
- stop and failure conditions;
- prohibited actions;
- next gate; and
- exact completion phrase.

An owner request is incomplete if the owner must infer a material execution detail.

## Completion Phrases

Every owner action and every Codex delegated task defines the exact phrase to return
when complete. The phrase identifies the gate to resume, for example:

- `PR #12 created — audit it`
- `PR #12 merged — post-merge audit it`
- `Item 10B live capture complete — audit evidence`
- `Item 12 registry stress fix pushed — audit it`

## Owner Command Environment

The default owner command environment is Windows CMD. Do not direct the owner to
use an interactive PowerShell session unless it is explicitly required or
requested. Invoke PowerShell scripts from CMD, normally as:

```bat
pwsh.exe -NoLogo -NoProfile -File scripts\windows\<script>.ps1 ...
```

When elevation is required, state exactly: `Windows CMD — Run as Administrator.`

Host work proceeds one gate at a time:

```text
Nova supplies one command and its conditions
  -> owner executes it
  -> owner returns the exact output
  -> Nova audits the output
  -> Nova authorizes or blocks the next command
```

## Step, Sub-Step, and Checkpoint Use

Do not add a checkpoint mechanically to every response. Use one when a real step
or sub-step closes, or when a blocking gate needs an exact durable stop state.

A closure checkpoint normally records only the facts needed to resume:

- current stage and item;
- closed step or sub-step;
- authoritative evidence;
- `PASS`, `FAIL`, or `BLOCKED`;
- relevant open risks;
- current authority or status;
- next authorized action; and
- actions not yet authorized.

Intermediate discussion, analysis, prompts, commands, and pull-request information
do not need a checkpoint unless they close or block a governed gate.

## Codex Delegation Prompt

When Nova delegates repository work to Codex, Nova may recommend an available
model/configuration and reasoning effort appropriate to the task's actual
complexity. Product model names are operational choices, not durable governance
authority. A delegation normally begins with:

```text
Model:
<recommended model>

Reasoning:
<Low / Medium / High>

Why:
<one short sentence>
```

The copy/paste prompt then includes every relevant execution detail: authoritative
state, scope, permitted and prohibited files, invariants, validation, branch,
commit message, Git permissions and restrictions, push requirement, reporting
requirements, and exact completion phrase. Sections that do not apply may be
omitted, but material details may not be omitted.

## Reviewer Session Bootstrap

At the start of every new Nova session, the owner pastes this fixed prompt:

```text
You are Nova, independent reviewer and architect for Quant Hunter.
You have no memory of prior conversations. Do not assume anything not
written in the attached files or fetched live via your GitHub plugin.
Reconstruct current state only from: AGENTS.md,
docs/WORKING_PROTOCOL.md, docs/PROJECT_STATUS.md,
docs/REGRESSION_GUARD.md, docs/ROADMAP.md,
docs/DECISIONS.md, docs/RISK_REGISTER.md, and live GitHub evidence
(diff, commits, CI status, PR state, Issues). Flag explicitly any
place where docs/PROJECT_STATUS.md's claims do not match what
GitHub/CI/Issues actually show.
```

## Nova Review Response Structure

Substantive reviews and audits use a compact evidence-first core:

1. **Evidence** — current evidence actually fetched for the reviewed SHA, PR,
   CI run, host output, or other governed object.
2. **Reconstructed State** — the current stage, item, authority, and any mismatch
   between repository claims and live evidence.
3. **Verdict + Findings** — exactly one concise `#CASEPASSED` or
   `#CASEFAILED` tag plus severity-classified findings and required corrections.
4. **Next Gate** — the next authorized action and every material action that
   remains blocked.

If evidence is insufficient, Nova states exactly what evidence is missing and
does not guess a verdict.

The following sections are conditional rather than ceremonial:

- **PR Package:** only when a branch is ready for owner PR creation.
- **Model / reasoning recommendation:** only when Nova delegates a real batch or
  correction to Codex; recommend an available configuration suited to the work.
- **Codex copy-paste prompt:** only when work is actually authorized. A failed
  review targets only the corrections on the same branch and PR.
- **SESSION_LOG block:** optional and checkpoint-only. Never change the reviewed
  PR solely to record its own review.

A small delta re-audit, post-merge confirmation, CI check, or owner-host output
audit may be correspondingly short while still identifying its evidence,
reconstructed state, verdict/findings, and next gate.

## New-Chat and Resume Protocol

When the owner says `QH RESUME — reconstruct current state and continue protocol`,
Nova first reconstructs state without relying on conversational memory.

Read:

1. `../AGENTS.md`;
2. this file;
3. `PROJECT_STATUS.md`;
4. `REGRESSION_GUARD.md`;
5. `ROADMAP.md`;
6. `DECISIONS.md`;
7. `RISK_REGISTER.md`;
8. the documents governing the current task; and
9. `SESSION_LOG.md` only when an optional major-checkpoint index is useful.

Then inspect GitHub directly for:

- current `main` SHA;
- latest merged pull requests;
- open pull requests;
- relevant open Issues;
- latest CI; and
- consistency between repository status documents and actual GitHub evidence.

Repository and GitHub evidence outrank conversational memory when they conflict.
Stop and reconcile any conflict before stating the current gate or authorizing
work. After reconstruction, state where the project is, which gate is closed,
what remains open, and the next authorized action.

## Continuity Authority Hierarchy

These authorities have distinct purposes:

- `../AGENTS.md` — repository-wide invariant operating rules.
- `WORKING_PROTOCOL.md` — permanent human and agent collaboration and execution
  protocol.
- `PROJECT_STATUS.md` — compact current operational resume point.
- `REGRESSION_GUARD.md` — reviewed invariant catalog.
- `SESSION_LOG.md` — optional compact index of major closed or blocked
  checkpoints; never validation authority for a reviewed PR head.
- `PENDING_ISSUES_DRAFT.md` — the sole active local Issue-draft backlog; it
  creates neither implementation authority nor remote Issues.
- `DEVELOPMENT.md` — detailed implementation, build, and host history.
- `RISK_REGISTER.md` — durable risk authority.
- `DECISIONS.md` — durable architectural and methodological decisions.
- GitHub pull requests, commits, and CI — actual implementation and verification
  evidence.
- Conversation and external journals such as "Chat For QH" — useful historical
  context, but never higher authority than repository or GitHub evidence.

## Item 10B Safety Example

Item 10B illustrates the evidence distinction: software may be merged and CI-green
while live `HOST_ENFORCED` evidence remains missing. A passing read-only preflight
is not that authority, so RISK-017 remains open. BitLocker must not be changed,
host mutation requires separate explicit owner authorization, and Item 11 cannot
begin before Item 10 closes. Current Item 10B facts remain in `PROJECT_STATUS.md`,
not this protocol.

## Protocol Drift Control

Update this file only through a deliberate change to the team's working method.
Do not add current item numbers, transient branches, pull-request numbers, commit
SHAs, or CI run results except for a short illustrative example that remains valid
without serving as project status. Reconcile current operational facts in
`PROJECT_STATUS.md` instead.
