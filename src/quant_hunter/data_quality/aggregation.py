"""Causal session aggregation persisted as a new canonical derived DATASET."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, cast

import pyarrow as pa  # type: ignore[import-untyped]

from quant_hunter.config import JsonRecord, canonicalize_json
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
    parquet_writer_profile_digest,
    publish_derived_table,
    verify_dataset_record_binding,
    verify_derived_dataset_evidence,
)
from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.markets import MarketError, MinuteBar, aggregate_minutes, sessions
from quant_hunter.markets.aggregation import TIMEFRAMES
from quant_hunter.markets.common import utc
from quant_hunter.storage import ArtifactManifest, ArtifactProducer, QualityDisposition

from .checks import bounds, stamp
from .models import QualityError, SelectedSnapshot

if TYPE_CHECKING:
    from .service import QualityService

TRANSFORMATION = "qh-causal-session-aggregation-v1"
COMMAND = "quant-hunter causal aggregation of quality-admitted minute data"


def _compute(
    service: QualityService,
    parent_id: str,
    *,
    timeframe: str,
    partial_policy: str,
    as_of: datetime,
) -> tuple[Any, JsonRecord, JsonRecord, Any]:
    head, config, table, parent_report = service._inputs(parent_id)
    if parent_report["admission"] == "BLOCKED":
        raise QualityError("AGGREGATION_PARENT_BLOCKED")
    revision = service._instrument(
        cast(str, config["instrument_id"]),
        cast(str, config["instrument_revision_digest"]),
    )
    try:
        utc(as_of)
    except MarketError:
        raise QualityError("AGGREGATION_AS_OF_REQUIRES_UTC") from None
    if revision.recorded_at > as_of:
        raise QualityError("INSTRUMENT_METADATA_NOT_AVAILABLE_AT_AS_OF")
    schedule = sessions(
        revision.instrument.calendar_id,
        date.fromisoformat(cast(str, config["calendar_start"])),
        date.fromisoformat(cast(str, config["calendar_end"])),
    )
    minutes = tuple(
        MinuteBar(
            revision.instrument.instrument_id,
            revision.instrument.symbol_at(row["open_at"]),
            row["open_at"],
            row["close_at"],
            row["available_at"],
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row.get("volume"),
            row.get("open_bid"),
            row.get("open_ask"),
        )
        for row in table.to_pylist()
    )
    try:
        result = aggregate_minutes(
            minutes,
            revision,
            schedule,
            as_of=as_of,
            timeframe=timeframe,
            partial_policy=partial_policy,
        )
    except MarketError:
        raise QualityError(
            "INVALID_AGGREGATION_CONFIGURATION_OR_MARKET_INPUT"
        ) from None
    output: list[dict[str, object]] = []
    for index, row in enumerate(result.bars, start=1):
        entry: dict[str, object] = {
            "source_row": index,
            "open_at": row.open_at,
            "close_at": row.close_at,
            "available_at": row.available_at,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "revision_time": None,
            "ingestion_time": as_of,
            "revision_time_status": "NOT_APPLICABLE"
            if parent_report["causal_eligible"]
            else "REQUIRED_UNKNOWN",
        }
        for key, value in (
            ("volume", row.volume),
            ("open_bid", row.open_bid),
            ("open_ask", row.open_ask),
        ):
            if key in table.column_names:
                entry[key] = value
        output.append(entry)
    if not output:
        raise QualityError("NO_AVAILABLE_COMPLETE_AGGREGATE")
    derived = pa.Table.from_pylist(output, schema=table.schema)
    report: JsonRecord = {
        "schema_version": "qh-aggregation-quality-v1",
        "parent_dataset_id": parent_id,
        "parent_record_digest": head.digest,
        "parent_quality_report_digest": config["quality_report_digest"],
        "aggregation_configuration_digest": result.configuration_digest,
        "timeframe": timeframe,
        "partial_policy": partial_policy,
        "as_of": stamp(as_of),
        "row_count": derived.num_rows,
        "admission": parent_report["admission"],
        "causal_eligible": parent_report["causal_eligible"],
        "reasons": parent_report["reasons"],
        "exclusions": [
            {
                "session": item.session,
                "open_at": stamp(item.open_at),
                "close_at": stamp(item.close_at),
                "reason": item.reason,
                "expected_minutes": item.expected_minutes,
                "observed_minutes": item.observed_minutes,
            }
            for item in result.exclusions
        ],
        "limitations": [
            "Opening marks and optional quotes remain distinct; no synthetic bid/ask is created.",
            "Window availability is the maximum constituent availability; no partial not-yet-closed bar is emitted.",
            "Excluded windows remain visible; parent licensing/timing/empirical limitations remain unchanged.",
        ],
    }
    return derived, report, config, head


def aggregate(
    service: QualityService,
    parent_id: str,
    *,
    expected_record_digest: str,
    expected_report_digest: str,
    timeframe: str,
    partial_policy: str,
    as_of: datetime,
) -> JsonRecord:
    table, report, parent_config, head = _compute(
        service,
        parent_id,
        timeframe=timeframe,
        partial_policy=partial_policy,
        as_of=as_of,
    )
    if (
        head.digest != expected_record_digest
        or parent_config["quality_report_digest"] != expected_report_digest
    ):
        raise QualityError("STALE_DATASET_SELECTION")
    identity = new_typed_id(RegistryKind.DATASET)
    created = stamp(service.clock())
    report["dataset_id"] = identity
    quality = service.objects.publish(canonicalize_json(report))
    configuration: JsonRecord = {
        "schema_version": "qh-session-aggregation-v1",
        "dataset_id": identity,
        "created_at": created,
        "parent_dataset_id": parent_id,
        "parent_record_digest": head.digest,
        "parent_quality_report_digest": expected_report_digest,
        "timeframe": timeframe,
        "partial_policy": partial_policy,
        "as_of": stamp(as_of),
        "quality_report_digest": quality.digest,
        "code_revision": service.code_revision,
        "environment_digest": service.environment_digest,
    }
    config_object = service.objects.publish(canonicalize_json(configuration))
    parent = ParentEvidence(
        parent_id,
        head.digest,
        cast(str, head.record["physical_object_digest"]),
        cast(str, head.record["provenance_lineage_digest"]),
        cast(str, head.record["logical_content_fingerprint"]),
    )
    evidence = publish_derived_table(
        store=service.objects,
        catalog=service.catalog,
        table=table,
        declared_schema=table.schema,
        dataset_id=identity,
        layer=DerivedLayer.CURATED,
        row_ordering=OrderingSemantics.ORDERED,
        parent_evidence=[parent],
        parent_ordering=OrderingSemantics.ORDERED,
        transformation_identity=TRANSFORMATION,
        transformation_configuration_digest=config_object.digest,
        created_at=created,
        producer=ArtifactProducer(
            service.code_revision, COMMAND, service.environment_digest
        ),
        source_ids=[cast(str, parent_config["source_id"])],
        quality_disposition=QualityDisposition.PENDING,
        references=[f"artifact:{quality.digest}", f"artifact:{expected_report_digest}"],
    )
    service.registry.create_initial(
        RegistryKind.DATASET,
        identity,
        service._dataset_record(
            created,
            cast(str, parent_config["source_id"]),
            bounds(table),
            evidence.schema_digest,
            evidence.parquet_object.digest,
            evidence.lineage_manifest.digest,
            evidence.logical_content_fingerprint,
            TRANSFORMATION,
            [parent_id],
            service.code_revision,
            service.environment_digest,
            "curated",
        ),
    )
    return get_aggregate(service, identity)


def get_aggregate(service: QualityService, identity: str) -> JsonRecord:
    from .service import equal, record

    head = service.registry.verify_object(identity)[-1]
    lineage_digest = cast(str, head.record["provenance_lineage_digest"])
    lineage_bytes = service.objects.read_bytes(lineage_digest)
    lineage = service._read(lineage_digest)
    config_digest = cast(str, record(lineage["transformation"])["configuration_digest"])
    config = service._read(config_digest)
    if (
        config["schema_version"] != "qh-session-aggregation-v1"
        or config["dataset_id"] != identity
    ):
        raise QualityError("AGGREGATION_GRAPH_MISMATCH")
    service._environment(cast(str, config["environment_digest"]))
    table, report, parent_config, parent_head = _compute(
        service,
        cast(str, config["parent_dataset_id"]),
        timeframe=cast(str, config["timeframe"]),
        partial_policy=cast(str, config["partial_policy"]),
        as_of=datetime.fromisoformat(cast(str, config["as_of"])),
    )
    report["dataset_id"] = identity
    if service._read(cast(str, config["quality_report_digest"])) != report:
        raise QualityError("AGGREGATION_REPORT_REPLAY_MISMATCH")
    equal(
        config,
        {
            "parent_record_digest": parent_head.digest,
            "parent_quality_report_digest": parent_config["quality_report_digest"],
        },
    )
    parent = ParentEvidence(
        cast(str, config["parent_dataset_id"]),
        parent_head.digest,
        cast(str, parent_head.record["physical_object_digest"]),
        cast(str, parent_head.record["provenance_lineage_digest"]),
        cast(str, parent_head.record["logical_content_fingerprint"]),
    )
    artifact_digest = cast(str, lineage["physical_artifact_manifest_digest"])
    evidence = DerivedDatasetEvidence(
        identity,
        DerivedLayer.CURATED,
        QualityDisposition.PENDING,
        OrderingSemantics.ORDERED,
        OrderingSemantics.ORDERED,
        table.schema,
        DEFAULT_PARQUET_PROFILE,
        (parent,),
        service.objects.get(cast(str, head.record["physical_object_digest"])),
        ArtifactManifest(service.objects.read_bytes(artifact_digest), artifact_digest),
        service.objects.get(artifact_digest),
        DatasetLineageManifest(lineage_bytes, lineage_digest),
        service.objects.get(lineage_digest),
        logical_schema_digest(table.schema, OrderingSemantics.ORDERED),
        logical_content_fingerprint(table, table.schema, OrderingSemantics.ORDERED),
        parquet_writer_profile_digest(DEFAULT_PARQUET_PROFILE),
    )
    verify_derived_dataset_evidence(
        store=service.objects, catalog=service.catalog, evidence=evidence
    )
    verify_dataset_record_binding(
        catalog=service.catalog, record=head.record, evidence=evidence
    )
    equal(
        head.record,
        service._dataset_record(
            cast(str, config["created_at"]),
            cast(str, parent_config["source_id"]),
            bounds(table),
            evidence.schema_digest,
            evidence.parquet_object.digest,
            lineage_digest,
            evidence.logical_content_fingerprint,
            TRANSFORMATION,
            [parent.dataset_id],
            cast(str, config["code_revision"]),
            cast(str, config["environment_digest"]),
            "curated",
        ),
    )
    equal(
        lineage,
        {
            "source_ids": [parent_config["source_id"]],
            "references": [
                f"artifact:{config['quality_report_digest']}",
                f"artifact:{config['parent_quality_report_digest']}",
            ],
            "transformation": {
                "identity": TRANSFORMATION,
                "configuration_digest": config_digest,
            },
            "producer": {
                "code_revision": config["code_revision"],
                "environment_digest": config["environment_digest"],
            },
        },
    )
    if service.objects.read_bytes(
        evidence.parquet_object.digest
    ) != deterministic_parquet_bytes(
        table, table.schema, OrderingSemantics.ORDERED, DEFAULT_PARQUET_PROFILE
    ):
        raise QualityError("AGGREGATION_REPLAY_MISMATCH")
    features = tuple(
        name
        for name in ("close", "open", "high", "low", "volume", "open_bid", "open_ask")
        if name in table.column_names
    )
    snapshot = SelectedSnapshot(
        identity,
        head.digest,
        evidence.parquet_object.digest,
        cast(str, config["quality_report_digest"]),
        cast(str, parent_config["instrument_id"]),
        cast(str, parent_config["instrument_revision_digest"]),
        cast(str, parent_config["calendar_digest"]),
        table.num_rows,
        bounds(table),
        TIMEFRAMES[cast(str, config["timeframe"])] * 60_000_000_000,
        features,
        cast(str, record(parent_config["metadata"])["evidence_mode"]),
        cast(str, report["admission"]),
        cast(bool, report["causal_eligible"]),
        tuple(cast(list[str], report["reasons"])),
    )
    return {
        **snapshot.to_record(),
        "source_id": parent_config["source_id"],
        "raw_dataset_id": parent_config["raw_dataset_id"],
        "raw_digest": parent_config["raw_digest"],
        "configuration_digest": config_digest,
        "metadata": parent_config["metadata"],
        "quality": report,
        "empirically_validated": False,
        "host_enforced": False,
    }
