# sembl-stack

**An open, swappable spec-driven coding factory.** Spec Kit plans, an agent writes,
a sandbox contains, **Sembl gates** — orchestrated by LangGraph, traced by Langfuse.
Every layer is an interface, not a hard dependency: swap any implementation without
touching the rest.

We own exactly three things — the **bounds/spec schema (L2)**, the **gate (L5 = Sembl)**,
and the **glue + layer-replacement protocol**. Everything else is an adapter behind an
interface (the *no-parasite rule* at platform scale).

---

## Two axes (don't conflate them)

1. **Pipeline layers** — *how work flows* (this repo). L0–L6 below.
2. **Domain integrations** — *what gets built & shipped* (GitHub, Vercel, Supabase, …).
   These are targets the pipeline deploys into, wired as MCP servers / CLIs. See
   `docs/integrations.md` (roadmap).

## The pipeline (L0–L6)

| Layer | Job | v0 adapter | Swap-in candidates | Own? |
|-------|-----|------------|--------------------|------|
| **L0 Protocol** | every layer speaks MCP | `mcp` stdio transport | A2A | **own contract** |
| **L1 Repo intel** | understand before editing | *(skipped in short loop)* | Graphify, code-review-graph, GitNexus | consume |
| **L2 Spec** | intent → governed bounds | `sembl` (bounds engine) | Kiro | **own** |
| **L3 Execute** | write the diff | `mock`, `opencode` | Aider, OpenHands, Claude Code/Codex | consume |
| **L4 Sandbox** | contain the change | `worktree` | E2B, Daytona | consume |
| **L5 Verify** | gate the diff | `sembl` (verify_change) | Semgrep, SonarQube + Sembl | **own** |
| **L6 Orchestrate+trace** | loop, retry, observe | LangGraph + Langfuse | CrewAI, Temporal, MLflow | consume |

## The short loop (v0)

```
task + spec
  → L2  bounds_from_spec        (sembl, over MCP)
  → L4  open sandbox            (git worktree)
  → L3  execute → diff+report   (mock / opencode)
  → L5  verify_change → verdict (sembl, over MCP)
  → BLOCK & attempts left? feed reasons back to L3 and retry
  → PASS/WARN: accept
```

LangGraph drives the state machine (retry-on-BLOCK); Langfuse traces every node.
Both are optional — a built-in fallback runner and no-op tracer keep the loop bootable
with zero extra installs.

## Run it

```bash
pip install -e .                 # + `sembl` on PATH (the gate)
sembl-stack run examples/tasks/login-redirect/task.yaml
```

## Swap a layer

Edit `sembl.stack.yaml` — one line per layer:

```yaml
layers:
  execute: opencode   # was: mock
```

No code change. That's the whole bet: the orchestration **contract** is the product.

## Layer-replacement protocol (own)

`signal → shadow → promote`: detect a layer falling behind, run a challenger in shadow
beside the incumbent, compare, then swap the interface and record the version. See
`docs/replacement.md` (roadmap).
