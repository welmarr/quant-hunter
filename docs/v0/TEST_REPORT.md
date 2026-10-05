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
is cross-agent review, not professional independent certification. Hosted CI
must still verify the exact new saved commit; the previous 950-test CI cannot
be attributed to these changes.
