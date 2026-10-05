"""Complete schema-governed records for synthetic software demonstrations."""

from __future__ import annotations

from copy import deepcopy

from quant_hunter.config import JsonRecord, JsonValue

LIMITATION = (
    "SYNTHETIC software demonstration only. No empirical profitability, "
    "confirmatory validation, real sealed data, or HOST_ENFORCED authority."
)
FAMILY_NAME = "V0 synthetic accounting demonstrations"
DOCUMENTATION = "https://github.com/welmarr/quant-hunter"


def pending(reason: str) -> JsonRecord:
    """Return a reason-bearing pending assertion, never observed evidence."""
    return {"status": "PENDING", "reason": reason}


def source_record(timestamp: str) -> JsonRecord:
    """Register only the application's explicitly synthetic source."""
    return {
        "schema_version": "1.0.0",
        "created_at": timestamp,
        "reviewed_at": timestamp,
        "status": "CANDIDATE",
        "provider": "Quant Hunter local synthetic fixture generator",
        "documentation_uri": DOCUMENTATION,
        "data_domain": "Synthetic accounting software fixtures",
        "granularity": "Explicit fixture observations; no provider coverage claim",
        "historical_depth": "Only the immutable supplied synthetic fixture",
        "realtime_availability": "HISTORICAL_ONLY",
        "latency_description": "Generated offline; no live feed or latency claim",
        "cost": {
            "class": "FREE",
            "currency": "USD",
            "monthly_cost": "0",
            "pricing_date": timestamp[:10],
        },
        "access": {
            "license": "Project-generated synthetic fixture; no external source",
            "api_restrictions": "No network provider is used",
            "redistribution_restrictions": "No third-party data is included",
            "retention_constraints": "Retain immutable generated evidence",
        },
        "time_semantics": {
            "event_time": "DERIVED",
            "publication_time": "NOT_APPLICABLE",
            "ingestion_time": "DERIVED",
            "revision_time": "NOT_APPLICABLE",
        },
        "price_nature": "INDICATIVE",
        "reliability": "Generated test observations; not market observations",
        "limitations": [LIMITATION],
        "owner": "local-lab",
    }


def research_record(
    *,
    timestamp: str,
    family_id: str,
    source_id: str,
    dataset_id: str,
    code_revision: str,
    name: str,
    configuration_digest: str,
    family: bool,
) -> JsonRecord:
    """Register a family or strategy before executing a variant."""
    return {
        "schema_version": "1.0.0",
        "created_at": timestamp,
        "object_type": "RESEARCH_FAMILY" if family else "STRATEGY",
        "status": "PROPOSED",
        "name": name,
        "hypothesis": "Deterministic fixture simulation obeys its accounting rules.",
        "rationale": "Exercise reproducible software, not estimate investment merit.",
        "source_citations": [DOCUMENTATION],
        "mathematical_definition": (
            "Cash plus marked position value equals equity; costs reduce cash. "
            "The fixed algorithm and parameters are bound by code and configuration."
        ),
        "inputs": ["immutable synthetic dataset", "frozen configuration"],
        "outputs": ["simulation accounting evidence"],
        "horizon": "Declared finite fixture interval",
        "sampling_frequency": "Declared synthetic fixture observations",
        "universe": "Project-generated synthetic fixtures only",
        "assumptions": [LIMITATION, "One fixed configuration per experiment"],
        "search_space": "One declared configuration; no adaptive parameter search",
        "parent_ids": [],
        "baseline_ids": [],
        "data_requirements": {
            "source_ids": [source_id],
            "dataset_ids": [dataset_id],
            "point_in_time_constraints": "Simulation must consume chronological data",
            "availability": "Immutable local fixture published before registration",
            "licensing": "Project-generated synthetic data",
            "expected_cost": "USD 0 incremental external service cost",
        },
        "owner": "local-lab",
        "academic_institutional_basis": "Software accounting identities only",
        "evidence_quality": "No empirical evidence",
        "independent_replication_evidence": "Not yet independently replicated",
        "fx_applicability": "Synthetic software checks only",
        "known_failures_or_decay": "Real-market applicability is untested",
        "distinctiveness": "One software demonstration in a shared evidence family",
        "validation_plan": "Deterministic replay and independent accounting oracles",
        "transaction_cost_sensitivity": "Costs are explicit in frozen configuration",
        "capacity_sensitivity": "No market capacity claim",
        "risk_sensitivity": "No investment risk validation claim",
        "regime_sensitivity": "No empirical regime claim",
        "decision": pending("Await human review; no automated scientific decision"),
        "limitations": LIMITATION,
        "failure_modes": "Simulation, validation or persistence errors are retained",
        "parameters": configuration_digest,
        "research_family_id": family_id,
        "successor_ids": [],
        "experiment_ids": [],
        "parameter_search_accounting": {
            "complete_search_space": "One fixed configuration per experiment",
            "ai_generated_variants": "Every run is conservatively counted as AI-originated",
            "combination_count": 1,
        },
        "implementation": {
            "exists": True,
            "location": f"{DOCUMENTATION}/tree/{code_revision}",
            "code_revision": code_revision,
        },
        "reproduction_outcome": {
            "status": "NOT_APPLICABLE",
            "reason": "Software demonstration, not reproduction of a research paper",
        },
    }


