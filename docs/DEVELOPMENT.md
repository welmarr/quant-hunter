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
Batch 4B.1 adds exact `pyarrow==25.0.1` for deterministic Parquet encoding.
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

### Batch 4A independent-review fixes

Windows may report an exclusive-create collision on a live registry lock as a
sharing `PermissionError` rather than `FileExistsError`. Registry acquisition
now retries that result only on Windows and only while the lock path is an
existing regular, non-symlink file. It also permits one immediate retry when a
contender removes the lock between the failed create and that inspection; a
second unconfirmed denial propagates. Directories, symlinks, persistent absent-path
denials, and non-Windows permission/configuration failures still fail closed,
and a confirmed live contender remains bounded by the original timeout. The
filesystem lock remains cross-process and exclusive-create based.

Authoritative object `get`, `read_bytes`, and `verify` operations now repeat the
existing symlink/Windows-reparse component inspection through the digest-prefix
directory immediately before reading. Final-object and artifact-root checks are
unchanged. These portable checks narrow accidental and unprivileged redirection,
but component inspection and file opening are separate operations and therefore
have an unavoidable TOCTOU window; they do not protect against a machine
administrator.

Before publication, artifact producer commands, provenance/request/source/coverage
references, request string values, provider text, and warning strings reject
explicit credential labels such as credential-bearing command options,
authorization headers, cookies, and bearer credentials. Detection is
label-based rather than entropy-based, does not match ordinary words containing
`token`, and never includes the suspected value in its exception text.

The review-fix locked Windows gate passed with 219 tests and 95.54% combined
statement/branch coverage. Lock, Ruff format, Ruff lint, strict mypy, package
import, and archive inspection passed. The first isolated build attempt could
not reach PyPI; the established `uv build --no-sources --offline` path then
built both distributions from the pinned local cache. No dependency or paid
service was added. Hosted Windows and Ubuntu CI remain for independent review
after push.

## Batch 4B.1 derived-data identity and deterministic Parquet validation

On 2026-09-05, Batch 4B.1 implemented only deterministic derived-table
identity and Parquet publication within roadmap item 7. PyArrow 25.0.1 is
exact-pinned after verifying Apache-2.0 licensing, CPython 3.14 compatibility,
and published Windows x86-64 and manylinux wheels. Arrow primitives are used
directly; pandas and other convenience dependencies were not added. The locked
Windows import reports PyArrow 25.0.1.

The versioned writer profile explicitly records column/schema and ordering
inputs plus row-group, compression/level, dictionary, statistics, Parquet/data
page versions, page/batch sizes, timestamp, metadata, null, page checksum,
schema-storage, nested-type, encoding, sorting, encryption, filesystem, bloom,
and decimal-storage choices. Input Arrow schema/field metadata is rejected.
Repeated local writes with the same explicit table, profile, and environment
produce identical bytes. Different governed profiles may produce different
physical digests and do not claim physical equivalence.

The logical fingerprint uses versioned length framing, JCS schema bytes,
type-tagged values, big-endian lengths and float64 bytes, declared-scale decimal
strings, and fixed-unit UTC timestamp strings. Ordered and unordered row modes
are explicit; unordered mode sorts framed rows while retaining duplicates.
Fixed expected schema, profile, ordered-content, and unordered-content digests
provide platform-independent regression vectors. The canonical lineage manifest
binds physical and artifact identities, full parent identities under declared
ordering, transformation/configuration, code/environment, logical schema and
content, writer profile, sources/references, creation time, and quality without
including its own digest.

The locked Windows gate passed: `uv lock --check`; Ruff format and lint over 50
files; strict mypy over 27 source files; and 241 pytest cases with 93.27%
combined statement/branch coverage. The offline governed build produced the
source and wheel distributions, package/PyArrow imports returned `0.1.0` and
`25.0.1`, archive inspection passed over 96 combined members, and
`git diff --check` passed. Hosted Ubuntu and Windows CI
remain for independent review after push. Physical-byte equality across
platforms, Arrow versions, or other Parquet libraries is not claimed; exact
physical digests identify observed files and logical vectors must remain stable.

Roadmap item 7 remains `IN PROGRESS`. Batch 4B.2 still owns the four timestamp
semantics, point-in-time/as-of eligibility, future-publication exclusion,
revision/vintage eligibility, and normalized/curated PIT selection tests. No
real data, connector, experiment, sealed release, model, backtest, strategy,
broker, Web, AI, or cloud capability was added.

## Batch 4B.1 provenance-integrity review fix

On 2026-09-05, independent-review hardening made semantic agreement mandatory
across individually valid immutable evidence. Derived dataset records now bind
all duplicated record/lineage claims, and artifact/lineage verification compares
physical identity, creation time, producer code/environment, ordered sources and
parents, references, and transformation configuration. Logical row ordering is
rechecked against the lineage schema. Raw-capture verification now compares its
payload, media type, ingestion time, source, dataset, and publication-defined
endpoint/request-reference sequence with the artifact manifest. Claims owned by
only one schema remain bound through the canonical manifest digest.

