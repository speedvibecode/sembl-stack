# Sembl-Stack — Process Action Plan (single source of truth)

> **This is the one plan.** It merges and supersedes the former `PLATFORM-MAP.md`,
> `ROADMAP-TO-PRODUCT.md`, `BUILD-PLAN.md`, `SURFACE-PLAN-tui.md`, and the repo `README`'s
> overview, into one document a session can act on cold. Reference material kept *beside* it
> (not merged): `process-self-improvement.md` (north-star theory), `eval-metric-O3.md` (the
> computable metric — code points at it), `memory-plane-hypothesis.md` (CBM-use decision), and
> the `SPEC-*.md` agy build specs. **[LOCKED]** = decided basis; change only by editing this file
> in a commit so the decision is diffable.
>
> Last reconciled: 2026-06-21. Current branch of record: `ws2-through-deploy-spine`
> (master untouched). Re-verify state against the repo before trusting any status line.

---

## 1. The product in one paragraph
An **open, swappable, spec-driven coding factory**: a spec is planned, an agent writes, a
sandbox contains, **Sembl gates**, it merges, deploys, and a post-deploy gate confirms or rolls
back — every layer an interchangeable adapter behind one typed contract. We sell **process
correctness** (the change did what the spec declared, stayed in bounds, is honestly evidenced,
reached production accountably) — **never "the model writes better code"** (that causal claim is
falsified; do not rebuild or re-test it). The core user is someone who wants a **deterministic**
way to ship with AI, not a slot-machine. The more detail the process derives from the user, the
better the output — spec-driven development as the wedge.

**Two axes, never conflated:** (1) **Pipeline layers** = *how work flows* (this repo, L0–L8).
(2) **Domain integrations** = *what gets built/shipped* (GitHub, Vercel, Supabase, Sentry, …) —
targets wired as MCP/CLI adapters, consumed not owned.

**We OWN exactly three things [LOCKED]:** the **artifact contract + stage Protocol**, the **gate
(Sembl, L5 + the post-deploy gate L8)**, and the **hub glue + layer-replacement protocol**.
Everything else is CONSUME (OSS behind an adapter) or INTEGRATE (external via MCP/API/CLI).

## 2. Architecture — the one inversion everything rests on [LOCKED]
**This is not a pipeline. It is composable _stages_ over a typed _artifact contract_.** The
"pipeline" is just the default wiring.
- A **stage** is `inputs (typed artifacts) → output (typed artifact)`. Stages know only about
  artifacts, never each other. Partial use, mid-entry, and custom insertion are therefore
  *normal*: run any subset; enter wherever you can supply the inputs; a custom step is legal
  between X and Y iff it consumes X's output type and produces Y's input type.
- **Run store [LOCKED]:** artifacts live as JSON in `.sembl/runs/<run-id>/` (git-ignorable),
  one file per artifact + a manifest. Local-first, portable, inspectable, no server to read a
  past run. **This is what makes "leave/resume anywhere" — and the TUI in §8 — nearly free.**

**Three planes + one hub [LOCKED]:** `BRAIN (context, plane C) → SPINE (process, plane A = this
repo) → TARGET (product, plane B)`, everything speaking **MCP** at the hub.

**Artifact contract:**

| Artifact | Produced by | Consumed by |
|---|---|---|
| `Task` | you / spec | L1–L3 |
| `Context` | L1 / Brain | L3 |
| `SpecGraph` | L2 / spec | L5.5 reconcile |
| `Bounds` | L2 | L3, L5 |
| `Change` | L3 | L4, L5 |
| `Verdict` | L5 | loop, merge, deploy |
| `ReconciliationReport` | L5.5 | human (advisory, NOT a gate) |
| `MergeRecord` | L6.5 | audit |
| `Trace` | L6 | web/TUI lens |
| `Delivery` | L7 | L8, audit |

## 3. The stage map (L0–L8) and current build status

