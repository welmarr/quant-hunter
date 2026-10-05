"""Hostile application integration tests against real Item 8 authorities."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from quant_hunter.config import JsonRecord
from quant_hunter.config.canonical import canonicalize_json, parse_json_document
from quant_hunter.experiments import ExperimentIntegrityError
from quant_hunter.identity import RegistryKind, new_typed_id
from quant_hunter.lab import LabService, LabValidationError
from quant_hunter.provenance import DataManifestReference
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.storage import (
    ImmutableObjectStore,
    ObjectCorruptionError,
    ObjectStoreError,
    SensitiveMetadataError,
)

SCHEMAS = Path(__file__).parents[1] / "schemas" / "v1"
REVISION = "7346cf4f79ca5897777c0118f8cf4c2292be929e"
DATASET = b'{"evidence_mode":"SYNTHETIC","values":[10,11,9]}'


def configuration() -> JsonRecord:
    """Supply actual fixture bounds explicitly rather than inventing coverage."""
    return {
        "market": "FX",
        "initial_cash": "10000",
        "quantity": "1",
        "commission_per_order": "1",
        "slippage_bps": "2",
        "lookback": 2,
        "dataset_start": "2025-01-01T00:00:00Z",
        "dataset_end": "2025-01-04T00:00:00Z",
    }


def service(tmp_path: Path) -> LabService:
    return LabService(tmp_path, SCHEMAS, REVISION, {"test_environment": "synthetic"})


def test_run_registers_before_callback_and_binds_real_bytes(tmp_path: Path) -> None:
    lab = service(tmp_path)
    original = configuration()

    def compute(dataset: bytes, config: JsonRecord) -> JsonRecord:
        runs = lab.list_runs()
        assert len(runs) == 1
        run = runs[0]
        assert run["lifecycle_status"] == "RUNNING"
        experiment_id = cast(str, run["experiment_id"])
        chain = lab.registry.verify_object(experiment_id)
        assert [item.record["lifecycle_status"] for item in chain] == [
            "DRAFT",
            "REGISTERED",
            "FROZEN",
            "RUNNING",
        ]
        assert dataset == DATASET
        assert config["evidence_mode"] == "SYNTHETIC"
        config["quantity"] = "999"  # Cannot mutate already frozen evidence.
        return {"equity": "10001", "oracle_passed": True}

    run = lab.run(original, DATASET, compute)
    assert original == configuration()
    assert run["lifecycle_status"] == "EVALUATED"
    assert run["evaluation_outcome"] == "INCONCLUSIVE"
    assert run["decision"] is None
    assert run["variants_attempted"] == 1
    assert run["variant_accounting"] == {
        "ai_generated_attempts": 1,
        "failed_attempts": 0,
        "accounting_basis": "All completed and interrupted trials count permanently",
    }
    bindings = cast(JsonRecord, run["bindings"])
    assert bindings["dataset_digest"] == sha256_bytes(DATASET)
    expected_config = configuration()
    expected_config["evidence_mode"] = "SYNTHETIC"
    assert bindings["configuration_digest"] == sha256_bytes(
        canonicalize_json(expected_config)
    )
    assert cast(JsonRecord, run["configuration"])["quantity"] == "1"
    assert run["result_digest"] == sha256_bytes(canonicalize_json(run["result"]))
    assert run["host_enforced"] is False
    all_records = lab.registry.verify_all()
    assert len(all_records) == 5
    assert {key.split("-")[0] for key in all_records} == {
        "SOURCE",
        "DATASET",
        "FAM",
        "STRAT",
        "EXP",
    }


def test_exception_retained_without_sensitive_message(tmp_path: Path) -> None:
    lab = service(tmp_path)

    def failing(_dataset: bytes, _config: JsonRecord) -> JsonRecord:
        raise ValueError("api_key=DO_NOT_PERSIST")

    run = lab.run(configuration(), DATASET, failing)
    assert run["evaluation_outcome"] == "FAILED"
    assert run["failure_modes"] == ["ValueError"]
    assert run["result"] is None
    assert cast(JsonRecord, run["variant_accounting"])["failed_attempts"] == 1
    assert all(
        b"DO_NOT_PERSIST" not in path.read_bytes() for path in tmp_path.rglob("*.json")
    )


def test_interruption_counts_and_remains_undecided(tmp_path: Path) -> None:
    lab = service(tmp_path)

    def interrupted(_dataset: bytes, _config: JsonRecord) -> JsonRecord:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        lab.run(configuration(), DATASET, interrupted)
    run = lab.list_runs()[0]
    assert run["evaluation_outcome"] == "FAILED"
    assert run["variants_attempted"] == 1
    assert run["decision"] is None


def test_abandoned_run_can_be_failed_after_restart(tmp_path: Path) -> None:
    lab = service(tmp_path)
    experiment_id = lab.begin_run(configuration(), DATASET)
    reopened = service(tmp_path)
    assert reopened.get_run(experiment_id)["variants_attempted"] == 0
    assert reopened.get_run(experiment_id)["pending_trial"] is True
    failed = reopened.recover_run(experiment_id)
    assert failed["evaluation_outcome"] == "FAILED"
    assert failed["variants_attempted"] == 1
    with pytest.raises(LabValidationError):
        reopened.fail_run(experiment_id)
    assert reopened.recover_run(experiment_id) == failed


@pytest.mark.parametrize("failed", [False, True])
def test_interrupted_finalization_recovers_exact_outcome_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    lab = service(tmp_path)
    experiment_id = lab.begin_run(configuration(), DATASET)

    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated interrupted persistence")

    monkeypatch.setattr(lab.lifecycle, "evaluate", interrupted)
    with pytest.raises(OSError):
        if failed:
            lab.fail_run(experiment_id, "ValueError")
        else:
            lab.evaluate_run(experiment_id, {"value": "retained original"})
    reopened = service(tmp_path)
    pending = reopened.get_run(experiment_id)
    assert pending["lifecycle_status"] == "RUNNING"
    assert pending["variants_attempted"] == 1
    with pytest.raises(LabValidationError):
        reopened.evaluate_run(experiment_id, {"value": "substitution forbidden"})
    with pytest.raises(LabValidationError):
        reopened.fail_run(experiment_id)
    result = reopened.recover_run(experiment_id)
    assert result["evaluation_outcome"] == ("FAILED" if failed else "INCONCLUSIVE")
    assert result["variants_attempted"] == 1
    assert result["result"] == (None if failed else {"value": "retained original"})
    assert reopened.recover_run(experiment_id) == result


def test_distinct_runs_share_family_and_retain_failed_history(tmp_path: Path) -> None:
    lab = service(tmp_path)
    first_id = lab.begin_run(configuration(), DATASET)
    first = lab.fail_run(first_id)
    second = lab.run(configuration(), DATASET, lambda _d, _c: {"answer": 3})
    assert first["experiment_id"] != second["experiment_id"]
    assert (
        cast(JsonRecord, first["bindings"])["family_id"]
        == cast(JsonRecord, second["bindings"])["family_id"]
    )
    assert len(lab.list_runs()) == 2
    assert sum(cast(int, run["variants_attempted"]) for run in lab.list_runs()) == 2


def test_result_tampering_is_rejected(tmp_path: Path) -> None:
    lab = service(tmp_path)
    run = lab.run(configuration(), DATASET, lambda _d, _c: {"value": "1"})
    lab.objects.object_path(cast(str, run["result_digest"])).write_bytes(b"corrupt")
    with pytest.raises(ObjectCorruptionError):
        lab.get_run(cast(str, run["experiment_id"]))


def test_dataset_tampering_prevents_finalization(tmp_path: Path) -> None:
    lab = service(tmp_path)
    experiment_id = lab.begin_run(configuration(), DATASET)
    lab.objects.object_path(sha256_bytes(DATASET)).write_bytes(b"corrupt")
    with pytest.raises(ObjectCorruptionError):
        lab.evaluate_run(experiment_id, {"value": "1"})
    assert (
        lab.registry.verify_object(experiment_id)[-1].record["lifecycle_status"]
        == "RUNNING"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"evidence_mode": "HISTORICAL_REAL"},
        {"dataset_start": "2025-01-04T00:00:00Z"},
        {"dataset_end": "2025-01-01T00:00:00Z"},
        {"dataset_start": "2025-01-01"},
        {"sealed_path": "D:/forbidden"},
    ],
)
def test_invalid_mode_bounds_or_handles_fail_before_registration(
    tmp_path: Path, change: JsonRecord
) -> None:
    lab = service(tmp_path)
    config = configuration()
    config.update(change)
    with pytest.raises(LabValidationError):
        lab.begin_run(config, DATASET)
    assert lab.list_runs() == []


def test_secret_and_nonfinite_inputs_are_rejected(tmp_path: Path) -> None:
    lab = service(tmp_path)
    config = configuration()
    config["api_key"] = "do-not-store"
    with pytest.raises(SensitiveMetadataError):
        lab.begin_run(config, DATASET)
    assert lab.list_runs() == []


def test_duplicate_finalization_cannot_rewrite_result(tmp_path: Path) -> None:
    lab = service(tmp_path)
    run = lab.run(configuration(), DATASET, lambda _d, _c: {"value": "1"})
    with pytest.raises(LabValidationError):
        lab.evaluate_run(cast(str, run["experiment_id"]), {"value": "2"})
    assert lab.get_run(cast(str, run["experiment_id"])) == run


def test_results_cannot_create_scientific_decisions(tmp_path: Path) -> None:
    lab = service(tmp_path)
    config = deepcopy(configuration())
    run = lab.run(
        config, DATASET, lambda _d, _c: {"claim": "profitable", "decision": "ACCEPT"}
    )
    assert run["decision"] is None
    assert run["evaluation_outcome"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "dataset,name",
    [
        (b"", "Valid name"),
        (b"x" * 2_000_001, "Valid name"),
        (DATASET, ""),
        (DATASET, "x" * 161),
    ],
    ids=["empty-fixture", "oversized-fixture", "empty-name", "oversized-name"],
)
def test_dataset_size_and_name_bounds(
    tmp_path: Path, dataset: bytes, name: str
) -> None:
    lab = service(tmp_path)
    with pytest.raises(LabValidationError):
        lab.begin_run(configuration(), dataset, name=name)
    assert lab.list_runs() == []


def test_invalid_constructor_and_configuration_identity(tmp_path: Path) -> None:
    with pytest.raises(LabValidationError):
        LabService(tmp_path, SCHEMAS, "not-a-revision", {})
    with pytest.raises(LabValidationError):
        LabService(Path("relative"), SCHEMAS, REVISION, {})
    lab = service(tmp_path)
    with pytest.raises(LabValidationError):
        lab.get_run("../not-an-experiment")
    config = configuration()
    config["large_input"] = "x" * 2_000_001
    with pytest.raises(LabValidationError):
        lab.begin_run(config, DATASET)
    assert lab.list_runs() == []


def test_incomplete_registration_remains_visible_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = service(tmp_path)

    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated interruption before freeze")

    monkeypatch.setattr(lab.lifecycle, "freeze", interrupted)
    with pytest.raises(OSError):
        lab.begin_run(configuration(), DATASET)
    run = service(tmp_path).list_runs()[0]
    assert run["lifecycle_status"] == "REGISTERED"
    assert run["variants_attempted"] == 0
    assert run["pending_trial"] is False
    with pytest.raises(LabValidationError):
        service(tmp_path).recover_run(cast(str, run["experiment_id"]))


def test_run_persistence_failure_stays_visible_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = service(tmp_path)

    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated interruption after attempt")

    monkeypatch.setattr(lab.lifecycle, "evaluate", interrupted)
    with pytest.raises(OSError):
        lab.run(configuration(), DATASET, lambda _d, _c: {"equity": "10"})
    restarted = service(tmp_path)
    run = restarted.list_runs()[0]
    assert run["variants_attempted"] == 1
    assert restarted.recover_run(cast(str, run["experiment_id"]))["result"] == {
        "equity": "10"
    }


def rebound_run(
    lab: LabService,
    original_id: str,
    manifest: JsonRecord,
    head_updates: JsonRecord | None = None,
) -> str:
    """Publish adversarial but valid objects through real lifecycle and schemas.

    Every digest is recomputed. These cases therefore exercise semantic binding,
    rather than being rejected incidentally by stale hashes or invalid schemas.
    """
    manifest_object = lab.objects.publish(canonicalize_json(manifest))
    record = deepcopy(lab.registry.verify_object(original_id)[1].record)
    for key in (
        "experiment_id",
        "revision",
        "previous_revision_digest",
        "created_at",
        "registered_at",
        "lifecycle_status",
    ):
        record.pop(key, None)
    record["provenance_artifact_digests"] = [manifest_object.digest]
    vintages = cast(list[JsonRecord], record["dataset_vintages"])
    vintages[0]["vintage"] = manifest_object.digest
    if head_updates:
        record.update(head_updates)
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    draft = lab.lifecycle.create_draft(record, created_at=timestamp)
    registered = lab.lifecycle.register(
        draft.object_id, draft.revision.digest, registered_at=timestamp
    )
    frozen = lab.lifecycle.freeze(
        draft.object_id,
        registered.digest,
        frozen_at=timestamp,
        data_manifests=[
            DataManifestReference(
                f"artifact:{manifest_object.digest}", manifest_object.digest
            )
        ],
    )
    lab.lifecycle.start(draft.object_id, frozen.revision.digest, started_at=timestamp)
    # Prove the hostile Item8 record remains independently lifecycle-valid.
    lab.lifecycle.resolve_rerun(draft.object_id).verify()
    return draft.object_id


@pytest.mark.parametrize(
    "field",
    [
        "dataset_id",
        "source_id",
        "strategy_id",
        "family_id",
        "partitions",
        "dataset_record_digest",
    ],
)
def test_rehashed_manifest_cannot_mix_frozen_authorities(
    tmp_path: Path, field: str
) -> None:
    lab = service(tmp_path)
    original = lab.begin_run(configuration(), DATASET)
    foreign = lab.begin_run(configuration(), DATASET + b" ")
    manifest = cast(JsonRecord, lab.get_run(original)["bindings"])
    other = cast(JsonRecord, lab.get_run(foreign)["bindings"])
    if field == "family_id":
        manifest[field] = cast(str, other["strategy_id"]).replace("STRAT-", "FAM-")
    elif field == "partitions":
        partitions = cast(JsonRecord, manifest[field])
        cast(JsonRecord, partitions["training"])["start"] = (
            "2024-12-31T00:00:00.000000Z"
        )
    else:
        manifest[field] = other[field]
    hostile_id = rebound_run(lab, original, manifest)
    with pytest.raises(ExperimentIntegrityError, match="Input manifest"):
        lab.get_run(hostile_id)
    with pytest.raises(ExperimentIntegrityError):
        lab.evaluate_run(hostile_id, {"answer": 1})
    with pytest.raises(ExperimentIntegrityError):
        lab.recover_run(hostile_id)


@pytest.mark.parametrize(
    "field",
    [
        "source_ids",
        "schema_digest",
        "provenance_lineage_digest",
        "coverage",
        "code_revision",
        "environment_digest",
    ],
)
def test_schema_valid_dataset_cannot_disagree_with_manifest(
    tmp_path: Path, field: str
) -> None:
    lab = service(tmp_path)
    original = lab.begin_run(configuration(), DATASET)
    manifest = cast(JsonRecord, lab.get_run(original)["bindings"])
    dataset = deepcopy(
        lab.registry.verify_object(cast(str, manifest["dataset_id"]))[0].record
    )
    for key in ("dataset_id", "revision", "previous_revision_digest"):
        dataset.pop(key)
    if field == "source_ids":
        source = deepcopy(
            lab.registry.verify_object(cast(str, manifest["source_id"]))[0].record
        )
        for key in ("source_id", "revision", "previous_revision_digest"):
            source.pop(key)
        dataset[field] = [lab.registry.allocate(RegistryKind.SOURCE, source).object_id]
    elif field == "coverage":
        cast(JsonRecord, dataset[field])["end"] = "2025-01-05T00:00:00Z"
    elif field == "code_revision":
        cast(JsonRecord, dataset["provenance"])[field] = (
            "e0ba326540b4493f122e384ac7e7d4bcd0ebf6e2"
        )
    elif field == "environment_digest":
        cast(JsonRecord, dataset["provenance"])[field] = lab.objects.publish(
            b"{}"
        ).digest
    else:
        dataset[field] = lab.objects.publish(b"{}").digest
    replacement = lab.registry.allocate(RegistryKind.DATASET, dataset)
    manifest["dataset_id"] = replacement.object_id
    manifest["dataset_record_digest"] = replacement.revision.digest
    manifest_digest = lab.objects.publish(canonicalize_json(manifest)).digest
    hostile_id = rebound_run(
        lab,
        original,
        manifest,
        {
            "dataset_ids": [replacement.object_id],
            "dataset_vintages": [
                {
                    "dataset_id": replacement.object_id,
                    "record_digest": replacement.revision.digest,
                    "vintage": manifest_digest,
                }
            ],
        },
    )
    with pytest.raises(
        ExperimentIntegrityError, match=r"Dataset (provenance|implementation)"
    ):
        lab.get_run(hostile_id)


@pytest.mark.parametrize("damaged", ["missing", "corrupt"])
@pytest.mark.parametrize("operation", ["get", "evaluate", "recover"])
def test_actual_source_snapshot_required_for_every_input_path(
    tmp_path: Path, damaged: str, operation: str
) -> None:
    objects = ImmutableObjectStore(tmp_path / "artifacts")
    snapshot = objects.publish(
        b'{"encoding":"base64-exact-bytes","files":{"src.py":"cGFzcwo="}}'
    )
    lab = LabService(
        tmp_path, SCHEMAS, REVISION, {"source_snapshot_digest": snapshot.digest}
    )
    experiment_id = lab.begin_run(configuration(), DATASET)
    assert lab.get_run(experiment_id)["pending_trial"] is True
    if damaged == "missing":
        snapshot.path.unlink()
    else:
        snapshot.path.write_bytes(b"changed source archive")
    with pytest.raises(ObjectStoreError):
        if operation == "get":
            lab.get_run(experiment_id)
        elif operation == "evaluate":
            lab.evaluate_run(experiment_id, {"answer": 1})
        else:
            lab.recover_run(experiment_id)
    assert (
        lab.registry.verify_object(experiment_id)[-1].record["variants_attempted"] == 0
    )


def registry_payload(lab: LabService, object_id: str, id_field: str) -> JsonRecord:
    """Copy a real schema-valid payload, retaining every semantic field."""
    record = deepcopy(lab.registry.verify_object(object_id)[0].record)
    for key in (id_field, "revision", "previous_revision_digest"):
        record.pop(key)
    return record


@pytest.mark.parametrize(
    "field",
    [
        "source_id",
        "source_record_digest",
        "physical_object_digest",
        "schema_digest",
        "environment_digest",
        "code_revision",
    ],
)
def test_rehashed_lineage_cannot_disagree_with_entire_valid_graph(
    tmp_path: Path, field: str
) -> None:
    lab = service(tmp_path)
    original = lab.begin_run(configuration(), DATASET)
    manifest = cast(JsonRecord, lab.get_run(original)["bindings"])
    lineage = cast(
        JsonRecord,
        parse_json_document(
            lab.objects.get(cast(str, manifest["lineage_digest"])).path.read_bytes()
        ),
    )
    if field == "source_id":
        lineage[field] = new_typed_id(RegistryKind.SOURCE)
    elif field == "code_revision":
        lineage[field] = "e0ba326540b4493f122e384ac7e7d4bcd0ebf6e2"
    else:
        lineage[field] = lab.objects.publish(b"different actual object").digest
    manifest["lineage_digest"] = lab.objects.publish(canonicalize_json(lineage)).digest
    dataset = registry_payload(lab, cast(str, manifest["dataset_id"]), "dataset_id")
    dataset["provenance_lineage_digest"] = manifest["lineage_digest"]
    replacement = lab.registry.allocate(RegistryKind.DATASET, dataset)
    manifest["dataset_id"] = replacement.object_id
    manifest["dataset_record_digest"] = replacement.revision.digest
    strategy = registry_payload(lab, cast(str, manifest["strategy_id"]), "object_id")
    cast(JsonRecord, strategy["data_requirements"])["dataset_ids"] = [
        replacement.object_id
    ]
    replacement_strategy = lab.registry.allocate(RegistryKind.STRATEGY, strategy)
    manifest["strategy_id"] = replacement_strategy.object_id
    manifest["strategy_record_digest"] = replacement_strategy.revision.digest
    manifest_digest = lab.objects.publish(canonicalize_json(manifest)).digest
    hostile_id = rebound_run(
        lab,
        original,
        manifest,
        {
            "dataset_ids": [replacement.object_id],
            "referenced_object_ids": [replacement_strategy.object_id],
            "dataset_vintages": [
                {
                    "dataset_id": replacement.object_id,
                    "record_digest": replacement.revision.digest,
                    "vintage": manifest_digest,
                }
            ],
        },
    )
    with pytest.raises(ExperimentIntegrityError, match="Lineage"):
        lab.get_run(hostile_id)


@pytest.mark.parametrize(
    "field",
    ["research_family_id", "parameters", "source_ids", "dataset_ids", "code_revision"],
)
def test_rehashed_strategy_cannot_select_foreign_inputs(
    tmp_path: Path, field: str
) -> None:
    lab = service(tmp_path)
    original = lab.begin_run(configuration(), DATASET)
    manifest = cast(JsonRecord, lab.get_run(original)["bindings"])
    strategy = registry_payload(lab, cast(str, manifest["strategy_id"]), "object_id")
    if field == "research_family_id":
        strategy[field] = new_typed_id(RegistryKind.FAMILY)
    elif field == "parameters":
        strategy[field] = lab.objects.publish(b"{}").digest
    elif field == "code_revision":
        cast(JsonRecord, strategy["implementation"])[field] = (
            "e0ba326540b4493f122e384ac7e7d4bcd0ebf6e2"
        )
    else:
        kind = RegistryKind.SOURCE if field == "source_ids" else RegistryKind.DATASET
        cast(JsonRecord, strategy["data_requirements"])[field] = [new_typed_id(kind)]
    replacement = lab.registry.allocate(RegistryKind.STRATEGY, strategy)
    manifest["strategy_id"] = replacement.object_id
    manifest["strategy_record_digest"] = replacement.revision.digest
    hostile_id = rebound_run(
        lab, original, manifest, {"referenced_object_ids": [replacement.object_id]}
    )
    with pytest.raises(ExperimentIntegrityError, match="Strategy"):
        lab.get_run(hostile_id)