The complete locked Windows gate passed: `uv lock --check`; Ruff format and lint
over 50 files; strict mypy over 27 source files; and 272 pytest cases with 93.36%
combined statement/branch coverage. The offline governed build produced both
distributions, imports returned package/PyArrow versions `0.1.0` and `25.0.1`,
and archive inspection passed over 96 combined members. No dependency or paid
service was added. Batch 4B.2 and roadmap item 7 completion remain deferred.

## Batch 4B.2 point-in-time and vintage-selection validation

On 2026-09-06, Batch 4B.2 completed the implementation portion of roadmap item
7 using synthetic fixtures only. The typed PIT configuration requires an exact
UTC as-of instant and cryptographically binds PUBLIC or OPERATIONAL policy, the
generic observation key, vintage identity, all four temporal columns, revision
states, eligibility and selection rules, fail-closed ambiguity, and canonical
output ordering. Canonical audit evidence accounts for every selected or
excluded vintage. Normalized and curated results publish through the existing
deterministic Parquet, immutable-object, parent-evidence, artifact, lineage, and
three-identity contracts.

Hostile cases cover exact equality and one-nanosecond future publication,
second/millisecond/microsecond/nanosecond Arrow units, future and missing
ingestion or revision evidence, V1/V2/V3 historical reconstruction, event times
after as-of, input permutation, equal-priority ambiguity, typed evidence
tampering, unchanged earlier materializations, and different configuration or
lineage identity for equal logical content. The PIT module reached 95% combined
statement/branch coverage in its focused run.

The complete locked Windows gate passed: `uv lock --check`; Ruff format over 52
files; Ruff lint; strict mypy over 29 source files; and 312 pytest cases with
93.72% combined statement/branch coverage. The offline governed build produced
both distributions. Package and PyArrow imports returned `0.1.0` and `25.0.1`;
archive inspection found 100 combined members, included the PIT module in both
artifacts, and found no `.tools/` or `.venv/` member. `git diff --check` passed.
No dependency or paid service was added. Roadmap item 7 is ready for independent
review; Stage 1B item 8 remains unstarted.

### Batch 4B.2 independent-review fix

On 2026-09-06, the PIT selection contract gained a narrow exact-input evidence
record. It binds all five existing parent identities, declared schema digest, and
explicit parent row ordering; selection recomputes the supplied table's governed
logical fingerprint before eligibility evaluation. The canonical audit now also
binds the complete selected table with the existing logical-content fingerprint
under the published derived ordering. Publication and later verification require
the exact audited parent and selected identities. No timestamp, availability,
vintage-priority, ambiguity, or three-identity rule changed.

Focused hostile tests use otherwise valid alternate derived evidence to reject
wrong parent revision, physical, lineage, and logical identities and changed
non-key selected values. The locked Windows gate passed: lock check; Ruff format
over 52 files; Ruff lint; strict mypy over 29 source files; and 321 pytest cases
with 93.68% combined statement/branch coverage. The PIT module retained 95%
coverage. The offline governed build produced both distributions; package and
PyArrow imports returned `0.1.0` and `25.0.1`; archive inspection found 100
combined members, included the PIT module in both artifacts, and found no
`.tools/` or `.venv/` member. No dependency or paid service was added. Item 7
remains in review-fix status pending independent review; Stage 1B item 8 remains
unstarted.

### Batch 4B.2 final review fix

On 2026-09-06, PIT publication and later verification gained an independent
transformation-correctness check. Both paths now require the exact bound input
table, rerun the governed PIT selection algorithm with the recorded
configuration and input evidence, and compare the complete selected table,
selected-vintage accounting, exclusions, row counts, logical fingerprint, and
canonical audit evidence. A hostile regression changes a selected non-key
value, recomputes every affected ordinary result digest, and demonstrates that
the internally self-consistent forged result passes its ordinary verification
but fails deterministic transformation replay and publication.

The complete locked Windows gate passed: `uv lock --check`; Ruff format over 52
files; Ruff lint; strict mypy over 29 source files; and 322 pytest cases with
93.33% combined statement/branch coverage. The PIT module retained 93%
coverage. The offline governed build produced both distributions; package and
PyArrow imports returned `0.1.0` and `25.0.1`; archive inspection found 100
combined members, included the PIT module in both artifacts, and found no
`.tools/` or `.venv/` member. `git diff --check` passed. This review fix added no
dependency or incremental direct cost. The canonical budget ledger separately
records the owner's previously purchased USD 10 Codex credits. Item 7 remains
in final-review-fix status pending independent review; Stage 1B item 8 remains
unstarted.

## Stage 1B Item 8A experiment lifecycle and freeze core

On 2026-09-06, independent review passed item 7 at commit
`952bd3a4a30518d51b6a9dbe679b00f9c28753fd`. Item 8A added only the governed
synthetic `DRAFT → REGISTERED → FROZEN` path. Registration requires concrete
scientific plans and rejects outcomes, decisions, and nonzero attempt evidence.
Freeze evidence binds the exact registered revision and publishes canonical
bytes through the immutable object store without dereferencing sealed data.

