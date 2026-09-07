"""Synthetic hostile tests for Item 9C metadata-only simulation contracts."""

from __future__ import annotations

import builtins
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from item9_test_support import (
    FROZEN_DIGEST,
    OTHER_EXPERIMENT_ID,
    OTHER_FROZEN_DIGEST,
    frozen_record,
    multiple_testing_binding,
    scientific_evidence_plan,
    temporal_binding,
    validation_plan,
)

import quant_hunter.backtesting as backtesting
from quant_hunter.backtesting import (
    AssumptionBasis,
    AssumptionSupport,
    ClaimedArtifact,
    CostComponent,
    CostComponentDeclaration,
    DataCapability,
    DurationUnit,
    ExactDuration,
    ExactQuantity,
    ExecutionAssumptionPlan,
    ExecutionTimeline,
    LatencyAssumption,
    LatencyKind,
    MarketPolicyArea,
    MarketPolicyDeclaration,
    OrderAssumptions,
    OrderSide,
    OrderType,
    OutputEvidenceCategory,
    OutputEvidenceDisposition,
    PartialFillPolicy,
    PriceAssumption,
    PriceQuality,
    PriceSource,
    QueueRealismDeclaration,
    RandomnessDeclaration,
    RandomnessMode,
    RealismLevel,
    SidePriceRule,
    SimulationContractError,
    SimulationInput,
    SimulationIntegrityError,
    SimulationOutputEvidence,
    TimeInForce,
    TransactionCostPlan,
    build_execution_assumption_plan,
    build_simulation_input,
    build_simulation_output,
    build_transaction_cost_plan,
)
from quant_hunter.config import JsonRecord
from quant_hunter.provenance import DataManifestReference
from quant_hunter.provenance.hashing import DigestMismatchError
from quant_hunter.validation import (
    Applicability,
    EvidenceOutcome,
    FrozenTemporalValidationBinding,
    PartitionRole,
    ScientificEvidenceError,
    ScientificEvidencePlan,
    TemporalValidationError,
    ValidationPlan,
)

EXPERIMENT_ID = "EXP-01990f30-7f5e-7b34-9b21-3d74c513c848"
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
CODE_REVISION = "d" * 40


def assumed() -> AssumptionSupport:
    return AssumptionSupport(AssumptionBasis.ASSUMED)


def latency_declarations() -> tuple[LatencyAssumption, ...]:
    return tuple(
        LatencyAssumption(
            declaration_id=f"latency-{kind.value.lower().replace('_', '-')}",
            kind=kind,
            applicability=Applicability.REQUIRED,
            rationale="Synthetic latency is explicitly assumed.",
            duration=ExactDuration("0.005", DurationUnit.SECONDS),
            support=assumed(),
        )
        for kind in LatencyKind
    )


def market_policies() -> tuple[MarketPolicyDeclaration, ...]:
    return tuple(
        MarketPolicyDeclaration(
            declaration_id=f"policy-{area.value.lower().replace('_', '-')}",
            area=area,
            applicability=Applicability.REQUIRED,
            rationale="The future executor must apply this synthetic policy.",
            policy=f"Synthetic {area.value.lower()} handling protocol.",
            support=assumed(),
        )
        for area in MarketPolicyArea
    )


def cost_declarations() -> tuple[CostComponentDeclaration, ...]:
    return tuple(
        CostComponentDeclaration(
            declaration_id=f"cost-{component.value.lower().replace('_', '-')}",
            component=component,
            applicability=Applicability.REQUIRED,
            rationale="This cost treatment is explicitly configured.",
            protocol=f"Synthetic {component.value.lower()} protocol reference.",
            value=(
                ExactQuantity(
                    "0.0001",
                    "decimal rate",
                    "notional rate",
                    sign_convention="positive value is a cost",
                )
                if component is CostComponent.SPREAD
                else None
            ),
            support=assumed(),
        )
        for component in CostComponent
    )


def cost_plan() -> TransactionCostPlan:
    return build_transaction_cost_plan(cost_declarations())


def order_assumptions(
    queue: QueueRealismDeclaration | None = None,
) -> OrderAssumptions:
    return OrderAssumptions(
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        cancellation_behavior="Cancel at the registered expiry condition.",
        partial_fill_policy=PartialFillPolicy.ALLOW,
        partial_fill_rationale="Partial fills remain relevant and explicitly allowed.",
        fill_priority_assumption="No exact queue position is claimed.",
        marketability_assumption="Limit crossing is governed by future data.",
        capacity_liquidity_limitation="Future executor must enforce registered capacity.",
        order_expiry_behavior="Expire at the declared session boundary.",
        queue_realism=queue
        or QueueRealismDeclaration(
            Applicability.NOT_APPLICABLE,
            "This BAR/OHLC study does not claim queue-position realism.",
        ),
        representative_quantity=ExactQuantity("10", "units", "order quantity"),
        representative_notional=ExactQuantity(
            "1000", "currency units", "order notional", currency="USD"
        ),
    )


