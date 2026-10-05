"""Additive execution adapters; Item8/Item9 remain the canonical authorities."""

from .service import ResearchValidationService, protocol_document
from .statistics import BootstrapSpec, holm_adjust, moving_block_mean
from .temporal import (
    FoldMembership,
    ObservationTimes,
    ResearchValidationError,
    SupervisedRow,
    execute_walk_forward,
    resolve_membership,
)

__all__ = [
    "BootstrapSpec",
    "FoldMembership",
    "ObservationTimes",
    "ResearchValidationError",
    "ResearchValidationService",
    "SupervisedRow",
    "execute_walk_forward",
    "holm_adjust",
    "moving_block_mean",
    "protocol_document",
    "resolve_membership",
]