The complete locked Windows gate passed: `uv lock --check`; Ruff format over 55
files; Ruff lint; strict mypy over 32 source files; and 364 pytest cases with
92.98% combined statement/branch coverage. The lifecycle module reached 90%
coverage. The offline governed build produced both distributions; package and
PyArrow imports returned `0.1.0` and `25.0.1`; archive inspection found 105
combined members, included the experiment lifecycle module in both artifacts,
and found no `.tools/` or `.venv/` member. Item 8 remains in progress: runtime
attempt counters, execution/later transitions, result and failure retention,
sealed-release integration, and deterministic rerun resolution remain
unimplemented. No dependency or incremental direct cost was added, and the
existing USD 10 prepaid Codex-credit spend was not counted again.

### Item 8A exact-timestamp review fix

On 2026-09-06, lifecycle ordering stopped using microsecond-resolution
`datetime` values. Calendar validation remains standard-library based, while
the complete fractional component is compared as an exact `Decimal`. Hostile
tests reject backward transitions below microsecond and nanosecond precision
and retain one-nanosecond progress, exact equality, whole-second, microsecond,
invalid-calendar, naive, and local-offset behavior.

The complete locked Windows gate passed: `uv lock --check`; Ruff format over 55
files; Ruff lint; strict mypy over 32 source files; and 371 pytest cases with
93.01% combined statement/branch coverage. The lifecycle module reached 91%
coverage. The offline governed build produced both distributions; package and
PyArrow imports returned `0.1.0` and `25.0.1`; archive inspection found 105
combined members, included the lifecycle module in both artifacts, and found no
`.tools/` or `.venv/` member. Item 8A remains in review-fix status pending
independent review. Item 8B was not started. No dependency or incremental
direct cost was added, and the existing USD 10 prepaid Codex-credit spend was
not counted again.

## Stage 1B Item 8B running state and attempt accounting

Independent review passed Item 8A at commit
`79730f9ed54d6fcf9c8b33ad70af6181941c0b5e`. Item 8B extends the same governed
experiment authority only through `FROZEN → RUNNING` and append-only runtime
attempt evidence. Each accepted attempt adds one registry revision under CAS;
the cumulative total, AI-generated subset, and failed subset are recomputed
from retained evidence and checked against the frozen multiple-testing budget.
No sealed reference is dereferenced and no result or decision behavior exists.

The complete locked Windows gate passed with repository-pinned uv 0.12.10:
`uv lock --check`; Ruff format over 55 files; Ruff lint; strict mypy over 32
source files; and 413 pytest cases with 91.44% combined statement/branch
coverage. The sandboxed run used an external disposable cache and the existing
pinned CPython 3.14.7 environment; it did not change the lock or dependencies.
The governed build produced both distributions, package/PyArrow and new
lifecycle-symbol imports returned `0.1.0`, `25.0.1`,
`ExperimentLifecycleService`, and `AttemptBudgetExceededError`; archive
inspection found 105 combined members, included the lifecycle module in both
artifacts, and excluded disposable tool/cache and virtual-environment paths.
Item 8B is `IN PROGRESS / REVIEW`. Item 8C and Item 9 were not started. The
incremental direct project cost is USD 0, and the existing USD 10 prepaid Codex
purchase was not counted again.

## Stage 1B Item 8C and Item 8 independent-review closure

Independent review passed Item 8C and the technical implementation of full
Stage 1B Item 8 at final PR head
`c80ca6d2dffba316239880cf6b3ce33c20ee6b2c`. The hosted final gate used CPython
3.14.7 and uv 0.12.10. Ubuntu passed 448 tests with exact combined
statement/branch coverage of 90.75%; `lifecycle.py` coverage was 84.59%.
Windows compatibility also passed all 448 tests. Ruff formatting, Ruff lint,
strict mypy, and `uv lock --check` passed.

Coverage reporting now sets `precision = 2` with `fail_under = 90`, so a true
combined result below 90.00% cannot pass through integer display rounding.
Item 8 is `COMPLETE / INDEPENDENT REVIEW PASSED`. Stage 1B remains in progress,
and Item 9 remains `NOT STARTED / NEXT`. This documentation reconciliation adds
no dependency or incremental direct cost.

## Stage 1B Item 9A temporal-validation contracts

Full Item 8 passed independent review and is merged on main at
`265d5f49e06f841a5e23fdf9ea177670bbfbc1e9`. Item 9A adds only immutable,
configuration-driven temporal-validation metadata contracts: exact UTC
half-open intervals, chronological top-level partitions, explicit
chronological-holdout, rolling, expanding, and purged folds, exact purge and
embargo evidence or reasoned non-applicability, and deterministic JCS/SHA-256
plan evidence. Construction and verification do not split data, execute a
model or strategy, compute statistics or returns, or dereference sealed-OOS
references.

