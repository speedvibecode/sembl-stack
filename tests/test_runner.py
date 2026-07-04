"""TUI Phase 2 orchestration glue — the REAL loop streamed as stage events.

`runner.run_stages` must drive the same `loop.run` the CLI does (identical artifacts in the
run store) while emitting bounds/loop/verify transitions the stage rail renders. Pure and
headless — no Textual needed here; the wizard pilot test lives in tests/local.
"""
from __future__ import annotations

from types import SimpleNamespace

import yaml

from sembl_stack import runner
from sembl_stack.artifacts import Bounds, Change, Verdict
from sembl_stack.session import Session
from sembl_stack.store import RunStore
from sembl_stack.wizard import _rail_text, _verdict_text

DIFF = "diff --git a/x.py b/x.py\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"


def _cfg(tmp_path, gate_statuses, max_attempts=3):
    """A loop-shaped fake config: mock spec/sandbox/executor + a scripted gate."""

    class _Spec:
        def plan(self, task):
            return Bounds(editable_paths=["x.py"])

    class _Sandbox:
        workdir = str(tmp_path)

        def diff(self):
            return DIFF

        def close(self):
            pass

    class _SandboxAdapter:
        def open(self, repo):
            return _Sandbox()

    class _Executor:
        def run(self, task, bounds, sandbox, feedback):
            return Change(diff=DIFF, report={"exit_code": 0, "agent": "mock"},
                          workdir=sandbox.workdir)

    class _Gate:
        def __init__(self):
            self.calls = 0

        def verify(self, bounds, change, strict):
            status = gate_statuses[min(self.calls, len(gate_statuses) - 1)]
            self.calls += 1
            return Verdict(status=status,
                           reasons=[] if status == "PASS" else ["scripted block"])

    return SimpleNamespace(
        spec=_Spec(), sandbox=_SandboxAdapter(), execute=_Executor(), verify=_Gate(),
        strict=True, max_attempts=max_attempts, langfuse=False, raw={"loop": {}})


def test_run_stages_streams_events_and_persists_the_run(tmp_path):
    events = []
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = runner.run_stages(_cfg(tmp_path, ["PASS"]), task, events.append)

    assert result.verdict.status == "PASS"
    seq = [(e.stage, e.state) for e in events]
    assert seq == [
        ("bounds", "running"), ("bounds", "done"),
        ("sandbox", "done"),                   # L4 made visible: the cage opened
        ("loop", "running"), ("loop", "done"),
        ("verify", "running"), ("verify", "done"),
        ("verify", "done"),                    # the final-verdict event
    ]
    assert events[-1].detail == "PASS"
    # Byte-identical machinery: the run store carries the same artifacts as a CLI run.
    run = RunStore(str(tmp_path)).open(result.run_id)
    assert run.manifest()["status"] == "PASS"
    assert run.get("change").diff == DIFF


def test_retry_on_block_emits_one_loop_event_per_attempt(tmp_path):
    events = []
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = runner.run_stages(_cfg(tmp_path, ["BLOCK", "PASS"]), task, events.append)

    assert result.verdict.status == "PASS"
    assert result.attempts == 2
    loop_events = [e for e in events if e.stage == "loop"]
    assert [e.detail for e in loop_events] == \
        ["attempt 1", "attempt 1", "attempt 2", "attempt 2"]
    verify_states = [(e.state, e.detail) for e in events if e.stage == "verify"]
    assert ("fail", "BLOCK") in verify_states      # attempt 1's verdict shown honestly
    assert verify_states[-1] == ("done", "PASS")
    # a fresh sandbox is opened (and reported) every attempt, not just the first
    sandbox_events = [e for e in events if e.stage == "sandbox"]
    assert [e.detail for e in sandbox_events] == \
        ["attempt 1 — disposable clone", "attempt 2 — disposable clone"]


def test_sandbox_open_failure_emits_a_fail_event(tmp_path):
    events = []
    cfg = _cfg(tmp_path, ["PASS"])

    class _DeadSandbox:
        def open(self, repo):
            raise RuntimeError("clone failed")

    cfg.sandbox = _DeadSandbox()
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    try:
        runner.run_stages(cfg, task, events.append)
        raise AssertionError("expected the sandbox crash to propagate")
    except RuntimeError:
        pass
    sandbox_events = [e for e in events if e.stage == "sandbox"]
    assert [(e.state, e.detail) for e in sandbox_events] == [("fail", "attempt 1")]


def test_executor_failure_still_ends_with_a_fail_event(tmp_path):
    # The loop BLOCKs a crashed/empty execution WITHOUT calling the gate — the rail must
    # still land on a fail state via the final-verdict event.
    events = []
    cfg = _cfg(tmp_path, ["PASS"], max_attempts=1)

    class _DeadExecutor:
        def run(self, task, bounds, sandbox, feedback):
            return Change(diff="", report={"error": "timeout", "exit_code": -1},
                          workdir=sandbox.workdir)

    cfg.execute = _DeadExecutor()
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = runner.run_stages(cfg, task, events.append)

    assert result.verdict.status == "BLOCK"
    assert events[-1].stage == "verify"
    assert (events[-1].state, events[-1].detail) == ("fail", "BLOCK")


# --- task + config resolution ---------------------------------------------------

def test_load_task_reads_repo_task_yaml(tmp_path):
    (tmp_path / "task.yaml").write_text(
        yaml.safe_dump({"text": "add pause", "repo": "."}), encoding="utf-8")
    task = runner.load_task(str(tmp_path))
    assert task is not None
    assert task.text == "add pause"
    assert task.repo == str(tmp_path.resolve())


def test_load_task_missing_returns_none(tmp_path):
    assert runner.load_task(str(tmp_path)) is None


def test_resolve_config_repo_file_wins_over_profile(tmp_path, monkeypatch):
    from sembl_stack import profile as profile_mod
    monkeypatch.setattr(profile_mod, "load",
                        lambda p=None: profile_mod.Profile(runner="mock", executor="claude"))
    (tmp_path / "sembl.stack.yaml").write_text(
        "layers:\n  execute: mock\nloop:\n  max_attempts: 7\n", encoding="utf-8")
    cfg = runner.resolve_config(str(tmp_path))
    assert cfg.max_attempts == 7                   # the file, not the profile

    # Without the file, the onboarded profile is the default (CLI `loop` precedence).
    (tmp_path / "sembl.stack.yaml").unlink()
    monkeypatch.setattr(profile_mod, "load",
                        lambda p=None: profile_mod.Profile(
                            runner="mock", executor="mock", strict=False))
    cfg = runner.resolve_config(str(tmp_path))
    assert cfg.strict is False                     # profile override applied


# --- rail rendering (pure, no Textual) --------------------------------------------

def test_rail_text_live_states_override_session_marks():
    s = Session(repo=".", completed=[], current_stage="bounds")
    live = {"bounds": {"state": "done", "detail": ""},
            "loop": {"state": "running", "detail": "attempt 2"},
            "verify": {"state": "fail", "detail": "BLOCK"}}
    text = _rail_text(s, live)
    assert "[x] bounds" in text
    assert "[~] loop  (attempt 2)" in text
    assert "[!] verify  (BLOCK)" in text
    assert "[ ] merge" in text                     # untouched stages stay session-marked


def test_verdict_text_shows_status_reasons_and_run_id():
    result = SimpleNamespace(
        verdict=Verdict(status="BLOCK", reasons=["out-of-scope edit"]),
        attempts=3, run_id="20260703-abc")
    text = _verdict_text(result)
    assert "FINAL: BLOCK" in text
    assert "out-of-scope edit" in text
    assert "20260703-abc" in text
