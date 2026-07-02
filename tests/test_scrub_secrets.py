"""scrub_secrets: executor stdout/stderr must never carry a credential into a run artifact.

The executors persist output tails into `.sembl/runs/<id>/change.json` for debuggability;
a CLI that echoes its key in an auth error must not turn that into a stored secret
(codex review of 161b6e7, finding 1).
"""
from __future__ import annotations

from sembl_stack.adapters import base
from sembl_stack.adapters import execute_opencode as oc
from sembl_stack.adapters.base import Bounds, Task


def test_env_secret_value_redacted(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "live-THE-SECRET-VALUE-123")
    out = base.scrub_secrets("auth failed for key live-THE-SECRET-VALUE-123 (401)")
    assert "THE-SECRET-VALUE" not in out
    assert "[redacted:ANTHROPIC_API_KEY]" in out


def test_generic_sk_token_redacted_even_if_not_in_env():
    out = base.scrub_secrets("using sk-proj-abcdef1234567890 for auth")
    assert "sk-proj-abcdef1234567890" not in out
    assert "[redacted:key]" in out


def test_short_env_values_left_alone(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "yes")   # too short to be a secret; don't mangle output
    assert base.scrub_secrets("yes: build passed") == "yes: build passed"


def test_empty_text_passthrough():
    assert base.scrub_secrets("") == ""


def test_adapter_report_is_scrubbed(monkeypatch):
    secret = "sk-or-v1-0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)

    def fake_run(cmd, **kwargs):
        class P:
            returncode = 1
            stdout = f"error: invalid key {secret}"
            stderr = f"auth: {secret}"
        return P()

    monkeypatch.setattr(oc, "_resolve_opencode", lambda: ["opencode"])
    monkeypatch.setattr(oc.subprocess, "run", fake_run)

    class FakeSandbox:
        workdir = "/tmp/wd"
        def diff(self):
            return ""

    result = oc.OpenCodeExecutor().run(
        Task(text="t", repo="/tmp/wd"),
        Bounds(editable_paths=[], forbidden_areas=[]),
        FakeSandbox(), feedback=None)
    assert secret not in str(result.report)
