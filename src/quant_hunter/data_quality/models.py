"""Bounded declarations and selected-data references; no research authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from quant_hunter.config import JsonRecord, JsonValue
from quant_hunter.identity import RegistryKind, validate_typed_id
from quant_hunter.provenance.hashing import require_sha256_digest


class QualityError(ValueError):
    """Sanitized stable failure code, optionally with retained audit identity."""

    def __init__(self, code: str, audit_digest: str | None = None) -> None:
        self.code, self.audit_digest = code, audit_digest
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SelectedSnapshot:
    dataset_id: str
    record_digest: str
    normalized_digest: str
    quality_report_digest: str
    instrument_id: str
    instrument_revision_digest: str
    calendar_digest: str
    row_count: int
    bounds: JsonRecord
    step_ns: int
    feature_columns: tuple[str, ...]
    evidence_mode: str
    admission: str
    causal_eligible: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_typed_id(self.dataset_id, RegistryKind.DATASET)
        validate_typed_id(self.instrument_id, RegistryKind.INSTRUMENT)
        for digest in (
            self.record_digest,
            self.normalized_digest,
            self.quality_report_digest,
            self.instrument_revision_digest,
            self.calendar_digest,
        ):
            require_sha256_digest(digest)
        if (
            type(self.row_count) is not int
            or not 1 <= self.row_count <= 50_000_000
            or type(self.step_ns) is not int
            or self.step_ns
            not in {
                60_000_000_000,
                300_000_000_000,
                3_600_000_000_000,
                18_000_000_000_000,
            }
            or not isinstance(self.feature_columns, tuple)
            or not 1 <= len(self.feature_columns) <= 16
            or self.feature_columns[0] != "close"
            or len(set(self.feature_columns)) != len(self.feature_columns)
            or set(self.feature_columns)
            - {"close", "open", "high", "low", "volume", "open_bid", "open_ask"}
            or self.evidence_mode not in {"SYNTHETIC", "HISTORICAL"}
            or self.admission
            not in {"SYNTHETIC_SOFTWARE_ONLY", "HISTORICAL_EXPLORATORY", "BLOCKED"}
            or self.causal_eligible != (self.admission == "SYNTHETIC_SOFTWARE_ONLY")
            or (
                self.admission == "SYNTHETIC_SOFTWARE_ONLY"
                and self.evidence_mode != "SYNTHETIC"
            )
            or (
                self.admission == "HISTORICAL_EXPLORATORY"
                and self.evidence_mode != "HISTORICAL"
            )
            or type(self.causal_eligible) is not bool
            or not isinstance(self.reasons, tuple)
            or len(self.reasons) > 64
            or any(
                not isinstance(reason, str) or not 1 <= len(reason) <= 160
                for reason in self.reasons
            )
        ):
            raise QualityError("INVALID_SELECTED_SNAPSHOT")
        if not isinstance(self.bounds, dict) or set(self.bounds) != {"start", "end"}:
            raise QualityError("INVALID_SELECTED_BOUNDS")
        values = tuple(self.bounds[k] for k in ("start", "end"))
        if any(
            not isinstance(v, str) or len(v) > 32 or not v.endswith("Z") for v in values
        ):
            raise QualityError("INVALID_SELECTED_BOUNDS")
        try:
            start, end = (datetime.fromisoformat(cast(str, v)) for v in values)
            if start >= end:
                raise ValueError
        except ValueError:
            raise QualityError("INVALID_SELECTED_BOUNDS") from None

    def to_record(self) -> JsonRecord:
        self.__post_init__()
        return {
            "dataset_id": self.dataset_id,
            "record_digest": self.record_digest,
            "normalized_digest": self.normalized_digest,
            "quality_report_digest": self.quality_report_digest,
            "instrument_id": self.instrument_id,
            "instrument_revision_digest": self.instrument_revision_digest,
            "calendar_digest": self.calendar_digest,
            "row_count": self.row_count,
            "bounds": dict(self.bounds),
            "step_ns": self.step_ns,
            "feature_columns": cast(list[JsonValue], list(self.feature_columns)),
            "evidence_mode": self.evidence_mode,
            "admission": self.admission,
            "causal_eligible": self.causal_eligible,
            "reasons": cast(list[JsonValue], list(self.reasons)),
        }
