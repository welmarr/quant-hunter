"""Candidate-first diagnostic probes using the existing governed raw capture.

No experiment, source approval, quality approval or research evaluation occurs.
The caller owns authentication, request quotas and private access to responses.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import uuid7

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.config.schema import VersionedSchemaCatalog
from quant_hunter.identity import RegistryKind, RegistryStore
from quant_hunter.sources.catalog import SourceSpec, list_sources
from quant_hunter.sources.connectors import (
    BLSConnector,
    ECBConnector,
    FetchedBatch,
    default_query,
)
from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, SourceError
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.storage.manifests import ArtifactProducer
from quant_hunter.storage.raw import (
    Compression,
    QualityDisposition,
    RetrievalStatus,
    capture_raw_payload,
)

type ConnectorFactory = Callable[[str], BLSConnector | ECBConnector]


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _connector(catalogue_id: str) -> BLSConnector | ECBConnector:
    if catalogue_id == "SRC-04":
        return BLSConnector()
    if catalogue_id == "SRC-08":
        return ECBConnector()
    raise SourceError("CONNECTOR_NOT_IMPLEMENTED")


def _candidate(spec: SourceSpec, timestamp: str) -> JsonRecord:
    return {
        "schema_version": "1.0.0",
        "created_at": timestamp,
        "reviewed_at": timestamp,
        "status": "CANDIDATE",
        "provider": spec.name,
        "documentation_uri": spec.documentation_url,
        "data_domain": ", ".join(spec.markets),
        "granularity": "Monthly observations"
        if spec.catalogue_id == "SRC-04"
        else "Daily reference observations",
        "historical_depth": "Only the bounded diagnostic request; no verified full coverage",
        "realtime_availability": "HISTORICAL_ONLY",
        "latency_description": "Reference periods are not publication timestamps; historical availability UNKNOWN",
        "cost": {
            "class": "FREE",
            "currency": "USD",
            "monthly_cost": "0",
            "pricing_date": spec.documentation_reviewed_on,
        },
        "access": {
            "license": spec.license_notes,
            "api_restrictions": spec.rate_limit,
            "redistribution_restrictions": "Local diagnostic only; broader reuse requires source-specific review",
            "retention_constraints": "Retain exact small public diagnostic bytes with attribution and acquisition metadata",
        },
        "time_semantics": {
            "event_time": "UNKNOWN",
            "publication_time": "UNKNOWN",
            "ingestion_time": "DERIVED",
            "revision_time": "UNKNOWN",
        },
        "price_nature": "INDICATIVE"
        if spec.catalogue_id == "SRC-08"
        else "NOT_APPLICABLE",
        "reliability": "No reliability or research-quality claim from a diagnostic request",
        "limitations": [
            spec.pit_notes,
            "Candidate review is bounded to a small public sample, not source approval",
            f"Mission catalogue key: {spec.catalogue_id}",
        ],
        "owner": "local-source-diagnostic",
    }


class SourceProbeService:
    """Register a reviewed free-source candidate before one fixed bounded request."""

    def __init__(
        self,
        registry: RegistryStore,
        objects: ImmutableObjectStore,
        schema_root: Path,
        code_revision: str,
        environment_digest: str,
        *,
        connector_factory: ConnectorFactory | None = None,
    ) -> None:
        if re.fullmatch(r"[0-9a-f]{40}", code_revision) is None:
            raise SourceError("EXACT_CODE_REVISION_REQUIRED")
        self.registry, self.objects = registry, objects
        self.schemas = VersionedSchemaCatalog(schema_root)
        self.code_revision, self.environment_digest = code_revision, environment_digest
        self.connector_factory = connector_factory or _connector
        self._verify_environment()

    def _verify_environment(self) -> None:
        environment = parse_json_document(
            self.objects.get(self.environment_digest).path.read_bytes()
        )
        if not isinstance(environment, dict):
            raise SourceError("INVALID_ENVIRONMENT")
        if "source_snapshot_digest" in environment:
            snapshot = environment["source_snapshot_digest"]
            if not isinstance(snapshot, str):
                raise SourceError("INVALID_SOURCE_SNAPSHOT")
            self.objects.get(snapshot)

    def probe(self, catalogue_id: str) -> JsonRecord:
        self._verify_environment()
        query = default_query(catalogue_id)
        spec = next(
            item for item in list_sources() if item.catalogue_id == catalogue_id
        )
        timestamp = _stamp(datetime.now(UTC))
        source = self.registry.allocate(
            RegistryKind.SOURCE, _candidate(spec, timestamp)
        )
        config: JsonRecord = {
            "catalogue_id": catalogue_id,
            "series_id": query.series_id,
            "start": query.start.isoformat(),
            "end": query.end.isoformat(),
            "unit": query.unit,
            "purpose": "bounded diagnostic; no research evaluation",
        }
        configuration = self.objects.publish(canonicalize_json(config))
        connector = self.connector_factory(catalogue_id)
        if connector.catalogue_id != catalogue_id:
            raise SourceError("CONNECTOR_ID_MISMATCH")
        try:
            batch = connector.test_connection(query)
        except SourceError as error:
            raw_digest: str | None = None
            if (
                connector.last_response
                and 0 < len(connector.last_response.body) <= MAX_RESPONSE_BYTES
            ):
                raw_digest = self.objects.publish(connector.last_response.body).digest
            failure: JsonRecord = {
                "catalogue_id": catalogue_id,
                "source_id": source.object_id,
                "source_record_digest": source.revision.digest,
                "configuration_digest": configuration.digest,
                "raw_digest": raw_digest,
                "error_code": error.code,
                "retrieved_at": _stamp(datetime.now(UTC)),
                "status": "FAILED",
                "quality": "QUARANTINED",
                "evidence_mode": connector.evidence_mode,
                "retry_after_seconds": error.retry_after_seconds,
                "raw_retained": raw_digest is not None,
            }
            artifact = self.objects.publish(canonicalize_json(failure))
            return {**failure, "capture_digest": artifact.digest}
        return self._retain(
            batch,
            source.object_id,
            source.revision.digest,
            configuration.digest,
            config,
            spec,
        )

    def _retain(
        self,
        batch: FetchedBatch,
        source_id: str,
        source_digest: str,
        configuration_digest: str,
        config: JsonRecord,
        spec: SourceSpec,
    ) -> JsonRecord:
        self._verify_environment()
        raw = self.objects.publish(batch.raw)
        if raw.digest != batch.sha256:
            raise SourceError("RAW_IDENTITY_MISMATCH")
        retrieved = _stamp(batch.retrieved_at)
        schema = self.objects.publish(
            canonicalize_json(
                {
                    "media_type": "application/json"
                    if batch.catalogue_id == "SRC-04"
                    else "text/csv",
                    "normalization_version": batch.normalization_version,
                    "time_semantics": "Raw opaque bytes; reference period dates are not event/publication timestamps",
                }
            )
        )
        lineage = self.objects.publish(
            canonicalize_json(
                {
                    "source_id": source_id,
                    "source_record_digest": source_digest,
                    "physical_object_digest": raw.digest,
                    "schema_digest": schema.digest,
                    "configuration_digest": configuration_digest,
                    "code_revision": self.code_revision,
                    "environment_digest": self.environment_digest,
                    "retrieved_at": retrieved,
                    "evidence_mode": batch.evidence_mode,
                    "transformation": "None; exact response bytes retained; displayed preview normalized separately",
                }
            )
        )
        dataset_uuid = uuid7()
        dataset = self.registry.allocate(
            RegistryKind.DATASET,
            {
                "schema_version": "1.0.0",
                "created_at": retrieved,
                "layer": "raw_landing",
                "source_ids": [source_id],
                "coverage": {
                    "start": _stamp(datetime.combine(batch.query.start, time(), UTC)),
                    "end": _stamp(
                        datetime.combine(
                            batch.query.end + timedelta(days=1), time(), UTC
                        )
                    ),
                },
                "time_fields": {
                    "event_time": "NOT_APPLICABLE",
                    "publication_time": "NOT_APPLICABLE",
                    "ingestion_time": "NOT_APPLICABLE",
                    "revision_time": "NOT_APPLICABLE",
                },
                "schema_digest": schema.digest,
                "physical_object_digest": raw.digest,
                "provenance_lineage_digest": lineage.digest,
                "provenance": {
                    "parent_dataset_ids": [],
                    "transformation": "Raw response; coverage is requested reference-date envelope, not certified observed coverage or availability",
                    "code_revision": self.code_revision,
                    "environment_digest": self.environment_digest,
                },
                "quality_status": "PENDING",
            },
            uuid_factory=lambda: dataset_uuid,
        )
        endpoint = (
            "https://api.bls.gov/publicAPI/v1/timeseries/data/"
            if batch.catalogue_id == "SRC-04"
            else "https://data-api.ecb.europa.eu/service/data/EXR/"
            + batch.query.series_id
        )
        capture = capture_raw_payload(
            store=self.objects,
            catalog=self.schemas,
            payload=batch.raw,
            source_id=source_id,
            dataset_id=dataset.object_id,
            provider=spec.name,
            source_endpoint=endpoint,
            request_parameters=config,
            request_reference=None,
            media_type="application/json"
            if batch.catalogue_id == "SRC-04"
            else "text/csv",
            compression=Compression.NONE,
            ingestion_time=retrieved,
            source_native_references=[batch.query.series_id],
            coverage_references=[
                "Requested reference-date envelope; completeness not verified"
            ],
            retrieval_status=RetrievalStatus.SUCCEEDED,
            quality_disposition=QualityDisposition.PENDING,
            warnings=[
                *batch.limitations,
                spec.license_notes,
                "Source remains CANDIDATE; no PIT or scientific approval",
            ],
            producer=ArtifactProducer(
                self.code_revision,
                "bounded public source diagnostic",
                self.environment_digest,
            ),
            configuration_digest=configuration_digest,
        )
        preview: list[JsonValue] = [
            {
                "period": item.period,
                "period_start": item.period_start.isoformat(),
                "value": str(item.value) if item.value is not None else None,
                "unit": item.unit,
                "publication_time": None,
                "revision_time": None,
                "ingestion_time": _stamp(item.ingestion_time),
                "vintage": item.vintage,
                "point_in_time_eligible": False,
                "price_nature": item.price_nature,
                "quality_flags": list(item.quality_flags),
            }
            for item in batch.observations[:10]
        ]
        return {
            "catalogue_id": batch.catalogue_id,
            "source_id": source_id,
            "source_record_digest": source_digest,
            "dataset_id": dataset.object_id,
            "dataset_record_digest": dataset.revision.digest,
            "raw_digest": raw.digest,
            "capture_digest": capture.metadata.digest,
            "lineage_digest": lineage.digest,
            "configuration_digest": configuration_digest,
            "record_count": len(batch.observations),
            "retrieved_at": retrieved,
            "evidence_mode": batch.evidence_mode,
            "preview": preview,
            "limitations": [*batch.limitations, spec.pit_notes],
            "quality": "PENDING",
            "source_status": "CANDIDATE",
            "status": "SUCCEEDED",
        }