The final locked Windows gate passed with repository-pinned uv 0.12.10:
`uv lock --check`; Ruff format over 58 files; Ruff lint; strict mypy over 35
source files; and 487 pytest cases with 91.54% combined statement/branch
coverage. The temporal-validation module reached 99.36% coverage. The offline
governed build produced both distributions; package, PyArrow, and new validation
imports returned `0.1.0`, `25.0.1`, `ValidationPlan`, and `ROLLING_WINDOW`.
Archive inspection found 110 combined members, included the temporal module in
both artifacts, and excluded `.tools/` and `.venv/` paths.

The Item 9A review fix removes the unsupported global-blackout interpretation
of fold-local purge and embargo evidence. An exact exclusion remains locally
bound to its fold and must remain coherent with that fold's boundary; overlap
with another otherwise-valid fold does not itself invalidate the plan. Actual
dataset membership and sufficient exclusion sizes require a later authorized
execution layer with registered temporal dependencies.

The locked Windows review-fix gate passed: `uv lock --check`; Ruff format over
58 files; Ruff lint; strict mypy over 35 source files; and 488 pytest cases with
91.51% combined statement/branch coverage. The corrected temporal-validation
module reached 99.34% coverage.

Independent review passed Item 9A at reviewed head
`e19c693557fc4debe7a12746ae682e1113e404b1`, squash-merged on main at
`5636ad431b1c660233189a45ebfd6157308df7fa`. Final hosted Ubuntu evidence was
488 passing tests with 91.46% combined statement/branch coverage and 99.34%
coverage for `temporal.py`; Windows passed all 488 tests. Ubuntu and Windows
post-merge CI succeeded. Item 9A is `COMPLETE / INDEPENDENT REVIEW PASSED`.

## Stage 1B Item 9B scientific-evidence contracts

Item 9B adds immutable metadata declarations for applicability, baseline roles,
the complete standard metric inventory, governed statistical methods,
sample-adequacy and robustness requirements, study-specific conventions, and
exact numeric evidence. A structural binding rejects family, budget, or
correction-plan contradictions against supplied Item 8 `FROZEN` metadata while
leaving attempts and counters in the append-only experiment authority. Canonical
reports retain unfavorable and pending outcomes, assess V0–V9 without creating
experiment decisions, and never dereference sealed release references. The
review fix restores the exact authoritative gate names, including V5 search
adjustment, makes pending observations narrative-only, binds report-level
`PENDING` to `NOT_YET_EVALUATED`, and prevents pending or failed required
evidence from supporting `VALIDATED`. Negative, null, and inconclusive completed
evidence remains valid scientific evidence and does not require positive
performance.

The complete locked Windows gate passed with repository-pinned uv 0.12.10:
`uv lock --check`; Ruff format over 60 files; Ruff lint; strict mypy over 37
source files; and 549 pytest cases with 92.89% combined statement/branch
coverage. The scientific-evidence module reached 99.73% coverage. The offline
governed build produced both distributions; package, PyArrow, plan, report, and
metric-inventory imports returned `0.1.0`, `25.0.1`,
`ScientificEvidencePlan`, `ScientificEvidenceReport`, and 31 standard metrics.
Archive inspection found 113 combined members, included the evidence module in
both artifacts, and excluded `.tools/` and `.venv/` paths.

Independent review passed Item 9B at reviewed head
`d828fb498de44df25d9fba908ac9a32868e6fbff`, squash-merged on main at
`26f1a8a5d62651aad9d545725d3200bad4170500`. Final hosted review evidence was 549
passing tests on Ubuntu and Windows, 92.85% combined Ubuntu statement/branch
coverage, and 99.73% coverage for `evidence.py`; post-merge Ubuntu and Windows CI
succeeded. Item 9B is `COMPLETE / INDEPENDENT REVIEW PASSED`.

## Stage 1B Item 9C simulation and execution-realism interfaces

Item 9C adds a metadata-only `backtesting` contract package. Canonical execution
plans record explicit BUY/SELL pricing rules, pricing quality, evidence basis,
exact physical latency, reasoned partial-fill assumptions, input data
capabilities, and complete market-session and gap policies. Executable plans
use side rules as the sole execution-price authority. Standard MARKET behavior
maps BUY to ASK and SELL to BID and cannot use LAST_TRADE as a direct executable
side quote; resting or custom behavior must describe its alternate semantics.
The global field is non-authoritative reference-source metadata. Canonical cost
plans require explicit applicability and a protocol
or reason for each governed cost component. Immutable simulation inputs bind the
Item 9A and 9B plan identities, data manifests, reproducibility identities,
candidate reference, partition, execution/cost plans, randomness, and optional
sealed-release metadata. Outputs retain separate claimed evidence references,
warnings, limitations, and failures without changing Item 8 authority. Completed
outcomes reject pending or failed categories; pending and failed category states
require matching report-level outcomes, while reasoned non-applicability remains
a completed disposition.

These interfaces contain no strategy, data iterator, event loop, backtest engine,
order matcher, fill simulator, PnL or transaction-cost calculation, market
calendar, connector, broker adapter, or live capability. They do not access
sealed contents, verify Item 10 authorization, or mark Item 9B V6 as passed.