def experiment_record(
    *,
    family_id: str,
    strategy_id: str,
    source_id: str,
    dataset_id: str,
    dataset_record_digest: str,
    manifest_digest: str,
    configuration_digest: str,
    environment_digest: str,
    code_revision: str,
    partitions: JsonRecord,
    name: str,
) -> JsonRecord:
    """Build a result-free, complete preregistration with one bounded trial."""
    payload: JsonRecord = {
        "schema_version": "1.0.0",
        "study_type": "OPERATIONAL_VALIDATION",
        "hypothesis": name,
        "research_family_id": family_id,
        "referenced_object_ids": [strategy_id],
        "dataset_ids": [dataset_id],
        "partitions": deepcopy(partitions),
        "search_space": "One fixed configuration; retries require a new experiment",
        "variants_planned": 1,
        "evaluation_metrics": ["simulation accounting outputs"],
        "statistical_tests": ["Software oracle only; no inferential statistical test"],
        "decision_criteria": "Retain evidence as INCONCLUSIVE pending human review",
        "execution_cost_assumptions": [
            "All costs and execution rules are explicit in frozen config and code"
        ],
        "code_revision": code_revision,
        "configuration_digest": configuration_digest,
        "environment_digest": environment_digest,
        "random_seed": 0,
        "author": "local-lab-ai-originated-software",
        "academic_institutional_basis": "Software accounting conservation identities",
        "dataset_vintages": [
            {
                "dataset_id": dataset_id,
                "record_digest": dataset_record_digest,
                "vintage": manifest_digest,
            }
        ],
        "source_registry_ids": [source_id],
        "provenance_artifact_digests": [manifest_digest],
        "instruments": ["SYNTHETIC fixture instruments; configuration-bound"],
        "sampling_frequency": "Chronological synthetic fixture observations",
        "feature_definitions": "Fixed implementation identified by frozen code revision",
        "label_definitions": "No learned label or empirical outcome hypothesis",
        "candidate_universe": "One software fixture and one declared configuration",
        "parameters_considered": configuration_digest,
        "variants_attempted": 0,
        "variant_accounting": {
            "ai_generated_attempts": 0,
            "failed_attempts": 0,
            "accounting_basis": "All completed and interrupted trials count permanently",
        },
        "multiple_testing": {
            "family_id": family_id,
            "budget": 1,
            "correction_plan": "No empirical inference; retain all AI trials in shared family",
        },
        "sealed_data_release": {
            "status": "UNRELEASED",
            "reason": "Future interval is unused metadata; no sealed dataset exists",
        },
        "earlier_experiment_ids": [],
        "configuration_location": f"artifact:{configuration_digest}",
        "baselines": ["No-trade accounting baseline; no scientific superiority claim"],
        "result_artifact_digests": [],
        "failure_modes": [],
        "decision_pending_reason": "Not evaluated; human decision remains required",
    }
    for field in ("results", "result_artifact_locations", "reason_for_decision"):
        payload[field] = pending("No execution or scientific decision has occurred")
    return payload


def require_record(value: JsonValue, context: str) -> JsonRecord:
    """Require an object without weakening the canonical JSON contract."""
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return value
