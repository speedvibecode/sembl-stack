# DESIGN — Sembl Factory IDE (locked design system + full target surface map)

Locked 2026-07-07 by the owner. The interactive reference is
`docs/design/sembl-ide-design-reference.html` (open in a browser; it has five
preview modes: idle / live / block / drift / component sheet). **Build to this
baseline — do not redesign it.** This doc extracts the reference into exact,
executable values so any agent can implement UI without judgment calls, and
pins the full target surface map (including the pieces the reference doesn't
yet show: graph view, discuss panel, factory guide).

## 1. Tokens (exact values from the reference)

Fonts — `IBM Plex Sans` (chrome labels, buttons) and `IBM Plex Mono`
(ALL data: run ids, verdicts, paths, stage labels, log lines, code).
Load via Google Fonts; weights 400/500/600.

Surfaces (dark only for now):

| token | hex | used for |
|---|---|---|
| page | `#0b0d10` | page behind the app frame |
| editor | `#0d1114` | editor bg, app frame bg |
| panel | `#101418` | file tree, bottom panel, tab bars |
| strip | `#0f1317` | factory strip bg |
| card | `#12171b` | drift panel bg, finding cards |

Borders: `1px solid rgba(255,255,255,0.07)` default, `0.08` for panel
separators. Text tiers (white alpha): `0.85` primary data · `0.72` chrome
title · `0.6`/`0.55` secondary · `0.4`–`0.45` muted · `0.28`–`0.35` disabled/
pending · `0.22` line numbers.

Chromatic colors — exactly four, each with one meaning:

| name | hex | meaning — and nothing else |
|---|---|---|
| CYAN | `#7cd4df` | "the factory is alive": active stage, selected tab underline, in-progress tick ring, primary re-run button, selection bg `rgba(124,212,223,0.25)` |
| GREEN | `#7fae86` | PASS only |
| AMBER | `#c9a15a` | WARN + drift findings only |
| RED | `#c1685c` | BLOCK / error / out-of-bounds only |

Chips/tints use the pattern `bg rgba(C,0.12–0.14)` + `border rgba(C,0.3–0.4)`
+ text at full color. Sanctioned animations (the only three):
`pulse-ring` 1.4s (active stage dot), `soft-pulse` 1.6s (error dot, drift dot,
in-progress tick), `blink` 1.1s (terminal cursor). Nothing else moves; no
gradients, no glow beyond pulse-ring's expanding shadow.

## 2. Components (from the component sheet)

- **Factory strip** — 32px tall, strip bg, bottom hairline. Left: 9px
  rounded-2px mark square (cyan when a run is live, else `rgba(255,255,255,0.3)`)
  + `SEMBL FACTORY` mono 11px/600 letter-spacing 0.06em. Center: 8 stage dots
  (context · spec · execute · sandbox · gate · merge · deploy · verify), 6px
  circles, 20px×1px connectors; states: pending `rgba(255,255,255,0.16)`,
  done `rgba(124,212,223,0.55)`, active cyan + pulse-ring, error red +
  soft-pulse; labels mono 10px colored to match. Right: drift dot + text
  (`drift: quiet` muted / `drift: N findings` amber + soft-pulse) and the gate
  chip. Whole strip at `opacity:0.82` when idle, `1` during runs (0.3s ease).
- **Gate verdict chip** — mono 10px/600, padding 3px 9px, radius 4px, tinted
  per verdict (neutral `—`, `running`, `PASS`, `WARN`, `BLOCK`).
- **Run ticks** — 6×16px, radius 1px, gap 3px; pass green(0.65) / warn amber /
  block red; selected = 1.5px white(0.65) border; in-progress = transparent
  fill + 1.5px cyan border + soft-pulse.
- **Drift finding card** — card bg, hairline border, radius 6px, padding 12px:
  5px amber dot + mono 10px uppercase path, 12px summary at white(0.75), then
  three buttons: `update spec` / `update code` (hairline, hover cyan) and
  `mark exception` (dimmer — a deliberate act, not the default).
