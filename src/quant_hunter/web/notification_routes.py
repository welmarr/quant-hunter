"""Bounded inbox routes; every external send is a distinct owner/CSRF action."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.config import parse_json_document
from quant_hunter.credentials import VaultError
from quant_hunter.notifications.types import TOKEN_PATTERN, NotificationError
from quant_hunter.web.notification_access import NotificationAccess
from quant_hunter.web.notification_projection import NotificationProjection
from quant_hunter.web.state import AccessError, ResourceBusyError, Session


class Authenticated(Protocol):
    def __call__(
        self, request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session: ...


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Configuration(_Closed):
    bot_token: Annotated[
        str, Field(pattern="^" + TOKEN_PATTERN + "$", max_length=149, repr=False)
    ]
    allowed_chat_id: Annotated[
        str, Field(pattern=r"^-?[1-9][0-9]{0,15}$", max_length=17, repr=False)
    ]
    enabled: bool
    expected_revision: Annotated[int, Field(ge=0, le=999)]


class Revision(_Closed):
    expected_revision: Annotated[int, Field(ge=1, le=1000)]


class _PrivateRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            chunks: list[bytes] = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    raise HTTPException(413, "Notification request exceeds 4096 bytes")
                chunks.append(chunk)
            request._body = b"".join(chunks)
            if request._body:
                try:
                    parse_json_document(request._body)
                except ValueError:
                    raise HTTPException(
                        400, "Invalid closed notification JSON"
                    ) from None
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(
                    400, "Invalid closed notification request"
                ) from None

        return handler


def install_notification_routes(
    app: FastAPI,
    authenticated: Authenticated,
    access: NotificationAccess | None,
    *,
    projection: NotificationProjection | None = None,
    projection_error: Callable[[], str | None] = lambda: None,
) -> None:
    router = APIRouter(prefix="/api/notifications", route_class=_PrivateRoute)

    def invoke(operation: Callable[[NotificationAccess], object]) -> object:
        if access is None:
            raise HTTPException(503, "Notifications are unavailable")
        try:
            return operation(access)
        except ResourceBusyError:
            raise HTTPException(
                503,
                "Inspection resources busy; retry later",
                headers={"Retry-After": "3"},
            ) from None
        except AccessError:
            raise HTTPException(403, "Notification access denied") from None
        except NotificationError:
            raise HTTPException(
                409, "Notification state, policy or input refused"
            ) from None
        except VaultError:
            raise HTTPException(
                503, "Private notification credentials are unavailable"
            ) from None
        except Exception:
            raise HTTPException(503, "Notification operation failed") from None

    @router.get("/inbox")
    def inbox(
        request: Request,
        after: Annotated[int, Query(ge=0, le=10_000)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> object:
        session = authenticated(request)
        return invoke(
            lambda service: service.inbox(session.user, after=after, limit=limit)
        )

    @router.get("/projection")
    def projection_status(request: Request) -> object:
        session = authenticated(request)
        if projection is None:
            raise HTTPException(503, "Local notification projection is unavailable")
        return invoke(
            lambda _: {
                **projection.status(session.user),
                "scheduler_error": projection_error(),
            }
        )

    @router.post("/projection")
    def projection_refresh(request: Request, payload: _Closed | None = None) -> object:
        session = authenticated(request, mutation=True)
        if projection is None:
            raise HTTPException(503, "Local notification projection is unavailable")
        return invoke(lambda _: projection.sweep(session.user, limit=100))

    @router.post("/inbox/{notification_id}/read")
    def mark_read(
        request: Request, notification_id: str, payload: _Closed | None = None
    ) -> object:
        session = authenticated(request, mutation=True)
        return invoke(lambda service: service.mark_read(session.user, notification_id))

    @router.post("/local-test")
    def local_test(request: Request, payload: _Closed | None = None) -> object:
        session = authenticated(request, mutation=True)
        return invoke(lambda service: service.local_test(session.user))

    @router.get("/configuration")
    def configuration(request: Request) -> object:
        session = authenticated(request, owner=True)
        return invoke(lambda service: service.configuration(session.user))

    @router.get("/profile-schema")
    def profile_schema(request: Request) -> object:
        session = authenticated(request, owner=True)
        return invoke(lambda service: service.profile_schema(session.user))

    @router.post("/configuration")
    def configure(request: Request, payload: Configuration) -> object:
        session = authenticated(request, mutation=True, owner=True)
        return invoke(
            lambda service: service.configure(
                session.user,
                bot_token=payload.bot_token,
                allowed_chat_id=payload.allowed_chat_id,
                enabled=payload.enabled,
                expected_revision=payload.expected_revision,
            )
        )

    @router.post("/configuration/disable")
    def disable(request: Request, payload: Revision) -> object:
        session = authenticated(request, mutation=True, owner=True)
        return invoke(
            lambda service: service.disable(
                session.user, expected_revision=payload.expected_revision
            )
        )

    @router.post("/inbox/{notification_id}/send")
    def send(request: Request, notification_id: str, payload: Revision) -> object:
        session = authenticated(request, mutation=True, owner=True)
        return invoke(
            lambda service: service.send(
                session.user,
                notification_id,
                expected_revision=payload.expected_revision,
            )
        )

    app.include_router(router)
