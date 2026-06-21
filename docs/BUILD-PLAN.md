# Build Plan — to the raised launch bar (S7)

> Created 2026-06-20 (PM). This is the **executable plan** behind the owner call in
> `ROADMAP-TO-PRODUCT.md` §1b (launch bar raised) and the architecture in `PLATFORM-MAP.md`.
> It is written to be picked up cold (e.g. by codex). **Verify every module path against the
> live repo before editing** — the docs assert some paths that may have moved.
>
> Guardrails that bind this whole plan (do not violate):
> - **Process correctness, never "better code"** (PLATFORM-MAP §8, O3 trap-guard). Any
>   analysis that compares code *quality* WITH vs WITHOUT as the headline is off-spec.
> - **Evidence-first / anti-trap:** the O3 number + a depth-1 end-to-end spine come BEFORE
>   any fan-out to breadth. Breadth is the back half.
> - **Own only:** artifact contract + stage Protocol, the Sembl gate, hub glue +
>   layer-replacement protocol. Everything else is CONSUME (OSS behind an adapter) or
>   INTEGRATE (external via MCP/API/CLI).

## Target (the raised bar, S7)
Launch = the **whole accountable chain, end-to-end, through deploy**, provably safer than a
prompt chain / `/goal`, across ~50 adapters (≈2–4 per layer). Decided inputs:
- **Flagship app (S11):** a **feedback board** (auth + DB writes/reads + list views) on
  **Vercel + Supabase** — small enough to run live, rich enough that drift is plausible.
- **O5 shape (S10):** **local-creds-first** — inherit local env/secrets for the single-user
  flagship; the full scoped-secret/permission/sandbox model is a separate pre-public-launch
  workstream.

## Already done (do not rebuild — see ROADMAP PROGRESS LOG)
L1 context into the loop · L2 Sembl bounds · L3 executors (Claude Code, Aider/NIM,
MiniMax-M3/OpenCode — 3 live, hot-swappable) · L4 git-worktree sandbox · L5 Sembl gate
(0.1.20) · L6 LangGraph orchestration + retry-on-BLOCK · C1 no-op/empty-diff BLOCK · run
store `.sembl/runs/<id>/`.

---

## Workstream 1 — Evidence harness (B1–B3) — BUILD FIRST
**Why first:** it is the proof *and* the public "beats prompt-chains/`/goal`" demo; the
WITHOUT arm *is* the prompt chain. No new surface area until this number exists.

- **B1 — metric:** DONE. `docs/eval-metric-O3.md` is the computable spec. Do not redefine it.
- **B2 — corpus** (`eval/build_corpus.py` → `eval/corpus/<NN-name>/case.json`): 10–20 task
  cases, each = repo snapshot + `task.yaml` + `bounds.json` + captured `diff` + `report` +
  a closed-set `label` (`clean` / `out_of_scope` / `forbidden` / `fabricated` / `unevidenced`
  / `over_churn`) + the `expect`ed verdict. Mix greenfield-create, in-repo-feature, refactor,
  forbidden-area-temptation, fabrication-prone. **[S6 still OPEN:** synthetic vs captured real
  PRs — default to a mix; captured real diffs are allowed, no live agent per cell required.]
- **B3 — harness** (`eval/harness.py`): runs each case twice through the real gate
  (`sembl.mcp_server.verify_change`, in-process) — WITHOUT (merge as-is) vs WITH (gate) — and
  prints ONE WITH/WITHOUT table: caught-rate, bad-merge-rate (headline delta), **false-alarm
  rate (always beside it)**, iterations-to-green (live/scripted-correction cases only), cost.
  Enforce §4–§5: every `clean` case must not block; any verdict drifting from a case's
  `expect` fails the run (regression guard).
- **Acceptance:** one command emits the table; bad-merge-rate drops materially WITH while
  false-alarm stays low; the regression guard is green. This table is the launch artifact.

## Workstream 2 — Depth-1 through-deploy spine (the flagship)
**Goal:** the feedback board flows the *entire* chain end-to-end, one tool per layer, real
deploy. This is "complete execution."

Chain to wire (depth-1):
`spec → SpecGraph → bounds → execute → CodeGraph → reconcile(S9) → Sembl gate → quality
review → merge → deploy(Vercel+Supabase) → post-deploy gate(L8)`

New pieces to build:
1. **`SpecGraph` artifact + builder** — graph of the feedback-board spec (entities, routes,
   data rules). JSON-serializable, persisted per run like every artifact.
