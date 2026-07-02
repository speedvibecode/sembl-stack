"""Profile core (Phase-1 onboarding): persistence, detection, preflight, and the
security invariant that no key value is ever serialized."""
import json

import pytest

from sembl_stack import profile as prof
from sembl_stack.profile import Profile


# --- persistence ----------------------------------------------------------------

def test_round_trip(tmp_path):
    p = tmp_path / "profile.json"
    original = Profile(runner="api-key", executor="opencode",
                       model="tokenrouter/MiniMax-M3",
                       key_source="env:OPENROUTER_API_KEY", strict=False, preset="full-loop")
    prof.save(original, p)
    assert prof.load(p) == original


def test_missing_file_is_none(tmp_path):
    assert prof.load(tmp_path / "nope.json") is None


@pytest.mark.parametrize("content", [
    "not json at all", '"a string"', '{"runner": "unknown-strategy"}',
    '{"runner": "api-key", "key_source": "sk-ant-actual-secret-value"}',
])
def test_unusable_file_is_none_never_crash(tmp_path, content):
    p = tmp_path / "profile.json"
    p.write_text(content, encoding="utf-8")
    assert prof.load(p) is None


def test_old_file_with_extra_keys_still_loads(tmp_path):
    p = tmp_path / "profile.json"
    p.write_text(json.dumps({"runner": "mock", "executor": "mock",
                             "some_future_field": 1}), encoding="utf-8")
    loaded = prof.load(p)
    assert loaded is not None and loaded.runner == "mock"


# --- the security invariant -----------------------------------------------------

def test_save_refuses_secret_shaped_key_source(tmp_path):
    p = tmp_path / "profile.json"
    with pytest.raises(ValueError):
        prof.save(Profile(runner="api-key", key_source="sk-ant-api03-XXXX"), p)
    assert not p.exists()   # nothing was written


def test_no_key_value_is_ever_serialized(tmp_path, monkeypatch):
    secret = "sk-ant-live-THE-SECRET"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    p = tmp_path / "profile.json"
    prof.save(Profile(runner="api-key", executor="claude",
                      key_source="env:ANTHROPIC_API_KEY"), p)
    on_disk = p.read_text(encoding="utf-8")
    assert secret not in on_disk
    assert "env:ANTHROPIC_API_KEY" in on_disk


# --- stack overrides ------------------------------------------------------------

def test_overrides_claude_login():
    over = prof.to_stack_overrides(Profile(runner="claude-login", executor="claude"))
    assert over["layers"]["execute"] == "claude"
    assert over["loop"]["strict"] is True
    assert "options" not in over    # no model chosen -> adapter default


def test_overrides_api_key_with_model():
    over = prof.to_stack_overrides(Profile(
        runner="api-key", executor="opencode", model="tokenrouter/MiniMax-M3", strict=False))
    assert over["layers"]["execute"] == "opencode"
    assert over["options"]["execute"]["model"] == "tokenrouter/MiniMax-M3"
    assert over["loop"]["strict"] is False


def test_overrides_mock():
    assert prof.to_stack_overrides(Profile())["layers"]["execute"] == "mock"


# --- auto-detection (presence only — never reads a key value) --------------------

def test_detect_prefers_claude_login(monkeypatch):
    monkeypatch.setattr(prof.shutil, "which", lambda b: "C:/bin/claude" if b == "claude" else None)
    p = prof.detect()
    assert (p.runner, p.executor) == ("claude-login", "claude")


def test_detect_falls_back_to_env_key(monkeypatch):
    monkeypatch.setattr(prof.shutil, "which", lambda b: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "whatever")
    p = prof.detect()
    assert p.runner == "api-key" and p.key_source == "env:OPENAI_API_KEY"


def test_detect_nothing_found_is_mock(monkeypatch):
    monkeypatch.setattr(prof.shutil, "which", lambda b: None)
    for var in prof._KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    assert prof.detect().runner == "mock"


# --- config precedence: DEFAULTS < profile overrides < sembl.stack.yaml ----------

def test_profile_overrides_apply_when_no_config_file():
    from sembl_stack.config import load
    over = prof.to_stack_overrides(Profile(runner="claude-login", executor="claude"))
    cfg = load(None, over)
    assert cfg.raw["layers"]["execute"] == "claude"


def test_explicit_config_file_beats_profile(tmp_path):
    from sembl_stack.config import load
    f = tmp_path / "sembl.stack.yaml"
    f.write_text("layers:\n  execute: mock\n", encoding="utf-8")
    over = prof.to_stack_overrides(Profile(runner="claude-login", executor="claude"))
    cfg = load(str(f), over)
    assert cfg.raw["layers"]["execute"] == "mock"   # the file always wins


# --- preflight ------------------------------------------------------------------

def test_preflight_mock_always_ready():
    ok, _ = prof.ready(prof.preflight(Profile()))
    assert ok


def test_preflight_claude_login_needs_binary(monkeypatch):
    monkeypatch.setattr(prof.shutil, "which", lambda b: None)
    ok, fix = prof.ready(prof.preflight(Profile(runner="claude-login", executor="claude")))
    assert not ok and "Claude Code" in fix


def test_preflight_api_key_needs_env_var(monkeypatch):
    monkeypatch.setattr(prof.shutil, "which", lambda b: "C:/bin/claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = Profile(runner="api-key", executor="claude", key_source="env:ANTHROPIC_API_KEY")
    ok, fix = prof.ready(prof.preflight(p))
    assert not ok and "ANTHROPIC_API_KEY" in fix
    monkeypatch.setenv("ANTHROPIC_API_KEY", "present")
    ok, _ = prof.ready(prof.preflight(p))
    assert ok
