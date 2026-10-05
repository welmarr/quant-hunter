"""Bounded source records and immutable submitted-byte identity; no approval."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote

from quant_hunter.sources._equity_transport import RawPage, text
from quant_hunter.sources.macro_common import (
    decimal_text,
    raw_page,
    reject_embedded_credentials,
)
from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, SourceError


@dataclass(frozen=True)
class PriorityKey:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        text(self.value, r"[A-Za-z0-9_.:+/-]{8,128}", "INVALID_API_KEY")


@dataclass(frozen=True)
class PriorityBatch[T]:
    catalogue_id: str
    records: tuple[T, ...]
    raw_pages: tuple[RawPage, ...]
    evidence_mode: str
    coverage_complete: bool = False
    limitations: tuple[str, ...] = (
        "No source, rights or quality approval",
        "Historical availability and coverage remain unverified",
        "Caller must govern source registration and immutable capture",
    )


def date_range(start: date, end: date, maximum_days: int = 3660) -> None:
    if (
        type(start) is not date
        or type(end) is not date
        or not 0 <= (end - start).days <= maximum_days
    ):
        raise SourceError("INVALID_DATE_RANGE")


def number(value: object, *, missing: bool = False) -> Decimal | None:
    if value is None and missing:
        return None
    if type(value) not in (int, Decimal):
        raise SourceError("INVALID_NUMBER")
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        if (
            not value.is_finite()
            or not isinstance(exponent, int)
            or not -12 <= exponent <= 24
            or len(value.as_tuple().digits) > 38
        ):
            raise SourceError("UNSUPPORTED_NUMBER_PRECISION")
    return decimal_text(
        format(value, "f") if isinstance(value, Decimal) else str(value)
    )


def exact_json(raw: bytes) -> object:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RESPONSE_BYTES:
        raise SourceError("INVALID_RESPONSE_SIZE")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise SourceError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def invalid(_: str) -> object:
        raise SourceError("INVALID_JSON_NUMBER")

    def decimal_number(encoded: str) -> Decimal:
        if len(encoded) > 80:
            raise SourceError("UNSUPPORTED_NUMBER_PRECISION")
        try:
            value = Decimal(encoded)
        except InvalidOperation:
            raise SourceError("INVALID_JSON_NUMBER") from None
        number(value)
        return value

    try:
        result: object = json.loads(
            raw,
            parse_float=decimal_number,
            parse_int=int,
            parse_constant=invalid,
            object_pairs_hook=unique,
        )
    except UnicodeDecodeError, ValueError, RecursionError:
        raise SourceError("INVALID_JSON") from None
    reject_embedded_credentials(result)
    # Additional provider-specific names, including EODHD and TE URL auth.
    stack = [result]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if any(
                str(key).lower() in ("api_token", "x-api-token", "client_secret")
                for key in item
            ):
                raise SourceError("CREDENTIAL_FIELD_REFUSED")
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and re.search(
            r"(?i)[?&](?:api_token|c|client)=", unquote(item)
        ):
            raise SourceError("CREDENTIAL_URL_REFUSED")
    return result


def imported[T](
    catalogue_id: str,
    records: tuple[T, ...],
    raw: bytes,
    retrieved: datetime,
    evidence_mode: str,
) -> PriorityBatch[T]:
    if evidence_mode not in ("OWNER_SUPPLIED", "RECORDED_FIXTURE"):
        raise SourceError("INVALID_EVIDENCE_MODE")
    return PriorityBatch(
        catalogue_id, records, (raw_page(raw, retrieved),), evidence_mode
    )
