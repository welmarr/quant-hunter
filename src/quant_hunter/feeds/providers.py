"""Provider clients: build requests, parse responses into dated rows.

Every row carries ``available_at``: the earliest time the value could have
been known. Where the provider does not say, a stated conservative rule is
used and the snapshot's ``basis`` names it.
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from statistics import median
from typing import Final
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from quant_hunter.feeds.config import SeriesSpec
from quant_hunter.feeds.http import FeedError, Transport
from quant_hunter.feeds.secrets import credentials
from quant_hunter.feeds.store import Row

NEW_YORK: Final = ZoneInfo("America/New_York")
COINBASE_PAGE_DAYS: Final = 300
COINBASE_EARLIEST: Final = date(2015, 1, 1)


@dataclass(slots=True)
class Fetched:
    rows: list[Row]
    fields: tuple[str, ...]
    basis: str
    raw: list[tuple[str, bytes]] = field(default_factory=list)


def _float(value: object) -> float | None:
    if value is None or value in ("", "."):
        return None
    try:
        number = float(str(value))
    except ValueError as error:
        raise FeedError(f"not a number: {value!r}") from error
    return number if number == number else None


def _midnight_after(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(0), tzinfo=UTC)


def _closed(rows: list[Row], now: datetime) -> list[Row]:
    """Drop bars that were not complete at retrieval time."""
    kept = [r for r in rows if isinstance(r["available_at"], datetime)]
    return [r for r in kept if r["available_at"] <= now]  # type: ignore[operator]


def _dedupe(rows: list[Row], key: Callable[[Row], object]) -> list[Row]:
    seen: dict[object, Row] = {}
    for row in rows:
        seen[key(row)] = row
    return sorted(seen.values(), key=lambda r: (r["date"], r["available_at"]))


# Yahoo Finance -------------------------------------------------------------
YAHOO_FIELDS: Final = ("open", "high", "low", "close", "adj_close", "volume")


def yahoo_url(symbol: str, now: datetime) -> str:
    query = urlencode(
        {
            "period1": 0,
            "period2": int(now.timestamp()),
            "interval": "1d",
            "events": "div,split",
            "includeAdjustedClose": "true",
        }
    )
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?{query}"


def parse_yahoo(body: bytes, spec: SeriesSpec, now: datetime) -> list[Row]:
    try:
        document = json.loads(body)
        result = document["chart"]["result"][0]
        stamps: list[int] = result.get("timestamp") or []
        quote_block = result["indicators"]["quote"][0]
        adj_block = result["indicators"].get("adjclose") or [{}]
        adj: list[object] = adj_block[0].get("adjclose") or [None] * len(stamps)
        zone = ZoneInfo(result["meta"].get("exchangeTimezoneName") or "UTC")
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise FeedError(f"unexpected Yahoo response for {spec.symbol}") from error
    rows: list[Row] = []
    for i, stamp in enumerate(stamps):
        close = _float(quote_block["close"][i])
        if close is None:
            continue
        day = datetime.fromtimestamp(stamp, zone).date()
        if spec.kind in ("etf", "equity"):
            available = datetime.combine(day, time(16), tzinfo=NEW_YORK).astimezone(UTC)
        else:
            available = _midnight_after(day)
        rows.append(
            {
                "date": day,
                "available_at": available,
                "open": _float(quote_block["open"][i]),
                "high": _float(quote_block["high"][i]),
                "low": _float(quote_block["low"][i]),
                "close": close,
                "adj_close": _float(adj[i]) if i < len(adj) else None,
                "volume": _float(quote_block["volume"][i]),
            }
        )
    return _dedupe(_closed(rows, now), lambda r: r["date"])


def fetch_yahoo(spec: SeriesSpec, transport: Transport, now: datetime) -> Fetched:
    url = yahoo_url(spec.symbol, now)
    response = transport.get(url)
    rows = parse_yahoo(response.body, spec, now)
    basis = (
        "BAR_CLOSE_NY_16H" if spec.kind in ("etf", "equity") else "NEXT_UTC_MIDNIGHT"
    )
    return Fetched(rows, YAHOO_FIELDS, f"YAHOO_DAILY/{basis}", [(url, response.body)])


# FRED (latest vintage, keyless) --------------------------------------------
def fred_url(symbol: str) -> str:
    return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={quote(symbol)}"


def assumed_lag(days: list[date]) -> timedelta:
    """Conservative publication lag from the series' observation spacing."""
    if len(days) < 3:
        return timedelta(days=45)
    gaps = [(b - a).days for a, b in pairwise(days)]
    step = median(gaps)
    if step <= 3:
        return timedelta(days=1)
    if step <= 8:
        return timedelta(days=7)
    if step <= 31:
        return timedelta(days=45)
    return timedelta(days=120)


