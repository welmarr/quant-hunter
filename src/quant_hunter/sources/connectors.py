"""BLS latest monthly observations and ECB daily reference FX; never PIT claims."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

from quant_hunter.sources.transport import (
    MAX_RESPONSE_BYTES,
    HTTPSPublicTransport,
    Request,
    Response,
    SourceError,
    Transport,
    checked_body,
)


@dataclass(frozen=True)
class SourceQuery:
    series_id: str
    start: date
    end: date
    unit: str

    def __post_init__(self) -> None:
        if (
            type(self.start) is not date
            or type(self.end) is not date
            or self.start > self.end
        ):
            raise SourceError("INVALID_DATE_RANGE")
        if not re.fullmatch(r"[A-Za-z0-9 _/().%=-]{1,80}", self.unit):
            raise SourceError("UNIT_DECLARATION_REQUIRED")


@dataclass(frozen=True)
class Observation:
    catalogue_id: str
    series_id: str
    period: str
    period_start: date
    value: Decimal | None
    unit: str
    ingestion_time: datetime
    publication_time: datetime | None = None
    revision_time: datetime | None = None
    vintage: str = "LATEST_AT_RETRIEVAL_NOT_HISTORICAL_VINTAGE"
    point_in_time_eligible: bool = False
    price_nature: str = "NOT_APPLICABLE"
    quality_flags: tuple[str, ...] = ("PUBLICATION_UNKNOWN", "REVISION_TIME_UNKNOWN")


@dataclass(frozen=True)
class FetchedBatch:
    catalogue_id: str
    query: SourceQuery
    raw: bytes
    sha256: str
    retrieved_at: datetime
    observations: tuple[Observation, ...]
    coverage_complete: bool = False
    normalization_version: str = "v0-sources-1"
    evidence_mode: str = "HISTORICAL_REAL"
    limitations: tuple[str, ...] = (
        "Latest retrieved values, not historical publication vintages.",
        "Reference periods are dates; no event/publication timestamp is invented.",
        "Coverage, gaps, unit declaration and freshness require dataset review.",
    )


@dataclass(frozen=True)
class Health:
    status: str = "UNTESTED"
    last_checked_at: datetime | None = None
    last_error: str | None = None


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise SourceError("INVALID_SCHEMA")
    return cast(dict[str, object], value)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _number(value: object) -> Decimal | None:
    if value in ("", "-", "."):
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise SourceError("INVALID_NUMERIC_VALUE")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise SourceError("INVALID_NUMERIC_VALUE") from None
    if not number.is_finite() or number.copy_abs() > Decimal("1e24"):
        raise SourceError("INVALID_NUMERIC_VALUE")
    return number


def _timestamp(value: datetime) -> None:
    if value.tzinfo is not UTC:
        raise SourceError("UTC_RETRIEVAL_TIME_REQUIRED")


def _text(raw: bytes) -> str:
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise SourceError("INVALID_RESPONSE_SIZE")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SourceError("INVALID_ENCODING") from None


class _Connector:
    catalogue_id: str

    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport if transport is not None else HTTPSPublicTransport()
        self.evidence_mode = (
            "HISTORICAL_REAL" if transport is None else "RECORDED_FIXTURE"
        )
        self._health = Health()
        self.last_response: Response | None = None

    def health(self) -> Health:
        return self._health

    def list_capabilities(self) -> tuple[str, ...]:
        return (
            "BOUNDED_RANGE",
            "EXACT_RAW_BYTES",
            "LATEST_VALUES_ONLY",
            "NO_AUTO_RETRY",
        )

    def validate_config(self, query: SourceQuery) -> None:
        raise NotImplementedError

    def _request(self, query: SourceQuery) -> Request:
        raise NotImplementedError

    def normalize(
        self, raw: bytes, query: SourceQuery, retrieved_at: datetime
    ) -> tuple[Observation, ...]:
        raise NotImplementedError

    def validate_batch(
        self, observations: tuple[Observation, ...], query: SourceQuery
    ) -> None:
        if not observations:
            raise SourceError("NO_OBSERVATIONS_IN_RANGE")
        if len(observations) > 4000:
            raise SourceError("TOO_MANY_OBSERVATIONS")
        keys = [item.period_start for item in observations]
        if keys != sorted(set(keys)):
            raise SourceError("DUPLICATE_OR_UNORDERED_OBSERVATIONS")
        for item in observations:
            if (
                item.series_id != query.series_id
                or item.catalogue_id != self.catalogue_id
            ):
                raise SourceError("CONTRADICTORY_SERIES")
            if not query.start <= item.period_start <= query.end:
                raise SourceError("OBSERVATION_OUTSIDE_RANGE")
            if (
                item.point_in_time_eligible
                or item.publication_time
                or item.revision_time
            ):
                raise SourceError("UNSUPPORTED_AVAILABILITY_CLAIM")

    def fetch_range(self, query: SourceQuery) -> FetchedBatch:
        self.validate_config(query)
        try:
            self.last_response = None
            self.last_response = self.transport.send(self._request(query))
            raw = checked_body(self.last_response)
            received = datetime.now(UTC)
            observations = self.normalize(raw, query, received)
            self.validate_batch(observations, query)
        except SourceError as error:
            self._health = Health("FAILED", datetime.now(UTC), error.code)
            raise
        except TimeoutError:
            self._health = Health("FAILED", datetime.now(UTC), "TIMEOUT")
            raise SourceError("TIMEOUT") from None
        except OSError:
            self._health = Health("FAILED", datetime.now(UTC), "NETWORK_FAILURE")
            raise SourceError("NETWORK_FAILURE") from None
        self._health = Health("SUCCEEDED", received)
        return FetchedBatch(
            self.catalogue_id,
            query,
            raw,
            "sha256:" + hashlib.sha256(raw).hexdigest(),
            received,
            observations,
            evidence_mode=self.evidence_mode,
        )

    def test_connection(self, query: SourceQuery) -> FetchedBatch:
        """Perform one actual bounded request and normalization; never a credential-only check."""
        return self.fetch_range(query)


class BLSConnector(_Connector):
    """One v1 unauthenticated monthly series; annual summaries explicitly omitted."""

    catalogue_id = "SRC-04"

    def validate_config(self, query: SourceQuery) -> None:
        if not re.fullmatch(r"[A-Z0-9_-]{1,40}", query.series_id):
            raise SourceError("INVALID_BLS_SERIES")
        if query.end.year - query.start.year > 9 or query.start.year < 1900:
            raise SourceError("BLS_RANGE_EXCEEDS_TEN_YEARS")

    def _request(self, query: SourceQuery) -> Request:
        body = json.dumps(
            {
                "seriesid": [query.series_id],
                "startyear": str(query.start.year),
                "endyear": str(query.end.year),
            },
            separators=(",", ":"),
        ).encode()
        return Request("POST", "api.bls.gov", "/publicAPI/v1/timeseries/data/", body)

    def normalize(
        self, raw: bytes, query: SourceQuery, retrieved_at: datetime
    ) -> tuple[Observation, ...]:
        self.validate_config(query)
        _timestamp(retrieved_at)
        try:
            payload = _mapping(json.loads(_text(raw), object_pairs_hook=_unique_pairs))
        except json.JSONDecodeError, RecursionError:
            raise SourceError("INVALID_JSON") from None
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise SourceError("PROVIDER_REJECTED_REQUEST")
        if payload.get("message") != []:
            raise SourceError("PROVIDER_WARNING_OR_SCHEMA_CHANGE")
        results = payload.get("Results")
        # Both wrappers occur in BLS's official v1 documentation/examples.
        if isinstance(results, list) and len(results) == 1:
            results = results[0]
        series = _mapping(results).get("series")
        if not isinstance(series, list) or len(series) != 1:
            raise SourceError("INVALID_SCHEMA")
        record = _mapping(series[0])
        if record.get("seriesID") != query.series_id:
            raise SourceError("CONTRADICTORY_SERIES")
        rows = record.get("data")
        if not isinstance(rows, list) or len(rows) > 130:
            raise SourceError("INVALID_SCHEMA")
        observed: list[Observation] = []
        for row in rows:
            item = _mapping(row)
            year, period = item.get("year"), item.get("period")
            if not isinstance(year, str) or not re.fullmatch(r"\d{4}", year):
                raise SourceError("INVALID_PERIOD")
            if not query.start.year <= int(year) <= query.end.year:
                raise SourceError("OBSERVATION_OUTSIDE_RANGE")
            if period == "M13":
                continue  # An annual average is not a thirteenth month.
            if not isinstance(period, str) or not re.fullmatch(
                r"M(0[1-9]|1[0-2])", period
            ):
                raise SourceError("UNSUPPORTED_BLS_FREQUENCY")
            try:
                period_start = date(int(year), int(period[1:]), 1)
            except ValueError:
                raise SourceError("INVALID_PERIOD") from None
            value = _number(item.get("value"))
            footnotes = item.get("footnotes")
            if not isinstance(footnotes, list):
                raise SourceError("INVALID_SCHEMA")
            codes = tuple(str(_mapping(note).get("code", "")) for note in footnotes)
            if not query.start <= period_start <= query.end:
                continue  # BLS query is year-granular; precise filter is declared.
            flags = [
                "PUBLICATION_UNKNOWN",
                "REVISION_TIME_UNKNOWN",
                "UNIT_CALLER_DECLARED",
            ]
            if value is None:
                flags.append("MISSING_VALUE")
            if "P" in codes:
                flags.append("PRELIMINARY")
            for code in dict.fromkeys(codes):
                if code and code != "P":
                    if not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", code):
                        raise SourceError("INVALID_FOOTNOTE_CODE")
                    flags.append("BLS_FOOTNOTE_" + code)
            observed.append(
                Observation(
                    self.catalogue_id,
                    query.series_id,
                    f"{year}-{period[1:]}",
                    period_start,
                    value,
                    query.unit,
                    retrieved_at,
                    quality_flags=tuple(flags),
                )
            )
        output = tuple(sorted(observed, key=lambda item: item.period_start))
        self.validate_batch(output, query)
        return output


class ECBConnector(_Connector):
    """One EXR daily currency/EUR reference series; no executable quote claim."""

    catalogue_id = "SRC-08"

    def validate_config(self, query: SourceQuery) -> None:
        if not re.fullmatch(r"D\.[A-Z]{3}\.EUR\.SP00\.A", query.series_id):
            raise SourceError("INVALID_ECB_SERIES")
        if query.series_id.split(".")[1] == "EUR":
            raise SourceError("INVALID_ECB_SERIES")
        if query.end - query.start > timedelta(days=366):
            raise SourceError("ECB_RANGE_EXCEEDS_366_DAYS")
        if query.unit != query.series_id.split(".")[1] + " per EUR":
            raise SourceError("ECB_UNIT_MISMATCH")

    def _request(self, query: SourceQuery) -> Request:
        return Request(
            "GET",
            "data-api.ecb.europa.eu",
            f"/service/data/EXR/{query.series_id}?startPeriod={query.start.isoformat()}"
            f"&endPeriod={query.end.isoformat()}&format=csvdata",
        )

    def normalize(
        self, raw: bytes, query: SourceQuery, retrieved_at: datetime
    ) -> tuple[Observation, ...]:
        self.validate_config(query)
        _timestamp(retrieved_at)
        reader = csv.DictReader(io.StringIO(_text(raw)))
        fields = reader.fieldnames or []
        required = {
            "KEY",
            "FREQ",
            "CURRENCY",
            "CURRENCY_DENOM",
            "EXR_TYPE",
            "EXR_SUFFIX",
            "TIME_PERIOD",
            "OBS_VALUE",
        }
        if not required.issubset(fields) or len(fields) != len(set(fields)):
            raise SourceError("INVALID_CSV_SCHEMA")
        observations: list[Observation] = []
        try:
            for row in reader:
                if (
                    len(observations) >= 367
                    or None in row
                    or any(value is None for value in row.values())
                ):
                    raise SourceError("INVALID_CSV_ROW")
                key = ".".join(
                    row[name]
                    for name in (
                        "FREQ",
                        "CURRENCY",
                        "CURRENCY_DENOM",
                        "EXR_TYPE",
                        "EXR_SUFFIX",
                    )
                )
                if key != query.series_id or row["KEY"] != "EXR." + key:
                    raise SourceError("CONTRADICTORY_SERIES")
                if "UNIT_MULT" in row and row["UNIT_MULT"] != "0":
                    raise SourceError("UNSUPPORTED_UNIT_MULTIPLIER")
                if "UNIT" in row and row["UNIT"] not in ("", row["CURRENCY"]):
                    raise SourceError("ECB_UNIT_MISMATCH")
                period = row["TIME_PERIOD"]
                if not re.fullmatch(r"\d{4}-\d\d-\d\d", period):
                    raise SourceError("INVALID_PERIOD")
                try:
                    period_start = date.fromisoformat(period)
                except ValueError:
                    raise SourceError("INVALID_PERIOD") from None
                value = _number(row["OBS_VALUE"])
                if value is not None and value <= 0:
                    raise SourceError("INVALID_REFERENCE_RATE")
                flags = [
                    "PUBLICATION_UNKNOWN",
                    "REVISION_TIME_UNKNOWN",
                    "NOT_EXECUTABLE",
                ]
                if "UNIT_MULT" not in row:
                    flags.append("UNIT_MULTIPLIER_NOT_PROVIDED")
                if "OBS_STATUS" in row:
                    status = row["OBS_STATUS"]
                    if status and not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", status):
                        raise SourceError("INVALID_OBSERVATION_STATUS")
                    flags.append(
                        "ECB_OBS_STATUS_" + status
                        if status
                        else "ECB_OBS_STATUS_UNKNOWN"
                    )
                if value is None:
                    flags.append("MISSING_VALUE")
                observations.append(
                    Observation(
                        self.catalogue_id,
                        query.series_id,
                        period,
                        period_start,
                        value,
                        query.unit,
                        retrieved_at,
                        price_nature="INDICATIVE_REFERENCE",
                        quality_flags=tuple(flags),
                    )
                )
        except csv.Error:
            raise SourceError("INVALID_CSV_SCHEMA") from None
        output = tuple(sorted(observations, key=lambda item: item.period_start))
        self.validate_batch(output, query)
        return output


def default_query(catalogue_id: str) -> SourceQuery:
    """Small fixed historical probes; never pretend they measure current freshness."""
    if catalogue_id == "SRC-04":
        return SourceQuery(
            "CES0000000001",
            date(2024, 1, 1),
            date(2024, 12, 31),
            "thousands of persons",
        )
    if catalogue_id == "SRC-08":
        return SourceQuery(
            "D.USD.EUR.SP00.A", date(2024, 1, 2), date(2024, 1, 5), "USD per EUR"
        )
    raise SourceError("CONNECTOR_NOT_IMPLEMENTED")
