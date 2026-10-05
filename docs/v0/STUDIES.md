# Synthetic study execution adapters

`research_methods/studies.py` connects twelve deterministic input profiles to the
reviewed mathematical cores. Ten are the mission CRP-01 through CRP-10 domains;
ENS-COV and META-OOF are additional comparison demonstrations. These domain keys
are not permanent STRAT, FAM, MODEL or EXP IDs. This module has no registry,
ledger, file, network, credential, sealed-data, broker or promotion authority.

Every fixture and result is **SYNTHETIC**. Outputs are software/mathematical
demonstrations, not historical replication, investment recommendations, reliable
confidence scores, validated strategies or evidence of future profitability.
The root application must register each requested variant through Item8, freeze
it, begin its attempt, execute once and preserve success or failure. Scientific
outcomes remain INCONCLUSIVE. The result's `EMPIRICALLY_UNVALIDATED` assessment
describes its limitation; it is not a scientific lifecycle decision.

## Preparation and execution boundary

`list_studies()` returns frozen `StudyDefinition` records with the study ID,
title, original-paper URL, named variant, one parameter's name/default/bounds,
sensitivity value, implemented scope, expected null behavior, assumptions and
cost model. The paper URL appears in catalogue metadata only. Source/version and
formula details are in [RESEARCH_METHODS.md](RESEARCH_METHODS.md); these adapters
do not upgrade that source map into an empirical replication claim.

`prepare_study(study_id, scenario="POSITIVE", parameter=None)` returns a JSON
configuration dictionary and exact RFC8785 canonical dataset bytes. Preparation
only constructs inputs: fixed arrays, timestamp metadata and seeded generative
samples. It does not fit a model, calculate a signal, score a forecast, allocate
a portfolio or inspect a result. Tests replace every evaluation function with
one that raises and successfully prepare every scenario in every domain.

`execute_study(payload_bytes, config)` performs one calculation using those
retained bytes. Only the governed runner should call it after Item8 freezing and
beginning the run. The Python function cannot authenticate that external
authority by itself. It does not search configurations or retry fits. Optimizer
failure and unavailable/degenerate inputs propagate as controlled errors; there
is no fallback constant presented as a successful result. The root runner must
record the failed attempt and retain its exact source/configuration/data graph.

Available scenarios are POSITIVE, NULL and SENSITIVITY. Each requested scenario
or explicit parameter change is a separate registered variant and search
exposure. The positive/null cases were defined for mathematical controls, not
selected from historical strategy performance. SENSITIVITY uses the catalogue's
predeclared alternate parameter when no explicit value is supplied. A null may
be a successful zero mechanism, residual cost drag or an expected failed fit;
those different outcomes are disclosed below.

## Frozen input and output shape

The configuration contains:

- `kind="CRP_STUDY"`, format version, study/domain ID, named variant, scenario,
  parameter name/value, SYNTHETIC evidence mode and MATHEMATICAL_DEMONSTRATION
  purpose;
- actual half-open `dataset_start`/`dataset_end`, `training_start`, inclusive
  `train_end` and `training_end_exclusive=train_end+1 microsecond`;
- `decision_at`, strictly later `target_start`, `target_end`,
  `target_available_at`, and an explicit `cost_per_unit_turnover`.

Root integration must use those training boundaries for the frozen temporal
plan. A midpoint split of the complete dataset is incorrect for these profiles:
for example, CRP-05 has300 training observations followed by one query and target.
The declared dataset interval includes all input metadata timestamps, including
older economic periods, prior fold cutoffs and consensus receipt times; its end
is one microsecond after the latest retained timestamp.

Dataset bytes contain a format/version binding, domain/variant/scenario/parameter,
declared observation kind, an `observations` array of `{at,available_at,values}`,
domain-specific `inputs`, and an explicitly typed `target`. The target identifies
its start/end, event time, actual availability and vector values. Structured
inputs preserve fundamentals, forward quotes, announcements, book updates or
OOF rows with their distinct dates and units. Fixed aligned column contracts and
target kinds are checked; arbitrary unit substitutions are rejected.

The complete dataset must be canonical JSON, at most2 MB, with finite I-JSON
numbers, unique keys, arrays bounded to4,096 and vectors bounded to64. Duplicate
keys, excess nesting, inconsistent config bindings, malformed timestamps,
contradictory coverage and unsafe parameter/cost values fail. Future numeric
observation/event payloads are passed unread to the core's availability filter;
changing a future value, even to a JSON string that would fail numerical
validation once visible, cannot enter an earlier fit or signal. Canonical JSON
itself never permits NaN/Infinity. Structural time/dimension contradictions still
fail immediately. Query information must be available by decision. ECM previous
levels exactly match the retained last training observation; its query is a
separately dated later observation, and its target is the next-observation delta.
GARCH decides immediately after its completed training period and scores the next
innovation period. META-OOF preserves a one-hour label horizon and two-hour
availability lag from each prediction for both training and the query. These
forecast-specific contracts reject a silently changed target horizon even when
the generic dataset coverage metadata remains internally consistent.

