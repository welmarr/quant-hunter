"""Credential-safe FRED v2 and public dated G17 transport only."""

from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit

from quant_hunter.sources._equity_transport import EquityResponse
from quant_hunter.sources.transport import (
    MAX_RESPONSE_BYTES,
    SOCKET_TIMEOUT,
    SourceError,
    public_address,
)


@dataclass(frozen=True)
class MacroRequest:
    host: str
    target: str = field(repr=False)
    bearer: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.host == "www.federalreserve.gov":
            if (
                self.bearer is not None
                or re.fullmatch(r"/releases/g17/[0-9]{8}/g17\.txt", self.target) is None
            ):
                raise SourceError("ENDPOINT_NOT_ALLOWED")
        elif self.host == "api.stlouisfed.org":
            if (
                self.bearer is None
                or re.fullmatch(r"[a-z0-9]{32}", self.bearer) is None
            ):
                raise SourceError("FRED_KEY_NOT_CONFIGURED")
            parts = urlsplit(self.target)
            pairs = parse_qsl(parts.query, keep_blank_values=True)
            params = dict(pairs)
            required = {"release_id", "format", "limit"}
            if (
                parts.scheme
                or parts.netloc
                or parts.fragment
                or parts.path != "/fred/v2/release/observations"
                or len(pairs) != len(params)
                or set(params) not in (required, required | {"next_cursor"})
            ):
                raise SourceError("ENDPOINT_NOT_ALLOWED")
            if (
                params["format"] != "json"
                or re.fullmatch(r"[1-9][0-9]{0,6}", params["release_id"]) is None
                or re.fullmatch(r"[1-9][0-9]{0,3}", params["limit"]) is None
                or int(params["limit"]) > 1000
            ):
                raise SourceError("REQUEST_NOT_ALLOWED")
            if (
                "next_cursor" in params
                and re.fullmatch(
                    r"[A-Za-z0-9_.-]{1,80},[0-9]{4}-[0-9]{2}-[0-9]{2}",
                    params["next_cursor"],
                )
                is None
            ):
                raise SourceError("INVALID_CURSOR")
            if self.bearer in self.target:
                raise SourceError("CREDENTIAL_IN_URL_REFUSED")
        else:
            raise SourceError("ENDPOINT_NOT_ALLOWED")


class MacroTransport(Protocol):
    def send(self, request: MacroRequest) -> EquityResponse: ...


class MacroHTTPS:
    def send(self, request: MacroRequest) -> EquityResponse:
        from quant_hunter.sources.process_http import run

        request.__post_init__()
        result = run(
            "MACRO",
            json.dumps(
                {
                    "host": request.host,
                    "target": request.target,
                    "bearer": request.bearer,
                }
            ).encode("utf-8"),
        )
        return EquityResponse(result.status, result.body, result.retry_after)

    @staticmethod
    def _send_once(request: MacroRequest) -> EquityResponse:
        """Private wire primitive; only public send provides the total deadline."""
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
                "User-Agent": "QuantHunter/0.1 bounded research source client",
                "Accept": "application/json,text/plain",
                "Accept-Encoding": "identity",
            }
            if request.bearer is not None:
                headers["Authorization"] = "Bearer " + request.bearer
            connection.request("GET", request.target, headers=headers)
            deadline = time.monotonic() + SOCKET_TIMEOUT
            response = connection.getresponse()
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise SourceError("ENCODED_RESPONSE_REFUSED")
            length = response.getheader("Content-Length")
            if length and (
                re.fullmatch(r"[0-9]{1,9}", length) is None
                or int(length) > MAX_RESPONSE_BYTES
            ):
                raise SourceError("RESPONSE_TOO_LARGE")
            size = 0
            chunks: list[bytes] = []
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
