# SPEC — Ideation + Chat Shell (the personal-supertool direction)

> Status: **[LOCKED direction, 2026-07-05]** — §1 (L0.5) and §2 (L1) built 2026-07-05; §3-8 (Track
> 5 items 3-8) not yet built. This doc is the detail; `PROCESS-ACTION-PLAN.md` §3/§5/§8/§9 (Track 5)
> carries the summary and is the source of truth for status. Priority explicitly set by the owner:
> **this is for personal use first, not product validation by other users** — build it because it
> makes sembl-stack usable end-to-end for real work, dogfood it on sembl-stack itself.

## 0. The one-paragraph goal

Go from a raw idea (or an existing repo) to a deployed, gated, accountable change — end to end,
inside one tool, with a UX as smooth as Claude Code — while keeping every guarantee sembl-stack
already earned (O1 headless-core/thin-surface, O3 process-correctness-not-quality, the
deterministic gate). The two things standing between today's sembl-stack and that: (1) no real
greenfield "idea → plan" stage exists (`scaffold.py`'s "new repo" path is a placeholder demo, not
real ideation), and (2) the current surface (`guide.py`, itself a replacement for the rejected
`wizard.py` Textual app) can't yet show the fused doc/code graph, drift, or a real chat-style
loop. Both gaps close with **one repeated pattern**: bounded LLM proposal into a fixed schema,
human confirms before anything is locked — never a free agent, never inside the gate.

## 1. L0.5 — Idea → Spec

**Trigger:** a `product.md` / `PRD.md` / `idea.md` in the target directory (or a pasted paragraph
pitch if none exists). The owner's own phrasing for the UX: *"I have this product.md, I want to
proceed"* — sembl-stack should recognize this file and offer it as the entry point instead of the
blank-task prompt.

**Why this can't be pure-deterministic, and why that's fine:** turning a messy pitch into a real
architecture plan requires judgment a fixed parser can't do. The owner's framing, verbatim: *"all
of this cannot be done with pure deterministic way but in a bounded environment this could yield
fantastic output."* "Bounded" is the load-bearing word — see the mechanism below.

**The mechanism (fixed slot schema, not free chat):**
1. LLM reads the doc and fills a **fixed set of slots** — it cannot invent new ones:
   - `stack_candidates` — up to 3, ranked, each with a one-line why. **Correction (built
     2026-07-05):** this is free text naming a real product tech stack (e.g. "Next.js +
     Supabase") — NOT `presets.py`'s preset menu, which is a different thing entirely
     (sembl-stack's own gate-operating-mode: `just-gate`/`gate+sandbox`/`full-loop`, unaffected by
     this feature). The bounding property is fixed slots + human-confirms-before-lock, not an enum
     — see `ideation.py`.
   - `open_questions` — only the slots it's genuinely unsure of (auth model? multi-tenant?
     realtime? persistence?), not a fixed interview script.
   - `data_model_sketch` — best-effort entities/relations.
   - `non_goals_guess` — what the pitch implies is explicitly out of scope.
2. Unresolved slots become the actual questions asked back to the owner — a thorough `product.md`
   might skip straight to "here's my read, confirm?"; a sparse one asks more. This directly answers
   the earlier design question ("one big batch vs. drip-fed") — it's neither fixed: **length is a
   function of how much the source doc actually resolves**, not a fixed script.
3. Stack choice defaults to the AI's top-ranked candidate but the owner can always type something
   else — nothing is silently locked to the AI's suggestion.
4. **Nothing is authoritative until the owner reviews/edits it.** Same non-silence rule as
   `update spec` in §5. Once confirmed, this becomes the **Spec (PRD) artifact** — the node the
   fused graph (§4) reconciles everything else against, and the reason "full spec/PRD first" was
   chosen over a thinner "just pick a stack" option: a real PRD is what makes reconcile meaningful
   (today it's honest but thin — "a one-line text spec yields 2 spec nodes," per the 2026-07-04
   live-proof review in `PROCESS-ACTION-PLAN.md` §9 Track 1 item 2).

**Precedent this reuses, not invents:** `guide.py`'s `ai_suggest_paths()` already does exactly this
shape of thing — asks a configured executor to scope editable/forbidden paths from free text, the
result is a suggestion the owner confirms, never applied silently. L0.5 is the same pattern run
once, earlier, over a bigger question.

