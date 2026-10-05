"""Bounded credential-free HTTPS transport to two fixed official services."""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Protocol

MAX_RESPONSE_BYTES = 2_000_000
SOCKET_TIMEOUT = 10.0


class SourceError(ValueError):
    """A sanitized source error; never retains provider body, URL or credentials."""

    def __init__(self, code: str, *, retry_after_seconds: int | None = None) -> None:
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


def _request_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("REQUEST_NOT_ALLOWED")
        result[key] = value
    return result


@dataclass(frozen=True)
class Request:
    method: str
    host: str
    target: str
    body: bytes | None = None

    def __post_init__(self) -> None:
        bls = (
            self.method == "POST"
            and self.host == "api.bls.gov"
            and self.target == "/publicAPI/v1/timeseries/data/"
            and self.body is not None
            and len(self.body) <= 4096
        )
        ecb = (
            self.method == "GET"
            and self.host == "data-api.ecb.europa.eu"
            and re.fullmatch(
                r"/service/data/EXR/D\.[A-Z]{3}\.EUR\.SP00\.A"
                r"\?startPeriod=\d{4}-\d\d-\d\d&endPeriod=\d{4}-\d\d-\d\d&format=csvdata",
                self.target,
            )
            and self.body is None
        )
        if not (bls or ecb):
            raise SourceError("ENDPOINT_NOT_ALLOWED")
        if bls:
            try:
                payload = json.loads(self.body or b"", object_pairs_hook=_request_pairs)
                if (
                    not isinstance(payload, dict)
                    or set(payload) != {"seriesid", "startyear", "endyear"}
                    or not isinstance(payload["seriesid"], list)
                    or len(payload["seriesid"]) != 1
                    or not isinstance(payload["seriesid"][0], str)
                    or not re.fullmatch(r"[A-Z0-9_-]{1,40}", payload["seriesid"][0])
                    or any(
                        not isinstance(payload[key], str)
                        or not re.fullmatch(r"\d{4}", payload[key])
                        for key in ("startyear", "endyear")
                    )
                ):
                    raise SourceError("REQUEST_NOT_ALLOWED")
            except json.JSONDecodeError, UnicodeDecodeError:
                raise SourceError("REQUEST_NOT_ALLOWED") from None


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    retry_after: str | None = None


class Transport(Protocol):
    """Inject a fixture transport for HTTP contract tests without network access."""

    def send(self, request: Request) -> Response: ...


def public_address(host: str) -> str:
    """Resolve once and pin the selected public IP to avoid a second DNS lookup."""
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise SourceError("DNS_UNAVAILABLE")
    ips = [str(address[4][0]) for address in addresses]
    if any(not ipaddress.ip_address(address).is_global for address in ips):
        raise SourceError("NONPUBLIC_ADDRESS_REFUSED")
    return ips[0]


class HTTPSPublicTransport:
    """No redirects, proxies, credentials, decompression or automatic retries.

    System DNS has its operating-system timeout. After DNS, connect/TLS use a
    10-second socket timeout and response reads have a 10-second total deadline.
    Request endpoints are fixed; TLS still validates the official hostname while
    the connection uses the previously checked public IP.
    """

    def send(self, request: Request) -> Response:
        # Revalidate even if a caller has bypassed the frozen dataclass API.
        Request(request.method, request.host, request.target, request.body)
        connection = http.client.HTTPSConnection(request.host, timeout=SOCKET_TIMEOUT)
        try:
            address = public_address(request.host)
            raw = socket.create_connection((address, 443), timeout=SOCKET_TIMEOUT)
            try:
                secure_socket = ssl.create_default_context().wrap_socket(
                    raw, server_hostname=request.host
                )
                connection.sock = secure_socket
            except Exception:
                raw.close()
                raise
            connection.request(
                request.method,
                request.target,
                body=request.body,
                headers={
                    "User-Agent": "QuantHunter/0.1 local research data client",
                    "Accept": "application/json,text/csv",
                    "Accept-Encoding": "identity",
                    "Content-Type": "application/json",
                },
            )
            deadline = time.monotonic() + SOCKET_TIMEOUT
            response = connection.getresponse()
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise SourceError("ENCODED_RESPONSE_REFUSED")
            length = response.getheader("Content-Length")
            if length and (not length.isdigit() or int(length) > MAX_RESPONSE_BYTES):
                raise SourceError("RESPONSE_TOO_LARGE")
            chunks: list[bytes] = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SourceError("TIMEOUT")
                secure_socket.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise SourceError("RESPONSE_TOO_LARGE")
            return Response(
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


def checked_body(response: Response) -> bytes:
    """Central response policy also applies to injected transports."""
    if response.status == 429:
        delay = response.retry_after
        retry = (
            min(int(delay), 86400)
            if delay and delay.isdigit() and len(delay) <= 6
            else None
        )
        raise SourceError("RATE_LIMITED", retry_after_seconds=retry)
    if response.status in (401, 403):
        raise SourceError("ACCESS_DENIED")
    if response.status == 404:
        raise SourceError("NOT_FOUND")
    if 300 <= response.status < 400:
        raise SourceError("REDIRECT_REFUSED")
    if response.status != 200:
        raise SourceError("HTTP_FAILURE")
    if not response.body:
        raise SourceError("EMPTY_RESPONSE")
    if len(response.body) > MAX_RESPONSE_BYTES:
        raise SourceError("RESPONSE_TOO_LARGE")
    return response.body
