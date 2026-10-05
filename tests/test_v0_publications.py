"""Synthetic-only publication workflows, resource bounds and hostile graph tests."""

from __future__ import annotations

import copy
import ctypes
import http.client
import importlib
import io
import json
import logging
import multiprocessing
import os
import socket
import ssl
import sys
import time
import zlib
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    TextStringObject,
)

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.config.canonical import canonicalize_json, parse_json_document
from quant_hunter.config.schema import RecordSchemaError
from quant_hunter.identity import (
    RegistryKind,
    RegistryStore,
    StaleWriterError,
    kind_for_id,
)
from quant_hunter.publications import (
    PublicationError,
    PublicationService,
    canonical_references,
)
from quant_hunter.publications import extraction as e
from quant_hunter.publications import transport as t
from quant_hunter.publications import validation as v
from quant_hunter.storage import (
    ImmutableObjectStore,
    ObjectCorruptionError,
)

SCHEMAS = Path(__file__).parents[1] / "schemas" / "v1"
CODE = "a" * 40
META: JsonRecord = {
    "title": "Synthetic Research Note",
    "authors": ["Example Author"],
    "year": 2026,
    "doi": "10.1234/example",
    "url": "https://authors.example.edu/paper.pdf",
    "version": "synthetic original 1",
}


class FakeTransport:
    def __init__(self, response: t.FetchResponse | Exception) -> None:
        self.response = response
        self.requests: list[t.FetchRequest] = []

    def send(self, request: t.FetchRequest) -> t.FetchResponse:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def service(tmp_path: Path) -> PublicationService:
    objects = ImmutableObjectStore(tmp_path / "objects")
    snapshot = objects.publish(b"synthetic recoverable source archive")
    environment = objects.publish(
        canonicalize_json(
            {"source_snapshot_digest": snapshot.digest, "mode": "SYNTHETIC"}
        )
    )
    return PublicationService(
        RegistryStore.governed(tmp_path / "registry", SCHEMAS),
        objects,
        code_revision=CODE,
        environment_digest=environment.digest,
    )


def pid(paper: JsonRecord) -> str:
    return cast(str, paper["paper_id"])


def head(paper: JsonRecord) -> str:
    return cast(str, paper["revision_digest"])


def upload(
    service: PublicationService,
    raw: bytes = b"Synthetic original text",
    media: str = "text/plain",
) -> JsonRecord:
    paper = service.create(copy.deepcopy(META))
    return service.attach(
        pid(paper),
        raw,
        media_type=media,
        declared_license="Synthetic author test permission",
        expected_digest=head(paper),
    )


def pdf(
    *,
    pages: int = 1,
    blank: bool = False,
    active: bool = False,
    encrypted: bool = False,
    expanded: int = 0,
) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    reference = writer._add_object(font)
    for index in range(pages):
        page = writer.add_blank_page(width=300, height=300)
        if not blank:
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): reference})}
            )
            stream: DecodedStreamObject | EncodedStreamObject
            if expanded:
                stream = EncodedStreamObject()
                stream[NameObject("/Filter")] = NameObject("/FlateDecode")
                stream._data = zlib.compress(b" " * expanded)
            else:
                stream = DecodedStreamObject()
                stream.set_data(
                    f"BT /F1 12 Tf 20 200 Td (Synthetic page {index + 1}: x = 2 + 3) Tj ET".encode()
                )
            page[NameObject("/Contents")] = writer._add_object(stream)
    if active:
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject(
                    "app.alert('untrusted synthetic action')"
                ),
            }
        )
    if encrypted:
        writer.encrypt("synthetic-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_canonical_paper_registry_and_plaintext_reading_are_separate(
    service: PublicationService,
) -> None:
    paper = upload(service)
    assert kind_for_id(pid(paper)) is RegistryKind.PAPER
    assert paper["text_access"] == "UNAVAILABLE"
    assert v.record(paper["reading"])["status"] == "UNREAD"
    extracted = service.extract(pid(paper), expected_digest=head(paper))
    assert extracted["text_access"] == "COMPLETE"
    assert v.record(extracted["reading"])["status"] == "UNREAD"
    assert service.get_text(pid(paper))["pages"] == [
        {"page": 1, "text": "Synthetic original text"}
    ]
    reading: JsonRecord = {
        "status": "FULL",
        "reader": "synthetic reviewer",
        "note": "Read attached page 1 only; software fixture",
        "text_digest": v.record(extracted["text"])["text_digest"],
        "pages": [1],
    }
    read = service.update(pid(paper), expected_digest=head(extracted), reading=reading)
    assert v.record(read["reading"])["status"] == "FULL"
    assert v.record(read["reproduction"])["status"] == "NOT_ATTEMPTED"
    assert len(service.registry.verify_object(pid(paper))) == 6
    assert service.list_papers([pid(paper)]) == [read]
    assert service.list_papers([]) == []


