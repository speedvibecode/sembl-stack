"""L3 executor: OpenCode (OSS, 75+ models) driven headless in the sandbox.

Hands the task (plus the gate's feedback on retry, and the in-scope file list) to
`opencode run` inside the worktree, then reads back the diff. OpenCode supplies its own
model key; sembl-stack never sees a token. Requires `opencode` on PATH.
"""
from __future__ import annotations

import shutil
import subprocess  # noqa: F401  (kept for tests that monkeypatch oc.subprocess.run)
from pathlib import Path

from .base import (
    Bounds,
    ExecutionResult,
    Sandbox,
    Task,
    changed_files_from_diff as _changed_files,
    run_executor,
    scrub_secrets,
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
        # Preserve the prompt's newlines: invoking the native opencode.exe directly (see
        # _resolve_opencode) passes argv straight through, so multi-line tasks and the gate's
        # multi-line retry feedback reach the agent intact. ONLY the legacy `cmd /c` shim
        # fallback truncates an argument at an embedded newline (cmd reads it as end-of-line),
        # so flatten to spaces in that case alone — never on the direct/POSIX path.
        if launcher and launcher[0].lower() == "cmd":
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
        # opencode resolves its project root via its own logic, NOT the inherited cwd, so
        # without this it escaped the sandbox and edited the *source* repo — leaving the
        # clone's diff empty (a false BLOCK). --dir nails it to the disposable clone, which
        # is the whole point of the cage.
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
            "output": scrub_secrets(out)[-2000:],
            "stderr": scrub_secrets(err)[-1000:],
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

    Prefer the real NATIVE binary so subprocess passes argv straight through — no `cmd /c`
    in the middle to truncate a multi-line prompt at the first newline. On Windows npm
    installs `opencode` as a `.cmd`/`.ps1` shim that itself calls
    `<dir>/node_modules/opencode-ai/bin/opencode.exe`; resolve to that exe directly. Fall
    back to invoking the shim through its interpreter only if the native exe isn't found
    (the caller then flattens newlines, since `cmd /c` would otherwise truncate). On POSIX
    `which` already returns the real binary.
    """
    exe = shutil.which("opencode")
    if not exe:
        return []
    # The native binary the npm shim wraps — invoke it directly when present.
    native = Path(exe).parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    if native.is_file():
        return [str(native)]
    low = exe.lower()
    if low.endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    if low.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", exe]
    return [exe]
