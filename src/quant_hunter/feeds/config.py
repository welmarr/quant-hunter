"""Feed universe configuration (TOML)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

PROVIDERS: Final = frozenset(
    {"yahoo", "fred", "alfred", "coinbase", "kraken_funding", "oanda", "alpaca"}
)
KINDS: Final = frozenset({"etf", "equity", "fx", "crypto", "macro", "funding"})
DEFAULT_MAX_JUMP: Final = {
    "etf": 0.25,
    "equity": 0.40,
    "fx": 0.10,
    "crypto": 0.50,
    "macro": 10.0,
    "funding": 10.0,
}
_SAFE = re.compile(r"[^A-Za-z0-9_-]")


@dataclass(frozen=True, slots=True)
class SeriesSpec:
    id: str
    provider: str
    symbol: str
    kind: str
    calendar: str | None
    max_jump: float


@dataclass(frozen=True, slots=True)
class FeedConfig:
    data_root: Path
    history_start: date
    series: tuple[SeriesSpec, ...]

    def by_id(self, series_id: str) -> SeriesSpec:
        for spec in self.series:
            if spec.id == series_id:
                return spec
        raise KeyError(series_id)


def series_id(provider: str, symbol: str) -> str:
    return f"{provider}.{_SAFE.sub('_', symbol)}"


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def parse_config(document: dict[str, object], *, base: Path) -> FeedConfig:
    settings = document.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("[settings] must be a table")
    root = Path(_text(settings.get("data_root", ".local/data/feeds"), "data_root"))
    if not root.is_absolute():
        root = base / root
    start = date.fromisoformat(
        _text(settings.get("history_start", "2000-01-01"), "history_start")
    )
    groups = document.get("groups", {})
    if not isinstance(groups, dict) or not groups:
        raise ValueError("[groups] must define at least one group")
    specs: list[SeriesSpec] = []
    seen: set[str] = set()
    for name, group in groups.items():
        if not isinstance(group, dict):
            raise ValueError(f"group {name} must be a table")
        provider = _text(group.get("provider"), f"{name}.provider")
        kind = _text(group.get("kind"), f"{name}.kind")
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r} in group {name}")
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r} in group {name}")
        calendar = group.get("calendar")
        if calendar is not None:
            calendar = _text(calendar, f"{name}.calendar")
        jump = group.get("max_jump", DEFAULT_MAX_JUMP[kind])
        if not isinstance(jump, int | float) or isinstance(jump, bool) or jump <= 0:
            raise ValueError(f"{name}.max_jump must be a positive number")
        symbols = group.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            raise ValueError(f"{name}.symbols must be a non-empty list")
        for symbol in symbols:
            sid = series_id(provider, _text(symbol, f"{name}.symbols"))
            if sid in seen:
                raise ValueError(f"duplicate series {sid}")
            seen.add(sid)
            specs.append(
                SeriesSpec(sid, provider, str(symbol), kind, calendar, float(jump))
            )
    return FeedConfig(data_root=root, history_start=start, series=tuple(specs))


def load_config(path: Path, *, base: Path | None = None) -> FeedConfig:
    with path.open("rb") as handle:
        document = tomllib.load(handle)
    return parse_config(document, base=base or path.resolve().parents[1])
