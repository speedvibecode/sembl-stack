"""L4 sandbox adapter: an isolated git worktree.

The cheapest real sandbox — the executor edits a throwaway checkout, never the user's
working tree. Swap-in candidates (E2B, Daytona) implement the same `open()` contract.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


class _Worktree:
    def __init__(self, repo: str, workdir: str, branch: str):
        self.repo = repo
        self.workdir = workdir
        self.branch = branch

    def diff(self) -> str:
        proc = subprocess.run(
            ["git", "add", "-A"], cwd=self.workdir, capture_output=True, text=True)
        proc = subprocess.run(
            ["git", "diff", "--cached"], cwd=self.workdir,
            capture_output=True, text=True)
        return proc.stdout

    def close(self) -> None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", self.workdir],
            cwd=self.repo, capture_output=True, text=True)
        # best-effort cleanup if the worktree dir lingers
        if Path(self.workdir).exists():
            shutil.rmtree(self.workdir, ignore_errors=True)
        subprocess.run(
            ["git", "branch", "-D", self.branch], cwd=self.repo,
            capture_output=True, text=True)


class WorktreeSandbox:
    def open(self, repo: str) -> _Worktree:
        repo = str(Path(repo).resolve())
        branch = f"sembl-stack/{uuid.uuid4().hex[:8]}"
        workdir = str(Path(tempfile.gettempdir()) / f"sembl-stack-{uuid.uuid4().hex[:8]}")
        proc = subprocess.run(
            ["git", "worktree", "add", "-b", branch, workdir, "HEAD"],
            cwd=repo, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"L4: git worktree add failed: {proc.stderr.strip()}")
        return _Worktree(repo, workdir, branch)
