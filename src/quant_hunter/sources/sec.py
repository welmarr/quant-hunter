"""Bounded SEC recent submissions and single-concept XBRL facts, latest snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from quant_hunter.sources._equity_transport import (
    EquityHTTPS,
    EquityRequest,
    EquityTransport,
    RawPage,
    calendar_date,
    json_object,
    mapping,
    number,
    receive,
    text,
    utc_timestamp,
)
from quant_hunter.sources.connectors import Health
from quant_hunter.sources.transport import SourceError


@dataclass(frozen=True)
class SECIdentity:
    organization: str = field(repr=False)
    contact_email: str = field(repr=False)

    def __post_init__(self) -> None:
        text(
            self.organization,
            r"[A-Za-z0-9][A-Za-z0-9 ._-]{1,79}",
            "SEC_ORGANIZATION_REQUIRED",
        )
        text(
            self.contact_email,
            r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,100}\.[A-Za-z]{2,24}",
            "SEC_CONTACT_REQUIRED",
        )

    def user_agent(self) -> str:
        return self.organization + " " + self.contact_email


@dataclass(frozen=True)
class SECQuery:
    cik: str
    start: date
    end: date
    resource: str = "submissions"
    taxonomy: str | None = None
    concept: str | None = None


@dataclass(frozen=True)
class SECFiling:
    cik: str
    accession: str
    form: str
    filing_date: date
    report_date: date | None
    acceptance_time: datetime | None
    primary_document: str
    is_amendment: bool
    ingestion_time: datetime
    publication_time: None = None
    revision_time: None = None
    point_in_time_eligible: bool = False
    quality_flags: tuple[str, ...] = (
        "DISSEMINATION_TIME_UNKNOWN",
        "LATEST_SUBMISSIONS_SNAPSHOT",
        "AMENDMENT_ORIGINAL_LINK_UNKNOWN",
    )


@dataclass(frozen=True)
class SECFact:
    cik: str
    accession: str
    taxonomy: str
    concept: str
    unit: str
    value: Decimal
    period_start: date | None
    period_end: date
    filing_date: date
    form: str
    fiscal_year: int | None
    fiscal_period: str | None
    frame: str | None
    is_amendment: bool
    ingestion_time: datetime
    acceptance_time: None = None
    publication_time: None = None
    revision_time: None = None
    point_in_time_eligible: bool = False
    quality_flags: tuple[str, ...] = (
        "FILING_DATE_IS_NOT_AVAILABILITY",
        "ALL_DISCLOSED_REVISIONS_RETAINED",
        "CURRENT_AGGREGATE_NOT_HISTORICAL_SNAPSHOT",
    )


type SECRecord = SECFiling | SECFact


@dataclass(frozen=True)
class SECBatch:
    catalogue_id: str
    query: SECQuery
    records: tuple[SECRecord, ...]
    raw_pages: tuple[RawPage, ...]
    evidence_mode: str
    coverage_complete: bool = False
    normalization_version: str = "v0-sec-1"
    limitations: tuple[str, ...] = (
        "Recent submissions only; older archive files are not downloaded",
        "Single-concept facts retain filing revisions, not a verified historical information set",
        "Acceptance, filing date and dissemination are distinct",
        "Source approval, licence review and immutable registration are caller responsibilities",
    )


class SECConnector:
    catalogue_id = "SRC-01"
    version = "v0-sec-1"
    documentation_url = (
        "https://www.sec.gov/search-filings/edgar-application-programming-interfaces"
    )

    def __init__(
        self,
        identity: SECIdentity | None = None,
        transport: EquityTransport | None = None,
    ) -> None:
        self._identity = identity
        self._transport = transport or EquityHTTPS()
        self.evidence_mode = (
            "RECORDED_FIXTURE" if transport is not None else "HISTORICAL_REAL"
        )
        self._health = Health("UNTESTED" if identity else "NOT_CONFIGURED")
        self.last_pages: tuple[RawPage, ...] = ()

    def health(self) -> Health:
        return self._health

    def list_capabilities(self) -> tuple[str, ...]:
        return (
            "RECENT_SUBMISSIONS",
            "SINGLE_CONCEPT_FACTS_ALL_UNITS",
            "ACCESSION_AND_AMENDMENT_PRESERVED",
            "NO_HISTORICAL_AVAILABILITY_CLAIM",
            "ONE_REQUEST_NO_RETRY",
        )

    def validate_config(self, query: SECQuery) -> None:
        if self._identity is None:
            raise SourceError("SEC_CONTACT_NOT_CONFIGURED")
        self._identity.__post_init__()
        text(query.cik, r"[0-9]{10}", "INVALID_CIK")
        if int(query.cik) == 0:
            raise SourceError("INVALID_CIK")
        if (
            type(query.start) is not date
            or type(query.end) is not date
            or not timedelta(0) <= query.end - query.start <= timedelta(days=3660)
        ):
            raise SourceError("INVALID_DATE_RANGE")
        if query.resource == "submissions":
            if query.taxonomy is not None or query.concept is not None:
                raise SourceError("UNSUPPORTED_SEC_QUERY")
        elif query.resource == "company_concept":
            if query.taxonomy not in ("us-gaap", "ifrs-full", "dei", "srt"):
                raise SourceError("UNSUPPORTED_TAXONOMY")
            text(query.concept, r"[A-Za-z][A-Za-z0-9]{0,119}", "INVALID_CONCEPT")
        else:
            raise SourceError("UNSUPPORTED_SEC_QUERY")

    def fetch_range(self, query: SECQuery) -> SECBatch:
        self.last_pages = ()
        try:
            self.validate_config(query)
            if self._identity is None:
                raise SourceError("SEC_CONTACT_NOT_CONFIGURED")
            target = (
                f"/submissions/CIK{query.cik}.json"
                if query.resource == "submissions"
                else f"/api/xbrl/companyconcept/CIK{query.cik}/{query.taxonomy}/{query.concept}.json"
            )
            page = receive(
                self._transport,
                EquityRequest("data.sec.gov", target, self._identity.user_agent()),
            )
            self.last_pages = (page,)
            records = self.normalize(page.raw, query, page.retrieved_at)
            self.validate_batch(records, query)
        except SourceError as error:
            self._health = Health("FAILED", datetime.now(UTC), error.code)
            raise
        self._health = Health("SUCCEEDED", page.retrieved_at)
        return SECBatch(
            self.catalogue_id, query, records, self.last_pages, self.evidence_mode
        )

    def test_connection(self, query: SECQuery) -> SECBatch:
        return self.fetch_range(query)

    def normalize(
        self, raw: bytes, query: SECQuery, retrieved_at: datetime
    ) -> tuple[SECRecord, ...]:
        self.validate_config(query)
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() != timedelta(0):
            raise SourceError("UTC_RETRIEVAL_REQUIRED")
        payload = json_object(raw)
        cik = payload.get("cik")
        if (
            isinstance(cik, bool)
            or not isinstance(cik, (int, str))
            or str(cik).zfill(10) != query.cik
        ):
            raise SourceError("CONTRADICTORY_CIK")
        if query.resource == "submissions":
            records = self._filings(payload, query, retrieved_at)
        else:
            records = self._facts(payload, query, retrieved_at)
        self.validate_batch(records, query)
        return records

    def _filings(
        self, payload: dict[str, object], query: SECQuery, retrieved: datetime
    ) -> tuple[SECRecord, ...]:
        recent = mapping(mapping(payload.get("filings")).get("recent"))
        keys = (
            "accessionNumber",
            "filingDate",
            "reportDate",
            "acceptanceDateTime",
            "form",
            "primaryDocument",
        )
        columns: dict[str, list[object]] = {}
        for key in keys:
            value = recent.get(key)
            if not isinstance(value, list):
                raise SourceError("INVALID_SUBMISSIONS_SCHEMA")
            columns[key] = value
        count = len(columns["accessionNumber"])
        if count > 2000 or any(len(value) != count for value in columns.values()):
            raise SourceError("INVALID_SUBMISSIONS_COLUMNS")
        result: list[SECRecord] = []
        all_accessions: set[str] = set()
        for index in range(count):
            accession = text(
                columns["accessionNumber"][index],
                r"[0-9]{10}-[0-9]{2}-[0-9]{6}",
                "INVALID_ACCESSION",
            )
            if accession in all_accessions:
                raise SourceError("DUPLICATE_ACCESSION")
            all_accessions.add(accession)
            filed = calendar_date(columns["filingDate"][index])
            report = columns["reportDate"][index]
            report_date = None if report == "" else calendar_date(report)
            accepted = columns["acceptanceDateTime"][index]
            acceptance = None if accepted in (None, "") else utc_timestamp(accepted)
            form = text(columns["form"][index], r"[A-Za-z0-9 /-]{1,32}", "INVALID_FORM")
            document = text(
                columns["primaryDocument"][index],
                r"[A-Za-z0-9_.-]{1,200}",
                "INVALID_DOCUMENT_NAME",
            )
            if query.start <= filed <= query.end:
                result.append(
                    SECFiling(
                        query.cik,
                        accession,
                        form,
                        filed,
                        report_date,
                        acceptance,
                        document,
                        form.endswith("/A"),
                        retrieved,
                    )
                )
        return tuple(result)

    def _facts(
        self, payload: dict[str, object], query: SECQuery, retrieved: datetime
    ) -> tuple[SECRecord, ...]:
        if (
            payload.get("taxonomy") != query.taxonomy
            or payload.get("tag") != query.concept
        ):
            raise SourceError("CONTRADICTORY_CONCEPT")
        units = mapping(payload.get("units"))
        if not units or len(units) > 100:
            raise SourceError("INVALID_UNITS")
        result: list[SECRecord] = []
        seen: set[tuple[object, ...]] = set()
        count = 0
        for unit, items in units.items():
            text(unit, r"[A-Za-z0-9][A-Za-z0-9_/*.-]{0,79}", "INVALID_UNIT")
            if not isinstance(items, list):
                raise SourceError("INVALID_FACTS_SCHEMA")
            for item in items:
                count += 1
                if count > 5000:
                    raise SourceError("FACTS_ROW_LIMIT")
                row = mapping(item)
                accession = text(
                    row.get("accn"), r"[0-9]{10}-[0-9]{2}-[0-9]{6}", "INVALID_ACCESSION"
                )
                end = calendar_date(row.get("end"))
                start = calendar_date(row["start"]) if "start" in row else None
                if start is not None and start > end:
                    raise SourceError("INVALID_FACT_PERIOD")
                filed = calendar_date(row.get("filed"))
                form = text(row.get("form"), r"[A-Za-z0-9 /-]{1,32}", "INVALID_FORM")
                value = number(row.get("val"))
                year = row.get("fy")
                if year is not None and (
                    type(year) is not int or not 1900 <= year <= 9999
                ):
                    raise SourceError("INVALID_FISCAL_YEAR")
                fiscal_year = year if isinstance(year, int) else None
                period = (
                    None
                    if row.get("fp") is None
                    else text(row["fp"], r"[A-Za-z0-9]{1,8}", "INVALID_FISCAL_PERIOD")
                )
                frame = (
                    None
                    if "frame" not in row
                    else text(row["frame"], r"[A-Za-z0-9]{1,24}", "INVALID_FRAME")
                )
                identity = (unit, accession, start, end, fiscal_year, period, frame)
                if identity in seen:
                    raise SourceError("DUPLICATE_OR_CONTRADICTORY_FACT")
                seen.add(identity)
                if query.start <= filed <= query.end:
                    result.append(
                        SECFact(
                            query.cik,
                            accession,
                            query.taxonomy or "",
                            query.concept or "",
                            unit,
                            value,
                            start,
                            end,
                            filed,
                            form,
                            fiscal_year,
                            period,
                            frame,
                            form.endswith("/A"),
                            retrieved,
                        )
                    )
        return tuple(result)

    def validate_batch(self, records: tuple[SECRecord, ...], query: SECQuery) -> None:
        if len(records) > 5000:
            raise SourceError("RECORD_LIMIT")
        for record in records:
            if (
                record.cik != query.cik
                or not query.start <= record.filing_date <= query.end
            ):
                raise SourceError("RECORD_QUERY_MISMATCH")
            if (
                record.point_in_time_eligible
                or record.publication_time is not None
                or record.revision_time is not None
            ):
                raise SourceError("UNSUPPORTED_AVAILABILITY_CLAIM")
