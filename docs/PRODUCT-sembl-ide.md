# PRODUCT — the sembl IDE (locked 2026-07-08)

This is the product definition for sembl's surface. It supersedes the Theia
surface bet in SPEC-theia-factory-ide.md (the *surfaces* proven there carry
over; the *shell* is retired). Change this doc only by diffing it with the
owner, same rule as the ledger.

## One-liner

**The IDE for spec-anchored development.** You state intent and bounds; a
swappable executor does the work; a deterministic gate judges it; the IDE
makes that loop visible, steerable, and effortless. We never compete on
editing — the editor is bone-stock VS Code, which is the point.

## Why the shell changes (post-mortem, one paragraph)

Three surfaces have now under-delivered the same way: the Textual TUI, the
chat shell, and the Theia slice. In every case the *engine signal* was fine
and the *shell* was the pain: Theia's stock chrome (explorer, rails, tabs,
splash, settings) is ~90% of visible pixels and reads as 2015 no matter how
good our four panels look. Cursor's lesson is exact: they forked the shell
people already love and inserted their value at the seams. That is the last
un-made decision, and it's now made: **VS Code OSS fork** (Cursor's path).

## The golden path (the only flow that matters — everything is ≤2 clicks off it)

1. **Open the app** (one click, cold start < 5s). The top of the window is
   the **factory strip**: the L0→L8 pipeline as a progress bar, always
   visible. Idle: pipeline + last verdict. Running: stages light live. This
   strip is the product's face.
2. **Every stage chip is a picker.** Click `execute` → choose
   claude / codex / opencode / aider / mock. Click `sandbox` → clone /
   worktree. Click `verify` → sembl. Swappability is a first-class UI verb —
   the picker writes `sembl.stack.yaml` through the engine (O1 intact),
   never a yaml file in the user's face.
3. **New work starts as a spec conversation** (discuss, O8): plain English →
   bounded proposal (task + editable + forbidden + questions) → human edits →
   confirm. `task.yaml`/`bounds.json` exist but the golden path never shows
   them raw.
4. **Run** (button on the strip): stages light, executor output streams,
   the verdict lands. PASS → merge action. BLOCK → re-run / revise bounds;
   applying a BLOCK is not a disabled button, it is *absent* (BLOCK-means-
   blocked made visually obvious).
5. **Stay anchored over time**: drift panel (tri-state resolution) and the
   spec graph keep spec ↔ code honest; the guide (O9, Haiku, read-only)
   explains any verdict/finding on demand.

Editing code at any point: it's VS Code. We add nothing and break nothing.

## Delight bar (acceptance criteria for every future surface PR)

- Golden-path actions reachable in ≤ 2 clicks from launch.
- Zero raw yaml/json in the golden path (power users can always open them).
- Nothing stock-ugly visible in the golden path (stage-managed default
  layout; anything we didn't style is hidden by default, not restyled).
- Cold open → usable < 5 seconds.
- Every LLM touchpoint shows *which* executor/model it used and lets you
  swap it in place.

## Non-goals (locked)

- No chat-driven code editing, no tab-completion, no "AI writes code better"
  anything (O3 — falsified claim; Cursor/Copilot own that lane).
- No custom editor features. No dashboard sprawl (the dashboard trap has
  killed a surface once already).
- No multi-user / cloud / marketplace until owner-dogfooding says so (S4).
- The gate stays model-free and un-overridable from any surface (BLOCK-
  means-blocked; overrides arrive engine-side first or not at all).

## Build order (anti-trap: each phase is daily-usable before the next starts)

- **P1 — the sembl extension, in stock VS Code (days, not weeks).** Port the
  five proven surfaces (factory home w/ strip header, discuss, guide, drift,
  spec graph) from the Theia widgets to VS Code webview views — same React,
  same SEMBL tokens, same thin-renderer services spawning the same CLIs.
  Executor pickers as VS Code quick-picks writing config through the engine.
  Status-bar verdict chip. Usable immediately inside VS Code *and Cursor*.
  Limitation accepted: the strip lives at the top of the home tab + status
  bar, not the window title — that's what P2 buys.
- **P2 — fork VS Code OSS** (only after P1 is the daily driver): ship the
  extension built-in, patch the workbench for the *real* always-visible top
  strip, brand it, default layout stage-managed, one-click launcher. Minimal
  patch set, tracked against upstream like Cursor/VSCodium do.
- **P3 — distribution** (after dogfooding): MCP server so sembl verdicts and
  discuss flow inside Claude Code sessions; publish the extension for
  non-fork users. Not before.

## What carries over / what dies

- **Carries 100%**: the engine, every headless CLI (`loop`, `discuss`,
  `discuss-confirm`, `explain`, `drift-review`, `drift-resolve`), all tests,
  the run store, the design tokens, O1/O3/O8/O9 and every ledger lock.
- **Ports (~70%)**: the React widget internals (transcripts, proposal cards,
  strip rendering, graph view) — webview-hosted instead of Theia-hosted.
- **Dies**: Theia glue (contributions, inversify modules, the boot-hang
  patch, the vendored windows-ca-certs workaround). `ide/` stays in-tree as
  reference until P1 reaches parity, then is archived.
