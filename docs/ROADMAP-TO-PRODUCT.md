# Roadmap to Product — from a working loop to the swappable factory

> Status: working plan as of 2026-06-17 (evening), owner-led. Decisions marked **[LOCKED]**
> are the basis we execute on; **[OPEN]** items need an owner call. This doc subordinates to
> `PLATFORM-MAP.md` (the architecture) and inherits its guardrails. It exists to keep the
> build honest: every milestone is gated by evidence, not vibes.

---

## 0. Where we are (the honest baseline)

The short loop is **proven live** (2026-06-17): a real Claude Code agent built a playable
Snake game end-to-end — Spec Kit `tasks.md` → L2 Sembl bounds → L3 agent → L4 worktree →
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

## 3. The gate sequence to product [LOCKED order]

```
C1 hardened + C2 swap proven + C4 a stranger can run it
        AND
B3 number shows the loop reduces bad merges (O3)
        ↓
private beta: 3–5 design partners (woven INTO C, not after) — answers
"how would someone actually use this" by watching real use
        ↓
iterate on their usage
        ↓
A — public open-pipeline launch (MCP registry, marketplace, Reddit)
        ↓
demand-pulled: L7 deploy + L8 post-deploy gate, the 100-tool community catalog,
hosted/web surface, process-RSI L2–L4
```

**Beta is not launch.** It is the cheapest insurance against building the wrong thing in a
vacuum — recruited the moment the loop is runnable end-to-end by someone who isn't us.

## 4. Immediate execution order (this is what we build next)

1. **C2/C3 down-payment — wire L1 context into the loop** so the running loop is L1→L2→L3→
   L4→L5 (bounds-expansion in the plan stage, not just the `bounds --expand` CLI). Makes the
   live loop the *fuller* pipeline and demonstrates a second layer participating.
2. **C1 — loop hardening** for the obvious failure modes + cost/latency capture.
3. **C2 — second executor adapter** (Aider or fix OpenCode) → the one-line swap demo.
4. **B1–B3 — the harness** stood up against the run store, O3 defined first.
5. Then **C4 (TUI/onboarding)** → beta gate.

---

## LEDGER

| # | Item | State |
|---|---|---|
| S1 | Strategy = B+C parallel, defer public A | **[LOCKED]** |
| S2 | Depth over breadth (2–3 adapters/layer, not 100) | **[LOCKED]** |
| S3 | Winnable bar = O3 + usable end-to-end, not "beats every tool" | **[LOCKED]** |
| S4 | Private beta woven into C (3–5 partners) before public launch | **[LOCKED]** |
| S5 | Which 2nd executor for the swap demo (Aider vs fix OpenCode) | **[OPEN]** |
| S6 | Corpus source (synthetic vs captured real PRs) | **[OPEN]** |
