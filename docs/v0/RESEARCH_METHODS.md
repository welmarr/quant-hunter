# V0 research mathematics: source map and limits

These are executable mathematical cores, not validated investment strategies.
All current test vectors are **SYNTHETIC**. No historical result, paper performance,
future profitability, operational readiness, or independent professional
certification follows from these tests. Each CRP label is a catalog domain ID;
it is not a permanent STRAT, FAM, MODEL, or EXP identifier. The application must
allocate those IDs, register every variant, freeze the definition, and begin
the actual Item 8 lifecycle before any research evaluation. These functions have
no registry, file, network, sealed-data, release, promotion, or order authority.

## Timing and numerical contract

`TimedRow(at, available_at, values)` is a synchronized vector. Dates must be UTC,
unique and increasing; availability cannot precede the observation or move
backward. `history` selects **only `available_at <= cutoff`** before any numeric
fit. Future numeric values are neither normalized nor inspected. An invalid
future value cannot affect a past calculation; it fails once it becomes visible.
Delaying availability can remove a row or make a sample insufficient. Structural
timestamp/dimension contradictions fail immediately. Missing interior periods
must be identified by the caller's calendar/data-quality contract; the math
does not invent a market calendar or silently impute observations.

Rows are bounded at 4,096, synchronized columns at 64. Numeric inputs are finite,
absolute magnitude at most 1e12, with nonzero magnitude at least 1e-100.
Array outputs are checked for finiteness. Degenerate variance, invalid dimensions,
insufficient samples, unavailable releases and failed optimizers raise
`MethodError`, except flat TSMOM explicitly returns `ZERO_VOLATILITY`, exposure
zero. Training minima are software safeguards, not statistical adequacy claims.

PCA truncation at tied singular values is rejected as an unidentifiable component
boundary; an arbitrary numerical eigenvector is not presented as a signal.
Fitted objects are frozen dataclasses containing their training cutoff. Forecasts
must occur strictly later. Observation vectors passed to a fitted-model prediction
are explicitly caller-supplied information known at its `at`; caller provenance
must bind those values and timestamps to governed immutable datasets. The module
cannot attest the truth of supplied metadata. Prices must already have correctly
dated corporate actions, total-return/FX conventions, synchronized universes and
properly recorded vintages. Parameters, universe, lookback, lag, cost, cadence,
training cutoff and every attempted choice belong in the preregistration.

## Original-source access record

Access date: **2026-10-05**. Every source below was available as original paper
text, and the identified methodological sections were inspected. This is not a
claim to have read every page or to have reproduced its empirical analysis.
No listed method rests only on an abstract. The scanned Engle–Granger estimation
pages and the Moreira–Muir realized-variance equation were rendered and inspected
visually. Raw PDFs/renders are ignored local reading material, not redistributed
in Git. Where a browser fetch failed, the public NBER PDF was readable through a
normal unauthenticated download; no paywall or access control was bypassed.

