"""OpenCode L3 adapter + clone sandbox: the wiring contract, without a live agent.

These lock in the fixes found while bringing the real executor online:
  * the Windows launcher must be resolved (a bare "opencode" is a .cmd/.ps1 shim that
    subprocess can't exec directly);
  * the headless invocation must carry --pure and --dangerously-skip-permissions and the
    configured model;
  * the sandbox is a *standalone clone* — it leaves the source repo completely untouched
    (no temp branches), which is also why OpenCode no longer hangs on a worktree .git file.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from sembl_stack.adapters import execute_opencode as oc
from sembl_stack.adapters.base import Bounds, Task
from sembl_stack.adapters.sandbox_worktree import WorktreeSandbox


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_resolve_launcher_wraps_shims(monkeypatch):
    monkeypatch.setattr(oc.shutil, "which", lambda _: r"C:\x\opencode.CMD")
    assert oc._resolve_opencode() == ["cmd", "/c", r"C:\x\opencode.CMD"]

    monkeypatch.setattr(oc.shutil, "which", lambda _: r"C:\x\opencode.ps1")
    assert oc._resolve_opencode()[:2] == ["powershell", "-NoProfile"]

    monkeypatch.setattr(oc.shutil, "which", lambda _: "/usr/bin/opencode")
    assert oc._resolve_opencode() == ["/usr/bin/opencode"]

    monkeypatch.setattr(oc.shutil, "which", lambda _: None)
    assert oc._resolve_opencode() == []


def test_run_builds_headless_argv(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        class P:  # noqa: D401 - tiny stand-in
            returncode = 0
            stdout = "done"
            stderr = ""
        return P()

    monkeypatch.setattr(oc, "_resolve_opencode", lambda: ["cmd", "/c", "opencode.CMD"])
    monkeypatch.setattr(oc.subprocess, "run", fake_run)

    class FakeSandbox:
        workdir = "/tmp/wd"
        def diff(self):
            return "+++ b/src/app/__init__.py\n"

    ex = oc.OpenCodeExecutor(model="tokenrouter/MiniMax-M3")
    result = ex.run(
        Task(text="add VERSION", repo="/tmp/wd"),
        Bounds(editable_paths=["src/app/"], forbidden_areas=["infra/"]),
        FakeSandbox(), feedback=None)

    cmd = captured["cmd"]
    assert cmd[:4] == ["cmd", "/c", "opencode.CMD", "run"]
    assert "--pure" in cmd and "--dangerously-skip-permissions" in cmd
    assert cmd[cmd.index("--model") + 1] == "tokenrouter/MiniMax-M3"
    assert any(c.startswith("add VERSION") for c in cmd)   # prompt passed through
    assert captured["cwd"] == "/tmp/wd"               # runs inside the sandbox
    assert result.report["model"] == "tokenrouter/MiniMax-M3"
    assert result.report["files_modified"] == ["src/app/__init__.py"]


def test_clone_sandbox_leaves_source_untouched(tmp_path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "a.py").write_text("# a\n", encoding="utf-8")
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t.t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)

    branches_before = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"], cwd=repo,
        capture_output=True, text=True).stdout

    sb = WorktreeSandbox().open(str(repo))
    try:
        assert Path(sb.workdir, ".git").is_dir()      # standalone repo, not a worktree file
        Path(sb.workdir, "a.py").write_text("# a\nVERSION = '0.1.0'\n", encoding="utf-8")
        diff = sb.diff()
        assert "VERSION" in diff
    finally:
        sb.close()

    assert not Path(sb.workdir).exists()              # disposable
    branches_after = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"], cwd=repo,
        capture_output=True, text=True).stdout
    assert branches_before == branches_after          # no temp branch left in the source