def test_pdf_real_child_extraction_complete_partial_blank_and_reading(
    service: PublicationService,
) -> None:
    raw = pdf(pages=2)
    paper = upload(service, raw, "application/pdf")
    partial = service.extract(
        pid(paper), expected_digest=head(paper), page_start=1, page_count=1
    )
    assert partial["text_access"] == "PARTIAL"
    reading: JsonRecord = {
        "status": "FULL",
        "reader": "reviewer",
        "note": "only page two",
        "text_digest": v.record(partial["text"])["text_digest"],
        "pages": [2],
    }
    with pytest.raises(PublicationError, match="ALL_TEXT"):
        service.update(pid(paper), expected_digest=head(partial), reading=reading)
    complete = service.extract(pid(paper), expected_digest=head(partial))
    text = service.get_text(pid(paper))
    assert complete["text_access"] == "COMPLETE"
    assert [v.record(p)["text"] for p in cast(list[JsonValue], text["pages"])] == [
        "Synthetic page 1: x = 2 + 3",
        "Synthetic page 2: x = 2 + 3",
    ]
    assert text["resource_boundary"] == (
        "WINDOWS_JOB_MEMORY_CPU" if sys.platform == "win32" else "LINUX_RLIMIT_AS_CPU"
    )
    assert text["ocr"] is False
    stored = v.record(complete["document"])
    assert service.objects.read_bytes(cast(str, stored["raw_digest"])) == raw
    blank = e.extract_pdf(pdf(blank=True))
    assert blank["access"] == "UNAVAILABLE"
    assert blank["pages"] == [{"page": 1, "text": ""}]


@pytest.mark.parametrize(
    "options,code",
    [
        ({"active": True}, "ACTIVE_PDF_CONTENT_REFUSED"),
        ({"encrypted": True}, "ENCRYPTED_PDF_REFUSED"),
        ({"expanded": e.MAX_DECODED + 1}, "PDF_EXTRACTION_FAILED"),
        ({"pages": 201}, "PAGE_LIMIT"),
    ],
)
def test_hostile_pdf_refused_with_actual_parser(
    options: dict[str, Any], code: str
) -> None:
    with pytest.raises(PublicationError, match=code):
        e.extract_pdf(pdf(**options))


@pytest.mark.parametrize(
    "raw,start,count",
    [
        (b"not a pdf", 0, 1),
        (b"%PDF-" + b"x" * v.MAX_RAW, 0, 1),
        (b"%PDF-", -1, 1),
        (b"%PDF-", 0, 0),
        (b"%PDF-", 0, 51),
        (b"%PDF-", True, 1),
    ],
    ids=[
        "signature",
        "oversize",
        "negative-start",
        "empty-count",
        "oversize-count",
        "bool-start",
    ],
)
def test_pdf_admission_limits(raw: bytes, start: int, count: int) -> None:
    with pytest.raises(PublicationError):
        e.extract_pdf(raw, page_start=start, page_count=count)


def _memory_probe(
    connection: Connection, _raw: bytes, _start: int, _count: int
) -> None:
    boundary = e._limits()
    try:
        bytearray(e.PROCESS_MEMORY + 1)
    except MemoryError:
        connection.send({"ok": {"boundary": boundary, "allocation_refused": True}})
    else:
        connection.send({"ok": {"allocation_refused": False}})
    connection.close()


def _sleeper(_connection: Connection, _raw: bytes, _start: int, _count: int) -> None:
    time.sleep(30)


def _crash(_connection: Connection, _raw: bytes, _start: int, _count: int) -> None:
    os._exit(19)


def test_actual_process_memory_limit_and_timeout_kill_reap() -> None:
    before = {p.pid for p in multiprocessing.active_children()}
    result = e._run(b"", 0, 1, worker=_memory_probe)
    assert result["allocation_refused"] is True
    with pytest.raises(PublicationError, match="TIMEOUT"):
        e._run(b"", 0, 1, deadline=0.1, worker=_sleeper)
    with pytest.raises(PublicationError, match="PROCESS_FAILED"):
        e._run(b"", 0, 1, worker=_crash)
    assert {p.pid for p in multiprocessing.active_children()} == before


def test_linux_limit_contract_without_mutating_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []
    fake = SimpleNamespace(
        RLIMIT_AS=1,
        RLIMIT_CPU=2,
        RLIMIT_CORE=3,
        setrlimit=lambda key, limits: calls.append((key, limits)),
    )
    monkeypatch.setattr(e, "_platform", lambda: "linux")
    monkeypatch.setattr(importlib, "import_module", lambda _name: fake)
    assert e._limits() == "LINUX_RLIMIT_AS_CPU"
    assert calls == [
        (1, (e.PROCESS_MEMORY, e.PROCESS_MEMORY)),
        (2, (5, 5)),
        (3, (0, 0)),
    ]
    monkeypatch.setattr(e, "_platform", lambda: "unsupported")
    with pytest.raises(PublicationError, match="UNAVAILABLE"):
        e._limits()