Outputs include actual `signals`, `fitted_model`, `metrics`, optional `accounting`
and `comparison`, declared timing, limitations, and SHA-256 digests of both exact
payload bytes and canonical configuration. Dataclass fits are serialized rather
than replaced by display constants. The canonical root evidence graph must bind
these outputs to actual code bytes, dependency environment, configuration,
dataset, registry IDs and the frozen Item8 attempt. These local digest fields do
not independently establish that graph.

## Domain profiles and their limits

| Domain | Executed mathematics and predeclared parameter | Fixture and null behavior |
|---|---|---|
| CRP-01 | `time_series_momentum`; target volatility0.1, bounded0.01–0.5 | Prices100,110,99,108.9; rolling sample volatility,12 periods/year. Constant-price null produces explicit ZERO_VOLATILITY and zero position. This is a disclosed rolling-volatility/price-return adaptation. |
| CRP-02 | `fx_cross_section_momentum`; gross-exposure multiplier1, bounded0.25–2 | Synchronized three-currency excess returns; centered ranks rather than the paper's six portfolios. Equal-return null gives zero weights. Synthetic excess returns are declared to include financing. |
| CRP-03 | `forward_carry`; forward quote1.20, bounded0.5–2 | Spot1.25, domestic-per-foreign quote, explicit maturity and separately supplied terminal spot1.27. Carry is not confused with realized payoff. Flat forward/terminal spot null has zero gross payoff but still pays configured entry cost. |
| CRP-04 | `value_momentum`; gross-exposure multiplier1, bounded0.25–2 | Three aligned price series and dated positive book/share releases. Paper gross-two becomes core gross-one, then the explicit demo multiplier applies. Equal price/book null gives zero ranks. |
| CRP-05 | `fit_cointegration` and `ecm_forecast`; known query-level shift0, bounded−5–5 | Same fixed seed412 generator as reviewed math tests:300 common-random-walk observations with AR residuals. Seed801 stationary null fails I(1) eligibility and ECM raises. No pair/lag search or trading rule is invented. |
| CRP-06 | `fit_pca` and `pca_residual`; query amplitude1, bounded0.5–3 | Known rank-one factor input matrix. Orthogonal query gives nonzero residual; in-span null gives zero. No OU model, threshold trades or complete statistical-arbitrage strategy. |
| CRP-07 | `fit_garch`, `garch_forecast`, `variance_scores`; innovation scale1, bounded0.5–3 | Fixed seed809 and150 observations in predeclared volatility blocks0.01,0.03,0.01. One actual SLSQP fit. Zero-innovation null raises. One later synthetic variance proxy gives MSE/QLIKE; it cannot establish forecast quality. |
| CRP-08 | `volatility_managed_exposure`; variance scale0.0002, bounded0.00005–0.001 | Completed returns−0.01,+0.01, sum of demeaned squares, cap2; later return0.01. Ex-ante scale is not the paper's full-sample normalization. Zero variance raises. |
| CRP-09 | `fit_surprise_scale` and `macro_surprise`; query announcement error2, bounded−10–10 | Training errors−1,0,1; first-release timing and synthetic survey MEDIAN identity retained. Query consensus is known before publication. No-surprise null yields zero. No position is inferred from the surprise sign. |
| CRP-10 | `order_flow_imbalance`; queue-size multiplier1, bounded0.5–3 | Four complete sequenced synthetic top-of-book events. Contributions+7,+7,−12. Unchanged-book null yields zero. No FI2010 execution substitution or fitted price-impact model. |
| ENS-COV | `fit_covariance_ensemble`; weight cap1, bounded0.5–1 | Fixed training component returns, ridge1e−6. Reports actual later ensemble and each component's costs/return. Equal correlated components remain invested; zero later-return null reveals cost drag. |
| META-OOF | `fit_temporal_meta` and `meta_prediction`; ridge1, bounded0.1–10 | Four synthetic OOF input rows with base-training cutoff, prediction time, label horizon and later label availability. Zero-target null produces zero. These are declared fixture predictions, not proof of governed upstream fold training. |

CRP-03/09/10 and META-OOF retain explicitly marked unused timeline anchors in the
generic observation array; their real mathematical inputs are their structured
domain records. CRP-06/09/10 retain a target marked UNUSED_DIAGNOSTIC_TARGET;
it is never scored or presented as a forecast result. These generic metadata
slots do not constitute additional evaluated observations or research evidence.

## Causal portfolio and cost demonstration

