# Quant Hunter Research Methodology

## Status and scope

This document is the normative method for proposing, registering, conducting, reproducing, and interpreting Quant Hunter research. It applies to human-authored work, automated searches, AI-generated hypotheses, models, strategies, ensembles, patterns, and execution studies. `docs/VALIDATION_STANDARD.md` defines the minimum evidence required to evaluate those research objects.

Quant Hunter is an independent quantitative research and market-hunting platform, not an instruction to build a trading bot immediately. Its long-term purpose is to combine established quantitative-finance research, high-quality market and economic data, statistical validation, machine learning, and—only later—advanced AI reasoning.

The aspirational objective is to find highly selective opportunities with strong risk-adjusted performance and to investigate whether robust subsets can approach or exceed a 75% win probability. That figure is a research question, never a target to manufacture or optimize toward. Historical performance is not evidence of future profitability.

## Scientific priorities

Research decisions must prioritize, in order appropriate to the hypothesis:

- scientific integrity and reproducibility over an attractive backtest;
- positive expectancy and probability calibration over raw win rate;
- out-of-sample evidence, robustness, and sample adequacy over in-sample fit;
- drawdown, tail risk, and regime stability over headline return;
- transaction costs and realistic execution over idealized fills;
- transparent limitations over unsupported certainty; and
- simpler defensible baselines over complexity that does not earn its place.

Never fabricate a 75% win rate, tune merely to reach one, or describe a strategy as having alpha solely because Sharpe ratio, profit factor, win rate, or CAGR looks attractive. Failed and rejected hypotheses are valuable scientific results and must remain permanently recorded.

AI enhances quantitative science; it does not replace statistical validation.

## Required research progression

The project proceeds from the bottom upward:

```text
DATA
  -> DATA QUALITY
  -> MATHEMATICS / ECONOMETRICS
  -> RESEARCH REPRODUCTION
  -> STRATEGY FAMILIES
  -> EXPERIMENTATION
  -> ANTI-OVERFITTING
  -> ENSEMBLES / META-MODELS
  -> AI RESEARCH LAYER
  -> PAPER TRADING
  -> SHADOW VALIDATION
  -> ONLY EVENTUALLY CONTROLLED CAPITAL
```

Later stages must not be used to bypass unfinished earlier stages. Stage 1 builds the infrastructure that makes later experiments scientifically defensible; it does not implement approximately 200 strategies. Stage 1 succeeds only when the repository functions as a reproducible quantitative research laboratory in which it is difficult to accidentally fool ourselves.

No live-money trading is permitted during the initial research stages. Do not create or connect live broker credentials. Paper-trading adapters belong to a later milestone, and paper trading must precede shadow validation and any controlled-capital proposal. Research code must not be able to approve, promote, or deploy itself directly into production.

## Research-family program

The long-range target is approximately 200 or more serious models drawn from genuinely distinct research families, not hundreds of parameter variations of the same indicator. Parameter variants remain variants of a family and count toward that family's multiple-testing exposure.

`MODEL_REGISTRY.md` is the canonical owner of the complete initial research-family catalog, the distinction between families and variants, and permanent model/strategy identity. That taxonomy is deliberately open: additions require strong academic or institutional grounding and a permanent registry record. Methodology consumes that catalog rather than maintaining a duplicate list.

## Permanent identity and prior registration

Every strategy, model, pattern, and experiment must have a permanent, immutable identifier. An identifier may never be recycled or reassigned. Relationships among objects—such as a strategy using a model, or an experiment testing a pattern—must be explicit.

Every experiment must be registered in `docs/EXPERIMENT_LEDGER.md` before result-seeking computation begins. Registration establishes the hypothesis, search space, data partitions, evidence standard, and multiple-testing exposure. Exploratory work is allowed only when labeled exploratory; converting an exploratory finding into confirmatory evidence requires a new experiment on data that was not used to generate the finding.

`EXPERIMENT_LEDGER.md` is the canonical owner of the complete minimum registration schema. In addition to the original hypothesis, family, data, partition, search, test, result, decision, code, seed, and timestamp fields, it requires related permanent object IDs, provenance, exact configuration/hash, earlier-experiment dependencies, and study type. Methodology must not redefine a weaker local schema.

The count of attempted variants includes manual parameter choices, automated searches, discarded trials, AI-generated candidates, and materially different data or feature choices. Rejected, failed, inconclusive, interrupted, and superseded experiments must never silently disappear. Their records remain append-only, with status and failure reasons preserved.

## Experiment lifecycle

### 1. Frame the question

