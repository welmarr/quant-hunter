"""Closed bounded dossier and source identity contracts, with no executable fields."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import unquote, urlsplit, urlunsplit

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.storage.security import SensitiveMetadataError, reject_secret_text

from .errors import PublicationError

MAX_RAW = 4_000_000
MAX_TEXT = 1_000_000
MAX_ATTEMPTS = 128
DOSSIER_FIELDS = (
    "question",
    "universe",
    "data",
    "signal_formula",
    "horizon",
    "estimation",
    "portfolio",
    "costs",
    "protocol",
    "metrics",
    "reported_results",
    "reproduced_results",
    "limitations",
    "deviations",
    "variant",
    "disposition_reason",
)


def text(value: object, maximum: int = 4000, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not empty and not value.strip())
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise PublicationError("INVALID_TEXT")
    try:
        reject_secret_text(value, "publication")
    except SensitiveMetadataError:
        raise PublicationError("SENSITIVE_METADATA") from None
    return value


def doi(value: object) -> str:
    value = text(value, 240)
    if re.fullmatch(r"10\.[0-9]{4,9}/[A-Za-z0-9._;()/:-]{1,220}", value) is None:
        raise PublicationError("INVALID_DOI")
    return value.lower()


def public_url(value: object) -> str:
    """HTTPS public DNS names only; credentials, ports, queries and fragments refused.

    This syntactic admission does not resolve a host. The transport independently
    checks every DNS answer and pins the selected IP for each explicit fetch.
    """
    value = text(value, 1800)
    if not value.isascii() or any(c.isspace() for c in value) or "\\" in value:
        raise PublicationError("UNSAFE_URL")
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if (
            parts.scheme != "https"
            or parts.username is not None
            or parts.password is not None
            or parts.port is not None
            or parts.query
            or parts.fragment
            or host.endswith(".")
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host)
            or "." not in host
            or any(not p or len(p) > 63 for p in host.split("."))
            or host.endswith((".localhost", ".local", ".internal", ".invalid"))
        ):
            raise PublicationError("UNSAFE_URL")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise PublicationError("IP_LITERAL_REFUSED")
        decoded = unquote(parts.path)
        if (
            "%" in decoded
            or "\\" in decoded
            or any(ord(c) < 32 for c in decoded)
            or any(segment in {".", ".."} for segment in decoded.split("/"))
            or re.search(r"(?i)(token|api[_-]?key|password|secret)=", decoded)
        ):
            raise PublicationError("UNSAFE_URL")
    except ValueError:
        raise PublicationError("UNSAFE_URL") from None
    return urlunsplit(("https", host, parts.path or "/", "", ""))


def metadata(value: JsonRecord) -> JsonRecord:
    required = {"title", "authors", "year", "doi", "url", "version"}
    if set(value) != required:
        raise PublicationError("INVALID_METADATA_FIELDS")
    authors = value["authors"]
    if not isinstance(authors, list) or not 1 <= len(authors) <= 64:
        raise PublicationError("INVALID_AUTHORS")
    year = value["year"]
    if year is not None and (type(year) is not int or not 1500 <= year <= 2100):
        raise PublicationError("INVALID_YEAR")
    reference_doi = doi(value["doi"]) if value["doi"] is not None else None
    url = public_url(value["url"]) if value["url"] is not None else None
    if reference_doi is None and url is None:
        raise PublicationError("STABLE_REFERENCE_REQUIRED")
    return {
        "title": text(value["title"], 500),
        "authors": [text(author, 160) for author in authors],
        "year": year,
        "doi": reference_doi,
        "url": url,
        "version": text(value["version"], 240),
    }


def empty_dossier() -> JsonRecord:
    return {
        **{key: "UNKNOWN" for key in DOSSIER_FIELDS},
        "equation_links": [],
        "disposition": "CANDIDATE",
    }


def dossier(value: JsonRecord) -> JsonRecord:
    if set(value) != {*DOSSIER_FIELDS, "equation_links", "disposition"}:
        raise PublicationError("INVALID_DOSSIER_FIELDS")
    result: JsonRecord = {key: text(value[key]) for key in DOSSIER_FIELDS}
    if value["disposition"] not in ("CANDIDATE", "SELECTED", "REJECTED", "DEFERRED"):
        raise PublicationError("INVALID_DISPOSITION")
    result["disposition"] = value["disposition"]
    links = value["equation_links"]
    if not isinstance(links, list) or len(links) > 64:
        raise PublicationError("INVALID_EQUATION_LINKS")
    checked: list[JsonValue] = []
    for link in links:
        if not isinstance(link, dict) or set(link) != {
            "section",
            "function",
            "assumptions",
            "oracle",
        }:
            raise PublicationError("INVALID_EQUATION_LINK")
        checked.append({key: text(item, 1000) for key, item in link.items()})
    result["equation_links"] = checked
    return result


def record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise PublicationError("INVALID_IMMUTABLE_DOCUMENT")
    return value
