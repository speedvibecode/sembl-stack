# CLAUDE.md — sembl-stack session bootstrap

This file is the cold-start contract for ANY agent working in this repo (Claude,
codex, or anything else — see AGENTS.md). Read it fully, then follow the read
order below before non-trivial work. It encodes the owner's working flows so a
fresh session produces the same quality as the sessions that built this.

## What this is

Two sibling repos, one product. `../sembl` is the **gate**: deterministic
verification of a diff against declared bounds (scope / forbidden / fabrication /
evidence / churn), no model in the judgment loop. This repo (`sembl-stack`) is the
**factory** around it: task → bounds → execute → sandbox → gate → merge → deploy →
verify-in-prod (L0–L8), every stage a swappable adapter behind one typed artifact
contract, every run recorded in `.sembl/runs/<id>/`. We sell **process
correctness** — never "the model writes better code" (that claim is falsified;
do not rebuild or re-test it).

## Read order (before any non-trivial change)

1. `docs/PRODUCT-sembl-ide.md` (v2, 2026-07-09) — **the product contract**: what
   sembl IDE is (conversation/truth/stage, preview-as-evidence, seats table,
   target profiles incl. smart contracts), the delight bar, non-goals, and the
   value-ranked roadmap. Every build step executes against this doc.
2. `docs/PROCESS-ACTION-PLAN.md` — architecture, stage map + status, the
   locked-decision ledger (O1–O15, S1–S13), the action plan.
3. Theia docs (`SPEC-theia-factory-ide.md`, `HANDOFF-theia-ide.md`) are
   **historical reference only** — the Theia slice is retired (O10); do not
   build on it. `vscode-ext/` holds the parked P1 extension scaffold.

Status lines in docs go stale. **Re-verify against the repo and git log before
trusting any "done" claim.**

## Non-negotiable guardrails (locked; change only by diffing the plan doc)

- **O1** — the engine is a headless lib; every surface (CLI, guide, IDE) is a
  thin renderer over existing functions in `sembl_stack/`. No core or gate logic
  in a surface. If a Theia service does more than read state off disk, stop.
- **O3** — nothing judges code quality as the headline. Quality is measured only
  as gate-caught regressions. LLM touch points never sit inside L5/L8.
- **O8 / O9 / O11** — exactly three LLM patterns exist, ever: O8
  bounded-LLM-into-fixed-schema (ai_suggest_paths, discuss parse, L0.5
  ideation), O9 the read-only factory guide, O11 the operator agent (free
  conversation, commits ONLY through typed engine tools, owns zero judgment).
  None touches the gate. Do not add a fourth silently.
- **Anti-trap build order** — prove signal headless on the one flagship before
  building chrome. Three shells died (Textual TUI → chat shell → Theia).
  The PRODUCT doc's roadmap order is not optional; chrome never outruns signal.
- **BLOCK means blocked** — a BLOCK verdict is never applied or merged; overrides
  are recorded permanently. Verdicts are bound to the diff SHA they judged.

## Operating standard (owner directives — these are load-bearing)

- **Work as if 10,000 users depend on every change.** Green tests + a clean
  review ≠ working. Nothing is "done" until the actual user-facing flow has been
  walked end-to-end and the rough edges a real user hits are gone. Be
  adversarial about your own "fixed" claims; when one thing breaks, assume
  adjacent things are broken too.
- **Build for the owner first.** This is his personal power tool; optimize for
  depth and his daily workflow, never gate a feature on hypothetical external
  users or adoption metrics. Public launch is archived, revisited after
  dogfooding — not on a date.
- **UI work:** never use generic/boring-UI rulesets (uncodixfy was explicitly
  rejected). Pull concrete DESIGN.md token references from
  `VoltAgent/awesome-design-md` (Linear / Warp / Raycast for dense dev tools);
  single chromatic accent = the existing sembl cyan `#7cd4df`.
- Verify browser-observable work with the `preview_*` tool workflow (config
  `sembl-theia-ide` in `.claude/launch.json`), reading rendered DOM/logs — never
  "it compiled" and never a screenshot alone.

## The delegation method (how big work gets built here)

