# SPEC — O12 Behavioral Acceptance (the fourth gate axis)

> **Status:** SHIPPED 2026-07-10 — all four WPs landed and live-proven per §10:
> WP1 `../sembl` 5d6066a, WP2 b1f444b, WP3 2a6dfc2 (flagship web BLOCK/PASS),
> WP4 8560bf9 (foundry invariant BLOCK/PASS, forge 1.7.1 local). Re-verify
> against git log before trusting this line. Recorded follow-on (not built):
> sandbox prepare/install step so dep-needing checks run inside the L4 clone.
> **Ledger:** implements O12 (`PROCESS-ACTION-PLAN.md` §5) + PRODUCT §"The engine
> addition". Roadmap item #1 (highest-value engine work). Stays within O1/O3/O8;
> adds no new LLM pattern.
> **Spans two repos:** `../sembl` (gate — the verdict) and `sembl-stack` (factory —
> the runner + contract + loop wiring). Both changes land together.

---

## 0. Owner decisions locked for this build (recorded 2026-07-09)

Three directional calls were resolved with the owner before this spec was pinned:

- **D1 — Gate judges, factory runs.** "Run deterministically *by the gate*" is
  honored as: the gate **owns the deterministic verdict** over behavioral results;
  a **swappable per-profile runner adapter executes** the checks in the L4 sandbox.
  The `sembl` gate stays execution-free. Rationale: the behavioral harness is
  inherently per-target-profile ⇒ an adapter class ⇒ it cannot live in the gate
  without giving the gate a seat, and "the gate has no seat" is locked (PRODUCT
  seats table). Execution already has a contained home (L4). The gate consumes a
  results artifact exactly as disciplined as it consumes the diff.
- **D2 — Web + contract profiles together** in this slice (owner overrode the
  single-profile-first recommendation). Reconciled with the anti-trap rule by
  build order (see §9): the **profile-agnostic core axis is proven headless FIRST**
  (WP1+WP2), then the web (WP3) and contract (WP4) harnesses are thin adapters on
  the proven core — chrome never precedes the signal.
- **D3 — ERROR ⇒ BLOCK, fail-closed.** A declared check that cannot produce a
  result (build fails, timeout, harness misconfig) is never a PASS. It BLOCKs, the
  error feeds back as retry input, and after `max_attempts` it escalates to the
  human like any BLOCK.

## 1. What it is (one line + golden path + non-goals)

**One line:** the gate gains a fourth axis — *behavioral acceptance* — that BLOCKs a
change which stays in bounds but fails the behavior the spec declared, judged
deterministically with zero model in the loop.

**Why (the class, not the instance):** today's gate judges *trespass* — where a
change went (scope/forbidden/churn) and whether its self-report is honest
(fabrication/evidence). It cannot catch *wrongness within bounds*: a change that
edits only allowed files, reports honestly, and still breaks the declared behavior
sails through as PASS. O12 closes that whole class by adding a declared behavioral
surface and the teeth to enforce it.

**The structural insight this build rests on.** The gate already runs one
discipline three times: **compare a declared contract against reported reality,
refuse fabrication/absence.** O12 is that same discipline applied to a new declared
surface (behavior). The upgrade over the existing *evidence* axis
(`validation_not_run`, a safe over-approximation that only WARNs on
claim-without-evidence) is a change of *who is trusted*:

| | today's evidence axis | O12 behavioral axis |
|---|---|---|
| who authored the checks | the executor (self-report) | the **spec** (human-confirmed, O8-proposed) |
| who ran them | the executor (claimed) | a **factory runner**, never the executor |
| trust | untrusted → degrade to WARN | trustworthy → can **BLOCK** |
| protection | — | checks are **gate contract surface**: a change editing its own acceptance criteria is a contract self-edit BLOCK |

That is the leverage: instead of trusting and degrading a self-report, the system
**owns the checks** (spec-attached, protected) and **owns running them** (factory
harness), removing the executor from the trust loop entirely.

**Golden path (headless, the loop):**
```
plan (L2, + Acceptance attached) → execute (L3, sandbox L4)
  → acceptance (L4.5: runner runs declared checks IN the sandbox → AcceptanceReport)
  → verify (L5: gate folds report → Verdict; behavioral FAIL/ERROR ⇒ BLOCK)
  → BLOCK? feed failing-check ids + detail back as retry input → retry
```

