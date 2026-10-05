"""Candidate-first bounded diagnostics for explicitly configured read-only sources."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.identity import RegistryKind
from quant_hunter.sources.alpaca_data import AlpacaBarQuery, AlpacaDataConnector
from quant_hunter.sources.catalog import list_sources
from quant_hunter.sources.probes import SourceProbeService, _candidate, _stamp
from quant_hunter.sources.sec import SECConnector, SECQuery
from quant_hunter.sources.transport import SourceError
from quant_hunter.storage.manifests import ArtifactProducer
from quant_hunter.storage.raw import (
    Compression,
    QualityDisposition,
    RetrievalStatus,
    capture_raw_payload,
)


def diagnostic_json(value: object) -> JsonValue:
    """Bounded source records retain decimal values and explicit date semantics."""
    if isinstance(value, datetime):
        return _stamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, tuple | list):
        return [diagnostic_json(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise SourceError("INVALID_RECORD_KEYS")
        return {key: diagnostic_json(item) for key, item in value.items()}
    if value is None or isinstance(value, str | bool | int):
        return value
    raise SourceError("UNSUPPORTED_RECORD_VALUE")


class EquityProbeService:
    """Reuse the existing raw-capture/registry authority; no approval or experiment."""

    def __init__(self, public: SourceProbeService) -> None:
        self.public = public

    def probe(
        self,
        catalogue_id: str,
        connector: SECConnector | AlpacaDataConnector,
        *,
        cik: str = "0000320193",
    ) -> JsonRecord:
        public = self.public
        public._verify_environment()
        if connector.catalogue_id != catalogue_id or catalogue_id not in (
            "SRC-01",
            "SRC-02",
        ):
            raise SourceError("CONNECTOR_ID_MISMATCH")
        spec = next(row for row in list_sources() if row.catalogue_id == catalogue_id)
        stamp = _stamp(datetime.now(UTC))
        candidate = _candidate(spec, stamp)
        candidate.update(
            granularity="Recent SEC filing metadata"
            if catalogue_id == "SRC-01"
            else "Daily IEX trade aggregates",
            price_nature="NOT_APPLICABLE"
            if catalogue_id == "SRC-01"
            else "VENUE_QUOTE_OR_TRADE",
            latency_description="Historical availability unknown; never execution quotes",
        )
        if catalogue_id == "SRC-02":
            candidate["cost"] = {
                "class": "LOW-COST",
                "currency": "USD",
                "monthly_cost": "UNKNOWN",
                "pricing_date": spec.documentation_reviewed_on,
            }
        source = public.registry.allocate(RegistryKind.SOURCE, candidate)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 5, tzinfo=UTC)
        config: JsonRecord = {
            "catalogue_id": catalogue_id,
            "purpose": "owner-triggered bounded read-only diagnostic",
            "maximum_pages": 1,
        }
        if isinstance(connector, SECConnector):
            start, end = (
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 12, 31, tzinfo=UTC),
            )
            config.update(cik=cik, resource="submissions")
            endpoint = f"https://data.sec.gov/submissions/CIK{cik}.json"
        else:
            config.update(
                symbol="AAPL",
                feed="iex",
                timeframe="1Day",
                adjustment="raw",
                symbol_mapping="DISABLED_ASOF_MINUS",
            )
            endpoint = "https://data.alpaca.markets/v2/stocks/bars"
        config.update(start=_stamp(start), end=_stamp(end))
        configuration = public.objects.publish(canonicalize_json(config))
        try:
            batch = (
                connector.test_connection(SECQuery(cik, start.date(), end.date()))
                if isinstance(connector, SECConnector)
                else connector.test_connection(
                    AlpacaBarQuery(
                        "AAPL", start, end, "iex", page_size=100, max_pages=1
                    )
                )
            )
        except SourceError as error:
            failure: JsonRecord = {
                "catalogue_id": catalogue_id,
                "source_id": source.object_id,
                "source_record_digest": source.revision.digest,
                "configuration_digest": configuration.digest,
                "error_code": error.code,
                "retrieved_at": _stamp(datetime.now(UTC)),
                "status": "FAILED",
                "quality": "QUARANTINED",
                "evidence_mode": connector.evidence_mode,
                "raw_retained": False,
            }
            evidence = public.objects.publish(canonicalize_json(failure))
            return {**failure, "capture_digest": evidence.digest}
        public._verify_environment()
        if len(batch.raw_pages) != 1:
            raise SourceError("DIAGNOSTIC_PAGE_BOUND")
        page = batch.raw_pages[0]
        raw = public.objects.publish(page.raw)
        if raw.digest != page.digest:
            raise SourceError("RAW_IDENTITY_MISMATCH")
        retrieved = _stamp(page.retrieved_at)
        schema = public.objects.publish(
            canonicalize_json(
                {
                    "media_type": "application/json",
                    "normalization_version": batch.normalization_version,
                    "time_semantics": "Opaque exact raw bytes; dates and trade times are not historical publication/availability proof",
                }
            )
        )
        lineage = public.objects.publish(
            canonicalize_json(
                {
                    "source_id": source.object_id,
                    "source_record_digest": source.revision.digest,
                    "physical_object_digest": raw.digest,
                    "schema_digest": schema.digest,
                    "configuration_digest": configuration.digest,
                    "code_revision": public.code_revision,
                    "environment_digest": public.environment_digest,
                    "retrieved_at": retrieved,
                    "evidence_mode": batch.evidence_mode,
                    "transformation": "None; exact provider response with bounded normalized preview",
                }
            )
        )
        dataset = public.registry.allocate(
            RegistryKind.DATASET,
            {
                "schema_version": "1.0.0",
                "created_at": retrieved,
                "layer": "raw_landing",
                "source_ids": [source.object_id],
                "coverage": {
                    "start": _stamp(start),
                    "end": _stamp(
                        datetime.combine(end.date() + timedelta(days=1), time(), UTC)
                    ),
                },
                "time_fields": {
                    key: "NOT_APPLICABLE"
                    for key in (
                        "event_time",
                        "publication_time",
                        "ingestion_time",
                        "revision_time",
                    )
                },
                "schema_digest": schema.digest,
                "physical_object_digest": raw.digest,
                "provenance_lineage_digest": lineage.digest,
                "provenance": {
                    "parent_dataset_ids": [],
                    "transformation": "Raw response; requested date envelope is not certified observed coverage or availability",
                    "code_revision": public.code_revision,
                    "environment_digest": public.environment_digest,
                },
                "quality_status": "PENDING",
            },
        )
        capture = capture_raw_payload(
            store=public.objects,
            catalog=public.schemas,
            payload=page.raw,
            source_id=source.object_id,
            dataset_id=dataset.object_id,
            provider=spec.name,
            source_endpoint=endpoint,
            request_parameters=config,
            request_reference=None,
            media_type="application/json",
            compression=Compression.NONE,
            ingestion_time=retrieved,
            source_native_references=[cik if catalogue_id == "SRC-01" else "AAPL:iex"],
            coverage_references=[
                "Requested envelope; actual completeness and availability unknown"
            ],
            retrieval_status=RetrievalStatus.SUCCEEDED,
            quality_disposition=QualityDisposition.PENDING,
            warnings=[
                *batch.limitations,
                spec.license_notes,
                "Source remains CANDIDATE; no scientific approval",
            ],
            producer=ArtifactProducer(
                public.code_revision,
                "owner-triggered read-only source diagnostic",
                public.environment_digest,
            ),
            configuration_digest=configuration.digest,
        )
        return {
            "catalogue_id": catalogue_id,
            "source_id": source.object_id,
            "source_record_digest": source.revision.digest,
            "dataset_id": dataset.object_id,
            "dataset_record_digest": dataset.revision.digest,
            "raw_digest": raw.digest,
            "capture_digest": capture.metadata.digest,
            "lineage_digest": lineage.digest,
            "configuration_digest": configuration.digest,
            "record_count": len(batch.records),
            "retrieved_at": retrieved,
            "evidence_mode": batch.evidence_mode,
            "preview": [diagnostic_json(asdict(row)) for row in batch.records[:10]],
            "limitations": [*batch.limitations, spec.pit_notes],
            "quality": "PENDING",
            "source_status": "CANDIDATE",
            "status": "SUCCEEDED",
        }
