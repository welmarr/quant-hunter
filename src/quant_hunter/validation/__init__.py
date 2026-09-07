"""Temporal validation and leakage-control contracts."""

from quant_hunter.validation.temporal import (
    INTERVAL_BOUNDARY_SEMANTICS,
    ChronologicalPartitions,
    GapDisposition,
    GapEvidence,
    TemporalInterval,
    TemporalValidationError,
    TemporalValidationIntegrityError,
    ValidationFold,
    ValidationPlan,
    ValidationScheme,
    build_validation_plan,
)

__all__ = [
    "INTERVAL_BOUNDARY_SEMANTICS",
    "ChronologicalPartitions",
    "GapDisposition",
    "GapEvidence",
    "TemporalInterval",
    "TemporalValidationError",
    "TemporalValidationIntegrityError",
    "ValidationFold",
    "ValidationPlan",
    "ValidationScheme",
    "build_validation_plan",
]
