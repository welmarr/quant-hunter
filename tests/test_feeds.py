from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from quant_hunter.feeds import (
    FeedError,
    FeedStore,
    load_config,
    refresh_all,
)
from quant_hunter.feeds.config import SeriesSpec, parse_config, series_id
from quant_hunter.feeds.http import HttpTransport, Response, check_url
from quant_hunter.feeds.providers import (
    assumed_lag,
    fetch,
    parse_alfred,
    parse_coinbase,
    parse_fred_csv,
    parse_kraken_funding,
    parse_yahoo,
)
from quant_hunter.feeds.quality import assess, xnys_sessions
from quant_hunter.feeds.refresh import main, summary

NOW = datetime(2026, 11, 6, 23, 0, tzinfo=UTC)  # Friday after the NY close


def spec(
    provider: str = "yahoo",
    symbol: str = "SPY",
    kind: str = "etf",
    calendar: str | None = "XNYS",
    max_jump: float = 0.25,
) -> SeriesSpec:
    return SeriesSpec(
        series_id(provider, symbol), provider, symbol, kind, calendar, max_jump
    )


def yahoo_body(
    days: list[date], closes: list[float | None], tz: str = "America/New_York"
) -> bytes:
    stamps = [
        int(datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC).timestamp())
        for d in days
    ]
    quote = {
        "open": [c for c in closes],
        "high": [None if c is None else c * 1.01 for c in closes],
        "low": [None if c is None else c * 0.99 for c in closes],
        "close": closes,
        "volume": [1000.0 for _ in closes],
    }
    doc = {
        "chart": {
            "result": [
                {
                    "meta": {"exchangeTimezoneName": tz},
                    "timestamp": stamps,
                    "indicators": {
                        "quote": [quote],
                        "adjclose": [{"adjclose": closes}],
                    },
                }
            ]
        }
    }
    return json.dumps(doc).encode()


class FakeTransport:
    def __init__(self, routes: dict[str, bytes]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str) -> Response:
        self.calls.append(url)
        for prefix, body in self.routes.items():
            if prefix in url:
                return Response(url, 200, body)
        raise FeedError(f"no route for {url}")


# config -------------------------------------------------------------------
def test_config_parses_groups(tmp_path: Path) -> None:
    path = tmp_path / "configs" / "feeds.toml"
    path.parent.mkdir()
    path.write_text(
        '[settings]\ndata_root = "data"\nhistory_start = "2010-01-01"\n'
        '[groups.a]\nprovider = "yahoo"\nkind = "fx"\nsymbols = ["EURUSD=X"]\n'
        '[groups.b]\nprovider = "fred"\nkind = "macro"\nmax_jump = 2\nsymbols = ["DGS10"]\n'
    )
    config = load_config(path)
    assert config.data_root == tmp_path / "data"
    assert config.history_start == date(2010, 1, 1)
    assert [s.id for s in config.series] == ["yahoo.EURUSD_X", "fred.DGS10"]
    assert config.by_id("fred.DGS10").max_jump == 2.0
    with pytest.raises(KeyError):
        config.by_id("nope")


@pytest.mark.parametrize(
    "groups",
    [
        {},
        {"a": "x"},
        {"a": {"provider": "nope", "kind": "etf", "symbols": ["A"]}},
        {"a": {"provider": "yahoo", "kind": "nope", "symbols": ["A"]}},
        {"a": {"provider": "yahoo", "kind": "etf", "symbols": []}},
        {"a": {"provider": "yahoo", "kind": "etf", "max_jump": -1, "symbols": ["A"]}},
        {"a": {"provider": "yahoo", "kind": "etf", "symbols": ["A", "A"]}},
        {"a": {"provider": "yahoo", "kind": "etf", "calendar": "", "symbols": ["A"]}},
    ],
)
def test_config_rejects_bad_groups(groups: dict[str, object], tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        parse_config({"groups": groups}, base=tmp_path)


def test_config_rejects_bad_settings(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        parse_config({"settings": "x", "groups": {}}, base=tmp_path)


def test_repository_feed_config_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "configs" / "feeds.toml")
    assert len(config.series) > 50
    assert {s.provider for s in config.series} >= {
        "yahoo",
        "fred",
        "coinbase",
        "kraken_funding",
    }


# http ---------------------------------------------------------------------
def test_check_url_allows_only_known_https_hosts() -> None:
    check_url("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10")
    with pytest.raises(FeedError):
        check_url("http://fred.stlouisfed.org/x")
    with pytest.raises(FeedError):
        check_url("https://example.com/x")
    with pytest.raises(FeedError):
        HttpTransport().get("https://example.com/x")


# providers ----------------------------------------------------------------
def test_yahoo_rows_close_at_ny_close_and_drop_open_bar() -> None:
    days = [date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9)]
    rows = parse_yahoo(yahoo_body(days, [100.0, None, 101.0, 102.0]), spec(), NOW)
    assert [r["date"] for r in rows] == [date(2026, 11, 4), date(2026, 11, 6)]
    assert rows[0]["available_at"] == datetime(2026, 11, 4, 21, 0, tzinfo=UTC)
    assert rows[1]["adj_close"] == 101.0


