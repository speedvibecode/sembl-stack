"""Artifact contract + run store: round-trip and persistence."""
from __future__ import annotations

from sembl_stack import artifacts
from sembl_stack.artifacts import Bounds, Change, Task, Verdict
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
