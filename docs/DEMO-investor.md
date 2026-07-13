# DEMO — the sembl cockpit (investor runbook)

Written 2026-07-13 by the overnight autonomous session. Everything in this
demo is real: real executor (Claude/Sonnet), real sandbox clones, real gate
verdicts, real rendered-DOM evidence. Nothing is mocked and nothing is
narrated by a model — every line on screen is engine data.

## Launch (one command)

```bash
cd C:\Users\totla\Desktop\projects\sembl-stack
.venv\Scripts\sembl-stack gui --repo C:\Users\totla\Desktop\projects\sembl-demo\feedback-board --browser
```

Opens the cockpit at http://127.0.0.1:8765 (add `--port` to change). The demo
repo is a standalone git copy of the flagship feedback board with the loop
configured: `execute: claude` (model `claude-sonnet-5`), `stage: web`,
`sandbox.prepare: npm ci`, `max_attempts: 2`, strict gate.

## The 5-minute narrative

1. **The claim** (30s): "Agents write code fine; nobody can *trust* what they
   did. sembl is process correctness: you declare a task and its bounds; a
   swappable executor builds in a disposable sandbox; a deterministic,
   model-free gate judges the diff against the declared contract; the live
   preview is recorded as evidence bound to the verdict."
2. **Recorded runs** (90s): click through the sidebar —
   - *"Add a search box…"* — one attempt, real diff, acceptance check green,
     **PASS**; the preview pane shows the sandbox's rendered DOM with the
     search box IN it, footer bound to the run id + diff SHA.
   - *"Add a CSV download button…"* (bounds narrowed to `src/components/`
     for this run) — the executor itself refused to cross the declared
     bounds and proposed widening them; the gate **BLOCK**ed the
     non-implementation. Read the BLOCK reason out loud: this is the system
     refusing to pretend.
3. **Live run** (2-3 min): click **New run**, type a small real task, e.g.
   *"Add per-status counts to the filter tabs"* or *"Highlight high-priority
   cards with a left border."* Confirm the task card (bounds prefilled from
   the repo). Watch: bounds → sandbox → executor → stage boots → the preview
   pane flips to the LIVE sandbox app → gate verdict lands in the
   conversation. The final attempt's live server STAYS up after the verdict
   (stage-hold) — click around the built feature in the preview pane.
   Cost per attempt ~$0.20-0.60, wall time ~2-4 min (npm ci dominates).
4. **The close** (30s): "Same loop, same gate, any executor — claude today,
   codex/aider/opencode by editing one line of config. The gate has no seat
   for a model. BLOCK is never mergeable. Every verdict replays with visual
   proof."

## If something goes sideways

- **Executor hiccup / no diff:** the gate BLOCKs honestly — that IS the
  product story; read the reason and move on to the recorded PASS runs.
- **npm/stage boot slow:** talk over it — the per-stage quiet lines keep
  the screen alive; or fall back to recorded runs (step 2 carries the demo).
- **Total fallback:** headless in a terminal:
  `sembl-stack loop task.yaml` from the demo repo, then
  `sembl-stack runs <id> --repo <demo repo>`.
- Do NOT demo deploy (L6+): not configured in the demo repo, by design.

## Honest limits (do not claim past these)

- The conversation region runs typed engine actions only (task → confirm →
  run); the free-chat operator agent (O11) exists headless
  (`sembl-stack operator`) but is not wired into this surface yet.
- Historical snapshots render the captured DOM without the app's CSS bundle
  (evidence, not a screenshot); the LIVE stage during and after a run is the
  fully styled real app. The held server (and its sandbox) is torn down when
  the next run starts or the cockpit process exits.
- One run at a time per cockpit process (personal-cockpit contract).
