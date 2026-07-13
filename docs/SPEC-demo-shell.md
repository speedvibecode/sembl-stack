# SPEC — demo-shell: the sembl cockpit (investor-demo slice)

Pinned 2026-07-13 by the lead session (owner asleep; standing instruction:
"build out the IDE nicely for the investor demo, core loop as the strong
claim, Sonnet executors"). Executors: build EXACTLY this; every judgment
call is resolved below. Deviations require stopping and reporting.

## What this is, in one line

The `sembl-stack gui` frontend rebuilt to the owner-approved shell design
(`docs/design/ide-shell-mockup.html`, codex-simple, 2026-07-10): runs
sidebar · conversation-shaped run view · preview-as-evidence pane — every
pixel backed by REAL engine artifacts from `.sembl/runs/`, the bus, and the
live loop.

## §0 Locked decisions (do not reopen)

- **D1 — surface.** This is the existing sanctioned `sembl_stack/gui`
  cockpit, NOT a shell pivot; O10 (VS Code fork) stands untouched. Full
  replacement of `sembl_stack/gui/static/*`; additive-only changes to
  `sembl_stack/gui/server.py`.
- **D2 — design source.** Copy the CSS custom properties, component styles,
  and layout of `docs/design/ide-shell-mockup.html` faithfully (light +
  dark via `prefers-color-scheme` plus `:root[data-theme=…]` overrides).
  Single accent `#7cd4df`. NO other design system. NO gradients, NO
  animation beyond a subtle pulse on the "running" dot.
- **D3 — no dead controls.** The mockup's "Spec graph" / "Code graph" /
  "Preview" top-bar buttons are OMITTED (nothing behind them tonight). Top
  bar = brand "sembl" · repo basename · spacer · primary button "New run".
  Every rendered control must do something real.
- **D4 — the composer is real, not an LLM.** Typing a task + Confirm
  creates `task.yaml`/`bounds.json` via the existing endpoint and starts
  the real loop over the existing WebSocket. No model call anywhere in
  this slice (O8/O11 wiring is a later slice). Never fabricate assistant
  prose — every line in the conversation view is real system/engine data.
- **D5 — BLOCK means blocked.** A BLOCK renders reasons and stops. There
  is NO apply/merge/override affordance anywhere on this surface.
- **D6 — writes must not clobber.** `guide.write_task_and_bounds` currently
  overwrites curated `bounds.json` (loses `churn_budget`) and `task.yaml`
  (loses `spec_path`). Fix the function itself: merge-preserve any existing
  keys not being set; only `text` (task) and `editable_paths`/
  `forbidden_areas` (bounds) are replaced. Keep the existing validation.
- **D7 — live preview via stage-hold.** `runner.run_stages` grows a
  `stage_hold: bool = False` keyword passed through to `loop.run`. The
  WS endpoint reads `?stage_hold=1`. The held `LoopResult.stage_handle`
  is stored on the server's `_State`; any previously held handle is
  `close()`d before a new run starts, and on process exit (`atexit`).
  The `done` WS message additionally carries `stage_url` (the held
  handle's `.url`, else `null`).

## §1 WP-A — backend (server.py + the two D6/D7 engine touch-points)

All endpoints additive; existing response fields keep their exact shape.
Read-only renderers over the run store (O1): no gate/core logic here.

1. **`GET /api/runs`** — each item gains: `created` (float ts from
   manifest), `executor` and `model` (best-effort from the LAST
   `change-N.json`'s `report.agent` / `report.model`, else `null`),
   `error` (manifest `error` string if present, else `null`). Must not
   raise on a run directory missing any artifact (a crashed run has only
   `run.json`); every field degrades to `null`. Sort newest-first by
   `created`.
2. **`GET /api/runs/{run_id}`** — gains top-level `created`, `error`,
   `bounds` (`{"editable_paths": [...], "forbidden_areas": [...]}` from
   the run's `bounds.json` artifact, else `null`), and per attempt (in
   `attempts[]`, existing fields unchanged):
   - `acceptance`: list of `{id, outcome, duration_s, detail}` from
     `acceptance-N.json` `results`, else `null`;
   - `stage`: from `stage-N.json`: `{ok: ready.ok, url, port, diff_sha256,
     routes: {route: {file, http_status, status}}}`, else `null`;
   - `cost_usd` (from `change-N.json` `report.cost`, else `null`),
     `model` (`report.model`, else `null`).
   Also top-level `acceptance_descriptions`: `{check_id: description}`
   read from the bound repo's `acceptance.json` (best-effort, `{}` when
   absent/unparseable — NEVER an exception).
3. **`GET /api/runs/{run_id}/stage/{attempt}`** — serves the first
   route's snapshot file from `stage-{attempt}.json`'s `routes` (resolve
   `file` relative to the RUN DIRECTORY, reject any resolved path that
   escapes it) as `text/html`. 404 JSON `{"error": ...}` when missing.
4. **`GET /api/events?cursor=0`** — `{"events": [...], "cursor": N}` via
   `bus.read_since(state.root, cursor)`.
5. **WS `/ws/run`** — accepts `?stage_hold=1` per D7. Existing message
   protocol unchanged otherwise.
6. **D6 fix** in `sembl_stack/guide.py` as specified.

**Tests — `tests/test_gui_server.py`, ≥ 12, all passing, plus the full
suite stays green.** Use `starlette.testclient.TestClient` against
`create_app(tmp_repo)` with fixture-written run dirs (copy real artifact
shapes from this spec's appendix). Required cases: empty store returns
`[]`; enriched list fields; crashed-run tolerance (only `run.json` with
`error`); detail with acceptance+stage; detail for run missing both →
`null`s; stage HTML served; stage 404; stage path-escape rejected (a
`file` of `"../../secret.html"` → 404); events cursor advances; bounds
merge preserves `churn_budget`; task write preserves `spec_path`;
`run_stages` passes `stage_hold` through (monkeypatched `loop.run`
asserting the kwarg).

**DO-NOTs (WP-A):** no new dependencies; no changes to `loop.py`,
`store.py`, `bus.py`, `artifacts.py`; no changes to existing endpoint
field shapes; no `print`; match the module's docstring/comment voice;
UTF-8 everywhere (`encoding="utf-8"` on every open).

## §2 WP-B — frontend (`sembl_stack/gui/static/` full rewrite)

Three files only: `index.html`, `styles.css`, `app.js`. Vanilla
HTML/CSS/JS (ES2020), no framework, no build step, no external requests
(no CDN fonts — system font stack per the mockup).

**Layout** (mockup verbatim): top bar; grid `250px | 1fr | 430px`;
below 1180px the preview column hides.

**Sidebar — Runs.** From `/api/runs`: dot (PASS `--pass`, BLOCK/`failed`
`--block`, running/started `--accent` with soft pulse, else muted), title
= first 60 chars of task text, meta line = `model · N attempts ·
verdict|status` (+ time from `created`, `h:mm am/pm`). Click selects.
Empty state: "No runs yet — describe a task below to start the first
one." as a muted row.

**Center — the selected run, conversation-shaped.** In order:
1. user bubble: the task text;
2. task card rows: `Task` (text) · `Can edit` (bounds editable, mono,
   `·`-separated) · `Can't touch` (forbidden) · `Must pass` (acceptance
   descriptions joined; row omitted when none);
3. per attempt N: a quiet line `attempt N · <run_id>` then a verdict
   block: colored dot + `Passed the gate` / `Blocked by the gate` /
   `Warned by the gate`; checks list (✓ green / ✗ red per outcome, id or
   description, `duration_s`s right-aligned muted); on BLOCK a mono
   `.why` box listing `reasons` verbatim;
4. a final quiet line for the run status (`merged`/`completed`/`failed ·
   <error first line>`).
No invented prose anywhere (D4). Deep-linkable: `#run=<id>` hash selects.

**Composer.** A real input (textarea, Enter submits, Shift+Enter
newline), placeholder "Describe a change — the loop plans bounds, builds
in a sandbox, and the gate judges it." Submitting shows a task card
(bounds prefilled from `/api/status` `task.editable`/`task.forbidden`,
editable inline as two comma-separated text inputs) with `Confirm and
run` (primary) and `Cancel`. Confirm → `POST /api/task`; on `{ok:true}`
open `WS /ws/run?stage_hold=1`.

**Live run.** While the WS is open: a sidebar row "(new run)" with
running dot; center shows real quiet lines from WS stage events (map:
`bounds`→"planning bounds", `sandbox`→"opening a disposable sandbox
(attempt N via detail)", `loop`→"executor writing (attempt N)",
`verify`→"the gate is judging"; `fail` states render the detail in the
block color). In parallel poll `/api/events?cursor=` every 2s; on
`run.started` adopt the real `run_id`; on `stage.up` flip the preview to
the live URL; on `stage.down` revert to snapshot mode. On WS `done`:
stop polling, re-fetch `/api/runs` + detail, select the run; if
`stage_url` present keep the preview live. On WS `error`: render the
message in a red-tinted card — honest failure, no retry loop.

**Preview pane.** Bar: live-dot (green = live URL, muted = snapshot),
URL text (live URL or `run <id> · snapshot`), right `attempt N ·
sandbox`. Body: `<iframe>` `src` = live URL when live, else
`/api/runs/{id}/stage/{n}` for the selected attempt (latest with stage
by default). Foot: `Evidence — bound to run <id>, attempt <n> · diff
<first 8 of diff_sha256>` and, when no stage exists: an empty-state
message "No stage evidence recorded for this run." (no iframe).

**DO-NOTs (WP-B):** no framework/CDN/fonts/network beyond the app's own
API; no dead buttons; no localStorage settings UI; no md rendering; no
override/apply UI (D5); do not edit `server.py` (that's WP-A); no emoji;
text tone matches the mockup (lowercase-quiet, precise).

## §3 Lead verification (not the executor's job, listed for transparency)

Browser live-proof against the demo repo
(`C:\Users\totla\Desktop\projects\sembl-demo\feedback-board`): render
recorded runs; walk composer → confirm → live run → verdict; check empty
states, BLOCK path, preview evidence binding; suite green.

## §4 Anti-trap note

Signal first was honored: the loop was live-proven headless on the demo
repo (run `20260713-015329-5d53bf`, real claude/sonnet executor, real
gate BLOCK, real stage evidence) BEFORE this chrome was specced. This
surface renders artifacts that already exist; if it burned down, the
engine would lose nothing.

## Appendix — real artifact shapes (from run 20260713-015329-5d53bf)

- `run.json`: `{id, created, status, artifacts{name:{kind,file,ts}},
  task{text,repo}, updated, attempts_log?[], error?}`
- `verdict-N.json`: `{status: "PASS"|"WARN"|"BLOCK", reasons: [str], ...}`
- `acceptance-N.json`: `{results: [{id, outcome: "PASS"|"FAIL"|"ERROR",
  seed, duration_s, evidence, detail}], runner}`
- `change-N.json`: `{diff, report{files_modified, agent, model,
  exit_code, output, stderr, cost, usage}, workdir}`
- `stage-N.json`: `{attempt, serve, url, port, ready{ok, detail, boot_s,
  stderr}, snapshot_s, diff_sha256, routes: {"/": {status, file,
  http_status}}}` — snapshot at `stage-N/root.html`
- bus kinds: `run.started|run.stage|run.verdict|run.finished|stage.up|
  stage.down|drift.new|deploy.status|postdeploy.status|other`
- WS protocol today: server → `{type:"stage", stage, state, detail,
  diff}` / `{type:"done", run_id, status, reasons, attempts}` /
  `{type:"error", message}`.
