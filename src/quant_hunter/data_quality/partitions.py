"""Bounded owned-parent composition, without a fabricated collective dataset ID."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_hunter.config import JsonRecord, JsonValue, canonicalize_json
from quant_hunter.provenance.hashing import require_sha256_digest, sha256_canonical_json

from .models import QualityError, SelectedSnapshot

if TYPE_CHECKING:
    from .service import QualityService


@dataclass(frozen=True, slots=True)
class PartitionSelection:
    manifest_digest: str
    total_rows: int
    bounds: JsonRecord
    parent_snapshots: tuple[SelectedSnapshot, ...]
    calendar_profile_digest: str
    instrument_id: str
    instrument_revision_digest: str
    step_ns: int
    feature_columns: tuple[str, ...]
    evidence_mode: str
    causal_eligible: bool

    def to_record(self) -> JsonRecord:
        require_sha256_digest(self.manifest_digest)
        require_sha256_digest(self.calendar_profile_digest)
        if (
            not isinstance(self.parent_snapshots, tuple)
            or not 1 <= len(self.parent_snapshots) <= 1024
            or type(self.total_rows) is not int
            or not 1 <= self.total_rows <= 50_000_000
        ):
            raise QualityError("PARTITION_SELECTION_LIMIT")
        if sum(row.row_count for row in self.parent_snapshots) != self.total_rows:
            raise QualityError("PARTITION_ROW_COUNT_MISMATCH")
        first = self.parent_snapshots[0]
        for parent in self.parent_snapshots:
            parent.to_record()
            if any(
                getattr(parent, key) != getattr(self, key)
                for key in (
                    "instrument_id",
                    "instrument_revision_digest",
                    "step_ns",
                    "feature_columns",
                    "evidence_mode",
                    "causal_eligible",
                )
            ):
                raise QualityError("PARTITION_PROFILE_MISMATCH")
        if self.bounds != {
            "start": first.bounds["start"],
            "end": self.parent_snapshots[-1].bounds["end"],
        }:
            raise QualityError("PARTITION_BOUNDS_MISMATCH")
        if any(
            datetime.fromisoformat(cast(str, current.bounds["start"]))
            < datetime.fromisoformat(cast(str, previous.bounds["end"]))
            for previous, current in zip(
                self.parent_snapshots, self.parent_snapshots[1:], strict=False
            )
        ):
            raise QualityError("PARTITION_OVERLAP_OR_ORDER")
        return {
            "manifest_digest": self.manifest_digest,
            "total_rows": self.total_rows,
            "bounds": dict(self.bounds),
            "parent_snapshots": [row.to_record() for row in self.parent_snapshots],
            "calendar_profile_digest": self.calendar_profile_digest,
            "instrument_id": self.instrument_id,
            "instrument_revision_digest": self.instrument_revision_digest,
            "step_ns": self.step_ns,
            "feature_columns": list(self.feature_columns),
            "evidence_mode": self.evidence_mode,
            "causal_eligible": self.causal_eligible,
        }


def _calendar_profile(
    service: QualityService, snapshot: SelectedSnapshot
) -> JsonRecord:
    calendar = service._read(snapshot.calendar_digest)
    return {
        key: calendar[key]
        for key in (
            "calendar_id",
            "anchor",
            "timezone",
            "timezone_package",
            "package",
            "package_version",
        )
    }


def compose(
    service: QualityService,
    selections: tuple[tuple[str, str, str], ...],
    *,
    purpose: str,
    _publish: bool = True,
) -> PartitionSelection:
    if (
        not isinstance(selections, tuple)
        or not 1 <= len(selections) <= 1024
        or len({v[0] for v in selections}) != len(selections)
    ):
        raise QualityError("PARTITION_SELECTION_LIMIT")
    snapshots: list[SelectedSnapshot] = []
    profile: JsonRecord | None = None
    total = 0
    boundaries: list[JsonValue] = []
    for identity, record_digest, report_digest in selections:
        selected, _ = service.select(
            identity,
            expected_record_digest=record_digest,
            expected_report_digest=report_digest,
            purpose=purpose,
        )
        current_profile = _calendar_profile(service, selected)
        if snapshots:
            first, previous = snapshots[0], snapshots[-1]
            for name in (
                "instrument_id",
                "instrument_revision_digest",
                "step_ns",
                "feature_columns",
                "evidence_mode",
                "causal_eligible",
                "admission",
            ):
                if getattr(first, name) != getattr(selected, name):
                    raise QualityError("PARTITION_PROFILE_MISMATCH")
            if current_profile != profile:
                raise QualityError("PARTITION_CALENDAR_PROFILE_MISMATCH")
            before = datetime.fromisoformat(cast(str, previous.bounds["end"]))
            after = datetime.fromisoformat(cast(str, selected.bounds["start"]))
            if after < before:
                raise QualityError("PARTITION_OVERLAP_OR_ORDER")
            if after > before:
                boundaries.append(
                    {
                        "after_parent": len(snapshots) - 1,
                        "start": previous.bounds["end"],
                        "end": selected.bounds["start"],
                        "status": "PRESERVED_GAP_NO_IMPUTATION",
                        "continuity_claim": False,
                    }
                )
        else:
            profile = current_profile
        total += selected.row_count
        if total > 50_000_000:
            raise QualityError("PARTITION_TOTAL_ROW_LIMIT")
        snapshots.append(selected)
    first = snapshots[0]
    coverage = {"start": first.bounds["start"], "end": snapshots[-1].bounds["end"]}
    manifest: JsonRecord = {
        "schema_version": "qh-owned-partition-selection-v1",
        "purpose": purpose,
        "total_rows": total,
        "bounds": coverage,
        "parent_snapshots": [row.to_record() for row in snapshots],
        "calendar_profile": profile,
        "calendar_profile_digest": sha256_canonical_json(cast(JsonRecord, profile)),
        "boundaries": boundaries,
        "no_implicit_continuity": True,
        "no_collective_dataset_identity": True,
        "limitations": [
            "Every parent requires independent caller ownership; this immutable manifest grants no access rights.",
            "Gaps are retained. Window consumers must test actual cadence, session and availability.",
            "No full-corpus data allocation is performed; each parent retains its own raw/normalized/quality identities.",
        ],
    }
    manifest_digest = sha256_canonical_json(manifest)
    if _publish:
        service.objects.publish(canonicalize_json(manifest))
    result = PartitionSelection(
        manifest_digest,
        total,
        coverage,
        tuple(snapshots),
        cast(str, manifest["calendar_profile_digest"]),
        first.instrument_id,
        first.instrument_revision_digest,
        first.step_ns,
        first.feature_columns,
        first.evidence_mode,
        first.causal_eligible,
    )
    result.to_record()
    return result


def iter_batches(
    service: QualityService, manifest_digest: str
) -> Iterator[tuple[int, Any]]:
    manifest = service._read(manifest_digest)
    if manifest.get("schema_version") != "qh-owned-partition-selection-v1":
        raise QualityError("NOT_A_PARTITION_SELECTION")
    parents = manifest.get("parent_snapshots")
    if not isinstance(parents, list) or not 1 <= len(parents) <= 1024:
        raise QualityError("PARTITION_SELECTION_LIMIT")
    # Reconstruct and hash the complete manifest without a write during verification.
    references = tuple(
        (
            cast(str, row["dataset_id"]),
            cast(str, row["record_digest"]),
            cast(str, row["quality_report_digest"]),
        )
        for row in parents
        if isinstance(row, dict)
    )
    if len(references) != len(parents):
        raise QualityError("INVALID_PARTITION_PARENT")
    verified = compose(
        service, references, purpose=cast(str, manifest["purpose"]), _publish=False
    )
    if verified.manifest_digest != manifest_digest:
        raise QualityError("PARTITION_MANIFEST_REPLAY_MISMATCH")
    for index, snapshot in enumerate(verified.parent_snapshots):
        selected, content = service.select(
            snapshot.dataset_id,
            expected_record_digest=snapshot.record_digest,
            expected_report_digest=snapshot.quality_report_digest,
            purpose=cast(str, manifest["purpose"]),
        )
        if selected.to_record() != snapshot.to_record():
            raise QualityError("PARTITION_PARENT_CHANGED")
        reader = pq.ParquetFile(pa.BufferReader(content))
        count = 0
        for batch in reader.iter_batches(batch_size=4096, use_threads=False):
            count += batch.num_rows
            if count > snapshot.row_count:
                raise QualityError("PARTITION_ROW_COUNT_MISMATCH")
            yield index, batch
        if count != snapshot.row_count:
            raise QualityError("PARTITION_ROW_COUNT_MISMATCH")
