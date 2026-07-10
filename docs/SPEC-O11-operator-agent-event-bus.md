# SPEC — O11 Operator Agent + Event Bus (the conversation as primary interface)

> **Status:** APPROVED by owner 2026-07-10; execution dispatched (WP-A → WP-B → WP-C,
> sequenced to avoid same-tree contention on loop.py/cli.py). Re-verify against
> git log before trusting this line.
> **Ledger:** implements O11 (`PROCESS-ACTION-PLAN.md` §5, LOCKED 2026-07-09) + PRODUCT
> §"Conversation" region. Roadmap item #2 (after O12). Stays within O1/O3/O8/O9;
> O11 is the third and FINAL sanctioned LLM pattern — this build adds no fourth.
> **Repo:** `sembl-stack` only. The gate (`../sembl`) is not touched.
> **Depends on:** nothing in O12's WPs (parallel-safe); the bus will carry O12's
> acceptance events once both land, but neither blocks the other.

---

## 0. Owner decisions locked for this build (recorded 2026-07-10)

- **D4 — Engine as MCP server.** The operator "harness" is not a thing we build:
  sembl-stack grows an MCP server (`sembl-stack-mcp`) exposing the typed engine
  tools, and ANY MCP-speaking agent (claude CLI, opencode, later the IDE panel)
  becomes an operator by connecting. One tool surface; every harness swappable by
  definition — satisfying the ledger's "any model" structurally. Mirrors how
  `../sembl` already ships `sembl-mcp` (FastMCP over stdio, `mcp>=1.2.0` extra,
  tool bodies as plain testable functions).
- **D5 — Repo-level JSONL bus.** One append-only `.sembl/bus.jsonl`; engine stages
  publish typed events; any subscriber (operator wrapper, IDE extension, `tail -f`)
  reads from a cursor. File-based because it must cross process boundaries (the
  VS Code extension is a separate process from the Python engine) and survive
  crashes. Generalizes the existing per-run `events.jsonl` pattern (store.py).
- **D6 — All five tool families in the first slice**, each a THIN wrapper over an
  existing engine function (O1: the engine already has them all). No new engine
  capability in this build — only the surface, the bus, and the discipline.

## 1. What it is

**One line:** the platform's primary interface becomes a free-flowing agent
conversation whose only hands are the typed engine tools — it may propose
anything, can commit only through those tools, owns zero judgment, and the
system talks back into it (verdicts/drift/deploys) via the event bus.

**Golden path (headless, the proof):**
```
sembl-stack operator
  → human: "add rate limiting to the feedback API"
  → agent calls propose_task (O8 fixed schema) → human approves in conversation
  → agent calls confirm_task → task.yaml + bounds.json materialized
  → agent calls run_loop → plan → execute → acceptance → gate
  → verdict event lands on the bus → surfaces in the conversation next turn
  → BLOCK? agent explains the reasons (read from the verdict, never re-judged)
    and proposes the fix path; PASS? agent reports the run id + what merged
```

**Non-goals (locked):**
- **Zero judgment.** The operator never grades code (O3), never decides a verdict,
  never overrides the gate. It reads verdicts and explains them; the explaining
  voice may be wrong, the verdict cannot be.
- **No free-form hands.** The MCP server exposes NO shell tool, NO file-write
  tool, NO apply/merge-anything tool. The five typed families are the entire
  surface. A change reaches the repo only via `run_loop`'s gated pipeline.
- **BLOCK means blocked, here too.** No tool applies or merges a BLOCKed change;
  there is no override tool.
- **No new LLM pattern.** The operator IS pattern three. `propose_task` reuses O8
  verbatim (discuss.py); the guide (O9) stays as-is; nothing else calls a model.
- **Not a UI.** The headless wrapper (§5) is the proof surface, ~a REPL; the IDE
  conversation panel is a later roadmap item that connects to the SAME server.

## 2. The event bus (`sembl_stack/bus.py`) — D5

