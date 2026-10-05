"""Train-only covariance baseline and time-qualified OOF ridge stacking."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from scipy.optimize import minimize  # type: ignore[import-untyped]

from .common import (
    MethodError,
    TimedRow,
    after,
    as_tuple,
    history,
    integer,
    number,
    utc,
    vector,
)


@dataclass(frozen=True)
class EnsembleFit:
    train_end: datetime
    weights: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]


def fit_covariance_ensemble(
    component_returns: Sequence[TimedRow],
    *,
    train_end: datetime,
    cap: float = 1.0,
    ridge: float = 1e-6,
) -> EnsembleFit:
    """Long-only minimum train variance, sum one, fixed ridge and weight cap."""
    data = history(component_returns, train_end, minimum=4)
    n = data.shape[1]
    cap, ridge = number(cap, positive=True), number(ridge, positive=True)
    if n < 2 or cap > 1 or cap * n < 1:
        raise MethodError("infeasible ensemble dimensions or cap")
    covariance = np.cov(data, rowvar=False, ddof=1) + ridge * np.eye(n)
    scale = float(np.trace(covariance))
    result = minimize(
        lambda w: float(w @ covariance @ w / scale),
        np.ones(n) / n,
        jac=lambda w: 2 * covariance @ w / scale,
        method="SLSQP",
        bounds=[(0, cap)] * n,
        constraints={"type": "eq", "fun": lambda w: float(w.sum() - 1)},
        options={"maxiter": 300, "ftol": 1e-12},
    )
    if (
        not result.success
        or abs(float(result.x.sum()) - 1) > 1e-8
        or bool((result.x < -1e-10).any())
        or bool((result.x > cap + 1e-10).any())
    ):
        raise MethodError("ensemble optimizer failed")
    return EnsembleFit(
        train_end, as_tuple(result.x), tuple(as_tuple(row) for row in covariance)
    )


def ensemble_prediction(
    model: EnsembleFit, predictions: Sequence[float], *, at: datetime
) -> float:
    after(model.train_end, at)
    values = vector(predictions)
    if len(values) != len(model.weights):
        raise MethodError("ensemble dimension mismatch")
    return float(values @ np.array(model.weights))


@dataclass(frozen=True)
class OOFPrediction:
    at: datetime
    label_end: datetime
    label_available_at: datetime
    base_training_end: datetime
    predictions: tuple[float, ...]
    target: float


@dataclass(frozen=True)
class MetaFit:
    train_end: datetime
    intercept: float
    coefficients: tuple[float, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]


def fit_temporal_meta(
    observations: Sequence[OOFPrediction],
    *,
    train_end: datetime,
    ridge: float = 1.0,
) -> MetaFit:
    """OOF provenance is supplied by governed fold records, never inferred from values."""
    utc(train_end)
    integer(len(observations), 4, 4096)
    penalty = number(ridge, positive=True)
    rows: list[TimedRow] = []
    targets: list[float] = []
    for row in observations:
        for date in (
            row.at,
            row.label_end,
            row.label_available_at,
            row.base_training_end,
        ):
            utc(date)
        if (
            not row.base_training_end
            < row.at
            <= row.label_end
            <= row.label_available_at
        ):
            raise MethodError("in-sample prediction or invalid target horizon")
        if row.label_available_at <= train_end:
            rows.append(TimedRow(row.at, row.label_available_at, row.predictions))
            targets.append(number(row.target))
    data = history(rows, train_end, minimum=4)
    means, scales = data.mean(axis=0), data.std(axis=0, ddof=1)
    scales[scales <= 1e-12] = 1.0
    scaled = (data - means) / scales
    y = np.array(targets)
    intercept = float(y.mean())
    system = scaled.T @ scaled + penalty * np.eye(data.shape[1])
    try:
        condition = float(np.linalg.cond(system))
        if not np.isfinite(condition) or condition > 1e12:
            raise MethodError("meta ridge system is numerically unidentifiable")
        coef = np.linalg.solve(system, scaled.T @ (y - intercept))
    except np.linalg.LinAlgError:
        raise MethodError("meta ridge solve failed") from None
    return MetaFit(
        train_end, intercept, as_tuple(coef), as_tuple(means), as_tuple(scales)
    )


def meta_prediction(
    model: MetaFit, predictions: Sequence[float], *, at: datetime
) -> float:
    after(model.train_end, at)
    values = vector(predictions)
    if len(values) != len(model.coefficients):
        raise MethodError("meta prediction dimension mismatch")
    return model.intercept + float(
        ((values - np.array(model.means)) / np.array(model.scales))
        @ np.array(model.coefficients)
    )
