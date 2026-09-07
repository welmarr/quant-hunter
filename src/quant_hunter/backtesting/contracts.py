"""Canonical Item 9C interfaces that describe, but never run, simulations."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.identity import RegistryKind, validate_typed_id
from quant_hunter.provenance import DataManifestReference
from quant_hunter.provenance.hashing import (
    require_sha256_digest,
    sha256_bytes,
    verify_sha256_bytes,
)
from quant_hunter.storage.security import reject_credential_uri, reject_secret_text
from quant_hunter.validation import (
    Applicability,
    EvidenceOutcome,
    ExactNumericEvidence,
    PartitionRole,
)

_IDENTITY: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_GIT_REVISION: Final = re.compile(r"^[0-9a-f]{40}$")
FILL_PRICE_TIME_RULE: Final = "PRICE_TIME_AT_OR_AFTER_ORDER_ELIGIBILITY"
V6_EVIDENCE_ONLY: Final = "ITEM_9B_V6_ASSESSMENT_REQUIRED"
ITEM_8_DECISION_AUTHORITY: Final = "ITEM_8_EXPERIMENT_LIFECYCLE"


class SimulationContractError(ValueError):
    """An Item 9C metadata declaration violates a scientific invariant."""


class SimulationIntegrityError(RuntimeError):
    """Canonical bytes differ from an Item 9C typed contract."""


class AssumptionBasis(StrEnum):
    ASSUMED = "ASSUMED"
    MEASURED = "MEASURED"
    EMPIRICALLY_SUPPORTED = "EMPIRICALLY_SUPPORTED"


class RealismLevel(StrEnum):
    IDEALIZED = "IDEALIZED"
    REALISTICALLY_MODELED = "REALISTICALLY_MODELED"


class PriceSource(StrEnum):
    BID = "BID"
    ASK = "ASK"
    MIDPOINT = "MIDPOINT"
    LAST_TRADE = "LAST_TRADE"
    OTHER = "OTHER"


class PriceQuality(StrEnum):
    INDICATIVE = "INDICATIVE"
    EXECUTABLE = "EXECUTABLE"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class DataCapability(StrEnum):
    BAR_OHLC = "BAR_OHLC"
    TRADE_TICK = "TRADE_TICK"
    TOP_OF_BOOK = "TOP_OF_BOOK"
    ORDER_BOOK = "ORDER_BOOK"
    FULL_DEPTH_WITH_QUEUE_EVENTS = "FULL_DEPTH_WITH_QUEUE_EVENTS"


class LatencyKind(StrEnum):
    DATA_VENDOR = "DATA_VENDOR"
    STRATEGY_PROCESSING = "STRATEGY_PROCESSING"
    ORDER_TRANSMISSION = "ORDER_TRANSMISSION"
    VENUE_BROKER = "VENUE_BROKER"


class DurationUnit(StrEnum):
    NANOSECONDS = "NANOSECONDS"
    MICROSECONDS = "MICROSECONDS"
    MILLISECONDS = "MILLISECONDS"
    SECONDS = "SECONDS"
    MINUTES = "MINUTES"
    HOURS = "HOURS"
    DAYS = "DAYS"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    OTHER = "OTHER"


class TimeInForce(StrEnum):
    DAY = "DAY"
    GOOD_TILL_CANCELLED = "GOOD_TILL_CANCELLED"
    IMMEDIATE_OR_CANCEL = "IMMEDIATE_OR_CANCEL"
    FILL_OR_KILL = "FILL_OR_KILL"
    SESSION_CLOSE = "SESSION_CLOSE"
    OTHER = "OTHER"


class PartialFillPolicy(StrEnum):
    ALLOW = "ALLOW"
    REQUIRE_FULL_FILL = "REQUIRE_FULL_FILL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CostComponent(StrEnum):
    SPREAD = "SPREAD"
    COMMISSION = "COMMISSION"
    EXCHANGE_BROKER_FEES = "EXCHANGE_BROKER_FEES"
    FINANCING = "FINANCING"
    CARRY = "CARRY"
    ROLLOVER = "ROLLOVER"
    SLIPPAGE = "SLIPPAGE"
    LATENCY_IMPACT = "LATENCY_IMPACT"
    PARTIAL_FILL_IMPACT = "PARTIAL_FILL_IMPACT"


class MarketPolicyArea(StrEnum):
    TRADING_SESSIONS = "TRADING_SESSIONS"
    SESSION_BOUNDARIES = "SESSION_BOUNDARIES"
    HOLIDAYS = "HOLIDAYS"
    MARKET_CLOSURES = "MARKET_CLOSURES"
    WEEKEND_GAPS = "WEEKEND_GAPS"
    STALE_QUOTES = "STALE_QUOTES"
    DATA_GAPS = "DATA_GAPS"
    ROLLOVER_BOUNDARIES = "ROLLOVER_BOUNDARIES"


class RandomnessMode(StrEnum):
    DETERMINISTIC_SEEDED = "DETERMINISTIC_SEEDED"
    DETERMINISTIC_NO_RANDOMNESS = "DETERMINISTIC_NO_RANDOMNESS"
    NONDETERMINISTIC = "NONDETERMINISTIC"


class OutputEvidenceCategory(StrEnum):
    GROSS_SIGNAL_PERFORMANCE = "GROSS_SIGNAL_PERFORMANCE"
    GROSS_TRADING_PERFORMANCE = "GROSS_TRADING_PERFORMANCE"
    TRANSACTION_COST = "TRANSACTION_COST"
    FINANCING_CARRY = "FINANCING_CARRY"
    NET_PERFORMANCE = "NET_PERFORMANCE"
    ORDER = "ORDER"
    FILL = "FILL"


class OutputEvidenceDisposition(StrEnum):
    PRODUCED = "PRODUCED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    FAILED = "FAILED"
    PENDING = "PENDING"


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SimulationContractError(f"{field} must be a nonempty string")
    reject_secret_text(value, field)
    return value


def _identity(value: object, field: str) -> str:
    text = _nonempty(value, field)
    if _IDENTITY.fullmatch(text) is None:
        raise SimulationContractError(f"{field} contains unsupported characters")
    return text


def _strings(values: object, field: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise SimulationContractError(f"{field} must be an immutable tuple")
    normalized = tuple(_nonempty(value, field) for value in values)
    if required and not normalized:
        raise SimulationContractError(f"{field} must not be empty")
    if len(set(normalized)) != len(normalized):
        raise SimulationContractError(f"{field} must not contain duplicates")
    return normalized


def _enum(value: object, expected: type[StrEnum], field: str) -> None:
    if not isinstance(value, expected):
        raise SimulationContractError(f"{field} must use the governed vocabulary")


@dataclass(frozen=True, slots=True)
class ExactQuantity:
    """An exact scientific quantity with explicit unit and interpretation basis."""

    value: str
    unit: str
    basis: str
    currency: str | None = None
    sign_convention: str | None = None

    def __post_init__(self) -> None:
        ExactNumericEvidence(self.value, self.unit)
        _nonempty(self.basis, "quantity basis")
        if self.currency is not None:
            _nonempty(self.currency, "quantity currency")
        if self.sign_convention is not None:
            _nonempty(self.sign_convention, "quantity sign convention")

    def document(self) -> JsonRecord:
        return {
            "value": self.value,
            "unit": self.unit,
            "basis": self.basis,
            "currency": self.currency,
            "sign_convention": self.sign_convention,
        }


@dataclass(frozen=True, slots=True)
class ExactDuration:
    """A nonnegative exact duration independent of platform timer precision."""

    value: str
    unit: DurationUnit

    def __post_init__(self) -> None:
        _enum(self.unit, DurationUnit, "duration unit")
        ExactNumericEvidence(self.value, self.unit.value)
        if Decimal(self.value) < 0:
            raise SimulationContractError("Duration must not be negative")

    def document(self) -> JsonRecord:
        return {"value": self.value, "unit": self.unit.value}


@dataclass(frozen=True, slots=True)
class SidePriceRule:
    """The declared price source for one order side; no lookup is performed."""

    side: OrderSide
    source: PriceSource
    rationale: str
    custom_source_description: str | None = None

    def __post_init__(self) -> None:
        _enum(self.side, OrderSide, "order side")
        _enum(self.source, PriceSource, "side price source")
        _nonempty(self.rationale, "side price rationale")
        if self.source is PriceSource.OTHER:
            _nonempty(self.custom_source_description, "custom side price source")
        elif self.custom_source_description is not None:
            raise SimulationContractError(
                "Only an OTHER side price source may have a custom description"
            )

    def document(self) -> JsonRecord:
        return {
            "side": self.side.value,
            "source": self.source.value,
            "rationale": self.rationale,
            "custom_source_description": self.custom_source_description,
        }


@dataclass(frozen=True, slots=True)
class ClaimedArtifact:
    """A claimed immutable reference; Item 9C does not access or verify its bytes."""

    reference: str
    digest: str

    def __post_init__(self) -> None:
        _nonempty(self.reference, "artifact reference")
        reject_credential_uri(self.reference)
        require_sha256_digest(self.digest)

    def document(self) -> JsonRecord:
        return {
            "reference": self.reference,
            "digest": self.digest,
            "cryptographically_verified": False,
        }


@dataclass(frozen=True, slots=True)
class AssumptionSupport:
    """Distinguish assumptions from measured or empirically supported claims."""

    basis: AssumptionBasis
    evidence: ClaimedArtifact | None = None

    def __post_init__(self) -> None:
        _enum(self.basis, AssumptionBasis, "assumption basis")
        if self.basis is AssumptionBasis.ASSUMED:
            if self.evidence is not None:
                raise SimulationContractError(
                    "An ASSUMED value cannot carry measured-evidence metadata"
                )
        elif not isinstance(self.evidence, ClaimedArtifact):
            raise SimulationContractError(
                "Measured or empirically supported assumptions require evidence"
            )

    def document(self) -> JsonRecord:
        return {
            "basis": self.basis.value,
            "evidence": self.evidence.document() if self.evidence else None,
        }


@dataclass(frozen=True, slots=True)
class PriceAssumption:
    reference_source: PriceSource
    quality: PriceQuality
    realism: RealismLevel
    support: AssumptionSupport
    rationale_or_limitation: str
    representative_price: ExactQuantity | None = None
    side_price_rules: tuple[SidePriceRule, ...] = ()
    custom_reference_source_description: str | None = None

    def __post_init__(self) -> None:
        _enum(self.reference_source, PriceSource, "reference price source")
        _enum(self.quality, PriceQuality, "price quality")
        _enum(self.realism, RealismLevel, "price realism")
        if not isinstance(self.support, AssumptionSupport):
            raise SimulationContractError("Price support must be typed")
        _nonempty(self.rationale_or_limitation, "price rationale or limitation")
        if self.reference_source is PriceSource.OTHER:
            _nonempty(
                self.custom_reference_source_description,
                "custom reference price source",
            )
        elif self.custom_reference_source_description is not None:
            raise SimulationContractError(
                "Only an OTHER reference price source may have a custom description"
            )
        if self.representative_price is not None and not isinstance(
            self.representative_price, ExactQuantity
        ):
            raise SimulationContractError("Representative price must be exact")
        if self.reference_source is PriceSource.MIDPOINT and (
            self.quality is PriceQuality.EXECUTABLE
            or self.realism is RealismLevel.REALISTICALLY_MODELED
        ):
            raise SimulationContractError(
                "MIDPOINT pricing cannot claim executable-price realism"
            )
        if (
            self.quality is PriceQuality.INDICATIVE
            and self.realism is RealismLevel.REALISTICALLY_MODELED
        ):
            raise SimulationContractError(
                "INDICATIVE pricing cannot claim executable-price realism"
            )
        if not isinstance(self.side_price_rules, tuple) or any(
            not isinstance(value, SidePriceRule) for value in self.side_price_rules
        ):
            raise SimulationContractError("Side-aware price rules must be typed")
        sides = tuple(value.side for value in self.side_price_rules)
        if len(sides) != len(set(sides)):
            raise SimulationContractError("Side-aware price rules must be unique")
        if self.quality is PriceQuality.EXECUTABLE and set(sides) != set(OrderSide):
            raise SimulationContractError(
                "Executable pricing requires explicit BUY and SELL side rules"
            )
        if self.quality is PriceQuality.EXECUTABLE and any(
            value.source is PriceSource.MIDPOINT for value in self.side_price_rules
        ):
            raise SimulationContractError(
                "MIDPOINT side pricing cannot claim executable-price realism"
            )

    def document(self) -> JsonRecord:
        return {
            "reference_source": self.reference_source.value,
            "reference_source_is_execution_authority": False,
            "execution_price_authority": (
                "SIDE_PRICE_RULES" if self.side_price_rules else "NOT_APPLICABLE"
            ),
            "quality": self.quality.value,
            "realism": self.realism.value,
            "support": self.support.document(),
            "rationale_or_limitation": self.rationale_or_limitation,
            "representative_price": (
                self.representative_price.document()
                if self.representative_price
                else None
            ),
            "side_price_rules": [
                value.document()
                for value in sorted(
                    self.side_price_rules, key=lambda item: item.side.value
                )
            ],
            "custom_reference_source_description": (
                self.custom_reference_source_description
            ),
        }


@dataclass(frozen=True, slots=True)
class LatencyAssumption:
    declaration_id: str
    kind: LatencyKind
    applicability: Applicability
    rationale: str
    duration: ExactDuration | None = None
    support: AssumptionSupport | None = None

    def __post_init__(self) -> None:
        _identity(self.declaration_id, "latency declaration identity")
        _enum(self.kind, LatencyKind, "latency kind")
        _enum(self.applicability, Applicability, "latency applicability")
        _nonempty(self.rationale, "latency rationale")
        if self.applicability is Applicability.REQUIRED:
            if not isinstance(self.duration, ExactDuration) or not isinstance(
                self.support, AssumptionSupport
            ):
                raise SimulationContractError(
                    "Applicable latency requires an exact duration and support basis"
                )
        elif self.duration is not None or self.support is not None:
            raise SimulationContractError(
                "NOT_APPLICABLE latency cannot contain configured values"
            )

    def document(self) -> JsonRecord:
        return {
            "declaration_id": self.declaration_id,
            "kind": self.kind.value,
            "applicability": self.applicability.value,
            "rationale": self.rationale,
            "duration": self.duration.document() if self.duration else None,
            "support": self.support.document() if self.support else None,
        }


def _latencies(values: object) -> tuple[LatencyAssumption, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, LatencyAssumption) for value in values
    ):
        raise SimulationContractError("Latency declarations must be typed")
    identities = tuple(value.declaration_id for value in values)
    kinds = tuple(value.kind for value in values)
    if len(set(identities)) != len(identities):
        raise SimulationContractError("Latency declaration identities must be unique")
    if len(kinds) != len(set(kinds)) or set(kinds) != set(LatencyKind):
        raise SimulationContractError("Every latency kind needs explicit applicability")
    return values


@dataclass(frozen=True, slots=True)
class ExecutionTimeline:
    information_availability_semantics: str
    decision_time_semantics: str
    order_eligibility_semantics: str
    latencies: tuple[LatencyAssumption, ...]

    def __post_init__(self) -> None:
        _nonempty(
            self.information_availability_semantics,
            "information availability semantics",
        )
        _nonempty(self.decision_time_semantics, "decision-time semantics")
        _nonempty(self.order_eligibility_semantics, "order-eligibility semantics")
        _latencies(self.latencies)

    def document(self) -> JsonRecord:
        latency_values: list[JsonValue] = [
            value.document()
            for value in sorted(self.latencies, key=lambda item: item.kind.value)
        ]
        sequence: list[JsonValue] = [
            "INFORMATION_AVAILABLE",
            "SIGNAL_DECISION",
            "PROCESSING_LATENCY",
            "ORDER_SUBMISSION_ELIGIBLE",
            "FUTURE_ORDER_FILL_HANDLING",
        ]
        return {
            "sequence": sequence,
            "information_availability_semantics": self.information_availability_semantics,
            "decision_time_semantics": self.decision_time_semantics,
            "order_eligibility_semantics": self.order_eligibility_semantics,
            "fill_price_time_rule": FILL_PRICE_TIME_RULE,
            "latencies": latency_values,
        }


@dataclass(frozen=True, slots=True)
class QueueRealismDeclaration:
    applicability: Applicability
    rationale: str
    realism: RealismLevel | None = None
    required_capability: DataCapability | None = None
    support: AssumptionSupport | None = None

    def __post_init__(self) -> None:
        _enum(self.applicability, Applicability, "queue-realism applicability")
        _nonempty(self.rationale, "queue-realism rationale")
        if self.applicability is Applicability.REQUIRED:
            if self.realism is not RealismLevel.REALISTICALLY_MODELED:
                raise SimulationContractError(
                    "Applicable queue realism must be explicitly realistically modeled"
                )
            if (
                self.required_capability
                is not DataCapability.FULL_DEPTH_WITH_QUEUE_EVENTS
            ):
                raise SimulationContractError(
                    "Exact queue realism requires full-depth queue-event data"
                )
            if not isinstance(self.support, AssumptionSupport):
                raise SimulationContractError(
                    "Applicable queue realism requires support"
                )
        elif any(
            value is not None
            for value in (self.realism, self.required_capability, self.support)
        ):
            raise SimulationContractError(
                "NOT_APPLICABLE queue realism cannot contain configured claims"
            )

    def document(self) -> JsonRecord:
        return {
            "applicability": self.applicability.value,
            "rationale": self.rationale,
            "realism": self.realism.value if self.realism else None,
            "required_capability": (
                self.required_capability.value if self.required_capability else None
            ),
            "support": self.support.document() if self.support else None,
        }


@dataclass(frozen=True, slots=True)
class OrderAssumptions:
    order_type: OrderType
    time_in_force: TimeInForce
    cancellation_behavior: str
    partial_fill_policy: PartialFillPolicy
    partial_fill_rationale: str
    fill_priority_assumption: str
    marketability_assumption: str
    capacity_liquidity_limitation: str
    order_expiry_behavior: str
    queue_realism: QueueRealismDeclaration
    custom_order_type_description: str | None = None
    custom_time_in_force_description: str | None = None
    representative_quantity: ExactQuantity | None = None
    representative_notional: ExactQuantity | None = None

    def __post_init__(self) -> None:
        _enum(self.order_type, OrderType, "order type")
        _enum(self.time_in_force, TimeInForce, "time in force")
        _enum(self.partial_fill_policy, PartialFillPolicy, "partial-fill policy")
        _nonempty(self.partial_fill_rationale, "partial-fill rationale")
        if self.order_type is OrderType.OTHER:
            _nonempty(self.custom_order_type_description, "custom order type")
        elif self.custom_order_type_description is not None:
            raise SimulationContractError(
                "Only OTHER order type may have a custom description"
            )
        if self.time_in_force is TimeInForce.OTHER:
            _nonempty(self.custom_time_in_force_description, "custom time in force")
        elif self.custom_time_in_force_description is not None:
            raise SimulationContractError(
                "Only OTHER time in force may have a custom description"
            )
        for value, field in (
            (self.cancellation_behavior, "cancellation behavior"),
            (self.fill_priority_assumption, "fill-priority assumption"),
            (self.marketability_assumption, "marketability assumption"),
            (self.capacity_liquidity_limitation, "capacity/liquidity limitation"),
            (self.order_expiry_behavior, "order-expiry behavior"),
        ):
            _nonempty(value, field)
        if not isinstance(self.queue_realism, QueueRealismDeclaration):
            raise SimulationContractError("Queue-realism declaration must be typed")
        for quantity, quantity_field in (
            (self.representative_quantity, "representative quantity"),
            (self.representative_notional, "representative notional"),
        ):
            if quantity is not None and not isinstance(quantity, ExactQuantity):
                raise SimulationContractError(f"{quantity_field} must be exact")

    def document(self) -> JsonRecord:
        return {
            "order_type": self.order_type.value,
            "time_in_force": self.time_in_force.value,
            "cancellation_behavior": self.cancellation_behavior,
            "partial_fill_policy": self.partial_fill_policy.value,
            "partial_fill_rationale": self.partial_fill_rationale,
            "fill_priority_assumption": self.fill_priority_assumption,
            "marketability_assumption": self.marketability_assumption,
            "capacity_liquidity_limitation": self.capacity_liquidity_limitation,
            "order_expiry_behavior": self.order_expiry_behavior,
            "queue_realism": self.queue_realism.document(),
            "custom_order_type_description": self.custom_order_type_description,
            "custom_time_in_force_description": (self.custom_time_in_force_description),
            "representative_quantity": (
                self.representative_quantity.document()
                if self.representative_quantity
                else None
            ),
            "representative_notional": (
                self.representative_notional.document()
                if self.representative_notional
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class CostComponentDeclaration:
    declaration_id: str
    component: CostComponent
    applicability: Applicability
    rationale: str
    protocol: str | None = None
    value: ExactQuantity | None = None
    support: AssumptionSupport | None = None

    def __post_init__(self) -> None:
        _identity(self.declaration_id, "cost declaration identity")
        _enum(self.component, CostComponent, "cost component")
        _enum(self.applicability, Applicability, "cost applicability")
        _nonempty(self.rationale, "cost rationale")
        if self.applicability is Applicability.REQUIRED:
            _nonempty(self.protocol, "applicable cost protocol")
            if not isinstance(self.support, AssumptionSupport):
                raise SimulationContractError(
                    "Applicable cost requires an assumption-support basis"
                )
            if self.value is not None and not isinstance(self.value, ExactQuantity):
                raise SimulationContractError("Configured cost value must be exact")
            if self.value is not None and self.value.sign_convention is None:
                raise SimulationContractError(
                    "Configured cost value requires an explicit sign convention"
                )
        elif any(
            value is not None for value in (self.protocol, self.value, self.support)
        ):
            raise SimulationContractError(
                "NOT_APPLICABLE cost cannot contain configured values"
            )

    def document(self) -> JsonRecord:
        return {
            "declaration_id": self.declaration_id,
            "component": self.component.value,
            "applicability": self.applicability.value,
            "rationale": self.rationale,
            "protocol": self.protocol,
            "value": self.value.document() if self.value else None,
            "support": self.support.document() if self.support else None,
        }


def _cost_components(values: object) -> tuple[CostComponentDeclaration, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, CostComponentDeclaration) for value in values
    ):
        raise SimulationContractError("Cost declarations must be typed")
    identities = tuple(value.declaration_id for value in values)
    components = tuple(value.component for value in values)
    if len(set(identities)) != len(identities):
        raise SimulationContractError("Cost declaration identities must be unique")
    if len(components) != len(set(components)) or set(components) != set(CostComponent):
        raise SimulationContractError(
            "Every cost component needs explicit applicability; missing is not zero"
        )
    return values


@dataclass(frozen=True, slots=True)
class TransactionCostPlan:
    components: tuple[CostComponentDeclaration, ...]
    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise SimulationIntegrityError("Cost plan is not a JSON object")
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)
        _cost_components(self.components)
        if (
            canonicalize_json(_cost_plan_document(self.components))
            != self.canonical_bytes
        ):
            raise SimulationIntegrityError("Cost plan differs from typed fields")


def _cost_plan_document(
    components: tuple[CostComponentDeclaration, ...],
) -> JsonRecord:
    values: list[JsonValue] = [value.document() for value in components]
    return {
        "schema_version": "1.0.0",
        "plan_type": "TRANSACTION_COST_PLAN",
        "calculation_authorized": False,
        "components": values,
    }


def build_transaction_cost_plan(
    components: Sequence[CostComponentDeclaration],
) -> TransactionCostPlan:
    values = tuple(components)
    _cost_components(values)
    ordered = tuple(sorted(values, key=lambda item: item.component.value))
    canonical_bytes = canonicalize_json(_cost_plan_document(ordered))
    plan = TransactionCostPlan(ordered, canonical_bytes, sha256_bytes(canonical_bytes))
    plan.verify()
    return plan


@dataclass(frozen=True, slots=True)
class MarketPolicyDeclaration:
    declaration_id: str
    area: MarketPolicyArea
    applicability: Applicability
    rationale: str
    policy: str | None = None
    support: AssumptionSupport | None = None

    def __post_init__(self) -> None:
        _identity(self.declaration_id, "market-policy declaration identity")
        _enum(self.area, MarketPolicyArea, "market-policy area")
        _enum(self.applicability, Applicability, "market-policy applicability")
        _nonempty(self.rationale, "market-policy rationale")
        if self.applicability is Applicability.REQUIRED:
            _nonempty(self.policy, "applicable market policy")
            if not isinstance(self.support, AssumptionSupport):
                raise SimulationContractError(
                    "Applicable market policy requires an assumption-support basis"
                )
        elif self.policy is not None or self.support is not None:
            raise SimulationContractError(
                "NOT_APPLICABLE market policy cannot contain configured values"
            )

    def document(self) -> JsonRecord:
        return {
            "declaration_id": self.declaration_id,
            "area": self.area.value,
            "applicability": self.applicability.value,
            "rationale": self.rationale,
            "policy": self.policy,
            "support": self.support.document() if self.support else None,
        }


def _market_policies(values: object) -> tuple[MarketPolicyDeclaration, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, MarketPolicyDeclaration) for value in values
    ):
        raise SimulationContractError("Market policies must be typed")
    identities = tuple(value.declaration_id for value in values)
    areas = tuple(value.area for value in values)
    if len(set(identities)) != len(identities):
        raise SimulationContractError("Market-policy identities must be unique")
    if len(areas) != len(set(areas)) or set(areas) != set(MarketPolicyArea):
        raise SimulationContractError(
            "Every session, closure, and gap area needs explicit applicability"
        )
    return values


def _data_capabilities(values: object) -> tuple[DataCapability, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, DataCapability) for value in values
    ):
        raise SimulationContractError("Data capabilities must use governed vocabulary")
    if not values:
        raise SimulationContractError("Data capabilities must not be empty")
    if len(set(values)) != len(values):
        raise SimulationContractError("Data capabilities must not contain duplicates")
    return values


def _validate_execution_plan(
    price: object,
    timeline: object,
    orders: object,
    capabilities: tuple[DataCapability, ...],
    policies: tuple[MarketPolicyDeclaration, ...],
) -> None:
    if not isinstance(price, PriceAssumption):
        raise SimulationContractError("Price assumption must be typed")
    if not isinstance(timeline, ExecutionTimeline):
        raise SimulationContractError("Execution timeline must be typed")
    if not isinstance(orders, OrderAssumptions):
        raise SimulationContractError("Order assumptions must be typed")
    _data_capabilities(capabilities)
    _market_policies(policies)
    queue = orders.queue_realism
    if (
        queue.applicability is Applicability.REQUIRED
        and queue.required_capability not in capabilities
    ):
        raise SimulationContractError(
            "Queue realism exceeds the declared data capability"
        )
    if (
        orders.order_type is OrderType.MARKET
        and price.quality is PriceQuality.EXECUTABLE
    ):
        side_sources = {value.side: value.source for value in price.side_price_rules}
        if PriceSource.LAST_TRADE in side_sources.values():
            raise SimulationContractError(
                "LAST_TRADE is not an executable side quote for a MARKET order"
            )
        if side_sources != {
            OrderSide.BUY: PriceSource.ASK,
            OrderSide.SELL: PriceSource.BID,
        }:
            raise SimulationContractError(
                "Standard executable MARKET pricing requires BUY to ASK and SELL to BID"
            )


def _execution_plan_document(
    price: PriceAssumption,
    timeline: ExecutionTimeline,
    orders: OrderAssumptions,
    capabilities: tuple[DataCapability, ...],
    policies: tuple[MarketPolicyDeclaration, ...],
) -> JsonRecord:
    capability_values: list[JsonValue] = [value.value for value in capabilities]
    policy_values: list[JsonValue] = [value.document() for value in policies]
    return {
        "schema_version": "1.0.0",
        "plan_type": "EXECUTION_ASSUMPTION_PLAN",
        "price_assumption": price.document(),
        "timeline": timeline.document(),
        "order_assumptions": orders.document(),
        "data_capabilities": capability_values,
        "market_policies": policy_values,
        "v6_claim_boundary": V6_EVIDENCE_ONLY,
        "execution_authorized": False,
    }


@dataclass(frozen=True, slots=True)
class ExecutionAssumptionPlan:
    price_assumption: PriceAssumption
    timeline: ExecutionTimeline
    order_assumptions: OrderAssumptions
    data_capabilities: tuple[DataCapability, ...]
    market_policies: tuple[MarketPolicyDeclaration, ...]
    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise SimulationIntegrityError("Execution plan is not a JSON object")
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)
        _validate_execution_plan(
            self.price_assumption,
            self.timeline,
            self.order_assumptions,
            self.data_capabilities,
            self.market_policies,
        )
        expected = _execution_plan_document(
            self.price_assumption,
            self.timeline,
            self.order_assumptions,
            self.data_capabilities,
            self.market_policies,
        )
        if canonicalize_json(expected) != self.canonical_bytes:
            raise SimulationIntegrityError("Execution plan differs from typed fields")


def build_execution_assumption_plan(
    *,
    price_assumption: PriceAssumption,
    timeline: ExecutionTimeline,
    order_assumptions: OrderAssumptions,
    data_capabilities: Sequence[DataCapability],
    market_policies: Sequence[MarketPolicyDeclaration],
) -> ExecutionAssumptionPlan:
    capabilities = tuple(data_capabilities)
    policies = tuple(market_policies)
    _validate_execution_plan(
        price_assumption,
        timeline,
        order_assumptions,
        capabilities,
        policies,
    )
    ordered_capabilities = tuple(sorted(capabilities, key=lambda value: value.value))
    ordered_policies = tuple(sorted(policies, key=lambda value: value.area.value))
    document = _execution_plan_document(
        price_assumption,
        timeline,
        order_assumptions,
        ordered_capabilities,
        ordered_policies,
    )
    canonical_bytes = canonicalize_json(document)
    plan = ExecutionAssumptionPlan(
        price_assumption,
        timeline,
        order_assumptions,
        ordered_capabilities,
        ordered_policies,
        canonical_bytes,
        sha256_bytes(canonical_bytes),
    )
    plan.verify()
    return plan


@dataclass(frozen=True, slots=True)
class RandomnessDeclaration:
    mode: RandomnessMode
    seeds: tuple[int, ...] = ()
    rationale: str | None = None

    def __post_init__(self) -> None:
        _enum(self.mode, RandomnessMode, "randomness mode")
        if not isinstance(self.seeds, tuple) or any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise SimulationContractError("Seeds must be nonnegative integers")
        if len(set(self.seeds)) != len(self.seeds):
            raise SimulationContractError("Seeds must not contain duplicates")
        if self.mode is RandomnessMode.DETERMINISTIC_SEEDED:
            if not self.seeds:
                raise SimulationContractError("Seeded simulation requires a seed")
            if self.rationale is not None:
                _nonempty(self.rationale, "randomness rationale")
        elif self.seeds:
            raise SimulationContractError("Unseeded mode cannot contain seeds")
        else:
            _nonempty(self.rationale, "randomness rationale")

    def document(self) -> JsonRecord:
        seed_values: list[JsonValue] = list(self.seeds)
        return {
            "mode": self.mode.value,
            "seeds": seed_values,
            "rationale": self.rationale,
        }


def _data_manifests(
    values: object,
) -> tuple[DataManifestReference, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, DataManifestReference) for value in values
    ):
        raise SimulationContractError("Data-manifest references must be typed")
    if not values:
        raise SimulationContractError("Data-manifest references must not be empty")
    pairs: list[tuple[str, str]] = []
    for value in values:
        _nonempty(value.reference, "data-manifest reference")
        reject_credential_uri(value.reference)
        require_sha256_digest(value.digest)
        pairs.append((value.reference, value.digest))
    if len(set(pairs)) != len(pairs):
        raise SimulationContractError("Data-manifest references must be unique")
    return values


def _validate_input(
    experiment_id: object,
    temporal_plan_digest: object,
    evidence_plan_digest: object,
    data_manifests: tuple[DataManifestReference, ...],
    code_revision: object,
    configuration_digest: object,
    environment_digest: object,
    candidate_reference: object,
    partition_role: object,
    execution_plan: object,
    cost_plan: object,
    randomness: object,
    sealed_release_reference: object,
) -> None:
    if not isinstance(experiment_id, str):
        raise SimulationContractError("Experiment identity must be a string")
    validate_typed_id(experiment_id, RegistryKind.EXPERIMENT)
    for digest, field in (
        (temporal_plan_digest, "temporal-validation plan digest"),
        (evidence_plan_digest, "scientific-evidence plan digest"),
        (configuration_digest, "configuration digest"),
        (environment_digest, "environment digest"),
    ):
        if not isinstance(digest, str):
            raise SimulationContractError(f"{field} must be a SHA-256 digest")
        require_sha256_digest(digest)
    _data_manifests(data_manifests)
    if (
        not isinstance(code_revision, str)
        or _GIT_REVISION.fullmatch(code_revision) is None
    ):
        raise SimulationContractError(
            "Code revision must be 40 lowercase hexadecimal characters"
        )
    _nonempty(candidate_reference, "candidate reference")
    if not isinstance(partition_role, PartitionRole):
        raise SimulationContractError("Partition role must be governed")
    if not isinstance(execution_plan, ExecutionAssumptionPlan):
        raise SimulationContractError("Execution plan must be typed")
    if not isinstance(cost_plan, TransactionCostPlan):
        raise SimulationContractError("Cost plan must be typed")
    execution_plan.verify()
    cost_plan.verify()
    if not isinstance(randomness, RandomnessDeclaration):
        raise SimulationContractError("Randomness declaration must be typed")
    if partition_role is PartitionRole.SEALED_OUT_OF_SAMPLE:
        _nonempty(sealed_release_reference, "sealed release evidence reference")
    elif sealed_release_reference is not None:
        raise SimulationContractError(
            "Only sealed-OOS input may declare release evidence"
        )


def _input_document(
    experiment_id: str,
    temporal_plan_digest: str,
    evidence_plan_digest: str,
    data_manifests: tuple[DataManifestReference, ...],
    code_revision: str,
    configuration_digest: str,
    environment_digest: str,
    candidate_reference: str,
    partition_role: PartitionRole,
    execution_plan: ExecutionAssumptionPlan,
    cost_plan: TransactionCostPlan,
    randomness: RandomnessDeclaration,
    sealed_release_reference: str | None,
) -> JsonRecord:
    manifests: list[JsonValue] = [
        {"reference": value.reference, "digest": value.digest}
        for value in data_manifests
    ]
    return {
        "schema_version": "1.0.0",
        "input_type": "SIMULATION_INPUT",
        "experiment_id": experiment_id,
        "temporal_validation_plan_digest": temporal_plan_digest,
        "scientific_evidence_plan_digest": evidence_plan_digest,
        "data_manifests": manifests,
        "code_revision": code_revision,
        "configuration_digest": configuration_digest,
        "environment_digest": environment_digest,
        "candidate_reference": candidate_reference,
        "partition_role": partition_role.value,
        "execution_assumption_plan_digest": execution_plan.digest,
        "transaction_cost_plan_digest": cost_plan.digest,
        "randomness": randomness.document(),
        "sealed_release_evidence_reference": sealed_release_reference,
        "item_10_authorization_verified": False,
        "input_consumption_verified": False,
        "execution_authorized": False,
    }


@dataclass(frozen=True, slots=True)
class SimulationInput:
    experiment_id: str
    temporal_validation_plan_digest: str
    scientific_evidence_plan_digest: str
    data_manifests: tuple[DataManifestReference, ...]
    code_revision: str
    configuration_digest: str
    environment_digest: str
    candidate_reference: str
    partition_role: PartitionRole
    execution_plan: ExecutionAssumptionPlan
    cost_plan: TransactionCostPlan
    randomness: RandomnessDeclaration
    sealed_release_evidence_reference: str | None
    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise SimulationIntegrityError("Simulation input is not a JSON object")
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)
        _validate_input(
            self.experiment_id,
            self.temporal_validation_plan_digest,
            self.scientific_evidence_plan_digest,
            self.data_manifests,
            self.code_revision,
            self.configuration_digest,
            self.environment_digest,
            self.candidate_reference,
            self.partition_role,
            self.execution_plan,
            self.cost_plan,
            self.randomness,
            self.sealed_release_evidence_reference,
        )
        expected = _input_document(
            self.experiment_id,
            self.temporal_validation_plan_digest,
            self.scientific_evidence_plan_digest,
            self.data_manifests,
            self.code_revision,
            self.configuration_digest,
            self.environment_digest,
            self.candidate_reference,
            self.partition_role,
            self.execution_plan,
            self.cost_plan,
            self.randomness,
            self.sealed_release_evidence_reference,
        )
        if canonicalize_json(expected) != self.canonical_bytes:
            raise SimulationIntegrityError("Simulation input differs from typed fields")


def build_simulation_input(
    *,
    experiment_id: str,
    temporal_validation_plan_digest: str,
    scientific_evidence_plan_digest: str,
    data_manifests: Sequence[DataManifestReference],
    code_revision: str,
    configuration_digest: str,
    environment_digest: str,
    candidate_reference: str,
    partition_role: PartitionRole,
    execution_plan: ExecutionAssumptionPlan,
    cost_plan: TransactionCostPlan,
    randomness: RandomnessDeclaration,
    sealed_release_evidence_reference: str | None = None,
) -> SimulationInput:
    manifests = tuple(data_manifests)
    _validate_input(
        experiment_id,
        temporal_validation_plan_digest,
        scientific_evidence_plan_digest,
        manifests,
        code_revision,
        configuration_digest,
        environment_digest,
        candidate_reference,
        partition_role,
        execution_plan,
        cost_plan,
        randomness,
        sealed_release_evidence_reference,
    )
    ordered_manifests = tuple(
        sorted(manifests, key=lambda value: (value.reference, value.digest))
    )
    document = _input_document(
        experiment_id,
        temporal_validation_plan_digest,
        scientific_evidence_plan_digest,
        ordered_manifests,
        code_revision,
        configuration_digest,
        environment_digest,
        candidate_reference,
        partition_role,
        execution_plan,
        cost_plan,
        randomness,
        sealed_release_evidence_reference,
    )
    canonical_bytes = canonicalize_json(document)
    result = SimulationInput(
        experiment_id,
        temporal_validation_plan_digest,
        scientific_evidence_plan_digest,
        ordered_manifests,
        code_revision,
        configuration_digest,
        environment_digest,
        candidate_reference,
        partition_role,
        execution_plan,
        cost_plan,
        randomness,
        sealed_release_evidence_reference,
        canonical_bytes,
        sha256_bytes(canonical_bytes),
    )
    result.verify()
    return result


@dataclass(frozen=True, slots=True)
class SimulationOutputEvidence:
    category: OutputEvidenceCategory
    disposition: OutputEvidenceDisposition
    rationale: str
    artifact: ClaimedArtifact | None = None

    def __post_init__(self) -> None:
        _enum(self.category, OutputEvidenceCategory, "output evidence category")
        _enum(self.disposition, OutputEvidenceDisposition, "output disposition")
        _nonempty(self.rationale, "output evidence rationale")
        if self.disposition is OutputEvidenceDisposition.PRODUCED:
            if not isinstance(self.artifact, ClaimedArtifact):
                raise SimulationContractError(
                    "Produced output evidence requires an artifact claim"
                )
        elif self.artifact is not None:
            raise SimulationContractError(
                "Unproduced output evidence cannot claim an artifact"
            )

    def document(self) -> JsonRecord:
        return {
            "category": self.category.value,
            "disposition": self.disposition.value,
            "rationale": self.rationale,
            "artifact": self.artifact.document() if self.artifact else None,
        }


def _output_evidence(
    values: object,
) -> tuple[SimulationOutputEvidence, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, SimulationOutputEvidence) for value in values
    ):
        raise SimulationContractError("Simulation output evidence must be typed")
    categories = tuple(value.category for value in values)
    if len(categories) != len(set(categories)) or set(categories) != set(
        OutputEvidenceCategory
    ):
        raise SimulationContractError(
            "Every output evidence category must remain explicitly separable"
        )
    return values


def _validate_output(
    simulation_input: object,
    outcome: object,
    evidence: tuple[SimulationOutputEvidence, ...],
    warnings: tuple[str, ...],
    limitations: tuple[str, ...],
    failures: tuple[str, ...],
) -> None:
    if not isinstance(simulation_input, SimulationInput):
        raise SimulationContractError("Simulation output requires a typed input")
    simulation_input.verify()
    if not isinstance(outcome, EvidenceOutcome):
        raise SimulationContractError("Simulation outcome must use evidence vocabulary")
    _output_evidence(evidence)
    has_pending = any(
        value.disposition is OutputEvidenceDisposition.PENDING for value in evidence
    )
    has_failed = any(
        value.disposition is OutputEvidenceDisposition.FAILED for value in evidence
    )
    if has_pending and outcome is not EvidenceOutcome.PENDING:
        raise SimulationContractError(
            "PENDING output evidence requires a PENDING report outcome"
        )
    if outcome is EvidenceOutcome.PENDING and not has_pending:
        raise SimulationContractError(
            "A PENDING report outcome requires pending output evidence"
        )
    if has_failed and outcome is not EvidenceOutcome.FAILED:
        raise SimulationContractError(
            "FAILED output evidence requires a FAILED report outcome"
        )
    if outcome is EvidenceOutcome.FAILED and has_pending:
        raise SimulationContractError(
            "A FAILED report outcome cannot retain PENDING output evidence"
        )
    _strings(warnings, "simulation warning")
    _strings(limitations, "simulation limitation")
    _strings(failures, "simulation failure", required=outcome is EvidenceOutcome.FAILED)


def _output_document(
    simulation_input: SimulationInput,
    outcome: EvidenceOutcome,
    evidence: tuple[SimulationOutputEvidence, ...],
    warnings: tuple[str, ...],
    limitations: tuple[str, ...],
    failures: tuple[str, ...],
) -> JsonRecord:
    evidence_values: list[JsonValue] = [value.document() for value in evidence]
    return {
        "schema_version": "1.0.0",
        "output_type": "SIMULATION_OUTPUT_EVIDENCE",
        "simulation_input_digest": simulation_input.digest,
        "experiment_id": simulation_input.experiment_id,
        "outcome": outcome.value,
        "evidence": evidence_values,
        "warnings": list(warnings),
        "limitations": list(limitations),
        "failures": list(failures),
        "artifact_claims_cryptographically_verified": False,
        "decision_authority": ITEM_8_DECISION_AUTHORITY,
        "v6_assessment_mutated": False,
    }


@dataclass(frozen=True, slots=True)
class SimulationOutput:
    simulation_input: SimulationInput
    outcome: EvidenceOutcome
    evidence: tuple[SimulationOutputEvidence, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    failures: tuple[str, ...]
    canonical_bytes: bytes
    digest: str

    @property
    def document(self) -> JsonRecord:
        value = parse_json_document(self.canonical_bytes)
        if not isinstance(value, dict):
            raise SimulationIntegrityError("Simulation output is not a JSON object")
        return value

    def verify(self) -> None:
        verify_sha256_bytes(self.canonical_bytes, self.digest)
        _validate_output(
            self.simulation_input,
            self.outcome,
            self.evidence,
            self.warnings,
            self.limitations,
            self.failures,
        )
        expected = _output_document(
            self.simulation_input,
            self.outcome,
            self.evidence,
            self.warnings,
            self.limitations,
            self.failures,
        )
        if canonicalize_json(expected) != self.canonical_bytes:
            raise SimulationIntegrityError(
                "Simulation output differs from typed fields"
            )


def build_simulation_output(
    *,
    simulation_input: SimulationInput,
    outcome: EvidenceOutcome,
    evidence: Sequence[SimulationOutputEvidence],
    warnings: Sequence[str] = (),
    limitations: Sequence[str] = (),
    failures: Sequence[str] = (),
) -> SimulationOutput:
    evidence_values = tuple(evidence)
    warning_values = tuple(sorted(tuple(warnings)))
    limitation_values = tuple(sorted(tuple(limitations)))
    failure_values = tuple(sorted(tuple(failures)))
    _validate_output(
        simulation_input,
        outcome,
        evidence_values,
        warning_values,
        limitation_values,
        failure_values,
    )
    ordered_evidence = tuple(
        sorted(evidence_values, key=lambda value: value.category.value)
    )
    document = _output_document(
        simulation_input,
        outcome,
        ordered_evidence,
        warning_values,
        limitation_values,
        failure_values,
    )
    canonical_bytes = canonicalize_json(document)
    result = SimulationOutput(
        simulation_input,
        outcome,
        ordered_evidence,
        warning_values,
        limitation_values,
        failure_values,
        canonical_bytes,
        sha256_bytes(canonical_bytes),
    )
    result.verify()
    return result
