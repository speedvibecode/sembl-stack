# Persistent Memory Plane — HYPOTHESIS (parked)

> Status: **HYPOTHESIS, not locked, PARKED behind Phase 1.** Created 2026-06-17.
> Nothing here is built or committed-to. This doc exists so the idea is captured and
> diffable, **not** so it jumps the queue. Promotion to a [LOCKED] decision requires the
> Phase-1 proofs (live OpenCode loop PASS + the WITH-vs-WITHOUT-Sembl test) to land first,
> and the decision gates at the bottom to clear. See PLATFORM-MAP §9 and the NEXT list in
> the sembl handoff.

---

## 0. The claim under test

> **Can a persistent, incrementally-synced code-memory graph (candidate:
> [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp), MIT, C, MCP-native)
> be promoted from an L1 *substrate* — one adapter behind the `ContextGraph` protocol — to
> the platform's *persistent memory plane*: a shared, queryable backbone that more than one
> stage reads and writes, and that gives the factory long-term memory of the codebase?**

This is a *Claim B* (the "spine, not substrate" framing). It is deliberately separated
from *Claim A* — "codebase-memory-mcp (CBM) is a strictly-better engine behind the existing
`ContextGraph` protocol" — which is low-risk, reversible, and can proceed independently
(see `sembl_stack/contextgraph.py`, adapter slot already exists next to symgraph/codegraph).
**This doc is only about Claim B.** Do not let approval of A be read as approval of B.

## 1. Why it's even tempting (the honest upside)

CBM is categorically more than symgraph. symgraph is a *stateless* binary you re-run to get
a file-level module graph (EXP-05: a *partial* fix — 1-hop recovers 35–57% of sibling files,
needs a precise seed, does nothing for the no-seed majority). CBM is:

- **Persistent + incrementally synced** — SQLite-backed knowledge graph, git-watcher keeps
  it current, committable `graph.db.zst` snapshot. State survives across runs.
- **Symbol-level, not just file-level** — and exposes `detect_changes` (git diff → affected
  symbols) and `trace_path` (call-chain BFS) as first-class MCP tools. That is exactly the
  primitive the scope/impact check wants, at a finer grain than `module-graph` gives.
- **MCP-native** — matches the platform's load-bearing surface (L0 hub). Its installer
  already auto-wires the exact L2 executors we consume (OpenCode, Claude Code, Aider, Kiro).
- **Deterministic** — Cypher engine, no LLM in the query. Does **not** violate the
  "no LLM in the gate" rule (PLATFORM-MAP §8) or the process-RSI non-circularity argument.
- **MIT** — consuming it is CONSUME-behind-an-adapter, not "build L4 ourselves." Clears the
  no-parasite rule (PLATFORM-MAP §1, "what we OWN").

## 2. What "memory plane" would mean against the locked model

The locked model already has a knowledge plane (**Plane C — Brain**) and a per-run state
substrate (the **artifact contract**, `.sembl/runs/<id>/`, PLATFORM-MAP §1–2). The
hypothesis is that CBM becomes the *durable, cross-run, code-grounded* layer that sits
**between** them — what neither currently provides:

| Layer | Scope | Lifetime | Today | Under this hypothesis |
|---|---|---|---|---|
| Artifact contract (`.sembl/runs/`) | one run | per-run, local | ✅ locked | unchanged |
| Brain (Obsidian/specs/rules) | human knowledge | durable, hand-authored | ✅ locked | unchanged |
| **Code-memory graph** | the codebase itself | **durable, auto-synced** | ⛔ none (symgraph is stateless) | **CBM = this plane** |

Stages that would *read* it: L1 (Context: structure, impact), L2 (Bounds: seed expansion
from `detect_changes`), L5 (Verify: symbol-level scope/impact). Stages that might *write* to
it: L6 (Trace/run outcomes annotated onto graph nodes — feeding the process-RSI signal,
`process-self-improvement.md` rung L1/L2). CBM's own `manage_adr` (Architecture Decision
Records) overlaps the Brain plane and is a candidate bridge.

**The one architectural change Claim B implies (and A does not):** today the `ContextGraph`
protocol is a *seam that keeps any substrate non-load-bearing* (LatentGraph → Joern →
symgraph all stayed behind it, "context not gate"). Promoting CBM to a memory plane means
**something other than L1 now depends on it persisting** — that is a real coupling increase,
and it is the thing this hypothesis must justify, not assume.

## 3. The case against (why this stays parked)

