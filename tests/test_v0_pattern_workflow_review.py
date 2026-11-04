"""Independent-contract regressions for native Pattern result and fixture edges."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest
from test_v0_pattern_workflows import Harness, make

from quant_hunter.config import JsonRecord, canonicalize_json
from quant_hunter.patterns.contracts import PatternError
from quant_hunter.storage import ObjectCorruptionError


@pytest.fixture(scope="module")
def h(tmp_path_factory: pytest.TempPathFactory) -> Harness:
    return make(tmp_path_factory.mktemp("pattern-reviewed"))


@pytest.fixture(scope="module")
def completed(h: Harness) -> dict[str, Any]:
    return h.execute(h.prepare())


@pytest.mark.parametrize(
    "field",
    [
        "canonical_binding",
        "dataset_id",
        "parent_snapshots",
        "method_id",
        "configuration",
        "evidence_mode",
    ],
)
def test_successful_result_requires_all_frozen_graph_edges(
    h: Harness, completed: dict[str, Any], monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    original = h.access.lab.get_run

    def missing(identity: str) -> JsonRecord:
        run = original(identity)
        cast(JsonRecord, run["result"]).pop(field)
        return run

    monkeypatch.setattr(h.access.lab, "get_run", missing)
    with pytest.raises(PatternError, match="RESULT_GRAPH_MISMATCH"):
        h.access.job(h.users["owner"], completed["job"]["id"])


def test_output_without_binding_is_counted_failed_before_evaluation(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = h.prepare()
    execute = h.access.product.execute_registered

    def omitted(*args: Any, **kwargs: Any) -> JsonRecord:
        result = execute(*args, **kwargs)
        result.pop("canonical_binding")
        return result

    monkeypatch.setattr(h.access.product, "execute_registered", omitted)
    result = h.execute(prepared)
    assert result["job"]["status"] == "FAILED"
    assert result["run"]["evaluation_outcome"] == "FAILED"
    assert result["run"]["variants_attempted"] == 1
    assert result["checkpoint_digest"]


@pytest.mark.parametrize(
    "change", ["price_scale", "volume_unit", "columns", "calendar"]
)
def test_positive_binds_tested_mapping_and_calendar(
    h: Harness, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    original = h.access._read
    dataset = h.datasets[0]

    def changed(digest: str) -> JsonRecord:
        value = original(digest)
        if digest == dataset["configuration_digest"] and change != "calendar":
            mapping = cast(JsonRecord, value["mapping"])
            if change == "columns":
                cast(JsonRecord, mapping["columns"])["close"] = "open"
            else:
                mapping[change] = "0.01" if change == "price_scale" else "LOTS"
        if digest == dataset["calendar_digest"] and change == "calendar":
            value["calendar_id"] = "FX_NY_17"
        return value

    monkeypatch.setattr(h.access, "_read", changed)
    with pytest.raises(PatternError, match="TESTED_NORMALIZATION"):
        h.prepare()


def test_corpus_source_union_is_not_accepted_from_its_own_record(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = h.access.lab.registry.verify_object
    identity = h.corpora[0]["dataset_id"]
    other_source = h.datasets[1]["source_id"]

    def changed(object_id: str) -> Any:
        revisions = original(object_id)
        if object_id == identity:
            record = dict(revisions[-1].record)
            record["source_ids"] = [other_source]
            return (*revisions[:-1], replace(revisions[-1], record=record))
        return revisions

    monkeypatch.setattr(h.access.lab.registry, "verify_object", changed)
    with pytest.raises(PatternError, match="CORPUS_GRAPH_MISMATCH"):
        h.access.corpus(h.users["owner"], identity)


def test_retained_corpus_environment_archive_remains_required(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = h.access.lab.environment_digest
    archive = h.access.lab.objects.publish(
        b"synthetic source archive for isolated review test"
    )
    environment = h.access.lab.objects.publish(
        canonicalize_json({"source_snapshot_digest": archive.digest})
    )
    try:
        h.access.lab.environment_digest = environment.digest
        corpus = h.access.materialize(h.users["owner"], h.selections[0])
    finally:
        h.access.lab.environment_digest = previous
    original = h.access.lab.objects.get

    def missing(digest: str) -> Any:
        if digest == archive.digest:
            raise ObjectCorruptionError("Synthetic missing executed source archive")
        return original(digest)

    monkeypatch.setattr(h.access.lab.objects, "get", missing)
    with pytest.raises(ObjectCorruptionError, match="source archive"):
        h.access.corpus(h.users["owner"], cast(str, corpus["dataset_id"]))
