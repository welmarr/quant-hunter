"""Typed, permanent identities for registry-backed research objects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from re import Pattern
from re import compile as compile_pattern
from uuid import RFC_4122, UUID, uuid7


class IdentityError(ValueError):
    """A persistent identifier does not match its declared kind."""


@dataclass(frozen=True, slots=True)
class KindDefinition:
    """The immutable prefix, registry directory, and record field for one kind."""

    prefix: str
    directory: str
    id_field: str


class RegistryKind(Enum):
    """Persistent identifier kinds approved by DEC-0009."""

    FAMILY = KindDefinition("FAM", "families", "object_id")
    MODEL = KindDefinition("MOD", "models", "object_id")
    STRATEGY = KindDefinition("STRAT", "strategies", "object_id")
    PATTERN = KindDefinition("PATTERN", "patterns", "pattern_id")
    EXPERIMENT = KindDefinition("EXP", "experiments", "experiment_id")
    SOURCE = KindDefinition("SOURCE", "sources", "source_id")
    DATASET = KindDefinition("DATASET", "datasets", "dataset_id")
    BACKLOG = KindDefinition("BACKLOG", "backlog", "backlog_id")
    COST = KindDefinition("COST", "costs", "cost_id")

    @property
    def prefix(self) -> str:
        """Return the stable textual prefix."""
        return self.value.prefix

    @property
    def directory(self) -> str:
        """Return the fixed directory below the registry root."""
        return self.value.directory

    @property
    def id_field(self) -> str:
        """Return the identifier field stored in this kind's records."""
        return self.value.id_field


UuidFactory = Callable[[], UUID]
_TYPED_ID: Pattern[str] = compile_pattern(
    r"^(?P<prefix>[A-Z]+)-(?P<uuid>[0-9a-f]{8}-[0-9a-f]{4}-"
    r"7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$"
)


def new_typed_id(kind: RegistryKind, *, uuid_factory: UuidFactory = uuid7) -> str:
    """Allocate a lowercase RFC 9562 UUIDv7 with the kind's stable prefix."""
    value = uuid_factory()
    if value.version != 7 or value.variant != RFC_4122:
        raise IdentityError("UUID factory must return an RFC 9562 UUIDv7")
    return f"{kind.prefix}-{value}"


def kind_for_id(object_id: str) -> RegistryKind:
    """Validate an identifier and return its declared registry kind."""
    match = _TYPED_ID.fullmatch(object_id)
    if match is None:
        raise IdentityError(f"Malformed typed UUIDv7 identifier: {object_id!r}")
    prefix = match.group("prefix")
    try:
        kind = next(
            candidate for candidate in RegistryKind if candidate.prefix == prefix
        )
    except StopIteration as error:
        raise IdentityError(
            f"Unknown persistent identifier prefix: {prefix!r}"
        ) from error
    return kind


def validate_typed_id(object_id: str, expected_kind: RegistryKind) -> None:
    """Require an identifier to have the exact expected persistent kind."""
    actual_kind = kind_for_id(object_id)
    if actual_kind is not expected_kind:
        raise IdentityError(
            f"Identifier kind {actual_kind.name} does not match {expected_kind.name}"
        )
