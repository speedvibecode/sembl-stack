"""SPEC-stage-preview-as-evidence WP-A: `sandbox.prepare` — a declared dependency
install command that runs in the attempt's clone before execute. Absent key is a
byte-identical no-op; a declared command that fails is an honest run failure
carrying the command's stderr, never a silent skip; a timeout is enforced; every
transition publishes a `run.stage` event (the same mechanism every other stage
transition uses).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sembl_stack import loop as loop_mod
from sembl_stack.artifacts import Bounds, Change, Verdict
from sembl_stack.store import RunStore


def _read_events(repo, run_id):
    path = RunStore(str(repo)).open(run_id).dir / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _read_bus(repo):
    path = Path(repo) / ".sembl" / "bus.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


_DIFF = "diff --git a/x.py b/x.py\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"


def _cfg(repo, *, sandbox_decl=None, executor_calls=None):
    class _Spec:
        def plan(self, task):
            return Bounds(editable_paths=["x.py"])

    class _Sandbox:
        workdir = str(repo)

        def diff(self):
            return _DIFF

        def close(self):
            pass

    class _SandboxAdapter:
        def open(self, r):
            return _Sandbox()

    class _Executor:
        def run(self, task, bounds, sandbox, feedback):
            if executor_calls is not None:
                executor_calls.append(1)
            return Change(diff=_DIFF, report={"exit_code": 0}, workdir=sandbox.workdir)

    class _Gate:
        def verify(self, bounds, change, strict, **kw):
            return Verdict(status="PASS")

    raw = {"loop": {}}
    if sandbox_decl is not None:
        raw["sandbox"] = sandbox_decl

    return SimpleNamespace(
        spec=_Spec(), sandbox=_SandboxAdapter(), execute=_Executor(),
        verify=_Gate(), acceptance=None, stage=None,
        strict=True, max_attempts=1, langfuse=False, raw=raw)


def test_absent_prepare_key_is_byte_identical_noop(tmp_path):
    calls = []
    cfg = _cfg(tmp_path, sandbox_decl=None, executor_calls=calls)
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    assert calls == [1]                          # the executor ran normally
    events = _read_events(tmp_path, result.run_id)
    assert [e["status"] for e in events if e["stage"] == "prepare"] == []


def test_declared_prepare_succeeds_then_executor_runs(tmp_path):
    calls = []
    marker = tmp_path / "prepared.txt"
    cmd = [sys.executable, "-c",
          f"open(r'{marker}', 'w').write('ok')"]
    cfg = _cfg(tmp_path, sandbox_decl={"prepare": cmd}, executor_calls=calls)
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    assert calls == [1]
    events = _read_events(tmp_path, result.run_id)
    prepare_statuses = [e["status"] for e in events if e["stage"] == "prepare"]
    assert prepare_statuses == ["start", "done"]


def test_declared_prepare_publishes_run_stage_bus_events(tmp_path):
    cmd = [sys.executable, "-c", "pass"]
    cfg = _cfg(tmp_path, sandbox_decl={"prepare": cmd})
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    bus_events = _read_bus(tmp_path)
    prepare_bus = [e for e in bus_events
                  if e["kind"] == "run.stage" and e["data"]["stage"] == "prepare"]
    assert [e["data"]["status"] for e in prepare_bus] == ["start", "done"]
    assert result.verdict.status == "PASS"


def test_declared_prepare_failure_blocks_and_never_calls_executor(tmp_path):
    calls = []
    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('npm ci exploded'); sys.exit(1)"]
    cfg = _cfg(tmp_path, sandbox_decl={"prepare": cmd}, executor_calls=calls)
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "BLOCK"
    assert calls == []                            # the executor never ran
    assert any("prepare" in r and "npm ci exploded" in r for r in result.verdict.reasons)
    events = _read_events(tmp_path, result.run_id)
    assert [e["status"] for e in events if e["stage"] == "prepare"] == ["start", "failed"]


def test_declared_prepare_timeout_is_enforced_and_blocks(tmp_path):
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    cfg = _cfg(tmp_path, sandbox_decl={"prepare": cmd, "timeout_s": 1})
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "BLOCK"
    assert any("timed out" in r for r in result.verdict.reasons)


def test_prepare_failure_skips_declared_acceptance_checks(tmp_path):
    """Lead-review fix: the acceptance node must skip on prepare_error exactly like
    the stage node does — running declared checks against a sandbox whose deps never
    installed burns their timeouts and records misleading ERRORs."""
    runner_calls = []

    class _Runner:
        def run(self, acceptance, sandbox, task, bounds):
            runner_calls.append(1)
            raise AssertionError("acceptance runner must not run after a prepare failure")

    (tmp_path / "acceptance.json").write_text(json.dumps({
        "version": 1,
        "checks": [{"id": "smoke", "profile": "command@1", "run": ["true"],
                    "expect": {"exit_code": 0}}],
    }), encoding="utf-8")
    cmd = [sys.executable, "-c", "import sys; sys.exit(1)"]
    cfg = _cfg(tmp_path, sandbox_decl={"prepare": cmd})
    cfg.acceptance = _Runner()
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "BLOCK"
    assert runner_calls == []
    events = _read_events(tmp_path, result.run_id)
    assert [e["status"] for e in events if e["stage"] == "acceptance"] == ["skip"]


def test_prepare_missing_binary_fails_honestly_not_a_traceback(tmp_path):
    cfg = _cfg(tmp_path, sandbox_decl={"prepare": "this-binary-does-not-exist-anywhere"})
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)              # must not raise

    assert result.verdict.status == "BLOCK"
    assert any("prepare" in r for r in result.verdict.reasons)
