"""Closed provider-file dispatch through the existing immutable diagnostic authority."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, time, timedelta
from typing import cast

from quant_hunter.config import JsonRecord
from quant_hunter.sources import archive_files as f
from quant_hunter.sources.equity_probes import diagnostic_json
from quant_hunter.sources.fx_forwards import ForwardFileImporter, ForwardQuery
from quant_hunter.sources.macro_ces import CESArchiveImporter, CESArchiveQuery
from quant_hunter.sources.macro_common import MacroBatch
from quant_hunter.sources.macro_surveys import (
    RTDSMImporter,
    RTDSMQuery,
    SurveyFileImporter,
    SurveyQuery,
)
from quant_hunter.sources.materialize import DiagnosticBatch, DiagnosticMaterializer
from quant_hunter.sources.transport import SourceError


def import_archive(
    materializer: DiagnosticMaterializer,
    catalogue_id: str,
    raw: bytes,
    metadata: JsonRecord,
) -> JsonRecord:
    """Rights/owner/quota checked by existing ProviderService/DataAccess caller."""
    common = {
        "profile",
        "declared_license",
        "license_confirmed",
        "start",
        "end",
        "export_vintage",
    }
    profile = f.token(metadata.get("profile"), r"[A-Z0-9_]{1,60}", "ARCHIVE_PROFILE")
    start, end, vintage = (
        f.day(metadata.get(key)) for key in ("start", "end", "export_vintage")
    )
    retrieved = datetime.now(UTC)
    f.context(start, end, retrieved, vintage)

    def project(batch: object) -> DiagnosticBatch:
        # Every branch below supplies one of the actual fixed parser dataclasses.
        from quant_hunter.sources.priority_common import PriorityBatch

        if isinstance(batch, MacroBatch):
            rows = batch.observations
        elif isinstance(batch, PriorityBatch):
            rows = batch.records
        else:
            raise SourceError("ARCHIVE_BATCH_TYPE")
        return DiagnosticBatch(
            catalogue_id,
            batch.raw_pages,
            len(rows),
            tuple(cast(JsonRecord, diagnostic_json(asdict(row))) for row in rows[:10]),
            batch.evidence_mode,
            profile,
            batch.limitations,
            "text/csv",
        )

    if catalogue_id == "SRC-04":
        if set(metadata) != common | {"series_id"}:
            raise SourceError("INVALID_ARCHIVE_METADATA")
        ces = CESArchiveQuery(
            f.metadata_text(metadata["series_id"]), start, end, vintage, profile
        )

        def fetch() -> DiagnosticBatch:
            return project(CESArchiveImporter().import_bytes(raw, ces, retrieved))
    elif catalogue_id == "SRC-21":
        if set(metadata) != common | {
            "base_currency",
            "quote_currency",
            "source_label",
        }:
            raise SourceError("INVALID_ARCHIVE_METADATA")
        forward = ForwardQuery(
            f.metadata_text(metadata["base_currency"]),
            f.metadata_text(metadata["quote_currency"]),
            f.metadata_text(metadata["source_label"]),
            start,
            end,
            vintage,
            profile,
        )

        def fetch() -> DiagnosticBatch:
            return project(ForwardFileImporter().import_bytes(raw, forward, retrieved))
    elif catalogue_id == "SRC-22" and profile == "RTDSM_QUARTERLY_CSV_V1":
        if set(metadata) != common | {
            "series_id",
            "vintage_units",
            "year_window_start",
        }:
            raise SourceError("INVALID_ARCHIVE_METADATA")
        units = metadata["vintage_units"]
        if (
            not isinstance(units, dict)
            or not 1 <= len(units) < f.MAX_COLUMNS
            or type(metadata["year_window_start"]) is not int
        ):
            raise SourceError("INVALID_RTDSM_VINTAGE_UNITS")
        rtdsm = RTDSMQuery(
            f.metadata_text(metadata["series_id"]),
            start,
            end,
            vintage,
            tuple((key, f.metadata_text(value)) for key, value in units.items()),
            metadata["year_window_start"],
            profile,
        )

        def fetch() -> DiagnosticBatch:
            return project(RTDSMImporter().import_bytes(raw, rtdsm, retrieved))
    elif catalogue_id == "SRC-22":
        if set(metadata) != common | {"variable", "unit", "statistic", "survey_round"}:
            raise SourceError("INVALID_ARCHIVE_METADATA")
        survey = SurveyQuery(
            profile,
            f.metadata_text(metadata["variable"]),
            f.metadata_text(metadata["unit"]),
            start,
            end,
            vintage,
            f.metadata_text(metadata["statistic"]),
            f.metadata_text(metadata["survey_round"])
            if metadata["survey_round"] is not None
            else None,
        )

        def fetch() -> DiagnosticBatch:
            return project(SurveyFileImporter().import_bytes(raw, survey, retrieved))
    else:
        raise SourceError("ARCHIVE_SOURCE_UNSUPPORTED")
    return materializer.run(
        catalogue_id,
        configuration={"catalogue_id": catalogue_id, **metadata},
        start=datetime.combine(start, time(), UTC),
        end=datetime.combine(end + timedelta(days=1), time(), UTC),
        endpoint=f"upload://local/{catalogue_id}/{profile}",
        evidence_mode="OWNER_SUPPLIED",
        fetch=fetch,
    )
