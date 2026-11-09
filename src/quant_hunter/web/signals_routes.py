"""Private read-only retained-decision routes; no execution or prediction API."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request

from quant_hunter.web.paper_routes import Authenticated
from quant_hunter.web.signals_access import (
    SignalChangedError,
    SignalError,
    SignalsAccess,
)
from quant_hunter.web.state import AccessError, ResourceBusyError


def install_signals_routes(
    app: FastAPI, authenticated: Authenticated, access: SignalsAccess | None
) -> None:
    router = APIRouter(prefix="/api/signals")

    def invoke(request: Request, action: Callable[[SignalsAccess], object]) -> object:
        authenticated(request)
        if access is None:
            raise HTTPException(503, "Retained signal inspection is unavailable")
        try:
            return action(access)
        except ResourceBusyError:
            raise HTTPException(
                503,
                "Inspection resources busy; retry later",
                headers={"Retry-After": "3"},
            ) from None
        except AccessError:
            raise HTTPException(403, "Retained observation unavailable") from None
        except SignalChangedError:
            raise HTTPException(
                409, "Recorded source advanced; refresh the inspection"
            ) from None
        except SignalError:
            raise HTTPException(
                409, "Retained observation evidence cannot be verified"
            ) from None
        except Exception:
            raise HTTPException(503, "Retained observation inspection failed") from None

    @router.get("/paper/sessions")
    def sessions(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=25)] = 25,
        offset: Annotated[int, Query(ge=0, le=31)] = 0,
    ) -> object:
        user = authenticated(request).user
        return invoke(
            request, lambda service: service.sessions(user, limit=limit, offset=offset)
        )

    @router.get("/paper/{identity}")
    def paper(
        request: Request,
        identity: str,
        limit: Annotated[int, Query(ge=1, le=25)] = 25,
        offset: Annotated[int, Query(ge=0, le=99)] = 0,
    ) -> object:
        user = authenticated(request).user
        return invoke(
            request,
            lambda service: service.paper_signals(
                user, identity, limit=limit, offset=offset
            ),
        )

    @router.get("/research/jobs")
    def jobs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=25)] = 25,
        offset: Annotated[int, Query(ge=0, le=9999)] = 0,
    ) -> object:
        user = authenticated(request).user
        return invoke(
            request,
            lambda service: service.research_jobs(user, limit=limit, offset=offset),
        )

    @router.get("/research/jobs/{identity}")
    def research(request: Request, identity: str) -> object:
        user = authenticated(request).user
        return invoke(request, lambda service: service.research(user, identity))

    app.include_router(router)