def parse_fred_csv(body: bytes, spec: SeriesSpec) -> list[Row]:
    reader = csv.reader(io.StringIO(body.decode("utf-8-sig")))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise FeedError(f"unexpected FRED response for {spec.symbol}")
    pairs: list[tuple[date, float]] = []
    observed: list[date] = []
    for line in reader:
        if len(line) < 2:
            continue
        try:
            day = date.fromisoformat(line[0])
        except ValueError as error:
            raise FeedError(f"bad FRED date {line[0]!r}") from error
        observed.append(day)
        value = _float(line[1])
        if value is not None:
            pairs.append((day, value))
    # Spacing from every observation date, missing values included.
    lag = assumed_lag(observed)
    rows: list[Row] = [
        {
            "date": d,
            "available_at": _midnight_after(d + lag - timedelta(days=1)),
            "value": v,
        }
        for d, v in pairs
    ]
    return _dedupe(rows, lambda r: r["date"])


def fetch_fred(spec: SeriesSpec, transport: Transport, now: datetime) -> Fetched:
    url = fred_url(spec.symbol)
    response = transport.get(url)
    rows = _closed(parse_fred_csv(response.body, spec), now)
    return Fetched(
        rows, ("value",), "FRED_LATEST_VINTAGE/ASSUMED_LAG", [(url, response.body)]
    )


# ALFRED (true vintages, needs FRED_API_KEY) --------------------------------
def alfred_url(symbol: str, key: str) -> str:
    query = urlencode(
        {
            "series_id": symbol,
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
            "file_type": "json",
            "api_key": key,
        }
    )
    return f"https://api.stlouisfed.org/fred/series/observations?{query}"


def parse_alfred(body: bytes, spec: SeriesSpec) -> list[Row]:
    try:
        observations = json.loads(body)["observations"]
    except (KeyError, TypeError, ValueError) as error:
        raise FeedError(f"unexpected ALFRED response for {spec.symbol}") from error
    rows: list[Row] = []
    for item in observations:
        value = _float(item.get("value"))
        if value is None:
            continue
        published = date.fromisoformat(item["realtime_start"])
        rows.append(
            {
                "date": date.fromisoformat(item["date"]),
                "available_at": _midnight_after(published),
                "value": value,
            }
        )
    return _dedupe(rows, lambda r: (r["date"], r["available_at"]))


def fetch_alfred(spec: SeriesSpec, transport: Transport, now: datetime) -> Fetched:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        raise FeedError("FRED_API_KEY is not set; ALFRED vintages need a free FRED key")
    url = alfred_url(spec.symbol, key)
    response = transport.get(url)
    rows = _closed(parse_alfred(response.body, spec), now)
    public = url.replace(key, "REDACTED")
    return Fetched(
        rows,
        ("value",),
        "ALFRED_VINTAGES/PUBLISHED_NEXT_UTC_DAY",
        [(public, response.body)],
    )


# Coinbase Exchange (crypto spot, daily) ------------------------------------
COINBASE_FIELDS: Final = ("open", "high", "low", "close", "volume")


