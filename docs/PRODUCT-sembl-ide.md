# PRODUCT — the sembl IDE, v2 (locked 2026-07-09)

v2 supersedes v1 (2026-07-08, which locked the shell pivot) after a full
product-thinking session with the owner. v1's shell decision (O10: VS Code
OSS fork, extension-first) stands; v2 defines *what the product is*. Change
this doc only by diffing it with the owner. Ledger locks: O10–O15 in
`PROCESS-ACTION-PLAN.md`.

## One-liner and thesis

**The IDE for spec-anchored software development.** You converse freely; a
swappable executor builds; a deterministic gate judges against the spec; a
live stage shows the evidence; a daemon keeps spec and code converged
forever.

The load-bearing synthesis: **freedom at the conversation, determinism at
the commitment.** The conversation can say and attempt anything (the Claude
Code feeling); everything consequential passes through typed engine actions,
is judged by the gate, and is remembered by the run store. Claude Code is
freedom without accountability; sembl is that freedom with a spine.

Success criterion (owner-stated): the owner genuinely enjoys using it daily
for his own work first; market follows from that, never precedes it.

## The four capabilities (what "a very large software-creation problem
solved" decomposes into)

1. **Spec** — the anchor object. Conversation produces and refines it (task +
   bounds + SpecGraph + behavioral acceptance checks); the human confirms;
   from then on the software is measured against it.
2. **Converging loop** — executor writes code in a sandbox → gate judges →
   BLOCK reasons feed back as structured retry input → bounded attempts →
   escalate to the human with diff + reasons. The gate being model-free is
   what makes the loop converge instead of wander.
3. **Drift watch** — continuous spec↔code reconciliation after the loop;
   new divergence surfaces once; tri-state resolution; manual edits
   reconciled per the adoption rule (below).
4. **Layer proof** — PASS means "worked through every declared layer":
   sandbox, merge, DB migration applied, API answering, deployed, verified
   in prod — each layer a swappable adapter chosen on the strip.

## The screen — one window, three regions

- **Conversation** (center): a real agentic chat, any model — the platform's
  primary interface, not a side panel. Its tools are exactly the typed
  engine surfaces: create/refine spec, run loop, resolve drift, swap
  adapter, read state. It may *propose* anything; it can only *commit*
  through those tools (O11). Verdicts, drift findings, and prod checks post
  *into* it (event bus) — the system talks back unprompted.
- **Truth** (right + top strip): SpecGraph, the L0–L8 strip with each
  layer's chosen adapter (every chip a picker), live verdict with reasons,
  drift state. Where claims are verified at a glance, in plain language.
- **Stage** (toggleable third region): the live preview — see below.

The editor underneath is bone-stock VS Code (O10). We add zero editor
features; technical users edit freely and the daemon reconciles (O14).

## The stage: preview-as-evidence

The preview is not a window, it is evidence:

- Every loop attempt runs in its own sandbox with its own live preview —
  watch the agent's current attempt working, hot-reloaded, per attempt.
- The verify seat drives that same preview (rendered DOM / network / state
  assertions); its observations land in the run record as evidence the gate
  consumes. Differentiator: what you see on the stage is bound to the
  verdict.
- Human free play on the stage can be captured: mark a clicked-through flow
  "this must keep working" → it becomes an executable acceptance check
  attached to the spec (feeds O12).
- The run store keeps per-attempt snapshots; every verdict replays with
  visual proof.

**The stage is an adapter class** (per target profile): web app → browser;
API → request console; **smart contract → local chain (anvil/foundry) with
state inspector + simulated transactions**; CLI → terminal.

## Target profiles (why this is an IDE, not an app-builder)

A target profile = stage harness + verify adapters + deploy chain. Launch
profiles: web app, API service, **smart contract** (verify = fuzz/invariant
runs e.g. foundry/echidna; deploy = testnet→mainnet promotion; postdeploy =
on-chain monitoring). Contracts are the showcase: bounds/forbidden/
invariants are the native language of audits, and immutability makes
converge-before-deploy existential. Same loop, same gate, same conversation
across all profiles.

## Seats and swappability (the freedom factor, enumerated)

Every LLM/tooling seat is independently swappable, per seat per run, from
the UI or by saying it in the conversation:

