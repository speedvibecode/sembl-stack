"""L3 executor: Antigravity CLI (`agy`), Google's terminal agent (Gemini CLI's
successor — the individual Gemini Code Assist tier was retired in its favor).

Drives `agy -p` headless inside the sandbox clone, then reads back the diff.
agy supplies its own auth (Google sign-in / keyring); sembl-stack never sees a
token. Requires `agy` on PATH — the installer drops a native Go binary into
%LOCALAPPDATA%\\Antigravity\\ on Windows, which we also probe directly so a
fresh install works before the user reopens their shell.

Headless contract (learned live 2026-07-12):
  * `-p <prompt>` one-shot print mode; native exe, so multi-line prompts pass
    through argv intact (no `cmd /c` newline truncation — the opencode lesson).
  * `--dangerously-skip-permissions`: print mode otherwise blocks on tool
    approvals. Safe here for the same reason as opencode: the agent runs inside
    a disposable clone (the cage), and the DIFF is what gets gated.
  * `--print-timeout <Go duration>`: agy's own print-mode budget defaults to
    5m — far too small for a work package. Pinned just under our hard kill
    timeout so agy dies politely before run_executor kills it.
  * model selection is agy-internal; `-m` is honored when configured but the
    CLI auto-routes by default.
"""
from __future__ import annotations

import os
import shutil
import subprocess  # noqa: F401  (kept for tests that monkeypatch ag.subprocess.run)
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


class AgyExecutor:
    def __init__(self, model: str | None = None, timeout: int = 1800):
        self.model = model
        self.timeout = timeout

    def run(self, task: Task, bounds: Bounds, sandbox: Sandbox,
            feedback: str | None) -> ExecutionResult:
        launcher = _resolve_agy()
        if not launcher:
            raise RuntimeError(
                "L3: `agy` not found on PATH (or %LOCALAPPDATA%\\Antigravity). "
                "Install it (irm https://antigravity.google/cli/install.ps1 | iex) "
                "and sign in once, or set execute: mock.")

        prompt = self._prompt(task, bounds, feedback)
        if launcher[0].lower() == "cmd":
            # only the legacy shim fallback truncates argv at a newline
            prompt = " ".join(prompt.splitlines())
        # agy's own print budget must expire BEFORE run_executor's hard kill, so
        # the agent exits with its partial output instead of being killed silently.
        soft_timeout = max(self.timeout - 30, 60)
        # --new-project: agy anchors its workspace to a PROJECT, not the cwd — a
        # prior session (even an interactive one the operator ran elsewhere) would
        # otherwise be resumed and agy would edit THAT tree while cwd sits in the
        # sandbox. Found live 2026-07-12: the first self-host run escaped the cage
        # and wrote a whole feature into the source repo while every sandbox diff
        # came back empty. A fresh project per invocation anchors to cwd = clone.
        cmd = launcher + ["--new-project", "-p", prompt,
                          "--dangerously-skip-permissions",
                          "--print-timeout", f"{soft_timeout}s"]
        if self.model:
            cmd += ["--model", self.model]
        rc, out, err, timed_out = run_executor(
            cmd, cwd=sandbox.workdir, timeout=self.timeout)

        diff = sandbox.diff()
        report = {
            "files_modified": _changed_files(diff),
            "agent": "agy",
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
        lines.append("Work ONLY inside the current working directory.")
        if feedback:
            lines += ["", feedback]
        return "\n".join(lines)


def _resolve_agy() -> list[str]:
    """Return the argv prefix that launches agy.

    agy ships as a native Go binary, so PATH resolution is usually the whole
    story. Two extra cases: (1) a fresh install lands in
    %LOCALAPPDATA%\\Antigravity\\ before the user's PATH refresh — probe it;
    (2) if some wrapper installed a .cmd/.ps1 shim anyway, unwrap it the same
    way the opencode/deploy_vercel adapters do."""
    exe = shutil.which("agy")
    if not exe and os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            # the official installer's target (verified live 2026-07-12)
            cand = Path(local) / "agy" / "bin" / "agy.exe"
            if cand.is_file():
                return [str(cand)]
    if not exe:
        return []
    low = exe.lower()
    if low.endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    if low.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", exe]
    return [exe]
