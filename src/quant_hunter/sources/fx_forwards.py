"""Explicit owner standard for dated outright/point FX forward quote files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Context, Decimal, localcontext

from quant_hunter.sources import archive_files as f
from quant_hunter.sources.macro_common import raw_page
from quant_hunter.sources.priority_common import PriorityBatch
from quant_hunter.sources.transport import SourceError

FORWARD_COLUMNS = (
    "quote_id",
    "quote_at",
    "base_currency",
    "quote_currency",
    "spot_date",
    "settlement_date",
    "tenor",
    "quote_kind",
    "spot_bid",
    "spot_ask",
    "forward_bid",
    "forward_ask",
    "point_scale",
    "declared_available_at",
)


@dataclass(frozen=True)
class ForwardQuery:
    base_currency: str
    quote_currency: str
    source_label: str
    start: date
    end: date
    export_vintage: date
    profile: str = "QH_FX_FORWARD_QUOTES_CSV_V1"


@dataclass(frozen=True)
class ForwardQuote:
    quote_id: str
    quote_at: datetime
    base_currency: str
    quote_currency: str
    source_label: str
    spot_date: date
    settlement_date: date
    tenor: str
    quote_kind: str
    spot_bid: Decimal
    spot_ask: Decimal
    quoted_forward_bid: Decimal
    quoted_forward_ask: Decimal
    point_scale: Decimal | None
    outright_bid: Decimal
    outright_ask: Decimal
    declared_available_at: datetime | None
    export_vintage: date
    ingestion_time: datetime
    instrument_kind: str = "FX_FORWARD"
    units: str = "QUOTE_CURRENCY_PER_ONE_BASE_CURRENCY"
    available_at: None = None
    point_in_time_eligible: bool = False
    executable_quote_verified: bool = False
    quality_flags: tuple[str, ...] = (
        "OWNER_DECLARED_QUOTE_UNVERIFIED",
        "TENOR_SETTLEMENT_CALENDAR_UNVERIFIED",
        "NO_FORWARD_EXECUTION_OR_SPOT_SUBSTITUTION",
        "HISTORICAL_AVAILABILITY_UNVERIFIED",
    )


class ForwardFileImporter:
    def import_bytes(
        self,
        raw: bytes,
        query: ForwardQuery,
        retrieved: datetime,
        *,
        evidence_mode: str = "OWNER_SUPPLIED",
    ) -> PriorityBatch[ForwardQuote]:
        f.evidence(evidence_mode)
        f.context(query.start, query.end, retrieved, query.export_vintage)
        for currency in (query.base_currency, query.quote_currency):
            f.token(currency, r"[A-Z]{3}", "FORWARD_CURRENCY")
            if currency not in {
                "USD",
                "EUR",
                "GBP",
                "JPY",
                "CHF",
                "AUD",
                "CAD",
                "NZD",
                "SEK",
                "NOK",
                "DKK",
                "SGD",
                "HKD",
                "CNH",
                "CNY",
                "MXN",
                "ZAR",
            }:
                raise SourceError("FORWARD_CURRENCY_UNSUPPORTED")
        f.metadata_text(query.source_label)
        if (
            query.base_currency == query.quote_currency
            or query.profile != "QH_FX_FORWARD_QUOTES_CSV_V1"
        ):
            raise SourceError("FORWARD_PAIR_OR_PROFILE")
        header, rows = f.csv_table(raw)
        if header != FORWARD_COLUMNS:
            raise SourceError("FORWARD_CLOSED_HEADER")
        records: list[ForwardQuote] = []
        previous: datetime | None = None
        ids: set[str] = set()
        for row in rows:
            (
                identity,
                encoded_time,
                base,
                quote,
                spot_text,
                settle_text,
                tenor,
                kind,
                *values,
            ) = row
            f.token(identity, r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", "FORWARD_QUOTE_ID")
            if (
                identity in ids
                or base != query.base_currency
                or quote != query.quote_currency
            ):
                raise SourceError("FORWARD_DUPLICATE_OR_PAIR")
            ids.add(identity)
            instant = f.timestamp(encoded_time)
            if (
                not query.start
                <= instant.date()
                <= min(query.end, query.export_vintage)
                or instant > retrieved
                or (previous and instant < previous)
            ):
                raise SourceError("FORWARD_QUOTE_TIME")
            previous = instant
            spot, settlement = f.day(spot_text), f.day(settle_text)
            if (
                not instant.date() <= spot < settlement
                or (settlement - spot).days > 3660
            ):
                raise SourceError("FORWARD_SETTLEMENT")
            f.token(tenor, r"(?:[1-9][0-9]{0,2}[DWMY]|BROKEN)", "FORWARD_TENOR")
            sb, sa, fb, fa = (f.number(value) for value in values[:4])
            if sb is None or sa is None or fb is None or fa is None:
                raise SourceError("FORWARD_NUMBER_REQUIRED")
            if not 0 < sb <= sa or fb > fa:
                raise SourceError("FORWARD_BID_ASK")
            scale: Decimal | None = None
            if kind == "OUTRIGHT":
                if values[4] != "":
                    raise SourceError("FORWARD_OUTRIGHT_SCALE_FORBIDDEN")
                outright_bid, outright_ask = fb, fa
            elif kind == "POINTS":
                scale = f.number(values[4])
                if scale not in {
                    Decimal("1"),
                    Decimal("0.1"),
                    Decimal("0.01"),
                    Decimal("0.001"),
                    Decimal("0.0001"),
                    Decimal("0.00001"),
                    Decimal("0.000001"),
                }:
                    raise SourceError("FORWARD_POINT_SCALE")
                # Bound decimal inputs make this precision exact for product+sum.
                with localcontext(Context(prec=80)):
                    outright_bid, outright_ask = sb + fb * scale, sa + fa * scale
            else:
                raise SourceError("FORWARD_QUOTE_KIND")
            if not 0 < outright_bid <= outright_ask <= Decimal("1e24"):
                raise SourceError("FORWARD_OUTRIGHT_BID_ASK")
            availability = f.timestamp(values[5]) if values[5] else None
            if availability is not None and not instant <= availability <= retrieved:
                raise SourceError("FORWARD_DECLARED_AVAILABILITY")
            records.append(
                ForwardQuote(
                    identity,
                    instant,
                    base,
                    quote,
                    query.source_label,
                    spot,
                    settlement,
                    tenor,
                    kind,
                    sb,
                    sa,
                    fb,
                    fa,
                    scale,
                    outright_bid,
                    outright_ask,
                    availability,
                    query.export_vintage,
                    retrieved,
                )
            )
        return PriorityBatch(
            "SRC-21",
            tuple(records),
            (raw_page(raw, retrieved),),
            evidence_mode,
            limitations=(
                "QH standard owner CSV, not an LSEG API/native-format compatibility claim",
                "Positive units are quote currency per one base; no implicit reciprocal conversion",
                "Points are added to matching spot bid/ask using an explicit decimal scale",
                "Explicit settlement governs; tenor calendar validation, rights and executability unverified",
                "Declared availability stays separate from verified availability; no PIT/source approval",
            ),
        )