| Layer | Job | In → Out | Own? | **Status (2026-06-21)** |
|---|---|---|---|---|
| L0 Protocol/Hub | one wire | — | OWN contract | ✅ |
| L1 Repo intel / code-graph | understand | `Task → Context` | consume | ✅ symgraph + CBM (per-PR index) |
| L2 Spec → bounds | scope | `Task → Bounds` | OWN schema | ✅ `sembl` |
| — SpecGraph builder | graph the spec | `Task → SpecGraph` | OWN | ✅ in loop plan node |
| L3 Execute | write | `Task+Bounds → Change` | consume | ✅ ×3 (claude / aider / opencode·MiniMax) |
| L4 Sandbox | contain | `Change → Change` | consume | ✅ disposable clone (alias worktree) |
| L5 Verify (gate) | gate the diff | `Change+Bounds → Verdict` | **OWN gate** | ✅ green, sembl 0.1.20 |
| L5.5 Reconcile (per-PR) | spec↔code drift | `SpecGraph+CodeGraph → Report` | INTEGRATE (advisory) | ✅ **live: `reconcile --live` drives a real CBM index** (landed 2026-06-22); flagship live-proof pending owner run |
| L5.5 Quality review | code-quality signal | diff → findings | INTEGRATE | 🟡 **prep complete (mock + shell + 2×2, landed 2026-06-22)**; real CodeRabbit wiring deferred to ~2026-07-02 (owner on another project + vacation) |
| L6 Orchestrate+observe | loop/trace | wiring + `*→Trace` | consume | ✅ LangGraph + retry-on-BLOCK |
| L6.5 Merge | gated merge | `Verdict(PASS) → MergeRecord` | OWN stage | ✅ **landed 2026-06-21** (PASS merges, BLOCK refused) |
| L7 Deploy | ship | `Verdict(PASS) → Delivery` | INTEGRATE (own stage, delegate mechanism) | ✅ Vercel; flagship live |
| L8 Verify-in-prod | gate prod | `Delivery → Verdict` | **OWN gate** | ✅ health/payload gate + **rollback trigger** (landed 2026-06-21) |

**Depth-1 spine = 11/11** (all stages wired). The L5.5 quality slot is **prepped to swap-ready**
(mock reviewer + CodeRabbit subprocess shell + planted case 14 + 2×2 eval, all green) — only the
real CodeRabbit CLI wiring remains, **deliberately deferred to ~2026-07-02** (owner takes up
another project, then vacation). Also pending: the flagship live-proof of reconcile-live (owner run).
*(L8 rollback closed 2026-06-21; reconcile-live closed 2026-06-22; CodeRabbit prep closed 2026-06-22.)*

## 4. The metric (O3) and current evidence
Full computable spec: `eval-metric-O3.md`. One-line claim: *with the gate in the loop, fewer bad
changes (out-of-scope / forbidden / fabricated / unevidenced / over-churn) reach merged, corrected
in fewer iterations, at a known cost, without harming quality.* Quality is measured **only** as
gate-caught regressions + a no-harm baseline — **never** as the headline (trap-guard).

**Numbers in hand (re-verified 2026-06-21, `eval/harness.py` + `eval/through_deploy.py`):**
- Static gate, 12-case corpus: **bad-merge 1.0 → 0.25**, false-alarm **0.0**, 0 mismatches.
- **Through deploy**, +1 runtime-break case: funnel over 9 bad = blocked-pre-deploy 6,
  rolled-back-by-L8 1, still-live 2 ⇒ **bad-live 1.0 → 0.222**, false-alarm **0.0**.

## 5. Locked decisions ledger
**Architecture (O):** O1 engine = headless lib + optional `serve`, surfaces are thin clients ·
O2 spine runs **through deploy** (own deploy stage + post-deploy gate + rollback, delegate the
mechanism) · O3 success = process correctness, quality only as gate-caught regressions, "better
code" never the criterion · O4 keep `sembl-stack` working name · O5 secret/permission/sandbox
model is the hard prerequisite for real deploy/hosted use · O6 first visual surface = in-terminal
TUI.

**Strategy/stage (S):** S1 B(measure)+C(build) parallel, **amended by S7** · S2 depth>breadth
(≈2–4 adapters/layer, not a 100-tool catalog) · S3 winnable bar = O3 + through-deploy
accountability, not "beats every tool" · S4 private beta (3–5 partners) before public · S5
2nd/3rd executor RESOLVED (Aider, MiniMax-M3) · S6 corpus source OPEN (default: mix) · **S7 launch
bar RAISED**: complete through-deploy + beats-prompt-chains (O3 public) + ~50 adapters · S8 O5 on
the critical path · S9 per-PR SpecGraph↔CodeGraph reconciliation (advisory, NOT the gate) · S10
flagship O5 = local-creds-first · S11 flagship = feedback board (Vercel+Supabase) · **S12
MurphyScan = launch-readiness gate** (the 3rd axis — see §7).

## 6. North Star — recursive PROCESS self-improvement
The process improves itself **because of the tools of the process**, not because any model gets
smarter (intelligence stays exogenous). Signal = the deterministic run-store artifacts; search
space = the swappable catalog; optimizer = the layer-replacement protocol (`signal → shadow →
promote`); the gate is both a component and the fitness function (non-circular: a mechanical
metric judges, never a model grading a model). Ladder L0→L4 in `process-self-improvement.md`.
**Where we are: L0 (manual swap). ~1 step from L1 (measured selection)** — needs live
multi-executor run-logging (iters-to-green + cost) over the existing corpus. L2–L4 are
demand-pulled, post-launch.

