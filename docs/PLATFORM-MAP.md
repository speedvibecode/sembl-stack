# Platform Map (LOCKED v1) — what we are building

> Status: locked working model as of 2026-06-16. Decisions marked **[LOCKED]** are the
> basis we build on; **[OPEN]** items still need an owner call (see ledger at bottom).
> Change a [LOCKED] item only by editing this file in a commit, so the decision is diffable.

---

## 0. The one inversion everything rests on

**This is not a pipeline. It is a set of composable _stages_ over a typed _artifact
contract_. The "pipeline" is just the default wiring of those stages.** [LOCKED]

- A **stage** is a function: `inputs (typed artifacts) → output (typed artifact)`.
  Stages never know about each other — only about artifacts.
- Partial use, mid-entry, and custom insertion are therefore *normal*, not special:
  run any subset; enter wherever you can supply the inputs; a custom step is legal
  between X and Y iff it consumes X's output type and produces Y's input type.
- The foundational unit is **the artifact + a stage that transforms one artifact into
  another** — NOT "the loop."

## 1. The three planes + one hub

```
            THE HUB — MCP (+ A2A): one protocol everything speaks   [LOCKED]
  BRAIN (context) ──feeds──▶ SPINE (process) ──ships into──▶ TARGET (product)
  plane C                    plane A (this repo)              plane B
```

- **Plane A — Spine (process):** the stages a change flows through. *This is sembl-stack.*
- **Plane B — Target (product):** what gets built/shipped — the 13 app-domain layers.
  Reached as integrations, NOT owned, NOT pipeline steps.
- **Plane C — Brain (knowledge):** persistent context (Obsidian/wiki, specs, rules,
  memory) pulled into a `Context` artifact and fed to the spine.

**What we OWN (total):** the **artifact contract + stage Protocol**, the **gate
(Sembl)**, and the **hub glue + layer-replacement protocol**. Nothing else. Everything
else is CONSUME (OSS behind an adapter) or INTEGRATE (external via MCP/API/CLI). [LOCKED]

## 2. The artifact contract (the substrate)

Artifacts are first-class, **JSON-serializable, and persisted per run**. If they were
only in-memory objects you could not enter/exit at arbitrary stages. [LOCKED]

| Artifact | Produced by | Consumed by | Notes |
|---|---|---|---|
| `Task` | you / spec | L1, L2, L3 | intent + repo ref |
| `Context` | L1 / Brain | L3 | repo-intel + pulled knowledge |
| `Bounds` | L2 | L3, L5 | scope contract (the thing Sembl checks) |
| `Change` | L3 | L4, L5 | diff + executor self-report |
| `Verdict` | L5 | loop, merge | PASS/WARN/BLOCK + reasons |
| `Trace` | L6 | web lens | step timeline |
| `Delivery` | Plane B | audit | deploy record (Phase 3) |

**Stage contract / insertability rule** [LOCKED]: a stage declares typed `inputs` and
`output`. A wiring is valid iff every stage's required inputs are produced upstream.
Custom stages register against the same Protocol (`sembl_stack/adapters/base.py`). The
graph is **DAG-capable in the contract, linear-first in the product.**

**Run store** [LOCKED]: artifacts live in `.sembl/runs/<run-id>/` in the repo
(git-ignorable), one JSON per artifact + a `run.json` manifest. Local-first, portable,
inspectable, no server required to read a past run.

## 3. Plane A — the stages (L0–L6)

| Layer | Job | In → Out | Tools | Status |
|---|---|---|---|---|
| L0 Protocol/Hub | one wire | — | MCP, A2A | **OWN contract** |
| L1 Repo intel | understand | `Task → Context` | tree-sitter, Joern, Sourcegraph, Graphify, Repomix | CONSUME |
| L2 Spec/Plan | scope | `Task → Bounds` | Spec Kit, Kiro, Tessl, AGENTS.md → **Sembl bounds** | **OWN schema** |
| L3 Execute | write | `Task+Bounds(+Context) → Change` | **OpenCode, Aider, Claude Code** (+Codex/Cursor when stable) | CONSUME |
| L4 Sandbox | contain | `Change → Change` | git worktree, Docker, E2B, Daytona | CONSUME |
| L5 Verify | gate | `Change+Bounds → Verdict` | **Sembl** + Semgrep, ruff/eslint/tsc, pytest | **OWN gate** |
| L6 Orchestrate+Observe | loop/trace | wiring + `* → Trace` | LangGraph, CrewAI + Langfuse, OTel | CONSUME |
| L7 Deploy | ship | `Verdict(PASS) → Delivery` | Vercel, Fly, Cloudflare, GH Actions | INTEGRATE (own the stage, **delegate the mechanism**) |
| L8 Verify-in-prod | gate prod | `Delivery → Verdict` | health/smoke + Sentry error-rate → **Sembl rollback gate** | **OWN gate** + consume signals |

## 4. Embeddability reality (verified 2026-06)

Two bars: **callable** (has MCP/API — almost everything; ~9.6k MCP servers, official
first-party for GitHub/Vercel/Supabase/Sentry) and **drivable** (headless + machine
output we can gate — the executor bar). [LOCKED findings]

