"""Explicitly enabled fixed paper-host HTTPS, bounded by a disposable process."""

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
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from urllib.parse import parse_qsl, urlsplit

from quant_hunter.sources.process_http import _limits as _limits

from .common import (
    MAX_BODY,
    MAX_REQUEST,
    BrokerError,
    Request,
    Response,
    checked_response,
    decimal,
    parse,
    record,
)

DEADLINE_SECONDS = 20.0
SOCKET_SECONDS = 5.0


def validate_request(request: Request) -> None:
    request.credentials.validate(request.provider)
    _ = request.host  # Fixed host property rejects unsupported providers.
    if request.method != "GET":
        if (
            request.authorization is None
            or request.authorization_config is None
            or request.authorization_payload is None
        ):
            raise BrokerError("RISK_AUTHORIZATION_REQUIRED")
        bound = request.authorization_config
        bound.validate()
        if (
            bound.provider != request.provider
            or bound.credentials != request.credentials
        ):
            raise BrokerError("RISK_AUTHORIZATION_BINDING")
        request.authorization.validate(
            bound, request.authorization_payload, datetime.now(UTC)
        )
        authorized = record(parse(request.authorization_payload))
        action = authorized.get("action")
        expected = (
            {"SUBMIT": "POST", "CANCEL": "DELETE", "REPLACE": "PATCH"}
            if request.provider == "ALPACA"
            else {"SUBMIT": "POST", "CANCEL": "PUT", "REPLACE": "PUT"}
        )
        if not isinstance(action, str) or expected.get(action) != request.method:
            raise BrokerError("RISK_ACTION_BINDING")
        if request.provider == "OANDA" and not request.target.startswith(
            "/v3/accounts/" + bound.account_id + "/orders"
        ):
            raise BrokerError("RISK_ACCOUNT_BINDING")
        if action == "CANCEL":
            if request.body is not None or (
                request.provider == "OANDA"
                and request.target
                != "/v3/accounts/"
                + bound.account_id
                + "/orders/@"
                + str(authorized.get("original_client_id"))
                + "/cancel"
            ):
                raise BrokerError("RISK_PAYLOAD_BINDING")
        else:
            frozen = record(authorized.get("intent"))
            body = record(parse(request.body or b""))
            if request.provider == "ALPACA":
                expected_body: dict[str, object] = {
                    "qty": str(decimal(frozen.get("quantity"), positive=True)),
                    "time_in_force": str(frozen.get("time_in_force")).lower(),
                    "client_order_id": frozen.get("client_order_id"),
                }
                if action == "SUBMIT":
                    expected_body.update(
                        {
                            "symbol": frozen.get("instrument"),
                            "side": str(frozen.get("side")).lower(),
                            "type": str(frozen.get("order_type")).lower(),
                            "order_class": "simple",
                            "extended_hours": False,
                        }
                    )
                if frozen.get("price") is not None:
                    expected_body[
                        "limit_price"
                        if frozen.get("order_type") == "LIMIT"
                        else "stop_price"
                    ] = str(decimal(frozen.get("price"), positive=True))
                if body != expected_body:
                    raise BrokerError("RISK_PAYLOAD_BINDING")
            else:
                units = decimal(frozen.get("quantity"), positive=True)
                expected_order: dict[str, object] = {
                    "instrument": frozen.get("instrument"),
                    "units": str(units if frozen.get("side") == "BUY" else -units),
                    "type": frozen.get("order_type"),
                    "timeInForce": frozen.get("time_in_force"),
                    "positionFill": frozen.get("position_fill"),
                    "clientExtensions": {"id": frozen.get("client_order_id")},
                }
                if frozen.get("price") is not None:
                    expected_order["price"] = str(
                        decimal(frozen.get("price"), positive=True)
                    )
                if body != {"order": expected_order}:
                    raise BrokerError("RISK_PAYLOAD_BINDING")
                expected_target = (
                    "/v3/accounts/"
                    + bound.account_id
                    + "/orders"
                    + (
                        "/@" + str(authorized.get("original_client_id"))
                        if action == "REPLACE"
                        else ""
                    )
                )
                if request.target != expected_target:
                    raise BrokerError("RISK_ACTION_BINDING")
    parts = urlsplit(request.target)
    if (
        parts.scheme
        or parts.netloc
        or parts.fragment
        or len(request.target) > 2048
        or any(value in request.target for value in request.credentials.values())
    ):
        raise BrokerError("REQUEST_TARGET_REFUSED")
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    query = dict(pairs)
    if len(pairs) != len(query):
        raise BrokerError("DUPLICATE_QUERY")
    if request.provider == "ALPACA":
        allowed = {
            "GET": r"/v2/(?:account|positions|orders|orders:by_client_order_id|account/activities/FILL|clock|assets/[A-Z][A-Z0-9.-]{0,14})",
            "POST": r"/v2/orders",
            "PATCH": r"/v2/orders/[a-f0-9-]{36}",
            "DELETE": r"/v2/orders/[a-f0-9-]{36}",
        }
        if request.method == "GET" and parts.path == "/v2/orders:by_client_order_id":
            if (
                set(query) != {"client_order_id"}
                or re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", query["client_order_id"]
                )
                is None
            ):
                raise BrokerError("REQUEST_QUERY_REFUSED")
        elif parts.path == "/v2/orders" and request.method == "GET":
            if query != {"status": "all", "limit": "100", "direction": "asc"}:
                raise BrokerError("REQUEST_QUERY_REFUSED")
        elif parts.path == "/v2/account/activities/FILL":
            if (
                set(query)
                not in (
                    {"direction", "page_size"},
                    {"direction", "page_size", "page_token"},
                )
                or query.get("direction") != "asc"
                or query.get("page_size") != "100"
                or (
                    "page_token" in query
                    and re.fullmatch(
                        r"[0-9]{14,20}::[a-f0-9-]{36}", query["page_token"]
                    )
                    is None
                )
            ):
                raise BrokerError("REQUEST_QUERY_REFUSED")
        elif query:
            raise BrokerError("REQUEST_QUERY_REFUSED")
    else:
        account = r"[0-9]{3}-[0-9]{3}-[0-9]{6,12}-[0-9]{3}"
        order = r"(?:@[A-Za-z0-9][A-Za-z0-9._:-]{0,63}|[0-9]{1,20})"
        allowed = {
            "GET": rf"/v3/accounts(?:/{account}/(?:summary|openPositions|pendingOrders|instruments|orders/{order}|transactions/sinceid))?",
            "POST": rf"/v3/accounts/{account}/orders",
            "PUT": rf"/v3/accounts/{account}/orders/{order}(?:/cancel)?",
        }
        if parts.path.endswith("/transactions/sinceid"):
            if (
                set(query) != {"id"}
                or re.fullmatch(r"[0-9]{1,20}", query["id"]) is None
            ):
                raise BrokerError("REQUEST_QUERY_REFUSED")
        elif parts.path.endswith("/instruments"):
            if (
                set(query) != {"instruments"}
                or re.fullmatch(r"[A-Z]{3}_[A-Z]{3}", query["instruments"]) is None
            ):
                raise BrokerError("REQUEST_QUERY_REFUSED")
        elif query:
            raise BrokerError("REQUEST_QUERY_REFUSED")
    if (
        request.method not in allowed
        or re.fullmatch(allowed[request.method], parts.path) is None
    ):
        raise BrokerError("REQUEST_ENDPOINT_REFUSED")
    if request.body is not None:
        if (
            request.method not in {"POST", "PUT", "PATCH"}
            or not isinstance(request.body, bytes)
            or len(request.body) > MAX_REQUEST
        ):
            raise BrokerError("REQUEST_BODY_REFUSED")
        record(parse(request.body))
        if any(
            secret.encode() in request.body for secret in request.credentials.values()
        ):
            raise BrokerError("CREDENTIAL_IN_BODY_REFUSED")
    elif request.method in {"POST", "PATCH"} or (
        request.method == "PUT" and not parts.path.endswith("/cancel")
    ):
        raise BrokerError("REQUEST_BODY_REQUIRED")


