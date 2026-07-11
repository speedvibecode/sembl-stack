# SPEC — O14, the manual-edit adoption daemon (roadmap #6)

> **Status:** DRAFT 2026-07-11 — awaiting owner approval. Do NOT dispatch: §0
> holds the owner decisions (each with the lead's recommendation). Everything
> below §0 is pinned.
> **Ledger:** O14 [LOCKED 2026-07-09]: in-bounds human edits auto-adopt into
> the spec (daemon announces, one-click veto); bound-crossing edits ALWAYS ask
> (widen bounds or revert) — a bounds violation is never silently adopted.
> PRODUCT v2 §"Manual edits: the adoption rule". Stays within O1/O3; the LLM
> touchpoint is O8 REUSE (bounded model into a fixed schema), not a fourth
> pattern.
> **Repo:** `sembl-stack` only.

---

## 0. OPEN — owner decisions required before dispatch

- **D-A1 — what "the daemon" is in this slice.** A resident file-watcher
  process is chrome-era plumbing. Options: (a) a headless engine function
  `adoption.scan(repo)` that classifies commits since its last high-water
  mark, invoked on demand (CLI `sembl-stack adopt scan`, operator turn, later
  the IDE on a timer); (b) a real resident watcher now. **Recommendation:
  (a)** — same signal, no process-lifetime problems, and the IDE can poll it
  exactly like it reads runs. The word "daemon" survives as the IDE's timer.
- **D-A2 — what "adopt into the spec" changes mechanically.** The spec today =
  task text + `bounds.json` + SpecGraph + acceptance checks. Options: (a) an
  O8-pattern proposal: bounded LLM reads the commit diff and emits a fixed-
  schema spec delta (SpecGraph node/edge additions + a one-line summary),
  applied to the stored SpecGraph; (b) no model: record the adoption as an
  append-only ledger entry ("commit X adopted, touches paths Y") without
  altering the SpecGraph. **Recommendation: (b) for this slice, (a) as a
  follow-on** — prove the classification + veto + always-ask machinery
  deterministically first; the LLM delta writer is a separable upgrade and
  keeps this build model-free.
- **D-A3 — veto semantics.** "Auto-adopt with one-click veto": adopt
  immediately and veto reverts the ADOPTION RECORD (never the human's code),
  or hold in a pending window before adopting? **Recommendation: adopt
  immediately, veto reverts the record** — a pending window is a queue the
  owner would have to tend; the ledger keeps vetoes permanent and auditable
  (same shape as gate overrides).
- **D-A4 — how the operator surface carries adoption.** SPEC-O11 §3.1 locks
  the nine tools ("NOTHING else"). Options: (a) adoption state rides the
  existing drift family — `list_drift` grows adoption items, `resolve_drift`
  gains actions `adopt-veto` / `widen-bounds` / `revert` (O14 is already
  "drift daemon extension" per PRODUCT); (b) new tools by diffing SPEC-O11.
  **Recommendation: (a)** — adoption IS drift state (spec↔code divergence
  with a human-resolution lifecycle); one commitment surface, no new tools.

## 1. What it is

**One line:** human edits are first-class citizens: every ordinary commit is
classified against the spec's bounds — in-bounds edits are adopted into the
spec record automatically (announced, vetoable), bound-crossing edits stop and
ask — so the spec stays the anchor without ever caging the human.

**Golden path (headless, the proof):**
```
# human edits src/feedback.ts (inside editable_paths), commits
sembl-stack adopt scan
  → "adopted a1b2c3d into spec (src/feedback.ts) — veto: sembl-stack adopt veto a1b2c3d"
  → adoption.adopted event on the bus → surfaces in the operator's next turn

# human edits infra/deploy.yml (inside forbidden_areas), commits
sembl-stack adopt scan
  → "a4f9e21 crosses bounds (infra/deploy.yml is forbidden) — choose:
     widen  : sembl-stack adopt widen a4f9e21   (edits bounds.json explicitly)
     revert : git revert a4f9e21                (your call, never ours)"
  → adoption.blocked event on the bus; NOTHING auto-applied, ever
```

**Non-goals (locked):** never touches the working tree or reverts a commit
itself (it asks; git stays the human's); never judges the QUALITY of a manual
edit (O3 — classification is deterministic path-matching against bounds.json,
a model never decides in/out of bounds); no resident process (D-A1); no
SpecGraph mutation in this slice (D-A2); no IDE chrome — the one-click veto's
"click" is a CLI/operator command until the IDE renders the same events.

## 2. Shape (all engine, existing patterns)

- **`sembl_stack/adoption.py`**: `scan(repo)` walks commits since the stored
  high-water mark (`.sembl/adoption-state.json`, same pattern as drift state),
  skipping commits authored by the loop itself (run-stamped merge commits);
  classifies each commit's touched paths against `bounds.json`:
  `in_bounds` (all paths editable) / `bound_crossing` (ANY path forbidden or
  outside editable — mixed commits are bound-crossing, fail-closed);
  appends adoption records to `.sembl/adoptions.jsonl` (append-only, like the
  bus); publishes `adoption.adopted` / `adoption.blocked` bus events (kinds
  added by diffing SPEC-O11 §2.2, as with the stage spec).
- **`veto(repo, sha)`** flips a record to vetoed (permanent, reasoned);
  **`widen(repo, sha)`** emits the EXPLICIT bounds.json diff for the paths and
  applies it only on confirm — the bounds file never changes silently.
- **CLI:** `sembl-stack adopt scan|veto|widen` — thin renderers (O1).
- **Operator:** per D-A4(a), drift tools carry adoption items; no new tools.

## 3. Work packages (dispatch only after §0 is resolved)

- **WP-A — classify + ledger.** `adoption.py` scan/state/ledger + tests (≥10):
  in-bounds commit → adopted record + event; forbidden-path commit → blocked
  record + event + nothing applied; mixed commit → bound-crossing; loop-
  authored commits skipped; high-water mark advances only past classified
  commits; re-scan is idempotent; empty repo / no new commits = clean no-op;
  corrupt state file = fail-closed rescan from the ledger, never a crash;
  records carry sha + paths + classification + ts. **DO-NOT:** call any
  model; touch the working tree; auto-edit bounds.json.
- **WP-B — veto/widen + CLI + operator ride-along.** Tests (≥8): veto flips a
  record permanently with reason; veto of unknown sha = clean error; widen
  prints the exact bounds diff and applies only on confirm; CLI renders all
  three commands over the engine functions with no logic of its own;
  `list_drift`/`resolve_drift` surface adoption items per D-A4; the O11
  boundary-lock test still passes (still nine tools). **DO-NOT:** grow the
  MCP tool set; let widen accept a path not in the blocked commit.
- **Lead live-proof:** on a scratch repo — make a real in-bounds edit, scan,
  see the adoption in the operator's `[factory events]` block; veto it; make
  a real forbidden-area edit, scan, verify NOTHING changed on disk and the
  ask is actionable; corrupt the state file and re-scan. Drive the operator
  path over the REAL MCP transport (the 2026-07-11 FastMCP stdio deadlock,
  fix commit `1fcbf46` — direct-call tests can't see transport breakage).

## 4. Why this order (systems note)

The adoption rule is the product's answer to "the spec rots the moment a human
touches the code." This slice makes the RULE real and auditable with zero
model risk; D-A2(a)'s LLM spec-delta writer can then be judged against a
working deterministic baseline — the same prove-signal-first order that saved
O12 and O11.
