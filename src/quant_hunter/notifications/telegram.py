"""Optional fixed-host Telegram protocol; local inbox has no network dependency."""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import multiprocessing
import queue
import re
import socket
import ssl
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from typing import Protocol, TypeVar
from urllib.parse import unquote

from quant_hunter.sources.process_http import _limits as _limits

from .store import Delivery, NotificationStore
from .types import (
    TOKEN_PATTERN,
    Notification,
    NotificationError,
    SendAuthorization,
    TelegramConfig,
    TelegramPolicy,
    digest,
    message_payload,
)

HOST = "api.telegram.org"
MAX_RESPONSE = 65_536
DEADLINE_SECONDS = 20.0
T = TypeVar("T")


class SecretResolver(Protocol):
    def with_secret(
        self, provider: str, account: str, slot: str, consumer: Callable[[bytes], T]
    ) -> T: ...


@dataclass(frozen=True)
class TelegramResult:
    state: str
    reason: str
    message_id: int | None = None


@dataclass(frozen=True)
class WireRequest:
    token: str = field(repr=False)
    config: TelegramConfig = field(repr=False)
    event: Notification = field(repr=False)
    authorization: SendAuthorization = field(repr=False)
    policy: TelegramPolicy = TelegramPolicy.DISABLED

    def validate(self, now: datetime) -> None:
        if self.policy is not TelegramPolicy.REVIEWED_V0_TOKEN_PATH:
            raise NotificationError("TOKEN_PATH_POLICY_NOT_APPROVED")
        if (
            not isinstance(self.token, str)
            or re.fullmatch(TOKEN_PATTERN, self.token) is None
        ):
            raise NotificationError("INVALID_BOT_TOKEN")
        self.config.validate()
        self.event.validate()
        self.authorization.validate(
            self.config.owner_id,
            digest(self.event.payload),
            digest(self.config.payload),
            message_payload(self.config, self.event),
            now,
        )
        if (
            not self.config.enabled
            or self.event.expires_at <= now
            or self.event.created_at > now
        ):
            raise NotificationError("SEND_DISABLED_OR_EXPIRED")
        if self.authorization.purpose == "EXPLICIT_TEST" and self.event.kind != "TEST":
            raise NotificationError("TEST_EVENT_REQUIRED")


class TelegramTransport(Protocol):
    def send(self, request: WireRequest) -> TelegramResult: ...


class OfflineTelegram:
    def send(self, request: WireRequest) -> TelegramResult:
        return TelegramResult("BLOCKED", "NETWORK_NOT_CONFIGURED")


def _object(raw: bytes) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise NotificationError("DUPLICATE_RESPONSE_FIELD")
            result[key] = value
        return result

    def bad_constant(_: str) -> None:
        raise NotificationError("INVALID_RESPONSE_NUMBER")

    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RESPONSE:
        raise NotificationError("RESPONSE_BOUND")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)
    except ValueError, UnicodeError, RecursionError:
        raise NotificationError("INVALID_RESPONSE_JSON") from None
    if not isinstance(value, dict):
        raise NotificationError("INVALID_RESPONSE_SCHEMA")
    return value


def normalize_response(status: int, raw: bytes, request: WireRequest) -> TelegramResult:
    """Never retain raw responses, arbitrary descriptions, URLs or echoed secrets."""
    if (
        type(status) is not int
        or not 100 <= status <= 599
        or not isinstance(raw, bytes)
        or len(raw) > MAX_RESPONSE
    ):
        raise NotificationError("RESPONSE_BOUND")
    try:
        string = raw.decode("utf-8")
    except UnicodeError:
        raise NotificationError("INVALID_RESPONSE_ENCODING") from None
    value = _object(raw)
    variants = (string, unquote(string), str(value), unquote(str(value)))
    if any(request.token in variant for variant in variants):
        raise NotificationError("CREDENTIAL_REFLECTION_REFUSED")
    if value.get("ok") is False and status in (200, 400, 401, 403, 404, 429):
        return TelegramResult("REJECTED", f"TELEGRAM_HTTP_{status}")
    if status != 200 or value.get("ok") is not True:
        raise NotificationError("AMBIGUOUS_TELEGRAM_RESPONSE")
    result = value.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("chat"), dict):
        raise NotificationError("INVALID_MESSAGE_RESULT")
    message_id, chat = result.get("message_id"), result["chat"]
    chat_id = chat.get("id")
    if (
        type(message_id) is not int
        or not 0 < message_id < 2**52
        or type(chat_id) is not int
        or str(chat_id) != request.config.chat_id
        or result.get("text") != request.event.telegram_text
    ):
        raise NotificationError("MESSAGE_IDENTITY_MISMATCH")
    return TelegramResult("SENT", "TELEGRAM_ACKNOWLEDGED", message_id)


