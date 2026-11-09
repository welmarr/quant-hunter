"""Owner-activated fixed public collections; no credentials or custom URLs."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.config import parse_json_document
from quant_hunter.web.source_schedules import (
    ScheduleError,
    SourceSchedules,
    public_profile,
)
from quant_hunter.web.state import AccessError, Session


class Authenticated(Protocol):
    def __call__(
        self, request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session: ...


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Collection(_Closed):
    catalogue_id: Literal["SRC-04", "SRC-06", "SRC-08"]
    interval_seconds: Annotated[int, Field(ge=3600, le=604800)]
    maximum_runs: Annotated[int, Field(ge=1, le=30)]


class Control(_Closed):
    action: Literal["ACTIVATE", "PAUSE", "RESUME", "CANCEL"]
    expected_revision: Annotated[int, Field(ge=1, le=160)]


class _BoundedRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            chunks: list[bytes] = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    raise HTTPException(
                        413, "Source schedule request exceeds 4096 bytes"
                    )
                chunks.append(chunk)
            request._body = b"".join(chunks)
            try:
                if request._body:
                    parse_json_document(request._body)
                return await original(request)
            except ValueError, RequestValidationError:
                raise HTTPException(
                    400, "Invalid closed source schedule request"
                ) from None

        return handler


def install_source_schedule_routes(
    app: FastAPI, authenticated: Authenticated, schedules: SourceSchedules | None
) -> None:
    router = APIRouter(prefix="/api/source-schedules", route_class=_BoundedRoute)

    def invoke(operation: Callable[[SourceSchedules], object]) -> object:
        if schedules is None:
            raise HTTPException(503, "Source collection scheduler is unavailable")
        try:
            return operation(schedules)
        except AccessError:
            raise HTTPException(403, "Source collection access denied") from None
        except ScheduleError:
            raise HTTPException(
                409, "Source collection state or revision refused"
            ) from None
        except Exception:
            raise HTTPException(503, "Source collection operation failed") from None

    @router.get("/profiles")
    def profiles(request: Request) -> object:
        authenticated(request)
        return [public_profile(source) for source in ("SRC-04", "SRC-06", "SRC-08")]

    @router.get("")
    def listing(request: Request) -> object:
        user = authenticated(request).user
        return invoke(lambda service: service.list_schedules(user))

    @router.post("")
    def create(request: Request, payload: Collection) -> object:
        user = authenticated(request, mutation=True, owner=True).user
        return invoke(
            lambda service: service.create(
                user,
                payload.catalogue_id,
                interval_seconds=payload.interval_seconds,
                maximum_runs=payload.maximum_runs,
            )
        )

    @router.get("/{schedule_id}")
    def detail(request: Request, schedule_id: str) -> object:
        user = authenticated(request).user
        return invoke(lambda service: service.get(user, schedule_id))

    @router.get("/{schedule_id}/history")
    def history(request: Request, schedule_id: str) -> object:
        user = authenticated(request).user
        return invoke(lambda service: service.history(user, schedule_id))

    @router.post("/{schedule_id}/control")
    def control(request: Request, schedule_id: str, payload: Control) -> object:
        user = authenticated(request, mutation=True, owner=True).user
        return invoke(
            lambda service: service.control(
                user,
                schedule_id,
                payload.action,
                expected_revision=payload.expected_revision,
            )
        )

    app.include_router(router)
