"""Governed immutable data quality and explicit application admission."""

from .mapping import MappingSpec, map_rows
from .models import QualityError, SelectedSnapshot
from .partitions import PartitionSelection
from .service import QualityService

__all__ = [
    "MappingSpec",
    "PartitionSelection",
    "QualityError",
    "QualityService",
    "SelectedSnapshot",
    "map_rows",
]
