"""Publication library: immutable documentation, not scientific approval authority."""

from .catalog import canonical_references
from .errors import PublicationError
from .service import PublicationService

__all__ = ("PublicationError", "PublicationService", "canonical_references")
