"""Production quality wiring, bounded HTTP routes and retained runtime recovery."""

import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_v0_publication_workflows import LocalClient

from quant_hunter.web.api import create_app
from quant_hunter.web.runtime import Runtime
from quant_hunter.web.state import User

ROOT = Path(__file__).parents[1]
PASSWORD = "synthetic quality integration password"  # noqa: S105 -- public fixture


@pytest.fixture
def runtime(tmp_path: Path) -> Runtime:
    return Runtime(
        tmp_path / "runtime",
        ROOT,
        "b" * 40,
        private_root=ROOT.parent / "QuantHunterPrivate" / secrets.token_hex(16),
    )


def authenticated(runtime: Runtime, user: User) -> LocalClient:
    token, session = runtime.state.login(user.username, PASSWORD)
    client = LocalClient(
        create_app(
            runtime.state.path.parent,
            ROOT,
            quality=runtime.quality,
            publications=runtime.publications,
            data=runtime.data,
        )
    )
    client.cookies.set("qh_session", token)
    client.headers.update({"X-QH-Request": "1", "X-CSRF-Token": session.csrf})
    return client


def test_production_quality_flow_uses_exact_shared_canonical_stores(
    runtime: Runtime,
) -> None:
    owner = runtime.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    client = authenticated(runtime, owner)
    assert runtime.quality.service.registry is runtime.lab.registry
    assert runtime.quality.service.objects is runtime.lab.objects
    assert runtime.quality.data is runtime.data
    response = client.post("/api/quality/demo", json={})
    assert response.status_code == 201, response.text
    datasets = response.json()["datasets"]
    assert len(datasets) == 2
    item = datasets[0]
    assert item["admission"] == "SYNTHETIC_SOFTWARE_ONLY"
    selection = client.post(
        "/api/quality/selections",
        json={
            "parents": [
                {
                    key: item[key]
                    for key in ("dataset_id", "record_digest", "quality_report_digest")
                }
            ],
            "purpose": "PATTERN_CAUSAL",
        },
    )
    assert selection.status_code == 201, selection.text
    receipt = selection.json()
    assert receipt["total_rows"] == 240
    assert receipt["causal_eligible"] is True
    digest = receipt["manifest_digest"]
    assert client.get(f"/api/quality/selections/{digest}").json() == receipt
    aggregated = client.post(
        f"/api/quality/datasets/{item['dataset_id']}/aggregate",
        json={
            "record_digest": item["record_digest"],
            "quality_report_digest": item["quality_report_digest"],
            "timeframe": "5m",
            "partial_policy": "DROP",
            "as_of": datetime.now(UTC).isoformat(),
        },
    )
    assert aggregated.status_code == 201, aggregated.text
    assert aggregated.json()["row_count"] == 48
    assert aggregated.json()["dataset_id"] != item["dataset_id"]
    assert runtime.quality.dataset(owner, item["dataset_id"]) == item

    interrupted = runtime.data._begin(owner, "QUALITY_IMPORT")
    runtime.recover()
    row = next(op for op in runtime.data.operations(owner) if op["id"] == interrupted)
    assert row["status"] == "INTERRUPTED"
    assert runtime.quality.selection(owner, digest) == receipt
    reader = runtime.state.create_user("reader", PASSWORD, "reader", bootstrap=False)
    other = authenticated(runtime, reader)
    assert other.get(f"/api/quality/datasets/{item['dataset_id']}").status_code == 403
    assert other.get(f"/api/quality/selections/{digest}").status_code == 403
    assert other.post("/api/quality/demo", json={}).status_code == 403
    assert other.get("/api/quality/datasets").json() == {"datasets": []}


def test_quality_upload_and_selection_body_allowances_are_exact(
    runtime: Runtime,
) -> None:
    owner = runtime.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    client = authenticated(runtime, owner)
    invalid = {"unexpected": "x" * 70_000}
    for path in ("/api/quality/datasets", "/api/quality/selections"):
        assert client.post(path, json=invalid).status_code == 422
    for path in (
        "/api/quality/demo",
        "/api/quality/datasets/extra",
        "/api/quality/selections/extra",
        "/api/quality/datasets/anything/aggregate",
        "/api/quality/datasets/extra/import",
    ):
        assert client.post(path, json=invalid).status_code == 413
    for path, size in (
        ("/api/quality/datasets", 3_000_000),
        ("/api/quality/selections", 1_000_000),
    ):
        assert client.post(path, json={"extra": "x" * size}).status_code == 413
    assert runtime.data.operations(owner) == []


def test_quality_creation_respects_active_publication_slots(runtime: Runtime) -> None:
    owner = runtime.state.create_user("owner", PASSWORD, "owner", bootstrap=True)
    client = authenticated(runtime, owner)
    for _ in range(2):
        runtime.publications._begin(owner, "CREATE", None)
    assert client.post("/api/quality/demo", json={}).status_code == 403
    assert runtime.quality.datasets(owner) == []
    assert runtime.instruments.list() == []
    runtime.recover()
    assert all(
        row["status"] == "INTERRUPTED" for row in runtime.publications.operations(owner)
    )
