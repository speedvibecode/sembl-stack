"""`doctor` (C4) — a config-aware environment preflight.

A stranger's first failure should be a clear diagnosis, not a stack trace. `run_checks`
inspects only what the (optional) config actually uses — it won't fail on a missing `claude`
when `execute: mock` — and returns structured `Check`s with actionable hints. The checks are
pure (no side effects) and don't import the heavy optionals, so they're unit-testable by
monkeypatching `shutil.which` / `find_spec`.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""
    required: bool = True       # an optional check that's missing -> WARN, not failure


def _have_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# executor layer name -> (binary on PATH, install hint)
_EXECUTOR_BINARY = {
    "claude": ("claude", "install Claude Code and log in (`claude`)"),
    "aider": ("aider", "`pip install aider-chat` and set your model env (OPENAI_API_KEY…)"),
    "opencode": ("opencode", "install OpenCode and ensure `opencode` is on PATH"),
}


def run_checks(cfg=None) -> list[Check]:
    """Structured preflight. `cfg` is an optional loaded StackConfig (config-aware checks)."""
    layers = (getattr(cfg, "raw", {}) or {}).get("layers", {}) if cfg else {}
    transport = (getattr(cfg, "raw", {}) or {}).get("transport", {}) if cfg else {}
    checks: list[Check] = []

    # --- always required ---
    py_ok = sys.version_info >= (3, 10)
    checks.append(Check(
        "python", py_ok, f"{sys.version_info.major}.{sys.version_info.minor}",
        "" if py_ok else "sembl-stack needs Python >= 3.10"))
    checks.append(Check(
        "git", shutil.which("git") is not None,
        shutil.which("git") or "not found", "install git (the sandbox clones the repo)"))

    # The gate (sembl) is the heart of the factory — required whenever verify=sembl.
    sembl_ok = _have_module("sembl")
    checks.append(Check(
        "sembl (gate)", sembl_ok, "importable" if sembl_ok else "missing",
        "" if sembl_ok else "`pip install sembl` into this environment", required=True))

    # --- transport-dependent (only when MCP transport is selected) ---
    uses_mcp = "mcp" in (transport.get("spec"), transport.get("verify"))
    if uses_mcp or cfg is None:
        mcp_ok = _have_module("mcp")
        checks.append(Check(
            "mcp (transport)", mcp_ok, "importable" if mcp_ok else "missing",
            "`pip install \"sembl[mcp]\"` — or use transport: cli (no MCP needed)",
            required=uses_mcp))
        server = transport.get("mcp_server", []) if cfg else ["uvx"]
        if server and server[0] == "uvx":
            uvx_ok = shutil.which("uvx") is not None
            checks.append(Check(
                "uvx (mcp launcher)", uvx_ok, shutil.which("uvx") or "not found",
                "install uv (`pip install uv`) — or point mcp_server at a local `sembl-mcp`",
                required=uses_mcp))

    # --- orchestration (optional: the loop has a zero-dep fallback) ---
    lg_ok = _have_module("langgraph")
    checks.append(Check(
        "langgraph (orchestration)", lg_ok, "importable" if lg_ok else "missing",
        "optional — the loop falls back to a built-in runner; `pip install langgraph` for "
        "the real retry graph", required=False))

    # --- executor binary (only the one the config actually selects) ---
    execute = layers.get("execute", "mock")
    if execute in _EXECUTOR_BINARY:
        binary, hint = _EXECUTOR_BINARY[execute]
        present = shutil.which(binary) is not None
        checks.append(Check(
            f"executor: {execute}", present, shutil.which(binary) or "not found",
            "" if present else hint, required=True))
    elif execute == "mock":
        checks.append(Check("executor: mock", True, "no binary needed", required=False))

    # --- context graph (only when context: symgraph) ---
    if layers.get("context") == "symgraph":
        sg_ok = shutil.which("symgraph") is not None
        checks.append(Check(
            "context: symgraph", sg_ok, shutil.which("symgraph") or "not found",
            "optional — `cargo install symgraph`; only needed for bounds --expand",
            required=False))

    return checks


def summarize(checks: list[Check]) -> tuple[bool, list[Check], list[Check]]:
    """Return (ready, blocking_failures, optional_warnings)."""
    blocking = [c for c in checks if c.required and not c.ok]
    warnings = [c for c in checks if not c.required and not c.ok]
    return (not blocking), blocking, warnings