State a falsifiable hypothesis, its economic or structural rationale, the relevant research family, expected mechanism, prediction horizon, target population, and what observation would count against it. Distinguish prediction from explanation and exploratory discovery from confirmatory testing.

### 2. Establish provenance and availability

Identify every dataset, field, provider, license constraint, vintage, and transformation. Raw source data remains immutable. Derived data must be traceable to raw inputs and deterministic transformations.

For time-dependent information, preserve and reason from event time, publication time, ingestion time, and revision time separately. Information is usable at a simulated decision point only if it was publicly available and operationally obtainable then. Revised macroeconomic values may not be substituted for the values known historically.

### 3. Pre-register the design

Create the permanent experiment record before observing results. Freeze the hypothesis, inclusion rules, features, parameters or bounded search space, baselines, splits, cost model, metrics, statistical tests, acceptance criteria, random seeds where applicable, and the number of contemplated variants.

### 4. Build simple baselines

Every complex model must compete with appropriately simple baselines, including naive, constant, linear, or established domain baselines where applicable. Complexity must justify itself through durable out-of-sample improvement after costs, not through novelty or in-sample fit.

### 5. Develop without access to sealed data

Use only the registered training and development-validation partitions. Strategy-development workflows—including notebooks, feature searches, automated tuning, and AI agents—must be technically unable to read the sealed out-of-sample data until the experiment is frozen.

### 6. Freeze the experiment

Record the source commit, environment and dependency lock, data identifiers and vintages, data hashes, full configuration, split boundaries, seeds, search count, and planned analyses. The frozen artifact must be sufficient for an independent rerun.

### 7. Unseal and evaluate

After freeze, grant controlled, logged access to the sealed interval and run the prespecified evaluation. The sealed result is not another tuning set. Any change prompted by seeing it creates a new hypothesis and experiment ID and must use a genuinely untouched validation interval. Data cannot become "sealed" again after exposure.

### 8. Decide and retain

Record results, uncertainty, failure modes, statistical tests, decision, and reasoning using the canonical decision vocabulary in `EXPERIMENT_LEDGER.md`. Never delete an unfavorable result. `CONTINUE_RESEARCH` authorizes further research only; it does not authorize live trading or self-promotion to production.

## Sealed out-of-sample protocol

The sealed interval is evidence held in reserve, not merely a date range in a configuration file. Until freeze:

- development code, notebooks, report generation, search services, and AI workflows must not have read permission to sealed observations or labels;
- summary statistics, plots, cached features, model-selection outputs, and indirect derivatives of the sealed interval are also prohibited;
- partition identity, access grants, access timestamps, and any accidental exposure must be logged;
- an accidental exposure invalidates the seal and must be recorded; and
- validation split design must account for label overlap, leakage through normalization or feature fitting, embargo needs, and the information actually available at each decision time.

The definitive implementation controls and claim rules are specified in `docs/VALIDATION_STANDARD.md`.

## Canonical research reproduction program

Before proprietary combinations are treated as a core research program, reproduce approximately ten foundational areas. The purpose is to validate data, mathematics, costs, controls, and reporting—not to force confirmation of published results.

| Program | Foundational area | Reproduction focus |
|---|---|---|
| CRP-01 | Time-Series Momentum | Directional persistence across horizons and instruments under chronological testing and realistic turnover. |
| CRP-02 | Currency Momentum | Cross-sectional and/or time-series currency momentum, portfolio formation, ranking choices, and FX implementation constraints. |
| CRP-03 | FX Carry | Returns associated with interest-rate differentials, including financing, crash exposure, and regime dependence. |
| CRP-04 | Value + Momentum | Individually and jointly specified value and momentum signals, interaction rules, and portfolio-construction effects. |
| CRP-05 | Cointegration / Error Correction | Long-run equilibrium relationships, residual dynamics, re-estimation, structural breaks, and trading frictions. |
| CRP-06 | PCA / Statistical Arbitrage | Common-factor extraction, residual construction, stability, universe effects, and turnover/capacity constraints. |
| CRP-07 | Volatility Forecasting / GARCH | ARCH/GARCH-family forecasts, forecast loss functions, distributional assumptions, and benchmark comparisons. |
| CRP-08 | Volatility Management | Volatility scaling or targeting, estimation lag, leverage constraints, crash behavior, and transaction costs. |
| CRP-09 | Macroeconomic Announcement Surprises | Consensus-versus-actual surprises using point-in-time calendars, exact publication timing, revisions, latency, and executable pricing. |
| CRP-10 | Market Microstructure / Order Flow | Bid/ask, spread, liquidity, trade/order-flow measures, clock choice, feed limitations, and execution sensitivity. |

