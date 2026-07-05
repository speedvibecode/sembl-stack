# Sembl-Stack — Process Action Plan (single source of truth)

> **This is the one plan.** It merges and supersedes the former `PLATFORM-MAP.md`,
> `ROADMAP-TO-PRODUCT.md`, `BUILD-PLAN.md`, `SURFACE-PLAN-tui.md`, and the repo `README`'s
> overview, into one document a session can act on cold. Reference material kept *beside* it
> (not merged): `process-self-improvement.md` (north-star theory), `eval-metric-O3.md` (the
> computable metric — code points at it), `memory-plane-hypothesis.md` (CBM-use decision), and
> the `SPEC-*.md` delegated build specs. **[LOCKED]** = decided basis; change only by editing this file
> in a commit so the decision is diffable.
>
> Last reconciled: 2026-07-02; **partial update 2026-07-05** (§3, §5, §8, §9 — the ideation +
> chat-shell direction, see `SPEC-ideation-and-chat-shell.md`; §8 also corrected: it still
> described the retired Textual wizard as current). Current branch of record: `master` (the ws2
> through-deploy spine, the L6.5 merge stage, `review: llm`, and WS-C onboarding+BYO-keys are all
> merged; feature branches deleted). Dates in this doc are sequence markers, not deadlines.
> Re-verify state against the repo before trusting any status line.
>
> **▶ For execution, start here: `SPEC-ideation-and-chat-shell.md` §9 (Track 5)** — the
> personal-use-first direction locked 2026-07-05. The prior `LAUNCH-PREP-JULY1.md` public-launch
> runbook (big-bang ~July 14: channels, waitlist, MurphyScan, design-partner QA) is **archived,
> not pursued right now** — owner decision 2026-07-05: dogfooding the factory on itself comes
> first; public launch is revisited after, not on a fixed date. The runbook is deleted (recoverable
> via git history) rather than left to mislead a future session.

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
| **L0.5 Idea → Spec** (new) | greenfield ideation | `Pitch/product.md → Spec(PRD)` | OWN (bounded LLM, fixed slot schema + human confirm) | ✅ **DONE 2026-07-05** (`ideation.py` + `guide.py`'s `_ideation_step`; product.md/PRD.md/idea.md detection, `spec.json`+`spec.md` artifacts; 22 new tests) — see `SPEC-ideation-and-chat-shell.md` |
| L1 Repo intel / code-graph | understand | `Task → Context` | consume | ✅ symgraph + CBM (per-PR index); ambient fused doc+code graph + drift daemon 🆕 planned |
| L2 Spec → bounds | scope | `Task → Bounds` | OWN schema | ✅ `sembl` |
| — SpecGraph builder | graph the spec | `Task → SpecGraph` | OWN | ✅ in loop plan node |
| L3 Execute | write | `Task+Bounds → Change` | consume | ✅ ×3 (claude / aider / opencode·MiniMax) |
| L4 Sandbox | contain | `Change → Change` | consume | ✅ disposable clone (alias worktree) |
| L5 Verify (gate) | gate the diff | `Change+Bounds → Verdict` | **OWN gate** | ✅ green, sembl 0.2.0 (`pyproject.toml` now requires >=0.1.21, the documented hardening baseline — was stuck at >=0.1.20, a codex review finding) |
| L5.5 Reconcile (per-PR) | spec↔code drift | `SpecGraph+CodeGraph → Report` | INTEGRATE (advisory) | ✅ **live-proven 2026-07-04**: `reconcile --live` against the real flagship on a real CBM index (2,953 code nodes) → ALIGNED report, exit 0. Evolving 🆕 toward ambient + interactive (tri-state per node + `update spec`/`update code`/`mark exception` commands) — see `SPEC-ideation-and-chat-shell.md` §5; stays advisory, still not the gate |
| L5.5 Quality review | code-quality signal | diff → findings | BUILD (llm) + INTEGRATE (coderabbit, best-effort) | ✅ **REAL quality axis live 2026-07-02 via `review: llm`** (BYO agent-CLI reviewer, default `claude -p` on the operator's own login; real 2×2 green: gate_only=4/quality_only=3/both=2, 0 UNKNOWN) — CodeRabbit auth UNBLOCKED 2026-07-03 (their backend fix after our report; adapter live-proven, see Track 3 item 11), optional 2nd reviewer; `review: mock` stays the no-AI preview default |
| L6 Orchestrate+observe | loop/trace | wiring + `*→Trace` | consume | ✅ LangGraph + retry-on-BLOCK |
| L6.5 Merge | gated merge | `Verdict(PASS) → MergeRecord` | OWN stage | ✅ **landed 2026-06-21** (PASS merges, BLOCK refused) |
| L7 Deploy | ship | `Verdict(PASS) → Delivery` | INTEGRATE (own stage, delegate mechanism) | ✅ Vercel; flagship live |
| L8 Verify-in-prod | gate prod | `Delivery → Verdict` | **OWN gate** | ✅ health/payload gate + **rollback trigger, live-proven 2026-07-01** |

**Depth-1 spine = 11/11** (all stages wired). The L5.5 quality slot is **prepped to swap-ready**
(mock reviewer + CodeRabbit subprocess shell + planted case 14 + 2×2 eval, all green) — only the
real CodeRabbit CLI wiring remains, **deliberately deferred to ~2026-07-02** (owner takes up
another project, then vacation). Also pending: the flagship live-proof of reconcile-live (owner run).
*(L8 rollback closed 2026-06-21, live-proven against the real flagship 2026-07-01 — see §9 track 1
item 1 for the 4 real bugs the live run found + fixed; reconcile-live closed 2026-06-22; CodeRabbit
prep closed 2026-06-22.)*

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
TUI **(superseded 2026-07-04 by the questionary-based `guide.py` inline CLI, itself the interim
step toward O7 — the Textual wizard `wizard.py` was tried and rejected, see below)** · **O7
[LOCKED 2026-07-05] the target surface is a thin custom chat shell** (not a reskinned wizard, not
"drive an existing agent CLI") — the artifact contract (Task, Bounds, Change, Verdict,
ReconciliationReport, MergeRecord, Delivery) renders 1:1 as chat blocks in a scrolling transcript;
resume-anywhere falls out of replaying the run-store manifest. The stage sequence stays fixed,
deterministic code — **never model-chosen** — with exactly two scoped LLM touch points: parse
free text into a structured artifact, and narrate/explain a finished deterministic result on
request (an `explain` command). · **O8 [LOCKED 2026-07-05] bounded-LLM-into-fixed-schema is the
one deliberate, scoped exception to "no LLM in the loop,"** reused at three points — `guide.py`'s
existing `ai_suggest_paths`, the chat shell's task-parse block, and the new L0.5 Idea→Spec
Q&A — and nowhere else. In every case: LLM proposes into a fixed structured schema it cannot
extend, a human confirms/edits before it's locked in, and it never touches the gate (L5/L8). See
`SPEC-ideation-and-chat-shell.md`.

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

## 8. The surface vision — chat shell over the artifact contract (elevates C4)
**Corrected 2026-07-05 — this section was stale.** The Textual wizard (`wizard.py`, Phase 0-2,
described below in its historical form) was tried, then **rejected 2026-07-04** ("rejected as
slop" per `guide.py`'s own docstring) and replaced by `guide.py` — a `questionary`-based inline
CLI in the Claude-Code/Codex style, currently live. That in turn is the interim step toward the
locked target (**O7**): a **thin, purpose-built chat shell**, not a reskin of either prior surface.

**Historical record (Phase 0-2, superseded, kept for context):** bare `sembl-stack` launched a
Textual wizard (`tui.py` `RunsDashboard` + `views.py` + `presets.py`) with a stage rail (CI-run-page
UX) and `session.json`-based resume; Phase 2 wired the rail to actually run the loop. All of this
is retired — do not build against `wizard.py`.

**Target journey (chat shell, O7):** drop a `product.md`/pitch → **L0.5 Idea→Spec** bounded LLM
Q&A (fixed slot schema: stack candidates, open questions, data model sketch, non-goals — only
unresolved slots become real questions) → user reviews/edits the Spec → **L1** real scaffold
derived from that Spec (not the demo placeholder) → ambient fused doc+code graph watches for
drift → task (free text) → **LLM parse** into structured `Task` → suggested `Bounds` +
graph-diff preview → confirm → **L3-L5** execute/sandbox/gate, streamed live (Claude-Code style,
not a static panel) → **PASS/WARN/BLOCK** verdict card → optional `explain` (LLM narrates the
deterministic result) → drift review if flagged (`update spec` / `update code` / `mark
exception`) → merge → deploy → post-deploy gate. Full design: `SPEC-ideation-and-chat-shell.md`.

**Why on-plan, not a detour:** still C4 (the locked stranger-runnable surface) + the **beta
surface (S4)** + the **self-test milestone** (dogfood: use `sembl stack` on the sembl-stack repo
itself → factory-builds-factory, the on-ramp to north-star L4) — same rationale as before, now
aimed at the corrected target surface.

**Surfaces order [LOCKED, unchanged]:** CLI (native habitat) → guided/live surface → web/IDE lens
(a 2nd front-end over the same run store + CLI stage commands — no core duplication). What changed
is *what* sits in the middle slot (chat shell, not a Textual wizard).

## 9. THE ACTION PLAN — remaining work, in order
Anti-trap discipline [LOCKED]: prove the **evidence + a depth-1 through-deploy spine on the ONE
flagship FIRST**; fan out to ~50 adapters only AFTER. Evidence ✅ done; spine ✅ CLOSED
(through-deploy + rollback + merge gate + real quality axis all live on master).

**Track 1 — close the spine (no external account):**
1. ~~**L8 rollback trigger**~~ — ✅ **DONE 2026-06-21** (`docs/SPEC-l8-rollback.md`, commit
   `b43b396`). Post-deploy `BLOCK` fires `VercelDeployAdapter.rollback` via opt-in `postdeploy
   --rollback`; outcome recorded in `verdict.raw["rollback"]`; gate stays mechanism-free. 4 new
   deterministic tests (mock promote + urlopen), 81 passed / 1 skipped.
   **Flagship LIVE-PROOF done 2026-07-01** (real prod break → real BLOCK → real Vercel rollback →
   real recovery, against `sembl-flagship-feedback-board.vercel.app`). The mocked tests never
   exercised the real Vercel CLI/Windows path — the live run surfaced 4 real bugs, now fixed +
   covered by new deterministic tests (125 passed): (a) `vercel` resolves to a Windows `.cmd`
   shim — bare `subprocess.run(["vercel", ...])` raised `FileNotFoundError`; (b) bare `vercel
   rollback` (no target) only reports rollback *status* on current CLI — it never rolled back;
   `rollback()` now auto-resolves the previous production deployment via `vercel ls --prod` and
   targets it explicitly; (c) `--config` defaulted relative to CWD, not `--repo` — running
   `postdeploy` against a repo other than CWD silently skipped its `expect_json` health contract;
   `deploy`/`postdeploy` now fall back to `<repo>/sembl.stack.yaml`; (d) `_last_url` picked a
   `vercel.com` dashboard / `api.vercel.com` link over the real `*.vercel.app` deployment URL —
   now prefers the `.vercel.app` host. See `sembl_stack/adapters/deploy_vercel.py` + `cli.py`.
2. ~~**Reconcile-live (S9)**~~ — ✅ **DONE 2026-06-22** (`docs/SPEC-reconcile-live.md`, commit
   `53ad50c`). New `CbmCodeGraph` adapter drives codebase-memory-mcp headlessly behind a
   `codegraph` layer; `reconcile --live --repo` builds the graph from a real CBM index (no
   hand-passed JSON). Subprocess-contained, advisory-only. 7 new tests, 88 passed / 1 skipped.
   *Flagship live-proof ✅ DONE 2026-07-04* (ran in-session, not owner-gated after all): spec
   §7 commands against `examples/flagship-feedback-board` on a real CBM index — 2,953 code
   nodes, report `ALIGNED` ("spec concepts are represented"), advisory exit 0. Reviewed:
   honest but thin on the spec side (a one-line text spec yields 2 spec nodes); a richer
   divergence demo would need a real Spec-Kit dir as `--spec` input — noted, not blocking.

**Track 2 — the `sembl stack` TUI (parallel):**
3. ~~**TUI Phase 0**~~ — ✅ **DONE 2026-06-22** (`docs/SPEC-tui-phase0.md`, commit `bc03beb`).
   Bare `sembl-stack` launches a Textual wizard (New/Existing + stage rail) with `session.json`
   resume over the run store; `session.py` (pure core, 6 committed tests) + `wizard.py` (pilot-
   tested locally) + `invoke_without_command` wiring. Built+verified by Claude (kept per owner
   decision; a from-scratch Textual app is the riskiest delegation). Committed suite 49 passed.
   *Remaining:* owner TTY live-proof (relaunch resumes mid-rail).
4. ~~**TUI Phase 1 — onboarding + BYO-keys (WS-C)**~~ — ✅ **DONE 2026-07-02** (spec
   `SPEC-tui-phase1-onboarding.md`, commits `161b6e7` + hardening `34a43b5`): `profile.py`
   credential core (pointer-only `key_source`, enforced save AND load; secret-scrub on executor
   output), codex-built Textual first-run wizard (welcome → BYO choice w/ preflight → prefs),
   `--reconfigure`, and profile-as-default `loop` (an explicit repo `sembl.stack.yaml` always
   wins). 126 committed + 52 local tests green.
5. ~~**TUI Phase 2**~~ — ✅ **DONE 2026-07-03**: the stage rail now RUNS the loop under the
   configured profile. Press `r` in the bare-`sembl-stack` wizard and the real `loop.run`
   (plan → execute → verify, retry-on-BLOCK) executes against the repo's `task.yaml`,
   streaming per-stage status (pending/running/pass/fail) into the rail and showing the final
   verdict panel; a PASS advances the resume pointer past the loop stages. Orchestration glue
   is `runner.py` (pure, headless — a TUI run and a headless `loop` run are byte-identical,
   same adapters wrapped in thin event-emitting proxies). The blocking loop runs in an
   executor with events drained on the app loop via a queue (no `call_from_thread`, which
   deadlocks a threaded worker under Textual's `run_test`). Still deferred (TODOs in
   `wizard.py`): CBM index trigger, reconcile panel, live deploy/postdeploy panels, MurphyScan
   readiness screen.

**Track 3 — the quality axis (L5.5) — ✅ CLOSED 2026-07-02 via `review: llm`; CodeRabbit
decoupled (confirmed third-party backend bug). History below (spec `SPEC-coderabbit-prep.md`):**
6. ✅ **L5.5 review-adapter shell** — `ReviewReport` artifact + `ReviewAdapter` protocol +
   `MockReviewAdapter` (validated file-level N+1/unsafe detector) + `CodeRabbitReviewAdapter`
   subprocess shell (PROVISIONAL, mock-tested, never run the real CLI) + `review` registry layer
   (mock default) + advisory `review` CLI.
7. ✅ **Planted quality-regression case 14** (`eval/corpus/14-quality-defect-passes-gate`) — the
   quality-axis analog of case 13: **passes the Sembl gate** (in-scope, evidenced, low-churn) but
   has a real N+1 defect the reviewer flags.
8. ✅ **The 2×2 eval** (`eval/two_axis.py`) — verified **gate_only=6, quality_only=1, both=0** ⇒
   each catches what the other misses, **complementary, not redundant.**
9. 🟡 **2026-07-02 — real CLI installed + agent-integrated, real auth BLOCKED.** Trial account
   open (org `speedvibecode`). No official Windows build exists yet; installed via the
   unofficial native port [Sukarth/CodeRabbit-Windows](https://github.com/Sukarth/CodeRabbit-Windows)
   (decompiles+recompiles the official Linux binary locally with Bun — script contents verified
   before running) → `coderabbit` v0.6.4, `doctor` all-green except auth. Installed the
   **official Claude Code plugin** (`coderabbit@claude-plugins-official` v1.1.1 via `claude
   plugin marketplace update && claude plugin install coderabbit`) and confirmed the **Codex
   plugin** is bundled+enabled (`coderabbit@openai-curated`) — both drive the same CLI binary.
   Real CLI contract (`coderabbit review --help`) has **no stdin/diff input**, only
   `--dir`/`--base`/`--type all|committed|uncommitted` against real git state — diverges from
   the original provisional `--stdin` design. Rewired `review_coderabbit.py`: `review(diff)`
   materializes the diff into a throwaway git repo (init + empty base commit + `git apply`)
   then runs `coderabbit review --agent --type uncommitted --dir <tmp>`, keeping the
   `ReviewAdapter` protocol diff-based (mock + the git-free 2×2 corpus untouched). **Live smoke
   test caught a real bug**: an unauthenticated run prints `{"type":"error",...}` to stdout with
   no `"findings"` key — old parser silently read that as CLEAN (false-clean); fixed to
   special-case `type == "error"` → UNKNOWN. 129 tests green (128 + 1 regression test).
   **Real auth still blocked — root-caused by decompiling the official CLI (read-only source
   trace, same Bun-decompile pipeline the Windows port uses), NOT port-specific.** Two distinct
   bugs found: (1) client-side, Windows-generic — `UZ()`'s environment detection checks only
   `$DISPLAY`/`xdg-open` (Linux-desktop-only, zero `process.platform` check anywhere in the
   bundle), always reporting headless on Windows and forcing the broken `coderabbit-cli://`
   fallback instead of the working localhost-callback server; fixed free with `$env:DISPLAY=1`
   (confirmed live: `authUrl` correctly switches to `http://127.0.0.1:<port>/callback`).
   (2) **server-side, not fixable locally** — even via the correct localhost callback, the tRPC
   client (`j6()`) correctly sends `Authorization: Bearer <accessToken>` (zero cookie logic
   anywhere in the client), but CodeRabbit's backend still rejects the org-listing call
   (`organizations.getAllOrgs`/`getAllOrgsForWorkspace`) demanding a cookie session — a genuine
   CodeRabbit backend bug/regression. Bug report filed with CodeRabbit (full trace, root-caused
   to the header logic). **Owner decision 2026-07-02: DECOUPLED CodeRabbit from the launch
   hard-gate** (`LAUNCH-PREP-JULY1.md` decision #8, archived 2026-07-05) — this is a confirmed
   third-party bug outside sembl's control; launch proceeds on the already-proven mock+shell+2×2
   thesis. `review: mock` stays the default; real-CLI wiring stays swap-ready, best-effort,
   revisited only if CodeRabbit fixes the bug or the owner buys Agentic-key credits.
10. ✅ **`review: llm` — the way out (2026-07-02, same day).** Rather than wait on CodeRabbit, built
   `LLMReviewAdapter` ("CodeRabbit at home", `review_llm.py`): drives a logged-in agent CLI the
   operator already has — default `claude -p` on the operator's own OAuth session (never a
   token), or `opencode` for cheap BYO models — with a strict reviewer prompt over the diff,
   mapped onto the same ReviewReport contract (UNKNOWN on any failure, advisory, never blocks).
   **Real 2×2 proven live** (`eval/two_axis.py --reviewer llm --model haiku`): 14/14 real
   reviews, 0 UNKNOWN — gate_only=4, quality_only=3 (incl. planted case 14 AND runtime-break
   case 13), both=2. The complementarity thesis now stands on a REAL reviewer, not just the
   mock. CodeRabbit demoted to an optional second real reviewer if it ever unblocks.
11. ✅ **CodeRabbit UNBLOCKED (2026-07-03).** CodeRabbit engineering deployed a backend fix after
   our bug report — `coderabbit auth status` green (Pro+ seat; owner-terminal login with
   `$env:DISPLAY="1"` for the separate client-side Windows bug). First real authenticated runs
   exposed three adapter-contract gaps, all fixed + regression-tested: (a) `--agent` streams
   **NDJSON events** (context/status/finding/complete lines), not a `{"findings":[...]}` doc —
   parser rewritten, truncated streams = UNKNOWN never CLEAN; (b) the CLI requires an explicit
   `--base` branch — throwaway repo pins `sembl-review-base`; (c) diffs modifying existing
   files couldn't `git apply` against an empty base — pre-image now synthesized from the
   diff's own hunks (before this, 12/14 corpus cases silently degraded to UNKNOWN). Live smoke:
   planted case 14 → real FINDINGS (SQL injection flagged critical + N+1 major). Back-to-back
   corpus runs hit CodeRabbit's **rate limit** (correctly UNKNOWN) — `eval/two_axis.py` gained
   `--patient` (waits out the window); full real CodeRabbit 2×2 ✅ **DONE 2026-07-04** after six
   failed monolithic attempts — root cause was the eval losing all progress on any mid-run death;
   fixed with `--checkpoint` (per-case review outcomes persisted as they land, reruns resume).
   Result, 14/14 real reviews, 0 UNKNOWN: **gate_only=4, quality_only=3** (planted case 14, runtime
   -break case 13, AND 01-greenfield-snake), **both=2, neither=5** — complementarity thesis now
   proven on BOTH real reviewers (llm + CodeRabbit), nearly identical grids.
   Status unchanged: optional second reviewer, never load-bearing.

**Track 4 — RSI-L1 readout (cheap, high-narrative):** per-executor iters-to-green + cost over the
corpus → the "measured selection" artifact. Advances the north star's first rung.

**Deep-audit backlog (codex across-the-board review, 2026-07-02).** Fixed same-day: gate
0.1.21 (contract self-edit BLOCK, traversal-safe paths, metadata lockstep) + stack hardening
(run-id validation, loop failed-status persistence, CBM repo_path contract, Vercel structured
failure, sembl+mcp as core deps, reviewer prompt treats diff as untrusted). Queued, in value order:
1. ~~**Verdict-to-source binding (L6.5)**~~ — ✅ **DONE 2026-07-03**: the loop stamps
   `verdict.raw["subject"] = {diff_sha256, files}` (`bind_verdict`, all three verdict paths incl.
   executor-failure/empty-diff BLOCKs); `apply` recomputes the patch hash and refuses a verdict
   issued for a different diff; `merge` compares the judged file set against
   `git diff --name-only into...source` and refuses on any delta (`--skip-binding-check` is the
   audited override, outcome recorded in `MergeRecord.data["source_binding"]`). Unbound
   pre-binding verdicts pass through with a recorded note (back-compat). 14 new tests.
2. ~~**`apply` dirty-tree guard**~~ — ✅ **DONE 2026-07-03** (same commit): `apply` refuses a
   dirty target tree (`.sembl/` run-store noise excluded) unless `--allow-dirty`; `--check`
   unaffected.
3. **Gate: staged-diff mode for the pre-commit hook** — the hook currently gates the whole
   worktree, not the commit being made.
4. **Gate: case-insensitive path comparison on Windows** — case-only mismatches can false-flag
   fabrication/out-of-scope; needs git-canonical paths, easy to get wrong, do deliberately.
Rejected with rationale: diff redaction in run artifacts (the diff must round-trip for `apply`;
`.sembl/` is local + gitignored — the gate's job is to CATCH a secret-bearing diff, not mask it);
postdeploy URL restriction (the URL is our own deploy adapter's output on a local tool);
`vendor/dist/build` generated-class (deliberate anti-false-alarm posture, forbidden_areas still
wins — document, don't change); absolute `source` globs in gate adapter configs (user-authored
config on a local CLI; the MCP server already runs with the user's own file access).

**Back half (spine ✅ + quality axis ✅ — gated now on owner dogfood):** owner dogfoods the
onboarded loop daily (starts the RSI-L1 feed) · Apache-2.0 relicense (both repos) · gate 0.2.0
MCP ergonomics · MurphyScan deep audit · PyPI `sembl-stack` 0.1.0 + public site · breadth →
~50 adapters (2–4/layer, demand-curated) · full O5 (hosted/team secret-permission-sandbox) · private beta
(3–5 partners, the moment a stranger can run the spine) · MurphyScan green on the flagship · then
**public launch (Track A)**: full through-deploy, beats-prompt-chains, ~50-tool product.

**Track 5 — ideation + chat shell (🆕 locked 2026-07-05, owner-personal-use priority — see
`SPEC-ideation-and-chat-shell.md`):**
1. ~~**L0.5 Idea → Spec**~~ — ✅ **DONE 2026-07-05.** `ideation.py` (pure core: pitch detection,
   fixed slot-schema prompt + tolerant JSON parser with a never-raises fallback, `spec.json`/
   `spec.md` read/write) + `guide.py`'s `_ideation_step` (wired into `launch()` right after the
   agent step): finds `product.md`/`PRD.md`/`idea.md`, offers to draft a Spec via the configured
   executor (free-text stack candidates + why, open questions, data model sketch, non-goals —
   **not** `presets.py`'s gate-mode menu, corrected in `SPEC-ideation-and-chat-shell.md` §1), then
   walks the user through confirming/editing every slot before writing `spec.json` (machine) +
   `spec.md` (human). Silent no-op for repos with no pitch doc or an existing spec — never
   interrupts an existing project. 22 new tests (`tests/test_ideation.py`) + a scripted end-to-end
   smoke run, 315 total passing. *Remaining, deferred:* the "no file, paste a paragraph" fallback
   path (SPEC §1 mentions it; skipped this pass — scaffold_demo pre-writes `task.yaml` before this
   step runs, so the "greenfield" trigger needs its own design, not a quick add).
2. ~~**L1 real scaffold**~~ — ✅ **DONE 2026-07-05.** No new mechanism, no new LLM touch point:
   `ideation.py`'s `spec_to_task_text` (pure string composition) turns a confirmed Spec into a real
   task description; `guide.py`'s `_ideation_step` (now taking a `fresh_scaffold` flag threaded
   from `launch()`) overwrites `scaffold.py`'s placeholder `task.yaml` with it and resets
   `bounds.json`'s demo `["app/"]` bound back to unscoped — the very next `_task_step` prefills the
   real task and lets its existing path-suggestion flow (AI-suggest or `suggest_editable`) pick
   real paths, instead of the demo's stale `app/` bound. The actual scaffolding work still runs
   through the same task→bounds→execute→gate loop every other change goes through — this is the
   `SPEC-ideation-and-chat-shell.md` §5 "update code" pattern, reused a step earlier, not a new one.
   A pre-existing repo's own `task.yaml` is never touched (`fresh_scaffold` is only true right after
   `scaffold_demo()` just ran). 3 new tests (`spec_to_task_text`) + a scripted end-to-end smoke run
   proving the placeholder task/bounds are correctly replaced and `existing_answers()` sees the new
   ones, 318 total passing.
3. **Ambient fused graph + drift daemon** — fuse the doc graph (Spec) and code graph (CBM) into
   one; ambient watcher writes a cheap immediate flag (draft ADR stub) the moment drift is
   detected; review batches at natural checkpoints (opening the chat shell, or `review drift`).
   Reopens `memory-plane-hypothesis.md` Claim B under a revised G0 (owner-dogfood gate, not
   stranger-demand) — G3 (CBM stays swappable behind the `ContextGraph` seam) unchanged.
4. **Drift resolution** — tri-state per graph node (code ahead / spec ahead / contradictory) +
   three chat commands: `update spec` (LLM rewrites just that node, reviewed diff, never silent),
   `update code` (seeds a new `Task`+`Bounds` from the spec delta, re-enters the same
   task→bounds→execute→gate loop — no new mechanism), `mark exception` (recorded as a CBM ADR).
5. **Chat shell** — thin custom transcript UI rendering the artifact contract as chat blocks;
   retires `wizard.py`; reuses `runner.py`'s headless event stream and `guide.py`'s
   `ai_suggest_paths` precedent for the task-parse block. Fixed deterministic stage sequence, two
   scoped LLM touch points only (parse, explain) — see O7/O8.
6. **First concrete slice** — task → suggested bounds + graph-diff preview (build this slice
   first, before the full chat shell, to prove the pattern).
7. **Onboarding/scaling views** — query-first over the fused graph (mirrors how CBM's own MCP
   tools onboard an agent cold today); one generated root index (hand-authored-authoritative vs.
   auto-derived); module-level drift rollup ("12/40 modules have drift, ranked by
   connectedness/staleness") instead of a flat per-node list.
8. **Deferred, not yet designed:** platform-level credential/integration vault — generalize
   `profile.py`'s BYO-executor-key pattern to every integration (GitHub, Vercel, Supabase, domain,
   …), connected once and reused across every project. Real security surface (storage, scoping);
   needs its own design pass before building.

## 10. The delegation method (the operating model)
Claude = **orchestration only**: pin a precise spec (all judgment + exact acceptance numbers) →
a cheap CLI **executes** → Claude **reviews the diff + re-verifies** (never trusts the agent's
self-check) → commit + push. Proven on the through-deploy evidence, the merge stage, and the
WS-C onboarding screens (all clean or near-clean on first review). Keep every delegation spec
fully pinned so each delegated session is execution-only.

**Roster (owner directive 2026-07-02): Claude + codex GPT-5.5 ONLY — agy retired** (TTY-only
auth friction). codex effort: `medium` for mechanical builds, `xhigh`/`high` for tough ones or
deep reviews. Claude keeps all credential-sensitive paths + review-the-review.

## 11. Tooling reality
- **codex (GPT-5.5)** — the delegate + independent reviewer. Headless recipe on this box:
  `codex exec --cd <repo> -s workspace-write|read-only -c 'mcp_servers={}'
  -c model_reasoning_effort="medium" - < prompt.md`. Two LOAD-BEARING gotchas: MCP must be
  disabled per-invocation (the CBM server wedges codex), and the prompt MUST be fed on stdin
  via `-` from a file — passing it as an argv argument wedges codex at startup forever when
  stdin is a non-TTY pipe.
- **opencode + MiniMax-M3** — `opencode -m tokenrouter/MiniMax-M3` (native exe to preserve
  multi-line prompts); a working cheap L3 *executor inside the loop*, but stalled ~1h on a
  single-shot build task — don't use it for delegated builds.
- **agy (Antigravity CLI) — RETIRED 2026-07-02** (needed the owner's foreground TTY for auth;
  replaced by codex).
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
- `memory-plane-hypothesis.md` — why CBM stays a per-PR tool, not a memory plane (Claim B reopened
  2026-07-05 under a revised gate — see `SPEC-ideation-and-chat-shell.md`).
- `SPEC-merge-stage.md` — the executed merge-stage build spec (record of the delegation method).
- `SPEC-ideation-and-chat-shell.md` — 🆕 the locked ideation + chat-shell direction (O7/O8, Track 5).