## 2. L1 — Spec → real scaffold

**Status: DONE 2026-07-05.** Today, `scaffold.py`'s `scaffold_demo()` / `ensure_demo_repo()` only
ever produce a placeholder `app/__init__.py` + starter config files + a first commit — enough to
make the loop runnable, not a real project. L1 derives the **actual** starter repo structure,
dependencies, and stack config from the confirmed Spec artifact from §1, instead of the demo
placeholder. This is the piece that answers the owner's "did sembl ever have an initial plan mode
for greenfield ideas like banter" question: no — this is that mode, built for real instead of
assumed to already exist.

**How it's built — no new mechanism, no fourth LLM touch point:** `ideation.py`'s
`spec_to_task_text(spec)` is pure string composition (stack + why + pitch + data model + non-goals
+ resolved questions -> one task description), not an LLM call. `guide.py`'s `_ideation_step` now
takes a `fresh_scaffold` flag (threaded from `launch()`, true only when this run's `_repo_step` just
called `scaffold_demo()` on a non-git dir). When a spec is confirmed on a fresh scaffold, it
overwrites the placeholder `task.yaml` with the derived text and resets `bounds.json`'s demo
`["app/"]` bound back to unscoped (`[]`) — the next `_task_step` call prefills the real task and
runs its existing path-suggestion flow fresh instead of prefilling the stale demo bound. From there
the actual scaffolding work is just a normal run of the same task→bounds→execute→gate loop every
other change goes through: **this is §5's "update code" mechanism, reused one step earlier** (seed
a Task from a spec delta, re-enter the same loop), not a new one — L1 needed zero new orchestration
beyond that one wiring point. A pre-existing repo's own `task.yaml` is never touched.

## 3. Ambient fused graph + drift daemon

One graph, not two: the Spec (doc graph, rooted at the L0.5 artifact) fused with the code graph
(CBM, already used per-PR today). An **ambient daemon** watches both and writes a cheap,
immediate, lightweight flag — a draft ADR stub via `manage_adr` — the instant it detects drift.
Review is **batched at natural checkpoints** (opening the chat shell, or an explicit `review
drift` command) rather than either silently accumulating or interrupting mid-work — this was
picked deliberately over "notify immediately" because the owner's actual complaint was about
losing track over time, not about wanting interruptions.

**This reopens `memory-plane-hypothesis.md`'s Claim B** (CBM as a persistent cross-run memory
plane, currently `[PARKED]`), because an ambient daemon needs persistence across runs, not just a
per-PR adapter. The gates from that doc still apply, with one reframing: **G0 changes from "prove
stranger demand" to "the owner dogfoods it daily for N days and it stays net-positive"** — the
anti-trap concern G0 originally guarded against (building capability nobody asked for) is directly
answered by the owner being the one asking for it here. **G3 (CBM must stay swappable behind the
`ContextGraph` protocol seam) is unchanged** — cheap insurance regardless of audience, and it's
what stops a single third-party graph engine from becoming load-bearing for the gate's identity
story. G1/G2/G4 are unaffected. *(This reframing is proposed here, not yet applied as an edit to
`memory-plane-hypothesis.md` itself — that doc's own ledger should be updated in a dedicated pass
when this piece is actually built, not as a side effect of this planning doc.)*

## 4. Coherence at scale

Two problems the owner raised explicitly: how does a large project stay legible to whoever picks
it up, and how does the drift-review not become an unmanageable flat list as the project grows.

- **Onboarding:** query-first over the fused graph — the same pattern this very tool's CBM MCP
  tools already use to onboard a cold session (`search_graph`, `trace_path`, `get_architecture`).
  Anchored by **one generated (not hand-maintained) root index** that distinguishes hand-authored
  authoritative content (the Spec, ADRs) from auto-derived content (the code graph) — generated
  so it can't rot the way a hand-maintained index would.