| seat | default | siblings |
|---|---|---|
| conversation (operator) | any chat model | user's choice |
| executor (L3) | claude | codex, opencode, aider (S13 classes) |
| reviewers (advisory) | CodeRabbit | LLM judge — post into conversation, never the gate |
| drift daemon | haiku-class | any |
| guide (O9) | haiku | any |
| repo intelligence (L1) | codebase-memory MCP | LLM-wiki agents, graphify, latentgraph (O13) |
| secrets manager | pointer-only local | 1Password, Doppler, Infisical (O15) |
| stage harness | per target profile | adapter class |

The gate has no seat. It is not swappable, not a model, and has no
conversation presence except its verdicts.

## The engine addition: behavioral acceptance (O12)

Today the gate judges *trespass* (scope/forbidden/churn/fabrication/
evidence), not *wrongness within bounds*. v2 adds the behavioral axis:
executable examples and properties attached to the spec (given/when/then
flows, property tests, contract invariants) that the gate runs
deterministically. Within O3: we run declared behavior; we never grade
style or quality. This is the highest-value engine work on the roadmap.

## Brownfield entry: spec recovery (O13)

Real users arrive with a large repo and no spec. Onboarding = the drift
engine running in reverse on day zero: the repo-intelligence adapter builds
the code graph; a bootstrap pass proposes a SpecGraph from code + docs; the
human curates it in the conversation. No new subsystem — same machinery,
same surfaces.

## Manual edits: the adoption rule (O14)

Manual edits are first-class, watched by the daemon as ordinary commits:
- **In-bounds edits auto-adopt** into the spec — the daemon posts "adopted X
  into spec" to the conversation with one-click veto.
- **Bound-crossing edits always ask** — "you edited inside the forbidden
  payments area: widen the bounds, or revert?" Never silently adopted.
The spec stays the anchor; the human stays free. Silent adoption of a
bounds violation is the one thing the daemon must never do.

## Git: the substrate, never the interface

Every run is a branch; every attempt a commit; a PASS merge is a merge
commit stamped with run ID + verdict SHA (verdicts are already SHA-bound).
Manual edits are ordinary commits the daemon watches. Rollback = revert a
run's merge. Non-tech users never see git; technical users see a normal
repo whose history is an audit log. No lock-in: clone and leave anytime —
that is a selling point.

## Credentials and environment promotion (O15)

A **connections surface**: log into GitHub / Supabase / Vercel / a wallet
once, via OAuth, from the platform. Secrets live in a swappable
secrets-manager adapter; sembl stores pointers, never keys (existing
`profile.py` key_source rule, now product-wide). Layers request creds at
run time by environment: **sandbox gets nothing; staging gets scoped keys;
prod requires explicit promotion.** Executors never see raw secrets — they
are injected at the adapter boundary, outside the model's context. Trust
story: the model that writes your code physically cannot read your prod
keys.

## Delight bar (acceptance criteria for every surface PR)

- Golden-path actions ≤ 2 clicks (or one conversational sentence) from
  launch; zero raw yaml/json on the golden path.
- Cold open → usable < 5s; nothing stock-ugly visible by default.
- Every LLM touchpoint shows which seat/model produced it and allows
  swapping in place.
- The system talks first when it has news (verdict, drift, prod check) —
  into the conversation, not a buried panel.

## Non-goals (unchanged, locked)

- No "AI writes better code" claims or features (O3). No custom editor
  features. No dashboard sprawl. No multi-user/cloud until owner-dogfooding
  says so (S4). BLOCK is never applied or merged from any surface; applying
  a BLOCK is *absent*, not disabled.

## Roadmap order (value-ranked; sequencing decided per build session)

1. Behavioral acceptance axis (engine — O12).
2. Operator agent + event bus (the conversation as primary interface — O11).
3. Stage/preview-as-evidence for the web-app profile.
4. Loop feedback quality: gate reasons as structured retry input + human
   escalation UX.
5. Repo-intelligence layer formalized (L1 adapter class) + brownfield spec
   recovery.
6. Manual-edit adoption (drift daemon extension, O14).
7. Connections surface + secrets adapter + env promotion (O15).
8. Smart-contract target profile.
9. Concurrency (parallel loops, bounds-conflict detection).

Shell work (P1 extension → P2 VS Code fork, per O10) proceeds in parallel
only as far as the roadmap items need somewhere to live — chrome never
outruns signal (the anti-trap rule survives v2 verbatim).

## What carries over from the Theia era

Engine, every headless CLI, all tests, run store, design tokens, and locks
O1/O3/O8/O9 carry unchanged. The five proven surfaces (factory home,
discuss, guide, drift, spec graph) port as webviews. `ide/` (Theia) is
reference-only; `vscode-ext/` holds the parked P1 scaffold, resumed when
roadmap items need it.
