"""Adapter registry — the swap mechanism.

`sembl.stack.yaml` names an adapter per layer; the registry resolves the name to a
class. Register a new implementation here (or via entry points later) and it becomes
swappable with a one-line config change.
"""
from __future__ import annotations

from .adapters.execute_aider import AiderExecutor
from .adapters.execute_claude import ClaudeCodeExecutor
from .adapters.execute_mock import MockExecutor
from .adapters.execute_opencode import OpenCodeExecutor
from .adapters.deploy_vercel import VercelDeployAdapter
from .adapters.merge_git import GitMergeAdapter
from .adapters.postdeploy_http import HttpPostDeployGate
from .adapters.sandbox_worktree import WorktreeSandbox
from .adapters.spec_sembl import SemblSpecAdapter
from .adapters.verify_sembl import SemblVerifyAdapter
from .adapters.codegraph_cbm import CbmCodeGraph
from .contextgraph import SymgraphGraph

# layer -> { adapter name -> factory(transport, mcp_server, opts) }
# opts is the per-layer `options:` block from sembl.stack.yaml (adapter-specific knobs
# like which model to drive) — keeps tuning a config change, not a code change.
_REGISTRY: dict[str, dict[str, object]] = {
    "spec": {
        "sembl": lambda t, s, o: SemblSpecAdapter(transport=t, mcp_server=s),
    },
    "execute": {
        "mock": lambda t, s, o: MockExecutor(),
        "opencode": lambda t, s, o: OpenCodeExecutor(
            model=o.get("model"), timeout=o.get("timeout", 900)),
        "claude": lambda t, s, o: ClaudeCodeExecutor(
            model=o.get("model"), timeout=o.get("timeout", 900)),
        "aider": lambda t, s, o: AiderExecutor(
            model=o.get("model"), timeout=o.get("timeout", 900)),
    },
    "sandbox": {
        "worktree": lambda t, s, o: WorktreeSandbox(),   # back-compat name
        "clone": lambda t, s, o: WorktreeSandbox(),       # disposable local clone
    },
    "verify": {
        "sembl": lambda t, s, o: SemblVerifyAdapter(transport=t, mcp_server=s),
    },
    "context": {                                          # L1 semantic graph (optional)
        "symgraph": lambda t, s, o: SymgraphGraph(timeout=o.get("timeout", 300)),
        "none": lambda t, s, o: None,
    },
    "codegraph": {                                        # L5.5 code graph for reconcile
        "cbm": lambda t, s, o: CbmCodeGraph(
            binary=o.get("binary", "codebase-memory-mcp"),
            timeout=o.get("timeout", 600), limit=o.get("limit", 5000)),
        "none": lambda t, s, o: None,
    },
    "merge": {
        "git": lambda t, s, o: GitMergeAdapter(timeout=o.get("timeout", 300)),
    },
    "deploy": {
        "vercel": lambda t, s, o: VercelDeployAdapter(timeout=o.get("timeout", 1800)),
    },
    "postdeploy": {
        "http": lambda t, s, o: HttpPostDeployGate(),
    },
}


def build(layer: str, name: str, transport: str, mcp_server: list[str],
          opts: dict | None = None):
    try:
        factory = _REGISTRY[layer][name]
    except KeyError:
        avail = ", ".join(_REGISTRY.get(layer, {})) or "(none)"
        raise SystemExit(
            f"Unknown {layer} adapter '{name}'. Available: {avail}")
    return factory(transport, mcp_server, opts or {})


def names(layer: str) -> list[str]:
    return list(_REGISTRY.get(layer, {}))
