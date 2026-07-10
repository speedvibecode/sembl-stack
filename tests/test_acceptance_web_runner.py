"""O12 WP3: the `web` acceptance runner adapter + its flagship live-proof.

`web` is a thin profile-specific layer over `CommandAcceptanceRunner` (WP2): it
adds a Node-toolchain preflight (fail-closed, actionable ERROR) and a longer
default timeout, then delegates everything else (shim resolution, evidence
scrubbing, expect-matching) to the already-proven command machinery.

The planted-break test is the real given/when/then flow: it drives
`examples/flagship-feedback-board` through the actual runner (an `npx next dev`
invocation), temporarily mutating the app's local-preview fallback dataset so the
rendered DOM breaks, and restores the original file (and the `next dev`-regenerated
`next-env.d.ts`) in a `finally` — the break exists ONLY for the duration of this
test and is never committed.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

from sembl_stack.adapters import acceptance_web as aw_mod
from sembl_stack.adapters.acceptance_web import WebAcceptanceRunner
from sembl_stack.artifacts import Acceptance

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FLAGSHIP = _REPO_ROOT / "examples" / "flagship-feedback-board"
_FEEDBACK_TS = _FLAGSHIP / "src" / "lib" / "feedback.ts"
_NEXT_ENV = _FLAGSHIP / "next-env.d.ts"
_WEB_CHECK_SCRIPT = _FLAGSHIP / "scripts" / "web-check-feedback-board.mjs"
_BROKEN_TITLE = "Invite review needs a status trail"


class _Sandbox:
    def __init__(self, workdir):
        self.workdir = workdir


def _check(cid, command, expect=None, timeout_s=90):
    return {"id": cid, "kind": "example", "profile": "web",
            "run": {"command": command}, "expect": expect or {},
            "seed": None, "timeout_s": timeout_s}


def test_web_runner_maps_exit_code_to_pass():
    runner = WebAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "ok", [sys.executable, "-c", "print('hi')"], {"exit_code": 0})])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "PASS"
    assert report.runner == "web@1"
    assert report.any_failed is False


def test_web_runner_maps_exit_code_to_fail():
    runner = WebAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "bad", [sys.executable, "-c", "import sys; sys.exit(1)"], {"exit_code": 0})])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "FAIL"
    assert "exit_code" in r["detail"]
    assert report.any_failed is True


def test_web_runner_missing_node_npx_errors_with_actionable_detail(monkeypatch):
    # Simulate an environment with no Node toolchain on PATH at all, without
    # uninstalling anything: monkeypatch the module's `shutil.which` lookup.
    monkeypatch.setattr(aw_mod.shutil, "which", lambda name: None)
    runner = WebAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "needs-node", [sys.executable, "-c", "print(1)"], {"exit_code": 0})])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "ERROR"
    assert "node" in r["detail"].lower()
    assert "install" in r["detail"].lower()


def test_web_runner_rejects_check_with_no_command():
    runner = WebAcceptanceRunner()
    acc = Acceptance(checks=[_check("no-cmd", None)])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "ERROR"
    assert "run.command" in r["detail"]


def test_web_runner_profile_default_timeout_survives_artifact_coercion():
    # The web profile's longer default_timeout must reach the subprocess through the
    # REAL path (raw dict -> Acceptance coercion -> runner). Coercion once injected
    # its own 120s default, silently making every profile-level default unreachable.
    runner = WebAcceptanceRunner(default_timeout=1)
    check = _check("slow", [sys.executable, "-c", "import time; time.sleep(5)"],
                   {"exit_code": 0})
    del check["timeout_s"]
    acc = Acceptance(checks=[check])
    assert acc.checks[0]["timeout_s"] is None   # declaration layer preserved absence
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "ERROR"
    assert "timed out after 1s" in r["detail"]


def test_web_check_determinism_no_external_network():
    """The flagship's declared example acceptance.json web check, and the script it
    invokes, must never reach beyond localhost."""
    snippet_path = _FLAGSHIP / "acceptance.json"
    declared = json.loads(snippet_path.read_text(encoding="utf-8"))
    web_checks = [c for c in declared["checks"] if c.get("profile") == "web"]
    assert web_checks, "expected at least one profile:web check in the example snippet"
    for check in web_checks:
        command_blob = json.dumps(check["run"]["command"])
        assert "http://" not in command_blob and "https://" not in command_blob, (
            f"web check {check['id']!r} run.command must not hardcode a network "
            f"URL: {command_blob}")

    script_src = _WEB_CHECK_SCRIPT.read_text(encoding="utf-8")
    urls = re.findall(r'https?://[^\s"\'`]+', script_src)
    assert urls, "expected the script to construct at least one fetch URL"
    for url in urls:
        assert url.startswith("http://127.0.0.1") or url.startswith("http://localhost"), (
            f"web check script must only ever fetch localhost, found: {url}")


@pytest.mark.skipif(shutil.which("npx") is None, reason="requires Node/npx on PATH")
def test_web_runner_planted_break_fails_real_flagship_flow():
    """The real given/when/then flow, driven through the actual runner: Given the
    feedback board with Supabase unconfigured normally renders 3 fallback items,
    When one item's title is planted-broken and the check runs via `npx next dev`,
    Then the runner reports FAIL with the broken flow's reason in the evidence."""
    assert _FEEDBACK_TS.is_file(), "flagship fixture file missing"
    original = _FEEDBACK_TS.read_text(encoding="utf-8")
    original_next_env = _NEXT_ENV.read_text(encoding="utf-8") if _NEXT_ENV.is_file() else None
    assert _BROKEN_TITLE in original, "fixture assumption changed upstream"
    broken = original.replace(_BROKEN_TITLE, "PLANTED BREAK: title removed")
    assert broken != original

    runner = WebAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "flagship-board-renders",
        ["node", "scripts/web-check-feedback-board.mjs"],
        {"exit_code": 0}, timeout_s=90)])

    try:
        _FEEDBACK_TS.write_text(broken, encoding="utf-8")
        report = runner.run(acc, _Sandbox(str(_FLAGSHIP)), task=None, bounds=None)
    finally:
        _FEEDBACK_TS.write_text(original, encoding="utf-8")
        if original_next_env is not None:
            _NEXT_ENV.write_text(original_next_env, encoding="utf-8")

    r = report.results[0]
    assert r["outcome"] == "FAIL"
    assert "missing expected" in r["evidence"] or _BROKEN_TITLE in r["evidence"]