def public_ip(host: str) -> str:
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise BrokerError("DNS_FAILURE") from None
    if not 1 <= len(addresses) <= 32:
        raise BrokerError("DNS_RESPONSE_BOUND")
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address[4][0])
        except ValueError:
            raise BrokerError("DNS_INVALID_ADDRESS") from None
        if (
            not parsed.is_global
            or parsed.is_multicast
            or parsed.is_reserved
            or parsed.is_unspecified
        ):
            raise BrokerError("NONPUBLIC_ADDRESS_REFUSED")
    return str(addresses[0][4][0])


def _wire(request: Request) -> Response:
    validate_request(request)
    connection = http.client.HTTPSConnection(request.host, timeout=SOCKET_SECONDS)
    try:
        raw = socket.create_connection(
            (public_ip(request.host), 443), timeout=SOCKET_SECONDS
        )
        try:
            secure = ssl.create_default_context().wrap_socket(
                raw, server_hostname=request.host
            )
            connection.sock = secure
        except Exception:
            raw.close()
            raise
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
            "User-Agent": "QuantHunter-PaperProtocol/0",
        }
        if request.provider == "ALPACA":
            headers["APCA-API-KEY-ID"] = request.credentials.key
            headers["APCA-API-SECRET-KEY"] = request.credentials.secret or ""
        else:
            headers["Authorization"] = "Bearer " + request.credentials.key
            headers["Accept-Datetime-Format"] = "RFC3339"
        # DNS and TLS can consume the remaining authorization lifetime. Check the
        # exact bound request again at the last point before sending HTTP bytes.
        validate_request(request)
        connection.request(
            request.method, request.target, body=request.body, headers=headers
        )
        response = connection.getresponse()
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise BrokerError("ENCODED_RESPONSE_REFUSED")
        length = response.getheader("Content-Length")
        if length is not None and (
            re.fullmatch(r"[0-9]{1,9}", length) is None or int(length) > MAX_BODY
        ):
            raise BrokerError("RESPONSE_BOUND")
        body = response.read(MAX_BODY + 1)
        return checked_response(
            Response(response.status, body, response.getheader("Retry-After")),
            request.credentials,
        )
    except BrokerError:
        raise
    except TimeoutError:
        raise BrokerError("NETWORK_TIMEOUT") from None
    except OSError, ValueError, http.client.HTTPException:
        raise BrokerError("NETWORK_FAILURE") from None
    finally:
        connection.close()


