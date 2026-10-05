"""Closed private mapped-data routes; no paths or implicit provider retrieval."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Coroutine
from datetime import date, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from quant_hunter.config import JsonRecord
from quant_hunter.data_quality import MappingSpec, QualityError
from quant_hunter.identity import StaleWriterError
from quant_hunter.web.publication_routes import Authenticated
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.state import AccessError, Session


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
DatasetID = Annotated[str, Field(pattern=r"^DATASET-[0-9a-f-]{36}$")]
FieldName = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Purpose = Literal["PATTERN_CAUSAL", "RESEARCH_CAUSAL", "EXPLORATORY_INSPECTION"]


class InstrumentMetadata(_Closed):
    symbol: Annotated[str, Field(min_length=1, max_length=32)]
    asset_class: Literal["EQUITY", "FX_SPOT"]
    base_currency: Currency
    quote_currency: Currency
    quantity_step: Annotated[str, Field(min_length=1, max_length=40)] = "1"


class Metadata(_Closed):
    source_name: Annotated[str, Field(min_length=1, max_length=120)]
    declared_license: Annotated[str, Field(min_length=1, max_length=1000)]
    evidence_mode: Literal["SYNTHETIC", "HISTORICAL"]
    instrument: InstrumentMetadata
    declared_restrictions: (
        Annotated[str, Field(min_length=1, max_length=1000)] | None
    ) = None


class Mapping(_Closed):
    columns: Annotated[dict[FieldName, FieldName], Field(min_length=6, max_length=11)]
    timezone: Literal["OFFSET_REQUIRED", "UTC", "America/New_York"] = "OFFSET_REQUIRED"
    price_scale: Literal["1", "0.01", "0.0001"] = "1"
    price_currency: Currency = "USD"
    volume_unit: Literal["UNITS", "LOTS"] = "UNITS"
    reject_policy: Literal["REJECT_DATASET", "EXCLUDE_WITH_REPORT"] = "REJECT_DATASET"
    revision_mode: Literal["REQUIRED_UNKNOWN", "KNOWN", "SYNTHETIC_NOT_APPLICABLE"] = (
        "REQUIRED_UNKNOWN"
    )


class Upload(_Closed):
    content_base64: Annotated[str, Field(min_length=4, max_length=2_666_668)]
    file_format: Literal["CSV", "PARQUET"]
    metadata: Metadata
    mapping: Mapping
    instrument_id: Annotated[str, Field(pattern=r"^INSTRUMENT-[0-9a-f-]{36}$")]
    instrument_revision_digest: Digest
    calendar_start: Day
    calendar_end: Day


class Receipt(_Closed):
    record_digest: Digest
    quality_report_digest: Digest


class Aggregate(Receipt):
    timeframe: Literal["1m", "5m", "1h", "5h"]
    partial_policy: Literal["DROP", "INCLUDE_CLOSED_SHORT_SESSION_TAIL"]
    as_of: Annotated[str, Field(min_length=20, max_length=35)]


class Parent(Receipt):
    dataset_id: DatasetID


class Compose(_Closed):
    parents: Annotated[list[Parent], Field(min_length=1, max_length=1024)]
    purpose: Purpose = "PATTERN_CAUSAL"


class Empty(_Closed):
    pass


class _PrivateRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(
                    422, "Invalid quality request fields or limits"
                ) from None

        return handler


def install_quality_routes(
    app: FastAPI, authenticated: Authenticated, quality: QualityAccess | None
) -> None:
    # The host's LocalBoundary must permit 3 MB only for the mapped upload route,
    # 1 MB only for composition, and keep its ordinary 64 KiB body bound elsewhere.
    router = APIRouter(route_class=_PrivateRoute)

    def invoke(
        request: Request,
        action: Callable[[QualityAccess, Session], object],
        *,
        mutation: bool = False,
        owner: bool = False,
    ) -> object:
        session = authenticated(request, mutation=mutation, owner=owner)
        if quality is None:
            raise HTTPException(503, "Quality data service is unavailable")
        try:
            return action(quality, session)
        except AccessError:
            raise HTTPException(
                403, "Dataset is unavailable or operation is not permitted"
            ) from None
        except StaleWriterError:
            raise HTTPException(
                409, "Dataset or instrument changed; refresh exact receipts"
            ) from None
        except QualityError as error:
            raise HTTPException(
                400, {"code": error.code, "audit_digest": error.audit_digest}
            ) from None
        except Exception:
            raise HTTPException(
                503, "Quality operation failed; retained evidence requires review"
            ) from None

    @router.get("/api/quality/datasets")
    def datasets(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=50)] = 25,
        offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    ) -> object:
        return invoke(
            request,
            lambda access, session: {
                "datasets": access.datasets(session.user, limit=limit, offset=offset)
            },
        )

    @router.get("/api/quality/operations")
    def operations(request: Request) -> object:
        return invoke(
            request,
            lambda access, session: {
                "operations": [
                    row
                    for row in access.data.operations(session.user)
                    if str(row["kind"]).startswith("QUALITY_")
                ]
            },
        )

    @router.post("/api/quality/datasets", status_code=201)
    def upload(request: Request, body: Upload) -> object:
        def action(access: QualityAccess, session: Session) -> JsonRecord:
            try:
                raw = base64.b64decode(body.content_base64, validate=True)
                start, end = (
                    date.fromisoformat(body.calendar_start),
                    date.fromisoformat(body.calendar_end),
                )
            except binascii.Error, ValueError:
                raise QualityError("INVALID_ENCODING_OR_CALENDAR_DATE") from None
            if not 0 < len(raw) <= 2_000_000:
                raise QualityError("UPLOAD_LIMIT")
            return access.import_mapped(
                session.user,
                raw,
                file_format=body.file_format,
                metadata=cast(JsonRecord, body.metadata.model_dump(exclude_none=True)),
                mapping=MappingSpec.from_record(
                    cast(JsonRecord, body.mapping.model_dump())
                ),
                instrument_id=body.instrument_id,
                instrument_revision_digest=body.instrument_revision_digest,
                calendar_start=start,
                calendar_end=end,
            )

        return invoke(request, action, mutation=True)

    @router.get("/api/quality/datasets/{dataset_id}")
    def dataset(request: Request, dataset_id: str) -> object:
        return invoke(
            request, lambda access, session: access.dataset(session.user, dataset_id)
        )

    @router.post("/api/quality/datasets/{dataset_id}/aggregate", status_code=201)
    def aggregate(request: Request, dataset_id: str, body: Aggregate) -> object:
        def action(access: QualityAccess, session: Session) -> JsonRecord:
            access.owns(session.user, dataset_id)
            try:
                as_of = datetime.fromisoformat(body.as_of)
                if as_of.tzinfo is None or as_of.utcoffset() is None:
                    raise ValueError
            except ValueError:
                raise QualityError("INVALID_AS_OF") from None
            return access.aggregate(
                session.user,
                dataset_id,
                record_digest=body.record_digest,
                quality_report_digest=body.quality_report_digest,
                timeframe=body.timeframe,
                partial_policy=body.partial_policy,
                as_of=as_of,
            )

        return invoke(request, action, mutation=True)

    @router.get("/api/quality/selections")
    def selections(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=50)] = 25,
        offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    ) -> object:
        return invoke(
            request,
            lambda access, session: {
                "selections": access.selections(
                    session.user, limit=limit, offset=offset
                )
            },
        )

    @router.post("/api/quality/selections", status_code=201)
    def compose(request: Request, body: Compose) -> object:
        return invoke(
            request,
            lambda access, session: access.compose(
                session.user,
                tuple(
                    (
                        parent.dataset_id,
                        parent.record_digest,
                        parent.quality_report_digest,
                    )
                    for parent in body.parents
                ),
                purpose=body.purpose,
            ),
            mutation=True,
        )

    @router.get("/api/quality/selections/{manifest_digest}")
    def selection(request: Request, manifest_digest: str) -> object:
        return invoke(
            request,
            lambda access, session: access.selection(session.user, manifest_digest),
        )

    @router.post("/api/quality/demo", status_code=201)
    def demo(request: Request, body: Empty) -> object:
        return invoke(
            request,
            lambda access, session: access.demo(session.user),
            mutation=True,
            owner=True,
        )

    app.include_router(router)
