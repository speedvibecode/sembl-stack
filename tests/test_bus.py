"""The event bus (`sembl_stack/bus.py`, SPEC-O11 §2, D5) — WP-A.

Covers the API pinned in §2.1 (publish/read_since), the publish points wired in
§2.3 (store.Run.append_event -> run.stage, loop.run -> run.started/verdict/
finished, drift.check_drift -> drift.new), and the never-raise contract that
mirrors `store.append_event`: a bus failure must never surface as an exception.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from sembl_stack import bus
from sembl_stack import drift
from sembl_stack import loop as loop_mod
from sembl_stack.artifacts import Bounds, Change, SpecGraph, Verdict
from sembl_stack.store import RunStore

_UNRELATED_CODE_GRAPH = {"results": [{"name": "Something", "file_path": "src/something.ts"}]}


def _one_concept_spec() -> SpecGraph:
    return SpecGraph(nodes=[
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback item"},
    ])


# --- 1. publish/read round-trip -----------------------------------------------------

def test_publish_read_round_trip_preserves_order_and_fields(tmp_path):
    bus.publish(tmp_path, {"kind": "run.started", "run_id": "r1", "summary": "first",
                            "data": {"a": 1}})
    bus.publish(tmp_path, {"kind": "run.finished", "run_id": "r1", "summary": "second",
                            "data": {"a": 2}})

    events, cursor = bus.read_since(tmp_path)

    assert [e["summary"] for e in events] == ["first", "second"]
    assert events[0]["kind"] == "run.started"
    assert events[1]["kind"] == "run.finished"
    assert events[0]["data"] == {"a": 1}
    assert events[1]["data"] == {"a": 2}
    assert all(isinstance(e["ts"], float) for e in events)
    assert cursor > 0


# --- 2. cursor semantics -------------------------------------------------------------

def test_read_since_cursor_returns_only_new_events(tmp_path):
    bus.publish(tmp_path, {"kind": "run.started", "run_id": "r1", "summary": "one"})
    first_events, cursor = bus.read_since(tmp_path)
    assert len(first_events) == 1

    bus.publish(tmp_path, {"kind": "run.finished", "run_id": "r1", "summary": "two"})
    bus.publish(tmp_path, {"kind": "drift.new", "summary": "three"})

    second_events, cursor2 = bus.read_since(tmp_path, cursor)
    assert [e["summary"] for e in second_events] == ["two", "three"]
    assert cursor2 > cursor

    # from-scratch read still sees everything, in order.
    all_events, _ = bus.read_since(tmp_path)
    assert [e["summary"] for e in all_events] == ["one", "two", "three"]


# --- 3. torn trailing line ------------------------------------------------------------

def test_torn_trailing_line_is_skipped_without_advancing_cursor(tmp_path):
    bus.publish(tmp_path, {"kind": "run.started", "run_id": "r1", "summary": "whole"})
    events, cursor = bus.read_since(tmp_path)
    assert len(events) == 1

    bus_file = tmp_path / bus.BUS_PATH
    partial = '{"kind": "run.finished", "run_id": "r1", "summary": "torn"'
    with bus_file.open("a", encoding="utf-8") as f:
        f.write(partial)          # deliberately no trailing newline: a torn write

    events2, cursor2 = bus.read_since(tmp_path, cursor)
    assert events2 == []
    assert cursor2 == cursor      # must NOT advance past the incomplete line

    # completing the line (closing brace + newline) makes it readable on the next call,
    # still from the SAME cursor.
    with bus_file.open("a", encoding="utf-8") as f:
        f.write('}\n')
    events3, cursor3 = bus.read_since(tmp_path, cursor2)
    assert len(events3) == 1
    assert events3[0]["summary"] == "torn"
    assert cursor3 > cursor2


# --- 4. never-raise on unwritable path -------------------------------------------------

def test_publish_never_raises_on_unwritable_root(tmp_path):
    not_a_dir = tmp_path / "im_a_file"
    not_a_dir.write_text("nope", encoding="utf-8")

    result = bus.publish(not_a_dir, {"kind": "run.started", "summary": "x"})

    assert result is None       # returned silently, no exception propagated


# --- 5. unknown kind -> "other" + raw_kind ---------------------------------------------

def test_unknown_kind_is_stored_as_other_with_raw_kind(tmp_path):
    bus.publish(tmp_path, {"kind": "totally.unrecognized", "summary": "mystery"})

    events, _ = bus.read_since(tmp_path)
    assert len(events) == 1
    assert events[0]["kind"] == "other"
    assert events[0]["raw_kind"] == "totally.unrecognized"


def test_missing_kind_is_also_stored_as_other(tmp_path):
    bus.publish(tmp_path, {"summary": "no kind at all"})

    events, _ = bus.read_since(tmp_path)
    assert events[0]["kind"] == "other"
    assert events[0]["raw_kind"] is None


def test_non_serializable_data_degrades_to_string_not_dropped(tmp_path):
    # A Path (or any non-JSON value) inside `data` must not silently drop the whole
    # event inside the never-raise envelope — it degrades to its string form.
    bus.publish(tmp_path, {"kind": "run.started", "summary": "with a path",
                            "data": {"where": tmp_path}})

    events, _ = bus.read_since(tmp_path)
    assert len(events) == 1
    assert events[0]["data"]["where"] == str(tmp_path)


# --- 5b. postdeploy.status fires through the real verify() when repo is passed ----------

def test_postdeploy_verify_publishes_status_when_repo_passed(tmp_path):
    from sembl_stack.adapters.base import Delivery
    from sembl_stack.adapters.postdeploy_http import HttpPostDeployGate

    gate = HttpPostDeployGate()
    bad = Delivery(target="vercel", status="failed", data={})

    verdict = gate.verify(bad, repo=str(tmp_path))
    assert verdict.status == "BLOCK"
    events, _ = bus.read_since(tmp_path)
    assert [e["kind"] for e in events] == ["postdeploy.status"]
    assert events[0]["data"]["status"] == "BLOCK"

    # without repo (legacy callers) verify still works and publishes nothing new.
    verdict2 = gate.verify(bad)
    assert verdict2.status == "BLOCK"
    events2, _ = bus.read_since(tmp_path)
    assert len(events2) == 1


# --- 6. run.stage mirrored from store.Run.append_event ---------------------------------

def test_append_event_mirrors_run_stage_to_the_bus(tmp_path):
    run = RunStore(str(tmp_path)).new_run()
    run.append_event("spec", "start")
    run.append_event("spec", "done", attempt=1)

    events, _ = bus.read_since(tmp_path)
    stage_events = [e for e in events if e["kind"] == "run.stage"]
    assert len(stage_events) == 2
    assert all(e["run_id"] == run.id for e in stage_events)
    assert stage_events[0]["data"] == {"stage": "spec", "status": "start", "attempt": 0}
    assert stage_events[1]["data"] == {"stage": "spec", "status": "done", "attempt": 1}


# --- 7. loop publishes started/verdict/finished (fallback engine) ----------------------

def _fallback_loop_cfg(diff, tmp_path):
    class _Spec:
        def plan(self, task):
            return Bounds(editable_paths=["x.py"])

    class _Sandbox:
        workdir = str(tmp_path)

        def diff(self):
            return diff

        def close(self):
            pass

    class _SandboxAdapter:
        def open(self, repo):
            return _Sandbox()

    class _Executor:
        def run(self, task, bounds, sandbox, feedback):
            return Change(diff=diff, report={"exit_code": 0}, workdir=sandbox.workdir)

    class _Gate:
        def verify(self, bounds, change, strict):
            return Verdict(status="PASS")

    return SimpleNamespace(
        spec=_Spec(), sandbox=_SandboxAdapter(), execute=_Executor(), verify=_Gate(),
        strict=True, max_attempts=1, langfuse=False, raw={"loop": {}})


def test_loop_publishes_started_verdict_finished_on_fallback_engine(tmp_path, monkeypatch):
    # Force the fallback branch deterministically (this venv may or may not have
    # langgraph importable) — the two engines share all the post-processing code in
    # `loop.run` where the bus publish calls live, so this exercises exactly the same
    # code the langgraph path would.
    def _raise_import_error(*a, **kw):
        raise ImportError("forced for test")

    monkeypatch.setattr(loop_mod, "_run_langgraph", _raise_import_error)

    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- /dev/null\n"
        "+++ b/x.py\n"
        "@@ -0,0 +1 @@\n"
        "+x = 1\n"
    )
    cfg = _fallback_loop_cfg(diff, tmp_path)
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)
    assert result.engine == "fallback"

    events, _ = bus.read_since(tmp_path)
    kinds = {e["kind"] for e in events}
    assert {"run.started", "run.verdict", "run.finished"} <= kinds
    for kind in ("run.started", "run.verdict", "run.finished"):
        matches = [e for e in events if e["kind"] == kind]
        assert len(matches) == 1
        assert matches[0]["run_id"] == result.run_id

    verdict_event = next(e for e in events if e["kind"] == "run.verdict")
    assert verdict_event["data"]["status"] == result.verdict.status == "PASS"


# --- 8. drift.new only when new findings exist ------------------------------------------

def test_drift_new_published_only_when_new_findings_exist(tmp_path):
    state_path = tmp_path / ".sembl" / "drift-state.json"
    spec = _one_concept_spec()

    result = drift.check_drift(spec, _UNRELATED_CODE_GRAPH, state_path=state_path)
    assert len(result.new) == 1

    events, cursor = bus.read_since(tmp_path)
    drift_events = [e for e in events if e["kind"] == "drift.new"]
    assert len(drift_events) == 1
    assert drift_events[0]["data"]["count"] == 1
    assert len(drift_events[0]["data"]["keys"]) == 1

    # a second check against the SAME spec/code graph has nothing new -> no extra event.
    second = drift.check_drift(spec, _UNRELATED_CODE_GRAPH, state_path=state_path)
    assert second.new == []

    events2, _ = bus.read_since(tmp_path, cursor)
    assert [e for e in events2 if e["kind"] == "drift.new"] == []
