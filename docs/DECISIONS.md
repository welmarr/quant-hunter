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

### DEC-0014 — Use a Pinned RFC 8785 Implementation for Canonical Identity

- **Date:** 2026-09-05
- **Status:** ACCEPTED
- **Scope:** architecture / validation / reproducibility
- **Context:** Batch 3B authorizes DEC-0007 canonicalization and hashing. Python's standard JSON encoder does not implement RFC 8785 number serialization or UTF-16 property ordering, and a local partial serializer would create a high-risk identity contract.
- **Decision:** Pin the small, pure-Python, Apache-2.0 `rfc8785` package at 0.1.4 for JCS serialization. Wrap it with strict project ingestion that rejects duplicate object keys, NaN/Infinity, invalid Unicode, unresolved `${...}` tokens, integers outside the interoperable IEEE 754 safe range, non-string keys, and non-JSON values. Keep exact-byte SHA-256 and canonical-JSON SHA-256 as separate public contracts using `sha256:<64 lowercase hex>`. New registry revisions use JCS, while chain validation continues to hash exact stored revision bytes so history is never rewritten. Governed registry writes require the existing versioned JSON Schemas and fail closed for unmapped kinds; a named synthetic-only constructor isolates low-level registry tests. Freeze-manifest construction binds the DEC-0007 inputs but performs no lifecycle or sealed-data action.
- **Alternatives considered:** `json.dumps(sort_keys=True)` is not JCS. A custom ECMAScript binary64 serializer is rejected as an unnecessary correctness risk. Silent normalization of historical registry files would violate append-only history. Duplicating registry validation rules outside the schemas would create drift.
- **Scientific/statistical consequences:** Canonically equivalent metadata has one stable identity, malformed inputs fail before hashing, and freeze inputs can be bound deterministically. This adds no model, data, experiment execution, sealed release, or trading behavior.
- **Reproducibility and cost consequences:** RFC 8785 examples and Appendix B vectors verify the dependency under pinned CPython 3.14.7. The dependency and its source are recorded in `uv.lock`; direct cost is USD 0. JSON Schema runtime packages move from development-only classification because governed writes now require them. No service or paid commitment is introduced.
- **References:** DEC-0007, DEC-0008, DEC-0009, DEC-0013, RFC 8785, `pyproject.toml`, `uv.lock`, `src/quant_hunter/config/`, `src/quant_hunter/provenance/`, and the JCS/freeze/governed-registry tests.
- **Supersedes / superseded by:** Completes the Batch 3B transition required by DEC-0013 without changing its exact-file history rule.
- **Owner and approver:** Project owner through explicit Stage 1B Batch 3B authorization dated 2026-09-05.

### DEC-0015 — Publish Exact-Byte Objects Through Exclusive Atomic Links

- **Date:** 2026-09-05
- **Status:** ACCEPTED
- **Scope:** architecture / data / security / reproducibility
- **Context:** Batch 4A requires complete immutable objects on both Windows and Ubuntu without allowing POSIX rename-overwrite behavior, partial final files, or caller-selected authoritative paths.
- **Decision:** Derive every final object path internally as `<artifact-root>/objects/sha256/<first-two>/<64-hex-digest>`. Write and `fsync` a unique staging file in the final object's directory, verify its exact-byte digest, and finalize with an exclusive same-filesystem hard link. A concurrent `FileExistsError` succeeds only after the existing final bytes verify against the derived digest; mismatched bytes are corruption and are never replaced. Staging names are non-authoritative and are removed after success or failure. Require an absolute non-root local artifact path, reject lexical traversal, and inspect existing root/object components for symbolic links and Windows reparse points before and after directory creation where portable filesystem APIs permit. Verified lookup, read, and verification repeat object-component inspection immediately before opening the final file. Portable path checks have an unavoidable check-to-use race and make no administrator-resistant claim. The object API has publish, verified lookup/read, and verification operations but no mutation, replacement, or deletion operation.
- **Alternatives considered:** `os.replace` can overwrite a valid object and conflicts with exclusive publication. Direct final-path writes can expose partial content. A lock file adds stale-lock recovery without eliminating corruption verification. An object database, S3, DVC, MLflow, and lakeFS remain premature and outside the local-first scope.
- **Scientific/statistical consequences:** Raw provider payloads retain exact received-byte identity. Corrections create new objects, identical payloads may deduplicate physically, and separate canonical capture metadata preserves distinct provenance and quarantine states. Artifact manifests explicitly bind physical digest, byte size, media type, producer, sources, datasets, references, and configuration. Batch 4A adds a pre-use v1 raw-capture schema and requires provenance in the generic artifact manifest; no scientific records require migration.
- **Reproducibility and cost consequences:** The implementation uses only the Python 3.14 standard library and existing locked dependencies. Direct cost is USD 0. Atomic hard-link creation is exercised locally on Windows and is supported by the governed Ubuntu filesystem profile; hosted cross-platform results remain subject to independent CI review.
- **References:** DEC-0007, DEC-0008, DATA_ARCHITECTURE.md, ARCHITECTURE.md, ROADMAP.md item 7, `schemas/v1/artifact-manifest.schema.json`, `schemas/v1/raw-capture.schema.json`, `src/quant_hunter/storage/`, and storage/raw-capture tests.
- **Supersedes / superseded by:** Implements only Batch 4A. Batch 4B remains responsible for the derived-data and point-in-time half of roadmap item 7.
- **Owner and approver:** Project owner through explicit Stage 1B Batch 4A authorization dated 2026-09-05.

### DEC-0016 — Separate Derived Physical, Lineage, and Logical Identities