def test_failure_is_retained_and_interrupted_attempt_recovers(
    service: PublicationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = upload(service)
    with pytest.raises(PublicationError) as error:
        service.attach(
            pid(paper),
            b"invalid",
            media_type="application/pdf",
            declared_license="test",
            expected_digest=head(paper),
        )
    failed = service.get(pid(paper))
    assert error.value.revision_digest == head(failed)
    assert v.record(cast(list[JsonValue], failed["attempts"])[-1])["status"] == "FAILED"
    assert failed["document"] == paper["document"]

    def interrupt(_manifest: JsonRecord) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        service._operation(pid(paper), head(failed), "EXTRACT", interrupt)
    pending = service.get(pid(paper))
    with pytest.raises(PublicationError, match="PENDING"):
        service.update(
            pid(paper), expected_digest=head(pending), dossier=v.empty_dossier()
        )
    recovered = service.recover_interrupted(pid(paper), expected_digest=head(pending))
    assert (
        v.record(cast(list[JsonValue], recovered["attempts"])[-1])["error"]
        == "INTERRUPTED"
    )
    assert (
        service.recover_interrupted(pid(paper), expected_digest=head(recovered))
        == recovered
    )
    assert (
        service.extract(pid(paper), expected_digest=head(recovered))["text_access"]
        == "COMPLETE"
    )


def test_corrections_cas_and_dossier_do_not_create_scientific_authority(
    service: PublicationService,
) -> None:
    paper = upload(service)
    original = service.objects.read_bytes(
        cast(str, v.record(paper["document"])["raw_digest"])
    )
    dossier = v.empty_dossier()
    dossier.update(
        question="Does a registered mechanism survive costs?",
        variant="explicit synthetic variant",
        reported_results="Original paper's claims are not project evidence",
        reproduced_results="Only scalar arithmetic tested",
        limitations="Historical data unavailable",
        disposition="DEFERRED",
        disposition_reason="No authorized point-in-time data",
        equation_links=[
            {
                "section": "Synthetic equation 1",
                "function": "package.module:compute",
                "assumptions": "Known inputs only",
                "oracle": "tests/test_example.py:test_scalar",
            }
        ],
    )
    updated = service.update(
        pid(paper),
        expected_digest=head(paper),
        dossier=dossier,
        reproduction={"status": "SYNTHETIC_SOFTWARE_ONLY", "experiment_ids": []},
    )
    with pytest.raises(StaleWriterError):
        service.update(pid(paper), expected_digest=head(paper), dossier=dossier)
    replaced = service.attach(
        pid(paper),
        b"new exact text version",
        media_type="text/plain",
        declared_license="synthetic",
        expected_digest=head(updated),
    )
    assert (
        v.record(replaced["document"])["raw_digest"]
        != v.record(paper["document"])["raw_digest"]
    )
    assert (
        service.objects.read_bytes(cast(str, v.record(paper["document"])["raw_digest"]))
        == original
    )
    assert v.record(replaced["reading"])["status"] == "UNREAD"
    assert (
        updated["claim_authority"] == "DECLARED_DOCUMENTATION_NOT_SCIENTIFIC_APPROVAL"
    )


def crossref() -> bytes:
    return json.dumps(
        {
            "status": "ok",
            "message": {
                "DOI": "10.1234/example",
                "title": ["Synthetic deposited title"],
                "author": [{"given": "Example", "family": "Author"}],
                "published": {"date-parts": [[2026, 1, 1]]},
            },
        }
    ).encode()


def test_explicit_crossref_metadata_and_primary_text_workflow(
    service: PublicationService,
) -> None:
    paper = service.create_reference(doi="10.1234/EXAMPLE")
    assert v.record(paper["metadata"])["year"] is None
    client = FakeTransport(t.FetchResponse(200, crossref(), "application/json"))
    service.transport = client
    retrieved = service.retrieve_metadata(pid(paper), expected_digest=head(paper))
    assert v.record(retrieved["metadata"])["title"] == "Synthetic deposited title"
    assert retrieved["text_access"] == "UNAVAILABLE"
    assert v.record(retrieved["reading"])["status"] == "UNREAD"
    assert client.requests == [
        t.FetchRequest("https://api.crossref.org/works/10.1234%2Fexample", "CROSSREF")
    ]
    raw = pdf()
    service.transport = FakeTransport(t.FetchResponse(200, raw, "application/pdf"))
    downloaded = service.fetch_primary(
        pid(paper),
        "https://authors.example.edu/paper.pdf",
        declared_license="Uploader declaration; independent rights review required",
        expected_digest=head(retrieved),
    )
    assert (
        v.record(downloaded["document"])["origin"]
        == "https://authors.example.edu/paper.pdf"
    )
    assert downloaded["text_access"] == "UNAVAILABLE"
    assert (
        service.extract(pid(paper), expected_digest=head(downloaded))["text_access"]
        == "COMPLETE"
    )


@pytest.mark.parametrize(
    "response",
    [
        t.FetchResponse(302, b"redirect", "application/pdf"),
        t.FetchResponse(200, b"<html>untrusted</html>", "text/html"),
        t.FetchResponse(200, b"x" * (v.MAX_RAW + 1), "text/plain"),
        TimeoutError("secret-shaped exception text"),
        t.FetchResponse(200, b"not json", "application/json"),
    ],
)
def test_http_and_metadata_failures_retained_without_payload_diagnostics(
    service: PublicationService, response: t.FetchResponse | Exception
) -> None:
    paper = service.create(copy.deepcopy(META))
    service.transport = FakeTransport(response)
    with pytest.raises(PublicationError) as error:
        service.retrieve_metadata(pid(paper), expected_digest=head(paper))
    assert "secret-shaped" not in str(error.value)
    retained = service.get(pid(paper))
    assert (
        v.record(cast(list[JsonValue], retained["attempts"])[-1])["status"] == "FAILED"
    )
    assert retained["metadata_capture"] is None


@pytest.mark.parametrize(
    "url",
    [
        "http://authors.example.edu/a",
        "file:///C:/private",
        "https://user:pass@authors.example.edu/paper",
        "https://127.0.0.1/a",
        "https://[::1]/a",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/a",
        "https://evil.local/a",
        "https://authors.example.edu:443/a",
        "https://authors.example.edu/a?token=secret",
        "https://authors.example.edu/a#fragment",
        "https://authors.example.edu/../secret",
        "https://authors.example.edu/%2e%2e/secret",
        "https://authors.example.edu/%252e%252e/secret",
        "https://authors.example.edu/\\secret",
        "https://authors.example.edu/%0d%0aHost:localhost",
        "https://authors.example.edu./a",
        "https://authors.example.edu/a\n",
        "https://áuthors.example.edu/a",
    ],
)
def test_ssrf_url_admission(url: str) -> None:
    with pytest.raises(PublicationError):
        v.public_url(url)


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["::1"],
        ["169.254.169.254"],
        ["10.1.1.1"],
        ["93.184.216.34", "192.168.1.1"],
        [],
    ],
)
def test_all_dns_answers_must_be_public(
    monkeypatch: pytest.MonkeyPatch, addresses: list[str]
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [(2, 1, 6, "", (ip, 443)) for ip in addresses],
    )
    with pytest.raises(PublicationError):
        t.public_address("authors.example.edu")


