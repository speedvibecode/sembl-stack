"""Load sembl.stack.yaml and resolve it into wired-up adapters."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import registry
from .artifacts import Acceptance

DEFAULTS = {
    "layers": {"spec": "sembl", "execute": "mock",
               "sandbox": "worktree", "verify": "sembl", "context": "none",
               "codegraph": "cbm", "review": "mock",
               "merge": "git", "deploy": "vercel", "postdeploy": "http",
               "acceptance": "command", "stage": "none"},
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
    codegraph: object = None
    review: object = None
    merge: object = None
    deploy: object = None
    postdeploy: object = None
    acceptance: object = None
    stage: object = None
    max_attempts: int = 3
    strict: bool = True
    langfuse: bool = False
    raw: dict = field(default_factory=dict)


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load(path: str | None, overrides: dict | None = None) -> StackConfig:
    """Resolve DEFAULTS < overrides < file. `overrides` is where the onboarding profile
    plugs in (profile.to_stack_overrides) — passed explicitly by the caller, never read
    from global state here, so resolution stays deterministic and testable. An explicit
    sembl.stack.yaml always wins over a profile."""
    cfg = _merge(DEFAULTS, overrides or {})
    if path and Path(path).is_file():
        cfg = _merge(cfg, yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

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
        codegraph=registry.build("codegraph", layers.get("codegraph", "cbm"), "cli", server,
                                 opts.get("codegraph")),
        review=registry.build("review", layers.get("review", "mock"), "cli", server,
                              opts.get("review")),
        merge=registry.build("merge", layers.get("merge", "git"), "cli", server,
                             opts.get("merge")),
        deploy=registry.build("deploy", layers.get("deploy", "vercel"), "cli", server,
                              opts.get("deploy")),
        postdeploy=registry.build("postdeploy", layers.get("postdeploy", "http"), "cli",
                                  server, opts.get("postdeploy")),
        acceptance=registry.build("acceptance", layers.get("acceptance", "command"), "cli",
                                  server, opts.get("acceptance")),
        stage=registry.build("stage", layers.get("stage", "none"), "cli",
                             server, opts.get("stage")),
        max_attempts=cfg["loop"]["max_attempts"],
        strict=cfg["loop"]["strict"],
        langfuse=cfg["tracing"]["langfuse"],
        raw=cfg,
    )


def load_acceptance(repo: str) -> Acceptance | None:
    """The declared `Acceptance` contract for `repo`, or `None` if none is declared.

    Loaded from `<repo>/acceptance.json`, else `<repo>/.sembl/acceptance.json` — the
    same "hand-written file beside the repo" fallback `SemblSpecAdapter.plan` uses for
    `bounds.json`. `None` (no file, or a well-formed file with zero checks) means the
    behavioral axis is a strict no-op for this run; it is never fabricated.

    A file that EXISTS but cannot be read as a contract (corrupt JSON, wrong shape)
    is NOT the same as no file: someone declared a behavioral surface and we cannot
    honor it. That returns a contract whose synthetic `invalid_ids` entry the gate
    will BLOCK on (declared, no result) — fail closed, never a silent skip."""
    for rel in ("acceptance.json", ".sembl/acceptance.json"):
        cand = Path(repo) / rel
        if not cand.is_file():
            continue
        try:
            payload = json.loads(cand.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            return Acceptance(sources=[str(cand)],
                              invalid_ids=[f"{rel} (unreadable: {exc})"])
        if not isinstance(payload, dict):
            return Acceptance(sources=[str(cand)],
                              invalid_ids=[f"{rel} (not a JSON object)"])
        acc = Acceptance(checks=payload.get("checks", []),
                         sources=payload.get("sources", [str(cand)]))
        if acc.checks or acc.invalid_ids:
            return acc
    return None
