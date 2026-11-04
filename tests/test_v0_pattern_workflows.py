"""Actual owned quality/Parquet/PATTERN/Item8 integration; no external service."""

from __future__ import annotations

import asyncio
import hmac
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

from quant_hunter.config import JsonRecord
from quant_hunter.data_quality import QualityService
from quant_hunter.imports import ImportService
from quant_hunter.lab.service import LabService
from quant_hunter.markets.registry import InstrumentRegistry
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.patterns.corpus import CorpusConfig
from quant_hunter.web.data_access import DataAccess
from quant_hunter.web.pattern_access import PatternAccess, Scenario
from quant_hunter.web.pattern_routes import install_pattern_routes
from quant_hunter.web.quality_access import QualityAccess
from quant_hunter.web.state import AccessError, AppState, Session, User

SCHEMAS = Path(
    os.environ.get(
        "QH_PATTERN_SCHEMA_ROOT", str(Path(__file__).parents[1] / "schemas/v1")
    )
)


class NoNetwork:
    def probe(self, catalogue_id: str) -> JsonRecord:
        raise AssertionError("Pattern workflow must never acquire external data")


@dataclass
class Harness:
    access: PatternAccess
    users: dict[str, User]
    sessions: dict[str, tuple[str, str]]
    app: FastAPI
    datasets: list[dict[str, Any]]
    selections: list[str]
    corpora: list[dict[str, Any]]

    def request(
        self,
        method: str,
        url: str,
        *,
        name: str = "owner",
        csrf: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        token, protection = self.sessions.get(name, ("", ""))

        async def run() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(self.app),
                base_url="http://testserver",
                cookies={"qh_session": token},
                headers={"x-csrf-token": protection if csrf else "wrong"},
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(run())

    def prepare(
        self, family: str = "PAT-13", scenario: Scenario = "POSITIVE"
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self.access.prepare(
                self.users["owner"],
                self.corpora[0]["dataset_id"],
                family=family,
                scenario=scenario,
                secondary_corpus_id=self.corpora[1]["dataset_id"]
                if family == "PAT-11"
                else None,
            ),
        )

    def execute(self, prepared: dict[str, Any]) -> dict[str, Any]:
        queued = self.access.enqueue(self.users["owner"], prepared["prepared_id"])
        claimed = self.access.state.claim()
        assert claimed is not None and claimed.id == queued.id
        self.access.execute_job(claimed)
        return cast(dict[str, Any], self.access.job(self.users["owner"], queued.id))


def make(root: Path) -> Harness:
    lab = LabService(
        root,
        SCHEMAS,
        "7346cf4f79ca5897777c0118f8cf4c2292be929e",
        {"synthetic_test": "Pattern workflow"},
    )
    state = AppState(root / "state.sqlite3")
    users, sessions = {}, {}
    for name, role in (
        ("owner", "owner"),
        ("other", "researcher"),
        ("reader", "reader"),
    ):
        users[name] = state.create_user(
            name,
            "synthetic software test password",
            cast(Literal["owner", "researcher", "reader"], role),
            bootstrap=name == "owner",
        )
        token, session = state.login(name, "synthetic software test password")
        sessions[name] = token, session.csrf
    importer = ImportService(
        lab.registry, lab.objects, SCHEMAS, lab.code_revision, lab.environment_digest
    )
    data = DataAccess(state, root, importer, NoNetwork())
    service = QualityService(
        lab.registry, lab.objects, SCHEMAS, lab.code_revision, lab.environment_digest
    )
    quality = QualityAccess(state, service, data, InstrumentRegistry(lab.registry))
    access = PatternAccess(state, quality, lab)
    app = FastAPI()

    def authenticated(
        request: Request, *, mutation: bool = False, owner: bool = False
    ) -> Session:
        try:
            session = state.session(request.cookies.get("qh_session", ""))
        except AccessError:
            raise HTTPException(401, "Sign in") from None
        if mutation and not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), session.csrf
        ):
            raise HTTPException(403, "CSRF")
        if owner and session.user.role != "owner":
            raise HTTPException(403, "Owner required")
        return session

    install_pattern_routes(app, authenticated, access)
    demo = quality.demo(users["owner"])
    datasets = cast(list[dict[str, Any]], demo["datasets"])
    selections, corpora = [], []
    for dataset in datasets:
        selection = quality.compose(
            users["owner"],
            (
                (
                    dataset["dataset_id"],
                    dataset["record_digest"],
                    dataset["quality_report_digest"],
                ),
            ),
        )
        digest = cast(str, selection["manifest_digest"])
        selections.append(digest)
        corpora.append(
            cast(
                dict[str, Any],
                access.materialize(
                    users["owner"],
                    digest,
                    config=CorpusConfig(block_rows=97, max_disk_bytes=4 * 1024**2),
                ),
            )
        )
    return Harness(access, users, sessions, app, datasets, selections, corpora)


