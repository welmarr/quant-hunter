# Quant Hunter

Quant Hunter is a planned quantitative-research and market-discovery platform. Its purpose is to reproduce established research, test hypotheses under strict point-in-time and out-of-sample controls, and eventually evaluate distinct strategy families without manufacturing attractive results.

## Current Status

Stage 0 and Stage 1A foundational planning are complete. The repository remains documentation-only and contains no trading strategies, Python project scaffold, verified setup commands, data connections, broker connections, or live-trading capability. Stage 1B implementation requires a later task that explicitly authorizes it.

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

## Development Commands

No build, test, lint, or run command is valid yet because no implementation or package manifest exists. DEC-0004–DEC-0008 select the future CPython 3.14, uv, locked environment, serialization, and quality conventions; Stage 1B must implement and verify them before any command is reported as operational.
