"""Artifact contract + run store: round-trip and persistence."""
from __future__ import annotations

import pytest

from sembl_stack import artifacts
from sembl_stack.artifacts import (
    Bounds, Change, ReconciliationReport, SpecGraph, Task, Verdict,
)
from sembl_stack.store import RunStore


def test_artifact_roundtrip_via_tag():
    b = Bounds(editable_paths=["src/"], forbidden_areas=["infra/"],
               churn_budget={"max_files": 4}, sources=["tasks.md"])
    # generic reconstruction from the tagged dict
    again = artifacts.from_dict(b.to_dict())
    assert isinstance(again, Bounds)
    assert again.editable_paths == ["src/"]
    assert again.to_contract() == {
        "editable_paths": ["src/"], "forbidden_areas": ["infra/"],
        "churn_budget": {"max_files": 4}}

    graph = SpecGraph(
        nodes=[{"id": "task", "type": "task", "name": "task"}],
        edges=[],
        sources=["task.text"],
        data={"schema_version": 1},
    )
    again_graph = artifacts.from_dict(graph.to_dict())
    assert isinstance(again_graph, SpecGraph)
    assert again_graph.nodes[0]["id"] == "task"

    report = ReconciliationReport(status="ALIGNED", summary="ok")
    again_report = artifacts.from_dict(report.to_dict())
    assert isinstance(again_report, ReconciliationReport)
    assert again_report.status == "ALIGNED"


def test_verdict_helpers():
    v = Verdict(status="BLOCK", reasons=["out-of-scope: infra/x"])
    assert v.blocked
    assert "out-of-scope" in v.feedback()
    assert artifacts.from_dict(v.to_dict()).status == "BLOCK"


def test_run_store_put_get_manifest(tmp_path):
    store = RunStore(str(tmp_path))
    run = store.new_run(Task(text="t", repo=str(tmp_path)))
    run.put(Bounds(editable_paths=["src/"]))
    run.put(Change(diff="--- a\n+++ b\n", report={"files_modified": ["src/x"]}),
            name="change-1")
    run.set_status("PASS", attempts=2)

    assert store.list_runs() == [run.id]
    loaded = run.get("bounds")
    assert isinstance(loaded, Bounds) and loaded.editable_paths == ["src/"]
    m = run.manifest()
    assert m["status"] == "PASS" and m["attempts"] == 2
    assert "bounds" in m["artifacts"] and "change-1" in m["artifacts"]


def test_open_rejects_path_shaped_run_ids(tmp_path):
    # A run id is a directory NAME, never a path — a crafted id must not resolve
    # (or mkdir) outside .sembl/runs (codex audit finding 4).
    store = RunStore(str(tmp_path))
    for bad in ("../evil", r"..\evil", "a/b", r"a\b", ".hidden", "..", ""):
        with pytest.raises(ValueError):
            store.open(bad)
    run = store.new_run()
    assert store.open(run.id).manifest()["id"] == run.id   # real ids still open
