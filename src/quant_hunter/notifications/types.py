"""Closed notification contracts: no raw configurations, errors or credential blobs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

MAX_PAYLOAD = 8192
TOKEN_PATTERN = r"[0-9]{5,20}:[A-Za-z0-9_-]{20,128}"  # noqa: S105 - validation pattern, not a credential


class NotificationError(ValueError):
    """Safe fixed code only; never raw provider/credential diagnostics."""


def identity(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value) is None
    ):
        raise NotificationError("INVALID_IDENTITY")
    return value


def utc(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is not UTC:
        raise NotificationError("UTC_REQUIRED")
    if not 1970 <= value.year <= 2200:
        raise NotificationError("TIMESTAMP_RANGE")


def stamp(value: datetime) -> str:
    utc(value)
    return value.isoformat(timespec="microseconds")


def text(value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or any(ord(c) < 32 and c != "\n" for c in value)
        or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
        or re.search(TOKEN_PATTERN, value)
        or re.search(
            r"(?i)(?:https?://|bearer\s|(?:password|secret|(?:bot_)?token|api[_-]?key)[\"']?\s*[:=])",
            value,
        )
    ):
        raise NotificationError("UNSAFE_OR_OVERSIZED_EVENT_TEXT")
    return value


def canonical(value: object) -> bytes:
    def default(item: object) -> str:
        if isinstance(item, datetime):
            return stamp(item)
        raise NotificationError("UNSUPPORTED_PAYLOAD")

    try:
        raw = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=default,
        ).encode("ascii")
    except ValueError, TypeError, RecursionError:
        raise NotificationError("INVALID_PAYLOAD") from None
    if len(raw) > MAX_PAYLOAD:
        raise NotificationError("PAYLOAD_LIMIT")
    return raw


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def require_digest(value: str) -> None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"sha256:[a-f0-9]{64}", value) is None
    ):
        raise NotificationError("INVALID_DIGEST")


@dataclass(frozen=True)
class Notification:
    notification_id: str
    dedupe_key: str
    kind: str
    severity: str
    mode: str
    title: str
    body: str
    created_at: datetime
    expires_at: datetime
    experiment_id: str | None = None

    def validate(self) -> None:
        identity(self.notification_id)
        identity(self.dedupe_key)
        if (
            self.kind not in ("SYSTEM", "SIGNAL", "ORDER", "RISK", "FAILURE", "TEST")
            or self.severity not in ("INFO", "WARNING", "ERROR")
            or self.mode
            not in ("SYNTHETIC", "REPLAY", "LOCAL_PAPER", "BROKER_PAPER", "SYSTEM")
        ):
            raise NotificationError("UNSUPPORTED_EVENT_CLASSIFICATION")
        text(self.title, 120)
        text(self.body, 2000)
        utc(self.created_at)
        utc(self.expires_at)
        if not self.created_at < self.expires_at <= self.created_at + timedelta(days=7):
            raise NotificationError("INVALID_EXPIRY")
        if self.experiment_id is not None:
            identity(self.experiment_id)
            if not self.experiment_id.startswith("EXP-"):
                raise NotificationError("EXPERIMENT_REFERENCE_REQUIRED")
        canonical(asdict(self))

    @property
    def payload(self) -> bytes:
        self.validate()
        return canonical(asdict(self))

    @property
    def telegram_text(self) -> str:
        self.validate()
        return (
            f"[{self.mode} / {self.kind} / {self.severity}] {self.title}\n{self.body}"
        )


@dataclass(frozen=True)
class VaultReference:
    provider: str
    account: str
    slot: str

    def validate(self) -> None:
        if self.provider != "TELEGRAM":
            raise NotificationError("INVALID_VAULT_PROVIDER")
        for value in (self.account, self.slot):
            if (
                not isinstance(value, str)
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value) is None
            ):
                raise NotificationError("INVALID_VAULT_REFERENCE")


@dataclass(frozen=True)
class TelegramConfig:
    owner_id: str
    revision: int
    vault: VaultReference
    chat_id: str = field(repr=False)
    enabled: bool = False

    def validate(self) -> None:
        identity(self.owner_id)
        self.vault.validate()
        if (
            type(self.revision) is not int
            or not 1 <= self.revision <= 1000
            or type(self.enabled) is not bool
        ):
            raise NotificationError("INVALID_CONFIGURATION")
        if (
            not isinstance(self.chat_id, str)
            or re.fullmatch(r"-?[1-9][0-9]{0,15}", self.chat_id) is None
            or abs(int(self.chat_id)) >= 2**52
        ):
            raise NotificationError("INVALID_CHAT_ID")

    @property
    def payload(self) -> bytes:
        self.validate()
        return canonical(asdict(self))


class TelegramPolicy(Enum):
    DISABLED = "DISABLED"
    REVIEWED_V0_TOKEN_PATH = "REVIEWED_V0_TELEGRAM_TOKEN_PATH_ONLY"  # noqa: S105 - policy label


@dataclass(frozen=True)
class SendAuthorization:
    authorization_id: str
    owner_id: str
    notification_digest: str
    configuration_digest: str
    request_digest: str
    purpose: str
    approved_at: datetime
    expires_at: datetime

    def validate(
        self,
        owner_id: str,
        notification_digest: str,
        configuration_digest: str,
        request: bytes,
        now: datetime,
    ) -> None:
        identity(self.authorization_id)
        identity(self.owner_id)
        utc(now)
        utc(self.approved_at)
        utc(self.expires_at)
        for value in (
            self.notification_digest,
            self.configuration_digest,
            self.request_digest,
        ):
            require_digest(value)
        if (
            self.owner_id != owner_id
            or self.notification_digest != notification_digest
            or self.configuration_digest != configuration_digest
            or self.request_digest != digest(request)
            or self.purpose not in ("EXPLICIT_TEST", "EXPLICIT_EVENT_SEND")
        ):
            raise NotificationError("SEND_AUTHORIZATION_BINDING")
        if (
            not self.approved_at <= now < self.expires_at
            or self.expires_at - self.approved_at > timedelta(seconds=30)
        ):
            raise NotificationError("SEND_AUTHORIZATION_EXPIRED")


def message_payload(config: TelegramConfig, event: Notification) -> bytes:
    config.validate()
    return canonical(
        {
            "chat_id": config.chat_id,
            "text": event.telegram_text,
            "link_preview_options": {"is_disabled": True},
            "protect_content": True,
        }
    )


def telegram_profile_schema() -> dict[str, object]:
    """Root stores this closed configuration in the existing encrypted vault.

    Root must introduce a notification-purpose profile, not mislabel send authority
    as the currently existing PAPER_OR_READ_ONLY credential purpose.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["bot_token", "allowed_chat_id"],
        "properties": {
            "bot_token": {
                "type": "string",
                "pattern": "^" + TOKEN_PATTERN + "$",
                "writeOnly": True,
                "maxLength": 149,
            },
            "allowed_chat_id": {
                "type": "string",
                "pattern": r"^-?[1-9][0-9]{0,15}$",
                "maxLength": 17,
            },
        },
    }
