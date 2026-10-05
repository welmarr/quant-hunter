# V0 test evidence

2026-10-05: V0 remains IN_PROGRESS. This report records successive executable
checkpoints; it does not certify the full mission or the host boundary.

Environment: Windows, CPython 3.14.7, uv 0.12.10, Node 25.8.0, TypeScript 5.9.3,
Playwright 1.63.0 using installed Chrome 154.0.8037.97. The tested source parent
is `c43d7c763177f62bf52cb8ef4ff81c01aa0c570a` plus the source changes in this
checkpoint. Every application run preserves exact source bytes as a base64
immutable snapshot; the Git parent is never represented as the entire dirty code.

## Executed checks and retained failures

- Initial 842 existing tests passed, but the coverage gate failed at 88.02% because
  newly added application files entered measurement during that initial run.
  This is not recorded as a successful baseline coverage gate.
- The standalone Decimal simulation passed 39 tests at 100% branch coverage.
- Initial combined new tests exposed four failures: the source snapshot used
  raw strings containing `${...}`, rejected by canonical configuration rules.
  Exact base64 bytes corrected the representation; no validation was weakened.
- A subsequent integration run passed 919 tests, one deprecation warning,
  90.25% combined statement/branch coverage in 401.35 seconds. This predates
  the final peer-review corrections and is not the final checkpoint gate.
- Peer review found missing source-snapshot verification and missing semantic
  cross-bindings among otherwise correctly hashed graph objects. Both were
  fixed. Corrective lifecycle tests: 53 passed in 84.44 seconds, 91.88% coverage,
  with Ruff formatting/lint and strict mypy passing. Hostile tests rehash
  schema-valid objects so they exercise contradictions, not merely corrupt hashes.
- Review also corrected failed-worker admission, shutdown ordering, exception-safe
  lifespan cleanup, and the binding to the actually imported repository source.
  Final corrected full regression: **950 passed, zero skipped, one warning,
  90.74% combined statement/branch coverage, 417.58 seconds**. The Python source
  was held unchanged throughout this final run.
- The real Chrome E2E passed 19 assertions, including the USD 10,008 equity
  oracle, FX calculation, Item 8 EVALUATED evidence, cookie/CSRF checks, owner
  creation of users, researcher isolation, reader rejection, offline recovery,
  invalid login, terminal polling stop, and layouts at 1440/768/390/320 pixels.
  Earlier harness syntax/status assumptions and a real mobile overflow failure
  were corrected. The failure capture is retained. A final run against the
  corrected backend also passed all 19 assertions, with separate artifacts in
  `.local/v0-proof-final` and no uncaught JavaScript errors.
- Lockfile, Ruff, strict mypy and wheel/sdist build passed before the final
  corrections and again on the corrected source. Package inspection found all three static assets and no local
  runtime, venv, node_modules or cache content. Both PowerShell scripts parsed.
  Locked `npm ci --ignore-scripts`, `npm run typecheck` and `npm run build` also
  passed. Clean-clone startup passed as recorded below. Restoration was executed
  subsequently in the Phase B checkpoint below.

The remaining Starlette warning concerns its deprecated httpx TestClient path;
it is reported rather than suppressed. No skipped test is presented as passed.

## Reproduction and local evidence

Set `UV_CACHE_DIR=D:\quant-hunter\.tools\uv-cache`,
`UV_PYTHON_INSTALL_DIR=D:\quant-hunter\.tools\python`, and
`TEMP`/`TMP=D:\quant-hunter\.tools\v0-tmp` for these commands:

```powershell
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy src tests
uv run --locked pytest --cov=quant_hunter --cov-branch --cov-fail-under=90 --basetemp=.tools/v0-final-tests --junitxml=.local/v0-proof/pytest-final.xml
uv build --no-sources
```

Browser reproduction is documented in `frontend/README.md`. Ignored local
artifacts are under `D:\quant-hunter\.local\v0-proof` and `v0-proof-final`:
actual PNG captures, browser-proof.json (timestamps, hashes, role scenarios and
experiment IDs), pytest text/XML, and server logs. Test credentials are held in
the separate ignored `v0-browser-private` directory. None belongs in Git.