def _public_ip() -> str:
    values = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
    if not 1 <= len(values) <= 32:
        raise NotificationError("DNS_BOUND")
    for value in values:
        address = ipaddress.ip_address(value[4][0])
        if not address.is_global or address.is_multicast or address.is_reserved:
            raise NotificationError("NONPUBLIC_ADDRESS_REFUSED")
    return str(values[0][4][0])


def _wire(request: WireRequest) -> TelegramResult:
    request.validate(datetime.now(UTC))
    connection = http.client.HTTPSConnection(HOST, timeout=5)
    try:
        raw = socket.create_connection((_public_ip(), 443), timeout=5)
        try:
            connection.sock = ssl.create_default_context().wrap_socket(
                raw, server_hostname=HOST
            )
        except Exception:
            raw.close()
            raise
        # The sole narrowly reviewed exception: target exists only at this call.
        # Never use urllib/requests URL objects or provider URL diagnostics here.
        request.validate(datetime.now(UTC))
        connection.request(
            "POST",
            "/bot" + request.token + "/sendMessage",
            body=message_payload(request.config, request.event),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "QuantHunter-Notifications/0",
            },
        )
        response = connection.getresponse()
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise NotificationError("COMPRESSED_RESPONSE_REFUSED")
        length = response.getheader("Content-Length")
        if length is not None and (
            re.fullmatch(r"[0-9]{1,8}", length) is None or int(length) > MAX_RESPONSE
        ):
            raise NotificationError("RESPONSE_BOUND")
        return normalize_response(
            response.status, response.read(MAX_RESPONSE + 1), request
        )
    finally:
        connection.close()


def _child(request: WireRequest, send: Connection) -> None:
    logging.disable(logging.CRITICAL)
    sys.dont_write_bytecode = True
    result = TelegramResult("UNKNOWN", "TRANSPORT_RESULT_UNKNOWN")
    try:
        _limits()
        result = _wire(request)
    except BaseException:
        # Raw exception text or contexts may contain the token-bearing path.
        result = TelegramResult("UNKNOWN", "TRANSPORT_RESULT_UNKNOWN")
    try:
        send.send_bytes(
            json.dumps(
                {
                    "state": result.state,
                    "reason": result.reason,
                    "message_id": result.message_id,
                }
            ).encode("ascii")
        )
    finally:
        send.close()


def _receive(receive: Connection, output: queue.Queue[bytes | None]) -> None:
    try:
        output.put(receive.recv_bytes(1024))
    except OSError, EOFError:
        output.put(None)


class FixedTelegramHTTPS:
    def __init__(self, *, network_enabled: bool = False) -> None:
        self.network_enabled = network_enabled

    def send(self, request: WireRequest) -> TelegramResult:
        request.validate(datetime.now(UTC))
        if self.network_enabled is not True:
            return TelegramResult("BLOCKED", "NETWORK_NOT_CONFIGURED")
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(target=_child, args=(request, send), daemon=True)
        output: queue.Queue[bytes | None] = queue.Queue(maxsize=1)
        reader = threading.Thread(target=_receive, args=(receive, output), daemon=True)
        started = time.monotonic()
        result = TelegramResult("UNKNOWN", "TRANSPORT_RESULT_UNKNOWN")
        try:
            process.start()
            send.close()
            reader.start()
            remaining = DEADLINE_SECONDS - (time.monotonic() - started)
            if remaining > 0:
                try:
                    raw = output.get(timeout=remaining)
                except queue.Empty:
                    raw = None
                if raw is not None:
                    value = _object(raw)
                    state, reason, message_id = (
                        value.get("state"),
                        value.get("reason"),
                        value.get("message_id"),
                    )
                    if (
                        state in ("SENT", "REJECTED", "UNKNOWN")
                        and isinstance(reason, str)
                        and re.fullmatch(r"[A-Z0-9_]{1,64}", reason)
                        and (message_id is None or type(message_id) is int)
                    ):
                        result = TelegramResult(str(state), reason, message_id)
        except Exception:
            result = TelegramResult("UNKNOWN", "TRANSPORT_RESULT_UNKNOWN")
        finally:
            cleanup_failed = False
            try:
                if process.pid is not None:
                    try:
                        process.join(timeout=0.2)
                    except OSError, RuntimeError, ValueError:
                        cleanup_failed = True
                    try:
                        alive = process.is_alive()
                    except OSError, RuntimeError, ValueError:
                        alive, cleanup_failed = True, True
                    if alive:
                        try:
                            process.kill()
                        except OSError, RuntimeError, ValueError:
                            cleanup_failed = True
                        try:
                            process.join(timeout=2)
                        except OSError, RuntimeError, ValueError:
                            cleanup_failed = True
                        try:
                            alive = process.is_alive()
                        except OSError, RuntimeError, ValueError:
                            alive, cleanup_failed = True, True
                    if alive:
                        cleanup_failed = True
                    else:
                        process.close()
                else:
                    process.close()
            except OSError, RuntimeError, ValueError:
                cleanup_failed = True
            finally:
                # Independently close both handles even if child termination failed.
                for connection in (send, receive):
                    try:
                        connection.close()
                    except OSError, RuntimeError, ValueError:
                        cleanup_failed = True
                if reader.ident is not None:
                    try:
                        reader.join(timeout=2)
                        cleanup_failed = cleanup_failed or reader.is_alive()
                    except OSError, RuntimeError, ValueError:
                        cleanup_failed = True
            if cleanup_failed:
                result = TelegramResult("UNKNOWN", "PROCESS_REAP_FAILED")
        return result


