"""Closed, authenticated publication HTTP routes with no implicit retrieval."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, Protocol, cast

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_hunter.config import JsonRecord
from quant_hunter.identity import StaleWriterError
from quant_hunter.publications import PublicationError
from quant_hunter.publications.catalog import canonical_references
from quant_hunter.web.publication_access import PublicationAccess
from quant_hunter.web.state import AccessError, Session


class Authenticated(Protocol):
    def __call__(
        self, request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session: ...


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Short = Annotated[str, Field(min_length=1, max_length=4000)]


class Metadata(_Closed):
    title: Annotated[str, Field(min_length=1, max_length=500)]
    authors: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=160)]],
        Field(min_length=1, max_length=64),
    ]
    year: Annotated[int, Field(ge=1500, le=2100)] | None
    doi: Annotated[str, Field(min_length=1, max_length=240)] | None
    url: Annotated[str, Field(min_length=1, max_length=1800)] | None
    version: Annotated[str, Field(min_length=1, max_length=240)]


class EquationLink(_Closed):
    section: Annotated[str, Field(min_length=1, max_length=1000)]
    function: Annotated[str, Field(min_length=1, max_length=1000)]
    assumptions: Annotated[str, Field(min_length=1, max_length=1000)]
    oracle: Annotated[str, Field(min_length=1, max_length=1000)]


class Dossier(_Closed):
    question: Short
    universe: Short
    data: Short
    signal_formula: Short
    horizon: Short
    estimation: Short
    portfolio: Short
    costs: Short
    protocol: Short
    metrics: Short
    reported_results: Short
    reproduced_results: Short
    limitations: Short
    deviations: Short
    variant: Short
    disposition_reason: Short
    disposition: Literal["CANDIDATE", "SELECTED", "REJECTED", "DEFERRED"]
    equation_links: Annotated[list[EquationLink], Field(max_length=64)]


class Reading(_Closed):
    status: Literal["UNREAD", "PARTIAL", "FULL"]
    reader: Annotated[str, Field(min_length=1, max_length=120)] | None
    note: Annotated[str, Field(min_length=1, max_length=2000)] | None
    text_digest: Digest | None
    pages: Annotated[list[Annotated[int, Field(ge=1, le=200)]], Field(max_length=50)]


class Reproduction(_Closed):
    status: Literal["NOT_ATTEMPTED", "SYNTHETIC_SOFTWARE_ONLY", "LINKED_EXPERIMENTS"]
    experiment_ids: Annotated[
        list[Annotated[str, Field(pattern=r"^EXP-[0-9a-f-]{36}$")]],
        Field(max_length=64),
    ]


class CreatePublication(_Closed):
    metadata: Metadata | None = None
    doi: Annotated[str, Field(min_length=1, max_length=240)] | None = None
    url: Annotated[str, Field(min_length=1, max_length=1800)] | None = None

    @model_validator(mode="after")
    def exactly_one_form(self) -> CreatePublication:
        if (self.metadata is not None) == (
            self.doi is not None or self.url is not None
        ):
            raise ValueError("Choose metadata or one reference")
        return self


class RevisionRequest(_Closed):
    expected_digest: Digest


class UpdatePublication(RevisionRequest):
    metadata: Metadata | None = None
    dossier: Dossier | None = None
    reading: Reading | None = None
    reproduction: Reproduction | None = None

    @model_validator(mode="after")
    def changed_fields(self) -> UpdatePublication:
        if all(
            value is None
            for value in (self.metadata, self.dossier, self.reading, self.reproduction)
        ):
            raise ValueError("Provide an update")
        return self


class Attachment(RevisionRequest):
    content_base64: Annotated[str, Field(min_length=4, max_length=5_333_336)]
    media_type: Literal["application/pdf", "text/plain"]
    declared_license: Annotated[str, Field(min_length=1, max_length=500)]


class Extraction(RevisionRequest):
    page_start: Annotated[int, Field(ge=0, le=199)] = 0
    page_count: Annotated[int, Field(ge=1, le=50)] = 50


class PrimaryFetch(RevisionRequest):
    url: Annotated[str, Field(min_length=1, max_length=1800)]
    declared_license: Annotated[str, Field(min_length=1, max_length=500)]


class _PrivateRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(
                    422, "Invalid publication request fields or limits"
                ) from None

        return handler


def install_publication_routes(
    app: FastAPI, authenticated: Authenticated, publications: PublicationAccess | None
) -> None:
    router = APIRouter(route_class=_PrivateRoute)

    def invoke(
        request: Request,
        action: Callable[[PublicationAccess, Session], object],
        *,
        mutation: bool = False,
    ) -> object:
        session = authenticated(request, mutation=mutation)
        if publications is None:
            raise HTTPException(503, "Publication library is unavailable")
        try:
            return action(publications, session)
        except AccessError:
            raise HTTPException(
                403, "Publication is unavailable or operation is not permitted"
            ) from None
        except StaleWriterError:
            raise HTTPException(
                409, "Publication changed; refresh its current revision"
            ) from None
        except PublicationError as error:
            raise HTTPException(
                400, {"code": error.code, "revision_digest": error.revision_digest}
            ) from None
        except Exception:
            raise HTTPException(
                503, "Publication operation failed; retained evidence requires review"
            ) from None

    @router.get("/api/publication-reference-catalog")
    def reference_catalog(request: Request) -> object:
        authenticated(request)
        return {"references": canonical_references()}

    @router.get("/api/publications")
    def publications_list(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=50)] = 25,
        offset: Annotated[int, Query(ge=0, le=500)] = 0,
    ) -> object:
        return invoke(
            request,
            lambda access, session: {
                "publications": access.list(session.user, limit=limit, offset=offset)
            },
        )

    @router.get("/api/publication-operations")
    def operations(request: Request) -> object:
        return invoke(
            request,
            lambda access, session: {"operations": access.operations(session.user)},
        )

    @router.post("/api/publications", status_code=201)
    def create(request: Request, body: CreatePublication) -> object:
        return invoke(
            request,
            lambda access, session: (
                access.create(
                    session.user, cast(JsonRecord, body.metadata.model_dump())
                )
                if body.metadata
                else access.create_reference(session.user, doi=body.doi, url=body.url)
            ),
            mutation=True,
        )

    @router.get("/api/publications/{paper_id}")
    def get(request: Request, paper_id: str) -> object:
        return invoke(
            request, lambda access, session: access.get(session.user, paper_id)
        )

    @router.get("/api/publications/{paper_id}/text")
    def text(request: Request, paper_id: str) -> object:
        return invoke(
            request, lambda access, session: access.text(session.user, paper_id)
        )

    @router.post("/api/publications/{paper_id}")
    def update(request: Request, paper_id: str, body: UpdatePublication) -> object:
        return invoke(
            request,
            lambda access, session: access.update(
                session.user,
                paper_id,
                expected_digest=body.expected_digest,
                **{
                    name: cast(JsonRecord, value.model_dump())
                    for name in ("metadata", "dossier", "reading", "reproduction")
                    if (value := getattr(body, name)) is not None
                },
            ),
            mutation=True,
        )

    @router.post("/api/publications/{paper_id}/attachment")
    def attachment(request: Request, paper_id: str, body: Attachment) -> object:
        def action(access: PublicationAccess, session: Session) -> JsonRecord:
            access.owns(session.user, paper_id)
            try:
                raw = base64.b64decode(body.content_base64, validate=True)
            except binascii.Error, ValueError:
                raise PublicationError("INVALID_BASE64") from None
            if not 0 < len(raw) <= 4_000_000:
                raise PublicationError("UPLOAD_LIMIT_OR_TYPE")
            return access.attach(
                session.user,
                paper_id,
                raw,
                expected_digest=body.expected_digest,
                media_type=body.media_type,
                declared_license=body.declared_license,
            )

        return invoke(request, action, mutation=True)

    @router.post("/api/publications/{paper_id}/extract")
    def extract(request: Request, paper_id: str, body: Extraction) -> object:
        return invoke(
            request,
            lambda access, session: access.extract(
                session.user,
                paper_id,
                expected_digest=body.expected_digest,
                page_start=body.page_start,
                page_count=body.page_count,
            ),
            mutation=True,
        )

    @router.post("/api/publications/{paper_id}/metadata/retrieve")
    def metadata(request: Request, paper_id: str, body: RevisionRequest) -> object:
        return invoke(
            request,
            lambda access, session: access.retrieve_metadata(
                session.user, paper_id, expected_digest=body.expected_digest
            ),
            mutation=True,
        )

    @router.post("/api/publications/{paper_id}/fetch")
    def fetch(request: Request, paper_id: str, body: PrimaryFetch) -> object:
        return invoke(
            request,
            lambda access, session: access.fetch_primary(
                session.user,
                paper_id,
                body.url,
                expected_digest=body.expected_digest,
                declared_license=body.declared_license,
            ),
            mutation=True,
        )

    app.include_router(router)