**Non-goals (locked):**
- **No quality/style grading** (O3). We run *declared* behavior and report
  PASS/FAIL/ERROR. We never score maintainability, coverage %, or "better code".
- **No model anywhere in the axis.** Not in the runner, not in the gate fold.
  Authoring checks may use the *existing* O8 bounded-LLM-into-fixed-schema pattern
  (§7) — a human confirms before anything is locked; that is not new (no fourth
  pattern).
- **The gate does not execute code.** It consumes results. Its no-execution
  invariant (safe as pre-commit hook / in CI / over scrubbed-env MCP) is preserved.
- **No behavioral axis when none is declared** — the axis is a strict no-op and the
  verdict is byte-identical to today (back-compat + incremental adoption, matching
  how `churn_budget` is only evaluated when declared).

## 2. Artifact contract additions (`sembl_stack/artifacts.py`)

Two new artifacts, both `_Serializable` dataclasses, registered in `KINDS`.

### 2.1 `Acceptance` — the declared behavioral contract (attached to the spec)

Sibling to `Bounds`: **Bounds governs *where* a change may go; Acceptance governs
*what must hold*.** Produced at plan time / spec time, consumed by the runner (L4.5)
and the gate (L5).

```python
@dataclass
class Acceptance(_Serializable):
    KIND = "acceptance"
    checks: list[dict] = field(default_factory=list)   # AcceptanceCheck dicts, see below
    sources: list[str] = field(default_factory=list)

    def to_contract(self) -> dict:
        """The shape the gate consumes for the declared-vs-ran integrity check:
        just the check ids + kinds, never the run/expect internals."""
        return {"checks": [{"id": c["id"], "kind": c["kind"],
                            "profile": c.get("profile", "command")}
                           for c in self.checks]}
```

**AcceptanceCheck** (a dict validated against a fixed schema — reuse the
discuss/ideation O8 `SCHEMA_KEYS` coercion discipline; a malformed check is dropped,
never crashes):

| field | type | meaning |
|---|---|---|
| `id` | str | stable, unique; referenced by report + retry feedback |
| `kind` | `"example"` \| `"property"` \| `"invariant"` | check family |
| `profile` | `"command"` \| `"web"` \| `"contract"` | which runner adapter |
| `description` | str | human-readable given/when/then prose |
| `run` | dict | profile-specific execution spec (see §6) |
| `expect` | dict | profile-specific expectation (see §6) |
| `seed` | int \| null | pinned for `property`/fuzz determinism; recorded on the result |
| `timeout_s` | int | kill-timeout; exceeding ⇒ ERROR (default 120, cap 600) |

### 2.2 `AcceptanceReport` — the runner's deterministic output

```python
@dataclass
class AcceptanceReport(_Serializable):
    KIND = "acceptance_report"
    results: list[dict] = field(default_factory=list)   # AcceptanceResult dicts
    runner: str = ""                                     # adapter id + version
    data: dict = field(default_factory=dict)

    @property
    def any_failed(self) -> bool:
        return any(r.get("outcome") in ("FAIL", "ERROR") for r in self.results)
```

**AcceptanceResult** dict:

| field | type | meaning |
|---|---|---|
| `id` | str | matches the declared check id |
| `outcome` | `"PASS"` \| `"FAIL"` \| `"ERROR"` | ran+passed / ran+failed / could-not-run |
| `seed` | int \| null | seed actually used (recorded for replay) |
| `duration_s` | float | wall time |
| `evidence` | str | captured stdout/stderr/counterexample, truncated + secret-scrubbed |
| `detail` | str | short reason on FAIL/ERROR |

## 3. Gate integration (`../sembl`) — D1: the gate judges, never runs

The gate gains one input and one axis. **It executes nothing.**

### 3.1 New input, threaded through the existing entry points

`validate_against_work_order(...)`, `verify_change(...)` (mcp_server.py), and
`sembl verify` (cli.py) each gain an optional `acceptance` argument:

```python
acceptance: dict | None = None
# shape: {"declared": [{"id","kind","profile"}, ...],   # from Acceptance.to_contract()
#         "results":  [{"id","outcome","detail", ...}, ...]}   # from AcceptanceReport
```

CLI: add `--acceptance <file.json>` to `sembl verify` (a JSON file with that shape),
mutually compatible with `--diff`/`--staged`/working-tree modes. MCP: add
`acceptance` param to `verify_change`. When absent/empty ⇒ axis is a strict no-op.

