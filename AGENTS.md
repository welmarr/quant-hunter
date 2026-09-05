# Repository Guidelines

## Mission and Current Scope

Quant Hunter is a long-horizon project to build an independent, scientifically defensible quantitative-research and market-discovery laboratory. It is not currently a trading bot. Stage 0 and Stage 1A planning are complete; Stage 1B implementation has not begun. Do not implement Stage 1B infrastructure, trading strategies, or later-stage systems without a subsequent explicit request and the applicable roadmap gate.

Agents working here must combine the responsibilities of principal quantitative systems architect, quantitative researcher, data engineer, statistician, and senior Python engineer, while respecting the stage and authorization boundaries below.

The aspirational goal of finding selective, strongly risk-adjusted opportunities—including testing whether robust subsets can approach a 75% win probability—is a research question, never a target to manufacture. Stage 1 succeeds only when the project is a reproducible laboratory in which it is difficult to fool ourselves.

## Non-Negotiable Operating Rules

1. Scientific integrity takes priority over attractive backtests or rapid delivery.
2. Never fabricate, target-fit, or imply a 75% win rate. Historical performance is not evidence of future profitability.
3. Register every experiment before evaluation under a permanent experiment ID.
4. Preserve failed, rejected, and inconclusive experiments in the ledger with their reasons.
5. Count every AI-generated strategy or parameter variant in multiple-testing exposure.
6. Prevent look-ahead bias in data, features, labels, validation, and execution simulation.
7. Never use revised macroeconomic values as though they were available historically; use point-in-time vintages.
8. Keep raw source data immutable. Corrections create new versions; they never overwrite source observations.
9. Reproducibility is mandatory: code revision, configuration, data vintages, seeds, environment, and outputs must be traceable.
10. Model bid/ask spreads, commissions, financing/carry, slippage, latency, order behavior, and other realistic execution effects where relevant.
11. No live-money trading is permitted during initial research stages. Do not create or connect live broker credentials.
12. Research code must not be able to deploy or promote itself directly to production. Execution requires a separate, controlled boundary.
13. Never commit secrets, credentials, tokens, or private licensed data. Use sanitized examples such as `.env.example` when configuration is introduced.
14. AI may enhance quantitative science; it never replaces statistical validation. Human- and AI-originated work face identical standards.
15. Complexity must demonstrate incremental value against simpler baselines after costs and validation.
16. Record data provenance, licensing, retrieval time, transformations, and vintage.
17. Assign every strategy, model, pattern, and experiment a permanent identifier before it becomes a research object.
18. Sealed out-of-sample data must be inaccessible to strategy-development workflows until the experiment definition is frozen.
19. Record any change affecting research methodology or statistical validity in `docs/DECISIONS.md`; never silently change the rules after seeing results.
20. Total Month-1 spending—including subscriptions, API use, infrastructure, data, and services—must remain within USD $400. No purchase is allowed without explicit user approval.

Positive expectancy, robustness, calibration, drawdown, sample size, cost sensitivity, regime stability, and out-of-sample behavior outrank raw win rate, Sharpe ratio, CAGR, or profit factor.

## Required Agent Workflow

Before changing code, documentation, data, configuration, registries, or research artifacts:

1. Read this file, `docs/PROJECT_CHARTER.md`, and the documents governing the task.
2. Check `docs/ROADMAP.md`, `docs/DECISIONS.md`, and `docs/RISK_REGISTER.md`; record unresolved assumptions instead of guessing.
3. For research, allocate permanent IDs, register the hypothesis and candidate-search scope, seal holdouts, and freeze the experiment definition before evaluation.
4. Keep raw data immutable and record provenance and vintages through the prescribed registries.
5. Run all documented tests, linters, and reproducibility checks once tooling exists. Do not invent successful results or claim success merely because code runs.
6. Update affected registries, ledgers, decisions, risks, and documentation in the same change.

Do not start strategy development before the research foundation and its validation controls satisfy the Stage 1 gate in `docs/ROADMAP.md`.

## Documentation Authority

Detailed requirements live in:

- `docs/PROJECT_CHARTER.md` — mission, principles, scope, research families, AI and spending boundaries.
- `docs/ARCHITECTURE.md` — planned repository, component, security, and deployment boundaries.
- `docs/RESEARCH_METHODOLOGY.md` — research lifecycle and canonical reproduction program.
- `docs/VALIDATION_STANDARD.md` — leakage controls, statistical tests, backtesting assumptions, and reports.
- `docs/DATA_ARCHITECTURE.md` — point-in-time data layers, immutability, timing, and provenance.
- `docs/DATA_SOURCE_REGISTRY.md` — provider-assessment schema and source-selection rules.
- `docs/MODEL_REGISTRY.md` — permanent model/strategy identities and research-family taxonomy.
- `docs/EXPERIMENT_LEDGER.md` — experiment schema, preregistration, freezing, and failure retention.
- `docs/PATTERN_DISCOVERY.md` — the complete structural-recognition research specification.
- `docs/DECISIONS.md` — durable methodological and architectural decision records.
- `docs/RISK_REGISTER.md` — active scientific, operational, data, security, and budget risks.
- `docs/BUDGET_LEDGER.md` — aggregate spending, commitments, approvals, and Month-1 headroom.
- `docs/ROADMAP.md` — stage gates, ordered work, completion evidence, and deferred scope.
- `docs/REQUIREMENTS_TRACEABILITY.md` — mapping from the original master specification to this hierarchy.

This file governs invariant behavior. The detailed documents govern implementation and research procedures. If they conflict, apply the stricter scientific, safety, reproducibility, and spending constraint and record the resolution in `docs/DECISIONS.md`.
