"""Adapter registry — the swap mechanism.

`sembl.stack.yaml` names an adapter per layer; the registry resolves the name to a
class. Register a new implementation here (or via entry points later) and it becomes
swappable with a one-line config change.
"""
from __future__ import annotations

from .adapters.execute_mock import MockExecutor
from .adapters.execute_opencode import OpenCodeExecutor
from .adapters.sandbox_worktree import WorktreeSandbox
from .adapters.spec_sembl import SemblSpecAdapter
from .adapters.verify_sembl import SemblVerifyAdapter

# layer -> { adapter name -> factory(transport, mcp_server) }
_REGISTRY: dict[str, dict[str, object]] = {
    "spec": {
        "sembl": lambda t, s: SemblSpecAdapter(transport=t, mcp_server=s),
    },
    "execute": {
        "mock": lambda t, s: MockExecutor(),
        "opencode": lambda t, s: OpenCodeExecutor(),
    },
    "sandbox": {
        "worktree": lambda t, s: WorktreeSandbox(),
    },
    "verify": {
        "sembl": lambda t, s: SemblVerifyAdapter(transport=t, mcp_server=s),
    },
}


def build(layer: str, name: str, transport: str, mcp_server: list[str]):
    try:
        factory = _REGISTRY[layer][name]
    except KeyError:
        avail = ", ".join(_REGISTRY.get(layer, {})) or "(none)"
        raise SystemExit(
            f"Unknown {layer} adapter '{name}'. Available: {avail}")
    return factory(transport, mcp_server)


def names(layer: str) -> list[str]:
    return list(_REGISTRY.get(layer, {}))