CRP-01/02/03/04/08 and ENS-COV call the actual `portfolio_net_return` core for one
holding period strictly after the decision. The prior portfolio is cash. Gross
return is the weight/return dot product; turnover is L1 traded notional; net
return subtracts the explicit one-way cost rate times turnover. The returned
wealth index starts at1 and ends at1+net return. Outputs identify FLOAT64
arithmetic; this is not a Decimal settlement ledger or a multi-period backtest.

Default cost is0.001, with a bounded explicit override0–0.1. It is a simplified
synthetic entry-cost assumption, not a complete commissions/spread/slippage/
borrow/financing/liquidity model. Positions are not automatically closed and a
closing trade is not silently charged or assumed. Signed/levered exposure here
is mathematical portfolio arithmetic, not permission or support for executing
those holdings through the cash-funded spot accounting core. Unknown/missing
realistic treatments still block a research execution-realism claim.

CRP-03 separately reports unchanged-spot carry and actual synthetic terminal
forward payoff. Its settlement return uses the retained terminal spot, not the
carry formula as an invented realized outcome. Costs are still the disclosed
single entry assumption, with no claim of real forward settlement completeness.

Other CRPs are diagnostics or forecasts and report no trading P&L. Creating a
strategy from their residual, surprise, variance or flow would require a separately
registered trading rule, cost/execution model, validation and trial accounting.
No Sharpe, confidence percentage, win rate or annualized performance is created
from these tiny examples.

## Independent numerical checks

- CRP-01: sample SD of0.1,−0.1,0.1 times√12 is0.4; exposure0.1/0.4=0.25.
  Later return0.01 gives gross0.0025, cost0.00025 and net0.00225.
- CRP-02/04: weights0.5,0,−0.5 and later returns0.02,0,−0.01 give gross0.015;
  turnover1 and cost0.001 give net0.014.
- CRP-03: carry(1.25−1.20)/1.25=0.04, while terminal return
  (1.27−1.20)/1.25=0.056; disclosed cost gives net0.055.
- CRP-05: the returned ECM coefficients are checked against a separate scalar
  feature dot product. The underlying fit's independent regression oracle is
  retained in the reviewed core suite.
- CRP-06: rank-one span removes the factor; the orthogonal query1,−2 retains
  squared residual norm5, while the collinear null has zero residual.
- CRP-07: a separate scalar variance recursion, using the actual fitted
  coefficients and exact retained innovations, reproduces the next variance.
  MSE and log(h)+RV/h are independently recomputed.
- CRP-08: realized variance0.01²+0.01²=0.0002; exposure1 and later return0.01
  give net0.009 after entry cost.
- CRP-09: training errors−1,0,1 have sample SD1; query error2 gives surprise2.
- CRP-10: independent book-event contributions7+7−12 give total2.
- ENS-COV: independent diagonal covariance quantities
  a=0.0004/3+1e−6 and b=0.0016/3+1e−6 imply weights b/(a+b),a/(a+b).
- META-OOF: centered x sum of squares5 and sample variance5/3 imply ridge1
  slope shrinkage2→1.5; intercept at mean3 gives prediction6.75 at x=4.
  Against later target8, squared error is1.5625; raw base prediction4 has error16.
  One synthetic comparison is not evidence that a meta model improves prediction.

All six portfolio profiles test that doubling cost leaves weights/gross return
unchanged and lowers net return by precisely the additional turnover cost. Every
domain's sensitivity scenario changes its relevant computed output. Future
feature/event mutations, delayed OOF labels, late announcement receipt, altered
future targets, wrong units and malformed chronology have explicit regressions.

## Local validation and integration status

Independent review found that fixed daily ECM/GARCH forecast horizons also need
fixed training cadence. Their frozen `observation_interval_seconds=86400` now
binds successive usable observations and the retained endpoint at `train_end`.
ECM additionally binds the query one day after that endpoint. Delayed final rows
cannot silently move a fitted forecast origin. Unavailable future rows remain
excluded. The actual fixture generator is bound as `random_seed`: CRP-05 uses
801 for NULL and412 otherwise, CRP-07 uses809, and other variants use0 to denote
deterministic construction without random draws. These values are validated at
execution and are suitable for projection into the governing Item8 record.

118 focused tests passed on Python3.14.7 with warnings treated as errors.
The new studies module has95.15% combined statement/branch coverage. Ruff
check/format and strict mypy passed. One initial oversized-fixture test generated
an excessively long pytest case ID; explicit short IDs corrected that test
infrastructure failure. Dotted-module coverage discovery also triggered a NumPy
repeated-import collection failure; filesystem source-directory instrumentation
passed with the same warnings policy. Neither was hidden as a successful run.

Only `studies.py`, `test_v0_studies.py` and this document are new deliverables.
The reviewed root pure-math files were copied into the isolated checkout solely
to resolve imports and were not modified. Accounting/source files remain frozen.
No dependency, account, network, Git or root-workspace change occurred. Root
LabService/runtime/API/UI integration, full regression/CI, frozen temporal-graph
verification and independent cross-review remain separate required gates.
