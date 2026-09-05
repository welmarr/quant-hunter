"""Quant Hunter's research-foundation package."""

from importlib.metadata import version

from quant_hunter.identity import RegistryKind, RegistryStore, kind_for_id, new_typed_id

__version__: str = version("quant-hunter")

__all__ = (
    "RegistryKind",
    "RegistryStore",
    "__version__",
    "kind_for_id",
    "new_typed_id",
)
