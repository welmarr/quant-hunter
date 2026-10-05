"""Bounded macro records, exact submitted bytes and explicit temporal uncertainty."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote

from quant_hunter.sources._equity_transport import RawPage, text
from quant_hunter.sources.transport import MAX_RESPONSE_BYTES, SourceError


@dataclass(frozen=True)
class MacroObservation:
    catalogue_id: str
    series_id: str
    period: str
    period_start: date
    value: Decimal | None
    unit: str
    ingestion_time: datetime
    vintage: str
    publication_time: datetime | None = None
    realtime_start: date | None = None
    realtime_end: date | None = None
    source_updated_at: datetime | None = None
    unit_multiplier: int = 0
    metric: str | None = None
    revision_time: None = None
    available_at: None = None
    point_in_time_eligible: bool = False
    quality_flags: tuple[str, ...] = ("HISTORICAL_AVAILABILITY_UNVERIFIED",)


@dataclass(frozen=True)
class MacroBatch:
    catalogue_id: str
    observations: tuple[MacroObservation, ...]
    raw_pages: tuple[RawPage, ...]
    evidence_mode: str
    normalization_version: str = "v0-macro-1"
    coverage_complete: bool = False
    limitations: tuple[str, ...] = (
        "No source or quality approval",
        "Retrieval and economic dates are not historical availability",
        "Owner must retain source registration, rights, configuration and immutable capture",
    )


def require_utc(value: datetime) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise SourceError("UTC_RETRIEVAL_REQUIRED")


def raw_page(raw: bytes, retrieved: datetime) -> RawPage:
    require_utc(retrieved)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RESPONSE_BYTES:
        raise SourceError("INVALID_RESPONSE_SIZE")
    return RawPage(raw, "sha256:" + hashlib.sha256(raw).hexdigest(), retrieved)


def decimal_text(value: object, *, commas: bool = False) -> Decimal | None:
    encoded = text(value, r"[^\r\n]{1,64}", "INVALID_NUMBER")
    if encoded in (".", "---", "(NA)", "(D)"):
        return None
    pattern = (
        r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?"
        if commas
        else r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
    )
    if re.fullmatch(pattern, encoded) is None:
        raise SourceError("INVALID_NUMBER")
    try:
        result = Decimal(encoded.replace(",", ""))
        if not result.is_finite() or result.copy_abs() > Decimal("1e24"):
            raise SourceError("INVALID_NUMBER")
        exponent = result.as_tuple().exponent
        if (
            not isinstance(exponent, int)
            or not -12 <= exponent <= 24
            or len(result.as_tuple().digits) > 38
        ):
            raise SourceError("UNSUPPORTED_NUMBER_PRECISION")
    except InvalidOperation:
        raise SourceError("INVALID_NUMBER") from None
    return result


def reject_secret_reflection(raw: bytes, secret: str) -> None:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise SourceError("RESPONSE_TOO_LARGE")
    reflected = raw.decode("utf-8", errors="replace")
    reflected = re.sub(
        r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match[1], 16)), reflected
    ).replace(r"\/", "/")
    if secret.encode("ascii") in raw or secret in unquote(reflected):
        raise SourceError("SENSITIVE_RESPONSE_REFUSED")


def safe_metadata(value: object, *, maximum: int = 200) -> str:
    return text(value, rf"[^\x00-\x1f\x7f]{{1,{maximum}}}", "INVALID_METADATA")


def reject_embedded_credentials(value: object) -> None:
    """Bounded JSON is checked before imported bytes may enter a batch."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            lowered = {str(key).lower(): nested for key, nested in item.items()}
            if ("userid" in lowered and lowered["userid"] != "[REDACTED]") or (
                str(lowered.get("parametername", "")).upper() == "USERID"
                and lowered.get("parametervalue") != "[REDACTED]"
            ):
                raise SourceError("UNREDACTED_BEA_USERID_REFUSED")
            for key, nested in item.items():
                if str(key).lower() in (
                    "api_key",
                    "authorization",
                    "secret",
                    "secret_key",
                    "password",
                    "access_token",
                ):
                    raise SourceError("CREDENTIAL_FIELD_REFUSED")
                stack.append(nested)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and re.search(
            r"(?i)(?:api_key|userid|token|secret_key)=", unquote(item)
        ):
            raise SourceError("CREDENTIAL_URL_REFUSED")


def validate_macro_batch(
    records: tuple[MacroObservation, ...], catalogue_id: str
) -> None:
    if len(records) > 5000:
        raise SourceError("ROW_LIMIT")
    seen: set[tuple[object, ...]] = set()
    for record in records:
        if record.catalogue_id != catalogue_id:
            raise SourceError("CATALOGUE_MISMATCH")
        require_utc(record.ingestion_time)
        if (
            record.point_in_time_eligible
            or record.available_at is not None
            or record.revision_time is not None
        ):
            raise SourceError("UNSUPPORTED_AVAILABILITY_CLAIM")
        identity = (record.series_id, record.period_start, record.vintage, record.unit)
        if identity in seen:
            raise SourceError("DUPLICATE_OBSERVATION")
        seen.add(identity)