class TelegramService:
    def __init__(
        self,
        store: NotificationStore,
        resolver: SecretResolver,
        *,
        policy: TelegramPolicy = TelegramPolicy.DISABLED,
        transport: TelegramTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.resolver, self.policy = store, resolver, policy
        self.transport, self.clock = transport or OfflineTelegram(), clock

    def send(
        self, owner: str, event_id: str, authorization: SendAuthorization
    ) -> Delivery:
        # Local inbox remains fully operational even while this policy is disabled.
        if self.policy is not TelegramPolicy.REVIEWED_V0_TOKEN_PATH:
            raise NotificationError("TOKEN_PATH_POLICY_NOT_APPROVED")
        fresh, delivery = self.store.reserve_send(
            owner, event_id, authorization, now=self.clock()
        )
        if not fresh:
            return delivery
        event = self.store.get(owner, event_id).event
        config = self.store.configuration(owner)
        if config is None or digest(config.payload) != delivery.configuration_digest:
            return self.store.finish_send(
                owner,
                event_id,
                "BLOCKED",
                "CONFIGURATION_CHANGED_BEFORE_SEND",
                now=self.clock(),
            )

        def consume(secret: bytes) -> TelegramResult:
            value = _object(secret)
            if (
                set(value) != {"bot_token", "allowed_chat_id"}
                or value.get("allowed_chat_id") != config.chat_id
                or not isinstance(value.get("bot_token"), str)
            ):
                return TelegramResult("BLOCKED", "VAULT_PROFILE_MISMATCH")
            current = self.store.configuration(owner)
            if (
                current is None
                or not current.enabled
                or digest(current.payload) != delivery.configuration_digest
            ):
                return TelegramResult("BLOCKED", "CONFIGURATION_CHANGED_BEFORE_SEND")
            request = WireRequest(
                str(value["bot_token"]), config, event, authorization, self.policy
            )
            request.validate(self.clock())
            return self.transport.send(request)

        failed = False
        result = TelegramResult("UNKNOWN", "SEND_OUTCOME_UNKNOWN_NO_RETRY")
        try:
            result = self.resolver.with_secret(
                config.vault.provider, config.vault.account, config.vault.slot, consume
            )
        except Exception:
            failed = True
        # Never retain original exception or its text/context in the delivery log.
        if (
            failed
            or not isinstance(result, TelegramResult)
            or result.state not in ("SENT", "REJECTED", "UNKNOWN", "BLOCKED")
            or not isinstance(result.reason, str)
            or re.fullmatch(r"[A-Z0-9_]{1,64}", result.reason) is None
            or (
                result.message_id is not None
                and (
                    type(result.message_id) is not int
                    or not 0 < result.message_id < 2**52
                )
            )
            or (result.state == "SENT" and result.message_id is None)
        ):
            result = TelegramResult("UNKNOWN", "SEND_OUTCOME_UNKNOWN_NO_RETRY")
        return self.store.finish_send(
            owner,
            event_id,
            result.state,
            result.reason,
            message_id=result.message_id,
            now=self.clock(),
        )
