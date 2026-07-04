"""L3 executor subprocess wiring — the stdin fix for the 2026-07-04 field hang.

A user picked OpenCode (found on PATH, but with no provider configured); `opencode run`
likely opened its own interactive first-run setup, invisible because stdout/stderr are
captured into pipes, and sat waiting on the terminal's real stdin forever. A headless
factory executor must never be able to block like that.
"""
from __future__ import annotations

import subprocess

from sembl_stack.adapters.base import run_executor


def test_stdin_is_devnull_by_default(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        class P:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return P()

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_executor(["echo", "hi"], cwd=".", timeout=5)
    assert captured["stdin"] is subprocess.DEVNULL


def test_caller_can_still_override_stdin(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        class P:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return P()

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_executor(["echo", "hi"], cwd=".", timeout=5, stdin=subprocess.PIPE)
    assert captured["stdin"] is subprocess.PIPE
