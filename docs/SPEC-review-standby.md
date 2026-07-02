# SPEC — standby review adapters (Semgrep + Qodo PR-Agent) [PINNED, BUILD ON DEMAND]

> **Status: STANDBY (owner, 2026-07-02).** Do NOT build yet. The L5.5 quality axis is
> already served by `review: llm` (real 2×2 green) with `review: mock` as the no-AI
> preview and `review: coderabbit` wired-but-auth-blocked. These two are the next review
> adapters to add **when a trigger fires** (see §3) — this spec exists so the build is
> mechanical: contract, invocation, parse mapping, and tests are pre-decided.

Both follow the locked review-slot rules (SPEC-coderabbit-prep.md §0): advisory only,
never a gate; every failure → `UNKNOWN` ReviewReport (never raise, never block); tool is
a subprocess shell, never a Python package dependency of sembl-stack; never persist raw
tool stdout (use `_redact.summarize`); registered in `registry.py` under `review:`.

## 1. `review: semgrep` — deterministic rules axis (no LLM, no account)

**Why it's interesting:** the only *deterministic* real reviewer — same input, same
findings, offline-capable. Complements `review: llm` the way the gate complements review.

- **Adapter:** `sembl_stack/adapters/review_semgrep.py`, `SemgrepReviewAdapter(binary="semgrep", config="auto", timeout=600)`.
- **Install (operator, not a dep):** `pipx install semgrep` or `uv tool install semgrep`.
  Windows note: semgrep's native support is spotty — verify `semgrep --version` on this
  box first; if broken, run via WSL or park it (that's a build-time gate, not a design change).
- **Invocation:** semgrep scans *files*, not diffs — reuse the `_materialize_diff`
  pattern from `review_coderabbit.py` (throwaway git repo, apply patch), then
  `semgrep scan --json --quiet --config <cfg> <tmpdir>`.
  `--config auto` needs network (registry); for offline/deterministic runs pin a ruleset
  (e.g. `p/ci` vendored, or a local `rules/` dir) via `options.review.config`.
- **Parse:** JSON `results[]` → findings: `severity` = map `extra.severity`
  (ERROR→error, WARNING/INFO→warn), `kind` = `check_id` tail (snake_case),
  `file` = `path` relative to tmpdir, `message` = `extra.message` first line.
  Empty results → CLEAN. Bad JSON / nonzero unexpected exit / timeout → UNKNOWN
  (semgrep exits 1 when findings exist with `--error`; do NOT pass `--error`, treat
  exit 0/1 with parseable JSON as success).
- **Tests (mirror test_review.py idiom):** missing binary → UNKNOWN; fake JSON results →
  FINDINGS mapped; empty results → CLEAN; garbage stdout → UNKNOWN + redacted; timeout →
  UNKNOWN; registry `names("review")` contains `semgrep`.

## 2. `review: qodo` — open-source AI PR reviewer (BYO LLM key)

**Why it's interesting:** pr-agent is effectively open-source CodeRabbit; gives a second
independent AI reviewer for cross-checking `review: llm`.

- **Adapter:** `sembl_stack/adapters/review_qodo.py`, `QodoReviewAdapter(binary="pr-agent", model=None, timeout=900)`.
- **Install (operator):** `pipx install pr-agent` (PyPI). **Build-time gate: check the
  current license** (pr-agent moved toward AGPL for newer versions; older tags are
  Apache-2.0) — record the pinned version + license in this doc before shipping the
  adapter, since sembl-stack is going Apache-2.0.
- **Auth:** BYO key via env (`OPENAI_API_KEY` / Anthropic config in `.pr_agent.toml`) —
  pointer-not-value rule holds; sembl never reads the key.
- **Invocation:** pr-agent's native mode is a hosted PR URL (`pr-agent --pr_url ... review`),
  which doesn't fit the diff-in/report-out contract. Preferred shape: drive its *local*
  review path against a materialized repo (same `_materialize_diff` throwaway), or if the
  installed version has no local mode, gate the adapter on a real PR URL passed via
  `reviewer_hint` and return UNKNOWN("needs a PR URL") otherwise. Decide against the
  version actually installed at build time; keep the ReviewAdapter signature unchanged.
- **Parse:** pr-agent emits markdown review text by default; request JSON output if the
  version supports it, else map its sectioned markdown (security/bugs sections → findings,
  "no issues" → CLEAN, anything unparseable → UNKNOWN + redacted).
- **Tests:** same failure-matrix as §1 + a markdown-reply mapping test.

## 3. Triggers — when to actually build

Build one of these ONLY when a trigger fires (owner call each time):
1. **Breadth push needs review-layer depth** (launch best-effort: 2–4 adapters/layer —
   review currently has mock/llm/coderabbit = 3; semgrep is the cheapest 4th).
2. **A user/partner asks** for deterministic or non-Anthropic review.
3. **`review: llm` cross-check wanted** — a second independent reviewer to measure
   agreement (feeds the RSI selection signal: which reviewer catches more at lower cost).
4. **CodeRabbit stays dead** past launch and the site wants a "works with real reviewers
   you already have" story with more than one named tool.

Semgrep first (no account, no key, deterministic), Qodo second (license check + heavier
integration). Each is a half-day agy-delegable build from this spec.