For every program, create a registered study dossier that identifies all of the following:

- seminal or otherwise strong research and a precise citation;
- the hypothesis being reproduced;
- required data and required data vintages;
- mathematical formulation, including estimators and portfolio rules;
- reproducibility difficulties;
- expected implementation complexity;
- transaction-cost sensitivity;
- known criticisms;
- known periods of failure;
- applicability to FX; and
- whether retail-accessible data is sufficient.

Each reproduction must state which elements are exact, approximate, substituted, or unavailable. Record the implementation outcome as `REPRODUCED`, `PARTIALLY REPRODUCED`, or `NOT REPRODUCIBLE WITH AVAILABLE DATA`. Separately classify the study design as an exact reproduction, partial reproduction, conceptual replication, or robustness study where appropriate. If the original proprietary dataset, universe construction, forecasts, order-flow feed, or other material input is unavailable, do not claim an exact paper reproduction; state the limitation explicitly.

### Reproduction workflow

1. Verify the source and distinguish the published specification from later interpretations.
2. Translate the hypothesis and equations into a versioned implementation specification.
3. Map every required field to a provenance-tracked, point-in-time dataset.
4. Register deviations, substitutions, search choices, and expected multiple-testing exposure.
5. Reproduce the simplest published or defensible baseline first.
6. Validate the implementation on synthetic or hand-checkable cases before empirical evaluation.
7. Apply chronological validation, realistic costs, robustness checks, and the full reporting standard.
8. Compare results without forcing agreement, explain discrepancies, and retain negative outcomes.

## Reproducibility requirements

Every backtest and empirical result must be reproducible from configuration. A reproducible experiment package must identify or preserve:

- permanent experiment, strategy, model, and pattern IDs as applicable;
- source-code commit and clean/dirty repository state;
- complete machine-readable configuration and schema version;
- data-source identifiers, dataset versions/vintages, raw-data hashes, and transformation lineage;
- chronological partition boundaries and sealed-data access history;
- environment, Python version, dependency lock, and relevant platform details;
- deterministic seeds and deterministic execution settings where applicable;
- feature definitions and fitted preprocessing state;
- model parameters and the complete candidate/search space;
- transaction-cost and execution assumptions;
- commands needed to rerun the experiment;
- statistical tests, software versions, and decision thresholds; and
- output artifacts, logs, warnings, failures, and result hashes.

If nondeterminism cannot be eliminated, quantify it by repeated runs and record its sources. Results that cannot be reproduced are not admissible evidence.

## Interpretation and decision discipline

Research reports must distinguish estimated effect size from uncertainty, statistical significance from economic significance, gross from net performance, calibration from discrimination, and exploration from confirmation. Conclusions must be proportional to sample size and validation strength.

Positive expectancy, robustness, calibration, drawdown, sample size, transaction costs, regime stability, and out-of-sample performance take priority over raw win rate. Research must examine degradation from training to validation to sealed evaluation and report material regime, instrument, session, and time-period dependence.

Methods that affect research methodology, leakage controls, multiple testing, statistical validity, or access to sealed data require an entry in `docs/DECISIONS.md` before or with the change. Unresolved assumptions must be recorded there rather than silently guessed.

## AI research boundary

Future AI agents may be given interfaces to:

- research literature;
- generate hypotheses;
- inspect experiment results;
- identify possible regime changes;
- suggest new datasets;
- critique strategies;
- detect suspicious results;
- write candidate implementations; and
- compare competing explanations.

An LLM must not be responsible for trade execution. An AI-authored candidate receives no evidentiary privilege: it must be registered, reproducible, and pass exactly the same validation as a human-designed candidate. Every AI-generated strategy, prompt-induced variation, rerun, parameterization, and selected candidate counts toward the relevant multiple-testing budget, including candidates never promoted to a final report.

## Relationship to other records

- `docs/VALIDATION_STANDARD.md` defines statistical, chronological, execution, robustness, and reporting gates.
- `docs/EXPERIMENT_LEDGER.md` is the permanent append-only experiment record and schema authority.
- `docs/MODEL_REGISTRY.md` governs permanent model and strategy identity and lineage.
- `docs/DATA_ARCHITECTURE.md` governs raw immutability, point-in-time semantics, and transformation lineage.
- `docs/DATA_SOURCE_REGISTRY.md` records provider, licensing, vintage, reliability, price-quality, and cost facts.
- `docs/PATTERN_DISCOVERY.md` applies this method to pattern research and its unusually severe search exposure.
- `docs/DECISIONS.md` records material methodological decisions and unresolved assumptions.
