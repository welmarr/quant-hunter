"""CRP07--08: explicit causal recursions, constrained QMLE, capped allocation."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

import numpy as np
from scipy.optimize import minimize  # type: ignore[import-untyped]

from .common import (
    Array,
    MethodError,
    TimedRow,
    after,
    as_tuple,
    history,
    integer,
    number,
    vector,
)


def ewma_variances(
    returns: Sequence[float],
    *,
    initial_variance: float,
    decay: float = 0.94,
) -> tuple[float, ...]:
    """h[t] precedes r[t]; final element forecasts the next observation."""
    data = vector(returns)
    initial = number(initial_variance, positive=True)
    if not 0 < number(decay) < 1:
        raise MethodError("EWMA decay must lie strictly between zero and one")
    result = [initial]
    for value in data:
        result.append(decay * result[-1] + (1 - decay) * float(value) ** 2)
    return tuple(result)


def garch_variances(
    returns: Sequence[float],
    *,
    omega: float,
    alpha: float,
    beta: float,
    initial_variance: float,
) -> tuple[float, ...]:
    data = vector(returns)
    omega = number(omega, positive=True)
    alpha, beta = number(alpha), number(beta)
    if min(alpha, beta) < 0 or alpha + beta >= 1:
        raise MethodError("stationary nonnegative GARCH coefficients required")
    result = [number(initial_variance, positive=True)]
    for value in data:
        result.append(omega + alpha * float(value) ** 2 + beta * result[-1])
    if not all(isfinite(x) and x > 0 for x in result):
        raise MethodError("invalid GARCH recursion")
    return tuple(result)


@dataclass(frozen=True)
class GARCHFit:
    train_end: datetime
    omega: float
    alpha: float
    beta: float
    next_variance: float
    negative_log_likelihood: float
    iterations: int
    converged: bool


def fit_garch(
    returns: Sequence[TimedRow],
    *,
    train_end: datetime,
    max_iterations: int = 300,
) -> GARCHFit:
    """Zero-mean Gaussian GARCH(1,1) QMLE; fixed initialization, SLSQP."""
    integer(max_iterations, 1, 1000)
    data = history(returns, train_end, minimum=40)
    if data.shape[1] != 1:
        raise MethodError("one zero-mean innovation series required")
    raw = data[:, 0]
    variance = float(np.mean(raw**2))
    if variance <= 1e-16 or float(np.std(raw)) <= 1e-12:
        raise MethodError("insufficient innovation variation")
    scaled = raw / np.sqrt(variance)

    def objective(parameters: Array) -> float:
        omega, alpha, beta = (float(x) for x in parameters)
        h = np.empty(len(scaled), dtype=np.float64)
        h[0] = 1.0
        for t in range(1, len(scaled)):
            h[t] = omega + alpha * scaled[t - 1] ** 2 + beta * h[t - 1]
        return float(0.5 * np.mean(np.log(h) + scaled**2 / h))

    fit = minimize(
        objective,
        np.array([0.05, 0.05, 0.9]),
        method="SLSQP",
        bounds=((1e-8, 10.0), (0.0, 0.999), (0.0, 0.999)),
        constraints={"type": "ineq", "fun": lambda p: 0.999 - p[1] - p[2]},
        options={"maxiter": max_iterations, "ftol": 1e-10},
    )
    if not fit.success or not bool(np.isfinite(fit.x).all()) or not isfinite(fit.fun):
        raise MethodError("GARCH_DID_NOT_CONVERGE")
    omega, alpha, beta = (float(x) for x in fit.x)
    path = garch_variances(
        as_tuple(raw),
        omega=omega * variance,
        alpha=alpha,
        beta=beta,
        initial_variance=variance,
    )
    nll = 0.5 * float(
        np.sum(np.log(2 * np.pi * np.array(path[:-1])) + raw**2 / np.array(path[:-1]))
    )
    return GARCHFit(
        train_end, omega * variance, alpha, beta, path[-1], nll, int(fit.nit), True
    )


def garch_forecast(model: GARCHFit, *, at: datetime, horizon: int = 1) -> float:
    after(model.train_end, at)
    integer(horizon, 1, 4096)
    if not model.converged:
        raise MethodError("unconverged model cannot forecast")
    persistence = model.alpha + model.beta
    long_run = model.omega / (1 - persistence)
    return long_run + persistence ** (horizon - 1) * (model.next_variance - long_run)


def variance_scores(
    forecasts: Sequence[float],
    realized_variances: Sequence[float],
) -> tuple[float, float]:
    """MSE and Gaussian QLIKE log(h)+realized/h; lower is better."""
    forecast, realized = vector(forecasts), vector(realized_variances)
    if (
        len(forecast) != len(realized)
        or bool((forecast <= 0).any())
        or bool((realized < 0).any())
    ):
        raise MethodError(
            "aligned positive forecasts and nonnegative realizations required"
        )
    return (
        float(np.mean((forecast - realized) ** 2)),
        float(np.mean(np.log(forecast) + realized / forecast)),
    )


def inverse_volatility_weights(
    volatilities: Sequence[float], *, cap: float = 1.0
) -> tuple[float, ...]:
    vol = vector(volatilities)
    if len(vol) > 64 or bool((vol <= 1e-12).any()):
        raise MethodError("positive nonzero asset volatilities required")
    cap = number(cap, positive=True)
    if cap > 1 or cap * len(vol) < 1 - 1e-12:
        raise MethodError("infeasible concentration cap")
    weights = np.zeros(len(vol))
    active = np.ones(len(vol), dtype=bool)
    for _ in range(len(vol)):
        remaining = 1.0 - float(weights.sum())
        inverse = 1 / vol[active]
        candidate = remaining * inverse / inverse.sum()
        indices = np.flatnonzero(active)
        capped = candidate > cap
        if not bool(capped.any()):
            weights[indices] = candidate
            break
        weights[indices[capped]] = cap
        active[indices[capped]] = False
    return as_tuple(weights)


def rolling_inverse_volatility(
    returns: Sequence[TimedRow],
    *,
    as_of: datetime,
    window: int,
    cap: float = 1.0,
) -> tuple[float, ...]:
    """Allocation at as_of using only the last available sample standard deviations."""
    integer(window, 2, 4096)
    data = history(returns, as_of, minimum=window)[-window:]
    return inverse_volatility_weights(as_tuple(data.std(axis=0, ddof=1)), cap=cap)


def volatility_managed_exposure(
    returns: Sequence[TimedRow],
    *,
    as_of: datetime,
    window: int,
    variance_scale: float,
    exposure_cap: float,
) -> float:
    """CRP08 Moreira--Muir inverse-variance core, fixed ex-ante scale and cap.

    Input observations form the completed lagged variance-estimation period.
    Realized variance is the SUM of within-period demeaned squared returns.
    Scale is preregistered or calibrated on a separate training sample.
    """
    integer(window, 2, 4096)
    scale = number(variance_scale, positive=True)
    cap = number(exposure_cap, positive=True)
    data = history(returns, as_of, minimum=window)[-window:]
    if data.shape[1] != 1:
        raise MethodError("one lagged factor-return series required")
    variance = float(np.sum((data[:, 0] - data[:, 0].mean()) ** 2))
    if variance <= 1e-16:
        raise MethodError("lagged realized variance is unidentifiable")
    return min(cap, scale / variance)


def portfolio_net_return(
    weights: Sequence[float],
    prior_drifted_weights: Sequence[float],
    asset_returns: Sequence[float],
    *,
    cost_per_unit_turnover: float,
) -> tuple[float, float]:
    """Gross return minus one-way cost times L1 traded notional; no hidden /2."""
    w, previous, returns = (
        vector(weights),
        vector(prior_drifted_weights),
        vector(asset_returns),
    )
    cost = number(cost_per_unit_turnover)
    if len(w) != len(previous) or len(w) != len(returns) or not 0 <= cost <= 1:
        raise MethodError("portfolio dimension or cost invalid")
    if bool((returns < -1).any()):
        raise MethodError("simple asset return below -100%")
    turnover = float(np.abs(w - previous).sum())
    return float(w @ returns) - cost * turnover, turnover
