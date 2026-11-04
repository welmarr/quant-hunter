"""Private read-only projections, with no portfolio pooling or mutation routes."""

from collections.abc import Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request

from quant_hunter.web.paper_portfolio import PaperPortfolio, PortfolioError
from quant_hunter.web.paper_routes import Authenticated
from quant_hunter.web.state import AccessError, ResourceBusyError


def install_paper_portfolio_routes(
    app: FastAPI, authenticated: Authenticated, access: PaperPortfolio | None
) -> None:
    router = APIRouter(prefix="/api/paper/portfolio")

    def invoke(action: Callable[[PaperPortfolio], object]) -> object:
        if access is None:
            raise HTTPException(503, "Paper portfolio inspection is unavailable")
        try:
            return action(access)
        except ResourceBusyError:
            raise HTTPException(
                503,
                "Inspection resources busy; retry later",
                headers={"Retry-After": "3"},
            ) from None
        except AccessError:
            raise HTTPException(403, "Paper portfolio access unavailable") from None
        except PortfolioError:
            raise HTTPException(
                409, "Paper portfolio evidence cannot be verified"
            ) from None
        except Exception:
            raise HTTPException(503, "Paper portfolio inspection failed") from None

    @router.get("/sessions")
    def sessions(request: Request) -> object:
        user = authenticated(request).user
        return invoke(lambda service: service.list_sessions(user))

    @router.get("/sessions/{session_id}")
    def detail(request: Request, session_id: str) -> object:
        user = authenticated(request).user
        return invoke(lambda service: service.get(user, session_id))

    app.include_router(router)