- **Heavy override control** (BLOCK panel only) — primary `re-run` (cyan bg,
  dark text) + secondary `revise bounds` (outline); far right, a checkbox
  "i accept responsibility for this bound violation" gating a disabled
  uppercase red-outline button `override — apply anyway`. The override is
  bureaucratic on purpose; never make it friendlier. BLOCK means blocked.
- **Editor diff badge** — `+13 / −0 · out of bounds` mono 10px red tint next
  to the filename when the open file's diff violated bounds.
- **File tree annotations** — active file: cyan 2px left border + cyan(0.08)
  bg; drift-flagged files: trailing ` ·`; bound-violating file: red name.

## 3. Full target surface map (what "every layer covered" means)

| surface | shell location | data source (O1: read-only renderers) | status 2026-07-07 |
|---|---|---|---|
| Factory strip | top area, below menu | `sembl.stack.yaml` + latest `.sembl/runs/*` + drift state | to build (restyle of existing data plumbing) |
| Factory panel (ribbon + run detail + BLOCK actions) | bottom, tabbed with terminal | `.sembl/runs/` | built plain; restyle + BLOCK actions to add |
| Live-run stage lighting | strip + panel | run store watched during a run | to build |
| Drift panel + tri-state actions | right | `.sembl/drift-state.json`; actions call the headless CLI (Track 5 item 4 — headless first) | panel built plain; tri-state pending headless |
| Graph view (spec↔code) | center tab (code stays default) | SpecGraph JSON + CBM code graph; render with an off-the-shelf lib (reactflow/cytoscape — do not hand-roll) | to build |
| Discuss panel (spec finalization) | right, sibling of drift | O8: free conversation → bounded artifact (Task+Bounds / spec note), human confirms | to build |
| Factory guide | strip-right entry + collapsible panel | O9 (see ledger): cheap model, read-only over run store/config/verdicts/docs | to build |
| MurphyScan / readiness | left sidebar destination | murphyscan output | deferred |

The center is always a real editor first — the factory is the frame, never
the content (the dashboard trap killed three prior surfaces).

## 4. The two new locked decisions this design implies

- **O9 — the factory guide** (second sanctioned LLM pattern, distinct from
  O8): a cheap (Haiku-class) model whose entire job is helping the human
  *operate* sembl — explain a verdict, suggest which resolution fits a drift
  finding, narrate where a run is stuck. It is **read-only**: it may read run
  store / config / drift state / docs; it writes no artifacts, executes
  nothing, and never sits in L5/L8. If it wants to *do* something, it hands
  the human a suggestion that routes through an existing surface (an O8 flow
  or a button). Executor AIs and the guide never share a context.
- **S13 — executor swappability tiers**: the L3 contract stays
  artifact-in/diff-out; CLI agents (claude, codex, opencode, aider) are one
  adapter *class*, not the definition. Planned second class: SDK-based
  adapters (Claude Agent SDK first) — structured events for live-run
  rendering, in-flight bounds enforcement via permission hooks (efficiency
  only — the post-hoc deterministic gate remains the judgment), token/cost
  telemetry into the run record. ACP (agent-client protocol) is a candidate
  third class. Swapping stays a config-level act (edit `sembl.stack.yaml`);
  the strip renders it, it does not hot-swap mid-run.

## 5. Build order (supersedes nothing — extends SPEC-theia §5 step 4)

1. Design tokens into the IDE: IBM Plex + palette as CSS, restyle factory
   panel + drift panel to §2, add the factory strip (static states first).
2. Live-run: stage lighting + in-progress tick fed by watching the run store
   during a `loop` run.
3. BLOCK actions in the factory panel (re-run / revise bounds / heavy
   override — override records permanently, per the existing rule).
4. Tri-state drift resolution — headless CLI first (Track 5 item 4), then the
   three buttons.
5. Graph view (center tab, reactflow/cytoscape over SpecGraph+CBM).
6. Discuss panel (O8) and factory guide (O9).

Each step lands only after being live-verified in the running IDE (preview
tools, rendered DOM — never "it compiled").
