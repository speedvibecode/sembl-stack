"""L4.5 acceptance runner: the `web` adapter (O12, WP3 — DOM-flow profile).

A thin adapter over `CommandAcceptanceRunner` (WP2's profile-agnostic core): the
`web` profile's job is only profile-specific defaults/validation, never a
reimplementation of the shim-resolution / timeout-clamp / evidence-scrub machinery
`command` already proved headless. A `profile:"web"` check's `run.command` is a
test-runner invocation the target already ships (or, absent one, a minimal script
added alongside it, per spec §6.2) — this runner:

1. rejects a check with no declared `run.command` instead of silently no-oping
   (mirrors the command runner's own fail-closed discipline);
2. fails closed with an actionable "install Node" detail when neither `node` nor
   `npx` is on PATH — a web check is Node-only by construction, so a spawn failure
   here should read as a missing-toolchain diagnosis, not a generic
   "failed to start command";
3. gives web checks more startup headroom by default than the bare `command`
   profile (a dev server takes longer to boot than an arbitrary command) via the
   runner-level `default_timeout`, still capped at the shared `_MAX_TIMEOUT_S`;
4. runs in the sandbox workdir by default — inherited for free from
   `CommandAcceptanceRunner._exec`, no override needed.
"""
from __future__ import annotations

import shutil

from .acceptance_command import CommandAcceptanceRunner, _MAX_TIMEOUT_S, _to_argv

_RUNNER_ID = "web@1"
# Web checks boot a dev server first; give more room than command's 120s default,
# still bounded by the shared cap.
_DEFAULT_TIMEOUT_S = min(300, _MAX_TIMEOUT_S)


def _toolchain_missing() -> str | None:
    """Both `node` and `npx` absent from PATH -> the honest, actionable detail.

    A `profile:"web"` check is Node-only by construction (it drives a JS
    test-runner invocation against a Node app); if neither resolves, fail fast
    with an install hint instead of surfacing a generic spawn-failure detail.
    """
    if shutil.which("node") or shutil.which("npx"):
        return None
    return ("node/npx not found on PATH — install Node.js "
            "(https://nodejs.org) to run web acceptance checks")


class WebAcceptanceRunner(CommandAcceptanceRunner):
    """`profile:"web"` — a test-runner invocation against a web target (e.g.
    `examples/flagship-feedback-board`), reusing the command runner's
    subprocess/shim/timeout/evidence machinery in full."""

    def __init__(self, default_timeout: int = _DEFAULT_TIMEOUT_S):
        super().__init__(default_timeout=default_timeout)

    def run(self, acceptance, sandbox, task, bounds):
        report = super().run(acceptance, sandbox, task, bounds)
        report.runner = _RUNNER_ID
        return report

    def _exec(self, check: dict, sandbox) -> tuple[str, str, str]:
        run = check.get("run") or {}
        if not _to_argv(run.get("command")):
            return "ERROR", "web check declared no run.command (profile:web requires one)", ""
        missing = _toolchain_missing()
        if missing:
            return "ERROR", missing, ""
        return super()._exec(check, sandbox)
