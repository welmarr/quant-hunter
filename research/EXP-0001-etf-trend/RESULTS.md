# EXP-0001 — Results

Decision (pre-registered rule, holdout, P1 vs B1 after 10 bps): **PASS** (not STRONG PASS).
Evaluated once on 2026-11-04. Holdout file: `results/holdout.json`.
Code commit frozen before holdout: `7f8a383`. Pre-registration: `2bb8e07`.

## Holdout 2017-01 .. 2026-10 (118 months, after 10 bps)

| | CAGR | Vol | Sharpe | Max DD | Calmar | Turnover/yr |
|---|---:|---:|---:|---:|---:|---:|
| P1 trend, equal weight | 5.2% | 5.7% | 0.66 | -9.5% | 0.55 | 2.85 |
| S1 trend, inverse vol | 4.2% | 5.0% | 0.55 | -9.2% | 0.46 | 3.20 |
| B1 equal-weight buy & hold | 7.4% | 9.6% | 0.65 | -19.4% | 0.38 | 0.28 |
| B2 60/40 SPY/IEF | 9.5% | 10.1% | 0.81 | -20.5% | 0.46 | 0.20 |
| B3 SPY | 15.0% | 15.4% | 0.88 | -23.9% | 0.63 | 0 |

P1 vs B1: drawdown 51% smaller; Sharpe difference +0.01, 90% bootstrap CI [-0.26, +0.23].

## Development 2003-09 .. 2016-12 (160 months)

P1: CAGR 6.6%, Sharpe 0.74, max DD -7.4%. B1: 7.1%, 0.53, -31.6%. B3 SPY: 8.3%, 0.49, -50.8%.

## Interpretation (honest)

- The rule does what the literature says it does out of sample: it cuts drawdowns roughly in half or more.
- It does NOT show better risk-adjusted return than holding the same assets in the holdout (Sharpe equal), and
  it is clearly worse than 60/40 or SPY on return and Sharpe in 2017-2026, a strong US-equity decade.
- In development it beat buy-and-hold mostly because of 2008; that edge did not repeat in size.
- Conclusion: a defensive overlay (lower drawdown, lower return), not a return engine. Not evidence of an exploitable edge.
- Cost sensitivity: at 25 bps P1 Sharpe 0.58 vs B1 0.64 -> drawdown benefit remains, Sharpe slightly worse.

## Verification

- Independent vectorized recomputation of P1 gross returns matched the engine (max abs diff 3e-18).
- Look-ahead placebo (same-month signal) gives development CAGR 11.2% vs 6.6% -> engine uses only past data.
- Limitations: one data source (Yahoo adjusted closes, not cross-checked), month-end close execution assumed,
  monthly data only, SHY as cash (not T-bills), 2 variants tested.
