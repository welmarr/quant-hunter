"""Canonical model records precede actual Item8 evaluation on synthetic inputs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from test_v0_data_quality import CODE, SCHEMAS

from quant_hunter.config import JsonRecord, canonicalize_json, parse_json_document
from quant_hunter.identity import RegistryKind
from quant_hunter.lab import LabService
from quant_hunter.storage import ObjectStoreError
from quant_hunter.web.state import AccessError, AppState, User
from quant_hunter.web.studies import prepare_job, request_config
from quant_hunter.web.study_model_ids import ModelIdentityError, StudyModelIds


def setup(tmp_path: Path) -> tuple[StudyModelIds, User]:
    state = AppState(tmp_path / "app.sqlite3")
    owner = state.create_user("owner", "synthetic password", "owner", bootstrap=True)
    lab = LabService(tmp_path / "lab", SCHEMAS, CODE, {"synthetic_test": True})
    return StudyModelIds(state, lab), owner


@pytest.mark.parametrize(
    "method", [*[f"CRP-{i:02}" for i in range(1, 11)], "ENS-COV", "META-OOF"]
)
def test_all_study_recipes_and_actual_fit_outputs_are_registered_before_math(
    tmp_path: Path, method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, user = setup(tmp_path)
    bridge.state.enqueue(user, request_config(method, "POSITIVE"))
    job = bridge.state.claim()
    assert job is not None
    config, source, name = prepare_job(job.config)
    bound, payload = bridge.register_study(user, job, config, source)
    registration = cast(JsonRecord, bound["model_registration"])
    recipe = cast(JsonRecord, registration["recipe"])
    assert str(recipe["model_id"]).startswith("MOD-")
    assert bridge.lab.list_runs() == []
    assert (
        bridge.lab.objects.read_bytes(cast(str, registration["source_digest"]))
        == source
    )
    for row in cast(list[JsonRecord], registration["fits"]):
        binding = cast(JsonRecord, row["binding"])
        record = bridge.lab.registry.verify_object(cast(str, binding["model_id"]))[
            -1
        ].record
        assert record["status"] == "PROPOSED"
        assert record["parent_ids"] == [recipe["model_id"]]
        assert record["experiment_ids"] == []
    experiment = bridge.lab.begin_run(bound, payload, name=name)
    bridge.state.bind(job.id, experiment)
    active = bridge.state.job(user, job.id)
    import quant_hunter.research_methods.studies as numerical

    original = numerical.execute_study

    def checked(raw: bytes, configuration: JsonRecord) -> JsonRecord:
        assert raw == source and configuration == config
        assert bridge.lab.get_run(experiment)["lifecycle_status"] == "RUNNING"
        bridge.verify(user, registration, current=True)
        return original(raw, configuration)

    monkeypatch.setattr(numerical, "execute_study", checked)
    result = bridge.execute_study(user, active, experiment, bound, payload)
    bridge.lab.evaluate_run(experiment, result)
    bridge.state.finish(job.id)
    inspected = bridge.inspect(user, bridge.state.job(user, job.id))
    assert inspected["variants_attempted"] == 1
    assert inspected["evaluation_outcome"] == "INCONCLUSIVE"
    assert result["fitted_model"] == original(source, config)["fitted_model"]


def test_preregistered_ids_are_job_specific_and_foreign_or_stale_producer_is_rejected(
    tmp_path: Path,
) -> None:
    bridge, user = setup(tmp_path)
    configurations: list[tuple[Any, JsonRecord, bytes]] = []
    for _ in range(2):
        bridge.state.enqueue(user, request_config("CRP-06", "POSITIVE"))
        job = bridge.state.claim()
        assert job is not None
        config, source, _ = prepare_job(job.config)
        bound, payload = bridge.register_study(user, job, config, source)
        configurations.append((job, bound, payload))
    first, second = configurations
    a, b = (
        cast(JsonRecord, config["model_registration"])
        for _, config, _ in configurations
    )
    assert a["recipe"] != b["recipe"] and a["fits"] != b["fits"]
    bad = {**a, "job_id": second[0].id}
    with pytest.raises(ModelIdentityError, match="RECORD_BINDING"):
        bridge.verify(user, bad)
    old = bridge.lab.code_revision
    bridge.lab.code_revision = "a" * 40
    with pytest.raises(ModelIdentityError, match="CURRENT_PRODUCER"):
        bridge.verify(user, a, current=True)
    bridge.verify(user, a)  # Historical producer remains inspectable.
    bridge.lab.code_revision = old
    foreign = bridge.state.create_user(
        "other", "synthetic password", "researcher", bootstrap=False
    )
    with pytest.raises(ModelIdentityError, match="REGISTRATION_BINDING"):
        bridge.verify(foreign, a)
    base, raw, _ = prepare_job(first[0].config)
    with pytest.raises(AccessError, match="Exact owned active"):
        bridge.register_study(user, replace(first[0], status="QUEUED"), base, raw)


def registered(
    bridge: StudyModelIds, user: User, method: str = "CRP-06"
) -> tuple[Any, JsonRecord, bytes]:
    bridge.state.enqueue(user, request_config(method, "POSITIVE"))
    job = bridge.state.claim()
    assert job is not None
    config, source, _ = prepare_job(job.config)
    bound, payload = bridge.register_study(user, job, config, source)
    return job, bound, payload


@pytest.mark.parametrize("edge", ["source", "producer", "parent", "owner", "status"])
def test_valid_rehashed_model_record_cannot_contradict_registration(
    tmp_path: Path, edge: str
) -> None:
    bridge, user = setup(tmp_path)
    _, bound, _ = registered(bridge, user)
    registration = deepcopy(cast(JsonRecord, bound["model_registration"]))
    fit = cast(JsonRecord, cast(list[JsonRecord], registration["fits"])[0]["binding"])
    original = bridge.lab.registry.verify_object(cast(str, fit["model_id"]))[-1]
    definition = deepcopy(
        {
            k: v
            for k, v in original.record.items()
            if k not in {"object_id", "revision", "previous_revision_digest"}
        }
    )
    if edge == "source":
        parameters = cast(
            JsonRecord, parse_json_document(cast(str, definition["parameters"]))
        )
        parameters["source_digest"] = bridge.lab.objects.publish(
            b"foreign exact input"
        ).digest
        definition["parameters"] = canonicalize_json(parameters).decode()
    elif edge == "producer":
        cast(JsonRecord, definition["implementation"])["code_revision"] = "b" * 40
    elif edge == "parent":
        definition["parent_ids"] = []
    elif edge == "owner":
        definition["owner"] = "local-user-999"
    else:
        definition["status"] = "REJECTED"
    replacement = bridge.lab.registry.allocate(RegistryKind.MODEL, definition)
    fit.update(
        model_id=replacement.object_id, record_digest=replacement.revision.digest
    )
    with pytest.raises(ModelIdentityError, match="RECORD_BINDING"):
        bridge.verify(user, registration)


@pytest.mark.parametrize(
    "edge",
    [
        "missing",
        "wrong_experiment",
        "wrong_output",
        "extra_field",
        "duplicate_fit",
        "source_missing",
    ],
)
def test_missing_or_coherently_rehashed_artifact_graph_is_rejected(
    tmp_path: Path, edge: str
) -> None:
    bridge, user = setup(tmp_path)
    _, bound, _ = registered(bridge, user)
    registration = cast(JsonRecord, bound["model_registration"])
    outputs: JsonRecord = {
        key: None for key in cast(list[str], registration["fit_keys"])
    }
    artifact = bridge.artifact(
        registration, "EXP-01990f30-7f5e-7b34-9b21-3d74c513c849", outputs
    )
    bridge.verify_artifact(
        user, artifact, "EXP-01990f30-7f5e-7b34-9b21-3d74c513c849", outputs
    )
    if edge == "missing":
        artifact["artifact_digest"] = "sha256:" + "f" * 64
    elif edge == "source_missing":
        bridge.lab.objects.get(cast(str, registration["source_digest"])).path.unlink()
    elif edge == "duplicate_fit":
        fits = cast(list[JsonRecord], registration["fits"])
        fits[1]["binding"] = fits[0]["binding"]
    else:
        payload = cast(
            JsonRecord,
            parse_json_document(
                bridge.lab.objects.read_bytes(cast(str, artifact["artifact_digest"]))
            ),
        )
        if edge == "wrong_experiment":
            payload["experiment_id"] = "EXP-01990f30-7f5e-7b34-9b21-3d74c513c850"
        elif edge == "wrong_output":
            payload["outputs"] = {}
        else:
            payload["extra"] = "not a closed artifact"
        artifact["artifact_digest"] = bridge.lab.objects.publish(
            canonicalize_json(payload)
        ).digest
    with pytest.raises((ModelIdentityError, ObjectStoreError)):
        bridge.verify_artifact(
            user, artifact, "EXP-01990f30-7f5e-7b34-9b21-3d74c513c849", outputs
        )


def test_item8_binding_prevents_computation_and_failed_fit_ids_remain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, user = setup(tmp_path)
    job, config, payload = registered(bridge, user)
    experiment = bridge.lab.begin_run(
        config, payload, name="Synthetic failure retention"
    )
    bridge.state.bind(job.id, experiment)
    active = bridge.state.job(user, job.id)
    import quant_hunter.research_methods.studies as numerical

    def failure(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("synthetic mathematical failure")

    monkeypatch.setattr(numerical, "execute_study", failure)
    with pytest.raises(ModelIdentityError, match="INPUT_MANIFEST"):
        bridge.execute_study(user, active, experiment, config, payload + b" ")
    with pytest.raises(ValueError, match="synthetic mathematical failure"):
        bridge.execute_study(user, active, experiment, config, payload)
    bridge.lab.fail_run(experiment, "SyntheticMathematicalFailure")
    bridge.state.finish(job.id, error="SyntheticMathematicalFailure")
    run = bridge.inspect(user, bridge.state.job(user, job.id))
    assert run["variants_attempted"] == 1 and run["evaluation_outcome"] == "FAILED"
    bridge.verify(user, cast(JsonRecord, config["model_registration"]))


def test_retained_environment_source_archive_is_required(tmp_path: Path) -> None:
    bridge, user = setup(tmp_path)
    source = bridge.lab.objects.publish(b"synthetic source archive")
    environment = bridge.lab.objects.publish(
        canonicalize_json({"source_snapshot_digest": source.digest})
    )
    bridge.lab.environment_digest = environment.digest
    _, bound, _ = registered(bridge, user)
    source.path.unlink()
    with pytest.raises(ObjectStoreError):
        bridge.verify(user, cast(JsonRecord, bound["model_registration"]))


@pytest.mark.parametrize(
    "edge",
    ["scope", "too_many", "duplicate", "empty_source", "large_source", "large_config"],
)
def test_registration_bounds_precede_model_allocation(
    tmp_path: Path, edge: str
) -> None:
    bridge, user = setup(tmp_path)
    bridge.state.enqueue(user, request_config("CRP-06", "POSITIVE"))
    job = bridge.state.claim()
    assert job is not None
    config, source, _ = prepare_job(job.config)
    keys: tuple[str, ...] = ("estimator",)
    if edge == "too_many":
        keys = tuple(str(i) for i in range(11))
    elif edge == "duplicate":
        keys = ("estimator", "estimator")
    elif edge == "empty_source":
        source = b""
    elif edge == "large_source":
        source = b"x" * 2_000_001
    elif edge == "large_config":
        config["oversized"] = "x" * 2_000_001
    with pytest.raises(ModelIdentityError, match=r"SCOPE|LIMIT"):
        bridge.register(
            user,
            job,
            scope="OTHER" if edge == "scope" else "STUDY",
            method_id="CRP-06",
            configuration=config,
            source=source,
            fit_keys=keys,
        )


def test_successful_study_inspection_requires_artifact_and_retains_historical_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, user = setup(tmp_path)
    job, config, payload = registered(bridge, user, "CRP-01")
    exp = bridge.lab.begin_run(config, payload, name="Synthetic result graph")
    bridge.state.bind(job.id, exp)
    active = bridge.state.job(user, job.id)
    result = bridge.execute_study(user, active, exp, config, payload)
    bridge.lab.evaluate_run(exp, result)
    bridge.state.finish(job.id)
    finished = bridge.state.job(user, job.id)
    run = bridge.inspect(user, finished)
    bridge.lab.code_revision = "b" * 40
    import quant_hunter.web.studies as studies

    monkeypatch.setattr(
        studies,
        "prepare_job",
        lambda *a: pytest.fail("historical input regenerated with current producer"),
    )
    bridge.inspect(user, finished)
    broken = {**result}
    del broken["canonical_models"]
    monkeypatch.setattr(bridge.lab, "get_run", lambda *a: {**run, "result": broken})
    with pytest.raises(ModelIdentityError, match="OBJECT_REQUIRED"):
        bridge.inspect(user, finished)


@pytest.mark.parametrize(
    "edge",
    [
        "job_request",
        "method",
        "recipe_fields",
        "fit_plan",
        "fit_fields",
        "fit_family",
        "artifact_fields",
        "artifact_plan",
        "artifact_size",
        "metadata_size",
        "input_mismatch",
    ],
)
def test_closed_graph_boundaries_do_not_admit_partial_or_oversized_evidence(
    tmp_path: Path, edge: str
) -> None:
    bridge, user = setup(tmp_path)
    job, config, _ = registered(bridge, user)
    registration = deepcopy(cast(JsonRecord, config["model_registration"]))
    if edge == "job_request":
        registration["job_request"] = {
            "kind": "CRP_STUDY",
            "study_id": "CRP-01",
            "scenario": "NULL",
        }
    elif edge == "method":
        registration["method"] = {}
    elif edge == "recipe_fields":
        cast(JsonRecord, registration["recipe"])["extra"] = "not permitted"
    elif edge == "fit_plan":
        registration["fits"] = []
    elif edge == "fit_fields":
        cast(list[JsonRecord], registration["fits"])[0]["extra"] = True
    elif edge == "fit_family":
        cast(JsonRecord, cast(list[JsonRecord], registration["fits"])[0]["binding"])[
            "family_record_digest"
        ] = "sha256:" + "f" * 64
    elif edge == "metadata_size":
        oversized = bridge.lab.objects.publish(
            canonicalize_json({"large": "x" * 2_000_001})
        ).digest
        with pytest.raises(ModelIdentityError, match="METADATA_LIMIT"):
            bridge._read(oversized)
        return
    elif edge == "input_mismatch":
        base, raw, _ = prepare_job(job.config)
        with pytest.raises(ModelIdentityError, match="INPUT_BINDING"):
            bridge.register_study(user, job, base, raw + b" ")
        return
    elif edge == "artifact_fields":
        with pytest.raises(ModelIdentityError, match="OUTPUT_BINDING"):
            bridge.verify_artifact(user, {"registration": registration}, "unused", {})
        return
    elif edge == "artifact_plan":
        with pytest.raises(ModelIdentityError, match="OUTPUT_PLAN"):
            bridge.artifact(registration, "unused", {})
        return
    else:
        with pytest.raises(ModelIdentityError, match="OUTPUT_LIMIT"):
            bridge.artifact(
                registration,
                "unused",
                {
                    key: "x" * 2_000_001
                    for key in cast(list[str], registration["fit_keys"])
                },
            )
        return
    with pytest.raises(ModelIdentityError):
        bridge.verify(user, registration)


def test_actual_lifecycle_and_result_method_gate_computation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, user = setup(tmp_path)
    job, config, payload = registered(bridge, user, "CRP-01")
    exp = bridge.lab.begin_run(config, payload, name="Synthetic execution boundaries")
    bridge.state.bind(job.id, exp)
    active = bridge.state.job(user, job.id)
    import quant_hunter.research_methods.studies as numerical

    monkeypatch.setattr(numerical, "execute_study", lambda *a: {"study_id": "CRP-02"})
    with pytest.raises(ModelIdentityError, match="JOB_EXPERIMENT"):
        bridge.execute_study(user, active, "foreign", config, payload)
    with pytest.raises(ModelIdentityError, match="RESULT_BINDING"):
        bridge.execute_study(user, active, exp, config, payload)
    monkeypatch.setattr(
        numerical,
        "execute_study",
        lambda *a: {"study_id": "CRP-01", "fitted_model": {"made_up": True}},
    )
    with pytest.raises(ModelIdentityError, match="UNREGISTERED_STUDY_FIT"):
        bridge.execute_study(user, active, exp, config, payload)
    bridge.lab.fail_run(exp, "SyntheticFailure")
    with pytest.raises(ModelIdentityError, match="ITEM8_BINDING"):
        bridge.execute_study(user, active, exp, config, payload)
    with pytest.raises(AccessError, match="Owned bound"):
        bridge.inspect(user, replace(active, experiment_id=None))


def test_operational_family_alias_cannot_replace_canonical_definition(
    tmp_path: Path,
) -> None:
    bridge, user = setup(tmp_path)
    job, _, _ = registered(bridge, user)
    bridge.state.finish(job.id, error="SyntheticStopBeforeEvaluation")
    with bridge.state.connection() as db:
        db.execute(
            "UPDATE model_identity_family SET record_digest=?", ("sha256:" + "f" * 64,)
        )
    with pytest.raises(ModelIdentityError, match="FAMILY_BINDING"):
        registered(bridge, user)
