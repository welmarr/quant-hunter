# EXP-0002 — Results

Decision (pre-registered rule, holdout, P3 vs B1 after 5 bps): **PASS** (not STRONG PASS).
Evaluated once on 2026-11-10 (UTC). Runner frozen at `eecd3be`; pre-registration `2a43077`.

## Holdout 2017-01 .. 2026-10 (118 months, after 5 bps)

| | Ann. return | Vol | Sharpe | Max DD | Positive months |
|---|---:|---:|---:|---:|---:|
| P1 carry | 2.1% | 3.3% | 0.64 | -6.2% | 64% |
| P2 trend | -1.4% | 4.7% | -0.29 | -16.9% | 51% |
| **P3 carry + trend (primary)** | **0.4%** | **3.0%** | **0.13** | **-6.7%** | 53% |
| B1 long 8 currencies vs USD | 0.0% | 6.8% | -0.00 | -16.4% | 52% |

P3 deflated Sharpe ratio (3 trials): 0.20. Probability that P3's true Sharpe exceeds zero: 0.65.

## Development 2007-06 .. 2016-12 (115 months)

P1 0.06, P2 -0.08, P3 -0.03, B1 0.04 (Sharpe). The sample starts in mid-2007 because
Yahoo's AUD/USD history begins in 2006-05 and trend needs 12 months.

## Interpretation (honest)

- The primary rule passes the pre-registered test only formally: 0.4% a year, and a deflated
  Sharpe of 0.20 says this is very likely not real skill. It is not tradable as is.
- Carry alone (P1) did well in the holdout (Sharpe 0.64), after doing nothing in 2007-2016
  (which includes the 2008 carry crash). P1 was a secondary variant: this is a hypothesis
  for a new pre-registered experiment, not a finding.
- FX trend lost money in both periods, in line with the documented decay of FX momentum.

## Limitations

Yahoo FX history contains bad ticks; monthly OECD interbank rates stand in for forward
points; rates are latest vintage; 5 bps costs assume a good retail FX broker.
