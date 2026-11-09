"""Data-quality checks run on every refreshed series."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Final

from quant_hunter.feeds.config import SeriesSpec
from quant_hunter.feeds.store import Row
from quant_hunter.markets.calendars import sessions as market_sessions

PRICE_KINDS: Final = frozenset({"etf", "equity", "fx", "crypto"})
STALE_DAYS: Final = {"fx": 4, "crypto": 2, "funding": 2}
MISSING_SHARE_WARN: Final = 0.005


@dataclass(slots=True)
class QualityReport:
    series_id: str
    status: str
    rows: int
    first_date: str | None
    last_date: str | None
    issues: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def to_record(self) -> dict[str, object]:
        return {
            "series": self.series_id,
            "status": self.status,
            "rows": self.rows,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "issues": list(self.issues),
            "metrics": dict(self.metrics),
        }


def xnys_sessions(start: date, end: date) -> list[date]:
    """XNYS session labels between two dates (2000-2035), using Codex's pinned
    calendar in 366-day chunks."""
    start = max(start, date(2000, 1, 1))
    labels: list[date] = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=365), end)
        labels.extend(s.label for s in market_sessions("XNYS", cursor, stop).sessions)
        cursor = stop + timedelta(days=1)
    return labels


def _num(row: Row, key: str) -> float | None:
    value = row.get(key)
    return float(value) if isinstance(value, int | float) else None


def assess(spec: SeriesSpec, rows: list[Row], now: datetime) -> QualityReport:
    if not rows:
        return QualityReport(spec.id, "FAIL", 0, None, None, ["no rows"])
    days = [r["date"] for r in rows if isinstance(r["date"], date)]
    report = QualityReport(
        spec.id, "OK", len(rows), days[0].isoformat(), days[-1].isoformat()
    )
    fail = False
    # duplicates ---------------------------------------------------------
    if spec.provider == "alfred":
        keys: list[object] = [(r["date"], r["available_at"]) for r in rows]
    elif spec.kind == "funding":
        keys = [r["available_at"] for r in rows]
    else:
        keys = list(days)
    duplicates = len(keys) - len(set(keys))
    if duplicates:
        report.issues.append(f"{duplicates} duplicate observations")
        fail = True
    # prices --------------------------------------------------------------
    if spec.kind in PRICE_KINDS:
        closes = [_num(r, "close") for r in rows]
        bad = sum(1 for c in closes if c is None or c <= 0)
        if bad:
            report.issues.append(f"{bad} missing or non-positive closes")
            fail = True
        series = [c for c in closes if c is not None and c > 0]
        moves = [abs(b / a - 1) for a, b in pairwise(series)]
        if moves:
            report.metrics["max_abs_move"] = max(moves)
            jumps = sum(1 for m in moves if m > spec.max_jump)
            if jumps:
                report.issues.append(
                    f"{jumps} moves above {spec.max_jump:.0%} (largest {max(moves):.1%})"
                )
        broken = 0
        for r in rows:
            o, h, lo, c = (_num(r, k) for k in ("open", "high", "low", "close"))
            if o is None or h is None or lo is None or c is None:
                continue
            if lo > min(o, c) * 1.0001 or h < max(o, c) * 0.9999:
                broken += 1
        if broken:
            report.issues.append(f"{broken} bars with inconsistent high/low")
    # calendar coverage and freshness -------------------------------------
    today = now.date()
    if spec.calendar == "XNYS":
        expected = xnys_sessions(days[0], today)
        closed = [d for d in expected if d < today or now.hour >= 22]
        have = set(days)
        missing = [d for d in closed if d not in have]
        share = len(missing) / max(len(closed), 1)
        report.metrics["missing_sessions"] = float(len(missing))
        if share > MISSING_SHARE_WARN:
            report.issues.append(f"{len(missing)} missing sessions ({share:.2%})")
        recent = [d for d in closed if d > days[-1]]
        report.metrics["sessions_behind"] = float(len(recent))
        if len(recent) > 3:
            report.issues.append(f"stale: {len(recent)} sessions behind")
            fail = True
        elif recent:
            report.issues.append(f"{len(recent)} recent session(s) not yet in data")
    elif spec.kind in STALE_DAYS:
        lag = (today - days[-1]).days
        report.metrics["days_behind"] = float(lag)
        if lag > STALE_DAYS[spec.kind] + 3:
            report.issues.append(f"stale: last observation {lag} days ago")
            fail = True
        elif lag > STALE_DAYS[spec.kind]:
            report.issues.append(f"last observation {lag} days ago")
    if fail:
        report.status = "FAIL"
    elif report.issues:
        report.status = "WARN"
    return report
