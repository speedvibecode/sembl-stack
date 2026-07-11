"""SPEC-stage-preview-as-evidence WP-B/WP-C: the stage node's loop wiring
(open/snapshot/close between execute and acceptance, bus events, --stage-hold)
and the evidence it writes (`stage-<attempt>.json` + `stage-<attempt>/<route>.html`,
bound to the same diff SHA the verdict uses, never colliding across attempts).
Uses a tiny fixture HTTP server (`python -m http.server`), never a real app.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

from sembl_stack import loop as loop_mod
from sembl_stack.adapters.stage_web import WebStageHarness
from sembl_stack.artifacts import Bounds, Change, Verdict, diff_sha256
from sembl_stack.store import RunStore

_DIFF = "diff --git a/x.py b/x.py\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"


def _read_bus(repo):
    path = Path(repo) / ".sembl" / "bus.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _port_is_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _http_stage_decl(routes=None, **extra):
    decl = {
        "serve": [sys.executable, "-m", "http.server", "{port}", "--bind", "127.0.0.1"],
        "ready": "http://127.0.0.1:{port}/",
        "routes": routes or ["/"],
        "ready_timeout_s": 15,
    }
    decl.update(extra)
    return decl


def _make_sandbox_dir(base: Path, n: int, page: str) -> Path:
    d = base / f"attempt-{n}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(page, encoding="utf-8")
    return d


def _cfg(repo, *, raw_extra=None, stage=None, gate=None):
    class _Spec:
        def plan(self, task):
            return Bounds(editable_paths=["x.py"])

    workdirs = {"n": 0}

    class _SandboxAdapter:
        def open(self, r):
            workdirs["n"] += 1
            n = workdirs["n"]
            d = _make_sandbox_dir(repo, n, f"<h1>attempt {n} page</h1>")

            class _Sandbox:
                workdir = str(d)

                def diff(self):
                    return _DIFF

                def close(self):
                    pass
            return _Sandbox()

    class _Executor:
        def run(self, task, bounds, sandbox, feedback):
            return Change(diff=_DIFF, report={"exit_code": 0}, workdir=sandbox.workdir)

    default_gate = SimpleNamespace(verify=lambda bounds, change, strict, **kw: Verdict(status="PASS"))

    class _GateWrap:
        def verify(self, bounds, change, strict, **kw):
            return (gate or default_gate).verify(bounds, change, strict, **kw)

    raw = {"loop": {}}
    if raw_extra:
        raw.update(raw_extra)

    return SimpleNamespace(
        spec=_Spec(), sandbox=_SandboxAdapter(), execute=_Executor(),
        verify=_GateWrap(), acceptance=None, stage=stage,
        strict=True, max_attempts=raw.get("_max_attempts", 2), langfuse=False, raw=raw)


def test_stage_inert_when_no_stage_block_declared(tmp_path):
    cfg = _cfg(tmp_path, stage=WebStageHarness())      # adapter wired, but no `stage:` decl
    cfg.max_attempts = 1
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    bus = _read_bus(tmp_path)
    assert [e for e in bus if e["kind"] in ("stage.up", "stage.down")] == []
    assert not (RunStore(str(tmp_path)).open(result.run_id).dir / "stage-1.json").is_file()


def test_stage_inert_when_adapter_is_none_even_if_declared(tmp_path):
    cfg = _cfg(tmp_path, raw_extra={"stage": _http_stage_decl()}, stage=None)
    cfg.max_attempts = 1
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    bus = _read_bus(tmp_path)
    assert [e for e in bus if e["kind"] in ("stage.up", "stage.down")] == []


def test_stage_boots_writes_manifest_bound_to_verdict_diff_sha_and_snapshots_route(tmp_path):
    cfg = _cfg(tmp_path, raw_extra={"stage": _http_stage_decl()}, stage=WebStageHarness())
    cfg.max_attempts = 1
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    run_dir = RunStore(str(tmp_path)).open(result.run_id).dir
    manifest = json.loads((run_dir / "stage-1.json").read_text(encoding="utf-8"))
    assert manifest["attempt"] == 1
    assert manifest["ready"]["ok"] is True
    assert manifest["diff_sha256"] == diff_sha256(_DIFF)
    assert manifest["diff_sha256"] == result.verdict.raw["subject"]["diff_sha256"]
    assert manifest["routes"]["/"]["status"] == "OK"
    html_path = run_dir / manifest["routes"]["/"]["file"]
    assert html_path.is_file()
    assert "attempt 1 page" in html_path.read_text(encoding="utf-8")


def test_stage_up_and_down_bus_events_carry_run_id_and_attempt(tmp_path):
    cfg = _cfg(tmp_path, raw_extra={"stage": _http_stage_decl()}, stage=WebStageHarness())
    cfg.max_attempts = 1
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    bus = _read_bus(tmp_path)
    up = [e for e in bus if e["kind"] == "stage.up"]
    down = [e for e in bus if e["kind"] == "stage.down"]
    assert len(up) == 1 and len(down) == 1
    assert up[0]["run_id"] == result.run_id == down[0]["run_id"]
    assert up[0]["data"]["attempt"] == 1 == down[0]["data"]["attempt"]
    assert up[0]["data"]["url"] == down[0]["data"]["url"]


def test_stage_boot_failure_blocks_attempt_and_manifest_records_stderr(tmp_path):
    bad_decl = {
        "serve": [sys.executable, "-c",
                 "import sys; sys.stderr.write('cannot bind: EADDRNOTAVAIL'); sys.exit(1)"],
        "ready": "http://127.0.0.1:{port}/",
        "ready_timeout_s": 5,
    }
    cfg = _cfg(tmp_path, raw_extra={"stage": bad_decl}, stage=WebStageHarness())
    cfg.max_attempts = 1
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)              # must not raise

    assert result.verdict.status == "BLOCK"
    assert any("stage failed to boot" in r for r in result.verdict.reasons)
    run_dir = RunStore(str(tmp_path)).open(result.run_id).dir
    manifest = json.loads((run_dir / "stage-1.json").read_text(encoding="utf-8"))
    assert manifest["ready"]["ok"] is False
    assert "EADDRNOTAVAIL" in manifest["ready"]["stderr"]
    assert manifest["diff_sha256"] == diff_sha256(_DIFF)


def test_two_attempts_stage_manifests_never_collide(tmp_path):
    calls = {"n": 0}

    class _FlakyGate:
        def verify(self, bounds, change, strict, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return Verdict(status="BLOCK", reasons=["retry me"])
            return Verdict(status="PASS")

    cfg = _cfg(tmp_path, raw_extra={"stage": _http_stage_decl()}, stage=WebStageHarness(),
              gate=_FlakyGate())
    cfg.max_attempts = 2
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    assert result.attempts == 2
    run_dir = RunStore(str(tmp_path)).open(result.run_id).dir
    m1 = json.loads((run_dir / "stage-1.json").read_text(encoding="utf-8"))
    m2 = json.loads((run_dir / "stage-2.json").read_text(encoding="utf-8"))
    assert m1["attempt"] == 1
    assert m2["attempt"] == 2
    assert m1["port"] != m2["port"]                # a fresh port per attempt
    html1 = run_dir / m1["routes"]["/"]["file"]
    html2 = run_dir / m2["routes"]["/"]["file"]
    assert html1 != html2
    assert "attempt 1 page" in html1.read_text(encoding="utf-8")
    assert "attempt 2 page" in html2.read_text(encoding="utf-8")

    bus = _read_bus(tmp_path)
    up_attempts = [e["data"]["attempt"] for e in bus if e["kind"] == "stage.up"]
    down_attempts = [e["data"]["attempt"] for e in bus if e["kind"] == "stage.down"]
    assert up_attempts == [1, 2]
    assert down_attempts == [1, 2]                 # attempt 1's stage came down before retry


def test_stage_hold_keeps_final_attempt_alive_and_returns_handle(tmp_path):
    cfg = _cfg(tmp_path, raw_extra={"stage": _http_stage_decl()}, stage=WebStageHarness())
    cfg.max_attempts = 1
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task, stage_hold=True)

    try:
        assert result.verdict.status == "PASS"
        assert result.stage_handle is not None
        port = result.stage_handle.port
        assert not _port_is_free(port)             # still up: --stage-hold kept it alive
        snap = result.stage_handle.snapshot(["/"])
        assert snap["/"]["status"] == "OK"

        bus = _read_bus(tmp_path)
        down = [e for e in bus if e["kind"] == "stage.down"]
        assert down == []                          # never closed automatically
    finally:
        if result.stage_handle is not None:
            result.stage_handle.close()             # test cleanup: no orphan process


def test_stage_without_hold_closes_after_the_final_attempt(tmp_path):
    cfg = _cfg(tmp_path, raw_extra={"stage": _http_stage_decl()}, stage=WebStageHarness())
    cfg.max_attempts = 1
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task, stage_hold=False)

    assert result.verdict.status == "PASS"
    assert result.stage_handle is None
    bus = _read_bus(tmp_path)
    assert len([e for e in bus if e["kind"] == "stage.down"]) == 1


def test_acceptance_checks_see_the_stage_url_in_env(tmp_path):
    """Lead-review fix (found live on the flagship, 2026-07-12): the stage boots
    before acceptance so checks can USE the running app — `SEMBL_STAGE_URL` is the
    discovery contract, exported only while checks run, restored afterwards
    (a second dev server in the same dir hits Next 16's single-instance lock)."""
    import os

    seen = {}

    class _Runner:
        def run(self, acceptance, sandbox, task, bounds):
            seen["url"] = os.environ.get("SEMBL_STAGE_URL")
            from sembl_stack.artifacts import AcceptanceReport
            return AcceptanceReport(results=[
                {"id": "smoke", "outcome": "PASS", "seed": None,
                 "duration_s": 0.0, "evidence": "", "detail": ""}])

    (tmp_path / "acceptance.json").write_text(json.dumps({
        "version": 1,
        "checks": [{"id": "smoke", "profile": "command@1", "run": ["true"],
                    "expect": {"exit_code": 0}}],
    }), encoding="utf-8")
    cfg = _cfg(tmp_path, raw_extra={"stage": _http_stage_decl()}, stage=WebStageHarness())
    cfg.max_attempts = 1
    cfg.acceptance = _Runner()
    task = SimpleNamespace(text="add x", repo=str(tmp_path))

    result = loop_mod.run(cfg, task)

    assert result.verdict.status == "PASS"
    assert seen["url"] and seen["url"].startswith("http://127.0.0.1:")
    assert os.environ.get("SEMBL_STAGE_URL") is None   # restored, never leaked