- **Scaling:** a **module-level rollup/health view** ("12/40 modules have drift, ranked by
  connectedness/staleness") rather than a flat per-node drift list — a view concern on top of the
  same graph, not a different mechanism.

## 5. Drift resolution — the actual owner ask

Direct quote: *"the user should have the option to update the spec or the code."* Mechanism:

- **Tri-state per graph node:** code ahead of spec / spec ahead of code / contradictory.
- **Three chat commands, all gated (never silent):**
  - `update spec` — LLM rewrites just that node, reviewed as a diff, never applied unattended.
  - `update code` — seeds a new `Task` + `Bounds` from the spec delta and re-enters the **same**
    task→bounds→execute→gate loop that already exists — no new mechanism, no shortcut around the
    gate.
  - `mark exception` — recorded as a CBM ADR (an explicit, permanent decision not to reconcile).

## 6. Chat shell — the surface

Confirmed direction (Option C of three considered: reskin the wizard / drive an existing agent CLI
headlessly / **build a thin custom shell** — the owner picked the third). The artifact contract
already maps 1:1 onto chat blocks:

`Task → Bounds → Change → Verdict → ReconciliationReport → MergeRecord → Delivery`

...each renders as a card in a scrolling transcript; resume-anywhere is free by replaying the
run-store manifest (`.sembl/runs/<run-id>/`) as blocks on open.

**Orchestration model (locked):** the stage sequence is fixed, deterministic code — **never
model-chosen**. Exactly two LLM touch points, no more:
1. **Parse** — free text → structured `Task` artifact (same shape as `guide.py`'s existing
   AI-path-suggestion, generalized).
2. **Explain** — on request (an `explain` command), narrate a *finished* deterministic result in
   plain language. Never changes what happened, never runs before the deterministic result exists.

**Reference mockup** (built via `mcp__visualize` earlier in this design conversation, not a repo
file — rebuild it when implementation starts): user free-text task → `LLM parse` tagged card
(interpreted task + area guess) → deterministic suggested-bounds card → deterministic
graph-preview card → user `confirm` → deterministic executor-stream card (live file stats) →
deterministic `sembl verify — PASS` card (styled with the existing success tokens) → user
`explain` → `LLM explain` tagged card → user `merge` → deterministic merged-to-main line.

**Retires:** `wizard.py` (already effectively dead — superseded 2026-07-04 by `guide.py`).
**Reuses, does not duplicate:** `runner.py`'s headless per-stage event stream (already
byte-identical between TUI and CLI runs) and `guide.py`'s `ai_suggest_paths`/`_apply_diff`/ship-flow
logic, which should be lifted into the chat shell rather than rewritten.

## 7. Deferred — credential/integration vault

Raised in the same breath as the rest ("one platform, various keys provided") but **not designed
in depth yet** — flagged here so it isn't lost, not because it's ready to build. Concept:
generalize `profile.py`'s existing BYO-executor-key pattern (currently just "which executor") to
every integration a project might need — GitHub, Vercel, Supabase, a domain registrar, etc. —
connected once, reused by every project instead of re-wiring `sembl.stack.yaml` per project. Real
security surface (storage, scoping, rotation) — needs its own design pass, including explicit
threat-modeling, before any of it is built.

## 8. Guardrails this must not violate

- **O1** — every new piece here is a thin renderer/orchestrator over existing headless stage
  functions (`runner.py`, `presets.py`, `scaffold.py`, CBM adapters). No new core/gate logic lives
  in the chat shell.
- **O3** — none of this claims to make code better. The two LLM touch points (parse, explain) and
  the one ideation Q&A are entirely on the *process/context* side — never inside L5/L8, never a
  quality judgment. The gate stays exactly as narrow and deterministic as it is today.
- **O8 (new)** — bounded-LLM-into-fixed-schema, applied at exactly three points
  (`ai_suggest_paths`, chat-shell task-parse, L0.5 ideation Q&A) and nowhere else. If a future
  idea wants a fourth LLM touch point, it must justify itself against this same shape (fixed
  schema, human confirms, never inside the gate) — not get a new ad hoc exception.

## 9. Build order (see `PROCESS-ACTION-PLAN.md` §9 Track 5 for the tracked checklist)

1. L0.5 Idea → Spec (bounded Q&A + product.md detection).
2. L1 real scaffold from the confirmed Spec.
3. First concrete chat-shell slice: task → suggested bounds + graph-diff preview (prove the
   pattern before building the full shell).
4. Ambient fused graph + drift daemon (reopens memory-plane-hypothesis Claim B, revised G0).
5. Drift resolution commands (`update spec` / `update code` / `mark exception`).
6. Full chat shell (retire `wizard.py`, lift `guide.py`'s reusable logic in).
7. Onboarding root index + module-level drift rollup view.
8. Credential/integration vault (separate design pass first).
