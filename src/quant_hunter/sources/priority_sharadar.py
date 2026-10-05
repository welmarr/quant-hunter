"""Bounded Nasdaq SF1 header-auth client; filing dates are not PIT authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import urlencode

from quant_hunter.sources._equity_transport import calendar_date, mapping, text
from quant_hunter.sources.connectors import Health
from quant_hunter.sources.macro_common import (
    raw_page,
    reject_secret_reflection,
    require_utc,
)
from quant_hunter.sources.priority_common import (
    PriorityBatch,
    PriorityKey,
    date_range,
    exact_json,
    number,
)
from quant_hunter.sources.priority_transport import (
    SF1_COLUMNS,
    PriorityHTTPS,
    PriorityRequest,
    PriorityTransport,
)
from quant_hunter.sources.transport import Response, SourceError, checked_body


@dataclass(frozen=True)
class SF1Query:
    ticker: str
    dimension: str
    start: date
    end: date
    max_pages: int = 5


@dataclass(frozen=True)
class SF1Record:
    ticker: str
    dimension: str
    datekey: date
    calendardate: date
    reportperiod: date
    lastupdated: date
    revenue: Decimal | None
    netinc: Decimal | None
    assets: Decimal | None
    ingestion_time: datetime
    financial_unit: str = "PROVIDER_NATIVE_CURRENCY_UNVERIFIED"
    available_at: None = None
    point_in_time_eligible: bool = False
    quality_flags: tuple[str, ...] = (
        "DATABASE_SNAPSHOT_NOT_AUTHENTICATED_HISTORICAL_DELIVERY",
        "DATE_ONLY_FILING_INDEX_NOT_AVAILABILITY",
        "CURRENCY_METADATA_REQUIRED_FOR_RESEARCH",
    )


@dataclass(frozen=True)
class SF1Page:
    records: tuple[SF1Record, ...]
    next_cursor: str | None = field(repr=False)


class SharadarConnector:
    catalogue_id = "SRC-18"

    def __init__(
        self, key: PriorityKey | None = None, transport: PriorityTransport | None = None
    ) -> None:
        self._key = key
        self._transport = transport or PriorityHTTPS()
        self.evidence_mode = (
            "RECORDED_FIXTURE" if transport is not None else "HISTORICAL_REAL"
        )
        self._health = Health("NOT_CONFIGURED" if key is None else "UNTESTED")
        self.last_pages: tuple[bytes, ...] = ()

    def health(self) -> Health:
        return self._health

    def list_capabilities(self) -> tuple[str, ...]:
        return (
            "NASDAQ_SF1_X_API_TOKEN",
            "AR_MR_DISTINCT",
            "THREE_RAW_FINANCIAL_FIELDS",
            "BOUNDED_PAGINATION",
            "NO_PIT_APPROVAL",
        )

    def validate_config(self, query: SF1Query) -> None:
        text(query.ticker, r"[A-Z][A-Z0-9.-]{0,15}", "INVALID_TICKER")
        date_range(query.start, query.end)
        if (
            query.dimension not in ("ARQ", "ARY", "ART", "MRQ", "MRY", "MRT")
            or type(query.max_pages) is not int
            or not 1 <= query.max_pages <= 5
        ):
            raise SourceError("INVALID_SF1_QUERY")

    def fetch_range(self, query: SF1Query) -> PriorityBatch[SF1Record]:
        self.last_pages = ()
        pages = []
        records: list[SF1Record] = []
        cursor: str | None = None
        seen: set[str] = set()
        try:
            self.validate_config(query)
            if self._key is None:
                raise SourceError("API_KEY_NOT_CONFIGURED")
            for _ in range(query.max_pages):
                params = {
                    "ticker": query.ticker,
                    "dimension": query.dimension,
                    "datekey.gte": query.start.isoformat(),
                    "datekey.lte": query.end.isoformat(),
                    "qopts.columns": SF1_COLUMNS,
                    "qopts.per_page": "1000",
                }
                if cursor is not None:
                    params["qopts.cursor_id"] = cursor
                response = self._transport.send(
                    PriorityRequest(
                        "data.nasdaq.com",
                        "/api/v3/datatables/SHARADAR/SF1.json?" + urlencode(params),
                        self._key,
                    )
                )
                reject_secret_reflection(response.body, self._key.value)
                raw = checked_body(
                    Response(response.status, response.body, response.retry_after)
                )
                retrieved = datetime.now(UTC)
                page = self.normalize(raw, query, retrieved)
                pages.append(raw_page(raw, retrieved))
                self.last_pages += (raw,)
                records.extend(page.records)
                self.validate_batch(tuple(records), query)
                cursor = page.next_cursor
                if cursor is None:
                    break
                if cursor in seen:
                    raise SourceError("PAGINATION_LOOP")
                seen.add(cursor)
            if cursor is not None:
                raise SourceError("PAGINATION_LIMIT")
        except TimeoutError:
            self._health = Health("FAILED", datetime.now(UTC), "TIMEOUT")
            raise SourceError("TIMEOUT") from None
        except OSError:
            self._health = Health("FAILED", datetime.now(UTC), "NETWORK_FAILURE")
            raise SourceError("NETWORK_FAILURE") from None
        except SourceError as error:
            self._health = Health("FAILED", datetime.now(UTC), error.code)
            raise
        # Official tables are not ordered; stable local sorting preserves raw pages.
        ordered = tuple(
            sorted(
                records,
                key=lambda row: (row.datekey, row.reportperiod, row.lastupdated),
            )
        )
        self._health = Health("SUCCEEDED", datetime.now(UTC))
        return PriorityBatch(
            self.catalogue_id, ordered, tuple(pages), self.evidence_mode
        )

    def test_connection(self, query: SF1Query) -> PriorityBatch[SF1Record]:
        return self.fetch_range(query)

    def normalize(self, raw: bytes, query: SF1Query, retrieved: datetime) -> SF1Page:
        self.validate_config(query)
        require_utc(retrieved)
        payload = mapping(exact_json(raw))
        table = mapping(payload.get("datatable"))
        columns = table.get("columns")
        if not isinstance(columns, list) or len(columns) != 9:
            raise SourceError("INVALID_SF1_COLUMNS")
        names: list[str] = []
        for item in columns:
            column = mapping(item)
            name = text(column.get("name"), r"[a-z]{1,20}", "INVALID_SF1_COLUMN")
            kind = column.get("type")
            expected = (
                "String"
                if name in ("ticker", "dimension")
                else "Date"
                if name in ("calendardate", "datekey", "reportperiod", "lastupdated")
                else None
            )
            if (expected is not None and kind != expected) or (
                expected is None
                and (
                    not isinstance(kind, str)
                    or re.fullmatch(
                        r"(?:BigDecimal\([0-9]{1,2},[0-9]{1,2}\)|Integer|Double)", kind
                    )
                    is None
                )
            ):
                raise SourceError("SF1_COLUMN_TYPE_MISMATCH")
            names.append(name)
        if len(set(names)) != 9 or set(names) != set(SF1_COLUMNS.split(",")):
            raise SourceError("INVALID_SF1_COLUMNS")
        data = table.get("data")
        if not isinstance(data, list) or len(data) > 1000:
            raise SourceError("INVALID_SF1_DATA")
        result: list[SF1Record] = []
        for values in data:
            if not isinstance(values, list) or len(values) != 9:
                raise SourceError("INVALID_SF1_ROW")
            row = dict(zip(names, values, strict=True))
            if row["ticker"] != query.ticker or row["dimension"] != query.dimension:
                raise SourceError("SF1_IDENTITY_MISMATCH")
            datekey, calendar, period, updated = (
                calendar_date(row[key])
                for key in ("datekey", "calendardate", "reportperiod", "lastupdated")
            )
            if (
                not query.start <= datekey <= query.end
                or updated > retrieved.date()
                or updated < datekey
                or (query.dimension.startswith("AR") and period > datekey)
                or (query.dimension.startswith("MR") and period != datekey)
            ):
                raise SourceError("SF1_TEMPORAL_MISMATCH")
            result.append(
                SF1Record(
                    query.ticker,
                    query.dimension,
                    datekey,
                    calendar,
                    period,
                    updated,
                    number(row["revenue"], missing=True),
                    number(row["netinc"], missing=True),
                    number(row["assets"], missing=True),
                    retrieved,
                )
            )
        meta = mapping(payload.get("meta"))
        if "next_cursor_id" not in meta:
            raise SourceError("PAGINATION_METADATA_REQUIRED")
        cursor = meta["next_cursor_id"]
        if cursor is not None:
            cursor = text(cursor, r"[A-Za-z0-9_-]{1,256}", "INVALID_CURSOR")
        records = tuple(result)
        self.validate_batch(records, query)
        return SF1Page(records, cursor)

    def validate_batch(self, records: tuple[SF1Record, ...], query: SF1Query) -> None:
        if len(records) > 1000 * query.max_pages:
            raise SourceError("ROW_LIMIT")
        seen: set[tuple[date, date]] = set()
        for record in records:
            require_utc(record.ingestion_time)
            if (
                record.ticker != query.ticker
                or record.dimension != query.dimension
                or record.available_at is not None
                or record.point_in_time_eligible
            ):
                raise SourceError("SF1_BATCH_MISMATCH")
            identity = (record.datekey, record.reportperiod)
            if identity in seen:
                raise SourceError("DUPLICATE_OR_CHANGED_SF1_OBSERVATION")
            seen.add(identity)
