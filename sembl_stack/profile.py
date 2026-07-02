"""Phase-1 onboarding core — the BYO-credentials profile (pure, headless).

sembl-stack provides orchestration, not inference: the user brings their own way of paying
for model calls (their Claude Code login, their API key, a local model — or the no-AI mock
preview). This module is the deterministic heart of that onboarding: a `Profile` dataclass
persisted at `~/.sembl/profile.json` (user-level; distinct from the per-repo
`.sembl/session.json`), auto-detection of what's already on the machine, a doctor-style
preflight per runner, and the mapping onto the existing `StackConfig` layers.

Security invariant (launch-credibility, do not weaken): **no key value is ever stored** —
`key_source` holds only a pointer like `"env:ANTHROPIC_API_KEY"`, validated on save; the
actual secret stays in the environment and is read only by the executor at runtime.
No Textual imports here; fully unit-testable.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .doctor import Check

# How the user pays for model calls. Order = preference during auto-detection.
STRATEGIES = ["claude-login", "api-key", "local", "mock"]

# runner -> default L3 executor adapter (user may override in Advanced).
_RUNNER_EXECUTOR = {
    "claude-login": "claude",
    "api-key": "claude",
    "local": "opencode",
    "mock": "mock",
}

# Env vars we auto-detect for the api-key runner, preference order. The var's *presence*
# is all we ever look at — the value is never read into a Profile or an artifact.
_KEY_ENV_VARS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"]

# key_source may only ever be a pointer: an env-var name or (post-launch) the keyring.
_SAFE_KEY_SOURCE = re.compile(r"^(env:[A-Za-z_][A-Za-z0-9_]*|keyring)$")

# model must look like a model id ("claude-opus-4-8", "tokenrouter/MiniMax-M3",
# "ollama/llama3:8b") — short, from a tight charset, and never key-prefixed. This is the
# second half of the security invariant: the free-form Model input is the one field a
# user could paste an API key into, and a key there would otherwise reach profile.json,
# argv (`--model`, visible in the process list), and run reports.
_SAFE_MODEL = re.compile(r"^(?!sk-)[A-Za-z0-9][A-Za-z0-9._:/\-]{0,63}$")


@dataclass
class Profile:
    runner: str = "mock"            # one of STRATEGIES
    executor: str = "mock"          # L3 adapter name (claude|opencode|aider|mock)
    model: str | None = None        # e.g. "claude-opus-4-8", "tokenrouter/MiniMax-M3"
    key_source: str | None = None   # "env:ANTHROPIC_API_KEY" | "keyring" — NEVER the value
    strict: bool = True
    preset: str | None = None       # presets.py name, if the user picked one


def path() -> Path:
    return Path.home() / ".sembl" / "profile.json"


def save(profile: Profile, p: Path | None = None) -> Path:
    """Persist the profile. Refuses anything secret-shaped in `key_source` or `model`."""
    if profile.key_source is not None and not _SAFE_KEY_SOURCE.match(profile.key_source):
        raise ValueError(
            "key_source must be a pointer ('env:VAR_NAME' or 'keyring'), never a key value")
    if profile.model is not None and not _SAFE_MODEL.match(profile.model):
        raise ValueError(
            "model must be a model id (e.g. 'claude-opus-4-8'), never an API key value")
    p = p or path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
    return p


def load(p: Path | None = None) -> Profile | None:
    """Read the saved profile, or None if missing OR unusable.

    A corrupt/old/hand-edited file must never brick the entrypoint — unusable is treated
    exactly like absent (re-onboard), mirroring `session.load`. A profile whose stored
    key_source fails the pointer rule is also unusable: we never trust a secret-shaped
    value back into memory.
    """
    p = p or path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        prof = Profile(**{k: v for k, v in data.items() if k in Profile.__dataclass_fields__})
    except (OSError, ValueError, TypeError):
        return None
    if prof.runner not in STRATEGIES:
        return None
    if prof.key_source is not None and (
            not isinstance(prof.key_source, str) or not _SAFE_KEY_SOURCE.match(prof.key_source)):
        return None
    # The remaining fields flow straight into config/registry/argv — a hand-edited file
    # with the wrong types (or a secret-shaped model) is unusable, same as corrupt.
    if not isinstance(prof.executor, str) or not prof.executor:
        return None
    if prof.model is not None and (
            not isinstance(prof.model, str) or not _SAFE_MODEL.match(prof.model)):
        return None
    if not isinstance(prof.strict, bool):
        return None
    if prof.preset is not None and not isinstance(prof.preset, str):
        return None
    return prof


def to_stack_overrides(profile: Profile) -> dict:
    """The dict the wizard merges into the resolved stack config.

    Maps the BYO choice onto layers the loop already reads — zero new core wiring:
    `layers.execute` (which adapter), `options.execute.model`, `loop.strict`.
    """
    over: dict = {"layers": {"execute": profile.executor},
                  "loop": {"strict": profile.strict}}
    if profile.model:
        over["options"] = {"execute": {"model": profile.model}}
    return over


def detect() -> Profile:
    """Auto-detect the strongest BYO option present; onboarding preselects the result.

    Preference: an existing `claude` install (their Claude Code login — token-free) >
    a known API key in env > a local-model CLI (`opencode`) > the mock preview.
    Detection only checks binary/env *presence* — never reads a key value.
    """
    if shutil.which("claude"):
        return Profile(runner="claude-login", executor="claude")
    for var in _KEY_ENV_VARS:
        if os.environ.get(var):
            executor = "claude" if var == "ANTHROPIC_API_KEY" else "opencode"
            return Profile(runner="api-key", executor=executor, key_source=f"env:{var}")
    if shutil.which("opencode"):
        return Profile(runner="local", executor="opencode")
    return Profile()   # mock — the keyless mechanics preview, never the hero path


def preflight(profile: Profile) -> list[Check]:
    """Doctor-style checks that this runner can actually run — before onboarding proceeds.

    On failure the wizard shows `hint` (the one concrete fix) and stays on the screen;
    a runner that can't run is never persisted as the profile.
    """
    checks: list[Check] = []
    if profile.executor == "mock":
        checks.append(Check("executor: mock", True, "no binary needed", required=False))
    else:
        # Checked even when runner == "mock": an Advanced executor override means a real
        # binary will run, and a profile that can't run must never be persisted.
        from .doctor import _EXECUTOR_BINARY   # single source of binary names + install hints
        binary, hint = _EXECUTOR_BINARY.get(profile.executor, (profile.executor, ""))
        found = shutil.which(binary)
        checks.append(Check(f"executor: {profile.executor}", found is not None,
                            found or "not found", hint))

    if profile.runner == "mock":
        checks.append(Check("runner: mock", True, "no credentials needed", required=False))
    elif profile.runner == "api-key":
        var = (profile.key_source or "")[len("env:"):] if (
            profile.key_source or "").startswith("env:") else ""
        ok = bool(var) and bool(os.environ.get(var))
        checks.append(Check(
            f"api key ({var or 'no env var chosen'})", ok,
            "set in env" if ok else "not set",
            f"set {var or 'your provider API key'} in your environment — sembl only ever "
            "reads it from there at runtime, never stores it"))
    elif profile.runner == "claude-login":
        # Binary presence is the cheap proxy; an un-logged-in `claude` fails loudly on
        # first use with its own login prompt, which is the right UX anyway. Checked
        # against `claude` itself — the executor may be a different binary.
        checks.append(Check(
            "claude login", shutil.which("claude") is not None,
            "uses your existing Claude Code session (token-free)",
            "run `claude` once and log in", required=False))
    return checks


def ready(checks: list[Check]) -> tuple[bool, str]:
    """(ok, first concrete fix) — the wizard's proceed/stay decision."""
    for c in checks:
        if c.required and not c.ok:
            return False, c.hint or f"{c.name}: {c.detail}"
    return True, ""
