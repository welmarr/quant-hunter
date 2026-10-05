"""Typed localhost-only API for synthetic software demonstrations."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from quant_hunter.config import JsonRecord
from quant_hunter.credentials import VaultError
from quant_hunter.identity import IdentityError, RegistryIntegrityError
from quant_hunter.markets import MarketError, sessions
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.sources.transport import SourceError
from quant_hunter.web.connections import Connections
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.state import AccessError, AppState, Role, Session


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(Input):
    username: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{3,40}$")]
    password: Annotated[str, Field(min_length=12, max_length=128)]


class NewUser(Credentials):
    role: Role


class Backtest(Input):
    market: Literal["EQUITY", "FX_SPOT"] = "EQUITY"
    initial_cash: Annotated[str, Field(pattern=r"^[0-9]{1,8}(\.[0-9]{1,4})?$")] = (
        "10000"
    )
    quantity: Annotated[str, Field(pattern=r"^[0-9]{1,6}(\.[0-9]{1,4})?$")] = "10"
    lookback: Annotated[int, Field(strict=True, ge=1, le=20)] = 1
    commission: Annotated[str, Field(pattern=r"^[0-9]{1,3}(\.[0-9]{1,4})?$")] = "1"
    slippage_bps: Annotated[str, Field(pattern=r"^[0-9]{1,2}(\.[0-9]{1,4})?$")] = "0"
    annual_financing_rate: Annotated[str, Field(pattern=r"^0(\.[0-9]{1,6})?$")] = "0"


class StudyRequest(Input):
    study_id: Annotated[str, Field(pattern=r"^(CRP-(0[1-9]|10)|ENS-COV|META-OOF)$")]
    scenario: Literal["POSITIVE", "NULL", "SENSITIVITY"] = "POSITIVE"
    parameter: Annotated[
        str | None, Field(pattern=r"^-?[0-9]{1,8}(\.[0-9]{1,10})?$")
    ] = None


class ImportInstrument(Input):
    symbol: Annotated[str, Field(min_length=1, max_length=32)]
    asset_class: Literal["EQUITY", "FX_SPOT"]
    base_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    quote_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    quantity_step: Annotated[str, Field(pattern=r"^[0-9]{1,8}(\.[0-9]{1,12})?$")] = "1"


class ImportMetadata(Input):
    source_name: Annotated[str, Field(min_length=1, max_length=120)]
    declared_license: Annotated[str, Field(min_length=1, max_length=1000)]
    evidence_mode: Literal["SYNTHETIC", "HISTORICAL"]
    instrument: ImportInstrument
    declared_restrictions: Annotated[str, Field(max_length=1000)] = (
        "Unverified user declaration; no redistribution approved"
    )


class DatasetUpload(Input):
    file_format: Literal["CSV", "PARQUET"]
    content_base64: Annotated[str, Field(min_length=1, max_length=2_666_668)]
    metadata: ImportMetadata
    corrects_dataset_id: Annotated[str | None, Field(max_length=80)] = None
    correction_reason: Annotated[str | None, Field(max_length=500)] = None


class ConnectionInput(Input):
    values: dict[str, str | bool]


class SourceUpload(Input):
    content_base64: Annotated[str, Field(min_length=1, max_length=2_666_668)]
    series_metadata_base64: Annotated[
        str | None, Field(min_length=1, max_length=2_666_668)
    ] = None
    metadata: dict[str, str | bool | int | None]


class InstrumentInterval(Input):
    start: Annotated[str, Field(max_length=32)]
    end: Annotated[str | None, Field(max_length=32)] = None


class InstrumentSymbol(InstrumentInterval):
    symbol: Annotated[str, Field(pattern=r"^[A-Z0-9][A-Z0-9._/-]{0,31}$")]


class InstrumentMetadata(Input):
    asset_class: Literal["EQUITY", "ETF", "FX_SPOT"]
    venue: Literal["XNYS", "OTC_NY_17_CONVENTION"]
    base_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    quote_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    price_precision: Annotated[int, Field(strict=True, ge=0, le=12)]
    quantity_precision: Annotated[int, Field(strict=True, ge=0, le=12)]
    lot_size: Annotated[
        str, Field(pattern=r"^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,12})?$")
    ]
    tick_size: Annotated[
        str, Field(pattern=r"^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,12})?$")
    ]
    multiplier: Literal["1"] = "1"
    timezone: Literal["America/New_York"] = "America/New_York"
    calendar_id: Literal["XNYS", "FX_NY_17"]
    activity: Annotated[list[InstrumentInterval], Field(min_length=1, max_length=128)]
    symbols: Annotated[list[InstrumentSymbol], Field(min_length=1, max_length=128)]
    status: Literal["ACTIVE", "INACTIVE", "DELISTED"] = "ACTIVE"


class InstrumentInput(Input):
    instrument: InstrumentMetadata
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    evidence_mode: Literal["SYNTHETIC", "HISTORICAL_DECLARED"]
    source_reference: Annotated[str, Field(min_length=1, max_length=1000)]


class InstrumentUpdate(InstrumentInput):
    expected_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class LocalBoundary:
    """Bound request size and reject foreign-origin mutations before parsing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            host = headers.get(b"host", b"")
            origin = headers.get(b"origin")
            expected = scope["scheme"].encode() + b"://" + host
            if headers.get(b"x-qh-request") != b"1" or (origin and origin != expected):
                await JSONResponse(
                    {"detail": "Request origin is not permitted"}, status_code=403
                )(scope, receive, send)
                return
        limit = (
            3_000_000
            if scope["method"] == "POST"
            and (
                scope["path"] == "/api/datasets"
                or (
                    scope["path"].startswith("/api/sources/")
                    and scope["path"].endswith("/import")
                )
            )
            else 65536
        )
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limit:
                await JSONResponse(
                    {"detail": "Request exceeds permitted size"}, status_code=413
                )(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {
                "type": "http.request",
                "body": b"".join(chunks),
                "more_body": False,
            }

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                    ),
                ]
            await send(message)

        await self.app(scope, replay, secure_send)


