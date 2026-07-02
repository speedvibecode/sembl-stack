"""Loop run manifest behavior that backs the inspect/apply workflow."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sembl_stack import loop as loop_mod
from sembl_stack.artifacts import Bounds, Change, Verdict
from sembl_stack.store import RunStore


def test_run_manifest_preserves_warn_and_final_change(tmp_path):
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
            return Change(diff=diff, report={"exit_code": 1}, workdir=sandbox.workdir)

    class _Gate:
        def verify(self, bounds, change, strict):
            return Verdict(status="PASS")

    cfg = SimpleNamespace(
        spec=_Spec(), sandbox=_SandboxAdapter(), execute=_Executor(), verify=_Gate(),
        strict=True, max_attempts=1, langfuse=False, raw={"loop": {}})
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "WARN"
    run = RunStore(str(tmp_path)).open(result.run_id)
    assert run.manifest()["status"] == "WARN"
    assert run.get("change").diff == diff


def test_loop_crash_persists_failed_status_and_closes_sandbox(tmp_path):
    # A crash outside the executor (here: the gate itself) must not leave the run stuck
    # at "started" with an open sandbox — codex audit finding 6.
    diff = "diff --git a/x.py b/x.py\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"
    closed = {"n": 0}

    class _Spec:
        def plan(self, task):
            return Bounds(editable_paths=["x.py"])

    class _Sandbox:
        workdir = str(tmp_path)

        def diff(self):
            return diff

        def close(self):
            closed["n"] += 1

    class _SandboxAdapter:
        def open(self, repo):
            return _Sandbox()

    class _Executor:
        def run(self, task, bounds, sandbox, feedback):
            return Change(diff=diff, report={"exit_code": 0}, workdir=sandbox.workdir)

    class _Gate:
        def verify(self, bounds, change, strict):
            raise RuntimeError("gate exploded")

    cfg = SimpleNamespace(
        spec=_Spec(), sandbox=_SandboxAdapter(), execute=_Executor(), verify=_Gate(),
        strict=True, max_attempts=1, langfuse=False, raw={"loop": {}})
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    with pytest.raises(RuntimeError, match="gate exploded"):
        loop_mod.run(cfg, task)

    store = RunStore(str(tmp_path))
    runs = store.list_runs()
    assert runs, "the run directory must still exist"
    m = store.open(runs[0]).manifest()
    assert m["status"] == "failed"
    assert "gate exploded" in m["error"]
    assert closed["n"] >= 1                       # the cage was closed on the way out
