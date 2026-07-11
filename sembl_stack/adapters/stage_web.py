"""L4.5 stage harness adapter: `stage: web` (SPEC-stage-preview-as-evidence, WP-B/C).

Boots the declared server as a live process inside the L4 sandbox, on an OS-assigned
free port, and waits for it to answer before handing back a `StageHandle` — so the
loop's stage node (WP-C) can fetch declared routes' rendered DOM as evidence bound to
the attempt's diff SHA. Deterministic machinery only (O3): this adapter never judges
what the server renders, it only opens/observes/tears down the process. No LLM, no
new MCP tool, no capture (D-S4 is out of this slice).
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
import urllib.request

from .acceptance_command import _resolve_shim, _to_argv

_DEFAULT_READY_TIMEOUT_S = 60
_MAX_READY_TIMEOUT_S = 300
_DEFAULT_SNAPSHOT_TIMEOUT_S = 10
_POLL_INTERVAL_S = 0.2
_DRAIN_CAP_BYTES = 8000
_CLOSE_WAIT_S = 10


class StageBootError(RuntimeError):
    """Raised by `WebStageHarness.open()` when the declared server never became
    ready — either it exited on its own (a real boot failure) or the ready-check
    timed out while it was still running. `stderr` carries whatever the process
    emitted so the loop can record an honest reason, never a bare "failed to
    start"."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


