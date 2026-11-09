"""Bounded documented CSV exports of RTDSM and quarterly surveys, not event consensus."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from quant_hunter.sources import archive_files as f
from quant_hunter.sources.macro_common import MacroBatch, MacroObservation, raw_page
from quant_hunter.sources.priority_common import PriorityBatch
from quant_hunter.sources.transport import SourceError


@dataclass(frozen=True)
class RTDSMQuery:
    series_id: str
    start: date
    end: date
    export_vintage: date
    vintage_units: tuple[tuple[str, str], ...]
    year_window_start: int = 1965
    profile: str = "RTDSM_QUARTERLY_CSV_V1"


def _vintage(header: str, query: RTDSMQuery) -> date:
    match = re.fullmatch(
        re.escape(query.series_id) + r"([0-9]{2}|[0-9]{4})([QM])([0-9]{1,2})", header
    )
    if match is None:
        raise SourceError("RTDSM_VINTAGE_HEADER")
    year, frequency, part = int(match[1]), match[2], int(match[3])
    if len(match[1]) == 2:
        year += query.year_window_start // 100 * 100
        if year < query.year_window_start:
            year += 100
    if not query.year_window_start <= year < query.year_window_start + 100:
        raise SourceError("RTDSM_YEAR_WINDOW")
    if frequency == "Q":
        if not 1 <= part <= 4:
            raise SourceError("RTDSM_VINTAGE_QUARTER")
        part = (part - 1) * 3 + 2  # Documentation: middle month; no invented day/time.
    return f.month(f"{year:04d}-{part:02d}")


class RTDSMImporter:
    def import_bytes(
        self,
        raw: bytes,
        query: RTDSMQuery,
        retrieved: datetime,
        *,
        evidence_mode: str = "OWNER_SUPPLIED",
    ) -> MacroBatch:
        f.evidence(evidence_mode)
        f.context(query.start, query.end, retrieved, query.export_vintage)
        f.token(query.series_id, r"[A-Z][A-Z0-9]{0,15}", "RTDSM_SERIES")
        if (
            query.profile != "RTDSM_QUARTERLY_CSV_V1"
            or type(query.year_window_start) is not int
            or not 1900 <= query.year_window_start <= 2000
        ):
            raise SourceError("RTDSM_PROFILE_OR_YEAR_WINDOW")
        header, rows = f.csv_table(raw)
        if header[0] != "DATE" or len(header) < 2:
            raise SourceError("RTDSM_DATE_HEADER")
        units = dict(query.vintage_units)
        if len(units) != len(query.vintage_units) or set(units) != set(header[1:]):
            raise SourceError("RTDSM_EXACT_VINTAGE_UNITS_REQUIRED")
        for unit in units.values():
            f.metadata_text(unit)
        vintages = tuple(_vintage(value, query) for value in header[1:])
        if tuple(sorted(set(vintages))) != vintages or any(
            value > query.export_vintage for value in vintages
        ):
            raise SourceError("RTDSM_VINTAGE_ORDER_OR_FUTURE")
        records: list[MacroObservation] = []
        previous: date | None = None
        for row in rows:
            encoded = row[0]
            if re.fullmatch(r"[0-9]{4}:0[1-4]", encoded):
                encoded = encoded[:4] + "Q" + encoded[-1]
            period = f.quarter(encoded)
            if previous and period <= previous:
                raise SourceError("RTDSM_REFERENCE_ORDER")
            previous = period
            for name, vintage, cell in zip(header[1:], vintages, row[1:], strict=True):
                value = f.number(cell, missing=True)
                # Quarterly observed economic values cannot predate their period
                # end in this profile. Blank future cells are explicitly absent.
                quarter_end_month = period.month + 2
                if (period.year, quarter_end_month) >= (vintage.year, vintage.month):
                    if value is not None:
                        raise SourceError("RTDSM_VALUE_BEFORE_PERIOD_COMPLETION")
                    continue
                if query.start <= period <= query.end:
                    records.append(
                        MacroObservation(
                            "SRC-22",
                            query.series_id,
                            encoded,
                            period,
                            value,
                            units[name],
                            retrieved,
                            name,
                            metric="OBSERVED_LEVEL_AS_VINTAGE",
                            quality_flags=(
                                "OWNER_WORKSHEET_EXPORT_UNVERIFIED",
                                "VINTAGE_MONTH:" + vintage.strftime("%Y-%m"),
                                "MONTH_PRECISION_NOT_RELEASE_TIMESTAMP",
                                "HISTORICAL_AVAILABILITY_UNVERIFIED",
                            )
                            + (("MISSING_VALUE",) if value is None else ()),
                        )
                    )
                if len(records) > f.MAX_ROWS:
                    raise SourceError("RTDSM_NORMALIZED_ROW_BOUND")
        if not records:
            raise SourceError("RTDSM_SELECTED_RANGE_EMPTY")
        return MacroBatch(
            "SRC-22",
            tuple(records),
            (raw_page(raw, retrieved),),
            evidence_mode,
            normalization_version=query.profile,
            limitations=(
                "Quarterly observations only; each vintage and declared vintage-specific unit preserved",
                "Two-digit years use the explicit frozen 100-year window, not the system clock",
                "Month/quarter vintage precision never becomes observed publication/availability",
                "Exact submitted CSV export only; no XLSX execution, PIT or rights approval",
            ),
        )


@dataclass(frozen=True)
class SurveyQuery:
    profile: str
    variable: str
    unit: str
    start: date
    end: date
    export_vintage: date
    statistic: str
    survey_round: str | None = None


@dataclass(frozen=True)
class SurveyObservation:
    catalogue_id: str
    provider: str
    variable: str
    survey_round: str
    target_period: str
    target_start: date
    value: Decimal | None
    unit: str
    statistic: str
    forecaster_id: str | None
    export_vintage: date
    ingestion_time: datetime
    publication_time: None = None
    available_at: None = None
    point_in_time_eligible: bool = False
    event_consensus_eligible: bool = False
    quality_flags: tuple[str, ...] = (
        "OWNER_WORKSHEET_EXPORT_UNVERIFIED",
        "HISTORICAL_AVAILABILITY_UNVERIFIED",
        "QUARTERLY_SURVEY_NOT_EVENT_ANNOUNCEMENT_CONSENSUS",
    )


def _record(
    query: SurveyQuery,
    retrieved: datetime,
    provider: str,
    survey: str,
    target: str,
    start: date,
    value: Decimal | None,
    statistic: str,
    forecaster: str | None = None,
) -> SurveyObservation:
    return SurveyObservation(
        "SRC-22",
        provider,
        query.variable,
        survey,
        target,
        start,
        value,
        query.unit,
        statistic,
        forecaster,
        query.export_vintage,
        retrieved,
        quality_flags=(
            "OWNER_WORKSHEET_EXPORT_UNVERIFIED",
            "HISTORICAL_AVAILABILITY_UNVERIFIED",
            "QUARTERLY_SURVEY_NOT_EVENT_ANNOUNCEMENT_CONSENSUS",
        )
        + (("MISSING_VALUE",) if value is None else ()),
    )


class SurveyFileImporter:
    def import_bytes(
        self,
        raw: bytes,
        query: SurveyQuery,
        retrieved: datetime,
        *,
        evidence_mode: str = "OWNER_SUPPLIED",
    ) -> PriorityBatch[SurveyObservation]:
        f.evidence(evidence_mode)
        f.context(query.start, query.end, retrieved, query.export_vintage)
        f.metadata_text(query.unit)
        header, rows = f.csv_table(raw)
        if query.profile == "PHILADELPHIA_SPF_QUARTERLY_CSV_V1":
            records = self._philadelphia(header, rows, query, retrieved)
        elif query.profile == "ECB_SPF_POINT_CSV_V1":
            records = self._ecb(header, rows, query, retrieved)
        else:
            raise SourceError("SURVEY_PROFILE_UNSUPPORTED")
        if not records:
            raise SourceError("SURVEY_SELECTED_RANGE_EMPTY")
        return PriorityBatch(
            "SRC-22",
            records,
            (raw_page(raw, retrieved),),
            evidence_mode,
            limitations=(
                "Fixed profile and exact submitted CSV bytes; export transformation is owner-declared",
                "Forecast target period and survey round are separate from publication and retrieval",
                "No probability, event consensus, source/rights, coverage or PIT approval",
            ),
        )

    def _philadelphia(
        self,
        header: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
        query: SurveyQuery,
        retrieved: datetime,
    ) -> tuple[SurveyObservation, ...]:
        if (
            query.variable
            not in {"NGDP", "RGDP", "UNEMP", "EMP", "INDPROD", "TBILL", "TBOND"}
            or query.statistic not in {"MEDIAN", "MEAN"}
            or query.survey_round is not None
        ):
            raise SourceError("PHILADELPHIA_SERIES_OR_STATISTIC")
        units = {
            "NGDP": "BILLIONS_USD_SAAR",
            "RGDP": "BILLIONS_REAL_USD_SAAR_BASE_VARIES",
            "UNEMP": "PERCENT_LABOUR_FORCE",
            "EMP": "THOUSANDS_OF_JOBS",
            "INDPROD": "INDEX_BASE_VARIES",
            "TBILL": "PERCENT_PER_ANNUM",
            "TBOND": "PERCENT_PER_ANNUM",
        }
        if query.unit != units[query.variable]:
            raise SourceError("PHILADELPHIA_UNIT")
        expected = ("YEAR", "QUARTER", *(query.variable + str(i) for i in range(1, 7)))
        if header != expected:
            raise SourceError("PHILADELPHIA_QUARTERLY_HEADER")
        result: list[SurveyObservation] = []
        previous: date | None = None
        for row in rows:
            f.token(row[0], r"[0-9]{4}", "SURVEY_YEAR")
            f.token(row[1], r"[1-4]", "SURVEY_QUARTER")
            survey = row[0] + "Q" + row[1]
            period = f.quarter(survey)
            if period > query.export_vintage or (previous and period <= previous):
                raise SourceError("SURVEY_ROUND_ORDER_OR_FUTURE")
            previous = period
            for i, cell in enumerate(row[2:]):
                value = f.number(cell, missing=True)
                if (
                    value is not None
                    and query.variable in {"NGDP", "RGDP", "EMP", "INDPROD"}
                    and value <= 0
                ):
                    raise SourceError("SURVEY_LEVEL_NONPOSITIVE")
                if (
                    value is not None
                    and query.variable == "UNEMP"
                    and not 0 <= value <= 100
                ):
                    raise SourceError("SURVEY_UNEMPLOYMENT_RANGE")
                ordinal = period.year * 4 + (period.month - 1) // 3 + i - 1
                target = f"{ordinal // 4:04d}Q{ordinal % 4 + 1}"
                target_start = f.quarter(target)
                if query.start <= period <= query.end:
                    result.append(
                        _record(
                            query,
                            retrieved,
                            "PHILADELPHIA_SPF",
                            survey,
                            target,
                            target_start,
                            value,
                            "HISTORICAL_VALUE_REPORTED" if i == 0 else query.statistic,
                        )
                    )
                if len(result) > f.MAX_ROWS:
                    raise SourceError("SURVEY_NORMALIZED_ROW_BOUND")
        return tuple(result)

    def _ecb(
        self,
        header: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
        query: SurveyQuery,
        retrieved: datetime,
    ) -> tuple[SurveyObservation, ...]:
        if (
            query.variable not in {"HICP", "HICPX", "RGDP", "UNEM"}
            or query.statistic != "INDIVIDUAL_POINT"
            or query.survey_round is None
        ):
            raise SourceError("ECB_SPF_VARIABLE_OR_STATISTIC")
        period = f.quarter(query.survey_round)
        if not query.start <= period <= query.end or period > query.export_vintage:
            raise SourceError("ECB_SPF_ROUND_RANGE")
        expected_unit = (
            "PERCENT_LABOUR_FORCE" if query.variable == "UNEM" else "PERCENT_YOY"
        )
        if query.unit != expected_unit or header != (
            "TARGET_PERIOD",
            "FCT_SOURCE",
            "POINT",
        ):
            raise SourceError("ECB_SPF_UNIT_OR_HEADER")
        result: list[SurveyObservation] = []
        seen: set[tuple[str, str]] = set()
        months = (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        )
        for row in rows:
            target, forecaster, cell = row
            if re.fullmatch(r"[0-9]{4}", target):
                start = f.day(target + "-01-01")
            elif re.fullmatch(r"[0-9]{4}Q[1-4]", target):
                if query.variable != "RGDP":
                    raise SourceError("ECB_SPF_TARGET_GRANULARITY")
                start = f.quarter(target)
            elif len(target) == 7 and target[4:] in months:
                if query.variable == "RGDP":
                    raise SourceError("ECB_SPF_TARGET_GRANULARITY")
                start = f.month(f"{target[:4]}-{months.index(target[4:]) + 1:02d}")
            else:
                raise SourceError("ECB_SPF_TARGET")
            f.token(forecaster, r"[1-9][0-9]{0,3}", "ECB_SPF_FORECASTER")
            if (
                not period.year <= start.year <= period.year + 6
                or (target, forecaster) in seen
            ):
                raise SourceError("ECB_SPF_TARGET_OR_DUPLICATE")
            seen.add((target, forecaster))
            value = f.number(cell, missing=True)
            if value is not None and query.variable == "UNEM" and not 0 <= value <= 100:
                raise SourceError("SURVEY_UNEMPLOYMENT_RANGE")
            result.append(
                _record(
                    query,
                    retrieved,
                    "ECB_SPF",
                    query.survey_round,
                    target,
                    start,
                    value,
                    query.statistic,
                    forecaster,
                )
            )
        return tuple(result)
