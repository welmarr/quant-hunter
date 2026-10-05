"""Fixed read-only TE calendar and Nasdaq SF1 endpoints, header credentials."""

from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import parse_qsl, unquote, urlsplit

from quant_hunter.sources._equity_transport import EquityResponse, calendar_date
from quant_hunter.sources.priority_common import PriorityKey, date_range
from quant_hunter.sources.transport import (
    MAX_RESPONSE_BYTES,
    SOCKET_TIMEOUT,
    SourceError,
    public_address,
)

SF1_COLUMNS = "ticker,dimension,calendardate,datekey,reportperiod,lastupdated,revenue,netinc,assets"


@dataclass(frozen=True)
class PriorityRequest:
    host: str
    target: str = field(repr=False)
    key: PriorityKey = field(repr=False)

    def __post_init__(self) -> None:
        self.key.__post_init__()
        if len(self.target) > 1000 or self.key.value in unquote(self.target):
            raise SourceError("REQUEST_NOT_ALLOWED")
        parts = urlsplit(self.target)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        params = dict(pairs)
        if parts.scheme or parts.netloc or parts.fragment or len(pairs) != len(params):
            raise SourceError("ENDPOINT_NOT_ALLOWED")
        if self.host == "api.tradingeconomics.com":
            match = re.fullmatch(
                r"/calendar/country/([a-z0-9% -]{2,80})/(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})",
                parts.path,
            )
            if match is None or params != {"f": "json"} or len(self.target) > 230:
                raise SourceError("ENDPOINT_NOT_ALLOWED")
            if re.fullmatch(r"[a-z][a-z -]{1,39}", unquote(match[1])) is None:
                raise SourceError("INVALID_COUNTRY")
            date_range(calendar_date(match[2]), calendar_date(match[3]), 7)
        elif self.host == "data.nasdaq.com":
            required = {
                "ticker",
                "dimension",
                "datekey.gte",
                "datekey.lte",
                "qopts.columns",
                "qopts.per_page",
            }
            if parts.path != "/api/v3/datatables/SHARADAR/SF1.json" or set(
                params
            ) not in (required, required | {"qopts.cursor_id"}):
                raise SourceError("ENDPOINT_NOT_ALLOWED")
            if (
                re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", params["ticker"]) is None
                or params["dimension"] not in ("ARQ", "ARY", "ART", "MRQ", "MRY", "MRT")
                or params["qopts.columns"] != SF1_COLUMNS
                or params["qopts.per_page"] != "1000"
            ):
                raise SourceError("REQUEST_NOT_ALLOWED")
            date_range(
                calendar_date(params["datekey.gte"]),
                calendar_date(params["datekey.lte"]),
            )
            if (
                "qopts.cursor_id" in params
                and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", params["qopts.cursor_id"])
                is None
            ):
                raise SourceError("INVALID_CURSOR")
        else:
            raise SourceError("ENDPOINT_NOT_ALLOWED")


class PriorityTransport(Protocol):
    def send(self, request: PriorityRequest) -> EquityResponse: ...


class PriorityHTTPS:
    def send(self, request: PriorityRequest) -> EquityResponse:
        from quant_hunter.sources.process_http import run

        request.__post_init__()
        result = run(
            "PRIORITY",
            json.dumps(
                {
                    "host": request.host,
                    "target": request.target,
                    "key": request.key.value,
                }
            ).encode("utf-8"),
        )
        return EquityResponse(result.status, result.body, result.retry_after)

    @staticmethod
    def _send_once(request: PriorityRequest) -> EquityResponse:
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
                "User-Agent": "QuantHunter/0.1 bounded data client",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            }
            headers[
                "Authorization"
                if request.host == "api.tradingeconomics.com"
                else "X-Api-Token"
            ] = request.key.value
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
            size, chunks = 0, []
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
