"""L3 executor: OpenCode (OSS, 75+ models) driven headless in the sandbox.

Hands the task (plus the gate's feedback on retry, and the in-scope file list) to
`opencode run` inside the worktree, then reads back the diff. OpenCode supplies its own
model key; sembl-stack never sees a token. Requires `opencode` on PATH.
"""
from __future__ import annotations

import shutil
import subprocess

from .base import Bounds, ExecutionResult, Sandbox, Task


class OpenCodeExecutor:
    def __init__(self, model: str | None = None, timeout: int = 900):
        self.model = model
        self.timeout = timeout

    def run(self, task: Task, bounds: Bounds, sandbox: Sandbox,
            feedback: str | None) -> ExecutionResult:
        if not shutil.which("opencode"):
            raise RuntimeError(
                "L3: `opencode` not found on PATH. Install it, or set execute: mock.")

        prompt = self._prompt(task, bounds, feedback)
        cmd = ["opencode", "run", prompt]
        if self.model:
            cmd += ["--model", self.model]
        proc = subprocess.run(
            cmd, cwd=sandbox.workdir, capture_output=True, text=True,
            timeout=self.timeout)

        diff = sandbox.diff()
        report = {
            "files_modified": _changed_files(diff),
            "agent": "opencode",
            "exit_code": proc.returncode,
            "output": (proc.stdout or "")[-2000:],
        }
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


def _changed_files(diff: str) -> list[str]:
    files = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:])
    return files
