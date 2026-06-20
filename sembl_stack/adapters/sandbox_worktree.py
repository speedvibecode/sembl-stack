"""L4 sandbox adapter: an isolated local clone of the target repo.

The cheapest real sandbox — the executor edits a throwaway checkout, never the user's
working tree. We use a local `git clone` (not `git worktree add`) on purpose:

  * A clone is a *standalone* repo (a real `.git` directory). A linked worktree has a
    `.git` *file* pointing back at the parent, and some agents (notably OpenCode, whose
    startup snapshots the project) hang on Windows when launched inside one.
  * A clone touches the user's repo not at all — no temp branches left behind. The
    worktree approach had to create and later delete a branch in the source repo.

Swap-in candidates (E2B, Daytona) implement the same `open()` contract:
`open(repo) -> sandbox` exposing `.workdir`, `.diff()`, `.close()`.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path


def _force_rmtree(path: str) -> None:
    """rmtree that survives Windows: git packs objects read-only, which blocks delete."""
    def _on_error(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_on_error)


class _Clone:
    def __init__(self, repo: str, workdir: str):
        self.repo = repo
        self.workdir = workdir

    def diff(self) -> str:
        # Stage everything (incl. new/untracked files) and diff against the clone's HEAD.
        # encoding/errors explicit: a diff can carry UTF-8 (non-ASCII source, filenames),
        # which the default locale codec (cp1252 on Windows) fails to decode — losing the
        # diff and producing a false "empty diff" BLOCK.
        subprocess.run(
            ["git", "add", "-A"], cwd=self.workdir, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        proc = subprocess.run(
            ["git", "diff", "--cached"], cwd=self.workdir,
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        return proc.stdout

    def close(self) -> None:
        # The clone is fully disposable and the source repo was never modified.
        try:
            _force_rmtree(self.workdir)
        except OSError:
            pass  # a stray handle (e.g. AV scan) — leave it for the OS temp sweep


class WorktreeSandbox:
    """A disposable standalone clone. (Name kept for config back-compat: `sandbox: worktree`.)"""

    def open(self, repo: str) -> _Clone:
        repo = str(Path(repo).resolve())
        workdir = str(Path(tempfile.gettempdir()) / f"sembl-stack-{uuid.uuid4().hex[:8]}")
        proc = subprocess.run(
            ["git", "clone", "--quiet", "--local", "--no-hardlinks", repo, workdir],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"L4: git clone failed: {proc.stderr.strip()}")
        # Give the clone a committer identity so any agent that commits won't error.
        for k, v in (("user.email", "agent@sembl.local"), ("user.name", "sembl-agent")):
            subprocess.run(["git", "config", k, v], cwd=workdir,
                           capture_output=True, text=True)
        return _Clone(repo, workdir)


# Clearer alias for new configs (`sandbox: clone`); same implementation.
CloneSandbox = WorktreeSandbox