def session_payload(
    session: Session | None, *, needs_owner: bool = False
) -> dict[str, object]:
    return {
        "needs_owner": needs_owner,
        "user": asdict(session.user) if session else None,
        "csrf": session.csrf if session else None,
    }


def create_app(
    runtime: Path,
    repository: Path,
    *,
    process_job: Callable[[], bool] | None = None,
    get_run: Callable[[str], object] | None = None,
    fixtures: list[dict[str, object]] | None = None,
    data: DataAccess | None = None,
    sources: list[dict[str, object]] | None = None,
    connections: Connections | None = None,
    instruments: InstrumentRegistry | None = None,
) -> FastAPI:
    """Create app without starting jobs or loading any external provider."""
    from quant_hunter.web.worker import Worker

    state = AppState(runtime / "application.sqlite3")
    worker = Worker(process_job) if process_job else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if worker:
            worker.start()
        try:
            yield
        finally:
            if worker:
                worker.stop()

    app = FastAPI(
        title="Quant Hunter local laboratory",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.store = state
    app.state.worker = worker
    app.add_middleware(LocalBoundary)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        try:
            session = state.session(request.cookies.get("qh_session", ""))
        except AccessError as exc:
            raise HTTPException(401, "Sign in to continue") from exc
        if mutation and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), session.csrf
        ):
            raise HTTPException(403, "Session verification failed; refresh and retry")
        if owner and session.user.role != "owner":
            raise HTTPException(403, "Owner role required")
        return session

    @app.exception_handler(AccessError)
    async def access_error(request: Request, exc: AccessError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic's default errors echo input, including passwords. Never return it.
        return JSONResponse(
            {"detail": "Invalid request. Check field formats and limits."},
            status_code=422,
        )

    @app.exception_handler(VaultError)
    @app.exception_handler(SourceError)
    async def private_configuration_error(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return JSONResponse(
            {
                "detail": "Private source operation failed. Check configuration, rights, key access and the retained source-operation status."
            },
            status_code=422,
        )

    @app.exception_handler(MarketError)
    @app.exception_handler(IdentityError)
    async def market_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            {
                "detail": "Market metadata or calendar request is invalid or unavailable. Check identities, intervals, precision, dates and explicit conventions."
            },
            status_code=422,
        )

    @app.exception_handler(RegistryIntegrityError)
    async def registry_error(
        request: Request, exc: RegistryIntegrityError
    ) -> JSONResponse:
        return JSONResponse(
            {
                "detail": "Governed record is unavailable or failed verification; retained history was not changed."
            },
            status_code=503,
        )

    @app.get("/api/session")
    def current_session(request: Request) -> dict[str, object]:
        try:
            current = state.session(request.cookies.get("qh_session", ""))
        except AccessError:
            current = None
        return session_payload(current, needs_owner=state.needs_owner())

    def sign_in(credentials: Credentials, response: Response) -> dict[str, object]:
        token, current = state.login(credentials.username, credentials.password)
        response.set_cookie(
            "qh_session", token, httponly=True, samesite="strict", max_age=28800
        )
        return session_payload(current)

    @app.post("/api/setup")
    def setup(credentials: Credentials, response: Response) -> dict[str, object]:
        state.create_user(
            credentials.username, credentials.password, "owner", bootstrap=True
        )
        return sign_in(credentials, response)

    @app.post("/api/login")
    def login(credentials: Credentials, response: Response) -> dict[str, object]:
        return sign_in(credentials, response)

    @app.post("/api/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        authenticated(request, mutation=True)
        state.logout(request.cookies.get("qh_session", ""))
        response.delete_cookie("qh_session")
        return {"ok": True}

    @app.get("/api/fixtures")
    def fixture_list(request: Request) -> list[dict[str, object]]:
        authenticated(request)
        return fixtures or []

    @app.get("/api/users")
    def user_list(request: Request) -> list[dict[str, object]]:
        authenticated(request, owner=True)
        return [asdict(user) for user in state.users()]

    @app.post("/api/users")
    def add_user(payload: NewUser, request: Request) -> dict[str, object]:
        authenticated(request, mutation=True, owner=True)
        return asdict(
            state.create_user(
                payload.username, payload.password, payload.role, bootstrap=False
            )
        )

    def private_connections(request: Request, *, mutation: bool = False) -> Connections:
        authenticated(request, mutation=mutation, owner=True)
        if connections is None:
            raise HTTPException(503, "Private source configuration is unavailable")
        return connections

    @app.get("/api/connections")
    def connection_status(request: Request) -> JsonRecord:
        return private_connections(request).status()

    @app.post("/api/connections/rotate")
    def rotate_connections(request: Request) -> JsonRecord:
        return private_connections(request, mutation=True).rotate()

    @app.post("/api/connections/{catalogue_id}")
    def configure_connection(
        catalogue_id: str, payload: ConnectionInput, request: Request
    ) -> JsonRecord:
        return private_connections(request, mutation=True).save(
            catalogue_id, cast(JsonRecord, payload.values)
        )

    @app.post("/api/connections/{catalogue_id}/revoke")
    def revoke_connection(catalogue_id: str, request: Request) -> JsonRecord:
        return private_connections(request, mutation=True).revoke(catalogue_id)

    def instrument_service(
        request: Request, *, mutation: bool = False
    ) -> InstrumentRegistry:
        authenticated(request, mutation=mutation, owner=mutation)
        if instruments is None:
            raise HTTPException(503, "Instrument registry is unavailable")
        return instruments

    @app.get("/api/instruments")
    def instrument_list(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=50)] = 25,
        offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    ) -> dict[str, object]:
        return {
            "instruments": instrument_service(request).list(limit=limit, offset=offset),
            "sharing": "Local reference metadata is visible to all authenticated users",
            "limit": limit,
            "offset": offset,
        }

    @app.post("/api/instruments", status_code=201)
    def create_instrument(payload: InstrumentInput, request: Request) -> JsonRecord:
        return instrument_service(request, mutation=True).create(
            cast(JsonRecord, payload.model_dump())
        )

    @app.post("/api/instruments/{instrument_id}")
    def update_instrument(
        instrument_id: str, payload: InstrumentUpdate, request: Request
    ) -> JsonRecord:
        from quant_hunter.identity import StaleWriterError

        try:
            return instrument_service(request, mutation=True).update(
                instrument_id,
                payload.expected_digest,
                cast(JsonRecord, payload.model_dump(exclude={"expected_digest"})),
            )
        except StaleWriterError as exc:
            raise HTTPException(
                409, "Instrument changed; reload the latest revision"
            ) from exc

    @app.get("/api/instruments/{instrument_id}")
    def get_instrument(instrument_id: str, request: Request) -> JsonRecord:
        return instrument_service(request).get(instrument_id)

    @app.get("/api/instruments/{instrument_id}/as-of")
    def instrument_as_of(
        instrument_id: str,
        knowledge_time: datetime,
        effective_time: datetime,
        request: Request,
    ) -> JsonRecord:
        return instrument_service(request).as_of(
            instrument_id, knowledge_time, effective_time
        )

    @app.get("/api/calendars/{calendar_id}")
    def calendar(
        calendar_id: str, start: date, end: date, request: Request
    ) -> JsonRecord:
        authenticated(request)
        schedule = sessions(calendar_id, start, end)
        return {
            "schedule": schedule.to_record(),
            "digest": schedule.digest,
            "availability": "Versioned rules; historical publication time not established",
        }

    @app.get("/api/jobs")
    def jobs(request: Request) -> list[dict[str, object]]:
        return [asdict(job) for job in state.jobs(authenticated(request).user)]

    @app.get("/api/studies")
    def studies(request: Request) -> dict[str, object]:
        from quant_hunter.web.studies import catalogue

        authenticated(request)
        return {
            "studies": catalogue(),
            "evidence_mode": "SYNTHETIC",
            "empirical_validation": "MISSING",
        }

    @app.post("/api/studies/jobs", status_code=202)
    def enqueue_study(payload: StudyRequest, request: Request) -> dict[str, object]:
        from quant_hunter.web.studies import request_config

        current = authenticated(request, mutation=True)
        if current.user.role not in ("owner", "researcher"):
            raise HTTPException(403, "Researcher role required")
        if worker is None or not worker.alive:
            raise HTTPException(503, "Research worker is unavailable")
        try:
            config = request_config(
                payload.study_id, payload.scenario, payload.parameter
            )
        except ValueError as error:
            raise HTTPException(
                422, "Study parameter is outside the declared bounds"
            ) from error
        return asdict(state.enqueue(current.user, config))

    @app.post("/api/jobs", status_code=202)
    def enqueue(payload: Backtest, request: Request) -> dict[str, object]:
        current = authenticated(request, mutation=True)
        if worker is None or not worker.alive:
            raise HTTPException(503, "Simulation worker is unavailable")
        return asdict(state.enqueue(current.user, payload.model_dump()))

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str, request: Request) -> dict[str, object]:
        job = state.job(authenticated(request).user, job_id)
        result = get_run(job.experiment_id) if get_run and job.experiment_id else None
        return {"job": asdict(job), "run": result}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request) -> dict[str, bool]:
        state.cancel(authenticated(request, mutation=True).user, job_id)
        return {"ok": True}

    @app.get("/api/project")
    def project(request: Request) -> dict[str, object]:
        authenticated(request)
        status = json.loads(
            (repository / "artifacts" / "status.json").read_text(encoding="utf-8")
        )
        return {
            "status": status,
            "mode": "SYNTHETIC",
            "live_trading": "DISABLED",
            "worker": "RUNNING" if worker and worker.alive else "STOPPED",
            "runtime": str(runtime),
            "limitations": [
                "Synthetic software demonstration; no empirical validation",
                "HOST_ENFORCED evidence remains blocked",
                "Paper brokers and PatternLab are not yet implemented",
                "Imported and public-source data are not admitted to synthetic backtests",
            ],
        }

    def data_services() -> DataAccess:
        if data is None:
            raise HTTPException(503, "Data services are unavailable")
        return data

    @app.get("/api/sources")
    def source_catalogue(request: Request) -> dict[str, object]:
        authenticated(request)
        return {"sources": sources or []}

    @app.get("/api/data-operations")
    def data_operations(request: Request) -> dict[str, object]:
        user = authenticated(request).user
        return {"operations": data_services().operations(user)}

    @app.post("/api/sources/{catalogue_id}/probe")
    def source_probe(catalogue_id: str, request: Request) -> JsonRecord:
        user = authenticated(request, mutation=True).user
        service = data_services()
        try:
            return service.probe(user, catalogue_id)
        except AccessError:
            raise
        except Exception as exc:
            raise HTTPException(
                422,
                "Source probe failed; inspect the operation status. No connection or data approval is claimed.",
            ) from exc

    @app.get("/api/datasets")
    def dataset_list(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=50)] = 25,
        offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    ) -> dict[str, object]:
        user = authenticated(request).user
        service = data_services()
        return {
            "datasets": service.datasets(user, limit=limit, offset=offset),
            "total": service.dataset_count(user),
            "limit": limit,
            "offset": offset,
        }

    @app.post("/api/sources/{catalogue_id}/import", status_code=201)
    def source_file_import(
        catalogue_id: str, payload: SourceUpload, request: Request
    ) -> JsonRecord:
        user = authenticated(request, mutation=True).user
        if user.role not in ("owner", "researcher"):
            raise HTTPException(403, "Researcher role required")
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
            metadata_bytes = (
                base64.b64decode(payload.series_metadata_base64, validate=True)
                if payload.series_metadata_base64 is not None
                else None
            )
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "File encoding is invalid") from exc
        if not 0 < len(content) + len(metadata_bytes or b"") <= 2_000_000:
            raise HTTPException(413, "Combined files must contain 1 to 2,000,000 bytes")
        try:
            return data_services().import_source(
                user,
                catalogue_id,
                content,
                cast(JsonRecord, payload.metadata),
                series_metadata=metadata_bytes,
            )
        except AccessError:
            raise
        except Exception as exc:
            raise HTTPException(
                422,
                "Source import rejected; inspect its recorded failure and the required source format. Availability and rights remain unverified.",
            ) from exc

    @app.get("/api/datasets/{dataset_id}")
    def dataset_detail(dataset_id: str, request: Request) -> JsonRecord:
        return data_services().dataset(authenticated(request).user, dataset_id)

    @app.post("/api/datasets", status_code=201)
    def dataset_import(payload: DatasetUpload, request: Request) -> JsonRecord:
        user = authenticated(request, mutation=True).user
        if user.role not in ("owner", "researcher"):
            raise HTTPException(403, "Researcher role required")
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "File encoding is invalid") from exc
        if not 0 < len(content) <= 2_000_000:
            raise HTTPException(413, "File must contain 1 to 2,000,000 bytes")
        service = data_services()
        try:
            return service.import_data(
                user,
                content,
                file_format=payload.file_format,
                metadata=cast(JsonRecord, payload.metadata.model_dump()),
                corrects_dataset_id=payload.corrects_dataset_id,
                correction_reason=payload.correction_reason,
            )
        except AccessError:
            raise
        except Exception as exc:
            raise HTTPException(
                422,
                "Import rejected. Check the required schema, finite values, declared currency, chronological UTC timestamps and availability at or after each close. The operation log retains the failure type.",
            ) from exc

    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static", check_dir=False),
        name="assets",
    )
    app.mount(
        "/",
        StaticFiles(
            directory=Path(__file__).parent / "static", html=True, check_dir=False
        ),
        name="frontend",
    )
    return app
