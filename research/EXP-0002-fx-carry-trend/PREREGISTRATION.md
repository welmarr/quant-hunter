# EXP-0002 — FX carry and trend, G10 + MXN vs USD (pre-registration)

Status: FROZEN before any return of this experiment was computed.
Frozen: 2026-11-09 (America/New_York). Author: Claude (agent), owner Rymaa.
Changes after commit = new experiment ID or a dated amendment below.

## Question
Do the two most documented FX premia, carry and time-series trend, earn a
positive risk-adjusted return after costs on data that post-dates their main
publications, and does combining them beat holding foreign currencies?

## Literature (rules taken from here, not tuned)
- Lustig, Roussanov, Verdelhan (2011), "Common risk factors in currency markets" (carry portfolios).
- Menkhoff, Sarno, Schmeling, Schrimpf (2012), "Currency momentum strategies".
- Moskowitz, Ooi, Pedersen (2012), "Time series momentum" (12-month lookback).
- Koijen, Moskowitz, Pedersen, Vrugt (2018), "Carry".

## Universe (fixed)
EUR, GBP, JPY, AUD, CAD, CHF, NZD, MXN against USD.
Spot: Hunter feed `yahoo.<PAIR>_X` (month-end close; pairs quoted USD per unit
are used directly, others inverted). Short rates: FRED OECD 3-month interbank
(IR3TIB01DE/GB/JP/AU/CA/CH/NZ/MX M156N; Germany stands for EUR) and US DTB3.
Rates are read with the Hunter feed store as of each month-end (point in time
under the feed's stated `available_at` rule: 45-day lag for monthly series,
1 day for daily ones; values are latest vintage, not ALFRED vintages).

## Returns
Long 1 unit of currency i over month t+1, in USD:
spot return (S_{t+1}/S_t - 1) + (r_i - r_US)/12 using rates known at t
(covered-interest-parity approximation of the forward premium).

## Strategies (decided at month-end t, held over t+1)
- P1 CARRY: rank by r_i - r_US; long the 3 highest, short the 3 lowest, 1/6 each (dollar-neutral, gross 1).
- P2 TREND: sign of the currency's cumulative 12-month long return (spot + carry); weight sign/8 each.
- P3 COMBO (PRIMARY): 0.5 * P1 + 0.5 * P2.
Costs: 5 bps per unit of one-way turnover (sensitivity 15 bps, reporting only).

## Baselines
- B1 DOLLAR: long all 8 currencies equally (short USD basket), monthly rebalanced, same costs.
- B0 CASH: zero excess return.

## Periods
- Development: first month with all rates and 12 months of spot history, through 2016-12.
- HOLDOUT: 2017-01 through 2026-10. Evaluated once, runner frozen in git first.

## Metrics
Annualised return, volatility, Sharpe (returns are already excess of USD cash),
max drawdown, share of positive months, turnover. Deflated Sharpe ratio of P3
with n_trials = 3 (P1, P2, P3) and the variance of their monthly Sharpe ratios
(Hunter `research_validation.overfitting`).

## Decision criteria (holdout, after 5 bps)
- PASS if P3 Sharpe > 0, P3 Sharpe > B1 Sharpe, and P3 max drawdown smaller in magnitude than B1's.
- STRONG PASS if additionally P3's deflated Sharpe ratio >= 0.95.
- FAIL otherwise, recorded and kept.

## Known limitations (stated before results)
Yahoo FX history contains bad ticks (see the feed quality report); month-end
closes reduce but do not remove this. Interbank rates are monthly averages,
not the exact forward points a dealer would quote. Rates are latest vintage.

## Multiple-testing count
3 strategy variants (P1, P2, P3). Hunter cumulative count including EXP-0001: 5.

## Amendments
(none)
