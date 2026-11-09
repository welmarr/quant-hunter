"""Closed, bounded text-file primitives; no binary/archive extraction or network."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal

from quant_hunter.sources.macro_common import decimal_text, require_utc
from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, SourceError
from quant_hunter.storage.security import reject_secret_text_values

MAX_ROWS = 5000
MAX_COLUMNS = 128
MAX_CELLS = 100_000


def csv_table(raw: bytes) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RESPONSE_BYTES:
        raise SourceError("ARCHIVE_FILE_SIZE")
    try:
        document = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SourceError("ARCHIVE_UTF8_REQUIRED") from None
    if any(ord(char) < 32 and char not in "\r\n\t" for char in document):
        raise SourceError("ARCHIVE_CONTROL_CHARACTER")
    # Bound each physical line before csv allocates fields. Embedded newlines
    # have no meaning in these numeric, closed profiles and are refused below.
    if any(len(line) > 32_768 for line in document.splitlines()):
        raise SourceError("ARCHIVE_LINE_BOUND")
    rows: list[tuple[str, ...]] = []
    cells = 0
    try:
        for row in csv.reader(io.StringIO(document, newline=""), strict=True):
            if not 1 <= len(row) <= MAX_COLUMNS or len(rows) > MAX_ROWS:
                raise SourceError("ARCHIVE_TABLE_BOUND")
            if any(len(value) > 128 or "\n" in value or "\r" in value for value in row):
                raise SourceError("ARCHIVE_FIELD_BOUND")
            cells += len(row)
            if cells > MAX_CELLS:
                raise SourceError("ARCHIVE_CELL_BOUND")
            rows.append(tuple(row))
    except csv.Error:
        raise SourceError("ARCHIVE_CSV_INVALID") from None
    if len(rows) < 2:
        raise SourceError("ARCHIVE_DATA_REQUIRED")
    header, *body = rows
    if (
        any(not name or name != name.strip() for name in header)
        or len(set(header)) != len(header)
        or any(len(row) != len(header) for row in body)
    ):
        raise SourceError("ARCHIVE_HEADER_OR_WIDTH")
    return header, tuple(body)


def token(value: object, pattern: str, code: str) -> str:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise SourceError(code)
    return value


def metadata_text(value: object) -> str:
    result = token(
        value, r"[A-Za-z0-9][A-Za-z0-9 ._(),/%:+-]{0,119}", "ARCHIVE_METADATA"
    )
    if (
        result != result.strip()
        or result.upper() in {"UNKNOWN", "N/A", "UNSPECIFIED"}
        or "://" in result
        or re.match(r"^[A-Za-z]:/", result)
    ):
        raise SourceError("ARCHIVE_METADATA")
    try:
        reject_secret_text_values(result, "archive metadata")
    except ValueError:
        raise SourceError("ARCHIVE_METADATA") from None
    return result


def day(value: object) -> date:
    encoded = token(value, r"[0-9]{4}-[0-9]{2}-[0-9]{2}", "ARCHIVE_DATE")
    try:
        result = date.fromisoformat(encoded)
    except ValueError:
        raise SourceError("ARCHIVE_DATE") from None
    if not 1900 <= result.year <= 2100:
        raise SourceError("ARCHIVE_DATE")
    return result


def month(value: object) -> date:
    encoded = token(value, r"[0-9]{4}-(?:0[1-9]|1[0-2])", "ARCHIVE_MONTH")
    return day(encoded + "-01")


def quarter(value: object) -> date:
    encoded = token(value, r"[0-9]{4}Q[1-4]", "ARCHIVE_QUARTER")
    return day(f"{encoded[:4]}-{(int(encoded[-1]) - 1) * 3 + 1:02d}-01")


def timestamp(value: object) -> datetime:
    encoded = token(
        value,
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z",
        "ARCHIVE_UTC_TIMESTAMP",
    )
    try:
        result = datetime.fromisoformat(encoded)
    except ValueError:
        raise SourceError("ARCHIVE_UTC_TIMESTAMP") from None
    require_utc(result)
    day(encoded[:10])
    return result


def number(value: str, *, missing: bool = False) -> Decimal | None:
    if missing and value in ("", ".", "#N/A"):
        return None
    result = decimal_text(value)
    if result is None:
        raise SourceError("ARCHIVE_NUMBER_REQUIRED")
    return result


def context(start: date, end: date, retrieved: datetime, export_vintage: date) -> None:
    require_utc(retrieved)
    if (
        type(start) is not date
        or type(end) is not date
        or type(export_vintage) is not date
        or not date(1900, 1, 1) <= start <= end <= date(2100, 12, 31)
        or not start <= export_vintage <= retrieved.date()
    ):
        raise SourceError("ARCHIVE_RANGE_OR_VINTAGE")


def evidence(mode: str) -> None:
    if mode not in ("OWNER_SUPPLIED", "RECORDED_FIXTURE"):
        raise SourceError("INVALID_EVIDENCE_MODE")
