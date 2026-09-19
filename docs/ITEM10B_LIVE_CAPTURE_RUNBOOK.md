# Item 10B Owner Live Capture and Independent Review Runbook

## Authority and current state

This runbook prepares the owner-controlled Windows evidence gate for Item 10B.
It does not authorize execution by itself. The current state remains `TOOLING
MERGED / LIVE HOST EVIDENCE BLOCKED`; RISK-017 remains `OPEN`; and no
`HOST_ENFORCED` authority exists until a real governed capture succeeds and its
canonical evidence passes independent review.

Use only an independently reviewed implementation commit that has been merged
to `main`. Never use an unmerged correction or governance branch as live host
authority. The workflow uses synthetic fixtures only. It must not access real
market or OOS data, persist authentication material, or modify BitLocker.

## Owner Windows live capture packet

Run from **Windows CMD — Run as Administrator**. Stop before setup if any
precondition or read-only preflight check fails.

```bat
cd /d D:\quant-hunter
set "QH_OOS_ROOT=D:\QuantHunterOOS"
git status --short --branch
git rev-parse HEAD
pwsh.exe -NoLogo -NoProfile -NonInteractive -File scripts\windows\item10b_preflight.ps1 -RepositoryRoot "%CD%" -CandidateRoot "%QH_OOS_ROOT%"
```

Before continuing, confirm all of the following:

- the checkout is clean, on `main`, and at the exact independently reviewed and
  merged implementation SHA;
- the preflight reports `Pass: true`, an elevated administrator, fixed local
  NTFS, BitLocker `On` and `FullyEncrypted`, no worktree/profile/cache/temp/sync
  overlap, absent governed identities, and an absent candidate root;
- the original File System audit-policy observation and backup observation are
  present;
- no prerequisite was bypassed and no BitLocker command was run.

Only then run the single governed capture command:

```bat
uv run --locked python scripts\windows\item10b_finalize.py --repository-root "%CD%" --candidate-root "%QH_OOS_ROOT%" --canonical-evidence "%QH_OOS_ROOT%\host-evidence\evidence-000001.json" --authorize-setup
```

A zero exit code and printed digest are necessary but not sufficient for Item
10B completion. Preserve the exact implementation SHA, console result, evidence
path, and printed digest for the independent reviewer. Do not rerun over an
existing candidate root or canonical evidence file.

### Immediate read-only evidence check

After a successful capture, this command reloads the evidence through the typed
v2 verifier and prints its canonical digest without creating release authority:

```bat
uv run --locked python -c "from pathlib import Path; from quant_hunter.isolation import WindowsHostBoundaryProfile, WindowsHostBoundaryVerifier; r=Path(r'D:\QuantHunterOOS'); e=r/'host-evidence'/'evidence-000001.json'; print(WindowsHostBoundaryVerifier(WindowsHostBoundaryProfile(r/'vault',r/'releases',r/'host-evidence'),Path(r'D:\quant-hunter\schemas\v2')).load(e).digest)"
```

The reloaded digest must exactly equal the digest printed by the capture.
Loading evidence does not constitute independent approval.

## Stop conditions

Stop with no `HOST_ENFORCED` authority if any of these occurs:

- the process is not elevated or the owner did not authorize the host mutation;
- the checkout is dirty, not `main`, or not the reviewed merged SHA;
- preflight fails or reports an unknown/unsafe filesystem, encryption, path,
  identity, worktree, sync, audit, or backup state;
- the candidate root or governed identities already exist;
- setup, verification, schema validation, digest validation, canonical
  publication, or typed reload fails;
- exact SIDs, object classification, event outcome, or event window cannot be
  proved;
- real/private data, credentials, or a BitLocker mutation would be involved.

Do not retry by weakening a gate or by manually reproducing only part of the
workflow.

## Emergency rollback packet

The capture boundary invokes the governed rollback automatically after any
post-setup validation or publication failure. If the process is interrupted
after mutation begins, or automatic rollback reports failure, inspect only the
exact governed state location. If this exact file exists:

`D:\QuantHunterOOS\host-evidence\item10b-created-state.json`

run, from **Windows CMD — Run as Administrator**:

