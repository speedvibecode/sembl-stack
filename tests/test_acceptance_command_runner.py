"""O12 WP2: the `command` acceptance runner adapter (L4.5, profile-agnostic core).

Proven headless on tiny fixtures built from `sys.executable -c "..."` — no external
toolchain, no shell builtins (a bare `exit 1` isn't a real executable on Windows and
would misreport as a spawn failure instead of a FAIL; `python -c` is portable).
"""
from __future__ import annotations

import sys

from sembl_stack.adapters import acceptance_command as ac_mod
from sembl_stack.adapters.acceptance_command import CommandAcceptanceRunner, _EVIDENCE_MAX
from sembl_stack.artifacts import Acceptance


class _Sandbox:
    def __init__(self, workdir):
        self.workdir = workdir


def _check(cid, command, expect=None, timeout_s=120, seed=None):
    return {"id": cid, "kind": "example", "profile": "command",
            "run": {"command": command}, "expect": expect or {},
            "seed": seed, "timeout_s": timeout_s}


def test_command_runner_pass(tmp_path):
    runner = CommandAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "ok", [sys.executable, "-c", "print('hello')"],
        {"exit_code": 0, "stdout_contains": "hello"})])
    report = runner.run(acc, _Sandbox(str(tmp_path)), task=None, bounds=None)

    assert len(report.results) == 1
    r = report.results[0]
    assert r["id"] == "ok"
    assert r["outcome"] == "PASS"
    assert r["detail"] == ""
    assert report.any_failed is False
    assert report.runner == "command@1"


def test_command_runner_fail_on_expect_mismatch():
    runner = CommandAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "bad", [sys.executable, "-c", "import sys; sys.exit(1)"], {"exit_code": 0})])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "FAIL"
    assert "exit_code" in r["detail"]
    assert report.any_failed is True


def test_command_runner_error_on_timeout():
    runner = CommandAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "slow", [sys.executable, "-c", "import time; time.sleep(5)"], {}, timeout_s=1)])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "ERROR"
    assert "timed out" in r["detail"]
    assert report.any_failed is True


def test_command_runner_error_on_spawn_failure():
    runner = CommandAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "missing", ["definitely-not-a-real-binary-xyz123"], {})])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "ERROR"
    assert "failed to start" in r["detail"].lower()


def test_command_runner_never_rejects_on_internal_crash(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom-internal")

    monkeypatch.setattr(ac_mod.subprocess, "run", boom)
    runner = CommandAcceptanceRunner()
    acc = Acceptance(checks=[_check("x", [sys.executable, "-c", "print(1)"])])

    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)   # must not raise
    r = report.results[0]
    assert r["outcome"] == "ERROR"
    assert "boom-internal" in r["detail"]


def test_command_runner_seed_recorded_on_result():
    runner = CommandAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "seeded", [sys.executable, "-c", "print(1)"], {"exit_code": 0}, seed=42)])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)
    assert report.results[0]["seed"] == 42


def test_command_runner_seed_none_for_example_kind():
    runner = CommandAcceptanceRunner()
    acc = Acceptance(checks=[_check("ex", [sys.executable, "-c", "print(1)"])])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)
    assert report.results[0]["seed"] is None


def test_command_runner_evidence_scrubbed_and_truncated(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "super-secret-value-123456")
    runner = CommandAcceptanceRunner()
    padding = "x" * 10000
    # padding first, secret last -> the secret survives the tail-truncation below.
    code = f"print('{padding}'); import os; print(os.environ['MY_API_KEY'])"
    acc = Acceptance(checks=[_check(
        "ev", [sys.executable, "-c", code], {"exit_code": 0})])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    ev = report.results[0]["evidence"]
    assert "super-secret-value-123456" not in ev
    assert "redacted" in ev
    assert len(ev) <= _EVIDENCE_MAX


def test_command_runner_reads_only_declared_checks_multiple():
    runner = CommandAcceptanceRunner()
    acc = Acceptance(checks=[
        _check("one", [sys.executable, "-c", "print(1)"], {"exit_code": 0}),
        _check("two", [sys.executable, "-c", "import sys; sys.exit(3)"], {"exit_code": 0}),
    ])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)
    outcomes = {r["id"]: r["outcome"] for r in report.results}
    assert outcomes == {"one": "PASS", "two": "FAIL"}


def test_command_runner_empty_expect_defaults_to_exit_code_zero(tmp_path):
    # Lead review fix: a check with no `expect` must not be a tautology (always-PASS).
    # The default expectation is "the command succeeds" (exit_code 0).
    runner = CommandAcceptanceRunner()
    acc = Acceptance(checks=[
        _check("no-expect-fails", [sys.executable, "-c", "raise SystemExit(3)"]),
        _check("no-expect-passes", [sys.executable, "-c", "pass"]),
    ])
    report = runner.run(acc, _Sandbox(str(tmp_path)), task=None, bounds=None)
    by_id = {r["id"]: r for r in report.results}
    assert by_id["no-expect-fails"]["outcome"] == "FAIL"
    assert "exit_code 3" in by_id["no-expect-fails"]["detail"]
    assert by_id["no-expect-passes"]["outcome"] == "PASS"
