"""Dated G17 ASCII summary: six monthly total-IP levels, not a full history."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from quant_hunter.sources._equity_transport import calendar_date
from quant_hunter.sources.connectors import Health
from quant_hunter.sources.macro_common import (
    MacroBatch,
    MacroObservation,
    decimal_text,
    raw_page,
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

_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        1,
    )
}
_SHORT = {name[:3]: number for name, number in _MONTHS.items()}


@dataclass(frozen=True)
class G17Query:
    release_date: date
    expected_base_year: int = 2017


class G17Connector:
    catalogue_id = "SRC-06"
    version = "v0-g17-1"

    def __init__(self, transport: MacroTransport | None = None) -> None:
        self._transport = transport or MacroHTTPS()
        self.evidence_mode = (
            "RECORDED_FIXTURE" if transport is not None else "HISTORICAL_REAL"
        )
        self._health = Health("UNTESTED")
        self.last_batch: MacroBatch | None = None
        self.last_raw: bytes | None = None

    def health(self) -> Health:
        return self._health

    def list_capabilities(self) -> tuple[str, ...]:
        return (
            "DATED_G17_ASCII",
            "SIX_MONTH_TOTAL_IP_LEVELS",
            "STATED_RELEASE_TIME",
            "NO_CURRENT_SERIES_SUBSTITUTION",
        )

    def validate_config(self, query: G17Query) -> None:
        if (
            type(query.release_date) is not date
            or not date(1997, 12, 1) <= query.release_date <= date(2100, 1, 1)
            or type(query.expected_base_year) is not int
            or not 1900 <= query.expected_base_year <= 2099
        ):
            raise SourceError("INVALID_G17_QUERY")

    def fetch_range(self, query: G17Query) -> MacroBatch:
        self.validate_config(query)
        self.last_batch = None
        self.last_raw = None
        try:
            response = self._transport.send(
                MacroRequest(
                    "www.federalreserve.gov",
                    f"/releases/g17/{query.release_date:%Y%m%d}/g17.txt",
                )
            )
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise SourceError("RESPONSE_TOO_LARGE")
            self.last_raw = response.body
            raw = checked_body(
                Response(response.status, response.body, response.retry_after)
            )
            retrieved = datetime.now(UTC)
            observations = self.normalize(raw, query, retrieved)
            result = MacroBatch(
                self.catalogue_id,
                observations,
                (raw_page(raw, retrieved),),
                self.evidence_mode,
            )
        except TimeoutError:
            self._health = Health("FAILED", datetime.now(UTC), "TIMEOUT")
            raise SourceError("TIMEOUT") from None
        except OSError:
            self._health = Health("FAILED", datetime.now(UTC), "NETWORK_FAILURE")
            raise SourceError("NETWORK_FAILURE") from None
        except SourceError as error:
            self._health = Health("FAILED", datetime.now(UTC), error.code)
            raise
        self.last_batch = result
        self._health = Health("SUCCEEDED", retrieved)
        return result

    def test_connection(self, query: G17Query) -> MacroBatch:
        return self.fetch_range(query)

    def normalize(
        self, raw: bytes, query: G17Query, retrieved: datetime
    ) -> tuple[MacroObservation, ...]:
        self.validate_config(query)
        raw_page(raw, retrieved)
        try:
            document = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise SourceError("INVALID_G17_ENCODING") from None
        header = re.search(
            r"G\.17[^\n]*For release at ([0-9]{1,2}):([0-9]{2}) (a\.m\.|p\.m\.) \(([A-Z]{2,4})\)\s*\n\s*([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})",
            document[:600],
        )
        if header is None or not document.lstrip().startswith(
            "FEDERAL RESERVE STATISTICAL RELEASE"
        ):
            raise SourceError("G17_RELEASE_HEADER_REQUIRED")
        try:
            release_date = date(int(header[7]), _MONTHS[header[5]], int(header[6]))
            hour, minute = int(header[1]), int(header[2])
            if not 1 <= hour <= 12 or not 0 <= minute <= 59:
                raise ValueError
        except KeyError, ValueError:
            raise SourceError("INVALID_RELEASE_DATE_TIME") from None
        if release_date != query.release_date:
            raise SourceError("RELEASE_DATE_MISMATCH")
        if release_date > retrieved.date():
            raise SourceError("FUTURE_RELEASE_REFUSED")
        publication: datetime | None = None
        if header[4] in ("EST", "EDT"):
            offset = -5 if header[4] == "EST" else -4
            publication = datetime(
                release_date.year,
                release_date.month,
                release_date.day,
                hour % 12 + (12 if header[3] == "p.m." else 0),
                minute,
                tzinfo=timezone(timedelta(hours=offset)),
            ).astimezone(UTC)
            if publication > retrieved:
                raise SourceError("FUTURE_RELEASE_REFUSED")
        elif header[4] != "ET":
            raise SourceError("UNSUPPORTED_PUBLICATION_ZONE")
        marker = "Industrial Production and Capacity Utilization:  Summary"
        if document.count(marker) != 1:
            raise SourceError("G17_SUMMARY_REQUIRED")
        summary = document.split(marker, 1)[1].split("Table 1", 1)[0]
        lines = summary.splitlines()
        if "Seasonally adjusted" not in summary:
            raise SourceError("UNSUPPORTED_SEASONAL_ADJUSTMENT")
        unit_rows = [line for line in lines if "=100" in line and "|" in line]
        if (
            len(unit_rows) != 1
            or unit_rows[0].split("|")[1].strip() != f"{query.expected_base_year}=100"
        ):
            raise SourceError("G17_UNIT_MISMATCH")
        month_rows = [
            i
            for i, line in enumerate(lines)
            if line.strip().startswith("Industrial production") and "|" in line
        ]
        if len(month_rows) != 1:
            raise SourceError("G17_MONTH_HEADER_REQUIRED")
        index = month_rows[0]
        if index == 0 or "|" not in lines[index - 1]:
            raise SourceError("G17_YEAR_HEADER_REQUIRED")
        month_text = lines[index].split("|")[1]
        months = re.findall(r"([A-Z][a-z]+)\.?\[([rp])\]", month_text)
        if (
            len(months) != 6
            or re.sub(r"([A-Z][a-z]+)\.?\[([rp])\]", "", month_text).strip()
        ):
            raise SourceError("UNSUPPORTED_MONTH_HEADER")
        years = re.findall(r"[0-9]{4}", lines[index - 1].split("|")[1])
        if not 1 <= len(years) <= 2:
            raise SourceError("G17_YEAR_HEADER_REQUIRED")
        total_rows = [
            line
            for line in lines
            if line.strip().startswith("Total index") and "|" in line
        ]
        if len(total_rows) != 1:
            raise SourceError("G17_TOTAL_INDEX_REQUIRED")
        values = total_rows[0].split("|")[1].split()
        if len(values) != 6:
            raise SourceError("G17_VALUE_COUNT")
        records: list[MacroObservation] = []
        year, previous = int(years[0]), None
        observed_years: list[int] = []
        for (month_name, qualifier), value in zip(months, values, strict=True):
            if month_name[:3] not in _SHORT:
                raise SourceError("INVALID_MONTH")
            month = _SHORT[month_name[:3]]
            if previous is not None:
                if month != previous % 12 + 1:
                    raise SourceError("G17_MONTH_SEQUENCE")
                if month == 1:
                    year += 1
            period = calendar_date(f"{year:04d}-{month:02d}-01")
            if period >= release_date.replace(day=1):
                raise SourceError("OBSERVATION_AFTER_RELEASE")
            previous = month
            if year not in observed_years:
                observed_years.append(year)
            numeric = decimal_text(value)
            if numeric is None or numeric <= 0:
                raise SourceError("INVALID_INDEX_LEVEL")
            flags = (
                "REVISED" if qualifier == "r" else "PRELIMINARY",
                "STATED_RELEASE_TIME_NOT_OBSERVED_DISSEMINATION"
                if publication
                else "PUBLICATION_TIME_UNKNOWN_AMBIGUOUS_ET",
            )
            records.append(
                MacroObservation(
                    self.catalogue_id,
                    "G17_TOTAL_IP_SA",
                    f"{year}-{month:02d}",
                    period,
                    numeric,
                    f"Index {query.expected_base_year}=100",
                    retrieved,
                    release_date.isoformat(),
                    publication_time=publication,
                    quality_flags=flags,
                )
            )
        if observed_years != [int(value) for value in years]:
            raise SourceError("G17_YEAR_SEQUENCE")
        result = tuple(records)
        self.validate_batch(result, query)
        return result

    def validate_batch(
        self, records: tuple[MacroObservation, ...], query: G17Query
    ) -> None:
        validate_macro_batch(records, self.catalogue_id)
        if len(records) != 6 or any(
            record.series_id != "G17_TOTAL_IP_SA"
            or record.vintage != query.release_date.isoformat()
            or record.unit != f"Index {query.expected_base_year}=100"
            for record in records
        ):
            raise SourceError("G17_BATCH_MISMATCH")
