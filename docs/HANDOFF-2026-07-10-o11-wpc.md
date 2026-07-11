# HANDOFF — resume O11 at WP-C (written 2026-07-10, Fable lead session)

> **Who this is for:** the next lead session (any model — Opus/Sonnet grade assumed).
> Follow `CLAUDE.md`'s read order first. This doc adds only what a fresh session
> cannot derive: exact position, the next dispatch, and session-specific traps.
> Re-verify every "done" claim below against `git log` before trusting it.

## Exact position (verify: `git log --oneline -12`)

- **O12 behavioral acceptance: COMPLETE.** Four WPs, all live-proven
  (`5d6066a` in ../sembl; `b1f444b`, `2a6dfc2`, `8560bf9` here). Spec status
  stamped in `625d444`.
- **O11 operator agent + event bus: 2 of 3 WPs landed.**
  - WP-A the bus — `e6a6a26`. `.sembl/bus.jsonl`, publish points at the five
    choke points, live-proven on a real loop run (both engine paths).
  - WP-B the MCP server — `4ded5d4`. `sembl_stack/operator_mcp.py`, exactly
    nine tools, boundary locks as tests. Suite: **496 passed, 3 skipped**
    (the 3 skips = forge not on PATH; expected).
  - **WP-C the operator REPL — NOT built. This is the next action.**
- Design: IDE shell mockup v2 (codex-simple, owner-corrected) at
  `docs/design/ide-shell-mockup.html` (`bf96926`). v1's dense register was
  rejected — see the design memory before ANY UI work.
- `vscode-ext/` is a parked P1 scaffold — untracked on purpose. Leave it.

## Next action: dispatch WP-C, then live-proof the golden path

WP-C is fully pinned in `docs/SPEC-O11-operator-agent-event-bus.md` §5 + §7
(read them; do not re-derive). Dispatch it execution-only to a Sonnet agent:
`cli.py` gets an `operator` command + a small `operator_shell.py` (~100 lines,
deliberately disposable), which

- writes a temp MCP config json pointing at
  `sys.executable -m sembl_stack.operator_mcp` (NOT the console script — PATH
  independence; the `sembl-stack-mcp` script only materializes after
  `pip install -e .`),
- launches `claude -p` with `--mcp-config` + per-turn session continuation,
- prefixes each human turn with `[factory events since last turn]` from
  `bus.read_since(cursor)` (in-memory cursor),
- `--print-mcp-config` prints the json and exits 0 (D4's any-client claim),
- claude-missing-from-PATH → actionable message, rc≠0, no traceback,
- tests ≥4 per §7 WP-C. DO-NOTs: no output parsing, no polish, no per-user
  state beyond the cursor.

Then the LEAD (you) runs SPEC §8 personally — never delegate this:
propose → confirm → run_loop on a task that BLOCKs → verdict event surfaces
in the next turn's event block → agent explains from the verdict → a PASSing
task → `--print-mcp-config` into a bare `claude` session (any-client proof).
Walk the empty state (no events ⇒ no block) and the claude-missing error path.
Commit with review fixes + limitations recorded, per the standing method.

## After O11: pin, don't build

Remaining highest-leverage work is SPEC-writing (bank judgment while the best
available model is in the lead seat):
1. **SPEC-stage** — roadmap #3, preview-as-evidence for the web profile
   (PRODUCT §stage). Judgment-dense; do a short product-thinking pass with the
   owner before pinning.
2. **SPEC-O14** — manual-edit adoption daemon (in-bounds auto-adopt with veto;
   bound-crossing always asks).
3. Recorded follow-on: sandbox prepare/install step so dep-needing acceptance
   checks run inside the L4 clone (O12 limitation, noted in `8560bf9`).

## Session-specific traps (beyond CLAUDE.md's list)

- `mcp` IS installed in this venv; `langgraph` IS importable and functional
  (the loop runs `engine: langgraph`) — older notes claiming otherwise are stale.
- forge 1.7.1 lives at `C:\Users\totla\tools\foundry\` (NOT on machine PATH —
  prepend per-process). The `foundry_stable_*` release URL 404s; use the
  versioned `foundry_v*_win32_amd64.zip` asset.
- The O12 live-proof scratch repo lived in the previous session's scratchpad —
  it is GONE for you. Recreate in your scratchpad via
  `sembl-stack init --preset gate+sandbox` (see
  `tests/test_operator_mcp.py::_scaffold_repo` for the exact working recipe).
- Executor sessions die silently when the host process exits: after any agent
  goes quiet, check `git status` — the work is usually on disk. Review it
  yourself as if the self-report never existed (WP-B landed exactly this way).
- Suite baseline: 496 passed, 3 skipped. Runtime ~2.5 min. Always run from repo root.

## The honest state of the product (for the owner's doubts — keep this frame)

What exists and is live-proven, end to end, today: a deterministic gate with
four axes (scope/forbidden/fabrication + behavioral); a factory loop (L0–L8,
every stage swappable) that real executors drive; behavioral acceptance with
real teeth on two profiles (a Next.js app's rendered DOM, a Solidity
invariant under fuzzing); an event bus any process can subscribe to; a typed
MCP tool surface any agent can operate through. 496 tests. Every claim above
was re-verified by a second party (the lead) against the running system, not
taken from reports. What does NOT exist yet: the conversation surface (WP-C,
~100 lines) and all chrome (deliberately last, per the three dead shells).
The distance from "here" to "talk to the factory in one window" is one small
work package plus one live proof.
