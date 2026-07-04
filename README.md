# sembl-stack

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Built around Sembl](https://img.shields.io/badge/gate-Sembl-ccff00.svg)](https://github.com/speedvibecode/sembl)

**A swappable, spec-driven software factory.** A task becomes declared bounds, an
agent writes the change inside a disposable sandbox, the **[Sembl](https://github.com/speedvibecode/sembl)
gate** judges the real diff against those bounds, a PASS merges and deploys, and a
post-deploy gate confirms it's healthy — or rolls it back. **Every stage is an
interchangeable adapter behind one typed artifact contract, and every run is
recorded.**

We sell **process correctness** — the change did what the spec declared, stayed in
bounds, is honestly evidenced, and reached production accountably — **never "the
model writes better code."** The stack takes no side in the agent wars: swap the
executor, the sandbox, or the deploy target with one line of config and the rest of
the pipeline doesn't notice.

[Website](https://sembl-stack.vercel.app) · [The gate (Sembl)](https://sembl.vercel.app) · [Architecture & plan](docs/PROCESS-ACTION-PLAN.md)

```text
task ─▶ bounds ─▶ execute ─▶ sandbox ─▶ SEMBL GATE ─▶ merge ─▶ deploy ─▶ verify-in-prod
        (L2)       (L3)        (L4)       (L5)         (L6.5)    (L7)       (L8)
                                          every arrow is a typed artifact on disk
```

## Quickstart

```bash
pip install sembl-stack sembl     # the stack + the gate it runs at its core
sembl-stack init                  # scaffold sembl.stack.yaml + task.yaml from a preset
sembl-stack doctor                # config-aware preflight
sembl-stack loop task.yaml        # plan → execute → gate → retry-on-BLOCK
sembl-stack runs [<id>]           # list / inspect runs
sembl-stack apply <id>            # apply the accepted patch (a BLOCK is never applied)
```

**Presets** (`sembl-stack init --preset …`):

| Preset | What runs | Needs |
|--------|-----------|-------|
| `just-gate` | gate any diff, nothing else | only `sembl` |
| `gate+sandbox` | the whole loop with a mock executor | no API keys |
| `full-loop` | real agent + sandbox + gate | an executor key |

Swap any layer in `sembl.stack.yaml` — e.g. `execute: opencode`, `execute: aider` —
with no code change.

## The stage map (L0–L8)

Each stage consumes and produces typed artifacts; that hand-off *is* the whole
interface, which is what makes every stage swappable.

| Stage | Does | Artifact flow | Who owns it |
|-------|------|---------------|-------------|
| **L0** Protocol & hub | one wire between stages | — | **we own** (the contract) |
| **L1** Repo intel | code-graph context | `Task → Context` | adapter |
| **L2** Spec → bounds | scope the change | `Task → Bounds` | **we own** (`sembl`) |
| **L3** Execute | write the change | `Task + Bounds → Change` | adapter (claude / aider / opencode) |
| **L4** Sandbox | contain a bad diff | `Change → Change` | adapter (disposable clone) |
| **L5** Verify | gate the diff | `Change + Bounds → Verdict` | **the gate** (`sembl`) |
| **L5.5** Review (advisory) | code-quality signal | `diff → findings` | adapter (`llm` — BYO agent-CLI reviewer; CodeRabbit optional) |
| **L6** Orchestrate | loop, retry, trace | wiring + `* → Trace` | **we own** (LangGraph) |
| **L6.5** Merge | gated merge | `Verdict(PASS) → MergeRecord` | **we own** |
| **L7** Deploy | ship | `Verdict(PASS) → Delivery` | adapter |
| **L8** Verify-in-prod | gate production | `Delivery → Verdict` | **the gate** (health + rollback) |

We own exactly three things: the **artifact contract + stage Protocol**, the **gate
(L5 + the post-deploy L8)**, and the **glue + layer-replacement protocol**.
Everything else is deliberately a best-in-class tool behind an interface.

## The accountable spine

A verdict is bound to the change it judged — most agent pipelines stop at "the check
passed"; this one guarantees a verdict can only ship the exact change it was issued
for:

- **Verdicts carry their subject.** Every verdict is stamped with the SHA-256 and
  file set of the diff it judged. `apply` recomputes the patch hash and refuses a
  verdict issued for a different patch; `merge` refuses if the merge would ship files
  the verdict never saw.
- **BLOCK means blocked.** A BLOCK verdict is never applied and never merged — the
  loop retries the executor instead. Overrides (`--skip-binding-check`) exist but are
  recorded permanently in the `MergeRecord`.
- **Production is gated too.** After deploy, the L8 gate checks the live delivery
  (health + payload, deterministically) and triggers a rollback when it fails.

Every run leaves a complete paper trail in `.sembl/runs/<id>/`:

```text
.sembl/runs/2ca41f/
├─ task.json          # what was asked
├─ bounds.json        # the declared contract
├─ change.json        # the actual diff
├─ verdict.json       # the gate's judgement + subject binding
├─ merge-record.json  # what shipped, and under whose PASS
└─ trace.json         # the timeline
```

## The guided TUI (optional)

`pip install "sembl-stack[tui]"` adds a Textual wizard. Run bare `sembl-stack` and
press `r`: the stage rail runs the real loop under your configured profile,
streaming per-stage status (pending/running/pass/fail) live and showing the final
verdict — byte-identical to a headless `sembl-stack loop`, because it drives the
same adapters.

## The full picture

**→ [`docs/PROCESS-ACTION-PLAN.md`](docs/PROCESS-ACTION-PLAN.md)** is the single
source of truth: architecture, the L0–L8 stage map with build status, the eval
metric, locked decisions, the guided-TUI vision, and the remaining-work plan.

Reference: [`process-self-improvement.md`](docs/process-self-improvement.md)
(north-star theory) · [`eval-metric-O3.md`](docs/eval-metric-O3.md) (the metric) ·
[`memory-plane-hypothesis.md`](docs/memory-plane-hypothesis.md).

## Local development

```bash
uv sync --extra all
uv pip install -e ../sembl          # or: pip install sembl
.venv/Scripts/python -m pytest -q   # run from the repo root (corpus paths are cwd-relative)
```

## Releasing

Publishing uses GitHub Actions + PyPI Trusted Publishing (OIDC); no tokens are
stored. `.github/workflows/release.yml` builds and publishes when you publish a
GitHub Release whose tag (`vX.Y.Z`) matches `pyproject.toml` and
`sembl_stack/__init__.py`.

---

Agents write the code. **sembl-stack makes the whole pipeline accountable.**
