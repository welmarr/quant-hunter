"""Private chronological job selection, without client-supplied numerical rows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.data_quality import QualityError
from quant_hunter.identity import StaleWriterError
from quant_hunter.research_validation import ResearchValidationError
from quant_hunter.web.publication_routes import Authenticated
from quant_hunter.web.quality_routes import Digest, Empty, _PrivateRoute
from quant_hunter.web.state import AccessError, ResourceBusyError, Session
from quant_hunter.web.validation_access import ValidationAccess
from quant_hunter.web.validation_jobs import ValidationControls


class Controls(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evaluation_as_of: Annotated[str, Field(min_length=20, max_length=32)]
    model: Literal["TRAIN_MEAN", "OLS_LAG_RETURNS"] = "TRAIN_MEAN"
    lookback: Annotated[int, Field(ge=1, le=16)] = 4
    horizon: Annotated[int, Field(ge=1, le=120)] = 1
    training_rows: Annotated[int, Field(ge=4, le=9998)] = 120
    folds: Annotated[int, Field(ge=1, le=5)] = 2
    purge_bars: Annotated[int, Field(ge=0, le=120)] = 2
    embargo_bars: Annotated[int, Field(ge=0, le=120)] = 1
    minimum_train: Annotated[int, Field(ge=2, le=10000)] = 20
    minimum_validation: Annotated[int, Field(ge=1, le=10000)] = 10
    commission_bps: Annotated[str, Field(min_length=1, max_length=40)] = "0"
    slippage_bps: Annotated[str, Field(min_length=1, max_length=40)] = "0"
    block_length: Annotated[int, Field(ge=1, le=10000)] = 2
    repetitions: Annotated[int, Field(ge=100, le=1000)] = 200
    seed: Annotated[int, Field(ge=0, le=2**32 - 1)] = 0
    confidence: Literal["0.80", "0.90", "0.95", "0.99"] = "0.95"
    minimum_observations: Annotated[int, Field(ge=4, le=10000)] = 20


class Submit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: Annotated[str, Field(pattern=r"^DATASET-[0-9a-f-]{36}$")]
    record_digest: Digest
    quality_report_digest: Digest
    controls: Controls


def install_validation_routes(
    app: FastAPI,
    authenticated: Authenticated,
    validation: ValidationAccess | None,
    *,
    worker_available: Callable[[], bool],
) -> None:
    router = APIRouter(route_class=_PrivateRoute)

    def invoke(
        request: Request,
        action: Callable[[ValidationAccess, Session], object],
        *,
        mutation: bool = False,
    ) -> object:
        session = authenticated(request, mutation=mutation)
        if validation is None:
            raise HTTPException(503, "Chronological validation is unavailable")
        try:
            return action(validation, session)
        except ResourceBusyError:
            raise HTTPException(
                503,
                "Inspection resources busy; retry later",
                headers={"Retry-After": "3"},
            ) from None
        except AccessError:
            raise HTTPException(
                403, "Validation job is unavailable or operation is not permitted"
            ) from None
        except StaleWriterError:
            raise HTTPException(
                409, "Dataset changed; refresh exact receipts"
            ) from None
        except QualityError as error:
            raise HTTPException(
                400, {"code": error.code, "audit_digest": error.audit_digest}
            ) from None
        except ResearchValidationError as error:
            code = str(error)
            raise HTTPException(
                400,
                code
                if len(code) <= 100
                and all(c.isupper() or c.isdigit() or c == "_" for c in code)
                else "INVALID_VALIDATION_DEFINITION",
            ) from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                503, "Validation evidence is unavailable or requires review"
            ) from None

    @router.get("/api/validations/jobs")
    def jobs(request: Request) -> object:
        return invoke(
            request, lambda access, session: {"jobs": access.list(session.user)}
        )

    @router.post("/api/validations/jobs", status_code=202)
    def submit(request: Request, body: Submit) -> object:
        def action(access: ValidationAccess, session: Session) -> object:
            if not worker_available():
                raise HTTPException(503, "Research worker is unavailable")
            return asdict(
                access.submit(
                    session.user,
                    body.dataset_id,
                    record_digest=body.record_digest,
                    quality_report_digest=body.quality_report_digest,
                    controls=ValidationControls(**body.controls.model_dump()),
                )
            )

        return invoke(request, action, mutation=True)

    @router.get("/api/validations/jobs/{job_id}")
    def get(request: Request, job_id: str) -> object:
        return invoke(request, lambda access, session: access.get(session.user, job_id))

    @router.get("/api/validations/jobs/{job_id}/report")
    def report(request: Request, job_id: str) -> object:
        return invoke(
            request,
            lambda access, session: access.get(
                session.user, job_id, include_report=True
            ),
        )

    @router.post("/api/validations/jobs/{job_id}/cancel")
    def cancel(request: Request, job_id: str, body: Empty) -> object:
        def action(access: ValidationAccess, session: Session) -> object:
            access.cancel(session.user, job_id)
            return {"status": "CANCELLED"}

        return invoke(request, action, mutation=True)

    app.include_router(router)
