"""Live-run stage-event recording (`.sembl/runs/<id>/events.jsonl`).

The IDE's factory strip (docs/DESIGN-sembl-ide.md §5 step 2) tails this file to light up
stage dots while a `loop` run executes. These tests pin the shape loop.py actually writes —
one JSON line per real stage transition, never fabricated — using the same fake-adapter
style as test_loop_manifest.py.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from sembl_stack import loop as loop_mod
from sembl_stack.artifacts import Bounds, Change, Verdict
from sembl_stack.store import RunStore


def _read_events(repo, run_id):
    path = RunStore(str(repo)).open(run_id).dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_events_jsonl_records_start_and_done_for_each_stage(tmp_path):
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- /dev/null\n"
        "+++ b/x.py\n"
        "@@ -0,0 +1 @@\n"
        "+x = 1\n"
    )

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

    cfg = SimpleNamespace(
        spec=_Spec(), sandbox=_SandboxAdapter(), execute=_Executor(), verify=_Gate(),
        strict=True, max_attempts=1, langfuse=False, raw={"loop": {}})
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)
    assert result.verdict.status == "PASS"

    events = _read_events(tmp_path, result.run_id)
    by_stage = {}
    for e in events:
        by_stage.setdefault(e["stage"], []).append(e["status"])
        assert set(e.keys()) == {"ts", "stage", "status", "attempt"}

    assert by_stage["spec"] == ["start", "done"]
    assert by_stage["sandbox"] == ["start", "done"]
    assert by_stage["execute"] == ["start", "done"]
    assert by_stage["verify"] == ["start", "done"]
    # execute/sandbox/verify events carry the 1-based attempt number.
    exec_events = [e for e in events if e["stage"] == "execute"]
    assert all(e["attempt"] == 1 for e in exec_events)


def test_events_jsonl_marks_a_crashed_executor_as_failed(tmp_path):
    diff = "diff --git a/x.py b/x.py\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"

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
            raise RuntimeError("executor crashed")

    class _Gate:
        def verify(self, bounds, change, strict):
            return Verdict(status="PASS")

    cfg = SimpleNamespace(
        spec=_Spec(), sandbox=_SandboxAdapter(), execute=_Executor(), verify=_Gate(),
        strict=True, max_attempts=1, langfuse=False, raw={"loop": {}})
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)
    assert result.verdict.status == "BLOCK"        # crash -> BLOCK, per the C1 hardening

    events = _read_events(tmp_path, result.run_id)
    exec_statuses = [e["status"] for e in events if e["stage"] == "execute"]
    assert exec_statuses == ["start", "failed"]


def test_run_manifest_status_started_means_running(tmp_path):
    """run.json's `status` already doubles as the running/finished signal ("started" until
    the loop finishes, then the verdict status or "failed") — the IDE reads this rather than
    a new field, per DESIGN-sembl-ide.md §5 step 2."""
    store = RunStore(str(tmp_path))
    run = store.new_run()
    assert run.manifest()["status"] == "started"
    run.set_status("PASS")
    assert run.manifest()["status"] == "PASS"
