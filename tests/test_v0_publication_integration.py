"""Real runtime wiring, shared admission and production native PDF extraction."""

from __future__ import annotations

import importlib.util
import multiprocessing
import secrets
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_v0_publication_workflows import LocalClient, synthetic_pdf

from quant_hunter.publications.extraction import extract_pdf
from quant_hunter.web.api import create_app
from quant_hunter.web.runtime import Runtime
from quant_hunter.web.state import AccessError

ROOT = Path(__file__).parents[1]


@pytest.fixture
def runtime(tmp_path: Path) -> Runtime:
    return Runtime(
        tmp_path / "runtime",
        ROOT,
        "a" * 40,
        private_root=ROOT.parent / "QuantHunterPrivate" / secrets.token_hex(16),
    )


def test_runtime_publications_share_store_and_recover_without_replay(
    runtime: Runtime,
) -> None:
    owner = runtime.state.create_user(
        "owner", "synthetic test password", "owner", bootstrap=True
    )
    operation = runtime.publications._begin(owner, "CREATE", None)
    runtime.recover()
    retained = runtime.publications.operations(owner)
    assert retained[0]["id"] == operation
    assert retained[0]["status"] == "INTERRUPTED"
    assert runtime.publications.service.registry is runtime.lab.registry
    assert runtime.publications.service.objects is runtime.lab.objects


@pytest.mark.parametrize("first", ["data", "publication", "mixed"])
def test_both_admission_paths_share_two_operation_cap(
    runtime: Runtime,
    first: str,
) -> None:
    owner = runtime.state.create_user(
        "owner", "synthetic test password", "owner", bootstrap=True
    )
    for index in range(2):
        if first == "data" or (first == "mixed" and index == 0):
            runtime.data._begin(owner, "IMPORT")
        else:
            runtime.publications._begin(owner, "CREATE", None)
    with pytest.raises(AccessError, match="busy"):
        runtime.data._begin(owner, "IMPORT")
    with pytest.raises(AccessError, match="busy"):
        runtime.publications._begin(owner, "CREATE", None)
    runtime.recover()
    assert runtime.data._begin(owner, "IMPORT")


def test_production_app_routes_and_attachment_only_size_allowance(
    runtime: Runtime,
) -> None:
    owner = runtime.state.create_user(
        "owner", "synthetic test password", "owner", bootstrap=True
    )
    token, session = runtime.state.login(owner.username, "synthetic test password")
    client = LocalClient(
        create_app(runtime.state.path.parent, ROOT, publications=runtime.publications)
    )
    client.cookies.set("qh_session", token)
    client.headers.update({"X-QH-Request": "1", "X-CSRF-Token": session.csrf})
    paper = client.post(
        "/api/publications", json={"url": "https://example.org/synthetic.pdf"}
    )
    assert paper.status_code == 201, paper.text
    route = f"/api/publications/{paper.json()['paper_id']}"
    assert client.get(route).status_code == 200
    references = client.get("/api/publication-reference-catalog")
    assert references.status_code == 200
    assert len(references.json()["references"]) == 10
    assert all(
        item["text_access"] == "UNAVAILABLE" and item["reading_status"] == "UNREAD"
        for item in references.json()["references"]
    )
    assert (
        LocalClient(client.app).get("/api/publication-reference-catalog").status_code
        == 401
    )
    # Invalid content reaches closed input validation only on the exact upload
    # route; adjacent and ordinary routes retain their existing 64 KiB limit.
    body = {"unexpected": "x" * 70_000}
    assert client.post(route + "/attachment", json=body).status_code == 422
    for suffix in ("", "/extract", "/extra/attachment"):
        assert client.post(route + suffix, json=body).status_code == 413
    assert (
        client.post(route + "/attachment", json={"x": "x" * 6_000_000}).status_code
        == 413
    )
    assert len(runtime.publications.operations(owner)) == 1


def test_disk_floor_reserves_both_concurrent_resource_operations(
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserve = 20 * 1024**3
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _: SimpleNamespace(total=100 * 1024**3, free=reserve + 40_000_000),
    )
    with pytest.raises(AccessError, match="reserve"):
        runtime.data._capacity()
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _: SimpleNamespace(total=100 * 1024**3, free=reserve + 64_000_000),
    )
    runtime.data._capacity()


@pytest.mark.skipif(
    sys.platform not in {"win32", "linux"}, reason="native worker profile"
)
def test_pdf_extracts_under_real_production_main_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys.modules["__main__"],
        "__spec__",
        importlib.util.find_spec("quant_hunter.web.main"),
    )
    before = {p.pid for p in multiprocessing.active_children()}
    result = extract_pdf(synthetic_pdf(), page_start=0, page_count=1)
    assert result["pages"][0]["text"] == "Synthetic PDF"
    assert result["ocr"] is False
    assert {p.pid for p in multiprocessing.active_children()} == before
