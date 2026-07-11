"""sembl-stack-mcp — the operator's typed hands over MCP (SPEC-O11 §3, D4/D6).

The operator "harness" is not a thing we build: sembl-stack grows an MCP server
exposing the existing engine's typed tools, and ANY MCP-speaking agent becomes an
operator by connecting. Mirrors `../sembl/sembl/mcp_server.py` structurally: tool
bodies are plain module-level functions (unit-testable with no MCP transport);
`main()` lazily imports FastMCP and registers exactly the nine tools on a stdio
server. Requires the `mcp` extra: `pip install "sembl-stack[mcp]"`.

Discipline encoded here, not just documented (SPEC-O11 §3.2):
  - Zero judgment: no code path in this module constructs or mutates a `Verdict` —
    tools only read persisted verdicts (via `run.get("verdict")`) or forward one
    the loop already computed.
  - No free-form hands: the nine tools below are the ENTIRE surface. No shell tool,
    no file-write tool, no apply/merge/override tool.
  - Read-only guide separation (O9): `factory_guide` is never imported here.
  - Secrets (O15): `read_config` returns layer/adapter NAMES only — never resolved
    credentials, env values, or profile secret material.
  - stdio transport discipline: NOTHING in this module writes to stdout (stdout is
    the MCP protocol channel). The one exception is the missing-`mcp`-dependency
    message in `main()`, which goes to stderr and exits nonzero — never a traceback.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from . import cli, discuss, drift, guide, registry
from .bus import read_since
from .loop import run as _run_loop
from .store import RunStore

# --------------------------------------------------------------------------- #
# read state (read-only)
# --------------------------------------------------------------------------- #


def _read_run_events(run_dir: Path, limit: int = 20) -> list[dict]:
    """The last `limit` lines of a run's own `events.jsonl` (stage transitions),
    parsed as JSON. Never raises: a missing file or a corrupt line degrades to
    fewer events, not an error — this is a read-only convenience view over a file
    `store.Run.append_event` already writes, not a new engine capability."""
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def read_state(repo: str, run_id: str | None = None) -> dict:
    """No `run_id`: list runs (id, status, task line, verdict status) from the
    `RunStore`. With `run_id`: that run's manifest + verdict (status, reasons) +
    its last 20 stage events + which artifact files exist. An unknown/invalid
    `run_id` returns `{"error": ...}`, never a traceback."""
    store = RunStore(repo)
    if run_id is None:
        runs = []
        for rid in store.list_runs():
            m = store.open(rid).manifest()
            status = m.get("status", "?")
            runs.append({
                "id": rid,
                "status": status,
                "task": (m.get("task") or {}).get("text", ""),
                "verdict_status": status,
            })
        return {"runs": runs}

    try:
        run = store.open(run_id)
    except ValueError as exc:
        return {"error": str(exc)}
    m = run.manifest()
    if not m:
        return {"error": f"no run {run_id!r} under {store.root}"}

    verdict = run.get("verdict")
    verdict_info = None
    if verdict is not None:
        verdict_info = {"status": verdict.status, "reasons": list(verdict.reasons)}

    return {
        "id": run_id,
        "manifest": m,
        "verdict": verdict_info,
        "events": _read_run_events(run.dir),
        "artifacts": sorted((m.get("artifacts") or {}).keys()),
    }


def read_events(repo: str, cursor: int = 0) -> dict:
    """`bus.read_since` passthrough — the pull half of "the system talks back"."""
    events, new_cursor = read_since(Path(repo).resolve(), cursor)
    return {"events": events, "cursor": new_cursor}


# The layers this factory has adapters for (registry.py's own keys — the source of
# truth `swap_adapter` validates against too, so the two can never drift apart).
def _known_layers() -> list[str]:
    return sorted(registry._REGISTRY)


def read_config(repo: str) -> dict:
    """Current `sembl.stack.yaml` layers + available registry adapters per layer.

    NEVER returns env values, credentials, or profile secret material — only the
    `layers:` block (adapter names) and `registry.names()` (adapter names), so
    "swap X to Y" can be proposed accurately without leaking anything (O15)."""
    raw = guide.existing_layers_config(Path(repo))
    layers = raw.get("layers", {}) if isinstance(raw, dict) else {}
    return {
        "layers": layers,
        "available_adapters": {layer: registry.names(layer) for layer in _known_layers()},
    }


# --------------------------------------------------------------------------- #
# run loop (mutating — THE commitment path)
# --------------------------------------------------------------------------- #


def run_loop(repo: str, task_file: str) -> dict:
    """Invoke the existing loop entry (`cli.resolve_loop_inputs` + the same
    `loop.run` the CLI's `loop` command calls) — plan -> execute -> verify,
    retry-on-BLOCK, gated exactly as before. Never retries beyond the loop's own
    `max_attempts`, never applies, never merges: a BLOCK returns as a BLOCK.
    Engine `RuntimeError`s (the adapters' own "L<n>: ..." failures) come back as
    `{"error": ...}`, never a traceback. `task_file` may be relative to `repo`."""
    tf = Path(task_file)
    if not tf.is_absolute():
        tf = Path(repo) / tf
    if not tf.is_file():
        return {"error": f"task file not found: {tf}"}
    try:
        # Anchor config resolution to `repo`, never to this server process's cwd:
        # an MCP client can launch the server from anywhere (claude's own cwd, an
        # IDE), and cwd-relative resolution silently loads THAT directory's
        # sembl.stack.yaml instead of the target repo's (live-hit 2026-07-11:
        # a scratch repo's run picked up sembl-stack's own dev config).
        cfg, task, _meta = cli.resolve_loop_inputs(
            str(tf), config_path=str(Path(repo) / "sembl.stack.yaml"))
        result = _run_loop(cfg, task)
    except RuntimeError as exc:
        return {"error": str(exc)}
    return {
        "run_id": result.run_id,
        "verdict": {"status": result.verdict.status, "reasons": list(result.verdict.reasons)},
        "attempts": result.attempts,
    }


# --------------------------------------------------------------------------- #
# create/refine spec (O8 reuse, two-step propose -> confirm)
# --------------------------------------------------------------------------- #


def propose_task(repo: str, text: str, executor: str | None = None) -> dict:
    """`discuss.propose_task` verbatim — the O8 fixed-schema proposal for the
    human to review IN the conversation. Never a write, never a model call beyond
    the one bounded-LLM-into-fixed-schema call `discuss.py` already makes."""
    root = Path(repo).resolve()
    return discuss.propose_task(root, executor or "mock", text)


def confirm_task(repo: str, proposal: dict) -> dict:
    """`discuss.sanitize_proposal` + `discuss.confirm_task` — the human-confirmed
    (possibly edited) proposal materialized to task.yaml + bounds.json. No LLM
    work here. Returns `{"error": ...}` (never raises) when the proposal is too
    empty to write (no task text / no editable paths)."""
    root = Path(repo).resolve()
    sanitized = discuss.sanitize_proposal(root, proposal)
    try:
        task_path, bounds_path = discuss.confirm_task(root, sanitized)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"task_file": str(task_path), "bounds_file": str(bounds_path)}


# --------------------------------------------------------------------------- #
# resolve drift
# --------------------------------------------------------------------------- #


def _drift_state_path(repo: str) -> Path:
    return Path(repo) / drift.DEFAULT_STATE_PATH


def list_drift(repo: str) -> dict:
    """`drift.pending_drift_items` — keys + findings, read-only."""
    items = drift.pending_drift_items(state_path=_drift_state_path(repo))
    return {"pending": [{"key": key, "finding": finding} for key, finding in items]}


_DRIFT_ACTIONS = ("ack", "exception")


def resolve_drift(repo: str, key: str, action: str, reason: str | None = None) -> dict:
    """`action="ack"` -> `drift.acknowledge_drift([key])`; `action="exception"`
    (requires a non-empty `reason`) -> `drift.resolve_exception`. Unknown `action`
    or unknown `key` each return a clean `{"error": ...}`, never a traceback — the
    update-code path is NOT a tool here: fixing code goes through
    propose_task -> run_loop like any other change (one commitment path)."""
    if action not in _DRIFT_ACTIONS:
        return {"error": f"unknown action {action!r}", "valid_actions": list(_DRIFT_ACTIONS)}

    state_path = _drift_state_path(repo)
    pending = dict(drift.pending_drift_items(state_path=state_path))
    if key not in pending:
        return {"error": f"unknown drift key {key!r}"}

    if action == "exception":
        if not reason or not reason.strip():
            return {"error": "reason is required for action='exception'"}
        ok = drift.resolve_exception(key, reason, state_path=state_path)
        return {"key": key, "action": "exception", "resolved": ok, "reason": reason}

    n = drift.acknowledge_drift([key], state_path=state_path)
    return {"key": key, "action": "ack", "acknowledged": n}


# --------------------------------------------------------------------------- #
# swap adapter (mutating)
# --------------------------------------------------------------------------- #


def swap_adapter(repo: str, layer: str, adapter: str) -> dict:
    """Validate `layer` + `adapter` against `registry.py`'s actual keys (reject
    unknowns with the valid options in the error), then rewrite ONLY that key in
    `sembl.stack.yaml` — preserving the rest of the file, matching
    `guide.write_layers_config`'s merge-then-`yaml.safe_dump(sort_keys=False)`
    style rather than inventing a new YAML writer."""
    if layer not in registry._REGISTRY:
        return {"error": f"unknown layer {layer!r}", "valid_layers": _known_layers()}
    valid_adapters = registry.names(layer)
    if adapter not in valid_adapters:
        return {"error": f"unknown adapter {adapter!r} for layer {layer!r}",
                "valid_adapters": valid_adapters}

    root = Path(repo)
    data = guide.existing_layers_config(root)
    layers = dict(data.get("layers") or {})
    layers[layer] = adapter
    data["layers"] = layers
    config_path = root / "sembl.stack.yaml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return {"layer": layer, "adapter": adapter, "config_file": str(config_path)}


# --------------------------------------------------------------------------- #
# MCP wiring
# --------------------------------------------------------------------------- #

# The boundary lock (SPEC-O11 §3.1): EXACTLY these nine tools, nothing else — no
# shell tool, no file-write tool, no apply/merge/override tool. `tests/test_
# operator_mcp.py` asserts this tuple is exactly what `main()` registers.
TOOL_NAMES: tuple[str, ...] = (
    "read_state",
    "read_events",
    "read_config",
    "run_loop",
    "propose_task",
    "confirm_task",
    "list_drift",
    "resolve_drift",
    "swap_adapter",
)

_TOOL_FUNCS: dict[str, Any] = {
    "read_state": read_state,
    "read_events": read_events,
    "read_config": read_config,
    "run_loop": run_loop,
    "propose_task": propose_task,
    "confirm_task": confirm_task,
    "list_drift": list_drift,
    "resolve_drift": resolve_drift,
    "swap_adapter": swap_adapter,
}


def build_server() -> Any:
    """Create the FastMCP server with exactly `TOOL_NAMES` registered. Imports
    `mcp` lazily — this module itself must import cleanly without the `mcp`
    package installed."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise SystemExit(
            "install the mcp extra: pip install 'sembl-stack[mcp]'"
        ) from exc

    server = FastMCP("sembl-stack")
    for name in TOOL_NAMES:
        fn = _TOOL_FUNCS[name]
        server.tool(name=name, description=fn.__doc__)(fn)
    return server


