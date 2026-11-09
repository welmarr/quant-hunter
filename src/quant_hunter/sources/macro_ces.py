"""CES bounded worksheet-export reader; vintage label is not a release timestamp."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from quant_hunter.sources import archive_files as f
from quant_hunter.sources.macro_common import MacroBatch, MacroObservation, raw_page
from quant_hunter.sources.transport import SourceError


@dataclass(frozen=True)
class CESArchiveQuery:
    series_id: str
    start: date
    end: date
    export_vintage: date
    profile: str = "QH_CES_RELEASE_MATRIX_CSV_V1"


class CESArchiveImporter:
    """Read declared employment levels in thousands, never latest-as-first release."""

    def import_bytes(
        self,
        raw: bytes,
        query: CESArchiveQuery,
        retrieved: datetime,
        *,
        evidence_mode: str = "OWNER_SUPPLIED",
    ) -> MacroBatch:
        f.evidence(evidence_mode)
        f.context(query.start, query.end, retrieved, query.export_vintage)
        f.token(query.series_id, r"CE[SU][0-9]{8}01", "CES_EMPLOYMENT_SERIES_REQUIRED")
        if query.profile != "QH_CES_RELEASE_MATRIX_CSV_V1":
            raise SourceError("CES_PROFILE_UNSUPPORTED")
        header, rows = f.csv_table(raw)
        if header[0] != "vintage_reference_month" or len(header) < 2:
            raise SourceError("CES_MATRIX_HEADER")
        periods = tuple(f.month(value) for value in header[1:])
        if tuple(sorted(set(periods))) != periods:
            raise SourceError("CES_REFERENCE_ORDER")
        records: list[MacroObservation] = []
        previous: date | None = None
        for row in rows:
            vintage = f.month(row[0])
            if vintage > query.export_vintage or (previous and vintage <= previous):
                raise SourceError("CES_VINTAGE_ORDER_OR_FUTURE")
            previous = vintage
            for period, cell in zip(periods, row[1:], strict=True):
                value = f.number(cell, missing=True)
                if period > vintage:
                    if value is not None:
                        raise SourceError("CES_VALUE_AFTER_VINTAGE")
                    continue  # Explicit triangular unavailable cell, not imputation.
                if value is not None and value < 0:
                    raise SourceError("CES_EMPLOYMENT_NEGATIVE")
                if query.start <= period <= query.end:
                    records.append(
                        MacroObservation(
                            "SRC-04",
                            query.series_id,
                            period.strftime("%Y-%m"),
                            period,
                            value,
                            "Thousands of payroll jobs",
                            retrieved,
                            "CES_REFERENCE_MONTH:" + row[0],
                            metric="EMPLOYMENT_LEVEL",
                            quality_flags=(
                                "OWNER_WORKSHEET_EXPORT_UNVERIFIED",
                                "VINTAGE_REFERENCE_MONTH_NOT_PUBLICATION_TIME",
                                "FIRST_RELEASE_STATUS_NOT_INFERRED",
                                "HISTORICAL_AVAILABILITY_UNVERIFIED",
                            )
                            + (("MISSING_VALUE",) if value is None else ()),
                        )
                    )
                if len(records) > f.MAX_ROWS:
                    raise SourceError("CES_NORMALIZED_ROW_BOUND")
        if not records:
            raise SourceError("CES_SELECTED_RANGE_EMPTY")
        return MacroBatch(
            "SRC-04",
            tuple(records),
            (raw_page(raw, retrieved),),
            evidence_mode,
            normalization_version=query.profile,
            limitations=(
                "Exact submitted CSV bytes retained; native XLSX/ZIP is not decoded",
                "Owner must export explicit reference-month matrix; transformation and rights unverified",
                "CES vintage reference month is not the publication or observed availability date",
                "Revisions remain separate; no first-release, PIT, coverage or source approval",
            ),
        )
