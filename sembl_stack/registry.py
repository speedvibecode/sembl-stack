"""Adapter registry — the swap mechanism.

`sembl.stack.yaml` names an adapter per layer; the registry resolves the name to a
class. Register a new implementation here (or via entry points later) and it becomes
swappable with a one-line config change.
"""
from __future__ import annotations

from .adapters.acceptance_command import CommandAcceptanceRunner
from .adapters.acceptance_contract import ContractAcceptanceRunner
from .adapters.acceptance_web import WebAcceptanceRunner
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
from .adapters.review_mock import MockReviewAdapter
from .adapters.review_coderabbit import CodeRabbitReviewAdapter
from .adapters.review_llm import LLMReviewAdapter
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
    "review": {
        "mock": lambda t, s, o: MockReviewAdapter(),
        "coderabbit": lambda t, s, o: CodeRabbitReviewAdapter(
            binary=o.get("binary", "coderabbit"), timeout=o.get("timeout", 600)),
        "llm": lambda t, s, o: LLMReviewAdapter(          # BYO agent CLI (claude/opencode)
            binary=o.get("binary", "claude"), model=o.get("model"),
            timeout=o.get("timeout", 600)),
    },
    "merge": {
        "git": lambda t, s, o: GitMergeAdapter(timeout=o.get("timeout", 300)),
    },
    "deploy": {
        "vercel": lambda t, s, o: VercelDeployAdapter(timeout=o.get("timeout", 1800)),
    },
    "postdeploy": {
        "http": lambda t, s, o: HttpPostDeployGate(
            health_path=o.get("health_path", "/"), expect_json=o.get("expect_json")),
    },
    "acceptance": {                                       # L4.5 behavioral axis (O12)
        "command": lambda t, s, o: CommandAcceptanceRunner(
            default_timeout=o.get("default_timeout", 120)),
        "web": lambda t, s, o: WebAcceptanceRunner(
            default_timeout=o.get("default_timeout", 300)),
        "contract": lambda t, s, o: ContractAcceptanceRunner(
            default_timeout=o.get("default_timeout", 300)),
        "none": lambda t, s, o: None,                      # explicit no-op (disables the axis)
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
