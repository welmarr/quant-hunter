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
item 7 remains in final-review-fix status pending independent review of exact
PIT transformation binding. No real data, connector, experiment,
trading strategy, quantitative algorithm, broker connection, backtest engine,
portfolio logic, or live-trading capability exists.

## Documentation Map

- Start with [`AGENTS.md`](AGENTS.md) for non-negotiable operating rules.
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
