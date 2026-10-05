"""Typed localhost-only API for synthetic software demonstrations."""

from __future__ import annotations

import hmac
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > 65536:
                await JSONResponse(
                    {"detail": "Request exceeds 64 KiB"}, status_code=413
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

    @app.get("/api/jobs")
    def jobs(request: Request) -> list[dict[str, object]]:
        return [asdict(job) for job in state.jobs(authenticated(request).user)]

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
                "Paper brokers, source ingestion and PatternLab are not yet implemented",
            ],
        }

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