def test_yahoo_fx_available_next_midnight() -> None:
    fx = spec(symbol="EURUSD=X", kind="fx", calendar=None)
    rows = parse_yahoo(
        yahoo_body([date(2026, 11, 5)], [1.1], tz="Europe/London"), fx, NOW
    )
    assert rows[0]["available_at"] == datetime(2026, 11, 6, tzinfo=UTC)


def test_yahoo_rejects_garbage() -> None:
    with pytest.raises(FeedError):
        parse_yahoo(b'{"chart": {"result": []}}', spec(), NOW)


def test_fred_csv_and_lag() -> None:
    body = b"observation_date,CPIAUCSL\n2026-07-01,320.1\n2026-08-01,.\n2026-09-01,321.0\n2026-10-01,321.5\n"
    rows = parse_fred_csv(body, spec("fred", "CPIAUCSL", "macro", None, 10))
    assert [r["value"] for r in rows] == [320.1, 321.0, 321.5]
    assert rows[0]["available_at"] == datetime(2026, 8, 15, tzinfo=UTC)
    with pytest.raises(FeedError):
        parse_fred_csv(b"x\n", spec("fred", "X", "macro", None, 10))
    with pytest.raises(FeedError):
        parse_fred_csv(b"DATE,X\nbad,1\n", spec("fred", "X", "macro", None, 10))


def test_assumed_lag_by_spacing() -> None:
    d = date(2020, 1, 1)
    assert assumed_lag([d]) == timedelta(days=45)
    assert assumed_lag([d + timedelta(days=i) for i in range(5)]) == timedelta(days=1)
    assert assumed_lag([d + timedelta(days=7 * i) for i in range(5)]) == timedelta(
        days=7
    )
    assert assumed_lag([d + timedelta(days=91 * i) for i in range(5)]) == timedelta(
        days=120
    )


def test_alfred_vintages_keep_each_publication() -> None:
    body = json.dumps(
        {
            "observations": [
                {"realtime_start": "2026-02-11", "date": "2026-01-01", "value": "1.0"},
                {"realtime_start": "2026-03-12", "date": "2026-01-01", "value": "1.1"},
                {"realtime_start": "2026-03-12", "date": "2026-02-01", "value": "."},
            ]
        }
    ).encode()
    rows = parse_alfred(body, spec("alfred", "PAYEMS", "macro", None, 10))
    assert [(r["value"], r["available_at"]) for r in rows] == [
        (1.0, datetime(2026, 2, 12, tzinfo=UTC)),
        (1.1, datetime(2026, 3, 13, tzinfo=UTC)),
    ]
    with pytest.raises(FeedError):
        parse_alfred(b"{}", spec("alfred", "X", "macro", None, 10))


def test_alfred_needs_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(FeedError, match="FRED_API_KEY"):
        fetch(
            spec("alfred", "PAYEMS", "macro", None, 10),
            FakeTransport({}),
            NOW,
            date(2000, 1, 1),
        )
    monkeypatch.setenv("FRED_API_KEY", "secret123")
    body = json.dumps(
        {
            "observations": [
                {"realtime_start": "2026-02-11", "date": "2026-01-01", "value": "2"}
            ]
        }
    ).encode()
    fetched = fetch(
        spec("alfred", "PAYEMS", "macro", None, 10),
        FakeTransport({"stlouisfed": body}),
        NOW,
        date(2000, 1, 1),
    )
    assert "secret123" not in fetched.raw[0][0]


def test_coinbase_pages_and_drops_today() -> None:
    def candle(d: date, c: float) -> list[float]:
        return [
            datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp(),
            c * 0.9,
            c * 1.1,
            c,
            c,
            5.0,
        ]

    body = json.dumps(
        [candle(date(2026, 11, 6), 3.0), candle(date(2026, 11, 5), 2.0)]
    ).encode()
    transport = FakeTransport({"coinbase": body})
    fetched = fetch(
        spec("coinbase", "BTC-USD", "crypto", None, 0.5),
        transport,
        NOW,
        date(2026, 6, 1),
    )
    assert len(transport.calls) == 1
    assert [r["date"] for r in fetched.rows] == [date(2026, 11, 5)]
    many = FakeTransport({"coinbase": b"[]"})
    fetch(spec("coinbase", "BTC-USD", "crypto", None, 0.5), many, NOW, date(2000, 1, 1))
    assert len(many.calls) > 10
    with pytest.raises(FeedError):
        parse_coinbase(
            b'{"message": "NotFound"}', spec("coinbase", "X", "crypto", None, 0.5)
        )
    with pytest.raises(FeedError):
        parse_coinbase(b"nope", spec("coinbase", "X", "crypto", None, 0.5))


