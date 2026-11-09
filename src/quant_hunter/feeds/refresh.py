"""Refresh every configured series, store it, check it, write a report."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from quant_hunter.feeds.config import FeedConfig, SeriesSpec
from quant_hunter.feeds.http import FeedError, Transport
from quant_hunter.feeds.providers import fetch
from quant_hunter.feeds.quality import QualityReport, assess
from quant_hunter.feeds.store import FeedStore


@dataclass(slots=True)
class RefreshResult:
    started_at: datetime
    finished_at: datetime | None = None
    series: list[dict[str, object]] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.series:
            status = str(item["status"])
            out[status] = out.get(status, 0) + 1
        return out

    def to_record(self) -> dict[str, object]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "counts": self.counts,
            "series": self.series,
        }


def refresh_one(
    spec: SeriesSpec,
    config: FeedConfig,
    store: FeedStore,
    transport: Transport,
    now: datetime,
) -> dict[str, object]:
    try:
        fetched = fetch(spec, transport, now, config.history_start)
    except FeedError as error:
        return {"series": spec.id, "status": "ERROR", "error": str(error)}
    shas = [
        store.capture(series_id=spec.id, url=url, body=body, retrieved_at=now)
        for url, body in fetched.raw
    ]
    report: QualityReport = assess(spec, fetched.rows, now)
    record: dict[str, object] = report.to_record()
    if fetched.rows:
        snapshot, written = store.write_snapshot(
            series_id=spec.id,
            rows=fetched.rows,
            fields=fetched.fields,
            retrieved_at=now,
            raw_sha256=shas,
            basis=fetched.basis,
        )
        record["snapshot"] = snapshot.path.name
        record["new_snapshot"] = written
    record["basis"] = fetched.basis
    return record


def refresh_all(
    config: FeedConfig,
    transport: Transport,
    *,
    only: set[str] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    pause: float = 0.3,
) -> RefreshResult:
    store = FeedStore(config.data_root)
    result = RefreshResult(started_at=clock())
    for spec in config.series:
        if only and spec.id not in only and spec.kind not in only:
            continue
        result.series.append(refresh_one(spec, config, store, transport, clock()))
        if pause:
            time.sleep(pause)
    result.finished_at = clock()
    reports = config.data_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = result.started_at.strftime("%Y%m%dT%H%M%SZ")
    text = json.dumps(result.to_record(), indent=1, default=str)
    (reports / f"refresh-{stamp}.json").write_text(text, encoding="utf-8")
    (reports / "latest.json").write_text(text, encoding="utf-8")
    return result


def summary(result: RefreshResult) -> str:
    lines = [f"Refresh {result.started_at:%Y-%m-%d %H:%M} UTC: {result.counts}"]
    for item in result.series:
        if item["status"] != "OK":
            detail = item.get("error") or "; ".join(map(str, item.get("issues", [])))  # type: ignore[call-overload]
            lines.append(f"  {item['status']:<5} {item['series']}: {detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from quant_hunter.feeds.config import load_config
    from quant_hunter.feeds.http import HttpTransport

    parser = argparse.ArgumentParser(prog="python -m quant_hunter.feeds")
    parser.add_argument("--config", type=Path, default=Path("configs/feeds.toml"))
    parser.add_argument("--only", nargs="*", help="series ids or kinds to refresh")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    result = refresh_all(
        config, HttpTransport(), only=set(args.only) if args.only else None
    )
    print(summary(result))
    return 1 if result.counts.get("ERROR") or result.counts.get("FAIL") else 0
