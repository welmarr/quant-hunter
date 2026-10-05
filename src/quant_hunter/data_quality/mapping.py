"""Explicit bounded mapping, timezone conversion, units and row dispositions."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.imports.page_limits import verify_pages
from quant_hunter.imports.validation import decimal_value, timestamp
from quant_hunter.markets.calendars import _new_york
from quant_hunter.storage.security import reject_secret_text_values

from .models import QualityError

MAX_RAW = 2_000_000
MAX_ROWS = 100_000
MAX_DECODED = 16_000_000
REQUIRED = ("open_at", "close_at", "open", "high", "low", "close")
OPTIONAL = ("available_at", "revision_time", "open_bid", "open_ask", "volume")
TIMES = ("open_at", "close_at", "available_at", "revision_time")
DECIMALS = ("open", "high", "low", "close", "open_bid", "open_ask", "volume")


@dataclass(frozen=True, slots=True)
class MappingSpec:
    """Target/source names; every transformation is explicit and reproducible."""

    columns: tuple[tuple[str, str], ...]
    timezone: str = "OFFSET_REQUIRED"
    price_scale: str = "1"
    price_currency: str = "USD"
    volume_unit: str = "UNITS"
    reject_policy: str = "REJECT_DATASET"
    revision_mode: str = "REQUIRED_UNKNOWN"

    def __post_init__(self) -> None:
        if not isinstance(self.columns, tuple) or not 6 <= len(self.columns) <= 11:
            raise QualityError("MAPPING_COLUMNS_INVALID")
        if any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or any(
                not isinstance(v, str)
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", v) is None
                for v in pair
            )
            for pair in self.columns
        ):
            raise QualityError("MAPPING_COLUMNS_INVALID")
        targets, sources = zip(*self.columns, strict=True)
        if (
            len(set(targets)) != len(targets)
            or len(set(sources)) != len(sources)
            or not set(REQUIRED) <= set(targets)
            or set(targets) - set(REQUIRED + OPTIONAL)
            or ("open_bid" in targets) != ("open_ask" in targets)
        ):
            raise QualityError("MAPPING_COLUMNS_INVALID")
        if (
            self.timezone not in {"OFFSET_REQUIRED", "UTC", "America/New_York"}
            or self.price_scale not in {"1", "0.01", "0.0001"}
            or self.volume_unit not in {"UNITS", "LOTS"}
            or self.reject_policy not in {"REJECT_DATASET", "EXCLUDE_WITH_REPORT"}
            or self.revision_mode
            not in {"REQUIRED_UNKNOWN", "KNOWN", "SYNTHETIC_NOT_APPLICABLE"}
            or not isinstance(self.price_currency, str)
            or re.fullmatch(r"[A-Z]{3}", self.price_currency) is None
            or (self.revision_mode == "KNOWN") != ("revision_time" in targets)
        ):
            raise QualityError("MAPPING_POLICY_INVALID")

    def to_record(self) -> JsonRecord:
        return {
            "columns": {target: source for target, source in self.columns},
            "timezone": self.timezone,
            "price_scale": self.price_scale,
            "price_currency": self.price_currency,
            "volume_unit": self.volume_unit,
            "reject_policy": self.reject_policy,
            "revision_mode": self.revision_mode,
        }

    @classmethod
    def from_record(cls, record: JsonRecord) -> MappingSpec:
        if set(record) != {
            "columns",
            "timezone",
            "price_scale",
            "price_currency",
            "volume_unit",
            "reject_policy",
            "revision_mode",
        }:
            raise QualityError("MAPPING_POLICY_INVALID")
        columns = record["columns"]
        if not isinstance(columns, dict) or any(
            not isinstance(v, str) for v in columns.values()
        ):
            raise QualityError("MAPPING_COLUMNS_INVALID")
        if any(not isinstance(record[k], str) for k in record if k != "columns"):
            raise QualityError("MAPPING_POLICY_INVALID")
        return cls(
            tuple((k, cast(str, v)) for k, v in sorted(columns.items())),
            *(
                cast(str, record[k])
                for k in (
                    "timezone",
                    "price_scale",
                    "price_currency",
                    "volume_unit",
                    "reject_policy",
                    "revision_mode",
                )
            ),
        )


def _time(value: object, zone: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and len(value) <= 64:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise QualityError("INVALID_TIMESTAMP") from None
    else:
        raise QualityError("INVALID_TIMESTAMP")
    if parsed.tzinfo is not None:
        return timestamp(parsed)
    if zone == "OFFSET_REQUIRED":
        raise QualityError("TIMEZONE_REQUIRED")
    if zone == "UTC":
        return parsed.replace(tzinfo=UTC)
    tz = _new_york()
    first, second = parsed.replace(tzinfo=tz, fold=0), parsed.replace(tzinfo=tz, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise QualityError("AMBIGUOUS_OR_NONEXISTENT_LOCAL_TIME")
    result = first.astimezone(UTC)
    if result.astimezone(tz).replace(tzinfo=None) != parsed:
        raise QualityError("NONEXISTENT_LOCAL_TIME")
    return result


def _input_rows(
    payload: bytes, file_format: str, spec: MappingSpec
) -> list[dict[str, object]]:
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_RAW:
        raise QualityError("RAW_SIZE_LIMIT")
    names = {source for _, source in spec.columns}
    if file_format == "CSV":
        try:
            content = payload.decode("utf-8-sig", errors="strict")
            reject_secret_text_values(content, "mapped data")
            reader = csv.reader(io.StringIO(content, newline=""), strict=True)
            header = next(reader)
            if len(header) != len(set(header)) or set(header) != names:
                raise QualityError("HEADER_MAPPING_MISMATCH")
            rows: list[dict[str, object]] = []
            for raw in reader:
                if (
                    len(rows) >= MAX_ROWS
                    or len(raw) != len(header)
                    or any(len(x) > 64 or "\x00" in x for x in raw)
                ):
                    raise QualityError("CSV_SHAPE_OR_SIZE_LIMIT")
                rows.append(dict(zip(header, raw, strict=True)))
            return rows
        except (UnicodeError, csv.Error, StopIteration, ValueError) as error:
            if isinstance(error, QualityError):
                raise
            raise QualityError("INVALID_OR_SENSITIVE_CSV") from None
    if file_format != "PARQUET":
        raise QualityError("UNSUPPORTED_FORMAT")
    if (
        len(payload) < 12
        or payload[:4] != b"PAR1"
        or payload[-4:] != b"PAR1"
        or not 0
        < int.from_bytes(payload[-8:-4], "little")
        <= min(262_144, len(payload) - 12)
    ):
        raise QualityError("PARQUET_ENVELOPE_LIMIT")
    try:
        reader_pq = pq.ParquetFile(
            pa.BufferReader(payload),
            thrift_string_size_limit=262_144,
            thrift_container_size_limit=10_000,
            page_checksum_verification=True,
        )
        info, schema = reader_pq.metadata, reader_pq.schema_arrow
        if (
            schema.metadata
            or any(f.metadata for f in schema)
            or len(schema.names) != len(set(schema.names))
            or set(schema.names) != names
        ):
            raise QualityError("PARQUET_MAPPING_OR_METADATA")
        if not 0 < info.num_rows <= MAX_ROWS or not 0 < info.num_row_groups <= 256:
            raise QualityError("PARQUET_ROW_LIMIT")
        target_by_source = {source: target for target, source in spec.columns}
        for field in schema:
            kind = field.type
            valid = (
                (pa.types.is_timestamp(kind) and kind.unit in {"s", "ms", "us"})
                if target_by_source[field.name] in TIMES
                else (
                    pa.types.is_integer(kind)
                    or pa.types.is_floating(kind)
                    or pa.types.is_decimal128(kind)
                )
            )
            if not valid:
                raise QualityError("PARQUET_FIXED_WIDTH_REQUIRED")
        expanded = compressed = 0
        for g in range(info.num_row_groups):
            group = info.row_group(g)
            if group.num_rows <= 0 or group.num_columns != len(names):
                raise QualityError("PARQUET_INVALID_GROUP")
            for c in range(group.num_columns):
                chunk = group.column(c)
                if (
                    chunk.file_path
                    or chunk.compression
                    not in {"UNCOMPRESSED", "SNAPPY", "GZIP", "ZSTD", "LZ4", "LZ4_RAW"}
                    or min(chunk.total_compressed_size, chunk.total_uncompressed_size)
                    < 0
                ):
                    raise QualityError("PARQUET_EXTERNAL_OR_CODEC")
                expanded += chunk.total_uncompressed_size
                compressed += chunk.total_compressed_size
        if expanded > MAX_DECODED or expanded > max(65_536, compressed * 128):
            raise QualityError("PARQUET_EXPANSION_LIMIT")
        verify_pages(payload, info, maximum=MAX_DECODED)
        output: list[dict[str, object]] = []
        decoded = 0
        for batch in reader_pq.iter_batches(batch_size=1024, use_threads=False):
            decoded += batch.nbytes
            if decoded > MAX_DECODED or len(output) + batch.num_rows > MAX_ROWS:
                raise QualityError("PARQUET_DECODE_LIMIT")
            values: dict[str, list[object]] = {}
            for idx, name in enumerate(batch.schema.names):
                col = batch.column(idx)
                if target_by_source[name] in TIMES and col.type.tz is not None:
                    values[name] = [
                        v.replace(tzinfo=UTC) if v is not None else None
                        for v in col.cast(pa.timestamp("us")).to_pylist()
                    ]
                else:
                    values[name] = col.to_pylist()
            output.extend(
                {name: vals[i] for name, vals in values.items()}
                for i in range(batch.num_rows)
            )
        if len(output) != info.num_rows:
            raise QualityError("PARQUET_ROW_COUNT_MISMATCH")
        return output
    except (pa.ArrowException, OSError, ValueError) as error:
        if isinstance(error, QualityError):
            raise
        raise QualityError("INVALID_PARQUET") from None


def map_rows(
    payload: bytes,
    file_format: str,
    spec: MappingSpec,
    *,
    lot_size: Decimal,
    ingestion_time: datetime,
) -> tuple[Any, JsonRecord]:
    """Map without sorting, imputation or learning; retain every input row disposition."""
    incoming = _input_rows(payload, file_format, spec)
    if not incoming:
        raise QualityError("EMPTY_DATASET")
    rows: list[dict[str, object]] = []
    rejects: list[JsonValue] = []
    included: list[JsonValue] = []
    prior_close: datetime | None = None
    previous_available: datetime | None = None
    for index, raw in enumerate(incoming, start=1):
        try:
            row: dict[str, object] = {"source_row": index}
            for target, source in spec.columns:
                value = raw[source]
                if target in TIMES:
                    row[target] = (
                        None
                        if value in (None, "") and target in OPTIONAL
                        else _time(value, spec.timezone)
                    )
                else:
                    with localcontext() as ctx:
                        ctx.prec = 60
                        scale = (
                            (lot_size if spec.volume_unit == "LOTS" else Decimal(1))
                            if target == "volume"
                            else Decimal(spec.price_scale)
                        )
                        row[target] = decimal_value(
                            decimal_value(value, zero_allowed=target == "volume")
                            * scale,
                            zero_allowed=target == "volume",
                        )
            opened, closed = (
                cast(datetime, row["open_at"]),
                cast(datetime, row["close_at"]),
            )
            available = cast(datetime | None, row.get("available_at"))
            revised = cast(datetime | None, row.get("revision_time"))
            if (
                closed - opened != timedelta(minutes=1)
                or opened.second
                or opened.microsecond
            ):
                raise QualityError("ONE_MINUTE_GRID_REQUIRED")
            if closed == datetime.max.replace(tzinfo=UTC) or (
                available is not None and available < closed
            ):
                raise QualityError("INVALID_AVAILABILITY")
            if prior_close is not None and opened < prior_close:
                raise QualityError("DUPLICATE_OVERLAP_OR_ORDER")
            if (
                previous_available is not None
                and available is not None
                and available < previous_available
            ):
                raise QualityError("AVAILABILITY_ORDER")
            if spec.revision_mode == "KNOWN" and (
                revised is None or available is None or revised > available
            ):
                raise QualityError("INVALID_REVISION_AVAILABILITY")
            prices = [cast(Decimal, row[k]) for k in ("open", "close")]
            if cast(Decimal, row["low"]) > min(prices) or cast(
                Decimal, row["high"]
            ) < max(prices):
                raise QualityError("OHLC_INCONSISTENT")
            if "open_bid" in row and cast(Decimal, row["open_bid"]) > cast(
                Decimal, row["open_ask"]
            ):
                raise QualityError("CROSSED_QUOTE")
            row.update(
                available_at=available,
                revision_time=revised,
                ingestion_time=ingestion_time,
                revision_time_status="NOT_APPLICABLE"
                if spec.revision_mode == "SYNTHETIC_NOT_APPLICABLE"
                else spec.revision_mode,
            )
            rows.append(row)
            included.append(index)
            prior_close = closed
            if available is not None:
                previous_available = available
        except (ValueError, OverflowError) as error:
            code = (
                error.code if isinstance(error, QualityError) else "INVALID_ROW_VALUE"
            )
            rejects.append({"source_row": index, "reason": code})
    columns = [
        "source_row",
        *REQUIRED,
        "available_at",
        "revision_time",
        "ingestion_time",
        "revision_time_status",
    ]
    columns += [
        name
        for name in ("open_bid", "open_ask", "volume")
        if name in dict(spec.columns)
    ]
    schema = pa.schema(
        [
            pa.field(
                name,
                pa.int64()
                if name == "source_row"
                else pa.string()
                if name == "revision_time_status"
                else pa.timestamp("us", tz="UTC")
                if name in (*TIMES, "ingestion_time")
                else pa.decimal128(38, 12),
                nullable=name in {"available_at", "revision_time"},
            )
            for name in columns
        ]
    )
    table = pa.Table.from_pylist(rows, schema=schema)
    if table.nbytes > MAX_DECODED:
        raise QualityError("DECODED_SIZE_LIMIT")
    return table, {
        "input_rows": len(incoming),
        "included_rows": included,
        "rejects": rejects,
        "reject_policy": spec.reject_policy,
        "rejected_rows": len(rejects),
        "accepted": bool(rows)
        and (not rejects or spec.reject_policy == "EXCLUDE_WITH_REPORT"),
    }
