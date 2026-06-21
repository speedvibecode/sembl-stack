# Roadmap to Product — from a working loop to the swappable factory

> Status: working plan as of 2026-06-17 (evening), owner-led. Decisions marked **[LOCKED]**
> are the basis we execute on; **[OPEN]** items need an owner call. This doc subordinates to
> `PLATFORM-MAP.md` (the architecture) and inherits its guardrails. It exists to keep the
> build honest: every milestone is gated by evidence, not vibes.
>
> **Update 2026-06-20:** several items below this baseline have since landed — the `run
> inspect`/`apply` workflow exists, failure/cost/latency hardening was added, and the Aider
> and Claude L3 adapters are wired and pushed. Where older sections describe those as
> "remaining," treat them as historical, not current source of truth.
>
> **Update 2026-06-20 (PM) — owner call, see §1b [supersedes S1 + §3 ordering]:** the launch
> bar was **RAISED**. Launch now = complete execution **through deploy + post-deploy gate +
> verticals**, beating prompt-chain/`/goal` baselines (O3 made public), with **~50 adapters
> across layers** (≈2–4/layer). This pulls Phase 2 (L7/L8) and a slice of Phase 3 (breadth)
> *before* launch and puts the **O5 security/permission model on the critical path**. §3/§4
> are re-sequenced to match. A new per-PR **spec-graph↔code-graph reconciliation agent**
> (advisory, human-reconciled, **NOT** the Sembl gate) is added — see §1b + PLATFORM-MAP.

---

## 0. Where we are (the honest baseline)

The short loop is **proven live** (2026-06-17): a real Claude Code agent built a playable
Snake game end-to-end — Spec Kit `tasks.md` → L2 Sembl bounds → L3 agent → L4 clone →
L5 Sembl gate → LangGraph — PASS; a second feature PASS in-bounds; a rogue diff BLOCKed on
all claim-vs-reality checks. See the handoff + [[sembl-stack-platform]].

That is a **capability** milestone, not a product. A stranger cannot yet run the full
pipeline; it is one task, one executor, mostly happy-path; the loop's value is not yet
**measured**; nothing is **swappable in practice** (one real executor wired). The gap to
product is **evidence + usability + proven swap**, not more surface area.

## 1. The strategy [LOCKED owner call, 2026-06-17]

**Run B (measure) and C (build it real) in parallel. Defer A (public launch) until the loop
is proven and a stranger can run it.** Rationale: the differentiator is the *open swappable
factory*, not the standalone gate; launching the gate alone invites "can't Claude already do
this?" A public launch only earns attention once we can show a proven, end-to-end loop.

