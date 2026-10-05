# Quant Hunter V0 resume

Date: 2026-10-05. Status: IN_PROGRESS; V0 is not delivered.

Owner reiterated: use only D: for all project writes, datasets, dependency
caches, temporary files, logs, private vaults and test/browser artifacts.
Set UV_CACHE_DIR/UV_PYTHON_INSTALL_DIR, TEMP/TMP and NPM_CONFIG_CACHE to their
documented D:\quant-hunter\.tools locations for every tool process. Existing
installed applications and the supplied original document may be read in place;
do not create project output on C: or move/delete unrelated user files.

Last saved executable checkpoint: `796771c81a7c49768ebe7040730c88707c98827b`,
verified on origin/version-0. Hosted run 37278264340 passed 1,460 tests per OS,
one platform-specific skip each; Ubuntu coverage was 92.09%. The earlier 9b74dd6 clean-clone launcher/browser proof
passed 20 checks. Work after 796771c must be reconciled separately; it is not
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
The next frozen checkpoint integrates macro/priority source parsers, private
provider configuration and file-import UI, ten sourced CRP methods plus two
comparison baselines, and reviewed publication, pattern and accounting cores.
The source process boundary covers DNS through body under a twenty-second parent
deadline. The first frozen full run passed 2,250 tests, one platform skip, one
existing warning and 93.07% coverage in 1,169.33 seconds. Independent review then
closed two corrections: generic PAPER references now validate in EXP/BACKLOG,
and lazy native-main imports leave room for actual TLS under the unchanged
256 MiB worker limit. The combined 175 focused corrections tests passed. Lock,
Ruff (212 files), strict mypy (157 files), TypeScript and build checks pass.
The corrected final regression passed2,288 tests, one platform skip, one
existing warning and93.07% coverage in998.05s. All131 source/config/schema/
frontend hashes matched after completion. The restored provider workflow passed
57 checks and Studies20, both with zero errors. This coherent checkpoint is
ready to commit/push; exact saved-commit hosted CI must still be verified.

An initial real G17 acquisition at 10:47:58 UTC failed because production main
imports exceeded the child memory limit before TLS. Its failure remains retained.
After the correction, a distinct restored web.main instance fetched six actual
G17 observations successfully in 1.745 seconds at 11:07:49 UTC. Raw SHA-256 is
cffccc27526bce9168f6dbeca2908b7c9a78805e3fe3abcbcd6018509143ae90. Source remains
CANDIDATE, quality PENDING, historical availability unverified; no scientific
admission or successful authenticated provider access is claimed.

Provider browser proof passed 57 checks with 32 screenshots and zero errors.
Studies browser proof passed 20 checks with 18 screenshots and zero errors,
including all twelve positive controls, three retained null failures and one
separately counted sensitivity variant. No browser provider request occurred.
All study results remain SYNTHETIC / EMPIRICALLY_UNVALIDATED. A distinct backup
restored all 436 files byte for byte and matched private database counts. The
original remains preserved. Dependencies lock 63 packages including SciPy
1.18.1, statsmodels 0.15.0 and pypdf 6.19.0.

Agent worktrees are under `.tools/v0-worktrees/{lifecycle,simulation,ui}`.
Root is the sole integrator. Publication owned API files are frozen but not yet
integrated; the durable paper engine awaits independent review. Paper-only
broker contracts are being implemented without credentials or actual orders.
Registered PatternLab product workflows, persistent corpus/search, paper UI and
scheduler, notification workflows, data/research admission and expanded recovery
remain required. Never overwrite isolated uncommitted work. No historical
research, sealed-data, host, production or live-order gate has been passed.

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


Next product preparation (not integrated or served):
`.tools/v0-drafts/publications-ui.ts` and `publication-smoke.mjs` contain the
private publication UI and browser draft. TypeScript/syntax checks pass; actual
workflow proof must follow API integration. Copy the frozen lifecycle agent's
publication_access.py/publication_routes.py/test_v0_publication_workflows.py,
wire PublicationService/Access through Runtime/create_app/main, recover only
under lease, add reciprocal shared2-active counting in DataAccess and exact
attachment-only6MB request allowance. Then integrate the UI route/typed view,
validate actual native PDF extraction, permissions and restored persistence.
No UI/API completion claim follows from these isolated drafts.

Paper engine85tests and peer review are closed in simulation worktree; broker
adapters/journal are still in progress. UI agent implements actual immutable
partitioned Pattern corpus/product, coordinating quality selected-partition
manifests with governance agent. Quality/research_validation modules remain
isolated. Root owns canonical identities, Item8/Item9 authority, authenticated
API/frontend integration and commits. Use the existing application SQLite file
for operational paper tables when compatible, preserving backup coverage.

Pattern integration contract: preparation must not require EXP, because Lab
allocates/freezes it internally. The isolated product now uses a root-supplied
FrozenPatternBinding after begin_run: actual EXP ID/revision, wrapped canonical
configuration digest, prepared digest and PATTERN ID. Root verifies the frozen
config references the prepared digest. Do not compare the wrapped Item8 config
digest directly to the prepared-manifest digest or create a second lifecycle.
Quality/Corpus integration supports a collective immutable partition-selection
manifest over up to1024 exact owned parents, streamed one bounded parent at a
time; retain all parents/reports, gaps/overlaps and actual row/byte counts.
Existing single upload/parser limits stay bounded; large corpus intake needs an
explicit multi-file/partition product flow, not only a synthetic benchmark.
