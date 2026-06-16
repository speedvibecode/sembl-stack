"""Load sembl.stack.yaml and resolve it into wired-up adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import registry

DEFAULTS = {
    "layers": {"spec": "sembl", "execute": "mock",
               "sandbox": "worktree", "verify": "sembl", "context": "none"},
    "transport": {"spec": "mcp", "verify": "mcp",
                  "mcp_server": ["uvx", "--from", "sembl[mcp]", "sembl-mcp"]},
    "loop": {"max_attempts": 3, "strict": True},
    "tracing": {"langfuse": False},
}


@dataclass
class StackConfig:
    spec: object
    execute: object
    sandbox: object
    verify: object
    context: object = None
    max_attempts: int = 3
    strict: bool = True
    langfuse: bool = False
    raw: dict = field(default_factory=dict)


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load(path: str | None) -> StackConfig:
    cfg = dict(DEFAULTS)
    if path and Path(path).is_file():
        cfg = _merge(DEFAULTS, yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    layers = cfg["layers"]
    tr = cfg["transport"]
    server = tr.get("mcp_server", DEFAULTS["transport"]["mcp_server"])
    opts = cfg.get("options", {})   # per-layer adapter knobs (e.g. execute.model)

    return StackConfig(
        spec=registry.build("spec", layers["spec"], tr.get("spec", "mcp"), server,
                            opts.get("spec")),
        execute=registry.build("execute", layers["execute"], "cli", server,
                               opts.get("execute")),
        sandbox=registry.build("sandbox", layers["sandbox"], "cli", server,
                               opts.get("sandbox")),
        verify=registry.build("verify", layers["verify"], tr.get("verify", "mcp"), server,
                              opts.get("verify")),
        context=registry.build("context", layers.get("context", "none"), "cli", server,
                               opts.get("context")),
        max_attempts=cfg["loop"]["max_attempts"],
        strict=cfg["loop"]["strict"],
        langfuse=cfg["tracing"]["langfuse"],
        raw=cfg,
    )
