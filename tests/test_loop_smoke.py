"""Smoke test: the short loop runs end to end and the gate does its job.

Creates a throwaway git repo with a Spec Kit tasks.md, then runs the loop with the
mock executor (misbehaves once -> BLOCK, then behaves -> PASS). Proves: L2 bounds,
L4 worktree, L3 execute, L5 verify, and L6 retry-on-BLOCK all wire together.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from sembl_stack.adapters.base import Task
from sembl_stack.config import StackConfig
from sembl_stack.adapters.spec_sembl import SemblSpecAdapter
from sembl_stack.adapters.execute_mock import MockExecutor
from sembl_stack.adapters.sandbox_worktree import WorktreeSandbox
from sembl_stack.adapters.verify_sembl import SemblVerifyAdapter
from sembl_stack.loop import run


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


def _make_repo(tmp: Path) -> Path:
    repo = tmp / "target"
    (repo / "src" / "app").mkdir(parents=True)
    (repo / "src" / "app" / "__init__.py").write_text("# app\n", encoding="utf-8")
    (repo / "infra").mkdir()
    (repo / "infra" / "deploy.yaml").write_text("kind: Deployment\n", encoding="utf-8")
    # A Spec Kit-style tasks.md naming the editable area.
    specs = repo / "specs" / "001-feature"
    specs.mkdir(parents=True)
    (specs / "tasks.md").write_text(
        "# Tasks\n\n- [ ] T001 update `src/app/__init__.py` to add a value\n",
        encoding="utf-8")
    # Hand-written bounds beside the spec, as a transport-independent fallback.
    (specs / "bounds.json").write_text(
        '{"editable_paths": ["src/app/"], '
        '"forbidden_areas": ["infra/"], '
        '"churn_budget": {"max_files": 4, "max_lines": 100}}',
        encoding="utf-8")
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t.t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    return repo


def _cfg() -> StackConfig:
    # CLI transport keeps the test hermetic (no MCP server spawn).
    return StackConfig(
        spec=SemblSpecAdapter(transport="cli"),
        execute=MockExecutor(),
        sandbox=WorktreeSandbox(),
        verify=SemblVerifyAdapter(transport="cli"),
        max_attempts=3, strict=True, langfuse=False,
        raw={"layers": {}},
    )


def test_loop_blocks_then_passes(tmp_path):
    repo = _make_repo(tmp_path)
    task = Task(text="add a value to the app module",
                repo=str(repo),
                spec_path=str(repo / "specs" / "001-feature"))
    result = run(_cfg(), task)

    statuses = [s for _, s in result.history]
    assert statuses[0] == "BLOCK", f"first attempt should block, got {statuses}"
    assert result.verdict.status == "PASS", f"loop should end PASS, got {statuses}"
    assert result.attempts >= 2
