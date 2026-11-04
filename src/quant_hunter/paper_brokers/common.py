"""Bounded paper broker types and mandatory host risk-authorization contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import unquote

HOSTS = {"ALPACA": "paper-api.alpaca.markets", "OANDA": "api-fxpractice.oanda.com"}
MAX_BODY = 2_097_152
MAX_REQUEST = 16_384


class BrokerError(ValueError):
    """Only fixed safe error codes cross the broker boundary."""


def identifier(
    value: object, pattern: str = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}"
) -> str:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise BrokerError("INVALID_IDENTIFIER")
    return value


def utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is not UTC:
        raise BrokerError("UTC_REQUIRED")


def decimal(value: object, *, positive: bool = False, signed: bool = False) -> Decimal:
    if not isinstance(value, (str, Decimal)) or (
        isinstance(value, str) and len(value) > 64
    ):
        raise BrokerError("INVALID_DECIMAL")
    try:
        result = Decimal(value)
        exponent = result.as_tuple().exponent
        if (
            not result.is_finite()
            or not isinstance(exponent, int)
            or not -12 <= exponent <= 18
            or len(result.as_tuple().digits) > 28
            or result.copy_abs() > Decimal("1e18")
            or (not signed and result < 0)
            or (positive and result <= 0)
        ):
            raise BrokerError("DECIMAL_BOUND")
        return result
    except InvalidOperation:
        raise BrokerError("INVALID_DECIMAL") from None


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise BrokerError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise BrokerError("INVALID_JSON_NUMBER")


def parse(raw: bytes) -> object:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BODY:
        raise BrokerError("RESPONSE_BOUND")
    try:
        return json.loads(
            raw, object_pairs_hook=_pairs, parse_float=Decimal, parse_constant=_constant
        )
    except ValueError, UnicodeError, RecursionError, InvalidOperation:
        raise BrokerError("INVALID_JSON") from None


def record(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise BrokerError("RESPONSE_SCHEMA")
    return value


def records(value: object, *, maximum: int = 100) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > maximum:
        raise BrokerError("RESPONSE_SCHEMA")
    return [record(item) for item in value]


def timestamp(value: object) -> str:
    # Preserve exact provider nanoseconds rather than silently truncating to microseconds.
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z",
            value,
        )
        is None
    ):
        raise BrokerError("INVALID_TIMESTAMP")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise BrokerError("INVALID_TIMESTAMP") from None
    return value


def canonical(value: object) -> bytes:
    def default(item: object) -> str:
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, datetime):
            utc(item)
            return item.isoformat()
        raise BrokerError("UNSUPPORTED_PAYLOAD")

    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=True,
            default=default,
        ).encode("ascii")
    except ValueError, TypeError, RecursionError:
        raise BrokerError("INVALID_PAYLOAD") from None
    if len(encoded) > MAX_REQUEST:
        raise BrokerError("REQUEST_BOUND")
    return encoded


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class PaperCredentials:
    key: str = field(repr=False)
    secret: str | None = field(default=None, repr=False)
    purpose: str = "PAPER_ONLY"

    def validate(self, provider: str) -> None:
        if self.purpose != "PAPER_ONLY":
            raise BrokerError("PAPER_CREDENTIAL_PURPOSE_REQUIRED")
        if any(
            re.fullmatch(r"[A-Za-z0-9_+./=-]{8,256}", item) is None
            for item in self.values()
        ):
            raise BrokerError("INVALID_CREDENTIAL")
        if (provider == "ALPACA" and self.secret is None) or (
            provider == "OANDA" and self.secret is not None
        ):
            raise BrokerError("CREDENTIAL_SCHEMA")

    def values(self) -> tuple[str, ...]:
        return (self.key,) if self.secret is None else (self.key, self.secret)


@dataclass(frozen=True)
class BrokerConfig:
    provider: str
    owner_id: str
    account_id: str = field(repr=False)
    credentials: PaperCredentials = field(repr=False)
    mode: str = "BROKER_PAPER"

    def validate(self) -> None:
        if self.provider not in HOSTS or self.mode != "BROKER_PAPER":
            raise BrokerError("PAPER_ENVIRONMENT_REQUIRED")
        identifier(self.owner_id)
        identifier(
            self.account_id,
            r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
            if self.provider == "ALPACA"
            else r"[0-9]{3}-[0-9]{3}-[0-9]{6,12}-[0-9]{3}",
        )
        self.credentials.validate(self.provider)


@dataclass(frozen=True)
class OrderIntent:
    client_order_id: str
    instrument: str
    quantity: Decimal
    side: str
    order_type: str
    time_in_force: str
    price: Decimal | None = None
    position_fill: str = "REDUCE_FIRST"

    def validate(self, provider: str) -> None:
        identifier(self.client_order_id)
        decimal(self.quantity, positive=True)
        if self.side not in {"BUY", "SELL"} or self.order_type not in {
            "MARKET",
            "LIMIT",
            "STOP",
        }:
            raise BrokerError("UNSUPPORTED_ORDER_COMBINATION")
        if provider == "ALPACA":
            identifier(self.instrument, r"[A-Z][A-Z0-9.-]{0,14}")
            if (
                self.time_in_force != "DAY"
                or self.quantity != self.quantity.to_integral_value()
                or self.position_fill != "REDUCE_FIRST"
            ):
                raise BrokerError("UNSUPPORTED_ALPACA_ORDER")
        elif provider == "OANDA":
            identifier(self.instrument, r"[A-Z]{3}_[A-Z]{3}")
            expected = {"FOK", "IOC"} if self.order_type == "MARKET" else {"GTC"}
            if self.time_in_force not in expected or self.position_fill not in {
                "REDUCE_FIRST",
                "REDUCE_ONLY",
                "OPEN_ONLY",
            }:
                raise BrokerError("UNSUPPORTED_OANDA_ORDER")
        else:
            raise BrokerError("UNKNOWN_PROVIDER")
        if self.order_type == "MARKET":
            if self.price is not None:
                raise BrokerError("UNEXPECTED_PRICE")
        elif self.price is None:
            raise BrokerError("ORDER_PRICE_REQUIRED")
        else:
            decimal(self.price, positive=True)


def action_bytes(
    action: str, intent: OrderIntent | None, original_client_id: str | None
) -> bytes:
    if action not in {"SUBMIT", "CANCEL", "REPLACE"}:
        raise BrokerError("INVALID_ACTION")
    if (
        (action == "SUBMIT" and (intent is None or original_client_id is not None))
        or (action == "CANCEL" and (intent is not None or original_client_id is None))
        or (action == "REPLACE" and (intent is None or original_client_id is None))
    ):
        raise BrokerError("ACTION_SCHEMA")
    if original_client_id is not None:
        identifier(original_client_id)
    return canonical(
        {
            "action": action,
            "intent": asdict(intent) if intent else None,
            "original_client_id": original_client_id,
        }
    )


@dataclass(frozen=True)
class RiskAuthorization:
    """Required host-created approval evidence; never accept this from request JSON.

    This is an in-process capability contract, not a signature or scientific approval.
    Root must issue it only after authenticated owner/atomic risk/kill checks.
    """

    authorization_id: str
    owner_id: str
    account_id: str
    provider: str
    experiment_id: str
    strategy_id: str
    request_digest: str
    risk_revision: int
    approved_at: datetime
    expires_at: datetime
    mode: str = "BROKER_PAPER"

    def validate(self, config: BrokerConfig, request: bytes, now: datetime) -> None:
        utc(now)
        utc(self.approved_at)
        utc(self.expires_at)
        for value in (
            self.authorization_id,
            self.owner_id,
            self.experiment_id,
            self.strategy_id,
        ):
            identifier(value)
        if (
            self.mode != "BROKER_PAPER"
            or self.provider != config.provider
            or self.owner_id != config.owner_id
            or self.account_id != config.account_id
            or self.request_digest != digest(request)
            or type(self.risk_revision) is not int
            or not 0 <= self.risk_revision <= 1_000_000_000
        ):
            raise BrokerError("RISK_AUTHORIZATION_BINDING")
        if (
            not self.approved_at <= now < self.expires_at
            or self.expires_at - self.approved_at > timedelta(seconds=30)
        ):
            raise BrokerError("RISK_AUTHORIZATION_EXPIRED")


@dataclass(frozen=True)
class Request:
    provider: str
    method: str
    target: str = field(repr=False)
    credentials: PaperCredentials = field(repr=False)
    body: bytes | None = field(default=None, repr=False)
    authorization: RiskAuthorization | None = field(default=None, repr=False)
    authorization_config: BrokerConfig | None = field(default=None, repr=False)
    authorization_payload: bytes | None = field(default=None, repr=False)

    @property
    def host(self) -> str:
        if self.provider not in HOSTS:
            raise BrokerError("PAPER_HOST_REQUIRED")
        return HOSTS[self.provider]


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = field(repr=False)
    retry_after: str | None = field(default=None, repr=False)


class Transport(Protocol):
    def send(self, request: Request) -> Response: ...


class OfflineTransport:
    def send(self, request: Request) -> Response:
        raise BrokerError("BLOCKED_EXTERNAL_TRANSPORT_NOT_CONFIGURED")


def checked_response(response: Response, credentials: PaperCredentials) -> Response:
    if (
        type(response.status) is not int
        or not 100 <= response.status <= 599
        or not isinstance(response.body, bytes)
        or len(response.body) > MAX_BODY
    ):
        raise BrokerError("RESPONSE_BOUND")
    try:
        raw = response.body.decode("utf-8")
        variants = [raw, unquote(raw)]
        # Malformed JSON can hide a reflected secret behind Unicode escapes.
        # Refuse it before callers can retain evidence; empty 204 remains valid.
        decoded = parse(response.body) if response.body else None
        variants.append(str(decoded))
        variants.extend(unquote(value) for value in tuple(variants))
        if any(
            secret in variant for secret in credentials.values() for variant in variants
        ):
            raise BrokerError("CREDENTIAL_REFLECTION_REFUSED")
    except UnicodeError:
        raise BrokerError("INVALID_RESPONSE_ENCODING") from None
    if response.retry_after is not None and (
        not isinstance(response.retry_after, str)
        or re.fullmatch(r"[0-9]{1,5}", response.retry_after) is None
    ):
        # Headers never enter diagnostics or a retained response unchecked.
        response = Response(response.status, response.body)
    return response