2. **L5.5 reconciliation agent (S9)** — per-PR, **advisory, human-reconciled, NOT a gate.**
   Consumes `SpecGraph` + `CodeGraph` (code graph via codebase-memory-mcp; **per-PR indexing
   suffices — do NOT promote CBM to a load-bearing memory plane**, see `memory-plane-
   hypothesis.md`). Emits a `ReconciliationReport` of divergence; **a haiku-class model is the
   target** given clean graphs. User decides which graph to update; output is informational.
3. **L5.5 quality-review integration** — invoke CodeRabbit/codex, ingest the verdict as a
   signal. INTEGRATE, not own. (Quality only ever as gate-caught regressions, never "better
   code.")
4. **Merge stage** — gated merge to main (PASS/WARN ⇒ merge; BLOCK ⇒ hold).
5. **L7 deploy** — own the stage, **delegate the mechanism** to Vercel+Supabase
   (local-creds-first per S10). `Verdict(PASS) → Delivery`.
6. **L8 post-deploy gate** — deterministic health/smoke + error-rate threshold → PASS or a
   **rollback trigger**. OWN gate + consume signals. This is what makes "reaches production
   correctly" true (PLATFORM-MAP O2).
- **Acceptance:** the feedback board goes spec→live-on-Vercel with every artifact persisted in
  `.sembl/runs/`, the gate honest, the reconciliation report produced, post-deploy gate green;
  and the WITH/WITHOUT comparison (Workstream 1) is run *through deploy* on this app — the
  prompt-chain arm ships a bad change (drift / out-of-scope / fabricated), the Sembl arm
  catches or post-deploy-rolls-back. That asymmetry is the demo.

## Workstream 3 — O5 security model (local-creds-first)
**Goal:** make Workstream 2's deploy real and safe at single-user scope. Inherit local
env/secrets; never log/persist secrets into the run store; scope deploy creds to the deploy
stage only. **Out of scope here:** the full scoped-secret/permission/sandbox model for
hosted/team use — that is its own workstream and a hard prerequisite for public/hosted launch
(PLATFORM-MAP O5). Flag clearly in the run store where a secret was used.
- **Acceptance:** the flagship deploys with real creds; no secret leaks into artifacts/traces;
  a written note on exactly what the full model must add before hosted use.

## Workstream 4 — Breadth to ~50 adapters (BACK HALF — only after WS1+WS2 prove out)
Fan out to ≈2–4 adapters per layer behind the existing Protocols
(`sembl_stack/adapters/base.py`): executors, context/graph, sandbox (worktree✓ +Docker/E2B),
deploy (Vercel✓ +Fly/Cloudflare/GH Actions), review, plus Plane-B integration targets
(GitHub, Vercel, Supabase, Sentry first-class). **Each adapter must meet the stage contract
(headless run → typed artifact) — curated, not exhaustive.** The 100-tool community catalog
stays Phase-3, demand-pulled.
- **Acceptance:** ~50 adapters across layers, each with a one-line config swap leaving the
  gate's verdict honest; at least two hot-swappable options proven per critical layer.

## Woven through WS2–WS4 — C4 + private beta (S4)
Build the **TUI run dashboard** (CI-run-page UX, O6) + named presets (`just-gate`,
`gate+sandbox`, `full-loop`) so a stranger can run the through-deploy spine. Recruit 3–5
design partners the moment that's true. Beta is NOT launch.

---

## Sequence (critical path) & the one big risk
```
WS1 (evidence number)  ──┐
WS3 (local-creds O5) ────┼──► WS2 (depth-1 through-deploy flagship + the WITH/WITHOUT demo)
                         │         └─ proven ─► WS4 (breadth ~50) + C4/beta ─► LAUNCH
```
- **Biggest risk = L7/L8 + O5.** Deploy through a third party with real creds is where the
  "complete execution" claim is won or lost; keep it local-creds-first and single-user until
  the number exists.
- **Trap watch:** if work drifts into wiring many adapters before WS1's table and WS2's
  flagship are green, stop — that is the capability trap the platform warns against.

## Open items a future session must still call
- **S6** — corpus source (synthetic vs captured real PRs). Default: mix.
- Full O5 model shape (hosted/team) — deferred, but name it before public launch.
- Where the SpecGraph builder lives and its schema (new) — design in WS2.