### 3.2 New axis on `ScopeReport` (validator.py)

Add three fields and fold them into the verdict with the **same structure** as the
existing axes:

```python
behavioral_failures: list = field(default_factory=list)   # ids: ran + assertion FAILED  → BLOCK
behavioral_errors:   list = field(default_factory=list)   # ids: could not run (D3)      → BLOCK
behavioral_missing:  list = field(default_factory=list)   # declared id with NO result   → BLOCK (integrity)
```

- `_blocking()`: OR in `bool(self.behavioral_failures or self.behavioral_errors or
  self.behavioral_missing)` under **every** policy (like `contract_edits` — behavior
  is never advisory; there is no "advisory behavioral" policy).
- `reasons()`: append, in this order, after the existing hard reasons:
  - `behavioral_failures` → `"behavioral checks failed: <id: detail>; ..."`
  - `behavioral_errors` → `"behavioral checks could not run: <id: detail>; ..."`
  - `behavioral_missing` → `"declared behavioral checks with no result (not run): <ids>"`
- `to_dict()` / `summary`: surface the three lists so callers (loop, IDE, run store)
  can render per-check status and build retry feedback.

The **declared-vs-ran integrity check** (`behavioral_missing`) is the behavioral
analog of `fabricated_claims`: for every id in `acceptance["declared"]`, there must
be a result in `acceptance["results"]`; a declared check with no result cannot be
trusted to pass, so it BLOCKs. Pure set comparison — deterministic, model-free.

### 3.3 Protect the acceptance declaration as gate contract surface

Extend `_is_contract_path()` so the acceptance declaration file is part of the
contract surface a change may never edit (like `bounds.json` / `.sembl/work-orders/`):
add `acceptance.json` and `.sembl/acceptance.json` to the recognized contract paths.
A diff that edits its own acceptance criteria is a `contract_edits` BLOCK under every
policy — this reuses the existing invariant verbatim; no new mechanism. **Grep-verify
(review checklist §5): the invariant holds repo-wide** — every place that computes
`contract_edits` (both diff mode and git working-tree mode) must recognize the new
paths.

### 3.4 Gate DO-NOTs

- DO NOT run, build, or import any repo code to establish an outcome. The gate reads
  the results it is given.
- DO NOT trust `report` (the executor self-report) for behavioral outcomes — the
  behavioral outcomes come ONLY from the `acceptance` input (the factory runner's
  report), never from `report`. Keep the two inputs separate.
- DO NOT make the behavioral axis policy-dependent. `advisory_scope` demotes scope;
  it never demotes behavior.

## 4. The runner (`sembl_stack`) — new L4.5 stage + adapter class

A new stage between execute and verify. **Runs only in the L4 sandbox** (contained,
disposable, no network, no secrets — consistent with O15 "sandbox gets nothing").

### 4.1 Adapter protocol (`adapters/base.py` + a registry entry)

```python
class AcceptanceRunner(Protocol):
    def run(self, acceptance: "Acceptance", sandbox, task, bounds) -> "AcceptanceReport": ...
```

Registered in `registry.py` under an `acceptance` layer key (mirrors `sandbox`,
`verify`, `review`): `acceptance: command` (default, profile-agnostic), `web`,
`contract`, and `none` (explicit no-op). Selected per run in `sembl.stack.yaml`.

### 4.2 Never-reject + determinism contract (load-bearing — review checklist §4)

- **Never rejects into the loop.** Any internal failure (harness missing, adapter
  crash, timeout) becomes an `ERROR` result, never a raised exception. Mirror the
  executor adapters' crash-to-report pattern.
- **Every check has a kill-timeout.** Exceeding `timeout_s` ⇒ the check process is
  killed ⇒ `ERROR` (never a hang; matches the codebase's subprocess-timeout
  discipline).
- **Property/fuzz checks pin a seed.** The runner injects `check["seed"]` (or a
  fixed default if null) into the harness invocation AND records the seed used on the
  result, so a verdict replays identically. A check whose harness cannot accept a
  fixed seed is `kind:"example"`, not `kind:"property"`.
- **Evidence is captured, truncated, and secret-scrubbed** via the existing
  `adapters/_redact.py` before it lands in the artifact (no-secrets-in-artifacts
  invariant).
