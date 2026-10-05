"""Candidate-first immutable publication for bounded provider diagnostics.

This is an internal server capability, not a URL fetcher or research approval.
Callers enforce user roles, quotas and provider-specific rights before entry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.identity import RegistryKind
from quant_hunter.sources._equity_transport import RawPage
from quant_hunter.sources.catalog import list_sources
from quant_hunter.sources.probes import SourceProbeService, _candidate, _stamp
from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, SourceError
from quant_hunter.storage.manifests import ArtifactProducer
from quant_hunter.storage.raw import (
    Compression,
    QualityDisposition,
    RetrievalStatus,
    capture_raw_payload,
)
from quant_hunter.storage.security import (
    reject_credential_shaped_fields,
    reject_credential_uri,
    reject_secret_text_values,
)


@dataclass(frozen=True)
class DiagnosticBatch:
    """Validated adapter output; previews are bounded and not normalized datasets."""

    catalogue_id: str
    pages: tuple[RawPage, ...]
    record_count: int
    preview: tuple[JsonRecord, ...]
    evidence_mode: str
    normalization_version: str
    limitations: tuple[str, ...]
    media_type: str = "application/json"
    compression: Compression = Compression.NONE


class DiagnosticMaterializer:
    """Use canonical source/dataset registries and exact raw capture for each page."""

    def __init__(self, public: SourceProbeService) -> None:
        self.public = public

    def run(
        self,
        catalogue_id: str,
        *,
        configuration: JsonRecord,
        start: datetime,
        end: datetime,
        endpoint: str,
        evidence_mode: str,
        fetch: Callable[[], DiagnosticBatch],
    ) -> JsonRecord:
        public = self.public
        public._verify_environment()
        if catalogue_id not in (
            "SRC-05",
            "SRC-06",
            "SRC-07",
            "SRC-09",
            "SRC-18",
            "SRC-19",
            "SRC-20",
        ):
            raise SourceError("UNSUPPORTED_DIAGNOSTIC_SOURCE")
        if evidence_mode not in (
            "HISTORICAL_REAL",
            "OWNER_SUPPLIED",
            "RECORDED_FIXTURE",
        ):
            raise SourceError("INVALID_EVIDENCE_MODE")
        if (
            start.utcoffset() != UTC.utcoffset(start)
            or end.utcoffset() != UTC.utcoffset(end)
            or start >= end
        ):
            raise SourceError("INVALID_DIAGNOSTIC_ENVELOPE")
        reject_credential_shaped_fields(configuration)
        reject_secret_text_values(configuration, "source diagnostic configuration")
        reject_credential_uri(endpoint)
        configured = canonicalize_json(configuration)
        if len(configured) > 16_384:
            raise SourceError("CONFIGURATION_TOO_LARGE")
        spec = next(row for row in list_sources() if row.catalogue_id == catalogue_id)
        stamp = _stamp(datetime.now(UTC))
        candidate = _candidate(spec, stamp)
        candidate.update(
            granularity="Only the declared bounded diagnostic; native units in preview",
            latency_description="Historical availability unverified; not execution authority",
            price_nature="VENUE_QUOTE_OR_TRADE"
            if catalogue_id == "SRC-09"
            else "UNKNOWN"
            if catalogue_id == "SRC-19"
            else "NOT_APPLICABLE",
        )
        if catalogue_id in ("SRC-07", "SRC-09", "SRC-18", "SRC-19", "SRC-20"):
            candidate["cost"] = {
                "class": "LOW-COST" if catalogue_id == "SRC-07" else "PREMIUM",
                "currency": "USD",
                "monthly_cost": "UNKNOWN",
                "pricing_date": spec.documentation_reviewed_on or "2026-10-05",
            }
        source = public.registry.allocate(RegistryKind.SOURCE, candidate)
        config = public.objects.publish(configured)
        try:
            batch = fetch()
            if (
                batch.catalogue_id != catalogue_id
                or batch.evidence_mode != evidence_mode
            ):
                raise SourceError("DIAGNOSTIC_BINDING_MISMATCH")
            if (
                not 1 <= len(batch.pages) <= 2
                or sum(len(page.raw) for page in batch.pages) > MAX_RESPONSE_BYTES
                or any(not page.raw for page in batch.pages)
                or type(batch.record_count) is not int
                or not 0 <= batch.record_count <= 100_000
                or len(batch.preview) > min(10, batch.record_count)
            ):
                raise SourceError("DIAGNOSTIC_BATCH_BOUND")
            if any(
                page.digest != "sha256:" + sha256(page.raw).hexdigest()
                or page.retrieved_at.utcoffset() != UTC.utcoffset(page.retrieved_at)
                or page.retrieved_at > datetime.now(UTC)
                for page in batch.pages
            ):
                raise SourceError("RAW_IDENTITY_OR_RETRIEVAL_MISMATCH")
            preview_bytes = canonicalize_json(list(batch.preview))
            if len(preview_bytes) > 100_000:
                raise SourceError("DIAGNOSTIC_PREVIEW_BOUND")
            reject_secret_text_values(list(batch.preview), "source diagnostic preview")
        except SourceError as error:
            failure: JsonRecord = {
                "catalogue_id": catalogue_id,
                "source_id": source.object_id,
                "source_record_digest": source.revision.digest,
                "configuration_digest": config.digest,
                "error_code": error.code,
                "retrieved_at": _stamp(datetime.now(UTC)),
                "status": "FAILED",
                "quality": "QUARANTINED",
                "evidence_mode": evidence_mode,
                "raw_retained": False,
            }
            artifact = public.objects.publish(canonicalize_json(failure))
            return {**failure, "capture_digest": artifact.digest}
        public._verify_environment()
        raw_objects = [public.objects.publish(page.raw) for page in batch.pages]
        if any(
            raw.digest != page.digest
            for raw, page in zip(raw_objects, batch.pages, strict=True)
        ):
            raise SourceError("RAW_IDENTITY_MISMATCH")
        summary = public.objects.publish(
            canonicalize_json(
                {
                    "catalogue_id": catalogue_id,
                    "raw_digests": [raw.digest for raw in raw_objects],
                    "record_count": batch.record_count,
                    "preview": list(batch.preview),
                    "normalization_version": batch.normalization_version,
                    "evidence_mode": evidence_mode,
                    "scope": "Bounded preview only; no full normalized or PIT-approved dataset",
                }
            )
        )
        schema = public.objects.publish(
            canonicalize_json(
                {
                    "media_type": batch.media_type,
                    "normalization_version": batch.normalization_version,
                    "scope": "Exact raw bytes; preview transformation declared separately",
                }
            )
        )
        datasets: list[JsonValue] = []
        for index, (page, raw) in enumerate(zip(batch.pages, raw_objects, strict=True)):
            retrieved = _stamp(page.retrieved_at)
            lineage = public.objects.publish(
                canonicalize_json(
                    {
                        "source_id": source.object_id,
                        "source_record_digest": source.revision.digest,
                        "physical_object_digest": raw.digest,
                        "schema_digest": schema.digest,
                        "configuration_digest": config.digest,
                        "code_revision": public.code_revision,
                        "environment_digest": public.environment_digest,
                        "retrieved_at": retrieved,
                        "evidence_mode": evidence_mode,
                        "diagnostic_summary_digest": summary.digest,
                        "payload_index": index,
                        "all_raw_digests": [item.digest for item in raw_objects],
                        "transformation": "None; immutable source bytes, separate bounded preview",
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
                    "coverage": {"start": _stamp(start), "end": _stamp(end)},
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
                        "transformation": "Declared request/import envelope; observed completeness and historical availability unverified",
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
                request_parameters={**configuration, "payload_index": index},
                request_reference="Owner-supplied bytes; endpoint is an import reference"
                if evidence_mode == "OWNER_SUPPLIED"
                else None,
                media_type=batch.media_type,
                compression=batch.compression,
                ingestion_time=retrieved,
                source_native_references=[catalogue_id, f"payload-{index}"],
                coverage_references=["Declared envelope only; completeness unverified"],
                retrieval_status=RetrievalStatus.SUCCEEDED,
                quality_disposition=QualityDisposition.PENDING,
                warnings=[
                    *batch.limitations,
                    spec.license_notes,
                    "Source remains CANDIDATE",
                ],
                producer=ArtifactProducer(
                    public.code_revision,
                    "bounded provider diagnostic",
                    public.environment_digest,
                ),
                configuration_digest=config.digest,
            )
            datasets.append(
                {
                    "dataset_id": dataset.object_id,
                    "dataset_record_digest": dataset.revision.digest,
                    "raw_digest": raw.digest,
                    "capture_digest": capture.metadata.digest,
                    "lineage_digest": lineage.digest,
                }
            )
        first = cast(JsonRecord, datasets[0])
        return {
            **first,
            "datasets": datasets,
            "catalogue_id": catalogue_id,
            "source_id": source.object_id,
            "source_record_digest": source.revision.digest,
            "configuration_digest": config.digest,
            "diagnostic_summary_digest": summary.digest,
            "record_count": batch.record_count,
            "retrieved_at": _stamp(batch.pages[-1].retrieved_at),
            "evidence_mode": evidence_mode,
            "preview": list(batch.preview),
            "limitations": [*batch.limitations, spec.pit_notes],
            "quality": "PENDING",
            "source_status": "CANDIDATE",
            "status": "SUCCEEDED",
        }