def _detach_child_std_handles() -> None:
    """Windows: point the process-level std handles at NUL so engine
    subprocesses never inherit the MCP stdio pipes.

    Without this, any child spawned from inside a tool call (git, executors,
    the sembl CLI) inherits the server's stdin — the MCP protocol pipe — while
    the transport keeps a synchronous read pending on it. The child's CRT
    startup queries that handle (GetFileType) and blocks behind the pending
    read: child waits for the client's next message, client waits for the
    tool's reply. Deadlock, live-hit 2026-07-11 (run_loop froze forever on
    `git status --porcelain`). SetStdHandle changes only what CreateProcess
    hands to children; the transport reads fd 0 / writes fd 1 via the CRT and
    is unaffected. stdout is detached too so a non-capturing child can never
    corrupt the protocol stream; stderr stays inherited (it is the visible
    error channel)."""
    if sys.platform != "win32":
        return
    import ctypes
    import msvcrt

    # opened for the process lifetime, deliberately never closed
    ctypes.windll.kernel32.SetStdHandle(
        -10, msvcrt.get_osfhandle(os.open(os.devnull, os.O_RDONLY)))
    ctypes.windll.kernel32.SetStdHandle(
        -11, msvcrt.get_osfhandle(os.open(os.devnull, os.O_WRONLY)))


def main() -> None:
    """Entry point: run the sembl-stack operator MCP server over stdio.

    If `mcp` isn't installed, prints an actionable message to STDERR and exits
    nonzero — never a traceback (stdout stays clean for the stdio protocol)."""
    try:
        server = build_server()
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    _detach_child_std_handles()
    server.run()


if __name__ == "__main__":  # pragma: no cover
    main()
