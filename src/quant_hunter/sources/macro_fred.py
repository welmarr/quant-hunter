"""FRED v2 header-auth release client and separately bounded ALFRED v1 imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from urllib.parse import urlencode

from quant_hunter.sources._equity_transport import (
    calendar_date,
    json_object,
    mapping,
    text,
    utc_timestamp,
)
from quant_hunter.sources.connectors import Health
from quant_hunter.sources.macro_common import (
    MacroBatch,
    MacroObservation,
    decimal_text,
    raw_page,
    reject_embedded_credentials,
    reject_secret_reflection,
    require_utc,
    safe_metadata,
    validate_macro_batch,
)
from quant_hunter.sources.macro_transport import (
    MacroHTTPS,
    MacroRequest,
    MacroTransport,
)
from quant_hunter.sources.transport import (
    MAX_RESPONSE_BYTES,
    Response,
    SourceError,
    checked_body,
)


@dataclass(frozen=True)
class FREDKey:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        text(self.value, r"[a-z0-9]{32}", "INVALID_FRED_KEY")


@dataclass(frozen=True)
class FREDReleaseQuery:
    release_id: int
    page_size: int = 1000
    max_pages: int = 5


@dataclass(frozen=True)
class FREDReleasePage:
    observations: tuple[MacroObservation, ...]
    next_cursor: str | None = field(repr=False)


class FREDReleaseConnector:
    catalogue_id = "SRC-07"
    version = "v0-fred-v2-1"

    def __init__(
        self, key: FREDKey | None = None, transport: MacroTransport | None = None
    ) -> None:
        self._key = key
        self._transport = transport or MacroHTTPS()
        self.evidence_mode = (
            "RECORDED_FIXTURE" if transport is not None else "HISTORICAL_REAL"
        )
        self._health = Health("NOT_CONFIGURED" if key is None else "UNTESTED")
        self.last_pages: tuple[bytes, ...] = ()

    def health(self) -> Health:
        return self._health

    def list_capabilities(self) -> tuple[str, ...]:
        return (
            "FRED_V2_HEADER_AUTH",
            "BOUNDED_RELEASE_PAGINATION",
            "LATEST_VALUES_ONLY",
            "NO_ALFRED_VINTAGE_QUERY",
        )

    def validate_config(self, query: FREDReleaseQuery) -> None:
        if self._key is None:
            raise SourceError("FRED_KEY_NOT_CONFIGURED")
        self._key.__post_init__()
        if (
            type(query.release_id) is not int
            or not 1 <= query.release_id <= 9999999
            or type(query.page_size) is not int
            or not 1 <= query.page_size <= 1000
            or type(query.max_pages) is not int
            or not 1 <= query.max_pages <= 5
        ):
            raise SourceError("INVALID_FRED_QUERY")

    def fetch_range(self, query: FREDReleaseQuery) -> MacroBatch:
        self.last_pages = ()
        records: list[MacroObservation] = []
        pages = []
        cursor: str | None = None
        seen: set[str] = set()
        try:
            self.validate_config(query)
            for _ in range(query.max_pages):
                params = {
                    "release_id": str(query.release_id),
                    "format": "json",
                    "limit": str(query.page_size),
                }
                if cursor is not None:
                    params["next_cursor"] = cursor
                request = MacroRequest(
                    "api.stlouisfed.org",
                    "/fred/v2/release/observations?" + urlencode(params),
                    None if self._key is None else self._key.value,
                )
                response = self._transport.send(request)
                if len(response.body) > MAX_RESPONSE_BYTES:
                    raise SourceError("RESPONSE_TOO_LARGE")
                if self._key is not None:
                    reject_secret_reflection(response.body, self._key.value)
                raw = checked_body(
                    Response(response.status, response.body, response.retry_after)
                )
                retrieved = datetime.now(UTC)
                page = self.normalize(raw, query, retrieved)
                self.last_pages += (raw,)
                pages.append(raw_page(raw, retrieved))
                records.extend(page.observations)
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
        self._health = Health("SUCCEEDED", datetime.now(UTC))
        return MacroBatch(
            self.catalogue_id, tuple(records), tuple(pages), self.evidence_mode
        )

    def test_connection(self, query: FREDReleaseQuery) -> MacroBatch:
        return self.fetch_range(query)

    def normalize(
        self, raw: bytes, query: FREDReleaseQuery, retrieved: datetime
    ) -> FREDReleasePage:
        self.validate_config(query)
        require_utc(retrieved)
        payload = json_object(raw)
        reject_embedded_credentials(payload)
        release_id = mapping(payload.get("release")).get("release_id")
        if type(release_id) is not int or release_id != query.release_id:
            raise SourceError("RELEASE_ID_MISMATCH")
        more = payload.get("has_more")
        if type(more) is not bool and more not in ("true", "false"):
            raise SourceError("INVALID_PAGINATION_STATE")
        has_more = more is True or more == "true"
        cursor = payload.get("next_cursor")
        if has_more:
            next_cursor = text(
                cursor,
                r"[A-Za-z0-9_.-]{1,80},[0-9]{4}-[0-9]{2}-[0-9]{2}",
                "INVALID_CURSOR",
            )
            calendar_date(next_cursor.split(",")[1])
        else:
            if cursor is not None:
                raise SourceError("CONTRADICTORY_PAGINATION")
            next_cursor = None
        series = payload.get("series")
        if not isinstance(series, list) or len(series) > query.page_size:
            raise SourceError("INVALID_SERIES_SCHEMA")
        result: list[MacroObservation] = []
        series_seen: set[str] = set()
        for item in series:
            row = mapping(item)
            series_id = text(
                row.get("series_id"), r"[A-Za-z0-9_.-]{1,80}", "INVALID_SERIES_ID"
            )
            if series_id in series_seen:
                raise SourceError("DUPLICATE_SERIES")
            series_seen.add(series_id)
            unit = safe_metadata(row.get("units"))
            frequency = safe_metadata(row.get("frequency"), maximum=40)
            seasonality = safe_metadata(row.get("seasonal_adjustment"), maximum=80)
            copyright_id = safe_metadata(row.get("copyright_id"), maximum=200)
            updated = utc_timestamp(row.get("last_updated"))
            if updated > retrieved:
                raise SourceError("FUTURE_UPDATE_TIME")
            observations = row.get("observations")
            if not isinstance(observations, list):
                raise SourceError("INVALID_OBSERVATIONS_SCHEMA")
            for observation in observations:
                if len(result) >= query.page_size:
                    raise SourceError("PAGE_ROW_LIMIT")
                data = mapping(observation)
                period = calendar_date(data.get("date"))
                if period > retrieved.date():
                    raise SourceError("FUTURE_OBSERVATION")
                value = decimal_text(data.get("value"))
                flags: tuple[str, ...] = (
                    "LATEST_VALUES_NOT_ALFRED_VINTAGES",
                    "SERIES_UPDATE_IS_NOT_OBSERVATION_PUBLICATION",
                    "RIGHTS:" + copyright_id,
                    "FREQUENCY:" + frequency,
                    "SEASONALITY:" + seasonality,
                )
                if value is None:
                    flags += ("MISSING_VALUE",)
                result.append(
                    MacroObservation(
                        self.catalogue_id,
                        series_id,
                        period.isoformat(),
                        period,
                        value,
                        unit,
                        retrieved,
                        "LATEST_AT_RETRIEVAL",
                        source_updated_at=updated,
                        quality_flags=flags,
                    )
                )
        normalized = tuple(result)
        self.validate_batch(normalized, query)
        return FREDReleasePage(normalized, next_cursor)

    def validate_batch(
        self, records: tuple[MacroObservation, ...], query: FREDReleaseQuery
    ) -> None:
        validate_macro_batch(records, self.catalogue_id)
        if len(records) > query.page_size * query.max_pages:
            raise SourceError("ROW_LIMIT")
        latest: dict[str, date] = {}
        metadata: dict[str, tuple[object, ...]] = {}
        for record in records:
            if (
                record.series_id in latest
                and record.period_start <= latest[record.series_id]
            ):
                raise SourceError("UNORDERED_OBSERVATIONS")
            latest[record.series_id] = record.period_start
            identity = (
                record.unit,
                record.source_updated_at,
                tuple(flag for flag in record.quality_flags if flag != "MISSING_VALUE"),
            )
            if record.series_id in metadata and metadata[record.series_id] != identity:
                raise SourceError("SERIES_CHANGED_DURING_PAGINATION")
            metadata[record.series_id] = identity


@dataclass(frozen=True)
class ALFREDImportQuery:
    series_id: str
    unit: str
    realtime_start: date
    realtime_end: date
    observation_start: date
    observation_end: date


class ALFREDFileImporter:
    """Parse owner-supplied v1 JSON + series metadata; never issue query-key HTTP."""

    transport_status = "BLOCKED_EXTERNAL"
    transport_reason = (
        "V1 documents URL api_key; no compatible header/body alternative verified"
    )

    def validate_config(self, query: ALFREDImportQuery) -> None:
        text(query.series_id, r"[A-Za-z0-9_.-]{1,80}", "INVALID_SERIES_ID")
        safe_metadata(query.unit)
        values = (
            query.realtime_start,
            query.realtime_end,
            query.observation_start,
            query.observation_end,
        )
        if (
            any(type(value) is not date for value in values)
            or query.realtime_start > query.realtime_end
            or query.observation_start > query.observation_end
        ):
            raise SourceError("INVALID_DATE_RANGE")

    def import_bytes(
        self,
        raw: bytes,
        series_metadata: bytes,
        query: ALFREDImportQuery,
        retrieved: datetime,
        *,
        evidence_mode: str = "OWNER_SUPPLIED",
    ) -> MacroBatch:
        if evidence_mode not in ("OWNER_SUPPLIED", "RECORDED_FIXTURE"):
            raise SourceError("INVALID_EVIDENCE_MODE")
        records = self.normalize(raw, series_metadata, query, retrieved)
        return MacroBatch(
            "SRC-07",
            records,
            (raw_page(raw, retrieved), raw_page(series_metadata, retrieved)),
            evidence_mode,
        )

    def normalize(
        self,
        raw: bytes,
        series_metadata: bytes,
        query: ALFREDImportQuery,
        retrieved: datetime,
    ) -> tuple[MacroObservation, ...]:
        self.validate_config(query)
        require_utc(retrieved)
        if len(raw) + len(series_metadata) > MAX_RESPONSE_BYTES:
            raise SourceError("RESPONSE_TOO_LARGE")
        payload, metadata = json_object(raw), json_object(series_metadata)
        reject_embedded_credentials(payload)
        reject_embedded_credentials(metadata)
        series = metadata.get("seriess")
        if not isinstance(series, list) or len(series) != 1:
            raise SourceError("SERIES_METADATA_REQUIRED")
        series_record = mapping(series[0])
        if (
            series_record.get("id") != query.series_id
            or series_record.get("units") != query.unit
        ):
            raise SourceError("SERIES_OR_UNIT_MISMATCH")
        if (
            payload.get("units") != "lin"
            or type(payload.get("output_type")) is not int
            or payload.get("output_type") != 1
            or payload.get("order_by") != "observation_date"
            or payload.get("sort_order") != "asc"
        ):
            raise SourceError("UNSUPPORTED_VINTAGE_OUTPUT")
        for field_name, expected in (
            ("realtime_start", query.realtime_start),
            ("realtime_end", query.realtime_end),
            ("observation_start", query.observation_start),
            ("observation_end", query.observation_end),
        ):
            if calendar_date(payload.get(field_name)) != expected:
                raise SourceError("VINTAGE_QUERY_MISMATCH")
        rows = payload.get("observations")
        if (
            not isinstance(rows, list)
            or len(rows) > 5000
            or type(payload.get("count")) is not int
            or payload["count"] != len(rows)
            or type(payload.get("offset")) is not int
            or payload.get("offset") != 0
        ):
            raise SourceError("INCOMPLETE_VINTAGE_EXPORT")
        result: list[MacroObservation] = []
        for item in rows:
            row = mapping(item)
            period = calendar_date(row.get("date"))
            start, end = (
                calendar_date(row.get("realtime_start")),
                calendar_date(row.get("realtime_end")),
            )
            if (
                not query.observation_start <= period <= query.observation_end
                or not query.realtime_start <= start <= end <= query.realtime_end
            ):
                raise SourceError("OBSERVATION_OUTSIDE_RANGE")
            if period > retrieved.date():
                raise SourceError("FUTURE_OBSERVATION")
            if start > retrieved.date():
                raise SourceError("FUTURE_REALTIME_START")
            result.append(
                MacroObservation(
                    "SRC-07",
                    query.series_id,
                    period.isoformat(),
                    period,
                    decimal_text(row.get("value")),
                    query.unit,
                    retrieved,
                    f"{start}/{end}",
                    realtime_start=start,
                    realtime_end=end,
                    quality_flags=(
                        "REALTIME_DATES_CLOSED_INTERVAL",
                        "INTRADAY_AVAILABILITY_UNKNOWN",
                        "SERIES_BINDING_FROM_OWNER_METADATA",
                    ),
                )
            )
        normalized = tuple(result)
        self.validate_batch(normalized, query)
        return normalized

    def validate_batch(
        self, records: tuple[MacroObservation, ...], query: ALFREDImportQuery
    ) -> None:
        validate_macro_batch(records, "SRC-07")
        previous: tuple[date, date] | None = None
        ends: dict[date, date] = {}
        for record in records:
            if (
                record.series_id != query.series_id
                or record.unit != query.unit
                or record.realtime_start is None
                or record.realtime_end is None
            ):
                raise SourceError("VINTAGE_BATCH_MISMATCH")
            key = (record.period_start, record.realtime_start)
            if previous is not None and key <= previous:
                raise SourceError("UNORDERED_VINTAGES")
            if (
                record.period_start in ends
                and record.realtime_start <= ends[record.period_start]
            ):
                raise SourceError("OVERLAPPING_REALTIME_INTERVALS")
            ends[record.period_start] = record.realtime_end
            previous = key
