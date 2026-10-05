"""Immutable mapped import/quality graph through canonical DATASET/SOURCE stores."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.config.schema import VersionedSchemaCatalog
from quant_hunter.data.derived import (
    DEFAULT_PARQUET_PROFILE,
    DatasetLineageManifest,
    DerivedDatasetEvidence,
    DerivedLayer,
    OrderingSemantics,
    ParentEvidence,
    deterministic_parquet_bytes,
    logical_content_fingerprint,
    logical_schema_digest,
    logical_schema_document,
    parquet_writer_profile_digest,
    publish_derived_table,
    verify_dataset_record_binding,
    verify_derived_dataset_evidence,
)
from quant_hunter.identity import (
    RegistryKind,
    RegistryStore,
    Revision,
    new_typed_id,
    validate_typed_id,
)
from quant_hunter.imports.validation import metadata_document
from quant_hunter.markets import InstrumentRevision, sessions
from quant_hunter.markets.registry import MANAGED_FIELDS
from quant_hunter.provenance.hashing import require_sha256_digest, sha256_bytes
from quant_hunter.storage import (
    ArtifactManifest,
    ArtifactProducer,
    Compression,
    ImmutableObjectStore,
    QualityDisposition,
    RawCapture,
    RawCaptureMetadata,
    RetrievalStatus,
    capture_raw_payload,
    verify_raw_capture,
)

from .checks import bounds, inspect_table, stamp
from .mapping import MappingSpec, map_rows
from .models import QualityError, SelectedSnapshot
from .partitions import PartitionSelection, compose, iter_batches

TRANSFORMATION = "qh-explicit-mapped-minute-bars-v1"
RAW_TRANSFORMATION = "qh-exact-bytes-hex-logical-envelope-v1"
COMMAND = "quant-hunter explicit immutable mapping and quality"
ENDPOINT = "upload://local/mapped-bytes"


def record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise QualityError("INVALID_EVIDENCE_DOCUMENT")
    return value


def equal(actual: JsonRecord, expected: JsonRecord) -> None:
    if any(actual.get(key) != value for key, value in expected.items()):
        raise QualityError("QUALITY_GRAPH_MISMATCH")


def raw_table(payload: bytes) -> Any:
    # Exact binary content has an explicit injective hex logical interpretation,
    # distinct from either its SHA-256 physical identity or mapped market rows.
    return pa.Table.from_pylist(
        [{"exact_bytes_hex": payload.hex()}],
        schema=pa.schema([pa.field("exact_bytes_hex", pa.string(), nullable=False)]),
    )


def source_record(metadata: JsonRecord, created: str) -> JsonRecord:
    return {
        "schema_version": "1.0.0",
        "created_at": created,
        "reviewed_at": created,
        "status": "CANDIDATE",
        "provider": metadata["source_name"],
        "documentation_uri": ENDPOINT,
        "data_domain": "Explicitly mapped local market bars",
        "granularity": "One-minute closed bars",
        "historical_depth": "Only the immutable local version",
        "realtime_availability": "HISTORICAL_ONLY",
        "latency_description": "Uploader declared; independently unverified",
        "cost": {
            "class": "FREE",
            "currency": "USD",
            "monthly_cost": "0",
            "pricing_date": created[:10],
        },
        "access": {
            "license": metadata["declared_license"],
            "api_restrictions": "Local bytes only",
            "redistribution_restrictions": metadata["declared_restrictions"],
            "retention_constraints": "Declared rights require independent review",
        },
        "time_semantics": {
            "event_time": "NATIVE",
            "publication_time": "UNKNOWN",
            "ingestion_time": "DERIVED",
            "revision_time": "UNKNOWN",
        },
        "price_nature": "INDICATIVE",
        "reliability": "UNKNOWN; structural diagnostics only",
        "limitations": [
            "Zero cost applies only to local ingestion; upstream cost is unknown.",
            "Timing, licensing, corporate actions and survivorship remain unverified.",
            "No empirical validation or HOST_ENFORCED authority.",
        ],
        "owner": "local-uploader",
    }


class QualityService:
    """Authentication/ownership are caller responsibilities; never exposes a global list."""

    def __init__(
        self,
        registry: RegistryStore,
        objects: ImmutableObjectStore,
        schema_root: Path,
        code_revision: str,
        environment_digest: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(code_revision) != 40 or any(
            c not in "0123456789abcdef" for c in code_revision
        ):
            raise QualityError("INVALID_CODE_REVISION")
        self.registry, self.objects = registry, objects
        self.catalog = VersionedSchemaCatalog(schema_root)
        self.code_revision, self.environment_digest, self.clock = (
            code_revision,
            environment_digest,
            clock,
        )
        self._environment(environment_digest)

    def _read(self, digest: str) -> JsonRecord:
        return record(parse_json_document(self.objects.read_bytes(digest)))

    def compose(
        self,
        selections: tuple[tuple[str, str, str], ...],
        *,
        purpose: str = "PATTERN_CAUSAL",
    ) -> PartitionSelection:
        return compose(self, selections, purpose=purpose)

    def iter_batches(self, manifest_digest: str) -> Iterator[tuple[int, Any]]:
        return iter_batches(self, manifest_digest)

    def aggregate(
        self,
        dataset_id: str,
        *,
        expected_record_digest: str,
        expected_report_digest: str,
        timeframe: str,
        partial_policy: str,
        as_of: datetime,
    ) -> JsonRecord:
        from .aggregation import aggregate

        return aggregate(
            self,
            dataset_id,
            expected_record_digest=expected_record_digest,
            expected_report_digest=expected_report_digest,
            timeframe=timeframe,
            partial_policy=partial_policy,
            as_of=as_of,
        )

    def _environment(self, digest: str) -> None:
        require_sha256_digest(digest)
        environment = self._read(digest)
        if "source_snapshot_digest" in environment:
            self.objects.get(cast(str, environment["source_snapshot_digest"]))

    def _instrument(self, identity: str, digest: str) -> InstrumentRevision:
        validate_typed_id(identity, RegistryKind.INSTRUMENT)
        require_sha256_digest(digest)
        revisions = self.registry.verify_object(identity)
        selected = next((row for row in revisions if row.digest == digest), None)
        if selected is None:
            raise QualityError("INSTRUMENT_REVISION_NOT_FOUND")
        snapshot = InstrumentRevision.from_record(
            {
                key: value
                for key, value in selected.record.items()
                if key not in MANAGED_FIELDS
            }
        )
        if snapshot.instrument.instrument_id != identity:
            raise QualityError("INSTRUMENT_IDENTITY_MISMATCH")
        return snapshot

    def ingest_mapped(
        self,
        payload: bytes,
        *,
        file_format: str,
        metadata: JsonRecord,
        mapping: MappingSpec,
        instrument_id: str,
        instrument_revision_digest: str,
        calendar_start: date,
        calendar_end: date,
    ) -> JsonRecord:
        """Corrections are new identities; every excluded row is retained in lineage."""
        created_dt = self.clock()
        if created_dt.tzinfo is None or created_dt.utcoffset() != UTC.utcoffset(
            created_dt
        ):
            raise QualityError("CLOCK_REQUIRES_UTC")
        created = stamp(created_dt)
        try:
            metadata = metadata_document(metadata)
            revision = self._instrument(instrument_id, instrument_revision_digest)
            if revision.recorded_at > created_dt:
                raise QualityError("FUTURE_INSTRUMENT_METADATA")
            instrument = revision.instrument
            declared = record(metadata["instrument"])
            equal(
                declared,
                {
                    "asset_class": instrument.asset_class,
                    "base_currency": instrument.base_currency,
                    "quote_currency": instrument.quote_currency,
                },
            )
            if mapping.price_currency != instrument.quote_currency:
                raise QualityError("PRICE_CURRENCY_MISMATCH")
            if (
                metadata["evidence_mode"] != "SYNTHETIC"
                and mapping.revision_mode == "SYNTHETIC_NOT_APPLICABLE"
            ):
                raise QualityError("HISTORICAL_REVISION_CANNOT_BE_SYNTHETIC")
            schedule = sessions(instrument.calendar_id, calendar_start, calendar_end)
            table, dispositions = map_rows(
                payload,
                file_format,
                mapping,
                lot_size=instrument.lot_size,
                ingestion_time=created_dt,
            )
            report = inspect_table(
                table,
                revision,
                schedule,
                evidence_mode=cast(str, metadata["evidence_mode"]),
                dispositions=dispositions,
            )
            if not dispositions["accepted"]:
                report["raw_digest"] = sha256_bytes(payload)
                audit = self.objects.publish(canonicalize_json(report))
                raise QualityError("ROW_POLICY_REJECTED", audit.digest)
            for row in table.to_pylist():
                if declared["symbol"] != instrument.symbol_at(row["open_at"]):
                    raise QualityError("SYMBOL_METADATA_MISMATCH")
        except ValueError as error:
            if isinstance(error, QualityError) and error.audit_digest is not None:
                raise
            code = (
                error.code
                if isinstance(error, QualityError)
                else "INVALID_MAPPING_INPUT"
            )
            audit = self.objects.publish(
                canonicalize_json(
                    {
                        "schema_version": "qh-quality-failure-v1",
                        "code": code,
                        "raw_digest": sha256_bytes(payload)
                        if isinstance(payload, bytes)
                        else None,
                        "raw_size": len(payload)
                        if isinstance(payload, bytes)
                        else None,
                    }
                )
            )
            raise QualityError(code, audit.digest) from None
        source = self.registry.allocate(
            RegistryKind.SOURCE, source_record(metadata, created)
        )
        raw_id, dataset_id = (
            new_typed_id(RegistryKind.DATASET),
            new_typed_id(RegistryKind.DATASET),
        )
        producer = ArtifactProducer(
            self.code_revision, COMMAND, self.environment_digest
        )
        byte_table = raw_table(payload)
        raw_schema = self.objects.publish(
            canonicalize_json(
                logical_schema_document(byte_table.schema, OrderingSemantics.ORDERED)
            )
        )
        raw_logical = logical_content_fingerprint(
            byte_table, byte_table.schema, OrderingSemantics.ORDERED
        )
        calendar_object = self.objects.publish(canonicalize_json(schedule.to_record()))
        report.update(
            dataset_id=dataset_id,
            source_id=source.object_id,
            instrument_id=instrument_id,
            instrument_revision_digest=instrument_revision_digest,
            calendar_digest=calendar_object.digest,
            mapping=mapping.to_record(),
            raw_digest=sha256_bytes(payload),
            evidence_mode=metadata["evidence_mode"],
        )
        quality = self.objects.publish(canonicalize_json(report))
        initial: JsonRecord = {
            "schema_version": "qh-mapped-import-v1",
            "created_at": created,
            "dataset_id": dataset_id,
            "raw_dataset_id": raw_id,
            "source_id": source.object_id,
            "source_record_digest": source.revision.digest,
            "metadata": metadata,
            "mapping": mapping.to_record(),
            "file_format": file_format,
            "instrument_id": instrument_id,
            "instrument_revision_digest": instrument_revision_digest,
            "calendar_digest": calendar_object.digest,
            "calendar_start": calendar_start.isoformat(),
            "calendar_end": calendar_end.isoformat(),
            "quality_report_digest": quality.digest,
            "raw_schema_digest": raw_schema.digest,
            "raw_logical_fingerprint": raw_logical,
            "code_revision": self.code_revision,
            "environment_digest": self.environment_digest,
        }
        initial_object = self.objects.publish(canonicalize_json(initial))
        capture = capture_raw_payload(
            store=self.objects,
            catalog=self.catalog,
            payload=payload,
            source_id=source.object_id,
            dataset_id=raw_id,
            provider=cast(str, metadata["source_name"]),
            source_endpoint=ENDPOINT,
            request_parameters={"format": file_format},
            request_reference=f"artifact:{initial_object.digest}",
            media_type="text/csv"
            if file_format == "CSV"
            else "application/vnd.apache.parquet",
            compression=Compression.NONE if file_format == "CSV" else Compression.OTHER,
            ingestion_time=created,
            source_native_references=[cast(str, declared["symbol"])],
            coverage_references=cast(list[str], list(bounds(table).values())),
            retrieval_status=RetrievalStatus.SUCCEEDED,
            quality_disposition=QualityDisposition.PENDING,
            warnings=["Uploader timing and rights are unverified"],
            producer=producer,
            configuration_digest=initial_object.digest,
        )
        raw = self.registry.create_initial(
            RegistryKind.DATASET,
            raw_id,
            self._dataset_record(
                created,
                source.object_id,
                bounds(table),
                raw_schema.digest,
                capture.payload.digest,
                capture.metadata.digest,
                raw_logical,
                RAW_TRANSFORMATION,
                [],
                self.code_revision,
                self.environment_digest,
                "raw_landing",
            ),
        )
        config = self.objects.publish(
            canonicalize_json(
                {
                    **initial,
                    "initial_configuration_digest": initial_object.digest,
                    "raw_record_digest": raw.digest,
                    "raw_digest": capture.payload.digest,
                    "raw_capture_digest": capture.metadata.digest,
                    "raw_artifact_digest": capture.artifact_manifest.digest,
                }
            )
        )
        parent = ParentEvidence(
            raw_id,
            raw.digest,
            capture.payload.digest,
            capture.metadata.digest,
            raw_logical,
        )
        evidence = publish_derived_table(
            store=self.objects,
            catalog=self.catalog,
            table=table,
            declared_schema=table.schema,
            dataset_id=dataset_id,
            layer=DerivedLayer.NORMALIZED,
            row_ordering=OrderingSemantics.ORDERED,
            parent_evidence=[parent],
            parent_ordering=OrderingSemantics.ORDERED,
            transformation_identity=TRANSFORMATION,
            transformation_configuration_digest=config.digest,
            created_at=created,
            producer=producer,
            source_ids=[source.object_id],
            quality_disposition=QualityDisposition.PENDING,
            references=[
                f"artifact:{quality.digest}",
                f"artifact:{calendar_object.digest}",
                f"{instrument_id}@{instrument_revision_digest}",
            ],
        )
        self.registry.create_initial(
            RegistryKind.DATASET,
            dataset_id,
            self._dataset_record(
                created,
                source.object_id,
                bounds(table),
                evidence.schema_digest,
                evidence.parquet_object.digest,
                evidence.lineage_manifest.digest,
                evidence.logical_content_fingerprint,
                TRANSFORMATION,
                [raw_id],
                self.code_revision,
                self.environment_digest,
                "normalized",
            ),
        )
        return self.get_dataset(dataset_id)

    @staticmethod
    def _dataset_record(
        created: str,
        source_id: str,
        coverage: JsonRecord,
        schema: str,
        physical: str,
        lineage: str,
        logical: str,
        transformation: str,
        parents: list[str],
        code: str,
        environment: str,
        layer: str,
    ) -> JsonRecord:
        return {
            "schema_version": "1.0.0",
            "created_at": created,
            "layer": layer,
            "source_ids": [source_id],
            "coverage": coverage,
            "time_fields": {
                "event_time": "close_at"
                if layer != "raw_landing"
                else "NOT_APPLICABLE",
                "publication_time": "available_at"
                if layer != "raw_landing"
                else "NOT_APPLICABLE",
                "ingestion_time": "ingestion_time"
                if layer != "raw_landing"
                else "NOT_APPLICABLE",
                "revision_time": "revision_time"
                if layer != "raw_landing"
                else "NOT_APPLICABLE",
            },
            "schema_digest": schema,
            "physical_object_digest": physical,
            "provenance_lineage_digest": lineage,
            "logical_content_fingerprint": logical,
            "provenance": {
                "parent_dataset_ids": cast(list[JsonValue], parents),
                "transformation": transformation,
                "code_revision": code,
                "environment_digest": environment,
            },
            "quality_status": "PENDING",
        }

    def _inputs(self, dataset_id: str) -> tuple[Revision, JsonRecord, Any, JsonRecord]:
        validate_typed_id(dataset_id, RegistryKind.DATASET)
        head = self.registry.verify_object(dataset_id)[-1]
        if (
            record(head.record["provenance"])["transformation"] != TRANSFORMATION
            or head.record["layer"] != "normalized"
        ):
            raise QualityError("NOT_A_QUALITY_DATASET")
        lineage_digest = cast(str, head.record["provenance_lineage_digest"])
        lineage_bytes = self.objects.read_bytes(lineage_digest)
        lineage = record(parse_json_document(lineage_bytes))
        config_digest = cast(
            str, record(lineage["transformation"])["configuration_digest"]
        )
        config = self._read(config_digest)
        initial_digest = cast(str, config["initial_configuration_digest"])
        equal(config, self._read(initial_digest))
        equal(
            config,
            {
                "dataset_id": dataset_id,
                "schema_version": "qh-mapped-import-v1",
                "created_at": head.record["created_at"],
            },
        )
        self._environment(cast(str, config["environment_digest"]))
        metadata = metadata_document(record(config["metadata"]))
        mapping = MappingSpec.from_record(record(config["mapping"]))
        revision = self._instrument(
            cast(str, config["instrument_id"]),
            cast(str, config["instrument_revision_digest"]),
        )
        schedule = sessions(
            revision.instrument.calendar_id,
            date.fromisoformat(cast(str, config["calendar_start"])),
            date.fromisoformat(cast(str, config["calendar_end"])),
        )
        if self.objects.read_bytes(
            cast(str, config["calendar_digest"])
        ) != canonicalize_json(schedule.to_record()):
            raise QualityError("CALENDAR_SNAPSHOT_MISMATCH")
        payload = self.objects.read_bytes(cast(str, config["raw_digest"]))
        created = cast(str, config["created_at"])
        table, dispositions = map_rows(
            payload,
            cast(str, config["file_format"]),
            mapping,
            lot_size=revision.instrument.lot_size,
            ingestion_time=datetime.fromisoformat(created),
        )
        expected_report = inspect_table(
            table,
            revision,
            schedule,
            evidence_mode=cast(str, metadata["evidence_mode"]),
            dispositions=dispositions,
        )
        expected_report.update(
            dataset_id=dataset_id,
            source_id=config["source_id"],
            instrument_id=config["instrument_id"],
            instrument_revision_digest=config["instrument_revision_digest"],
            calendar_digest=config["calendar_digest"],
            mapping=mapping.to_record(),
            raw_digest=config["raw_digest"],
            evidence_mode=metadata["evidence_mode"],
        )
        report = self._read(cast(str, config["quality_report_digest"]))
        if report != expected_report or not dispositions["accepted"]:
            raise QualityError("QUALITY_REPORT_REPLAY_MISMATCH")
        if mapping.price_currency != revision.instrument.quote_currency or (
            metadata["evidence_mode"] != "SYNTHETIC"
            and mapping.revision_mode == "SYNTHETIC_NOT_APPLICABLE"
        ):
            raise QualityError("QUALITY_GRAPH_MISMATCH")
        declared = record(metadata["instrument"])
        equal(
            declared,
            {
                "asset_class": revision.instrument.asset_class,
                "base_currency": revision.instrument.base_currency,
                "quote_currency": revision.instrument.quote_currency,
            },
        )
        if revision.recorded_at > datetime.fromisoformat(created) or any(
            declared["symbol"] != revision.instrument.symbol_at(r["open_at"])
            for r in table.to_pylist()
        ):
            raise QualityError("QUALITY_GRAPH_MISMATCH")
        source = self.registry.verify_object(cast(str, config["source_id"]))[0]
        raw = self.registry.verify_object(cast(str, config["raw_dataset_id"]))[0]
        equal(
            config,
            {"source_record_digest": source.digest, "raw_record_digest": raw.digest},
        )
        equal(source.record, source_record(metadata, created))
        byte_table = raw_table(payload)
        raw_schema = logical_schema_digest(byte_table.schema, OrderingSemantics.ORDERED)
        raw_logical = logical_content_fingerprint(
            byte_table, byte_table.schema, OrderingSemantics.ORDERED
        )
        self.objects.get(raw_schema)
        equal(
            config,
            {"raw_schema_digest": raw_schema, "raw_logical_fingerprint": raw_logical},
        )
        equal(
            raw.record,
            self._dataset_record(
                created,
                cast(str, source.record["source_id"]),
                bounds(table),
                raw_schema,
                cast(str, config["raw_digest"]),
                cast(str, config["raw_capture_digest"]),
                raw_logical,
                RAW_TRANSFORMATION,
                [],
                cast(str, config["code_revision"]),
                cast(str, config["environment_digest"]),
                "raw_landing",
            ),
        )
        capture_digest, artifact_digest = (
            cast(str, config["raw_capture_digest"]),
            cast(str, config["raw_artifact_digest"]),
        )
        capture = RawCapture(
            self.objects.get(cast(str, config["raw_digest"])),
            ArtifactManifest(self.objects.read_bytes(artifact_digest), artifact_digest),
            self.objects.get(artifact_digest),
            RawCaptureMetadata(self.objects.read_bytes(capture_digest), capture_digest),
            self.objects.get(capture_digest),
        )
        verify_raw_capture(store=self.objects, catalog=self.catalog, capture=capture)
        equal(
            capture.metadata.document,
            {
                "source_id": config["source_id"],
                "dataset_id": config["raw_dataset_id"],
                "provider": metadata["source_name"],
                "source_endpoint": ENDPOINT,
                "ingestion_time": created,
                "request": {
                    "parameters": {"format": config["file_format"]},
                    "reference": f"artifact:{initial_digest}",
                },
                "coverage_references": list(bounds(table).values()),
                "source_native_references": [declared["symbol"]],
                "quality_disposition": "PENDING",
                "retrieval_status": "SUCCEEDED",
                "media_type": "text/csv"
                if config["file_format"] == "CSV"
                else "application/vnd.apache.parquet",
                "compression": "NONE" if config["file_format"] == "CSV" else "OTHER",
                "warnings": ["Uploader timing and rights are unverified"],
            },
        )
        equal(
            record(capture.artifact_manifest.document["producer"]),
            {
                "code_revision": config["code_revision"],
                "environment_digest": config["environment_digest"],
                "command": COMMAND,
            },
        )
        equal(
            record(capture.artifact_manifest.document["provenance"]),
            {"configuration_digest": initial_digest},
        )
        parent = ParentEvidence(
            cast(str, config["raw_dataset_id"]),
            raw.digest,
            cast(str, config["raw_digest"]),
            capture_digest,
            raw_logical,
        )
        artifact_digest = cast(str, lineage["physical_artifact_manifest_digest"])
        evidence = DerivedDatasetEvidence(
            dataset_id,
            DerivedLayer.NORMALIZED,
            QualityDisposition.PENDING,
            OrderingSemantics.ORDERED,
            OrderingSemantics.ORDERED,
            table.schema,
            DEFAULT_PARQUET_PROFILE,
            (parent,),
            self.objects.get(cast(str, head.record["physical_object_digest"])),
            ArtifactManifest(self.objects.read_bytes(artifact_digest), artifact_digest),
            self.objects.get(artifact_digest),
            DatasetLineageManifest(lineage_bytes, lineage_digest),
            self.objects.get(lineage_digest),
            logical_schema_digest(table.schema, OrderingSemantics.ORDERED),
            logical_content_fingerprint(table, table.schema, OrderingSemantics.ORDERED),
            parquet_writer_profile_digest(DEFAULT_PARQUET_PROFILE),
        )
        verify_derived_dataset_evidence(
            store=self.objects, catalog=self.catalog, evidence=evidence
        )
        verify_dataset_record_binding(
            catalog=self.catalog, record=head.record, evidence=evidence
        )
        equal(
            head.record,
            self._dataset_record(
                created,
                cast(str, config["source_id"]),
                bounds(table),
                evidence.schema_digest,
                evidence.parquet_object.digest,
                lineage_digest,
                evidence.logical_content_fingerprint,
                TRANSFORMATION,
                [cast(str, config["raw_dataset_id"])],
                cast(str, config["code_revision"]),
                cast(str, config["environment_digest"]),
                "normalized",
            ),
        )
        equal(
            record(lineage["transformation"]),
            {"identity": TRANSFORMATION, "configuration_digest": config_digest},
        )
        equal(
            record(lineage["producer"]),
            {
                "code_revision": config["code_revision"],
                "environment_digest": config["environment_digest"],
            },
        )
        equal(
            lineage,
            {
                "source_ids": [config["source_id"]],
                "references": [
                    f"artifact:{config['quality_report_digest']}",
                    f"artifact:{config['calendar_digest']}",
                    f"{config['instrument_id']}@{config['instrument_revision_digest']}",
                ],
            },
        )
        if self.objects.read_bytes(
            evidence.parquet_object.digest
        ) != deterministic_parquet_bytes(
            table, table.schema, OrderingSemantics.ORDERED, DEFAULT_PARQUET_PROFILE
        ):
            raise QualityError("NORMALIZED_REPLAY_MISMATCH")
        return head, config, table, report

    def get_dataset(self, dataset_id: str) -> JsonRecord:
        from .aggregation import TRANSFORMATION as AGGREGATION
        from .aggregation import get_aggregate

        validate_typed_id(dataset_id, RegistryKind.DATASET)
        candidate = self.registry.verify_object(dataset_id)[-1]
        if record(candidate.record["provenance"])["transformation"] == AGGREGATION:
            return get_aggregate(self, dataset_id)
        head, config, table, report = self._inputs(dataset_id)
        features = tuple(
            name
            for name in (
                "close",
                "open",
                "high",
                "low",
                "volume",
                "open_bid",
                "open_ask",
            )
            if name in table.column_names
        )
        snapshot = SelectedSnapshot(
            dataset_id,
            head.digest,
            cast(str, head.record["physical_object_digest"]),
            cast(str, config["quality_report_digest"]),
            cast(str, config["instrument_id"]),
            cast(str, config["instrument_revision_digest"]),
            cast(str, config["calendar_digest"]),
            table.num_rows,
            bounds(table),
            60_000_000_000,
            features,
            cast(str, record(config["metadata"])["evidence_mode"]),
            cast(str, report["admission"]),
            cast(bool, report["causal_eligible"]),
            tuple(cast(list[str], report["reasons"])),
        )
        return {
            **snapshot.to_record(),
            "source_id": config["source_id"],
            "raw_dataset_id": config["raw_dataset_id"],
            "raw_digest": config["raw_digest"],
            "configuration_digest": record(
                self._read(cast(str, head.record["provenance_lineage_digest"]))[
                    "transformation"
                ]
            )["configuration_digest"],
            "metadata": config["metadata"],
            "quality": report,
            "empirically_validated": False,
            "host_enforced": False,
        }

    def select(
        self,
        dataset_id: str,
        *,
        expected_record_digest: str,
        expected_report_digest: str,
        purpose: str = "PATTERN_CAUSAL",
    ) -> tuple[SelectedSnapshot, bytes]:
        detail = self.get_dataset(dataset_id)
        if (
            detail["record_digest"] != expected_record_digest
            or detail["quality_report_digest"] != expected_report_digest
        ):
            raise QualityError("STALE_DATASET_SELECTION")
        if purpose not in {
            "PATTERN_CAUSAL",
            "RESEARCH_CAUSAL",
            "EXPLORATORY_INSPECTION",
        }:
            raise QualityError("INVALID_SELECTION_PURPOSE")
        if detail["admission"] == "BLOCKED" or (
            purpose != "EXPLORATORY_INSPECTION" and not detail["causal_eligible"]
        ):
            raise QualityError("DATASET_NOT_ADMISSIBLE")
        snapshot = SelectedSnapshot(
            cast(str, detail["dataset_id"]),
            detail["record_digest"],
            cast(str, detail["normalized_digest"]),
            detail["quality_report_digest"],
            cast(str, detail["instrument_id"]),
            cast(str, detail["instrument_revision_digest"]),
            cast(str, detail["calendar_digest"]),
            cast(int, detail["row_count"]),
            record(detail["bounds"]),
            cast(int, detail["step_ns"]),
            tuple(cast(list[str], detail["feature_columns"])),
            cast(str, detail["evidence_mode"]),
            cast(str, detail["admission"]),
            cast(bool, detail["causal_eligible"]),
            tuple(cast(list[str], detail["reasons"])),
        )
        return snapshot, self.objects.read_bytes(snapshot.normalized_digest)
