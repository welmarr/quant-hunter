# V0 test evidence

2026-10-05: V0 remains IN_PROGRESS. This report describes the first executable
synthetic slice only; it does not certify the full mission or the host boundary.

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
  passed. Clean-clone startup and restoration are still unexecuted.

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
