"""Ten sourced reference suggestions; no automatic fetch, allocation or reading claim."""

from typing import cast

from quant_hunter.config import JsonRecord, JsonValue

from .validation import empty_dossier

_YALE = "https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/"
_REFERENCES = (
    (
        "CRP-01",
        "Time Series Momentum",
        "Tobias J. Moskowitz;Yao Hua Ooi;Lasse Heje Pedersen",
        2012,
        _YALE + "2019/09/TimeSeriesMomentum.pdf",
        "JFE 2012 author-hosted published copy",
        "Sections 2-3, equation (3)",
        "time_series_momentum",
        "test_crp01_independent_return_and_sample_volatility_oracle",
        "Sign of trailing price return scaled by causal rolling sample volatility",
        "The rolling volatility estimator and price-return input differ from the paper's excess-return protocol.",
    ),
    (
        "CRP-02",
        "Currency Momentum Strategies",
        "Lukas Menkhoff;Lucio Sarno;Maik Schmeling;Andreas Schrimpf",
        2011,
        "https://www.bis.org/publications/working-paper-366-currency-momentum-strategies.pdf",
        "BIS Working Paper 366, December 2011",
        "Section 3 portfolio construction",
        "fx_cross_section_momentum",
        "test_crp02_dated_cross_section_ties_null_and_perturbation",
        "Centered ranks of lagged cumulative dated FX excess returns",
        "Gross-one rank weighting differs from six sorted portfolios; financing and universe history remain required.",
    ),
    (
        "CRP-03",
        "Carry",
        "Ralph S. J. Koijen;Tobias J. Moskowitz;Lasse Heje Pedersen;Evert B. Vrugt",
        2018,
        _YALE + "2019/04/Carry.pdf",
        "JFE 2018 author-hosted published copy",
        "Section 2, equation (4)",
        "forward_carry",
        "test_crp03_payoff_orientation_not_forward_premium",
        "Domestic-per-foreign quote: unchanged-spot carry (S-F)/S",
        "Capital X=S and simple ACT/365.25 annualization are explicit choices; carry is not expected total return.",
    ),
    (
        "CRP-04",
        "Value and Momentum Everywhere",
        "Clifford S. Asness;Tobias J. Moskowitz;Lasse Heje Pedersen",
        2013,
        _YALE + "2019/09/ValueandMomentumEverywhere.pdf",
        "Journal of Finance 2013 author-hosted copy",
        "Equation (1), portfolio construction",
        "value_momentum",
        "test_crp04_rank_oracle_and_publication_time",
        "Average gross-one centered book/price and skip-period momentum ranks",
        "Paper gross two is halved to gross one; positive book values, historical universe and PIT releases required.",
    ),
    (
        "CRP-05",
        "Co-Integration and Error Correction: Representation, Estimation, and Testing",
        "Robert F. Engle;Clive W. J. Granger",
        1987,
        "https://users.ssc.wisc.edu/~bhansen/718/EngleGranger1987.pdf",
        "Econometrica 1987 institutional scanned original",
        "Section 4, pages 260-261, equation (4.5)",
        "fit_cointegration;ecm_forecast",
        "test_crp05_manual_ols_and_residual_adf_t_oracle",
        "Train-only OLS cointegration and lagged-residual error correction",
        "Fixed lags and I(1) diagnostics are not proof of stationarity or prospective trading profitability.",
    ),
    (
        "CRP-06",
        "Statistical Arbitrage in the U.S. Equities Market",
        "Marco Avellaneda;Jeong-Hyun Lee",
        2009,
        "https://math.nyu.edu/faculty/avellane/AvellanedaLeeStatArb20090616.pdf",
        "Author manuscript June 15, 2009; later published 2010",
        "Section 2.1; equations (5) and (8)",
        "fit_pca;pca_residual",
        "test_crp06_known_rank_one_projection_and_no_future_fit",
        "Training-standardized correlation PCA and orthogonal residual projection",
        "Only factor residual extraction is implemented; OU fitting, entry rules and historical replication remain separate work.",
    ),
    (
        "CRP-07",
        "Generalized Autoregressive Conditional Heteroskedasticity",
        "Tim Bollerslev",
        1986,
        "https://public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf",
        "Journal of Econometrics 1986 author copy",
        "Section 3 equation (8), Theorem 1",
        "fit_garch;garch_variances;garch_forecast",
        "test_crp07_scalar_recursion_and_score_oracles",
        "h(t+1)=omega+alpha*r(t)^2+beta*h(t), constrained train-only Gaussian QMLE",
        "Zero-mean innovations and train mean-square initialization; unsuccessful convergence produces no forecast.",
    ),
    (
        "CRP-08",
        "Volatility Managed Portfolios",
        "Alan Moreira;Tyler Muir",
        2016,
        "https://www.nber.org/system/files/working_papers/w22208/w22208.pdf",
        "NBER Working Paper 22208, April 2016 revised June 2016",
        "Section 2.2 equations (1) and (2)",
        "volatility_managed_exposure",
        "test_crp08_moreira_muir_inverse_variance_not_inverse_volatility",
        "Capped c divided by sum of demeaned squared returns in the completed previous window",
        "Fixed or training-calibrated c replaces paper full-sample normalization. Inverse-volatility allocation is a separate comparison.",
    ),
    (
        "CRP-09",
        "Micro Effects of Macro Announcements: Real-Time Price Discovery in Foreign Exchange",
        "Torben G. Andersen;Tim Bollerslev;Francis X. Diebold;Clara Vega",
        2003,
        "https://econ.duke.edu/~boller/Published_Papers/aer_03.pdf",
        "AER 2003 author copy",
        "Printed page 42, unnumbered standardized-surprise formula",
        "fit_surprise_scale;macro_surprise",
        "test_crp09_independent_surprise_scale_and_delayed_publication",
        "First-release actual minus known prepublication consensus, divided by training surprise SD",
        "Original uses MMS survey median; bound source and MEDIAN/MEAN statistic are explicit. Missing historical consensus blocks empirical study.",
    ),
    (
        "CRP-10",
        "The Price Impact of Order Book Events",
        "Rama Cont;Arseniy Kukanov;Sasha Stoikov",
        2011,
        "https://arxiv.org/pdf/1011.6402",
        "arXiv 1011.6402v3, April 13, 2011; later published 2014",
        "Section 2, PDF page 4, event contribution and summation",
        "order_flow_imbalance",
        "test_crp10_event_oracle_and_causality",
        "Sum signed bid/ask price-and-size update contributions; final queue imbalance",
        "True sequenced book updates required; FI-2010 features cannot establish executable prices or fills.",
    ),
)