```bat
cd /d D:\quant-hunter
pwsh.exe -NoLogo -NoProfile -NonInteractive -File scripts\windows\item10b_rollback.ps1 -StatePath "D:\QuantHunterOOS\host-evidence\item10b-created-state.json" -Apply -Confirm:$false
```

The rollback is marker-, path-, name-, and retained-SID-bound. Never substitute
another state file, root, script, or manual deletion sequence. After rollback,
verify read-only that:

- `qh-oos-custodian` and `qh-research` are absent if the state says this batch
  created them;
- `D:\QuantHunterOOS` is absent if the state says this batch created it;
- File System audit policy matches the recorded original state;
- no canonical evidence exists and no `HOST_ENFORCED` ledger event was written;
- BitLocker remains unchanged.

Preserve the bounded `ITEM10B_CAPTURE_FAILED` diagnostic and rollback outcome.
Do not expose raw stderr, secrets, absolute private paths, or authentication
material in review records.

## Nova live evidence audit packet

Label the packet exactly:

`PENDING INDEPENDENT NOVA REVIEW`

Supply these facts and artifacts without self-approval:

- implementation `main` SHA and proof that it was independently reviewed and
  merged;
- governance PR/merge state, noting that governance documentation does not
  create host authority;
- canonical evidence path, the capture-printed digest, and the independently
  reloaded digest;
- host profile, repository, launcher, and schema-v2 bindings;
- complete preflight result: elevation, filesystem, fixed-local-volume status,
  BitLocker protection/encryption state, worktree/profile/cache/temp exclusions,
  sync result, original audit policy, and backup observation/status;
- exact custodian and research SIDs and proof both accounts are unprivileged;
- DACL allow-list and inheritance evidence for vault and release roots;
- SACL evidence and final File System audit-policy state;
- normalized 4656 `FAILURE` evidence for the exact research SID and governed
  sealed target;
- normalized 4663 `SUCCESS` evidence for the exact custodian SID and governed
  released target;
- verification window and proof both selected events occurred inside it;
- effective research denials, custodian successes, and released-artifact
  research read-only/immutability results;
- index exclusion, synthetic-only status, no persisted authentication material,
  and post-verification identity-disabled status;
- rollback state and result if any failure occurred;
- limitations and residual risks, including administrators/SYSTEM, backup
  equivalence, and RISK-017.

The reviewer must reject raw caller-authored mappings, arbitrary JSON, a
different schema/repository/profile, display-name-only identity evidence,
events outside the window, wrong success/failure semantics, or evidence created
before all checks completed.

## Item 10B closure checklist

Apply a closure change only after every box is supported by retained evidence:

- [ ] all Item 10B corrections are independently reviewed, merged to `main`,
      and covered by green applicable CI;
- [ ] owner-controlled governed live capture succeeded on the exact merged SHA;
- [ ] canonical v2 evidence exists at the governed path and its digest reloads;
- [ ] every live success requirement in this runbook is satisfied;
- [ ] Nova independently passed the complete live evidence packet;
- [ ] residual risks and limitations are explicitly reconciled;
- [ ] RISK-017 is closed, reduced, or transformed only as justified by actual
      evidence;
- [ ] `docs/PROJECT_STATUS.md`, `docs/REGRESSION_GUARD.md`,
      `docs/RISK_REGISTER.md`, `docs/DEVELOPMENT.md`, and `docs/ROADMAP.md` are
      updated together;
- [ ] any genuinely new durable decision is recorded in `docs/DECISIONS.md`;
- [ ] the closure change itself passes independent review and applicable CI.

Until then, Item 10B is **not complete**.

## Item 10 closure checklist

- [ ] Item 10A remains independently verified `COMPLETE`;
- [ ] Item 10B satisfies every closure criterion above and is independently
      verified `COMPLETE`;
- [ ] the combined Item 10 invariant review and full regression pass;
- [ ] current status, roadmap, regression, risk, and development authorities
      agree on the closure evidence;
- [ ] the owner authorizes the resulting stage progression.

Only then may Item 10 become `COMPLETE`. Item 11, Item 12, Item 13, the Stage 1
tracer, and Stage 2 remain outside this runbook and require their own gates and
authorization.
