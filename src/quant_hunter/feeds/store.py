"""Immutable raw captures and versioned curated snapshots on local disk."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_hunter.feeds.http import FeedError

Row = dict[str, object]
STAMP: Final = "%Y%m%dT%H%M%S%fZ"


@dataclass(frozen=True, slots=True)
class Snapshot:
    series_id: str
    retrieved_at: datetime
    path: Path
    rows: int
    content_sha256: str
    basis: str


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    tmp = path.with_name(path.name + ".partial")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def content_hash(rows: Sequence[Row]) -> str:
    canonical = json.dumps(
        [{k: _plain(v) for k, v in sorted(r.items())} for r in rows],
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class FeedStore:
    """``root/raw`` holds exact response bytes; ``root/curated`` the snapshots."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # raw -----------------------------------------------------------------
    def capture(
        self, *, series_id: str, url: str, body: bytes, retrieved_at: datetime
    ) -> str:
        digest = hashlib.sha256(body).hexdigest()
        _write_once(self.root / "raw" / digest[:2] / f"{digest}.bin", body)
        self._append(
            self.root / "raw" / "manifest.jsonl",
            {
                "sha256": digest,
                "bytes": len(body),
                "series": series_id,
                "url": url,
                "retrieved_at": retrieved_at.astimezone(UTC).isoformat(),
            },
        )
        return digest

    def raw(self, digest: str) -> bytes:
        return (self.root / "raw" / digest[:2] / f"{digest}.bin").read_bytes()

    # curated -------------------------------------------------------------
    def write_snapshot(
        self,
        *,
        series_id: str,
        rows: Sequence[Row],
        fields: Sequence[str],
        retrieved_at: datetime,
        raw_sha256: Sequence[str],
        basis: str,
    ) -> tuple[Snapshot, bool]:
        """Write a new snapshot unless identical to the latest one.

        Returns the current snapshot and whether a new file was written.
        """
        if not rows:
            raise FeedError(f"no rows to store for {series_id}")
        digest = content_hash(rows)
        latest = self.latest(series_id)
        if latest is not None and latest.content_sha256 == digest:
            self._append(
                self._dir(series_id) / "checks.jsonl",
                {
                    "verified_unchanged_at": retrieved_at.astimezone(UTC).isoformat(),
                    "content_sha256": digest,
                    "raw_sha256": list(raw_sha256),
                },
            )
            return latest, False
        stamp = retrieved_at.astimezone(UTC).strftime(STAMP)
        path = self._dir(series_id) / f"{stamp}.parquet"
        columns: dict[str, pa.Array] = {
            "date": pa.array([r["date"] for r in rows], type=pa.date32()),
            "available_at": pa.array(
                [r["available_at"] for r in rows], type=pa.timestamp("us", tz="UTC")
            ),
        }
        for field in fields:
            columns[field] = pa.array([r.get(field) for r in rows], type=pa.float64())
        table = pa.table(columns)
        tmp = path.with_name(path.name + ".partial")
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, tmp)
        os.replace(tmp, path)
        meta = {
            "series": series_id,
            "retrieved_at": retrieved_at.astimezone(UTC).isoformat(),
            "rows": len(rows),
            "fields": list(fields),
            "content_sha256": digest,
            "raw_sha256": list(raw_sha256),
            "basis": basis,
            "first_date": _plain(rows[0]["date"]),
            "last_date": _plain(rows[-1]["date"]),
        }
        _write_once(path.with_suffix(".json"), json.dumps(meta, indent=1).encode())
        snapshot = Snapshot(series_id, retrieved_at, path, len(rows), digest, basis)
        return snapshot, True

    def snapshots(self, series_id: str) -> list[Snapshot]:
        folder = self._dir(series_id)
        if not folder.exists():
            return []
        found: list[Snapshot] = []
        for meta_path in sorted(folder.glob("*.json")):
            meta = json.loads(meta_path.read_text())
            found.append(
                Snapshot(
                    series_id=series_id,
                    retrieved_at=datetime.fromisoformat(meta["retrieved_at"]),
                    path=meta_path.with_suffix(".parquet"),
                    rows=int(meta["rows"]),
                    content_sha256=str(meta["content_sha256"]),
                    basis=str(meta["basis"]),
                )
            )
        return sorted(found, key=lambda s: s.retrieved_at)

    def latest(self, series_id: str, as_of: datetime | None = None) -> Snapshot | None:
        candidates = [
            s
            for s in self.snapshots(series_id)
            if as_of is None or s.retrieved_at <= as_of
        ]
        return candidates[-1] if candidates else None

    def load(self, series_id: str, as_of: datetime | None = None) -> pa.Table:
        """Rows as known at ``as_of``: the snapshot retrieved by then, keeping
        only observations whose ``available_at`` is not after ``as_of``."""
        snapshot = self.latest(series_id, as_of)
        if snapshot is None:
            raise FeedError(f"no snapshot for {series_id} as of {as_of}")
        table = pq.read_table(snapshot.path)
        if as_of is None:
            return table
        cutoff = pa.scalar(as_of.astimezone(UTC), type=pa.timestamp("us", tz="UTC"))
        mask = pc.less_equal(table["available_at"], cutoff)
        return table.filter(mask)

    # helpers -------------------------------------------------------------
    def _dir(self, series_id: str) -> Path:
        return self.root / "curated" / series_id

    @staticmethod
    def _append(path: Path, record: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
