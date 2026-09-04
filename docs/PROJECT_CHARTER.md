# Project Charter

## Purpose

Quant Hunter will be an independent quantitative-research and market-hunting platform combining established quantitative-finance research, high-quality market and economic data, econometrics, statistical validation, machine learning, and—only later—advanced AI reasoning. It is not a request to immediately create a trading bot.

The long-term aspiration is to discover highly selective opportunities with strong risk-adjusted performance and to investigate whether any robust subset can approach or exceed a 75% win probability. That figure is not a delivery target. Never manufacture it, optimize merely to reach it, or treat historical performance as proof of future profitability.

Research decisions prioritize positive expectancy, robustness, probability calibration, drawdown, sample size, realistic transaction costs, regime stability, and out-of-sample performance over headline win rate, Sharpe ratio, profit factor, or CAGR. Failed hypotheses are valuable permanent results.

## Development Philosophy

Build from the bottom upward:

1. Data
2. Data quality
3. Mathematics and econometrics
4. Reproduction of established research
5. Distinct strategy families
6. Registered experimentation
7. Anti-overfitting controls
8. Ensembles and meta-models
9. AI research assistance
10. Paper trading
11. Shadow validation
12. Only eventually, separately authorized controlled capital

AI enhances quantitative science; it does not replace it. The eventual target of roughly 200 serious models means genuinely distinct evidence and research families, not hundreds of parameter variations. The initial taxonomy is maintained in `MODEL_REGISTRY.md` and must be expanded only from strong academic or institutional research.

## Stage 1 Charter

The first implementation milestone is the research foundation, not strategy production. It must make future experiments scientifically defensible through point-in-time data, immutable provenance, registries, reproducible configuration, testable interfaces, realistic backtesting assumptions, sealed validation data, and durable reporting. Favor clean interfaces, reproducibility, and testability over premature complexity.

Stage 1 explicitly excludes:

- implementation of the proposed 200-model library;
- live-money trading or live broker credentials;
- an LLM making or executing trades;
- self-promotion of research code into production;
- unnecessary distributed or GPU infrastructure;
- unapproved purchases.

Its success criterion is: **a reproducible quantitative-research laboratory in which it is difficult to accidentally fool ourselves.** Code merely executing is not success.

## AI Research Boundary

Future AI agents may research literature, generate hypotheses, inspect experiment results, identify possible regime changes, suggest datasets, critique strategies, detect suspicious results, write candidate implementations, and compare competing explanations. Every AI-originated candidate must be registered, counted in the multiple-testing budget, and pass exactly the same validation as human work. An LLM must not be responsible for trade execution.

## Budget and Procurement

Month-1 total spending is capped at USD $400, including ChatGPT, OpenAI API use, servers, data, and every paid service. No purchase may occur without explicit user approval. Prefer open-source libraries and authoritative free data; avoid GPUs unless quantitatively justified; document expected cost before recommending a paid dependency; and reserve expensive AI models for selective use.

## Governance

The permanent rules in `../AGENTS.md` control all work. Methodological changes require a decision record. Experiments, models, strategies, and patterns require permanent identifiers. Data provenance and failures remain auditable. `ROADMAP.md` owns stage gates; no later-stage capability is authorized merely because its interface has been discussed.
