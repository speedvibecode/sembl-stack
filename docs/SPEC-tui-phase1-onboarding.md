# SPEC — `sembl-stack` guided TUI, Phase 1: onboarding + bring-your-own-credits

> **Status: PINNED (2026-06-22), revised to the BYO stance, for July-1 execution.** Builds on
> Phase 0 ([SPEC-tui-phase0.md](SPEC-tui-phase0.md): `session.py` + `wizard.py` + the stage rail +
> `.sembl/session.json` resume). Phase 1 adds the **first-run onboarding**.
>
> **Bring your own keys is the price of entry (owner, 2026-06-22).** sembl-stack is an
> *orchestration layer* — it does not provide inference. To use the loop, a user **brings their own
> keys / subscription** (their Claude Code login, their API key, or a local model). This is the
> correct filter for who actually adopts it. The onboarding's job is to make *bringing your booze*
> seamless — auto-detect what's already there, validate it, get out of the way — **not** to coddle
> with a free ride. **Mock is only a no-AI "see the mechanics" preview, never the hero path.**
> "Non-tech-easy" means the *flow* is smooth; it does not mean we supply inference.
>
> **Delegation:** agy builds the Textual screens + the pure profile core from this spec; **Claude
> writes and reviews the credential-selection path itself** (security-sensitive — keys must never
> reach an artifact). Never trust the agent's self-check.

## 0. What Phase 1 delivers
On a first run (no profile yet), bare **`sembl-stack`** opens an **onboarding wizard** that:
1. **Welcomes + explains in one plain sentence** what Sembl does (an accountability gate around an
   AI coding loop) — no jargon wall.
2. **Auto-detects the user's own credentials** (existing `claude` login? `ANTHROPIC_API_KEY` /
   `OPENAI_API_KEY` in env? a local endpoint?) and **preselects** the one it finds; the user
   confirms or switches (the BYO choice — §2). **Validates it works** (doctor preflight) before
   proceeding. If nothing is found, it explains plainly that Sembl runs on *your* keys and points
   to the 30-second setup — with the no-AI mock preview as the only keyless option.
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

## 2. The BYO choice (the heart of Phase 1)
Onboarding presents the bring-your-own options; each maps to an existing executor adapter. The one
auto-detected (§0.2) is preselected.
| Choice (shown to user) | `runner` | `executor` | Credentials |
|---|---|---|---|
| **"Use my Claude Code login"** | `claude-login` | `claude` | the user's `claude` OAuth — token-free; we shell `claude -p` (never `--bare`) |
| **"Use my API key"** (Anthropic / OpenAI-compatible) | `api-key` | `claude` / `aider` / `opencode` | key read from an **env var**; only a `key_source` pointer is stored, **never the value** (env-only for launch; keyring post-launch) |
| **"Use a local model"** | `local` | `opencode` / `aider` | local endpoint; no cloud key |
| _"Preview the mechanics (no AI)"_ | `mock` | `mock` | none — **not the hero path**; a keyless way to see the loop's shape, clearly labelled as not-real-AI |
Selection → **doctor preflight** for that runner (binary present? key env set? `claude` logged in?).
On failure, show the one concrete fix and stay on the screen — never proceed with a runner that
can't run. The expectation is BYO keys; `mock` is the only no-key option and is presented as a
preview, not a default.

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
  a log. Only a `key_source` pointer (e.g. `"env:ANTHROPIC_API_KEY"`). **Env-only for launch** —
  reads happen at runtime from env; OS-keyring support is a post-launch nicety, not in scope now.
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
