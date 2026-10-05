"""Fixed read-only SEC/Alpaca HTTPS endpoints; no broker or arbitrary URL API."""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import parse_qsl, unquote, urlsplit

from quant_hunter.sources.transport import (
    MAX_RESPONSE_BYTES,
    SOCKET_TIMEOUT,
    Response,
    SourceError,
    checked_body,
    public_address,
)


@dataclass(frozen=True)
class EquityRequest:
    host: str
    target: str = field(repr=False)
    user_agent: str = field(repr=False)
    key_id: str | None = field(default=None, repr=False)
    secret_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[ -~]{8,240}", self.user_agent):
            raise SourceError("INVALID_USER_AGENT")
        if self.host == "data.sec.gov":
            if self.key_id is not None or self.secret_key is not None:
                raise SourceError("SEC_AUTHENTICATION_REFUSED")
            if not re.fullmatch(
                r"/submissions/CIK[0-9]{10}\.json|"
                r"/api/xbrl/companyconcept/CIK[0-9]{10}/"
                r"(?:us-gaap|ifrs-full|dei|srt)/[A-Za-z][A-Za-z0-9]{0,119}\.json",
                self.target,
            ):
                raise SourceError("ENDPOINT_NOT_ALLOWED")
            if "@" not in self.user_agent:
                raise SourceError("SEC_CONTACT_REQUIRED")
        elif self.host == "data.alpaca.markets":
            if any(
                value is None or re.fullmatch(r"[A-Za-z0-9_+/-]{8,256}", value) is None
                for value in (self.key_id, self.secret_key)
            ):
                raise SourceError("ALPACA_CREDENTIALS_REQUIRED")
            parts = urlsplit(self.target)
            pairs = parse_qsl(parts.query, keep_blank_values=True)
            query = dict(pairs)
            required = {
                "symbols",
                "timeframe",
                "start",
                "end",
                "limit",
                "adjustment",
                "asof",
                "feed",
                "currency",
                "sort",
            }
            if (
                parts.scheme
                or parts.netloc
                or parts.fragment
                or parts.path != "/v2/stocks/bars"
                or len(pairs) != len(query)
                or set(query) not in (required, required | {"page_token"})
                or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", query.get("symbols", ""))
                is None
                or query.get("timeframe") not in ("1Min", "1Day")
                or query.get("feed") not in ("iex", "sip")
                or query.get("adjustment") != "raw"
                or query.get("asof") != "-"
                or query.get("currency") != "USD"
                or query.get("sort") != "asc"
                or not re.fullmatch(r"[0-9]{1,4}", query.get("limit", ""))
                or not 1 <= int(query["limit"]) <= 1000
            ):
                raise SourceError("REQUEST_NOT_ALLOWED")
            utc_timestamp(query["start"])
            utc_timestamp(query["end"])
            if "page_token" in query:
                page_token(query["page_token"])
            # Even incorrectly constructed requests cannot move a credential into a URL.
            if any(
                value in self.target
                for value in (self.key_id, self.secret_key)
                if value
            ):
                raise SourceError("CREDENTIAL_IN_URL_REFUSED")
        else:
            raise SourceError("ENDPOINT_NOT_ALLOWED")


@dataclass(frozen=True)
class EquityResponse:
    status: int
    body: bytes = field(repr=False)
    retry_after: str | None = field(default=None, repr=False)


class EquityTransport(Protocol):
    def send(self, request: EquityRequest) -> EquityResponse: ...


class EquityHTTPS:
    """No proxy, redirects, retries, decompression or endpoint changes.

    DNS uses the OS timeout. After a single public-address lookup, TLS validates
    the official host against the pinned IP. Socket stages and response reading
    are bounded. Header values and response bodies never enter diagnostics.
    """

    def send(self, request: EquityRequest) -> EquityResponse:
        request.__post_init__()
        connection = http.client.HTTPSConnection(request.host, timeout=SOCKET_TIMEOUT)
        try:
            address = public_address(request.host)
            raw = socket.create_connection((address, 443), timeout=SOCKET_TIMEOUT)
            try:
                secure = ssl.create_default_context().wrap_socket(
                    raw, server_hostname=request.host
                )
                connection.sock = secure
            except Exception:
                raw.close()
                raise
            headers = {
                "User-Agent": request.user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            }
            if request.key_id is not None and request.secret_key is not None:
                headers["APCA-API-KEY-ID"] = request.key_id
                headers["APCA-API-SECRET-KEY"] = request.secret_key
            connection.request("GET", request.target, headers=headers)
            deadline = time.monotonic() + SOCKET_TIMEOUT
            response = connection.getresponse()
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise SourceError("ENCODED_RESPONSE_REFUSED")
            length = response.getheader("Content-Length")
            if length and (
                not re.fullmatch(r"[0-9]{1,9}", length)
                or int(length) > MAX_RESPONSE_BYTES
            ):
                raise SourceError("RESPONSE_TOO_LARGE")
            chunks: list[bytes] = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SourceError("TIMEOUT")
                secure.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise SourceError("RESPONSE_TOO_LARGE")
                chunks.append(chunk)
            return EquityResponse(
                response.status, b"".join(chunks), response.getheader("Retry-After")
            )
        except SourceError:
            raise
        except TimeoutError:
            raise SourceError("TIMEOUT") from None
        except OSError, http.client.HTTPException, ValueError:
            raise SourceError("NETWORK_FAILURE") from None
        finally:
            connection.close()


