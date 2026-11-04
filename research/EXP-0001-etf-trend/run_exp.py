"""EXP-0001 runner. Rules are fixed by PREREGISTRATION.md; do not tune.

Usage: python run_exp.py development|holdout
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw" / "yahoo_monthly_2026-11-04.json"
RISK = ["SPY", "EFA", "EEM", "IEF", "TLT", "LQD", "GLD", "DBC", "VNQ"]
CASH = "SHY"
LOOKBACK = 12
PERIODS = {
    "development": ("1900-01", "2016-12"),
    "holdout": ("2017-01", "2026-10"),
}
LAST_FULL_MONTH = "2026-10"
SEED = 20261104


def load_prices() -> pd.DataFrame:
    d = json.loads(RAW.read_text())
    cols = {}
    for t, s in d["series"].items():
        rows = [r for r in s["rows"] if r[0].endswith("-01") and r[2] is not None]
        idx = pd.PeriodIndex([r[0][:7] for r in rows], freq="M")
        cols[t] = pd.Series([r[2] for r in rows], index=idx, dtype=float)
    px = pd.DataFrame(cols).sort_index()
    return px.loc[: pd.Period(LAST_FULL_MONTH, "M")]


def weights(px: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Weights decided with information up to and including month-end t.
    Row t is applied to the return of month t+1 (shift done by caller)."""
    ret = px.pct_change(fill_method=None)
    mom = px / px.shift(LOOKBACK) - 1.0
    vol = ret.rolling(LOOKBACK).std()
    w = pd.DataFrame(0.0, index=px.index, columns=RISK + [CASH])
    for t in px.index:
        if pd.isna(mom.at[t, CASH]):
            w.loc[t] = np.nan
            continue
        avail = [a for a in RISK if not pd.isna(mom.at[t, a]) and not pd.isna(vol.at[t, a])]
        if not avail:
            w.loc[t] = np.nan
            continue
        if rule == "S1":
            iv = 1.0 / vol.loc[t, avail]
            base = iv / iv.sum()
        else:
            base = pd.Series(1.0 / len(avail), index=avail)
        for a in avail:
            if rule == "B1":
                w.at[t, a] = base[a]
            elif mom.at[t, a] - mom.at[t, CASH] > 0:
                w.at[t, a] = base[a]
            else:
                w.at[t, CASH] += base[a]
    return w


def fixed_weights(px: pd.DataFrame, mix: dict[str, float]) -> pd.DataFrame:
    w = pd.DataFrame(0.0, index=px.index, columns=RISK + [CASH])
    for a, v in mix.items():
        w[a] = v
    ok = px[list(mix)].notna().all(axis=1) & px[CASH].notna()
    w.loc[~ok] = np.nan
    return w


def simulate(px: pd.DataFrame, w_decided: pd.DataFrame, cost_bps: float) -> pd.DataFrame:
    ret = px.pct_change(fill_method=None)[w_decided.columns]
    out = []
    drift = None
    months = list(px.index)
    for i in range(len(months) - 1):
        t, t1 = months[i], months[i + 1]
        w = w_decided.loc[t]
        if w.isna().any():
            continue
        r_next = ret.loc[t1].fillna(0.0)
        if (w[r_next.index[ret.loc[t1].isna()]] > 0).any():
            raise RuntimeError(f"weight on asset without return at {t1}")
        prev = drift if drift is not None else pd.Series(0.0, index=w.index)
        turnover = float((w - prev).abs().sum())
        gross = float((w * r_next).sum())
        net = gross - turnover * cost_bps / 1e4
        grown = w * (1 + r_next)
        drift = grown / grown.sum()
        out.append({"month": t1, "ret": net, "gross": gross, "turnover": turnover})
    return pd.DataFrame(out).set_index("month")


def stats(r: pd.Series, cash: pd.Series, turnover: pd.Series | None = None) -> dict:
    ex = r - cash
    wealth = (1 + r).cumprod()
    dd = wealth / wealth.cummax() - 1
    yrs = len(r) / 12
    cagr = wealth.iloc[-1] ** (1 / yrs) - 1
    mdd = dd.min()
    s = {
        "months": len(r),
        "cagr": cagr,
        "vol": r.std() * np.sqrt(12),
        "sharpe": ex.mean() / ex.std() * np.sqrt(12),
        "max_dd": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "pct_pos": (r > 0).mean(),
    }
    if turnover is not None:
        s["turnover_yr"] = turnover.mean() * 12
    return s


