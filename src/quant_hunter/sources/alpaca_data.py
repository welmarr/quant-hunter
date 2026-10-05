"""Read-only historical stock bars with declared feeds and unknown availability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from quant_hunter.sources._equity_transport import (
    EquityHTTPS,
    EquityRequest,
    EquityTransport,
    RawPage,
    json_object,
    mapping,
    number,
    page_token,
    receive,
    stamp,
    text,
    utc_timestamp,
)
from quant_hunter.sources.connectors import Health
from quant_hunter.sources.transport import SourceError

_BAR_FLAGS = (
    "HISTORICAL_AVAILABILITY_UNKNOWN",
    "LATEST_AT_RETRIEVAL_MAY_INCLUDE_CORRECTIONS",
    "NO_SESSION_COMPLETENESS_CLAIM",
)


@dataclass(frozen=True)
class AlpacaCredentials:
    key_id: str = field(repr=False)
    secret_key: str = field(repr=False)
    credential_source: str

    def __post_init__(self) -> None:
        if self.credential_source not in ("PAPER_ACCOUNT", "READ_ONLY_MARKET_DATA"):
            raise SourceError("PAPER_OR_READ_ONLY_CREDENTIAL_SOURCE_REQUIRED")
        for value in (self.key_id, self.secret_key):
            text(value, r"[A-Za-z0-9_+/-]{8,256}", "INVALID_CREDENTIAL_FORMAT")


@dataclass(frozen=True)
class AlpacaBarQuery:
    symbol: str
    start: datetime
    end: datetime
    feed: str
    timeframe: str = "1Day"
    page_size: int = 1000
    max_pages: int = 5


@dataclass(frozen=True)
class AlpacaBar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int
    vwap: Decimal | None
    feed: str
    timeframe: str
    ingestion_time: datetime
    currency: str = "USD"
    adjustment: str = "raw"
    symbol_mapping: str = "DISABLED_ASOF_MINUS"
    available_at: None = None
    publication_time: None = None
    revision_time: None = None
    point_in_time_eligible: bool = False
    price_nature: str = "TRADE_AGGREGATE_NOT_BID_ASK"
    quality_flags: tuple[str, ...] = _BAR_FLAGS


@dataclass(frozen=True)
class AlpacaPage:
    records: tuple[AlpacaBar, ...]
    next_page_token: str | None = field(repr=False)


@dataclass(frozen=True)
class AlpacaBatch:
    catalogue_id: str
    query: AlpacaBarQuery
    records: tuple[AlpacaBar, ...]
    raw_pages: tuple[RawPage, ...]
    evidence_mode: str
    pagination_exhausted: bool = True
    coverage_complete: bool = False
    normalization_version: str = "v0-alpaca-data-1"
    limitations: tuple[str, ...] = (
        "IEX is one venue; SIP access requires separate rights and entitlement verification",
        "Bars are trade aggregates, not executable bid/ask quotes",
        "No calendar, delisting, corporate-action or historical availability certification",
        "Source registration, rights review and immutable storage are caller responsibilities",
    )


class AlpacaDataConnector:
    catalogue_id = "SRC-02"
    version = "v0-alpaca-data-1"
    documentation_url = "https://docs.alpaca.markets/us/reference/stockbars"

    def __init__(
        self,
        credentials: AlpacaCredentials | None = None,
        transport: EquityTransport | None = None,
        *,
        allowed_feeds: tuple[str, ...] = ("iex",),
    ) -> None:
        if (
            not allowed_feeds
            or len(set(allowed_feeds)) != len(allowed_feeds)
            or any(feed not in ("iex", "sip") for feed in allowed_feeds)
        ):
            raise SourceError("INVALID_FEED_AUTHORIZATION")
        self._credentials = credentials
        self._transport = transport or EquityHTTPS()
        self._allowed_feeds = allowed_feeds
        self.evidence_mode = (
            "RECORDED_FIXTURE" if transport is not None else "HISTORICAL_REAL"
        )
        self._health = Health("UNTESTED" if credentials else "NOT_CONFIGURED")
        self.last_pages: tuple[RawPage, ...] = ()

    def health(self) -> Health:
        return self._health

    def list_capabilities(self) -> tuple[str, ...]:
        return (
            "HISTORICAL_STOCK_BARS",
            "EXPLICIT_IEX_OR_SIP",
            "RAW_UNADJUSTED",
            "SYMBOL_MAPPING_DISABLED",
            "BOUNDED_PAGINATION",
            "NO_ORDERS_NO_BROKER_HOST",
            "NO_HISTORICAL_AVAILABILITY_CLAIM",
        )

    def validate_config(self, query: AlpacaBarQuery) -> None:
        if self._credentials is None:
            raise SourceError("ALPACA_CREDENTIALS_NOT_CONFIGURED")
        self._credentials.__post_init__()
        text(query.symbol, r"[A-Z][A-Z0-9.-]{0,14}", "INVALID_SYMBOL")
        if query.feed not in self._allowed_feeds:
            raise SourceError("FEED_NOT_AUTHORIZED")
        if query.timeframe not in ("1Min", "1Day"):
            raise SourceError("UNSUPPORTED_TIMEFRAME")
        for value in (query.start, query.end):
            if (
                type(value) is not datetime
                or value.tzinfo is None
                or value.utcoffset() != timedelta(0)
            ):
                raise SourceError("UTC_QUERY_REQUIRED")
        if not timedelta(0) <= query.end - query.start <= timedelta(days=366):
            raise SourceError("INVALID_DATE_RANGE")
        if (
            type(query.page_size) is not int
            or not 1 <= query.page_size <= 1000
            or type(query.max_pages) is not int
            or not 1 <= query.max_pages <= 5
        ):
            raise SourceError("INVALID_PAGE_BOUND")

    def _request(self, query: AlpacaBarQuery, token: str | None) -> EquityRequest:
        if self._credentials is None:
            raise SourceError("ALPACA_CREDENTIALS_NOT_CONFIGURED")
        params = {
            "symbols": query.symbol,
            "timeframe": query.timeframe,
            "start": stamp(query.start),
            "end": stamp(query.end),
            "feed": query.feed,
            "limit": str(query.page_size),
            "adjustment": "raw",
            "asof": "-",
            "currency": "USD",
            "sort": "asc",
        }
        if token is not None:
            params["page_token"] = token
        return EquityRequest(
            "data.alpaca.markets",
            "/v2/stocks/bars?" + urlencode(params),
            "QuantHunter/0.1 read-only data",
            self._credentials.key_id,
            self._credentials.secret_key,
        )

    def fetch_range(self, query: AlpacaBarQuery) -> AlpacaBatch:
        self.last_pages = ()
        records: list[AlpacaBar] = []
        seen: set[str] = set()
        token: str | None = None
        try:
            self.validate_config(query)
            for _ in range(query.max_pages):
                page = receive(self._transport, self._request(query, token))
                self.last_pages += (page,)
                normalized = self.normalize(page.raw, query, page.retrieved_at)
                records.extend(normalized.records)
                self.validate_batch(tuple(records), query)
                token = normalized.next_page_token
                if token is None:
                    break
                if token in seen:
                    raise SourceError("PAGINATION_LOOP")
                seen.add(token)
            if token is not None:
                raise SourceError("PAGINATION_LIMIT")
        except SourceError as error:
            self._health = Health("FAILED", datetime.now(UTC), error.code)
            raise
        self._health = Health("SUCCEEDED", datetime.now(UTC))
        return AlpacaBatch(
            self.catalogue_id,
            query,
            tuple(records),
            self.last_pages,
            self.evidence_mode,
        )

    def test_connection(self, query: AlpacaBarQuery) -> AlpacaBatch:
        return self.fetch_range(query)

    def normalize(
        self, raw: bytes, query: AlpacaBarQuery, retrieved_at: datetime
    ) -> AlpacaPage:
        self.validate_config(query)
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() != timedelta(0):
            raise SourceError("UTC_RETRIEVAL_REQUIRED")
        payload = json_object(raw)
        if "bars" not in payload or "next_page_token" not in payload:
            raise SourceError("INVALID_BARS_SCHEMA")
        grouped = mapping(payload["bars"])
        if set(grouped) - {query.symbol}:
            raise SourceError("CONTRADICTORY_SYMBOL")
        rows = grouped.get(query.symbol, [])
        if not isinstance(rows, list) or len(rows) > query.page_size:
            raise SourceError("BAR_ROW_LIMIT")
        records: list[AlpacaBar] = []
        for row in rows:
            item = mapping(row)
            timestamp = utc_timestamp(item.get("t"))
            prices = [
                number(item.get(key), nonnegative=True) for key in ("o", "h", "l", "c")
            ]
            opening, high, low, close = prices
            if (
                min(prices) <= 0
                or high < max(opening, low, close)
                or low > min(opening, high, close)
            ):
                raise SourceError("INCONSISTENT_OHLC")
            volume = number(item.get("v"), nonnegative=True)
            count = item.get("n")
            if type(count) is not int or not 0 <= count <= 10**12:
                raise SourceError("INVALID_TRADE_COUNT")
            vwap = (
                None if item.get("vw") is None else number(item["vw"], nonnegative=True)
            )
            if vwap is not None and vwap <= 0:
                raise SourceError("INVALID_VWAP")
            flags = (
                ("IEX_SINGLE_VENUE_PARTIAL_COVERAGE",)
                if query.feed == "iex"
                else ("SIP_ENTITLEMENT_AND_COVERAGE_NOT_CERTIFIED",)
            )
            records.append(
                AlpacaBar(
                    query.symbol,
                    timestamp,
                    opening,
                    high,
                    low,
                    close,
                    volume,
                    count,
                    vwap,
                    query.feed,
                    query.timeframe,
                    retrieved_at,
                    quality_flags=_BAR_FLAGS + flags,
                )
            )
        result = tuple(records)
        self.validate_batch(result, query)
        return AlpacaPage(result, page_token(payload["next_page_token"]))

    def validate_batch(
        self, records: tuple[AlpacaBar, ...], query: AlpacaBarQuery
    ) -> None:
        if len(records) > query.page_size * query.max_pages:
            raise SourceError("BAR_ROW_LIMIT")
        previous: datetime | None = None
        for record in records:
            if (
                record.symbol != query.symbol
                or record.feed != query.feed
                or record.timeframe != query.timeframe
                or not query.start <= record.timestamp <= query.end
            ):
                raise SourceError("RECORD_QUERY_MISMATCH")
            if previous is not None and record.timestamp <= previous:
                raise SourceError("DUPLICATE_OR_UNORDERED_BAR")
            if (
                record.available_at is not None
                or record.point_in_time_eligible
                or record.publication_time is not None
                or record.revision_time is not None
            ):
                raise SourceError("UNSUPPORTED_AVAILABILITY_CLAIM")
            previous = record.timestamp
