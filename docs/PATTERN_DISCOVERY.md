# Pattern Discovery and Structural Recognition

## Purpose and Scope

Quant Hunter must treat Pattern Discovery as a first-class research module. Its purpose is to investigate algorithms that discover recurring, predictive, anomalous, transitional, and regime-specific structures directly from market and contextual time-series data.

The lab is not limited to manually named chart patterns such as triangles, flags, head-and-shoulders, double tops, candlestick formations, or support/resistance patterns. Traditional structures may be investigated, but only through mathematical definitions and scientific testing.

This document defines the required research scope and governance. It does not authorize strategy implementation or live trading.

## Pattern Lab Principle

The objective is not:

> Find a chart that looks like something seen previously.

The objective is:

> Determine whether statistically recurring market structures exist, establish their conditional future distributions, determine under which regimes they remain predictive, and reject patterns that cannot survive rigorous out-of-sample testing.

Pattern discovery should ultimately become an independent evidence family within the Quant Hunter Meta Engine alongside:

- trend;
- momentum;
- carry;
- value;
- macro;
- volatility;
- statistical arbitrage;
- market microstructure;
- cross-asset;
- regime; and
- machine learning.

Pattern-family models must not receive multiple votes merely because many closely related variants detect the same underlying structure. Ensemble design must identify correlated or duplicate evidence and prevent family-size voting advantages.

## Required Methodological Families

The research program must design support for at least the following families. This is a minimum scope, not an exhaustive list.

### A. Time-Series Motif Discovery

Investigate:

- Matrix Profile;
- matrix-profile motif discovery;
- discord and anomaly detection;
- nearest-neighbor subsequence search;
- repeated-subsequence mining; and
- multivariate motif discovery.

The system should identify historical subsequences that resemble the current market state and evaluate the distribution of returns that followed those subsequences.

### B. Dynamic Time Warping

Support Dynamic Time Warping (DTW) and appropriate variants for comparing patterns with similar structure but different durations or temporal alignments. Research:

- DTW distance;
- constrained DTW;
- derivative DTW;
- multivariate DTW;
- nearest-neighbor classification using DTW; and
- computational acceleration techniques.

Do not permit uncontrolled brute-force matching. Candidate search, constraints, pruning, and computational budgets must be explicit and reproducible.

### C. Shapelet Discovery

Investigate time-series shapelets that identify subsequences discriminative for:

- direction;
- volatility expansion;
- breakout probability;
- reversal probability;
- drawdown risk; and
- regime transition.

Evaluate shapelets out of sample and subject them to the same multiple-testing controls as trading strategies.

### D. Symbolic Time-Series Mining

Investigate:

- SAX (Symbolic Aggregate approXimation);
- symbolic sequences;
- grammar-based pattern discovery;
- frequent sequential-pattern mining; and
- transition probabilities.

Evaluate whether symbolic representations can convert noisy continuous market behavior into useful, searchable state sequences.

### E. Change-Point Detection

Provide a research framework for detecting structural changes. Investigate:

- CUSUM;
- Bayesian Online Change Point Detection;
- PELT;
- kernel change-point detection;
- variance-change detection; and
- distributional-change detection.

Potential detection targets include changes in:

- mean return;
- volatility;
- correlation;
- spread;
- liquidity;
- order flow;
- factor exposure;
- trend strength; and
- market regime.

### F. Hidden-State and Sequence Models

Investigate:

- Hidden Markov Models;
- Gaussian HMMs;
- switching autoregressive models;
- Markov-switching models; and
- semi-Markov models where useful.

These methods may be used to identify recurring sequences such as:

```text
CALM
-> COMPRESSION
-> LIQUIDITY SHIFT
-> BREAKOUT
-> TREND
-> EXHAUSTION
-> REVERSAL
```

Do not assign economic meaning to latent states automatically. Infer interpretations only after statistical analysis.

### G. Signal-Processing Pattern Analysis

Investigate:

- Fourier transforms;
- wavelet transforms;
- continuous wavelet transforms;
- discrete wavelets;
- multiresolution analysis;
- spectral density; and
- Hilbert transforms where justified.

Do not assume markets are periodic. Use these methods to investigate changes in dominant timescales, transient structures, volatility bursts, and multiscale behavior.

### H. Recurrence Analysis

Research:

- recurrence plots;
- recurrence quantification analysis;
- recurrence rate;
- determinism;
- laminarity; and
- trapping time.

Evaluate whether recurrence properties contain useful information about market-state transitions or predictability.

### I. Unsupervised Trajectory Clustering

Support clustering of normalized historical market trajectories using methods such as:

- hierarchical clustering;
- k-medoids;
- density-based clustering;
- spectral clustering;
- DTW-based clustering; and
- representation-based clustering.

Do not force every sequence into a cluster. The system must allow an `UNKNOWN` or out-of-distribution (`OOD`) state. For each discovered cluster, measure the distribution of future outcomes instead of automatically assigning a directional prediction.

### J. Structural and Geometric Pattern Recognition

