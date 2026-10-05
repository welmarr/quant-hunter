"""Sanitized publication failures; untrusted document contents never enter errors."""

import re


class PublicationError(ValueError):
    """Stable code, optionally pointing to the immutable retained failure revision."""

    def __init__(self, code: str, *, revision_digest: str | None = None) -> None:
        self.code = (
            code if re.fullmatch(r"[A-Z_]{1,80}", code) else "PUBLICATION_FAILURE"
        )
        self.revision_digest = revision_digest
        super().__init__(self.code)
