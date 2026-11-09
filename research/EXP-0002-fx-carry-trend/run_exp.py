"""EXP-0002 runner. Rules fixed by PREREGISTRATION.md; do not tune.

Usage (repo root, Hunter venv): python research/EXP-0002-fx-carry-trend/run_exp.py development|holdout
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from quant_hunter.feeds import FeedStore
from quant_hunter.research_validation.overfitting import deflated_sharpe_ratio

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STORE = FeedStore(ROOT / ".local" / "data" / "feeds")
# currency: (yahoo series, quoted as USD per unit?, FRED rate series)
UNIVERSE = {
    "EUR": ("yahoo.EURUSD_X", True, "fred.IR3TIB01DEM156N"),
    "GBP": ("yahoo.GBPUSD_X", True, "fred.IR3TIB01GBM156N"),
    "JPY": ("yahoo.USDJPY_X", False, "fred.IR3TIB01JPM156N"),
    "AUD": ("yahoo.AUDUSD_X", True, "fred.IR3TIB01AUM156N"),
    "CAD": ("yahoo.USDCAD_X", False, "fred.IR3TIB01CAM156N"),
    "CHF": ("yahoo.USDCHF_X", False, "fred.IR3TIB01CHM156N"),
    "NZD": ("yahoo.NZDUSD_X", True, "fred.IR3TIB01NZM156N"),
    "MXN": ("yahoo.USDMXN_X", False, "fred.IR3TIB01MXM156N"),
}
US_RATE = "fred.DTB3"
COST_BPS = (5, 15)
PERIODS = {"development": ("1900-01", "2016-12"), "holdout": ("2017-01", "2026-10")}
LAST_FULL = pd.Period("2026-10", "M")


def frame(series_id: str) -> pd.DataFrame:
    table = STORE.load(series_id)  # latest snapshot; rows filtered by available_at below
    df = table.to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    return df


def spot_month_end() -> pd.DataFrame:
    cols = {}
    for ccy, (sid, usd_per_unit, _) in UNIVERSE.items():
        df = frame(sid).set_index("date")["close"].astype(float)
        usd = df if usd_per_unit else 1.0 / df
        cols[ccy] = usd.groupby(usd.index.to_period("M")).last()
    out = pd.DataFrame(cols).sort_index()
    return out.loc[:LAST_FULL]


def rates_as_of(month_ends: pd.PeriodIndex) -> pd.DataFrame:
    """Annual % rates known at each decision time (start of next month, 00:00 UTC)."""
    series = {ccy: frame(rid) for ccy, (_, _, rid) in UNIVERSE.items()}
    series["USD"] = frame(US_RATE)
    out = {}
    for name, df in series.items():
        df = df.sort_values("available_at")
        vals = []
        for p in month_ends:
            cutoff = pd.Timestamp((p + 1).start_time, tz="UTC")
            known = df[df["available_at"] <= cutoff]
            vals.append(np.nan if known.empty else float(known.sort_values("date")["value"].iloc[-1]))
        out[name] = vals
    return pd.DataFrame(out, index=month_ends)


def weights(spot: pd.DataFrame, rates: pd.DataFrame, rule: str) -> pd.DataFrame:
    ccys = list(UNIVERSE)
    diff = rates[ccys].sub(rates["USD"], axis=0) / 100.0
    long_ret = spot.pct_change(fill_method=None) + (diff.shift(1) / 12.0)
    trend = (1 + long_ret).rolling(12).apply(np.prod, raw=True) - 1
    w = pd.DataFrame(np.nan, index=spot.index, columns=ccys)
    for t in spot.index:
        d = diff.loc[t]
        if d.isna().any() or spot.loc[t].isna().any():
            continue
        if rule == "B1":
            w.loc[t] = 1.0 / len(ccys)
            continue
        carry = pd.Series(0.0, index=ccys)
        order = d.sort_values()
        carry[order.index[-3:]] = 1.0 / 6
        carry[order.index[:3]] = -1.0 / 6
        tr = trend.loc[t]
        if tr.isna().any():
            continue
        trend_w = np.sign(tr) / len(ccys)
        w.loc[t] = {"P1": carry, "P2": trend_w, "P3": 0.5 * carry + 0.5 * trend_w}[rule]
    return w


def simulate(spot: pd.DataFrame, rates: pd.DataFrame, w: pd.DataFrame, cost_bps: float) -> pd.Series:
    ccys = list(UNIVERSE)
    diff = rates[ccys].sub(rates["USD"], axis=0) / 100.0
    spot_ret = spot.pct_change(fill_method=None)
    out, prev = {}, None
    months = list(spot.index)
    for i in range(len(months) - 1):
        t, t1 = months[i], months[i + 1]
        wt = w.loc[t]
        if wt.isna().any():
            prev = None
            continue
        r = spot_ret.loc[t1] + diff.loc[t] / 12.0
        if r.isna().any():
            continue
        base = prev if prev is not None else pd.Series(0.0, index=ccys)
        turnover = float((wt - base).abs().sum())
        out[t1] = float((wt * r).sum()) - turnover * cost_bps / 1e4
        grown = wt * (1 + r)
        prev = grown  # drifted exposures (dollar-neutral books need no renormalising)
    return pd.Series(out, dtype=float)


def stats(r: pd.Series) -> dict[str, float]:
    wealth = (1 + r).cumprod()
    dd = wealth / wealth.cummax() - 1
    sd = r.std()
    return {
        "months": float(len(r)),
        "ann_return": float(r.mean() * 12),
        "ann_vol": float(sd * np.sqrt(12)),
        "sharpe": float(r.mean() / sd * np.sqrt(12)) if sd > 0 else 0.0,
        "max_dd": float(dd.min()),
        "pct_pos": float((r > 0).mean()),
    }


def main(period: str) -> None:
    spot = spot_month_end()
    rates = rates_as_of(spot.index)
    ws = {k: weights(spot, rates, k) for k in ("P1", "P2", "P3", "B1")}
    lo, hi = (pd.Period(x, "M") for x in PERIODS[period])
    results, series = {}, {}
    for cost in COST_BPS:
        sims = {k: simulate(spot, rates, w, cost) for k, w in ws.items()}
        common = sorted(set.intersection(*(set(s.index) for s in sims.values())))
        common = [m for m in common if lo <= m <= hi]
        for k, s in sims.items():
            results[f"{k}@{cost}bps"] = stats(s.loc[common])
            if cost == COST_BPS[0]:
                series[k] = s.loc[common]
    monthly_sr = [float(series[k].mean() / series[k].std()) for k in ("P1", "P2", "P3")]
    dsr = deflated_sharpe_ratio(
        series["P3"].tolist(), n_trials=3, trial_sharpe_variance=float(np.var(monthly_sr, ddof=1))
    )
    p3, b1 = results["P3@5bps"], results["B1@5bps"]
    verdict = "FAIL"
    if p3["sharpe"] > 0 and p3["sharpe"] > b1["sharpe"] and abs(p3["max_dd"]) < abs(b1["max_dd"]):
        verdict = "STRONG PASS" if dsr.dsr >= 0.95 else "PASS"
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{period}.json"
    if period == "holdout" and out.exists():
        raise SystemExit("holdout already evaluated; refusing to overwrite")
    snaps = {sid: STORE.latest(sid).path.name for sid in [v[0] for v in UNIVERSE.values()] + [v[2] for v in UNIVERSE.values()] + [US_RATE]}  # type: ignore[union-attr]
    report = {
        "experiment": "EXP-0002",
        "period": period,
        "window": [str(series["P3"].index[0]), str(series["P3"].index[-1])],
        "prereg_sha256": hashlib.sha256((HERE / "PREREGISTRATION.md").read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "feed_snapshots": snaps,
        "stats": results,
        "p3_dsr": {"dsr": dsr.dsr, "psr_zero": dsr.psr_zero, "monthly_sharpe": dsr.sharpe, "benchmark": dsr.benchmark},
        "verdict_if_holdout": verdict,
    }
    out.write_text(json.dumps(report, indent=2))
    pd.DataFrame(series).to_csv(out_dir / f"{period}_monthly_returns.csv")
    print(period, report["window"])
    print(pd.DataFrame(results).T.round(3).to_string())
    print(json.dumps(report["p3_dsr"], indent=1), verdict)


if __name__ == "__main__":
    main(sys.argv[1])
