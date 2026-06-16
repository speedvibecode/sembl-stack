# Recursive PROCESS self-improvement — the theory

> North star (PLATFORM-MAP §North Star). The claim: the *process* improves itself
> **because of the tools of the process** — not because any model gets smarter.

## The distinction that makes it sane

- **Model RSI (what we are NOT doing):** a model edits/retrains itself to become more
  capable. Powerful but *circular and unverifiable* — the thing being improved is also
  the judge. This is the same failure mode we already reject (a model grading a model).
- **Process RSI (ours):** the *orchestration* improves — which tool, in which wiring, for
  which work — by measuring outcomes and selecting among swappable components. The
  components don't get smarter; the **selection, routing, and composition** get better,
  and the system **absorbs newer/better tools** as they ship. Intelligence stays
  exogenous.

## Why it's even coherent: you need three things, and we have all three

1. **A measurable signal** — you cannot optimize without a metric. We have one: the
   deterministic artifacts (verdicts, iterations-to-green, cost, gate-caught regressions)
   recorded per run in `.sembl/runs/`. The O3 metric is the objective.
2. **A search space** — the swappable **catalog** (executors, sandboxes, wirings,
   bounds strategies). Each is a knob.
3. **An optimizer** — the **layer-replacement protocol** (`signal → shadow → promote`).

The gate (L5) is special: it is both a *component* of the process **and** the *fitness
function* that scores outcomes. That is literally how "the tools of the process improve
the process."

## The ladder (each rung is real and buildable; ambition rises)

- **L0 — Manual (today).** Human reads runs, swaps a tool in `sembl.stack.yaml`.
- **L1 — Measured selection.** Record outcome stats per tool/wiring/task-type; surface
  "executor X passes the gate in 1.3 attempts at $0.04; Y takes 2.1 at $0.11." Decision
  stays human. *(Pure analytics over the run store — trivial once we have a corpus.)*
- **L2 — Auto-routing.** A router picks the executor/wiring per task from history (a
  contextual bandit). The process tunes itself to the work. *(Standard ML, bounded.)*
- **L3 — Shadow & promote.** Run a challenger tool in shadow beside the incumbent on real
  tasks, compare on the metric, auto-promote the winner, record the swap. *(A/B testing
  for pipeline layers — the layer-replacement protocol, fully mechanical.)*
- **L4 — Self-authoring (the recursive peak).** The factory proposes changes to *its own*
  config/adapters (a new catalog entry, a tuned bounds strategy, a new wiring) — and
  those changes go through **its own gated loop** before landing. The factory builds the
  factory, vetted by its own gate. *(Bootstrapping. Real, but bounded — see limits.)*

L0–L3 are unambiguously possible — they are AutoML / bandits / A-B testing applied to a
tool pipeline, nothing exotic. L4 is where the recursion closes.

## Why ours is non-circular (and safer than model RSI)

The optimizer's *judge* is the **deterministic gate**, which is **separate from the thing
being optimized** (tool selection). A model never grades itself; a mechanical metric does.
That breaks the circularity that makes model RSI untrustworthy. **The determinism we
committed to for other reasons is exactly what makes process-RSI tractable and safe.**
The first product's "it's just a gate" property becomes the engine of the north star.

## The honest ceiling (do not oversell)

- **Bounded by the ecosystem.** The process can only *select and compose* existing tools;
  it cannot exceed the best available tool. It is curation + routing, not creation. Gains
  are real but diminishing — capped by the frontier, not unbounded.
- **Goodhart risk.** Optimizing "gate-pass rate" could select executors that *game the
  gate*. Guards: the O3 trap-guard (never optimize "better code"), held-out eval tasks
  the router can't see, and the no-harm quality baseline. The metric must stay honest or
  the loop optimizes the wrong thing.
- **Not magic.** No emergent superintelligence. What you get is a **self-tuning,
  self-curating delivery system** that quietly gets better at picking the right tools and
  absorbs new ones the day they ship. That is genuinely valuable *and* defensible —
  precisely because it's bounded and grounded.

## Verdict

Possible? **Yes — L0–L3 plainly, L4 in a bounded form.** Not as runaway model
self-improvement, but as a process that measurably improves its own *selection and
orchestration* using its own deterministic outputs. It is the natural payoff of the
locked architecture (artifacts as signal, catalog as search space, gate as fitness
function), and it is *more* achievable than model RSI because it is non-circular.