## 7. Three accountability axes (do not conflate) + honesty guardrails
- **Sembl gate (L5/L8)** = *process correctness* — per change/deploy, deterministic, in the loop.
- **CodeRabbit (L5.5)** = *code quality* — per PR, advisory signal.
- **MurphyScan (S12)** = *operational / launch readiness* — the 13-layer P0–P3 production audit,
  per release / pre-launch (NOT in the per-change loop). Must be green on the flagship before
  public launch; already earned it (caught the magic-link auth P0). Run `/murphyscan` as a
  standing pre-deploy/pre-release step.
- **Guardrail [LOCKED]:** never sell "better code." "Reaches production correctly" = does what the
  spec declared, stays in bounds, passes the merge gate, deploys, passes the deterministic
  post-deploy gate (health + error-rate) with a rollback trigger, on an auditable trail.

## 8. The surface vision — `sembl stack` guided TUI (elevates C4)
Bare **`sembl-stack`** (no subcommand) launches a **Textual** wizard (Textual already a dep;
`tui.py` `RunsDashboard` + `views.py` + `presets.py` are the foundation) that **guides** the whole
journey with a **stage rail (CI-run-page UX)** and **leave/continue-anywhere resume** via a tiny
`session.json` pointer `{run_id, current_stage}` over the existing run store — a *thin guide over
artifact-first machinery, no new core/gate logic* (the TUI shells the same stage functions as the
CLI, so TUI and headless runs are byte-identical).

Journey = New-or-Existing repo → (Existing → CBM `index_repository`, code-graph alive) → intent
(spec) → bounds → pick executor/preset → run loop (live) → reconcile (S9) → quality-review slot →
merge gate → deploy + post-deploy → MurphyScan readiness.

**Why on-plan, not a detour:** it *is* C4 (the locked stranger-runnable surface) + the **beta
surface (S4)** + a **self-test milestone** (dogfood: use `sembl stack` on the sembl-stack repo to
build the next sembl-stack feature → factory-builds-factory, the on-ramp to north-star L4). It can
run **in parallel** with closing the spine because Phase 0 only wires already-headless stages.

**Surfaces order [LOCKED]:** CLI (native habitat) → TUI live/guided → web/IDE lens (a 2nd
front-end that watches the run store + calls the same CLI stage commands — no core duplication).

## 9. THE ACTION PLAN — remaining work, in order
Anti-trap discipline [LOCKED]: prove the **evidence + a depth-1 through-deploy spine on the ONE
flagship FIRST**; fan out to ~50 adapters only AFTER. Evidence ✅ done; spine 9/11.

**Track 1 — close the spine (no external account; agy-delegable):**
1. ~~**L8 rollback trigger**~~ — ✅ **DONE 2026-06-21** (`docs/SPEC-l8-rollback.md`, commit
   `b43b396`). Post-deploy `BLOCK` fires `VercelDeployAdapter.rollback` via opt-in `postdeploy
   --rollback`; outcome recorded in `verdict.raw["rollback"]`; gate stays mechanism-free. 4 new
   deterministic tests (mock promote + urlopen), 81 passed / 1 skipped.
2. ~~**Reconcile-live (S9)**~~ — ✅ **DONE 2026-06-22** (`docs/SPEC-reconcile-live.md`, commit
   `53ad50c`). New `CbmCodeGraph` adapter drives codebase-memory-mcp headlessly behind a
   `codegraph` layer; `reconcile --live --repo` builds the graph from a real CBM index (no
   hand-passed JSON). Subprocess-contained, advisory-only. 7 new tests, 88 passed / 1 skipped.
   *Remaining:* the flagship live-proof run (owner, §7 of the spec) → hand the report to Claude.

**Track 2 — the `sembl stack` TUI (parallel; agy-delegable):**
3. ~~**TUI Phase 0**~~ — ✅ **DONE 2026-06-22** (`docs/SPEC-tui-phase0.md`, commit `bc03beb`).
   Bare `sembl-stack` launches a Textual wizard (New/Existing + stage rail) with `session.json`
   resume over the run store; `session.py` (pure core, 6 committed tests) + `wizard.py` (pilot-
   tested locally) + `invoke_without_command` wiring. Built+verified by Claude (kept per owner
   decision; a from-scratch Textual app is the riskiest delegation). Committed suite 49 passed.
   *Remaining:* owner TTY live-proof (relaunch resumes mid-rail).
4. **TUI Phase 1** — CBM index trigger, reconcile panel, live deploy/postdeploy panels, MurphyScan
   readiness screen.