def test_public_dns_and_endpoint_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert t.public_address("authors.example.edu") == "93.184.216.34"
    for url, purpose in [
        ("https://evil.example/works/10.1234/a", "CROSSREF"),
        ("https://api.crossref.org/evil", "CROSSREF"),
        ("https://authors.example.edu/paper", "EXECUTE"),
    ]:
        with pytest.raises(PublicationError):
            t.FetchRequest(url, purpose)


def test_environment_source_archive_is_required_on_every_read(
    service: PublicationService,
) -> None:
    paper = service.create(copy.deepcopy(META))
    environment = v.record(
        parse_json_document(service.objects.read_bytes(service.environment_digest))
    )
    service.objects.object_path(
        cast(str, environment["source_snapshot_digest"])
    ).write_bytes(b"corrupt")
    with pytest.raises(ObjectCorruptionError):
        service.get(pid(paper))
    with pytest.raises(ObjectCorruptionError):
        PublicationService(
            service.registry,
            service.objects,
            code_revision=CODE,
            environment_digest=service.environment_digest,
        )


@pytest.mark.parametrize("target", ["raw", "text", "manifest"])
def test_retained_immutable_bytes_tampering_rejected(
    service: PublicationService, target: str
) -> None:
    paper = upload(service)
    paper = service.extract(pid(paper), expected_digest=head(paper))
    digest = (
        paper["manifest_digest"]
        if target == "manifest"
        else v.record(paper["document"])["raw_digest"]
        if target == "raw"
        else v.record(paper["text"])["text_digest"]
    )
    service.objects.object_path(cast(str, digest)).write_bytes(b"tampered exact bytes")
    with pytest.raises(ObjectCorruptionError):
        service.get(pid(paper))


def hostile_revision(
    service: PublicationService, paper: JsonRecord, change: Callable[[JsonRecord], None]
) -> None:
    _, manifest = service._head(pid(paper))
    change(manifest)
    service.registry.append(pid(paper), head(paper), service._registry_record(manifest))


