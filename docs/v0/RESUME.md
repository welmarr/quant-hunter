# Quant Hunter V0 resume

Date: 2026-10-05. Status: IN_PROGRESS; V0 is not delivered.

Last saved executable checkpoint: `5da83fd97637624c54022affd06bfd8bfc839054`,
verified on origin/version-0. Hosted run 37272040597 passed 1,193 tests per OS;
Ubuntu coverage was 91.58%. The earlier 9b74dd6 clean-clone launcher/browser proof
passed 20 checks. Work after 5da83fd must be reconciled separately; it is not
covered by that CI.

Working and integration branch: `version-0` (tracking `origin/version-0`).
Immutable saved branch: `work-before-v0`, locally/remotely verified at
`7346cf4f79ca5897777c0118f8cf4c2292be929e`. Leave it and main unchanged.
Never force-push, delete user work or rewrite history.

Read MISSION.md, REQUIREMENTS.md, DECISIONS.md and the canonical repository
authorities. Reconcile Git and open Issues/PRs. Host evidence and the Stage 1
gate remain open; the synthetic application does not change that authority.

The first executable slice implements local authentication/roles, a loopback
web UI, a single worker with persistent jobs and safe interruption handling,
Decimal equity/FX demonstrations, and real Item 8 preregistration/freeze/attempt/
result evidence. The actual source snapshot is immutable, including dirty code.
Six UI views are functional. The real browser verified the accounting oracle,
authorization boundaries, errors and responsive layouts. See TEST_REPORT.md for
the corrected full-gate status and honest failures, and QUICKSTART.md to launch.

The saved 5da83fd checkpoint adds private immutable CSV/Parquet import, the
22-source catalogue and bounded BLS/ECB probes, Sources/Data UI, quotas and
versioned private backup/restore. It passed 1,193 tests, zero skips, one warning,
91.62% coverage, lock/Ruff/mypy/TypeScript/build checks, and 32 browser assertions
on a separately restored instance. Recovery compared all 265 files byte for
byte. See TEST_REPORT.md and OPERATIONS.md. Reconcile HEAD and origin before
assuming this implementation is saved or covered by hosted CI.

Current Phase C work integrates fixed-host SEC/Alpaca read-only clients,
authenticated encrypted credentials with owner-only UI, canonical instrument
identities, metadata history, XNYS/named-FX calendars and bounded aggregation.
These are software capabilities, not verified provider access or historical
market facts. The corrected full gate passed 1,460 tests, one Linux-only skip,
one warning and 92.33% coverage. A distinct restored instance passed 48 browser
checks plus five delayed-response isolation assertions, after independently
comparing 245 files and both instrument revisions. Exact evidence and initial
failures are retained in TEST_REPORT.md. Reconcile the next saved commit/CI.
Priority macro/other-source clients and ten sourced research math modules remain
isolated under review and are not included in this checkpoint. Agent worktrees are under
`.tools/v0-worktrees/{lifecycle,simulation,ui}`. Root is the sole integrator.
Do not overwrite those uncommitted files or claim they are integrated without
copy/review/testing. Continuous paper execution, ten CRPs, fifteen PatternLab
families, notifications, portfolio/meta-model workflows and expanded recovery
for these future modules are still required. No historical research is validated.

Use the ignored `.local/v0` for owner runtime and `.tools` for caches/temporary
files on D:. `.local/v0-browser` is a separate test instance; private test login
state lives in `.local/v0-browser-private`. Do not commit either. Browser proof
artifacts are in `.local/v0-proof` and `.local/v0-proof-final`.

Do not perform large Docker builds while C: storage/VHD placement remains
unsuitable/unverified. The normal process sandbox launcher fails with an ACL
setup error; reviewed command-local escalation has run authorized commands
without changing host ACL/security settings. No new spending occurred.

Each coherent capability must be tested, documented, committed and pushed on
version-0. Remaining requirements cannot be relabeled complete. Continue the
mission; this checkpoint is not a stop-after-batch instruction.
