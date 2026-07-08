# SPEC — Theia-forked Factory IDE (graph/code-first cockpit)

> Status: **[LOCKED direction, 2026-07-05]** — design-conversation stage only, **nothing built yet**.
> This supersedes `PROCESS-ACTION-PLAN.md` §5 O7 (currently still describes a pywebview multi-pane
> dashboard app) and elevates/re-homes Track 5 item 5 ("chat shell", §9). That doc's own status
> lines have not been edited to point here yet — do that in the same commit that starts real work,
> so the ledger stays diffable. Do not treat this doc as validated just because it's written down;
> §1's honest-differentiation case is the thing that must survive contact with real dogfooding, not
> a rhetorical exercise.

## 0. The one-paragraph goal

A forked-Theia IDE where the L0–L8 pipeline (spec → bounds → execute → sandbox → gate → merge →
deploy → postdeploy) is a first-class, swappable control surface, and the codebase's own
spec-to-code drift is an always-visible structural view — not a dashboard bolted onto an editor,
not a chat transcript with extra panels. Code stays the primary, default surface (this is a real
IDE technical users work in daily); the graph, pipeline strip, and drift view are one click away,
not the thing competing with the editor for the center of attention on day one.

## 1. Why this and not another dashboard/chat shell — the honest case

This is the fourth surface decision for sembl-stack (Textual wizard → `guide.py` CLI → chat shell →
pywebview dashboard → this). Each prior one died to some version of "this is just Claude Code /
Cursor with extra chrome." Before committing more build time, the differentiation case has to
survive being argued against directly, not asserted.

**The structural differences that are real, not decorative, if built and used correctly:**

1. **The verdict is mechanical, not another model's opinion.** Cursor/Kiro's review step is an LLM
   (or a human) judging a diff. `sembl verify` is deterministic — scope/forbidden/fabrication/
   evidence/churn checks against a declared contract, no model in the loop for the judgment. The
   top bar's PASS/WARN/BLOCK is a rerunnable, auditable fact.
2. **The pipeline is a typed, swappable artifact contract**, not one vendor's agent loop. L0–L8 are
   independent stages (`Task → Context → SpecGraph → Bounds → Change → Verdict → ReconciliationReport
   → MergeRecord → Trace → Delivery`) that can each be swapped — executor, reviewer, deploy target —
   and made a first-class, visible control. Cursor has no concept of "8 independently swappable
   stages" to expose.
3. **Accountability doesn't stop at merge.** L7/L8 (deploy + post-deploy gate + rollback) extend the
   guarantee into production mechanically — most agent IDEs are done at "PR opened."
4. **Spec↔code drift, continuously reconciled against a real code graph (CBM), not a static spec
   file that rots.** — **this is the point that actually closed the argument in the design
   conversation this spec comes from.** Kiro writes a spec once; nothing here keeps it honest
   against the code as it moves. A live, bidirectional, structurally-reconciled drift view is not
   something either competitor has, and it does not depend on the user ever touching the
   swap/persona/config machinery to be felt — it fires on its own as code and spec diverge.

**The honest counter-case, which is why this doc does not call the argument settled:**

- If the top bar's swap control is set once and never touched again in daily use, it is decoration,
  not a differentiator anyone feels.
- The deterministic gate's edge is clearest at team/CI scale, catching what a distracted reviewer
  across many PRs misses. For a solo owner reviewing his own repo closely, a human-in-the-loop diff
  review may already catch most of the same things — the gate's value is less *felt* at n=1.
- If drift/verdict/readiness rarely fire in real usage, they are unused chrome — which is precisely
  the failure mode that killed the dashboard and chat-shell attempts.

**The validation criterion, not just design reasoning (see §5 build order):** drift, gate WARN/BLOCK,
and executor/reviewer swapping must already be producing real, non-trivial signal in the *existing*
CLI/stack — which runs today without any of this UI — before the IDE is trusted to carry the
differentiation. If those things aren't firing yet at the CLI level, building the IDE chrome first
just dresses up something not yet proven, and repeats the exact mistake the last three surfaces made.

## 2. Base & scope

- **Fork Theia**, not VSCodium — Theia is built as an extensible platform (custom panels/views are
  first-class); VSCodium fights harder on deep structural additions.
- L3 executors (codex, opencode, aider, claude) stay swappable adapters behind the existing
  `ReviewAdapter`/executor protocol, run out-of-process the way they do in the CLI today — the IDE
  watches the run store, it does not need to embed them as editor extensions.

