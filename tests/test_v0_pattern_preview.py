"""Literal preview, shared read admission and post-evaluation recovery oracles."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest
from test_v0_pattern_workflows import Harness, make

from quant_hunter.config import JsonRecord
from quant_hunter.data_quality import QualityError
from quant_hunter.identity import StaleWriterError
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.web.state import AccessError


@pytest.fixture(scope="module")
def h(tmp_path_factory: pytest.TempPathFactory) -> Harness:
    return make(tmp_path_factory.mktemp("pattern-preview"))


def test_preview_literal_bars_across_partition_boundary(h: Harness) -> None:
    response = h.request(
        "GET",
        f"/api/patterns/corpora/{h.corpora[0]['dataset_id']}/preview?start=95&stop=100",
    )
    assert response.status_code == 200, response.text
    result = response.json()
    for key in ("dataset_id", "record_digest", "manifest_digest", "selection_digest"):
        assert result[key] == h.corpora[0][key]
    assert result["row_start"] == 95 and result["row_stop"] == 100
    assert result["feature_columns"] == [
        "close",
        "open",
        "high",
        "low",
        "volume",
        "open_bid",
        "open_ask",
    ]
    assert result["instrument_id"] == h.datasets[0]["instrument_id"]
    assert (
        result["instrument_revision_digest"]
        == h.datasets[0]["instrument_revision_digest"]
    )
    assert result["step_ns"] == 60_000_000_000
    # Hand-computable qh-quality-demo-v1 row95: open100.11, close100.09.
    assert result["rows"][0] == {
        "row": 95,
        "open_ns": "1736179500000000000",
        "close_ns": "1736179560000000000",
        "available_ns": "1736179560000000000",
        "values": [100.09, 100.11, 100.13, 100.07, 107.0, 100.10, 100.12],
    }
    assert [row["row"] for row in result["rows"]] == list(range(95, 100))
    assert "outcome" not in str(result) and "normalized" not in result


@pytest.mark.parametrize(
    "bounds", [(-1, 1), (0, 0), (2, 1), (0, 513), (0, 241), (True, 2)]
)
def test_preview_refuses_out_of_range_or_oversized_request(
    h: Harness, bounds: tuple[int, int]
) -> None:
    with pytest.raises(PatternError, match="PREVIEW_RANGE"):
        h.access.preview(
            h.users["owner"],
            h.corpora[0]["dataset_id"],
            start=bounds[0],
            stop=bounds[1],
        )


def test_preview_other_user_rejected_before_any_content(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        h.access.lab.objects,
        "read_bytes",
        lambda *a: pytest.fail("foreign content read"),
    )
    response = h.request(
        "GET",
        f"/api/patterns/corpora/{h.corpora[0]['dataset_id']}/preview?start=0&stop=1",
        name="other",
    )
    assert response.status_code == 403
    with h.access.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0] == 0


def test_all_detailed_reads_reserve_before_replay_and_release(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed = h.execute(h.prepare())
    original = h.access._corpus
    observed: list[int] = []

    def guarded(*args: Any) -> Any:
        with h.access.state.connection() as db:
            readers = db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0]
        observed.append(readers)
        assert readers == 1
        return original(*args)

    monkeypatch.setattr(h.access, "_corpus", guarded)
    owner, identity = h.users["owner"], h.corpora[0]["dataset_id"]
    h.access.corpus(owner, identity)
    h.access.preview(owner, identity, start=0, stop=2)
    h.access.prepared(owner, completed["prepared_id"])
    h.access.job(owner, completed["job"]["id"])
    assert len(observed) == 4
    with h.access.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0] == 0


def test_full_read_cap_refuses_before_source_and_frees_on_error(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = [
        h.access.quality.data._begin(h.users["owner"], "TEST") for _ in range(2)
    ]
    monkeypatch.setattr(
        h.access, "_corpus", lambda *a: pytest.fail("unreserved source replay")
    )
    try:
        with pytest.raises(AccessError, match="busy"):
            h.access.preview(
                h.users["owner"], h.corpora[0]["dataset_id"], start=0, stop=1
            )
    finally:
        for operation in operations:
            h.access.quality.data._finish(operation, error="TestFinished")
    monkeypatch.setattr(
        h.access,
        "_corpus",
        lambda *a: (_ for _ in ()).throw(PatternError("INJECTED_CORRUPTION")),
    )
    with pytest.raises(PatternError, match="CORRUPTION"):
        h.access.corpus(h.users["owner"], h.corpora[0]["dataset_id"])
    with h.access.state.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM resource_readers").fetchone()[0] == 0


def test_linked_worker_and_positive_read_do_not_reserve_twice(h: Harness) -> None:
    # One unrelated operation plus the real worker fills exactly two slots.
    prepared = h.prepare()
    other = h.access.quality.data._begin(h.users["other"], "TEST_OTHER")
    try:
        result = h.execute(prepared)
        assert result["job"]["status"] == "SUCCEEDED"
        # Synchronous preparation has its own slot, reused by POSITIVE reads.
        assert h.prepare()["scenario"] == "POSITIVE"
    finally:
        h.access.quality.data._finish(other, error="TestFinished")


@pytest.mark.parametrize("after_commit", [False, True])
def test_canonical_success_survives_one_shot_operational_finish_error(
    h: Harness, monkeypatch: pytest.MonkeyPatch, after_commit: bool
) -> None:
    prepared = h.prepare()
    original = h.access._finish
    calls = 0

    def interrupted(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            if after_commit:
                original(*args, **kwargs)
            raise OSError("controlled operational interruption")
        original(*args, **kwargs)

    monkeypatch.setattr(h.access, "_finish", interrupted)
    result = h.execute(prepared)
    assert result["job"]["status"] == "SUCCEEDED"
    assert result["run"]["lifecycle_status"] == "EVALUATED"
    assert result["run"]["variants_attempted"] == 1
    assert result["run"]["evaluation_outcome"] == "INCONCLUSIVE"
    assert calls == (1 if after_commit else 2)
    with h.access.state.connection() as db:
        row = db.execute(
            "SELECT status FROM pattern_job_receipts WHERE job_id=?",
            (result["job"]["id"],),
        ).fetchone()
    assert row[0] == "COMPLETED"


def test_retained_success_recovers_before_canonical_evaluated_revision(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare()
    original = h.access.lab.lifecycle.evaluate
    calls = 0

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("after immutable result and counted successful attempt")
        return original(*args, **kwargs)

    monkeypatch.setattr(h.access.lab.lifecycle, "evaluate", interrupted)
    result = h.execute(prepared)
    assert calls == 2
    assert result["job"]["status"] == "SUCCEEDED"
    assert result["run"]["variants_attempted"] == 1
    assert result["run"]["evaluation_outcome"] == "INCONCLUSIVE"
    assert result["run"]["result"]["canonical_binding"]


@pytest.mark.parametrize(
    "error,status,body",
    [
        (StaleWriterError("private text"), 409, "Exact input"),
        (QualityError("private text"), 400, "Quality selection"),
        (PatternError("CLOSED_PATTERN_CODE"), 400, "CLOSED_PATTERN_CODE"),
        (PatternError("private text"), 400, "PATTERN_REQUEST_INVALID"),
        (RuntimeError("private text"), 503, "retained evidence"),
    ],
)
def test_route_errors_are_sanitized(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
    body: str,
) -> None:
    monkeypatch.setattr(
        h.access, "preview", lambda *a, **k: (_ for _ in ()).throw(error)
    )
    response = h.request(
        "GET",
        f"/api/patterns/corpora/{h.corpora[0]['dataset_id']}/preview?start=0&stop=1",
    )
    assert response.status_code == status and body in response.text
    assert "private text" not in response.text


def test_manifest_graph_and_preparation_revision_change_fail_closed(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare()
    original = h.access.lab.registry.verify_object

    def changed(identity: str) -> Any:
        revisions = original(identity)
        if identity == prepared["pattern_id"]:
            return (
                *revisions[:-1],
                replace(revisions[-1], digest="sha256:" + "9" * 64),
            )
        return revisions

    monkeypatch.setattr(h.access.lab.registry, "verify_object", changed)
    with pytest.raises(PatternError, match="REGISTRY_CHANGED"):
        h.access.prepared(h.users["owner"], prepared["prepared_id"])


def test_stale_prepared_corpus_and_secondary_are_rejected(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare("PAT-11")
    original = h.access._corpus

    def changed(user: Any, identity: str) -> Any:
        corpus, receipt = original(user, identity)
        if identity == h.corpora[1]["dataset_id"]:
            receipt["row_count"] = 1
        return corpus, receipt

    monkeypatch.setattr(h.access, "_corpus", changed)
    with pytest.raises(PatternError, match="SECONDARY_CHANGED"):
        h.access.prepared(h.users["owner"], prepared["prepared_id"])


def test_unavailable_identity_and_invalid_pages(h: Harness) -> None:
    for limit, offset in ((0, 0), (26, 0), (1, -1), (True, 0)):
        with pytest.raises(AccessError):
            h.access.corpus_list(h.users["owner"], limit=limit, offset=offset)
    with pytest.raises(AccessError):
        h.access.enqueue(h.users["owner"], "0" * 32)
    with pytest.raises(AccessError):
        h.access.prepared(h.users["owner"], "0" * 32)
    with pytest.raises(PatternError, match="SCENARIO_UNKNOWN"):
        h.access.prepare(
            h.users["owner"], h.corpora[0]["dataset_id"], scenario=cast(Any, "invalid")
        )


def test_corpus_lineage_corruption_and_interrupted_grant(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = h.corpora[0]["dataset_id"]
    lineage = h.access.lab.registry.verify_object(identity)[-1].record[
        "provenance_lineage_digest"
    ]
    original = h.access._read

    def altered(digest: str) -> JsonRecord:
        value = original(digest)
        if digest == lineage:
            value["normalization"] = "undeclared transformation"
        return value

    monkeypatch.setattr(h.access, "_read", altered)
    with pytest.raises(PatternError, match="LINEAGE_MISMATCH"):
        h.access.corpus(h.users["owner"], identity)
    operation = h.access.quality.data._begin(h.users["owner"], "TEST")
    h.access.quality.data._finish(operation, error="Interrupted")
    with pytest.raises(AccessError, match="interrupted"):
        h.access._finish(h.users["owner"], operation, {})
