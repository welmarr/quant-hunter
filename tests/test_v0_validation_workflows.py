"""Actual owned quality bytes, canonical Item8 attempts and independent math oracles."""

from __future__ import annotations

import io
import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from fastapi import FastAPI, HTTPException, Request
from test_v0_data_quality import CODE, SCHEMAS
from test_v0_publication_workflows import LocalClient
from test_v0_quality_workflows import NoNetwork

from quant_hunter.config import JsonRecord, canonicalize_json, parse_json_document
from quant_hunter.data_quality import QualityService, SelectedSnapshot
from quant_hunter.imports import ImportService
from quant_hunter.lab import LabService
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.provenance.hashing import sha256_bytes
from quant_hunter.research_validation import ResearchValidationError
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.state import AccessError, AppState, Job, Session, User
from quant_hunter.web.validation_access import KIND, ValidationAccess
from quant_hunter.web.validation_jobs import (
    ValidationControls,
    cost_number,
    fit_model,
    fit_outputs,
    instant,
    observations,
    prepare,
    table,
)
from quant_hunter.web.validation_routes import install_validation_routes


@dataclass
class Harness:
    access: ValidationAccess
    client: LocalClient
    users: dict[str, User]
    dataset: JsonRecord

    def controls(self, **changes: Any) -> ValidationControls:
        values = {"evaluation_as_of": "2026-10-05T23:00:00Z", **changes}
        return ValidationControls(**values)

    def body(self, **changes: Any) -> JsonRecord:
        return {
            "dataset_id": self.dataset["dataset_id"],
            "record_digest": self.dataset["record_digest"],
            "quality_report_digest": self.dataset["quality_report_digest"],
            "controls": cast(JsonRecord, asdict(self.controls(**changes))),
        }

    def submit(self, **changes: Any) -> Job:
        response = self.client.post("/api/validations/jobs", json=self.body(**changes))
        assert response.status_code == 202, response.text
        return self.access.state.job(self.users["owner"], response.json()["id"])

    def run(self, **changes: Any) -> tuple[Job, JsonRecord]:
        queued = self.submit(**changes)
        claimed = self.access.state.claim()
        assert claimed is not None and claimed.id == queued.id
        self.access.execute_job(claimed)
        return claimed, self.access.get(
            self.users["owner"], claimed.id, include_report=True
        )


