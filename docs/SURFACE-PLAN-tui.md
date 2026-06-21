# Surface plan — `sembl stack` guided TUI (and the IDE surface behind it)

> Owner vision 2026-06-21: a single entry — `cd <dir>` then `sembl-stack` — launches a TUI
> that **guides** a person through the whole accountable chain (new-or-existing repo → code
> graph alive → spec → loop → gate → merge → deploy → readiness), **resumable anywhere**
> (leave/continue). This doc is the guide-through. It is on-plan, not a detour: it *is* C4
> (stranger-runnable surface) + the **beta-test surface** + a **self-test milestone**.

## 0. Why this is tractable (the load-bearing insight)
The platform was built **artifact-first**: every stage reads/writes typed JSON in
`.sembl/runs/<id>/` (see `PLATFORM-MAP.md` §2, `artifacts.py`). "Enter, leave, resume at any
stage" was a *design property from day one*. So the TUI is a **thin guide over machinery that
already persists every step** — not a rewrite. We already have the pieces:
- `tui.py` — a working **Textual** app (`RunsDashboard`), Textual already an optional extra.
- `views.py` — run data (`list_rows`, `detail_lines`) the TUI renders.
- `presets.py` — `just-gate | gate+sandbox | full-loop` annotated configs (the adoption ramp).
- `loop.py` — plan → execute → sandbox → gate → retry, persisted to the run store.
- per-stage CLI commands — `specgraph, bounds, execute, verify, merge, deploy, postdeploy,
  reconcile, runs, dash, doctor, init` — each a re-enterable stage over an artifact.
- codebase-memory-mcp (CBM) — `index_repository` / `detect_changes` for the code graph.

The TUI **orchestrates these**; it owns no new business logic. That is the whole point of the
artifact contract.

## 1. Entry & framing (match the opencode feel)
- **Bare `sembl-stack`** (no subcommand) → launches the guided TUI. Subcommands stay for
  power users / automation / agy delegation (exactly like `opencode` vs `opencode run`).
- On launch the wizard scans `.sembl/runs/` for an **incomplete session** and offers
  **Resume `<id>` (at: gate)** or **Start new** — this is the leave/continue-anywhere behaviour,
  and it is nearly free (a `session.json` pointer = `{run_id, current_stage}` beside the
  artifacts that already exist on disk).

## 2. The guided journey (a state machine = the stage rail)
A persistent **left rail** shows the pipeline with check-marks as each stage completes (a
CI-run-page UX). Each step is a Textual `Screen`; each writes its artifact to the run store.

| # | Screen | Backs onto | Produces |
|---|---|---|---|
| 1 | **New or Existing repo?** | git init (new) / pick dir (existing) | `Task.repo` |
|   | → Existing → **index code graph** | CBM `index_repository` (bg, progress shown) | code-graph live |
| 2 | **Intent** — type the goal, or point at a Spec Kit dir | `spec` stage | `Task` (+ `SpecGraph`) |
| 3 | **Bounds** — show/confirm/edit editable_paths, forbidden, churn | `bounds` stage | `Bounds` |
| 4 | **Pick executor + preset** | `presets.py` | `sembl.stack.yaml` |
| 5 | **Run the loop** — live stream (reuse `views`) | `loop.py` | `Change`, `Verdict` |
| 6 | **Reconcile (S9)** — SpecGraph↔CodeGraph divergence; choose update-spec/update-code | `reconcile` | `ReconciliationReport` |
| 7 | **Quality review** (slot; lights up when CodeRabbit wired) | L5.5 adapter | findings signal |
| 8 | **Merge gate** — PASS/WARN ⇒ merge button; BLOCK ⇒ held + reasons | `merge` stage | `MergeRecord` |
| 9 | **Deploy + post-deploy** — live status, URL, rollback | `deploy`/`postdeploy` | `Delivery`, prod `Verdict` |
| 10 | **Readiness** — MurphyScan launch-readiness summary (S12) | `/murphyscan` | readiness report |

Resume = load the artifacts that exist, jump the rail to `current_stage`. Leave = it's already
on disk; just quit.

## 3. Build phases (each a pinned spec → agy executes → Claude reviews)
- **Phase 0 — MVP skeleton (the C4 close).** Bare `sembl-stack` → Textual app with the stage
  rail + New/Existing prompt + Resume detection (`session.json`). Wire ONLY stages that already
  run headlessly (steps 1–3, 5, 8, 9) as screens that call the existing functions. No new
  backend. **This alone makes a stranger able to run the whole loop — C4 done properly.**
- **Phase 1 — full journey.** Add CBM index trigger on Existing (step 1b), the reconcile panel
  (step 6), live deploy/postdeploy panels (step 9), the MurphyScan readiness screen (step 10).
- **Phase 2 — beta-ready.** Error/empty states, `doctor` preflight inside the TUI, onboarding
  copy, the quality-review slot (step 7) wired to CodeRabbit when its adapter lands. **Surface
  exists end-to-end ⇒ recruit the 3–5 private-beta partners (S4).**
- **Phase 3 — launch-ready / IDE surface.** A VS Code extension that watches `.sembl/runs/` and
  renders the *same* stage rail in a webview, calling the *same* CLI stage commands. TUI and IDE
  are **two front-ends over one engine** — no core duplication. (Build TUI first; IDE second.)

## 4. The self-test milestone (dogfood = proof)
Once Phase 0–1 works, **use `sembl-stack` on the sembl-stack repo itself** to build the next
sembl-stack feature (e.g. the L8 rollback trigger): Existing repo → CBM indexes our own code →
spec the feature → loop → gate → merge → deploy. The factory building the factory, vetted by its
own gate. This is the literal self-test, and it is the on-ramp to the north-star **L4
self-authoring** rung (`process-self-improvement.md`). It is also the single most convincing demo
artifact we can produce.

## 5. Where it sits in the roadmap (on-plan, not a detour)
This **elevates C4** from "exists (dash/presets/doctor)" to "guided, resumable journey" — and C4
is a locked launch requirement (ROADMAP §2 C4, §3 sequence). It is the prerequisite surface for
the private beta (S4) and the vehicle for the self-test milestone. Sequencing: it can proceed
**in parallel** with closing the depth-1 spine (rollback + reconcile-live), because Phase 0 only
wires stages that already exist — the spine work and the surface work touch different layers.

## 6. The honest engineering notes (so the ambition stays grounded)
- **Textual is the right tool** (already a dep; matches the opencode TUI feel; pure-Python so it
  ships in the same package). IDE later reuses the artifacts, not the Textual code.
- **The TUI must never embed gate logic.** It shells the same stage functions the CLI does, so a
  TUI run and a headless run are byte-identical in the run store. (Same degrade-don't-fail stance
  as `tui.available()` today.)
- **Resumability is a `session.json` pointer + the existing artifacts.** Do not invent a new
  persistence layer — the run store already is it.
- **Long-running stages (loop, deploy) run in a worker**, streaming into the pane via `views`;
  the rail stays responsive and quit-safe at any moment.

## 7. First concrete step
Write the **Phase-0 pinned spec** (`docs/SPEC-tui-phase0.md`): the bare-`sembl-stack` entry, the
Textual app + stage rail, New/Existing screen, `session.json` resume pointer, and screens 1–3/5/8/9
shelling existing functions — plus tests (the app boots headless, `session.json` round-trips,
resume detection picks the latest incomplete run). Then agy executes it from the spec; Claude
reviews + verifies; commit on a `tui-surface` branch.
