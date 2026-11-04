"""Owner-only paper profile, account-read and offline protocol routes."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.config import parse_json_document
from quant_hunter.credentials import VaultError
from quant_hunter.paper_brokers.common import BrokerError
from quant_hunter.web.broker_access import BrokerAccess
from quant_hunter.web.state import AccessError, ResourceBusyError, Session


class Authenticated(Protocol):
    def __call__(
        self, request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session: ...


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Profile(_Closed):
    account_id: Annotated[str, Field(min_length=1, max_length=64, repr=False)]
    key: Annotated[str, Field(min_length=8, max_length=256, repr=False)]
    secret: Annotated[str | None, Field(max_length=256, repr=False)] = None
    credential_source: Literal["ALPACA_PAPER", "OANDA_PRACTICE"]
    paper_only_confirmed: bool
    expected_revision: Annotated[int, Field(ge=0, le=62)]


class Revision(_Closed):
    expected_revision: Annotated[int, Field(ge=1, le=64)]


class DryRun(_Closed):
    paper_id: Annotated[str, Field(pattern=r"^PAPER-[a-f0-9]{32}$", max_length=38)]
    expected_revision: Annotated[int, Field(ge=1, le=600)]


class _PrivateRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            chunks: list[bytes] = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    raise HTTPException(413, "Paper broker request exceeds 4096 bytes")
                chunks.append(chunk)
            request._body = b"".join(chunks)
            if request._body:
                try:
                    parse_json_document(request._body)
                except ValueError:
                    raise HTTPException(
                        400, "Invalid closed paper broker JSON"
                    ) from None
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(
                    400, "Invalid closed paper broker request"
                ) from None

        return handler


def install_broker_routes(
    app: FastAPI, authenticated: Authenticated, access: BrokerAccess | None
) -> None:
    router = APIRouter(prefix="/api/paper-brokers", route_class=_PrivateRoute)

    def invoke(operation: Callable[[BrokerAccess], object]) -> object:
        if access is None:
            raise HTTPException(503, "Paper broker operations unavailable")
        try:
            return operation(access)
        except ResourceBusyError:
            raise HTTPException(
                503,
                "Inspection resources busy; retry later",
                headers={"Retry-After": "3"},
            ) from None
        except AccessError:
            raise HTTPException(403, "Paper broker access denied") from None
        except BrokerError:
            raise HTTPException(409, "Paper broker state or input refused") from None
        except VaultError:
            raise HTTPException(503, "Private paper credentials unavailable") from None
        except Exception:
            raise HTTPException(503, "Paper broker operation failed") from None

    @router.get("/configuration")
    def status(request: Request) -> object:
        session = authenticated(request, owner=True)
        return invoke(lambda service: service.status(session.user))

    @router.get("/profile-schema")
    def schema(request: Request) -> object:
        authenticated(request, owner=True)
        return Profile.model_json_schema()

    @router.get("/operations")
    def operations(request: Request) -> object:
        session = authenticated(request, owner=True)
        return invoke(lambda service: service.operations(session.user))

    @router.get("/operations/{operation_id}")
    def detail(request: Request, operation_id: str) -> object:
        session = authenticated(request, owner=True)
        return invoke(lambda service: service.get(session.user, operation_id))

    @router.post("/operations/{operation_id}/verify")
    def evidence(
        request: Request, operation_id: str, payload: _Closed | None = None
    ) -> object:
        session = authenticated(request, mutation=True, owner=True)
        return invoke(lambda service: service.evidence(session.user, operation_id))

    @router.post("/{provider}/configuration")
    def configure(request: Request, provider: str, payload: Profile) -> object:
        session = authenticated(request, mutation=True, owner=True)
        return invoke(
            lambda service: service.configure(
                session.user, provider, **payload.model_dump()
            )
        )

    @router.post("/{provider}/revoke")
    def revoke(request: Request, provider: str, payload: Revision) -> object:
        session = authenticated(request, mutation=True, owner=True)
        return invoke(
            lambda service: service.revoke(
                session.user, provider, expected_revision=payload.expected_revision
            )
        )

    @router.post("/{provider}/test")
    def test(request: Request, provider: str, payload: Revision) -> object:
        session = authenticated(request, mutation=True, owner=True)
        return invoke(
            lambda service: service.test_connection(
                session.user, provider, expected_revision=payload.expected_revision
            )
        )

    @router.post("/{provider}/dry-run")
    def dry_run(request: Request, provider: str, payload: DryRun) -> object:
        session = authenticated(request, mutation=True, owner=True)
        return invoke(
            lambda service: service.dry_run(
                session.user,
                provider,
                payload.paper_id,
                expected_revision=payload.expected_revision,
            )
        )

    app.include_router(router)