## 3. Layout (the resolved information architecture)

- **Top bar — the pipeline strip.** L0.5 through L8 as clickable, swappable segments (e.g. `L3
  execute: codex ▾`), status-colored. This is the one part of the UI carrying the actual thesis (see
  §1) — clicking a segment must surface *why* a stage produced its verdict (e.g. "why WARN" →
  churn/scope/fabrication detail), not just show a color. **Exact drill-down content is not yet
  designed** — flagged as open work, not assumed solved by this doc.
- **Activity bar + file explorer.** Standard file tree, first-class — files are not secondary to the
  graph.
- **Center — three tabs, `code` is the default:** `graph` (fused spec+code graph, Track 5 item 3,
  nodes colored by drift tri-state: aligned / code-ahead / spec-ahead / contradictory) → `code`
  (normal editor, opens here by default and when a graph node is clicked) → `preview` (embedded
  terminal/test output for CLI-shaped targets, embedded browser preview for web targets — same
  pattern as this assistant's own preview tooling).
- **Right — the discuss panel.** Open-ended, back-and-forth conversation (question → tradeoff →
  decision), same depth as Claude Code/Codex chat — explicitly **not** a one-way "here's what
  changed" narration, that was tried and rejected in this design conversation as too passive. Its
  job is to produce *bounded* artifacts (a spec note, a `Task`+`Bounds` pair, a diff) as the outcome
  of unbounded discussion — the boundary is on the artifact, never on the conversation.
- **Bottom — a scrubbable run-history ribbon.** Every past run as a small PASS/WARN/BLOCK tick,
  always visible regardless of which sidebar/center view is open.
- **L8/readiness (MurphyScan) gets its own sidebar destination**, not a top-bar chip — it's a
  13-layer P0–P3 audit, too much surface for one dropdown.
- **Progressive disclosure.** On a fresh repo, the pipeline strip/sidebars start collapsed/minimal —
  a near-empty-cockpit first run, Replit/Lovable-style. Chrome earns screen space as real runs,
  graph nodes, and drift accumulate. The cockpit feel is a deliberate, confirmed goal once there's
  something to show — this is not "strip the cockpit down," it's "don't front-load it before it's
  earned."
- **Persona setting (technical / non-technical), in settings.** Same shared panel set for both.
  Technical unlocks: raw `sembl.stack.yaml` fields in the top-bar dropdowns (not just adapter names),
  terminal passthrough, direct artifact JSON editing (`bounds.json`, `spec.json`), MCP tool access.
  Non-technical keeps the same panels with plain-language status ("using Codex to write, Sembl to
  check" instead of adapter internals) and a more recommendation-forward discuss panel. This is the
  existing O8 pattern (bounded LLM into a fixed schema, human confirms) — persona changes which layer
  of that schema is exposed, not a different product underneath.

## 4. What this reuses vs. builds new

- **Reuses unchanged (O1 intact):** `runner.py`, `loop.py`, all adapters, `reconcile --live`, the CBM
  graph, the full artifact contract. Zero core/business-logic rewrite.
- **New:** Theia extension(s) that render these as panels/views and call the same headless functions
  the CLI already calls. The IDE is a thin client, same as every other surface this project has built.

## 5. Sequencing / build order — anti-trap discipline applies here too

Per `PROCESS-ACTION-PLAN.md`'s already-locked discipline (prove on the one flagship before fanning
out), building full Theia chrome before the thing it's meant to showcase exists would repeat the
exact mistake that killed the last three surfaces. Concretely, in order:

1. ~~**Finish Track 5 item 3 first, headless, no IDE involved**~~ — ✅ **DONE 2026-07-05,
   live-proven, not yet committed.** `sembl_stack/drift.py` + `drift-check`/`drift-review` CLI
   commands (see `PROCESS-ACTION-PLAN.md` Track 5 item 3 for the full account). Run live against
   the real flagship (`examples/flagship-feedback-board`, real CBM index, 2953 nodes, a real
   10-node SpecGraph from its actual spec dir): **the drift signal is real, not a demo** — it
   found 5 genuine findings (an entity naming mismatch, 4 unrepresented RLS/secret-handling data
   rules), correctly stayed quiet on re-check (no duplicate flagging), and correctly stopped
   surfacing findings once acknowledged. §1's validation criterion is satisfied for the drift
   axis specifically — this does NOT by itself validate the swappable-pipeline-strip or
   gate-felt-at-n=1 questions §1 also raised; those remain open until the IDE itself is used
   daily.
2. ~~**Only then, the smallest possible Theia slice**~~ — 🟡 **PARTIALLY DONE 2026-07-05,
   framework mechanics live-proven; graph view + resolution commands not yet built.** A real,
   running Theia 1.73.1 browser app (`sembl-stack/ide/`: `drift-view` extension + `browser-app`)
   with a right-side-panel React widget that reads `.sembl/drift-state.json` through a genuine
   backend JSON-RPC service (`DriftService` over `/services/sembl-drift`) — not mocked, not
   hardcoded. Verified with the `preview_*` tools against a live running instance: `tsc -b` and
   `theia build` both complete with 0 errors, the app boots to `ready`, the command palette's
   "View: Toggle Drift" opens the panel, and it renders the **same 5 real findings** from
   step 1's flagship live-proof, fetched live over the RPC channel.
   **Bug caught and fixed in the process:** the extension's `package.json` pinned
   `"react": "^18.2.0"`, which the workspace root couldn't satisfy (root hoisted `react@19.2.7`
   via `@theia/core`'s `^18.3.1 || ^19.0.0` range) — npm silently installed a second, incompatible
   React copy nested in `drift-view/node_modules`. Two React instances in one page is a classic
   silent-failure mode: the app built and booted fine, the widget's tab/icon appeared, but its
   `render()` output was rejected by Theia's React root (`An error occurred in the <Root>
   component`, swallowed to a blank panel with no thrown exception anywhere in the visible logs).
   Fixed by widening the range to match `@theia/core`'s (`^18.3.1 || ^19.0.0`) and doing a clean
   reinstall (deleting the stale lockfile, which had pinned the conflicting resolution even after
   the range widened). **Still not done:** the graph-panel visualization and the three tri-state
   resolution commands (`update spec` / `update code` / `mark exception`, Track 5 item 4) — this
   slice deliberately only proves the plumbing (real backend data reaching a real Theia widget)
   works, per this section's own smallest-possible-slice discipline.
3. ~~**Everything else comes after step 2 is validated by actual daily use**~~ — 🟡 **PARTIALLY
   SUPERSEDED 2026-07-07 by owner directive** ("make this IDE ready so I can start using Claude
   Code/codex from there, all tools in one place"): daily-drivability itself became the priority,
   consistent with the build-for-owner-first memory. Built and live-verified 2026-07-07:
   - **Full IDE horizontals via stock Theia packages** (zero custom code): embedded terminal
     (node-pty 1.2.0-beta.12 win32 prebuilds — proven live: command typed in the IDE terminal
     executed by a real shell; `claude --version` → `2.1.179 (Claude Code)` from inside the IDE),
     search-in-workspace, file-search, markers/problems, keymaps, messages, editor-preview, task,
     scm, userstorage, variable-resolver.
   - **VS Code plugin system + Open VSX marketplace** (`@theia/plugin-ext-vscode` +
     `@theia/vsx-registry`), with builtin plugins pinned in `browser-app/package.json`
     `theiaPlugins` (vscode.git 1.95.3 + git-base + markdown-language-features; restore via
     `npm run download:plugins`). Git proven live: SCM view showed the repo's real 25 changes,
     status bar showed `master*`. Any further tool (LSPs, themes, linters) is user-installable
     from the Extensions view.
   - **The factory chrome, v1** (`ide/factory-view/`, same thin-renderer pattern as drift-view):
     a bottom **Factory panel** = pipeline strip (L1–L8 segments, adapter names read live from
     `sembl.stack.yaml` via a line-wise reader mirroring `config.py` DEFAULTS; config-set vs
     default visually distinguished) + run-history ribbon over `.sembl/runs/` (PASS/WARN/BLOCK
     ticks; click → verdict, reasons, task text, attempt count) + a status-bar verdict chip.
     Proven live against a real `gate+sandbox` run (BLOCK → retry → PASS, 2 attempts) rendered
     from real run-store JSON. App renamed **"Sembl Factory IDE"**.
   - Windows build gotchas discovered + handled: (a) `@vscode/windows-ca-certs` cannot node-gyp
     here (MSB8040 Spectre libs); prebuilt with `SpectreMitigation=false`, vendored at
     `ide/vendor/windows-ca-certs/`, auto-restored by the `postinstall` script — Theia's backend
     bundler hard-requires it on win32. (b) `theia build` while the app is running fails with a
     file-lock on `lib/backend/native/*.node` — stop the server before rebuilding.
   **Still not built, still gated on daily use:** graph view, the three tri-state resolution
   commands (Track 5 item 4), top-bar swap *control* (strip is read-only; swapping = editing
   the yaml), discuss panel, persona split, progressive disclosure, visual/brand polish (§6).
   Chrome beyond the above stays gated per §1 — the strip/ribbon/chip themselves are now the
   signal surface daily use is meant to validate.
4. **Design system LOCKED 2026-07-07** — the owner generated and approved a full visual design
   (interactive reference: `docs/design/sembl-ide-design-reference.html`; exact tokens,
   components, and the full target surface map extracted into `docs/DESIGN-sembl-ide.md` —
   build to it, do not redesign it). The same session locked two ledger additions
   (`PROCESS-ACTION-PLAN.md` §5): **O9** (the factory guide — a Haiku-class, strictly read-only
   operator-assist LLM, the second and last sanctioned LLM pattern) and **S13** (executor
   swappability tiered by adapter class — CLI today, SDK-based next, ACP candidate; the L3
   contract unchanged). Build order from here is `DESIGN-sembl-ide.md` §5: (1) tokens +
   restyle + factory strip, (2) live-run stage lighting, (3) BLOCK actions incl. the heavy
   override, (4) tri-state drift resolution headless-first, (5) graph view via an
   off-the-shelf graph lib, (6) discuss panel (O8) + factory guide (O9). The owner also
   directed one-click launch (desktop shortcut → backend + app-mode window; scripts staged
   in `ide/scripts/launch.ps1`/`launch.vbs`, production build script `build:prod` added) —
   finish and verify it alongside step 1.
5. **Build-order status (2026-07-08, each step Sonnet-executed to a pinned spec, lead-reviewed
   and independently re-verified live before commit):** steps 1–4 ✅ — (1) tokens + restyle +
   factory strip + one-click launch (`b28198e`), (2) live-run stage lighting off
   `events.jsonl`/run status (`e36fb3f`), (3) BLOCK action row: re-run (spawns a real loop),
   revise bounds, heavy override — deliberately inert until an engine-side override path
   exists, since `apply`/`merge` refuse BLOCK with no bypass (`8bc16b6`), (4) tri-state drift
   resolution: headless `drift-resolve` CLI (`4b36be5`) + drift panel restyle and buttons as
   thin CLI invokers, exception records made check-proof (`2d2ef43`). **Next: step 5 (graph
   view), then step 6 (discuss panel O8 + factory guide O9).**

## 6. Open questions — not yet resolved by this doc

- Exact content/interaction of the top-bar "why WARN" drill-down.
- Exact technical/non-technical feature split beyond the three examples given in §3.
- Visual/brand polish (these designs used generic default styling, not sembl's own cyan-accent
  identity) — deliberately deferred until there's a working Theia scaffold to skin against, since
  Theia's own widget/theming APIs will constrain what's feasible more than an abstract design pass
  would reveal.
- Theia's real extension-API limits on center-tab custom rendering (graph canvas, preview toggle) —
  unverified against the actual framework, this doc reasons from Theia's stated extensibility, not
  from a working spike yet.

## 7. Guardrails this must not violate

- **O1** — every new piece is a thin renderer over existing headless stage functions. No new core/
  gate logic lives in the Theia extension.
- **O3** — none of this claims to make code better. The discuss panel's two LLM-touch shape (parse
  intent → bounded artifact) stays on the process/context side, never inside L5/L8, never a quality
  judgment.
- **O8** — bounded-LLM-into-fixed-schema stays the only LLM pattern in play (discuss-panel output,
  L0.5 ideation, `ai_suggest_paths`) — a persona-gated feature does not get to add a fourth,
  unbounded LLM touch point without separately justifying it against this same shape.

## 8. Supersedes / superseded by

Supersedes: `PROCESS-ACTION-PLAN.md` §5 O7's pywebview dashboard app description; re-homes
`SPEC-ideation-and-chat-shell.md` §6's "chat shell" as this doc's discuss panel (the artifact-contract-
as-chat-blocks idea survives, the "chat is the whole surface" framing does not). See also the memory
`surface-pivot-theia-factory-ide` (persistent, cross-session) for the same content in a form future
sessions read before touching this file.