@pytest.fixture(scope="module")
def h(tmp_path_factory: pytest.TempPathFactory) -> Harness:
    return make(tmp_path_factory.mktemp("pattern-native"))


@pytest.mark.parametrize("scenario", ["POSITIVE", "NULL", "SENSITIVITY"])
@pytest.mark.parametrize("family", [f"PAT-{number:02}" for number in range(1, 16)])
def test_all_fifteen_native_counted_software_controls(
    h: Harness, family: str, scenario: Scenario
) -> None:
    prepared = h.prepare(family, scenario)
    result = h.execute(prepared)
    assert result["job"]["status"] == "SUCCEEDED", result
    run = result["run"]
    assert run["lifecycle_status"] == "EVALUATED"
    assert run["evaluation_outcome"] == "INCONCLUSIVE"
    assert run["variants_attempted"] == 1
    value = run["result"]
    assert value["method_id"] == family and value["native_scenario"] == scenario
    assert (
        value["exposure"]["variant_count"] == 1
        and value["exposure"]["rows_visited"] == 240
    )
    assert value["empirical_validation"] == "MISSING"
    assert (
        value["native_input_graph"]["corpus"]["dataset_id"]
        == h.corpora[0]["dataset_id"]
    )
    assert value["canonical_binding"]["prepared_digest"] == prepared["prepared_digest"]
    assert value["checkpoint_digest"] == result["checkpoint_digest"]
    assert value["method"]["status"] in {"EXECUTED", "INCONCLUSIVE"}
    if scenario == "NULL":
        assert value["state"] == "UNKNOWN" and value["occurrences"] == []
        assert value["exposure"]["eligible_windows"] == 0
    if scenario == "POSITIVE":
        assert value["state"] == "MATCHES" and value["occurrences"]
    if family in {"PAT-12", "PAT-13", "PAT-14"} and scenario == "SENSITIVITY":
        assert value["configuration"]["cost_bps"] == 27
        for hit in value["occurrences"]:
            assert hit["outcome"]["gross_return"] - hit["net_return"] == pytest.approx(
                0.0027
            )
    pattern = h.access.lab.registry.verify_object(prepared["pattern_id"])[-1].record
    assert pattern["status"] == "SOFTWARE_ONLY"
    assert (
        pattern["validation_dataset_id"] is None
        and pattern["sealed_dataset_id"] is None
    )
    assert pattern["empirical_validation"] == "UNVALIDATED"
    assert run["bindings"]["dataset_id"] != h.corpora[0]["dataset_id"]


def test_async_corpus_queue_progress_restart_and_real_manifest(h: Harness) -> None:
    response = h.request(
        "POST",
        "/api/patterns/corpora",
        json={"selection_digest": h.selections[0], "options": {"block_rows": 80}},
    )
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "QUEUED"
    job = h.access.state.claim()
    assert job and job.id == queued["id"]
    h.access.execute_corpus_job(job)
    result = h.access.job(h.users["owner"], job.id)
    detail = cast(dict[str, Any], result["corpus"])
    assert cast(dict[str, Any], result["job"])["status"] == "SUCCEEDED"
    assert detail["row_count"] == 240 and detail["partition_count"] == 3
    assert result["operation_id"] and result["progress"]
    stored = h.access.lab.registry.verify_object(detail["dataset_id"])[-1].record
    assert stored["physical_object_digest"] == detail["manifest_digest"]
    restarted = PatternAccess(h.access.state, h.access.quality, h.access.lab)
    assert restarted.corpus(h.users["owner"], detail["dataset_id"]) == detail
    assert restarted.job(h.users["owner"], job.id) == result
    with pytest.raises(AccessError):
        restarted.execute_corpus_job(job)


