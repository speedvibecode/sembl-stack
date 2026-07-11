# SPEC — the stage, preview-as-evidence for the web profile (roadmap #3)

> **Status:** APPROVED 2026-07-12 — owner directed "proceed to build"; the §0
> recommendations are thereby LOCKED as decisions (D-S1 declared prepare,
> D-S2 DOM-only, D-S3 down-by-default + `--stage-hold`, D-S4 capture out of
> slice). Dispatchable. Everything below is pinned.
> **Ledger:** PRODUCT-sembl-ide.md §"The stage: preview-as-evidence" (v2,
> locked 2026-07-09), roadmap item #3. Stays within O1 (engine headless, every
> surface a renderer), O3 (nothing judges quality; the stage carries evidence,
> never opinion). Adds NO LLM anywhere — the stage is deterministic machinery.
> **Repo:** `sembl-stack` only. The gate (`../sembl`) is not touched.
> **Prerequisite it absorbs:** the recorded O12 limitation (commit `8560bf9`
> era): L4 sandbox clones carry no installed deps, so dep-needing acceptance
> checks can't run inside the sandbox (WP3 live-proof needed a shim pointing
> `WEB_CHECK_APP_DIR` at the real app). The stage requires the app to RUN in
> the sandbox, so fixing that is WP-A here, not a side quest.

---

## 0. OPEN — owner decisions required before dispatch

- **D-S1 — how a sandbox gets its dependencies.** Options: (a) run a declared
  `sandbox.prepare` command (e.g. `npm ci`) in every attempt's clone — slow
  (~minutes/attempt on Windows) but always correct; (b) copy `node_modules`
  from the source repo when present, fall back to prepare — fast but can mask
  lockfile drift; (c) prepare once per RUN into the attempt-1 clone and reuse
  that clone's deps for later attempts. **Recommendation: (a) declared
  prepare, correctness first** — speed optimizations are measurable follow-ons
  once the honest cost is known from real runs.
- **D-S2 — what the per-attempt evidence snapshot is.** Options: (a) rendered
  DOM (HTML text) of declared routes — diffable, small, no new deps; (b)
  screenshots — visual but needs a browser dep and can't be diffed; (c) both.
  **Recommendation: (a) DOM-only for this slice**; screenshots arrive with the
  IDE stage region, which can render live instead.
- **D-S3 — does the stage stay up after the verdict?** A live server outliving
  its attempt is human-playable (the capture story) but leaks processes in
  headless runs. **Recommendation: down by default when the attempt ends; a
  `--stage-hold` flag on `loop` keeps the FINAL attempt's server up and prints
  the URL** — free play arrives without a resident-process problem.
- **D-S4 — capture ("mark this flow as an acceptance check").** Judgment-dense
  (recording mechanism, check synthesis, spec attachment). **Recommendation:
  OUT of this slice entirely; its own spec after the harness proves signal.**
  Listed here so deferring it is an owner decision, not lead drift.

## 1. What it is

**One line:** every loop attempt's sandbox serves a live, hot copy of the app,
and what that copy observably renders lands in the run record bound to the same
diff SHA the gate judged — the preview is evidence, not a window.

**Golden path (headless, the proof — no IDE, no chrome):**
```
sembl-stack loop task.yaml            # web-profile repo with stage declared
  → attempt 1: sandbox clone → prepare (deps in) → stage up (url on the bus)
  → executor edits; acceptance + stage snapshot run against THAT sandbox
  → verdict binds: diff SHA + acceptance report + stage snapshot, one attempt
  → BLOCK → attempt 2 gets ITS OWN stage; artifacts never overwrite
  → tail .sembl/bus.jsonl elsewhere: stage.up/stage.down events carry the url
  → after PASS: open .sembl/runs/<id>/stage-1/, see what attempt 1 rendered
```

**Non-goals (locked):** no IDE stage region, webview, or browser chrome (that
is a later roadmap item rendering THESE artifacts unchanged); no screenshots
(D-S2); no capture (D-S4); no LLM touchpoint; no new gate axis — the gate
already consumes acceptance evidence, the stage adds observability, never
judgment (O3); API/contract/CLI stage harnesses are later adapters of the same
class, web only in this slice.

