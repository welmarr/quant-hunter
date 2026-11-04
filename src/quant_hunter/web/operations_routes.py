"""Private read-only operational status with sanitized failure responses."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, Response

from quant_hunter.web.operations_access import (
    OperationsAccess,
    OperationsUnavailableError,
)
from quant_hunter.web.publication_routes import Authenticated
from quant_hunter.web.state import AccessError


def install_operations_routes(
    app: FastAPI, authenticated: Authenticated, access: OperationsAccess | None
) -> None:
    @app.get("/api/operations/status")
    def status(request: Request, response: Response) -> object:
        response.headers["Cache-Control"] = "no-store"
        try:
            user = authenticated(request).user
            if access is None:
                raise OperationsUnavailableError("OPERATIONS_UNAVAILABLE")
            return access.status(user)
        except AccessError:
            raise HTTPException(403, "Operations access denied") from None
        except OperationsUnavailableError as error:
            code = str(error)
            raise HTTPException(
                503,
                code
                if code in {"OPERATIONS_UNAVAILABLE", "DATABASE_UNAVAILABLE"}
                else "OPERATIONS_UNAVAILABLE",
            ) from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "OPERATIONS_UNAVAILABLE") from None