def canonical_references() -> list[JsonRecord]:
    """Copy bibliography/method notes only; create/attach/read are explicit operations.

    Selected original sections were inspected during the separate methodology
    task. Their local raw documents are not implicitly imported into this library;
    new PAPER records start UNREAD/UNAVAILABLE until their own evidence is added.
    """
    result: list[JsonRecord] = []
    for (
        domain,
        title,
        authors,
        year,
        url,
        version,
        section,
        function,
        oracle,
        formula,
        limits,
    ) in _REFERENCES:
        dossier = empty_dossier()
        dossier.update(
            question="Does the described mechanism survive causal validation and realistic costs?",
            signal_formula=formula,
            limitations=limits,
            deviations=limits,
            reported_results="Paper-reported empirical conclusions have not been reproduced by these software tests.",
            reproduced_results="SYNTHETIC mathematical oracles only; see docs/v0/RESEARCH_METHODS.md. No PAPER experiment is implied.",
            variant="Named implementation variant documented in docs/v0/RESEARCH_METHODS.md",
            protocol="Register every variant with Item 8 before evaluation; train-only fitting, preserved holdout and failed-trial accounting required.",
            disposition_reason="Primary original methodological sections inspected 2026-10-05; this library has not yet retained or read a document.",
            equation_links=[
                {
                    "section": section,
                    "function": "quant_hunter.research_methods:" + function,
                    "assumptions": limits,
                    "oracle": "tests/test_v0_research_methods.py:" + oracle,
                }
            ],
        )
        result.append(
            {
                "domain": domain,
                "metadata": {
                    "title": title,
                    "authors": cast(list[JsonValue], authors.split(";")),
                    "year": year,
                    "doi": None,
                    "url": url,
                    "version": version,
                },
                "dossier": dossier,
                "text_access": "UNAVAILABLE",
                "reading_status": "UNREAD",
            }
        )
    return result
