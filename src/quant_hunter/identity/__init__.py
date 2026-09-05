"""Typed identities and append-only registry storage."""

from quant_hunter.identity.ids import (
    IdentityError,
    RegistryKind,
    kind_for_id,
    new_typed_id,
    validate_typed_id,
)
from quant_hunter.identity.registry import (
    Allocation,
    AllocationExhaustedError,
    DuplicateIdentifierError,
    JsonRecord,
    JsonValue,
    ObjectAlreadyExistsError,
    RegistryIntegrityError,
    RegistryLockTimeoutError,
    RegistryStore,
    Revision,
    StaleWriterError,
)

__all__ = (
    "Allocation",
    "AllocationExhaustedError",
    "DuplicateIdentifierError",
    "IdentityError",
    "JsonRecord",
    "JsonValue",
    "ObjectAlreadyExistsError",
    "RegistryIntegrityError",
    "RegistryKind",
    "RegistryLockTimeoutError",
    "RegistryStore",
    "Revision",
    "StaleWriterError",
    "kind_for_id",
    "new_typed_id",
    "validate_typed_id",
)
