"""Bounded sanitized BEA NIPA response imports; query-secret HTTP is disabled."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from quant_hunter.sources._equity_transport import json_object, mapping, text
from quant_hunter.sources.macro_common import (
    MacroBatch,
    MacroObservation,
    decimal_text,
    raw_page,
    reject_embedded_credentials,
    require_utc,
    safe_metadata,
    validate_macro_batch,
)
from quant_hunter.sources.transport import SourceError


@dataclass(frozen=True)
class BEANIPAQuery:
    table: str
    series_id: str
    unit: str
    unit_multiplier: int
    start: date
    end: date
    declared_vintage: date | None = None


class BEANIPAFileImporter:
    transport_status = "BLOCKED_EXTERNAL"
    transport_reason = "BEA documents GET with UserID in URL; no compatible header/body alternative verified"

    def validate_config(self, query: BEANIPAQuery) -> None:
        text(query.table, r"T[0-9]{5,7}", "INVALID_TABLE")
        text(query.series_id, r"[A-Za-z0-9_.-]{1,80}", "INVALID_SERIES_ID")
        safe_metadata(query.unit)
        if (
            type(query.unit_multiplier) is not int
            or not -12 <= query.unit_multiplier <= 12
            or type(query.start) is not date
            or type(query.end) is not date
            or query.start > query.end
            or (
                query.declared_vintage is not None
                and type(query.declared_vintage) is not date
            )
        ):
            raise SourceError("INVALID_BEA_QUERY")

    def import_bytes(
        self,
        raw: bytes,
        query: BEANIPAQuery,
        retrieved: datetime,
        *,
        evidence_mode: str = "OWNER_SUPPLIED",
    ) -> MacroBatch:
        if evidence_mode not in ("OWNER_SUPPLIED", "RECORDED_FIXTURE"):
            raise SourceError("INVALID_EVIDENCE_MODE")
        records = self.normalize(raw, query, retrieved)
        return MacroBatch(
            "SRC-05",
            records,
            (raw_page(raw, retrieved),),
            evidence_mode,
            limitations=(
                "Submitted sanitized export bytes are not the original unredacted HTTP response",
                "Owner-declared vintage is not authenticated historical availability",
                "Retain attribution, source rights and immutable governed capture separately",
            ),
        )

    def normalize(
        self, raw: bytes, query: BEANIPAQuery, retrieved: datetime
    ) -> tuple[MacroObservation, ...]:
        self.validate_config(query)
        require_utc(retrieved)
        if (
            query.declared_vintage is not None
            and query.declared_vintage > retrieved.date()
        ):
            raise SourceError("FUTURE_DECLARED_VINTAGE")
        payload = json_object(raw)
        reject_embedded_credentials(payload)
        root = mapping(payload.get("BEAAPI"))
        params = mapping(root.get("Request")).get("RequestParam")
        if not isinstance(params, list) or len(params) > 20:
            raise SourceError("BEA_REQUEST_METADATA_REQUIRED")
        request: dict[str, str] = {}
        for item in params:
            row = mapping(item)
            name = text(
                row.get("ParameterName"), r"[A-Za-z]{1,32}", "INVALID_REQUEST_PARAMETER"
            ).upper()
            parameter_value = safe_metadata(row.get("ParameterValue"), maximum=120)
            if name in request:
                raise SourceError("DUPLICATE_REQUEST_PARAMETER")
            if name == "USERID" and parameter_value != "[REDACTED]":
                raise SourceError("UNREDACTED_BEA_USERID_REFUSED")
            request[name] = parameter_value
        if (
            request.get("DATASETNAME", "").upper() != "NIPA"
            or request.get("METHOD", "").upper() != "GETDATA"
            or request.get("TABLENAME") != query.table
        ):
            raise SourceError("BEA_REQUEST_MISMATCH")
        results = root.get("Results")
        if isinstance(results, list) and len(results) == 1:
            results = results[0]
        result = mapping(results)
        if "Error" in result:
            raise SourceError("BEA_PROVIDER_REJECTED")
        rows = result.get("Data")
        if not isinstance(rows, list) or len(rows) > 5000:
            raise SourceError("BEA_DATA_SCHEMA")
        records: list[MacroObservation] = []
        for item in rows:
            row = mapping(item)
            if row.get("TableName") != query.table:
                raise SourceError("BEA_TABLE_MISMATCH")
            series_id = text(
                row.get("SeriesCode"), r"[A-Za-z0-9_.-]{1,80}", "INVALID_SERIES_ID"
            )
            period = text(
                row.get("TimePeriod"),
                r"[0-9]{4}(?:Q[1-4]|M(?:0?[1-9]|1[0-2]))?",
                "INVALID_BEA_PERIOD",
            )
            try:
                year = int(period[:4])
                month = (
                    (int(period[5:]) - 1) * 3 + 1
                    if "Q" in period
                    else int(period[5:])
                    if "M" in period
                    else 1
                )
                start = date(year, month, 1)
            except ValueError:
                raise SourceError("INVALID_BEA_PERIOD") from None
            unit = safe_metadata(row.get("CL_UNIT"))
            exponent = text(
                row.get("UNIT_MULT"), r"-?(?:[0-9]|1[0-2])", "INVALID_UNIT_MULTIPLIER"
            )
            value = decimal_text(row.get("DataValue"), commas=True)
            metric = safe_metadata(row.get("METRIC_NAME", row.get("Metric_Name")))
            if series_id == query.series_id:
                if unit != query.unit or int(exponent) != query.unit_multiplier:
                    raise SourceError("BEA_UNIT_MISMATCH")
                if query.start <= start <= query.end:
                    if start > retrieved.date():
                        raise SourceError("FUTURE_OBSERVATION")
                    flags: tuple[str, ...] = (
                        ("OWNER_VINTAGE_CLAIM_UNVERIFIED",)
                        if query.declared_vintage
                        else ("LATEST_EXPORT_NOT_HISTORICAL_VINTAGE",)
                    )
                    if value is None:
                        flags += ("MISSING_VALUE",)
                    records.append(
                        MacroObservation(
                            "SRC-05",
                            series_id,
                            period,
                            start,
                            value,
                            unit,
                            retrieved,
                            query.declared_vintage.isoformat()
                            if query.declared_vintage
                            else "LATEST_AT_EXPORT",
                            unit_multiplier=int(exponent),
                            metric=metric,
                            quality_flags=flags,
                        )
                    )
        if not records:
            raise SourceError("REQUESTED_SERIES_OR_PERIOD_NOT_FOUND")
        normalized = tuple(sorted(records, key=lambda record: record.period_start))
        self.validate_batch(normalized, query)
        return normalized

    def validate_batch(
        self, records: tuple[MacroObservation, ...], query: BEANIPAQuery
    ) -> None:
        validate_macro_batch(records, "SRC-05")
        if any(
            record.series_id != query.series_id
            or record.unit != query.unit
            or record.unit_multiplier != query.unit_multiplier
            for record in records
        ):
            raise SourceError("BEA_BATCH_MISMATCH")
