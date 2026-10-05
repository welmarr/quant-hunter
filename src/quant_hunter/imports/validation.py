"""Strict bounded CSV and fixed-width Parquet decoding, without filesystem input."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.imports.page_limits import PageLimitError, verify_pages
from quant_hunter.storage.security import (
    reject_credential_shaped_fields,
    reject_secret_text_values,
)

MAX_RAW_BYTES = 2_000_000
MAX_DECODED_BYTES = 16_000_000
MAX_ROWS = 100_000
REQUIRED = ("open_at", "close_at", "available_at", "open_bid", "open_ask", "close")
OPTIONAL = ("high", "low", "volume")
TIMES = REQUIRED[:3]
CURRENCIES = frozenset("USD EUR GBP JPY CHF CAD AUD NZD SEK NOK DKK SGD HKD".split())
_TIMESTAMP = re.compile(
    r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$"
)
_DECIMAL = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")


class ImportValidationError(ValueError):
    """A bounded error code safe for logs and import failure reports."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.audit_digest: str | None = None
        super().__init__(code)


def text(value: JsonValue, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
        or "://" in value
        or "\\" in value
        or ".." in value
        or value.startswith("/")
        or re.search(r"(?:^|\s)[A-Za-z]:", value)
    ):
        raise ImportValidationError("INVALID_METADATA_TEXT")
    return value


def decimal_value(value: object, *, zero_allowed: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise ImportValidationError("INVALID_NUMERIC_TYPE")
    encoded = str(value)
    if len(encoded) > 64 or _DECIMAL.fullmatch(encoded) is None:
        raise ImportValidationError("INVALID_DECIMAL")
    try:
        result = Decimal(encoded)
        with localcontext() as context:
            context.prec = 60
            fixed = result.quantize(Decimal("0.000000000001"))
    except InvalidOperation, ValueError:
        raise ImportValidationError("DECIMAL_OUT_OF_RANGE") from None
    if (
        not result.is_finite()
        or result < 0
        or (not zero_allowed and result == 0)
        or result >= Decimal("1e26")
        or fixed != result
    ):
        raise ImportValidationError("DECIMAL_OUT_OF_RANGE")
    return fixed


def metadata_document(value: Mapping[str, JsonValue]) -> JsonRecord:
    record = dict(value)
    required = {"source_name", "declared_license", "evidence_mode", "instrument"}
    if not required <= record.keys() or record.keys() - required - {
        "declared_restrictions"
    }:
        raise ImportValidationError("UNKNOWN_OR_MISSING_METADATA")
    source = text(record["source_name"], maximum=120)
    license_text = text(record["declared_license"], maximum=1000)
    mode = record["evidence_mode"]
    if mode not in ("SYNTHETIC", "HISTORICAL"):
        raise ImportValidationError("UNSUPPORTED_EVIDENCE_MODE")
    instrument = record["instrument"]
    if not isinstance(instrument, dict):
        raise ImportValidationError("INVALID_INSTRUMENT")
    fields = {"symbol", "asset_class", "base_currency", "quote_currency"}
    if not fields <= instrument.keys() or instrument.keys() - fields - {
        "quantity_step"
    }:
        raise ImportValidationError("UNKNOWN_OR_MISSING_INSTRUMENT_FIELD")
    symbol = text(instrument["symbol"], maximum=32)
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,31}", symbol):
        raise ImportValidationError("INVALID_INSTRUMENT_SYMBOL")
    base, quote = instrument["base_currency"], instrument["quote_currency"]
    if (
        not isinstance(base, str)
        or not isinstance(quote, str)
        or base not in CURRENCIES
        or quote not in CURRENCIES
    ):
        raise ImportValidationError("UNSUPPORTED_CURRENCY")
    market = instrument["asset_class"]
    if market not in ("EQUITY", "FX_SPOT"):
        raise ImportValidationError("UNSUPPORTED_MARKET")
    if market == "FX_SPOT" and (
        base == quote or symbol not in {base + quote, base + "/" + quote}
    ):
        raise ImportValidationError("FX_SYMBOL_CURRENCY_MISMATCH")
    if market == "EQUITY" and "/" in symbol:
        raise ImportValidationError("INVALID_EQUITY_SYMBOL")
    step = decimal_value(instrument.get("quantity_step", "1"))
    restrictions = text(
        record.get("declared_restrictions", "UNKNOWN; no redistribution approved"),
        maximum=1000,
    )
    result: JsonRecord = {
        "source_name": source,
        "declared_license": license_text,
        "declared_restrictions": restrictions,
        "evidence_mode": mode,
        "instrument": {
            "symbol": symbol,
            "asset_class": market,
            "base_currency": base,
            "quote_currency": quote,
            "quantity_step": format(step, "f"),
        },
    }
    # Inspect only the bounded flat contract, never traverse arbitrary nested
    # untrusted metadata before its shape and string sizes have been checked.
    try:
        reject_credential_shaped_fields(result)
        reject_secret_text_values(result, "import metadata")
    except ValueError:
        raise ImportValidationError("SENSITIVE_METADATA") from None
    return result


