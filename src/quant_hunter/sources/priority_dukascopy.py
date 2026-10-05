"""Local daily BI5 decoder; AWS Requester Pays acquisition is disabled."""

from __future__ import annotations

import lzma
import math
import struct
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from quant_hunter.sources.connectors import Health
from quant_hunter.sources.macro_common import raw_page, require_utc
from quant_hunter.sources.priority_common import PriorityBatch, imported
from quant_hunter.sources.transport import SourceError

MAX_DECODED = 16 * 1024 * 1024
MAX_TICKS = 100000
SCALES = {
    "EURUSD": 100000,
    "GBPUSD": 100000,
    "AUDUSD": 100000,
    "NZDUSD": 100000,
    "USDCHF": 100000,
    "USDCAD": 100000,
    "USDJPY": 1000,
    "EURJPY": 1000,
    "GBPJPY": 1000,
}


@dataclass(frozen=True)
class DukascopyQuery:
    pair: str
    day: date
    point_scale: int
    timestamp_basis: str = "UTC_DAY_MILLISECONDS"


@dataclass(frozen=True)
class DukascopyTick:
    pair: str
    timestamp: datetime
    sequence: int
    ask: Decimal
    bid: Decimal
    ask_volume_millions: float
    bid_volume_millions: float
    ingestion_time: datetime
    price_nature: str = "BROKER_SPECIFIC"
    volume_scope: str = "DUKASCOPY_QUOTED_SIDE_VOLUME_NOT_GLOBAL_FX_VOLUME"
    instrument_type: str = "SPOT_FX_QUOTE_NOT_FORWARD"
    available_at: None = None
    point_in_time_eligible: bool = False


class DukascopyDailyImporter:
    transport_status = "BLOCKED_EXTERNAL"
    transport_reason = "Official current daily archive requires AWS Requester Pays credentials and spending approval"

    def __init__(self) -> None:
        self._health = Health("UNTESTED")

    def health(self) -> Health:
        return self._health

    def list_capabilities(self) -> tuple[str, ...]:
        return (
            "LOCAL_DAILY_BI5",
            "BOUND_LZMA_BEFORE_DECODE",
            "BROKER_BID_ASK",
            "NO_AWS_ACCESS",
        )

    def validate_config(self, query: DukascopyQuery) -> None:
        if (
            query.pair not in SCALES
            or type(query.point_scale) is not int
            or query.point_scale != SCALES[query.pair]
            or type(query.day) is not date
            or not date(1990, 1, 1) <= query.day <= date(2100, 1, 1)
            or query.timestamp_basis != "UTC_DAY_MILLISECONDS"
        ):
            raise SourceError("INVALID_DUKASCOPY_CONFIG")

    def import_bytes(
        self,
        raw: bytes,
        query: DukascopyQuery,
        retrieved: datetime,
        *,
        evidence_mode: str = "OWNER_SUPPLIED",
    ) -> PriorityBatch[DukascopyTick]:
        try:
            records = self.normalize(raw, query, retrieved)
            result = imported("SRC-09", records, raw, retrieved, evidence_mode)
        except SourceError as error:
            self._health = Health("FAILED", datetime.now(UTC), error.code)
            raise
        self._health = Health("SUCCEEDED", retrieved)
        return result

    def normalize(
        self, raw: bytes, query: DukascopyQuery, retrieved: datetime
    ) -> tuple[DukascopyTick, ...]:
        self.validate_config(query)
        raw_page(raw, retrieved)
        # The documented decoder accepts LZMA-alone; true raw streams have no
        # self-describing properties and are rejected rather than guessed.
        if len(raw) < 13 or raw[0] >= 225:
            raise SourceError("INVALID_LZMA_HEADER")
        dictionary = int.from_bytes(raw[1:5], "little")
        declared = int.from_bytes(raw[5:13], "little")
        if not 4096 <= dictionary <= 8 * 1024 * 1024:
            raise SourceError("LZMA_DICTIONARY_LIMIT")
        unknown = 2**64 - 1
        if declared != unknown and (declared > MAX_DECODED or declared % 20):
            raise SourceError("LZMA_OUTPUT_METADATA_LIMIT")
        try:
            decoder = lzma.LZMADecompressor(
                format=lzma.FORMAT_ALONE, memlimit=16 * 1024 * 1024
            )
            decoded = decoder.decompress(raw, max_length=MAX_DECODED + 1)
        except lzma.LZMAError:
            raise SourceError("INVALID_LZMA_STREAM") from None
        if len(decoded) > MAX_DECODED:
            raise SourceError("DECODED_SIZE_LIMIT")
        if not decoder.eof:
            raise SourceError("TRUNCATED_LZMA_STREAM")
        if (
            decoder.unused_data
            or not decoded
            or len(decoded) % 20
            or (declared != unknown and declared != len(decoded))
        ):
            raise SourceError("INVALID_BI5_LENGTH")
        if len(decoded) // 20 > MAX_TICKS:
            raise SourceError("TICK_LIMIT")
        start = datetime.combine(query.day, time(), UTC)
        records: list[DukascopyTick] = []
        previous = -1
        for sequence, (ms, ask, bid, ask_volume, bid_volume) in enumerate(
            struct.iter_unpack(">IIIff", decoded)
        ):
            if ms >= 86400000 or ms < previous:
                raise SourceError("INVALID_TICK_TIME_ORDER")
            previous = ms
            timestamp = start + timedelta(milliseconds=ms)
            if timestamp > retrieved:
                raise SourceError("FUTURE_TICK")
            if not 0 < bid <= ask or any(
                not math.isfinite(volume) or not 0 <= volume <= 1e9
                for volume in (ask_volume, bid_volume)
            ):
                raise SourceError("INVALID_BID_ASK_OR_VOLUME")
            records.append(
                DukascopyTick(
                    query.pair,
                    timestamp,
                    sequence,
                    Decimal(ask) / query.point_scale,
                    Decimal(bid) / query.point_scale,
                    ask_volume,
                    bid_volume,
                    retrieved,
                )
            )
        result = tuple(records)
        self.validate_batch(result, query)
        return result

    def validate_batch(
        self, records: tuple[DukascopyTick, ...], query: DukascopyQuery
    ) -> None:
        self.validate_config(query)
        if not 0 < len(records) <= MAX_TICKS:
            raise SourceError("TICK_LIMIT")
        previous: datetime | None = None
        for i, record in enumerate(records):
            require_utc(record.timestamp)
            require_utc(record.ingestion_time)
            if (
                record.pair != query.pair
                or record.timestamp.date() != query.day
                or record.sequence != i
                or (previous is not None and record.timestamp < previous)
                or record.available_at is not None
                or record.point_in_time_eligible
            ):
                raise SourceError("TICK_BATCH_MISMATCH")
            previous = record.timestamp
