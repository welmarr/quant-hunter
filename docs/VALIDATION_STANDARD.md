# Quant Hunter Validation Standard

## Status and applicability

This document is the minimum validation standard for every Quant Hunter experiment, strategy, model, pattern, ensemble, forecast, portfolio rule, and execution study. It applies equally to human-designed, algorithmically searched, and AI-generated work. A result that fails a mandatory gate may remain a useful exploratory finding, but it may not be presented as validated evidence.

The standard is designed to prevent accidental self-deception. Statistical integrity, point-in-time correctness, realistic implementation, and reproducibility take precedence over impressive performance.

## Non-negotiable claim rules

- Never fabricate a 75% win rate or optimize merely to reach a requested win rate.
- Never treat historical performance as evidence of future profitability.
- Never claim alpha solely because Sharpe ratio, profit factor, win rate, CAGR, or another headline metric is attractive.
- Positive expectancy, robustness, calibration, drawdown, sample adequacy, transaction costs, regime stability, and out-of-sample performance take priority over raw win rate.
- Complexity must demonstrate durable value against simpler baselines.
- AI-generated work receives exactly the same scrutiny as human-designed work.
- Failed, rejected, inconclusive, and superseded experiments remain part of the scientific record.

Any reported probability, including a win probability near or above 75%, must be an estimate with its definition, sample size, confidence interval, calibration evidence, selection history, applicable market population, horizon, costs, and out-of-sample status disclosed. It is not a promise of future performance.

## Mandatory evidence gates

An experiment may be called validated only when all applicable gates pass and all non-applicable checks have a documented rationale.

| Gate | Requirement |
|---|---|
| V0 — Registration | Permanent IDs and a pre-result experiment record exist; hypothesis, variants, partitions, costs, tests, metrics, and decision rules are frozen. |
| V1 — Data provenance | Inputs have source, vintage, lineage, quality status, availability semantics, and immutable raw references. |
| V2 — Temporal integrity | Features, labels, universe membership, revisions, and executions use only information available at the simulated decision time. |
| V3 — Baseline | The candidate is compared with appropriate naive, simple, and established baselines. |
| V4 — Chronological evidence | Train/development, validation, and sealed out-of-sample evaluation are strictly separated; walk-forward or other time-aware analysis is used as appropriate. |
| V5 — Search adjustment | Every attempted variant is counted and data-snooping/multiple-hypothesis exposure is assessed and corrected. |
| V6 — Execution realism | Bid/ask, costs, financing, order behavior, latency, market sessions, and relevant fill limitations are modeled or the omission is disclosed and stress-tested. |
| V7 — Robustness | Sampling uncertainty, parameter sensitivity, cost sensitivity, degradation, and regime/instrument stability are evaluated. |
| V8 — Reproducibility | A frozen configuration, source commit, environment, data identifiers, seeds, and outputs permit an independent rerun. |
| V9 — Reporting and decision | The full applicable metric set, uncertainty, limitations, failures, decision, and reason are recorded without deleting unfavorable evidence. |

Passing these gates authorizes at most the next research stage. It does not authorize live trading, broker connectivity, or automatic production promotion.

## Chronological partitioning and sealed evidence

### Required partitions

Use strict chronological train/development, validation, and untouched test separation. Names may vary by study, but roles may not:

- **Training/development:** fit estimators and construct the candidate.
- **Validation:** compare bounded choices and assess stability without touching final evidence.
- **Sealed out-of-sample:** perform the prespecified final evaluation only after the experiment is frozen.

Random cross-validation is not an acceptable default for market time series. Use rolling or expanding windows, walk-forward validation, purged time-series cross-validation, and embargo periods when dictated by forecast horizon, label overlap, feature construction, or dependency structure.

### Access control

Sealed out-of-sample data must remain inaccessible to all strategy-development workflows until freeze. This includes researchers, notebooks, tuning jobs, automated searches, report previews, feature caches, and AI agents. Summary statistics, visualizations, precomputed features, and other derivatives of the sealed observations also constitute access.

The experiment ledger must record partition boundaries, the sealing mechanism, authorized unseal event, timestamp, code commit, configuration hash, and any accidental exposure. An exposed interval cannot be resealed. Any design or parameter change informed by sealed results requires a new experiment ID, must count toward multiple-testing exposure, and requires a genuinely untouched interval for confirmatory testing. If none remains, the finding is exploratory until new data accrues.

## Look-ahead and point-in-time controls

No future information may enter a historical decision through features, labels, preprocessing, normalization, universe construction, data cleaning, imputation, parameter estimation, timestamps, or execution assumptions.

For each observation distinguish and retain:

- event time;
- publication time;
- ingestion time; and
- revision time.

Macroeconomic and other revised data must use the value and vintage actually public at the simulated decision time. Revised observations must never be used as if they were known historically. Availability must include publication delays, vendor latency, processing latency, and a realistic decision/execution delay. Research on announcement surprises must preserve contemporaneous consensus, actual-release values, corrections, release timestamps, and tradable prices.