def sharpe(x: np.ndarray) -> float:
    return x.mean() / x.std(ddof=1) * np.sqrt(12)


def stationary_bootstrap_ci(a: np.ndarray, b: np.ndarray, block: float = 6, n: int = 5000):
    rng = np.random.default_rng(SEED)
    T = len(a)
    p = 1 / block
    diffs = np.empty(n)
    for k in range(n):
        idx = np.empty(T, dtype=int)
        idx[0] = rng.integers(T)
        for i in range(1, T):
            idx[i] = rng.integers(T) if rng.random() < p else (idx[i - 1] + 1) % T
        diffs[k] = sharpe(a[idx]) - sharpe(b[idx])
    return float(np.quantile(diffs, 0.05)), float(np.quantile(diffs, 0.95)), float((diffs > 0).mean())


def main(period: str) -> None:
    px = load_prices()
    lo, hi = (pd.Period(x, "M") for x in PERIODS[period])
    ws = {
        "P1": weights(px, "P1"),
        "S1": weights(px, "S1"),
        "B1": weights(px, "B1"),
        "B2": fixed_weights(px, {"SPY": 0.6, "IEF": 0.4}),
        "B3": fixed_weights(px, {"SPY": 1.0}),
    }
    cash_ret = px[CASH].pct_change(fill_method=None)
    results = {}
    series = {}
    for cost in (10, 25):
        sims = {k: simulate(px, w, cost) for k, w in ws.items()}
        common = sorted(set.intersection(*(set(s.index) for s in sims.values())))
        common = [m for m in common if lo <= m <= hi]
        for k, s in sims.items():
            s = s.loc[common]
            results[f"{k}@{cost}bps"] = stats(s["ret"], cash_ret.loc[common], s["turnover"])
            if cost == 10:
                series[k] = s["ret"]
    c = series["P1"].index
    ex = {k: (v - cash_ret.loc[c]).to_numpy() for k, v in series.items()}
    lo_ci, hi_ci, p_pos = stationary_bootstrap_ci(ex["P1"], ex["B1"])
    p1, b1 = results["P1@10bps"], results["B1@10bps"]
    dd_reduction = 1 - abs(p1["max_dd"]) / abs(b1["max_dd"])
    sharpe_diff = p1["sharpe"] - b1["sharpe"]
    verdict = "FAIL"
    if dd_reduction >= 0.30 and sharpe_diff >= -0.10:
        verdict = "STRONG PASS" if lo_ci > 0 else "PASS"
    report = {
        "experiment": "EXP-0001",
        "period": period,
        "window": [str(c[0]), str(c[-1])],
        "prereg_sha256": hashlib.sha256((HERE / "PREREGISTRATION.md").read_bytes()).hexdigest(),
        "data_sha256": hashlib.sha256(RAW.read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "stats": results,
        "p1_vs_b1": {
            "dd_reduction": dd_reduction,
            "sharpe_diff": sharpe_diff,
            "sharpe_diff_ci90": [lo_ci, hi_ci],
            "bootstrap_share_positive": p_pos,
        },
        "verdict_if_holdout": verdict,
    }
    out = HERE / "results" / f"{period}.json"
    out.parent.mkdir(exist_ok=True)
    if period == "holdout" and out.exists():
        raise SystemExit("holdout already evaluated; refusing to overwrite")
    out.write_text(json.dumps(report, indent=2, default=float))
    pd.DataFrame(series).to_csv(HERE / "results" / f"{period}_monthly_returns.csv")
    tbl = pd.DataFrame(results).T
    print(f"{period} {c[0]}..{c[-1]}")
    print(tbl.to_string(float_format=lambda x: f"{x:8.3f}"))
    print(json.dumps(report["p1_vs_b1"], indent=1), verdict)


if __name__ == "__main__":
    main(sys.argv[1])
