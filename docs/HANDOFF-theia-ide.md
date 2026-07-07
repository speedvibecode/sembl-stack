# Handoff: Theia factory IDE — continue building here, in sembl-stack

Written 2026-07-05 for a fresh chat session rooted in this repo (`sembl-stack`), to
pick up the Theia IDE build without needing the prior conversation's history. That
prior conversation ran in the sibling `sembl` repo as its primary working directory,
which is why the IDE code lives under `sembl-stack/ide/` but was built/verified from
outside it — this doc exists so a session rooted directly in `sembl-stack` can
continue cleanly with its own `.claude/launch.json` already in place.

## Read this first

`docs/SPEC-theia-factory-ide.md` is the authoritative design doc — full target layout
(top pipeline strip, left sidebar, center graph/code/preview tabs with code default,
right discuss panel, bottom run ribbon, persona split, dedicated L8 view, progressive
disclosure), the honest differentiation argument against Cursor/Kiro (§1, including the
counter-case — don't skip it), and the build-order discipline (§5). §5 is kept
up to date with what's actually done vs. deferred — trust it over this doc for status,
since this doc will go stale and that one is the one meant to be maintained.

`docs/PROCESS-ACTION-PLAN.md` Track 5 has the parallel headless-mechanics account
(items 1-8), especially item 3 (the drift daemon this IDE renders).

## What's actually done, verified, and committed (commit `5e63c34`)

1. **The drift daemon, headless** (`sembl_stack/drift.py` + `drift-check`/`drift-review`
   CLI commands, committed earlier in `55e6b4b`) — wraps the existing, unchanged
   `reconcile_spec_code` with a persisted state file (`.sembl/drift-state.json`) so
   repeated checks only surface genuinely new findings. Live-proven against
   `examples/flagship-feedback-board`'s real CBM index: 5 genuine findings, correct
   dedup on re-check, correct quieting after `--ack`.

2. **A real, running Theia 1.73.1 app** under `ide/`:
   - `ide/drift-view/` — the extension. `src/common/drift-protocol.ts` (the
     `DriftService` RPC contract), `src/node/` (backend: reads
     `<repoPath>/.sembl/drift-state.json` off disk, serves it over JSON-RPC at
     `/services/sembl-drift`), `src/browser/` (a `ReactWidget` in the right sidebar
     with a repo-path input + "load" button + findings list).
   - `ide/browser-app/` — the Theia application shell that depends on the extension
     plus `@theia/core`/`filesystem`/`navigator`/`workspace`/`preferences`.
   - Both build clean (`npm run build --workspace=drift-view` → `tsc -b`, 0 errors;
     `npm run build --workspace=browser-app` → `theia build --mode development`,
     0 errors on both browser and node bundles).
   - **Verified live**, not just compiled: started via `preview_start` (config
     `sembl-theia-ide` now in this repo's own `.claude/launch.json`, port 3000),
     confirmed the app boots to Theia's `ready` state, the command palette's
     "View: Toggle Drift" command opens the panel, and — after regenerating the
     flagship's `.sembl/drift-state.json` via a real `drift-check --live` run —
     the panel rendered the same 5 real findings, confirmed by reading the
     widget's actual rendered DOM text (not just a screenshot).

3. **A real bug found and fixed in the process**, worth knowing if a future widget
   in this repo renders blank with no visible error: `drift-view/package.json` pinned
   `"react": "^18.2.0"`, which the workspace's hoisted `react@19.2.7` (pulled in via
   `@theia/core`'s own `"^18.3.1 || ^19.0.0"` range) doesn't satisfy — npm silently
   installed a second, incompatible React copy nested in `drift-view/node_modules`.
   Two React instances in one page means React's own root rejects elements built by
   the "wrong" instance: the build succeeds, the app boots, the widget's sidebar icon
   and tab appear, but the panel body stays empty, with only a swallowed
   `An error occurred in the <Root> component` warning in the backend log (easy to
   miss — it doesn't look like it's about your widget). If this happens again:
   `find ide -maxdepth 3 -type d -name react` to check for a duplicate first, before
   assuming a logic bug. Fixed here by widening the range to match `@theia/core`'s and
   doing a clean reinstall (`rm -rf node_modules */node_modules package-lock.json &&
   npm install`) — a stale lockfile kept re-resolving the broken version even after
   the `package.json` range was widened, so deleting the lockfile was necessary too.

## What's explicitly NOT done yet (don't assume otherwise)

Per `SPEC-theia-factory-ide.md` §5, in build order:

- **Graph visualization** in the drift panel (currently a flat findings list, no
  graph/canvas at all).
- **The three tri-state resolution commands** — `update spec` / `update code` /
  `mark exception` (`PROCESS-ACTION-PLAN.md` Track 5 item 4). `mark exception` is
  where `manage_adr` actually belongs (see the correction noted in item 3 — `manage_adr`
  is a single whole-project doc, not an append-only log, don't re-assume the old
  wrong model).
- Top pipeline strip (swappable per-layer adapters), left activity bar/file explorer
  wiring beyond Theia's stock navigator, persona split (technical/non-technical),
  the discuss panel (open-ended chat, bounded artifact output), bottom run-history
  ribbon. All deliberately deferred until the drift-panel slice above is validated by
  actual daily use — building chrome before the underlying signal is proven was the
  failure mode that killed three prior surface attempts (TUI → chat shell → dashboard),
  see `SPEC-theia-factory-ide.md` §1/§8 for that history if useful context.

## How to run it in this session

```
npm run build --workspace=drift-view   # from ide/, if you change the extension
npm run build --workspace=browser-app  # from ide/, if you change the app or extension
```

Then use `preview_start` with config name `sembl-theia-ide` (already defined in this
repo's `.claude/launch.json`, port 3000) — do not use Bash to run the server, per the
mandated preview-tool workflow for anything browser-observable.

The panel defaults to pointing at
`C:/Users/totla/Desktop/projects/sembl-stack/examples/flagship-feedback-board` — that
repo's `.sembl/drift-state.json` is gitignored and may not exist locally; regenerate it
with:

```
.venv/Scripts/python.exe -m sembl_stack.cli specgraph \
  --task examples/flagship-feedback-board/task.yaml \
  --repo examples/flagship-feedback-board \
  --spec examples/flagship-feedback-board/specs/001-feedback-board \
  --out <scratch>/fg-spec.json

cd examples/flagship-feedback-board && \
  ../../.venv/Scripts/python.exe -m sembl_stack.cli drift-check \
  --specgraph <scratch>/fg-spec.json --live --repo .
```

(This needs `codebase-memory-mcp` installed and the flagship indexed — it was, as of
this session; if `--live` comes back empty, index it first via the CBM CLI/MCP tools.)

To open the panel in a fresh Theia session: press F1 (or dispatch the keydown via
`preview_eval` if a real keypress doesn't register), type `>Drift`, select
"View: Toggle Drift", then click "load" in the panel (or click the drift icon —
`.fa-code-fork` — in the right activity bar once the widget has been opened at least
once).

## Guardrails (don't violate these — see SPEC §7 for the full list)

- **O1**: every new piece here is a thin renderer over existing headless functions
  (`reconciliation.py`, `drift.py`). No new core/gate logic belongs in the Theia
  extension — if you're tempted to add real logic to `drift-service-impl.ts` beyond
  "read the state file," stop and put it in `sembl_stack/` instead.
- **O3**: nothing here judges code quality. The eventual discuss panel's LLM touch
  points (parse intent → bounded artifact) must stay process/context-side, never a
  quality judgment, never inside L5/L8.
- **O8**: bounded-LLM-into-fixed-schema is the only sanctioned LLM-in-the-loop pattern
  when the discuss panel gets built — fixed schema, human confirms, never touches the
  gate directly.
