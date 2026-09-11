# Quant Hunter

Quant Hunter is a planned quantitative-research and market-discovery platform. Its purpose is to reproduce established research, test hypotheses under strict point-in-time and out-of-sample controls, and eventually evaluate distinct strategy families without manufacturing attractive results.

## Current Status

Stage 0 and Stage 1A are complete. Stage 1B is in progress: Batches 1–2
provide the minimal Python scaffold, locked quality gate, public-repository CI
workflow, and versioned JSON Schema foundation. Batches 3A–3B add typed UUIDv7
allocation, append-only file-backed registries, RFC 8785 canonicalization,
separate exact-byte and canonical-JSON SHA-256 contracts, mandatory governed
registry validation, and generic freeze-manifest construction. No real registry
object exists. Batch 4A adds local immutable exact-byte object publication,
generic artifact sidecars, and synthetic byte-faithful raw capture. Batch 4B.1
adds the synthetic deterministic Parquet and distinct physical, lineage, and
logical-content identity foundation. Batch 4B.2 adds the synthetic point-in-time
selection contract for explicit UTC as-of queries, PUBLIC and OPERATIONAL
availability, immutable vintages, and normalized/curated publication. Roadmap
item 7 is complete after independent review passed commit
`952bd3a4a30518d51b6a9dbe679b00f9c28753fd`. Independent review passed Item
8A at commit `79730f9ed54d6fcf9c8b33ad70af6181941c0b5e`, Item 8B at commit
`747ae70b9b6d95179271d5770239347e24d6b2bd`, and Item 8C at reviewed PR head
`c80ca6d2dffba316239880cf6b3ce33c20ee6b2c`. Full Stage 1B Item 8 is complete
after independent review and is merged on main at
`265d5f49e06f841a5e23fdf9ea177670bbfbc1e9`. It provides the governed lifecycle through `DECIDED`,
permanent result/failure evidence, immutable result-object verification, and
deterministic rerun-input resolution. Item 9A is
`COMPLETE / INDEPENDENT REVIEW PASSED` at reviewed head
`e19c693557fc4debe7a12746ae682e1113e404b1` and merged on main at
`5636ad431b1c660233189a45ebfd6157308df7fa`. Item 9B is `COMPLETE / INDEPENDENT
REVIEW PASSED` at reviewed head
`d828fb498de44df25d9fba908ac9a32868e6fbff`, merged on main at
`26f1a8a5d62651aad9d545725d3200bad4170500`, with
metadata-only applicability, baseline, metric, statistical-method, robustness,
multiple-testing binding, and scientific-report contracts. Item 9C is
`COMPLETE / INDEPENDENT REVIEW PASSED`
with metadata-only side-aware execution, cost, simulation-input, and fail-closed
simulation-output contracts. The full-review fix cross-binds Items 9A–9C to the
same supplied Item 8 FROZEN experiment and revision authority. Side rules are the execution-price authority;
standard executable MARKET assumptions require BUY to ASK and SELL to BID. Item
9 and its cross-binding are `COMPLETE / INDEPENDENT REVIEW PASSED` at reviewed
head `d6ff6b26fced3c7750f8a4c68b520b70c0567c77`, merged on main at
`6c9d5ae1eec58faeca53239d832748053387f1bc`. Post-merge Quality #32 passed on
Ubuntu and Windows; Ubuntu ran 630 tests with 90.99% combined statement/branch
coverage. Item 10A is `COMPLETE / INDEPENDENT REVIEW PASSED / MERGED /
POST-MERGE CI GREEN` at merged main
`20851f262041cda1fe26844032f298b2a1531ffd`. It adds a synthetic-only
sealed-release authority, canonical
hash-chained exposure ledger, exact Item 8 FROZEN binding, irreversible
`EXPOSED` evidence, and post-release search termination. The release service is
the sole supported public exposure writer; the ledger remains the structural
read/verification primitive. Item 10B real Windows host enforcement is the
current explicitly authorized item and remains separately evidence-gated.
No real data, connector, executed experiment,
trading strategy, quantitative algorithm, broker connection, backtest engine,
order matcher, fill simulator, transaction-cost calculator, portfolio logic, or
live-trading capability exists.

## Documentation Map

- Start with [`AGENTS.md`](AGENTS.md) for non-negotiable operating rules.
- Resume from [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md), then apply the reviewed invariants in [`docs/REGRESSION_GUARD.md`](docs/REGRESSION_GUARD.md).
- Use [`docs/ISSUE_GOVERNANCE.md`](docs/ISSUE_GOVERNANCE.md) for material deferred-work tracking and closure rules.
- Read [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md) for mission, scope, and success criteria.
- Use [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the planned modular boundaries.
- Follow [`docs/RESEARCH_METHODOLOGY.md`](docs/RESEARCH_METHODOLOGY.md) and [`docs/VALIDATION_STANDARD.md`](docs/VALIDATION_STANDARD.md) for research design and evaluation.
- Consult [`docs/DATA_ARCHITECTURE.md`](docs/DATA_ARCHITECTURE.md) and [`docs/DATA_SOURCE_REGISTRY.md`](docs/DATA_SOURCE_REGISTRY.md) before acquiring or transforming data.
- Register durable objects in [`docs/MODEL_REGISTRY.md`](docs/MODEL_REGISTRY.md) and [`docs/EXPERIMENT_LEDGER.md`](docs/EXPERIMENT_LEDGER.md).
- Follow [`docs/PATTERN_DISCOVERY.md`](docs/PATTERN_DISCOVERY.md) for structural-recognition research.
- Record changes and uncertainty in [`docs/DECISIONS.md`](docs/DECISIONS.md) and [`docs/RISK_REGISTER.md`](docs/RISK_REGISTER.md).
- Record every proposed or actual project cost in [`docs/BUDGET_LEDGER.md`](docs/BUDGET_LEDGER.md).
- Use [`docs/ROADMAP.md`](docs/ROADMAP.md) for stage gates and [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md) for specification coverage.
- Use [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for the pinned toolchain, setup commands, CI constraints, and preflight evidence.

## Development Commands

Use CPython 3.14.7 and uv 0.12.10:

```text
uv sync --locked --group dev
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy src tests
uv run --locked pytest --cov=quant_hunter --cov-branch --cov-fail-under=90
```

See `docs/DEVELOPMENT.md` for bootstrap evidence and host limitations.