### 2.1 API (pin exactly; WP-B codes against this without waiting for WP-A)

```python
BUS_PATH = ".sembl/bus.jsonl"   # repo-relative, like .sembl/runs/

def publish(root: Path, event: dict) -> None:
    """Append one event line. NEVER raises (mirror store.append_event):
    a bus write failure can never affect the loop or the gate.
    Injects ts (time.time()) and validates `kind` is a known kind; an
    unknown kind is written with kind="other" + the original under raw_kind."""

def read_since(root: Path, cursor: int = 0) -> tuple[list[dict], int]:
    """Read events after byte-offset `cursor`; returns (events, new_cursor).
    Tolerates a torn/corrupt trailing line (skip it, don't advance past it).
    Missing file ⇒ ([], 0). Never raises."""
```

### 2.2 Event schema (one JSON object per line)

| field | type | meaning |
|---|---|---|
| `ts` | float | epoch seconds (injected by publish) |
| `kind` | str | see kinds table |
| `run_id` | str \| absent | present for every run-scoped event |
| `summary` | str | ONE human-readable line (what the conversation shows) |
| `data` | dict | kind-specific payload (verdict reasons, drift keys, url…) |

Kinds (closed set for this build): `run.started`, `run.stage` (data: stage,
status, attempt — mirrors events.jsonl lines), `run.verdict` (data: status,
reasons), `run.finished` (data: status), `drift.new` (data: keys, count),
`deploy.status`, `postdeploy.status`, `other`.

### 2.3 Publish points (all wired in WP-A; each is ≤3 lines at the call site)

- `store.Run.append_event` additionally mirrors to the bus as `run.stage` with
  the run id (single choke point — every stage transition rides for free).
- The loop publishes `run.started`, `run.verdict` (from the bound Verdict), and
  `run.finished` (both LangGraph and fallback paths — they stay identical).
- `drift.check_drift` publishes `drift.new` when `new` is non-empty.
- `adapters/deploy_vercel.py` / `postdeploy_http.py` publish their status via the
  same choke points the run store already records them through.
- Publishing is fire-and-forget everywhere: no publish may sit on a hot path's
  error handling or change any existing return value.

## 3. The MCP tool surface (`sembl_stack/operator_mcp.py`) — D4, D6

Mirror `../sembl/sembl/mcp_server.py` structurally: **tool bodies are plain
functions** (unit-testable with no MCP transport), `main()` registers them on a
FastMCP stdio server. New optional dependency: `mcp>=1.2.0` under an `[mcp]`
extra in pyproject (match sembl's). Console script: `sembl-stack-mcp`.

Every tool returns JSON-serializable dicts built from artifact `to_dict()`s —
never free prose, never a model call inside the server.

### 3.1 The tools (the five locked families → nine tools; NOTHING else)

**read state** (read-only):
- `read_state(repo, run_id=None)` — no run_id: list runs (id, status, task line,
  verdict status) from `RunStore`; with run_id: the run's manifest + verdict
  (status, reasons) + last N events + which artifacts exist.
- `read_events(repo, cursor=0)` — `bus.read_since` passthrough (the pull half of
  "the system talks back"; the wrapper §5 is the push half).
- `read_config(repo)` — current `sembl.stack.yaml` layers + available registry
  adapters per layer (so "swap X to Y" can be proposed accurately).

**run loop** (mutating, THE commitment path):
- `run_loop(repo, task_file)` — invoke the existing loop entry (same function
  `cli.py loop` calls) with the existing config loading. Returns
  `{run_id, verdict: {status, reasons}, attempts}`. The gate inside the loop is
  untouched; a BLOCK returns as a BLOCK — the tool never retries beyond the
  loop's own `max_attempts`, never applies, never merges.

**create/refine spec** (O8 reuse, two-step propose→confirm):
- `propose_task(repo, text, executor=None)` — `discuss.propose_task` verbatim.
  Returns the fixed-schema proposal for the human to see IN the conversation.
- `confirm_task(repo, proposal)` — `discuss.sanitize_proposal` +
  `discuss.confirm_task`. Returns the task.yaml/bounds.json paths written.

**resolve drift**:
- `list_drift(repo)` — `drift.pending_drift_items` (keys + findings).
- `resolve_drift(repo, key, action, reason=None)` — action ∈ `ack` |
  `exception` (exception requires reason; maps to `drift.resolve_exception`,
  ack to `drift.acknowledge_drift([key])`). The update-code path is NOT a
  separate tool: fixing code goes through propose_task → run_loop like any
  other change (one commitment path, not two).

**swap adapter** (mutating):
- `swap_adapter(repo, layer, adapter)` — validate layer + adapter against
  `registry.py`'s actual keys (reject unknowns with the valid options in the
  error), then rewrite ONLY that key in `sembl.stack.yaml` (preserve the rest
  of the file: comments may be lost only if the existing config loader already
  round-trips lossily — match whatever `wizard.py`/`onboarding.py` already do
  when they write config; do not invent a new YAML writer).

