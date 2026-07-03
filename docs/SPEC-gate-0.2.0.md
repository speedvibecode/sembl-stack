# SPEC — gate 0.2.0: IDE quickstart + one-call "gate this PR" MCP tool

> **Pinned 2026-07-03 (Claude).** Implements launch decision #16
> (LAUNCH-PREP-JULY1.md §0): "Package + IDE quickstart + version bump + 1-2 new
> MCP ergonomics (e.g. a one-call 'gate this PR')." Built in the **sembl** repo
> on branch `gate-0.2.0`; master stays at `da0582f` so the owner can cut
> `v0.1.21 --target da0582f` first.

## Why 0.2.0 (not 0.1.22)

The IDE/MCP milestone is the launch wedge (decision #4: "MCP is the hook").
0.2.0 marks the surface where an IDE agent can adopt the gate in one tool call.

## Scope (exactly this, nothing else)

### 1. `gate_pr` — the headline MCP tool (sembl/mcp_server.py)

One call, no pre-computed diff, no pre-assembled contract:

```python
def gate_pr(
    repo_path: str = ".",
    base: str | None = None,     # base ref; auto-detect when omitted
    head: str = "HEAD",
    bounds_file: str | None = None,
    editable_paths: list | None = None,   # inline overrides, win over files
    forbidden_areas: list | None = None,
    churn_budget: dict | None = None,
    scope_tolerance: dict | None = None,
    report: dict | None = None,
    strict: bool = False,
) -> dict
```

Behavior:
- **Base auto-detect** (when `base` is None): `refs/remotes/origin/HEAD` →
  `origin/main` → `origin/master` → `main` → `master`, first ref that
  `git rev-parse --verify` accepts. No candidate → structured
  `{"error": ..., "hint": ...}` (never a raw exception over MCP).
- **Diff**: `git diff <base>...<head>` (three-dot, merge-base semantics — the
  PR's own commits only). Parsed with the existing `parse_unified_diff`.
- **Bounds**: inline fields win; else `bounds_file`; else the CLI's discovery
  order (latest `.sembl/work-orders/*/work-order.json`, `bounds.json`,
  `.sembl/bounds.json`). **No bounds at all → structured error**, not a vacuous
  PASS (an empty contract passes everything — false assurance).
- **Contract self-edit**: the resolved bounds file's repo-relative path is
  passed as `contract_paths` (parity with `sembl verify`, which already does
  this; 0.1.21 behavior).
- **Result**: same shape as `verify_change` (`to_dict` + `summary`), plus
  `pr: {base, head, merge_base, bounds_source}` so the caller can audit what
  was actually gated.

### 2. `verify_change` gap fix: contract self-edit detection

`verify_change` never passed `contract_paths`, so a diff that rewrites the
very `bounds.json` judging it did NOT flag over MCP (it does via the CLI).
Fix: when bounds came from a file, pass its repo-relative path through.
Inline-only bounds have no file to protect — unchanged.

### 3. IDE quickstart (docs/ide-quickstart.md + README pointer)

One page: register the sembl MCP server in Claude Code / Cursor / VS Code
(uvx one-liner from server.json), then the two workflows —
(a) `gate_pr` one-call on a branch, (b) `bounds_from_spec` → `verify_change`
for orchestrators. Include the pre-commit + GitHub Action recall links.

### 4. Version ceremony (versioning-rule, same commit per repo)

- sembl: `pyproject.toml`, `sembl/__init__.py`, `server.json` (×2),
  `.release-please-manifest.json`, doc pins (`README.md` ×2,
  `docs/integrations.md` ×2, `skills/**/SKILL.md` ×1) → `0.2.0` / `v0.2.0`.
- site (branch, merge on release): `changelog.html` (new entry), `docs.html`,
  `index.html`, `main.js`.

## Non-goals

- No new checks, no policy changes, no generation-half work.
- No keyring/credential work (WS-C owns that).
- `save_bounds`/write-side MCP tools — deferred; the authoring flow
  (`sembl bounds`, untracked bounds.json) already covers it and a write tool
  invites contract-weakening by the agent being judged.

## Acceptance

- Unit tests: base auto-detect fallback, no-bounds error, three-dot diff vs a
  real temp git repo (two branches), contract-self-edit flag through both
  `gate_pr` and `verify_change` (diff touching bounds.json → BLOCK), inline
  overrides win, `pr` metadata present.
- Full suite green (`.venv\Scripts\python.exe -m pytest`).
- `sembl-mcp` still starts (FastMCP registers 7 tools).
