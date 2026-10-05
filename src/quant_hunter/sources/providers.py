"""Concrete provider operations, bounded to explicit diagnostics or owner exports."""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from typing import cast

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.sources.equity_probes import diagnostic_json
from quant_hunter.sources.macro_bea import BEANIPAFileImporter, BEANIPAQuery
from quant_hunter.sources.macro_common import MacroBatch
from quant_hunter.sources.macro_fred import (
    ALFREDFileImporter,
    ALFREDImportQuery,
    FREDReleaseConnector,
    FREDReleaseQuery,
)
from quant_hunter.sources.macro_g17 import G17Connector, G17Query
from quant_hunter.sources.materialize import DiagnosticBatch, DiagnosticMaterializer
from quant_hunter.sources.priority_common import PriorityBatch
from quant_hunter.sources.priority_dukascopy import (
    DukascopyDailyImporter,
    DukascopyQuery,
    DukascopyTick,
)
from quant_hunter.sources.priority_eodhd import EODHDFileImporter, EODQuery, EODRecord
from quant_hunter.sources.priority_sharadar import (
    SF1Query,
    SF1Record,
    SharadarConnector,
)
from quant_hunter.sources.priority_tradingeconomics import (
    CalendarEvent,
    CalendarQuery,
    TradingEconomicsConnector,
)
from quant_hunter.sources.probes import SourceProbeService
from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, SourceError
from quant_hunter.storage.raw import Compression

type ProviderConnector = (
    G17Connector | FREDReleaseConnector | SharadarConnector | TradingEconomicsConnector
)
type ProviderBatch = (
    MacroBatch
    | PriorityBatch[SF1Record]
    | PriorityBatch[CalendarEvent]
    | PriorityBatch[DukascopyTick]
    | PriorityBatch[EODRecord]
)