def test_kraken_funding() -> None:
    body = json.dumps(
        {
            "rates": [
                {
                    "timestamp": "2026-11-06T20:00:00.000Z",
                    "fundingRate": 0.1,
                    "relativeFundingRate": 0.00001,
                },
                {
                    "timestamp": "2026-11-06T21:00:00.000Z",
                    "fundingRate": 0.2,
                    "relativeFundingRate": 0.00002,
                },
            ]
        }
    ).encode()
    fund = spec("kraken_funding", "PF_XBTUSD", "funding", None, 10)
    fetched = fetch(fund, FakeTransport({"kraken": body}), NOW, date(2000, 1, 1))
    assert [r["funding_rate"] for r in fetched.rows] == [0.1, 0.2]
    with pytest.raises(FeedError):
        parse_kraken_funding(b"{}", fund)
    with pytest.raises(FeedError):
        fetch(
            spec("bogus", "X", "macro", None, 1),
            FakeTransport({}),
            NOW,
            date(2000, 1, 1),
        )


# store --------------------------------------------------------------------
def test_store_snapshots_are_immutable_and_as_of(tmp_path: Path) -> None:
    store = FeedStore(tmp_path)
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 2, 1, tzinfo=UTC)
    rows = [
        {
            "date": date(2025, 12, 1),
            "available_at": datetime(2025, 12, 2, tzinfo=UTC),
            "value": 1.0,
        }
    ]
    digest = store.capture(series_id="s", url="https://x", body=b"raw", retrieved_at=t1)
    assert store.raw(digest) == b"raw"
    first, written = store.write_snapshot(
        series_id="s",
        rows=rows,
        fields=["value"],
        retrieved_at=t1,
        raw_sha256=[digest],
        basis="B",
    )
    assert written
    same, written = store.write_snapshot(
        series_id="s",
        rows=rows,
        fields=["value"],
        retrieved_at=t2,
        raw_sha256=[digest],
        basis="B",
    )
    assert not written and same.path == first.path
    revised = [
        dict(rows[0], value=2.0),
        {
            "date": date(2026, 1, 1),
            "available_at": datetime(2026, 1, 20, tzinfo=UTC),
            "value": 3.0,
        },
    ]
    store.write_snapshot(
        series_id="s",
        rows=revised,
        fields=["value"],
        retrieved_at=t2,
        raw_sha256=[digest],
        basis="B",
    )
    assert len(store.snapshots("s")) == 2
    assert store.load("s", datetime(2026, 1, 15, tzinfo=UTC))["value"].to_pylist() == [
        1.0
    ]
    assert store.load("s")["value"].to_pylist() == [2.0, 3.0]
    assert store.load("s", datetime(2026, 2, 5, tzinfo=UTC)).num_rows == 2
    assert store.latest("s", datetime(2025, 1, 1, tzinfo=UTC)) is None
    with pytest.raises(FeedError):
        store.load("s", datetime(2025, 1, 1, tzinfo=UTC))
    with pytest.raises(FeedError):
        store.write_snapshot(
            series_id="s", rows=[], fields=[], retrieved_at=t2, raw_sha256=[], basis="B"
        )
    assert store.snapshots("missing") == []


# quality ------------------------------------------------------------------
def bars(days: list[date], closes: list[float]) -> list[dict[str, object]]:
    return [
        {
            "date": d,
            "available_at": datetime(d.year, d.month, d.day, 21, tzinfo=UTC),
            "open": c,
            "high": c * 1.01,
            "low": c * 0.99,
            "close": c,
        }
        for d, c in zip(days, closes, strict=True)
    ]


def test_quality_ok_for_complete_xnys_series() -> None:
    days = xnys_sessions(date(2026, 10, 1), date(2026, 11, 6))
    report = assess(spec(), bars(days, [100.0 + i for i in range(len(days))]), NOW)
    assert report.status == "OK", report.issues
    assert report.to_record()["rows"] == len(days)


