"""Private publication workflows with real stores and synthetic documents only."""

from __future__ import annotations

import asyncio
import base64
import hmac
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import quant_hunter.web.state as state_module
from quant_hunter.config import JsonRecord
from quant_hunter.config.canonical import canonicalize_json
from quant_hunter.identity import RegistryStore
from quant_hunter.lab import LabService
from quant_hunter.publications import PublicationService
from quant_hunter.publications.transport import FetchRequest, FetchResponse
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.web.publication_access import PublicationAccess
from quant_hunter.web.publication_routes import install_publication_routes
from quant_hunter.web.state import AccessError, AppState, Session, User

SCHEMAS = Path(state_module.__file__).parents[3] / "schemas" / "v1"
META: JsonRecord = {
    "title": "Synthetic note",
    "authors": ["Test Author"],
    "year": 2026,
    "doi": "10.1234/example",
    "url": None,
    "version": "synthetic1",
}


class LocalClient:
    """Real ASGI requests without Starlette's deprecated httpx compatibility shim."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.cookies = httpx.Cookies()
        self.headers = httpx.Headers()

    def request(self, method: str, path: str, body: object = None) -> httpx.Response:
        async def send() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
                headers=self.headers,
                cookies=self.cookies,
            ) as client:
                return await client.request(method, path, json=body)

        return asyncio.run(send())

    def get(self, path: str) -> httpx.Response:
        return self.request("GET", path)

    def post(self, path: str, *, json: object) -> httpx.Response:
        return self.request("POST", path, json)


class Transport:
    def __init__(self) -> None:
        self.response: FetchResponse | BaseException = FetchResponse(
            200, b"Synthetic paper", "text/plain"
        )
        self.requests: list[FetchRequest] = []

    def send(self, request: FetchRequest) -> FetchResponse:
        self.requests.append(request)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


@dataclass
class Harness:
    access: PublicationAccess
    client: LocalClient
    owner: User
    other: User
    reader: User
    sessions: dict[str, tuple[str, str]]
    transport: Transport

    def login(self, name: str) -> None:
        token, csrf = self.sessions[name]
        self.client.cookies.set("qh_session", token)
        self.client.headers["x-csrf-token"] = csrf

    def create(self) -> dict[str, object]:
        response = self.client.post("/api/publications", json={"metadata": META})
        assert response.status_code == 201, response.text
        return cast(dict[str, object], response.json())


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    state = AppState(tmp_path / "state.sqlite3")
    owner = state.create_user(
        "owner", "synthetic test password", "owner", bootstrap=True
    )
    other = state.create_user(
        "other", "synthetic test password", "researcher", bootstrap=False
    )
    reader = state.create_user(
        "reader", "synthetic test password", "reader", bootstrap=False
    )
    sessions: dict[str, tuple[str, str]] = {}
    for user in (owner, other, reader):
        token, session = state.login(user.username, "synthetic test password")
        sessions[user.username] = token, session.csrf
    objects = ImmutableObjectStore(tmp_path / "objects")
    environment = objects.publish(canonicalize_json({"evidence_mode": "SYNTHETIC"}))
    transport = Transport()
    service = PublicationService(
        RegistryStore.governed(tmp_path / "registry", SCHEMAS),
        objects,
        code_revision="a" * 40,
        environment_digest=environment.digest,
        transport=transport,
    )
    access = PublicationAccess(state, service, capacity=lambda: None)
    app = FastAPI()

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        try:
            session = state.session(request.cookies.get("qh_session", ""))
        except AccessError:
            raise HTTPException(401, "Sign in") from None
        if mutation and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), session.csrf
        ):
            raise HTTPException(403, "CSRF")
        if owner and session.user.role != "owner":
            raise HTTPException(403, "Owner required")
        return session

    install_publication_routes(app, authenticated, access)
    result = Harness(
        access, LocalClient(app), owner, other, reader, sessions, transport
    )
    result.login("owner")
    return result


def digest(paper: dict[str, object]) -> str:
    return cast(str, paper["revision_digest"])


def path(paper: dict[str, object]) -> str:
    return f"/api/publications/{paper['paper_id']}"


def attach(
    h: Harness,
    paper: dict[str, object],
    raw: bytes = b"Synthetic original text",
    media: str = "text/plain",
) -> dict[str, object]:
    response = h.client.post(
        path(paper) + "/attachment",
        json={
            "expected_digest": digest(paper),
            "content_base64": base64.b64encode(raw).decode(),
            "media_type": media,
            "declared_license": "Synthetic author permission",
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, object], response.json())


def test_reference_is_offline_private_and_persisted(harness: Harness) -> None:
    h = harness
    response = h.client.post("/api/publications", json={"doi": "10.1234/example"})
    assert response.status_code == 201 and h.transport.requests == []
    paper = response.json()
    assert (
        paper["reading"]["status"] == "UNREAD" and paper["text_access"] == "UNAVAILABLE"
    )
    restored = PublicationAccess(
        AppState(h.access.state.path), h.access.service, capacity=lambda: None
    )
    assert restored.get(h.owner, paper["paper_id"]) == paper
    assert h.client.get("/api/publications").json()["publications"] == [paper]
    assert (
        h.client.get("/api/publication-operations").json()["operations"][0]["status"]
        == "SUCCEEDED"
    )
    h.login("other")
    assert h.client.get("/api/publications").json() == {"publications": []}
    assert h.client.get("/api/publication-operations").json() == {"operations": []}
    assert h.client.get(path(paper)).status_code == 403


def test_text_dossier_reading_and_version_cas_roundtrip(harness: Harness) -> None:
    h = harness
    first = h.create()
    paper = attach(h, first)
    response = h.client.post(
        path(paper) + "/extract", json={"expected_digest": digest(paper)}
    )
    assert response.status_code == 200
    extracted = response.json()
    text = h.client.get(path(paper) + "/text").json()
    assert text["pages"] == [{"page": 1, "text": "Synthetic original text"}]
    dossier = extracted["dossier"]
    dossier["question"] = "Does the example satisfy its stated identity?"
    reading = {
        "status": "FULL",
        "reader": "Test reader",
        "note": "Explicit test declaration",
        "text_digest": extracted["text"]["text_digest"],
        "pages": [1],
    }
    updated = h.client.post(
        path(paper),
        json={
            "expected_digest": digest(extracted),
            "dossier": dossier,
            "reading": reading,
            "reproduction": {"status": "SYNTHETIC_SOFTWARE_ONLY", "experiment_ids": []},
        },
    )
    assert updated.status_code == 200 and updated.json()["reading"] == reading
    assert (
        h.client.post(
            path(paper), json={"expected_digest": digest(first), "metadata": META}
        ).status_code
        == 409
    )
    assert h.access.operations(h.owner)[0]["error"] == "STALE_REVISION"
    assert (
        h.access.service.objects.read_bytes(text["raw_digest"])
        == b"Synthetic original text"
    )
    replaced = attach(h, updated.json(), b"Corrected document")
    assert (
        replaced["text_access"] == "UNAVAILABLE"
        and cast(dict[str, object], replaced["reading"])["status"] == "UNREAD"
    )


def synthetic_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=100)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 10 Tf 10 50 Td (Synthetic PDF) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def test_actual_pdf_child_extraction_through_authenticated_app(
    harness: Harness,
) -> None:
    h = harness
    raw = synthetic_pdf()
    paper = attach(h, h.create(), raw, "application/pdf")
    response = h.client.post(
        path(paper) + "/extract",
        json={"expected_digest": digest(paper), "page_start": 0, "page_count": 1},
    )
    assert response.status_code == 200, response.text
    text = h.client.get(path(paper) + "/text").json()
    assert "Synthetic PDF" in text["pages"][0]["text"] and text["ocr"] is False
    assert h.access.service.objects.read_bytes(text["raw_digest"]) == raw


@pytest.mark.parametrize(
    "suffix,body",
    [
        ("", {"metadata": META}),
        (
            "/attachment",
            {
                "content_base64": "eA==",
                "media_type": "text/plain",
                "declared_license": "Synthetic",
            },
        ),
        ("/extract", {}),
        ("/metadata/retrieve", {}),
        (
            "/fetch",
            {"url": "https://example.edu/paper.txt", "declared_license": "Synthetic"},
        ),
    ],
)
def test_every_mutation_and_text_is_owner_private(
    harness: Harness, suffix: str, body: dict[str, object]
) -> None:
    h = harness
    paper = h.create()
    before = len(h.access.service.registry.verify_object(cast(str, paper["paper_id"])))
    h.login("other")
    assert (
        h.client.post(
            path(paper) + suffix, json={"expected_digest": digest(paper), **body}
        ).status_code
        == 403
    )
    assert h.client.get(path(paper) + "/text").status_code == 403
    assert (
        len(h.access.service.registry.verify_object(cast(str, paper["paper_id"])))
        == before
    )
    assert not h.transport.requests and not h.access.operations(h.other)


def test_reader_reads_owned_paper_but_cannot_mutate(harness: Harness) -> None:
    h = harness
    paper = attach(h, h.create())
    with h.access.state.connection() as db:
        db.execute(
            "UPDATE publication_ownership SET owner_id=? WHERE paper_id=?",
            (h.reader.id, paper["paper_id"]),
        )
    h.login("reader")
    assert h.client.get(path(paper)).status_code == 200
    assert (
        h.client.post(
            path(paper) + "/extract", json={"expected_digest": digest(paper)}
        ).status_code
        == 403
    )
    assert (
        h.client.post("/api/publications", json={"metadata": META}).status_code == 403
    )
    h.login("owner")
    assert h.client.get(path(paper)).status_code == 403


def test_login_csrf_and_disabled_library(harness: Harness) -> None:
    h = harness
    h.client.cookies.clear()
    assert h.client.get("/api/publications").status_code == 401
    h.login("owner")
    h.client.headers["x-csrf-token"] = "incorrect"
    assert (
        h.client.post("/api/publications", json={"metadata": META}).status_code == 403
    )
    app = FastAPI()

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        return Session(h.owner, "synthetic")

    install_publication_routes(app, authenticated, None)
    assert LocalClient(app).get("/api/publications").status_code == 503


def test_explicit_metadata_and_primary_fetch(harness: Harness) -> None:
    h = harness
    paper = h.create()
    h.transport.response = FetchResponse(
        200,
        json.dumps(
            {
                "status": "ok",
                "message": {
                    "DOI": "10.1234/example",
                    "title": ["Fetched synthetic title"],
                    "author": [{"given": "A", "family": "Writer"}],
                    "published": {"date-parts": [[2026]]},
                },
            }
        ).encode(),
        "application/json",
    )
    response = h.client.post(
        path(paper) + "/metadata/retrieve", json={"expected_digest": digest(paper)}
    )
    assert (
        response.status_code == 200
        and response.json()["metadata"]["title"] == "Fetched synthetic title"
    )
    h.transport.response = FetchResponse(200, b"Fetched synthetic text", "text/plain")
    response = h.client.post(
        path(paper) + "/fetch",
        json={
            "expected_digest": digest(response.json()),
            "url": "https://example.edu/paper.txt",
            "declared_license": "Synthetic permission",
        },
    )
    assert response.status_code == 200
    assert [r.purpose for r in h.transport.requests] == ["CROSSREF", "PRIMARY_TEXT"]
    assert response.json()["document"]["origin"] == "https://example.edu/paper.txt"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.edu/paper",
        "https://localhost/paper",
        "https://127.0.0.1/paper",
        "https://example.edu/paper?api_key=private",
    ],
)
def test_unsafe_reference_is_audited_without_network(
    harness: Harness, url: str
) -> None:
    h = harness
    paper = h.create()
    response = h.client.post(
        path(paper) + "/fetch",
        json={
            "expected_digest": digest(paper),
            "url": url,
            "declared_license": "Synthetic",
        },
    )
    assert response.status_code == 400 and not h.transport.requests
    assert h.access.operations(h.owner)[0]["status"] == "FAILED"
    assert "private" not in response.text


def test_failed_upload_and_network_are_sanitized_and_audited(harness: Harness) -> None:
    h = harness
    paper = h.create()
    response = h.client.post(
        path(paper) + "/attachment",
        json={
            "expected_digest": digest(paper),
            "content_base64": "YmFk",
            "media_type": "application/pdf",
            "declared_license": "Synthetic",
        },
    )
    assert response.status_code == 400 and response.json()["detail"]["revision_digest"]
    paper = h.client.get(path(paper)).json()
    h.transport.response = RuntimeError("secret-bearing unsafe provider message")
    response = h.client.post(
        path(paper) + "/fetch",
        json={
            "expected_digest": digest(paper),
            "url": "https://example.edu/paper.txt",
            "declared_license": "Synthetic",
        },
    )
    assert response.status_code == 400 and "secret-bearing" not in response.text
    operations = h.client.get("/api/publication-operations").json()
    assert "secret-bearing" not in json.dumps(operations)
    assert operations["operations"][0]["error"] == "HTTP_NETWORK_FAILURE"


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": "private arbitrary input"},
        {"page_count": 51},
        {"page_start": -1},
        {"page_count": True},
        {"page_count": "1"},
    ],
)
def test_closed_bounded_models_do_not_echo_input(
    harness: Harness, change: dict[str, object]
) -> None:
    paper = harness.create()
    response = harness.client.post(
        path(paper) + "/extract", json={"expected_digest": digest(paper), **change}
    )
    assert response.status_code == 422 and "private arbitrary" not in response.text


def test_base64_page_and_empty_update_limits(harness: Harness) -> None:
    paper = harness.create()
    response = harness.client.post(
        path(paper) + "/attachment",
        json={
            "expected_digest": digest(paper),
            "content_base64": "!!!!",
            "media_type": "text/plain",
            "declared_license": "Synthetic",
        },
    )
    assert response.status_code == 400
    assert (
        harness.client.post(
            path(paper), json={"expected_digest": digest(paper)}
        ).status_code
        == 422
    )
    assert harness.client.get("/api/publications?limit=51").status_code == 422


def test_capacity_failure_never_allocates_paper(harness: Harness) -> None:
    def full() -> None:
        raise AccessError("Synthetic disk quota")

    harness.access.capacity = full
    assert (
        harness.client.post("/api/publications", json={"metadata": META}).status_code
        == 403
    )
    assert harness.access.service.registry.verify_all() == {}


def test_global_two_active_same_paper_and_total_admission(harness: Harness) -> None:
    h = harness
    paper = h.create()
    active = h.access._begin(h.owner, "TEST", cast(str, paper["paper_id"]))
    with pytest.raises(AccessError, match="active"):
        h.access._begin(h.owner, "TEST", cast(str, paper["paper_id"]))
    with h.access.state.connection() as db:
        db.executescript(
            "CREATE TABLE data_operations(status TEXT NOT NULL); INSERT INTO data_operations VALUES('RUNNING');"
        )
    with pytest.raises(AccessError, match="busy"):
        h.access.create(h.owner, META)
    h.access._finish(active, error="SYNTHETIC_STOP")
    with h.access.state.connection() as db:
        db.execute("DELETE FROM data_operations")
        for i in range(498):
            db.execute(
                "INSERT INTO publication_operations VALUES(?,?,?,NULL,0,'FAILED',NULL,'SYNTHETIC')",
                (f"quota{i}", h.owner.id, "TEST"),
            )
    with pytest.raises(AccessError, match="quota"):
        h.access.create(h.owner, META)
    assert len(h.access.operations(h.owner)) == 100


def test_interrupted_fetch_recovery_never_replays(harness: Harness) -> None:
    h = harness
    paper = h.create()
    h.transport.response = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        h.access.fetch_primary(
            h.owner,
            cast(str, paper["paper_id"]),
            "https://example.edu/paper.txt",
            expected_digest=digest(paper),
            declared_license="Synthetic",
        )
    assert h.access.operations(h.owner)[0]["status"] == "RUNNING"
    h.access.recover()
    h.access.recover()
    assert len(h.transport.requests) == 1
    assert h.access.operations(h.owner)[0]["status"] == "INTERRUPTED"
    retained = h.access.get(h.owner, cast(str, paper["paper_id"]))
    assert cast(list[JsonRecord], retained["attempts"])[-1]["error"] == "INTERRUPTED"


def test_foreign_experiment_refused_before_write(harness: Harness) -> None:
    h = harness
    paper = h.create()
    identity = "EXP-019947a8-7920-7000-8000-000000000001"
    foreign = h.access.state.enqueue(h.other, {"synthetic": 1})
    with h.access.state.connection() as db:
        db.execute("UPDATE jobs SET experiment_id=? WHERE id=?", (identity, foreign.id))
    response = h.client.post(
        path(paper),
        json={
            "expected_digest": digest(paper),
            "reproduction": {
                "status": "LINKED_EXPERIMENTS",
                "experiment_ids": [identity],
            },
        },
    )
    assert response.status_code == 403
    assert h.access.get(h.owner, cast(str, paper["paper_id"]))[
        "revision_digest"
    ] == digest(paper)
    assert len(h.access.operations(h.owner)) == 1


def test_unlinked_creation_remains_unclaimable_after_crash(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    original = h.access._finish

    def interrupted(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(h.access, "_finish", interrupted)
    with pytest.raises(KeyboardInterrupt):
        h.access.create(h.owner, META)
    monkeypatch.setattr(h.access, "_finish", original)
    h.access.recover()
    assert h.access.list(h.owner) == []
    identity = next(iter(h.access.service.registry.verify_all()))
    assert identity.startswith("PAPER-")
    with pytest.raises(AccessError):
        h.access.get(h.owner, identity)
    assert h.access.operations(h.owner)[0]["status"] == "INTERRUPTED"


def test_corrupt_evidence_is_private_sanitized_failure(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper = harness.create()

    def broken(_: str) -> JsonRecord:
        raise RuntimeError("untrusted text from corrupted immutable evidence")

    monkeypatch.setattr(harness.access.service, "get", broken)
    response = harness.client.get(path(paper))
    assert response.status_code == 503 and "untrusted text" not in response.text


def test_actual_owned_experiment_link_and_later_ownership_check(
    harness: Harness,
    tmp_path: Path,
) -> None:
    h = harness
    lab = LabService(tmp_path / "lab", SCHEMAS, "a" * 40, {"mode": "SYNTHETIC"})
    h.access.service = PublicationService(
        lab.registry,
        lab.objects,
        code_revision=lab.code_revision,
        environment_digest=lab.environment_digest,
        transport=h.transport,
    )
    identity = lab.begin_run(
        {
            "dataset_start": "2025-01-01T00:00:00Z",
            "dataset_end": "2025-01-04T00:00:00Z",
        },
        b"synthetic fixture",
    )
    job = h.access.state.enqueue(h.owner, {"synthetic": 1})
    with h.access.state.connection() as db:
        db.execute("UPDATE jobs SET experiment_id=? WHERE id=?", (identity, job.id))
    paper = h.create()
    response = h.client.post(
        path(paper),
        json={
            "expected_digest": digest(paper),
            "reproduction": {
                "status": "LINKED_EXPERIMENTS",
                "experiment_ids": [identity],
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["reproduction"]["experiment_ids"] == [identity]
    assert (
        lab.registry.verify_object(identity)[-1].record["lifecycle_status"] == "RUNNING"
    )
    with h.access.state.connection() as db:
        db.execute("UPDATE jobs SET owner_id=? WHERE id=?", (h.other.id, job.id))
    assert h.client.get(path(paper)).status_code == 403
    assert (
        h.client.post(
            path(paper) + "/extract", json={"expected_digest": digest(response.json())}
        ).status_code
        == 403
    )


def test_real_raw_tampering_blocks_read_and_interrupted_recovery(
    harness: Harness,
) -> None:
    h = harness
    paper = attach(h, h.create())
    identity = cast(str, paper["paper_id"])
    h.access._begin(h.owner, "EXTRACT", identity)
    doc = cast(dict[str, object], paper["document"])
    h.access.service.objects.object_path(cast(str, doc["raw_digest"])).write_bytes(
        b"changed bytes"
    )
    assert h.client.get(path(paper)).status_code == 503
    h.access.recover()
    assert h.access.operations(h.owner)[0]["error"] == "RECOVERY_REQUIRES_REVIEW"


def test_raw_upload_limit_and_nested_closed_forms(harness: Harness) -> None:
    h = harness
    paper = h.create()
    response = h.client.post(
        path(paper) + "/attachment",
        json={
            "expected_digest": digest(paper),
            "content_base64": base64.b64encode(b"x" * 4_000_001).decode(),
            "media_type": "text/plain",
            "declared_license": "Synthetic",
        },
    )
    assert response.status_code == 400
    for body in (
        {},
        {"metadata": META, "doi": "10.1234/example"},
        {"metadata": {**META, "credential": "private reflected value"}},
    ):
        response = h.client.post("/api/publications", json=body)
        assert response.status_code == 422 and "private reflected" not in response.text
    with pytest.raises(AccessError, match="page"):
        h.access.list(h.owner, limit=True)


def test_unknown_own_job_reference_does_not_bypass_canonical_verification(
    harness: Harness,
) -> None:
    h = harness
    paper = h.create()
    identity = "EXP-019947a8-7920-7000-8000-000000000001"
    job = h.access.state.enqueue(h.owner, {"synthetic": 1})
    with h.access.state.connection() as db:
        db.execute("UPDATE jobs SET experiment_id=? WHERE id=?", (identity, job.id))
    response = h.client.post(
        path(paper),
        json={
            "expected_digest": digest(paper),
            "reproduction": {
                "status": "LINKED_EXPERIMENTS",
                "experiment_ids": [identity],
            },
        },
    )
    assert response.status_code == 503
    assert h.access.operations(h.owner)[0]["status"] == "FAILED"
    assert h.client.get(path(paper)).json()["revision_digest"] == digest(paper)
