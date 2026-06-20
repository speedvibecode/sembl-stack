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
| **L1 Repo intel** | understand before editing | *(opt-in: `bounds --expand`)* | symgraph, codegraph, code-review-graph | consume |
| **L2 Spec** | intent → governed bounds | `sembl` (bounds engine) | Kiro | **own** |
| **L3 Execute** | write the diff | `mock`, `opencode`, `claude`, `aider` | OpenHands, Codex | consume |
| **L4 Sandbox** | contain the change | `clone` (disposable; alias `worktree`) | E2B, Daytona | consume |
| **L5 Verify** | gate the diff | `sembl` (verify_change) | Semgrep, SonarQube + Sembl | **own** |
| **L6 Orchestrate+trace** | loop, retry, observe | LangGraph + Langfuse | CrewAI, Temporal, MLflow | consume |

## The short loop (v0)

```
task + spec
  → L2  bounds_from_spec        (sembl, over MCP)
  → L4  open sandbox            (disposable clone)
  → L3  execute → diff+report   (configured executor)
  → L5  verify_change → verdict (sembl, over MCP)
  → BLOCK & attempts left? feed reasons back to L3 and retry
  → PASS/WARN: accept
```

LangGraph drives the state machine (retry-on-BLOCK); Langfuse traces every node.
Both are optional — a built-in fallback runner and no-op tracer keep the loop bootable
with zero extra installs.

## Quickstart

```bash
pip install -e .                 # + the gate:  pip install sembl
sembl-stack init                 # scaffold sembl.stack.yaml + task.yaml from a preset
sembl-stack doctor               # preflight: is the environment ready for this config?
sembl-stack loop task.yaml       # run the loop (plan → execute → gate → retry-on-BLOCK)
sembl-stack runs                 # list runs (status, attempts, latency)
sembl-stack runs <id>            # inspect one: per-attempt verdicts, reasons, latency
sembl-stack apply <id>           # apply the accepted patch to the source repo
sembl-stack dash                 # live TUI dashboard  (pip install "sembl-stack[tui]")
```

`init` has three presets for the adoption ramp:

| preset | what it gives you | needs |
|---|---|---|
| `just-gate` | the wedge — gate any diff/PR (`verify --diff`) | just `sembl` |
| `gate+sandbox` | the whole loop with a deterministic mock executor | no API keys |
| `full-loop` | a real agent writes, the sandbox contains, Sembl gates | `claude` on PATH |

`doctor` is config-aware — it only requires the layers your config actually selects (it
won't ask for `claude` when `execute: mock`) and prints an actionable hint for anything
missing. Optional pieces (langgraph, MCP) degrade to warnings, not failures.

`loop` writes a complete run record under `.sembl/runs/<id>/`: the final `change.json`
patch, verdicts, reasons, attempts, and timings. `runs <id>` is the inspection page;
`apply <id>` validates the final patch with `git apply --check` and applies it to the
source repo. A final `WARN` requires `--allow-warn`; `BLOCK` is never applied.

```bash
sembl-stack init --preset full-loop   # or just-gate | gate+sandbox
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