def execution_plan(
    *,
    latencies: tuple[LatencyAssumption, ...] | None = None,
    policies: tuple[MarketPolicyDeclaration, ...] | None = None,
    capabilities: tuple[DataCapability, ...] = (DataCapability.BAR_OHLC,),
    orders: OrderAssumptions | None = None,
    price: PriceAssumption | None = None,
) -> ExecutionAssumptionPlan:
    return build_execution_assumption_plan(
        price_assumption=price
        or PriceAssumption(
            PriceSource.BID,
            PriceQuality.EXECUTABLE,
            RealismLevel.REALISTICALLY_MODELED,
            assumed(),
            "Executable bid use remains an explicit synthetic assumption.",
            ExactQuantity("1.2345", "USD per unit", "reference price", "USD"),
            (
                SidePriceRule(
                    OrderSide.BUY,
                    PriceSource.ASK,
                    "An immediately executable BUY uses the ask.",
                ),
                SidePriceRule(
                    OrderSide.SELL,
                    PriceSource.BID,
                    "An immediately executable SELL uses the bid.",
                ),
            ),
        ),
        timeline=ExecutionTimeline(
            "Use only information available at the registered event time.",
            "Decision follows information availability.",
            "Submission eligibility follows every declared latency.",
            latencies or latency_declarations(),
        ),
        order_assumptions=orders or order_assumptions(),
        data_capabilities=capabilities,
        market_policies=policies or market_policies(),
    )


def simulation_input(
    *,
    partition_role: PartitionRole = PartitionRole.VALIDATION,
    release_reference: str | None = None,
    manifests: tuple[DataManifestReference, ...] | None = None,
    experiment_id: str = EXPERIMENT_ID,
    temporal_plan: ValidationPlan | None = None,
    evidence_plan: ScientificEvidencePlan | None = None,
) -> SimulationInput:
    return build_simulation_input(
        experiment_id=experiment_id,
        temporal_validation_plan=temporal_plan or validation_plan(),
        scientific_evidence_plan=evidence_plan or scientific_evidence_plan(),
        data_manifests=manifests
        or (
            DataManifestReference("manifest://synthetic/a", DIGEST_A),
            DataManifestReference("manifest://synthetic/b", DIGEST_B),
        ),
        code_revision=CODE_REVISION,
        configuration_digest=DIGEST_C,
        environment_digest=DIGEST_A,
        candidate_reference="candidate://synthetic/no-object-created",
        partition_role=partition_role,
        execution_plan=execution_plan(),
        cost_plan=cost_plan(),
        randomness=RandomnessDeclaration(
            RandomnessMode.DETERMINISTIC_NO_RANDOMNESS,
            rationale="The metadata-only fixture uses no randomness.",
        ),
        sealed_release_evidence_reference=release_reference,
    )


def output_evidence() -> tuple[SimulationOutputEvidence, ...]:
    return tuple(
        SimulationOutputEvidence(
            category,
            OutputEvidenceDisposition.PRODUCED,
            "Synthetic future-executor evidence claim.",
            ClaimedArtifact(f"artifact://synthetic/{category.value.lower()}", DIGEST_C),
        )
        for category in OutputEvidenceCategory
    )


def test_complete_execution_and_simulation_contracts_are_deterministic() -> None:
    first_execution = execution_plan()
    second_execution = execution_plan()
    first_cost = cost_plan()
    second_cost = cost_plan()
    first_input = simulation_input()
    second_input = simulation_input()

    first_execution.verify()
    first_cost.verify()
    first_input.verify()
    assert first_execution == second_execution
    assert first_cost == second_cost
    assert first_input == second_input


def test_unordered_declaration_permutations_preserve_canonical_identity() -> None:
    normal_cost = cost_plan()
    reversed_cost = build_transaction_cost_plan(tuple(reversed(cost_declarations())))
    normal_execution = execution_plan()
    reversed_execution = execution_plan(
        latencies=tuple(reversed(latency_declarations())),
        policies=tuple(reversed(market_policies())),
    )

    assert normal_cost.digest == reversed_cost.digest
    assert normal_execution.digest == reversed_execution.digest


def test_duplicate_declaration_identities_fail() -> None:
    costs = list(cost_declarations())
    costs[1] = replace(costs[1], declaration_id=costs[0].declaration_id)
    with pytest.raises(SimulationContractError, match="identities must be unique"):
        build_transaction_cost_plan(costs)

    policies = list(market_policies())
    policies[1] = replace(policies[1], declaration_id=policies[0].declaration_id)
    with pytest.raises(SimulationContractError, match="identities must be unique"):
        execution_plan(policies=tuple(policies))


