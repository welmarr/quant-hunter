"""Pinned XNYS rules and an explicitly named, non-universal OTC FX convention."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from importlib.metadata import version
from importlib.resources import files
from typing import cast
from zoneinfo import ZoneInfo

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.markets.common import MarketError, utc
from quant_hunter.provenance.hashing import sha256_canonical_json

CALENDAR_VERSION = "4.13.2"
TZDATA_VERSION = "2026.5"
MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(2035, 12, 31)


def _new_york() -> ZoneInfo:
    if version("tzdata") != TZDATA_VERSION:
        raise MarketError("Calendar timezone package differs from its pinned version")
    resource = files("tzdata.zoneinfo").joinpath("America", "New_York")
    with resource.open("rb") as handle:
        return ZoneInfo.from_file(handle, key="America/New_York")


@dataclass(frozen=True, slots=True)
class Session:
    """A continuous [open, close) session; no implicit breaks or overnight joining."""

    label: date
    open_at: datetime
    close_at: datetime

    def __post_init__(self) -> None:
        if type(self.label) is not date:
            raise MarketError("Session label must be a date")
        utc(self.open_at)
        utc(self.close_at)
        if not timedelta(0) < self.close_at - self.open_at <= timedelta(days=1):
            raise MarketError(
                "Session duration must be positive and no longer than 24h"
            )
        if any(
            item.second or item.microsecond for item in (self.open_at, self.close_at)
        ):
            raise MarketError("Session boundaries require whole minutes")


@dataclass(frozen=True, slots=True)
class CalendarSchedule:
    """Versioned rules snapshot; the calendar is not historical publication evidence."""

    calendar_id: str
    start: date
    end: date
    sessions: tuple[Session, ...]
    package: str
    package_version: str
    timezone_version: str
    limitations: tuple[str, ...]
    anchor: str = "SESSION_OPEN"

    def __post_init__(self) -> None:
        _dates(self.start, self.end)
        if self.calendar_id not in {"XNYS", "FX_NY_17"}:
            raise MarketError("Calendar has no implemented market profile")
        if not isinstance(self.sessions, tuple) or len(self.sessions) > 366:
            raise MarketError("Sessions require a bounded immutable tuple")
        if self.anchor != "SESSION_OPEN":
            raise MarketError("Only explicit session-open anchoring is implemented")
        previous: Session | None = None
        for session in self.sessions:
            if not self.start <= session.label <= self.end:
                raise MarketError("Session lies outside the declared date range")
            if previous and (
                session.label <= previous.label or session.open_at < previous.close_at
            ):
                raise MarketError("Session labels/times must be ordered and disjoint")
            previous = session

    def to_record(self) -> JsonRecord:
        return {
            "calendar_id": self.calendar_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "anchor": self.anchor,
            "timezone": "America/New_York",
            "timezone_package": f"tzdata=={self.timezone_version}",
            "package": self.package,
            "package_version": self.package_version,
            "sessions": cast(
                list[JsonValue],
                [
                    {
                        "label": row.label.isoformat(),
                        "open_at": row.open_at.isoformat(),
                        "close_at": row.close_at.isoformat(),
                    }
                    for row in self.sessions
                ],
            ),
            "limitations": list(self.limitations),
        }

    @property
    def digest(self) -> str:
        return sha256_canonical_json(self.to_record())


def _dates(start: date, end: date) -> None:
    if type(start) is not date or type(end) is not date:
        raise MarketError("Calendar boundaries require explicit dates")
    if not MIN_DATE <= start <= end <= MAX_DATE or (end - start).days >= 366:
        raise MarketError(
            "Calendar request must be within 2000-2035 and at most 366 days"
        )


def sessions(calendar_id: str, start: date, end: date) -> CalendarSchedule:
    """Return a bounded rules schedule without network calls or host timezone state."""
    _dates(start, end)
    zone = _new_york()
    if calendar_id == "XNYS":
        if version("exchange-calendars") != CALENDAR_VERSION:
            raise MarketError(
                "Exchange calendar package differs from its pinned version"
            )
        from exchange_calendars.exchange_calendar_xnys import (  # type: ignore[import-untyped]
            XNYSExchangeCalendar,
        )

        class PinnedXNYS(XNYSExchangeCalendar):  # type: ignore[misc]
            # The library normally loads the host tzdb. Bind its existing rules to
            # the pinned resource instead, without resetting global zoneinfo state.
            tz = zone

        calendar = PinnedXNYS(
            start=(start - timedelta(days=7)).isoformat(),
            end=(end + timedelta(days=7)).isoformat(),
            side="left",
        )
        rows = tuple(
            Session(
                cast(date, label.date()),
                cast(datetime, row["open"].to_pydatetime()),
                cast(datetime, row["close"].to_pydatetime()),
            )
            for label, row in calendar.schedule.iterrows()
            if start <= label.date() <= end
        )
        return CalendarSchedule(
            calendar_id,
            start,
            end,
            rows,
            "exchange-calendars",
            CALENDAR_VERSION,
            TZDATA_VERSION,
            (
                "XNYS regular cash session only; pre/post-market excluded.",
                "Versioned library rules, not historical calendar-publication vintages.",
                "No security-specific halt, suspension, or guaranteed future closure truth.",
            ),
        )
    if calendar_id != "FX_NY_17":
        raise MarketError(
            "Unsupported calendar; crypto/futures plugins are not implemented"
        )
    rows_list: list[Session] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            opening = datetime.combine(current - timedelta(days=1), time(17), zone)
            closing = datetime.combine(current, time(17), zone)
            rows_list.append(
                Session(current, opening.astimezone(UTC), closing.astimezone(UTC))
            )
        current += timedelta(days=1)
    return CalendarSchedule(
        calendar_id,
        start,
        end,
        tuple(rows_list),
        "quant-hunter-fx-convention",
        "1",
        TZDATA_VERSION,
        (
            "OTC_NY_17_CONVENTION: daily Sunday-Friday 17:00 America/New_York boundary.",
            "No centralized FX exchange or universal calendar is asserted.",
            "Venue holidays, maintenance, outages and executable liquidity are UNKNOWN.",
            "Spot FX only; no forwards, swaps, funding, or global-volume claim.",
        ),
    )