## 2. Shape (all engine, all existing patterns)

- **`stage` becomes a registry layer** (adapter class, like `acceptance`):
  `stage: web` in `sembl.stack.yaml`; `open(sandbox, decl) -> StageHandle`
  exposing `.url`, `.snapshot(routes) -> dict`, `.close()`. Declared in config:
  `stage: {serve: "npm run dev", ready: "http://localhost:{port}", routes: ["/"]}`
  — port allocated per attempt (OS-assigned free port), never fixed.
- **Loop wiring:** stage opens after execute, before acceptance (L4.5 sees a
  running app); closes when the attempt ends (D-S3 default). Stage failure to
  boot = attempt-level ERROR with the server's captured stderr as the reason —
  fail-closed, mirroring the acceptance runners' discipline.
- **Artifacts:** `.sembl/runs/<id>/stage-<attempt>.json` (serve command, url,
  ready-check result, timings) + `stage-<attempt>/` route DOM snapshots. Bound
  to the attempt's diff SHA (same binding the verdict already uses).
- **Bus events:** `stage.up` / `stage.down` (run_id, attempt, url) — new kinds
  added to `bus.py`'s closed set by diffing SPEC-O11 §2.2 (this spec IS that
  diff once approved).
- **Prepare (WP-A):** `sandbox.prepare` in config; runs in the clone workdir
  with an explicit timeout; publishes `run.stage` events like any stage
  transition; failure fails the run at L4 with the command's stderr.

## 3. Work packages (dispatch only after §0 is resolved)

- **WP-A — sandbox prepare.** Config key + loop wiring + tests (≥6): declared
  prepare runs in the clone before execute; absent key = no-op (today's
  behavior byte-identical); failure = honest run failure with stderr reason,
  never a silent skip; timeout enforced; events published; existing suite
  green. **DO-NOT:** touch the source repo; install anything outside the
  sandbox workdir; special-case any package manager.
- **WP-B — the web stage harness.** Registry layer + adapter + loop wiring +
  tests (≥8, fixture server not a real Next.js app): open/ready/close
  lifecycle; per-attempt port isolation (two attempts, two ports); boot
  failure = attempt ERROR with stderr; ready-check timeout enforced; stage.up/
  stage.down on the bus with run_id+attempt; `.close()` kills the process tree
  (Windows: the deploy_vercel shim + kill lessons apply); no stage declared =
  layer inert. **DO-NOT:** parse app output; retry boots; leave a process
  alive after close (test asserts the port is free again).
- **WP-C — evidence snapshots.** `.snapshot(routes)` fetches declared routes'
  rendered DOM (plain HTTP GET for this slice — a JS-rendering fetch is a
  follow-on decision once real use shows it's needed), writes
  `stage-<attempt>/<route>.html` + manifest, binds attempt diff SHA + tests
  (≥5): snapshot lands per attempt; two attempts never collide; unreachable
  route = recorded ERROR entry, not a crash; manifest carries the SHA; suite
  green. **DO-NOT:** diff or judge snapshots (evidence, not verdict — O3).
- **Lead live-proof (§SPEC-O11-§8-style, on the flagship):** run a real loop
  on `examples/flagship-feedback-board` with prepare+stage declared; watch
  stage.up on the bus from a second process; verify attempt-1 vs attempt-2
  snapshots differ where the diff says they should; kill -9 the loop mid-run
  and verify no orphaned server survives. Drive the REAL transport if any MCP
  surface changes (the 2026-07-11 FastMCP stdio deadlock, fix commit
  `1fcbf46`: direct-call tests are blind to transport-level breakage).

## 4. Anti-trap reconciliation

Three shells died building chrome before signal. This spec's entire output is
headless engine surface: a config key, an adapter class, artifacts, bus
events — provable with `curl` and `cat`. The IDE stage region, when it comes,
renders `stage-*.json` + snapshots + `stage.up` events with zero engine change;
if this slice's proof fails, no chrome was built on it.
