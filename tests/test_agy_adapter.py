"""Antigravity CLI (agy) L3 adapter: the wiring contract, without a live agent.

Mirrors test_opencode_adapter.py — locks the launcher resolution (native Go
binary, %LOCALAPPDATA% probe for fresh installs, shim unwrap as belt-and-
braces), the headless argv (-p prompt, --dangerously-skip-permissions, a
--print-timeout softer than our hard kill), and the missing-binary error.
"""
from __future__ import annotations

import pytest

from sembl_stack.adapters import execute_agy as ag
from sembl_stack.adapters.base import Bounds, Task


def test_resolve_prefers_path_binary(monkeypatch):
    monkeypatch.setattr(ag.shutil, "which", lambda _: r"C:\x\agy.exe")
    assert ag._resolve_agy() == [r"C:\x\agy.exe"]

    monkeypatch.setattr(ag.shutil, "which", lambda _: r"C:\x\agy.CMD")
    assert ag._resolve_agy() == ["cmd", "/c", r"C:\x\agy.CMD"]

    monkeypatch.setattr(ag.shutil, "which", lambda _: r"C:\x\agy.ps1")
    assert ag._resolve_agy()[:2] == ["powershell", "-NoProfile"]


def test_resolve_probes_localappdata_when_not_on_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ag.shutil, "which", lambda _: None)
    monkeypatch.setattr(ag.os, "name", "nt")
    exe = tmp_path / "Antigravity" / "agy.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert ag._resolve_agy() == [str(exe)]


def test_resolve_empty_when_missing_everywhere(monkeypatch, tmp_path):
    monkeypatch.setattr(ag.shutil, "which", lambda _: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))   # exists, but no agy.exe
    assert ag._resolve_agy() == []


def test_run_builds_headless_argv(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        class P:
            returncode = 0
            stdout = "done"
            stderr = ""
        return P()

    monkeypatch.setattr(ag, "_resolve_agy", lambda: [r"C:\x\agy.exe"])
    monkeypatch.setattr(ag.subprocess, "run", fake_run)

    class FakeSandbox:
        workdir = "/tmp/wd"
        def diff(self):
            return "+++ b/src/app/__init__.py\n"

    ex = ag.AgyExecutor(model="gemini-3-pro", timeout=1800)
    result = ex.run(
        Task(text="add VERSION\nsecond line survives", repo="/tmp/wd"),
        Bounds(editable_paths=["src/app/"], forbidden_areas=["infra/"]),
        FakeSandbox(), feedback=None)

    cmd = captured["cmd"]
    assert cmd[0] == r"C:\x\agy.exe"
    assert "--dangerously-skip-permissions" in cmd
    prompt = cmd[cmd.index("-p") + 1]
    assert "add VERSION\nsecond line survives" in prompt   # native exe: newlines intact
    assert "You may ONLY edit these paths: src/app/" in prompt
    assert "Never touch: infra/" in prompt
    soft = cmd[cmd.index("--print-timeout") + 1]
    assert soft == "1770s"                                 # softer than the hard kill
    assert cmd[cmd.index("-m") + 1] == "gemini-3-pro"
    assert captured["cwd"] == "/tmp/wd"
    assert result.report["agent"] == "agy"
    assert result.report["files_modified"] == ["src/app/__init__.py"]


def test_missing_binary_is_an_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ag, "_resolve_agy", lambda: [])

    class FakeSandbox:
        workdir = "/tmp/wd"
        def diff(self):
            return ""

    with pytest.raises(RuntimeError) as exc:
        ag.AgyExecutor().run(Task(text="t", repo="/tmp/wd"),
                             Bounds(), FakeSandbox(), feedback=None)
    assert "agy" in str(exc.value) and "install" in str(exc.value).lower()


def test_gate_feedback_rides_the_retry_prompt():
    p = ag.AgyExecutor._prompt(
        Task(text="do the thing", repo="."), Bounds(),
        feedback="gate said: BLOCK because reasons")
    assert p.rstrip().endswith("gate said: BLOCK because reasons")
