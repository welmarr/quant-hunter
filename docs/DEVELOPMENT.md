# Development and Stage 1B Batch 1 Evidence

## Pinned toolchain

Stage 1B Batch 1 uses standard GIL-enabled, 64-bit CPython 3.14.7 and uv
0.12.10. The exact runtime is pinned by `.python-version`; uv is pinned by
`uv.toml` and CI. Patch upgrades require an explicit decision, lock
regeneration, Windows and Ubuntu quality runs, and updated environment evidence.

| Component | Pin or digest | Source |
|---|---|---|
| CPython | 3.14.7, Windows x86-64, standard GIL | [Python.org release](https://www.python.org/downloads/release/python-3147/) |
| uv | 0.12.10; release commit `3c979abda4530fe9bf3d92e9bcf5c5575e3b3126` | [uv release](https://github.com/astral-sh/uv/releases/tag/0.12.10) |
| uv Windows archive | SHA-256 `f65744f94072152b1f86ba2aace4d01f1124d9a8ecb235805039e3718c36cac2` | Official release checksum |
| uv Windows executable used for validation | SHA-256 `a8bf95637ba520491de06713d718a55b90f18d127980b9531fd8fc5a8e99dc1d` | Extracted from the verified archive |

The host's pre-existing system interpreter is CPython 3.14.3. Validation uses a
uv-managed 3.14.7 installation under ignored `.tools/`; no Python registration
or system-wide installation was performed.

## Setup and quality commands

```text
uv sync --locked --group dev
uv lock --check
uv build --no-sources
uv run --locked python -c "import quant_hunter; print(quant_hunter.__version__)"
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy src tests
uv run --locked pytest --cov=quant_hunter --cov-branch --cov-fail-under=90
```

Direct development dependencies are intentionally limited to Hatchling 1.32.0
(packaging), Ruff 0.16.6 (format/lint), mypy 1.20.2 (strict typing), pytest
8.4.2 (tests), and pytest-cov 7.1.0 with coverage.py 7.16.0 (branch coverage).
Exact resolved versions and transitive dependencies are authoritative in
`uv.lock`. No quantitative, market-data, broker, backtest, optimizer,
portfolio, or AI library is installed.

## Preflight record

Recorded 2026-09-05 before Batch 1 changes:

- Repository: `D:/quant-hunter`, clean `main` at
  `bac4f40d62b3200a033f6c949199f9c811735d3c`; origin is
  `https://github.com/welmarr/quant-hunter.git`.
- Git host issue: the checkout owner differs from the process identity. Git was
  run with a temporary global-config file containing only
  `safe.directory=D:/quant-hunter`, then that file was deleted. No wildcard or
  persistent global trust was added.
- Host: Microsoft Windows NT 10.0.26200.0 / 25H2 build 26200.9278, x64 OS and
  process, fixed NTFS `D:` volume.
- Sealed-OOS feasibility: NTFS and ACL inspection are available, but encryption,
  separate identities, effective denial, and SACL audit evidence are not yet
  established. Audit-policy inspection returned privilege error `0x00000522`;
  filesystem volume inspection through `fsutil` returned access denied. No
  privileged host setting was changed. The sealed boundary remains a later
  Stage 1B gate.
- GitHub REST reported the repository `public` at
  2026-09-05T05:55:08Z. GitHub's
  [billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
  stated, as checked 2026-09-05, that standard GitHub-hosted runners are free
  for public repositories and larger runners are always charged. The workflow
  therefore uses only standard Ubuntu and Windows runners, disables uv caching,
  uploads no artifacts, and grants only `contents: read`. Reassess and disable
  hosted CI before or when repository visibility changes.

## Batch boundary

This batch contains only package and directory scaffolding, tool configuration,
an import/version smoke test, and the quality workflow. Schemas, registry
behavior, canonicalization, data contracts, experiment controls, quantitative
algorithms, connectors, backtesting, portfolio logic, brokers, and sealed-data
release remain deferred.

## Initial local validation

Validation completed on the Windows host on 2026-09-05:

- `uv lock` resolved 18 installed project/development packages, and
  `uv sync --locked --group dev` created a new `.venv` from its prior absent
  state using CPython 3.14.7.
- The package imported as version `0.1.0`; `sys._is_gil_enabled()` returned
  `True`.
- `uv build --no-sources` produced the source and wheel distributions.
  Archive inspection confirmed that ignored `.tools/` and `.venv/` content
  was not packaged.
- Ruff 0.16.6 formatting and lint checks passed after Ruff normalized two
  end-of-file differences.
- mypy 1.20.2 strict checking reported no issues in two source files.
- pytest 8.4.2 with pytest-cov 7.1.0 and coverage.py 7.16.0 passed one smoke
  test with 100% statement and branch-aware coverage. The scaffold contains no
  branch paths; coverage is not a claim of substantive behavior.
- High-confidence secret patterns and prohibited implementation terms returned
  no matches in their scoped scans. `git diff --check` passed.

The hosted workflow is enabled in the working tree but was not run during this
local, uncommitted batch. Its first remote result must be reviewed after a
separately authorized commit/push.
