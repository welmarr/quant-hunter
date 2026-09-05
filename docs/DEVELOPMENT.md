# Development and Stage 1B Evidence

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
| uv Linux x86-64 GNU archive | SHA-256 `173d95a0c32d18c896c46ba6fafbf3cf9c14ab74b033f81b76c883ef492a976b` | Official release checksum |
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
Batch 2 adds jsonschema 4.26.0, referencing 0.37.0, rfc3339-validator 0.1.4,
and types-jsonschema 4.26.0.20260518 for local Draft 2020-12 conformance,
reference resolution, semantic timestamp checks, and strict typing. Batch 3B
makes the three runtime validation packages direct runtime dependencies and
adds the exact runtime pin `rfc8785==0.1.4` for standards-conformant JCS.
Exact resolved versions and transitive dependencies are authoritative in
`uv.lock`. No quantitative, market-data, broker, backtest, optimizer,
portfolio, or AI library is installed.

Pytest's nonessential cache provider is disabled. The host contains an ignored
`.pytest_cache/` directory that this process identity cannot inspect or remove;
disabling the cache avoids nondeterministic warnings without changing its ACLs.

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

Batches 1–2 contain only package and directory scaffolding, tool configuration,
the quality workflow, versioned schemas, and synthetic schema conformance tests.
Registry behavior, canonicalization, hashing, data contracts, experiment
controls, quantitative algorithms, connectors, backtesting, portfolio logic,
brokers, and sealed-data release remain deferred.

## Schema foundation

`schemas/v1/` defines Draft 2020-12 schemas for configurations, artifacts,
environments, sources, datasets, research families/models/strategies, patterns,
experiments, backlog items, and sealed release events. Every instance requires
`schema_version: "1.0.0"`; schema IDs include `/v1/`, and incompatible changes
require a new retained version plus an explicit migration decision.

The schemas close object shapes where fields are governed, preserve typed UUIDv7
formats, require provenance and scientific metadata, use UTC RFC 3339
timestamps, avoid unconstrained JSON `number` fields, and represent
precision-sensitive decimal values as constrained strings. Revision fields
prepare registry-shaped records for append-only history without implementing a
registry.

Batch 2 local validation checked all 11 schema documents against the Draft
2020-12 metaschema and validated one meaningful synthetic object for each of the
10 instance schemas. Targeted invalid fixtures proved rejection of missing
mandatory fields, unknown fields, malformed typed IDs, malformed timestamps,
schema-version mismatches, credential-shaped configuration keys, and broken
revision metadata. An in-memory NaN case was also rejected. The final locked
gate passed 21 tests with Ruff, strict mypy, and branch-aware coverage.

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

The Batch 2 review found that the SHA-pinned `setup-uv` action and exact uv
version selected the intended installer and release, but did not independently
pin the downloaded platform artifact. Both CI jobs now pass the official
platform-specific uv 0.12.10 SHA-256 through the action's supported `checksum`
input. This satisfies DEC-0005 without adding a custom installer.

## Batch 2 Fix validation

On 2026-09-05, the experiment and research-object v1 schemas were corrected
against their governing minimum records under DEC-0012. No registered research
records exist to migrate. Required metadata now includes explicit reason-bearing
pending/unavailable values, attempted-search accounting, evidence and sensitivity
records, and conditional freeze/implementation references. The remaining Batch 3
and behavioral registry/release controls remain unauthorized and unstarted.

The locked local quality gate passed: lock check, Ruff formatting and lint,
strict mypy (three files), and 87 pytest cases with 100% package coverage.
The package still has no substantive branch paths; coverage does not establish
research or release-control correctness. The fixtures add 59 isolated invalid
metadata cases and seven lifecycle/type positive cases, and extend the two
existing valid records. Local schema references remain offline.

The initial build attempt failed because PyPI access was blocked. Repeating
`uv build --no-sources --offline` succeeded from the existing cache for both
source and wheel distributions. Package import returned `0.1.0`.
`git diff --check` passed. Hosted CI was not triggered during this fix.
No dependencies, purchases, or paid commitments were added; aggregate budget
headroom remains unknown pending the existing subscription/API accounting inputs.

## Batch 3A registry validation

On 2026-09-05, Batch 3A implemented only Stage 1B roadmap item 5. The
`quant_hunter.identity` package defines all nine DEC-0009 identifier kinds and
their fixed registry directories. `RegistryStore` exclusive-creates
`v000001.json`, appends zero-padded revisions under a per-object filesystem
lock, compares the caller's prior digest with the verified current head, scans
globally for duplicate full IDs, and verifies contiguous exact-file SHA-256
links. Allocation is serialized by a registry-root lock and retries logged UUID
collisions. Generated indexes declare themselves non-authoritative.