def timestamp(value: object) -> datetime:
    if isinstance(value, str):
        if not _TIMESTAMP.fullmatch(value):
            raise ImportValidationError("TIMESTAMP_REQUIRES_EXPLICIT_TIMEZONE")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ImportValidationError("INVALID_TIMESTAMP") from None
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ImportValidationError("INVALID_TIMESTAMP_TYPE")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ImportValidationError("TIMESTAMP_REQUIRES_EXPLICIT_TIMEZONE")
    try:
        return parsed.astimezone(UTC)
    except OverflowError:
        raise ImportValidationError("INVALID_TIMESTAMP") from None


def columns(names: list[str]) -> tuple[str, ...]:
    if (
        len(names) != len(set(names))
        or set(names) - set(REQUIRED + OPTIONAL)
        or not set(REQUIRED) <= set(names)
    ):
        raise ImportValidationError("DUPLICATE_UNKNOWN_OR_MISSING_COLUMN")
    return REQUIRED + tuple(name for name in OPTIONAL if name in names)


def csv_rows(payload: bytes) -> tuple[tuple[str, ...], Iterator[dict[str, object]]]:
    try:
        content = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise ImportValidationError("CSV_REQUIRES_UTF8") from None
    if "\x00" in content:
        raise ImportValidationError("CSV_NUL_BYTE")
    reader = csv.reader(io.StringIO(content, newline=""), strict=True)
    try:
        header = next(reader)
        order = columns(header)
    except StopIteration, csv.Error:
        raise ImportValidationError("INVALID_CSV_HEADER") from None

    def records() -> Iterator[dict[str, object]]:
        try:
            for row in reader:
                if len(row) != len(header) or any(
                    not cell or len(cell) > 64 for cell in row
                ):
                    raise ImportValidationError("INVALID_CSV_ROW")
                yield dict(zip(header, row, strict=True))
        except csv.Error:
            raise ImportValidationError("INVALID_CSV_ENCODING") from None

    return order, records()


def parquet_rows(payload: bytes) -> tuple[tuple[str, ...], Iterator[dict[str, object]]]:
    if len(payload) < 12 or payload[:4] != b"PAR1" or payload[-4:] != b"PAR1":
        raise ImportValidationError("INVALID_PARQUET_ENVELOPE")
    footer_size = int.from_bytes(payload[-8:-4], "little")
    if not 0 < footer_size <= min(262_144, len(payload) - 12):
        raise ImportValidationError("PARQUET_FOOTER_LIMIT")
    try:
        reader = pq.ParquetFile(
            pa.BufferReader(payload),
            thrift_string_size_limit=262_144,
            thrift_container_size_limit=10_000,
            page_checksum_verification=True,
        )
        info = reader.metadata
        schema = reader.schema_arrow
        order = columns(schema.names)
        if schema.metadata or any(field.metadata for field in schema):
            raise ImportValidationError("PARQUET_CUSTOM_METADATA_UNSUPPORTED")
        if not 0 < info.num_rows <= MAX_ROWS or not 0 < info.num_row_groups <= 256:
            raise ImportValidationError("PARQUET_ROW_LIMIT")
        for field in schema:
            kind = field.type
            if field.name in TIMES:
                valid = (
                    pa.types.is_timestamp(kind)
                    and kind.tz is not None
                    and kind.unit in ("s", "ms", "us")
                )
            else:
                valid = (
                    pa.types.is_integer(kind)
                    or pa.types.is_floating(kind)
                    or pa.types.is_decimal128(kind)
                )
            if not valid:
                raise ImportValidationError("PARQUET_FIXED_WIDTH_TYPES_REQUIRED")
        expanded = compressed = rows = 0
        for index in range(info.num_row_groups):
            group = info.row_group(index)
            rows += group.num_rows
            if group.num_rows < 0 or group.num_columns != len(order):
                raise ImportValidationError("PARQUET_INVALID_METADATA")
            for column_index in range(group.num_columns):
                chunk = group.column(column_index)
                if chunk.file_path or chunk.compression not in {
                    "UNCOMPRESSED",
                    "SNAPPY",
                    "GZIP",
                    "ZSTD",
                    "LZ4",
                    "LZ4_RAW",
                }:
                    raise ImportValidationError("PARQUET_EXTERNAL_OR_UNSUPPORTED_CODEC")
                if chunk.total_uncompressed_size < 0 or chunk.total_compressed_size < 0:
                    raise ImportValidationError("PARQUET_INVALID_METADATA")
                expanded += chunk.total_uncompressed_size
                compressed += chunk.total_compressed_size
        if (
            rows != info.num_rows
            or expanded > MAX_DECODED_BYTES
            or expanded > max(65_536, compressed * 128)
        ):
            raise ImportValidationError("PARQUET_EXPANSION_LIMIT")
        try:
            verify_pages(payload, info, maximum=MAX_DECODED_BYTES)
        except PageLimitError as error:
            raise ImportValidationError(str(error)) from None
    except (pa.ArrowException, OSError, ValueError) as error:
        if isinstance(error, ImportValidationError):
            raise
        raise ImportValidationError("INVALID_PARQUET") from None

    def records() -> Iterator[dict[str, object]]:
        decoded = observed_rows = 0
        try:
            for batch in reader.iter_batches(batch_size=1024, use_threads=False):
                decoded += batch.nbytes
                observed_rows += batch.num_rows
                if decoded > MAX_DECODED_BYTES or observed_rows > MAX_ROWS:
                    raise ImportValidationError("PARQUET_DECODE_LIMIT")
                # Arrow timestamps store UTC instants. Cast away display timezone
                # before Python conversion so Windows needs no optional TZ database.
                values: dict[str, list[object]] = {}
                for index, name in enumerate(batch.schema.names):
                    column = batch.column(index)
                    if name in TIMES:
                        instants = column.cast(pa.timestamp("us")).to_pylist()
                        values[name] = [
                            value.replace(tzinfo=UTC) if value is not None else None
                            for value in instants
                        ]
                    else:
                        values[name] = column.to_pylist()
                for index in range(batch.num_rows):
                    yield {name: value[index] for name, value in values.items()}
            if observed_rows != info.num_rows:
                raise ImportValidationError("PARQUET_ROW_COUNT_MISMATCH")
        except (pa.ArrowException, OSError, ValueError) as error:
            if isinstance(error, ImportValidationError):
                raise
            raise ImportValidationError("INVALID_PARQUET_DATA") from None

    return order, records()