def _free_port() -> int:
    """An OS-assigned free TCP port. Never fixed — two attempts never collide."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Drain:
    """Continuously drains a subprocess text stream into a bounded tail buffer.

    A chatty dev server that nobody reads from can fill its OS pipe buffer and
    block on write forever, wedging the boot — this daemon thread keeps the pipe
    empty for the life of the process. Only the last `_DRAIN_CAP_BYTES` characters
    survive (evidence for a boot-failure diagnosis, not an unbounded log)."""

    def __init__(self, stream):
        self._lines: list[str] = []
        self._total = 0
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, args=(stream,), daemon=True)
        self._thread.start()

    def _run(self, stream) -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                with self._lock:
                    self._lines.append(line)
                    self._total += len(line)
                    while self._total > _DRAIN_CAP_BYTES and len(self._lines) > 1:
                        dropped = self._lines.pop(0)
                        self._total -= len(dropped)
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def text(self) -> str:
        with self._lock:
            return "".join(self._lines)


def _bind_lifetime_to_this_process(proc: subprocess.Popen):
    """Windows: put the stage server in a kill-on-close Job Object owned by THIS
    process, so the OS reaps the whole server tree even when the loop dies without
    running any cleanup (`kill -9`, crash, closed terminal — the spec's orphan
    guarantee). Descendants the server spawns join the job automatically. Returns
    the job handle (must stay referenced for the server's lifetime) or None —
    best-effort: a denied assignment degrades to `.close()`-only teardown, never
    an error. POSIX already gets this via `start_new_session` + killpg on close;
    parent-death reaping there is a documented gap (prctl is Linux-only)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None

        class _BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BasicLimits),
                        ("IoInfo", _IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info),
                                           ctypes.sizeof(info)):  # 9 = ExtendedLimitInformation
            k32.CloseHandle(job)
            return None
        if not k32.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle)):
            k32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _kill_tree(proc: subprocess.Popen, timeout: int = _CLOSE_WAIT_S) -> None:
    """Kill `proc` and every descendant it spawned (a dev server commonly forks a
    bundler/watcher). Windows: `taskkill /T /F` (mirrors the deploy_vercel-shim
    lesson — a CreateProcess-launched tree doesn't die from a single
    `.terminate()`). POSIX: the process was started in its own session
    (`start_new_session=True`), so killing the process group takes the whole
    tree. Never raises — a stray already-dead process is not a caller-visible
    failure."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, timeout=timeout)
        else:
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
    except Exception:
        pass
    try:
        proc.wait(timeout=timeout)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=timeout)
        except Exception:
            pass


def _wait_ready(proc: subprocess.Popen, url: str, timeout_s: float):
    """Poll `url` until it answers, `proc` exits, or `timeout_s` elapses.
    Returns `(ok, detail)`. Any HTTP response (including a 404) counts as ready —
    this slice observes, it never judges (O3); only a connection-level failure
    keeps the poll going."""
    deadline = time.perf_counter() + timeout_s
    last_err = None
    while time.perf_counter() < deadline:
        rc = proc.poll()
        if rc is not None:
            return False, f"stage server exited before ready (exit code {rc})"
        try:
            with urllib.request.urlopen(url, timeout=2):
                pass
            return True, None
        except Exception as exc:
            last_err = exc
        time.sleep(_POLL_INTERVAL_S)
    rc = proc.poll()
    if rc is not None:
        return False, f"stage server exited before ready (exit code {rc})"
    return False, f"ready-check timed out after {timeout_s}s (last error: {last_err})"


class StageHandle:
    """A live stage instance. `.url` is stable for the handle's lifetime;
    `.close()` is idempotent and always safe to call more than once."""

    def __init__(self, url: str, port: int, workdir: str, serve_argv: list,
                 process: subprocess.Popen, out_drain: _Drain, err_drain: _Drain,
                 job=None):
        self.url = url
        self.port = port
        self.workdir = workdir
        self.serve_argv = serve_argv
        self._process = process
        self._out = out_drain
        self._err = err_drain
        self._job = job          # kill-on-close Job Object handle; alive = server caged
        self._closed = False

    def snapshot(self, routes: list) -> dict:
        """HTTP GET every declared route; never raises — an unreachable route
        becomes an ERROR entry in the returned dict, not a crash (D-S2: DOM-only,
        plain HTTP GET for this slice, no JS execution)."""
        out: dict = {}
        for route in routes:
            url = self._route_url(route)
            try:
                with urllib.request.urlopen(url, timeout=_DEFAULT_SNAPSHOT_TIMEOUT_S) as resp:
                    body = resp.read().decode("utf-8", "replace")
                    out[route] = {"status": "OK", "html": body,
                                  "http_status": resp.status}
            except Exception as exc:
                out[route] = {"status": "ERROR", "html": None, "detail": str(exc)}
        return out

    def _route_url(self, route: str) -> str:
        base = self.url.rstrip("/")
        if not route or route == "/":
            return base + "/"
        return base + "/" + route.lstrip("/")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process is not None:
            _kill_tree(self._process)
        if self._job is not None:
            # releasing the kill-on-close job handle also reaps any straggler the
            # taskkill above raced with, then frees the handle itself
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self._job)
            except Exception:
                pass
            self._job = None

    def stderr_tail(self) -> str:
        return self._err.text() if self._err is not None else ""

    def stdout_tail(self) -> str:
        return self._out.text() if self._out is not None else ""


class WebStageHarness:
    """`stage: web` — boots the declared serve command against an OS-assigned free
    port and waits for it to answer before handing back a `StageHandle`.

    `decl` (the per-run declaration, e.g. from `sembl.stack.yaml`'s top-level
    `stage:` block) shape: `{"serve": "npm run dev -- -p {port}",
    "ready": "http://127.0.0.1:{port}/", "routes": ["/"], "ready_timeout_s": 60}`.
    `{port}` is substituted with the assigned port in both `serve` and `ready`.
    """

    def __init__(self, ready_timeout_s: int = _DEFAULT_READY_TIMEOUT_S,
                 snapshot_timeout_s: int = _DEFAULT_SNAPSHOT_TIMEOUT_S):
        try:
            ready_timeout_s = int(ready_timeout_s)
        except (TypeError, ValueError):
            ready_timeout_s = _DEFAULT_READY_TIMEOUT_S
        self.ready_timeout_s = min(max(ready_timeout_s, 1), _MAX_READY_TIMEOUT_S)
        self.snapshot_timeout_s = snapshot_timeout_s

    def open(self, sandbox, decl: dict) -> StageHandle:
        decl = decl or {}
        serve = decl.get("serve")
        argv = _to_argv(serve)
        if not argv:
            raise StageBootError("stage.serve not declared (the web stage harness "
                                 "requires one)")
        port = _free_port()
        argv = [str(tok).replace("{port}", str(port)) for tok in argv]
        argv = _resolve_shim(argv)
        ready_tpl = decl.get("ready") or "http://127.0.0.1:{port}/"
        ready_url = ready_tpl.replace("{port}", str(port))
        timeout_s = decl.get("ready_timeout_s", self.ready_timeout_s)
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or timeout_s <= 0:
            timeout_s = self.ready_timeout_s
        timeout_s = min(timeout_s, _MAX_READY_TIMEOUT_S)
        workdir = getattr(sandbox, "workdir", None) or "."

        popen_kwargs: dict = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        try:
            proc = subprocess.Popen(
                argv, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                **popen_kwargs)
        except (OSError, ValueError) as exc:
            raise StageBootError(f"failed to start stage server: {exc}") from exc

        job = _bind_lifetime_to_this_process(proc)
        out_drain = _Drain(proc.stdout)
        err_drain = _Drain(proc.stderr)

        ok, detail = _wait_ready(proc, ready_url, timeout_s)
        if not ok:
            _kill_tree(proc)
            raise StageBootError(detail or "stage server never became ready",
                                 stderr=err_drain.text())

        return StageHandle(url=ready_url, port=port, workdir=workdir, serve_argv=argv,
                           process=proc, out_drain=out_drain, err_drain=err_drain,
                           job=job)