1. **The anti-trap binds.** The locked open question is **DEMAND, not capability**
   (handoff guardrail; PLATFORM-MAP §8). A richer graph is a capability upgrade — it does
   **not** move whether anyone wants the gate. CBM is the 4th substrate in the log;
   substrate-chasing is the comfortable way to avoid the two blocked Phase-1 proofs. Those
   proofs come first, full stop.
2. **Coupling we deliberately avoided.** The `ContextGraph` protocol exists *so that* no
   single third-party project is load-bearing for the gate's identity. "Memory plane"
   reverses that for a single-maintainer C project we don't control. The determinism /
   auditability story is clean today precisely because the gate depends on *its own*
   deterministic checks, not on someone else's graph being correct and present.
3. **Drift toward the falsified edge.** Symbol-level impact could power a *new deterministic
   scope check* ("change touches symbols the spec never authorized / breaks N callers") —
   legitimately in-scope. But the moment graph richness starts informing *whether the code
   is good*, we are back in the reviewer space EXP-01 falsified as our edge. Any memory-plane
   use must stay strictly **scope/impact**, never quality (PLATFORM-MAP §8, O3 trap-guard).
4. **Goodhart, at the plane level.** If run outcomes get written back onto graph nodes and
   feed routing (process-RSI), the memory plane becomes part of the optimizer's state —
   inheriting the Goodhart risk in `process-self-improvement.md`. That's not disqualifying,
   but it raises the bar for what "correct" means here.

## 4. Decision gates — what must be true to promote (in order)

- **G0 — Phase 1 proofs landed.** Live OpenCode loop PASS *and* the WITH-vs-WITHOUT-Sembl
  test, per O3. Until then this doc does not get built. (Non-negotiable, anti-trap.)
- **G1 — Claim A proven valuable first.** Ship CBM as a `CodebaseMemoryGraph` adapter behind
  the existing protocol and show `detect_changes`-seeded, 1-hop expansion beats symgraph on
  the EXP-05 precise-seed re-test (recall **and** precision both high). If A doesn't pay,
  B is moot.
- **G2 — Operational due diligence on THIS box:**
  - Windows static binary actually indexes a real repo here (claimed zero-dep; verify).
  - `graph.db.zst` snapshot format stable enough to commit / diff / share.
  - Index/sync cost acceptable on our corpus; incremental watcher behaves.
- **G3 — Sustainability check.** DeusData = single-maintainer risk if it becomes a *plane*.
  Mitigation must exist: the protocol seam stays in place so CBM is *replaceable* even as
  the plane (codegraph or a vendored fallback as the escape hatch). If we can't cheaply
  swap it out, it does **not** become load-bearing.
- **G4 — A use that needs persistence/cross-run.** Name at least one capability that the
  stateless adapter (Claim A) genuinely *cannot* deliver — e.g. cross-run impact memory
  feeding process-RSI routing, or a committed shared graph for team/CI. If every use is
  served by per-run indexing, there is no memory plane; there is just a better adapter.

## 5. Smallest honest experiment (when G0 clears)

Do **not** re-architect to find out. The cheap probe is: wire the `CodebaseMemoryGraph`
adapter (Claim A work), then run the EXP-05 precise-seed re-test with `detect_changes` as
the seed source. One number decides whether symbol-level impact is real lift over file-level
`module-graph`. Only if that pays — and only if G4 names a persistence-only use — does the
"plane" question become live. Everything above G1 is speculative until that number exists.

## 6. Relation to existing locked docs

- PLATFORM-MAP §1 ("what we OWN" / CONSUME-behind-adapter) — CBM is CONSUME; this doc does
  not propose owning it. The seam (`ContextGraph` protocol) stays.
- PLATFORM-MAP §8 + O3 — memory-plane use is scope/impact only; never a quality claim.
- `process-self-improvement.md` rungs L1–L2 — the only *new* capability a true memory plane
  unlocks (cross-run, code-grounded outcome memory) lives here; that is the steel-man for
  Claim B, and also where the Goodhart guard applies.

---

## LEDGER

| # | Item | State |
|---|---|---|
| H1 | CBM as a `ContextGraph` adapter (Claim A) | **[OPEN]** — approved direction, reversible; not in this doc's scope |
| H2 | CBM as the persistent memory plane (Claim B) | **[HYPOTHESIS / PARKED]** — gated by G0–G4 |
| H3 | Run-outcome write-back onto graph nodes (process-RSI signal) | **[SPECULATIVE]** — only if H2 + G4 |