**Track 3 — prep the CodeRabbit trial BEFORE opening the 14-day account — ✅ PREP DONE
2026-06-22 (spec `SPEC-coderabbit-prep.md`, agy-built, reviewed + re-verified; 59 passed):**
5. ✅ **L5.5 review-adapter shell** — `ReviewReport` artifact + `ReviewAdapter` protocol +
   `MockReviewAdapter` (validated file-level N+1/unsafe detector) + `CodeRabbitReviewAdapter`
   subprocess shell (PROVISIONAL, mock-tested, never run the real CLI) + `review` registry layer
   (mock default) + advisory `review` CLI.
6. ✅ **Planted quality-regression case 14** (`eval/corpus/14-quality-defect-passes-gate`) — the
   quality-axis analog of case 13: **passes the Sembl gate** (in-scope, evidenced, low-churn) but
   has a real N+1 defect the reviewer flags.
7. ✅ **The 2×2 eval** (`eval/two_axis.py`) — verified **gate_only=6, quality_only=1, both=0** ⇒
   each catches what the other misses, **complementary, not redundant.**
   → *Items 5–7 done. Opening the CodeRabbit trial is **deliberately deferred to ~2026-07-02***
   *(owner takes up another project first, then vacation). On day 1: swap the mock for the real*
   *CLI (finalize the subcommand/JSON shape in `review_coderabbit.py`) and spend all 14 days on*
   *the 2×2 proof. **Do NOT open the account before then.***

**Track 4 — RSI-L1 readout (cheap, high-narrative):** per-executor iters-to-green + cost over the
corpus → the "measured selection" artifact. Advances the north star's first rung.

**Back half (only after the spine + CodeRabbit proof):** breadth → ~50 adapters (2–4/layer,
demand-curated, agy-delegable) · full O5 (hosted/team secret-permission-sandbox) · private beta
(3–5 partners, the moment a stranger can run the spine) · MurphyScan green on the flagship · then
**public launch (Track A)**: full through-deploy, beats-prompt-chains, ~50-tool product.

## 10. The delegation method (the operating model)
Claude = **orchestration only**: pin a precise spec (all judgment + exact acceptance numbers) →
a cheap CLI **executes** → Claude **reviews the diff + re-verifies** (never trusts the agent's
self-check) → commit + push. Proven on the through-deploy evidence and the merge stage (both clean
on first review). Keep every delegation spec fully pinned so each agy/cheap-model session is
execution-only and the limited test-time tools aren't burned on setup.

## 11. Tooling reality
- **agy (Antigravity CLI, Gemini-3.5-Flash)** — `C:\Users\totla\AppData\Local\agy\bin\agy.exe`;
  headless `agy -p "<prompt>" --dangerously-skip-permissions --model gemini-3.5-flash`. **Needs
  interactive auth (a TTY)** — hangs silently otherwise — so the **owner runs it in their own
  foreground terminal**; it cannot run from Claude's automated shell. Fast path for delegation.
- **opencode + MiniMax-M3** — `opencode -m tokenrouter/MiniMax-M3` (native exe to preserve
  multi-line prompts); a working cheap executor, but stalled ~1h on a single-shot build task —
  prefer agy for delegation.
- **codebase-memory-mcp (CBM)** — code-graph engine (`index_repository`/`detect_changes`); feeds
  reconcile (S9) and bounds-expansion. Claim-A use; per-PR indexing suffices (do NOT promote it
  to a load-bearing memory plane — see `memory-plane-hypothesis.md`).
- **codex (GPT-5.5)** — tough tasks + review; wedges on CBM (comment out that MCP block in
  `~/.codex/config.toml` for a codex run, then restore).

## 12. Quickstart (from the former README)
```bash
pip install -e .            # + the gate:  pip install sembl
sembl-stack init            # scaffold sembl.stack.yaml + task.yaml from a preset
sembl-stack doctor          # config-aware preflight
sembl-stack loop task.yaml  # plan → execute → gate → retry-on-BLOCK
sembl-stack runs [<id>]     # list / inspect runs (verdicts, reasons, latency)
sembl-stack apply <id>      # apply the accepted patch (BLOCK never applied)
sembl-stack merge --verdict v.json --source <branch>   # L6.5 gated merge
sembl-stack deploy --verdict v.json --prod             # L7
sembl-stack postdeploy --delivery d.json               # L8
```
Presets (adoption ramp): `just-gate` (the wedge — gate any diff, needs only `sembl`) ·
`gate+sandbox` (whole loop, mock executor, no keys) · `full-loop` (real agent + sandbox + gate).
Swap any layer with one line in `sembl.stack.yaml` (e.g. `execute: opencode`) — no code change.

## 13. Reference docs (kept beside this plan, not merged)
- `process-self-improvement.md` — north-star theory (the L0→L4 ladder).
- `eval-metric-O3.md` — the computable metric (code points here).
- `memory-plane-hypothesis.md` — why CBM stays a per-PR tool, not a memory plane.
- `SPEC-merge-stage.md` — the executed merge-stage build spec (record of the delegation method).