@pytest.mark.parametrize(
    "field", ["identity", "access", "size", "attempt", "reading", "text_source"]
)
def test_correctly_rehashed_contradictory_graph_rejected(
    service: PublicationService, field: str
) -> None:
    paper = upload(service)
    paper = service.extract(pid(paper), expected_digest=head(paper))
    foreign = service.create(copy.deepcopy(META))

    def change(manifest: JsonRecord) -> None:
        if field == "identity":
            manifest["paper_id"] = pid(foreign)
        elif field == "access":
            manifest["text_access"] = "UNAVAILABLE"
        elif field == "size":
            v.record(manifest["document"])["byte_size"] = 99
        elif field == "attempt":
            v.record(cast(list[JsonValue], manifest["attempts"])[0])["status"] = (
                "FAILED"
            )
        elif field == "reading":
            v.record(manifest["reading"])["status"] = "FULL"
        else:
            descriptor = v.record(manifest["text"])
            evidence = service.get_text(pid(paper))
            evidence["raw_digest"] = service.objects.publish(
                b"foreign synthetic bytes"
            ).digest
            descriptor["raw_digest"] = evidence["raw_digest"]
            descriptor["text_digest"] = service._publish(evidence)

    hostile_revision(service, paper, change)
    with pytest.raises(PublicationError):
        service.get(pid(paper))


def test_governed_schema_cannot_accept_unknown_or_missing_fields(
    service: PublicationService,
) -> None:
    paper = service.create(copy.deepcopy(META))
    _, manifest = service._head(pid(paper))
    malformed = service._registry_record(manifest) | {"scientific_approved": True}
    with pytest.raises(RecordSchemaError):
        service.registry.append(pid(paper), head(paper), malformed)
    malformed.pop("scientific_approved")
    malformed.pop("manifest_digest")
    with pytest.raises(RecordSchemaError):
        service.registry.append(pid(paper), head(paper), malformed)


@pytest.mark.parametrize(
    "kind", ["title", "year", "authors", "doi", "url", "secret", "unknown"]
)
def test_invalid_metadata_cannot_allocate_identity(
    service: PublicationService, kind: str
) -> None:
    metadata = copy.deepcopy(META)
    if kind == "title":
        metadata["title"] = ""
    elif kind == "year":
        metadata["year"] = True
    elif kind == "authors":
        metadata["authors"] = []
    elif kind == "doi":
        metadata["doi"] = "invalid"
    elif kind == "url":
        metadata["url"] = "https://localhost/secret"
    elif kind == "secret":
        metadata["title"] = "api_key=synthetic-secret"
    else:
        metadata["execute"] = "forbidden"
    with pytest.raises(PublicationError):
        service.create(metadata)
    assert service.registry.verify_all() == {}


def test_dossier_reading_and_reproduction_constraints(
    service: PublicationService,
) -> None:
    paper = service.create(copy.deepcopy(META))
    for value in [
        {"status": "FULL"},
        {**v.empty_dossier(), "disposition": "APPROVED"},
        {**v.empty_dossier(), "equation_links": [{}]},
    ]:
        with pytest.raises(PublicationError):
            service.update(
                pid(paper), expected_digest=head(paper), dossier=cast(JsonRecord, value)
            )
    for reproduction in [
        {"status": "PROFITABLE", "experiment_ids": []},
        {"status": "LINKED_EXPERIMENTS", "experiment_ids": []},
        {"status": "LINKED_EXPERIMENTS", "experiment_ids": [pid(paper)]},
    ]:
        with pytest.raises(PublicationError):
            service.update(
                pid(paper),
                expected_digest=head(paper),
                reproduction=cast(JsonRecord, reproduction),
            )
    with pytest.raises(PublicationError):
        service.update(
            pid(paper),
            expected_digest=head(paper),
            reading={
                "status": "FULL",
                "reader": "reader",
                "note": "abstract only",
                "text_digest": None,
                "pages": [1],
            },
        )
    with pytest.raises(PublicationError):
        service.list_papers([pid(paper), pid(paper)])


