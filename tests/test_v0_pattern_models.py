"""Permanent recipe/fit IDs precede actual learned computation and never imply validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from math import sqrt
from typing import Any, cast

import pytest
from test_v0_pattern_workflows import Harness, make

from quant_hunter.config import JsonRecord, parse_json_document
from quant_hunter.identity import RegistryKind
from quant_hunter.patterns import product
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.web.state import AccessError


@pytest.fixture(scope="module")
def h(tmp_path_factory: pytest.TempPathFactory) -> Harness:
    return make(tmp_path_factory.mktemp("pattern-models"))


@pytest.mark.parametrize("family", ["PAT-03", "PAT-04", "PAT-05", "PAT-06", "PAT-09"])
def test_actual_learned_models_are_registered_before_lab_and_compute(
    h: Harness, monkeypatch: pytest.MonkeyPatch, family: str
) -> None:
    prepared = h.prepare(family)
    recipe = prepared["model_recipe"]
    assert recipe["model_id"].startswith("MOD-")
    pattern = h.access.lab.registry.verify_object(prepared["pattern_id"])[-1].record
    definition = cast(
        dict[str, Any], parse_json_document(cast(str, pattern["definition"]))
    )
    assert definition["model_recipe"] == recipe
    begin = h.access.lab.begin_run
    execute = h.access.product.execute_registered
    seen: list[str] = []

    def before_lab(config: Any, data: bytes, **kwargs: Any) -> str:
        fit = config["model_fit"]
        assert fit["model_id"] != recipe["model_id"]
        record = h.access.lab.registry.verify_object(fit["model_id"])[-1].record
        assert record["object_type"] == "MODEL" and record["status"] == "PROPOSED"
        assert record["parent_ids"] == [recipe["model_id"]]
        assert cast(dict[str, Any], record["decision"])["status"] == "PENDING"
        assert config["model_recipe"] == recipe
        assert cast(dict[str, Any], parse_json_document(data))["model_fit"] == fit
        seen.append("registered_before_lab")
        return begin(config, data, **kwargs)

    def before_compute(*args: Any, **kwargs: Any) -> JsonRecord:
        assert seen == ["registered_before_lab"]
        binding = kwargs["binding"]
        run = h.access.lab.get_run(binding.experiment_id)
        assert run["lifecycle_status"] == "RUNNING" and run["variants_attempted"] == 0
        h.access.models.verify_fit(
            h.users["owner"],
            cast(JsonRecord, run["configuration"])["model_fit"],
            prepared,
            next(
                job.id
                for job in h.access.state.jobs(h.users["owner"])
                if job.experiment_id == binding.experiment_id
            ),
        )
        seen.append("compute_after_freeze")
        return execute(*args, **kwargs)

    monkeypatch.setattr(h.access.lab, "begin_run", before_lab)
    monkeypatch.setattr(h.access.product, "execute_registered", before_compute)
    result = h.execute(prepared)
    assert seen == ["registered_before_lab", "compute_after_freeze"]
    assert result["job"]["status"] == "SUCCEEDED"
    output = result["run"]["result"]
    assert (
        output["model_recipe"] == recipe and output["model_fit"] == result["model_fit"]
    )
    artifact = output["model_artifact"]
    retained = h.access.models._read(artifact["artifact_digest"])
    assert retained["fit"] == output["model_fit"]
    if output["method"]["status"] == "EXECUTED":
        assert retained["trained_parameters"] == output["method"]["output"]["model"]
    else:
        assert retained["trained_parameters"] is None
    assert result["run"]["variants_attempted"] == 1
    assert result["run"]["evaluation_outcome"] == "INCONCLUSIVE"


def test_refit_and_new_recipe_have_distinct_ids_shared_family(h: Harness) -> None:
    prepared = h.prepare("PAT-05")
    first, second = h.execute(prepared), h.execute(prepared)
    another = h.prepare("PAT-05")
    assert first["model_fit"]["model_id"] != second["model_fit"]["model_id"]
    assert first["job"]["experiment_id"] != second["job"]["experiment_id"]
    assert first["run"]["result"]["method"] == second["run"]["result"]["method"]
    assert prepared["model_recipe"]["model_id"] != another["model_recipe"]["model_id"]
    assert prepared["model_recipe"]["family_id"] == another["model_recipe"]["family_id"]
    assert first["model_fit"]["family_id"] == prepared["model_recipe"]["family_id"]
    with pytest.raises(PatternError, match="MODEL_BINDING"):
        h.access.models.verify_fit(
            h.users["owner"], first["model_fit"], prepared, second["job"]["id"]
        )


def test_failed_actual_fit_retains_model_and_counted_experiment(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare("PAT-06")
    monkeypatch.setattr(
        product,
        "fit_hmm",
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("injected private fit failure")
        ),
    )
    result = h.execute(prepared)
    assert result["job"]["status"] == "FAILED"
    assert result["run"]["evaluation_outcome"] == "FAILED"
    assert result["run"]["variants_attempted"] == 1
    fit = result["model_fit"]
    assert fit["model_id"].startswith("MOD-")
    assert h.access.lab.registry.verify_object(fit["model_id"])[-1].record[
        "parent_ids"
    ] == [prepared["model_recipe"]["model_id"]]
    assert result["run"]["configuration"]["model_fit"] == fit
    assert "private fit failure" not in str(result)


def test_failed_preparation_retains_recipe_identity(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        h.access.product,
        "prepare",
        lambda *a, **k: (_ for _ in ()).throw(
            PatternError("INJECTED_PREPARATION_FAILURE")
        ),
    )
    with pytest.raises(PatternError):
        h.prepare("PAT-05")
    operation = next(
        row
        for row in h.access.quality.data.operations(h.users["owner"])
        if row["kind"] == "PATTERN_PREPARE"
    )
    assert operation["status"] == "FAILED"
    recipe = cast(dict[str, Any], operation["result"])["model_recipe"]
    assert (
        h.access.lab.registry.verify_object(recipe["model_id"])[-1].record["status"]
        == "PROPOSED"
    )


def test_wrong_recipe_fit_and_foreign_owner_rejected(h: Harness) -> None:
    first, second = h.prepare("PAT-05"), h.prepare("PAT-05")
    queued = h.access.enqueue(h.users["owner"], first["prepared_id"])
    claimed = h.access.state.claim()
    assert claimed and claimed.id == queued.id
    fit = h.access.models.fit(h.users["owner"], first, claimed)
    with pytest.raises(PatternError, match="MODEL_BINDING"):
        h.access.models.verify_fit(h.users["owner"], fit, second, queued.id)
    with pytest.raises(AccessError, match="not owned"):
        h.access.models.verify_fit(h.users["other"], fit, first, queued.id)
    with pytest.raises(AccessError):
        h.access.models.fit(h.users["other"], first, claimed)
    with pytest.raises(PatternError, match="MODEL_BINDING"):
        h.access.models.verify_fit(h.users["owner"], fit, first, "1" * 32)
    h.access.state.finish(queued.id, error="Synthetic direct factory test complete")
    wrong = deepcopy(first)
    wrong["configuration"]["seed"] = 8
    with pytest.raises(PatternError, match="MODEL_BINDING"):
        h.access.models.verify_recipe(
            h.users["owner"],
            wrong["model_recipe"],
            wrong["configuration"],
            wrong["corpus"],
            wrong["secondary_corpus"],
            code_revision=h.access.lab.code_revision,
            method_profile={
                "expanded_method_parameters": wrong["expanded_method_parameters"],
                "method_input_schema": wrong["method_input_schema"],
            },
        )


@pytest.mark.parametrize("field", ["model_recipe", "model_fit", "model_artifact"])
def test_successful_retained_model_edges_are_mandatory(
    h: Harness, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    result = h.execute(h.prepare("PAT-05"))
    original = h.access.lab.get_run

    def missing(identity: str) -> JsonRecord:
        value = original(identity)
        cast(JsonRecord, value["result"]).pop(field)
        return value

    monkeypatch.setattr(h.access.lab, "get_run", missing)
    with pytest.raises(PatternError, match="MODEL_RESULT_BINDING"):
        h.access.job(h.users["owner"], result["job"]["id"])


def test_fitted_artifact_substitution_is_rejected(h: Harness) -> None:
    result = h.execute(h.prepare("PAT-06"))["run"]["result"]
    substituted = deepcopy(result)
    substituted["method"]["output"]["model"]["threshold"] = 999
    with pytest.raises(PatternError, match="ARTIFACT_BINDING"):
        h.access.models.verify_artifact(
            result["model_fit"], result["model_artifact"], substituted
        )


@pytest.mark.parametrize("kind", ["code", "environment"])
def test_stale_execution_version_fails_before_new_fit_or_experiment(
    h: Harness, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    prepared = h.prepare("PAT-05")
    monkeypatch.setattr(
        h.access.models,
        "fit",
        lambda *a: pytest.fail("fit registered against stale preparation"),
    )
    if kind == "code":
        monkeypatch.setattr(h.access.lab, "code_revision", "1" * 40)
    else:
        monkeypatch.setattr(
            h.access.lab,
            "environment_digest",
            h.access.lab.objects.publish(b'{"other_environment":true}').digest,
        )
    result = h.execute(prepared)
    assert result["job"]["status"] == "FAILED"
    assert result["job"]["experiment_id"] is None and result["run"] is None
    assert result["model_fit"] is None


def test_nonlearned_diagnostics_and_paa_do_not_invent_models(h: Harness) -> None:
    prepared = h.prepare("PAT-15")
    result = h.execute(prepared)
    assert prepared["model_recipe"] is None
    assert result["model_fit"] is None
    assert result["run"]["result"]["model_artifact"] is None
    assert (
        result["run"]["result"]["method"]["output"]["optional_status"]
        == "NOT_INSTALLED_UNVALIDATED"
    )


@pytest.mark.parametrize("field", ["source", "dataset", "code"])
def test_rehashed_model_cannot_change_repeated_data_or_producer(
    h: Harness, field: str
) -> None:
    prepared = h.prepare("PAT-05")
    original = h.access.lab.registry.verify_object(
        prepared["model_recipe"]["model_id"]
    )[-1].record
    record = deepcopy(original)
    for key in ("object_id", "revision", "previous_revision_digest"):
        record.pop(key)
    if field == "code":
        cast(JsonRecord, record["implementation"])["code_revision"] = "f" * 40
    elif field == "source":
        cast(JsonRecord, record["data_requirements"])["source_ids"] = [
            h.datasets[1]["source_id"]
        ]
    else:
        cast(JsonRecord, record["data_requirements"])["dataset_ids"] = [
            h.corpora[1]["dataset_id"]
        ]
    changed = h.access.lab.registry.allocate(RegistryKind.MODEL, record)
    binding = {
        **prepared["model_recipe"],
        "model_id": changed.object_id,
        "record_digest": changed.revision.digest,
    }
    with pytest.raises(PatternError, match=r"MODEL_(DATA_)?BINDING"):
        h.access.models.verify_recipe(
            h.users["owner"],
            binding,
            prepared["configuration"],
            prepared["corpus"],
            prepared["secondary_corpus"],
            code_revision=h.access.lab.code_revision,
            method_profile={
                "expanded_method_parameters": prepared["expanded_method_parameters"],
                "method_input_schema": prepared["method_input_schema"],
            },
        )


def test_cusum_explicit_volume_projection_has_independent_mean_oracle(
    h: Harness,
) -> None:
    corpus, _ = h.access._corpus(h.users["owner"], h.corpora[0]["dataset_id"])
    config = replace(
        h.access.scenario_config(corpus, "PAT-05", "BASELINE"),
        method_parameters_json='{"feature_index":4}',
    )
    prepared = cast(
        dict[str, Any],
        h.access.prepare(h.users["owner"], corpus.dataset_id, config=config),
    )
    schema = prepared["method_input_schema"]
    assert schema["feature_index"] == 4 and schema["method_feature_columns"] == [
        "volume"
    ]
    assert schema["source_feature_columns"] == h.corpora[0]["feature_columns"]
    assert prepared["expanded_method_parameters"]["feature_index"] == 4
    result = h.execute(prepared)["run"]["result"]
    assert result["method"]["status"] == "EXECUTED"
    model = result["method"]["output"]["model"]
    assert model["features"] == ["volume"] and model["training_rows"] == 128
    assert model["mean"] == pytest.approx(sum(100 + i % 11 for i in range(128)) / 128)
    assert result["method_input_schema"] == schema
    assert result["exposure"]["method_internal"]["method_input_schema"] == schema


def test_haar_explicit_close_projection_has_independent_sum_oracle(h: Harness) -> None:
    prepared = h.prepare("PAT-07")
    result = h.execute(prepared)["run"]["result"]
    assert result["method"]["status"] == "EXECUTED"
    assert result["method_input_schema"]["method_feature_columns"] == ["close"]
    closing = [
        100 + ((i % 24) - 12) / 100 + ((i % 5) - 2) / 100 for i in range(208, 240)
    ]
    assert result["method"]["output"]["haar_approximation"] == pytest.approx(
        sum(closing) / sqrt(32)
    )
    assert result["model_fit"] is None


@pytest.mark.parametrize("index", [7, -1, 1.5, True])
def test_projection_rejects_unknown_column_before_model_registration(
    h: Harness, monkeypatch: pytest.MonkeyPatch, index: Any
) -> None:
    import json

    corpus, _ = h.access._corpus(h.users["owner"], h.corpora[0]["dataset_id"])
    base = h.access.scenario_config(corpus, "PAT-05", "BASELINE")
    monkeypatch.setattr(
        h.access.models,
        "recipe",
        lambda *a, **k: pytest.fail("model before valid projection"),
    )
    with pytest.raises(PatternError):
        config = replace(
            base, method_parameters_json=json.dumps({"feature_index": index})
        )
        h.access.prepare(h.users["owner"], corpus.dataset_id, config=config)
