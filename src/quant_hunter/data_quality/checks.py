"""Replayable calendar, instrument and timing checks; no approval mutation."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.markets import CalendarSchedule, InstrumentRevision, MarketError
from quant_hunter.markets.common import on_grid

from .models import QualityError


def inspect_table(
    table: Any,
    revision: InstrumentRevision,
    schedule: CalendarSchedule,
    *,
    evidence_mode: str,
    dispositions: JsonRecord,
) -> JsonRecord:
    if schedule.calendar_id != revision.instrument.calendar_id:
        raise QualityError("CALENDAR_INSTRUMENT_MISMATCH")
    if table.num_rows > 100_000:
        raise QualityError("QUALITY_ROW_LIMIT")
    rows = table.to_pylist()
    failures: list[JsonValue] = []
    times: set[datetime] = set()
    missing_availability = unknown_revisions = 0
    for row in rows:
        opened, closed = row["open_at"], row["close_at"]
        times.add(opened)
        reason: str | None = None
        if not any(
            s.open_at <= opened and closed <= s.close_at for s in schedule.sessions
        ):
            reason = "OUTSIDE_CALENDAR"
        instrument = revision.instrument
        try:
            instrument.symbol_at(opened)
            if not any(
                x.start <= opened and (x.end is None or closed <= x.end)
                for x in instrument.activity
            ):
                reason = "OUTSIDE_INSTRUMENT_ACTIVITY"
            if not any(
                x.start <= opened and (x.end is None or closed <= x.end)
                for x in instrument.symbols
            ):
                reason = "CROSSES_SYMBOL_HISTORY"
            for name in ("open", "high", "low", "close", "open_bid", "open_ask"):
                if name in row:
                    on_grid(row[name], instrument.tick_size)
            if "volume" in row:
                on_grid(
                    row["volume"], Decimal(1).scaleb(-instrument.quantity_precision)
                )
        except MarketError:
            reason = "INSTRUMENT_OR_PRICE_GRID"
        if reason:
            failures.append({"source_row": row["source_row"], "reason": reason})
        missing_availability += row["available_at"] is None
        unknown_revisions += row["revision_time_status"] == "REQUIRED_UNKNOWN"
    gaps: list[JsonValue] = []
    if rows:
        first, last = rows[0]["open_at"], rows[-1]["close_at"]
        expected = 0
        for session in schedule.sessions:
            start, end = max(first, session.open_at), min(last, session.close_at)
            if start >= end:
                continue
            count = int((end - start).total_seconds() // 60)
            expected += count
            if expected > 100_000:
                raise QualityError("CALENDAR_MINUTE_LIMIT")
            gap_start: datetime | None = None
            for offset in range(count):
                at = start + timedelta(minutes=offset)
                if at not in times and gap_start is None:
                    gap_start = at
                if at in times and gap_start is not None:
                    gaps.append({"start": stamp(gap_start), "end": stamp(at)})
                    gap_start = None
            if gap_start is not None:
                gaps.append({"start": stamp(gap_start), "end": stamp(end)})
    reasons: list[str] = []
    if not rows or not dispositions["accepted"]:
        reasons.append("ROW_REJECTION_POLICY")
    if failures:
        reasons.append("INSTRUMENT_CALENDAR_OR_GRID_FAILURE")
    if gaps:
        reasons.append("MISSING_TRADING_MINUTES")
    if missing_availability:
        reasons.append("UNKNOWN_AVAILABILITY")
    if unknown_revisions:
        reasons.append("REQUIRED_UNKNOWN_REVISION_TIMING")
    blocking = bool(reasons)
    if evidence_mode == "HISTORICAL":
        reasons.extend(
            (
                "UPLOADER_TIMING_NOT_INDEPENDENTLY_VERIFIED",
                "INSTRUMENT_RULES_NOT_HISTORICAL_PUBLICATION_EVIDENCE",
            )
        )
    if dispositions["rejected_rows"]:
        reasons.append("EXPLICIT_ROW_EXCLUSIONS_RETAINED")
    admission = (
        "BLOCKED"
        if blocking
        else "SYNTHETIC_SOFTWARE_ONLY"
        if evidence_mode == "SYNTHETIC"
        else "HISTORICAL_EXPLORATORY"
    )
    return {
        "schema_version": "qh-quality-report-v1",
        "dispositions": dispositions,
        "failures": failures,
        "gaps": gaps,
        "row_count": len(rows),
        "unknown_availability_rows": missing_availability,
        "unknown_revision_rows": unknown_revisions,
        "admission": admission,
        "causal_eligible": admission == "SYNTHETIC_SOFTWARE_ONLY",
        "reasons": cast(list[JsonValue], reasons),
        "checks": [
            "OHLC",
            "FINITE_DECIMAL",
            "UNIQUE_ORDERED_MINUTES",
            "PRICE_UNIT_AND_TICK",
            "VOLUME_UNIT_AND_GRID",
            "DECLARED_AVAILABILITY",
            "REVISION_TIMING",
            "CALENDAR",
            "ACTIVITY_AND_SYMBOLS",
            "INTERNAL_COVERAGE_GAPS",
        ],
        "unverified": [
            "LICENSING",
            "CORPORATE_ACTION_COMPLETENESS",
            "SUSPENSIONS_OUTSIDE_DECLARED_METADATA",
            "SURVIVORSHIP",
            "PRICE_ACCURACY",
            "HISTORICAL_METADATA_PUBLICATION",
            "EMPIRICAL_VALIDITY",
            "HOST_ENFORCED",
        ],
        "limitations": [
            "No learned cleaning, imputation, interpolation or outlier deletion.",
            "Calendar completeness covers only the declared observed start/end interval.",
            "Synthetic eligibility is software evidence only; historical exploratory data cannot enter causal Pattern search.",
            "Source and licensing remain candidate/unverified; no scientific gate or promotion.",
        ],
    }


def stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def bounds(table: Any) -> JsonRecord:
    rows = table.to_pylist()
    if not rows:
        raise QualityError("EMPTY_DATASET")
    return {"start": stamp(rows[0]["open_at"]), "end": stamp(rows[-1]["close_at"])}
