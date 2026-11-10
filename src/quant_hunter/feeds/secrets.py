"""Read provider credentials from the private folder, never from the repo.

Files are simple ``name=value`` lines. Names are matched loosely (case,
spaces and underscores ignored) so a hand-written file works as is.
Values are returned to the caller only; they are never logged or stored.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

from quant_hunter.feeds.http import FeedError

ALIASES: Final = {
    "oanda": {
        "token": ("oandaapikey", "oandaapitoken", "apitoken", "apikey", "token"),
        "account": ("accountid", "oandaaccountid", "account"),
    },
    "alpaca": {
        "key": ("key", "apikey", "keyid", "apcaapikeyid", "alpacaapikeyid"),
        "secret": ("secret", "secretkey", "apcaapisecretkey", "alpacasecretkey"),
    },
}
_NORMAL = re.compile(r"[\s_\-]+")


def private_dir() -> Path:
    configured = os.environ.get("HUNTER_PRIVATE_DIR")
    if configured:
        return Path(configured)
    for candidate in (Path(r"D:\QuantHunterPrivate"), Path("/opt/hunter/private")):
        if candidate.exists():
            return candidate
    return Path(r"D:\QuantHunterPrivate")


def _norm(name: str) -> str:
    return _NORMAL.sub("", name).lower()


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[_norm(name)] = value.strip().strip("'\"")
    return values


def credentials(provider: str, folder: Path | None = None) -> dict[str, str]:
    """Return the provider's credentials under canonical names."""
    if provider not in ALIASES:
        raise FeedError(f"no credential layout for {provider}")
    path = (folder or private_dir()) / f"{provider}.env"
    if not path.exists():
        raise FeedError(f"missing credential file {path.name} in the private folder")
    found = parse_env(path.read_text(encoding="utf-8-sig"))
    out: dict[str, str] = {}
    for canonical, names in ALIASES[provider].items():
        value = next((found[n] for n in names if found.get(n)), "")
        if not value:
            raise FeedError(f"{path.name} has no value for {canonical}")
        out[canonical] = value
    return out
