"""Concrete EOD daily owner export parser, without URL-token transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from quant_hunter.sources._equity_transport import calendar_date, mapping, text
from quant_hunter.sources.connectors import Health
from quant_hunter.sources.macro_common import require_utc
from quant_hunter.sources.priority_common import (
    PriorityBatch,
    date_range,
    exact_json,
    imported,
    number,
)
from quant_hunter.sources.transport import SourceError


@dataclass(frozen=True)
class EODQuery:
    symbol: str
    currency: str
    start: date
    end: date
    declared_listing_status: str = "UNKNOWN"


@dataclass(frozen=True)
class EODRecord:
    symbol: str
    trading_date: date
    declared_currency: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal
    split_adjusted_volume: int
    declared_listing_status: str
    ingestion_time: datetime
    ohlc_basis: str = "RAW_AS_TRADED"
    adjusted_close_basis: str = "SPLIT_AND_DIVIDEND_ADJUSTED_CURRENT_EXPORT"
    currency_binding: str = "OWNER_DECLARED_NOT_IN_RESPONSE"
    symbol_binding: str = "OWNER_DECLARED_NOT_IN_RESPONSE"
    available_at: None = None
    point_in_time_eligible: bool = False


class EODHDFileImporter:
    transport_status = "BLOCKED_EXTERNAL"
    transport_reason = "Official REST docs use URL api_token; compatible header authentication not verified"

    def __init__(self) -> None:
        self._health = Health("UNTESTED")

    def health(self) -> Health:
        return self._health

    def list_capabilities(self) -> tuple[str, ...]:
        return (
            "LOCAL_EOD_JSON",
            "RAW_VS_ADJUSTED_DISTINCT",
            "DECLARED_DELISTED_SYMBOLS",
            "NO_SURVIVORSHIP_CLAIM",
        )

    def validate_config(self, query: EODQuery) -> None:
        text(
            query.symbol,
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,30}\.[A-Z]{2,8}",
            "INVALID_SYMBOL",
        )
        text(query.currency, r"[A-Z]{3}", "INVALID_CURRENCY")
        date_range(query.start, query.end)
        if query.declared_listing_status not in ("UNKNOWN", "ACTIVE", "DELISTED"):
            raise SourceError("INVALID_LISTING_STATUS")

    def import_bytes(
        self,
        raw: bytes,
        query: EODQuery,
        retrieved: datetime,
        *,
        evidence_mode: str = "OWNER_SUPPLIED",
    ) -> PriorityBatch[EODRecord]:
        try:
            records = self.normalize(raw, query, retrieved)
            result = imported("SRC-19", records, raw, retrieved, evidence_mode)
        except SourceError as error:
            self._health = Health("FAILED", datetime.now(UTC), error.code)
            raise
        self._health = Health("SUCCEEDED", retrieved)
        return result

    def normalize(
        self, raw: bytes, query: EODQuery, retrieved: datetime
    ) -> tuple[EODRecord, ...]:
        self.validate_config(query)
        require_utc(retrieved)
        payload = exact_json(raw)
        if not isinstance(payload, list) or len(payload) > 5000:
            raise SourceError("INVALID_EOD_SCHEMA")
        result: list[EODRecord] = []
        for item in payload:
            row = mapping(item)
            day = calendar_date(row.get("date"))
            if not query.start <= day <= query.end or day > retrieved.date():
                raise SourceError("OBSERVATION_OUTSIDE_RANGE")
            values = [
                number(row.get(key))
                for key in ("open", "high", "low", "close", "adjusted_close")
            ]
            o, h, low, close, adjusted = values
            if (
                o is None
                or h is None
                or low is None
                or close is None
                or adjusted is None
                or min(o, h, low, close, adjusted) <= 0
            ):
                raise SourceError("INVALID_EOD_PRICE")
            if not low <= min(o, close) <= max(o, close) <= h:
                raise SourceError("INVALID_OHLC_RELATIONSHIP")
            volume = row.get("volume")
            if type(volume) is not int or not 0 <= volume <= 10**15:
                raise SourceError("INVALID_VOLUME")
            result.append(
                EODRecord(
                    query.symbol,
                    day,
                    query.currency,
                    o,
                    h,
                    low,
                    close,
                    adjusted,
                    volume,
                    query.declared_listing_status,
                    retrieved,
                )
            )
        records = tuple(result)
        self.validate_batch(records, query)
        return records

    def validate_batch(self, records: tuple[EODRecord, ...], query: EODQuery) -> None:
        previous: date | None = None
        for record in records:
            require_utc(record.ingestion_time)
            if (
                record.symbol != query.symbol
                or record.declared_currency != query.currency
                or record.declared_listing_status != query.declared_listing_status
                or (previous is not None and record.trading_date <= previous)
                or record.available_at is not None
                or record.point_in_time_eligible
            ):
                raise SourceError("EOD_BATCH_MISMATCH")
            previous = record.trading_date
