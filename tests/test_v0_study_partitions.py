"""Study training boundaries are frozen and revalidated by canonical authority."""

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from test_v0_lab import DATASET, configuration, rebound_run, service

from quant_hunter.config import JsonRecord
from quant_hunter.experiments import ExperimentIntegrityError
from quant_hunter.identity import RegistryKind
from quant_hunter.lab import LabValidationError


def study_config() -> JsonRecord:
    return {
        **configuration(),
        "kind": "CRP_STUDY",
        "training_start": "2025-01-01T00:00:00Z",
        "train_end": "2025-01-02T00:00:00Z",
        "training_end_exclusive": "2025-01-02T00:00:00.000001Z",
        "decision_at": "2025-01-02T01:00:00Z",
        "target_start": "2025-01-02T02:00:00Z",
        "target_end": "2025-01-03T00:00:00Z",
        "target_available_at": "2025-01-03T01:00:00Z",
        "random_seed": 412,
        "software_method": {
            "implemented_scope": "Synthetic numerical oracle only",
            "source_citations": ["https://github.com/welmarr/quant-hunter"],
            "assumptions": ["Synthetic fixture; no empirical inference"],
            "cost_model": "No trading rule; no PnL claim",
        },
    }


def test_explicit_study_partition_survives_immutable_roundtrip(tmp_path: Path) -> None:
    lab = service(tmp_path)
    config = study_config()
    identity = lab.begin_run(config, DATASET)
    head = lab.registry.verify_object(identity)[-1]
    partitions = cast(JsonRecord, head.record["partitions"])
    assert (
        cast(JsonRecord, partitions["training"])["end"]
        == config["training_end_exclusive"]
    )
    result = lab.evaluate_run(identity, {"synthetic": True})
    assert (
        result["variants_attempted"] == 1
        and result["evaluation_outcome"] == "INCONCLUSIVE"
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("training_start", "2025-01-01T00:01:00Z"),
        ("training_end_exclusive", "2025-01-02T00:00:00.000002Z"),
        ("train_end", "2025-01-05T00:00:00Z"),
        ("decision_at", "2025-01-01T00:00:00Z"),
        ("target_start", "2025-01-02T01:00:00Z"),
        ("target_available_at", "2025-01-02T23:00:00Z"),
        ("target_end", "2025-01-04T00:00:00Z"),
        ("training_start", None),
    ],
)
def test_invalid_explicit_time_plan_never_allocates_research_identity(
    tmp_path: Path, key: str, value: str | None
) -> None:
    lab = service(tmp_path)
    config = study_config()
    if value is None:
        del config[key]
    else:
        config[key] = value
    with pytest.raises(LabValidationError):
        lab.begin_run(config, DATASET)
    assert lab.registry.verify_all() == {}


@pytest.mark.parametrize(
    "field,value",
    [
        ("random_seed", 99),
        ("feature_definitions", "A different method"),
        ("label_definitions", "An inconsistent future target"),
        ("execution_cost_assumptions", ["Zero realistic cost asserted"]),
        ("baselines", ["Unregistered comparator"]),
        ("evaluation_metrics", ["Invented metric"]),
    ],
)
def test_rehashed_experiment_cannot_change_method_or_seed(
    tmp_path: Path, field: str, value: object
) -> None:
    lab = service(tmp_path)
    original = lab.begin_run(study_config(), DATASET)
    manifest = cast(JsonRecord, lab.get_run(original)["bindings"])
    identity = rebound_run(lab, original, manifest, cast(JsonRecord, {field: value}))
    actions: tuple[Callable[[], JsonRecord], ...] = (
        lambda: lab.get_run(identity),
        lambda: lab.evaluate_run(identity, {"numerical": 1}),
        lambda: lab.recover_run(identity),
    )
    for action in actions:
        with pytest.raises(ExperimentIntegrityError, match="Declared"):
            action()


@pytest.mark.parametrize(
    "field,value",
    [
        ("mathematical_definition", "Another formula"),
        ("source_citations", ["https://example.test/another"]),
        ("assumptions", ["Later revisions assumed known"]),
        ("transaction_cost_sensitivity", "Undeclared free execution"),
    ],
)
def test_rehashed_strategy_cannot_contradict_frozen_method(
    tmp_path: Path, field: str, value: object
) -> None:
    lab = service(tmp_path)
    original = lab.begin_run(study_config(), DATASET)
    manifest = cast(JsonRecord, lab.get_run(original)["bindings"])
    strategy = deepcopy(
        lab.registry.verify_object(str(manifest["strategy_id"]))[0].record
    )
    for key in ("object_id", "revision", "previous_revision_digest"):
        strategy.pop(key, None)
    strategy.update(cast(JsonRecord, {field: value}))
    changed = lab.registry.allocate(RegistryKind.STRATEGY, strategy)
    manifest["strategy_id"] = changed.object_id
    manifest["strategy_record_digest"] = changed.revision.digest
    identity = rebound_run(
        lab, original, manifest, {"referenced_object_ids": [changed.object_id]}
    )
    with pytest.raises(ExperimentIntegrityError, match="Declared strategy method"):
        lab.get_run(identity)
