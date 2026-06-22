# LAUNCH-PREP — finalized plan (execution starts July 1, target launch ~July 14)

> **Finalized 2026-06-22** after a full decision pass with the owner. This is the execution
> overlay; [PROCESS-ACTION-PLAN.md](PROCESS-ACTION-PLAN.md) stays the architecture/decision
> source-of-truth. Nothing auto-runs — owner fires agents manually. Method: Claude pins specs +
> reviews/re-verifies (never trusts an agent's self-check); cheap CLIs execute.
>
> **Framing (owner, 2026-06-22):** launch is **a target, not a guillotine.** The standing,
> non-negotiable bar is that the three repos are **clean and fully usable** (owner-dogfood-grade) —
> the owner is the **first user** and will use Claude *through* sembl regardless, so the RSI loop
> survives even if the launch underperforms (just slower). Launch polish (channels, waitlist,
> big-bang timing, the CodeRabbit hard-gate) sits *on top* of "clean + usable", never in place of
> it. If a hard gate disappoints, slipping/de-scoping it is fine; shipping something rough is not.
> We move fast — this is a ~2-week big-bang, not a quarter — but unhurried where it matters.

## 0. Locked decisions (the consensus)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Launch shape | **Big-bang launch day** (coordinated, polished) |
| 2 | Demand test | **Hand-recruited design partners** — but as a 3-4 day **QA pass**, not a demand verdict; the big-bang itself is the demand test (chosen consciously) |
| 3 | Breadth | **~30-40 adapters, spread evenly across layers, BEST-EFFORT** (never slips the date) |
| 4 | Wedge / hero | **MCP is the hook; "go run the whole loop yourself — it's even better" is the headline** |
| 5 | Target date | **~July 14** (≈2 weeks; checklist-gated, not calendar-gated) |
| 6 | Try-it scope | **Local loop (spec→gate→merge) = the try-path; through-deploy = showcase** (BYO-deploy documented) |
| 7 | Showcase | **Polish the existing flagship feedback board** (real, deployed, gated, auth-fixed) |
| 8 | CodeRabbit | **HARD GATE — prove the REAL 2×2 before launch** ⇒ trial opens **July 1, first thing**; mock is the instant fallback |
| 9 | Beta model | **Rolling QA pass ~3-4 days** (recruit early, onboard when try-it is green) |
| 10 | Merge | **Merge the reviewed spine to master now**; all WS branch off master |
| 11 | Versions | **sembl-stack `0.1.0`** at launch; **gate → `0.2.0`** (IDE/MCP milestone) |
| 12 | Onboarding | **Bring-your-own-keys is the price of entry** — BYO Claude login / API key / local; **mock is only a no-AI mechanics preview**, never the hero path |
| 13 | Credentials | **Env vars only** (store a pointer, never the value); keyring post-launch; auto-detect what's present |
| 14 | MurphyScan | **P0 blocks; P1 triaged** (fix cheap/critical, consciously defer the rest with a reason) |
| 15 | Proof artifact | **asciinema recorded runs + the rogue-diff gate-catch** + the WITH/WITHOUT numbers |
| 16 | Gate 0.2.0 scope | Package + IDE quickstart + version bump **+ 1-2 new MCP ergonomics** (e.g. a one-call "gate this PR") |
| 17 | Channels | **Everywhere** — Show HN + r/cursor + dev subreddits + X thread + Product Hunt + more |
| 18 | Money | **Free now.** ~100 users ⇒ raise + incorporate. Real money = **Sembl Hosted / Teams / Enterprise** ⇒ capture that interest via a **waitlist** on the site (the demand instrument) |
| 19 | License | **Apache-2.0** across both repos (currently MIT ⇒ **relicense task**; owner is sole copyright holder, so clean) |
| 20 | Internal dashboard | **Post-launch** (WS-K) — the status diagram fed live from run-store + evals |

## 1. Pre-flight (do once, ~10 min)
- **Gotchas:** comment out the CBM MCP block before running **codex** (it wedges); pytest
  `--basetemp` must be OFF the repo tree; venv has no pip (use `uv pip install`,
  `.venv\Scripts\python.exe`); **agy needs a TTY** (owner runs it foreground).
- **Agent roster:** Claude = pin/review/QA + the credential path. **agy** (Gemini-3.5-Flash) =
  mechanical builds from pinned specs (breadth, screens). **codex** (GPT-5.5) = tough + review.
- **First action, July 1:** (a) merge `ws2-through-deploy-spine` → master; (b) **open the
  CodeRabbit trial** (it's the hard gate on a 14-day clock — day-1 or bust).

## 2. Hard-gate checklist for ~July 14 (all must be green)
1. Spine merged to master; sembl-stack `0.1.0` + gate `0.2.0` cut.
2. **Onboarding + BYO-keys** flow is the make-or-break first 60s — smooth, env-only, auto-detect, no secret persisted.
3. **Real CodeRabbit 2×2** demonstrated (gate-only > 0 AND quality-only > 0 with the real CLI).
4. **MurphyScan**: no open P0 on flagship or orchestrator (P1 triaged).
5. **Public site** live with the asciinema proof + gate-catch + WITH/WITHOUT numbers + hosted/teams waitlist.
6. **Stranger-runnable proof**: fresh-env `pip install sembl-stack` → onboarding → one gated loop, by someone who's never seen it.
7. **Design-partner QA pass** done; embarrassing friction fixed.
8. **Apache-2.0** relicensing landed.

**Best-effort (ship without if behind, never slips the date):** breadth toward 30-40 adapters;
Sentry/observability + rate-limits; flagship CI gate.

## 3. Day-by-day (~July 1 → 14, heavily parallelized)
- **Jul 1** — merge → master; **open CodeRabbit trial**; relicense MIT→Apache-2.0 (both repos);
  kick agy on (a) onboarding screens and (b) the adapter-breadth recipe in parallel; begin partner recruiting.
- **Jul 2-3** — **CodeRabbit real swap + real-2×2 proof** (front-loaded hard gate); Claude builds/reviews
  the BYO-credential core; gate 0.2.0 MCP ergonomics + IDE quickstart.
- **Jul 4-5** — onboarding done + doctor preflight per runner; **MurphyScan** run, fix P0s; flagship
  showcase polish; record **asciinema** casts (a clean loop + the rogue-diff BLOCK).
- **Jul 5-6** — **stranger-runnable proof** (fresh-env install → onboarding → loop); build the **site**
  (proof page, casts, hosted/teams **waitlist**); reconcile docs.
- **Jul 6-9** — **design-partner rolling QA** (~3-4 days): onboard 3-5, capture friction, fix fast.
- **Jul 9-11** — incorporate partner fixes; breadth continues (best-effort); finalize 0.2.0 + IDE guide.
- **Jul 11-13** — final MurphyScan (P0 clean, P1 triaged); polish; **launch dry-run**; draft all channel posts.
- **Jul 14 — LAUNCH:** fire every channel.

## 4. Workstreams (pinned-spec status)
- **WS-C onboarding + BYO-keys** — **[spec pinned: [SPEC-tui-phase1-onboarding.md](SPEC-tui-phase1-onboarding.md)]** (revised to the BYO stance).
- **WS-B CodeRabbit real** — **[spec pinned: [SPEC-coderabbit-prep.md](SPEC-coderabbit-prep.md)]** (RESUME-HERE banner; now front-loaded to Jul 1-3).
- **WS-H breadth recipe**, **gate-0.2.0 mini-spec**, **site/proof spec**, **MurphyScan run-plan**,
  **RSI-L1 readout** — **[pin on request]**: say the word and Claude pins these so July 1 is zero-spec-writing.

## 5. Launch-day kit
- **Channels:** Show HN (core), r/cursor + dev subreddits (warm/on-target), X build-in-public thread
  with the gate-catch cast, Product Hunt, + owner's extras — coordinated same-day.
- **Hero narrative:** "Your IDE agent, now accountable (MCP) — and you can run the *whole* gated
  loop yourself; it's even better." Frame = **process accountability, never "better code."**
- **Proof:** asciinema casts + WITH/WITHOUT numbers (bad-merge 1.0→0.25, bad-live 1.0→0.222, 0 false
  alarms) — numbers must match live eval output, no falsified claims.

## 6. The honest line
The big-bang **is** the demand test (the partner pass is just QA). The success signal is adoption,
not applause. **~100 users is the trigger** to raise + incorporate; the money sits in **Sembl
Hosted / Teams / Enterprise**, so the launch site's job is partly to *capture that interest*
(waitlist) while the open-core tool is free. Anti-trap [foundation-falsified] holds: sell process
correctness, never "better code."