def test_private_reads_and_reader_write_authority_before_content(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare()
    monkeypatch.setattr(
        h.access.lab.objects,
        "read_bytes",
        lambda value: pytest.fail("foreign object read"),
    )
    for route in (
        f"corpora/{h.corpora[0]['dataset_id']}",
        f"prepared/{prepared['prepared_id']}",
    ):
        assert (
            h.request("GET", "/api/patterns/" + route, name="other").status_code == 403
        )
    assert (
        h.request(
            "POST",
            "/api/patterns/corpora",
            name="other",
            json={"selection_digest": h.selections[0]},
        ).status_code
        == 403
    )
    assert (
        h.request(
            "POST",
            "/api/patterns/prepare",
            name="reader",
            json={
                "corpus_id": h.corpora[0]["dataset_id"],
                "family": "PAT-13",
                "scenario": "POSITIVE",
            },
        ).status_code
        == 403
    )
    assert h.request("GET", "/api/patterns/catalogue", name="reader").status_code == 200


def test_auth_csrf_closed_limits_and_no_error_echo(h: Harness) -> None:
    assert (
        h.request("GET", "/api/patterns/catalogue", name="unknown").status_code == 401
    )
    assert (
        h.request(
            "POST",
            "/api/patterns/corpora",
            csrf=False,
            json={"selection_digest": h.selections[0]},
        ).status_code
        == 403
    )
    for extra in (
        {"path": "private-fixture-must-not-echo"},
        {"options": {"max_disk_bytes": 536870913}},
        {"options": {"block_rows": True}},
    ):
        response = h.request(
            "POST",
            "/api/patterns/corpora",
            json={"selection_digest": h.selections[0], **extra},
        )
        assert response.status_code == 422 and "private-fixture" not in response.text
    assert h.request("GET", "/api/patterns/corpora?limit=26").status_code == 422


def test_selected_configuration_and_each_retry_new_experiment(h: Harness) -> None:
    corpus, _ = h.access._corpus(h.users["owner"], h.corpora[0]["dataset_id"])
    cfg = h.access.scenario_config(corpus, "PAT-13", "BASELINE")
    prepared = cast(
        dict[str, Any],
        h.access.prepare(h.users["owner"], corpus.dataset_id, config=cfg),
    )
    first, second = h.execute(prepared), h.execute(prepared)
    assert first["job"]["experiment_id"] != second["job"]["experiment_id"]
    assert (
        first["run"]["variants_attempted"] == second["run"]["variants_attempted"] == 1
    )
    assert (
        first["run"]["result"]["occurrences"] == second["run"]["result"]["occurrences"]
    )


def test_computation_failure_is_counted_and_checkpoint_retained(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare()
    original = h.access.product.execute_registered

    def broken(*args: Any, **kwargs: Any) -> JsonRecord:
        original(*args, **kwargs)
        raise RuntimeError("private secret failure must not be stored")

    monkeypatch.setattr(h.access.product, "execute_registered", broken)
    result = h.execute(prepared)
    assert result["job"]["status"] == "FAILED"
    assert result["run"]["variants_attempted"] == 1
    assert result["run"]["evaluation_outcome"] == "FAILED"
    assert result["checkpoint_digest"]
    assert "private secret" not in str(result)


def test_claim_once_recovery_no_replay(h: Harness) -> None:
    prepared = h.prepare()
    job = h.access.enqueue(h.users["owner"], prepared["prepared_id"])
    claimed = h.access.state.claim()
    assert claimed and claimed.id == job.id
    h.access._claim(claimed)
    with pytest.raises(AccessError, match="already started"):
        h.access.execute_job(claimed)
    h.access.recover()
    h.access.state.finish(job.id, error="Interrupted explicit test")
    h.access.recover()
    with h.access.state.connection() as db:
        row = db.execute(
            "SELECT status FROM pattern_job_receipts WHERE job_id=?", (job.id,)
        ).fetchone()
    assert row[0] == "INTERRUPTED"
    assert h.access.state.claim() is None


def test_stale_claim_and_wrong_owner_cannot_execute(h: Harness) -> None:
    prepared = h.prepare()
    queued = h.access.enqueue(h.users["owner"], prepared["prepared_id"])
    with pytest.raises(AccessError):
        h.access.execute_job(queued)
    claimed = h.access.state.claim()
    assert claimed
    with pytest.raises(AccessError):
        h.access.execute_job(replace(claimed, owner_id=h.users["other"].id))
    h.access.execute_job(claimed)
    assert h.access.state.job(h.users["owner"], queued.id).status == "SUCCEEDED"


def test_disk_limit_rejects_before_parent_replay(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        h.access.quality,
        "_selection",
        lambda *args: pytest.fail("heavy replay before resource admission"),
    )
    monkeypatch.setattr(
        h.access.quality.data,
        "_capacity",
        lambda: (_ for _ in ()).throw(AccessError("test resource limit")),
    )
    with pytest.raises(AccessError):
        h.access.materialize(h.users["owner"], h.selections[0])


def test_prepared_scope_and_parent_graph_are_rebound(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare()
    original = h.access._read

    def wrong(digest: str) -> JsonRecord:
        record = original(digest)
        if digest == prepared["prepared_digest"]:
            record["planned_scope"] = {"variant_count": 0}
        return record

    monkeypatch.setattr(h.access, "_read", wrong)
    with pytest.raises(PatternError, match="GRAPH_MISMATCH"):
        h.access.prepared(h.users["owner"], prepared["prepared_id"])


def test_queue_poll_does_not_replay_content_and_cancel_preserves_no_attempt(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare()
    monkeypatch.setattr(
        h.access.lab.objects,
        "read_bytes",
        lambda digest: pytest.fail("queue or polling read content"),
    )
    jobs = [
        h.access.enqueue(h.users["owner"], prepared["prepared_id"]) for _ in range(8)
    ]
    with pytest.raises(AccessError, match="Queue is full"):
        h.access.enqueue(h.users["owner"], prepared["prepared_id"])
    for job in jobs:
        detail = h.access.job(h.users["owner"], job.id)
        assert detail["run"] is None
        h.access.state.cancel(h.users["owner"], job.id)
        assert (
            cast(dict[str, Any], h.access.job(h.users["owner"], job.id)["job"])[
                "status"
            ]
            == "CANCELLED"
        )


def test_positive_requires_exact_known_raw_fixture_and_baseline_remains_available(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = h.access.quality.dataset

    def unknown(*args: Any, **kwargs: Any) -> JsonRecord:
        value = original(*args, **kwargs)
        value["raw_digest"] = "sha256:" + "1" * 64
        return value

    # This changes only the extra positive-fixture classification read. It must
    # not create a scientific positive label for arbitrary admitted raw bytes.
    monkeypatch.setattr(h.access.quality, "dataset", unknown)
    with pytest.raises(PatternError, match="KNOWN_FIXTURE"):
        h.prepare()
    prepared = h.prepare(scenario="BASELINE")
    assert prepared["scenario"] == "BASELINE"


def test_reader_can_inspect_own_retained_result_but_cannot_enqueue(h: Harness) -> None:
    prepared = h.prepare()
    completed = h.execute(prepared)
    # A role reduction preserves the same authenticated owner's read rights.
    reader = replace(h.users["owner"], role="reader")
    assert h.access.job(reader, completed["job"]["id"]) == completed
    with pytest.raises(AccessError):
        h.access.enqueue(reader, prepared["prepared_id"])


def test_result_canonical_binding_rechecked_against_frozen_registry(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare()
    completed = h.execute(prepared)
    original = h.access.lab.get_run

    def changed(identity: str) -> JsonRecord:
        value = original(identity)
        result = cast(dict[str, Any], value["result"])
        result["canonical_binding"]["experiment_record_digest"] = "sha256:" + "4" * 64
        with h.access.state.connection() as db:
            import json

            db.execute(
                "UPDATE pattern_job_receipts SET binding=? WHERE job_id=?",
                (json.dumps(result["canonical_binding"]), completed["job"]["id"]),
            )
        return value

    monkeypatch.setattr(h.access.lab, "get_run", changed)
    with pytest.raises(PatternError, match="RESULT_GRAPH_MISMATCH"):
        h.access.job(h.users["owner"], completed["job"]["id"])


def test_failed_corpus_never_grants_partial_ownership(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = len(h.access._ids(h.users["owner"], "corpus", 25, 0))
    queued = h.access.enqueue_corpus(h.users["owner"], h.selections[0])
    claimed = h.access.state.claim()
    assert claimed and claimed.id == queued.id
    monkeypatch.setattr(
        h.access.corpora,
        "build_selection",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("private input failure")),
    )
    h.access.execute_corpus_job(claimed)
    detail = h.access.job(h.users["owner"], queued.id)
    assert cast(dict[str, Any], detail["job"])["status"] == "FAILED"
    assert detail["corpus"] is None and detail["operation_id"]
    assert len(h.access._ids(h.users["owner"], "corpus", 25, 0)) == before
    assert "private input" not in str(detail)


def test_preparation_failure_retains_allocated_pattern_identity(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        h.access.product,
        "prepare",
        lambda *a, **k: (_ for _ in ()).throw(
            PatternError("CONTROLLED_PREPARATION_FAILURE")
        ),
    )
    with pytest.raises(PatternError):
        h.prepare()
    operations = h.access.quality.data.operations(h.users["owner"])
    failed = next(row for row in operations if row["kind"] == "PATTERN_PREPARE")
    assert failed["status"] == "FAILED"
    identity = cast(dict[str, Any], failed["result"])["pattern_id"]
    assert (
        h.access.lab.registry.verify_object(identity)[-1].record["status"]
        == "SOFTWARE_ONLY"
    )


def test_shared_slots_refuse_preparation_before_source_replay(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    one = h.access.quality.data._begin(h.users["owner"], "TEST_RESERVED_SLOT")
    two = h.access.quality.data._begin(h.users["owner"], "TEST_RESERVED_SLOT")
    monkeypatch.setattr(
        h.access, "_corpus", lambda *a: pytest.fail("source replay without shared slot")
    )
    try:
        with pytest.raises(AccessError, match="busy"):
            h.prepare()
    finally:
        h.access.quality.data._finish(one, error="SyntheticTestFinished")
        h.access.quality.data._finish(two, error="SyntheticTestFinished")


def test_pattern_limits_and_selected_schema_do_not_allocate_hidden_variants(
    h: Harness,
) -> None:
    with pytest.raises(PatternError, match="DISK_LIMIT"):
        h.access.enqueue_corpus(
            h.users["owner"],
            h.selections[0],
            config=CorpusConfig(max_disk_bytes=1024**3),
        )
    corpus, _ = h.access._corpus(h.users["owner"], h.corpora[0]["dataset_id"])
    chosen = h.access.scenario_config(corpus, "PAT-13", "BASELINE")
    with pytest.raises(PatternError, match="CHECKPOINT_LIMIT"):
        h.access.prepare(
            h.users["owner"],
            corpus.dataset_id,
            config=replace(chosen, max_checkpoint_bytes=1024**3),
        )
    with pytest.raises(PatternError, match="SELECTED_CONFIG"):
        h.access.prepare(h.users["owner"], corpus.dataset_id)
    with pytest.raises(PatternError, match="CONFLICT"):
        h.access.prepare(
            h.users["owner"],
            corpus.dataset_id,
            config=chosen,
            family="PAT-13",
            scenario="BASELINE",
        )


def test_http_selected_query_and_owned_preparation_workflow(h: Harness) -> None:
    corpus, _ = h.access._corpus(h.users["owner"], h.corpora[0]["dataset_id"])
    chosen = h.access.scenario_config(corpus, "PAT-13", "BASELINE").to_record()
    chosen.pop("secondary_manifest")
    chosen.pop("method_parameters_json")
    chosen["purge_ns"] = "0"
    chosen["method_parameters"] = {}
    response = h.request(
        "POST",
        "/api/patterns/prepare",
        json={"corpus_id": corpus.dataset_id, "configuration": chosen},
    )
    assert response.status_code == 201, response.text
    preparation = response.json()
    assert (
        h.request(
            "GET", f"/api/patterns/prepared/{preparation['prepared_id']}"
        ).status_code
        == 200
    )
    assert h.request("GET", "/api/patterns/prepared?limit=1").json()["prepared"]
    assert h.request("GET", "/api/patterns/corpora?limit=1").json()["corpora"]
    queued = h.request(
        "POST", "/api/patterns/jobs", json={"prepared_id": preparation["prepared_id"]}
    )
    assert queued.status_code == 202
    assert (
        h.request(
            "GET", f"/api/patterns/jobs/{queued.json()['id']}", name="other"
        ).status_code
        == 403
    )
    assert (
        h.request("GET", f"/api/patterns/jobs/{queued.json()['id']}").json()["run"]
        is None
    )
    h.access.state.cancel(h.users["owner"], queued.json()["id"])


def test_sources_remain_unchanged_by_pattern_work(h: Harness) -> None:
    for dataset in h.datasets:
        current = h.access.quality.dataset(h.users["owner"], dataset["dataset_id"])
        for key in (
            "record_digest",
            "normalized_digest",
            "raw_digest",
            "quality_report_digest",
        ):
            assert current[key] == dataset[key]
    for detail in h.access.corpus_list(h.users["owner"]):
        assert "parents" not in detail and "SUMMARY" in cast(str, detail["inspection"])
