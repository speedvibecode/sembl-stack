# LAUNCH-PREP — the July-1 turnkey runbook

> **Purpose.** On 2026-07-01 you open Claude (or Codex), fire up agents, and execute — no
> re-derivation, no "where were we." This doc is the entry point: it states the launch bar, the
> exact ordered workstreams (each fire-able), which agent runs each, and the gotchas. It is NOT a
> schedule — nothing auto-runs; you drive it. Source-of-truth architecture/decisions stay in
> [PROCESS-ACTION-PLAN.md](PROCESS-ACTION-PLAN.md); this is the execution overlay.
>
> **Method (locked).** Claude pins the spec + reviews/re-verifies (never trusts an agent's
> self-check); cheap CLIs execute from the pinned spec. Claude = orchestration/judgment only.
>
> **North star framing (owner, 2026-06-22).** Launch is the *prerequisite* to the RSI vision —
> we only get to "100% of the process self-improvement" by shipping first. So: launch-first,
> breadth-and-RSI-after.

---

## 0. Pre-flight (do these before firing anything — ~10 min)

1. **Decide the spine merge.** `ws2-through-deploy-spine` is **18 commits ahead of master**, fully
   codex-reviewed and remediated (commit `0fb2d10`), all green. First action is either: merge to
   master, or open the PR for one final codex pass. Until merged, every WS below branches off it.
