"""`sembl-stack operator` — the headless proof surface for O11 (SPEC-O11 §5, WP-C).

A minimal, deliberately disposable REPL (~100 lines) that proves "the operator
is a free-flowing conversation whose only hands are the typed engine tools, and
the system talks back via the event bus" — headless, no chrome. The IDE
conversation panel (later roadmap item) replaces this wrapper; it connects to
the SAME MCP server unchanged.

Discipline (SPEC-O11 §5/§7 WP-C, encoded not just documented):
  - Never parses or reformats the model's stdout — `claude -p` inherits this
    process's stdio, so its output streams straight to the terminal untouched.
  - No colors, no history file, no UI polish.
  - No per-user state beyond the in-memory bus cursor (kept in the caller's
    stack frame across turns, never written to disk).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .bus import read_since

_CLAUDE_MISSING_MESSAGE = """\
claude CLI not found on PATH.

Install it (https://docs.claude.com/en/docs/claude-code) and re-run
`sembl-stack operator`, or connect any other MCP client to the same
engine tool surface with:

  sembl-stack operator --print-mcp-config
"""


def build_mcp_config() -> dict:
    """The MCP config for the `sembl-stack` server: `sys.executable -m
    sembl_stack.operator_mcp` over stdio. NEVER the `sembl-stack-mcp` console
    script — PATH independence is the point (the script only exists after
    `pip install -e .`; this venv's interpreter always exists)."""
    return {
        "mcpServers": {
            "sembl-stack": {
                "command": sys.executable,
                "args": ["-m", "sembl_stack.operator_mcp"],
            }
        }
    }


def write_mcp_config_file(config: dict) -> Path:
    """Write `config` to a temp json file for the session; returns its path."""
    fd, name = tempfile.mkstemp(prefix="sembl-stack-operator-mcp-", suffix=".json")
    path = Path(name)
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return path


def format_turn(human_text: str, events: list[dict]) -> str:
    """Prefix `human_text` with a bracketed block of new factory events, or
    return it unmodified when there are none — the unprompted "system talks
    back" half of the conversation (SPEC-O11 §5)."""
    if not events:
        return human_text
    lines = ["[factory events since last turn]"]
    lines.extend(f"- {e.get('summary', '')}" for e in events)
    lines.append("")
    lines.append(human_text)
    return "\n".join(lines)


def build_turn(root: Path, cursor: int, human_text: str) -> tuple[str, int]:
    """`bus.read_since(root, cursor)` + `format_turn` in one call; returns the
    turn text to send and the advanced cursor to keep for the next turn."""
    events, new_cursor = read_since(root, cursor)
    return format_turn(human_text, events), new_cursor


def resolve_claude() -> list[str]:
    """The argv prefix that actually launches the claude CLI.

    On Windows, `claude` resolves to a `.cmd` shim — `subprocess.run(["claude",
    ...])` without a shell raises `FileNotFoundError` because CreateProcess
    can't launch a batch file directly (the same lesson `deploy_vercel.py`'s
    `_resolve_vercel` already encodes). Raises `FileNotFoundError` when
    `claude` isn't on PATH at all, so callers have one failure mode to catch.
    """
    exe = shutil.which("claude")
    if not exe:
        raise FileNotFoundError("claude CLI not found on PATH")
    low = exe.lower()
    if low.endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    if low.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", exe]
    return [exe]


def run_repl(repo: str) -> int:
    """The REPL: read a human line from stdin, prefix it with any new bus
    events, send it to `claude -p` with session continuation, and stream its
    stdout straight through (no parsing, no polish). Exits cleanly on
    EOF/Ctrl-D/Ctrl-C or the input `exit`/`quit`. Returns the process exit
    code (0 on a clean exit; nonzero, never a traceback, when `claude` isn't
    on PATH)."""
    root = Path(repo).resolve()
    try:
        claude_prefix = resolve_claude()
    except FileNotFoundError:
        print(_CLAUDE_MISSING_MESSAGE, file=sys.stderr)
        return 1

    config_path = write_mcp_config_file(build_mcp_config())
    cursor = 0
    turn = 0
    while True:
        try:
            human_text = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        human_text = human_text.strip()
        if human_text in ("exit", "quit"):
            break
        if not human_text:
            continue

        turn_text, cursor = build_turn(root, cursor, human_text)
        cmd = claude_prefix + ["-p", turn_text, "--mcp-config", str(config_path)]
        if turn > 0:
            cmd.append("--continue")
        turn += 1
        subprocess.run(cmd, encoding="utf-8", errors="replace")
    return 0