def test_missing_cost_component_cannot_silently_mean_zero() -> None:
    with pytest.raises(SimulationContractError, match="missing is not zero"):
        build_transaction_cost_plan(cost_declarations()[:-1])


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CostComponentDeclaration(
            "cost-spread", CostComponent.SPREAD, Applicability.NOT_APPLICABLE, " "
        ),
        lambda: MarketPolicyDeclaration(
            "policy-holiday",
            MarketPolicyArea.HOLIDAYS,
            Applicability.NOT_APPLICABLE,
            " ",
        ),
        lambda: LatencyAssumption(
            "latency-vendor",
            LatencyKind.DATA_VENDOR,
            Applicability.NOT_APPLICABLE,
            " ",
        ),
    ],
)
def test_not_applicable_requires_scientific_rationale(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(SimulationContractError, match="nonempty"):
        factory()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ExactQuantity(cast(str, 1.2), "USD", "price"),
        lambda: ExactQuantity(cast(str, 10.0), "units", "quantity"),
        lambda: ExactQuantity(cast(str, 1000.0), "USD", "notional", "USD"),
        lambda: ExactQuantity(cast(str, 0.001), "decimal rate", "cost rate"),
        lambda: ExactDuration(cast(str, 0.5), DurationUnit.SECONDS),
    ],
)
def test_binary_float_scientific_quantities_are_rejected(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(ValueError, match="normalized exact decimal"):
        factory()


def test_negative_latency_is_rejected() -> None:
    with pytest.raises(SimulationContractError, match="must not be negative"):
        ExactDuration("-0.001", DurationUnit.SECONDS)


def test_latency_unit_cannot_silently_infer_bar_frequency() -> None:
    with pytest.raises(SimulationContractError, match="duration unit"):
        ExactDuration("1", cast(DurationUnit, "BARS"))


@pytest.mark.parametrize(
    ("quality", "realism"),
    [
        (PriceQuality.EXECUTABLE, RealismLevel.IDEALIZED),
        (PriceQuality.INDICATIVE, RealismLevel.REALISTICALLY_MODELED),
    ],
)
def test_midpoint_cannot_claim_executable_price_realism(
    quality: PriceQuality, realism: RealismLevel
) -> None:
    with pytest.raises(SimulationContractError, match="MIDPOINT"):
        PriceAssumption(
            PriceSource.MIDPOINT,
            quality,
            realism,
            assumed(),
            "Midpoint is idealized.",
        )


def test_indicative_price_cannot_claim_realistically_modeled() -> None:
    with pytest.raises(SimulationContractError, match="INDICATIVE"):
        PriceAssumption(
            PriceSource.LAST_TRADE,
            PriceQuality.INDICATIVE,
            RealismLevel.REALISTICALLY_MODELED,
            assumed(),
            "Last trade is not necessarily executable.",
        )


def test_standard_side_aware_market_pricing_maps_buy_ask_sell_bid() -> None:
    orders = replace(order_assumptions(), order_type=OrderType.MARKET)
    plan = execution_plan(orders=orders)
    price = plan.price_assumption
    mapping = {value.side: value.source for value in price.side_price_rules}

    assert mapping == {
        OrderSide.BUY: PriceSource.ASK,
        OrderSide.SELL: PriceSource.BID,
    }


def side_price_assumption(
    buy_source: PriceSource,
    sell_source: PriceSource,
) -> PriceAssumption:
    return replace(
        execution_plan().price_assumption,
        side_price_rules=(
            SidePriceRule(
                OrderSide.BUY,
                buy_source,
                "The BUY-side rule is explicit for this synthetic study.",
            ),
            SidePriceRule(
                OrderSide.SELL,
                sell_source,
                "The SELL-side rule is explicit for this synthetic study.",
            ),
        ),
    )


def test_market_executable_rejects_reversed_side_mapping() -> None:
    with pytest.raises(SimulationContractError, match="BUY to ASK and SELL to BID"):
        execution_plan(
            price=side_price_assumption(PriceSource.BID, PriceSource.ASK),
            orders=replace(order_assumptions(), order_type=OrderType.MARKET),
        )


@pytest.mark.parametrize(
    ("buy_source", "sell_source"),
    [
        (PriceSource.BID, PriceSource.BID),
        (PriceSource.ASK, PriceSource.ASK),
    ],
)
def test_market_executable_rejects_each_wrong_side_even_with_rationale(
    buy_source: PriceSource,
    sell_source: PriceSource,
) -> None:
    with pytest.raises(SimulationContractError, match="BUY to ASK and SELL to BID"):
        execution_plan(
            price=side_price_assumption(buy_source, sell_source),
            orders=replace(order_assumptions(), order_type=OrderType.MARKET),
        )


@pytest.mark.parametrize("side", [OrderSide.BUY, OrderSide.SELL])
def test_market_executable_rejects_last_trade_as_side_quote(side: OrderSide) -> None:
    buy_source = PriceSource.LAST_TRADE if side is OrderSide.BUY else PriceSource.ASK
    sell_source = PriceSource.LAST_TRADE if side is OrderSide.SELL else PriceSource.BID
    with pytest.raises(SimulationContractError, match="LAST_TRADE"):
        execution_plan(
            price=side_price_assumption(buy_source, sell_source),
            orders=replace(order_assumptions(), order_type=OrderType.MARKET),
        )


def test_limit_study_can_retain_explicit_alternate_side_semantics() -> None:
    plan = execution_plan(
        price=side_price_assumption(PriceSource.BID, PriceSource.ASK),
        orders=order_assumptions(),
    )

    assert plan.order_assumptions.order_type is OrderType.LIMIT
    assert all(value.rationale for value in plan.price_assumption.side_price_rules)


def test_side_rule_permutation_preserves_canonical_identity() -> None:
    normal = execution_plan()
    permuted_price = replace(
        normal.price_assumption,
        side_price_rules=tuple(reversed(normal.price_assumption.side_price_rules)),
    )
    permuted = execution_plan(price=permuted_price)

    assert normal.canonical_bytes == permuted.canonical_bytes
    assert normal.digest == permuted.digest


def test_canonical_price_document_has_one_execution_authority() -> None:
    document = execution_plan().price_assumption.document()

    assert "source" not in document
    assert document["reference_source_is_execution_authority"] is False
    assert document["execution_price_authority"] == "SIDE_PRICE_RULES"


@pytest.mark.parametrize("source", [PriceSource.BID, PriceSource.ASK])
def test_global_one_sided_price_cannot_masquerade_as_executable_policy(
    source: PriceSource,
) -> None:
    with pytest.raises(SimulationContractError, match="BUY and SELL"):
        PriceAssumption(
            source,
            PriceQuality.EXECUTABLE,
            RealismLevel.REALISTICALLY_MODELED,
            assumed(),
            "A global source alone is not a two-sided policy.",
        )


def test_other_price_source_requires_explicit_description() -> None:
    with pytest.raises(SimulationContractError, match="custom reference price source"):
        PriceAssumption(
            PriceSource.OTHER,
            PriceQuality.INDICATIVE,
            RealismLevel.IDEALIZED,
            assumed(),
            "A custom source must be defined.",
        )
    with pytest.raises(SimulationContractError, match="custom side price source"):
        SidePriceRule(
            OrderSide.BUY,
            PriceSource.OTHER,
            "A custom resting-order source is required.",
        )


@pytest.mark.parametrize(
    ("order_type", "time_in_force", "match"),
    [
        (OrderType.OTHER, TimeInForce.DAY, "custom order type"),
        (OrderType.LIMIT, TimeInForce.OTHER, "custom time in force"),
    ],
)
def test_other_order_vocabulary_requires_explicit_description(
    order_type: OrderType, time_in_force: TimeInForce, match: str
) -> None:
    with pytest.raises(SimulationContractError, match=match):
        replace(
            order_assumptions(),
            order_type=order_type,
            time_in_force=time_in_force,
        )


@pytest.mark.parametrize(
    "basis", [AssumptionBasis.MEASURED, AssumptionBasis.EMPIRICALLY_SUPPORTED]
)
def test_empirical_claim_requires_evidence_reference(basis: AssumptionBasis) -> None:
    with pytest.raises(SimulationContractError, match="require evidence"):
        AssumptionSupport(basis)


def test_assumed_value_cannot_masquerade_as_measured() -> None:
    with pytest.raises(SimulationContractError, match="ASSUMED"):
        AssumptionSupport(
            AssumptionBasis.ASSUMED,
            ClaimedArtifact("artifact://synthetic/latency-study", DIGEST_A),
        )
    measured = AssumptionSupport(
        AssumptionBasis.MEASURED,
        ClaimedArtifact("artifact://synthetic/latency-study", DIGEST_A),
    )
    assert measured.document()["basis"] == "MEASURED"


def test_queue_realism_fails_when_data_capability_is_bar_only() -> None:
    queue = QueueRealismDeclaration(
        Applicability.REQUIRED,
        "Exact priority is material to this synthetic study.",
        RealismLevel.REALISTICALLY_MODELED,
        DataCapability.FULL_DEPTH_WITH_QUEUE_EVENTS,
        assumed(),
    )
    with pytest.raises(SimulationContractError, match="exceeds"):
        execution_plan(orders=order_assumptions(queue))


def test_queue_realism_can_be_honestly_not_applicable() -> None:
    plan = execution_plan()
    queue = plan.order_assumptions.queue_realism

    assert queue.applicability is Applicability.NOT_APPLICABLE
    assert queue.rationale


def test_exact_queue_realism_accepts_explicitly_sufficient_capability() -> None:
    queue = QueueRealismDeclaration(
        Applicability.REQUIRED,
        "Synthetic full-depth event data is declared as required.",
        RealismLevel.REALISTICALLY_MODELED,
        DataCapability.FULL_DEPTH_WITH_QUEUE_EVENTS,
        assumed(),
    )
    plan = execution_plan(
        capabilities=(DataCapability.FULL_DEPTH_WITH_QUEUE_EVENTS,),
        orders=order_assumptions(queue),
    )

    assert plan.document["data_capabilities"] == ["FULL_DEPTH_WITH_QUEUE_EVENTS"]


def test_cost_inventory_is_explicit_and_pluggable_without_calculation() -> None:
    plan = cost_plan()
    components = {value.component for value in plan.components}

    assert components == set(CostComponent)
    assert all(
        value.applicability is Applicability.REQUIRED for value in plan.components
    )
    assert all(value.protocol for value in plan.components)
    assert plan.document["calculation_authorized"] is False


def test_configured_cost_value_requires_sign_convention() -> None:
    with pytest.raises(SimulationContractError, match="sign convention"):
        CostComponentDeclaration(
            "cost-commission",
            CostComponent.COMMISSION,
            Applicability.REQUIRED,
            "A synthetic commission value is configured.",
            "Per-order synthetic protocol.",
            ExactQuantity("1", "USD", "per order", currency="USD"),
            assumed(),
        )


def test_session_closure_and_gap_policies_cannot_disappear() -> None:
    with pytest.raises(SimulationContractError, match="Every session"):
        execution_plan(policies=market_policies()[:-1])

    plan = execution_plan()
    assert {value.area for value in plan.market_policies} == set(MarketPolicyArea)


def test_simulation_input_binds_exact_item_9a_and_item_9b_digests() -> None:
    simulation = simulation_input()

    assert simulation.document["temporal_validation_plan_digest"] == (
        simulation.temporal_validation_plan.digest
    )
    assert simulation.document["scientific_evidence_plan_digest"] == (
        simulation.scientific_evidence_plan.digest
    )
    assert simulation.document["execution_assumption_plan_digest"] == (
        simulation.execution_plan.digest
    )
    assert simulation.document["transaction_cost_plan_digest"] == (
        simulation.cost_plan.digest
    )


def test_input_manifest_permutation_preserves_equivalent_identity() -> None:
    manifests = (
        DataManifestReference("manifest://synthetic/a", DIGEST_A),
        DataManifestReference("manifest://synthetic/b", DIGEST_B),
    )
    normal = simulation_input(manifests=manifests)
    reversed_input = simulation_input(manifests=tuple(reversed(manifests)))

    assert normal.canonical_bytes == reversed_input.canonical_bytes
    assert normal.digest == reversed_input.digest


def test_typed_field_and_canonical_integrity_tampering_fails() -> None:
    execution = execution_plan()
    with pytest.raises(DigestMismatchError):
        replace(execution, digest=DIGEST_A).verify()
    with pytest.raises(DigestMismatchError):
        replace(execution, canonical_bytes=execution.canonical_bytes + b" ").verify()

    simulation = simulation_input()
    with pytest.raises(SimulationIntegrityError, match="Stored temporal digest"):
        replace(simulation, temporal_validation_plan_digest=DIGEST_C).verify()


def test_sealed_input_construction_and_verification_never_access_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = (tmp_path / "sealed" / "holdout.parquet").resolve()

    def reject_access(*args: object, **kwargs: object) -> object:
        raise AssertionError("Item 9C attempted sealed filesystem access")

    monkeypatch.setattr(builtins, "open", reject_access)
    monkeypatch.setattr(Path, "open", reject_access)
    monkeypatch.setattr(Path, "read_bytes", reject_access)
    monkeypatch.setattr(Path, "stat", reject_access)
    monkeypatch.setattr(Path, "iterdir", reject_access)
    monkeypatch.setattr(os, "stat", reject_access)
    monkeypatch.setattr(os, "listdir", reject_access)

    simulation = simulation_input(
        partition_role=PartitionRole.SEALED_OUT_OF_SAMPLE,
        release_reference=str(sealed),
        manifests=(DataManifestReference(str(sealed), DIGEST_A),),
    )
    simulation.verify()

    assert simulation.document["sealed_release_evidence_reference"] == str(sealed)
    assert simulation.document["item_10_authorization_verified"] is False


def test_sealed_input_requires_release_metadata_without_claiming_authorization() -> (
    None
):
    with pytest.raises(SimulationContractError, match="release evidence"):
        simulation_input(partition_role=PartitionRole.SEALED_OUT_OF_SAMPLE)

    simulation = simulation_input(
        partition_role=PartitionRole.SEALED_OUT_OF_SAMPLE,
        release_reference="release://synthetic/metadata-only",
    )
    assert simulation.document["item_10_authorization_verified"] is False
    assert simulation.document["input_consumption_verified"] is False


def test_simulation_output_retains_failures_warnings_and_limitations() -> None:
    result = build_simulation_output(
        simulation_input=simulation_input(),
        outcome=EvidenceOutcome.FAILED,
        evidence=output_evidence(),
        warnings=("Synthetic warning retained.",),
        limitations=("Synthetic limitation retained.",),
        failures=("Synthetic failure retained.",),
    )
    result.verify()

    assert result.document["warnings"] == ["Synthetic warning retained."]
    assert result.document["limitations"] == ["Synthetic limitation retained."]
    assert result.document["failures"] == ["Synthetic failure retained."]
    assert result.document["decision_authority"] == "ITEM_8_EXPERIMENT_LIFECYCLE"


@pytest.mark.parametrize(
    "outcome",
    [
        EvidenceOutcome.POSITIVE,
        EvidenceOutcome.NEGATIVE,
        EvidenceOutcome.NULL,
        EvidenceOutcome.INCONCLUSIVE,
    ],
)
def test_completed_output_rejects_pending_category(
    outcome: EvidenceOutcome,
) -> None:
    evidence = list(output_evidence())
    evidence[0] = replace(
        evidence[0],
        disposition=OutputEvidenceDisposition.PENDING,
        artifact=None,
    )

    with pytest.raises(SimulationContractError, match="PENDING report outcome"):
        build_simulation_output(
            simulation_input=simulation_input(),
            outcome=outcome,
            evidence=evidence,
        )


def test_completed_output_rejects_failed_category() -> None:
    evidence = list(output_evidence())
    evidence[0] = replace(
        evidence[0],
        disposition=OutputEvidenceDisposition.FAILED,
        artifact=None,
    )

    with pytest.raises(SimulationContractError, match="FAILED report outcome"):
        build_simulation_output(
            simulation_input=simulation_input(),
            outcome=EvidenceOutcome.POSITIVE,
            evidence=evidence,
        )


def test_pending_output_requires_and_accepts_pending_category() -> None:
    with pytest.raises(SimulationContractError, match="requires pending"):
        build_simulation_output(
            simulation_input=simulation_input(),
            outcome=EvidenceOutcome.PENDING,
            evidence=output_evidence(),
        )

    evidence = list(output_evidence())
    evidence[0] = replace(
        evidence[0],
        disposition=OutputEvidenceDisposition.PENDING,
        artifact=None,
    )
    result = build_simulation_output(
        simulation_input=simulation_input(),
        outcome=EvidenceOutcome.PENDING,
        evidence=evidence,
    )
    assert result.document["outcome"] == "PENDING"


def test_failed_category_is_retained_with_failed_report_semantics() -> None:
    evidence = list(output_evidence())
    evidence[0] = replace(
        evidence[0],
        disposition=OutputEvidenceDisposition.FAILED,
        artifact=None,
    )
    result = build_simulation_output(
        simulation_input=simulation_input(),
        outcome=EvidenceOutcome.FAILED,
        evidence=evidence,
        failures=("Synthetic category failure retained.",),
    )

    assert any(
        value.disposition is OutputEvidenceDisposition.FAILED
        for value in result.evidence
    )


def test_not_applicable_output_category_remains_reasoned_and_completed() -> None:
    evidence = list(output_evidence())
    evidence[0] = SimulationOutputEvidence(
        evidence[0].category,
        OutputEvidenceDisposition.NOT_APPLICABLE,
        "Gross signal evidence is not applicable to this synthetic study.",
    )
    result = build_simulation_output(
        simulation_input=simulation_input(),
        outcome=EvidenceOutcome.INCONCLUSIVE,
        evidence=evidence,
    )

    assert any(
        value.disposition is OutputEvidenceDisposition.NOT_APPLICABLE
        for value in result.evidence
    )


@pytest.mark.parametrize(
    "outcome",
    [EvidenceOutcome.NEGATIVE, EvidenceOutcome.NULL, EvidenceOutcome.INCONCLUSIVE],
)
def test_nonpositive_completed_outputs_remain_representable(
    outcome: EvidenceOutcome,
) -> None:
    result = build_simulation_output(
        simulation_input=simulation_input(),
        outcome=outcome,
        evidence=output_evidence(),
    )

    assert result.outcome is outcome


@pytest.mark.parametrize(
    "policy", [PartialFillPolicy.REQUIRE_FULL_FILL, PartialFillPolicy.NOT_APPLICABLE]
)
def test_partial_fill_suppression_requires_rationale(
    policy: PartialFillPolicy,
) -> None:
    with pytest.raises(SimulationContractError, match="partial-fill rationale"):
        replace(
            order_assumptions(),
            partial_fill_policy=policy,
            partial_fill_rationale=" ",
        )


def test_output_evidence_categories_remain_explicitly_separable() -> None:
    result = build_simulation_output(
        simulation_input=simulation_input(),
        outcome=EvidenceOutcome.INCONCLUSIVE,
        evidence=tuple(reversed(output_evidence())),
        limitations=("Synthetic evidence is not an experiment decision.",),
    )
    categories = [value.category for value in result.evidence]

    assert set(categories) == set(OutputEvidenceCategory)
    assert categories == sorted(categories, key=lambda value: value.value)
    assert all(
        value.artifact is not None
        and value.artifact.document()["cryptographically_verified"] is False
        for value in result.evidence
    )


def test_output_missing_evidence_category_fails_closed() -> None:
    with pytest.raises(SimulationContractError, match="explicitly separable"):
        build_simulation_output(
            simulation_input=simulation_input(),
            outcome=EvidenceOutcome.INCONCLUSIVE,
            evidence=output_evidence()[:-1],
        )


def test_failed_output_requires_failure_evidence() -> None:
    with pytest.raises(SimulationContractError, match="must not be empty"):
        build_simulation_output(
            simulation_input=simulation_input(),
            outcome=EvidenceOutcome.FAILED,
            evidence=output_evidence(),
        )


def test_v6_and_execution_authority_boundaries_are_explicit() -> None:
    plan = execution_plan()
    result = build_simulation_output(
        simulation_input=simulation_input(),
        outcome=EvidenceOutcome.INCONCLUSIVE,
        evidence=output_evidence(),
    )

    assert plan.document["v6_claim_boundary"] == "ITEM_9B_V6_ASSESSMENT_REQUIRED"
    assert plan.document["execution_authorized"] is False
    assert result.document["v6_assessment_mutated"] is False


def test_no_execution_engine_or_broker_entry_point_exists() -> None:
    forbidden = {
        "run_backtest",
        "execute_strategy",
        "match_order",
        "generate_fill",
        "calculate_transaction_costs",
        "calculate_slippage",
        "connect_broker",
    }

    assert forbidden.isdisjoint(vars(backtesting))


@pytest.mark.parametrize(
    ("partition", "boundary", "changed_value"),
    [
        ("training", "end", "2020-01-09T00:00:00Z"),
        ("validation", "start", "2020-01-11T00:00:00Z"),
        ("sealed_out_of_sample", "end", "2020-01-29T00:00:00Z"),
    ],
)
def test_frozen_temporal_binding_rejects_each_partition_mismatch(
    partition: str,
    boundary: str,
    changed_value: str,
) -> None:
    record = frozen_record()
    partition_values = cast(JsonRecord, record["partitions"])
    interval_values = cast(JsonRecord, partition_values[partition])
    interval_values[boundary] = changed_value

    with pytest.raises(TemporalValidationError, match=partition):
        temporal_binding(record=record)


def test_frozen_temporal_binding_requires_complete_frozen_authority() -> None:
    nonfrozen = frozen_record()
    nonfrozen["lifecycle_status"] = "RUNNING"
    with pytest.raises(TemporalValidationError, match="requires FROZEN"):
        temporal_binding(record=nonfrozen)

    malformed_id = frozen_record()
    malformed_id["experiment_id"] = "EXP-not-a-uuid"
    with pytest.raises(ValueError, match="Malformed typed"):
        temporal_binding(record=malformed_id)

    incomplete = frozen_record()
    cast(JsonRecord, incomplete["partitions"]).pop("validation")
    with pytest.raises(TemporalValidationError, match="structurally incomplete"):
        temporal_binding(record=incomplete)

    with pytest.raises(ValueError, match="sha256"):
        temporal_binding(frozen_revision_digest="sha256:not-a-digest")


def test_frozen_temporal_binding_compares_exact_boundary_strings() -> None:
    record = frozen_record()
    partitions = cast(JsonRecord, record["partitions"])
    training = cast(JsonRecord, partitions["training"])
    training["start"] = "2020-01-01T00:00:00.0Z"

    with pytest.raises(TemporalValidationError, match="training"):
        temporal_binding(record=record)


def test_coherent_frozen_item9_chain_passes_and_retains_identities() -> None:
    record = frozen_record()
    temporal = temporal_binding(record=record)
    multiple = multiple_testing_binding(record=record)
    evidence = scientific_evidence_plan(
        temporal=temporal,
        multiple_testing=multiple,
    )
    simulation = simulation_input(
        temporal_plan=temporal.validation_plan,
        evidence_plan=evidence,
    )

    temporal.verify()
    evidence.verify()
    simulation.verify()
    assert temporal.experiment_id == EXPERIMENT_ID
    assert temporal.frozen_revision_digest == FROZEN_DIGEST
    assert temporal.temporal_validation_plan_digest == temporal.validation_plan.digest
    assert evidence.temporal_validation_plan_digest == temporal.validation_plan.digest
    assert simulation.temporal_validation_plan_digest == temporal.validation_plan.digest
    assert simulation.scientific_evidence_plan_digest == evidence.digest
    assert evidence.document["temporal_validation"] == temporal.document()
    assert temporal.document()["registry_chain_verified"] is False
    assert temporal.document()["sealed_reference_dereferenced"] is False
    assert simulation.document["input_consumption_verified"] is False


def test_evidence_rejects_temporal_and_multiple_testing_experiment_mismatch() -> None:
    other_record = frozen_record(experiment_id=OTHER_EXPERIMENT_ID)
    with pytest.raises(ScientificEvidenceError, match="multiple-testing binding"):
        scientific_evidence_plan(
            temporal=temporal_binding(),
            multiple_testing=multiple_testing_binding(record=other_record),
        )


def test_evidence_rejects_different_frozen_revision_bindings() -> None:
    with pytest.raises(ScientificEvidenceError, match="different frozen revisions"):
        scientific_evidence_plan(
            temporal=temporal_binding(frozen_revision_digest=FROZEN_DIGEST),
            multiple_testing=multiple_testing_binding(
                frozen_revision_digest=OTHER_FROZEN_DIGEST
            ),
        )


def test_evidence_cannot_accept_unbound_temporal_digest() -> None:
    with pytest.raises(ScientificEvidenceError, match="binding is required"):
        scientific_evidence_plan(
            temporal=cast(FrozenTemporalValidationBinding, DIGEST_C)
        )


def test_evidence_rejects_temporal_digest_tampering() -> None:
    evidence = scientific_evidence_plan()

    with pytest.raises(ScientificEvidenceError, match="temporal digest"):
        replace(evidence, temporal_validation_plan_digest=DIGEST_C).verify()


def test_simulation_rejects_evidence_for_another_experiment() -> None:
    other_record = frozen_record(experiment_id=OTHER_EXPERIMENT_ID)
    other_temporal = temporal_binding(record=other_record)
    other_evidence = scientific_evidence_plan(
        experiment_id=OTHER_EXPERIMENT_ID,
        temporal=other_temporal,
        multiple_testing=multiple_testing_binding(record=other_record),
    )

    with pytest.raises(SimulationContractError, match="Simulation experiment"):
        simulation_input(
            experiment_id=EXPERIMENT_ID,
            temporal_plan=other_temporal.validation_plan,
            evidence_plan=other_evidence,
        )


def test_simulation_rejects_evidence_bound_to_different_validation_plan() -> None:
    plan_b = validation_plan(sealed_reference="sealed://synthetic/other-holdout")
    temporal_b = temporal_binding(plan=plan_b)
    evidence_b = scientific_evidence_plan(temporal=temporal_b)

    with pytest.raises(SimulationContractError, match="different ValidationPlan"):
        simulation_input(
            temporal_plan=validation_plan(),
            evidence_plan=evidence_b,
        )


def test_nested_plan_digest_tampering_fails_simulation_verification() -> None:
    simulation = simulation_input()
    tampered_temporal = replace(
        simulation.temporal_validation_plan,
        digest=OTHER_FROZEN_DIGEST,
    )
    with pytest.raises(DigestMismatchError):
        replace(simulation, temporal_validation_plan=tampered_temporal).verify()

    tampered_evidence = replace(
        simulation.scientific_evidence_plan,
        digest=OTHER_FROZEN_DIGEST,
    )
    with pytest.raises(DigestMismatchError):
        replace(simulation, scientific_evidence_plan=tampered_evidence).verify()


def test_cross_bound_identity_is_deterministic_for_unordered_inputs() -> None:
    temporal = temporal_binding()
    multiple = multiple_testing_binding()
    normal_evidence = scientific_evidence_plan(
        temporal=temporal,
        multiple_testing=multiple,
    )
    permuted_evidence = scientific_evidence_plan(
        temporal=temporal,
        multiple_testing=multiple,
        reverse_unordered_inputs=True,
    )

    assert normal_evidence.canonical_bytes == permuted_evidence.canonical_bytes
    assert normal_evidence.digest == permuted_evidence.digest
    normal_input = simulation_input(
        temporal_plan=temporal.validation_plan,
        evidence_plan=normal_evidence,
    )
    permuted_input = simulation_input(
        temporal_plan=temporal.validation_plan,
        evidence_plan=permuted_evidence,
        manifests=tuple(reversed(normal_input.data_manifests)),
    )
    assert normal_input.canonical_bytes == permuted_input.canonical_bytes
    assert normal_input.digest == permuted_input.digest


def test_full_cross_binding_chain_never_accesses_sealed_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sealed_reference = str(tmp_path / "sealed" / "holdout.parquet")

    def reject_access(*args: object, **kwargs: object) -> object:
        raise AssertionError("Item 9 cross-binding attempted sealed filesystem access")

    monkeypatch.setattr(builtins, "open", reject_access)
    monkeypatch.setattr(Path, "open", reject_access)
    monkeypatch.setattr(Path, "read_bytes", reject_access)
    monkeypatch.setattr(Path, "stat", reject_access)
    monkeypatch.setattr(Path, "iterdir", reject_access)
    monkeypatch.setattr(os, "stat", reject_access)
    monkeypatch.setattr(os, "listdir", reject_access)

    temporal = temporal_binding(plan=validation_plan(sealed_reference=sealed_reference))
    evidence = scientific_evidence_plan(temporal=temporal)
    simulation = simulation_input(
        partition_role=PartitionRole.SEALED_OUT_OF_SAMPLE,
        release_reference=sealed_reference,
        temporal_plan=temporal.validation_plan,
        evidence_plan=evidence,
    )

    temporal.verify()
    evidence.verify()
    simulation.verify()
    assert simulation.document["item_10_authorization_verified"] is False
    assert simulation.document["input_consumption_verified"] is False


@pytest.mark.parametrize(
    ("temporal_plan", "evidence_plan", "message"),
    [
        (cast(ValidationPlan, object()), None, "ValidationPlan"),
        (None, cast(ScientificEvidencePlan, object()), "ScientificEvidencePlan"),
    ],
)
def test_simulation_requires_verified_item9_plan_objects(
    temporal_plan: ValidationPlan | None,
    evidence_plan: ScientificEvidencePlan | None,
    message: str,
) -> None:
    with pytest.raises(SimulationContractError, match=message):
        simulation_input(
            temporal_plan=temporal_plan,
            evidence_plan=evidence_plan,
        )