- **Executor depth bar met today:** OpenCode (`run -p`, `serve`, `-f json`, OSS),
  Aider (`--message`, `--yes`, Python API, OSS), Claude Code (`claude -p`, Agent SDK).
- **Partial / watch:** Codex (`codex exec` but non-TTY instability), Cursor CLI (beta,
  `-p` hangs). **Shallow/GUI-bound:** Copilot, Windsurf (not catalog-eligible as headless).
- **Rule** [LOCKED]: a tool is **catalog-eligible iff it meets the stage contract**
  (headless run → typed artifact). Curated, not exhaustive. PARTIAL tools join when stable.

## 5. Planes B & C (catalog, not owned)

- **Plane B (Target):** Frontend, APIs, DB/storage, Auth, Hosting, Cloud, CI/CD,
  Security/RLS, Rate-limit, Cache/CDN, LB/scaling, Error/logs, Availability. First-class
  MCP integration targets: **GitHub, Vercel, Supabase, Sentry**.
- **Plane C (Brain):** Obsidian (Local REST API + MCP), Spec Kit docs, AGENTS.md/rules,
  memory. Feeds the spine as `Context`.

## 6. Surfaces (UX) — locked direction

- **Engine is headless and surface-agnostic; every surface is a thin client of one API.**
  [LOCKED]
- **Center of gravity = the _run_** (bounds, attempts, verdicts, diff, trace).
  UX reference = a **CI/CD run page** (GitHub Actions / Vercel deployment). [LOCKED]
- **Explicitly NOT** a node-graph canvas ("whiteboard") and **NOT** a chat box
  ("ChatGPT wrapper"). The config file is the source of truth; visuals are views over it.
- **Surface order** [LOCKED]: CLI (primary, native habitat) → TUI live dashboard →
  web (secondary lens: traces, catalog/marketplace, onboarding, hosted/team).

## 7. Adoption & product shape

- **Front door = a single stage** (the gate on existing diffs; or bounds on existing
  specs). Brownfield, mid-flight, zero migration. The full loop is the **destination**,
  not the entry. [LOCKED]
- **Composable underneath, opinionated on top** [LOCKED]: substrate allows any wiring;
  product ships named presets (`just-gate`, `gate+sandbox`, `full-loop`) + a linear
  default. Custom wiring is an advanced affordance, never the front door.
- **Personal-first, public later** [LOCKED]: wire your ~12 tools now; community-
  extendable catalog + hosted option only after the spine is proven on real execution.

## 8. Honesty guardrails (carried from the first product)

- We sell **process correctness**, never "the model writes better code" (that causal
  claim is falsified — do not rebuild or re-test it). [LOCKED] Quality signals may be
  *measured* (O3) but only as gate-caught regressions + a no-harm baseline — never as the
  success criterion.
- "Reaches production correctly" = the change does what the spec declared, stays in
  bounds, passes the merge gate, deploys, and **passes a deterministic post-deploy gate**
  (health/smoke + error-rate thresholds) with a rollback trigger — all on an auditable
  trail. We own the deploy *stage* + the *post-deploy gate*; we **delegate the deploy
  mechanism** (Vercel/Fly/etc.). Through-deploy scope, no deploy infra owned. [LOCKED O2]

## 9. Build phases (unchanged)

1. **Phase 1** — prove the Spine to **merge-ready** on real OpenCode execution against a
   real corpus, measured per O3 (process correctness primary; quality only as gate-caught
   regressions + no-harm). Deploy stubbed; local-only (O5). Brain only as L2/L3 need it.
   TUI dashboard (O6) prototyped here.
2. **Phase 2** — more spine stages that earn it (repo-intel, real sandbox, live
   observability) + **L7 deploy + L8 post-deploy gate (the through-deploy ambition)** +
   layer-replacement protocol.
3. **Phase 3** — broader Plane B integrations + public/community catalog + web lens.

---

## AMBIGUITY LEDGER — all resolved (owner call, 2026-06-16)

| # | Decision [LOCKED] |
|---|---|
| O1 | Engine = headless library + optional `serve` daemon; CLI/TUI/web are thin clients. |
| O2 | Spine runs **through deploy** — own the deploy stage + post-deploy gate (rollback), delegate the deploy mechanism. No deploy infra owned. |
| O3 | Success metric: **primary** = process correctness (bad/out-of-scope/forbidden/fabricated caught or corrected before merge, WITH vs WITHOUT, + iterations-to-green); **secondary** = quality signals *only* as gate-caught lint/test/security regressions + a no-harm baseline. **Trap-guard: "agent writes better code" is NEVER the success criterion** (that claim is falsified). |
| O4 | Keep `sembl-stack` as working name; defer public brand. |
| O5 | Phase 1 (merge-ready) is local-only: inherit user env, sandbox executors, no deploy creds. A real secret + permission model is a **hard prerequisite for Phase 2 (deploy)** and any shared/hosted use. |
| O6 | First visual surface = in-terminal **TUI** run dashboard (Phase 1). |
