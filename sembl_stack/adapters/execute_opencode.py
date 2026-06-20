"""L3 executor: OpenCode (OSS, 75+ models) driven headless in the sandbox.

Hands the task (plus the gate's feedback on retry, and the in-scope file list) to
`opencode run` inside the worktree, then reads back the diff. OpenCode supplies its own
model key; sembl-stack never sees a token. Requires `opencode` on PATH.
"""
from __future__ import annotations

import shutil
import subprocess  # noqa: F401  (kept for tests that monkeypatch oc.subprocess.run)

from .base import (
    Bounds,
    ExecutionResult,
    Sandbox,
    Task,
    changed_files_from_diff as _changed_files,
    run_executor,
)


class OpenCodeExecutor:
    def __init__(self, model: str | None = None, timeout: int = 900):
        self.model = model
        self.timeout = timeout

    def run(self, task: Task, bounds: Bounds, sandbox: Sandbox,
            feedback: str | None) -> ExecutionResult:
        launcher = _resolve_opencode()
        if not launcher:
            raise RuntimeError(
                "L3: `opencode` not found on PATH. Install it, or set execute: mock.")

        prompt = self._prompt(task, bounds, feedback)
        # Flatten newlines to spaces: the prompt is passed as a single argv, and through
        # the Windows `cmd /c` shim an embedded newline truncates the argument (cmd reads
        # it as end-of-line) — opencode would receive only the first line of a multi-line
        # task. Joining with spaces preserves every word; newlines aren't load-bearing in
        # an instruction.
        prompt = " ".join(prompt.splitlines())
        # --dangerously-skip-permissions: headless `opencode run` otherwise blocks on an
        # interactive approval prompt for every file write. It is safe here because the
        # agent runs inside a disposable git-worktree sandbox (the cage, not the repo) —
        # the diff is what gets gated, and the worktree is thrown away after.
        # --pure: ignore the user's external plugins/skills/global agents. The factory
        # wants a lean, deterministic agent driven only by the task + bounds we hand it —
        # not whatever happens to be in the operator's personal opencode config. It also
        # shrinks the request (smaller/faster, less prone to free-tier queueing).
        # --dir: pin opencode's working directory to the sandbox clone explicitly.
        # opencode resolves its project root via its own logic, NOT the inherited cwd —
        # on Windows (launched through the `.cmd` shim) that let it escape the sandbox and
        # edit the *source* repo, leaving the clone's diff empty (a false BLOCK). Passing
        # --dir nails it to the disposable clone, which is the whole point of the cage.
        cmd = launcher + ["run", "--pure", "--dangerously-skip-permissions",
                          "--dir", sandbox.workdir, prompt]
        if self.model:
            cmd += ["--model", self.model]
        rc, out, err, timed_out = run_executor(
            cmd, cwd=sandbox.workdir, timeout=self.timeout)

        diff = sandbox.diff()
        report = {
            "files_modified": _changed_files(diff),
            "agent": "opencode",
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


def _resolve_opencode() -> list[str]:
    """Return the argv prefix that actually launches opencode.

    On Windows, npm installs `opencode` as a `.cmd`/`.ps1` shim. Passing the bare name
    (or even the shim path) to subprocess fails: CreateProcess ignores PATHEXT and can't
    execute a script directly. Resolve the shim and invoke it through its interpreter.
    On POSIX, `which` returns the real binary and we use it as-is.
    """
    exe = shutil.which("opencode")
    if not exe:
        return []
    low = exe.lower()
    if low.endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    if low.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", exe]
    return [exe]