@dataclass(frozen=True)
class RawPage:
    raw: bytes = field(repr=False)
    digest: str
    retrieved_at: datetime


def receive(transport: EquityTransport, request: EquityRequest) -> RawPage:
    try:
        response = transport.send(request)
    except TimeoutError:
        raise SourceError("TIMEOUT") from None
    except OSError, http.client.HTTPException:
        raise SourceError("NETWORK_FAILURE") from None
    if len(response.body) > MAX_RESPONSE_BYTES:
        raise SourceError("RESPONSE_TOO_LARGE")
    # Refuse ordinary JSON/URL-escaped reflection before retaining even errors.
    reflected = response.body.decode("utf-8", errors="replace")
    reflected = re.sub(
        r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match[1], 16)), reflected
    ).replace(r"\/", "/")
    reflected = unquote(reflected)
    for secret in (request.key_id, request.secret_key):
        if secret and (secret.encode("ascii") in response.body or secret in reflected):
            raise SourceError("SENSITIVE_RESPONSE_REFUSED")
    raw = checked_body(Response(response.status, response.body, response.retry_after))
    return RawPage(raw, "sha256:" + hashlib.sha256(raw).hexdigest(), datetime.now(UTC))


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise SourceError("NONFINITE_NUMBER")


def json_object(raw: bytes) -> dict[str, object]:
    if not 0 < len(raw) <= MAX_RESPONSE_BYTES:
        raise SourceError("INVALID_RESPONSE_SIZE")
    try:
        result: object = json.loads(
            raw.decode("utf-8-sig"),
            parse_float=Decimal,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
    except UnicodeDecodeError, ValueError, RecursionError, InvalidOperation:
        raise SourceError("INVALID_JSON") from None
    return mapping(result)


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise SourceError("INVALID_SCHEMA")
    return value


def text(value: object, pattern: str, code: str = "INVALID_SCHEMA") -> str:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise SourceError(code)
    return value


def calendar_date(value: object) -> date:
    encoded = text(value, r"[0-9]{4}-[0-9]{2}-[0-9]{2}", "INVALID_DATE")
    try:
        return date.fromisoformat(encoded)
    except ValueError:
        raise SourceError("INVALID_DATE") from None


def utc_timestamp(value: object) -> datetime:
    encoded = text(
        value,
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|\+00:00)",
        "UTC_TIMESTAMP_REQUIRED",
    )
    fraction = (
        encoded.split(".", 1)[1].split("Z")[0].split("+")[0] if "." in encoded else ""
    )
    if any(digit != "0" for digit in fraction[6:]):
        raise SourceError("TIMESTAMP_PRECISION_UNSUPPORTED")
    try:
        return datetime.fromisoformat(encoded).astimezone(UTC)
    except ValueError:
        raise SourceError("INVALID_TIMESTAMP") from None


def number(value: object, *, nonnegative: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise SourceError("INVALID_NUMBER")
    try:
        result = Decimal(value)
        if (
            not result.is_finite()
            or result.copy_abs() > Decimal("1e24")
            or (nonnegative and result < 0)
        ):
            raise SourceError("INVALID_NUMBER")
        exponent = result.as_tuple().exponent
        if (
            not isinstance(exponent, int)
            or exponent < -12
            or exponent > 24
            or len(result.as_tuple().digits) > 38
        ):
            raise SourceError("UNSUPPORTED_NUMBER_PRECISION")
    except InvalidOperation:
        raise SourceError("INVALID_NUMBER") from None
    return result


def page_token(value: object) -> str | None:
    if value is None:
        return None
    return text(value, r"[A-Za-z0-9_+/=-]{1,512}", "INVALID_PAGE_TOKEN")


def stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
