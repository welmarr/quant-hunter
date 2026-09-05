# Decisions

## Decision Policy

Record decisions that affect architecture, research methodology, statistical validity, data timing, leakage controls, experiment scope, cost modeling, production isolation, security, or spending. Record them before or with the change—never after seeing results merely to justify an outcome. Unresolved assumptions belong here as explicit open questions rather than silent guesses.

Entries are append-only. A later decision may supersede an earlier one but must link to it and preserve its rationale. Changes to frozen experiments also require a new experiment ID under `EXPERIMENT_LEDGER.md`.

## Required Decision Record

```text
ID: DEC-NNNN
Date: YYYY-MM-DD
Status: PROPOSED | ACCEPTED | REJECTED | SUPERSEDED
Scope: architecture | governance | methodology | validation | data | security | cost | operations
Context:
Decision:
Alternatives considered:
Scientific/statistical consequences:
Reproducibility and cost consequences:
References (experiments, models, data sources, code):
Supersedes / superseded by:
Owner and approver:
```

## Decision Log

### DEC-0001 — Split the Master Specification by Authority

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** architecture / governance
- **Context:** The full specification had grown too large for persistent agent instructions.
- **Decision:** Keep invariants and workflow in `AGENTS.md`; move detailed domain requirements into named documents and maintain `REQUIREMENTS_TRACEABILITY.md`.
- **Alternatives considered:** Retain the entire specification in `AGENTS.md`, or split it without a traceability map. Both increase drift or persistent-context cost.
- **Scientific/statistical consequences:** Invariants remain prominent while detailed standards have explicit authorities; no evidence standard is relaxed.
- **Reproducibility and cost consequences:** Cross-document auditing becomes possible; no purchase or implementation cost is introduced.
- **References:** `AGENTS.md`, `README.md`, `REQUIREMENTS_TRACEABILITY.md`, and all domain documents created by this decision.
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through the explicit documentation-refactor request dated 2026-09-04.

### DEC-0002 — Documentation Before Stage 1

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** operations
- **Context:** The existing master specification required a research foundation before strategy work, and the refactor request prohibited Stage 1 until documentation architecture was complete.
- **Decision:** Complete and audit the documentation architecture before any Stage 1 implementation. This decision does not itself authorize Stage 1 or strategy development.
- **Alternatives considered:** Scaffold Stage 1 concurrently, or begin strategy code. Both violate the requested gate and increase the risk of designing controls after results exist.
- **Scientific/statistical consequences:** Validation, data, registry, and leakage requirements precede research computation.
- **Reproducibility and cost consequences:** The repository remains documentation-only; no dependency, data, service, or infrastructure spending is introduced.
- **References:** `AGENTS.md`, `PROJECT_CHARTER.md`, `ROADMAP.md`, `VALIDATION_STANDARD.md`.
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through the explicit documentation-refactor request dated 2026-09-04.

### DEC-0003 — Make Algorithm Discovery and Expansion Operational Stages

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** governance / methodology / validation
- **Context:** An independent review found that algorithm discovery, canonical implementation, large-scale model expansion, the Pattern Lab, automated research flow, and AI sealed-data restrictions were present as intentions or domain rules but were not explicit operational roadmap sub-stages.
- **Decision:** Define Stage 2A–2D and Stage 3A–3D with registration-first discovery, a source hierarchy, canonical implementation outcomes, the unchanged ten-area reproduction set, a gated Pattern Lab, evidence-family governance, a status-compatible automated pipeline, and a permanent research backlog. Strengthen Stage 4 so AI contributors to a hypothesis cannot access its sealed OOS evidence before freeze.
- **Alternatives considered:** Leave the requirements implicit across domain documents, or duplicate all domain specifications inside the roadmap. The first is not operational; the second would create competing authorities and drift.
- **Scientific/statistical consequences:** Candidate-search exposure becomes visible earlier; reproduction claims use honest outcome labels; Pattern Lab and AI work remain bound to multiple-testing, sealed-OOS, and reproducibility controls.
- **Reproducibility and cost consequences:** This is documentation-only and adds no code, dependency, service, data purchase, or spend. Canonical schemas remain in the registries and detailed methods remain in their governing documents.
- **References:** `ROADMAP.md`, `REQUIREMENTS_TRACEABILITY.md`, `MODEL_REGISTRY.md`, `EXPERIMENT_LEDGER.md`, `RESEARCH_METHODOLOGY.md`, `VALIDATION_STANDARD.md`, `PATTERN_DISCOVERY.md`.
- **Supersedes / superseded by:** Extends DEC-0002; supersedes no requirement.
- **Owner and approver:** Project owner, through the explicit independent-review correction request dated 2026-09-04.