The chain digest is private to registry-file integrity under DEC-0013. It hashes
the exact stored UTF-8 bytes and is not RFC 8785 JCS or a reusable artifact,
configuration, dataset, or freeze digest. Batch 3B remains responsible for
general canonicalization, standard vectors, hash APIs, and freeze manifests.
No authoritative research record was created; tests use temporary synthetic
directories and payloads. The common schema gained its previously documented
`COST-<uuidv7>` definition as a backward-compatible addition.

The locked local gate passed after implementation: `uv lock --check`, Ruff
format and lint, strict mypy, and 114 pytest cases. Registry tests exercise all
nine prefixes, exclusive first creation, collision retry/exhaustion,
multi-threaded allocation, one-winner compare-and-swap, stale-writer rejection,
zero-padded append history, global duplicates, broken links, lock timeout,
injected validation, non-finite JSON rejection, retained rejected/failed
history, and disposable index rebuilds. Combined statement/branch coverage was
94.04%; the collision and revision-conflict
behaviors required by DEC-0008 are directly exercised. `git diff --check` and
the offline source/wheel build passed. Hosted CI was not triggered. No runtime
or development dependency, purchase, service, or paid commitment was added.

## Batch 3B canonicalization and hashing validation

On 2026-09-05, Batch 3B implemented only Stage 1B roadmap item 6. The
`quant_hunter.config` package strictly ingests I-JSON, rejects duplicate keys,
non-finite numbers, unsupported values, invalid Unicode, and unresolved
environment tokens, then delegates number and property serialization to pinned
`rfc8785` 0.1.4. The `quant_hunter.provenance` package separates exact-byte
SHA-256 from canonical-JSON SHA-256 and constructs a generic deterministic
DEC-0007 freeze manifest. This does not implement experiment lifecycle or data
storage.

New registry revisions are canonical JCS bytes. Governed writes must pass the
existing Draft 2020-12 schema catalog; an unmapped kind fails closed. The
explicit low-level synthetic test constructor remains available for registry
mechanics. Chain verification hashes each stored file exactly, so historical
bytes are neither normalized nor rewritten. No real persistent record exists or
requires migration.

The locked Windows gate passed with 160 tests and 96.60% combined
statement/branch coverage. The dedicated canonicalization and hashing suite
achieved 100% statement and branch coverage. It includes the RFC 8785 primary
example, UTF-16 property ordering, 24 finite Appendix B binary64 vectors,
Unicode and escaping, NaN/Infinity and duplicate-key rejection, digest
stability/change and mismatch cases, schema-invalid governed writes,
historical-byte preservation, and deterministic freeze manifests. Ruff
format/lint and strict mypy passed; the offline build and final exact results are
recorded with the Batch 3B change. Hosted CI remains for independent review
after push. The new dependency is open source and costs USD 0; no paid
commitment was created.

## Batch 4A immutable object and raw-capture validation

On 2026-09-05, Batch 4A implemented only the first half of Stage 1B roadmap
item 7. Exact bytes publish under the DEC-0007 SHA-256 layout through a verified
same-directory staging file and exclusive atomic hard-link finalization. Existing
valid content deduplicates; mismatched content, unsafe roots, traversal,
link-like components, malformed descriptors, and partial staging names fail
closed. The abstraction exposes no mutation, replacement, or deletion method.

Generic artifact sidecars and raw-capture metadata use the existing strict JSON,
JCS, SHA-256, and versioned schema catalog. Payload bytes, artifact metadata,
and capture metadata remain separate immutable objects. Synthetic tests cover
distinct correction provenance, physical deduplication, quarantine retention,
and credential-shaped metadata rejection. No external request or real data was
used.

The locked Windows gate passed with 200 tests and 96.46% combined
statement/branch coverage. The focused storage suite gives 100% coverage
to raw capture, artifact manifests, and credential controls, and 95% to the
object store including atomic races and filesystem failure paths. Ruff,
strict mypy, build, import, archive inspection, and diff checks also passed.
Hosted Windows and Ubuntu CI remain for independent review after push. Batch 4B
retains every derived-Parquet, three-digest, normalized/curated, timestamp, and
point-in-time obligation. No dependency or paid commitment was added.
