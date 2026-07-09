"""O12 WP2 §4.3: the `acceptance` node wired between `execute` and `verify`.

Uses a stub verify adapter that implements the behavioral fold semantics (FAIL/ERROR/
missing declared-check -> BLOCK, with the check id in the reasons) — the real
cross-repo gate integration (../sembl WP1) is verified separately once both packages
land; these tests only prove the factory-side wiring: the acceptance node runs the
real `CommandAcceptanceRunner` in the sandbox, persists the report, and the result
reaches `verify()` and then `Verdict.feedback()`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sembl_stack import loop as loop_mod
from sembl_stack.adapters.acceptance_command import CommandAcceptanceRunner
from sembl_stack.artifacts import Bounds, Change, Verdict
from sembl_stack.store import RunStore


def _read_events(repo, run_id):
    path = RunStore(str(repo)).open(run_id).dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


class _BehavioralGate:
    """Mirrors the ../sembl WP1 fold: a declared check with no matching result, or a
    FAIL/ERROR result, blocks — with the check id + detail in `reasons`."""

    def verify(self, bounds, change, strict, acceptance=None):
        reasons = []
        if acceptance:
            results_by_id = {r["id"]: r for r in acceptance.get("results", [])}
            for c in acceptance.get("declared", []):
                r = results_by_id.get(c["id"])
                if r is None:
                    reasons.append(f"declared behavioral check with no result: {c['id']}")
                elif r.get("outcome") in ("FAIL", "ERROR"):
                    reasons.append(
                        f"behavioral checks failed: {c['id']}: {r.get('detail', '')}")
        if reasons:
            return Verdict(status="BLOCK", reasons=reasons)
        return Verdict(status="PASS")


_DIFF = "diff --git a/x.py b/x.py\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"


def _cfg(repo, acceptance_runner):
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
            return Change(diff=_DIFF, report={"exit_code": 0}, workdir=sandbox.workdir)

    return SimpleNamespace(
        spec=_Spec(), sandbox=_SandboxAdapter(), execute=_Executor(),
        verify=_BehavioralGate(), acceptance=acceptance_runner,
        strict=True, max_attempts=1, langfuse=False, raw={"loop": {}})


def _write_acceptance(repo: Path, command, expect):
    (repo / "acceptance.json").write_text(json.dumps({
        "checks": [{
            "id": "must-print-ok", "kind": "example", "profile": "command",
            "run": {"command": command}, "expect": expect,
        }]
    }), encoding="utf-8")


def test_loop_blocks_on_failing_acceptance_check_with_id_in_feedback(tmp_path):
    _write_acceptance(tmp_path, [sys.executable, "-c", "import sys; sys.exit(1)"],
                      {"exit_code": 0})
    cfg = _cfg(tmp_path, CommandAcceptanceRunner())
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "BLOCK"
    assert "must-print-ok" in result.verdict.feedback()

    events = _read_events(tmp_path, result.run_id)
    acc_statuses = [e["status"] for e in events if e["stage"] == "acceptance"]
    assert acc_statuses == ["start", "done"]

    report = RunStore(str(tmp_path)).open(result.run_id).get("acceptance-1")
    assert report is not None
    assert report.results[0]["id"] == "must-print-ok"
    assert report.results[0]["outcome"] == "FAIL"
    assert report.any_failed is True


def test_loop_passing_acceptance_check_leaves_verdict_to_trespass_axes(tmp_path):
    _write_acceptance(tmp_path, [sys.executable, "-c", "print('ok')"],
                      {"exit_code": 0, "stdout_contains": "ok"})
    cfg = _cfg(tmp_path, CommandAcceptanceRunner())
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    report = RunStore(str(tmp_path)).open(result.run_id).get("acceptance-1")
    assert report.results[0]["outcome"] == "PASS"
    assert report.any_failed is False


def test_loop_noop_skip_when_no_acceptance_declared(tmp_path):
    # No acceptance.json written at all -> the axis is a strict no-op even though a
    # real runner is configured.
    cfg = _cfg(tmp_path, CommandAcceptanceRunner())
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    events = _read_events(tmp_path, result.run_id)
    acc_statuses = [e["status"] for e in events if e["stage"] == "acceptance"]
    assert acc_statuses == ["skip"]
    assert RunStore(str(tmp_path)).open(result.run_id).get("acceptance-1") is None


def test_loop_noop_skip_when_runner_is_none_even_if_declared(tmp_path):
    # acceptance.json declares a check, but the runner is `none` (disabled) -> still a
    # strict no-op; a declared-but-disabled check must NOT read as a missing result.
    _write_acceptance(tmp_path, [sys.executable, "-c", "print('ok')"], {"exit_code": 0})
    cfg = _cfg(tmp_path, None)   # registry.build("acceptance", "none", ...) resolves to None
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    events = _read_events(tmp_path, result.run_id)
    acc_statuses = [e["status"] for e in events if e["stage"] == "acceptance"]
    assert acc_statuses == ["skip"]