class FakeHTTPResponse:
    def __init__(
        self,
        body: bytes = b"synthetic source text",
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status, self.body = status, body
        self.headers = {"Content-Type": "text/plain", **(headers or {})}
        self.offset = 0

    def getheader(self, key: str, default: str = "") -> str:
        return self.headers.get(key, default)

    def read1(self, maximum: int) -> bytes:
        result = self.body[self.offset : self.offset + maximum]
        self.offset += len(result)
        return result


def wired_http(
    monkeypatch: pytest.MonkeyPatch, response: FakeHTTPResponse
) -> tuple[Mock, Mock, Mock]:
    connection, raw, secure = Mock(), Mock(), Mock()
    connection.getresponse.return_value = response
    monkeypatch.setattr(http.client, "HTTPSConnection", lambda *_a, **_k: connection)
    monkeypatch.setattr(t, "public_address", lambda _host: "93.184.216.34")
    monkeypatch.setattr(socket, "create_connection", Mock(return_value=raw))
    context = Mock()
    context.wrap_socket.return_value = secure
    monkeypatch.setattr(ssl, "create_default_context", lambda: context)
    return connection, raw, context


def test_real_transport_contract_pins_tls_and_sends_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, raw, context = wired_http(
        monkeypatch, FakeHTTPResponse(headers={"Content-Length": "21"})
    )
    result = t.PublicationHTTPS._send_once(
        t.FetchRequest("https://authors.example.edu/paper.txt", "PRIMARY_TEXT")
    )
    assert result.body == b"synthetic source text"
    cast(Mock, socket.create_connection).assert_called_once_with(
        ("93.184.216.34", 443), timeout=10
    )
    context.wrap_socket.assert_called_once_with(
        raw, server_hostname="authors.example.edu"
    )
    args = connection.request.call_args
    assert args.args == ("GET", "/paper.txt")
    assert set(args.kwargs["headers"]) == {"User-Agent", "Accept", "Accept-Encoding"}
    assert args.kwargs["headers"]["Accept-Encoding"] == "identity"
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "kind",
    [
        "redirect",
        "error",
        "encoding",
        "large-length",
        "bad-length",
        "media",
        "large-body",
        "empty",
        "short-body",
        "timeout",
        "socket",
        "tls",
    ],
)
def test_real_transport_failures_close_without_redirect_or_reflection(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    response = FakeHTTPResponse()
    if kind == "redirect":
        response.status = 302
    elif kind == "error":
        response.status = 403
    elif kind == "encoding":
        response.headers["Content-Encoding"] = "gzip"
    elif kind == "large-length":
        response.headers["Content-Length"] = str(v.MAX_RAW + 1)
    elif kind == "bad-length":
        response.headers["Content-Length"] = "-5"
    elif kind == "media":
        response.headers["Content-Type"] = "text/html"
    elif kind == "large-body":
        response.body = b"x" * (v.MAX_RAW + 1)
    elif kind == "empty":
        response.body = b""
    elif kind == "short-body":
        response.headers["Content-Length"] = "99"
    connection, raw, context = wired_http(monkeypatch, response)
    if kind == "timeout":
        connection.getresponse.side_effect = TimeoutError("untrusted exception")
    elif kind == "socket":
        connection.getresponse.side_effect = OSError("untrusted exception")
    elif kind == "tls":
        context.wrap_socket.side_effect = ssl.SSLError("untrusted exception")
    with pytest.raises(PublicationError) as error:
        t.PublicationHTTPS._send_once(
            t.FetchRequest("https://authors.example.edu/paper.txt", "PRIMARY_TEXT")
        )
    assert "untrusted" not in str(error.value)
    connection.close.assert_called_once()
    if kind == "tls":
        raw.close.assert_called_once()
    assert connection.request.call_count <= 1


def test_crossref_transport_mime_and_body_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = crossref()
    connection, _raw, _context = wired_http(
        monkeypatch,
        FakeHTTPResponse(
            payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(payload)),
            },
        ),
    )
    assert (
        t.PublicationHTTPS._send_once(t.crossref_request("10.1234/example")).body
        == payload
    )
    assert (
        connection.request.call_args.kwargs["headers"]["Accept"] == "application/json"
    )
    import quant_hunter.publications.transport as module

    times = iter([0, 11])
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(times)))
    with pytest.raises(PublicationError, match="TIMEOUT"):
        t.PublicationHTTPS._send_once(t.crossref_request("10.1234/example"))


def test_bounded_synthetic_parser_core_and_worker_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Direct core tests only use small, generated bytes; application calls always spawn.
    result = e._pdf(pdf(pages=2), 0, 2)
    assert result["access"] == "COMPLETE"
    with pytest.raises(PublicationError, match="ACTIVE"):
        e._pdf(pdf(active=True), 0, 1)
    with pytest.raises(PublicationError, match="ENCRYPTED"):
        e._pdf(pdf(encrypted=True), 0, 1)
    with pytest.raises(PublicationError, match="PAGE"):
        e._pdf(pdf(), 2, 1)
    fake = Mock()
    monkeypatch.setattr(logging, "disable", Mock())
    monkeypatch.setattr(e, "_limits", lambda: "SYNTHETIC_MOCK")
    e._worker(fake, pdf(), 0, 1)
    assert fake.send.call_args.args[0]["ok"]["pages"][0]["page"] == 1
    e._worker(fake, pdf(active=True), 0, 1)
    assert fake.send.call_args.args[0] == {"error": "ACTIVE_PDF_CONTENT_REFUSED"}
    e._worker(fake, b"%PDF-malformed", 0, 1)
    assert fake.send.call_args.args[0] == {"error": "PDF_EXTRACTION_FAILED"}


@pytest.mark.parametrize("failure", ["none", "create", "set", "assign"])
def test_windows_job_limit_contract_fail_closed_without_parent_mutation(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    api = Mock()
    api.CreateJobObjectW.return_value = 0 if failure == "create" else 456
    api.SetInformationJobObject.return_value = 0 if failure == "set" else 1
    api.AssignProcessToJobObject.return_value = 0 if failure == "assign" else 1
    api.GetCurrentProcess.return_value = 789
    monkeypatch.setattr(e, "_platform", lambda: "win32")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_a, **_k: api, raising=False)
    if failure == "none":
        assert e._limits() == "WINDOWS_JOB_MEMORY_CPU"
        api.AssignProcessToJobObject.assert_called_once_with(456, 789)
        settings = cast(e._Extended, api.SetInformationJobObject.call_args.args[2]._obj)
        assert settings.process_memory == e.PROCESS_MEMORY
        assert settings.basic.active_processes == 1
        assert settings.basic.process_time == 50_000_000
        assert settings.basic.flags == 0x210A
    else:
        with pytest.raises(PublicationError, match="UNAVAILABLE"):
            e._limits()
        if failure != "create":
            api.CloseHandle.assert_called_once_with(456)


