"""L4.5 acceptance runner: the `command` adapter (O12, WP2 — profile-agnostic core).

The minimal, language-agnostic harness: run a declared check's `run.command` inside
the L4 sandbox workdir, map its exit code / stdout / stderr against `expect`, and
NEVER let anything raise into the loop — any internal failure (spawn failure,
timeout, an unexpected crash) becomes an `ERROR` result instead of a propagated
exception. The runner reads checks ONLY from the `Acceptance` contract it is
handed — never from the diff or the executor's report.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from .base import Acceptance, AcceptanceReport, Bounds, Sandbox, Task, scrub_secrets

_RUNNER_ID = "command@1"
_DEFAULT_TIMEOUT_S = 120
_MAX_TIMEOUT_S = 600
_EVIDENCE_MAX = 4000     # tail-truncated, like the execute adapters' scrub_secrets(out)[-2000:]


def _to_argv(command) -> list[str] | None:
    """`run.command` (an argv list or a shell-style string) -> an argv list, or None
    if it's missing/empty. Strings are split with POSIX-off on Windows so backslash
    paths survive `shlex.split` unescaped."""
    if isinstance(command, list) and command:
        return [str(c) for c in command]
    if isinstance(command, str) and command.strip():
        return shlex.split(command, posix=(os.name != "nt"))
    return None


def _resolve_shim(argv: list[str]) -> list[str]:
    """Windows .cmd/.bat/.ps1 shim resolution (mirrors `deploy_vercel.py`'s
    `_resolve_vercel`) — CreateProcess cannot exec a batch file directly, so an
    npm-installed CLI invoked bare (`npx ...`, `forge ...`) raises FileNotFoundError
    under a plain `subprocess.run`. Resolve the first token through `shutil.which`
    and route .cmd/.bat/.ps1 shims through their own interpreter; anything else (a
    real .exe, an absolute path, a POSIX shebang binary) passes through unchanged.
    A name not found on PATH is left as-is — subprocess raises its own
    FileNotFoundError, which the caller converts into an ERROR result."""
    if not argv:
        return argv
    which = shutil.which(argv[0])
    if not which:
        return argv
    low = which.lower()
    if low.endswith((".cmd", ".bat")):
        return ["cmd", "/c", which, *argv[1:]]
    if low.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 which, *argv[1:]]
    return [which, *argv[1:]]


def _clamp_timeout(v) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        v = _DEFAULT_TIMEOUT_S
    return min(v, _MAX_TIMEOUT_S)


def _prepare_evidence(stdout: str, stderr: str) -> str:
    """Captured stdout/stderr -> secret-scrubbed, tail-truncated evidence text (the
    no-secrets-in-artifacts invariant, same discipline the execute adapters apply to
    their own captured output)."""
    parts = []
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    combined = scrub_secrets("\n\n".join(parts))
    return combined[-_EVIDENCE_MAX:]


def _evaluate(returncode: int, stdout: str, stderr: str, expect: dict) -> tuple[str, str]:
    """(returncode, stdout, stderr) vs. `expect` -> (outcome, detail). All present
    `expect` keys must hold for a PASS; any that don't hold -> FAIL with the reasons."""
    failures = []
    if "exit_code" in expect and returncode != expect["exit_code"]:
        failures.append(f"exit_code {returncode} != expected {expect['exit_code']!r}")
    if "stdout_contains" in expect and expect["stdout_contains"] not in stdout:
        failures.append(f"stdout did not contain {expect['stdout_contains']!r}")
    if "stderr_contains" in expect and expect["stderr_contains"] not in stderr:
        failures.append(f"stderr did not contain {expect['stderr_contains']!r}")
    if "stdout_not_contains" in expect and expect["stdout_not_contains"] in stdout:
        failures.append(f"stdout unexpectedly contained {expect['stdout_not_contains']!r}")
    if failures:
        return "FAIL", "; ".join(failures)
    return "PASS", ""


class CommandAcceptanceRunner:
    """`profile:"command"` — the profile-agnostic core axis, proven headless on a
    tiny in-repo fixture (a passing check and a failing check), no external
    toolchain required."""

    def __init__(self, default_timeout: int = _DEFAULT_TIMEOUT_S):
        self.default_timeout = default_timeout

    def run(self, acceptance: Acceptance, sandbox: Sandbox, task: Task,
            bounds: Bounds) -> AcceptanceReport:
        results = [self._run_one(check, sandbox) for check in acceptance.checks]
        return AcceptanceReport(results=results, runner=_RUNNER_ID)

    def _run_one(self, check: dict, sandbox: Sandbox) -> dict:
        cid = check.get("id", "")
        seed = check.get("seed")
        t0 = time.perf_counter()
        try:
            outcome, detail, evidence = self._exec(check, sandbox)
        except Exception as exc:
            # Never-reject (§4.2): any internal crash here becomes an ERROR result,
            # never a raised exception that would abort the loop.
            outcome, detail, evidence = "ERROR", f"acceptance runner crashed: {exc!r}", ""
        duration_s = round(time.perf_counter() - t0, 3)
        return {
            "id": cid,
            "outcome": outcome,
            "seed": seed,
            "duration_s": duration_s,
            "evidence": evidence,
            "detail": detail,
        }

    def _exec(self, check: dict, sandbox: Sandbox) -> tuple[str, str, str]:
        run = check.get("run") or {}
        expect = check.get("expect") or {}
        argv = _to_argv(run.get("command"))
        if not argv:
            return "ERROR", "no command declared in check.run.command", ""
        argv = _resolve_shim(argv)
        cwd_rel = run.get("cwd")
        workdir = getattr(sandbox, "workdir", None) or "."
        cwd = str(Path(workdir) / cwd_rel) if cwd_rel else workdir
        if not expect:
            # A check with no expectation must not be a tautology (always-PASS is the
            # fail-open this whole axis exists to prevent). The universal convention —
            # "the command succeeds" — is the default expectation.
            expect = {"exit_code": 0}
        timeout_s = _clamp_timeout(check.get("timeout_s"))
        try:
            proc = subprocess.run(
                argv, cwd=cwd, capture_output=True, text=True, timeout=timeout_s,
                encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or ""
            err = exc.stderr or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            if isinstance(err, bytes):
                err = err.decode("utf-8", "replace")
            return "ERROR", f"timed out after {timeout_s}s", _prepare_evidence(out, err)
        except (OSError, ValueError) as exc:
            return "ERROR", f"failed to start command: {exc}", ""
        outcome, detail = _evaluate(proc.returncode, proc.stdout or "", proc.stderr or "",
                                    expect)
        return outcome, detail, _prepare_evidence(proc.stdout or "", proc.stderr or "")
