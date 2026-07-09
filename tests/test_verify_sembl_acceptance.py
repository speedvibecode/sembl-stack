"""O12 WP2 §4.4: `SemblVerifyAdapter.verify()` forwards `acceptance` on both transports,
and OMITS it entirely when empty (back-compat with an older gate that lacks the param).

Never calls the real `sembl` gate here — both transports are mocked so this stays a
pure unit test of the argument-shaping the adapter does.
"""
from __future__ import annotations

import json
from pathlib import Path

from sembl_stack.adapters import verify_sembl as vs
from sembl_stack.adapters.base import Bounds, Change
from sembl_stack.adapters.verify_sembl import SemblVerifyAdapter
from sembl_stack.transport import mcp_client

_ACCEPTANCE = {
    "declared": [{"id": "c1", "kind": "example", "profile": "command"}],
    "results": [{"id": "c1", "outcome": "FAIL", "detail": "exit_code 1 != expected 0"}],
}


def _bounds():
    return Bounds(editable_paths=["a/"], forbidden_areas=[], churn_budget={})


def _change():
    return Change(diff="diff --git a/x b/x\n+1\n", report={})


# --- MCP transport -------------------------------------------------------------

def test_verify_forwards_acceptance_on_mcp(monkeypatch):
    captured = {}

    monkeypatch.setattr(mcp_client, "available", lambda: True)

    def fake_call_tool(server, tool, args):
        captured["tool"] = tool
        captured["args"] = args
        return {"verdict": "BLOCK", "reasons": ["behavioral checks failed: c1"]}

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)

    adapter = SemblVerifyAdapter(transport="mcp")
    verdict = adapter.verify(_bounds(), _change(), True, acceptance=_ACCEPTANCE)

    assert captured["tool"] == "verify_change"
    assert captured["args"]["acceptance"] == _ACCEPTANCE
    assert verdict.status == "BLOCK"


def test_verify_omits_acceptance_on_mcp_when_empty(monkeypatch):
    captured = {}

    monkeypatch.setattr(mcp_client, "available", lambda: True)

    def fake_call_tool(server, tool, args):
        captured["args"] = args
        return {"verdict": "PASS", "reasons": []}

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)

    adapter = SemblVerifyAdapter(transport="mcp")
    adapter.verify(_bounds(), _change(), True)                     # no acceptance at all
    adapter.verify(_bounds(), _change(), True, acceptance=None)     # explicit None
    adapter.verify(_bounds(), _change(), True,
                   acceptance={"declared": [], "results": []})      # explicit empty

    assert "acceptance" not in captured["args"]


# --- CLI transport ---------------------------------------------------------------

def test_verify_cli_writes_acceptance_file_and_passes_flag(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        if "--acceptance" in cmd:
            af = Path(cmd[cmd.index("--acceptance") + 1])
            captured["acceptance_file_content"] = json.loads(af.read_text(encoding="utf-8"))

        class P:
            returncode = 0
            stdout = json.dumps({"verdict": "BLOCK", "reasons": ["behavioral checks failed: c1"]})
            stderr = ""
        return P()

    monkeypatch.setattr(vs.subprocess, "run", fake_run)

    adapter = SemblVerifyAdapter(transport="cli")
    verdict = adapter.verify(_bounds(), _change(), True, acceptance=_ACCEPTANCE)

    assert "--acceptance" in captured["cmd"]
    assert captured["acceptance_file_content"] == _ACCEPTANCE
    assert verdict.status == "BLOCK"


def test_verify_cli_omits_acceptance_flag_when_empty(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class P:
            returncode = 0
            stdout = json.dumps({"verdict": "PASS", "reasons": []})
            stderr = ""
        return P()

    monkeypatch.setattr(vs.subprocess, "run", fake_run)

    adapter = SemblVerifyAdapter(transport="cli")
    verdict = adapter.verify(_bounds(), _change(), True)   # no acceptance declared at all

    assert "--acceptance" not in captured["cmd"]
    assert verdict.status == "PASS"
