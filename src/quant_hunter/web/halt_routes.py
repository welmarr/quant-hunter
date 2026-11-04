"""Explicit owner controls for the persistent local-paper halt barrier."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.web.paper_access import PaperConflictError
from quant_hunter.web.paper_halt import GlobalPaperHalt, HaltError
from quant_hunter.web.paper_routes import Authenticated, _PrivateRoute
from quant_hunter.web.state import AccessError, ResourceBusyError


class HaltRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: Annotated[int, Field(ge=0, le=65)]


def install_halt_routes(
    app: FastAPI, authenticated: Authenticated, halt: GlobalPaperHalt | None
) -> None:
    router = APIRouter(prefix="/api/paper/halt", route_class=_PrivateRoute)

    def invoke(action: Callable[[GlobalPaperHalt], object]) -> object:
        if halt is None:
            raise HTTPException(503, "Local paper halt is unavailable")
        try:
            return action(halt)
        except ResourceBusyError:
            raise HTTPException(
                503,
                "Protection inspection busy; retry later",
                headers={"Retry-After": "3"},
            ) from None
        except AccessError:
            raise HTTPException(403, "Local paper halt access denied") from None
        except HaltError, PaperConflictError:
            raise HTTPException(
                409, "Halt state or proof conflict; refresh retained status"
            ) from None
        except Exception:
            raise HTTPException(
                503, "Halt evidence unavailable; retain current protection"
            ) from None

    @router.get("")
    def status(request: Request) -> object:
        user = authenticated(request).user
        return invoke(lambda service: service.status(user))

    @router.post("")
    def stop(request: Request, body: HaltRevision) -> object:
        user = authenticated(request, mutation=True, owner=True).user
        return invoke(
            lambda service: service.halt(user, expected_revision=body.expected_revision)
        )

    @router.post("/clear")
    def clear(request: Request, body: HaltRevision) -> object:
        user = authenticated(request, mutation=True, owner=True).user
        return invoke(
            lambda service: service.clear(
                user, expected_revision=body.expected_revision
            )
        )

    app.include_router(router)
