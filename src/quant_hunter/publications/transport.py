"""Explicit credential-free public HTTPS retrieval; zero automatic redirects."""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from multiprocessing.connection import Connection
from typing import Protocol
from urllib.parse import quote, unquote, urlsplit

from .errors import PublicationError
from .extraction import _limits, _run
from .validation import MAX_RAW, doi, public_url

NETWORK_DEADLINE = 20.0


@dataclass(frozen=True)
class FetchRequest:
    url: str = field(repr=False)
    purpose: str

    def __post_init__(self) -> None:
        normalized = public_url(self.url)
        parts = urlsplit(normalized)
        if self.purpose == "CROSSREF":
            if parts.hostname != "api.crossref.org" or not parts.path.startswith(
                "/works/"
            ):
                raise PublicationError("METADATA_ENDPOINT_REFUSED")
            doi(unquote(parts.path.removeprefix("/works/")))
        elif self.purpose != "PRIMARY_TEXT":
            raise PublicationError("FETCH_PURPOSE_REFUSED")


@dataclass(frozen=True)
class FetchResponse:
    status: int
    body: bytes = field(repr=False)
    media_type: str


class PublicationTransport(Protocol):
    def send(self, request: FetchRequest) -> FetchResponse: ...


def crossref_request(identifier: str) -> FetchRequest:
    return FetchRequest(
        "https://api.crossref.org/works/" + quote(doi(identifier), safe=""), "CROSSREF"
    )


def public_address(host: str) -> str:
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise PublicationError("DNS_UNAVAILABLE")
    ips = [str(item[4][0]) for item in addresses]
    if any(not ipaddress.ip_address(item).is_global for item in ips):
        raise PublicationError("NONPUBLIC_ADDRESS_REFUSED")
    return ips[0]


class PublicationHTTPS:
    """Public DNS/TLS pinning; no ambient proxy/cookies/auth, retries or redirects.

    The parent kills/reaps the child after twenty seconds, covering DNS, TLS,
    slow headers and body. Native allocation/CPU limits also apply to that child.
    Socket stages and body reads retain their narrower ten-second bounds.
    """

    def send(self, request: FetchRequest) -> FetchResponse:
        request.__post_init__()
        payload = json.dumps({"url": request.url, "purpose": request.purpose}).encode(
            "utf-8"
        )
        try:
            result = _run(
                payload, 0, 0, deadline=NETWORK_DEADLINE, worker=_network_worker
            )
        except PublicationError as error:
            mapped = {
                "EXTRACTION_TIMEOUT": "HTTP_TOTAL_TIMEOUT",
                "EXTRACTION_PROCESS_FAILED": "HTTP_PROCESS_FAILED",
                "EXTRACTION_REAP_FAILED": "HTTP_REAP_FAILED",
            }
            raise PublicationError(mapped.get(error.code, error.code)) from None
        return FetchResponse(result["status"], result["body"], result["media_type"])

    @staticmethod
    def _send_once(request: FetchRequest) -> FetchResponse:
        """Private wire primitive: public callers must use the bounded child."""
        request.__post_init__()
        parts = urlsplit(public_url(request.url))
        host = parts.hostname or ""
        connection = http.client.HTTPSConnection(host, timeout=10)
        try:
            address = public_address(host)
            raw = socket.create_connection((address, 443), timeout=10)
            try:
                secure = ssl.create_default_context().wrap_socket(
                    raw, server_hostname=host
                )
                connection.sock = secure
            except Exception:
                raw.close()
                raise
            connection.request(
                "GET",
                parts.path,
                headers={
                    "User-Agent": "QuantHunterPublication/0.1",
                    "Accept": "application/json"
                    if request.purpose == "CROSSREF"
                    else "application/pdf,text/plain",
                    "Accept-Encoding": "identity",
                },
            )
            deadline = time.monotonic() + 10
            response = connection.getresponse()
            if response.status != 200:
                raise PublicationError(
                    "REDIRECT_REFUSED"
                    if 300 <= response.status < 400
                    else "HTTP_FAILURE"
                )
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise PublicationError("HTTP_ENCODING_REFUSED")
            maximum = 1_000_000 if request.purpose == "CROSSREF" else MAX_RAW
            length = response.getheader("Content-Length")
            if length is not None and (
                re.fullmatch(r"[0-9]{1,8}", length) is None or int(length) > maximum
            ):
                raise PublicationError("HTTP_SIZE_LIMIT")
            media = (
                response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            )
            allowed = (
                {"application/json"}
                if request.purpose == "CROSSREF"
                else {"application/pdf", "text/plain"}
            )
            if media not in allowed:
                raise PublicationError("HTTP_MEDIA_REFUSED")
            chunks: list[bytes] = []
            size = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PublicationError("HTTP_TIMEOUT")
                secure.settimeout(remaining)
                chunk = response.read1(min(65536, maximum + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > maximum:
                    raise PublicationError("HTTP_SIZE_LIMIT")
                chunks.append(chunk)
            body = b"".join(chunks)
            if not body or (length is not None and len(body) != int(length)):
                raise PublicationError("HTTP_LENGTH_MISMATCH")
            return FetchResponse(200, body, media)
        except PublicationError:
            raise
        except TimeoutError:
            raise PublicationError("HTTP_TIMEOUT") from None
        except OSError, http.client.HTTPException, ValueError:
            raise PublicationError("HTTP_NETWORK_FAILURE") from None
        finally:
            connection.close()


def _network_worker(
    connection: Connection, payload: bytes, _start: int, _count: int
) -> None:
    logging.disable(logging.CRITICAL)
    try:
        _limits()
        if len(payload) > 4096:
            raise PublicationError("FETCH_REQUEST_LIMIT")
        request = FetchRequest(**json.loads(payload))
        response = PublicationHTTPS._send_once(request)
        connection.send(
            {
                "ok": {
                    "status": response.status,
                    "body": response.body,
                    "media_type": response.media_type,
                }
            }
        )
    except PublicationError as error:
        connection.send({"error": error.code})
    except BaseException:
        connection.send({"error": "HTTP_NETWORK_FAILURE"})
    finally:
        connection.close()


def fetch(transport: PublicationTransport, request: FetchRequest) -> FetchResponse:
    request.__post_init__()
    try:
        response = transport.send(request)
    except PublicationError:
        raise
    except Exception:
        raise PublicationError("HTTP_NETWORK_FAILURE") from None
    maximum = 1_000_000 if request.purpose == "CROSSREF" else MAX_RAW
    if response.status != 200:
        raise PublicationError("HTTP_FAILURE")
    if not isinstance(response.body, bytes) or not 0 < len(response.body) <= maximum:
        raise PublicationError("HTTP_SIZE_LIMIT")
    allowed = (
        {"application/json"}
        if request.purpose == "CROSSREF"
        else {"application/pdf", "text/plain"}
    )
    if response.media_type not in allowed:
        raise PublicationError("HTTP_MEDIA_REFUSED")
    return response
