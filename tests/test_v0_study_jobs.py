"""Actual mathematical studies run only after canonical preregistration/freezing."""

from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from test_v0_runtime import REPOSITORY, runner_at
from test_v0_web import PASSWORD, setup

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.research_methods import studies
from quant_hunter.web.api import create_app
from quant_hunter.web.studies import catalogue, prepare_job, request_config


@pytest.mark.parametrize("study_id", [item.study_id for item in studies.list_studies()])
def test_actual_study_is_frozen_before_fit_and_permanently_inconclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, study_id: str
) -> None:
    runner = runner_at(tmp_path)
    owner = runner.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    compute = studies.execute_study
    invocations = 0

    def inspected(payload: bytes, config: JsonRecord) -> JsonRecord:
        nonlocal invocations
        invocations += 1
        run = runner.lab.list_runs()[0]
        identity = str(run["experiment_id"])
        chain = runner.lab.registry.verify_object(identity)
        assert [r.record["lifecycle_status"] for r in chain] == [
            "DRAFT",
            "REGISTERED",
            "FROZEN",
            "RUNNING",
        ]
        assert chain[-1].record["random_seed"] == config["random_seed"]
        assert (
            chain[-1].record["feature_definitions"]
            == cast(JsonRecord, config["software_method"])["implemented_scope"]
        )
        partitions = cast(JsonRecord, chain[-1].record["partitions"])
        assert (
            cast(JsonRecord, partitions["training"])["end"]
            == config["training_end_exclusive"]
        )
        bindings = cast(JsonRecord, run["bindings"])
        assert (
            runner.lab.objects.get(str(bindings["dataset_digest"])).path.read_bytes()
            == payload
        )
        assert runner.lab.objects.get(
            str(bindings["configuration_digest"])
        ).path.read_bytes() == canonicalize_json(config)
        return compute(payload, config)

    monkeypatch.setattr(studies, "execute_study", inspected)
    job = runner.state.enqueue(owner, request_config(study_id, "POSITIVE"))
    assert runner.process_one()
    finished = runner.state.job(owner, job.id)
    assert finished.status == "SUCCEEDED", finished.error
    run = runner.lab.get_run(str(finished.experiment_id))
    assert (
        run["evaluation_outcome"] == "INCONCLUSIVE" and run["variants_attempted"] == 1
    )
    assert run["decision"] is None and invocations == 1
    result = cast(JsonRecord, run["result"])
    assert (
        result["assessment"] == "EMPIRICALLY_UNVALIDATED"
        and result["study_id"] == study_id
    )
    assert result["input_digest"] == cast(JsonRecord, run["bindings"])["dataset_digest"]
    assert (
        result["config_digest"]
        == cast(JsonRecord, run["bindings"])["configuration_digest"]
    )
    assert not runner.process_one()
    reopened = runner_at(tmp_path)
    reopened.recover()
    assert reopened.state.job(owner, job.id).status == "SUCCEEDED"
    assert invocations == 1


@pytest.mark.parametrize("study_id", ["CRP-05", "CRP-07", "CRP-08"])
def test_degenerate_null_is_failed_once_and_retry_counts_separately(
    tmp_path: Path, study_id: str
) -> None:
    runner = runner_at(tmp_path)
    owner = runner.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    for _ in range(2):
        job = runner.state.enqueue(owner, request_config(study_id, "NULL"))
        assert runner.process_one()
        failed = runner.state.job(owner, job.id)
        assert failed.status == "FAILED" and failed.experiment_id
        run = runner.lab.get_run(failed.experiment_id)
        assert run["evaluation_outcome"] == "FAILED" and run["variants_attempted"] == 1
    runs = runner.lab.list_runs()
    assert len(runs) == 2
    assert (
        len({str(cast(JsonRecord, run["bindings"])["family_id"]) for run in runs}) == 1
    )
    assert sum(cast(int, run["variants_attempted"]) for run in runs) == 2


def test_study_api_admission_and_roles(tmp_path: Path) -> None:
    app = create_app(tmp_path / "runtime", REPOSITORY, process_job=lambda: False)
    with TestClient(app) as client:
        assert client.get("/api/studies").status_code == 401
        headers = setup(client)
        assert len(client.get("/api/studies").json()["studies"]) == 12
        assert (
            client.post(
                "/api/studies/jobs",
                headers={"X-QH-Request": "1"},
                json={"study_id": "CRP-01"},
            ).status_code
            == 403
        )
        for change in (
            {"study_id": "CRP-99"},
            {"scenario": "OPTIMIZE"},
            {"parameter": "NaN"},
            {"parameter": "99"},
            {"random_seed": 991},
        ):
            response = client.post(
                "/api/studies/jobs",
                headers=headers,
                json={"study_id": "CRP-01", **change},
            )
            assert response.status_code == 422
        queued = client.post(
            "/api/studies/jobs",
            headers=headers,
            json={"study_id": "CRP-01", "scenario": "SENSITIVITY", "parameter": "0.2"},
        )
        assert (
            queued.status_code == 202 and queued.json()["config"]["kind"] == "CRP_STUDY"
        )
        for role in ("researcher", "reader"):
            client.post(
                "/api/users",
                headers=headers,
                json={"username": role, "password": PASSWORD, "role": role},
            )
        client.post("/api/logout", headers=headers)
        for role in ("researcher", "reader"):
            login = client.post(
                "/api/login",
                headers={"X-QH-Request": "1"},
                json={"username": role, "password": PASSWORD},
            )
            other = {"X-QH-Request": "1", "X-CSRF-Token": login.json()["csrf"]}
            assert client.get(f"/api/jobs/{queued.json()['id']}").status_code == 403
            response = client.post(
                "/api/studies/jobs", headers=other, json={"study_id": "CRP-01"}
            )
            assert response.status_code == (202 if role == "researcher" else 403)
            client.post("/api/logout", headers=other)


def test_invalid_operational_study_configs_cannot_run() -> None:
    assert len(catalogue()) == 12
    for config in ({"kind": "OTHER"}, {"kind": "CRP_STUDY", "secret": "refused"}):
        with pytest.raises(ValueError):
            prepare_job(cast(dict[str, str | int], config))
    for identity, scenario, parameter in (
        ("BAD", "POSITIVE", None),
        ("CRP-01", "BAD", None),
        ("CRP-01", "POSITIVE", "garbage"),
        ("CRP-01", "POSITIVE", "Infinity"),
    ):
        with pytest.raises(ValueError):
            request_config(identity, scenario, parameter)