Lead agent = **orchestration + review only**: pin a precise `docs/SPEC-*.md`
(all judgment calls resolved, exact acceptance criteria and test counts) → a
cheap CLI executes it → lead **reviews the diff and independently re-verifies**
(never trust the executor's self-check) → commit. Keep every delegation spec
pinned enough that the delegated session is execution-only — this is what lets
weaker/cheaper models still produce high-quality work here.

codex recipe (two load-bearing gotchas):
`codex exec --cd <repo> -s workspace-write -c 'mcp_servers={}'
-c model_reasoning_effort="medium" - < prompt.md`
(1) MCP must be disabled per-invocation — the CBM server wedges codex;
(2) the prompt MUST come on stdin via `-` — an argv prompt wedges it forever.

## How to run things

```bash
# tests — from the repo root (corpus paths are cwd-relative)
.venv/Scripts/python -m pytest -q

# the loop, headless
sembl-stack loop task.yaml    # plan → execute → gate → retry-on-BLOCK

# the Theia IDE slice (from ide/)
npm run build --workspace=drift-view && npm run build --workspace=browser-app
# then preview_start config "sembl-theia-ide" (port 3000) — never Bash for servers
```

Regenerating flagship drift data (gitignored, often missing): see
`docs/HANDOFF-theia-ide.md` "How to run it in this session" — needs
codebase-memory-mcp with `examples/flagship-feedback-board` indexed.

Run `/murphyscan` as the standing pre-release/pre-deploy audit (S12).

## Known traps (each of these cost real hours)

- **Theia app hangs on the splash forever, zero errors anywhere:** Theia 1.73.1's
  `@theia/ai-core` (forced in via plugin-ext) ships `SkillPromptCoordinator`, whose
  `onStart` awaits `workspaceService.ready` — unresolved on a no-workspace boot —
  and Theia awaits all onStarts BEFORE attaching the shell. Patched fire-and-forget
  in `ide/factory-view/src/browser/factory-view-frontend-module.ts`; re-check on any
  Theia upgrade. Diagnose this class of hang via `window.theia.container` (grab
  `FrontendApplicationStateService.state`) + `performance.getEntriesByType('mark')`
  — the contribution with a start mark and no measure is the one that's wedged.
- **Theia widget renders blank, no error:** duplicate React. Check
  `find ide -maxdepth 3 -type d -name react` for a second copy before assuming a
  logic bug; extension React ranges must match `@theia/core`'s
  (`^18.3.1 || ^19.0.0`), and a stale lockfile re-pins the bad resolution —
  delete it and clean-reinstall.
- **The sites (`sembl-site`, `sembl-stack-site`) do NOT auto-deploy on git
  push.** Deploy manually with `vercel --prod --yes` from the site repo, then
  curl the production URL before claiming live. Git author must be speedvibecode.
- `vercel` on Windows resolves to a `.cmd` shim; bare `subprocess.run(["vercel"])`
  raises FileNotFoundError (already handled in `adapters/deploy_vercel.py` —
  don't regress it).
- **`theia build` fails while the app is running** — Windows locks
  `lib/backend/native/*.node`; stop the preview server before rebuilding
  `browser-app`, then restart it.
- **`@vscode/windows-ca-certs` cannot npm-install here** (node-gyp MSB8040:
  Spectre-mitigated libs missing) but Theia's backend bundler hard-requires it
  on win32. A prebuilt copy is vendored at `ide/vendor/windows-ca-certs/` and
  auto-restored into node_modules by `ide/scripts/install-windows-ca-certs.js`
  (postinstall). If a clean install ever fails on this module again, run
  `npm run postinstall` in `ide/`.
- opencode/MiniMax works as an L3 executor inside the loop but stalls on
  single-shot delegated builds — don't use it as a delegate.
- `eval/.fg-*`, `eval/.suite-*`, `eval/.checkpoint-*` are local scratch from
  live runs — never commit them.

## Systems thinking (owner directive, 2026-07-09 — applies to everything here)

Supremely valued at every scale, smallest fix to biggest design: every change
is an intervention in a system — name the whole before touching the part; fix
the class, not the instance; prefer structural leverage (contracts, invariants,
defaults) over patching call sites; build feedback loops so the system reports
its own state; when one part breaks, assume its siblings are broken too. Full
operational version: `~/.claude/CLAUDE.md`.
