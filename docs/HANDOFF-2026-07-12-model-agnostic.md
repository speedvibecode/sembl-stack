# HANDOFF 2026-07-12 — model-agnostic continuation

Written by the lead session on the owner's instruction: Fable access is ending;
this repo must keep improving under ANY lead model (codex, GPT, Gemini, Sonnet).
Read `AGENTS.md` → `CLAUDE.md` first; this doc is the resume point after that.

## Verified state (re-verify against git log before trusting)

- master @ `7aa6a88`+ (SPEC approvals stamped after that commit). Suite:
  **508 passed / 3 skipped** (`.venv/Scripts/python -m pytest -q` from repo root).
- O11 COMPLETE: event bus (`sembl_stack/bus.py`), MCP server
  (`sembl_stack/operator_mcp.py`, exactly nine tools — locked, NOTHING else),
  operator REPL (`sembl_stack/operator_shell.py`, `sembl-stack operator`).
  Live-proven over the REAL stdio transport. One leg unverified: propose→confirm
  in a live claude conversation — blocked on the machine's claude CLI OAuth
  (expired 2026-07-05; owner must run `claude /login` once, then SPEC-O11 §8
  step 3 is ~5 min).
- SPEC-stage and SPEC-O14 are **APPROVED 2026-07-12** (owner: "proceed to
  build"); their §0 decisions are locked in the spec headers. Dispatch order:
  **stage first (WP-A → WP-B → WP-C), then O14 (WP-A → WP-B)**.

## How the owner uses it TODAY (no new build required)

```bash
# the factory, headless — real task, real gate, real verdicts
sembl-stack loop task.yaml        # plan → execute → gate → retry-on-BLOCK
cat .sembl/runs/<id>/verdict-*.json

# the operator (after `claude /login`, or via any MCP client)
sembl-stack operator --repo <repo>
sembl-stack operator --print-mcp-config   # plug sembl-stack-mcp into ANY MCP client
```

The engine is already model-agnostic: L3 executors are adapters (codex recipe
in CLAUDE.md; opencode works inside the loop but NOT as a single-shot delegate).

## Model-agnostic operation map

| Role | Today | If Claude access lapses |
|---|---|---|
| Lead (orchestrate/review) | Claude | Any strong model via AGENTS.md→CLAUDE.md; codex recipe in CLAUDE.md |
| Executor (build WPs) | Sonnet subagents | `codex exec` recipe (CLAUDE.md — stdin prompt + `mcp_servers={}` are load-bearing) |
| Loop L3 executor | adapter-configured | already swappable (adapter class) |
| Operator surface | `claude -p` REPL | `--print-mcp-config` output into any MCP client (codex, etc.). Small follow-on: generalize `operator_shell.resolve_claude()` to a configurable client command |

## Standing review discipline for whoever leads next

1. Never trust an executor self-check: read the full diff, run the suite
   yourself, live-proof the golden path from the spec.
2. MCP-surface changes MUST be proven over the REAL stdio transport from a
   foreign cwd (2026-07-11 deadlock class, fix `1fcbf46` — direct-call tests
   are structurally blind to transport breakage).
3. Fail-closed on unrecognizable input everywhere (O12's five-instance class).
4. Commit after independent verification without asking; NEVER deploy/publish/
   push outward without an explicit ask in-session.

## Next actions, in order

1. Dispatch SPEC-stage WPs to a cheap executor (spec is fully pinned; ≥6/≥8/≥5
   tests; DO-NOTs inline). Lead live-proof on `examples/flagship-feedback-board`
   per the spec's live-proof section.
2. Dispatch SPEC-O14 WPs (≥10/≥8 tests). Live-proof per spec.
3. Owner: `claude /login`, then walk SPEC-O11 §8 step 3 (check whether
   `claude -p` permission-prompts MCP tools; may need `--allowedTools`).
4. Only after stage+O14 are live-proven: the IDE surface (PRODUCT v2 roadmap;
   `vscode-ext/` holds the parked scaffold). Chrome never outruns signal.
