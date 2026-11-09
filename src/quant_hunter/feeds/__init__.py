"""Rolling daily market and macro feeds (Hunter v2, phase 1).

Unlike the fixed historical diagnostic probes in ``quant_hunter.sources``,
these collectors keep a rolling history current. Every response is kept as
exact immutable bytes, and every refresh writes a new immutable curated
snapshot, so research can always ask "what did we know at time T?".
"""

from __future__ import annotations

from quant_hunter.feeds.config import FeedConfig, SeriesSpec, load_config
from quant_hunter.feeds.http import FeedError, HttpTransport, Transport
from quant_hunter.feeds.quality import QualityReport, assess
from quant_hunter.feeds.refresh import RefreshResult, refresh_all
from quant_hunter.feeds.store import FeedStore, Snapshot

__all__ = [
    "FeedConfig",
    "FeedError",
    "FeedStore",
    "HttpTransport",
    "QualityReport",
    "RefreshResult",
    "SeriesSpec",
    "Snapshot",
    "Transport",
    "assess",
    "load_config",
    "refresh_all",
]
