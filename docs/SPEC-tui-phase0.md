# SPEC / RECORD — `sembl-stack` guided TUI, Phase 0

> Status: **BUILT & GREEN (2026-06-22)**. Unlike the L8-rollback and reconcile-live specs (pinned
> for agy), this from-scratch Textual app was **implemented and verified directly by Claude** — a
> new Textual app is the highest-risk thing to hand a cheap model, so it was prototyped to green
> (98 passed) first. This doc is the record + acceptance, not a build order. Owner decision
> (2026-06-22): keep the verified build.

## 0. What Phase 0 delivers (action-plan §9 item 3)
Bare **`sembl-stack`** (no subcommand) launches a Textual wizard that **guides** the run with a
New/Existing choice + a **stage rail** (CI-run-page UX) and **leave/continue-anywhere resume** via
a tiny `session.json` pointer over the existing run store. It is a *thin guide over artifact-first
machinery* — **no new core/gate logic**: the rail shells the same already-headless stages the CLI
exposes. (Live execution panels, CBM index, reconcile/deploy/MurphyScan screens = Phase 1.)

## 1. The deterministic core — `sembl_stack/session.py` (NEW)
Pure, headless, no Textual. The `Session` dataclass + `.sembl/session.json` persistence +
`resume_or_new`. Stage rail order (already-headless only):
`STAGES = ["bounds", "loop", "verify", "merge", "deploy", "postdeploy"]`.
- `Session(repo, mode, run_id, current_stage, completed)`; `advance()` marks the current stage
  complete and clamps at the last stage; `done` is true when all stages are complete.
- `save(session)` writes `.sembl/session.json`; `load(repo)` reads it (None if absent, ignoring
  unknown keys); `resume_or_new(repo)` returns the saved session if it exists **and is
  incomplete** (the continue-anywhere point), else a fresh session at the first stage.

## 2. The guided surface — `sembl_stack/wizard.py` (NEW)
Textual app, guarded by `available()` (Textual is the `[tui]` extra; degrade-don't-crash, same
stance as `tui.py`). `_rail_text(session)` renders the rail as plain text (`[x]` done / `[>]`
current / `[ ]` pending) — a pure function, unit-tested directly. `StackWizard(App)`:
- `compose`: Header; a `#mode` panel with **New repo** / **Existing repo** buttons; a `#rail`
  Static showing the stage rail; Footer.
- BINDINGS: `q` quit · `n` New · `e` Existing · `space` advance. Buttons and keys both call the
  same handlers; every mode-change/advance **persists `session.json`** and refreshes the rail.
- `launch(repo)` runs the app (caller checks `available()` first).

## 3. Bare-command wiring — `sembl_stack/cli.py`
The `main` group became `@click.group(invoke_without_command=True)` + `@click.pass_context`. With
no subcommand it launches the wizard; if Textual is absent it raises an actionable
`UsageError` (`pip install "sembl-stack[tui]"`, or run a stage directly). All existing subcommands
are unaffected; `--version` still works (eager option).

## 4. Tests
- `tests/test_session.py` (always-run, pure): round-trip through disk, missing→None, advance
  marks complete + moves next, over-advance clamps + marks done, resume returns a saved incomplete
  session, resume starts fresh when none/complete. **6 tests.**
- `tests/local/test_wizard.py` (mirrors `test_c4_tui.py`; **local-only — `tests/local/` is
  gitignored**, the TUI-pilot convention since pilots need the `[tui]` extra): pure `_rail_text`
  markers; bare-command degradation without Textual (CliRunner); and a **headless pilot**
  (`asyncio.run` + `app.run_test`, `skipif(not wizard.available())`) asserting the New/Existing
  buttons + rail mount and that `e` then `space` persist `mode="existing"` and the first stage in
  `completed`. **3 tests.**

## 5. Acceptance (verified 2026-06-22)
- **Committed suite (CI):** `.venv\Scripts\python.exe -m pytest -q --ignore=tests/local` →
  **49 passed** (43 prior + 6 new `tests/test_session.py`). The deterministic session core — the
  load-bearing resume logic — is fully covered here, no Textual needed.
- **Full local suite (with the `[tui]` extra):** `pytest -q` → **98 passed** (includes the 3
  local-only wizard pilot tests + the existing `tests/local` set). Install the extra with
  `uv pip install "textual>=0.50"`; without it the pilot tests skip.
- All four §9-item-3 acceptance points met: app **boots headless in CI** (pilot), **session.json
  round-trips** (session tests), **resume picks the latest incomplete run** (`resume_or_new`),
  and bare `sembl-stack` presents New/Existing → stage rail covering **loop→gate→merge→deploy**.
- **Owner live-proof (manual, stranger-runnable):** in a TTY, run bare `sembl-stack`, pick a mode,
  press `space` to walk the rail, quit, relaunch → it resumes mid-rail from `.sembl/session.json`.

## 6. Out of scope (Phase 1, §9 item beyond)
Live loop/agent execution from the rail, CBM index trigger, reconcile/deploy/postdeploy/MurphyScan
panels, a real multi-Screen flow. Phase 0 deliberately wires only already-headless stages and a
single screen so the guide stays a thin shell over the run store.
