"""L4.5 acceptance runner: the `contract` adapter (O12, WP4 — Foundry invariant/fuzz
profile).

A thin adapter over `CommandAcceptanceRunner` (WP2's profile-agnostic core), same
shape as `acceptance_web.py`: the `contract` profile's job is only profile-specific
defaults/validation/seed-forwarding, never a reimplementation of the shim-resolution
/ timeout-clamp / evidence-scrub machinery `command` already proved headless. A
`profile:"contract"` check's `run.command` is a `forge test` invocation (invariant
or fuzz campaign) against a Foundry project — this runner:

1. rejects a check with no declared `run.command` instead of silently no-oping
   (mirrors the command/web runners' own fail-closed discipline);
2. fails closed with an actionable "install Foundry" detail when `forge` is not on
   PATH — a contract check is Foundry-only by construction, so a missing toolchain
   here should read as a diagnosis, not a generic "failed to start command";
3. gives contract checks the same generous default timeout as `web` (a `forge test`
   invariant/fuzz campaign can run far longer than an arbitrary command), still
   capped at the shared `_MAX_TIMEOUT_S`;
4. pins a declared `seed` onto the `forge` invocation as `--fuzz-seed <seed>` for
   deterministic replay — ONLY when the check declares a non-null integer seed AND
   the resolved command is actually a `forge` invocation (basename match, `.cmd`/
   `.exe` tolerated); a check with no seed gets no injected flag. The base runner
   already records the check's declared seed on the result dict — this only makes
   sure the flag reaches the subprocess. Built as a copy of the check's `run` dict;
   the caller's check object is never mutated.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .acceptance_command import CommandAcceptanceRunner, _MAX_TIMEOUT_S, _to_argv

_RUNNER_ID = "contract@1"
# Foundry invariant/fuzz campaigns can run far longer than a bare command; give the
# same headroom as `web`, still bounded by the shared cap.
_DEFAULT_TIMEOUT_S = min(300, _MAX_TIMEOUT_S)


def _toolchain_missing() -> str | None:
    """`forge` absent from PATH -> the honest, actionable detail.

    A `profile:"contract"` check is Foundry-only by construction (it drives a
    `forge test` invocation against a Solidity project); if it doesn't resolve,
    fail fast with an install hint instead of surfacing a generic spawn-failure
    detail.
    """
    if shutil.which("forge"):
        return None
    return ("forge not found on PATH — install Foundry "
            "(https://getfoundry.sh) to run contract acceptance checks")


def _is_forge_argv(argv: list[str]) -> bool:
    """True if `argv[0]` resolves (by basename) to `forge`, tolerating a Windows
    `.cmd`/`.exe`/`.bat` shim suffix. Used to decide whether it's safe to append a
    foundry-specific `--fuzz-seed` flag — never do that to an arbitrary command."""
    if not argv:
        return False
    name = Path(str(argv[0])).name.lower()
    for suffix in (".cmd", ".exe", ".bat"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name == "forge"


class ContractAcceptanceRunner(CommandAcceptanceRunner):
    """`profile:"contract"` — a Foundry invariant/fuzz invocation against a Solidity
    project (e.g. `examples/contract-invariant`), reusing the command runner's
    subprocess/shim/timeout/evidence machinery in full."""

    def __init__(self, default_timeout: int = _DEFAULT_TIMEOUT_S):
        super().__init__(default_timeout=default_timeout)

    def run(self, acceptance, sandbox, task, bounds):
        report = super().run(acceptance, sandbox, task, bounds)
        report.runner = _RUNNER_ID
        return report

    def _exec(self, check: dict, sandbox) -> tuple[str, str, str]:
        run = check.get("run") or {}
        argv = _to_argv(run.get("command"))
        if not argv:
            return ("ERROR",
                     "contract check declared no run.command "
                     "(profile:contract requires one)", "")
        missing = _toolchain_missing()
        if missing:
            return "ERROR", missing, ""

        seed = check.get("seed")
        if isinstance(seed, int) and not isinstance(seed, bool) and _is_forge_argv(argv):
            # Append the fuzz seed to a COPY of the command/run/check dicts — never
            # mutate the caller's check object (that object may be the loop's own
            # declared Acceptance.checks entry).
            new_argv = [*argv, "--fuzz-seed", str(seed)]
            check = {**check, "run": {**run, "command": new_argv}}

        return super()._exec(check, sandbox)
