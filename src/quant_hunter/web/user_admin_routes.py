"""Closed owner-only account maintenance routes with sanitized credential errors."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.config import parse_json_document
from quant_hunter.web.state import AccessError, Session
from quant_hunter.web.user_admin import UserAdministration


class Authenticated(Protocol):
    def __call__(
        self, request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session: ...


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: Annotated[int, Field(ge=0, lt=10000)]
    action: Literal["ROLE", "PASSWORD", "REVOKE_SESSIONS"]
    role: Literal["owner", "researcher", "reader"] | None = None
    password: Annotated[
        str | None, Field(min_length=12, max_length=128, repr=False)
    ] = None


class PrivateRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            chunks: list[bytes] = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    raise HTTPException(413, "Account request exceeds 4096 bytes")
                chunks.append(chunk)
            request._body = b"".join(chunks)
            if request._body:
                try:
                    parse_json_document(request._body)
                except ValueError:
                    raise HTTPException(400, "Invalid closed account JSON") from None
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(400, "Invalid closed account fields") from None

        return handler


def install_user_administration_routes(
    app: FastAPI, authenticated: Authenticated, access: UserAdministration
) -> None:
    router = APIRouter(prefix="/api/administration", route_class=PrivateRoute)

    @router.get("/users")
    def users(
        request: Request,
        after: Annotated[int, Query(ge=0, le=9223372036854775807)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> object:
        return access.accounts(
            authenticated(request, owner=True).user, after=after, limit=limit
        )

    @router.post("/users/{target_id}/change")
    def change(
        request: Request,
        target_id: Annotated[int, Field(ge=1, le=9223372036854775807)],
        payload: Change,
    ) -> object:
        actor = authenticated(request, mutation=True, owner=True).user
        try:
            return access.change(
                actor,
                target_id,
                expected_revision=payload.expected_revision,
                action=payload.action,
                role=payload.role,
                password=payload.password,
            )
        except AccessError as error:
            raise HTTPException(409, str(error)) from None

    @router.get("/history")
    def history(
        request: Request,
        after: Annotated[int, Query(ge=0, le=10000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ) -> object:
        return access.history(
            authenticated(request, owner=True).user, after=after, limit=limit
        )

    app.include_router(router)