The complete locked Windows gate passed with repository-pinned uv 0.12.10:
`uv lock --check`; Ruff format over 63 files; Ruff lint; strict mypy over 40
source files; and 613 pytest cases with 91.38% combined statement/branch
coverage. The metadata-only simulation contract module reached 83.87%
statement/branch coverage through hostile interface tests. The offline governed
build produced both distributions; package, PyArrow, execution plan, cost plan,
simulation input, and simulation output imports succeeded. Archive inspection
found 118 combined members, included the Item 9C contracts in both artifacts,
and excluded `.tools/` and `.venv/` paths.

Item 9C is `COMPLETE / INDEPENDENT REVIEW PASSED` at reviewed head
`97141bce973258f4393314f4205702eed2f5a67c`, squash-merged on main at
`529f401b5b75e9b213067abb00bbaa1c633b7ac8`. Full Item 9 is `IN PROGRESS / FULL
REVIEW FIX`; Item 10 is `NOT STARTED`. No new dependency or incremental direct cost was added, and
the owner-reported ChatGPT Pro amount remains unknown pending invoice
reconciliation.


## Stage 1B Full Item 9 cross-binding review fix

DEC-0028 adds a metadata-only `FrozenTemporalValidationBinding` that verifies an
Item 9A plan and exactly compares its partition boundary strings with supplied
Item 8 FROZEN metadata. Scientific-evidence plans derive the temporal digest from
that binding and require it to share the experiment and frozen-revision identity
of the existing multiple-testing binding. Simulation inputs accept verified Item
9A and Item 9B objects and derive their canonical digests. Canonical inputs still
state that consumption, execution, and Item 10 authorization are unverified.

Hostile tests reject mismatched training, validation, and sealed boundaries;
malformed frozen authority; cross-experiment and cross-revision bindings;
unbound or tampered plan digests; and unrelated Item 9A/9B objects. Sealed
references remain metadata-only under patched file, stat, and directory-listing
operations. The final locked Windows gate passed with `630` tests and
`91.03%` combined statement/branch coverage; the temporal, evidence,
and simulation contract modules reached `95.29%`,
`98.70%`, and `83.67%`, respectively. The governed
offline build/import/archive checks also passed.

Full Item 9 remains `IN PROGRESS / FULL REVIEW FIX` pending independent re-audit.
Item 10 is `NOT STARTED`. This fix performs no statistical calculation, split,
evaluation, simulation, experiment execution, registry-chain verification, or
sealed-content access. No new dependency or incremental direct cost was added;
the ChatGPT Pro charge remains unknown pending invoice reconciliation.

### Full Item 9 independent-review closure and continuity governance

The preceding status records the state of the cross-binding implementation
before independent re-audit. Independent review subsequently passed full Item 9
at reviewed head `d6ff6b26fced3c7750f8a4c68b520b70c0567c77`, merged on main at
`6c9d5ae1eec58faeca53239d832748053387f1bc`. Post-merge Quality #32 passed on
Ubuntu and Windows. Ubuntu ran all 630 tests with 90.99% combined
statement/branch coverage; Windows also succeeded.

Full Item 9 is therefore `COMPLETE / INDEPENDENT REVIEW PASSED`. Item 10 remains
`NOT STARTED`. DEC-0029 adds repository-authoritative current-state and
regression-governance documents without adding scientific computation, sealed
release behavior, a dependency, or incremental direct cost.

## Stage 1B Item 10A sealed-OOS software release core

Item 10A adds a synthetic-only release service and an append-only exposure
ledger. Authorization reuses Item 8's exact FROZEN authority and binds the sole
FROZEN revision, immutable freeze manifest, code/configuration/environment,
complete canonical dataset-ID set, exact sealed interval, release timestamp,
and an immutable released artifact. Canonical event identity is SHA-256 over
RFC 8785 JCS of the full event body excluding only `event_digest`, so the prior
event digest remains inside every non-genesis preimage. Exclusive event
publication, verified-head compare-and-swap, canonical head anchoring, and full
chain verification reject concurrent forks, stale writers, overwrites,
corruption, missing/reordered events, and tail truncation.

Authorized release and accidental exposure are permanently `EXPOSED`. The
release digest is retained when Item 8 appends the later `RUNNING` revision;
new search attempts then fail, while the fixed prespecified evaluation can
continue with zero new attempts. The software accepts no sealed source path and
hostile tests poison read/open/stat/exists/list/hash/traversal operations. Item
10A emits and accepts only `SYNTHETIC_TEST` evidence. It does not create or prove
a Windows host boundary, and Item 10B remains `NOT STARTED`.

The complete locked Windows gate passed with repository-pinned uv 0.12.10:
`uv lock --check`; Ruff format over 70 files; Ruff lint; strict mypy over 45
source files; and 674 pytest cases with 90.17% combined statement/branch
coverage. The Item 10A hostile suite contributed 38 passing parameterized cases.
The governed offline build produced both distributions. Package, PyArrow,
exposure-ledger, release-service, and post-release-search imports returned
`0.1.0`, `25.0.1`, `ExposureLedger`, `SealedReleaseService`, and
`PostReleaseSearchError`. Archive inspection found 129 combined members,
included both isolation modules in the source and wheel artifacts, and excluded
`.tools/` and `.venv/` content. Independent review and hosted Ubuntu/Windows CI
remain pending; no Item 10B host evidence is claimed.

