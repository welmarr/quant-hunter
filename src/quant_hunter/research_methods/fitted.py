"""CRP05--06: train-only Engle--Granger/ECM and standardized PCA."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from statsmodels.tsa.stattools import adfuller, coint  # type: ignore[import-untyped]

from .common import MethodError, TimedRow, after, as_tuple, history, integer, vector


@dataclass(frozen=True)
class CointegrationFit:
    train_end: datetime
    intercept: float
    hedge_ratio: float
    residual_scale: float
    statistic: float
    pvalue: float
    critical_values: tuple[float, ...]
    level_adf_pvalues: tuple[float, ...]
    difference_adf_pvalues: tuple[float, ...]
    eligible: bool
    ecm_coefficients: tuple[float, ...]


def fit_cointegration(
    levels: Sequence[TimedRow],
    *,
    train_end: datetime,
    adf_lags: int = 1,
    significance: float = 0.05,
) -> CointegrationFit:
    """Two levels [y,x]; intercept EG test, fixed ADF lags, lagged-only ECM."""
    integer(adf_lags, 0, 12)
    if significance not in (0.01, 0.05, 0.1):
        raise MethodError("significance must be preregistered at 1%, 5% or 10%")
    data = history(levels, train_end, minimum=max(40, 4 * adf_lags + 10))
    if data.shape[1] != 2 or bool((np.std(data, axis=0) <= 1e-10).any()):
        raise MethodError("two nondegenerate level series required")
    y, x = data[:, 0], data[:, 1]
    design = np.column_stack((np.ones(len(x)), x))
    coef, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ coef
    scale = float(np.std(residual, ddof=2))
    if rank != 2 or scale < max(1e-10, float(np.std(y)) * 0.002):
        raise MethodError("degenerate or near-exact cointegration regression")
    if bool((np.std(np.diff(data, axis=0), axis=0) <= 1e-12).any()):
        raise MethodError("constant first differences cannot support I(1) diagnostics")
    stat, pvalue, critical = coint(
        y,
        x,
        trend="c",
        maxlag=adf_lags,
        autolag=None,
        return_results=False,
    )
    level_p = tuple(
        float(
            adfuller(
                data[:, i],
                maxlag=adf_lags,
                autolag=None,
                regression="c",
                result_object=False,
            )[1]
        )
        for i in (0, 1)
    )
    difference_p = tuple(
        float(
            adfuller(
                np.diff(data[:, i]),
                maxlag=adf_lags,
                autolag=None,
                regression="c",
                result_object=False,
            )[1]
        )
        for i in (0, 1)
    )
    # Forecast delta-y using information at t-1 only; no contemporaneous future x.
    dy, dx = np.diff(y), np.diff(x)
    ecm_design = np.column_stack(
        (np.ones(len(dy) - 1), residual[1:-1], dy[:-1], dx[:-1])
    )
    ecm, _, ecm_rank, _ = np.linalg.lstsq(ecm_design, dy[1:], rcond=None)
    if ecm_rank != 4 or not bool(
        np.isfinite([stat, pvalue, *level_p, *difference_p, *ecm]).all()
    ):
        raise MethodError("degenerate ECM or nonfinite test statistic")
    eligible = (
        pvalue < significance
        and all(p >= significance for p in level_p)
        and all(p < significance for p in difference_p)
    )
    return CointegrationFit(
        train_end,
        float(coef[0]),
        float(coef[1]),
        scale,
        float(stat),
        float(pvalue),
        as_tuple(critical),
        level_p,
        difference_p,
        bool(eligible),
        as_tuple(ecm),
    )


def ecm_forecast(
    model: CointegrationFit,
    levels: Sequence[float],
    previous_levels: Sequence[float],
    *,
    at: datetime,
) -> float:
    """Next-observation delta-y conditional on levels known at ``at``."""
    after(model.train_end, at)
    if not model.eligible:
        raise MethodError("I(1)/cointegration training diagnostics not satisfied")
    now, previous = vector(levels), vector(previous_levels)
    if len(now) != 2 or len(previous) != 2:
        raise MethodError("two synchronized levels required")
    residual = now[0] - model.intercept - model.hedge_ratio * now[1]
    features = np.array([1, residual, now[0] - previous[0], now[1] - previous[1]])
    return float(
        as_tuple(features @ np.array(model.ecm_coefficients).reshape(-1, 1))[0]
    )


@dataclass(frozen=True)
class PCAFit:
    train_end: datetime
    means: tuple[float, ...]
    scales: tuple[float, ...]
    loadings: tuple[tuple[float, ...], ...]
    explained_variance: tuple[float, ...]


def fit_pca(
    returns: Sequence[TimedRow],
    *,
    train_end: datetime,
    components: int = 1,
) -> PCAFit:
    data = history(returns, train_end, minimum=4)
    integer(components, 1, min(data.shape) - 1)
    means, scales = data.mean(axis=0), data.std(axis=0, ddof=1)
    if bool((scales <= 1e-12).any()):
        raise MethodError("constant feature cannot be standardized")
    _, singular, right = np.linalg.svd((data - means) / scales, full_matrices=False)
    if singular[components - 1] - singular[components] <= 1e-10 * singular[0]:
        raise MethodError("PCA component boundary is not identifiable")
    loadings = right[:components].copy()
    for row in loadings:
        if row[np.argmax(np.abs(row))] < 0:
            row *= -1
    return PCAFit(
        train_end,
        as_tuple(means),
        as_tuple(scales),
        tuple(as_tuple(row) for row in loadings),
        as_tuple(singular[:components] ** 2 / float((singular**2).sum())),
    )


def pca_residual(
    model: PCAFit, returns: Sequence[float], *, at: datetime
) -> tuple[float, ...]:
    """Out-of-training observation residuals in original return units."""
    after(model.train_end, at)
    values = vector(returns)
    if len(values) != len(model.means):
        raise MethodError("PCA observation dimension mismatch")
    scaled = (values - np.array(model.means)) / np.array(model.scales)
    loadings = np.array(model.loadings)
    return as_tuple((scaled - (scaled @ loadings.T) @ loadings) * model.scales)