def _child(request: Request, send: Connection) -> None:
    logging.disable(logging.CRITICAL)
    sys.dont_write_bytecode = True
    try:
        _limits()
        response = checked_response(_wire(request), request.credentials)
        metadata = json.dumps(
            {"status": response.status, "retry_after": response.retry_after},
            separators=(",", ":"),
        ).encode()
        send.send_bytes(len(metadata).to_bytes(4, "big") + metadata + response.body)
    except BaseException:
        # Exception text may contain credentials from a library: never serialize it.
        send.send_bytes(b"FAIL")
    finally:
        send.close()


def _receive(connection: Connection, output: queue.Queue[bytes | None]) -> None:
    try:
        output.put(connection.recv_bytes(MAX_BODY + 1024))
    except OSError, EOFError:
        output.put(None)


class FixedPaperHTTPS:
    """Explicit network enablement is required; no call is made by construction."""

    def __init__(self, *, network_enabled: bool = False) -> None:
        self.network_enabled = network_enabled

    def send(self, request: Request) -> Response:
        if self.network_enabled is not True:
            raise BrokerError("BLOCKED_EXTERNAL_NETWORK_DISABLED")
        validate_request(request)
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(target=_child, args=(request, send), daemon=True)
        output: queue.Queue[bytes | None] = queue.Queue(maxsize=1)
        reader = threading.Thread(target=_receive, args=(receive, output), daemon=True)
        started = time.monotonic()
        result: Response | None = None
        failure: str | None = None
        try:
            process.start()
            send.close()
            reader.start()
            remaining = DEADLINE_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise BrokerError("NETWORK_TIMEOUT")
            try:
                frame = output.get(timeout=remaining)
            except queue.Empty:
                raise BrokerError("NETWORK_TIMEOUT") from None
            if frame is None or len(frame) < 5:
                raise BrokerError("NETWORK_FAILURE")
            size = int.from_bytes(frame[:4], "big")
            if not 0 < size <= 1024 or len(frame) < 4 + size:
                raise BrokerError("WIRE_FRAME_INVALID")
            meta = record(parse(frame[4 : 4 + size]))
            status = meta.get("status")
            retry = meta.get("retry_after")
            if type(status) is not int or (
                retry is not None and not isinstance(retry, str)
            ):
                raise BrokerError("WIRE_FRAME_INVALID")
            result = checked_response(
                Response(status, frame[4 + size :], retry), request.credentials
            )
        except BrokerError as error:
            code = str(error)
            failure = (
                code if re.fullmatch(r"[A-Z0-9_]{1,64}", code) else "NETWORK_FAILURE"
            )
        except Exception:
            failure = "NETWORK_FAILURE"
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
                failure = "PROCESS_REAP_FAILED"
        if failure is not None:
            raise BrokerError(failure)
        if result is None:
            raise BrokerError("NETWORK_FAILURE")
        return result