### 3.2 Discipline (encoded, not just documented)

- **Commit-only-through-tools:** the mutating tools are exactly `run_loop`,
  `confirm_task`, `resolve_drift`, `swap_adapter`. Each one's result includes
  what artifact/file/run it wrote (`run_id` or paths) — every commitment is
  bound to an inspectable record. The human-approval layer is the MCP client's
  own tool-permission prompt (claude CLI prompts on tool use by default) PLUS
  the propose→confirm split for specs; the server itself never asks questions.
- **Zero judgment:** the server never imports gate internals for anything but
  reading persisted verdicts; grep-verify no code path in `operator_mcp.py`
  constructs or mutates a `Verdict`.
- **Read-only guide separation (O9):** `factory_guide.py` remains separate and
  unimported here; the operator does not answer via the guide's model call.
- **Secrets (O15):** tools never return env values or `profile.py` secret
  material; `read_config` returns layer names, never resolved credentials.

## 4. Loop/engine touch points

- The loop entry used by `run_loop` must be the SAME function `cli.py loop`
  invokes today (extract if currently inline in the click command — a pure
  extract-function refactor, behavior identical, CLI output unchanged).
- Bus publishes per §2.3. No other engine change. O1 check: everything the
  server does must be a call into existing `sembl_stack/` functions.

## 5. The headless proof surface: `sembl-stack operator` (thin, disposable)

A minimal REPL (~100 lines, `cli.py` command + helper in `operator_mcp.py` or a
small `operator_shell.py`) that proves "system talks back" headless:

- Writes a temp MCP config json pointing at `sembl-stack-mcp` (this venv's
  console script; use `sys.executable -m sembl_stack.operator_mcp` — the same
  PATH-independence lesson as verify_sembl.py) and launches `claude -p` with
  `--mcp-config <file>` and session continuation (`--resume`/`--continue`) per
  turn, so the conversation persists across turns.
- Before sending each human turn, calls `bus.read_since(cursor)` and prefixes
  any new events as a bracketed block:
  `[factory events since last turn]\n- <summary>\n...` — this is the unprompted
  talk-back. Cursor kept in memory for the session.
- `--print-mcp-config` flag: print the MCP config json and exit, so ANY other
  MCP client (opencode, the future IDE) can connect to the same server — D4's
  swappability made demonstrable.
- Honest degradation: if `claude` is not on PATH, print exactly what to install
  and the `--print-mcp-config` alternative; never a traceback.
- This wrapper is scaffolding for the proof; the IDE conversation panel replaces
  it. Do not gold-plate (no colors, no history file, no streaming parse).

## 6. Platform/security review (applied)

- Windows: `claude` resolves to a `.cmd` shim — launch it the way
  `deploy_vercel.py` handles shims; subprocess always
  `encoding="utf-8", errors="replace"` + explicit timeouts (none on the
  interactive child itself; it's the user's session).