def _preview(value: object) -> JsonValue:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SourceError("NONFINITE_PREVIEW")
        # BI5 volumes originate as float32; retain their decoded value as text.
        return str(value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise SourceError("INVALID_PREVIEW_KEYS")
        return {key: _preview(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_preview(item) for item in value]
    return diagnostic_json(value)


def project_batch(batch: ProviderBatch, *, bi5: bool = False) -> DiagnosticBatch:
    rows = batch.observations if isinstance(batch, MacroBatch) else batch.records
    return DiagnosticBatch(
        batch.catalogue_id,
        batch.raw_pages,
        len(rows),
        tuple(cast(JsonRecord, _preview(asdict(row))) for row in rows[:10]),
        batch.evidence_mode,
        batch.normalization_version
        if isinstance(batch, MacroBatch)
        else "v0-priority-1",
        batch.limitations,
        "application/octet-stream"
        if bi5
        else "text/plain"
        if batch.catalogue_id == "SRC-06"
        else "application/json",
        Compression.OTHER if bi5 else Compression.NONE,
    )


def _date(value: JsonValue) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise SourceError("INVALID_DATE")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise SourceError("INVALID_DATE") from None


def _text(value: JsonValue) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 200:
        raise SourceError("INVALID_IMPORT_METADATA")
    return value.strip()


class ProviderService:
    """No arbitrary endpoints, hidden retries, paid acquisition or PIT approval."""

    def __init__(self, public: SourceProbeService) -> None:
        self.materializer = DiagnosticMaterializer(public)

    def probe(
        self, catalogue_id: str, connector: ProviderConnector | None = None
    ) -> JsonRecord:
        if connector is None:
            if catalogue_id != "SRC-06":
                raise SourceError("PROVIDER_CONFIGURATION_REQUIRED")
            connector = G17Connector()
        if connector.catalogue_id != catalogue_id:
            raise SourceError("CONNECTOR_ID_MISMATCH")
        start, end = datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)
        config: JsonRecord = {
            "catalogue_id": catalogue_id,
            "purpose": "bounded explicit connection diagnostic",
            "maximum_pages": 1,
        }
        if isinstance(connector, G17Connector):
            query_g17 = G17Query(date(2025, 1, 17))
            config.update(release_date="2025-01-17", expected_base_year=2017)
            endpoint = "https://www.federalreserve.gov/releases/g17/20250117/g17.txt"

            def fetch() -> DiagnosticBatch:
                return project_batch(connector.test_connection(query_g17))
        elif isinstance(connector, FREDReleaseConnector):
            config.update(
                release_id=10,
                page_size=100,
                completeness="Required; pagination-bound exhaustion fails",
            )
            endpoint = "https://api.stlouisfed.org/fred/v2/release/observations"
            # This release endpoint has no time filter: envelope is only the
            # explicitly declared diagnostic scope, never certified coverage.
            start = datetime(1900, 1, 1, tzinfo=UTC)
            end = datetime.now(UTC)

            def fetch() -> DiagnosticBatch:
                return project_batch(
                    connector.test_connection(FREDReleaseQuery(10, 100, 1))
                )
        elif isinstance(connector, SharadarConnector):
            config.update(
                ticker="AAPL", dimension="ARQ", start="2024-01-01", end="2024-12-31"
            )
            endpoint = "https://data.nasdaq.com/api/v3/datatables/SHARADAR/SF1.json"

            def fetch() -> DiagnosticBatch:
                return project_batch(
                    connector.test_connection(
                        SF1Query("AAPL", "ARQ", start.date(), date(2024, 12, 31), 1)
                    )
                )
        else:
            config.update(country="united states", start="2024-01-02", end="2024-01-03")
            start, end = (
                datetime(2024, 1, 2, tzinfo=UTC),
                datetime(2024, 1, 4, tzinfo=UTC),
            )
            endpoint = "https://api.tradingeconomics.com/calendar/country/united%20states/2024-01-02/2024-01-03"

            def fetch() -> DiagnosticBatch:
                return project_batch(
                    connector.test_connection(
                        CalendarQuery("united states", start.date(), date(2024, 1, 3))
                    )
                )

        return self.materializer.run(
            catalogue_id,
            configuration=config,
            start=start,
            end=end,
            endpoint=endpoint,
            evidence_mode=connector.evidence_mode,
            fetch=fetch,
        )

    def import_file(
        self,
        catalogue_id: str,
        payload: bytes,
        metadata: JsonRecord,
        *,
        series_metadata: bytes | None = None,
    ) -> JsonRecord:
        if (
            not isinstance(payload, bytes)
            or not 0 < len(payload) + len(series_metadata or b"") <= MAX_RESPONSE_BYTES
        ):
            raise SourceError("IMPORT_TOTAL_SIZE_BOUND")
        if metadata.get("license_confirmed") is not True:
            raise SourceError("SOURCE_RIGHTS_DECLARATION_REQUIRED")
        _text(metadata.get("declared_license"))
        common = {"declared_license", "license_confirmed"}
        retrieved = datetime.now(UTC)
        if catalogue_id == "SRC-05":
            if set(metadata) != common | {
                "table",
                "series_id",
                "unit",
                "unit_multiplier",
                "start",
                "end",
                "vintage",
            }:
                raise SourceError("INVALID_IMPORT_METADATA")
            if type(metadata["unit_multiplier"]) is not int:
                raise SourceError("INVALID_UNIT_MULTIPLIER")
            start, end = _date(metadata["start"]), _date(metadata["end"])
            bea = BEANIPAQuery(
                _text(metadata["table"]),
                _text(metadata["series_id"]),
                _text(metadata["unit"]),
                metadata["unit_multiplier"],
                start,
                end,
                _date(metadata["vintage"]) if metadata["vintage"] is not None else None,
            )

            def fetch() -> DiagnosticBatch:
                return project_batch(
                    BEANIPAFileImporter().import_bytes(payload, bea, retrieved)
                )
        elif catalogue_id == "SRC-07":
            if (
                set(metadata)
                != common
                | {
                    "series_id",
                    "unit",
                    "start",
                    "end",
                    "realtime_start",
                    "realtime_end",
                }
                or series_metadata is None
            ):
                raise SourceError("ALFRED_SERIES_METADATA_REQUIRED")
            start, end = _date(metadata["start"]), _date(metadata["end"])
            alfred = ALFREDImportQuery(
                _text(metadata["series_id"]),
                _text(metadata["unit"]),
                _date(metadata["realtime_start"]),
                _date(metadata["realtime_end"]),
                start,
                end,
            )

            def fetch() -> DiagnosticBatch:
                return project_batch(
                    ALFREDFileImporter().import_bytes(
                        payload, series_metadata, alfred, retrieved
                    )
                )
        elif catalogue_id == "SRC-09":
            if (
                set(metadata) != common | {"pair", "day", "point_scale"}
                or type(metadata["point_scale"]) is not int
            ):
                raise SourceError("INVALID_IMPORT_METADATA")
            start = end = _date(metadata["day"])
            duka = DukascopyQuery(
                _text(metadata["pair"]), start, metadata["point_scale"]
            )

            def fetch() -> DiagnosticBatch:
                return project_batch(
                    DukascopyDailyImporter().import_bytes(payload, duka, retrieved),
                    bi5=True,
                )
        elif catalogue_id == "SRC-19":
            if set(metadata) != common | {
                "symbol",
                "currency",
                "start",
                "end",
                "listing_status",
            }:
                raise SourceError("INVALID_IMPORT_METADATA")
            start, end = _date(metadata["start"]), _date(metadata["end"])
            eod = EODQuery(
                _text(metadata["symbol"]),
                _text(metadata["currency"]),
                start,
                end,
                _text(metadata["listing_status"]),
            )

            def fetch() -> DiagnosticBatch:
                return project_batch(
                    EODHDFileImporter().import_bytes(payload, eod, retrieved)
                )
        else:
            raise SourceError("SOURCE_FILE_IMPORT_NOT_IMPLEMENTED")
        if catalogue_id != "SRC-07" and series_metadata is not None:
            raise SourceError("UNEXPECTED_SUPPLEMENTARY_FILE")
        if end == date.max:
            raise SourceError("INVALID_DIAGNOSTIC_ENVELOPE")
        return self.materializer.run(
            catalogue_id,
            configuration={"catalogue_id": catalogue_id, **metadata},
            start=datetime.combine(start, time(), UTC),
            end=datetime.combine(end + timedelta(days=1), time(), UTC),
            endpoint=f"upload://local/{catalogue_id}",
            evidence_mode="OWNER_SUPPLIED",
            fetch=fetch,
        )
