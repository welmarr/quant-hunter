"""Bounded import correctness, hostile data and immutable provenance tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from quant_hunter.config import JsonRecord
from quant_hunter.config.canonical import canonicalize_json, parse_json_document
from quant_hunter.data import DerivedDataIntegrityError
from quant_hunter.identity import RegistryStore
from quant_hunter.imports import ImportService, ImportValidationError, validation
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.storage import (
    ImmutableObjectStore,
    ObjectCorruptionError,
    ObjectStoreError,
)

SCHEMAS = Path(__file__).parents[1] / "schemas" / "v1"
CODE = "7346cf4f79ca5897777c0118f8cf4c2292be929e"
HEADER = "open_at,close_at,available_at,open_bid,open_ask,close"
ROW1 = "2025-01-01T12:00:00Z,2025-01-01T13:00:00Z,2025-01-01T13:00:00Z,100,101,100.5"
ROW2 = "2025-01-02T12:00:00Z,2025-01-02T13:00:00Z,2025-01-02T13:00:00Z,101,102,101.5"
CSV = (HEADER + "\n" + ROW1 + "\n" + ROW2 + "\n").encode()


def metadata() -> JsonRecord:
    return {
        "source_name": "Owner supplied sample",
        "declared_license": "Research only; owner declaration",
        "evidence_mode": "HISTORICAL",
        "instrument": {
            "symbol": "ACME",
            "asset_class": "EQUITY",
            "base_currency": "USD",
            "quote_currency": "USD",
        },
    }


def service(tmp_path: Path) -> ImportService:
    objects = ImmutableObjectStore(tmp_path / "objects")
    environment = objects.publish(b'{"test_environment":"offline"}')
    return ImportService(
        RegistryStore.governed(tmp_path / "registry", SCHEMAS),
        objects,
        SCHEMAS,
        CODE,
        environment.digest,
    )


def parquet(table: Any = None, *, compression: str = "SNAPPY") -> bytes:
    if table is None:
        table, _rows = validation.decode(CSV, "CSV")
    buffer = pa.BufferOutputStream()
    pq.write_table(table, buffer, compression=compression)
    return cast(bytes, buffer.getvalue().to_pybytes())


@pytest.mark.parametrize("format_name", ["CSV", "PARQUET"])
def test_import_retains_exact_bytes_and_governed_derived_graph(
    tmp_path: Path, format_name: str
) -> None:
    importer = service(tmp_path)
    payload = CSV if format_name == "CSV" else parquet()
    result = importer.import_bytes(
        payload, file_format=format_name, metadata=metadata()
    )
    assert result["row_count"] == 2
    assert result["raw_digest"] == sha256_bytes(payload)
    assert (
        result["raw_digest"]
        != result["normalized_digest"]
        != result["logical_fingerprint"]
    )
    assert importer.objects.read_bytes(result["raw_digest"]) == payload
    assert result["quality"] == "STRUCTURAL_PASS_REVIEW_PENDING"
    assert result["empirically_validated"] is False
    assert result["host_enforced"] is False
    assert result["metadata"] == validation.metadata_document(metadata())
    assert importer.list_datasets() == [result]
    assert service(tmp_path).get_dataset(cast(str, result["dataset_id"])) == result
    records = importer.registry.verify_all()
    assert len(records) == 3
    assert records[cast(str, result["source_id"])][0].record["status"] == "CANDIDATE"
    raw = records[cast(str, result["raw_dataset_id"])]
    assert raw[0].record["layer"] == "raw_landing"
    normalized = pq.read_table(
        pa.BufferReader(
            importer.objects.read_bytes(cast(str, result["normalized_digest"]))
        )
    )
    assert (
        normalized.column("revision_time_status").to_pylist()
        == ["REQUIRED_UNKNOWN"] * 2
    )
    assert normalized.column("revision_time").to_pylist() == [None, None]
    assert normalized.schema.field("ingestion_time").type.tz == "UTC"
    assert normalized.column("ingestion_time").null_count == 0


def test_corrections_and_reimports_never_overwrite(tmp_path: Path) -> None:
    importer = service(tmp_path)
    first = importer.import_bytes(CSV, file_format="CSV", metadata=metadata())
    again = importer.import_bytes(CSV, file_format="CSV", metadata=metadata())
    corrected = importer.import_bytes(
        CSV.replace(b"100.5", b"100.6"),
        file_format="CSV",
        metadata=metadata(),
        corrects_dataset_id=cast(str, first["dataset_id"]),
        correction_reason="Provider supplied corrected closing value",
    )
    assert (
        len({cast(str, item["dataset_id"]) for item in (first, again, corrected)}) == 3
    )
    assert first["raw_digest"] == again["raw_digest"] != corrected["raw_digest"]
    assert corrected["corrects_dataset_id"] == first["dataset_id"]
    assert importer.get_dataset(cast(str, first["dataset_id"])) == first
    assert len(importer.list_datasets()) == 3


@pytest.mark.parametrize(
    "payload,code",
    [
        (b"", "RAW_SIZE_LIMIT"),
        (b"x" * 2_000_001, "RAW_SIZE_LIMIT"),
        (CSV.replace(b"open_bid", b"close"), "DUPLICATE_UNKNOWN_OR_MISSING_COLUMN"),
        (CSV.replace(b",100,101,", b",102,101,"), "CROSSED_QUOTE"),
        (CSV.replace(b",100,101,", b",NaN,101,"), "INVALID_DECIMAL"),
        (CSV.replace(b",100,101,", b",0,101,"), "DECIMAL_OUT_OF_RANGE"),
        (CSV.replace(b",100,101,", b",,101,"), "INVALID_CSV_ROW"),
        (
            (HEADER + "\n" + ROW1 + "\n" + ROW1).encode(),
            "DUPLICATE_OVERLAPPING_OR_UNSORTED_BAR",
        ),
        (
            (HEADER + "\n" + ROW2 + "\n" + ROW1).encode(),
            "DUPLICATE_OVERLAPPING_OR_UNSORTED_BAR",
        ),
        (
            CSV.replace(b"12:00:00Z", b"12:00:00"),
            "TIMESTAMP_REQUIRES_EXPLICIT_TIMEZONE",
        ),
        (
            CSV.replace(b"13:00:00Z,100", b"12:59:00Z,100"),
            "BAR_TIME_OR_AVAILABILITY_ORDER",
        ),
        (CSV.replace(b",100,101,", b",0.0000000000001,101,"), "DECIMAL_OUT_OF_RANGE"),
        ((HEADER + "\n").encode(), "EMPTY_DATASET"),
        (b"\xff", "CSV_REQUIRES_UTF8"),
        (CSV + b"\x00", "CSV_NUL_BYTE"),
    ],
    ids=[
        "empty",
        "oversized",
        "duplicate-field",
        "crossed",
        "nan",
        "zero",
        "null",
        "duplicate-bar",
        "unsorted",
        "naive-time",
        "premature-availability",
        "excess-precision",
        "no-rows",
        "encoding",
        "nul",
    ],
)
def test_bad_csv_retains_sanitized_failure_without_raw(
    tmp_path: Path, payload: bytes, code: str
) -> None:
    importer = service(tmp_path)
    with pytest.raises(ImportValidationError, match=code) as caught:
        importer.import_bytes(payload, file_format="CSV", metadata=metadata())
    assert caught.value.audit_digest is not None
    audit = cast(
        JsonRecord,
        parse_json_document(importer.objects.read_bytes(caught.value.audit_digest)),
    )
    assert audit["error_code"] == code
    assert audit["raw_retained"] is False
    assert importer.registry.verify_all() == {}


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_name", "../traversal"),
        ("source_name", "https://example.invalid"),
        ("declared_license", "token=must-not-persist"),
        ("evidence_mode", "LIVE_READ_ONLY"),
        ("api_key", "must-not-persist"),
        ("source_name", " "),
    ],
)
def test_metadata_rejected_without_sensitive_text_retention(
    tmp_path: Path, field: str, value: str
) -> None:
    importer = service(tmp_path)
    details = metadata()
    details[field] = value
    with pytest.raises(ImportValidationError):
        importer.import_bytes(CSV, file_format="CSV", metadata=details)
    assert all(
        b"must-not-persist" not in path.read_bytes()
        for path in importer.objects.objects_root.rglob("*")
        if path.is_file()
    )


def test_fx_currency_identity_quantity_and_optional_values(tmp_path: Path) -> None:
    importer = service(tmp_path)
    details = metadata()
    details["evidence_mode"] = "SYNTHETIC"
    instrument: JsonRecord = {
        "symbol": "EUR/USD",
        "asset_class": "FX_SPOT",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "quantity_step": "0.1",
    }
    details["instrument"] = instrument
    extended = (
        HEADER + ",high,low,volume\n" + ROW1 + ",102,99,0\n" + ROW2 + ",103,100,12.5"
    ).encode()
    result = importer.import_bytes(extended, file_format="CSV", metadata=details)
    assert result["columns"] == [*validation.REQUIRED, "high", "low", "volume"]
    assert cast(JsonRecord, result["metadata"])["evidence_mode"] == "SYNTHETIC"
    for key, value in [
        ("quote_currency", "XYZ"),
        ("base_currency", "USD"),
        ("symbol", "GBP/USD"),
        ("quantity_step", "0"),
    ]:
        bad = deepcopy(details)
        cast(JsonRecord, bad["instrument"])[key] = value
        with pytest.raises(ImportValidationError):
            importer.import_bytes(extended, file_format="CSV", metadata=bad)


@pytest.mark.parametrize(
    "suffix,code",
    [
        ("100,99,1", "HIGH_BELOW_PRICE"),
        ("102,100.1,1", "LOW_ABOVE_PRICE"),
        ("102,99,-1", "INVALID_DECIMAL"),
    ],
)
def test_optional_ohlc_and_volume_are_not_ignored(
    tmp_path: Path, suffix: str, code: str
) -> None:
    payload = (HEADER + ",high,low,volume\n" + ROW1 + "," + suffix).encode()
    with pytest.raises(ImportValidationError, match=code):
        service(tmp_path).import_bytes(payload, file_format="CSV", metadata=metadata())


def test_timezone_normalization_does_not_change_available_instant(
    tmp_path: Path,
) -> None:
    payload = CSV.replace(b"12:00:00Z", b"07:00:00-05:00").replace(
        b"13:00:00Z", b"08:00:00-05:00"
    )
    result = service(tmp_path).import_bytes(
        payload, file_format="CSV", metadata=metadata()
    )
    assert cast(JsonRecord, result["bounds"])["start"] == "2025-01-01T12:00:00.000000Z"


@pytest.mark.parametrize(
    "kind",
    ["raw_digest", "normalized_digest", "lineage_digest", "configuration_digest"],
)
def test_any_immutable_tampering_invalidates_import(tmp_path: Path, kind: str) -> None:
    importer = service(tmp_path)
    result = importer.import_bytes(CSV, file_format="CSV", metadata=metadata())
    importer.objects.object_path(cast(str, result[kind])).write_bytes(b"corrupted")
    with pytest.raises(ObjectCorruptionError):
        importer.get_dataset(cast(str, result["dataset_id"]))


def test_parquet_fixed_width_guard_rejects_dictionary_expansion(tmp_path: Path) -> None:
    # Large strings can expand after dictionary decode. They never reach decode.
    huge = pa.table({name: ["x" * 10000] * 300 for name in validation.REQUIRED})
    payload = parquet(huge, compression="ZSTD")
    assert len(payload) < validation.MAX_RAW_BYTES
    with pytest.raises(
        ImportValidationError, match="PARQUET_FIXED_WIDTH_TYPES_REQUIRED"
    ):
        service(tmp_path).import_bytes(
            payload, file_format="PARQUET", metadata=metadata()
        )


def test_parquet_metadata_limits_precede_batch_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = parquet()
    monkeypatch.setattr(validation, "MAX_DECODED_BYTES", 128)
    with pytest.raises(ImportValidationError, match="PARQUET_EXPANSION_LIMIT"):
        service(tmp_path).import_bytes(
            payload, file_format="PARQUET", metadata=metadata()
        )


def test_parquet_schema_nulls_timestamp_and_envelope(tmp_path: Path) -> None:
    importer = service(tmp_path)
    table, _rows = validation.decode(CSV, "CSV")
    bad = table.set_column(
        0, "open_at", pa.array([datetime(2025, 1, 1), datetime(2025, 1, 2)])
    )
    with pytest.raises(
        ImportValidationError, match="PARQUET_FIXED_WIDTH_TYPES_REQUIRED"
    ):
        importer.import_bytes(parquet(bad), file_format="PARQUET", metadata=metadata())
    null = table.set_column(3, "open_bid", pa.array([None, 101.0], type=pa.float64()))
    with pytest.raises(ImportValidationError, match="INVALID_NUMERIC_TYPE"):
        importer.import_bytes(parquet(null), file_format="PARQUET", metadata=metadata())
    for payload in (b"not parquet", b"PAR1" + b"x" * 8 + b"PAR1", parquet()[:-2]):
        with pytest.raises(ImportValidationError):
            importer.import_bytes(payload, file_format="PARQUET", metadata=metadata())


def test_import_list_never_exposes_unrelated_dataset_or_source(tmp_path: Path) -> None:
    importer = service(tmp_path)
    result = importer.import_bytes(CSV, file_format="CSV", metadata=metadata())
    with pytest.raises(ImportValidationError, match="NOT_AN_IMPORTED_DATASET"):
        importer.get_dataset(cast(str, result["raw_dataset_id"]))
    with pytest.raises(ImportValidationError, match="INVALID_DATASET_ID"):
        importer.get_dataset(cast(str, result["source_id"]))
    assert [item["dataset_id"] for item in importer.list_datasets()] == [
        result["dataset_id"]
    ]


def test_unrepresentable_coverage_is_audited_before_identity_allocation(
    tmp_path: Path,
) -> None:
    payload = (
        HEADER
        + "\n9999-12-31T23:59:59Z,9999-12-31T23:59:59.999999Z,9999-12-31T23:59:59.999999Z,1,2,1"
    ).encode()
    importer = service(tmp_path)
    with pytest.raises(ImportValidationError, match="EXCLUSIVE_COVERAGE") as caught:
        importer.import_bytes(payload, file_format="CSV", metadata=metadata())
    assert caught.value.audit_digest is not None
    assert importer.registry.verify_all() == {}


def test_corrections_require_compatible_identity_and_safe_reason(
    tmp_path: Path,
) -> None:
    importer = service(tmp_path)
    first = importer.import_bytes(CSV, file_format="CSV", metadata=metadata())
    dataset_id = cast(str, first["dataset_id"])
    for previous, reason, details in [
        (dataset_id, None, metadata()),
        (None, "Correction", metadata()),
        (dataset_id, "token=must-not-persist", metadata()),
        (dataset_id, "Correction", {**metadata(), "evidence_mode": "SYNTHETIC"}),
    ]:
        with pytest.raises(ImportValidationError):
            importer.import_bytes(
                CSV,
                file_format="CSV",
                metadata=details,
                corrects_dataset_id=previous,
                correction_reason=reason,
            )
    assert len(importer.list_datasets()) == 1
    assert all(
        b"must-not-persist" not in path.read_bytes()
        for path in importer.objects.objects_root.rglob("*")
        if path.is_file()
    )


@pytest.mark.parametrize("damaged", [False, True])
def test_executed_source_snapshot_is_required_on_construction_and_reads(
    tmp_path: Path, damaged: bool
) -> None:
    importer = service(tmp_path)
    snapshot = importer.objects.publish(b'{"source":"immutable exact test source"}')
    environment = importer.objects.publish(
        canonicalize_json({"source_snapshot_digest": snapshot.digest})
    )
    importer = ImportService(
        importer.registry, importer.objects, SCHEMAS, CODE, environment.digest
    )
    imported = importer.import_bytes(CSV, file_format="CSV", metadata=metadata())
    if damaged:
        snapshot.path.write_bytes(b"corrupted")
    else:
        snapshot.path.unlink()
    with pytest.raises(ObjectStoreError):
        importer.get_dataset(cast(str, imported["dataset_id"]))
    with pytest.raises(ObjectStoreError):
        ImportService(
            importer.registry, importer.objects, SCHEMAS, CODE, environment.digest
        )


@pytest.mark.parametrize("claim", ["coverage", "time_fields", "source_ids"])
def test_schema_valid_rehashed_registry_cannot_override_actual_import_claims(
    tmp_path: Path, claim: str
) -> None:
    importer = service(tmp_path)
    imported = importer.import_bytes(CSV, file_format="CSV", metadata=metadata())
    object_id = cast(str, imported["dataset_id"])
    original = importer.registry.verify_object(object_id)[-1]
    hostile = deepcopy(original.record)
    if claim == "coverage":
        cast(JsonRecord, hostile["coverage"])["start"] = "2024-01-01T00:00:00Z"
    elif claim == "time_fields":
        cast(JsonRecord, hostile["time_fields"])["publication_time"] = "open_at"
    else:
        foreign = importer.import_bytes(CSV, file_format="CSV", metadata=metadata())
        hostile["source_ids"] = [foreign["source_id"]]
    for key in ("dataset_id", "revision", "previous_revision_digest"):
        hostile.pop(key)
    importer.registry.append(object_id, original.digest, hostile)
    assert len(importer.registry.verify_object(object_id)) == 2
    with pytest.raises((ObjectCorruptionError, DerivedDataIntegrityError)):
        importer.get_dataset(object_id)


@pytest.mark.parametrize("codec", ["NONE", "SNAPPY", "GZIP", "ZSTD"])
@pytest.mark.parametrize("page_version", ["1.0", "2.0"])
def test_supported_parquet_pages_preserve_typed_observations(
    codec: str, page_version: str
) -> None:
    table, rows = validation.decode(CSV, "CSV")
    buffer = pa.BufferOutputStream()
    pq.write_table(
        table,
        buffer,
        compression=codec,
        data_page_version=page_version,
        row_group_size=1,
        write_page_checksum=True,
    )
    decoded, observed = validation.decode(buffer.getvalue().to_pybytes(), "PARQUET")
    assert decoded.equals(table)
    assert observed == rows


def unsigned(value: int) -> bytes:
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def page_header(*, size: int = 16, compressed: int = 18, count: int = 2) -> bytes:
    # Compact protocol dictionary PageHeader with no data decompression needed.
    return (
        b"\x15\x04\x15"
        + unsigned(size << 1)
        + b"\x15"
        + unsigned(compressed << 1)
        + b"\x4c\x15"
        + unsigned(count << 1)
        + b"\x15\x00\x00\x00"
    )


@pytest.mark.parametrize(
    "header,code",
    [
        (page_header(size=16_000_001), "PARQUET_PAGE_EXPANSION_LIMIT"),
        (page_header(compressed=2_000_000), "PARQUET_PAGE_BODY_RANGE"),
        (page_header(count=100_001), "PARQUET_PAGE_VALUE_COUNT"),
        (b"\x00", "PARQUET_PAGE_REQUIRED_FIELDS"),
        (b"\x19", "PARQUET_PAGE_HEADER_UNSUPPORTED_TYPE"),
        (b"\x15" + b"\xff" * 10, "PARQUET_PAGE_HEADER_INTEGER_LIMIT"),
        (b"\x1c" * 6, "PARQUET_PAGE_HEADER_DEPTH_LIMIT"),
        (b"\x15\x04\x05\x02\x00", "PARQUET_PAGE_HEADER_FIELDS"),
    ],
    ids=[
        "expansion",
        "body-range",
        "value-count",
        "missing-field",
        "container",
        "varint",
        "depth",
        "duplicate-field",
    ],
)
def test_forged_page_headers_rejected_despite_valid_small_footer(
    header: bytes, code: str
) -> None:
    payload = bytearray(parquet())
    info = pq.ParquetFile(pa.BufferReader(payload)).metadata
    offset = info.row_group(0).column(0).dictionary_page_offset
    payload[offset : offset + len(header)] = header
    # Footer remains independently parseable and within its advertised budget.
    assert pq.ParquetFile(pa.BufferReader(payload)).metadata.num_rows == 2
    with pytest.raises(ImportValidationError, match=code):
        validation.decode(bytes(payload), "PARQUET")


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("open_at", "2025-02-31T12:00:00Z", "INVALID_TIMESTAMP"),
        ("open_at", "0001-01-01T00:00:00+01:00", "INVALID_TIMESTAMP"),
        ("open_bid", "1e99999", "DECIMAL_OUT_OF_RANGE"),
        ("open_bid", "Infinity", "INVALID_DECIMAL"),
        ("open_bid", "-1", "INVALID_DECIMAL"),
    ],
)
def test_typed_validation_rejects_extremes(field: str, value: str, code: str) -> None:
    row = ROW1.split(",")
    row[list(validation.REQUIRED).index(field)] = value
    with pytest.raises(ImportValidationError, match=code):
        validation.decode((HEADER + "\n" + ",".join(row)).encode(), "CSV")


def test_input_limits_formats_and_availability_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ImportValidationError, match="UNSUPPORTED_FORMAT"):
        validation.decode(CSV, "JSON")
    with pytest.raises(ImportValidationError, match="INVALID_CSV_ENCODING"):
        validation.decode((HEADER + '\n"unterminated').encode(), "CSV")
    with pytest.raises(ImportValidationError, match="UNSORTED_AVAILABILITY"):
        validation.decode(
            CSV.replace(b"2025-01-01T13:00:00Z,100", b"2025-01-03T13:00:00Z,100"), "CSV"
        )
    parquet_payload = parquet()
    monkeypatch.setattr(validation, "MAX_ROWS", 1)
    with pytest.raises(ImportValidationError, match="ROW_LIMIT"):
        validation.decode(CSV, "CSV")
    with pytest.raises(ImportValidationError, match="PARQUET_ROW_LIMIT"):
        validation.decode(parquet_payload, "PARQUET")


@pytest.mark.parametrize(
    "field,value", [(2, -1), (2, 3), (3, 1), (5, -1), (5, 1000), (6, 1)]
)
def test_forged_v2_level_sections_fail_before_arrow_decode(
    field: int, value: int
) -> None:
    payload = bytearray(parquet())
    info = pq.ParquetFile(pa.BufferReader(payload)).metadata
    offset = info.row_group(0).column(0).data_page_offset
    values = {1: 2, 2: 0, 3: 2, 4: 0, 5: 0, 6: 0}
    values[field] = value
    nested = (
        b"".join(
            b"\x15" + unsigned((number << 1) ^ (number >> 63))
            for number in values.values()
        )
        + b"\x00"
    )
    header = b"\x15\x06\x15\x10\x15\x10\x5c" + nested + b"\x00"
    payload[offset : offset + len(header)] = header
    with pytest.raises(ImportValidationError, match="PARQUET_V2_LEVEL_OR_ROW_LIMIT"):
        validation.decode(bytes(payload), "PARQUET")


def test_page_byte_sizes_must_match_unchanged_footer() -> None:
    payload = bytearray(parquet())
    info = pq.ParquetFile(pa.BufferReader(payload)).metadata
    offset = info.row_group(0).column(0).dictionary_page_offset
    assert payload[offset : offset + 3] == b"\x15\x04\x15"
    assert payload[offset + 3] < 126
    payload[offset + 3] += 2
    with pytest.raises(ImportValidationError, match="PARQUET_PAGE_FOOTER_MISMATCH"):
        validation.decode(bytes(payload), "PARQUET")


@pytest.mark.parametrize(
    "change",
    [
        {"source_name": []},
        {"extra": "unrecognized"},
        {"instrument": []},
        {"instrument": {"symbol": "ACME"}},
        {
            "instrument": {
                "symbol": "acme",
                "asset_class": "EQUITY",
                "base_currency": "USD",
                "quote_currency": "USD",
            }
        },
        {
            "instrument": {
                "symbol": "ACME",
                "asset_class": "FUTURE",
                "base_currency": "USD",
                "quote_currency": "USD",
            }
        },
        {
            "instrument": {
                "symbol": "AC/ME",
                "asset_class": "EQUITY",
                "base_currency": "USD",
                "quote_currency": "USD",
            }
        },
    ],
)
def test_unknown_and_ambiguous_metadata_schema_rejected(change: JsonRecord) -> None:
    with pytest.raises(ImportValidationError):
        validation.metadata_document({**metadata(), **change})


def test_parquet_unknown_metadata_and_malformed_decoding_fail_closed() -> None:
    table, _rows = validation.decode(CSV, "CSV")
    with pytest.raises(
        ImportValidationError, match="PARQUET_CUSTOM_METADATA_UNSUPPORTED"
    ):
        validation.decode(
            parquet(table.replace_schema_metadata({b"token": b"do-not-retain"})),
            "PARQUET",
        )
    malformed = bytearray(parquet())
    footer = int.from_bytes(malformed[-8:-4], "little")
    malformed[-8 - footer] = 0xFF
    with pytest.raises(ImportValidationError, match="INVALID_PARQUET"):
        validation.decode(bytes(malformed), "PARQUET")


def test_bad_runtime_types_and_decoded_size_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ImportValidationError, match="INVALID_TIMESTAMP_TYPE"):
        validation.timestamp(None)
    with pytest.raises(
        ImportValidationError, match="TIMESTAMP_REQUIRES_EXPLICIT_TIMEZONE"
    ):
        validation.timestamp(datetime(2025, 1, 1))
    with pytest.raises(ImportValidationError, match="INVALID_NUMERIC_TYPE"):
        validation.decimal_value(True)
    with pytest.raises(ImportValidationError, match="INVALID_CSV_HEADER"):
        validation.decode(b'"unfinished', "CSV")
    monkeypatch.setattr(validation, "MAX_DECODED_BYTES", 1)
    with pytest.raises(ImportValidationError, match="DECODED_SIZE_LIMIT"):
        validation.decode(CSV, "CSV")
