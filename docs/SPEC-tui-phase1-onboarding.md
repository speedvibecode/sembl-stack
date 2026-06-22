# SPEC — `sembl-stack` guided TUI, Phase 1: onboarding + bring-your-own-credits

> **Status: PINNED (2026-06-22), for July-1 execution.** Builds on Phase 0
> ([SPEC-tui-phase0.md](SPEC-tui-phase0.md): `session.py` + `wizard.py` + the stage rail +
> `.sembl/session.json` resume). Phase 1 adds the **first-run onboarding** the owner specified: a
> seamless flow that captures the user's preferences and, crucially, **how they want Sembl to pay
> for model calls — using their own credits / plan / tool-calling**. Easy enough for non-technical
> users, powerful enough for the technical target.
>
> **Delegation:** agy builds the Textual screens + the pure profile core from this spec; **Claude
> writes and reviews the credential-selection path itself** (security-sensitive — keys must never
> reach an artifact). Never trust the agent's self-check.

## 0. What Phase 1 delivers
On a first run (no profile yet), bare **`sembl-stack`** opens an **onboarding wizard** that:
1. **Welcomes + explains in one plain sentence** what Sembl does (an accountability gate around an
   AI coding loop) — no jargon wall.
2. **Asks how to run the AI** (the BYO-credits choice — §2) and **validates it works** (doctor
   preflight) before proceeding.
3. **Captures preferences** (§3): new-or-existing repo, strictness/preset, default executor options.
4. **Persists a profile** (§4) so subsequent runs skip onboarding and go straight to the stage rail.
A returning user (profile present) **never sees onboarding** — they land on the rail (Phase-0 resume).

It adds **no core/gate logic** — onboarding only *writes config the existing layers already read*
(executor adapter + `options.execute` + transport). Same "thin guide over artifact-first machinery"
stance as Phase 0.

## 1. New deterministic core — `sembl_stack/profile.py` (NEW, pure, headless)
A `Profile` dataclass + `~/.sembl/profile.json` persistence (user-level, distinct from the per-repo
`.sembl/session.json`). No Textual; fully unit-testable.
```python
STRATEGIES = ["claude-login", "api-key", "local", "mock"]   # how model calls are paid for

@dataclass
class Profile:
    runner: str = "mock"            # one of STRATEGIES
    executor: str = "mock"          # the L3 adapter name (claude|opencode|aider|mock)
    model: str | None = None        # e.g. "claude-opus-4-8", "tokenrouter/MiniMax-M3"
    key_source: str | None = None   # "env:ANTHROPIC_API_KEY" | "keyring" | None  (NEVER the key value)
    strict: bool = True
    preset: str | None = None       # reuse presets.py
```
- `save(profile)` → `~/.sembl/profile.json`; `load()` → `Profile | None` (tolerant of corrupt/old
  files exactly like `session.load` — bad file ⇒ None ⇒ re-onboard, never crash).
- **`key_source` stores only a pointer**, never the secret. The actual key lives in an env var or
  the OS keyring; `claude-login` uses the user's existing `claude` OAuth (token-free, per the
  "never handle a token" rule).
- `to_stack_overrides()` → the dict the wizard merges into the resolved `StackConfig`
  (`layers.execute`, `options.execute.{model,...}`, `loop.strict`) so the loop runs under the
  user's chosen runner with zero extra wiring.

## 2. The BYO-credits choice (the heart of Phase 1)
Onboarding presents four plain-language options; each maps to existing executor adapters:
| Choice (shown to user) | `runner` | `executor` | Credentials |
|---|---|---|---|
| **"Use my Claude Code login"** (recommended) | `claude-login` | `claude` | the user's `claude` OAuth — token-free; we shell `claude -p` (never `--bare`) |
| **"Use my API key"** (Anthropic / OpenAI-compatible) | `api-key` | `claude` or `aider`/`opencode` | key read from an **env var** (or OS keyring); pointer stored as `key_source`, value never persisted |
| **"Use a local model"** | `local` | `opencode`/`aider` | local endpoint; no cloud key |
| **"Just try it (no AI)"** | `mock` | `mock` | none — lets a newcomer see the whole loop instantly |
Selection → **doctor preflight** for that runner (binary present? key env set? `claude` logged in?).
On failure, show the one concrete fix and stay on the screen — never proceed with a runner that
can't run.

## 3. Preferences captured
Repo mode (new/existing — reuses Phase-0 `Session.mode`), strictness (`loop.strict`), and an optional
preset (`presets.py`). Keep it to **one screen** with sane defaults so the non-technical path is
"accept defaults → go"; expose an **"Advanced"** expander for the technical target (explicit
executor, model string, transport, churn/scope knobs).

## 4. Persistence + resume
- First run: no `~/.sembl/profile.json` ⇒ run onboarding ⇒ write profile ⇒ continue to the rail.
- Later runs: profile present ⇒ skip onboarding ⇒ Phase-0 `resume_or_new` for the per-repo session.
- A `--reconfigure` flag (or a rail action) re-opens onboarding.

## 5. UX stance (owner requirement)
**Seamless; non-technical-easy, technical-powerful.** Plain language, one recommended default,
"just try it" escape hatch, never a wall of options on screen one. Reuse the `uncodixfy` aesthetic
discipline for any rendered copy. The technical depth lives behind "Advanced", not in the default path.

## 6. Security (launch-credibility — do not cut)
- **No API key value is ever written** to `profile.json`, `session.json`, any run-store artifact, or
  a log. Only a `key_source` pointer. Reads happen at runtime from env/keyring.
- Reuse the redaction helper (`adapters/_redact.py`) for any executor output surfaced in the UI.
- This is the single-user slice of O5; the hosted/multi-user permission model stays out of scope
  (LAUNCH-PREP WS-L, post-launch).

## 7. Tests
- `tests/test_profile.py` (always-run, pure): round-trip, corrupt/old file ⇒ None, `to_stack_overrides`
  maps each strategy correctly, and **a test asserting no key value is serialized** when `key_source`
  is set.
- A `doctor`-style preflight test per runner (binary/env/login checks, mocked).
- `tests/local/test_onboarding.py` (gitignored TUI-pilot convention): headless pilot that walks
  welcome → choose runner → preferences → profile written, plus the returning-user skip path.

## 8. Acceptance
- A fresh machine with no profile: bare `sembl-stack` → onboarding → pick "Use my Claude Code login"
  → preflight passes → land on the rail; `~/.sembl/profile.json` written with **no secret in it**.
- "Just try it" completes onboarding with the mock runner and zero credentials.
- Second launch goes straight to the rail (no onboarding).
- Committed suite stays green (`pytest --ignore=tests/local`); pilots run locally with the `[tui]` extra.
