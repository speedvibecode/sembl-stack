"""Onboarding presets (C4) — a one-command path to a working config.

Three presets cover the adoption ramp, lightest first:

  * just-gate     — the wedge: gate a diff/PR with NO model and NO infra (CLI transport,
                    so it shells the installed `sembl` — no uvx/MCP required).
  * gate+sandbox  — see the whole loop with a deterministic mock executor (no keys): plan
                    -> sandbox -> execute -> gate -> retry-on-BLOCK.
  * full-loop     — a real agent (Claude Code on the operator's OAuth session) writes, the
                    sandbox contains, Sembl gates. Swap `execute` for aider/opencode.

Each preset is stored as ANNOTATED YAML (not a dumped dict) so the file a stranger lands on
explains itself. `render()` returns that text; `config_dict()` parses it back for validation.
"""
from __future__ import annotations

import yaml

_JUST_GATE = """\
# sembl-stack config — preset: just-gate
# The adoption wedge: gate any diff/PR with zero model and zero infra.
#   sembl-stack verify --diff change.patch --bounds bounds.json
layers:
  spec: sembl          # L2 bounds engine (ours)
  execute: mock        # not used by `verify`; kept so `loop` still boots if you try it
  sandbox: worktree    # L4 disposable sandbox
  verify: sembl        # L5 gate (ours)
transport:
  spec: cli            # shell the installed `sembl` — no uvx/MCP needed
  verify: cli
loop:
  max_attempts: 1
  strict: true         # out-of-scope edits BLOCK
tracing:
  langfuse: false
"""

_GATE_SANDBOX = """\
# sembl-stack config — preset: gate+sandbox
# See the full loop with a deterministic mock executor (no API keys):
#   plan -> sandbox -> execute -> gate -> retry-on-BLOCK
#   sembl-stack loop task.yaml
layers:
  spec: sembl
  execute: mock        # deterministic: misbehaves once (BLOCK), then complies (PASS)
  sandbox: clone       # disposable local git clone — the source repo is never touched
  verify: sembl
transport:
  spec: cli
  verify: cli
loop:
  max_attempts: 3
  strict: true
tracing:
  langfuse: false
"""

_FULL_LOOP = """\
# sembl-stack config — preset: full-loop
# A real agent writes, the sandbox contains, Sembl gates.
#   requires `claude` on PATH (Claude Code, the operator's own login — no token handled).
#   swap execute: aider | opencode to drive a different agent.
#   sembl-stack loop task.yaml
layers:
  spec: sembl
  execute: claude
  sandbox: clone
  verify: sembl
transport:
  spec: cli
  verify: cli
options:
  execute:
    model:             # blank = the operator's default model
    timeout: 900       # seconds before the executor is treated as a failed attempt
loop:
  max_attempts: 3
  strict: true
tracing:
  langfuse: false
"""

PRESETS: dict[str, str] = {
    "just-gate": _JUST_GATE,
    "gate+sandbox": _GATE_SANDBOX,
    "full-loop": _FULL_LOOP,
}

DEFAULT_PRESET = "gate+sandbox"

_STARTER_TASK = """\
# A task for the short loop. Paths resolve relative to this file.
text: "Add a VALUE constant to the app module, in scope, without touching infra."
repo: "."
# spec_path: "./specs/001-feature"   # optional: a Spec Kit feature dir / tasks.md
"""


def names() -> list[str]:
    return list(PRESETS)


def render(preset: str) -> str:
    """The annotated YAML text for a preset (raises KeyError on an unknown name)."""
    return PRESETS[preset]


def config_dict(preset: str) -> dict:
    """The preset parsed to a dict — used to validate it loads and wires."""
    return yaml.safe_load(PRESETS[preset])


def starter_task() -> str:
    return _STARTER_TASK