### DEC-0004 — Standardize on CPython 3.14

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** architecture / reproducibility
- **Context:** Stage 1 needs one supported runtime with current scientific-Python compatibility and a useful maintenance horizon.
- **Decision:** Use 64-bit, standard GIL-enabled CPython `3.14.x`. Declare `requires-python = ">=3.14,<3.15"`, use the latest patched 3.14 release available when an environment is created, and record the exact interpreter build, platform, and architecture in every environment manifest. Adding a dependency requires a Python 3.14 wheel/import smoke test on the supported host.
- **Alternatives considered:** CPython 3.13 has broad compatibility but reaches source-only security maintenance sooner; 3.12 has a still shorter horizon; 3.15/pre-release runtimes and the free-threaded build add avoidable compatibility or determinism risk. All are rejected for the initial single-runtime baseline.
- **Scientific/statistical consequences:** A single interpreter reduces unexplained numerical variation. Runtime upgrades require locked-dependency tests and a new environment digest; they never silently alter a frozen experiment.
- **Reproducibility and cost consequences:** Python is free. The exact patch version is evidence, not an unconstrained dependency; reruns use the recorded environment. No paid service is introduced.
- **References:** [Python 3.14 schedule](https://peps.python.org/pep-0745/), [NumPy support](https://numpy.org/news/), `ARCHITECTURE.md`.
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through Stage 1A authorization dated 2026-09-04.

### DEC-0005 — Use uv with a Committed Lockfile and Project-Local Environment

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** architecture / reproducibility / operations
- **Context:** Dependency resolution, tool execution, and environment creation need one cross-platform workflow.
- **Decision:** Use PEP 621 metadata in `pyproject.toml`, uv as the sole dependency/environment manager, a committed `uv.lock`, and an uncommitted project-local `.venv`. Pin the uv executable version and installer checksum in the toolchain manifest and CI. In CI this means an immutable `setup-uv` action SHA, an exact uv version, and the official platform-specific uv archive SHA-256 supplied through the action's `checksum` input; the action must fail on mismatch. Normal setup is `uv sync --locked`; CI first runs `uv lock --check`, and all commands run through `uv run --locked`. Dependency changes deliberately regenerate and review the lock. Use Hatchling as the minimal build backend for the `src/` package; export `pylock.toml` or an SBOM only as a derived interoperability artifact.
- **Alternatives considered:** Poetry and PDM provide integrated workflows but add a second project-specific command model; pip-tools does not manage the interpreter/project environment; Conda is useful for unusual native/GPU stacks but adds a second solver. They are rejected initially and require a new decision if a measured native dependency cannot be supported.
- **Scientific/statistical consequences:** Frozen runs bind to the lock digest and exact environment manifest, preventing opportunistic package drift.
- **Reproducibility and cost consequences:** uv and Hatchling are open source and add USD 0 direct cost. `.venv` is disposable and never committed; `pyproject.toml`, `uv.lock`, toolchain metadata, and their digests are retained.
- **References:** [uv project layout](https://docs.astral.sh/uv/concepts/projects/layout/), [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/), `ARCHITECTURE.md`.
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through Stage 1A authorization dated 2026-09-04.

### DEC-0006 — Isolate Sealed OOS Data with Separate OS Identities

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** security / validation / data
- **Context:** A path convention or configuration flag cannot make sealed evidence inaccessible to development and AI workflows.
- **Decision:** For Stage 1 on Windows, store sealed OOS data outside the repository, worktrees, artifact cache, search index, and ordinary backup/sync roots on an encrypted NTFS volume. A dedicated `qh-oos-custodian` OS identity owns an allow-only, inheritance-disabled DACL; the separate `qh-research` identity used by developers, notebooks, agents, tests, and reports receives no read, list, traverse, write, ownership, or ACL-change rights. SACL auditing records access and permission changes. A custodian-only release command may create an immutable, experiment-specific read-only release after verifying `FROZEN` status, experiment ID, code/config/environment/data-manifest digests, and release reason. It exclusive-creates a JCS/SHA-256 hash-chained release event. Exposure is one-way: the source partition becomes `EXPOSED`; any pre-freeze or unauthorized access marks affected experiments `INVALIDATED` and triggers risk/decision review.
- **Alternatives considered:** A config flag or hidden directory is not a security boundary; an encrypted archive with a shared password is easy to leak; immediate cloud object storage/IAM adds account, network, and cost complexity. These are rejected for Stage 1. A deny-by-default cloud/WORM backend remains a later migration behind the same release interface.
- **Scientific/statistical consequences:** The threat model prevents accidental or workflow-level inspection, including by AI, but does not claim protection from a machine administrator who can take ownership. Real OOS data is never used in CI; synthetic fixtures test both denial and controlled release.
- **Reproducibility and cost consequences:** Built-in Windows ACL, audit, and disk-encryption facilities have USD 0 incremental software cost when supported by the existing host. If the host cannot provide separate identities, NTFS ACLs, encryption, and audit evidence, the Stage 1 isolation gate fails rather than degrading to convention.
- **References:** [Windows file access control](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights), [Windows ACLs and auditing](https://learn.microsoft.com/en-us/windows/win32/secauthz/access-control-lists), [NIST least privilege](https://csrc.nist.gov/glossary/term/least_privilege), `DATA_ARCHITECTURE.md`, `VALIDATION_STANDARD.md`.
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through Stage 1A authorization dated 2026-09-04.

### DEC-0007 — Canonicalize Metadata and Hash All Immutable Evidence

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** architecture / reproducibility / data
- **Context:** Configurations, datasets, models, reports, and reruns need stable identity across machines and serializations.
- **Decision:** Use JSON Schema Draft 2020-12 for configurations, manifests, registries, and ledgers; reject duplicate keys, unknown schema versions, NaN/Infinity, and unresolved environment substitutions. Canonicalize valid JSON with RFC 8785 JCS to UTF-8 and identify it as `sha256:<lowercase-hex>`. Schema-governed decimal, money, quantity, and timestamp values use normalized strings (UTC RFC 3339 for timestamps); arrays retain order unless the schema explicitly declares set semantics and sorting. Raw payloads are hashed byte-for-byte. Tabular derived data uses Parquet with a deterministic schema and row-order rule; both physical files and a canonical lineage manifest are hashed. Models use non-executable formats where supported and always have a training/freeze manifest; pickle/joblib is not canonical and untrusted serialized code is never loaded. Markdown/JSON report sources are canonical evidence; rendered HTML/PDF and every other artifact receive exact-byte hashes and sidecars. Immutable objects live under `<artifact-root>/objects/sha256/<first-two>/<digest>` outside Git; small manifests may be committed.
- **Alternatives considered:** YAML has ambiguous typing and inconsistent canonicalization; TOML remains appropriate for `pyproject.toml` but not authoritative experiment evidence; hashing ordinary pretty JSON is whitespace-sensitive; BLAKE3 adds a dependency; DVC, MLflow, lakeFS, or an object database is premature. These are rejected for Stage 1.
- **Scientific/statistical consequences:** An experiment freeze manifest binds hypothesis/configuration, code revision, data lineage, environment, seeds, search budget, and criteria. `rerun EXP-…` resolves only that manifest and fails on any digest mismatch.
- **Reproducibility and cost consequences:** SHA-256 and JSON support are available without paid infrastructure. The environment manifest records Python build, OS/architecture, uv version, lock digest, and material native-library versions. Storage growth is controlled by content addressing and retention policy, never mutation.
- **References:** [RFC 8785 JCS](https://www.rfc-editor.org/rfc/rfc8785), [JSON Schema 2020-12](https://json-schema.org/draft/2020-12), [NIST SHA-256 standard](https://csrc.nist.gov/pubs/fips/180-4/upd1/final), `DATA_ARCHITECTURE.md`, `EXPERIMENT_LEDGER.md`.
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through Stage 1A authorization dated 2026-09-04.

### DEC-0008 — Adopt a Small, Strict Python Quality Gate

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** architecture / validation / operations
- **Context:** Stage 1 controls need repeatable local and CI enforcement without a large maintenance surface.
- **Decision:** Use Ruff for formatting and linting, mypy in strict mode for first-party code, pytest for tests, and coverage.py through pytest-cov with branch coverage. The merge gate is `uv lock --check`, `uv run --locked ruff format --check .`, `uv run --locked ruff check .`, `uv run --locked mypy src tests`, and `uv run --locked pytest --cov=quant_hunter --cov-branch --cov-fail-under=90`. Require 100% behavioral branch coverage for critical invariants: sealed-access denial/release, raw immutability, identifier collision/revision conflict, canonicalization/hash vectors, and freeze enforcement. Tests are deterministic and offline by default; network/integration tests are separately marked. The initial CI target is GitHub Actions with least-privilege permissions and third-party actions pinned to commit SHAs: one general Ubuntu quality job plus a focused Windows synthetic security job. The same commands remain provider-neutral and authoritative locally.
- **Alternatives considered:** Black + isort + Flake8 duplicates responsibilities; Pyright adds a Node toolchain; tox/nox adds orchestration before multiple environments exist; an unrestricted OS matrix and mandatory pre-commit hooks add cost/latency. These are rejected initially.
- **Scientific/statistical consequences:** Coverage is a floor, not evidence of correctness; invariant tests and review remain mandatory. Numerical tests use declared tolerances and fixed seeds rather than brittle exact equality where inappropriate.
- **Reproducibility and cost consequences:** All selected tools are open source. CI may run only within an existing free entitlement; no paid minutes, runner, or hosting plan is authorized. If CI is unavailable, local gate evidence is mandatory and the limitation remains recorded.
- **References:** [Ruff formatter](https://docs.astral.sh/ruff/formatter/), [pytest practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html), [mypy strict options](https://mypy.readthedocs.io/en/stable/command_line.html), [coverage.py branch measurement](https://coverage.readthedocs.io/en/latest/branch.html), [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use).
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through Stage 1A authorization dated 2026-09-04.

### DEC-0009 — Allocate Typed UUIDv7 IDs in Append-Only JSON Registries

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** architecture / governance / reproducibility
- **Context:** Sequential examples do not allocate safely across concurrent agents and make later database migration harder.
- **Decision:** New persistent objects use uppercase type prefixes plus a lowercase RFC 9562 UUIDv7: `FAM-<uuid>`, `MOD-<uuid>`, `STRAT-<uuid>`, `PATTERN-<uuid>`, `EXP-<uuid>`, `SOURCE-<uuid>`, `DATASET-<uuid>`, `BACKLOG-<uuid>`, and `COST-<uuid>`. IDs contain no status or mutable meaning and are never reused. Python 3.14 `uuid.uuid7()` is the allocator. An allocation exclusive-creates `registries/<kind>/<id>/v000001.json`; an improbable collision retries with a new UUID and is logged. Each later JCS record is a new zero-padded revision containing `previous_revision_digest`; compare-and-swap on that digest rejects stale concurrent writers. Schema validation, prefix/type checks, global duplicate scans, and revision-chain verification are merge gates. Generated Markdown/JSONL indexes are disposable views, never authority.
- **Alternatives considered:** Central sequential counters require locking and encourage merge conflicts; UUIDv4 lacks time locality; ULID/KSUID add dependencies; one mutable JSON file conflicts under parallel work; SQLite offers transactions but introduces a binary authority and review/migration overhead. They are rejected for the initial file-backed registry.
- **Scientific/statistical consequences:** Families, variants, data, patterns, failed experiments, and backlog items remain unambiguously traceable. New revisions cannot erase unfavorable history.
- **Reproducibility and cost consequences:** UUIDv7 is in the selected Python standard library and JSON files remain Git-reviewable; direct cost is USD 0. The schema and revision model map cleanly to a future relational or document database without changing permanent IDs.
- **References:** [RFC 9562 UUIDs](https://www.rfc-editor.org/rfc/rfc9562), [Python 3.14 `uuid7`](https://docs.python.org/3.14/library/uuid.html#uuid.uuid7), `MODEL_REGISTRY.md`, `EXPERIMENT_LEDGER.md`, `DATA_SOURCE_REGISTRY.md`, `PATTERN_DISCOVERY.md`.
- **Supersedes / superseded by:** Supersedes only the non-normative sequential ID examples in existing documentation; no allocated object exists to migrate.
- **Owner and approver:** Project owner, through Stage 1A authorization dated 2026-09-04.

### DEC-0010 — Define the Month-1 Budget Window and Liability Basis

- **Date:** 2026-09-04
- **Status:** ACCEPTED
- **Scope:** cost / governance
- **Context:** The USD 400 cap could not be enforced while the calendar window and pre-existing subscription treatment were ambiguous.
- **Decision:** Month 1 is the half-open interval `[2026-09-04T00:00:00-04:00, 2026-10-04T00:00:00-04:00)` in `America/New_York`. For each item, count the greatest known Month-1 liability: actual project usage/spend when final, otherwise the approved or committed maximum. Pre-existing fixed subscriptions materially used by Quant Hunter count by straight-line allocation of the actual invoiced total, including tax, over invoice service days overlapping the window; if service dates are unavailable, count the full invoice or renewal charged during the window. Project API usage, storage, egress, and cloud use count at actual usage plus any unavoidable commitment. Renewals, upgrades, one-time purchases, cancellation fees, and non-cancelable obligations created in the window count in full to the extent they can fall within the window. Convert non-USD costs using the documented transaction-card rate when known, otherwise a dated authoritative rate plus disclosed fees. `remaining = 400 - allocated baseline - sum(item liabilities)`; any unknown material amount makes remaining headroom `UNKNOWN`.
- **Alternatives considered:** Calendar September shortens the project's first month; starting at the first purchase can be gamed; excluding pre-existing subscriptions contradicts the all-in cap; counting every existing personal service regardless of project use overstates cost. These are rejected.
- **Scientific/statistical consequences:** No research result changes. Cost cannot silently select methods or data after results are known.
- **Reproducibility and cost consequences:** The decision itself costs USD 0 and authorizes no purchase. Until the owner supplies relevant invoice/service-period and project API usage facts, paid actions remain blocked even though zero-cost Stage 1B work may proceed after separate authorization.
- **References:** `BUDGET_LEDGER.md`, `PROJECT_CHARTER.md`, `AGENTS.md`.
- **Supersedes / superseded by:** None.
- **Owner and approver:** Project owner, through Stage 1A authorization dated 2026-09-04.

### DEC-0011 — Pin the Initial Stage 1B Toolchain and Public CI Profile

- **Date:** 2026-09-05
- **Status:** ACCEPTED
- **Scope:** architecture / reproducibility / operations / cost
- **Context:** Stage 1B Batch 1 requires the floating CPython 3.14 design to become an exact, reproducible toolchain. The host has CPython 3.14.3, while Python.org lists 3.14.7 as the current maintenance release. The repository is public, and GitHub's current billing documentation makes standard hosted runners free for public repositories.
- **Decision:** Pin standard GIL-enabled, 64-bit CPython 3.14.7 in `.python-version` and uv 0.12.10 in `uv.toml` and CI. Treat any Python patch or uv change as an explicit upgrade requiring a decision, lock regeneration, clean Windows and Ubuntu checks, and updated toolchain evidence. Use only standard `ubuntu-24.04` and `windows-2025` GitHub-hosted runners with `contents: read`, disabled uv caching, no artifact upload, and immutable action SHAs. Reassess and disable hosted CI before or when repository visibility or GitHub billing policy changes.
- **Alternatives considered:** Retaining host Python 3.14.3 would ignore available security and maintenance fixes. uv 0.12.0 passed archive verification but its managed-Python catalog could not install CPython 3.14.7; it was rejected for the project pin. Floating Python, uv, or action tags weaken reproducibility and supply-chain review. Larger or self-hosted runners add cost or security exposure and are rejected.
- **Scientific/statistical consequences:** The batch adds no research method or result. Exact toolchain identity reduces unexplained environment drift; future frozen experiments must bind their own environment evidence.
- **Reproducibility and cost consequences:** CPython, uv, Hatchling, Ruff, mypy, pytest, pytest-cov, coverage.py, and eligible standard public-repository Actions usage add USD 0 direct cost. The verified uv Windows archive SHA-256 and local executable SHA-256 are recorded in `DEVELOPMENT.md`. Budget headroom remains `UNKNOWN`; no purchase is authorized.
- **References:** `pyproject.toml`, `.python-version`, `uv.toml`, `uv.lock`, `.github/workflows/quality.yml`, `DEVELOPMENT.md`, `BUDGET_LEDGER.md`, `RISK_REGISTER.md`.
- **Supersedes / superseded by:** Implements DEC-0004, DEC-0005, and DEC-0008 without superseding their constraints.
- **Owner and approver:** Project owner, through Stage 1B Batch 1 authorization dated 2026-09-05.

## Remaining Inputs Before Paid Work

The seven Stage 1A design decisions are resolved. The following are factual inputs, not unresolved architecture choices:

- enter invoice amount and service dates for any pre-existing ChatGPT or other fixed subscription materially used by Quant Hunter;
- enter any project-attributable OpenAI API usage during the Month-1 window; and
- re-confirm public visibility and free standard-runner policy if repository visibility or GitHub billing policy changes; and
- retain the verified ephemeral exact-path Git trust method for `D:/quant-hunter`, or obtain owner approval for a persistent repository-specific ownership/trust correction; wildcard or silent global trust is prohibited.

Until the first two values are recorded, budget headroom remains `UNKNOWN` and no paid action is permitted. These factual inputs do not invalidate the design. Separately authorized, local, zero-cost Stage 1B work may use the verified exact-path Git method; hosted CI remains conditional on confirmed free entitlement.

### DEC-0012 — Correct Batch 2 Minimum Metadata Contracts

- **Date:** 2026-09-05
- **Status:** ACCEPTED
- **Scope:** governance / validation / reproducibility
- **Context:** Independent review identified missing normative metadata in the experiment and research-object schemas. No experiments, models, or strategies have been registered.
- **Decision:** Under the explicit Batch 2 Fix authorization, correct the two v1 foundation schemas in place and update their synthetic fixtures. This is a narrowly scoped exception to the retained-version policy in DEVELOPMENT.md: old incomplete synthetic records must be replaced, not silently accepted. No persistent research records require migration. Future incompatible changes still require a retained version and migration decision. Require explicit reason-bearing unavailable metadata; require concrete frozen definitions and a freeze-manifest reference from FROZEN onward. Preserve existing enums, typed identities, closed shapes, and revision constraints. Existing implementations require location and immutable code revision together; reproduction outcomes retain the methodology vocabulary.
- **Alternatives considered:** Leaving missing fields optional contradicts the normative minima. Creating a second schema generation before the foundation has registered records adds unnecessary migration surface.
- **Scientific/statistical consequences:** Record attempted search exposure including failed and AI attempts, evidence, sensitivities, provenance, decisions, and limitations. Counts and references are structural contracts only: cross-record consistency, digest verification, actual freeze transitions, and sealed-access enforcement remain deferred. No research evaluation or trading behavior is introduced.
- **Reproducibility and cost consequences:** Synthetic conformance tests use the existing lock and dependencies; no purchase or new paid commitment. Budget headroom remains unknown.
- **References:** EXPERIMENT_LEDGER.md Required Metadata and Lifecycle; MODEL_REGISTRY.md Minimum Record; RESEARCH_METHODOLOGY.md reproduction classifications; schemas/v1/experiment.schema.json; schemas/v1/research-object.schema.json; tests/test_schemas.py.
- **Supersedes / superseded by:** Narrow pre-use v1 correction exception only; no scientific standard superseded.
- **Owner and approver:** Project owner through explicit Stage 1B Batch 2 Fix request.

### DEC-0013 — Stage Registry Integrity Before General Canonicalization

- **Date:** 2026-09-05
- **Status:** ACCEPTED
- **Scope:** architecture / governance / reproducibility
- **Context:** Batch 3A authorizes typed identity and append-only registry behavior, while RFC 8785 canonicalization and reusable content hashing remain a separately gated Batch 3B. Revision compare-and-swap still needs an unambiguous prior-file identity.
- **Decision:** Implement DEC-0009's registry layout, UUIDv7 allocation, exclusive creation, revisions, compare-and-swap, duplicate scans, and chain verification in Batch 3A. Until Batch 3B, compute the private revision-chain digest as SHA-256 over the exact stored UTF-8 revision-file bytes. Do not expose this helper as general artifact, configuration, dataset, or freeze-manifest hashing. No real research record may be created in this batch; tests use temporary synthetic records only. A caller may inject its governed schema validator, while the core always owns and validates the typed ID, revision number, prior digest, finite JSON encoding, and path placement. Generated indexes are explicitly non-authoritative and disposable.
- **Alternatives considered:** Implementing JCS early would cross the Batch 3B boundary. Omitting a digest would make stale-writer rejection and chain verification impossible. Mutable latest-record files and in-place locking were rejected by DEC-0009.
- **Scientific/statistical consequences:** Concurrent writers cannot silently fork one object's history, and rejected or failed revisions remain present. Exact-file hashing is limited to registry history integrity and makes no claim that arbitrary JSON is canonically equivalent.
- **Reproducibility and cost consequences:** The implementation uses the Python 3.14 standard library and the existing locked test toolchain at USD 0 direct cost. Batch 3B must add and validate RFC 8785 behavior before any real record is admitted and must preserve any existing revision bytes rather than rewrite history.
- **References:** DEC-0007, DEC-0009, `ARCHITECTURE.md`, `ROADMAP.md` Stage 1B items 5–6, `src/quant_hunter/identity/`, and `tests/test_registry.py`.
- **Supersedes / superseded by:** Stages, and does not supersede, DEC-0007 or DEC-0009.
- **Owner and approver:** Project owner through explicit Stage 1B Batch 3A authorization dated 2026-09-05.
