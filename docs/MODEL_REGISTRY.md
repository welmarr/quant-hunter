# Model Registry

## Purpose and Identity

Every research family, model, and strategy must be a durable research object before evaluation or use. Under DEC-0009, allocate typed UUIDv7 identifiers such as `FAM-01990f30-7f5e-7b34-9b21-3d74c513c841`, `MOD-<uuidv7>`, and `STRAT-<uuidv7>`; pattern identifiers follow `PATTERN_DISCOVERY.md`, and experiment identifiers follow `EXPERIMENT_LEDGER.md`. Renaming, rejection, or replacement never reuses an ID. Material definition changes create a new append-only revision or successor record rather than rewriting history.

The registry distinguishes:

- **research family:** a genuinely different hypothesis or evidence source;
- **model:** a fully defined estimator, signal, forecaster, allocator, or execution method;
- **strategy:** a decision rule joining models, portfolio logic, and execution assumptions; and
- **variant:** a parameterization or close derivative that remains part of its parent family and multiple-testing count.

Roughly 200 serious models may eventually be researched, but hundreds of indicator settings do not become independent models or votes. Complexity and combination count must be explicit, and every complex candidate must compete with a simpler baseline.

## Minimum Record

Each family, model, or strategy record must include:

- permanent ID, name, version, type, lifecycle status, and parent/successor IDs;
- hypothesis, research family, economic/statistical rationale, and academic or institutional basis;
- authoritative source and citation, mathematical definition, inputs, outputs, horizon, sampling frequency, universe, and assumptions;
- parameters and complete search space, including AI-generated variants;
- data requirements, point-in-time constraints, availability, licensing, and expected cost;
- evidence quality, independent replication evidence, FX applicability, and known failures or decay;
- implementation/reproduction outcome where applicable, using the classifications in `RESEARCH_METHODOLOGY.md`;
- baseline comparators and distinctiveness from existing objects;
- compatible validation plan and experiment IDs;
- transaction-cost, capacity, risk, and regime sensitivities;
- implementation location and source-code revision when one exists;
- owner, creation timestamp, decision, limitations, and failure modes.

Status values should include `PROPOSED`, `REPRODUCTION`, `RESEARCH`, `VALIDATED`, `REJECTED`, `RETIRED`, and `SUPERSEDED`. Status is evidence, not promotion authority; nothing in this registry authorizes live trading.

## Foundational Research-Family Catalog

The initial catalog is deliberately broad and non-exhaustive:

- time-series momentum; cross-sectional momentum; FX carry; currency value;
- trend following; breakouts; mean reversion;
- cointegration; error-correction models; statistical arbitrage; PCA residual models;
- factor models; state-space models; Kalman filtering;
- regime-switching models; Hidden Markov Models;
- ARCH, GARCH, EGARCH, and GJR-GARCH; volatility forecasting; volatility targeting;
- macroeconomic surprise models; interest-rate differentials; yield-curve models;
- cross-asset relationships;
- market microstructure; order flow; liquidity and spread models;
- point processes and Hawkes processes;
- systematic technical-pattern recognition;
- nonparametric models; machine learning; probability calibration;
- portfolio construction; Kelly-inspired sizing; drawdown-constrained sizing;
- execution-cost models; Almgren-Chriss-style execution research; and
- transaction-cost analysis.

Expand this catalog from strong academic and institutional evidence; do not assume it is complete. A named technique is not automatically a strategy, and a family earns no claim of alpha from an attractive backtest alone.

## Independence and Ensemble Governance

Registry lineage must expose parameter siblings, common data, shared labels, overlapping trades, and correlated signals. Closely related variants are one multiple-testing family and must not receive multiple ensemble votes merely because they reproduce the same underlying evidence. This is mandatory for pattern-family models and should guide every meta-model.

## Registry Entries

No models or strategies are registered yet. Do not add implementations during Stage 1A. Machine authority will be a schema-validated JCS record at `registries/<kind>/<id>/vNNNNNN.json`, linked to its prior revision digest. Human-readable tables in this file and generated indexes are views only. Future entries must be append-only or explicitly superseded and cross-linked to decisions and experiments.
