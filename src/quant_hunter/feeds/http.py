"""Minimal, bounded HTTPS transport for public feed endpoints."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.parse import urlsplit

ALLOWED_HOSTS: Final = frozenset(
    {
        "query1.finance.yahoo.com",
        "query2.finance.yahoo.com",
        "fred.stlouisfed.org",
        "api.stlouisfed.org",
        "api.exchange.coinbase.com",
        "futures.kraken.com",
    }
)
MAX_BYTES: Final = 50 * 1024 * 1024
USER_AGENT: Final = "Mozilla/5.0 (QuantHunter research feed; personal use)"


class FeedError(RuntimeError):
    """A feed request or response could not be used."""


@dataclass(frozen=True, slots=True)
class Response:
    url: str
    status: int
    body: bytes


class Transport(Protocol):
    def get(self, url: str) -> Response: ...


def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise FeedError(f"only https is allowed: {url}")
    if parts.hostname not in ALLOWED_HOSTS:
        raise FeedError(f"host not allowed: {parts.hostname}")


class HttpTransport:
    """GET with a timeout, a size cap and a small fixed retry budget."""

    def __init__(
        self, *, timeout: float = 30.0, retries: int = 2, pause: float = 1.5
    ) -> None:
        self._timeout = timeout
        self._retries = retries
        self._pause = pause

    def get(self, url: str) -> Response:
        check_url(url)
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            request = urllib.request.Request(  # noqa: S310 - scheme checked above
                url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
            )
            try:
                with urllib.request.urlopen(  # noqa: S310 - scheme checked above
                    request, timeout=self._timeout
                ) as handle:
                    body = handle.read(MAX_BYTES + 1)
                    if len(body) > MAX_BYTES:
                        raise FeedError(f"response too large: {url}")
                    return Response(url=url, status=int(handle.status), body=body)
            except urllib.error.HTTPError as error:
                last = error
                if error.code not in (429, 500, 502, 503, 504):
                    raise FeedError(f"HTTP {error.code} for {url}") from error
            except (urllib.error.URLError, TimeoutError) as error:
                last = error
            if attempt < self._retries:
                time.sleep(self._pause * (attempt + 1))
        raise FeedError(f"request failed after retries: {url}: {last}")
