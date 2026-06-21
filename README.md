# sembl-stack

**An open, swappable spec-driven coding factory.** A spec is planned, an agent writes, a
sandbox contains, **Sembl gates**, it merges, deploys, and a post-deploy gate confirms or
rolls back — every layer an interchangeable adapter behind one typed contract. We sell
**process correctness** (the change did what the spec declared, stayed in bounds, is honestly
evidenced, reached production accountably), **never "the model writes better code."**

We own exactly three things: the **artifact contract + stage Protocol**, the **gate (Sembl,
L5 + post-deploy L8)**, and the **glue + layer-replacement protocol**. Everything else is an
adapter behind an interface.

## Quickstart

```bash
pip install -e .            # + the gate:  pip install sembl
sembl-stack init            # scaffold sembl.stack.yaml + task.yaml from a preset
sembl-stack doctor          # config-aware preflight
sembl-stack loop task.yaml  # plan → execute → gate → retry-on-BLOCK
sembl-stack runs [<id>]     # list / inspect runs
sembl-stack apply <id>      # apply the accepted patch (BLOCK never applied)
```

Presets: `just-gate` (gate any diff — needs only `sembl`) · `gate+sandbox` (whole loop, mock
executor, no keys) · `full-loop` (real agent + sandbox + gate). Swap any layer with one line
in `sembl.stack.yaml` (e.g. `execute: opencode`) — no code change.

## The full picture

**→ [`docs/PROCESS-ACTION-PLAN.md`](docs/PROCESS-ACTION-PLAN.md)** is the single source of
truth: architecture, the L0–L8 stage map + build status, the O3 metric, locked decisions, the
`sembl stack` guided-TUI vision, and the remaining-work action plan.

Reference: [`process-self-improvement.md`](docs/process-self-improvement.md) (north-star
theory) · [`eval-metric-O3.md`](docs/eval-metric-O3.md) (the metric) ·
[`memory-plane-hypothesis.md`](docs/memory-plane-hypothesis.md).
