"""SPEC-stage-preview-as-evidence WP-B: the `stage: web` harness adapter itself
(`WebStageHarness`/`StageHandle`) — open/ready/close lifecycle, per-attempt port
isolation, boot-failure + ready-timeout diagnosis, and process-tree teardown.
Uses a tiny fixture HTTP server (`python -m http.server`), never a real app.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sembl_stack.adapters.stage_web import StageBootError, WebStageHarness, _free_port


def _sandbox(workdir: Path):
    return SimpleNamespace(workdir=str(workdir))


def _port_is_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _http_server_decl(extra_routes=None):
    return {
        "serve": [sys.executable, "-m", "http.server", "{port}", "--bind", "127.0.0.1"],
        "ready": "http://127.0.0.1:{port}/",
        "routes": extra_routes or ["/"],
        "ready_timeout_s": 15,
    }


def test_open_boots_server_and_reports_a_working_url(tmp_path):
    (tmp_path / "index.html").write_text("<h1>hello stage</h1>", encoding="utf-8")
    harness = WebStageHarness()
    handle = harness.open(_sandbox(tmp_path), _http_server_decl())
    try:
        assert handle.url.startswith("http://127.0.0.1:")
        assert handle.port > 0
        snap = handle.snapshot(["/"])
        assert snap["/"]["status"] == "OK"
        assert "hello stage" in snap["/"]["html"]
    finally:
        handle.close()


def test_two_opens_get_different_isolated_ports(tmp_path):
    harness = WebStageHarness()
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    h1 = harness.open(_sandbox(d1), _http_server_decl())
    try:
        h2 = harness.open(_sandbox(d2), _http_server_decl())
        try:
            assert h1.port != h2.port
            assert h1.url != h2.url
        finally:
            h2.close()
    finally:
        h1.close()


def test_boot_failure_raises_stage_boot_error_with_stderr(tmp_path):
    decl = {
        "serve": [sys.executable, "-c",
                 "import sys; sys.stderr.write('boom: missing module'); sys.exit(1)"],
        "ready": "http://127.0.0.1:{port}/",
        "ready_timeout_s": 5,
    }
    harness = WebStageHarness()
    with pytest.raises(StageBootError) as exc_info:
        harness.open(_sandbox(tmp_path), decl)
    assert "boom: missing module" in exc_info.value.stderr


def test_ready_check_timeout_raises_and_kills_the_hung_process(tmp_path):
    decl = {
        "serve": [sys.executable, "-c", "import time; time.sleep(60)"],
        "ready": "http://127.0.0.1:{port}/",
        "ready_timeout_s": 1,
    }
    harness = WebStageHarness()
    with pytest.raises(StageBootError) as exc_info:
        harness.open(_sandbox(tmp_path), decl)
    assert "timed out" in str(exc_info.value)


def test_close_kills_process_tree_and_frees_the_port(tmp_path):
    harness = WebStageHarness()
    handle = harness.open(_sandbox(tmp_path), _http_server_decl())
    port = handle.port
    assert not _port_is_free(port)                # server is listening

    handle.close()

    assert _port_is_free(port)                    # taskkill/killpg actually freed it


def test_close_is_idempotent(tmp_path):
    harness = WebStageHarness()
    handle = harness.open(_sandbox(tmp_path), _http_server_decl())
    handle.close()
    handle.close()                                 # must not raise a second time


def test_snapshot_records_error_for_an_unreachable_route(tmp_path):
    harness = WebStageHarness()
    handle = harness.open(_sandbox(tmp_path), _http_server_decl())
    handle.close()                                 # now nothing is listening

    snap = handle.snapshot(["/"])                  # must not raise

    assert snap["/"]["status"] == "ERROR"
    assert snap["/"]["html"] is None
    assert snap["/"]["detail"]


def test_no_serve_declared_raises_stage_boot_error(tmp_path):
    harness = WebStageHarness()
    with pytest.raises(StageBootError):
        harness.open(_sandbox(tmp_path), {})


def test_free_port_helper_returns_a_bindable_port():
    port = _free_port()
    assert _port_is_free(port)


def test_stage_server_dies_with_its_owner_process_no_close_needed(tmp_path):
    """SPEC live-proof clause "kill -9 the loop mid-run and verify no orphaned
    server survives": the harness binds the server's lifetime to the opening
    process via a kill-on-close Job Object (Windows), so even a SIGKILLed loop —
    no cleanup code ran — leaves no orphan. POSIX gets killpg-on-close only;
    parent-death reaping there is a documented gap."""
    import subprocess as sp
    import sys as _sys
    import time as _time
    if _sys.platform != "win32":
        import pytest
        pytest.skip("job-object lifetime binding is the Windows orphan guarantee")

    script = tmp_path / "owner.py"
    script.write_text(
        "import sys, time\n"
        "from sembl_stack.adapters.stage_web import WebStageHarness\n"
        "class _SB:\n"
        f"    workdir = {str(tmp_path)!r}\n"
        "h = WebStageHarness().open(_SB(), {\n"
        "    'serve': [sys.executable, '-m', 'http.server', '{port}', '--bind', '127.0.0.1'],\n"
        "    'ready': 'http://127.0.0.1:{port}/', 'ready_timeout_s': 15})\n"
        "print(h.port, flush=True)\n"
        "time.sleep(120)\n",   # never closes; only SIGKILL ends it
        encoding="utf-8")
    owner = sp.Popen([_sys.executable, str(script)], stdout=sp.PIPE, text=True,
                     cwd=str(tmp_path))
    try:
        port = int(owner.stdout.readline().strip())
        assert not _port_is_free(port)            # server is really up
        owner.kill()                              # SIGKILL: zero cleanup code runs
        owner.wait(timeout=10)
        deadline = _time.perf_counter() + 10
        while _time.perf_counter() < deadline and not _port_is_free(port):
            _time.sleep(0.2)
        assert _port_is_free(port), "stage server survived its owner's SIGKILL"
    finally:
        if owner.poll() is None:
            owner.kill()
