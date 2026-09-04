# Risk Register

## Governance

Review this register at each stage gate and whenever evidence, scope, cost, or controls change. Use permanent IDs; retain closed risks. Link mitigations to decisions, experiments, data sources, and tests. `OPEN` means the risk requires active control, not that work is authorized.

| ID | Risk | Required controls | Status |
|---|---|---|---|
| RISK-001 | Targeting a requested 75% win rate creates selection bias or fabricated claims. | Treat win rate as descriptive; preregister hypotheses and decision criteria; prioritize expectancy, robustness, calibration, drawdown, costs, sample size, regimes, and OOS evidence. | OPEN |
| RISK-002 | Large model, parameter, pattern, or AI searches create severe multiple-testing exposure. | Record every candidate and variant; use family-aware corrections, Reality Check/SPA/DSR/PBO where appropriate; retain failures. | OPEN |
| RISK-003 | Look-ahead, target leakage, or repeated holdout use invalidates results. | Enforce point-in-time joins, chronological splits, inaccessible sealed OOS data, freeze/release logs, purging and embargo where appropriate. | OPEN |
| RISK-004 | Revised macro data is mistaken for historically available information. | Preserve publication and revision times; use vintage datasets such as ALFRED/FRED or authoritative equivalents; never overwrite vintages. | OPEN |
| RISK-005 | Mutable or weakly traced data prevents reproduction. | Immutable raw storage, checksums, acquisition manifests, transformation lineage, quality reports, and exact dataset-vintage IDs. | OPEN |
| RISK-006 | Idealized prices and fills turn weak signals into attractive backtests. | Model executable bid/ask, spread, commissions, financing/carry, slippage, latency, order types, fills, sessions, gaps, closures, rollover, and cost stress. | OPEN |
| RISK-007 | Regime instability, small samples, or tail events make results unreliable. | Confidence intervals, block/bootstrap and Monte Carlo analysis, regime and instrument decomposition, parameter stability, degradation, and tail-risk reports. | OPEN |
| RISK-008 | Complex models outperform through flexibility rather than information. | Require simpler baselines, ablations, search accounting, stability tests, and cost-adjusted incremental value. | OPEN |
| RISK-009 | Closely related models or patterns receive duplicate ensemble votes. | Track lineage and dependence; cluster correlated evidence; give no extra votes for variants of the same structure. | OPEN |
| RISK-010 | Research code or AI crosses into live execution. | Separate packages, processes, credentials, and approvals; no live trading or live broker credentials in initial stages; no self-promotion. | OPEN |
| RISK-011 | Secrets or licensed data enter Git, logs, or fixtures. | Sanitized `.env.example`, secret scanning when implemented, least privilege, redacted logs, and license-aware storage. | OPEN |
| RISK-012 | Data licensing, latency, or indicative pricing makes a study unusable. | Complete source registry fields, prefer primary authoritative sources, record executable-versus-indicative status and limitations. | OPEN |
| RISK-013 | Month-1 spending exceeds USD $400 or creates lock-in. | No purchase without explicit approval; maintain cost estimates; prefer open source and free authoritative data; use expensive AI selectively. | OPEN |
| RISK-014 | Proprietary source data makes a claimed paper reproduction false. | State unavailable inputs and deviations explicitly; label the work an approximation, not a reproduction. | OPEN |
| RISK-015 | Results execute but cannot be independently reconstructed. | Pin code, configuration, environment, seeds, data vintages, and artifacts; require rerun evidence before acceptance. | OPEN |
| RISK-016 | Subjective chart labeling introduces hindsight and confirmation bias. | Require mathematical pattern definitions, registered search spaces, blind/OOS evaluation, and uncertainty estimates. | OPEN |

## Escalation

Stop and record a decision when a control cannot be satisfied, a sealed dataset may have been exposed, provenance is incomplete, a result depends on unavailable proprietary data, a credential may have leaked, or a purchase is proposed. Scientific or safety controls may not be waived for schedule pressure.
