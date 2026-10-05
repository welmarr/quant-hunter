"""Fixed credential error codes never interpolate secret values."""


class VaultError(ValueError):
    """Credential operation failed without returning sensitive diagnostics."""