@pytest.mark.parametrize(
    "kind", ["empty", "utf8", "nul", "huge-text", "wrong-type", "missing-license"]
)
def test_upload_failures_are_bounded_and_audited(
    service: PublicationService, kind: str
) -> None:
    paper = service.create(copy.deepcopy(META))
    raw, media, license = b"test", "text/plain", "synthetic"
    if kind == "empty":
        raw = b""
    elif kind == "utf8":
        raw = b"\xff\xfe"
    elif kind == "nul":
        raw = b"nul\x00text"
    elif kind == "huge-text":
        raw = b"x" * (v.MAX_TEXT + 1)
    elif kind == "wrong-type":
        media = "text/html"
    else:
        license = ""
    with pytest.raises(PublicationError):
        service.attach(
            pid(paper),
            raw,
            media_type=media,
            declared_license=license,
            expected_digest=head(paper),
        )
    retained = service.get(pid(paper))
    assert retained["document"] is None
    assert (
        v.record(cast(list[JsonValue], retained["attempts"])[-1])["status"] == "FAILED"
    )


def test_metadata_override_preserves_prior_capture_and_blanks_read_unavailable(
    service: PublicationService,
) -> None:
    paper = service.create(copy.deepcopy(META))
    service.transport = FakeTransport(
        t.FetchResponse(200, crossref(), "application/json")
    )
    captured = service.retrieve_metadata(pid(paper), expected_digest=head(paper))
    changed = service.update(
        pid(paper), expected_digest=head(captured), metadata=copy.deepcopy(META)
    )
    assert changed["metadata_capture"] is None
    assert service.objects.get(
        cast(str, v.record(captured["metadata_capture"])["raw_digest"])
    )
    empty = service.attach(
        pid(paper),
        b" \n",
        media_type="text/plain",
        declared_license="synthetic",
        expected_digest=head(changed),
    )
    assert (
        service.extract(pid(paper), expected_digest=head(empty))["text_access"]
        == "UNAVAILABLE"
    )


def test_ten_original_reference_suggestions_do_not_fake_text_access(
    service: PublicationService,
) -> None:
    suggestions = canonical_references()
    assert [item["domain"] for item in suggestions] == [
        f"CRP-{i:02d}" for i in range(1, 11)
    ]
    assert len({v.record(item["metadata"])["url"] for item in suggestions}) == 10
    for item in suggestions:
        paper = service.create(v.record(item["metadata"]))
        updated = service.update(
            pid(paper), expected_digest=head(paper), dossier=v.record(item["dossier"])
        )
        assert updated["text_access"] == "UNAVAILABLE"
        assert v.record(updated["reading"])["status"] == "UNREAD"
        assert v.record(updated["reproduction"])["status"] == "NOT_ATTEMPTED"
        assert v.record(updated["dossier"])["equation_links"]
    v.record(suggestions[0]["metadata"])["title"] = "changed copy"
    assert (
        v.record(canonical_references()[0]["metadata"])["title"]
        == "Time Series Momentum"
    )


@pytest.mark.parametrize(
    "change",
    [
        "capture",
        "text_descriptor",
        "resource",
        "page_number",
        "text_bound",
        "missing_evidence",
    ],
)
def test_additional_rehashed_provenance_contradictions(
    service: PublicationService, change: str
) -> None:
    paper = upload(service)
    service.transport = FakeTransport(
        t.FetchResponse(200, crossref(), "application/json")
    )
    paper = service.retrieve_metadata(pid(paper), expected_digest=head(paper))
    paper = service.extract(pid(paper), expected_digest=head(paper))

    def mutate(manifest: JsonRecord) -> None:
        if change == "capture":
            v.record(manifest["metadata"])["title"] = "Foreign metadata"
        elif change == "text_descriptor":
            v.record(manifest["text"])["pages"] = [2]
        else:
            evidence = service.get_text(pid(paper))
            if change == "resource":
                evidence["resource_boundary"] = "HOST_ENFORCED"
            elif change == "page_number":
                v.record(cast(list[JsonValue], evidence["pages"])[0])["page"] = 999
            elif change == "text_bound":
                v.record(cast(list[JsonValue], evidence["pages"])[0])["text"] = "x" * (
                    v.MAX_TEXT + 1
                )
            else:
                evidence.pop("raw_digest")
            v.record(manifest["text"])["text_digest"] = service._publish(evidence)

    hostile_revision(service, paper, mutate)
    with pytest.raises(PublicationError):
        service.get(pid(paper))