Fit scalers, imputers, encoders, feature selectors, dimensionality reductions, regime models, and all other learned transformations only on the training information available at that fold. Account for overlapping labels and leakage across adjacent observations. Address survivorship and universe-selection bias wherever applicable.

## Required anti-overfitting analyses

Validation infrastructure must support, and each experiment must apply when appropriate:

- strict chronological train/validation/test separation;
- walk-forward validation;
- rolling and expanding windows;
- purged time-series cross-validation;
- embargo periods;
- bootstrap analysis;
- block bootstrap for dependent observations;
- Monte Carlo analysis;
- White's Reality Check;
- Hansen's Superior Predictive Ability test;
- Deflated Sharpe Ratio;
- Probability of Backtest Overfitting;
- Combinatorially Symmetric Cross-Validation;
- multiple-hypothesis correction;
- parameter-stability analysis;
- performance-degradation analysis; and
- regime-by-regime evaluation.

Methods are not a checklist to apply mechanically. The registered analysis plan must state which are applicable, why, their assumptions, and parameter choices. Omitting an applicable method requires a documented reason. A statistically sophisticated method does not rescue leaky data, an invalid time split, unrealistic execution, or an unrecorded search.

### Resampling and simulation

Ordinary independent resampling can be invalid for serially dependent returns and overlapping trades. Use block/bootstrap designs consistent with dependence and record block-selection logic. Monte Carlo analysis should perturb appropriate sources of uncertainty—such as trade order, fills, costs, parameters, or return paths—without destroying the structure whose risk is being evaluated.

### Data-snooping tests

Use White's Reality Check or Hansen's Superior Predictive Ability test where the question concerns the best result selected from many competing rules. Use Deflated Sharpe Ratio to account for non-normality and selection among trials where applicable. Use Probability of Backtest Overfitting and Combinatorially Symmetric Cross-Validation when the strategy-selection design supports them. State limitations when test assumptions do not match the data or search process.

## Multiple-testing accounting

The multiple-testing universe includes every hypothesis, parameterization, feature set, label, horizon, instrument subset, regime filter, preprocessing choice, pattern candidate, rerun used for selection, and model variant examined—not merely the candidate shown in the final report.

All AI-generated strategy variants count toward multiple-testing exposure. This includes variants generated in separate prompts or agent runs and candidates discarded before formal evaluation. Automated pattern discovery must record the total number of candidate patterns searched. Failed and rejected attempts remain in the ledger so the search history cannot be cosmetically reduced.

Closely related variants are not independent evidence and may not receive multiple votes merely because they detect the same underlying structure. Register family and lineage relationships and use dependence-aware interpretation. Predeclare the correction or selection-aware method where possible; otherwise label the analysis exploratory. Report both raw and adjusted inferential quantities when meaningful.

## Sample adequacy and uncertainty

Prespecify minimum observation, event, occurrence, and trade thresholds appropriate to the horizon and dependence structure. Effective sample size, not merely row count, governs confidence. Report confidence intervals for important effect, risk, and probability estimates, including conditional win probability.

Evaluate at minimum:

- sensitivity to start/end dates and reasonable sampling choices;
- stability across rolling and expanding windows;
- degradation from training to validation to sealed evaluation;
- concentration in a small number of trades, days, events, or instruments;
- stability across periods, instruments, sessions, volatility regimes, and market regimes;
- parameter neighborhoods, not only the selected optimum;
- plausible transaction-cost and latency stress; and
- tail behavior and drawdown duration.

When observations overlap or are dependent, confidence intervals and tests must reflect that dependence. Small or unstable samples require cautious language and may justify an inconclusive decision even when point estimates are attractive.

## Backtesting and execution standard

Every backtest must be reproducible from configuration and model at minimum, when relevant:

- executable bid and ask rather than an idealized midpoint where possible;
- spread;
- commissions;
- financing and carry;
- slippage;
- latency assumptions;
- order type;
- partial fills;
- session boundaries;
- weekend gaps;
- market closures;
- data gaps;
- rollover;
- look-ahead prevention; and
- survivorship issues.

Execution assumptions must be appropriate to instrument, venue, sampling frequency, data granularity, and strategy capacity. Clearly label indicative versus executable prices. A midpoint-only study must be identified as idealized and must not be presented as net tradable performance without a documented bridge to executable assumptions.

### Required execution controls

- Generate signals using only information available before the assumed order decision.
- Apply realistic processing and order latency; do not fill at a price that preceded the decision.
- Use the correct side of the market and record spread treatment.
- Apply commissions, fees, financing/carry, and rollover consistently in time and currency.
- Define order lifecycle, time in force, cancellation, and fill priority assumptions where material.
- Model partial fills when liquidity or order type makes them relevant; otherwise document why full fills are reasonable.
- Handle sessions, holidays, closures, weekend gaps, stale quotes, and missing intervals explicitly.
- Stress slippage, spread, latency, financing, and cost assumptions beyond the central estimate.
- Separate gross signal quality, gross trading performance, transaction costs, financing, and net performance.

If data cannot support a claimed execution model—for example, bar data used to infer queue position—the limitation must constrain the claim rather than be hidden behind optimistic assumptions.

## Required reporting metrics

