"""Bounded local-paper routes. No scheduler, broker or scientific gate endpoints."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from contextlib import AbstractContextManager
from typing import Annotated, Any, Literal, Protocol, cast

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.config import JsonRecord, parse_json_document
from quant_hunter.web.paper_access import (
    PaperAccess,
    PaperConflictError,
    PaperWorkflowError,
    default_paper_config,
)
from quant_hunter.web.state import AccessError, ResourceBusyError, Session, User


class Authenticated(Protocol):
    def __call__(
        self, request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session: ...


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Number = Annotated[
    str,
    Field(
        min_length=1,
        max_length=15,
        pattern=r"^(?:0|[1-9][0-9]{0,6})(?:[.][0-9]{1,6})?$",
    ),
]


class PaperConfiguration(_Closed):
    market: Literal["EQUITY", "ETF", "FX_SPOT"]
    mode: Literal["LOCAL_PAPER", "REPLAY"]
    bars: Annotated[int, Field(ge=20, le=100)]
    lookback: Annotated[int, Field(ge=1, le=10)]
    initial_cash: Number
    quantity: Number
    max_fill_quantity: Number
    commission_per_fill: Number
    slippage_bps: Number
    max_order_notional: Number
    max_exposure: Number
    max_concentration: Number
    max_drawdown: Number
    max_loss: Number
    max_spread_bps: Number
    max_slippage_bps: Number
    max_orders_per_window: Annotated[int, Field(ge=1, le=100)]


class CreatePaper(_Closed):
    configuration: PaperConfiguration


class Revision(_Closed):
    expected_revision: Annotated[int, Field(ge=1, le=600)]


class PaperControl(Revision):
    action: Literal["ACTIVATE", "PAUSE", "RESUME", "CANCEL", "KILL", "RESET_KILL"]


class _PrivateRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 8192:
                    raise HTTPException(413, "Paper request exceeds 8192 bytes")
                chunks.append(chunk)
            request._body = b"".join(chunks)
            if request._body:
                try:
                    parse_json_document(request._body)
                except ValueError:
                    raise HTTPException(400, "Invalid closed paper JSON") from None
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(400, "Invalid closed paper request") from None

        return handler


def install_paper_routes(
    app: FastAPI,
    authenticated: Authenticated,
    access: PaperAccess | None,
    *,
    inspection: Callable[[User], AbstractContextManager[object]] | None = None,
) -> None:
    router = APIRouter(prefix="/api/paper", route_class=_PrivateRoute)

    def invoke(operation: Callable[[PaperAccess], object]) -> object:
        if access is None:
            raise HTTPException(503, "Local paper workflow is unavailable")
        try:
            return operation(access)
        except ResourceBusyError:
            raise HTTPException(
                503,
                "Inspection resources busy; retry later",
                headers={"Retry-After": "3"},
            ) from None
        except AccessError:
            raise HTTPException(403, "Paper access denied") from None
        except PaperConflictError:
            raise HTTPException(
                409, "Paper state or capacity conflict; refresh session"
            ) from None
        except PaperWorkflowError:
            raise HTTPException(400, "Paper request or evidence refused") from None
        except Exception:
            raise HTTPException(
                503, "Paper operation failed; inspect retained local evidence"
            ) from None

    def inspect(user: User, operation: Callable[[PaperAccess], object]) -> object:
        if inspection is None:
            raise HTTPException(503, "Paper read admission is unavailable")

        def reserved(service: PaperAccess) -> object:
            with inspection(user):
                return operation(service)

        return invoke(reserved)

    @router.get("/configuration")
    def configuration(request: Request) -> object:
        authenticated(request)
        return {
            "defaults": {
                "EQUITY": default_paper_config(),
                "ETF": default_paper_config("ETF"),
                "FX_SPOT": default_paper_config("FX_SPOT"),
            },
            "evidence_mode": "SYNTHETIC",
            "network_enabled": False,
            "maximum_bars": 100,
            "maximum_controls": 64,
            "supported_modes": ["LOCAL_PAPER", "REPLAY"],
        }

    @router.get("/sessions")
    def sessions(request: Request) -> object:
        session = authenticated(request)
        return inspect(
            session.user, lambda service: service.list_sessions(session.user)
        )

    @router.post("/sessions")
    def create(request: Request, payload: CreatePaper) -> object:
        session = authenticated(request, mutation=True)
        return invoke(
            lambda service: service.create(
                session.user, cast(JsonRecord, payload.configuration.model_dump())
            )
        )

    @router.get("/sessions/{job_id}")
    def detail(request: Request, job_id: str) -> object:
        session = authenticated(request)
        return inspect(session.user, lambda service: service.get(session.user, job_id))

    @router.post("/sessions/{job_id}/control")
    def control(request: Request, job_id: str, payload: PaperControl) -> object:
        session = authenticated(request, mutation=True)
        return invoke(
            lambda service: service.control(
                session.user,
                job_id,
                payload.action,
                expected_revision=payload.expected_revision,
            )
        )

    @router.post("/sessions/{job_id}/reconcile")
    def reconcile(request: Request, job_id: str, payload: Revision) -> object:
        session = authenticated(request, mutation=True)
        return invoke(
            lambda service: service.reconcile(
                session.user, job_id, expected_revision=payload.expected_revision
            )
        )

    app.include_router(router)