def test_fixed_limits_and_metadata_errors_are_fail_closed(
    service: PublicationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(PublicationError):
        PublicationService(
            service.registry,
            service.objects,
            code_revision="not-code",
            environment_digest=service.environment_digest,
        )
    with pytest.raises(PublicationError):
        service.create_reference()
    with pytest.raises(PublicationError):
        v.dossier(v.empty_dossier() | {"equation_links": [{}] * 65})
    paper = service.create(copy.deepcopy(META))
    monkeypatch.setattr(v, "MAX_ATTEMPTS", 0)
    with pytest.raises(PublicationError, match="ATTEMPT_LIMIT"):
        service.attach(
            pid(paper),
            b"valid",
            media_type="text/plain",
            declared_license="synthetic",
            expected_digest=head(paper),
        )


def _synthetic_http_worker(
    connection: Connection, payload: bytes, start: int, count: int
) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        wired_http(monkeypatch, FakeHTTPResponse(headers={"Content-Length": "21"}))
        t._network_worker(connection, payload, start, count)


def _mark_stall() -> None:
    Path(os.environ["QH_SYNTHETIC_NETWORK_MARKER"]).write_bytes(
        b"entered-stalled-network-stage"
    )
    time.sleep(30)


def _slow_dns_worker(
    connection: Connection, payload: bytes, start: int, count: int
) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(t, "public_address", lambda _host: _mark_stall())
        t._network_worker(connection, payload, start, count)


def _slow_headers_worker(
    connection: Connection, payload: bytes, start: int, count: int
) -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        conn, _raw, _context = wired_http(monkeypatch, FakeHTTPResponse())
        conn.getresponse.side_effect = _mark_stall
        t._network_worker(connection, payload, start, count)


def test_public_transport_runs_real_resource_limited_child_with_synthetic_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(t, "_network_worker", _synthetic_http_worker)
    response = t.PublicationHTTPS().send(
        t.FetchRequest("https://authors.example.edu/paper.txt", "PRIMARY_TEXT")
    )
    assert response.body == b"synthetic source text"
    assert response.media_type == "text/plain"


@pytest.mark.parametrize("stage", ["dns", "headers"])
def test_network_total_deadline_covers_dns_headers_and_reaps_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    marker = tmp_path / "network-stall.bin"
    monkeypatch.setenv("QH_SYNTHETIC_NETWORK_MARKER", str(marker))
    monkeypatch.setattr(t, "NETWORK_DEADLINE", 3.0)
    monkeypatch.setattr(
        t,
        "_network_worker",
        _slow_dns_worker if stage == "dns" else _slow_headers_worker,
    )
    before = {p.pid for p in multiprocessing.active_children()}
    began = time.monotonic()
    with pytest.raises(PublicationError, match="HTTP_TOTAL_TIMEOUT"):
        t.PublicationHTTPS().send(
            t.FetchRequest("https://authors.example.edu/paper.txt", "PRIMARY_TEXT")
        )
    assert marker.read_bytes() == b"entered-stalled-network-stage"
    assert time.monotonic() - began < 8
    assert {p.pid for p in multiprocessing.active_children()} == before


def test_network_worker_sanitizes_errors_and_preserves_deadline_failure_audit(
    service: PublicationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging, "disable", Mock())
    monkeypatch.setattr(t, "_limits", lambda: "SYNTHETIC_MOCK")
    connection = Mock()
    t._network_worker(connection, b"x" * 4097, 0, 0)
    assert connection.send.call_args.args[0] == {"error": "FETCH_REQUEST_LIMIT"}
    t._network_worker(connection, b"invalid synthetic JSON", 0, 0)
    assert connection.send.call_args.args[0] == {"error": "HTTP_NETWORK_FAILURE"}
    monkeypatch.setattr(
        t.PublicationHTTPS,
        "_send_once",
        lambda _request: t.FetchResponse(200, b"text", "text/plain"),
    )
    payload = json.dumps(
        {"url": "https://authors.example.edu/paper.txt", "purpose": "PRIMARY_TEXT"}
    ).encode()
    t._network_worker(connection, payload, 0, 0)
    assert connection.send.call_args.args[0]["ok"]["body"] == b"text"
    paper = service.create(copy.deepcopy(META))

    def timed_out(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise PublicationError("EXTRACTION_TIMEOUT")

    monkeypatch.setattr(t, "_run", timed_out)
    with pytest.raises(PublicationError, match="HTTP_TOTAL_TIMEOUT"):
        service.fetch_primary(
            pid(paper),
            "https://authors.example.edu/paper.txt",
            declared_license="synthetic",
            expected_digest=head(paper),
        )
    retained = service.get(pid(paper))
    assert (
        v.record(cast(list[JsonValue], retained["attempts"])[-1])["error"]
        == "HTTP_TOTAL_TIMEOUT"
    )