| Domain | Original source and version | Inspected method location |
|---|---|---|
| CRP01 | Moskowitz, Ooi, Pedersen, **Time Series Momentum**, JFE 2012, author-hosted published PDF via Yale [original](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2019/09/TimeSeriesMomentum.pdf) | Sections 2–3, sign/volatility scaling and portfolio formation; Eq. (3) |
| CRP02 | Menkhoff, Sarno, Schmeling, Schrimpf, **Currency Momentum Strategies**, BIS WP366, December 2011 [original](https://www.bis.org/publications/working-paper-366-currency-momentum-strategies.pdf) | Section 3, currency excess returns and formation/holding portfolios |
| CRP03 | Koijen, Moskowitz, Pedersen, Vrugt, **Carry**, JFE 2018, Yale author-hosted published PDF [original](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2019/04/Carry.pdf) | Section 2, Eqs. (3)–(5), unchanged-spot carry |
| CRP04 | Asness, Moskowitz, Pedersen, **Value and Momentum Everywhere**, Journal of Finance 2013, Yale author-hosted published PDF [original](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2019/09/ValueandMomentumEverywhere.pdf) | Portfolio construction, Eq. (1), centered signal ranks and 50/50 combination |
| CRP05 | Engle, Granger, **Co-Integration and Error Correction: Representation, Estimation, and Testing**, Econometrica 1987, institutional scanned original [original](https://users.ssc.wisc.edu/~bhansen/718/EngleGranger1987.pdf) | Section 4, pp. 260–261, two-step estimation and Eq. (4.5); original access, selected pages read |
| CRP06 | Avellaneda, Lee, **Statistical Arbitrage in the U.S. Equities Market**, author manuscript June 15, 2009, published 2010 [original](https://math.nyu.edu/faculty/avellane/AvellanedaLeeStatArb20090616.pdf) | Section 2.1 standardized returns/correlation Eq. (8), factor/residual decomposition Eq. (5) |
| CRP07 | Bollerslev, **Generalized Autoregressive Conditional Heteroskedasticity**, Journal of Econometrics 1986, Duke author copy [original](https://public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf) | Section 3 Eq. (8), Theorem 1 stationarity; likelihood estimation discussion |
| CRP08 | Moreira, Muir, **Volatility Managed Portfolios**, NBER WP22208, April 2016 revised June 2016 [original](https://www.nber.org/system/files/working_papers/w22208/w22208.pdf) | Section 2.2 Eqs. (1)–(2), lagged inverse realized variance; Section 2.3 evaluation |
| CRP09 | Andersen, Bollerslev, Diebold, Vega, **Micro Effects of Macro Announcements: Real-Time Price Discovery in Foreign Exchange**, AER 2003, Duke author copy [original](https://econ.duke.edu/~boller/Published_Papers/aer_03.pdf) | News-data discussion, printed p. 42: unnumbered standardized-surprise formula |
| CRP10 | Cont, Kukanov, Stoikov, **The Price Impact of Order Book Events**, arXiv 1011.6402v3, April 13, 2011, published 2014 [original](https://arxiv.org/pdf/1011.6402) | Section 2, event contribution and interval OFI summation, PDF p. 4 |

The inverse-volatility **comparison**, not the primary CRP08 implementation, uses
Maillard, Roncalli, Teïletche, *On the Properties of Equally-Weighted Risk
Contributions Portfolios*, May 2009 author manuscript, Section 3.2 Eq. (3).
The author-hosted URL returned 502; the [author-uploaded original full text](https://www.researchgate.net/publication/45397778_On_the_Properties_of_Equally-Weighted_Risk_Contributions_Portfolios)
was inspected. Its inverse-volatility solution assumes equal correlations; the
capped comparison here does not claim equal risk contributions under arbitrary
correlations.

## Equation → function → variant → oracle

The oracle names below refer to `tests/test_v0_research_methods.py`. Named variants
make deviations visible; an actual change of variant/parameters still counts as
a new trial under the governed search family.

| Domain and implemented variant | Executable mapping and assumptions | Independent small oracle |
|---|---|---|
| CRP01 `price-sign-rolling-sample-vol-v1` | `time_series_momentum`: sign(P[t]/P[t-L]−1) × min(cap,target/annualized sample SD). Decision follows final available close. Rolling simple-return SD replaces the paper's volatility estimator; price momentum is not automatically futures excess-return momentum. | Prices 100,110,99,108.9 imply returns .1,−.1,.1; standard-library sample SD × sqrt(12); exposure .1/SD. Flat prices produce explicit zero exposure; future mutation leaves prior output unchanged. |
| CRP02 `dated-fx-excess-return-rank-v1` | `fx_cross_section_momentum`: centered average-tie ranks of sum log(1+r) over synchronized dated FX excess returns, gross one. This simple-return rank weighting differs from the paper's six sorted portfolios/log-return convention. Caller must construct correctly oriented excess returns including financing. | Two periods [.1,0,−.1] give weights [.5,0,−.5]; ties [0,0,1] give [−.25,−.25,.5]. Long negative-return panels retain ranking without floating-point underflow ties. |
| CRP03 `spot-normalized-forward-carry-v1` | `forward_carry`: Eq. (4) with capital X=S, C=(S−F)/S. Quote is domestic currency per unit foreign; long foreign forward benefits from F<S under unchanged spot. Actual forward maturity and causal quote availability required. Annualization is simple ACT/365.25, not an expected-return estimate. | S=1.25,F=1.20 implies .04 horizon carry; F=1.30 reverses sign; S=F gives zero. Inverted convention, future quote and expired contract fail. |
| CRP04 `pit-book-price-skip-momentum-rank-v1` | `value_momentum`: average of separately gross-one centered book/price and skip-period momentum ranks, adapting Eq. (1). The paper uses one dollar long and one dollar short (gross two); this core halves that leverage to gross one. Book/share releases require period≤publication≤availability; latest known period/revision selected per asset. Fixed aligned universe; positive book/share only. | Three assets with value/momentum ranks aligned produce [.5,0,−.5]. Equal signals produce zero. A later high book value changes ranks only after availability; missing fundamentals fail. |
| CRP05 `eg-intercept-fixed-adf-lag-ecm-v1` | `fit_cointegration`, `ecm_forecast`: y=a+bx+e, augmented EG test; fixed-lag ADF diagnostics on levels/differences; Δy[t]=c+αe[t−1]+γΔy[t−1]+δΔx[t−1]. Fixed normalization, no future contemporaneous x. Near collinearity/deterministic first differences fail. Eligibility requires EG rejection, level nonrejection and difference rejection; it is a diagnostic, not proof of I(1). | Independent scalar covariance/variance OLS; explicit residual DF normal equations and t statistic; synthetic common random walk positive, stationary-series null rejected for I(1) eligibility. Future data does not change fit. |
| CRP06 `train-correlation-pca-residual-v1` | `fit_pca`, `pca_residual`: training z=(r−mean)/SD, SVD correlation factors, residual (z−zVᵀV)×SD. Fixed component count; sign convention only stabilizes representation. Includes factor residual extraction, not the paper's OU fitting, threshold trades or complete strategy. | Training rows [−2,−4],[−1,−2],[1,2],[2,4] span one factor. [3,6] residual is zero; [1,−2] is unchanged. Append a future outlier: fitted center/scale/loadings unchanged. |
| CRP07 `zero-mean-garch11-qmle-v1` | `garch_variances`, `fit_garch`, `garch_forecast`: h[t+1]=ω+αr[t]²+βh[t]; ω>0, α,β≥0, α+β≤.999. Zero-mean innovations; train mean-square initializes likelihood; SLSQP on variance-scaled data. Failed convergence raises. `ewma_variances` is explicit fixed-decay comparison h[t+1]=λh[t]+(1−λ)r[t]² with supplied prior initial variance. | ω=.1,α=.2,β=.5,h0=2 and r=[1,2,0] give h=[2,1.3,1.55,.875]. Independent likelihood loop; return scale×3 implies variance×9. EWMA λ=.5 gives [2,1.5,2.75,1.375]. |
| CRP08 `lagged-realized-inverse-variance-capped-v1` | `volatility_managed_exposure`: Eq. (2) RV²=SUM(r−within-window mean)²; Eq. (1) exposure=min(cap,c/RV²). Completed lagged window only. Fixed preregistered/train-calibrated c replaces paper full-sample normalization. `portfolio_net_return` charges one-way rate×L1 traded notional. | r=[−.01,.01], c=.0002 gives exposure1; r=[−.02,.02] gives .25. Cap .6 binds. Moving from cash to exposure1, next return .01 and cost .001 gives .009. Zero realized variance fails. |
| CRP09 `train-first-release-surprise-v1` | `fit_surprise_scale`, `macro_surprise`: S=(actual−known consensus)/training sample SD of surprises. One indicator/unit/consensus source/statistic, unique periods, first release only, consensus timestamp strictly before publication. The paper uses the MMS survey median; a different source or explicit MEAN is a generic adaptation, not exact-paper replication. Train-only scale is a deliberate prospective adaptation. No consensus proxy is manufactured. | Training errors [−1,0,1] have SD1; next error2 gives S=2. Error0 gives0. Delayed release cannot be used early; revisions, missing consensus and changed units/source/statistic fail. |
| CRP10 `sequenced-l1-ofi-v1` | `order_flow_imbalance`: e=I(b≥bprev)qb−I(b≤bprev)qbprev−I(a≤aprev)qa+I(a≥aprev)qaprev; sum transitions after initialization. Contiguous per-stream sequence, nondecreasing event/availability times, positive queues and uncrossed book. Final imbalance=(qb−qa)/(qb+qa). | Bid/ask quantity change (10,20)→(15,18) gives+7; bid improvement with size7 gives+7; ask improvement with size12 gives−12, total2. Future queue changes leave earlier OFI unchanged. |

## Dossier boundaries and empirical work still required

All ten questions concern whether the source's mechanism survives on the selected
market with causal information and realistic costs. Paper-reported conclusions
remain **reported, not reproduced**. No numeric paper metric is claimed here.
The source samples, protocols and portfolios do not become project evidence by
citation. This delivery supplies mathematical tests, not historical replication.

| Domain | Required governed data / horizon | Required evaluation and material limitations |
|---|---|---|
| 01 | Dated adjusted levels or correctly constructed excess-return index, fixed cadence and lookbacks | Chronological forecast/holding periods; costs, financing and volatility-target sensitivity; this rolling estimator is a disclosed deviation. |
| 02 | Common numeraire, dated synchronized spot/forward excess returns and financing; fixed formation/holding periods | Cross-sectional selection accounting, bid/ask, carry attribution and universe history; no spot-only substitute labeled excess return. |
| 03 | Same convention, timestamp and tenor for executable spot/forward quotes | Forward settlement and funding/cross-currency basis, spread and rollover; carry alone is neither realized nor expected total return. |
| 04 | Historically available book/share, adjusted price and membership/corporate-action history | Delisting/survivorship, accounting release lag, borrow/costs and skip sensitivity; cannot use today's revised fundamentals retroactively. |
| 05 | Fixed synchronized level series, cadence and preregistered pair/search family | Walk-forward stability, structural breaks, appropriate I(1) evidence, multiple pairs/lag exposure and costs; p-values are asymptotic and low-power diagnostics. |
| 06 | Synchronized adjusted total returns and historical universe | Train-only PCA in each fold, dimensional sensitivity and residual stability; OU/entry rules and complete paper replication are additional registered work. |
| 07 | Dated zero-mean innovations and independent later realized variance proxy | Compare EWMA/GARCH via MSE and `log(h)+RV/h` QLIKE on later data; validate distribution/tails and failure frequency, no optimizer success treated as empirical validity. |
| 08 | Completed prior variance period and following factor excess-return period | Compare unscaled, inverse-variance, inverse-volatility allocation, turnover/cost/cap sensitivity; fixed c must never be calibrated using validation/holdout. |
| 09 | First-release actual, contemporaneous consensus with known source, MEDIAN/MEAN statistic and timestamp, publication and receipt times | Predefined post-publication windows, surprise/return response and costs; missing licensed consensus may block historical research. |
| 10 | True sequenced quote updates, exchange and receipt times, complete queues | Event-window relation, spread/latency/queue/cost sensitivity and out-of-period evidence. FI-2010 transformed features are rejected as book/execution input. |

For every empirical run: use registered train/validation intervals, purging and
embargo where labels overlap, untouched sealed final holdout, all-trial accounting,
failed/inconclusive retention, null/permutation controls, prospective publication
perturbations and doubled-cost sensitivity. No global normalization or threshold
selection after viewing holdout results is permitted.

## Ensemble and temporal meta baseline

`fit_covariance_ensemble` minimizes wᵀ(Σ_train+ridge I)w, subject to sum(w)=1,
0≤w≤cap. It estimates correlation/exposure from training only, returns covariance
and weights, and refuses failed optimization. Two uncorrelated variances 4/3 and
16/3 have approximately [.8,.2] minimum-variance weights; the test computes the
closed form independently. This is a simple mathematical comparison, not a new
claim about a paper or an extra CRP count.

`OOFPrediction(at,label_end,label_available_at,base_training_end,predictions,target)`
requires each base training cutoff strictly before its prediction and explicit
label availability at or after its economic horizon end. Meta training reads
only predictions/targets whose `label_available_at <= train_end`; horizon end
alone never implies a label was available. `fit_temporal_meta` learns train mean/scale and ridge
coefficients with an unpenalized intercept; constant columns use scale1. Systems
with condition number above 1e12 or failed linear solve are refused, including
ridge penalties that disappear at the Gram matrix's numerical precision.
Prediction occurs later. A one-feature four-row independent ridge oracle returns6.75 at x=4;
zero-target controls return0. The wrapper must supply real retained out-of-fold
predictions and prove purge/embargo provenance. Merely supplying these datetimes
does not prove the upstream model was fitted causally. In-period base predictions
cannot be substituted. Later-data comparison to each component is still required.

## Dependency and test evidence

NumPy2.5.3 and SciPy1.18.1 provide bounded linear algebra/optimization;
statsmodels0.15.0 supplies augmented Engle–Granger and ADF tests with published
MacKinnon distributions, not invented critical values. Consult the
[official coint API](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.coint.html)
for the I(1) assumption and near-collinear numerical warning, and
[official SLSQP API](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html)
for convergence fields. Versions are exact proposals to the root lock authority;
this isolated task never edits dependency files.

Official PyPI hashes checked before isolated installation:

| Package | CPython3.14 Windows AMD64 wheel SHA-256 | Metadata |
|---|---|---|
| scipy1.18.1 | `78a0d7c918e74a232394117160e7e3db503377572a45bcef8826e4ab8a35feba` | [PyPI](https://pypi.org/pypi/scipy/1.18.1/json) |
| statsmodels0.15.0 | `c3c1138b4d0e5b0c2387b17dafd2a0fd137c67bd869f70d4ee56feecc918cb0d` | [PyPI](https://pypi.org/pypi/statsmodels/0.15.0/json) |

Focused post-correction local evidence on 2026-10-05: **97 tests passed with
98.64% branch-inclusive package coverage**, `--cov-fail-under=90` and `-W error`.
Ruff checks/format and strict mypy passed. Independent review identified label
availability being conflated with economic horizon end and a numerically
ineffective ridge penalty; both fail-closed corrections and hostile regressions
passed. Consensus source/statistic binding and naive-availability rejection were
also verified. The suite covers
independent scalar/normal-equation/projection/recursion/accounting oracles, positive
and null vectors, changed relevant inputs, future and delayed availability,
nonfinite/oversized data, genuine optimizer iteration failure, chronology and
malformed book/release metadata. Root full regression and cross-agent review are
separate required integration gates. No Git command was run by this subagent.