- The MCP server runs with the user's repo permissions on purpose (it IS the
  user's typed hands) — but its tool surface is the containment: no shell, no
  raw write, no gate mutation. That surface is the security boundary; tests
  must lock it (see WP-B tests: "no unexpected tools registered").
- Bus file writes are append-only, tolerate concurrent writers per line
  (single `f.write(line)` call per event, same as events.jsonl).

## 7. Work packages (dispatchable; WP-A ∥ WP-B, then WP-C)

- **WP-A — the bus.** `bus.py` per §2 (API pinned) + all §2.3 publish points +
  tests (≥8): publish/read round-trip; cursor semantics (incremental reads,
  torn trailing line skipped without advancing); never-raise on unwritable
  path; unknown kind → `other`+`raw_kind`; run.stage mirrored from
  append_event with run_id; loop publishes started/verdict/finished (fallback
  runner path at minimum); drift.new published only when new findings exist;
  existing suite green (no hot-path behavior change).
  **DO-NOT:** change any existing function's return value or error behavior;
  publish from inside the gate.
- **WP-B — the MCP server.** `operator_mcp.py` per §3 + pyproject `[mcp]` extra
  + console script + tests (≥14, calling tool BODIES directly, no transport):
  read_state list + detail; read_events passthrough; read_config lists layers
  and registry options and leaks no secret values; run_loop returns
  run_id+verdict and returns BLOCK as BLOCK (stub/fixture loop); propose_task
  returns the O8 fixed schema (mock the model call the way discuss tests do);
  confirm_task writes task+bounds; list_drift; resolve_drift ack; resolve_drift
  exception requires reason; resolve_drift unknown key = clean error not
  traceback; swap_adapter happy path rewrites one key; swap_adapter rejects
  unknown layer/adapter listing valid options; the registered tool set is
  EXACTLY the nine names in §3.1 (the boundary-lock test).
  **DO-NOT:** add any tool beyond §3.1; call any model inside the server; import
  factory_guide; construct/mutate a Verdict; add an apply/merge/override tool.
- **WP-C — the operator REPL (after A+B green).** §5 + tests (≥4): temp MCP
  config content correct (uses sys.executable); event block prefixed to the
  turn when bus has new events, absent when not; `--print-mcp-config` prints
  valid json and exits 0; claude-missing path prints actionable message, rc≠0,
  no traceback. Live-proof is the lead's (§8).
  **DO-NOT:** parse/reformat model output; add UI polish; keep any per-user
  state beyond the in-memory cursor.

## 8. How the lead re-verifies before commit

1. Read every diff fully. Grep-verify the boundary locks: no tool name beyond
   §3.1 registered; no `Verdict(` constructed in operator_mcp.py; no
   factory_guide import; no shell/file-write tool.
2. Run both suites myself (`.venv/Scripts/python -m pytest -q`).
3. Drive the golden path myself on a scratch repo: `sembl-stack operator` →
   propose → confirm → run_loop on a task that BLOCKs → see the verdict event
   surface in the next turn's event block → ask the agent to explain → then a
   task that PASSes. Also: `--print-mcp-config` into a bare `claude` session to
   prove D4's any-client claim. Walk the empty state (no events ⇒ no block)
   and the error path (claude missing from PATH via env manipulation).
4. Confirm the bus file contents by eye: one JSON object per line, kinds from
   the closed set, run ids present on run-scoped events.
5. Commit per WP with honest limitations recorded.

## 9. Anti-trap reconciliation

The three dead shells were chrome built before signal. This build's "surface"
is a ~100-line disposable REPL whose only purpose is to prove the signal
(typed-tools conversation + talk-back) headless; the durable deliverables are
the bus and the MCP server — pure engine surfaces the IDE will consume as-is.
The IDE conversation panel (chrome) remains a later roadmap item and connects
to the same server unchanged; if the REPL proof fails, no chrome was built on it.