@pytest.fixture
def h(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    lab = LabService(tmp_path / "lab", SCHEMAS, CODE, {"synthetic_software_test": True})
    state = AppState(tmp_path / "state.sqlite3")
    users = {
        name: state.create_user(
            name,
            "synthetic password",
            cast(Literal["owner", "researcher", "reader"], role),
            bootstrap=name == "owner",
        )
        for name, role in (
            ("owner", "owner"),
            ("other", "researcher"),
            ("reader", "reader"),
        )
    }
    service = QualityService(
        lab.registry, lab.objects, SCHEMAS, CODE, lab.environment_digest
    )
    data = DataAccess(
        state,
        tmp_path,
        ImportService(lab.registry, lab.objects, SCHEMAS, CODE, lab.environment_digest),
        NoNetwork(),
    )
    monkeypatch.setattr(data, "_capacity", lambda: None)
    quality = QualityAccess(state, service, data, InstrumentRegistry(lab.registry))
    dataset = cast(list[JsonRecord], quality.demo(users["owner"])["datasets"])[0]
    access = ValidationAccess(state, lab, quality)
    app = FastAPI()

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        name = request.headers.get("x-test-user", "")
        if name not in users:
            raise HTTPException(401, "Sign in")
        if mutation and request.headers.get("x-csrf-token") != "synthetic-csrf":
            raise HTTPException(403, "CSRF")
        return Session(users[name], "synthetic-csrf")

    install_validation_routes(app, authenticated, access, worker_available=lambda: True)
    client = LocalClient(app)
    client.headers.update({"x-test-user": "owner", "x-csrf-token": "synthetic-csrf"})
    return Harness(access, client, users, dataset)


def test_prepare_snapshot_has_real_temporal_plan(h: Harness) -> None:
    row = h.dataset
    snapshot, raw = h.access.quality.selected(
        h.users["owner"],
        cast(str, row["dataset_id"]),
        record_digest=cast(str, row["record_digest"]),
        quality_report_digest=cast(str, row["quality_report_digest"]),
        purpose="RESEARCH_CAUSAL",
    )
    manifest, plan = prepare(snapshot, raw, h.controls())
    plan.verify()
    assert manifest["plan_digest"] == plan.digest


def test_prepare_is_no_fit_and_actual_mean_job_is_counted(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant_hunter.web.validation_jobs as jobs

    original = jobs.fit_model

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("fitting occurred before Item8 begin")

    monkeypatch.setattr(jobs, "fit_model", forbidden)
    queued = h.submit()
    assert h.access.lab.list_runs() == []
    monkeypatch.setattr(jobs, "fit_model", original)
    claimed = h.access.state.claim()
    assert claimed is not None
    h.access.execute_job(claimed)
    value = h.access.get(h.users["owner"], queued.id, include_report=True)
    run = cast(JsonRecord, value["run"])
    assert cast(JsonRecord, value["job"])["status"] == "SUCCEEDED", value
    assert (
        run["variants_attempted"] == 1 and run["evaluation_outcome"] == "INCONCLUSIVE"
    )
    assert cast(JsonRecord, run["variant_accounting"])["ai_generated_attempts"] == 1
    result = cast(JsonRecord, run["result"])
    assert (
        result["model"] == "TRAIN_MEAN" and result["empirical_status"] == "INCONCLUSIVE"
    )
    folds = cast(list[JsonRecord], cast(JsonRecord, value["report"])["folds"])
    assert all(fold["status"] == "COMPUTED_SOFTWARE_ONLY" for fold in folds)
    assert cast(JsonRecord, result["multiple_testing"])["adjusted_p_values"] is None
    assert (
        cast(JsonRecord, cast(JsonRecord, run["configuration"])["model_registration"])[
            "source_digest"
        ]
        == queued.config["submission_manifest_digest"]
    )
    assert (
        cast(JsonRecord, run["bindings"])["dataset_digest"]
        != queued.config["submission_manifest_digest"]
    )


def test_ols_and_mean_are_two_actual_attempts(h: Harness) -> None:
    _, first = h.run(model="TRAIN_MEAN")
    _, second = h.run(model="OLS_LAG_RETURNS")
    assert (
        cast(JsonRecord, first["job"])["status"]
        == cast(JsonRecord, second["job"])["status"]
        == "SUCCEEDED"
    ), second
    assert (
        cast(JsonRecord, first["run"])["experiment_id"]
        != cast(JsonRecord, second["run"])["experiment_id"]
    )
    assert (
        sum(cast(int, row["variants_attempted"]) for row in h.access.lab.list_runs())
        == 2
    )


def test_each_actual_fold_fit_has_distinct_canonical_identity_before_computation(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant_hunter.web.validation_jobs as jobs

    original = jobs.fit_model
    seen: list[str] = []

    def checked(
        model: str, x: tuple[tuple[float, ...], ...], y: tuple[float, ...]
    ) -> Any:
        runs = h.access.lab.list_runs()
        assert len(runs) == 1
        run = h.access.lab.get_run(cast(str, runs[0]["experiment_id"]))
        assert run["lifecycle_status"] == "RUNNING" and run["variants_attempted"] == 0
        registration = cast(
            JsonRecord, cast(JsonRecord, run["configuration"])["model_registration"]
        )
        h.access.models.verify(h.users["owner"], registration, current=True)
        fits = cast(list[JsonRecord], registration["fits"])
        assert [row["fit_key"] for row in fits] == [
            "fold-1:standardizer",
            "fold-1:estimator",
            "fold-2:standardizer",
            "fold-2:estimator",
        ]
        ids = [cast(str, cast(JsonRecord, row["binding"])["model_id"]) for row in fits]
        assert len(set(ids)) == 4
        seen.append(ids[len(seen) * 2 + 1])
        return original(model, x, y)

    monkeypatch.setattr(jobs, "fit_model", checked)
    _, value = h.run(model="OLS_LAG_RETURNS")
    assert cast(JsonRecord, value["job"])["status"] == "SUCCEEDED", value
    assert len(set(seen)) == 2
    folds = cast(list[JsonRecord], cast(JsonRecord, value["report"])["folds"])
    assert all(
        cast(JsonRecord, fold["fitted_parameters"])["model"] == "OLS_LAG_RETURNS"
        for fold in folds
    )
    result = cast(JsonRecord, cast(JsonRecord, value["run"])["result"])
    artifact = cast(JsonRecord, result["canonical_models"])
    retained = cast(
        JsonRecord,
        parse_json_document(
            h.access.lab.objects.read_bytes(cast(str, artifact["artifact_digest"]))
        ),
    )
    outputs = cast(JsonRecord, retained["outputs"])
    assert outputs["fold-1:estimator"] == folds[0]["fitted_parameters"]
    assert (
        cast(JsonRecord, outputs["fold-1:standardizer"])["means"]
        == cast(JsonRecord, folds[0]["fitted_parameters"])["means"]
    )


def test_independent_ols_and_mean_oracles() -> None:
    features = tuple((float(i),) for i in range(1, 6))
    labels = tuple(3 + 2 * row[0] for row in features)
    model = fit_model("OLS_LAG_RETURNS", features, labels)
    assert model((6.0,)) == pytest.approx(15.0)
    assert fit_model("TRAIN_MEAN", features, labels)((-999.0,)) == 9.0
    with pytest.raises(ResearchValidationError, match="RANK"):
        fit_model(
            "OLS_LAG_RETURNS",
            tuple((float(i), float(i)) for i in range(6)),
            tuple(float(i) for i in range(6)),
        )
    with pytest.raises(ResearchValidationError, match="DEGENERATE"):
        fit_model("OLS_LAG_RETURNS", ((1.0,), (1.0,)), (1.0, 2.0))


@pytest.mark.parametrize(
    "edge", ["fold_order", "missing_fitted", "invented_pending", "wrong_estimator"]
)
def test_fold_artifact_cannot_invent_or_omit_training(edge: str) -> None:
    controls = ValidationControls(evaluation_as_of="2026-10-05T23:00:00Z", folds=1)
    parameters: JsonRecord = {"model": "TRAIN_MEAN", "mean": 0.1, "training_count": 20}
    fold: JsonRecord = {
        "fold_id": "fold-1",
        "status": "COMPUTED_SOFTWARE_ONLY",
        "fitted_parameters": parameters,
    }
    if edge == "fold_order":
        fold["fold_id"] = "fold-2"
    elif edge == "missing_fitted":
        fold["fitted_parameters"] = None
    elif edge == "invented_pending":
        fold["status"] = "PENDING"
    else:
        parameters["model"] = "OLS_LAG_RETURNS"
    with pytest.raises(ResearchValidationError, match="FIT_ARTIFACT_BINDING"):
        fit_outputs({"folds": [fold]}, controls)


def test_ownership_reader_csrf_and_forged_job(h: Harness) -> None:
    job = h.submit()
    h.client.headers["x-test-user"] = "other"
    assert h.client.get(f"/api/validations/jobs/{job.id}").status_code == 403
    assert h.client.post("/api/validations/jobs", json=h.body()).status_code == 403
    assert h.client.get("/api/validations/jobs").json() == {"jobs": []}
    h.client.headers["x-test-user"] = "reader"
    assert h.client.post("/api/validations/jobs", json=h.body()).status_code == 403
    h.client.headers["x-test-user"] = "owner"
    h.client.headers["x-csrf-token"] = "wrong"
    assert h.client.post("/api/validations/jobs", json=h.body()).status_code == 403
    claimed = h.access.state.claim()
    assert claimed is not None
    with pytest.raises(AccessError):
        h.access.execute_job(replace(claimed, owner_id=h.users["other"].id))
    assert h.access.lab.list_runs() == []


def test_rehashed_manifest_cannot_change_frozen_description(h: Harness) -> None:
    job = h.submit()
    original = cast(str, job.config["submission_manifest_digest"])
    manifest = cast(
        JsonRecord, parse_json_document(h.access.lab.objects.read_bytes(original))
    )
    manifest["planned_fitted_candidates"] = 0
    digest = h.access.lab.objects.publish(canonicalize_json(manifest)).digest
    with h.access.state.connection() as db:
        db.execute(
            "UPDATE jobs SET config=? WHERE id=?",
            (json.dumps({"kind": KIND, "submission_manifest_digest": digest}), job.id),
        )
    with pytest.raises(ResearchValidationError, match="REPLAY"):
        h.access.get(h.users["owner"], job.id)


def test_interrupted_fit_is_not_replayed_and_counts_failure(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant_hunter.web.validation_jobs as jobs

    def stop(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(jobs, "fit_model", stop)
    job = h.submit()
    claimed = h.access.state.claim()
    assert claimed is not None
    with pytest.raises(KeyboardInterrupt):
        h.access.execute_job(claimed)
    interrupted = h.access.state.job(h.users["owner"], job.id)
    assert interrupted.experiment_id is not None
    result = h.access.lab.recover_run(interrupted.experiment_id)
    h.access.state.finish(job.id, error="WorkerInterrupted")
    assert (
        result["variants_attempted"] == 1 and result["evaluation_outcome"] == "FAILED"
    )
    with pytest.raises(AccessError):
        h.access.execute_job(claimed)


def test_insufficient_and_pending_folds_remain_unfitted(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant_hunter.web.validation_jobs as jobs

    def stop(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("insufficient fold fit")

    monkeypatch.setattr(jobs, "fit_model", stop)
    _, value = h.run(minimum_train=9999)
    result = cast(JsonRecord, cast(JsonRecord, value["run"])["result"])
    assert all(
        row["status"] == "INCONCLUSIVE"
        for row in cast(list[JsonRecord], result["folds"])
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("lookback", 0),
        ("seed", True),
        ("folds", 6),
        ("model", "AUTOTUNE"),
        ("commission_bps", "NaN"),
        ("evaluation_as_of", "2025-01-01T00:00:00"),
    ],
)
def test_closed_invalid_controls_no_trial(
    h: Harness, field: str, value: object
) -> None:
    body = h.body()
    cast(dict[str, object], body["controls"])[field] = value
    response = h.client.post("/api/validations/jobs", json=body)
    assert response.status_code in (400, 422)
    assert h.access.lab.list_runs() == []


def small_source(
    *,
    prices: list[float] | None = None,
    delay: int | None = None,
    gap: bool = False,
    missing_column: bool = False,
) -> tuple[SelectedSnapshot, bytes]:
    """Pure adapter vectors: IDs are only inert typed references, not registry claims."""
    start = datetime.fromisoformat("2025-01-06T14:30:00Z")
    closes = [
        start + timedelta(minutes=i + 1 + (int(gap) if i >= 30 else 0))
        for i in range(80)
    ]
    available = list(closes)
    if delay is not None:
        available[delay] += timedelta(days=3)
    values: dict[str, Any] = {"close_at": closes, "available_at": available}
    if not missing_column:
        values["close"] = prices or [100 + i / 10 for i in range(80)]
    buffer = io.BytesIO()
    pq.write_table(pa.table(values), buffer)
    raw = buffer.getvalue()
    digest = "sha256:" + "a" * 64
    return SelectedSnapshot(
        "DATASET-01990f30-7f5e-7b34-9b21-3d74c513c848",
        digest,
        sha256_bytes(raw),
        digest,
        "INSTRUMENT-01990f30-7f5e-7b34-9b21-3d74c513c848",
        digest,
        digest,
        80,
        {
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": closes[-1].isoformat().replace("+00:00", "Z"),
        },
        60_000_000_000,
        ("close",),
        "SYNTHETIC",
        "SYNTHETIC_SOFTWARE_ONLY",
        True,
        (),
    ), raw


def small_controls(**changes: Any) -> ValidationControls:
    return ValidationControls(
        **{"evaluation_as_of": "2025-01-07T00:00:00Z", "training_rows": 40, **changes}
    )


def test_delayed_numeric_values_are_unread_and_gaps_never_imputed() -> None:
    prices = [100 + i / 10 for i in range(80)]
    prices[60] = float("nan")
    snapshot, raw = small_source(prices=prices, delay=60)
    rows, _ = observations(snapshot, raw, small_controls())
    by_id = {r.timing.row_id: r for r in rows}
    assert math.isnan(by_id["row-59"].label)
    assert all(math.isnan(x) for x in by_id["row-60"].features)
    assert by_id["row-59"].timing.label_available_at > instant(
        small_controls().evaluation_as_of
    )
    # Once the unavailable numeric value is actually observed, invalidity is not hidden.
    with pytest.raises(ResearchValidationError, match="PRICE_RANGE"):
        observations(
            snapshot, raw, small_controls(evaluation_as_of="2025-01-10T00:00:00Z")
        )
    snapshot, raw = small_source(gap=True)
    rows, exclusions = observations(snapshot, raw, small_controls())
    assert "row-30" not in {r.timing.row_id for r in rows}
    assert {
        "row_id": "row-30",
        "reason": "NONCONTIGUOUS_SUPPORT_NO_IMPUTATION",
    } in exclusions


def test_future_perturbations_do_not_change_training_vectors_or_fit() -> None:
    source, raw = small_source()
    changed, other = small_source(
        prices=[100 + i / 10 if i < 45 else 10000 + i for i in range(80)]
    )
    before, _ = observations(source, raw, small_controls())
    after, _ = observations(changed, other, small_controls())
    train_before = tuple(
        r for r in before if r.timing.decision_at < instant("2025-01-06T15:00:00Z")
    )
    train_after = tuple(
        r for r in after if r.timing.decision_at < instant("2025-01-06T15:00:00Z")
    )
    assert train_before == train_after

    def fit(rows: Any) -> Any:
        return fit_model(
            "TRAIN_MEAN", tuple(r.features for r in rows), tuple(r.label for r in rows)
        )

    assert fit(train_before)((0.0,) * 4) == fit(train_after)((0.0,) * 4)
    assert before[-2].features != after[-2].features


def test_source_admission_hash_shape_and_fold_bounds() -> None:
    snapshot, raw = small_source()
    with pytest.raises(ResearchValidationError, match="BOUND_OR_HASH"):
        table(snapshot, raw + b"corrupt")
    with pytest.raises(ResearchValidationError, match="BOUND_OR_HASH"):
        table(replace(snapshot, row_count=10001), raw)
    with pytest.raises(ResearchValidationError, match="SCHEMA"):
        table(replace(snapshot, row_count=79), raw)
    historical = replace(
        snapshot,
        evidence_mode="HISTORICAL",
        admission="HISTORICAL_EXPLORATORY",
        causal_eligible=False,
    )
    with pytest.raises(ResearchValidationError, match="ADMISSION"):
        table(historical, raw)
    bad, other = small_source(missing_column=True)
    with pytest.raises(ResearchValidationError, match="SCHEMA"):
        table(bad, other)
    for change in ({"training_rows": 80}, {"purge_bars": 25}, {"embargo_bars": 30}):
        with pytest.raises(ResearchValidationError, match="INTERVALS_TOO_SMALL"):
            prepare(snapshot, raw, small_controls(**change))
    _, plan = prepare(
        snapshot, raw, small_controls(folds=1, purge_bars=0, embargo_bars=0)
    )
    assert (
        plan.folds[0].purge.interval is None and plan.folds[0].embargo.interval is None
    )


@pytest.mark.parametrize(
    "value", ["", "NaN", "Infinity", "-1", "1001", "1e99999999", "x"]
)
def test_diagnostic_cost_validation(value: str) -> None:
    with pytest.raises(ResearchValidationError, match="COST"):
        cost_number(value)


@pytest.mark.parametrize(
    "value", ["2025-01-01T00:00:00", "2025-99-01T00:00:00Z", "x" * 40]
)
def test_asof_utc_validation(value: str) -> None:
    with pytest.raises(ResearchValidationError, match="UTC"):
        instant(value)


def test_closed_control_record_and_solver_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = small_controls().to_record()
    assert ValidationControls.from_record(valid) == small_controls()
    with pytest.raises(ResearchValidationError, match="CONTROLS"):
        ValidationControls.from_record({**valid, "autotune": True})
    for x, y in (
        (((1.0,),), (1.0,)),
        (((float("nan"),), (1.0,)), (1.0, 2.0)),
        (((1.0,), (2.0,)), (1.0,)),
    ):
        with pytest.raises(ResearchValidationError, match="SHAPE"):
            fit_model("OLS_LAG_RETURNS", x, y)
    with pytest.raises(ResearchValidationError, match="MODEL"):
        fit_model("UNKNOWN", ((1.0,), (2.0,)), (1.0, 2.0))

    def solver(*args: Any, **kwargs: Any) -> Any:
        raise np.linalg.LinAlgError("sensitive native message")

    monkeypatch.setattr(np.linalg, "lstsq", solver)
    with pytest.raises(ResearchValidationError, match=r"^OLS_SOLVER_FAILED$"):
        fit_model("OLS_LAG_RETURNS", ((1.0,), (2.0,), (3.0,)), (1.0, 2.0, 3.0))


def test_shared_admission_precedes_heavy_replay_and_worker_child_is_once_only(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = h.submit()
    claimed = h.access.state.claim()
    assert claimed is not None
    child = h.access.quality.data._begin(
        h.users["owner"], "OTHER_CHILD", worker_job_id=job.id
    )

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("replay ran despite duplicate resource child")

    monkeypatch.setattr(h.access, "_resolve", forbidden)
    with pytest.raises(AccessError, match="active operation"):
        h.access.execute_job(claimed)
    assert h.access.lab.list_runs() == []
    assert h.access.state.job(h.users["owner"], job.id).status == "RUNNING"
    h.access.quality.data._finish(child, error="SyntheticInterrupted")
    h.access.state.finish(job.id, error="SyntheticInterrupted")
    first = h.access.quality.data._begin(h.users["owner"], "FIRST")
    second = h.access.quality.data._begin(h.users["owner"], "SECOND")
    monkeypatch.setattr(h.access.quality, "selected", forbidden)
    assert h.client.post("/api/validations/jobs", json=h.body()).status_code == 403
    assert len(h.access.state.jobs(h.users["owner"])) == 1
    h.access.quality.data._finish(first)
    h.access.quality.data._finish(second)


def test_cancel_retains_private_job_without_trial_and_pending_folds_do_not_fit(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_hunter.web.validation_jobs as jobs

    job = h.submit()
    assert (
        h.client.post(f"/api/validations/jobs/{job.id}/cancel", json={}).status_code
        == 200
    )
    assert (
        h.client.post(f"/api/validations/jobs/{job.id}/cancel", json={}).status_code
        == 403
    )
    assert h.access.state.claim() is None
    assert h.access.lab.list_runs() == []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("unclosed validation fold fitted")

    monkeypatch.setattr(jobs, "fit_model", forbidden)
    _, value = h.run(evaluation_as_of="2025-01-06T14:30:00Z")
    result = cast(JsonRecord, cast(JsonRecord, value["run"])["result"])
    assert all(
        fold["status"] == "PENDING" for fold in cast(list[JsonRecord], result["folds"])
    )
    assert (
        cast(JsonRecord, result["uncertainty_of_mean_absolute_error"])["interval"]
        is None
    )
    assert cast(JsonRecord, value["family_exposure"])["total_attempts"] == 1
    run = cast(JsonRecord, value["run"])
    artifact = cast(JsonRecord, cast(JsonRecord, run["result"])["canonical_models"])
    retained = cast(
        JsonRecord,
        parse_json_document(
            h.access.lab.objects.read_bytes(cast(str, artifact["artifact_digest"]))
        ),
    )
    assert cast(JsonRecord, retained["outputs"]) == {
        "fold-1:estimator": None,
        "fold-2:estimator": None,
    }
    assert h.client.get(f"/api/validations/jobs/{job.id}/report").status_code == 200


def test_solver_failure_is_retained_and_counts_family_exposure(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quant_hunter.web.validation_jobs as jobs

    def failure(*args: Any, **kwargs: Any) -> Any:
        raise ResearchValidationError("OLS_SOLVER_FAILED")

    monkeypatch.setattr(jobs, "fit_model", failure)
    _, value = h.run(model="OLS_LAG_RETURNS")
    assert cast(JsonRecord, value["job"])["status"] == "FAILED"
    assert cast(JsonRecord, value["run"])["evaluation_outcome"] == "FAILED"
    inventory = cast(JsonRecord, value["family_exposure"])
    assert inventory["total_attempts"] == inventory["failed_attempts"] == 1
    assert "trials" not in inventory and "inventory_digest" not in inventory
    run = cast(JsonRecord, value["run"])
    registration = cast(
        JsonRecord, cast(JsonRecord, run["configuration"])["model_registration"]
    )
    assert len(cast(list[JsonRecord], registration["fits"])) == 4
    h.access.models.verify(h.users["owner"], registration)


def test_completed_evaluation_survives_finish_crash_window(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = h.access.quality.data._finish
    once = False

    def finish(operation: str, **kwargs: Any) -> None:
        nonlocal once
        result = kwargs.get("result")
        if isinstance(result, dict) and "experiment_id" in result and not once:
            once = True
            raise OSError("synthetic operational write failure")
        original(operation, **kwargs)

    monkeypatch.setattr(h.access.quality.data, "_finish", finish)
    _, value = h.run()
    assert once
    assert cast(JsonRecord, value["job"])["status"] == "SUCCEEDED"
    assert cast(JsonRecord, value["run"])["variants_attempted"] == 1


def test_report_missing_and_coherently_rehashed_foreign_report_are_rejected(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job, value = h.run()
    run = cast(JsonRecord, value["run"])
    result = cast(JsonRecord, run["result"])
    report = dict(cast(JsonRecord, value["report"]))
    report["experiment_id"] = "EXP-01990f30-7f5e-7b34-9b21-3d74c513c849"
    foreign = h.access.lab.objects.publish(canonicalize_json(report)).digest
    original_get = h.access.lab.get_run
    changed = {**run, "result": {**result, "report_digest": foreign}}
    monkeypatch.setattr(h.access.lab, "get_run", lambda identity: changed)
    with pytest.raises(ResearchValidationError, match="REPORT_BINDING"):
        h.access.get(h.users["owner"], job.id)
    changed["result"] = {**result, "profile": "unexpected"}
    with pytest.raises(ResearchValidationError, match="RESULT_PROFILE"):
        h.access.get(h.users["owner"], job.id)
    changed["result"] = {**result, "controls": {}}
    with pytest.raises(ResearchValidationError, match="RESULT_BINDING"):
        h.access.get(h.users["owner"], job.id)
    monkeypatch.setattr(h.access.lab, "get_run", original_get)
    path = h.access.lab.objects.get(cast(str, result["report_digest"])).path
    path.unlink()
    assert h.client.get(f"/api/validations/jobs/{job.id}").status_code == 503


def test_role_revocation_prevents_replay_and_unauthorized_read_is_private(
    h: Harness,
) -> None:
    job = h.submit()
    claimed = h.access.state.claim()
    assert claimed is not None
    with h.access.state.connection() as db:
        db.execute("UPDATE users SET role='reader' WHERE id=?", (h.users["owner"].id,))
    with pytest.raises(AccessError, match="Researcher"):
        h.access.execute_job(claimed)
    assert h.access.lab.list_runs() == []
    h.client.headers["x-test-user"] = ""
    assert h.client.get(f"/api/validations/jobs/{job.id}").status_code == 401