2. **Tooling gotchas (both bit us 2026-06-22 — don't relearn):**
   - **codex wedges on the CBM MCP server** → comment out that MCP block in the codex config before launching it.
   - **pytest basetemp must be OFF the repo tree** → `--basetemp=<dir outside the repo>`; an in-repo
     basetemp makes `test_source_tree_status_skips_git_and_store` read the parent repo's dirty files,
     and the AppData temp default fails on this box.
   - **venv has no pip** → use `uv pip install`; run Python as `.venv\Scripts\python.exe`.
   - **agy needs a TTY** → owner runs it in their own foreground terminal; it can't run from Claude's shell.
3. **Agent roster (per [operating-model]):** Claude = pin/review/QA. **agy** (Gemini-3.5-Flash,
   `agy -p "<prompt>" --dangerously-skip-permissions --model gemini-3.5-flash`) = mechanical builds
   from pinned specs. **codex** (GPT-5.5) = tough tasks + review. **opencode/MiniMax-M3** = cheap
   executor fallback. Token-saving is the point: spec is judgment, agent types the lines.

---

## 1. Where the three repos stand + target shape

| Repo | Path | State today | Target for launch |
|------|------|-------------|-------------------|
| **sembl** (gate) | `Downloads/sembl` | `master`, **0.1.20 live on PyPI**, clean. The load-bearing core; mature. | Stay green; optional `0.2.0` IDE/MCP polish (NOT launch-blocking). Keep the version-lockstep CI guard passing. |
| **sembl-stack** (factory) | `Downloads/sembl-stack` | `ws2-through-deploy-spine`, spine **11/11**, reviewed+hardened. | Merge → TUI Phase-1 onboarding (BYO-credits) → CodeRabbit real → MurphyScan green → breadth → beta-runnable. |
| **sembl-site** (public) | `Downloads/sembl-site` | static site on Vercel (`index/docs/proof/changelog`), clean. | Public launch page + the WITH/WITHOUT proof artifact + replayed-run view; docs reconciled to the shipped product. |

---

## 2. Ordered workstreams — fire-up-and-go

Grouped **P0 = must-have for a credible public launch**, **P1 = breadth + operational polish**,
**P2 = post-launch**. Each item: repo · agent · what · acceptance · depends-on. Items marked
**[spec pinned]** have a ready `docs/SPEC-*.md`; items marked **[pin on request]** still need me to
write the spec — say the word before July 1 and I'll pin them so they're equally turnkey.

### P0 — credible public launch
- **WS-A · Merge the spine** — sembl-stack · Claude/owner. Merge `ws2-through-deploy-spine` → master
  (or PR + final codex). _Acceptance:_ master green, branch retired. _Depends:_ pre-flight §0.1.
- **WS-B · CodeRabbit real wiring** — sembl-stack · owner+agy · **[spec pinned:
  [SPEC-coderabbit-prep.md](SPEC-coderabbit-prep.md)]**. Open the 14-day trial; swap `review: mock`
  → `coderabbit`; finalize the real CLI subcommand/JSON in `review_coderabbit.py`; re-run the 2×2
  with the *real* reviewer. _Acceptance:_ 2×2 still complementary (gate-only > 0, quality-only > 0)
  with the real CLI; advisory-never-gates holds. _Note:_ the spec has a RESUME-HERE banner.
- **WS-C · TUI Phase-1 onboarding + BYO-credits** — sembl-stack · Claude(credential path)+agy(screens)
  · **[spec pinned: [SPEC-tui-phase1-onboarding.md](SPEC-tui-phase1-onboarding.md)]**. The big new UX
  requirement (see §3). _Acceptance:_ a stranger launches bare `sembl-stack`, picks how Sembl runs the
  AI (their Claude login / their API key / local / mock), and lands on the rail — non-tech-easy,
  tech-powerful; no secret ever written to the run store.
- **WS-D · MurphyScan green** — sembl-stack + flagship · Claude/owner · run the `murphyscan` skill on
  the flagship and the orchestrator. _Acceptance:_ no P0/P1 launch blockers open; standing audit
  recorded. _Depends:_ WS-A.
- **WS-E · Public launch surface** — sembl-site · Claude/owner. A "what is sembl-stack" page, the
  **WITH/WITHOUT proof** (bad-merge 1.0→0.25, bad-live 1.0→0.222, 0 false alarms) as the hero
  artifact, a replayed-run view, docs reconciled. Frame = **process accountability, never "better
  code."** _Acceptance:_ site live on Vercel; numbers match the eval output; no falsified claims.
  _Depends:_ WS-A (the numbers), WS-D.
- **WS-F · Stranger-runnable proof** — sembl-stack · owner. `pip install sembl-stack` in a fresh
  env → `sembl-stack` onboarding → run one loop end-to-end; plus the TTY live-proof of TUI resume and
  the reconcile-live flagship proof. _Acceptance:_ a person who has never seen the repo completes a
  gated run. _Depends:_ WS-C.
- **WS-G · Private beta (3–5 partners)** — owner. The demand gate (see §5). Recruit, watch them run
  WS-F's path, capture friction. _Acceptance:_ ≥3 external runs + written feedback. _Depends:_ WS-F.

### P1 — breadth + operational credibility
- **WS-H · Breadth → ~50 adapters (2–4/layer)** — sembl-stack · agy · **[pin on request:
  adapter-authoring recipe]**. The long pole; demand-curated, not the 100-tool catalog. Can run in a
  beta window if needed. _Acceptance:_ each adapter meets the stage contract + a smoke test.
- **WS-I · Rate-limit + Sentry/observability + flagship CI gate** — flagship · agy · **[pin on
  request]**. _Acceptance:_ limits enforced, errors reported, CI gates the flagship.
- **WS-J · RSI-L1 measured-selection readout** — sembl-stack · Claude/agy · **[pin on request]**.
  Per-executor iters-to-green + cost over the corpus → the "measured selection" artifact (north-star
  first rung). _Acceptance:_ a reproducible table; advances RSI L0→L1.

### P2 — post-launch (capture now, build later)
- **WS-K · Internal progress dashboard** — owner says: *make the status diagram a live internal
  dashboard* (the SVG from the 2026-06-22 status read is the design seed). _Design intent:_ same
  layout — stage spine (per-stage status) + evidence strip + launch-readiness scorecard — but fed
  **live** from the run store (`.sembl/runs/`), eval outputs (harness/two_axis/through_deploy), and
  the latest gate verdicts, so it shows **where Sembl is breaking** (failed runs, BLOCKs, eval
  mismatches) in real time. Explicitly **post-launch** (owner: "worth making after launch").
- **WS-L · O5 hosted secret/permission/sandbox model** — for any hosted/multi-user offering; the
  single-user BYO-credits path (WS-C) is enough for launch.

---

## 3. WS-C in detail — the onboarding + BYO-credits requirement (owner, 2026-06-22)

The pinned spec is [SPEC-tui-phase1-onboarding.md](SPEC-tui-phase1-onboarding.md). The essence the
owner asked for:
- When a user comes in, **onboarding asks their preferences** and, crucially, **how they want to pay
  for the model calls** — they should use **their own credits / plan / tool-calling while inside
  Sembl** (their Claude Code login, their OpenAI/Anthropic key, a local model, or mock-to-try).
- The whole flow is **seamless** — **even non-technical people use it with ease**, while the **main
  target stays technical users**. Sensible recommended default + "just try it" for newcomers; full
  executor/transport/options control for power users.
- No credential ever lands in an artifact or the run store (ties to the redaction discipline +
  O5); keys live in env/OS-keyring, the `claude` login path stays token-free.

---

## 4. Definition of "super launch ready" (the bar)

From the locked launch bar (PROCESS-ACTION-PLAN §1b): **spine complete** (✅) · **beats
prompt-chains artifact** (✅ have the numbers) · **~50 adapters** (WS-H) · **MurphyScan green**
(WS-D) · **beta feedback** (WS-G) · plus the owner's adds: **BYO-credits onboarding** (WS-C) and a
**public proof surface** (WS-E). Honest read: depth + proof ~80–90% done; breadth + beta + public
surface are the back half this runbook closes.

## 5. The one thing that actually gates launch

Per [foundation-falsified] + [gtm-open-core]: the open question is **demand, not capability**. We
are very good at proving the loop works *in our own demos*. WS-F→WS-G (a stranger runs it, then
3–5 beta partners) is the real test — prioritize getting the onboarding surface in front of actual
people over gold-plating breadth. **Anti-trap holds: sell process correctness, never "better code."**