### Two guardrails that keep B+C from becoming the capability trap [LOCKED]
1. **Depth over breadth.** Swappability is proven by **2–3 curated adapters per layer, not
   100.** This is the existing platform lock ("curated, not exhaustive"; "personal-first…
   wire your ~12 tools now; community catalog later"). Integrating 100 tools before anyone
   uses it is months of plumbing that does not change the thesis and indefinitely delays the
   evidence. The 100-tool catalog is a Phase-3, demand-pulled effort.
2. **A winnable bar, not "better than everything."** "The gate catches more than every tool"
   is FALSIFIED ([[foundation-falsified]]). The launchable claim is **open + deterministic +
   swappable + through-deploy-accountable**, with the loop *provably reducing bad/out-of-
   scope/fabricated merges* (O3) — not out-detecting CodeRabbit. Set every gate against O3,
   never against "beats tool X at quality."

## 1b. OWNER CALL 2026-06-20 (PM) — launch bar RAISED [LOCKED; supersedes S1 + §3 order]

The product we want to be judged on is the **whole accountable chain end-to-end**, not the
standalone gate. Therefore:

- **New launch bar (S7) [LOCKED].** Public launch (Track A) is earned only when ALL hold:
  1. **Complete execution through deploy** — spec → **spec-graph** → bounds → execute →
     **code-graph** → **per-PR spec/code reconciliation (S9)** → Sembl gate → quality review →
     merge → **deploy (Vercel/Supabase/etc.)** → **post-deploy gate (L8)** — runs on a real app.
  2. **Beats prompt-chains / `/goal`** — the O3 WITH-vs-WITHOUT number, extended *through
     deploy*, made into a public artifact. Equal on the happy path; decisively safer on the
     bad path (caught / bad-merge delta, false-alarm rate reported beside it).
  3. **~50 adapters across layers** — ≈2–4 per layer over the ~8 spine + ~13 Plane-B layers.
     This **reconciles S2** ("depth over breadth"): breadth spread thin across many layers,
     NOT a 100-tool single-layer catalog. The 100-tool community catalog stays Phase-3.
- **Cost owned honestly.** This pulls Phase 2 (L7 deploy + L8 post-deploy gate) and part of
  Phase 3 (breadth) *before* launch — months, not weeks.
- **O5 is now critical path (S8) [LOCKED].** Real through-deploy needs deploy credentials
  flowing safely → the secret/permission/sandbox model is no longer parked; it gates
  L7/L8/verticals and any shared use.
- **Anti-trap discipline retained (non-negotiable).** To avoid the capability trap this
  platform warns against repeatedly: prove the **EVIDENCE + a depth-1 end-to-end
  through-deploy spine on ONE flagship app FIRST**; fan out to ~50 adapters only AFTER that
  number exists. Breadth is the back half, never the thing that delays the proof.

### New stage — per-PR SpecGraph↔CodeGraph reconciliation agent (S9) [LOCKED; NOT Sembl]
- **Spawns per pull request** — not continuous, not a gate equivalent. Compares the
  **`SpecGraph`** (graph of the spec) against the **`CodeGraph`** (e.g. via
  [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)) and reports whether
  they point at the same thing.
- **Advisory + human-reconciled:** the user decides whether to update the spec-graph or the
  code-graph. It does **not** BLOCK; it surfaces divergence. Distinct from L5 verify (which
  checks the diff's claim-vs-reality at the boundary).
- **Cheap by design:** a **haiku-class** model suffices *given* clean `SpecGraph` +
  `CodeGraph` artifacts.
- **Architecture impact:** introduces a new **`SpecGraph` artifact** + a reconciliation stage
  (recorded in PLATFORM-MAP §2/§3). It **CONSUMES** a code graph — a *Claim-A-level* use of
  CBM ([[memory-plane-hypothesis]]); per-PR indexing suffices, so it does **NOT** require
  promoting CBM to a load-bearing memory plane.

## 2. The two tracks

### Track C — make it real and genuinely usable (the build)
- **C1 — Harden the loop into an engine, not a demo.** Failure modes: executor timeout,
  empty diff, partial change, non-zero exit, no-op retry. Real BLOCK→PASS retry with a *real*
  agent (not just the mock). Capture cost + latency per run in the run store.
- **C2 — Prove the swap.** 2–3 curated adapters per layer behind the existing Protocols:
  executors (Claude ✓ + Aider/OpenCode), context (symgraph ✓ + codegraph), sandbox
  (worktree ✓ + Docker/E2B). Demonstrate a **one-line config swap** leaving the gate's
  verdict honest. *This* is the swappable factory — minimally, two hot-swappable executors.
- **C3 — Bounds quality (the real value lever).** The loop is only as good as the contract
  ([[exp04-falsealarm-finding]]; today's greenfield finding). Precise Spec-Kit seeds, the
  `clarify` stage, context-graph bounds-expansion (EXP-05, wired into the loop, not just the
  CLI).
- **C4 — A surface a stranger can run.** The O6 TUI run dashboard (CI-run-page UX) + real
  onboarding (presets: `just-gate`, `gate+sandbox`, `full-loop`). This closes the "nowhere to
  use it" gap and is the prerequisite for any beta tester.

### Track B — measure it, continuously (the evidence)
- **B1 — Define the O3 metric first.** Process correctness: bad/out-of-scope/forbidden/
  fabricated changes caught-or-corrected before merge + iterations-to-green, WITH vs WITHOUT
  Sembl. Quality ONLY as gate-caught regressions + a no-harm baseline. Trap-guard: "better
  code" is never the success criterion.
- **B2 — Build a 10–20 task corpus** (mix: greenfield create, in-repo feature, refactor,
  forbidden-area temptation, fabrication-prone). Captured real diffs allowed (no live agent
  required for every cell).
- **B3 — The WITH/WITHOUT harness** over the run store. Run it *as* C lands each stage, so
  every addition is justified by the number. Same dataset seeds **process-RSI L1** (measured
  selection: "executor X passes in 1.3 attempts at $0.04 vs Y at 2.1/$0.11").

## 3. The gate sequence to product [RE-SEQUENCED 2026-06-20 PM for the raised bar (S7); evidence-first preserved]

```
EVIDENCE-FIRST (anti-trap — nothing fans out until the number exists):
  B2 O3 corpus + B3 WITH/WITHOUT harness → the number that beats prompt-chains/`/goal`
        AND
  depth-1 end-to-end THROUGH-DEPLOY spine on ONE flagship app
  (spec → spec-graph → bounds → exec → code-graph → reconcile(S9) → gate → review →
   merge → deploy → post-deploy gate)
        AND
  O5 security/permission model sufficient for real deploy creds (now critical path, S8)
        ↓
  BREADTH: fan out to ~50 adapters (≈2–4 per layer across spine + Plane-B) — back half
        ↓
  C4 stranger-runnable surface (TUI + presets) + private beta (3–5 partners), woven in
        ↓
  A — public launch: the full through-deploy, beats-prompt-chains, ~50-tool product
        ↓
  demand-pulled: 100-tool community catalog, hosted/web surface, process-RSI L2–L4
```

**Beta is not launch.** It is the cheapest insurance against building the wrong thing in a
vacuum — recruited the moment the through-deploy spine is runnable end-to-end by someone who
isn't us. **Evidence + the depth-1 spine come before breadth, always.**

## 4. Immediate execution order [RE-SEQUENCED 2026-06-20 PM — what we build next]

> Items 1–3 of the old order (L1-into-loop, C1 hardening, 2nd executor) are **DONE** — see
> PROGRESS LOG. The new order is driven by the raised bar (S7), evidence-first.

1. **Evidence harness FIRST (B1–B3).** O3 is defined (`eval-metric-O3.md`). Build the 10–20
   task corpus (B2) and stand up the WITH/WITHOUT harness (B3) over the run store. **This is
   also the public "beats prompt-chains / `/goal`" demo** — the WITHOUT arm *is* the prompt
   chain. No new surface area until this number exists.
2. **Depth-1 through-deploy spine.** Extend the proven L1–L6 loop through **merge → L7 deploy
   (Vercel+Supabase) → L8 post-deploy gate** on ONE flagship app. Add the **`SpecGraph`
   artifact + per-PR reconciliation agent (S9)** and a **quality-review integration**
   (CodeRabbit/codex) at L5.5. Depth-1 everywhere (one tool per layer).
3. **O5 security model.** The minimum secret/permission/sandbox model to make step 2's deploy
   real and safe. **[OPEN call:** local-creds-first vs. full model — see S10.]
4. **Breadth → ~50 adapters.** Only now: 2–4 per layer across spine + Plane-B.
5. **C4 (TUI + presets) + private beta**, woven into 2–4; beta the moment a stranger can run
   the end-to-end through-deploy spine.

---

## LEDGER

| # | Item | State |
|---|---|---|
| S1 | Strategy = B+C parallel, defer public A | **[LOCKED]** — **AMENDED 2026-06-20 PM by S7:** launch no longer deferred-minimal; raised to full through-deploy (still evidence-first) |
| S2 | Depth over breadth (2–3 adapters/layer, not 100) | **[LOCKED]** — reconciled by S7: ~50 = ≈2–4/layer across many layers; 100-catalog still Phase-3 |
| S3 | Winnable bar = O3 + usable end-to-end, not "beats every tool" | **[LOCKED]** — extended by S7 to include through-deploy accountability |
| S4 | Private beta woven into C (3–5 partners) before public launch | **[LOCKED]** |
| S5 | Which 2nd executor for the swap demo (Aider vs fix OpenCode) | **[RESOLVED]** — Aider, proven live via NIM llama-3.3-70b; MiniMax-M3 via OpenCode added 2026-06-20 (3rd live executor) |
| S6 | Corpus source (synthetic vs captured real PRs) | **[OPEN]** |
| S7 | Launch bar RAISED: complete through-deploy + beats-prompt-chains + ~50 adapters | **[LOCKED 2026-06-20 PM]** — supersedes S1 ordering; §1b |
| S8 | O5 secret/permission/sandbox model on the critical path (gates L7/L8/verticals) | **[LOCKED 2026-06-20 PM]** |
| S9 | Per-PR SpecGraph↔CodeGraph reconciliation agent (advisory, human-reconciled, NOT the gate) | **[LOCKED 2026-06-20 PM]** — needs `SpecGraph` artifact |
| S10 | O5 shape for the flagship: local-creds-first vs. full secret/permission model | **[RESOLVED 2026-06-20 PM]** — local-creds-first; full model is a separate pre-public-launch workstream |
| S11 | Flagship app for the depth-1 through-deploy demo | **[RESOLVED 2026-06-20 PM]** — **feedback board** (auth + DB writes/reads) on Vercel+Supabase |

## PROGRESS LOG

- **2026-06-20 (PM) — owner call: launch bar RAISED (S7–S9), §3/§4 re-sequenced.** See §1b.
  **Baseline refresh:** sembl **0.1.20 live on PyPI** (gate ignores Python bytecode/tool-caches
  as generated-class); **MiniMax-M3 via OpenCode is a 3rd live executor** on Windows (3 path
  bugs fixed: `--dir` isolation, UTF-8 capture, prompt-newline truncation); the **C1 no-op /
  empty-diff BLOCK** landed and is in master; two flagship demos built (a link-shortener built
  end-to-end through the gated loop + a rogue-patch BLOCK-on-5-checks); Proof page live
  (sembl.vercel.app/proof). sembl and sembl-stack versioning **DECOUPLED** (separate packages,
  independent version lines). Old §4 items 1–3 (L1-into-loop, C1 hardening, 2nd executor) are
  therefore DONE; the new §4 starts at the evidence harness.
- **2026-06-17 — C2 swap proof DONE.** Two real, hot-swappable executors behind one config
  line: Claude Code (`execute: claude`) and Aider (`execute: aider`, OpenAI-compatible /
  NVIDIA NIM). Both drive green loops; Aider proven live (NIM llama-3.3-70b → real code →
  gate PASS).
- **2026-06-17 — C1 (in progress).** First hardening item shipped: a no-op execution (empty
  diff *or* an empty/contentless file from an errored/dead-model executor) now BLOCKs with
  actionable feedback instead of false-passing. Surfaced live by a NIM 410 end-of-life model
  and by MiniMax-M3 returning empty completions. Remaining C1: executor timeout/exit-code
  surfacing, partial-change handling, cost+latency capture per run.
- **Model note:** on this NIM key, `minimaxai/minimax-m3` returns empty completions to aider
  (0 tokens, `choices=[]`) and `qwen2.5-coder-32b` is end-of-life (410). Use
  `meta/llama-3.3-70b-instruct` (verified working) for live aider runs.