Standard reports must include every applicable metric below. If a metric is not meaningful, mark it not applicable and state why; do not silently omit unfavorable metrics.

### Return and risk

- total return;
- CAGR;
- annualized volatility;
- Sharpe ratio;
- Sortino ratio;
- Calmar ratio;
- maximum drawdown;
- drawdown duration;
- tail loss; and
- VaR and CVaR where meaningful.

### Trade and payoff behavior

- profit factor;
- expectancy;
- win rate;
- loss rate;
- average winner;
- average loser;
- payoff ratio; and
- trades per year.

### Implementation and portfolio behavior

- turnover;
- exposure; and
- transaction costs.

### Conditional performance

- performance by year;
- performance by asset;
- performance by session;
- performance by volatility regime; and
- performance by market regime.

### Statistical reliability

- probability calibration;
- confidence intervals;
- sensitivity to parameter changes; and
- sensitivity to execution costs.

Reports must define conventions such as return frequency, annualization factor, risk-free rate, trade counting, portfolio aggregation, missing-data treatment, and confidence-interval method. Metrics must be shown for chronological development, validation, and sealed out-of-sample partitions separately, together with gross and net results where applicable.

## Probability and calibration standard

A directional label or high win rate is not sufficient. Probabilistic models must be evaluated for calibration and resolution using prespecified appropriate tools, with reliability examined through time and across relevant regimes. State the forecast horizon, event definition, probability threshold, decision rule, class balance, and consequences of abstention.

Conditional probabilities discovered after searching filters or subgroups inherit the full search burden. Report occurrence count, effective sample size, uncertainty, base rate, costs, and adverse outcomes. A selective model may abstain, but abstention rules must be fixed before sealed evaluation.

## Pattern-specific validation

Pattern discovery creates unusually severe data-mining exposure. In addition to all general gates, each discovered pattern must pass:

- a strict chronological holdout;
- walk-forward evaluation;
- prespecified minimum occurrence/sample thresholds;
- confidence intervals;
- multiple-hypothesis correction;
- Deflated Sharpe Ratio where applicable;
- Probability of Backtest Overfitting analysis;
- stability across periods;
- stability across instruments;
- parameter-sensitivity analysis;
- transaction-cost stress tests; and
- regime decomposition.

Record the total number of candidate patterns searched. Treat spectacular results found after millions of searches with extreme skepticism. Shapelets, clustering-derived states, motifs, nearest-neighbor matches, and future machine-learning pattern models receive the same controls as explicit trading strategies. Full pattern requirements are in `docs/PATTERN_DISCOVERY.md`.

## Canonical-reproduction validation

Do not claim to have reproduced a paper when a proprietary or otherwise unavailable original dataset, universe, forecast history, feed, or implementation detail is material to the result. Record `REPRODUCED`, `PARTIALLY REPRODUCED`, or `NOT REPRODUCIBLE WITH AVAILABLE DATA` as the implementation outcome, and separately classify the study accurately as an exact reproduction, partial reproduction, conceptual replication, or robustness study. State substitutions and their likely effect.

Published results are references, not acceptance targets. A failure to reproduce must be retained and investigated for data differences, vintages, specification ambiguity, costs, sample period, coding error, and publication or selection effects without tuning merely to match the paper.

## Reproducibility gate

Before results can support a decision, an independent runner must be able to recover or identify:

- the permanent experiment ID and related model, strategy, and pattern IDs;
- hypothesis and predeclared decision criteria;
- source-code commit and repository-state disclosure;
- exact configuration and schema version;
- data providers, dataset IDs, vintages, raw hashes, and transformation lineage;
- point-in-time availability fields and chronological partitions;
- sealed-data controls and access log;
- Python/runtime and dependency lock;
- feature definitions and fitted preprocessing artifacts;
- complete candidate count and search space;
- seeds and nondeterminism controls;
- execution and transaction-cost assumptions;
- statistical methods, parameters, and software versions;
- commands required to rerun; and
- full outputs, warnings, logs, failures, and result hashes.

If exact determinism is impossible, perform registered repeated runs, quantify the variability, and identify the nondeterministic source. A result that cannot be reproduced is not admissible validated evidence.

## Decision statuses and language

Every experiment must use the canonical outcome in `EXPERIMENT_LEDGER.md`: `CONTINUE_RESEARCH`, `REVISE_NEW_EXPERIMENT`, `REJECT`, `INCONCLUSIVE`, `DEFER`, `INVALIDATED`, or `SUPERSEDED`. The decision and reason must be recorded permanently. Failed experiments remain visible, and no outcome authorizes deployment.

Use claim language proportional to the evidence. Prefer formulations such as "observed under the registered historical evaluation" and report uncertainty and limitations. Do not use "proven profitable," "guaranteed," or equivalent future-performance language.

Changes affecting research methodology or statistical validity—including partition policy, leakage rules, multiple-testing accounting, sealed-data access, cost assumptions, or acceptance thresholds—must be documented in `docs/DECISIONS.md`.

No validation outcome grants research code permission to deploy itself. No live-money trading is permitted during the initial research stages, and an LLM must not control trade execution.
