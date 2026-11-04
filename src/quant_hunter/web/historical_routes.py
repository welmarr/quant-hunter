"""Closed owned historical chart-inspection routes; no research search route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.data_quality import QualityError
from quant_hunter.identity import StaleWriterError
from quant_hunter.web.historical_access import HistoricalPreviewAccess
from quant_hunter.web.publication_routes import Authenticated
from quant_hunter.web.quality_routes import DatasetID, Digest, _PrivateRoute
from quant_hunter.web.state import AccessError, ResourceBusyError, Session


class Inspection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: DatasetID
    record_digest: Digest
    quality_report_digest: Digest
    start: Annotated[int, Field(ge=0, le=100_000)]
    stop: Annotated[int, Field(ge=1, le=100_000)]


def install_historical_routes(
    app: FastAPI, authenticated: Authenticated, access: HistoricalPreviewAccess | None
) -> None:
    router = APIRouter(route_class=_PrivateRoute)

    def invoke(
        request: Request,
        action: Callable[[HistoricalPreviewAccess, Session], object],
        *,
        mutation: bool = False,
    ) -> object:
        session = authenticated(request, mutation=mutation)
        if access is None:
            raise HTTPException(503, "Historical chart inspection is unavailable")
        try:
            return action(access, session)
        except ResourceBusyError:
            raise HTTPException(
                503,
                "Inspection resources busy; retry later",
                headers={"Retry-After": "3"},
            ) from None
        except AccessError:
            raise HTTPException(
                403, "Historical inspection access or capacity denied"
            ) from None
        except StaleWriterError:
            raise HTTPException(409, "Refresh exact quality receipts") from None
        except QualityError as error:
            code = error.code
            raise HTTPException(
                400,
                code
                if len(code) <= 100
                and all(c.isupper() or c.isdigit() or c == "_" for c in code)
                else "INSPECTION_FAILED",
            ) from None
        except Exception:
            raise HTTPException(503, "Historical inspection unavailable") from None

    @router.post("/api/quality/inspections", status_code=201)
    def inspect(request: Request, response: Response, body: Inspection) -> object:
        response.headers["Cache-Control"] = "no-store"
        return invoke(
            request,
            lambda service, session: service.inspect(session.user, **body.model_dump()),
            mutation=True,
        )

    @router.get("/api/quality/inspections")
    def listing(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=50)] = 25,
        offset: Annotated[int, Query(ge=0, le=9999)] = 0,
    ) -> object:
        response.headers["Cache-Control"] = "no-store"
        return invoke(
            request,
            lambda service, session: {
                "inspections": service.list(session.user, limit=limit, offset=offset)
            },
        )

    @router.get("/api/quality/inspections/{identity}")
    def get(
        request: Request,
        response: Response,
        identity: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")],
    ) -> object:
        response.headers["Cache-Control"] = "no-store"
        return invoke(
            request, lambda service, session: service.get(session.user, identity)
        )

    app.include_router(router)
