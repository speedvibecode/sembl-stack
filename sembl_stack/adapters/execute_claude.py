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
  --output-format json            the result envelope carries `total_cost_usd` + `usage`
                                  — the REAL per-attempt cost signal the run store's
                                  `attempts_log` (C1.3) and the RSI-L1 readout consume.
                                  Parsed best-effort: a non-JSON stdout (older CLI, crash
                                  mid-stream) degrades to the raw text, never an error —
                                  and never an invented cost.
We deliberately do NOT pass --bare: that would force ANTHROPIC_API_KEY auth and ignore the
operator's OAuth login. Default auth keeps the "never see a token" property.
"""
from __future__ import annotations

import json
import shutil
import subprocess  # noqa: F401  (kept for tests that monkeypatch cc.subprocess.run)

from .base import (
    Bounds,
    ExecutionResult,
    Sandbox,
    Task,
    changed_files_from_diff as _changed_files,
    run_executor,
    scrub_secrets,
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
        cmd = [exe, "-p", "--dangerously-skip-permissions", "--output-format", "json"]
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
            "output": scrub_secrets(out)[-2000:],
            "stderr": scrub_secrets(err)[-1000:],
        }
        report.update(_usage_from_result_json(out))    # cost/usage — only when reported
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


def _usage_from_result_json(out: str) -> dict:
    """Cost/usage from the `--output-format json` result envelope — or {} (never invented).

    The envelope is `{"type": "result", ..., "total_cost_usd": <float>, "usage": {...}}`.
    Anything that doesn't parse as that shape (older CLI, text output, truncated stream)
    yields {} so the run store simply records no usage — the RSI readout then reports
    "not yet recorded" for the run instead of a fabricated number.
    """
    try:
        data = json.loads(out)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    extra: dict = {}
    cost = data.get("total_cost_usd")
    if isinstance(cost, (int, float)):
        extra["cost"] = cost
    usage = data.get("usage")
    if isinstance(usage, dict):
        usage = dict(usage)
        if "total_tokens" not in usage:
            parts = [usage.get(k) for k in ("input_tokens", "output_tokens")]
            if all(isinstance(p, int) for p in parts):
                usage["total_tokens"] = sum(parts)   # derived from reported parts only
        extra["usage"] = usage
    return extra