- **The runner reads checks from the `Acceptance` contract, never from the diff or
  the executor's report** — the executor cannot introduce or alter a check.

### 4.3 Loop wiring (`loop.py`)

- Add an `acceptance` node after `execute`, before `verify`:
  `plan → execute → acceptance → verify → route`.
- `acceptance` node: if no `Acceptance` is configured/attached OR `cfg.acceptance` is
  the `none` runner ⇒ emit an empty `AcceptanceReport` and a `run.append_event`
  no-op-skip (never fabricate a stage that did nothing — matches `_maybe_expand`).
  Otherwise run `cfg.acceptance.run(...)` in the sandbox, persist the report per
  attempt (`run.put(report, name=f"acceptance-{n}")`), emit start/done events.
- `verify` node: pass `acceptance={"declared": acceptance.to_contract()["checks"],
  "results": report.results}` into `cfg.verify.verify(...)`. The
  `SemblVerifyAdapter` (both MCP and CLI paths) forwards it to the gate.
- **Retry feedback (minimal structured input, the O12 slice of roadmap item #4):**
  when the verdict BLOCKs on behavioral reasons, `Verdict.feedback()` must include
  the failing check ids + their `detail`, so the executor's next attempt sees exactly
  which declared behavior it broke. Extend the reasons carried into `feedback()`;
  no schema change to `Verdict` beyond what already flows through `reasons`.
- Behavioral BLOCK routes and escalates identically to any other BLOCK (retry until
  `max_attempts`, then return the BLOCK verdict — D3).

### 4.4 `SemblVerifyAdapter` change (`adapters/verify_sembl.py`)

`verify(...)` gains an `acceptance` kwarg forwarded on both transports:
- MCP: add `"acceptance": acceptance` to the `verify_change` args dict.
- CLI fallback: write the acceptance JSON to a temp file, pass `--acceptance <file>`.
Absent ⇒ omit the arg (back-compat with an older gate that lacks the param — the
adapter must not send `acceptance` when it's empty, so a pinned older `sembl` still
verifies).

## 5. Config (`sembl.stack.yaml` + `config.py`)

- New `acceptance:` layer key (default `command`; `none` to disable).
- The `Acceptance` contract is loaded from `<repo>/acceptance.json` (or
  `.sembl/acceptance.json`) if present, else from the Spec/plan step. `config.py`
  exposes `cfg.acceptance` (the runner adapter) and a loader for the `Acceptance`
  artifact, following the existing `cfg.verify` / `cfg.sandbox` pattern.
- Doctor (`doctor.py`): add a preflight line reporting the selected acceptance runner
  and, for `web`/`contract`, whether the harness toolchain is present (honest
  "unavailable — install X" message, never a silent skip).

## 6. Profile adapters + targets (D2 — built on the proven core)

### 6.1 `command` runner (WP2, profile-agnostic core — proven headless FIRST)

`kind:"example"`. The minimal, language-agnostic harness.
- `run`: `{"command": "<argv or shell string>", "cwd": "<rel path, optional>"}`
- `expect`: any of `{"exit_code": 0, "stdout_contains": "...",
  "stderr_contains": "...", "stdout_not_contains": "..."}` (all present must hold).
- Runs the command in the sandbox with a kill-timeout; maps exit/output against
  `expect` → PASS/FAIL; timeout/spawn-failure → ERROR.
- Proven on a tiny in-repo fixture (a passing check and a failing check) — no external
  toolchain. **This is the headless signal the anti-trap rule requires.**

### 6.2 `web` runner (WP3) — target: `examples/flagship-feedback-board`

`kind:"example"`, `profile:"web"`. A given/when/then flow expressed as a test-runner
invocation against the flagship Next.js app.
- `run`: `{"command": "npx playwright test <spec> --grep <name>"}` (or the app's
  existing `vitest`/`jest` invocation — use whatever the flagship already ships;
  do not add a new framework).
- `expect`: `{"exit_code": 0}`.
- Ties to PRODUCT "stage: preview-as-evidence": the check drives the rendered DOM and
  its pass/fail is bound to the verdict. **Prerequisite:** confirm the flagship has a
  runnable spec harness; if not, WP3 adds one minimal spec (a real GWT flow that
  currently passes) + one planted-break variant used only in tests.
- **Determinism note:** web specs must not hit the network; run against the local dev
  server the harness starts, seeded fixtures only.

### 6.3 `contract` runner (WP4) — target: a new minimal foundry fixture

`kind:"invariant"` (+ `kind:"property"` fuzz), `profile:"contract"`. The showcase.
- `run`: `{"command": "forge test --match-contract <C>", "seed": <int>}` for invariant
  campaigns; the runner passes foundry's seed flag and records it.
- `expect`: `{"exit_code": 0}` (no counterexample found).
- **Prerequisite (real dependency — flag before dispatch):** foundry (`forge`) must
  install on this Windows box. If it does not (treat as a known-trap category), WP4
  is gated: build the adapter + a foundry fixture, but mark the live-proof
  "unverified — foundry unavailable on win32" honestly rather than faking it. Do NOT
  block WP1–WP3 on WP4.
- **Fixture:** add `examples/contract-invariant/` — a tiny foundry project with one
  invariant that holds on the good version and is violated by a planted in-bounds
  change (the contract analog of the planted corpus case 14). This is what proves the
  axis has teeth on the contract profile.

## 7. Authoring the checks (O8 — no new LLM pattern)

Behavioral checks enter the `Acceptance` contract by exactly the existing sanctioned
routes; **this build wires only the headless/programmatic path** (surfaces come later
in the roadmap):
- **Programmatic / headless:** `acceptance.json` authored by the user, or emitted by
  the plan step. This is all WP1–WP4 require.
- **O8 proposal (reuse, do not rebuild):** the discuss/ideation modules already
  propose into a fixed schema a human confirms (`discuss.py` `SCHEMA_KEYS`,
  `ideation.draft_spec_slots`). A follow-on (out of scope here) adds `acceptance
  checks` as another fixed-schema slot the LLM may *propose* and the human *confirms*.
  **DO NOT add a model call in this spec.** Note the seam; build the schema so a
  proposal drops in later.
- **Stage capture (PRODUCT §stage, future):** "mark this clicked-through flow as must-
  keep-working" → an `example`/`web` check. Out of scope here; the artifact schema
  must not preclude it (it doesn't — a captured flow is a `web` example).

## 8. Determinism, security & platform review (applied, not deferred)

- **Windows reality:** commands run via the same subprocess discipline already in the
  repo (`encoding="utf-8", errors="replace"`, explicit timeouts). `forge`/`npx`
  resolve to `.cmd` shims on Windows — resolve them the way `deploy_vercel.py` already
  handles the vercel `.cmd` shim; do not regress into a bare `subprocess.run(["forge"])`
  `FileNotFoundError`.
- **Containment:** runner executes only inside the L4 sandbox clone; the loop's
  existing isolation guard (`_source_tree_status`) still asserts the source tree is
  untouched after the run.
- **Secrets (O15):** sandbox env carries no secrets; evidence is scrubbed via
  `_redact` before persistence.
- **Honest empty/error states:** no checks ⇒ no-op (verdict unchanged). Harness
  missing ⇒ ERROR with an actionable "install X" detail, never a silent PASS.
- **Replay:** seeds + commands + outcomes are all in the persisted `AcceptanceReport`,
  so a past verdict's behavioral basis is fully reconstructable from the run store.

## 9. Work packages (dispatchable, in build order — D2 reconciled with anti-trap)

Each WP is execution-only and independently reviewable. **WP1 and WP2 prove the core
axis headless before any profile harness (WP3/WP4) is built.**

- **WP1 — gate axis (`../sembl`).** §3 in full: the `acceptance` input on all three
  entry points, the three `ScopeReport` fields + fold + reasons + summary, the
  contract-surface protection (§3.3, grep-verified repo-wide), `--acceptance` CLI
  flag. **Acceptance criteria:** behavioral FAIL/ERROR/missing each ⇒ BLOCK under
  both policies; no `acceptance` ⇒ byte-identical verdict to today; editing
  `acceptance.json` in the diff ⇒ `contract_edits` BLOCK. **Tests (≥10 new):**
  FAIL⇒BLOCK, ERROR⇒BLOCK, missing⇒BLOCK, all-PASS⇒verdict unchanged, no-acceptance
  no-op (diff mode AND working-tree mode), acceptance present + a scope WARN ⇒ still
  BLOCK (behavior dominates), reasons ordering, summary surfaces the three lists,
  acceptance-file self-edit ⇒ contract BLOCK. **DO-NOT:** execute code; touch the
  `report` self-report path; add an advisory-behavioral policy.
- **WP2 — factory core (`sembl_stack`).** §2 artifacts, §4 protocol + `command`
  runner + loop wiring + `SemblVerifyAdapter` forwarding, §5 config/doctor. Proven on
  an in-repo fixture (passing + failing `command` check). **Acceptance criteria:** a
  declared failing `command` check drives the loop to BLOCK with the check id in the
  feedback; a passing check leaves the verdict as the trespass axes decide; `none`/no
  Acceptance ⇒ no acceptance stage runs (event log shows the skip, verdict
  unchanged). **Tests (≥12 new):** artifact round-trip (both new kinds), `command`
  runner PASS/FAIL/ERROR(timeout)/ERROR(spawn-fail), never-reject on adapter crash,
  seed recorded, evidence scrubbed+truncated, loop BLOCK-on-behavioral-fail +
  feedback contents, loop no-op when disabled, adapter forwards `acceptance` on both
  MCP and CLI transports (and omits it when empty). **DO-NOT:** read checks from the
  diff/report; let the runner raise into the loop; run outside the sandbox.
- **WP3 — web profile (`sembl_stack`) — after WP1+WP2 green.** §6.2. The `web` runner
  + a real GWT flow on the flagship. **Acceptance criteria:** a real flagship flow
  passes headless; a planted in-bounds break makes the same check FAIL ⇒ loop BLOCKs.
  **Tests (≥4 new):** web runner maps exit→outcome, planted-break⇒FAIL, missing-node/
  npx⇒ERROR(actionable), determinism (no network). **Live-proof (lead re-verifies):**
  run the loop against the flagship with a web check, watch a real BLOCK on a real
  broken DOM flow.
- **WP4 — contract profile (`sembl_stack`) — after WP1+WP2 green; parallel to WP3.**
  §6.3. The `contract` runner + `examples/contract-invariant/` foundry fixture.
  **Acceptance criteria:** invariant holds on the good contract (PASS); the planted
  in-bounds change violates it (FAIL ⇒ BLOCK); seed recorded + campaign replays.
  **Tests (≥4 new):** invariant PASS, planted-violation⇒FAIL, forge-missing⇒
  ERROR(actionable), seed pinned+recorded. **Prerequisite gate:** if `forge` will not
  install on win32, deliver adapter+fixture+tests and mark the live-proof honestly
  unverified; do NOT fake it, do NOT block WP1–WP3.

## 10. How the lead re-verifies before commit (never trust the executor self-check)

Per the delegation method and `~/.claude/CLAUDE.md` "definition of done" — for each WP:
1. Read the full diff end-to-end (both repos for WP1↔WP2 interplay).
2. Run the tests **myself** from each repo root
   (`.venv/Scripts/python -m pytest -q`), confirm the stated new-test counts landed
   and pass, and that pre-existing suites stay green in both repos.
3. **Drive the real headless flow myself:** author an `acceptance.json` with one
   passing and one failing `command` check on a scratch repo, run `sembl-stack loop`,
   and confirm the failing check produces a real BLOCK with the id in the feedback and
   an `AcceptanceReport` in the run store — the empty state (no checks ⇒ no-op), the
   error path (timeout ⇒ ERROR ⇒ BLOCK), and the retry feedback all walked, not just
   "it compiled."
4. Independently re-derive the back-compat claim: run the existing eval corpus and
   confirm no verdict shifted when no acceptance is declared.
5. WP3/WP4: drive the real flagship / foundry fixture and watch a real behavioral
   BLOCK; report any profile whose live-proof is unverified honestly.
6. Commit per WP (or logically grouped) only after 1–5 pass, recording review fixes
   and any unverified limitation in the commit message.

## 11. Anti-trap reconciliation (why D2's two-profile scope is still on-plan)

The anti-trap rule (three dead shells) says prove signal headless before chrome. D2
adds a *second execution profile*, not a UI. The reconciliation is the build order:
WP1+WP2 prove the axis end-to-end headless on a trivial `command` fixture — that is
the signal. WP3/WP4 are thin harness adapters over the *already-proven* core, each
with its own real target and planted-break proof. No surface work is in this spec at
all; the IDE rendering of the behavioral axis is a later roadmap item (#2, the
operator agent + event bus) and rides on the artifacts this build produces.
