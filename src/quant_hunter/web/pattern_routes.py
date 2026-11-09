"""Closed authenticated PatternLab routes. Workers own persistent heavy work."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Coroutine
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.data_quality import QualityError
from quant_hunter.identity import StaleWriterError
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.patterns.corpus import CorpusConfig
from quant_hunter.patterns.product import PatternJobConfig
from quant_hunter.web.pattern_access import PatternAccess, Scenario
from quant_hunter.web.publication_routes import Authenticated
from quant_hunter.web.state import AccessError, ResourceBusyError, Session


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Identity = Annotated[str, Field(pattern=r"^DATASET-[0-9a-f-]{36}$")]
PreparedID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Family = Annotated[str, Field(pattern=r"^PAT-(0[1-9]|1[0-5])$")]
Nanoseconds = Annotated[str, Field(pattern=r"^[0-9]{1,19}$")]


class CorpusOptions(_Closed):
    block_rows: Annotated[int, Field(ge=2, le=65536)] = 32768
    max_rows: Annotated[int, Field(ge=2, le=50000000)] = 10000000
    max_disk_bytes: Annotated[int, Field(ge=4096, le=536870912)] = 536870912
    max_shards: Annotated[int, Field(ge=1, le=2048)] = 2048


class Materialize(_Closed):
    selection_digest: Digest
    options: CorpusOptions = Field(default_factory=CorpusOptions)


class QueryConfig(_Closed):
    family: Family
    query_start: Annotated[int, Field(ge=0, le=50000000)]
    query_stop: Annotated[int, Field(ge=8, le=50000256)]
    train_start: Annotated[int, Field(ge=0, le=50000000)]
    train_stop: Annotated[int, Field(ge=8, le=50000000)]
    decision_ns: Nanoseconds
    train_cutoff_ns: Nanoseconds
    candidate_cutoff_ns: Nanoseconds
    purge_ns: Nanoseconds = "0"
    normalization: Literal[
        "RAW",
        "BASE100",
        "RETURNS",
        "LOG_RETURNS",
        "Z_WINDOW",
        "CAUSAL_VOL",
        "RELATIVE_OHLC",
    ] = "Z_WINDOW"
    mode: Literal["EXACT_SMALL", "APPROXIMATE"] = "APPROXIMATE"
    metric: Literal["EUCLIDEAN", "DTW"] = "EUCLIDEAN"
    horizon: Annotated[int, Field(ge=1, le=256)] = 4
    cost_bps: Annotated[float, Field(ge=0, le=10000)] = 7.0
    maximum_distance: Annotated[float, Field(ge=0, le=1000000)] = 1.0
    candidate_cap: Annotated[int, Field(ge=1, le=256)] = 256
    max_results: Annotated[int, Field(ge=1, le=40)] = 20
    paa_segments: Annotated[int, Field(ge=1, le=64)] = 8
    dtw_radius: Annotated[int, Field(ge=0, le=256)] = 4
    train_window_cap: Annotated[int, Field(ge=4, le=64)] = 32
    seed: Annotated[int, Field(ge=0, le=4294967295)] = 0
    method_parameters: Annotated[dict[str, int | float], Field(max_length=12)] = Field(
        default_factory=dict
    )
    max_checkpoint_bytes: Annotated[int, Field(ge=4096, le=268435456)] = 268435456

    def configuration(self) -> PatternJobConfig:
        values = self.model_dump(exclude={"method_parameters"})
        for name in (
            "decision_ns",
            "train_cutoff_ns",
            "candidate_cutoff_ns",
            "purge_ns",
        ):
            values[name] = int(values[name])
        values["method_parameters_json"] = json.dumps(
            self.method_parameters, allow_nan=False
        )
        return PatternJobConfig(**values)


class Prepare(_Closed):
    corpus_id: Identity
    secondary_corpus_id: Identity | None = None
    scenario: Scenario = "SELECTED"
    family: Family | None = None
    configuration: QueryConfig | None = None


class Enqueue(_Closed):
    prepared_id: PreparedID


class _PrivateRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(
                    422, "Invalid PatternLab fields or limits"
                ) from None

        return handler


def install_pattern_routes(
    app: FastAPI,
    authenticated: Authenticated,
    patterns: PatternAccess | None,
    *,
    worker_available: Callable[[], bool] = lambda: True,
) -> None:
    """Host retains local boundary, 64 KiB bodies, session and CSRF enforcement."""
    router = APIRouter(route_class=_PrivateRoute)

    def invoke(
        request: Request,
        action: Callable[[PatternAccess, Session], object],
        *,
        mutation: bool = False,
        queued: bool = False,
    ) -> object:
        session = authenticated(request, mutation=mutation)
        if patterns is None:
            raise HTTPException(503, "PatternLab is unavailable")
        if queued and not worker_available():
            raise HTTPException(503, "PatternLab worker is unavailable")
        try:
            return action(patterns, session)
        except ResourceBusyError:
            raise HTTPException(
                503,
                "Inspection resources busy; retry later",
                headers={"Retry-After": "3"},
            ) from None
        except AccessError:
            raise HTTPException(
                403, "PatternLab object unavailable or operation not permitted"
            ) from None
        except StaleWriterError:
            raise HTTPException(
                409, "Exact input receipt changed; refresh selection"
            ) from None
        except QualityError:
            raise HTTPException(
                400, "Quality selection is not admissible for this operation"
            ) from None
        except PatternError as error:
            code = str(error)
            raise HTTPException(
                400,
                code
                if re.fullmatch(r"[A-Z0-9_]{1,90}", code)
                else "PATTERN_REQUEST_INVALID",
            ) from None
        except Exception:
            raise HTTPException(
                503, "PatternLab operation failed; retained evidence requires review"
            ) from None

    @router.get("/api/patterns/catalogue")
    def catalogue(request: Request) -> object:
        return invoke(request, lambda access, session: access.catalogue())

    @router.get("/api/patterns/corpora")
    def corpora(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=25)] = 10,
        offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    ) -> object:
        return invoke(
            request,
            lambda access, session: {
                "corpora": access.corpus_list(session.user, limit=limit, offset=offset),
                "limit": limit,
                "offset": offset,
            },
        )

    @router.post("/api/patterns/corpora", status_code=202)
    def materialize(request: Request, body: Materialize) -> object:
        return invoke(
            request,
            lambda access, session: asdict(
                access.enqueue_corpus(
                    session.user,
                    body.selection_digest,
                    config=CorpusConfig(**body.options.model_dump()),
                )
            ),
            mutation=True,
            queued=True,
        )

    @router.get("/api/patterns/corpora/{identity}")
    def corpus(request: Request, identity: str) -> object:
        return invoke(
            request, lambda access, session: access.corpus(session.user, identity)
        )

    @router.get("/api/patterns/corpora/{identity}/preview")
    def preview(
        request: Request,
        identity: str,
        start: Annotated[int, Query(ge=0)],
        stop: Annotated[int, Query(ge=1)],
    ) -> object:
        return invoke(
            request,
            lambda access, session: access.preview(
                session.user, identity, start=start, stop=stop
            ),
        )

    @router.get("/api/patterns/prepared")
    def prepared_list(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=25)] = 10,
        offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    ) -> object:
        return invoke(
            request,
            lambda access, session: {
                "prepared": access.prepared_list(
                    session.user, limit=limit, offset=offset
                ),
                "limit": limit,
                "offset": offset,
            },
        )

    @router.get("/api/patterns/prepared/{identity}")
    def prepared(request: Request, identity: str) -> object:
        return invoke(
            request, lambda access, session: access.prepared(session.user, identity)
        )

    @router.post("/api/patterns/prepare", status_code=201)
    def prepare(request: Request, body: Prepare) -> object:
        return invoke(
            request,
            lambda access, session: access.prepare(
                session.user,
                body.corpus_id,
                config=body.configuration.configuration()
                if body.configuration
                else None,
                family=body.family,
                scenario=body.scenario,
                secondary_corpus_id=body.secondary_corpus_id,
            ),
            mutation=True,
        )

    @router.post("/api/patterns/jobs", status_code=202)
    def enqueue(request: Request, body: Enqueue) -> object:
        return invoke(
            request,
            lambda access, session: asdict(
                access.enqueue(session.user, body.prepared_id)
            ),
            mutation=True,
            queued=True,
        )

    @router.get("/api/patterns/jobs/{identity}")
    def job(request: Request, identity: str) -> object:
        return invoke(
            request, lambda access, session: access.job(session.user, identity)
        )

    app.include_router(router)
