"""Read-only Item8 inventory and exact frozen Item9/application plan bindings."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import cast

from quant_hunter.config import (
    JsonRecord,
    JsonValue,
    canonicalize_json,
    parse_json_document,
)
from quant_hunter.experiments import ExperimentLifecycleService
from quant_hunter.identity import (
    RegistryKind,
    RegistryStore,
    Revision,
    validate_typed_id,
)
from quant_hunter.provenance.hashing import require_sha256_digest
from quant_hunter.storage import ImmutableObjectStore
from quant_hunter.validation import (
    FrozenTemporalValidationBinding,
    ScientificEvidencePlan,
    ValidationPlan,
    bind_frozen_temporal_validation,
)

from .statistics import BootstrapSpec, holm_adjust, probability
from .temporal import (
    Predictor,
    ResearchValidationError,
    SupervisedRow,
    execute_walk_forward,
)


def protocol_document(
    plan: ValidationPlan,
    bootstrap: BootstrapSpec,
    *,
    minimum_train: int,
    minimum_validation: int,
    alpha: str = "0.05",
    test_definition_digest: str | None = None,
) -> JsonRecord:
    plan.verify()
    bootstrap.__post_init__()
    if test_definition_digest is not None:
        require_sha256_digest(test_definition_digest)
    if (
        type(minimum_train) is not int
        or not 2 <= minimum_train <= 100_000
        or type(minimum_validation) is not int
        or not 1 <= minimum_validation <= 100_000
        or not 0 < probability(alpha) < 1
    ):
        raise ResearchValidationError("INVALID_VALIDATION_PROTOCOL")
    return {
        "schema_version": "qh-registered-validation-v1",
        "temporal_plan": plan.document,
        "temporal_plan_digest": plan.digest,
        "bootstrap": bootstrap.to_record(),
        "minimum_train": minimum_train,
        "minimum_validation": minimum_validation,
        "multiple_testing_method": "HOLM_STEP_DOWN_BONFERRONI_1979",
        "alpha": alpha,
        "test_definition_digest": test_definition_digest,
        "missing_trial_statistics": "INCONCLUSIVE_NO_ADJUSTED_P_VALUES",
        "learned_transforms": "FIT_EACH_FOLD_TRAIN_ONLY",
        "membership": "FEATURE_AND_LABEL_RECEIPT_AT_FIT_WITH_EXACT_GAP_DEPENDENCIES",
        "sealed_access": "NONE",
    }


def _record(value: JsonValue) -> JsonRecord:
    if not isinstance(value, dict):
        raise ResearchValidationError("INVALID_VALIDATION_EVIDENCE")
    return value


class ResearchValidationService:
    """No lifecycle writes, evaluation/promotion decisions, attempts or holdout I/O."""

    def __init__(self, registry: RegistryStore, objects: ImmutableObjectStore) -> None:
        self.registry, self.objects = registry, objects
        self.lifecycle = ExperimentLifecycleService(registry, objects)

    def _frozen(self, experiment_id: str) -> tuple[Revision, JsonRecord]:
        resolution = self.lifecycle.resolve_rerun(experiment_id)
        resolution.verify()
        digest = resolution.document["frozen_revision_digest"]
        revisions = self.registry.verify_object(experiment_id)
        frozen = next((row for row in revisions if row.digest == digest), None)
        if frozen is None or frozen.record["lifecycle_status"] != "FROZEN":
            raise ResearchValidationError("FROZEN_IDENTITY_MISMATCH")
        config = _record(
            parse_json_document(
                self.objects.read_bytes(
                    cast(str, resolution.document["configuration_digest"])
                )
            )
        )
        return frozen, config

    def bind(
        self, experiment_id: str, plan: ValidationPlan, protocol: JsonRecord
    ) -> FrozenTemporalValidationBinding:
        frozen, config = self._frozen(experiment_id)
        if (
            config.get("chronological_validation") != protocol
            or protocol.get("temporal_plan_digest") != plan.digest
            or protocol.get("temporal_plan") != plan.document
        ):
            raise ResearchValidationError("PROTOCOL_NOT_FROZEN")
        # Merely naming an arbitrary method/policy does not satisfy the supported
        # execution contract. Rebuild it from its closed known fields.
        bootstrap = _record(protocol["bootstrap"])
        specification = BootstrapSpec(
            cast(int, bootstrap["block_length"]),
            cast(int, bootstrap["repetitions"]),
            cast(int, bootstrap["seed"]),
            cast(str, bootstrap["confidence"]),
            cast(int, bootstrap["minimum_observations"]),
        )
        expected = protocol_document(
            plan,
            specification,
            minimum_train=cast(int, protocol["minimum_train"]),
            minimum_validation=cast(int, protocol["minimum_validation"]),
            alpha=cast(str, protocol["alpha"]),
            test_definition_digest=cast(str | None, protocol["test_definition_digest"]),
        )
        if protocol != expected:
            raise ResearchValidationError("INVALID_VALIDATION_PROTOCOL")
        if protocol["test_definition_digest"] is not None:
            self.objects.get(cast(str, protocol["test_definition_digest"]))
        return bind_frozen_temporal_validation(frozen.record, frozen.digest, plan)

    def bind_scientific_plan(
        self, experiment_id: str, plan: ScientificEvidencePlan
    ) -> str:
        """Only accept an actual Item9B object whose declarations were frozen."""
        plan.verify()
        frozen, config = self._frozen(experiment_id)
        if (
            plan.experiment_id != experiment_id
            or plan.temporal_validation.frozen_revision_digest != frozen.digest
        ):
            raise ResearchValidationError("SCIENTIFIC_PLAN_IDENTITY_MISMATCH")
        requirements = {
            key: plan.document[key]
            for key in (
                "baselines",
                "metrics",
                "statistical_methods",
                "robustness_requirements",
                "reporting_conventions",
            )
        }
        if config.get("scientific_requirements") != requirements:
            raise ResearchValidationError("SCIENTIFIC_REQUIREMENTS_NOT_FROZEN")
        self.bind(
            experiment_id,
            plan.temporal_validation.validation_plan,
            _record(config["chronological_validation"]),
        )
        multiple = _record(frozen.record["multiple_testing"])
        if (
            plan.multiple_testing.family_id != multiple["family_id"]
            or plan.multiple_testing.budget != multiple["budget"]
            or plan.multiple_testing.correction_plan != multiple["correction_plan"]
        ):
            raise ResearchValidationError("MULTIPLE_TESTING_BINDING_MISMATCH")
        return self.objects.publish(plan.canonical_bytes).digest

    def execute(
        self,
        experiment_id: str,
        plan: ValidationPlan,
        rows: tuple[SupervisedRow, ...],
        fit: Callable[[tuple[tuple[float, ...], ...], tuple[float, ...]], Predictor],
        *,
        evaluation_as_of: datetime,
    ) -> JsonRecord:
        _, config = self._frozen(experiment_id)
        protocol = _record(config["chronological_validation"])
        binding = self.bind(experiment_id, plan, protocol)
        if (
            self.registry.verify_object(experiment_id)[-1].record["lifecycle_status"]
            != "RUNNING"
        ):
            raise ResearchValidationError("EXECUTION_REQUIRES_ITEM8_RUNNING")
        return execute_walk_forward(
            binding,
            rows,
            fit,
            evaluation_as_of=evaluation_as_of,
            minimum_train=cast(int, protocol["minimum_train"]),
            minimum_validation=cast(int, protocol["minimum_validation"]),
        )

    def trial_inventory(self, family_id: str) -> JsonRecord:
        """Read every registered EXP in this family, including failed/unfinalized ones."""
        validate_typed_id(family_id, RegistryKind.FAMILY)
        self.registry.verify_object(family_id)
        root = self.registry.root / RegistryKind.EXPERIMENT.directory
        paths = tuple(root.iterdir()) if root.exists() else ()
        if len(paths) > 10_000:
            raise ResearchValidationError("TRIAL_INVENTORY_LIMIT")
        records: list[JsonValue] = []
        total = failed = ai = 0
        for path in sorted(paths, key=lambda item: item.name):
            revisions = self.registry.verify_object(path.name)
            head = revisions[-1]
            if head.record["research_family_id"] != family_id:
                continue
            status = head.record["lifecycle_status"]
            if status not in {"DRAFT", "REGISTERED"}:
                self.lifecycle.resolve_rerun(path.name).verify()
            attempts = head.record.get("attempt_records", [])
            if not isinstance(attempts, list):
                raise ResearchValidationError("INVALID_TRIAL_INVENTORY")
            count = cast(int, head.record["variants_attempted"])
            accounting = _record(head.record["variant_accounting"])
            total += count
            failed += cast(int, accounting["failed_attempts"])
            ai += cast(int, accounting["ai_generated_attempts"])
            if total > 10_000:
                raise ResearchValidationError("TRIAL_INVENTORY_LIMIT")
            records.append(
                {
                    "experiment_id": path.name,
                    "revision_digest": head.digest,
                    "status": status,
                    "attempts": attempts,
                    "variants_attempted": count,
                    "failed_attempts": accounting["failed_attempts"],
                    "ai_generated_attempts": accounting["ai_generated_attempts"],
                    "decision": head.record.get("decision"),
                    "result_artifact_digests": head.record.get(
                        "result_artifact_digests", []
                    ),
                }
            )
        report: JsonRecord = {
            "schema_version": "qh-canonical-trial-inventory-v1",
            "family_id": family_id,
            "authority": "ITEM_8_EXPERIMENT_LIFECYCLE",
            "experiments": records,
            "total_attempts": total,
            "failed_attempts": failed,
            "ai_generated_attempts": ai,
            "empirical_status": "INCONCLUSIVE",
        }
        return {
            **report,
            "inventory_digest": self.objects.publish(canonicalize_json(report)).digest,
        }

    def adjusted_family(self, family_id: str, *, alpha: str = "0.05") -> JsonRecord:
        """Use only retained result artifacts with explicit per-attempt test bindings.

        A valid numerical p-value is not invented for a failure, unfinished job or
        ordinary diagnostic result. Any such gap blocks the family correction.
        """
        inventory = self.trial_inventory(family_id)
        values: list[tuple[str, str]] = []
        missing: list[JsonValue] = []
        for item in cast(list[JsonRecord], inventory["experiments"]):
            experiment_id = cast(str, item["experiment_id"])
            if (
                item["status"] not in {"EVALUATED", "DECIDED"}
                or item["failed_attempts"]
            ):
                missing.append(
                    {
                        "experiment_id": experiment_id,
                        "reason": "FAILED_OR_UNFINALIZED_TRIAL",
                    }
                )
                continue
            frozen, config = self._frozen(experiment_id)
            protocol = config.get("chronological_validation")
            if (
                not isinstance(protocol, dict)
                or protocol.get("multiple_testing_method")
                != "HOLM_STEP_DOWN_BONFERRONI_1979"
                or protocol.get("alpha") != alpha
            ):
                missing.append(
                    {
                        "experiment_id": experiment_id,
                        "reason": "CORRECTION_NOT_PREREGISTERED",
                    }
                )
                continue
            observations: dict[int, str] = {}
            definition_digest = protocol.get("test_definition_digest")
            if not isinstance(definition_digest, str):
                missing.append(
                    {
                        "experiment_id": experiment_id,
                        "reason": "TEST_DEFINITION_NOT_PREREGISTERED",
                    }
                )
                continue
            require_sha256_digest(definition_digest)
            self.objects.get(definition_digest)
            for digest in cast(list[str], item["result_artifact_digests"]):
                result = _record(parse_json_document(self.objects.read_bytes(digest)))
                if result.get("schema_version") != "qh-prespecified-trial-tests-v1":
                    continue
                if (
                    result.get("experiment_id") != experiment_id
                    or result.get("frozen_revision_digest") != frozen.digest
                ):
                    raise ResearchValidationError("TEST_RESULT_IDENTITY_MISMATCH")
                tests = result.get("tests")
                if not isinstance(tests, list) or len(tests) > 10_000:
                    raise ResearchValidationError("INVALID_TEST_RESULT")
                for test_value in tests:
                    test = _record(test_value)
                    number = test.get("attempt_number")
                    if (
                        type(number) is not int
                        or number in observations
                        or not 1 <= number <= cast(int, item["variants_attempted"])
                    ):
                        raise ResearchValidationError(
                            "DUPLICATE_OR_UNKNOWN_TEST_ATTEMPT"
                        )
                    attempt = _record(
                        cast(list[JsonValue], item["attempts"])[number - 1]
                    )
                    if (
                        not isinstance(attempt.get("variant_configuration_digest"), str)
                        or test.get("variant_configuration_digest")
                        != attempt.get("variant_configuration_digest")
                        or not isinstance(test.get("test_definition_digest"), str)
                        or test.get("test_definition_digest")
                        != protocol.get("test_definition_digest")
                    ):
                        raise ResearchValidationError("TEST_DEFINITION_NOT_FROZEN")
                    self.objects.get(cast(str, attempt["variant_configuration_digest"]))
                    observations[number] = str(
                        probability(cast(str, test.get("p_value")))
                    )
            count = cast(int, item["variants_attempted"])
            if set(observations) != set(range(1, count + 1)) or count == 0:
                missing.append(
                    {
                        "experiment_id": experiment_id,
                        "reason": "MISSING_VALID_PER_ATTEMPT_TEST",
                    }
                )
            values.extend(
                (f"{experiment_id}:{number}", value)
                for number, value in sorted(observations.items())
            )
        if missing or len(values) != inventory["total_attempts"] or not values:
            adjustment: JsonRecord = {
                "status": "INCONCLUSIVE",
                "reason": "INCOMPLETE_TRIAL_STATISTICS",
                "adjusted_p_values": None,
                "missing": missing,
            }
        else:
            adjustment = {
                "status": "COMPUTED_SOFTWARE_ONLY",
                "adjusted_p_values": holm_adjust(tuple(values), alpha=alpha),
                "missing": [],
            }
        current = self.trial_inventory(family_id)
        if current["inventory_digest"] != inventory["inventory_digest"]:
            raise ResearchValidationError("TRIAL_INVENTORY_CHANGED_DURING_ASSESSMENT")
        return {
            "inventory": inventory,
            "adjustment": adjustment,
            "empirical_status": "INCONCLUSIVE",
            "promotion_allowed": False,
        }