### Item 10A pre-independent-review hardening

DEC-0032 changes the software exposure query from experiment-scoped exact
equality to global dataset/time overlap. Exact UTC half-open intervals compare
all fractional-second digits without floats. Any same-dataset component overlap
across release or incident history blocks a later authorized release; adjacent
intervals and different datasets remain independent. Incidents remain appendable
after exposure. Prospective release still requires the current FROZEN head,
while retained evidence is reverified against the complete Item 8 history, sole
historical FROZEN revision and manifest, exact authority fields, and retained
release-event digest through RUNNING, EVALUATED, and DECIDED.

The corrected Item 10A hostile suite passed all 54 cases. The complete locked
Windows gate passed `uv lock --check`, Ruff format over 70 files, Ruff lint,
strict mypy over 45 source files, and all 690 pytest cases with 90.18% combined
statement/branch coverage. The governed offline build and import checks passed;
archive inspection again found 129 combined members, included both isolation
modules in source and wheel, and excluded `.tools/` and `.venv/` content.
Independent review and hosted CI remain pending.

### Item 10A independent-review writer-authority fix

Nova's independent review of head
`859233574d4d8ea9595e7985f3da82aba252c99a` failed because the public
`ExposureLedger.append_event` method formed a competing supported writer path.
It could persist a structurally valid release event without exact Item 8 FROZEN
authorization or immutable released-artifact verification. DEC-0033 makes
`SealedReleaseService.authorize_release` the sole supported public release
writer and `record_accidental_exposure` the sole supported public incident
writer. The ledger retains public read and chain-verification methods, while its
validated append hook is private/internal and retains all existing schema,
canonical digest, CAS, overlap, and append-only controls.

The corrective Item 10A hostile suite passed all 58 cases. The complete locked
Windows gate passed `uv lock --check`, Ruff format, Ruff lint, strict mypy, and
all 694 pytest cases with 90.18% combined statement/branch coverage. The
governed offline build and import/archive checks also passed with no dependency
drift. Item 10A remains `IMPLEMENTED / INDEPENDENT REVIEW PENDING` until Nova
re-audits the corrective head; Item 10B remains `NOT STARTED`.

### Item 10A closure and deferred-issue governance

Independent review passed the corrected Item 10A branch head
`0892bfdb9231053e8896867facb8fc3de47ebf8e`. PR #7 merged it on main at
`20851f262041cda1fe26844032f298b2a1531ffd`. Post-merge Quality #36 succeeded
on Ubuntu and Windows with 694 tests on each platform and 90.11% combined
statement/branch coverage on Ubuntu. Item 10A is therefore `COMPLETE /
INDEPENDENT REVIEW PASSED / MERGED / POST-MERGE CI GREEN`; this establishes no
real Windows host boundary.

DEC-0034 adds the detailed deferred-material-work standard, GitHub Issue Form,
and agent resume/closure rules. GitHub CLI was unavailable on the local host, so
no remote Issue was searched or created. Complete ready-to-post drafts for
RISK-018, RISK-023, RISK-024, COST schema authority, and pre-ingestion data
architecture are retained in `DEFERRED_ISSUE_DRAFTS.md` pending duplicate search
and authorized remote creation. This governance work adds no dependency or
incremental direct cost.

### Item 10B Windows host tooling and blocked evidence

The 2026-09-11 read-only preflight ran on the local Windows host before any
mutation. It confirmed Windows 10.0.26200.0 and two fixed NTFS volumes, but the
process was not elevated. BitLocker queries returned access denied, File System
audit-policy evidence could not be obtained, and backup status could not be
read. The governed local accounts and proposed roots were absent. Windows
Search was running and a consumer-sync root was detected. These facts fail the
encryption and evidence gates. No setup, verification, rollback, user, ACL,
SACL, audit-policy, index-attribute, filesystem, or BitLocker mutation ran.

Item 10B therefore adds tooling without claiming host evidence:

- `windows_host.py` loads only protected canonical evidence into a typed object,
  binds sanitized location fingerprints, and authorizes host releases only
  through the effective custodian identity and exact Item 8/10A authorities.
- `windows-host-boundary-evidence.schema.json` requires every successful host
  assertion and the explicit administrator/SYSTEM limitation.
- the release-event schema requires an exact evidence digest for
  `HOST_ENFORCED` and forbids it for `SYNTHETIC_TEST`;
- `item10b_preflight.ps1` is read-only; setup and rollback require explicit
  `-Apply`; identity authentication material remains in memory; and normal CI
  never executes host mutation scripts.

From Windows CMD, an owner-selected already encrypted fixed NTFS target is
checked with:

```bat
set QH_OOS_ROOT=<existing-encrypted-volume>:\QuantHunterOOS
pwsh.exe -NoLogo -NoProfile -File scripts\windows\item10b_preflight.ps1 -RepositoryRoot "%CD%" -CandidateRoot "%QH_OOS_ROOT%"
```