def decode(payload: bytes, file_format: str) -> tuple[Any, list[dict[str, object]]]:
    """Validate every row before publishing data or allocating research identities."""
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_RAW_BYTES:
        raise ImportValidationError("RAW_SIZE_LIMIT")
    if file_format == "CSV":
        order, incoming = csv_rows(payload)
    elif file_format == "PARQUET":
        order, incoming = parquet_rows(payload)
    else:
        raise ImportValidationError("UNSUPPORTED_FORMAT")
    result: list[dict[str, object]] = []
    previous_close: datetime | None = None
    previous_available: datetime | None = None
    for row in incoming:
        if len(result) >= MAX_ROWS:
            raise ImportValidationError("ROW_LIMIT")
        item: dict[str, object] = {}
        for name in order:
            item[name] = (
                timestamp(row[name])
                if name in TIMES
                else decimal_value(row[name], zero_allowed=name == "volume")
            )
        open_at, close_at, available_at = (cast(datetime, item[name]) for name in TIMES)
        if close_at <= open_at or available_at < close_at:
            raise ImportValidationError("BAR_TIME_OR_AVAILABILITY_ORDER")
        if close_at == datetime.max.replace(tzinfo=UTC):
            raise ImportValidationError("EXCLUSIVE_COVERAGE_END_OUT_OF_RANGE")
        if previous_close is not None and open_at < previous_close:
            raise ImportValidationError("DUPLICATE_OVERLAPPING_OR_UNSORTED_BAR")
        if previous_available is not None and available_at < previous_available:
            raise ImportValidationError("UNSORTED_AVAILABILITY")
        bid, ask, close = (
            cast(Decimal, item[name]) for name in ("open_bid", "open_ask", "close")
        )
        if bid > ask:
            raise ImportValidationError("CROSSED_QUOTE")
        if "high" in item and cast(Decimal, item["high"]) < max(bid, ask, close):
            raise ImportValidationError("HIGH_BELOW_PRICE")
        if "low" in item and cast(Decimal, item["low"]) > min(bid, ask, close):
            raise ImportValidationError("LOW_ABOVE_PRICE")
        previous_close, previous_available = close_at, available_at
        result.append(item)
    if not result:
        raise ImportValidationError("EMPTY_DATASET")
    schema = pa.schema(
        [
            pa.field(
                name,
                pa.timestamp("us", tz="UTC")
                if name in TIMES
                else pa.decimal128(38, 12),
                nullable=False,
            )
            for name in order
        ]
    )
    table = pa.Table.from_pylist(result, schema=schema)
    if table.nbytes > MAX_DECODED_BYTES:
        raise ImportValidationError("DECODED_SIZE_LIMIT")
    return table, result
