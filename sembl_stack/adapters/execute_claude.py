"""L3 executor: Claude Code (Anthropic) driven headless in the sandbox.

Hands the task (plus the gate's feedback on retry, and the in-scope file list) to
`claude -p` (print / non-interactive mode) inside the worktree, then reads back the diff.
Claude Code uses the operator's own logged-in session (OAuth/keychain) — sembl-stack never
handles a token. Requires `claude` on PATH.

Why the flags:
  -p / --print                    non-interactive: run the task and exit (no TUI).
  --dangerously-skip-permissions  headless edits otherwise block on a per-write approval
                                  prompt. Safe here: the agent runs inside a disposable
                                  git-worktree sandbox (the cage, not the repo) — only the
                                  diff is gated and the worktree is thrown away after.
We deliberately do NOT pass --bare: that would force ANTHROPIC_API_KEY auth and ignore the
operator's OAuth login. Default auth keeps the "never see a token" property.
"""
from __future__ import annotations

import shutil
import subprocess  # noqa: F401  (kept for tests that monkeypatch cc.subprocess.run)

from .base import (
    Bounds,
    ExecutionResult,
    Sandbox,
    Task,
    changed_files_from_diff as _changed_files,
    run_executor,
)


class ClaudeCodeExecutor:
    def __init__(self, model: str | None = None, timeout: int = 900):
        self.model = model
        self.timeout = timeout

    def run(self, task: Task, bounds: Bounds, sandbox: Sandbox,
            feedback: str | None) -> ExecutionResult:
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError(
                "L3: `claude` not found on PATH. Install Claude Code, or set execute: mock.")

        prompt = self._prompt(task, bounds, feedback)
        cmd = [exe, "-p", "--dangerously-skip-permissions"]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append(prompt)
        rc, out, err, timed_out = run_executor(
            cmd, cwd=sandbox.workdir, timeout=self.timeout)

        diff = sandbox.diff()
        report = {
            "files_modified": _changed_files(diff),
            "agent": "claude-code",
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
