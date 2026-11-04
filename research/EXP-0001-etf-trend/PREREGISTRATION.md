# EXP-0001 — Time-series trend on a diversified ETF universe (pre-registration)

Status: FROZEN before any data was downloaded or any result computed.
Frozen: 2026-11-04 (America/New_York). Author: Claude (agent), owner Rymaa.
Any change after this file is committed must be a new experiment ID or a dated
amendment section below, never a silent edit.

## Question
Does a simple, published trend rule improve risk-adjusted outcomes versus
buy-and-hold of the same assets, after costs, on data that was NOT available
to the papers that proposed it?

## Literature (parameters are taken from here, not tuned)
- Moskowitz, Ooi, Pedersen (2012), "Time series momentum", JFE — 12-month lookback, monthly rebalance.
- Hurst, Ooi, Pedersen (2017), "A Century of Evidence on Trend-Following Investing", JPM.
- Faber (2007), "A Quantitative Approach to Tactical Asset Allocation" — long-only, equal-weight, move to cash when trend is negative.

## Universe (fixed)
Risk assets (9): SPY, EFA, EEM, IEF, TLT, LQD, GLD, DBC, VNQ. Cash proxy: SHY.
An asset enters only after 13 monthly observations exist. Choice reflects
liquid US-listed ETFs covering equities, bonds, credit, gold, commodities,
real estate with long histories; chosen before seeing results.

## Data
Monthly dividend-and-split-adjusted closes (month-end), single free public
source, raw response stored immutably with SHA-256 and retrieval time.

## Rules
- Signal at month-end t: 12-month total return of asset minus 12-month total return of SHY.
- PRIMARY (P1): long-only, equal 1/N_t slice per available risk asset; slice is
  held in the asset if signal > 0, otherwise in SHY.
- SECONDARY (S1): same, but slices weighted by inverse trailing 12-month volatility (monthly returns).
- Trade at month-end t close, hold over month t+1 (market-on-close assumption).
- Costs: 10 bps per unit of one-way turnover (sensitivity: 25 bps, reported, not used for decision).

## Baselines
- B1 equal-weight buy-and-hold of the same available risk assets, rebalanced monthly (same costs).
- B2 60% SPY / 40% IEF, rebalanced monthly. B3 SPY.

## Periods
- Development: first eligible month through 2016-12. Results may be looked at.
- HOLDOUT: 2017-01 through last full month available (≈ 2026-10). Post-publication
  of all three papers. Evaluated ONCE, with code unchanged after development run.

## Metrics
CAGR, annualised volatility, Sharpe (excess over SHY), max drawdown, Calmar,
share of positive months, annual turnover; difference P1–B1 Sharpe with
stationary-bootstrap 90% CI (block 6 months, 5,000 draws, seed 20261104).

## Decision criteria (holdout, P1 vs B1, after 10 bps costs)
- PASS if: max drawdown at least 30% smaller in magnitude AND Sharpe not lower by more than 0.10.
- STRONG PASS if additionally the Sharpe-difference 90% CI lies above 0.
- FAIL otherwise. A FAIL is recorded and kept.
Honest note: ~10 years of monthly data cannot establish a Sharpe difference
with high confidence; the drawdown criterion is the primary practical test.

## Multiple-testing count
2 strategy variants (P1, S1). Cost sensitivity is reporting only.

## Amendments
(none)