Research algorithmic definitions of traditional and nontraditional structures, including:

- breakouts;
- channels;
- triangles;
- wedges;
- flags;
- double tops and bottoms;
- head-and-shoulders;
- support/resistance structures;
- volatility compression;
- failed breakouts;
- liquidity sweeps;
- trend exhaustion; and
- gap behavior where relevant.

Every pattern must be mathematically defined and tested. Subjective visual labeling is never sufficient evidence.

### K. Multivariate Patterns

Pattern discovery must operate on more than price. A market pattern may combine simultaneous behavior in:

- returns;
- bid;
- ask;
- spread;
- volatility;
- volume;
- order flow;
- liquidity;
- interest rates;
- yield differentials;
- commodities;
- equity indices;
- volatility indices;
- positioning;
- macroeconomic state;
- time of day;
- trading session; and
- proximity to economic releases.

Develop representations capable of discovering multivariate motifs. For example, the following combination may constitute a pattern even when the price chart alone appears unremarkable:

```text
LOW VOLATILITY
+ TIGHT SPREAD
+ RISING RATE DIFFERENTIAL
+ NEGATIVE USD ORDER FLOW
+ LONDON OPEN APPROACHING
```

### L. Pattern-to-Outcome Database

Every discovered pattern must become a durable research object with a permanent identifier, for example `PATTERN-MP-0042`. Patterns must not remain arbitrary chart labels.

For each pattern, store at minimum:

- discovery algorithm;
- definition;
- features;
- normalization method;
- similarity metric;
- historical matches;
- time horizon;
- markets;
- regimes;
- subsequent-return distribution;
- conditional win probability;
- average favorable excursion;
- average adverse excursion;
- tail outcomes;
- transaction-cost-adjusted expectancy;
- sample size;
- confidence interval;
- stability through time;
- parameter sensitivity;
- out-of-sample performance;
- discovery dataset and exact training/development partition manifest;
- development-validation dataset;
- untouched, sealed out-of-sample validation dataset and recorded access-release event; and
- number of candidate patterns searched.

The identifier and metadata must remain stable so results, failures, revisions, and dependent experiments can be traced over time.

### M. Nearest-Historical-State Engine

Design a future component capable of answering:

> Which historical market states were most similar to the current state, and what happened afterward?

The state vector may include price behavior together with:

- volatility;
- spread;
- rates;
- macro conditions;
- cross-asset behavior;
- market regime;
- session information; and
- order-flow information.

The engine must return a probability distribution of outcomes, not merely a `BUY` or `SELL` instruction.

### N. Pattern Validation

Pattern discovery creates an especially severe data-mining problem. Every discovered pattern must pass:

- strict chronological holdout;
- walk-forward evaluation;
- minimum occurrence and sample thresholds;
- confidence intervals;
- multiple-hypothesis correction;
- Deflated Sharpe Ratio where applicable;
- Probability of Backtest Overfitting analysis;
- stability checks across periods;
- stability checks across instruments;
- parameter-sensitivity analysis;
- transaction-cost stress tests; and
- regime decomposition.

Record the total number of patterns searched, including unsuccessful candidates and closely related variants. A spectacular result found after searching millions of possible structures must be treated with extreme skepticism.

### O. Future Machine-Learning Pattern Models

Prepare interfaces for the following model families, but do not prioritize them before classical pattern methods are functioning:

- convolutional neural networks (CNNs);
- temporal convolutional networks;
- autoencoders;
- variational autoencoders;
- transformers;
- contrastive representation learning;
- self-supervised time-series models; and
- graph neural networks where cross-market topology warrants them.

These models must compete against simpler baselines. Complexity is not evidence of superiority.

## Cross-Cutting Research Rules

All pattern research is governed by the project's general scientific, data, validation, reproducibility, cost, security, and deployment standards. In particular:

- Discovery and evaluation datasets must respect chronological boundaries, including any sealed or untouched validation interval.
- Pattern definitions, features, normalization, similarity measures, parameters, candidate-search spaces, code versions, data vintages, and random seeds where applicable must be reproducible.
- Pattern outcomes must be evaluated as conditional distributions with uncertainty, tail behavior, costs, and adverse excursion—not reduced to attractive win-rate summaries.
- Failed, unstable, duplicated, and rejected patterns remain part of the research record.
- Pattern candidates generated by AI or automated search count toward multiple-testing exposure exactly as human-proposed candidates do.
- Advanced models and elaborate representations must demonstrate incremental value against simpler, transparent baselines.

## Governing Documents

- Register pattern identities and lineage consistently with `MODEL_REGISTRY.md`.
- Register every discovery and validation run in `EXPERIMENT_LEDGER.md`.
- Apply all chronological, multiple-testing, execution, robustness, and reporting gates in `VALIDATION_STANDARD.md`.
- Use point-in-time inputs governed by `DATA_ARCHITECTURE.md` and registered sources from `DATA_SOURCE_REGISTRY.md`.
- Record methodological or statistical-validity changes in `DECISIONS.md`.
