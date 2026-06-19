"""L3 executor: Aider (OSS) driven headless in the sandbox.

Hands the task (plus the gate's feedback on retry, and the in-scope file list) to a
non-interactive `aider --message ...` run inside the worktree, then reads back the diff.
Aider resolves its own model credentials from the environment (e.g. OPENAI_API_BASE +
OPENAI_API_KEY for an OpenAI-compatible router, or ANTHROPIC_API_KEY) — sembl-stack never
handles a token. Requires `aider` on PATH.

Why the flags:
  --message <prompt>      run one instruction non-interactively and exit (headless).
  --yes-always            auto-confirm (create files, apply edits) — no TTY prompts.
  --no-auto-commits       leave edits in the WORKING TREE so the sandbox's `git diff`
                          captures them; otherwise aider commits and the diff looks empty.
  --no-stream / --no-check-update / --no-show-model-warnings
                          quiet, deterministic, non-blocking startup.
The model is a one-line config (`options.execute.model`), e.g. an `openai/<name>` route.
"""
from __future__ import annotations

import glob
import shutil
import subprocess
from pathlib import Path

from .base import (
    Bounds,
    ExecutionResult,
    Sandbox,
    Task,
    changed_files_from_diff as _changed_files,
    run_executor,
)


class AiderExecutor:
    def __init__(self, model: str | None = None, timeout: int = 900):
        self.model = model
        self.timeout = timeout

    def run(self, task: Task, bounds: Bounds, sandbox: Sandbox,
            feedback: str | None) -> ExecutionResult:
        exe = shutil.which("aider")
        if not exe:
            raise RuntimeError(
                "L3: `aider` not found on PATH. `pip install aider-chat`, or set execute: mock.")

        prompt = self._prompt(task, bounds, feedback)
        cmd = [exe, "--yes-always", "--no-auto-commits", "--no-stream",
               "--no-check-update", "--no-show-model-warnings", "--no-gitignore"]
        if self.model:
            cmd += ["--model", self.model]
        cmd += ["--message", prompt]
        cmd += _file_targets(bounds)          # focus aider on the in-scope files
        rc, out, err, timed_out = run_executor(
            cmd, cwd=sandbox.workdir, timeout=self.timeout, stdin=subprocess.DEVNULL)

        _clean_aider_scratch(sandbox.workdir)   # drop aider's own .aider* artifacts
        diff = sandbox.diff()
        report = {
            "files_modified": _changed_files(diff),
            "agent": "aider",
            "model": self.model,
            "exit_code": rc,
            "output": out[-2000:],
            "stderr": err[-1000:],
        }
        if timed_out:                          # surfaced to the gate as a BLOCK, not a crash
            report["error"] = "timeout"
            report["timed_out"] = True
        return ExecutionResult(diff=diff, report=report, workdir=sandbox.workdir)

    @staticmethod
    def _prompt(task: Task, bounds: Bounds, feedback: str | None) -> str:
        lines = [task.text, ""]
        if bounds.editable_paths:
            lines.append("You may ONLY edit these paths: "
                         + ", ".join(bounds.editable_paths))
        if bounds.forbidden_areas:
            lines.append("Never touch: " + ", ".join(bounds.forbidden_areas))
        if feedback:
            lines += ["", feedback]
        return "\n".join(lines)


def _clean_aider_scratch(workdir: str) -> None:
    """Remove aider's own working files (`.aider*`) before the diff is captured.

    Aider writes `.aider.chat.history.md`, `.aider.input.history`, and a
    `.aider.tags.cache.v4/` dir into the working directory. With `--no-gitignore` these are
    untracked clutter that the sandbox diff would otherwise pick up as out-of-scope edits.
    They are aider internals, never part of the change, so we delete them in the disposable
    cage before gating. Best-effort; failures are non-fatal.
    """
    for p in glob.glob(str(Path(workdir) / ".aider*")):
        path = Path(p)
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass


def _file_targets(bounds: Bounds) -> list[str]:
    """The concrete files aider should add to the chat (skip directory bounds)."""
    out = []
    for p in bounds.editable_paths:
        p = p.replace("\\", "/")
        if p.endswith("/"):
            continue                          # a directory prefix, not a file target
        if "." in p.rsplit("/", 1)[-1]:       # looks like a file (has an extension)
            out.append(p)
    return out