Only after that command returns `Pass: true` in an elevated owner-controlled
session may the single governed capture workflow be explicitly authorized. It
reruns preflight, uses that exact in-memory result for setup and verification,
consumes the resulting probes directly, and publishes canonical evidence:

```bat
uv run --locked python scripts\windows\item10b_finalize.py --repository-root "%CD%" --candidate-root "%QH_OOS_ROOT%" --canonical-evidence "%QH_OOS_ROOT%\host-evidence\evidence-000001.json" --authorize-setup
```

There is no supported report-finalization step. A raw mapping, JSON document,
or caller-selected report path cannot create typed host authority. The setup
script passes the exact successful preflight object to verification; the
published record separates those observed facts from the later effective
identity, ACL, SACL/audit-event, release, and indexing checks. Authentication
material remains inside the PowerShell process and never returns to Python.

The tooling must then run the locked quality gate and receive independent review.
Do not change BitLocker, use real OOS bytes, or advance to Item 11.

Local software validation passed `uv lock --check`, Ruff format and lint, strict
mypy over 48 source files, and all 743 pytest cases with 90.55% combined
statement/branch coverage. The focused Item 10A/10B/schema/script suite passed
204 cases, and the host module reached 96.62% coverage. The offline build
produced both distributions; package, PyArrow, Item 10A, and Item 10B imports
passed; archive inspection found 144 combined members, included
`isolation/windows_host.py` in both artifacts, and excluded `.tools/` and
`.venv/`. All PowerShell host files passed parser validation. These are
software/tooling results only and do not change the blocked live-host status.

Independent review of head `238a1538888a34635b7f274b451fbd57c980cb0e`
failed Item 10B because the public raw-report finalizer could turn caller
assertions into typed authority. DEC-0036 removes that method and the
`--live-report` CLI route. The corrective capture path runs the governed
workflow itself and publishes only its immediate, bound result. This correction
creates no live host evidence and leaves Item 10B at `IMPLEMENTED TOOLING / HOST
EVIDENCE BLOCKED` pending independent review and a separately authorized,
successful elevated execution.

Corrective local validation passed `uv lock --check`, Ruff format and lint,
strict mypy over 48 source files, and all 757 pytest cases with 90.26% combined
statement/branch coverage. The focused Item 10A/10B/schema/script suite passed
218 cases; the host module's focused suite passed 35 cases with 91.74%
statement/branch coverage. The offline build produced both distributions;
package, PyArrow, Item 10A, and Item 10B imports passed; archive inspection
found 144 combined members, retained `isolation/windows_host.py` in both
artifacts, and excluded `.tools/` and `.venv/`. All five PowerShell host scripts
passed parser validation. These are software results only and do not constitute
live Windows host-boundary evidence.

### Item 10B Windows audit-event semantics correction

The raw-report authority bypass was corrected at
`45611b771951839c96f4f19111ae4d8e7fb6898e`. Independent re-review then found
that the live verifier queried Security event 4663 for both denied research
access and successful custodian activity. That does not match the configured
SACLs: a declined handle request is evidenced by event 4656 with the standard
Audit Failure keyword, while 4663 records a right actually exercised and uses
Audit Success for the permitted custodian activity.

The verifier now queries events 4656 and 4663 over the exact probe window and
normalizes `SubjectUserSid`, diagnostic account name, object name, timestamp,
and standard audit keywords from event metadata. Research denial requires a
4656 Audit Failure from the exact already-resolved research SID and the exact
synthetic vault/fixture probe target. Custodian activity requires a 4663 Audit
Success from the exact already-resolved custodian SID and the exact synthetic
fixture or released object. Event ID alone, success-classified 4656,
failure-classified 4663, a same-named account with another SID, another object,
and stale events do not satisfy either gate. Display names and message text are
not authority and are not used to infer success or failure.

This correction changes no SACL, host identity, BitLocker setting, dependency,
or authority architecture. No live host workflow ran and no host evidence was
captured. Item 10B remains `IMPLEMENTED TOOLING / HOST EVIDENCE BLOCKED` pending
independent review and a later separately authorized live execution.

Corrective local validation passed `uv lock --check`, Ruff format and lint,
strict mypy over 48 source files, and all 767 pytest cases with 90.26% combined
statement/branch coverage. The focused Item 10A/10B/schema/script suite passed
228 cases. All six production Item 10B PowerShell files and the synthetic audit
harness passed parser validation. The offline build produced both
distributions; package, PyArrow, Item 10A, and Item 10B imports passed; archive
inspection found 146 combined members, retained `isolation/windows_host.py` in
both artifacts, and excluded `.tools/` and `.venv/`. These results contain no
live Windows host-boundary evidence.

### PR #8 audit-target provider-independence correction

Quality #37 passed all 767 tests on Windows. Ubuntu reported 758 passed and
nine setup errors because the pure audit classifier called
`Join-Path` with the synthetic Windows ObjectName base
`D:\QuantHunterOOS\vault`; Linux PowerShell tried to resolve `D:` as a local
provider drive. The security and scientific semantics were unchanged.