def coinbase_url(symbol: str, start: datetime, end: datetime) -> str:
    query = urlencode(
        {
            "granularity": 86400,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    return f"https://api.exchange.coinbase.com/products/{quote(symbol)}/candles?{query}"


def parse_coinbase(body: bytes, spec: SeriesSpec) -> list[Row]:
    try:
        candles = json.loads(body)
    except ValueError as error:
        raise FeedError(f"unexpected Coinbase response for {spec.symbol}") from error
    if not isinstance(candles, list):
        raise FeedError(
            f"unexpected Coinbase response for {spec.symbol}: {candles!r:.200}"
        )
    rows: list[Row] = []
    for candle in candles:
        stamp, low, high, open_, close, volume = candle
        day = datetime.fromtimestamp(int(stamp), UTC).date()
        rows.append(
            {
                "date": day,
                "available_at": _midnight_after(day),
                "open": _float(open_),
                "high": _float(high),
                "low": _float(low),
                "close": _float(close),
                "volume": _float(volume),
            }
        )
    return rows


def fetch_coinbase(
    spec: SeriesSpec, transport: Transport, now: datetime, start: date
) -> Fetched:
    rows: list[Row] = []
    raw: list[tuple[str, bytes]] = []
    cursor = datetime.combine(max(start, COINBASE_EARLIEST), time(0), tzinfo=UTC)
    while cursor < now:
        end = min(cursor + timedelta(days=COINBASE_PAGE_DAYS - 1), now)
        url = coinbase_url(spec.symbol, cursor, end)
        response = transport.get(url)
        raw.append((url, response.body))
        rows.extend(parse_coinbase(response.body, spec))
        cursor = end + timedelta(days=1)
    rows = _dedupe(_closed(rows, now), lambda r: r["date"])
    return Fetched(rows, COINBASE_FIELDS, "COINBASE_DAILY_UTC/NEXT_UTC_MIDNIGHT", raw)


# Kraken Futures funding rates (hourly) -------------------------------------
def kraken_funding_url(symbol: str) -> str:
    return (
        "https://futures.kraken.com/derivatives/api/v4/historicalfundingrates?"
        + urlencode({"symbol": symbol})
    )


def parse_kraken_funding(body: bytes, spec: SeriesSpec) -> list[Row]:
    try:
        rates = json.loads(body)["rates"]
    except (KeyError, TypeError, ValueError) as error:
        raise FeedError(f"unexpected Kraken response for {spec.symbol}") from error
    rows: list[Row] = []
    for item in rates:
        stamp = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00"))
        rows.append(
            {
                "date": stamp.astimezone(UTC).date(),
                "available_at": stamp.astimezone(UTC),
                "funding_rate": _float(item.get("fundingRate")),
                "relative_funding_rate": _float(item.get("relativeFundingRate")),
            }
        )
    return _dedupe(rows, lambda r: r["available_at"])


def fetch_kraken_funding(
    spec: SeriesSpec, transport: Transport, now: datetime
) -> Fetched:
    url = kraken_funding_url(spec.symbol)
    response = transport.get(url)
    rows = _closed(parse_kraken_funding(response.body, spec), now)
    return Fetched(
        rows,
        ("funding_rate", "relative_funding_rate"),
        "KRAKEN_FUNDING/RATE_TIMESTAMP",
        [(url, response.body)],
    )


# OANDA v20 (practice), daily mid/bid/ask candles closing 17:00 New York --------
OANDA_FIELDS: Final = (
    "open",
    "high",
    "low",
    "close",
    "bid_close",
    "ask_close",
    "volume",
)
OANDA_PAGE: Final = 5000
OANDA_EARLIEST: Final = date(2005, 1, 1)


def _rfc3339(value: str) -> datetime:
    return datetime.fromisoformat(value[:19] + "+00:00")


def oanda_url(instrument: str, start: datetime) -> str:
    query = urlencode(
        {
            "price": "MBA",
            "granularity": "D",
            "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": OANDA_PAGE,
            "dailyAlignment": 17,
            "alignmentTimezone": "America/New_York",
        }
    )
    return (
        "https://api-fxpractice.oanda.com/v3/instruments/"
        f"{quote(instrument)}/candles?{query}"
    )


def parse_oanda(body: bytes, spec: SeriesSpec) -> tuple[list[Row], datetime | None]:
    """Rows of complete candles, and the start time of the last candle seen."""
    try:
        candles = json.loads(body)["candles"]
    except (KeyError, TypeError, ValueError) as error:
        raise FeedError(f"unexpected OANDA response for {spec.symbol}") from error
    rows: list[Row] = []
    last: datetime | None = None
    for candle in candles:
        start = _rfc3339(str(candle["time"]))
        last = start
        if not candle.get("complete"):
            continue
        end = start + timedelta(days=1)
        mid, bid, ask = candle["mid"], candle["bid"], candle["ask"]
        rows.append(
            {
                "date": end.astimezone(NEW_YORK).date(),
                "available_at": end,
                "open": _float(mid["o"]),
                "high": _float(mid["h"]),
                "low": _float(mid["l"]),
                "close": _float(mid["c"]),
                "bid_close": _float(bid["c"]),
                "ask_close": _float(ask["c"]),
                "volume": _float(candle.get("volume")),
            }
        )
    return rows, last


def fetch_oanda(
    spec: SeriesSpec, transport: Transport, now: datetime, start: date
) -> Fetched:
    token = credentials("oanda")["token"]
    headers = {"Authorization": f"Bearer {token}"}
    cursor = datetime.combine(max(start, OANDA_EARLIEST), time(0), tzinfo=UTC)
    rows: list[Row] = []
    raw: list[tuple[str, bytes]] = []
    for _ in range(20):
        url = oanda_url(spec.symbol, cursor)
        response = transport.get(url, headers)
        raw.append((url, response.body))
        page, last = parse_oanda(response.body, spec)
        rows.extend(page)
        if last is None or last + timedelta(seconds=1) <= cursor:
            break
        cursor = last + timedelta(seconds=1)
        if len(json.loads(response.body)["candles"]) < OANDA_PAGE:
            break
    rows = _dedupe(_closed(rows, now), lambda r: r["date"])
    return Fetched(rows, OANDA_FIELDS, "OANDA_MBA_DAILY_NY17/CANDLE_END", raw)


# Alpaca market data (daily bars, split and dividend adjusted) --------------
ALPACA_FIELDS: Final = ("open", "high", "low", "close", "volume", "vwap")
ALPACA_EARLIEST: Final = date(2016, 1, 1)


def alpaca_url(symbol: str, start: date, feed: str, page_token: str | None) -> str:
    params: dict[str, str | int] = {
        "timeframe": "1Day",
        "start": f"{start.isoformat()}T00:00:00Z",
        "adjustment": "all",
        "feed": feed,
        "limit": 10000,
    }
    if page_token:
        params["page_token"] = page_token
    return f"https://data.alpaca.markets/v2/stocks/{quote(symbol)}/bars?" + urlencode(
        params
    )


def parse_alpaca(body: bytes, spec: SeriesSpec) -> tuple[list[Row], str | None]:
    try:
        document = json.loads(body)
        bars = document.get("bars") or []
        token = document.get("next_page_token")
    except (AttributeError, TypeError, ValueError) as error:
        raise FeedError(f"unexpected Alpaca response for {spec.symbol}") from error
    rows: list[Row] = []
    for bar in bars:
        day = _rfc3339(str(bar["t"])).astimezone(NEW_YORK).date()
        rows.append(
            {
                "date": day,
                "available_at": datetime.combine(
                    day, time(16), tzinfo=NEW_YORK
                ).astimezone(UTC),
                "open": _float(bar.get("o")),
                "high": _float(bar.get("h")),
                "low": _float(bar.get("l")),
                "close": _float(bar.get("c")),
                "volume": _float(bar.get("v")),
                "vwap": _float(bar.get("vw")),
            }
        )
    return rows, str(token) if token else None


def fetch_alpaca(
    spec: SeriesSpec, transport: Transport, now: datetime, start: date
) -> Fetched:
    creds = credentials("alpaca")
    headers = {"APCA-API-KEY-ID": creds["key"], "APCA-API-SECRET-KEY": creds["secret"]}
    first = max(start, ALPACA_EARLIEST)
    for feed in ("sip", "iex"):
        rows: list[Row] = []
        raw: list[tuple[str, bytes]] = []
        token: str | None = None
        try:
            for _ in range(20):
                url = alpaca_url(spec.symbol, first, feed, token)
                response = transport.get(url, headers)
                raw.append((url, response.body))
                page, token = parse_alpaca(response.body, spec)
                rows.extend(page)
                if not token:
                    break
        except FeedError as error:
            if feed == "sip" and "HTTP 403" in str(error):
                continue
            raise
        rows = _dedupe(_closed(rows, now), lambda r: r["date"])
        return Fetched(
            rows,
            ALPACA_FIELDS,
            f"ALPACA_{feed.upper()}_DAILY_ADJ/BAR_CLOSE_NY_16H",
            raw,
        )
    raise FeedError(f"Alpaca refused every data feed for {spec.symbol}")


def fetch(
    spec: SeriesSpec, transport: Transport, now: datetime, start: date
) -> Fetched:
    if spec.provider == "yahoo":
        return fetch_yahoo(spec, transport, now)
    if spec.provider == "fred":
        return fetch_fred(spec, transport, now)
    if spec.provider == "alfred":
        return fetch_alfred(spec, transport, now)
    if spec.provider == "coinbase":
        return fetch_coinbase(spec, transport, now, start)
    if spec.provider == "kraken_funding":
        return fetch_kraken_funding(spec, transport, now)
    if spec.provider == "oanda":
        return fetch_oanda(spec, transport, now, start)
    if spec.provider == "alpaca":
        return fetch_alpaca(spec, transport, now, start)
    raise FeedError(f"unknown provider {spec.provider}")