- **Date:** 2026-09-05
- **Status:** ACCEPTED
- **Scope:** architecture / data / reproducibility / cost
- **Context:** DEC-0007 requires deterministic Parquet and three identities with different meanings. A byte digest cannot establish logical equivalence, while a content fingerprint cannot prove the exact physical object or its scientific provenance. Batch 4B.1 also requires a maintained Parquet implementation with pinned CPython 3.14 support rather than a local file-format implementation.
- **Decision:** Pin Apache-2.0 `pyarrow==25.0.1`, which publishes CPython 3.14 Windows and manylinux wheels, and admit only an explicit supported logical Arrow type set. Reject schema inference mismatches, schema/field metadata, ambiguous timestamps, unsupported/nested types, invalid non-null fields, and non-finite floats. Write Parquet only through a complete versioned profile that passes every material PyArrow option explicitly and binds the exact library version. Define the physical digest as exact final Parquet bytes. Define the logical fingerprint as SHA-256 over a versioned, length-framed, platform-independent stream containing the JCS logical schema and type-tagged normalized rows; ordered rows retain order, while unordered rows sort by canonical framed bytes without removing duplicates. Define the lineage digest as SHA-256 over a closed JCS manifest containing physical/artifact identities, full parent evidence under declared ordering, transformation/configuration, code, environment, logical schema/fingerprint, writer profile, sources/references, creation time, and quality. The lineage manifest omits its own digest. Publish Parquet, artifact sidecars, and lineage bytes through the existing immutable object store. Validate existing v1 dataset records and their three fields against this evidence rather than creating a second dataset vocabulary.
- **Alternatives considered:** A custom Parquet writer is rejected as unsafe and unnecessary. pandas is not added because Arrow primitives are sufficient. Hashing Parquet-decoded rows without the schema would erase nullability, precision, and timestamp distinctions. JCS rows cannot represent full int64 values without loss and canonicalizes negative zero, so the logical content stream uses explicit binary framing and type-specific canonical values while the logical schema and lineage remain JCS. Treating unordered rows as a set would lose duplicate multiplicity. Reusing the generic artifact manifest as the complete lineage record would conflate physical packaging with scientific production history.
- **Scientific/statistical consequences:** Equal logical fingerprints mean the governed schema and normalized row multiset/sequence are equal under the declared semantics; they do not mean the files or provenance are equal. Any parent, transformation/configuration, code, environment, schema, ordering, writer, physical artifact, source/reference, creation-time, or quality change alters lineage. This batch introduces no point-in-time selection or empirical data.
- **Reproducibility and cost consequences:** PyArrow 25.0.1 and all wheel hashes are locked in `uv.lock`; its direct monetary cost is USD 0. Local repeated writes on pinned Windows reproduce exact bytes. Exact equivalence across Arrow versions, other Parquet libraries, CPUs, or Windows/Ubuntu is not claimed until measured; physical digests always identify observed bytes, while logical fingerprints remain independent of Parquet encoding. Hosted Ubuntu and Windows CI provide the next independent environment evidence.
- **References:** DEC-0007, DEC-0008, DEC-0015, `DATA_ARCHITECTURE.md`, `ROADMAP.md` item 7, `schemas/v1/dataset.schema.json`, `schemas/v1/dataset-lineage-manifest.schema.json`, `src/quant_hunter/data/`, [Apache Arrow installation and Python support](https://arrow.apache.org/docs/python/install.html), [Apache Arrow 25.0.1 release artifacts](https://arrow.apache.org/install/), and [PyArrow package metadata](https://pypi.org/project/pyarrow/).
- **Supersedes / superseded by:** Implements Batch 4B.1 only. Batch 4B.2 retains all point-in-time, as-of, future-publication, revision/vintage, and normalized/curated selection obligations.
- **Owner and approver:** Project owner through explicit Stage 1B Batch 4B.1 authorization dated 2026-09-05.

### DEC-0017 — Reject Semantically Contradictory Immutable Provenance

- **Date:** 2026-09-05
- **Status:** ACCEPTED
- **Scope:** data / provenance / reproducibility
- **Context:** Independent review found that artifact, lineage, dataset-record, and raw-capture evidence could each be schema-valid and internally hash-consistent while disagreeing on duplicated scientific provenance. Valid individual digests do not establish that the evidence set describes one production event.
- **Decision:** Verification must validate every supplied manifest against its existing schema and require exact semantic agreement for every claim represented in more than one object. Derived artifact and lineage evidence agree on physical identity, creation time, producer code/environment, source sequence, normalized parent dataset and physical-digest sequences, references, and configuration. Dataset records agree with the verified lineage/evidence on identifiers, creation time, layer, sources, all three identities, parents, transformation, code/environment, and quality; lineage verification binds row ordering and transformation configuration even where the dataset schema does not duplicate those fields. Raw metadata and artifact evidence agree on payload identity/size, media type, ingestion/creation time, source, dataset, and the publication-defined deduplicated endpoint/request-reference sequence. Raw configuration remains owned by the artifact manifest and is bound by the metadata's artifact-manifest digest. Do not add redundant schema fields solely to duplicate an already digest-bound claim. Preserve exact sequence order and existing deduplication rules.
- **Alternatives considered:** Accepting independently valid objects permits provenance substitution. Comparing source or parent identifiers as unordered sets would erase governed sequence semantics. Expanding schemas with redundant fields would add drift without additional integrity when a canonical manifest digest already binds the claim.
- **Scientific/statistical consequences:** A verifier rejects mixed evidence from different synthetic production events even when every object is otherwise valid. The physical, lineage, and logical identity definitions remain unchanged. No point-in-time/as-of behavior or empirical data is introduced.
- **Reproducibility and cost consequences:** Focused negative tests rebuild schema-valid canonical evidence with correct replacement digests before asserting rejection. The change uses existing dependencies and has USD 0 direct cost.
- **References:** DEC-0007, DEC-0015, DEC-0016, `DATA_ARCHITECTURE.md`, `schemas/v1/artifact-manifest.schema.json`, `schemas/v1/dataset-lineage-manifest.schema.json`, `schemas/v1/dataset.schema.json`, `schemas/v1/raw-capture.schema.json`, `src/quant_hunter/data/derived.py`, `src/quant_hunter/storage/raw.py`, and the derived/raw provenance tests.
- **Supersedes / superseded by:** Hardens Batch 4B.1 without changing its three-identity contract. Batch 4B.2 remains separately gated and unstarted.
- **Owner and approver:** Project owner through explicit Stage 1B Batch 4B.1 provenance-integrity hardening authorization dated 2026-09-05.

### DEC-0018 — Bind Explicit As-Of and Vintage Policy into Derived Lineage

- **Date:** 2026-09-06
- **Status:** ACCEPTED
- **Scope:** data / point-in-time correctness / reproducibility
- **Context:** Roadmap item 7 requires historical information sets to distinguish event, publication, ingestion, and revision times without using incidental row order or latest-provider values. The existing dataset and lineage schemas already govern derived identities, parents, and transformation configuration, but a complete PIT selection policy needs its own closed, reviewable configuration.
- **Decision:** Add a pre-use v1 PIT-selection configuration schema rather than duplicate dataset or lineage vocabulary. Require an explicit exact UTC `as_of`, generic observation-key and vintage-ID columns, distinct temporal columns, explicit PUBLIC or OPERATIONAL mode, revision status, fixed eligibility and latest-eligible-vintage rules, fail-closed ambiguity, and canonical output ordering. PUBLIC requires publication and applicable revision no later than `as_of`; OPERATIONAL additionally requires ingestion no later than `as_of`. Event time never serves as the public-availability boundary. Missing or future required times create deterministic exclusions, `REQUIRED_UNKNOWN` cannot masquerade as an initial value, and equal winning availability priorities fail closed. Publish only normalized or curated selections through the existing derived-data path with exactly one configured parent; store and reference canonical configuration and audit evidence, and use the configuration digest as the transformation-configuration identity.
- **Alternatives considered:** A single effective timestamp would erase governing semantics. Choosing the latest input row or arbitrary vintage ID would make results order-dependent. Adding PIT fields to the dataset or lineage schemas would duplicate digest-bound configuration and create drift. A general query engine, source-specific key, or mutable materialized view exceeds item 7.
- **Scientific/statistical consequences:** Exact equality at the `as_of` boundary is eligible while one nanosecond later is future information. Earlier queries reconstruct earlier immutable vintages after later revisions arrive. PUBLIC and OPERATIONAL views remain explicit and reproducible. Different policy/configuration digests produce different lineage while equal selected rows may retain the same logical fingerprint. The physical, lineage, and logical identity definitions from DEC-0016 are unchanged.
- **Reproducibility and cost consequences:** Selection and exclusion evidence uses existing JCS, SHA-256, Arrow, deterministic Parquet, schema validation, and immutable publication. Tests are offline and synthetic. No dependency, service, data, or paid commitment is added; direct incremental cost is USD 0.
- **References:** DEC-0007, DEC-0015–DEC-0017, `DATA_ARCHITECTURE.md`, `ROADMAP.md` item 7, `schemas/v1/pit-selection-config.schema.json`, `src/quant_hunter/data/pit.py`, and `tests/test_pit.py`.
- **Supersedes / superseded by:** Completes the Batch 4B.2 implementation portion of roadmap item 7 without superseding existing provenance or identity contracts. Item 8 remains separately gated and unstarted.
- **Owner and approver:** Project owner through explicit Stage 1B Batch 4B.2 authorization dated 2026-09-06.

### DEC-0019 — Bind PIT Inputs and Selected Content End to End

- **Date:** 2026-09-06
- **Status:** ACCEPTED
- **Scope:** data / provenance / reproducibility
- **Context:** Independent review found that a dataset ID alone did not prove the table supplied to PIT selection was the immutable parent later cited by publication, while selected vintage IDs and keys did not bind non-key selected values.
- **Decision:** Add a narrow typed PIT input-evidence record containing the existing five-field `ParentEvidence`, declared logical schema digest, and explicit parent row-ordering semantics. Selection must recompute the supplied input table's existing logical-content fingerprint under that schema/order and match the parent claim. The immutable PIT audit binds that complete input evidence, the configuration digest, the selected table's existing logical-content fingerprint under its declared derived ordering, and selected/excluded vintage accounting. Publication and later verification require exact equality of all parent evidence fields and require the published derived logical identity and ordering to match the selection audit. Do not change the temporal algorithm or any physical, lineage, or logical identity definition.
- **Alternatives considered:** Recomputing every parent as unordered would make a false claim when parent ordering is meaningful. Matching only dataset ID or logical fingerprint would omit immutable revision, physical, or lineage identity. Adding a broad catalog or a cosmetic audit schema would exceed the narrow fix.
- **Scientific/statistical consequences:** A table cannot be selected under one logical parent and published against another revision, physical object, lineage, or logical-content claim with the same dataset ID. Altering a non-key selected value invalidates the result and cannot be published under the original audit.
- **Reproducibility and cost consequences:** The change reuses existing Arrow logical schema/fingerprint, JCS, SHA-256, immutable storage, and lineage contracts. It adds no dependency, service, data, infrastructure, or paid commitment; direct incremental cost is USD 0.
- **References:** DEC-0016–DEC-0018, `DATA_ARCHITECTURE.md`, `ROADMAP.md` item 7, `src/quant_hunter/data/pit.py`, and `tests/test_pit.py`.
- **Supersedes / superseded by:** Hardens DEC-0018 without changing PIT science. Item 7 remains in review-fix status pending independent review; item 8 remains unstarted.
- **Owner and approver:** Project owner through explicit Stage 1B Batch 4B.2 review-fix authorization dated 2026-09-06.

### DEC-0020 — Verify PIT Transformation Semantics by Deterministic Replay

- **Date:** 2026-09-06
- **Status:** ACCEPTED
- **Scope:** data / provenance / reproducibility
- **Context:** Rehashing a modified selected table and its audit can restore internal hash consistency without proving that the governed PIT algorithm produced that table from the exact bound input.
- **Decision:** Publication and published-evidence verification must receive the exact input table explicitly, verify it against the existing `PitInputEvidence`, rerun the unchanged PIT selection algorithm with the bound configuration, and compare the complete selected Arrow table, selected vintage IDs, exclusions, input-row accounting, selected logical fingerprint, and canonical audit evidence. Do not retain a duplicate input payload inside `PitSelectionResult`; callers must supply the verified immutable input material when establishing transformation correctness.
- **Alternatives considered:** Another self-declared digest would only restore hash consistency. Retaining the complete parent table inside every result duplicates potentially large data. A general query engine or recursive provenance-DAG verifier exceeds this review fix.
- **Scientific/statistical consequences:** A fully canonical, correctly rehashed forged selection still fails unless deterministic replay from the exact input produces identical output and dispositions. Event/publication/ingestion/revision semantics, PUBLIC/OPERATIONAL policy, vintage priority, equality boundaries, and ambiguity behavior are unchanged.
- **Reproducibility and cost consequences:** The replay uses existing deterministic Arrow and PIT contracts and adds no dependency. Its incremental direct cost is USD 0. Separately, the owner-reported USD 10 Codex-credit purchase is recorded as spent in `BUDGET_LEDGER.md`; unresolved baseline costs keep headroom unknown.
- **References:** DEC-0018, DEC-0019, `DATA_ARCHITECTURE.md`, `BUDGET_LEDGER.md`, `ROADMAP.md` item 7, `src/quant_hunter/data/pit.py`, and `tests/test_pit.py`.
- **Supersedes / superseded by:** Extends DEC-0019 from evidence identity to deterministic transformation verification. Item 7 remains in final-review-fix status pending independent review; item 8 remains unstarted.
- **Owner and approver:** Project owner through explicit final Stage 1B Batch 4B.2 review-fix authorization dated 2026-09-06.

### DEC-0021 — Bind Experiment Freeze to the Exact Registered Revision

- **Date:** 2026-09-06
- **Status:** ACCEPTED
- **Scope:** governance / methodology / reproducibility
- **Context:** The generic DEC-0007 freeze manifest bound an experiment ID and reproduction inputs but did not identify the exact append-only `REGISTERED` registry revision. A lifecycle label alone also cannot distinguish a complete preregistration from a draft containing placeholders or observed outcomes.
- **Decision:** Item 8A introduces a typed service around the existing governed `RegistryStore` for only `DRAFT → REGISTERED → FROZEN`. Callers supply every transition timestamp. Registration requires concrete scientific plans, exact datasets and vintages, result-free and decision-free evidence, zero attempted variants, and a multiple-testing budget covering planned variants. Freeze binds the exact `REGISTERED` revision digest and derives configuration, code, environment, search/multiple-testing budget, criteria, baselines, and seeds from that immutable revision. Supplied data-manifest references must carry the exact preregistered provenance digests. Canonical freeze bytes are published through the existing immutable object store, and the next registry revision references their digest without circularity.
- **Alternatives considered:** A second experiment ledger would compete with the governed registry. Binding only the experiment ID permits a different revision to reuse freeze evidence. Accepting `UNKNOWN` or `PENDING` scientific plans would make registration cosmetic. Reading sealed data to validate a reference would cross the separately gated release boundary.
- **Scientific/statistical consequences:** Skipped, backward, repeated, stale, result-bearing, decision-bearing, malformed, and identity-mismatched transitions fail closed. Frozen scientific assumptions remain exactly recoverable from the registered revision and cannot be silently rewritten under the same freeze evidence. No experiment execution, observed result, runtime multiple-testing counter, or sealed-data access is introduced.
- **Reproducibility and cost consequences:** The change reuses the experiment schema, UUIDv7 identity, append-only JCS registry, SHA-256, generic freeze manifest, and immutable object store. It adds no dependency, service, data, infrastructure, or incremental direct project cost. The existing owner-reported USD 10 prepaid Codex-credit purchase remains the only known Month-1 spend and is not counted twice.
- **References:** DEC-0007, DEC-0009, DEC-0020, `EXPERIMENT_LEDGER.md`, `ROADMAP.md` item 8, `schemas/v1/experiment.schema.json`, `src/quant_hunter/experiments/lifecycle.py`, and `src/quant_hunter/provenance/freeze.py`.
- **Supersedes / superseded by:** Extends the generic freeze foundation without replacing any registry or artifact authority. Later item-8 controls remain separately gated.
- **Owner and approver:** Project owner through explicit Stage 1B Item 8A authorization dated 2026-09-06.

### DEC-0022 — Compare Lifecycle Timestamps at Full Accepted Precision

- **Date:** 2026-09-06
- **Status:** ACCEPTED
- **Scope:** governance / methodology / reproducibility
- **Context:** The common timestamp schema accepts UTC RFC 3339 fractions of arbitrary length, while Python `datetime` retains only microseconds. Comparing parsed `datetime` values could therefore treat a sub-microsecond backward transition as equality.
- **Decision:** Parse lifecycle timestamp components with the existing strict UTC shape, validate their calendar and whole-second components with the standard library, and compare the fractional component as an exact standard-library `Decimal`. Preserve every accepted digit without float conversion, rounding, truncation, or a dependency on point-in-time data code. Continue allowing exact equality.
- **Alternatives considered:** Limiting the common schema to six or nine fractional digits would be a broad semantic change. Float timestamps and `datetime` microseconds are lossy. Importing PIT timestamp machinery would create an inappropriate experiment-to-data dependency.
- **Scientific/statistical consequences:** `created_at ≤ registered_at ≤ frozen_at` now holds for the full precision accepted by the governed schema, including beyond nanoseconds. No preregistration, multiple-testing, result exclusion, freeze binding, immutable storage, or sealed-data rule changes.
- **Reproducibility and cost consequences:** The correction uses only the Python standard library, adds no dependency, and costs USD 0 incrementally. The existing USD 10 prepaid Codex purchase is not counted again.
- **References:** DEC-0021, `EXPERIMENT_LEDGER.md`, `schemas/v1/common.schema.json`, `src/quant_hunter/experiments/lifecycle.py`, and `tests/test_experiment_lifecycle.py`.
- **Supersedes / superseded by:** Corrects only timestamp ordering within Item 8A. Item 8A remains in review-fix status pending independent review; Item 8B remains unstarted.
- **Owner and approver:** Project owner through explicit Stage 1B Item 8A review-fix authorization dated 2026-09-06.

### DEC-0023 — Derive Runtime Exposure Counters from Append-Only Attempt Evidence

- **Date:** 2026-09-06
- **Status:** ACCEPTED
- **Scope:** governance / methodology / reproducibility
- **Context:** Item 8A froze planned search exposure but did not provide a `RUNNING` edge or auditable runtime evidence behind cumulative attempt counters. Mutable counters alone could omit failures, retries, or AI-generated work and could lose increments under concurrent writers.
- **Decision:** Item 8B extends the existing lifecycle service and governed experiment revision chain through only `FROZEN → RUNNING`. Starting independently verifies the chain, exact `REGISTERED` predecessor, immutable freeze object and digest, reconstructed manifest, unchanged scientific record, and caller-owned CAS head. The caller supplies `started_at`; exact accepted precision enforces `frozen_at ≤ started_at`. Each actual exposure appends one cumulative typed attempt record with deterministic sequence and experiment identity, caller-supplied nondecreasing recording time, AI and failure flags, an exposure reason, an optional immutable variant-configuration digest, and an optional earlier-attempt retry link. Total, AI, and failed counters are recomputed from retained evidence. The frozen multiple-testing budget is an immutable upper bound, and exhausted attempts fail before append. Schema v1 is corrected before real use to govern `started_at`, attempt records, and result-free `RUNNING` records; no persistent experiments require migration.
- **Alternatives considered:** A second attempt database would compete with the experiment registry. Caller-replaced counters could lose or rewrite exposure. Counting successful outputs would omit failures and retries. A process-local lock would weaken existing cross-process CAS. A scheduler or execution engine exceeds Item 8B.
- **Scientific/statistical consequences:** Human or ordinary algorithm-generated work is represented by a false AI flag; AI-generated and failed attempts may overlap while each contributes exactly once to total exposure. Retries are new exposure linked to retained history. Runtime revisions cannot change frozen hypothesis, data, partitions, feature/label definitions, candidate universe, search space, planned variants, multiple-testing plan, tests, metrics, baselines, costs, criteria, code/configuration/environment bindings, or freeze digest. `RUNNING` cannot contain final results or a decision and does not read or release sealed OOS data.
- **Reproducibility and cost consequences:** The change reuses the existing schema catalog, JCS/SHA-256 registry chain, immutable object store, exact timestamp parser, and filesystem CAS. It adds no dependency, paid service, data, infrastructure, or incremental direct cost. The owner-reported USD 10 prepaid Codex purchase is not counted again.
- **References:** DEC-0007, DEC-0009, DEC-0021, DEC-0022, `EXPERIMENT_LEDGER.md`, `ROADMAP.md` item 8, `schemas/v1/experiment.schema.json`, `src/quant_hunter/experiments/lifecycle.py`, and `tests/test_experiment_lifecycle.py`.
- **Supersedes / superseded by:** Extends Item 8A without replacing its registry, freeze, or timestamp authority. Item 8B remains in review. Item 8C and Item 9 remain separately gated and unstarted.
- **Owner and approver:** Project owner through explicit Stage 1B Item 8B authorization dated 2026-09-06.

### DEC-0024 — Retain Evaluation Evidence in the Experiment Revision Chain

- **Date:** 2026-09-06
- **Status:** ACCEPTED
- **Scope:** governance / methodology / reproducibility
- **Context:** Item 8B ended at a verified RUNNING history. Evaluation and decision evidence must remain permanent without adding a mutable results database, while deterministic rerun resolution must recover only preregistered scientific inputs and must never execute research or treat observed outcomes as inputs.
- **Decision:** Item 8C extends the existing lifecycle authority through only `RUNNING → EVALUATED → DECIDED`. Evaluation re-verifies the complete freeze and attempt history, requires a full-precision caller-supplied timestamp after the latest runtime evidence, and stores a typed positive, negative, null, failed, or inconclusive outcome, nonempty result summary, failure modes, and paired artifact digest/location evidence in the append-only JCS experiment revision. When no external artifact exists, the revision records an explicit reason. Supplied digests must resolve to intact bytes in the existing immutable object store. Decision re-verifies the EVALUATED predecessor, requires a full-precision caller-supplied timestamp, governed vocabulary, and explicit reason, and permits no change to observed, failure, attempt, frozen, or sealed-release evidence. Schema v1 is corrected before real use for evaluation/decision timestamps and typed outcomes; no persistent experiment requires migration. A deterministic resolver verifies FROZEN-or-later history and canonicalizes only REGISTERED/FROZEN reproduction inputs and identities. It neither reads sealed contents nor executes or creates an experiment.
- **Alternatives considered:** A separate results database or decision store would create competing mutable authority. A redundant evaluation manifest adds no integrity beyond the exact append-only registry revision. Deriving decisions from metrics would replace explicit research judgment with automation. Including results or decisions in rerun inputs would turn observations into methodology. Creating a new EXP record during resolution would conflate deterministic lookup with separately governed execution.
- **Scientific/statistical consequences:** Positive, negative, failed, null, invalidated, deferred, rejected, and inconclusive histories remain permanent. Failed evaluation requires retained failure evidence even without a successful artifact. Corrections after observation require a new permanent `EXP-<uuidv7>` linked through `earlier_experiment_ids`. No decision grants paper trading, deployment, broker access, or live-capital authority. The existing sealed-release reference is preserved exactly; Item 8C does not implement or invoke release infrastructure.
- **Reproducibility and cost consequences:** Rerun resolution returns stable canonical bytes and `sha256:<lowercase-hex>` identity for the exact experiment, REGISTERED revision, FROZEN revision and manifest, code/configuration/environment, data manifests, seeds or not-applicable reason, search/multiple-testing budget, criteria, and baselines. It reuses existing JCS, SHA-256, registry CAS, freeze, and object-store code without a dependency or paid service. Incremental direct cost is USD 0; the existing owner-reported USD 10 prepaid Codex purchase is not counted again.
- **References:** DEC-0007, DEC-0009, DEC-0021–DEC-0023, `EXPERIMENT_LEDGER.md`, `ROADMAP.md` item 8, `schemas/v1/experiment.schema.json`, `src/quant_hunter/experiments/lifecycle.py`, and `tests/test_experiment_lifecycle.py`.
- **Supersedes / superseded by:** Extends the reviewed Item 8B lifecycle without replacing its experiment, attempt, freeze, timestamp, registry, or object authority. Item 8C remains in review; full Item 8 is not complete until that review passes. Item 9 remains separately gated and unstarted.
- **Owner and approver:** Project owner through explicit Stage 1B Item 8C authorization dated 2026-09-06.

### DEC-0025 — Use Exact Half-Open Boundaries for Temporal Validation

- **Date:** 2026-09-07
- **Status:** ACCEPTED
- **Scope:** methodology / validation / reproducibility
- **Context:** The experiment schema requires explicit UTC partition starts and ends, but the governing documents did not state whether boundary instants were included. Item 9A needs one deterministic interpretation before any real validation plan exists.
- **Decision:** Every Item 9A temporal interval is nonempty and half-open: `[start, end)`, with the start included and the end excluded. Exact equality between one interval's end and the next interval's start is valid non-overlapping adjacency. Parse the existing strict UTC timestamp shape, validate calendar values, and compare every fractional-second digit exactly without float conversion or microsecond/nanosecond truncation. Top-level roles must remain ordered TRAINING/DEVELOPMENT → VALIDATION → SEALED OUT-OF-SAMPLE. Explicit folds declare their sequence and identity; input ordering cannot define chronology. Purge and embargo evidence uses exact excluded intervals or a nonempty reason for non-applicability. Plan evidence uses existing JCS and SHA-256 primitives and remains metadata-only; sealed references are never dereferenced.
- **Alternatives considered:** Closed boundaries make adjacent partitions share an instant. Inferring an epsilon or a bar duration silently assumes a sampling frequency. Importing the private experiment-lifecycle timestamp helper would couple separate authorities.
- **Scientific/statistical consequences:** Boundary adjacency and overlap now have one testable meaning at all accepted timestamp precision. These contracts reject obvious temporal contradictions but do not prove label independence or choose sufficient purge/embargo sizes; a later authorized execution layer must derive those from the registered label horizon, feature dependencies, and sampling structure.
- **Reproducibility and cost consequences:** Canonical plans have deterministic bytes and `sha256:<64 lowercase hex>` identity under the existing local dependencies. No dependency, service, data, infrastructure, or incremental direct cost is added. The owner-reported ChatGPT Pro amount remains unknown pending invoice reconciliation.
- **References:** `VALIDATION_STANDARD.md`; `EXPERIMENT_LEDGER.md`; `schemas/v1/experiment.schema.json`; `src/quant_hunter/validation/temporal.py`; `tests/test_temporal_validation.py`.
- **Supersedes / superseded by:** Clarifies previously unspecified interval boundaries without changing the reviewed Item 8 experiment/freeze authority. Item 9B, Item 9C, and Item 10 remain separately gated.
- **Owner and approver:** Project owner through explicit Stage 1B Item 9A authorization dated 2026-09-07.

### DEC-0026 — Declare Scientific Evidence Without Executing It

- **Date:** 2026-09-07
- **Status:** ACCEPTED
- **Scope:** methodology / validation / reproducibility
- **Context:** Item 9A governs temporal-validation metadata, while Stage 1 also needs explicit preregistered coverage of baselines, metrics, statistical methods, multiple testing, sample adequacy, robustness, and future reporting. Missing or unfavorable requirements must not disappear, but Item 9B is not authorized to calculate evidence or replace the Item 8 experiment authority.
- **Decision:** Add immutable Item 9B evidence plans with explicit `REQUIRED` or reason-bearing `NOT_APPLICABLE` declarations. Require applicability for naive, simple, and established-reference baseline roles; every standard reporting metric; every governed statistical/anti-overfitting method; and every governed sample/robustness category. Permit identified custom metrics and baselines only in addition to that inventory. Store study-specific reporting conventions and exact configuration settings, using normalized decimal text rather than binary floats for canonical numeric evidence. Cross-check family, budget, and correction plan against supplied `FROZEN` Item 8 metadata and retain its exact revision digest, while leaving all runtime counters and attempt history in Item 8. Reports preserve positive, negative, null, failed, inconclusive, and narrowly pending outcomes; assess the authoritative V0–V9 gates, including V5 search adjustment; require support references for `PASS`; and identify Item 8 as the sole decision authority. Pending observations are narrative-only, `NOT_YET_EVALUATED` and report-level `PENDING` occur together, and `VALIDATED` rejects a `FAIL` or `PENDING` gate, pending or failed required evidence, or a failed report outcome. Negative, null, and inconclusive completed evidence does not by itself prevent validation. Sealed-OOS reports require a release-evidence reference but label it unverified and never access its target.
- **Alternatives considered:** Missing declarations would let unfavorable requirements disappear. Requiring every method to run mechanically would contradict the governing methodology. A parallel attempt counter, results state machine, or evidence registry would compete with Item 8. Binary floats would weaken canonical numeric evidence. Implementing formulas or backtesting would cross the Item 9B boundary.
- **Scientific/statistical consequences:** Plans make omissions, conventions, assumptions, and future interpretation explicit without claiming that a method is appropriate merely because it is sophisticated. A plan or report digest proves only its canonical content; it does not prove execution, registry-chain authority, artifact semantics, or authorized sealed access. Actual calculations and effective methodology remain later gated work.
- **Reproducibility and cost consequences:** Plans and reports reuse existing RFC 8785 JCS and `sha256:<64 lowercase hex>` helpers. No schema, registry kind, dependency, service, data, infrastructure, or incremental direct cost is added. The owner-reported ChatGPT Pro charge remains unknown pending invoice reconciliation.
- **References:** `VALIDATION_STANDARD.md`; `RESEARCH_METHODOLOGY.md`; `EXPERIMENT_LEDGER.md`; `ROADMAP.md` Item 9; `src/quant_hunter/validation/evidence.py`; `tests/test_scientific_evidence.py`.
- **Supersedes / superseded by:** Extends DEC-0025 without changing temporal semantics or the reviewed Item 8 authority. Item 9C and Item 10 remain separately gated.
- **Owner and approver:** Project owner through explicit Stage 1B Item 9B authorization dated 2026-09-07.

### DEC-0027 — Describe Simulation Realism Without Executing a Simulation

- **Date:** 2026-09-07
- **Status:** ACCEPTED
- **Scope:** architecture / validation / reproducibility
- **Context:** Item 9 requires future simulation inputs, outputs, and execution-realism assumptions to be reproducible without authorizing an engine, inventing market behavior, or competing with Item 8 or Item 9B authority.
- **Decision:** Add canonical Item 9C transaction-cost and execution-assumption plans plus immutable simulation input/output evidence envelopes. Use normalized exact decimal text for prices, quantities, notionals, rates, and costs, and exact nonnegative physical-duration units for latency. Require explicit applicability for every governed cost and market-session/gap category. Distinguish indicative from executable prices, idealized from realistically modeled assumptions, and assumed from measured or empirically supported claims; evidence is required for the latter claims. Midpoint and indicative prices cannot claim executable-price realism. Executable pricing requires explicit BUY and SELL rules as the sole execution-price authority; the global field is non-authoritative reference-source metadata. Standard immediately executable `MARKET` semantics require BUY to ASK and SELL to BID and reject `LAST_TRADE` as a direct executable side quote. Limit, resting, passive, stop, and custom policies may retain alternate mappings with explicit descriptions and rationales. Custom price, order-type, and time-in-force semantics require descriptions. Exact queue realism requires explicitly declared full-depth queue-event data capability, and partial-fill suppression requires a rationale. Inputs bind Item 9A and Item 9B plan digests and mark sealed release authorization unverified. Outputs preserve separate evidence categories and enforce coherent completed, pending, failed, and reasoned not-applicable states while remaining decision support only.
- **Alternatives considered:** A backtest engine would exceed Item 9C. Float quantities would weaken canonical identity. Silent zero costs, implicit calendars, midpoint execution, or bar-derived queue positions would allow scientifically unsupported claims. A new validation gate or lifecycle would compete with Item 9B and Item 8.
- **Scientific/statistical consequences:** These contracts make future execution assumptions and missing treatments reviewable, but calculate no fills, costs, financing, PnL, or performance. Their digests prove declared canonical metadata only; they do not prove execution, input consumption, artifact verification, V6 passage, or authorized sealed access.
- **Reproducibility and cost consequences:** Item 9C reuses existing RFC 8785 JCS, SHA-256, exact evidence, identity, and manifest primitives. Unordered declarations are sorted while the governed execution timeline remains explicit. No dependency, data, service, infrastructure, or incremental direct cost is added. ChatGPT Pro charge, tax, proration, and Plus credit remain unknown pending invoice reconciliation.
- **References:** `VALIDATION_STANDARD.md`; `RESEARCH_METHODOLOGY.md`; `EXPERIMENT_LEDGER.md`; `ARCHITECTURE.md`; `ROADMAP.md` Item 9; `src/quant_hunter/backtesting/contracts.py`; `tests/test_simulation_contracts.py`.
- **Supersedes / superseded by:** Extends DEC-0025 and DEC-0026 without changing their authorities. Full Item 9 remains pending independent cross-item review. Item 10 remains separately gated and unstarted.
- **Owner and approver:** Project owner through explicit Stage 1B Item 9C authorization dated 2026-09-07.


### DEC-0028 — Cross-Bind Item 9 Plans to Frozen Experiment Authority

- **Date:** 2026-09-07
- **Status:** ACCEPTED
- **Scope:** scientific identity / validation / reproducibility
- **Context:** Independently valid Item 8, Item 9A, Item 9B, and Item 9C digests could be combined while referring to different experiments, FROZEN revisions, or temporal partitions. Full Item 9 review requires one structural identity chain without authorizing execution.
- **Decision:** Item 8 FROZEN experiment partitions remain authoritative. Add an immutable metadata-only binding that verifies an Item 9A ValidationPlan and exactly compares its training/development, validation, and sealed-out-of-sample boundary strings with supplied FROZEN metadata. Item 9B must derive its temporal digest from that binding, and its temporal and multiple-testing bindings must identify the same experiment and exact frozen-revision digest. Item 9C must accept verified Item 9A and Item 9B objects, derive their compact digests, and reject mismatched experiment or temporal identities. Item 9A remains reusable temporal metadata. Item 8 retains lifecycle, attempt, evaluation, and decision authority.
- **Alternatives considered:** Independent digest strings preserve the integration defect. Copying Item 8 counters or state into Item 9 would create competing authority. Registry reads, sealed-data reads, or an executor would exceed this review fix.
- **Scientific/statistical consequences:** The chain proves structural coherence of supplied frozen metadata and declared plans. It performs no split, statistical calculation, evaluation, simulation, or experiment execution. Exact registered boundary strings are compared without rounding or float conversion.
- **Reproducibility and security consequences:** Canonical evidence retains the experiment, frozen revision, temporal plan, and scientific plan identities. Digests prove identity, not registry-chain verification or actual executor consumption. Construction and verification remain metadata-only, never dereference sealed references, and do not verify Item 10 authorization. No dependency, paid service, data, or infrastructure is added; incremental direct cost is USD 0.
- **References:** `EXPERIMENT_LEDGER.md`; `VALIDATION_STANDARD.md`; `RESEARCH_METHODOLOGY.md`; `ARCHITECTURE.md`; `ROADMAP.md` Item 9; `src/quant_hunter/validation/temporal.py`; `src/quant_hunter/validation/evidence.py`; `src/quant_hunter/backtesting/contracts.py`; `tests/test_simulation_contracts.py`.
- **Supersedes / superseded by:** Cross-binds DEC-0025, DEC-0026, and DEC-0027 without changing their separate authorities. Full Item 9 remains `IN PROGRESS / FULL REVIEW FIX` pending independent re-audit. Item 10 remains separately gated and `NOT STARTED`.
- **Owner and approver:** Project owner through explicit Stage 1B Full Item 9 cross-binding-fix authorization dated 2026-09-07.

### DEC-0029 — Make Project Status and Regression Invariants Repository-Authoritative

- **Date:** 2026-09-10
- **Status:** ACCEPTED
- **Scope:** governance / reproducibility / operations
- **Context:** Conversation memory is useful working context but is not durable or authoritative. After a pause, a new conversation, Codex session, or future agent must be able to recover the reviewed project state and its regression obligations from repository evidence without relying on hidden history.
- **Decision:** Git repository evidence remains the durable source of truth. Maintain `docs/PROJECT_STATUS.md` as a compact, mutable current-state resume document and `docs/REGRESSION_GUARD.md` as the permanent catalog of implemented, reviewed, and future-required invariants. Future agents must read both, verify Git state, and reconcile the status summary against actual repository and review evidence before substantial work. Every material implementation batch must run its change and hostile tests, the full existing regression suite, and a cross-item invariant review before independent pass, followed by governed CI and post-merge evidence. Prior reviewed invariants cannot be intentionally changed without a new accepted decision and explicit independent review.
- **Alternatives considered:** Conversation-only continuity is not durable. Repeating current status throughout every governing document creates drift. Turning the status file into a historical ledger duplicates Git, decisions, risks, development evidence, and pull-request records.
- **Scientific/statistical consequences:** Current status and regression obligations become explicit without creating a new scientific authority. `PROJECT_STATUS.md` may be updated as current-state evidence; `DECISIONS.md` and `RISK_REGISTER.md` retain historical reasoning and observations. Historical decisions must not be rewritten to make current behavior appear inevitable.
- **Reproducibility and cost consequences:** A future agent can reconstruct the exact reviewed resume point and the invariants that must remain green. This documentation/governance change adds no scientific computation, data access, Item 10 functionality, dependency, service, or infrastructure. Incremental direct cost is USD 0.
- **References:** `AGENTS.md`, `docs/PROJECT_STATUS.md`, `docs/REGRESSION_GUARD.md`, `docs/ROADMAP.md`, `docs/RISK_REGISTER.md`, and `docs/DEVELOPMENT.md`.
- **Supersedes / superseded by:** Adds continuity and regression governance without rewriting or superseding DEC-0028. The future sealed-OOS decision must use the next available decision number.
- **Owner and approver:** Project owner through the explicit Quant Hunter durable project continuity and regression-governance authorization dated 2026-09-10.

### DEC-0030 — Restore Bounded Codex Git Write Authority with Mandatory Audit Trail

- **Date:** 2026-09-10
- **Status:** ACCEPTED
- **Scope:** governance / operations / reproducibility
- **Context:** The project owner intentionally supersedes the temporary owner-only Git-write workflow recorded in the current `PROJECT_STATUS.md` draft. Codex needs bounded authority to complete the ordinary branch, commit, and publication steps of an explicitly authorized Quant Hunter batch while leaving final integration and higher-risk decisions with the owner.
- **Decision:** For an explicitly authorized batch, Codex may use normal non-destructive Git operations: status, diff, log, fetch, fast-forward-only pull when needed, feature-branch creation and switching, add, commit, push, and upstream setup. Codex may use command-local Git author identity when needed. Codex may not merge into `main` without owner authorization, force-push, hard reset, destructive clean, rewrite published history, rebase published reviewed history, delete branches or tags, or bypass failing checks. Every executed Git command, including a failed command and any command-local identity override, must be reported under `### Git Actions Executed`. Each report occupies exactly one line using `<exact command> | <READ-ONLY|LOCAL WRITE|REMOTE WRITE> | <purpose> | Result: <concise result>`.
- **Alternatives considered:** Keeping the owner-only workflow would leave routine authorized batches incomplete. Unbounded Git authority would weaken independent review and owner-controlled integration. Multi-line or success-only reporting would make the operational audit incomplete and harder to scan.
- **Scientific/statistical consequences:** This decision changes workflow authority only. It does not alter scientific, security, validation, budget, architecture, or stage-gate invariants. Intentional scientific-invariant changes and architecture changes arising from failed independent review still require owner involvement.
- **Reproducibility and cost consequences:** Exact successful and failed Git actions become durable handoff evidence in task reports. Final merge authorization, stage transitions, host or security mutations, and new spending remain with the owner. Incremental direct cost is USD 0.
- **References:** `AGENTS.md`, `docs/PROJECT_STATUS.md`, and DEC-0029.
- **Supersedes / superseded by:** Supersedes only the temporary owner-only Git-write restriction reflected in the `PROJECT_STATUS.md` draft. It does not modify or supersede the scientific or continuity content of DEC-0029.
- **Owner and approver:** Project owner through the explicit Continuity Governance narrow independent-review fix authorization dated 2026-09-10.

### DEC-0031 — Make Sealed OOS Release One-Way and Search-Terminating

- **Date:** 2026-09-11
- **Status:** ACCEPTED
- **Scope:** scientific integrity / sealed OOS / security / reproducibility
- **Context:** Item 8 provides the reviewed experiment lifecycle, frozen scientific definition, attempt accounting, evaluation, and decision authorities. Item 10A needs a narrow software release contract that can bind synthetic released evidence to that authority without claiming the separately gated Windows host boundary or creating a competing lifecycle.
- **Decision:** Item 8 remains the sole lifecycle and attempt authority. Every release starts from `ExperimentLifecycleService.verify_frozen` and must exactly match the experiment ID, sole FROZEN revision digest, immutable freeze-manifest digest, code/configuration/environment identities, complete canonical dataset-ID set, exact sealed interval, and full-precision release time at or after `frozen_at`. Release never mutates the FROZEN revision and never creates another FROZEN state. The release event identity is SHA-256 over RFC 8785 JCS of the complete event body excluding only `event_digest`; `previous_event_digest` is part of that preimage. Events use exclusive append-only publication, compare-and-swap, a verified hash chain, and a retained canonical head anchor. Authorized release and accidental exposure irreversibly change the exact binding to `EXPOSED`; neither can be unseen, removed, reset, or replaced by a pristine release. Release terminates every new candidate-search, tuning, retry-as-search, model-selection, modification, and AI-variant attempt for the experiment. A fixed prespecified evaluation may proceed with zero new search attempts, and later Item 8 revisions retain the exact release-event digest. Accidental exposure requires invalidation, risk, and decision review without automatically writing a scientific conclusion or rewriting an Item 8 decision. Item 10A can create and accept only `SYNTHETIC_TEST` evidence and consumes an immutable released-artifact reference rather than a sealed source path. `HOST_ENFORCED` evidence and the real Windows boundary remain Item 10B work under separate authorization.
- **Alternatives considered:** Attaching release metadata by appending a second FROZEN revision violates Item 8 authority. Hashing an event containing its own digest is circular. Single-dataset or separately typed partition inputs permit cross-binding mistakes. Treating a successful or partial disclosure as reversible destroys the holdout claim. A schema enum or synthetic denial test cannot prove real host enforcement.
- **Scientific/statistical consequences:** One exact FROZEN scientific definition controls authorization, and all post-release search is prohibited. The release reference permits only the already specified zero-new-search evaluation path. Accidental exposure remains permanent evidence requiring review, so an observed holdout cannot silently return to confirmatory status.
- **Reproducibility and security consequences:** Canonical event bytes bind the entire authority and exposure chain, and verification detects malformed schemas, stale writers, forks, missing or reordered files, altered prior digests, corrupt events, and tail truncation. Research-side software accepts no sealed path and does not read, list, stat, traverse, or hash sealed source content. Item 10A uses synthetic fixtures only, creates no Windows identities or vault, changes no ACL/SACL, encryption, audit, backup, sync, or indexing configuration, and claims no administrator-resistant filesystem security. It adds no dependency, service, data, or infrastructure; incremental direct cost is USD 0.
- **References:** DEC-0006, DEC-0007, DEC-0021–DEC-0024, `EXPERIMENT_LEDGER.md`, `VALIDATION_STANDARD.md`, `ARCHITECTURE.md`, `ROADMAP.md` Item 10A, `schemas/v1/sealed-release-event.schema.json`, `schemas/v1/sealed-exposure-incident.schema.json`, `src/quant_hunter/isolation/`, `src/quant_hunter/experiments/lifecycle.py`, and `tests/test_sealed_release.py`.
- **Supersedes / superseded by:** Implements only the Item 10A software and synthetic-security portion of DEC-0006. It does not complete Item 10, close RISK-017, or authorize Item 10B host changes.
- **Owner and approver:** Project owner through explicit Stage 1B Item 10A authorization dated 2026-09-11.

### DEC-0032 — Make Sealed Exposure Global and Historically Re-Verifiable

- **Date:** 2026-09-11
- **Status:** ACCEPTED
- **Scope:** scientific integrity / sealed OOS / reproducibility
- **Context:** Builder self-review before independent review found that the initial software ledger scoped exposure to `experiment_id + sealed_binding` and used current-head FROZEN verification when rechecking retained release evidence. That allowed a different experiment to treat previously observed data as pristine and prevented complete audit verification after the authorized experiment advanced through Item 8.
- **Decision:** Release authorization remains experiment-specific and exactly bound to the current Item 8 FROZEN authority. Exposure state belongs globally to the underlying dataset/time footprint. An event containing multiple dataset IDs exposes the declared interval independently for every component. A future candidate is already exposed if any same-dataset component overlaps any retained release or incident, regardless of experiment or event type. Intervals use exact UTC half-open `[start, end)` semantics: two intervals overlap only when each starts before the other ends, and equal adjacent boundaries do not overlap. Start must precede end, and fractional seconds are compared without float conversion. An `AUTHORIZED_RELEASE` may be appended only while every requested component is pristine; full ledger verification independently rejects an authorized event following prior overlapping exposure. An `ACCIDENTAL_EXPOSURE` remains appendable after exposure, including repeated and overlapping incidents, because incident retention is distinct from the one-way state transition. Prospective authorization continues to require `verify_frozen` with a current FROZEN head. Permanent release audit uses a separate Item 8 historical verification path that proves the complete lifecycle history, exactly one governed FROZEN revision, its immutable manifest and all release bindings, plus retention of the exact event digest after lifecycle progression. Item 8 remains the sole lifecycle, attempt, evaluation, and decision authority.
- **Alternatives considered:** Experiment-scoped exposure contradicts the physical fact that the same data was observed. Exact-binding equality misses subset, superset, and partial overlap. Lexicographic timestamp comparison can mis-handle equivalent instants with different legal fractional precision. Rejecting later incidents discards adverse security evidence. Weakening prospective authorization to accept a historical FROZEN would permit a new release after the experiment had advanced.
- **Scientific/statistical consequences:** Previously observed dataset intervals cannot be reused as pristine evidence by another experiment. Adjacent non-overlapping intervals remain available. Every later security incident remains permanent, while no incident creates a new state or restores confirmatory status. Fixed post-release evaluation and zero-attempt search termination remain unchanged.
- **Reproducibility and security consequences:** Retained release evidence remains fully verifiable while the experiment is FROZEN, RUNNING, EVALUATED, or DECIDED. Verification still covers the ledger, canonical event digest and chain, immutable released artifact, exact historical FROZEN authority, and later Item 8 event-digest reference. Item 10A remains synthetic software evidence only; Item 10B is `NOT STARTED`. No real sealed data, host mutation, dependency, service, or infrastructure is added; incremental direct cost is USD 0.
- **References:** DEC-0031, `EXPERIMENT_LEDGER.md`, `VALIDATION_STANDARD.md`, `ARCHITECTURE.md`, `REGRESSION_GUARD.md` REG-F01–REG-F03, `src/quant_hunter/isolation/ledger.py`, `src/quant_hunter/isolation/release.py`, `src/quant_hunter/experiments/lifecycle.py`, and `tests/test_sealed_release.py`.
- **Supersedes / superseded by:** Corrects the exposure-key and retained-verification semantics in the first Item 10A implementation without weakening DEC-0031's digest, lifecycle, search-termination, synthetic-only, or append-only requirements. It does not authorize Item 10B or close RISK-017.
- **Owner and approver:** Project owner through explicit Stage 1B Item 10A pre-independent-review hardening authorization dated 2026-09-11.

### DEC-0033 — Make SealedReleaseService the Sole Supported Exposure Writer

- **Date:** 2026-09-11
- **Status:** ACCEPTED
- **Scope:** scientific authority / security / reproducibility
- **Context:** Independent review found that public `ExposureLedger.append_event` created a competing writer authority. A caller could construct a schema-valid `AUTHORIZED_RELEASE` or `ACCIDENTAL_EXPOSURE` from a raw mapping without passing through the Item 8 FROZEN authority and, for release, immutable released-artifact verification.
- **Decision:** `SealedReleaseService.authorize_release` is the sole supported public authorized-release writer, and `SealedReleaseService.record_accidental_exposure` is the sole supported public incident writer. `ExposureLedger` remains the public read and structural-verification primitive, but its low-level validated append operation is private/internal. An `AUTHORIZED_RELEASE` cannot be created through a raw public ledger API. The ledger provides append-only persistence, schema and canonical-digest checks, chain verification, compare-and-swap, and one-way exposure enforcement; it is not the scientific release authority. Structural ledger validity never substitutes for exact Item 8 FROZEN authorization or immutable released-artifact verification. Item 8 remains the sole experiment lifecycle and attempt authority.
- **Alternatives considered:** Keeping a documented-but-public raw writer would preserve an easy workflow bypass. Removing the ledger's public read model would conflate storage verification with release authorization. Authentication, operating-system identities, and ACL enforcement belong to the separately gated Item 10B host boundary.
- **Scientific/statistical consequences:** Every supported authorized release must pass the exact Item 8 FROZEN checks before any exposure event is appended. Accidental exposure remains permanently recordable through its explicit service method. Existing global dataset/time exposure, exact half-open overlap, incident retention, post-release zero-search, and historical release verification semantics remain unchanged.
- **Reproducibility and security consequences:** The public API now distinguishes scientific/security authorization from structural persistence and verification. Python-private naming protects against accidental workflow misuse at this software layer; it does not claim protection against a machine administrator or arbitrary code in the process. Item 10B remains `NOT STARTED`. No real sealed data or host-security mutation is involved, and no dependency, service, or infrastructure is added; incremental direct cost is USD 0.
- **References:** DEC-0031, DEC-0032, `EXPERIMENT_LEDGER.md`, `VALIDATION_STANDARD.md`, `ARCHITECTURE.md`, `REGRESSION_GUARD.md` REG-F01–REG-F02, `src/quant_hunter/isolation/ledger.py`, `src/quant_hunter/isolation/release.py`, and `tests/test_sealed_release.py`.
- **Supersedes / superseded by:** Narrows the supported Item 10A writer authority without changing DEC-0031 or DEC-0032 exposure, lifecycle, history, or synthetic-only semantics. It does not authorize Item 10B or close RISK-017.
- **Owner and approver:** Project owner through the explicitly authorized Stage 1B Item 10A narrow independent-review fix dated 2026-09-11.