The classifier now normalizes and joins Windows ObjectName evidence using only
ordinal, case-insensitive string operations. Its pure target-building path does
not call `Join-Path`, `Resolve-Path`, `Test-Path`, `Get-Item`, or filesystem
APIs. Tests retain the Windows-style `D:` evidence strings and the full 4656
Failure / 4663 Success hostile scenario set. Local Windows validation passed
the locked dependency, Ruff, and strict mypy checks; all 768 tests passed with
90.26% combined statement/branch coverage, and the focused Item 10A/10B/schema
suite passed 229 cases. Local WSL enumeration was unavailable to the process,
so no local Linux result is claimed. Item 10B remains `IMPLEMENTED TOOLING /
HOST EVIDENCE BLOCKED` pending the new PR checks, independent review, and later
separately authorized live evidence.

### Item 10B owner-host failure and SID-authority correction

PR #8 merged the provider-independent audit correction on main at
`cf26f4a3c8abd2387649a0baf90d398679ea8ca5`. Post-merge Quality #39 passed 768
tests on Ubuntu and Windows; Ubuntu combined statement/branch coverage was
90.20%.

The owner then ran the governed workflow from an elevated session against a
separate fixed NTFS target. Preflight passed with BitLocker On/FullyEncrypted,
repository/profile/cache/temp exclusion, absent governed identities and target,
and no sync overlap. Backup configuration was unreadable and remains residual
risk. Setup failed closed after the two governed accounts were created and
before audit-policy or effective-identity work. Security events showed
4720/4722/4738 for both accounts and 4726 deletion during rollback; no 4719
audit-policy change and no governed 4656/4663 evidence occurred. Independent
inspection confirmed the batch root, marker, state, evidence, and users absent,
File System auditing restored to No Auditing, and BitLocker unchanged. No
canonical `HOST_ENFORCED` authority was created.

A separate owner-controlled read-only probe showed that `.\` local-account name
translation is not portable on the tested host. The correction obtains each
new local user's actual `SecurityIdentifier`, verifies that the account is
local, enabled, and outside the prohibited privileged local groups, and uses
those SIDs for every governed DACL and SACL rule. SYSTEM and Administrators use
well-known SIDs. Verification translates access and audit rules to SIDs and
requires the exact SID set, rights, allow type, and audit outcome. A same named
account with another SID cannot satisfy the checks. Effective probes use the
runtime machine-qualified account name only inside `PSCredential`; neither the
machine name nor passwords enter canonical evidence. The elevated verifier
redirects each child probe's stdout into its evidence file; the research account
does not receive write authority to the protected evidence directory.

Setup failures now carry a non-secret phase through a bounded structured stderr
block. PowerShell strips terminal controls, redacts explicit credential labels,
and limits the reason; Python accepts only the marker plus a known phase, safe
exception type, and sanitized reason, with a 384-character final bound.
Unstructured stderr remains hidden, and failed execution cannot publish
canonical evidence. The existing marker/state-bound rollback still restores the
original audit Success/Failure state and removes only batch-created users and
the batch-created root. The correction performs no live host or BitLocker
mutation and leaves Item 10B at `TOOLING MERGED / LIVE HOST EVIDENCE BLOCKED`.

Independent review of head `6fe7ce1b097d68418cae22920725c85f00ad7729`
accepted the DACL/SACL SID correction with changes and found that live event
classification still compared only the account-name leaf. The follow-up
normalizes `SubjectUserSid` and passes the same resolved research and custodian
SIDs through DACL verification, SACL verification, 4656 denial evidence, and
4663 performed-access evidence. Machine/account display text remains transient
diagnostic metadata; no SID was added to canonical scientific evidence. This
follow-up has no live-host success claim and RISK-017 remains `OPEN`.

Corrective local validation passed the lock check, Ruff format and lint, strict
mypy over 48 source files, and all 780 pytest cases with 90.15% combined
statement/branch coverage. The focused Item 10A/10B/schema/script suite passed
241 cases. All seven production Item 10B PowerShell files plus the synthetic
ACL and audit harnesses passed parser validation. The documented exact pytest
command initially encountered access denial while enumerating a pre-existing
user temp directory before fixture setup; no product test failed. Repeating the
same locked coverage gate with a workspace-local `--basetemp` completed all 780
tests. The offline build produced both distributions; package, PyArrow, Item
10A, and Item 10B imports passed; archive inspection found 148 combined members,
included `isolation/windows_host.py` in both artifacts and the new ACL helper in
the source distribution, and excluded `.tools/` and `.venv/`. No dependency or
lockfile change was made.

The audit-event SID-binding follow-up passed `uv lock --check`, Ruff format and
lint, and strict mypy over 48 source files. The focused Item 10A/10B host,
script, schema, and sealed-release suite passed 243 tests. The exact full pytest
command first encountered the known Windows user-temp ACL problem: 425 tests
passed and 357 fixtures could not be created. Its workspace-local `--basetemp`
rerun passed all 782 tests with 90.15% combined statement/branch coverage. No
dependency, lockfile, canonical-evidence schema, host, or BitLocker change was
made.
