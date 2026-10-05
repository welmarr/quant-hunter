"""Independent mapping, temporal, calendar, graph and admission oracles."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

import quant_hunter
from quant_hunter.config import JsonRecord, canonicalize_json, parse_json_document
from quant_hunter.data_quality import MappingSpec, QualityError, QualityService
from quant_hunter.data_quality.mapping import map_rows
from quant_hunter.identity import RegistryStore
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.storage import ImmutableObjectStore

SCHEMAS = Path(quant_hunter.__file__).parents[2] / "schemas" / "v1"
CODE = "7346cf4f79ca5897777c0118f8cf4c2292be929e"
NAMES = (
    "open_at",
    "close_at",
    "open",
    "high",
    "low",
    "close",
    "available_at",
    "volume",
)


def dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


def payload(count: int = 5) -> bytes:
    return (
        ",".join(NAMES)
        + "\n"
        + "\n".join(
            f"2025-01-06T14:{30 + i:02}:00Z,2025-01-06T14:{31 + i:02}:00Z,100,102,99,101,2025-01-06T14:{31 + i:02}:00Z,2"
            for i in range(count)
        )
        + "\n"
    ).encode()


def spec(**kwargs: Any) -> MappingSpec:
    return MappingSpec(
        tuple((name, name) for name in NAMES),
        revision_mode="SYNTHETIC_NOT_APPLICABLE",
        **kwargs,
    )


def metadata(mode: str = "SYNTHETIC") -> JsonRecord:
    return {
        "source_name": "Synthetic oracle",
        "declared_license": "Self generated fixture",
        "evidence_mode": mode,
        "instrument": {
            "symbol": "ACME",
            "asset_class": "EQUITY",
            "base_currency": "USD",
            "quote_currency": "USD",
        },
    }


def setup(tmp_path: Path) -> tuple[QualityService, str, str]:
    objects = ImmutableObjectStore(tmp_path / "objects")
    archive = objects.publish(b'{"synthetic_source":"exact synthetic bytes"}')
    env = objects.publish(canonicalize_json({"source_snapshot_digest": archive.digest}))
    registry = RegistryStore.governed(tmp_path / "registry", SCHEMAS)
    instruments = InstrumentRegistry(registry, clock=lambda: dt("2020-01-01T00:00:00Z"))
    instrument = instruments.create(
        {
            "instrument": {
                "asset_class": "EQUITY",
                "venue": "XNYS",
                "base_currency": "USD",
                "quote_currency": "USD",
                "price_precision": 2,
                "quantity_precision": 0,
                "lot_size": "1",
                "tick_size": "0.01",
                "multiplier": "1",
                "timezone": "America/New_York",
                "calendar_id": "XNYS",
                "activity": [{"start": "2020-01-01T00:00:00Z", "end": None}],
                "symbols": [
                    {"symbol": "ACME", "start": "2020-01-01T00:00:00Z", "end": None}
                ],
                "status": "ACTIVE",
            },
            "reason": "Synthetic test",
            "evidence_mode": "SYNTHETIC",
            "source_reference": "Generated oracle",
        }
    )
    return (
        QualityService(
            registry,
            objects,
            SCHEMAS,
            CODE,
            env.digest,
            clock=lambda: dt("2026-01-01T00:00:00Z"),
        ),
        cast(str, cast(dict[str, Any], instrument["record"])["instrument_id"]),
        cast(str, instrument["digest"]),
    )


def ingest(
    service: QualityService,
    identity: str,
    digest: str,
    data: bytes | None = None,
    **kwargs: Any,
) -> JsonRecord:
    return service.ingest_mapped(
        payload() if data is None else data,
        file_format=kwargs.pop("file_format", "CSV"),
        metadata=kwargs.pop("metadata", metadata()),
        mapping=kwargs.pop("mapping", spec()),
        instrument_id=identity,
        instrument_revision_digest=digest,
        calendar_start=date(2025, 1, 6),
        calendar_end=date(2025, 1, 6),
        **kwargs,
    )


def test_real_registry_raw_identity_and_positive_selection(tmp_path: Path) -> None:
    service, identity, digest = setup(tmp_path)
    result = ingest(service, identity, digest)
    assert result["row_count"] == 5
    assert result["admission"] == "SYNTHETIC_SOFTWARE_ONLY"
    assert result["causal_eligible"] is True
    assert result["empirically_validated"] is False
    assert service.objects.read_bytes(cast(str, result["raw_digest"])) == payload()
    selected, data = service.select(
        cast(str, result["dataset_id"]),
        expected_record_digest=cast(str, result["record_digest"]),
        expected_report_digest=cast(str, result["quality_report_digest"]),
    )
    assert selected.instrument_revision_digest == digest
    assert selected.feature_columns[0] == "close"
    table = pq.read_table(pa.BufferReader(data))
    assert table.column("close").to_pylist() == [101] * 5
    assert service.get_dataset(selected.dataset_id) == result
    again = ingest(service, identity, digest)
    assert again["dataset_id"] != result["dataset_id"]
    assert service.get_dataset(selected.dataset_id) == result


def test_cents_and_lots_mapping_independent_oracle() -> None:
    from decimal import Decimal

    table, report = map_rows(
        payload(1),
        "CSV",
        spec(price_scale="0.01", volume_unit="LOTS"),
        lot_size=Decimal(100),
        ingestion_time=datetime.now(UTC),
    )
    assert table.column("close").to_pylist() == [Decimal("1.01")]
    assert table.column("volume").to_pylist() == [200]
    assert report["included_rows"] == [1]


@pytest.mark.parametrize("local", ["2025-11-02T01:30:00", "2025-03-09T02:30:00"])
def test_dst_ambiguous_and_nonexistent_are_rejected(local: str) -> None:
    from decimal import Decimal

    data = payload(1).replace(b"2025-01-06T14:30:00Z", local.encode())
    table, report = map_rows(
        data,
        "CSV",
        spec(timezone="America/New_York"),
        lot_size=Decimal(1),
        ingestion_time=datetime.now(UTC),
    )
    assert table.num_rows == 0
    assert (
        cast(list[dict[str, Any]], report["rejects"])[0]["reason"]
        == "AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIME"
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda x: x.replace(b",102,99,101,", b",100,99,101,"), "OHLC_INCONSISTENT"),
        (
            lambda x: x.replace(b",100,102,99,101,", b",NaN,102,99,101,"),
            "INVALID_ROW_VALUE",
        ),
        (lambda x: x.replace(b"14:31:00Z,2", b"14:30:00Z,2"), "INVALID_AVAILABILITY"),
    ],
)
def test_rejections_retained_without_invalid_raw_persistence(
    tmp_path: Path, mutation: Any, reason: str
) -> None:
    service, identity, digest = setup(tmp_path)
    with pytest.raises(QualityError) as error:
        ingest(service, identity, digest, mutation(payload(1)))
    assert error.value.audit_digest is not None
    report = parse_json_document(service.objects.read_bytes(error.value.audit_digest))
    assert (
        cast(dict[str, Any], report)["dispositions"]["rejects"][0]["reason"] == reason
    )
    assert not any(k.startswith("DATASET-") for k in service.registry.verify_all())


def test_exclusion_requires_explicit_policy_and_missing_minute_blocks(
    tmp_path: Path,
) -> None:
    service, identity, digest = setup(tmp_path)
    data = payload().replace(b"14:32:00Z,100,102", b"14:32:00Z,NaN,102")
    result = ingest(
        service,
        identity,
        digest,
        data,
        mapping=spec(reject_policy="EXCLUDE_WITH_REPORT"),
    )
    report = cast(dict[str, Any], result["quality"])
    assert report["dispositions"]["rejected_rows"] == 1
    assert report["gaps"] == [
        {"start": "2025-01-06T14:31:00.000000Z", "end": "2025-01-06T14:32:00.000000Z"}
    ]
    assert result["admission"] == "BLOCKED"
    with pytest.raises(QualityError, match="NOT_ADMISSIBLE"):
        service.select(
            cast(str, result["dataset_id"]),
            expected_record_digest=cast(str, result["record_digest"]),
            expected_report_digest=cast(str, result["quality_report_digest"]),
        )


def test_unknown_revision_cannot_be_upgraded(tmp_path: Path) -> None:
    service, identity, digest = setup(tmp_path)
    result = ingest(
        service,
        identity,
        digest,
        metadata=metadata("HISTORICAL"),
        mapping=replace(spec(), revision_mode="REQUIRED_UNKNOWN"),
    )
    assert result["admission"] == "BLOCKED"
    assert "REQUIRED_UNKNOWN_REVISION_TIMING" in cast(list[str], result["reasons"])
    with pytest.raises(QualityError, match="HISTORICAL_REVISION_CANNOT_BE_SYNTHETIC"):
        ingest(service, identity, digest, metadata=metadata("HISTORICAL"))


def test_parquet_mapping_roundtrip(tmp_path: Path) -> None:
    from decimal import Decimal

    service, identity, digest = setup(tmp_path)
    table, _ = map_rows(
        payload(), "CSV", spec(), lot_size=Decimal(1), ingestion_time=datetime.now(UTC)
    )
    table = table.select(list(NAMES))
    buffer = pa.BufferOutputStream()
    pq.write_table(table, buffer)
    result = ingest(
        service, identity, digest, buffer.getvalue().to_pybytes(), file_format="PARQUET"
    )
    assert result["causal_eligible"] is True


def test_stale_digest_and_source_archive_tampering(tmp_path: Path) -> None:
    service, identity, digest = setup(tmp_path)
    result = ingest(service, identity, digest)
    with pytest.raises(QualityError, match="STALE_DATASET_SELECTION"):
        service.select(
            cast(str, result["dataset_id"]),
            expected_record_digest=digest,
            expected_report_digest=cast(str, result["quality_report_digest"]),
        )
    environment = cast(
        dict[str, Any],
        parse_json_document(service.objects.read_bytes(service.environment_digest)),
    )
    service.objects.get(environment["source_snapshot_digest"]).path.write_bytes(
        b"tampered"
    )
    with pytest.raises(Exception, match=r"digest|corrupt|mismatch"):
        service.get_dataset(cast(str, result["dataset_id"]))


def reference(result: JsonRecord) -> tuple[str, str, str]:
    return tuple(
        cast(str, result[key])
        for key in ("dataset_id", "record_digest", "quality_report_digest")
    )  # type: ignore[return-value]


def test_causal_aggregation_oracle_future_availability_and_roundtrip(
    tmp_path: Path,
) -> None:
    service, identity, digest = setup(tmp_path)
    result = ingest(service, identity, digest)
    dataset, record_digest, report_digest = reference(result)
    with pytest.raises(QualityError, match="NO_AVAILABLE_COMPLETE"):
        service.aggregate(
            dataset,
            expected_record_digest=record_digest,
            expected_report_digest=report_digest,
            timeframe="5m",
            partial_policy="DROP",
            as_of=dt("2025-01-06T14:34:59Z"),
        )
    grouped = service.aggregate(
        dataset,
        expected_record_digest=record_digest,
        expected_report_digest=report_digest,
        timeframe="5m",
        partial_policy="DROP",
        as_of=dt("2025-01-06T14:35:00Z"),
    )
    assert grouped["dataset_id"] != dataset
    assert grouped["step_ns"] == 300_000_000_000
    assert grouped["row_count"] == 1
    assert service.get_dataset(cast(str, grouped["dataset_id"])) == grouped
    _, data = service.select(
        cast(str, grouped["dataset_id"]),
        expected_record_digest=cast(str, grouped["record_digest"]),
        expected_report_digest=cast(str, grouped["quality_report_digest"]),
    )
    row = pq.read_table(pa.BufferReader(data)).to_pylist()[0]
    assert (row["open"], row["high"], row["low"], row["close"], row["volume"]) == (
        100,
        102,
        99,
        101,
        10,
    )
    assert row["available_at"] == dt("2025-01-06T14:35:00Z")
    assert cast(dict[str, Any], grouped["quality"])["exclusions"]
    assert service.get_dataset(dataset) == result


def test_partition_composition_streams_each_parent_and_preserves_gaps(
    tmp_path: Path,
) -> None:
    service, identity, digest = setup(tmp_path)
    first = ingest(service, identity, digest)
    second = ingest(service, identity, digest, payload().replace(b"14:3", b"14:4"))
    selection = service.compose((reference(first), reference(second)))
    assert selection.total_rows == 10
    assert [s.dataset_id for s in selection.parent_snapshots] == [
        first["dataset_id"],
        second["dataset_id"],
    ]
    batches = list(service.iter_batches(selection.manifest_digest))
    assert [(i, batch.num_rows) for i, batch in batches] == [(0, 5), (1, 5)]
    manifest = cast(
        dict[str, Any],
        parse_json_document(service.objects.read_bytes(selection.manifest_digest)),
    )
    assert manifest["no_implicit_continuity"] is True
    assert manifest["boundaries"][0]["status"] == "PRESERVED_GAP_NO_IMPUTATION"
    with pytest.raises(QualityError, match="PARTITION_OVERLAP_OR_ORDER"):
        service.compose((reference(second), reference(first)))
    with pytest.raises(QualityError, match="PARTITION_SELECTION_LIMIT"):
        service.compose((reference(first), reference(first)))
    changed = {**manifest, "total_rows": 11}
    hostile = service.objects.publish(canonicalize_json(changed))
    with pytest.raises(QualityError, match="PARTITION_MANIFEST_REPLAY"):
        list(service.iter_batches(hostile.digest))


def test_historical_known_revision_remains_exploratory_not_causal(
    tmp_path: Path,
) -> None:
    service, identity, digest = setup(tmp_path)
    lines = payload(1).decode().splitlines()
    data = (
        lines[0] + ",revision_time\n" + lines[1] + ",2025-01-06T14:31:00Z\n"
    ).encode()
    mapping = replace(
        spec(),
        columns=(*spec().columns, ("revision_time", "revision_time")),
        revision_mode="KNOWN",
    )
    result = ingest(
        service,
        identity,
        digest,
        data,
        metadata=metadata("HISTORICAL"),
        mapping=mapping,
    )
    assert result["admission"] == "HISTORICAL_EXPLORATORY"
    assert result["causal_eligible"] is False
    dataset, record_digest, report_digest = reference(result)
    with pytest.raises(QualityError, match="NOT_ADMISSIBLE"):
        service.select(
            dataset,
            expected_record_digest=record_digest,
            expected_report_digest=report_digest,
        )
    selected, _ = service.select(
        dataset,
        expected_record_digest=record_digest,
        expected_report_digest=report_digest,
        purpose="EXPLORATORY_INSPECTION",
    )
    assert selected.causal_eligible is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("quality_status", "APPROVED"),
        ("coverage", {"start": "2025-01-06T14:30:00Z", "end": "2025-01-07T14:35:00Z"}),
        (
            "time_fields",
            {
                "event_time": "open_at",
                "publication_time": "available_at",
                "ingestion_time": "ingestion_time",
                "revision_time": "revision_time",
            },
        ),
    ],
)
def test_schema_valid_registry_rebinding_is_rejected(
    tmp_path: Path, field: str, value: Any
) -> None:
    service, identity, digest = setup(tmp_path)
    result = ingest(service, identity, digest)
    dataset = cast(str, result["dataset_id"])
    head = service.registry.verify_object(dataset)[-1]
    body = {
        key: item
        for key, item in head.record.items()
        if key not in {"dataset_id", "revision", "previous_revision_digest"}
    }
    body[field] = value
    service.registry.append(dataset, head.digest, body)
    with pytest.raises(
        (QualityError, RuntimeError),
        match=r"mismatch|MISMATCH|bind|quality|Quality|differs",
    ):
        service.get_dataset(dataset)


@pytest.mark.parametrize(
    "change",
    [
        {"timezone": "America/Unknown"},
        {"price_scale": "0.1"},
        {"price_currency": "US"},
        {"volume_unit": "GUESSED"},
        {"reject_policy": "SILENT_DROP"},
        {"revision_mode": "KNOWN"},
        {"columns": (("close", "close"),)},
    ],
)
def test_closed_mapping_policy_rejects_ambiguity(change: dict[str, Any]) -> None:
    with pytest.raises(QualityError):
        replace(spec(), **change)


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.replace(b"open_at,", b"open_at,open_at,"),
        lambda x: x.replace(b"open_at", b"unmapped"),
        lambda x: x + b"x" * 2_000_000,
        lambda x: x.replace(b"100", b"A" * 65),
        lambda x: b"\xff" + x,
        lambda x: b"",
    ],
)
def test_hostile_csv_envelope_fails_before_allocation(change: Any) -> None:
    from decimal import Decimal

    with pytest.raises(QualityError):
        map_rows(
            change(payload()),
            "CSV",
            spec(),
            lot_size=Decimal(1),
            ingestion_time=datetime.now(UTC),
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.replace(b"14:30:00Z", b"14:30:30Z"),
        lambda x: x.replace(b"14:30:00Z", b"14:30:00"),
        lambda x: x.replace(b",100,102", b",-1,102"),
        lambda x: x.replace(b",100,102", b",1e9999999,102"),
        lambda x: x.replace(b",99,101,", b",102,101,"),
    ],
)
def test_hostile_rows_have_bounded_reject_codes(change: Any) -> None:
    from decimal import Decimal

    table, report = map_rows(
        change(payload(1)),
        "CSV",
        spec(),
        lot_size=Decimal(1),
        ingestion_time=datetime.now(UTC),
    )
    assert table.num_rows == 0
    assert report["accepted"] is False
    assert len(cast(list[Any], report["rejects"])) == 1


def test_missing_availability_and_calendar_violation_are_not_guessed(
    tmp_path: Path,
) -> None:
    service, identity, digest = setup(tmp_path)
    unknown = ingest(
        service, identity, digest, payload(1).replace(b"2025-01-06T14:31:00Z,2", b",2")
    )
    assert unknown["admission"] == "BLOCKED"
    assert "UNKNOWN_AVAILABILITY" in cast(list[str], unknown["reasons"])
    outside = ingest(service, identity, digest, payload(1).replace(b"T14:", b"T13:"))
    assert outside["admission"] == "BLOCKED"
    assert (
        cast(dict[str, Any], outside["quality"])["failures"][0]["reason"]
        == "OUTSIDE_CALENDAR"
    )


def test_timezone_conversion_rename_and_unknown_column_preservation_policy() -> None:
    from decimal import Decimal

    data = (
        payload(1).replace(b"14:30:00Z", b"09:30:00").replace(b"14:31:00Z", b"09:31:00")
    )
    data = data.replace(b"open_at", b"Start")
    mapping = replace(
        spec(timezone="America/New_York"),
        columns=tuple(
            (target, "Start" if target == "open_at" else source)
            for target, source in spec().columns
        ),
    )
    table, _ = map_rows(
        data, "CSV", mapping, lot_size=Decimal(1), ingestion_time=datetime.now(UTC)
    )
    assert table.column("open_at").to_pylist() == [dt("2025-01-06T14:30:00Z")]


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_mode", "HISTORICAL"),
        ("causal_eligible", False),
        ("step_ns", 1),
        ("row_count", True),
        ("bounds", {"start": "bad", "end": "bad"}),
        ("feature_columns", ("volume",)),
    ],
)
def test_selected_snapshot_refuses_contradictory_claims(
    tmp_path: Path, field: str, value: Any
) -> None:
    service, identity, digest = setup(tmp_path)
    detail = ingest(service, identity, digest)
    dataset, revision, quality = reference(detail)
    selected, _ = service.select(
        dataset, expected_record_digest=revision, expected_report_digest=quality
    )
    with pytest.raises((QualityError, ValueError)):
        replace(selected, **{field: value})


@pytest.mark.parametrize(
    "kind",
    [
        "string_price",
        "nested",
        "metadata",
        "wrong_column",
        "duplicate",
        "empty",
        "too_many",
    ],
)
def test_actual_hostile_parquet_schemas_are_bounded(kind: str) -> None:
    from decimal import Decimal

    table, _ = map_rows(
        payload(1), "CSV", spec(), lot_size=Decimal(1), ingestion_time=datetime.now(UTC)
    )
    table = table.select(list(NAMES))
    if kind == "string_price":
        table = table.set_column(2, "open", pa.array(["100"]))
    elif kind == "nested":
        table = table.set_column(2, "open", pa.array([[100]]))
    elif kind == "metadata":
        table = table.replace_schema_metadata({b"custom": b"untrusted"})
    elif kind == "wrong_column":
        table = table.rename_columns(["alien", *NAMES[1:]])
    elif kind == "duplicate":
        table = table.rename_columns(["close", *NAMES[1:]])
    elif kind == "empty":
        table = table.slice(0, 0)
    elif kind == "too_many":
        table = pa.concat_tables([table] * 100_001)
    output = pa.BufferOutputStream()
    pq.write_table(table, output)
    with pytest.raises(QualityError):
        map_rows(
            output.getvalue().to_pybytes(),
            "PARQUET",
            spec(),
            lot_size=Decimal(1),
            ingestion_time=datetime.now(UTC),
        )


@pytest.mark.parametrize(
    "data",
    [
        b"PAR1",
        b"PAR1" + bytes(10) + b"PAR1",
        b"PAR1" + bytes(8) + (300_000).to_bytes(4, "little") + b"PAR1",
        b"garbage",
    ],
)
def test_malformed_parquet_envelopes_fail_without_arrow_allocation(data: bytes) -> None:
    from decimal import Decimal

    with pytest.raises(QualityError):
        map_rows(
            data,
            "PARQUET",
            spec(),
            lot_size=Decimal(1),
            ingestion_time=datetime.now(UTC),
        )


def test_currency_and_foreign_instrument_are_not_relabelled(tmp_path: Path) -> None:
    service, identity, digest = setup(tmp_path)
    with pytest.raises(QualityError, match="PRICE_CURRENCY_MISMATCH"):
        ingest(service, identity, digest, mapping=replace(spec(), price_currency="EUR"))
    with pytest.raises(QualityError, match="INSTRUMENT_REVISION_NOT_FOUND"):
        ingest(service, identity, "sha256:" + "f" * 64)


def test_utc_naive_conversion_is_explicit_and_replay_stable() -> None:
    from decimal import Decimal

    table, _ = map_rows(
        payload(1).replace(b"Z", b""),
        "CSV",
        spec(timezone="UTC"),
        lot_size=Decimal(1),
        ingestion_time=dt("2026-01-01T00:00:00Z"),
    )
    assert table.column("close_at").to_pylist() == [dt("2025-01-06T14:31:00Z")]
    assert MappingSpec.from_record(spec().to_record()).to_record() == spec().to_record()


def test_partition_value_object_and_manifest_cannot_rebind_parent_evidence(
    tmp_path: Path,
) -> None:
    service, identity, digest = setup(tmp_path)
    first = ingest(service, identity, digest)
    second = ingest(service, identity, digest, payload().replace(b"14:3", b"14:4"))
    selected = service.compose((reference(first), reference(second)))
    for change in (
        {"parent_snapshots": ()},
        {"total_rows": 9},
        {"step_ns": 300_000_000_000},
        {"bounds": {"start": first["bounds"], "end": "invented"}},
        {
            "parent_snapshots": tuple(reversed(selected.parent_snapshots)),
            "bounds": {
                "start": selected.parent_snapshots[-1].bounds["start"],
                "end": selected.parent_snapshots[0].bounds["end"],
            },
        },
    ):
        with pytest.raises(QualityError):
            replace(selected, **change).to_record()
    manifest = cast(
        JsonRecord,
        parse_json_document(service.objects.read_bytes(selected.manifest_digest)),
    )
    manifest_changes: tuple[JsonRecord, ...] = (
        {"schema_version": "foreign"},
        {"parent_snapshots": []},
        {"parent_snapshots": [None]},
    )
    for manifest_change in manifest_changes:
        rewritten = service.objects.publish(
            canonicalize_json({**manifest, **manifest_change})
        )
        with pytest.raises(QualityError):
            list(service.iter_batches(rewritten.digest))
    grouped = service.aggregate(
        cast(str, first["dataset_id"]),
        expected_record_digest=cast(str, first["record_digest"]),
        expected_report_digest=cast(str, first["quality_report_digest"]),
        timeframe="5m",
        partial_policy="DROP",
        as_of=dt("2025-01-06T14:35:00Z"),
    )
    with pytest.raises(QualityError, match="PROFILE_MISMATCH"):
        service.compose((reference(grouped), reference(second)))
    with pytest.raises(QualityError, match="STALE"):
        service.aggregate(
            cast(str, first["dataset_id"]),
            expected_record_digest="sha256:" + "a" * 64,
            expected_report_digest=cast(str, first["quality_report_digest"]),
            timeframe="5m",
            partial_policy="DROP",
            as_of=dt("2025-01-06T14:35:00Z"),
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda r: {**r, "unexpected": 1},
        lambda r: {**r, "columns": []},
        lambda r: {**r, "columns": {"open": 1}},
        lambda r: {**r, "price_scale": 1},
    ],
)
def test_mapping_record_replay_refuses_ambiguous_types(change: Any) -> None:
    with pytest.raises(QualityError):
        MappingSpec.from_record(change(spec().to_record()))


@pytest.mark.parametrize(
    "columns",
    [
        (("bad/path", "source"),) * 6,
        (("open_at", "open_at"),) * 6,
        (*((name, name) for name in NAMES), ("open_bid", "open_bid")),
    ],
)
def test_invalid_mapping_names_duplicate_fields_and_unpaired_quote(
    columns: Any,
) -> None:
    with pytest.raises(QualityError, match="COLUMNS"):
        replace(spec(), columns=columns)


@pytest.mark.parametrize(
    "case",
    [
        "unsupported",
        "empty_csv",
        "invalid_timestamp",
        "duplicate",
        "availability_order",
        "revision",
        "crossed_quote",
    ],
)
def test_explicit_row_reject_report_or_fatal_envelope(case: str) -> None:
    from decimal import Decimal

    data, mapping = payload(2), spec()
    if case == "unsupported":
        with pytest.raises(QualityError, match="UNSUPPORTED_FORMAT"):
            map_rows(
                data,
                "XLSX",
                mapping,
                lot_size=Decimal(1),
                ingestion_time=datetime.now(UTC),
            )
        return
    if case == "empty_csv":
        with pytest.raises(QualityError, match="EMPTY"):
            map_rows(
                (",".join(NAMES) + "\n").encode(),
                "CSV",
                mapping,
                lot_size=Decimal(1),
                ingestion_time=datetime.now(UTC),
            )
        return
    if case == "invalid_timestamp":
        data = payload(1).replace(b"2025-01-06T14:30:00Z", b"not_a_timestamp")
    elif case == "duplicate":
        data = (
            payload(1).decode() + payload(1).decode().splitlines()[1] + "\n"
        ).encode()
    elif case == "availability_order":
        data = data.replace(b"2025-01-06T14:31:00Z,2", b"2025-01-06T14:35:00Z,2")
    else:
        lines = payload(1).decode().splitlines()
        if case == "revision":
            mapping = replace(
                mapping,
                columns=(*mapping.columns, ("revision_time", "revision_time")),
                revision_mode="KNOWN",
            )
            data = (
                lines[0] + ",revision_time\n" + lines[1] + ",2025-01-06T14:32:00Z\n"
            ).encode()
        else:
            mapping = replace(
                mapping,
                columns=(
                    *mapping.columns,
                    ("open_bid", "open_bid"),
                    ("open_ask", "open_ask"),
                ),
            )
            data = (
                lines[0] + ",open_bid,open_ask\n" + lines[1] + ",101,100\n"
            ).encode()
    _, report = map_rows(
        data, "CSV", mapping, lot_size=Decimal(1), ingestion_time=datetime.now(UTC)
    )
    assert report["accepted"] is False
    assert report["rejected_rows"] == 1
    assert (
        len(cast(list[Any], report["included_rows"]))
        + cast(int, report["rejected_rows"])
        == report["input_rows"]
    )


def test_invalid_instrument_grid_blocks_aggregation_and_selection(
    tmp_path: Path,
) -> None:
    service, identity, digest = setup(tmp_path)
    detail = ingest(
        service, identity, digest, payload(1).replace(b",100,102", b",100.001,102")
    )
    assert detail["admission"] == "BLOCKED"
    assert (
        cast(dict[str, Any], detail["quality"])["failures"][0]["reason"]
        == "INSTRUMENT_OR_PRICE_GRID"
    )
    with pytest.raises(QualityError, match="PARENT_BLOCKED"):
        service.aggregate(
            cast(str, detail["dataset_id"]),
            expected_record_digest=cast(str, detail["record_digest"]),
            expected_report_digest=cast(str, detail["quality_report_digest"]),
            timeframe="5m",
            partial_policy="DROP",
            as_of=dt("2025-01-06T14:35:00Z"),
        )
    with pytest.raises(QualityError, match="PURPOSE"):
        service.select(
            cast(str, detail["dataset_id"]),
            expected_record_digest=cast(str, detail["record_digest"]),
            expected_report_digest=cast(str, detail["quality_report_digest"]),
            purpose="AUTO_APPROVE",
        )