Independent arithmetic oracles: 10 units bought at 100 and sold at 101, with
commission 1 each way, gives cash 10,008; doubling commission gives 10,006.
Separate bid/ask spread gives 10,004; separate adverse slippage gives 10,005.99.
These are synthetic software tests, not historical evidence of profitability.

## Saved checkpoint, hosted CI and clean start

The first working slice was committed and pushed as
`9b74dd674077a824e35d2265111c7e6f946593f6` on `origin/version-0`. Remote
`work-before-v0` remains `7346cf4f79ca5897777c0118f8cf4c2292be929e`; remote main
remains `e0ba326540b4493f122e384ac7e7d4bcd0ebf6e2`.
[Quality #53](https://github.com/welmarr/quant-hunter/actions/runs/37268298076)
passed on that exact commit: Ubuntu 950 tests, one warning, 90.69% coverage in
170.34 seconds; Windows 950 tests, one warning in 256.39 seconds. No skips.

A separate shallow clone from origin was created at
`D:\quant-hunter\.tools\v0-cold-start`. Its unmodified documented launcher ran
with a fresh runtime on D: and port 8766, installing the locked environment.
Chrome then passed 20 checks including fresh owner creation, first equity/FX
backtests, role isolation, offline recovery and mobile/tablet layouts. Fetched
JavaScript bytes were compared with the clone's committed static artifact.
Proof: `.local/v0-cold-proof/browser-proof.json` and its actual captures;
private test credentials: `.local/v0-cold-private`. The temporary test server
was closed after completion. Clone and test evidence were retained.

## Cross-item review

The simulation agent reviewed the lifecycle and root application; the root
reviewed the engine and frontend integration. This is agent cross-review,
not professional independent certification. Applicable REG-001–011 and
REG-013–020 were inspected for immutable data/registry history, frozen identities,
temporal availability, exact execution sides, retained failures, counted AI
variants, and no sealed-host authority. Item 8 remains sole lifecycle authority;
SQLite carries only operational jobs and user sessions. Demonstrations remain
INCONCLUSIVE. No core invariant or schema was changed. CI and the historical
independent-review/host gates retain their own status.

Sandbox process startup failed with `helper_unknown_error: apply deny-read ACLs`.
Read-only commands and explicitly authorized branch operations succeeded through
the reviewed sandbox override. No host ACL or security setting was changed.

## Phase B: imports, public diagnostics and private recovery

Source parent: `9b74dd674077a824e35d2265111c7e6f946593f6` plus this checkpoint's
uncommitted implementation. Exact source snapshots are retained with application
runs. No SEC/Alpaca/credential/calendar agent work is included in this gate.

- The frozen full regression passed **1,193 tests, zero skips, one warning,
  91.62% combined statement/branch coverage in 508.39 seconds**. Lock validation,
  Ruff formatting (122 files), lint and strict mypy (80 files) passed. Python
  production/test sources were unchanged during the final run. The existing
  Starlette TestClient deprecation warning remains reported.
- Import tests: 82 passed, 93.32% targeted coverage. Hostile native Parquet
  metadata/page preflight, decompression bounds, timestamp offsets, decimal
  precision, duplicate rows, immutable corrections and graph contradictions
  are checked. A Windows Arrow timezone-database failure was corrected by
  converting epoch microseconds explicitly; no time or validity check was relaxed.
- Source tests: 88 passed, 95.19% targeted coverage. Corrected checks include
  ECB unit multipliers, safe failure retention and exact source/environment
  binding. One real BLS request returned 12 observations and one real ECB request
  returned four. The UI subsequently performed one explicit ECB diagnostic.
  These are bounded acquisition proofs with PENDING quality and unknown
  historical publication/revision timing. Raw hashes are in SOURCES.md; raw
  data remain in ignored local stores. No credential or purchase was used.
- Eight DataAccess tests exercise persistent quotas, atomic operation admission,
  ownership, pagination and disk-budget refusal. API tests exercise strict input
  validation, roles, private data, source errors and absence of secret echoing.
- Independent backup tests: 65 passed, 97.64% targeted coverage. Cross-review
  corrected a restore lease race, a missing extraction hash recheck, and a forged
  central-directory entry count. A coverage run made while code was still
  changing was discarded; the frozen rerun passed. Tests cover traversal,
  symlinks, encrypted/compressed/oversized ZIPs, disk limits, interrupted restore,
  active runtimes, SQLite integrity, overwrite refusal and actual CLI execution.
- A real stopped-runtime backup restored to a distinct path. Independent hash
  comparison found **265 identical files**. Original/restored database counts
  matched: 9 users, 16 jobs, 5 data operations, 3 owned datasets. Archive SHA-256:
  `715741336163102404a3009d69e68fabcd4988fb886ca3912c7f6eda907f3697`.
  Private archive: `.local/v0-backups/phase-b.qhbackup`; comparison proof:
  `.local/v0-phase-b-proof/restoration-proof.json`. The source runtime was retained.
- Initial Phase B browser verification passed 31 checks, including valid CSV and
  Parquet, invalid timestamp rejection, correction IDs, raw hashes, source probe,
  account isolation and responsive layouts. After restoration, the harness
  initially timed out waiting for an unnecessary GET on an unchanged Data route.
  That test-only defect was corrected, and its failure evidence was retained.
  The final restored-instance run passed **32 assertions, zero uncaught errors
  or dialogs**, with 20 screenshots in Chrome 154.0.8037.97 (06:09:21–06:10:04 UTC).
  It also verified literal rendering of hostile imported markup, no injected
  image or JavaScript effect, dataset pagination metadata, synthetic EQ/FX
  accounting, role boundaries, offline recovery and 320/390/768 pixel layouts.
  No external source request ran in this final restored-instance verification.
- `npm run typecheck` and `npm run build` passed after the final frontend change.
  Wheel/source archive build and membership inspection are recorded with this
  checkpoint; the build's warning about a cache inside the source tree does not
  imply that caches entered an artifact. No private runtime or dependency cache
  is accepted in a distribution.

Reproduction uses the earlier environment variables, then:

```powershell
uv run --locked pytest --cov=quant_hunter --cov-branch --cov-fail-under=90 --basetemp=.tools/v0-phase-b-full --junitxml=.local/v0-phase-b-proof/full.xml
```

Full text/XML are in `.local/v0-phase-b-proof/full.txt` and `full.xml`.
Restored browser evidence is `.local/v0-restored-proof/final/browser-proof.json`
with actual captures and `gallery-metadata.json`; prior harness failure artifacts
remain in the parent directory. Browser use and private credential handling are
documented in `frontend/README.md`; recovery commands are in OPERATIONS.md.

Applicable prior invariants were re-reviewed across the import/raw/derived
graph, operational SQLite migrations, source timing and runtime recovery.
Registry/source data history remains immutable; imported declarations cannot
become scientific approval, backtest input or host authority. The root reviewed
the imports and source clients; another agent independently authored/reviewed
the hostile backup tests and another executed the restored browser flow. This
is cross-agent review, not professional independent certification. The saved
Phase B commit `5da83fd97637624c54022affd06bfd8bfc839054` subsequently passed
[hosted run 37272040597](https://github.com/welmarr/quant-hunter/actions/runs/37272040597):
Windows 1,193 passed in 285.89 seconds; Ubuntu 1,193 passed in 205.79 seconds,
91.58% coverage. Each retained one existing warning and no skips. This evidence
applies to that exact commit, not subsequent work.

## Private source configuration and market metadata checkpoint

Source parent: `5da83fd97637624c54022affd06bfd8bfc839054` plus the Phase C
implementation. Exact dirty source snapshots are retained by the application.
Macro/priority source adapters and research-method agent drafts are excluded.

The integrated scope adds the authenticated private credential vault, fixed-host
SEC/Alpaca read-only clients, owner configuration and explicit probe routes,
canonical INSTRUMENT registry records, metadata history, market-calendar API,
Markets UI and bounded minute aggregation. No actual SEC/Alpaca request or
provider credential was used. Market reference data are shared explicitly among
local accounts; owners alone may append metadata. Historical declarations,
calendar rule snapshots and fixture arithmetic are not empirical validation.

Targeted verification and corrections:

- Credential tests used actual Windows DPAPI, concurrent processes, interrupted
  rotation, authenticated identity/tamper checks, serialized revoke/use and a
  separate private-copy recovery. The isolated result was 46 passed and one
  Linux-only permission test skipped on Windows, 93.84% targeted coverage.
- SEC/Alpaca tests passed 99 cases after independent review added decimal
  magnitude/exponent bounds and escaped/URL-encoded secret-reflection checks.
  Fixed public DNS/TLS hosts, request/header bounds, pagination and safe failures
  are tested without authenticated provider access.
- An initial integrated targeted run had two failures because assertions used
  `StoredObject.size` instead of `byte_size`; these test errors were corrected.
  The corrected instrument/connection integration run passed 23 tests. Later
  instrument API additions passed nine tests. Cross-review identified mutable
  base/quote currency as an identity error; the fix and regression then passed
  100 combined market/instrument tests. Stale CAS, full-history semantic replay,
  historical selection, owner roles and calendar early closes are covered.
- The first private-configuration browser run passed 41 checks, zero uncaught
  errors/dialogs, 23 screenshots. A separate test delayed an actual owner API
  response across reader login and passed five account-isolation assertions.
  Synthetic credentials were saved, rotated and revoked; no provider was called.
  Evidence is `.local/v0-connections-proof/browser/`.
- Markets browser verification first found the route missing from the hash
  allowlist. The production fix preserves the new view, and failure artifacts
  remain under `.local/v0-phase-c-proof/browser/`. The final rerun passed
  **48 checks, 26 screenshots, zero JavaScript errors**, Chrome 154.0.8037.97,
  07:07:45.516–07:08:45.030 UTC. It exercised the real app's EQ/FX calculations,
  private configuration, imports/hostile markup, instrument create/correction,
  stale-write 409, as-of snapshots, NYSE early close, FX weekend/DST and roles.
  Evidence: `.local/v0-phase-c-proof/browser/final/browser-proof.json` and
  `gallery-metadata.json`, including source/screenshot hashes. No provider called.
- Lock check, Ruff formatting/lint and strict mypy passed (147 formatted files,
  100 checked source files). TypeScript and the PowerShell launcher syntax passed.
  The first complete run reported **2 failed, 1,453 passed, one platform skip,
  one warning, 92.31% coverage in 634.68 seconds**. A real competing-process race
  removed SQLite's optional DELETE journal during permission inspection. The fix
  allows a genuinely absent optional sidecar while rejecting existing unsafe
  paths, links and permission failures; mandatory database/key checks remain.
  Three deterministic hostile/race regressions were added, and an independent
  reviewer executed those plus the actual competing-process test: four passed.
  The other failure was a stale SRC-01-unimplemented assertion; it now checks
  SRC-05 and also verifies the new owner-only SEC boundary. The two affected
  modules then passed 57 tests, one Linux-only skip and one warning.
- Independent source review found an unhandled Decimal exception for an extreme
  JSON exponent. Both exponent signs now fail with sanitized SourceError. The
  complete SEC/Alpaca module passed 101 tests; the reviewer separately passed the
  two hostile cases. These checks preceded a new frozen **1,461-test** full run.
  The corrected frozen full run passed **1,460 tests, one Linux-only skip, one
  existing warning, 92.33% combined coverage in 583.60 seconds**. The same source
  passed the lock check, Ruff format/lint and strict mypy gate. Full text/XML:
  `.local/v0-phase-c-proof/final.txt` and `final.xml`. No Python production/test
  edits occurred during this final run. The unchanged 90% threshold was met.
- A stopped-runtime Phase C backup restored to a distinct new path with **245
  byte-identical files**, including both canonical instrument revisions. Counts
  matched: seven users, eight jobs, 15 data operations and 12 owned datasets.
  The archive excludes `vault.sqlite3` and master-key files. Archive SHA-256:
  `d8c76d7ba3250263ead01299eec6c7e823d99128294360a13c948d4a509ad267`.
  Independent evidence: `.local/v0-phase-c-proof/restoration-proof.json`.
  The original runtime/vault are retained. A distinct synthetic private vault
  was used when subsequently testing the restored application.
  The first browser launch preceded server readiness and failed with connection
  refused; its evidence is retained. After an explicit readiness check, the
  restored browser passed **48 checks, 26 screenshots, zero errors** at
  07:26:06.189–07:27:00.911 UTC. The delayed-response account-isolation test also
  passed with zero provider requests. Evidence is under
  `.local/v0-phase-c-proof/restored-browser-final/`.
- The final wheel (73 members) and source archive (202 members) built
  successfully. Membership checks excluded runtime data, vaults, caches,
  dependencies, Git metadata and private archives, and compared updated vault,
  parser and served JavaScript bytes with source. An initial membership-check
  script mistakenly tried to parse the builder's `.gitignore` marker as an
  archive; restricting inspection to `.whl`/`.tar.gz` corrected that check.

The root reviewed credential, source and market math changes; another agent
independently reviewed the owner/API/persistence integration and ran real-browser
flows. This is cross-agent software review, not external professional approval.
REG-001–020 and REG-F01–F04 retain their scientific and host meanings. None of
these changes create sealed release, production promotion or live-order authority.

The saved checkpoint `796771c81a7c49768ebe7040730c88707c98827b` passed
[hosted run 37278264340](https://github.com/welmarr/quant-hunter/actions/runs/37278264340):
Windows 1,460 passed, one POSIX-only skip, one warning in 453.17 seconds; Ubuntu
1,460 passed, one Windows-DPAPI skip, one warning in 179.30 seconds, **92.09%**
combined coverage. Source/research integration after this commit is separate
unfinished work and cannot inherit that full-gate result.


## Provider workflows, mathematical Studies and reviewed research cores

Parent commit: `796771c81a7c49768ebe7040730c88707c98827b`; actual dirty runtime
source snapshots remain the execution authority. This checkpoint is IN_PROGRESS
until its complete regression and exact-commit hosted CI results are recorded.
No historical or empirical research claim follows from synthetic verification.

- Integrated reviewed macro/priority parsers, encrypted FRED/Sharadar/Trading
  Economics configuration, bounded materialization and BEA/ALFRED/BI5/EODHD
  imports. The corrected provider/source/connection slice passed 135 tests; the
  subsequent provider/partition/legacy-Lab slice passed 81. A first comparison
  incorrectly required Decimal trailing zeroes, helper fixture mistakes were
  corrected, and a synthetic key made of repeated `a` bytes collided with the
  synthetic source SHA in a test-only no-key assertion. These failures remain in
  `.local/v0-phase-c-proof`; production errors were not hidden as successes.
- The provider Chrome proof passed **57 checks, 32 screenshots, zero errors**
  at 08:17:28.280–08:18:10.145 UTC. It saved/revoked nonfunctional synthetic keys,
  imported four actual file formats, retained malformed input failure, checked
  privacy and mobile layout and made no provider probe requests. Its first run
  used incorrect unprefixed form IDs; retained failure artifacts show this
  harness error. Corrected evidence is under
  `.local/v0-phase-d-proof/providers-browser-second/browser-proof.json`.
- Ten CRP mathematical methods plus ENS-COV and META-OOF run through the actual
  preregistration/freeze/attempt/result path. Preparation does not fit a model.
  Recorded training partitions, actual random seed, method/citation/assumption/
  cost metadata and metrics/baselines are checked against immutable inputs.
  Independent review found and corrected cadence, cutoff and seed mismatches;
  twelve positive, null and sensitivity variants remain distinct counted attempts.
  ENS/META use truthful source-documentation descriptions without inventing a
  primary paper URL. A fixture mutation initially removed `strategy_id` rather
  than the canonical `object_id`; its four retained failures were corrected.
  The final focused workflow/binding run passed **36 tests**, one existing
  Starlette warning, in 192.48 seconds (`study-workflow-2.txt/xml`).
- Actual Studies browser proof passed **20 checks, 18 screenshots, zero errors
  and zero external requests** at 10:38:44.836–10:40:23.669 UTC. It executed all
  twelve positive controls, three expected null failures and a separately
  counted sensitivity variant, inspected actual result digests/metrics, and
  checked reader denial and 390px mobile layout. Evidence is
  `.local/v0-phase-d-proof/studies-browser-first/study-proof.json`.
- Reviewed pure cores include 66 Decimal accounting tests, 69 classical pattern
  tests and 105 publication tests. Pattern benchmark evidence uses explicitly
  synthetic 2015–2024 schedules: 977,640 equity plus 3,756,960 FX rows, 4,734,600
  total, 8.82 seconds and 119.6 MB observed peak memory. Approximate budgets
  8/32/128 retained 0/25/100 percent recall and 8/6/0 false negatives against
  their small oracle. This is measured synthetic throughput, not empirical
  validation or a completed persistent corpus product. Detailed contracts and
  independent-review boundaries are in PATTERNLAB.md, ACCOUNTING.md and
  PUBLICATIONS.md. Owned publication APIs and the durable paper service remain
  separate product integration work.
- The four source transports now use resource-bounded spawned workers with a
  twenty-second parent deadline covering startup/DNS through response body.
  The isolated transport batch passed **443 tests**, 97.15% combined coverage;
  the new module reached 98.11%. Independent review ran all **26** new deadline
  tests successfully. Actual web.main G17 acquisition at 10:47:58 UTC returned
  quarantined NETWORK_FAILURE after **5.654 seconds**, no retained raw bytes.
  This is a retained unsuccessful acquisition. Native-entry diagnosis is pending;
  network success is not inferred from synthetic fixtures or the HTTP200 wrapper.
- Independent cross-item review found that generic EXP/BACKLOG references reject
  valid PAPER identities although the PAPER registry itself works. A minimal
  common-schema correction and conformance tests are required before closure.
- A stopped-runtime backup restored to a distinct D-only directory with **436
  byte-identical files** and matching counts: five users, 21 jobs, 15 data
  operations and six owned datasets. SQLite integrity passed. Private vaults
  and master keys were excluded; the original runtime is preserved. Archive
  SHA-256: `a62cbd715cae69bf38c623cdbf698ad596a7bb0bc11bdcc0697b1caf0da8036b`.
  Evidence: `.local/v0-phase-d-proof/restoration-proof.json`. Restored UI proof
  for this checkpoint is still required.
- Current lock check, Ruff check/format, strict mypy, TypeScript and frontend
  build all passed (`static-gate.json`). The initial full run collected 2,251
  tests and is running. No full-checkpoint success is claimed yet. All output,
  temporary files, dependency caches, raw data and browser profiles stay on D:.

Cross-agent review is software review, not external professional certification.
No host/sealed-data/stage/promotion gate, source license or provider entitlement
has been approved by this checkpoint. Every current correctness finding must
be corrected and retested; it cannot be deferred merely by recording it here.

The failed native G17 request prompted a no-network production-entry diagnosis.
Spawning the actual heavy `quant_hunter.web.main` module consumed 297,476,096
private bytes before its 256 MiB child limit; creating the actual TLS trust
context then raised SSLError. A minimal isolated fix moves application imports
inside main() after argument parsing. Its fresh child used 24,694,784 bytes before
limits and 25,563,136 after loading 84 trusted CAs, without increasing limits.
The exact native regression failed against the old entry and passed with the
fix; 27 native/deadline tests passed together. Root integration, complete
regression and a new explicit real acquisition remain required. Isolated proof:
`.tools/v0-worktrees/ui/.tools/native_source_diagnostic/tls-proof-before.json`
and `tls-proof-after.json`. The original failed acquisition is preserved.

The initial frozen full gate completed: **2,250 passed, one POSIX-mode skip on
Windows, one existing Starlette warning, 93.07% combined coverage, 1,169.33s**.
Text/XML are `full-1.txt/xml` under `.local/v0-phase-d-proof`. The reviewed generic
PAPER-reference and native-main fixes were then integrated. Root Ruff required
only first-party import ordering; it was corrected without moving imports out
of main(). **175 targeted tests passed under -W error in 31.94s**; Ruff check,
format (212 files) and strict mypy (157 files) passed. The new frozen complete
gate includes 2,289 tests and remains pending until recorded below.

A distinct restored native application with the correction made one explicit
new public G17 acquisition at **11:07:49 UTC**: **SUCCEEDED in 1.7451166s**, six
observations, immutable raw SHA-256
`cffccc27526bce9168f6dbeca2908b7c9a78805e3fe3abcbcd6018509143ae90`.
Source status remains CANDIDATE and quality PENDING; available_at is unknown and
point_in_time_eligible is false. The failed earlier acquisition remains intact.
This verifies actual TLS/network/materialization through the production entry,
not licensing, historical timing or research admissibility. Exact evidence is
`.local/v0-phase-d-proof/native-g17-corrected.json`. Entry-source SHA-256 is
`ba4c048ef35cd9921909d437e615d466081e6db03b139288ace92fe469ee0cdd`;
transport-process SHA-256 remains
`9bd9e94c9875eb6c76b2ce6c827b13e1ce361134de8790a99ec985563fb7dcd1`.

The corrected distinct restored instance passed the full provider/import/market
browser workflow: **57 checks, 32 screenshots, zero errors**,
11:08:51.782–11:10:02.296 UTC. It then passed the separate Studies workflow:
**20 checks, 18 screenshots, zero errors and zero external requests**. Both
proofs retain actual timestamps, screenshot hashes, private experiment IDs and
result evidence under `.local/v0-phase-d-proof/restored-browser/` and
`restored-studies/`. These are separate from the original-instance proofs.

Distribution inspection passed: wheel **113 members**, source archive **269**;
no runtime, vault, credential file, Git metadata, dependency cache or generated
cache was included. Five required new/updated served/source modules were
present and byte-identical to root. The builder warns that its D-only uv cache
is within the repository; actual archive membership verified its exclusion.
Wheel SHA-256 `b3d8c7f85031739dcf350347e8dbee654488e5a155d34cbab6d9ecd7df5ee139`;
source archive SHA-256
`13da1c77666f8fb5f00e561db59dcdc49dbe4b6bf20e62a80ca9f06c05664c6d`.
Evidence is `distribution-build.txt` and `distribution-proof.json` under the
same private proof directory. The source archive predates this documentation
append; its source-code bytes match the frozen tested implementation.


Final corrected frozen gate: **2,288 passed, one POSIX-only skip on Windows,
one existing Starlette warning, 93.07% statement/branch coverage in 998.05s**.
The unchanged 90% threshold passed. Text/XML: `.local/v0-phase-d-proof/final.txt`
and `final.xml`. All131 frozen source/config/schema/frontend hashes matched
again after completion. Lock/Ruff/format/strict mypy and prior unchanged
TypeScript/build checks passed. Both review findings are corrected and covered
by the full suite; independent cross-item review found no additional material
failure in the reviewed scope. Exact saved-commit hosted CI remains required.

The 2,288-test gate covers the provider/Studies product workflows and reviewed
pure publication/pattern/accounting cores. It does not cover the isolated
publication-owned API/UI draft, persistent paper service, broker journal, large
corpus product or data-quality/validation adapters that are being developed
for subsequent checkpoints. No deferred current-checkpoint failure is hidden
inside those remaining mission requirements.


## Publication product integration — 2026-10-05, local gate passed

Base executable checkpoint0541337; CI-only correction8c6eabb. Root integrates
private PublicationAccess/routes into Runtime/main/API, adds reference cards and
safe frontend workflows, preserves Item8 EXP ownership, and shares two resource
slots with DataAccess. Exact64MB reserve correction recorded in DEC-0043.

Executed commands:

- `.venv\Scripts\pytest.exe tests/test_v0_publication_workflows.py tests/test_v0_data_access.py tests/test_v0_native_source_spawn.py -q --no-cov`:41passed, one existing Starlette warning,115.30s.
- `.venv\Scripts\pytest.exe tests/test_v0_publication_integration.py -q --no-cov -W error`: corrected7passed,17.47s; actual production-main PDF child, runtime recovery/store binding, both shared-admission paths, exact upload-only body allowance, authenticated10-reference catalogue and64MB floor.
- `ruff check .`, `ruff format --check .`, `mypy src tests`:PASS;217formatted files,161typed Python files. TypeScript build and browser syntax check pass.
- `node frontend/publication-smoke.mjs`: initial11checks/3screens/zeroerrors, then separately restored11checks. Corrected reference-card workflow12checks/3screens/zeroerrors/zeroexternalrequests. Actual generated PDF SHA256ee30ed9ed77fbabf56409bc0d72dde455f4f7561ec49364a68088f6e935630c1.

Proof roots are `.local/v0-publication-proof/{browser-initial,restored-browser,corrected-browser-2}`.
The private archive `.local/backups/publication-20261005.qhbackup` has SHA256
4202a2ee70583e6ab59f666b1ebc222aacc41229a275edbd0d2a3dd41f145737.
Its780archive-managed files match exactly in a new destination; application
SQLite integrity and counts match (7users,40jobs,9datasets,26data operations,
1owned PAPER,11publication operations). Recreated worker.lock is intentionally
excluded from the archive count. No vault or credential backup is implied.

Retained unsuccessful checks: first five integration fixtures failed because
the test private-root path overlapped the application, then passed with a distinct
private-root configuration; the production PDF test passed in that first run.
The first corrected-browser launch preceded server readiness and got connection
refused; no application error was logged, ready-state returned200, and the next
bounded run passed12checks. The first full regression was explicitly interrupted
at24% to apply review corrections; it is incomplete, not a pass. Its log remains
`full.txt`. The corrected frozen full suite passed **2,327 tests, one POSIX-only
skip, one existing Starlette warning, and 93.19% combined statement/branch
coverage in 1,162.32 seconds** (`corrected-full.txt/xml`). All 135 source,
configuration, schema and frontend hashes matched after completion against
`corrected-frozen-source-manifest.json`. No check or coverage threshold was
removed. Independent review closed the shared-resource reserve and reference
catalogue findings; its own focused runtime/route checks passed. The hosted
saved-commit check remains required after this checkpoint is pushed.

Publication distribution inspection: wheel and source archive contain the five
required publication/runtime/frontend modules byte for byte. No private runtime,
vault, caches, node_modules or Git metadata is included. Member counts/hashes:
- `quant_hunter-0.1.0-py3-none-any.whl`: 115 members; SHA-256 `a3fd6110bce685c8eedefb3cfa2e70ebe19a6bf48ac7c3b5acbeea2ba382b74e`.
- `quant_hunter-0.1.0.tar.gz`: 275 members; SHA-256 `e9bc778e6acee9b1f4a85a52b61417b7952af23118dee871a20c495b69609f7a`.
Proof: `.local/v0-publication-proof/distribution-proof.json`; build log retained.
The first archive-inspection helper attempted to parse uv's one-byte `.gitignore`
sentinel as a tar archive and failed; the corrected helper explicitly selects
only `.whl` and `.tar.gz` outputs. No distribution contents were changed.