def test_quality_flags_problems() -> None:
    days = xnys_sessions(date(2026, 9, 1), date(2026, 10, 20))
    closes = [100.0] * len(days)
    closes[5] = 200.0
    rows = bars(days, closes)
    rows[3]["low"] = 500.0
    del rows[10]
    rows.append(dict(rows[-1]))
    report = assess(spec(), rows, NOW)
    assert report.status == "FAIL"
    text = " ".join(report.issues)
    assert "duplicate" in text and "moves above" in text and "inconsistent" in text
    assert "stale" in text and "missing sessions" in text
    assert assess(spec(), [], NOW).status == "FAIL"
    bad = bars([date(2026, 11, 6)], [100.0])
    bad[0]["close"] = -1.0
    assert assess(spec(), bad, NOW).status == "FAIL"


def test_quality_recent_and_staleness_by_kind() -> None:
    days = xnys_sessions(date(2026, 10, 1), date(2026, 11, 5))
    report = assess(spec(), bars(days, [100.0] * len(days)), NOW)
    assert report.status == "WARN"
    fx = spec(symbol="EURUSD=X", kind="fx", calendar=None, max_jump=0.1)
    assert assess(fx, bars([date(2026, 11, 1)], [1.1]), NOW).status == "WARN"
    assert assess(fx, bars([date(2026, 10, 20)], [1.1]), NOW).status == "FAIL"
    fund = spec("kraken_funding", "PF_XBTUSD", "funding", None, 10)
    row = {"date": date(2026, 11, 6), "available_at": NOW, "funding_rate": 0.1}
    assert assess(fund, [row, dict(row)], NOW).status == "FAIL"
    alf = spec("alfred", "PAYEMS", "macro", None, 10)
    assert assess(alf, [row], NOW).status == "OK"


# refresh ------------------------------------------------------------------
def test_refresh_all_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = parse_config(
        {
            "settings": {"data_root": str(tmp_path / "data")},
            "groups": {
                "etf": {
                    "provider": "yahoo",
                    "kind": "etf",
                    "calendar": "XNYS",
                    "symbols": ["SPY"],
                },
                "macro": {"provider": "fred", "kind": "macro", "symbols": ["DGS10"]},
                "broken": {
                    "provider": "kraken_funding",
                    "kind": "funding",
                    "symbols": ["PF_X"],
                },
            },
        },
        base=tmp_path,
    )
    days = xnys_sessions(date(2026, 10, 1), date(2026, 11, 6))
    transport = FakeTransport(
        {
            "finance.yahoo": yahoo_body(days, [100.0 + i for i in range(len(days))]),
            "fredgraph": b"DATE,DGS10\n2026-11-02,4.1\n2026-11-03,4.2\n2026-11-04,4.0\n",
        }
    )
    result = refresh_all(config, transport, clock=lambda: NOW, pause=0)
    statuses = {s["series"]: s["status"] for s in result.series}
    assert statuses == {
        "yahoo.SPY": "OK",
        "fred.DGS10": "OK",
        "kraken_funding.PF_X": "ERROR",
    }
    assert (tmp_path / "data" / "reports" / "latest.json").exists()
    assert "ERROR" in summary(result)
    again = refresh_all(config, transport, only={"etf"}, clock=lambda: NOW, pause=0)
    assert [s["new_snapshot"] for s in again.series] == [False]

    cfg = tmp_path / "configs" / "feeds.toml"
    cfg.parent.mkdir()
    cfg.write_text(
        f'[settings]\ndata_root = "{(tmp_path / "data").as_posix()}"\n'
        '[groups.m]\nprovider = "fred"\nkind = "macro"\nsymbols = ["DGS10"]\n'
    )
    monkeypatch.setattr("quant_hunter.feeds.http.HttpTransport.get", transport.get)
    assert main(["--config", str(cfg)]) == 0


class _Handle:
    def __init__(self, body: bytes) -> None:
        self.body, self.status = body, 200

    def __enter__(self) -> _Handle:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return self.body[:size]


def test_http_transport_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    from quant_hunter.feeds import http

    urlopen = "urllib.request.urlopen"
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(urlopen, lambda req, timeout: _Handle(b"ok"))
    assert HttpTransport().get(url).body == b"ok"

    monkeypatch.setattr(http, "MAX_BYTES", 1)
    with pytest.raises(FeedError, match="too large"):
        HttpTransport().get(url)
    monkeypatch.setattr(http, "MAX_BYTES", 1024)

    def not_found(req: object, timeout: float) -> _Handle:
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urlopen, not_found)
    with pytest.raises(FeedError, match="HTTP 404"):
        HttpTransport().get(url)

    calls: list[int] = []

    def busy(req: object, timeout: float) -> _Handle:
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)  # type: ignore[arg-type]
        raise urllib.error.URLError("down")

    monkeypatch.setattr(urlopen, busy)
    with pytest.raises(FeedError, match="after retries"):
        HttpTransport(retries=1).get(url)
    assert len(calls) == 2
