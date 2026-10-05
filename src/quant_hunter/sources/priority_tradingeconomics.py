"""One bounded calendar snapshot; current consensus is not pre-release evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import quote

from quant_hunter.sources._equity_transport import mapping, text, utc_timestamp
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
)
from quant_hunter.sources.priority_transport import (
    PriorityHTTPS,
    PriorityRequest,
    PriorityTransport,
)
from quant_hunter.sources.transport import Response, SourceError, checked_body


@dataclass(frozen=True)
class CalendarQuery:
    country: str
    start: date
    end: date


@dataclass(frozen=True)
class CalendarEvent:
    calendar_id: str
    country: str
    event: str
    category: str
    scheduled_release: datetime
    time_precision: str
    reference: str
    reference_date: str | None
    actual: str | None
    previous_after_revision: str | None
    previous_before_revision: str | None
    consensus_forecast: str | None
    provider_forecast: str | None
    unit: str
    currency: str
    importance: int
    provider_last_update: str
    source: str
    ticker: str
    ingestion_time: datetime
    available_at: None = None
    consensus_available_at: None = None
    point_in_time_eligible: bool = False
    quality_flags: tuple[str, ...] = (
        "CURRENT_SNAPSHOT_NOT_PREPUBLICATION_CONSENSUS",
        "SCHEDULED_TIME_NOT_OBSERVED_DISSEMINATION",
        "LAST_UPDATE_TIMEZONE_UNVERIFIED",
    )


def _string(value: object, *, maximum: int = 200, missing: bool = False) -> str | None:
    if missing and value in (None, ""):
        return None
    return text(value, rf"[^\x00-\x1f\x7f]{{0,{maximum}}}", "INVALID_CALENDAR_FIELD")


class TradingEconomicsConnector:
    catalogue_id = "SRC-20"

    def __init__(
        self, key: PriorityKey | None = None, transport: PriorityTransport | None = None
    ) -> None:
        self._key = key
        self._transport = transport or PriorityHTTPS()
        self.evidence_mode = (
            "RECORDED_FIXTURE" if transport is not None else "HISTORICAL_REAL"
        )
        self._health = Health("NOT_CONFIGURED" if key is None else "UNTESTED")
        self.last_raw: bytes | None = None

    def health(self) -> Health:
        return self._health

    def list_capabilities(self) -> tuple[str, ...]:
        return (
            "CALENDAR_AUTHORIZATION_HEADER",
            "ONE_COUNTRY_SEVEN_DAY_MAX",
            "ACTUAL_PREVIOUS_CONSENSUS_SEPARATE",
            "NO_CONSENSUS_VINTAGE_CLAIM",
        )

    def validate_config(self, query: CalendarQuery) -> None:
        text(query.country, r"[A-Za-z][A-Za-z -]{1,39}", "INVALID_COUNTRY")
        date_range(query.start, query.end, 7)

    def fetch_range(self, query: CalendarQuery) -> PriorityBatch[CalendarEvent]:
        self.last_raw = None
        try:
            self.validate_config(query)
            if self._key is None:
                raise SourceError("API_KEY_NOT_CONFIGURED")
            country = quote(query.country.lower(), safe="-")
            target = f"/calendar/country/{country}/{query.start}/{query.end}?f=json"
            response = self._transport.send(
                PriorityRequest("api.tradingeconomics.com", target, self._key)
            )
            reject_secret_reflection(response.body, self._key.value)
            raw = checked_body(
                Response(response.status, response.body, response.retry_after)
            )
            retrieved = datetime.now(UTC)
            records = self.normalize(raw, query, retrieved)
            self.last_raw = raw
        except TimeoutError:
            self._health = Health("FAILED", datetime.now(UTC), "TIMEOUT")
            raise SourceError("TIMEOUT") from None
        except OSError:
            self._health = Health("FAILED", datetime.now(UTC), "NETWORK_FAILURE")
            raise SourceError("NETWORK_FAILURE") from None
        except SourceError as error:
            self._health = Health("FAILED", datetime.now(UTC), error.code)
            raise
        self._health = Health("SUCCEEDED", retrieved)
        return PriorityBatch(
            self.catalogue_id, records, (raw_page(raw, retrieved),), self.evidence_mode
        )

    def test_connection(self, query: CalendarQuery) -> PriorityBatch[CalendarEvent]:
        return self.fetch_range(query)

    def normalize(
        self, raw: bytes, query: CalendarQuery, retrieved: datetime
    ) -> tuple[CalendarEvent, ...]:
        self.validate_config(query)
        require_utc(retrieved)
        payload = exact_json(raw)
        # Provider's maximum is 1000; equality may mean silent truncation.
        if not isinstance(payload, list) or len(payload) >= 1000:
            raise SourceError("CALENDAR_ROW_LIMIT_OR_TRUNCATION")
        result: list[CalendarEvent] = []
        for item in payload:
            row = mapping(item)
            required = {
                "Country",
                "Date",
                "DateSpan",
                "Importance",
                "LastUpdate",
                "Event",
                "Category",
                "Reference",
                "ReferenceDate",
                "Actual",
                "Previous",
                "Revised",
                "Forecast",
                "TEForecast",
                "Unit",
                "Currency",
                "Source",
                "Ticker",
            }
            if not required.issubset(row):
                raise SourceError("CALENDAR_MISSING_FIELD")
            identifier = row.get("CalendarId", row.get("CalendarID"))
            if (
                "CalendarId" in row
                and "CalendarID" in row
                and row["CalendarId"] != row["CalendarID"]
            ):
                raise SourceError("CALENDAR_ID_CONFLICT")
            calendar_id = text(identifier, r"[0-9]{1,20}", "INVALID_CALENDAR_ID")
            country = text(
                row.get("Country"), r"[A-Za-z][A-Za-z -]{1,39}", "INVALID_COUNTRY"
            )
            if country.lower() != query.country.lower():
                raise SourceError("CALENDAR_COUNTRY_MISMATCH")
            # Official calendar Date is UTC despite offset-free example syntax.
            encoded = text(
                row.get("Date"),
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z?",
                "INVALID_CALENDAR_TIME",
            )
            scheduled = utc_timestamp(
                encoded if encoded.endswith("Z") else encoded + "Z"
            )
            if not query.start <= scheduled.date() <= query.end:
                raise SourceError("CALENDAR_OUTSIDE_RANGE")
            precision = row.get("DateSpan")
            if precision not in ("0", "1"):
                raise SourceError("INVALID_TIME_PRECISION")
            importance = row.get("Importance")
            if type(importance) is not int or importance not in (1, 2, 3):
                raise SourceError("INVALID_IMPORTANCE")
            actual = _string(row.get("Actual"), missing=True)
            if actual is not None and precision == "0" and scheduled > retrieved:
                raise SourceError("FUTURE_ACTUAL_VALUE")
            update = text(
                row.get("LastUpdate"),
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z?",
                "INVALID_UPDATE_TIME",
            )
            # Validate the date/time shape without inventing a timezone assignment.
            utc_timestamp(update if update.endswith("Z") else update + "Z")
            reference_date = _string(row.get("ReferenceDate"), missing=True)
            if reference_date is not None:
                text(
                    reference_date,
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T00:00:00",
                    "INVALID_REFERENCE_DATE",
                )
                utc_timestamp(reference_date + "Z")
            result.append(
                CalendarEvent(
                    calendar_id,
                    country,
                    text(row.get("Event"), r"[^\x00-\x1f]{1,200}", "INVALID_EVENT"),
                    text(
                        row.get("Category"), r"[^\x00-\x1f]{1,200}", "INVALID_CATEGORY"
                    ),
                    scheduled,
                    "EXACT_SOURCE_SCHEDULE"
                    if precision == "0"
                    else "ESTIMATED_SOURCE_SCHEDULE",
                    _string(row.get("Reference")) or "",
                    reference_date,
                    actual,
                    _string(row.get("Previous"), missing=True),
                    _string(row.get("Revised"), missing=True),
                    _string(row.get("Forecast"), missing=True),
                    _string(row.get("TEForecast"), missing=True),
                    _string(row.get("Unit")) or "",
                    _string(row.get("Currency")) or "",
                    importance,
                    update,
                    _string(row.get("Source")) or "",
                    _string(row.get("Ticker")) or "",
                    retrieved,
                )
            )
        records = tuple(
            sorted(result, key=lambda row: (row.scheduled_release, row.calendar_id))
        )
        self.validate_batch(records, query)
        return records

    def validate_batch(
        self, records: tuple[CalendarEvent, ...], query: CalendarQuery
    ) -> None:
        seen: set[str] = set()
        for record in records:
            require_utc(record.scheduled_release)
            require_utc(record.ingestion_time)
            if (
                record.calendar_id in seen
                or record.country.lower() != query.country.lower()
                or record.available_at is not None
                or record.consensus_available_at is not None
                or record.point_in_time_eligible
            ):
                raise SourceError("CALENDAR_BATCH_MISMATCH")
            seen.add(record.calendar_id)
