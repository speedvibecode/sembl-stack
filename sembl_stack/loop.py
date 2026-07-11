"""L6 orchestration: the short loop as a state machine.

plan (L2) -> execute (L3, in a fresh sandbox L4) -> verify (L5) ->
  BLOCK & attempts left? feed the gate's reasons back and retry
  PASS/WARN? accept.

Driven by LangGraph when installed (real retry graph + checkpointable), with a
built-in fallback runner of identical semantics so the loop boots with zero extra
installs. Every node is wrapped in a Langfuse span via the tracer.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from .adapters.acceptance_command import _resolve_shim, _to_argv
from .adapters.base import Task, Verdict
from .adapters.stage_web import StageBootError
from .artifacts import AcceptanceReport, Change, Trace, bind_verdict, diff_sha256
from .bus import publish
from .config import StackConfig, load_acceptance
from .specgraph import build_spec_graph
from .store import RunStore
from .tracing import get_tracer


class LoopState(TypedDict, total=False):
    """The state threaded through the graph (last-value channels)."""
    attempt: int
    feedback: str | None
    history: list
    bounds: Any
    sandbox: Any
    result: Any
    prepare_error: str | None   # WP-A: sandbox.prepare failure reason this attempt, or None
    stage_handle: Any           # WP-B: this attempt's live StageHandle, or None
    stage_error: str | None     # WP-B: this attempt's stage boot failure reason, or None
    acceptance: Any             # the declared Acceptance contract this attempt ran, or None
    acceptance_report: Any      # the AcceptanceReport this attempt produced
    verdict: Any


@dataclass
class LoopResult:
    verdict: Verdict
    attempts: int
    history: list = field(default_factory=list)   # [(attempt, status), ...]
    workdir: str | None = None
    engine: str = "fallback"
    run_id: str | None = None
    # WP-B/D-S3: set only when --stage-hold kept the final attempt's server alive.
    # `.url` is what the CLI prints; the caller owns closing it when done.
    stage_handle: Any = None


def _is_empty_change(change) -> bool:
    """True when the executor produced no substantive change.

    Not just "no diff": an executor that errored or hit a dead model often *creates an
    empty file*, which has a `diff --git` header but no content — a no-op in substance. So
    the real signal is the absence of added/removed content (or a structural rename/delete/
    copy). `+++`/`---` file markers are skipped; any other `+`/`-` line is real content.
    """
    diff = getattr(change, "diff", "") or ""
    for line in diff.splitlines():
        s = line.rstrip()
        if s.startswith(("+++", "---")):
            continue
        if s.startswith(("+", "-")):
            return False                      # real content added or removed
        if s.startswith(("rename ", "deleted file", "copy ")):
            return False                      # structural change with no +/- body
    return True


def _execution_error(change) -> str | None:
    """A hard executor failure (timeout / crash / nonzero exit with nothing to show for
    it) recorded by the adapter, or None.

    The adapters convert a `TimeoutExpired` / internal crash into `report["error"]`
    instead of letting it abort the loop; this reads that signal back so the verify
    stage can BLOCK rather than the loop raising. A nonzero exit code paired with an
    empty diff is the same kind of hard failure (auth error, rate limit, crashed CLI)
    even when the adapter didn't set `error` explicitly — without this, `verify()` fell
    through to the generic "executor produced no changes" message and silently threw
    away the actual reason (e.g. a 401 from the coding agent's own CLI), which is
    exactly the kind of failure someone debugging "why didn't it change anything" needs
    to see (codex-adjacent finding from a real manual run, not a review).
    """
    report = getattr(change, "report", {}) or {}
    err = report.get("error")
    if err:
        return str(err)
    rc = report.get("exit_code")
    if isinstance(rc, int) and rc != 0 and _is_empty_change(change):
        detail = _first_line(report.get("output")) or _first_line(report.get("stderr"))
        return f"exit code {rc}" + (f" — {detail}" if detail else "")
    return None


def _first_line(text) -> str | None:
    """The first non-empty line of `text`, trimmed to a sane length, or None."""
    if not text or not isinstance(text, str):
        return None
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:300]
    return None


def _nonzero_exit(change) -> int | None:
    """The executor's non-zero process exit code, if any (else None).

    A non-zero exit means the agent process did not finish cleanly. The gate verifies the
    *change* (bounds + claim integrity), not process health — so a non-zero exit that still
    produced an in-scope diff would otherwise PASS silently. The loop surfaces it instead.
    """
    report = getattr(change, "report", {}) or {}
    rc = report.get("exit_code")
    return rc if isinstance(rc, int) and rc != 0 else None


def _usage_tokens(report: dict):
    """Total tokens an executor reported, if any (C1.3) — best-effort, never required.

    Accepts a few shapes: `usage.total_tokens`, `usage.tokens`, or a bare `tokens`. Returns
    None when the executor didn't surface usage (the common case for the OAuth/CLI agents).
    """
    usage = report.get("usage")
    if isinstance(usage, dict):
        return usage.get("total_tokens") or usage.get("tokens")
    return report.get("tokens")


# --- WP-A: sandbox.prepare (declared dependency install per attempt-clone) ----

_PREPARE_DEFAULT_TIMEOUT_S = 300
_PREPARE_MAX_TIMEOUT_S = 1800


def _run_sandbox_prepare(cfg: StackConfig, sandbox, run, attempt_n: int) -> tuple[bool, str | None]:
    """Run the declared `sandbox.prepare` command in the attempt's clone, before
    execute (the O12 limitation this spec absorbs: a fresh clone carries no
    installed deps). Absent key -> no-op, today's behavior byte-identical:
    `(True, None)`. A declared command that fails (nonzero exit, spawn failure, or
    timeout) -> `(False, <reason with stderr>)`, never a silent skip. Publishes
    `run.stage` events (via `run.append_event`, the same mechanism every other
    stage transition uses) for "prepare" start/done/failed. Tolerates a `cfg`
    with no `.raw` at all (some tests build a bare `SimpleNamespace`) — that's
    the same as declaring nothing."""
    decl = (getattr(cfg, "raw", None) or {}).get("sandbox", {}) or {}
    argv = _to_argv(decl.get("prepare"))
    if not argv:
        return True, None
    argv = _resolve_shim(argv)
    timeout_s = decl.get("timeout_s", _PREPARE_DEFAULT_TIMEOUT_S)
    if not isinstance(timeout_s, int) or isinstance(timeout_s, bool) or timeout_s <= 0:
        timeout_s = _PREPARE_DEFAULT_TIMEOUT_S
    timeout_s = min(timeout_s, _PREPARE_MAX_TIMEOUT_S)
    workdir = getattr(sandbox, "workdir", None) or "."

    run.append_event("prepare", "start", attempt=attempt_n)
    try:
        proc = subprocess.run(
            argv, cwd=workdir, capture_output=True, text=True, timeout=timeout_s,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        err = exc.stderr or ""
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        run.append_event("prepare", "failed", attempt=attempt_n)
        return False, f"sandbox prepare timed out after {timeout_s}s: {err.strip()[-2000:]}"
    except (OSError, ValueError) as exc:
        run.append_event("prepare", "failed", attempt=attempt_n)
        return False, f"sandbox prepare failed to start: {exc}"

    if proc.returncode != 0:
        run.append_event("prepare", "failed", attempt=attempt_n)
        detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        return False, f"sandbox prepare exited {proc.returncode}: {detail}"
    run.append_event("prepare", "done", attempt=attempt_n)
    return True, None


# --- WP-B/C: the web stage harness (preview-as-evidence) ----------------------

def _stage_decl(cfg: StackConfig) -> dict:
    """The declared `stage:` block (top-level in `sembl.stack.yaml`), or `{}` —
    absence means the layer is completely inert regardless of which `stage`
    adapter `layers.stage` names (mirrors `load_acceptance`'s None-means-no-op
    discipline, just inline in config instead of a sibling file)."""
    return (getattr(cfg, "raw", None) or {}).get("stage") or {}


def _route_filename(route: str) -> str:
    """A declared route (e.g. "/", "/about") -> a filesystem-safe `<name>.html`.
    "/" (the common case) becomes "root.html" so it never collides with an empty
    name; anything not alnum/./_/- is replaced so a route can't escape the
    attempt's snapshot directory."""
    r = (route or "").strip("/")
    if not r:
        return "root.html"
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in r)
    return f"{safe}.html"


def _write_stage_manifest(run, attempt: int, decl: dict, handle, snapshot: dict | None,
                          diff: str, *, ready_ok: bool, ready_detail: str | None,
                          boot_s: float, snapshot_s: float | None = None,
                          stderr: str | None = None) -> None:
    """`.sembl/runs/<id>/stage-<attempt>.json` (+ `stage-<attempt>/<route>.html`
    for every reachable route) — evidence bound to the SAME diff SHA `bind_verdict`
    uses. The attempt number is baked into every path, so attempts never collide.
    An unreachable route is recorded as an ERROR entry here, never a crash."""
    routes_out: dict = {}
    if snapshot:
        stage_dir = Path(run.dir) / f"stage-{attempt}"
        for route, res in snapshot.items():
            if res.get("status") == "OK":
                stage_dir.mkdir(parents=True, exist_ok=True)
                fname = _route_filename(route)
                (stage_dir / fname).write_text(res.get("html") or "", encoding="utf-8")
                routes_out[route] = {
                    "status": "OK", "file": f"stage-{attempt}/{fname}",
                    "http_status": res.get("http_status")}
            else:
                routes_out[route] = {"status": "ERROR", "detail": res.get("detail")}
    manifest = {
        "attempt": attempt,
        "serve": decl.get("serve"),
        "url": getattr(handle, "url", None),
        "port": getattr(handle, "port", None),
        "ready": {"ok": ready_ok, "detail": ready_detail, "boot_s": boot_s,
                  "stderr": stderr},
        "snapshot_s": snapshot_s,
        "diff_sha256": diff_sha256(diff or ""),
        "routes": routes_out,
    }
    path = Path(run.dir) / f"stage-{attempt}.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def _close_stage(handle, bus_root: Path, run_id: str, attempt: int) -> None:
    """Tear a stage handle's process tree down and mirror it on the bus (D5) as
    `stage.down`. Never raises — a close failure can't be allowed to affect the
    loop (mirrors every other adapter-teardown call in this module)."""
    url = getattr(handle, "url", None)
    try:
        handle.close()
    except Exception:
        pass
    publish(bus_root, {
        "kind": "stage.down", "run_id": run_id,
        "summary": f"stage down: {url}" if url else "stage down",
        "data": {"attempt": attempt, "url": url}})


def _maybe_expand(cfg: StackConfig, task: Task, bounds, tracer, run=None) -> None:
    """L1 context stage (in-loop): widen `bounds.editable_paths` along the coupling closure.

    Opt-in via `loop.expand_bounds`. This makes the running loop the fuller pipeline
    (L1→L2→L3→L4→L5) instead of only the `bounds --expand` CLI. It is a no-op — and so leaves
    the gate exactly as strict — when no context adapter is configured/available or the seed
    has no indexed files. Mutates `bounds` in place (one hop, closure-capped; EXP-05).

    `run`, when given, gets "context" start/done events (live-run stage lighting) — emitted
    only when the stage actually does something, never fabricated for a no-op skip.
    """
    if not (cfg.raw.get("loop", {}) or {}).get("expand_bounds"):
        return
    g = cfg.context
    if g is None or not getattr(g, "available", lambda: False)():
        return
    from .contextgraph import expand_bounds as _eb

    opts = (cfg.raw.get("options", {}) or {}).get("context", {}) or {}
    if run is not None:
        run.append_event("context", "start")
    with tracer.span("L1.context"):
        g.index(task.repo)
        fg = g.file_graph(task.repo)
    bounds.editable_paths = _eb(
        list(bounds.editable_paths), fg, hops=opts.get("hops", 1),
        min_strength=opts.get("min_strength", 0), max_fraction=opts.get("max_fraction", 0.4))
    if run is not None:
        run.append_event("context", "done")


# --- L4 isolation guard (defense-in-depth) -----------------------------------
#
# The sandbox (L4) clones the repo so the executor (L3) edits ONLY a disposable copy; the
# gate verifies that copy's diff. But a swapped-in executor can ignore the cage and edit the
# SOURCE tree instead (this happened live 2026-06-20: `opencode` ignored the inherited cwd
# and wrote into the source repo until `--dir <sandbox.workdir>` was passed, commit 4a76163).
# That leak was caught only by eye. These helpers assert — cheaply, once before and once
# after the run — that the source working tree is left untouched, so a future regression
# fails LOUD (forced BLOCK) instead of slipping through.

_STORE_PREFIX = ".sembl/"          # the run store writes here BY DESIGN; never a breach


def _source_tree_status(repo: str) -> set[str] | None:
    """Snapshot the source repo's dirty working tree, EXCLUDING the `.sembl/` run store.

    Returns the set of `git status --porcelain` lines for paths outside `.sembl/` (which
    `store.py` writes into the source repo on every run, by design). Returns None — so the
    caller skips the guard gracefully — when `repo` is not a git repo or git is unavailable.
    """
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, timeout=30,
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None                                  # git missing/wedged/bad path: can't guard
    if proc.returncode != 0:
        return None                                  # not a git repo: nothing to guard
    lines: set[str] = set()
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()                      # porcelain: "XY <path>"
        if " -> " in path:                           # a rename: "old -> new"
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if path == _STORE_PREFIX.rstrip("/") or path.startswith(_STORE_PREFIX):
            continue                                 # run-store writes are expected
        lines.add(line)
    return lines


def _isolation_breach(before: set[str] | None, after: set[str] | None) -> str | None:
    """A human reason if the source tree changed during the run (the cage leaked), else None.

    `before`/`after` are `_source_tree_status` snapshots (or None when unguardable). Any
    difference outside `.sembl/` means the executor wrote into the SOURCE repo instead of the
    disposable clone.
    """
    if before is None or after is None or before == after:
        return None
    paths = sorted({line[3:].strip().split(" -> ")[-1].strip().strip('"')
                    for line in (before ^ after)})
    shown = ", ".join(paths[:5]) + (" …" if len(paths) > 5 else "")
    return ("sandbox isolation breach: the executor modified the source repo "
            f"(unexpected working-tree changes outside {_STORE_PREFIX}: {shown})")


def _acceptance_contract(cfg: StackConfig, task: Task):
    """The `Acceptance` contract declared for this run, or `None` (O12).

    The loop attaches nothing itself — a contract is filesystem-declared the same way
    `Bounds`' hand-written `bounds.json` fallback works (`config.load_acceptance`
    reads `<repo>/acceptance.json` / `.sembl/acceptance.json`). `None` means no
    behavioral surface was declared for this repo; the axis stays a strict no-op.
    """
    return load_acceptance(getattr(task, "repo", "."))


def _acceptance_node(cfg: StackConfig, task: Task, tracer, run):
    """Build the L4.5 acceptance node (§4.3): runs declared checks in the L4 sandbox,
    between execute and verify. A no-op — an empty `AcceptanceReport` plus a single
    "skip" event, never a fabricated "start"/"done" — when no `Acceptance` is
    declared/attached OR the configured runner is `none` (`cfg.acceptance is None`).
    """
    def acceptance(state: dict) -> dict:
        attempt_n = state["attempt"] + 1
        if state.get("prepare_error") is not None:
            # WP-A sibling of the stage node's skip: dependencies never installed, so
            # running declared checks would only burn their timeouts and record
            # misleading ERRORs — verify() already blocks on the prepare failure.
            run.append_event("acceptance", "skip", attempt=attempt_n)
            return {"acceptance": None, "acceptance_report": AcceptanceReport()}
        runner = getattr(cfg, "acceptance", None)
        contract = _acceptance_contract(cfg, task)
        # `invalid_ids` counts as a declared surface: a contract we could not read/coerce
        # must reach the gate (where its checks will be "declared, no result" => BLOCK),
        # never fall into the silent no-op path.
        if runner is None or contract is None or not (contract.checks or contract.invalid_ids):
            run.append_event("acceptance", "skip", attempt=attempt_n)
            return {"acceptance": None, "acceptance_report": AcceptanceReport()}

        run.append_event("acceptance", "start", attempt=attempt_n)
        sandbox = state["sandbox"]
        # SPEC-stage: the stage boots BEFORE acceptance precisely so checks can use
        # the already-running app. `SEMBL_STAGE_URL` is the discovery contract —
        # exported only while checks run, only when a stage is actually up. Without
        # it, a web check that boots its own dev server collides with the stage's
        # (Next 16 holds a per-directory single-instance lock — found live 2026-07-12).
        stage_handle = state.get("stage_handle")
        stage_url = getattr(stage_handle, "url", None) if stage_handle is not None else None
        had_env = os.environ.get("SEMBL_STAGE_URL")
        if stage_url:
            os.environ["SEMBL_STAGE_URL"] = stage_url
        with tracer.span("L4.5.acceptance", attempt=attempt_n):
            try:
                report = runner.run(contract, sandbox, task, state.get("bounds"))
            except Exception as exc:
                # Defense-in-depth mirror of the never-reject contract the runner itself
                # must already honor (§4.2): even if a swapped-in runner crashes past its
                # own guard, the loop must not abort — every declared check becomes an
                # ERROR result instead of a raised exception reaching the graph.
                report = AcceptanceReport(
                    results=[
                        {"id": c.get("id", "*"), "outcome": "ERROR", "seed": c.get("seed"),
                         "duration_s": 0.0, "evidence": "",
                         "detail": f"acceptance runner crashed: {exc!r}"}
                        for c in contract.checks
                    ],
                    runner="crashed")
            finally:
                # restore, never leak: the var must not outlive this attempt's checks
                if stage_url:
                    if had_env is None:
                        os.environ.pop("SEMBL_STAGE_URL", None)
                    else:
                        os.environ["SEMBL_STAGE_URL"] = had_env
        run.put(report, name=f"acceptance-{attempt_n}")
        run.append_event("acceptance", "done", attempt=attempt_n)
        return {"acceptance": contract, "acceptance_report": report}

    return acceptance


def _stage_node(cfg: StackConfig, task: Task, tracer, run, holder: dict | None = None):
    """Build the L4.5 stage node (SPEC-stage-preview-as-evidence WP-B/C): opens the
    declared web stage against the attempt's sandbox (after execute, before
    acceptance — so a declared acceptance check also sees a running app),
    snapshots its declared routes, and writes the evidence manifest. A no-op — a
    single "skip" event, never a fabricated "start"/"done" — when no `stage`
    adapter is wired OR no `stage:` block is declared (mirrors the acceptance
    node's no-op discipline), or when this attempt already failed at
    `sandbox.prepare` (WP-A): there is nothing meaningful to boot.

    Boot failure is fail-closed (mirrors the acceptance runners' discipline):
    `stage_error` is returned instead of a `StageHandle`, and the manifest is
    still written recording the boot attempt, its stderr, and the diff SHA — the
    caller (`verify()`) is what turns `stage_error` into an attempt-level BLOCK.
    """
    bus_root = Path(task.repo).resolve()

    def stage(state: dict) -> dict:
        n = state["attempt"] + 1
        adapter = getattr(cfg, "stage", None)
        decl = _stage_decl(cfg)
        if state.get("prepare_error") is not None:
            run.append_event("stage", "skip", attempt=n)
            return {"stage_handle": None, "stage_error": None}
        if adapter is None or not decl.get("serve"):
            run.append_event("stage", "skip", attempt=n)
            return {"stage_handle": None, "stage_error": None}

        sandbox = state["sandbox"]
        run.append_event("stage", "start", attempt=n)
        t0 = time.perf_counter()
        try:
            with tracer.span("L4.5.stage", attempt=n):
                handle = adapter.open(sandbox, decl)
        except StageBootError as exc:
            boot_s = round(time.perf_counter() - t0, 3)
            run.append_event("stage", "failed", attempt=n)
            _write_stage_manifest(
                run, n, decl, None, None, getattr(state["result"], "diff", ""),
                ready_ok=False, ready_detail=str(exc), boot_s=boot_s, stderr=exc.stderr)
            return {"stage_handle": None, "stage_error": str(exc)}
        except Exception as exc:
            # Never-reject mirror of the acceptance runner's own guard: a swapped-in
            # stage adapter crashing past its own contract must not abort the loop.
            boot_s = round(time.perf_counter() - t0, 3)
            run.append_event("stage", "failed", attempt=n)
            detail = f"stage adapter crashed: {exc!r}"
            _write_stage_manifest(
                run, n, decl, None, None, getattr(state["result"], "diff", ""),
                ready_ok=False, ready_detail=detail, boot_s=boot_s)
            return {"stage_handle": None, "stage_error": detail}

        boot_s = round(time.perf_counter() - t0, 3)
        if holder is not None:
            holder["stage"] = handle
            holder["stage_attempt"] = n
        publish(bus_root, {
            "kind": "stage.up", "run_id": run.id,
            "summary": f"stage up: {handle.url}",
            "data": {"attempt": n, "url": handle.url}})
        run.append_event("stage", "done", attempt=n)

        routes = decl.get("routes") or ["/"]
        t1 = time.perf_counter()
        snap = handle.snapshot(routes)
        snapshot_s = round(time.perf_counter() - t1, 3)
        _write_stage_manifest(
            run, n, decl, handle, snap, getattr(state["result"], "diff", ""),
            ready_ok=True, ready_detail=None, boot_s=boot_s, snapshot_s=snapshot_s)
        return {"stage_handle": handle, "stage_error": None}

    return stage


def _nodes(cfg: StackConfig, task: Task, tracer, run, holder: dict | None = None):
    bus_root = Path(task.repo).resolve()

    def plan(state: dict) -> dict:
        run.append_event("spec", "start")
        with tracer.span("L2.plan"):
            try:
                bounds = cfg.spec.plan(task)
            except Exception:
                run.append_event("spec", "failed")
                raise
        run.append_event("spec", "done")
        run.put(build_spec_graph(task, bounds))
        _maybe_expand(cfg, task, bounds, tracer, run)  # L1: widen along the context graph
        run.put(bounds)                            # persist Bounds artifact (post-expansion)
        return {"bounds": bounds}

    def execute(state: dict) -> dict:
        n = state["attempt"] + 1
        prev = state.get("sandbox")
        prev_stage = state.get("stage_handle")
        if prev_stage is not None:
            # D-S3 default: an attempt's stage server comes down once the attempt
            # ends — here, the moment a retry needs a fresh sandbox. `--stage-hold`
            # (handled in `run()`) only keeps the FINAL attempt's server alive.
            _close_stage(prev_stage, bus_root, run.id, state.get("attempt", 0))
            if holder is not None:
                holder["stage"] = None
        if prev is not None:
            prev.close()                           # fresh cage per attempt
        run.append_event("sandbox", "start", attempt=n)
        sandbox = cfg.sandbox.open(task.repo)
        run.append_event("sandbox", "done", attempt=n)
        if holder is not None:
            holder["sandbox"] = sandbox            # so run() can close it on a crash

        prep_ok, prep_err = _run_sandbox_prepare(cfg, sandbox, run, n)
        if not prep_ok:
            # WP-A: an honest run failure carrying the command's stderr, never a
            # silent skip — the executor never runs against a sandbox whose
            # declared dependencies didn't install.
            result = Change(diff="", workdir=getattr(sandbox, "workdir", ""),
                            report={"prepare_error": prep_err, "exit_code": -1})
            run.put(result, name=f"change-{n}")
            run.record_attempt(n, latency_s=0.0)
            return {"sandbox": sandbox, "result": result, "prepare_error": prep_err,
                    "stage_handle": None, "stage_error": None}

        t0 = time.perf_counter()
        run.append_event("execute", "start", attempt=n)
        exec_failed = False
        with tracer.span("L3.execute", attempt=n):
            try:
                result = cfg.execute.run(task, state["bounds"], sandbox,
                                         state.get("feedback"))
            except Exception as exc:
                # An executor that crashes (or whose subprocess raises past the adapter's
                # own timeout handling) must NOT abort the loop, leak the sandbox, or skip
                # the persisted verdict. Convert the failure into a recorded Change so the
                # verify stage turns it into a BLOCK and the run still completes cleanly.
                diff = ""
                try:
                    diff = sandbox.diff()
                except Exception:
                    pass
                result = Change(
                    diff=diff, workdir=getattr(sandbox, "workdir", ""),
                    report={"error": "executor-crashed", "exit_code": -1,
                            "detail": repr(exc)})
                exec_failed = True
        run.append_event("execute", "failed" if exec_failed else "done", attempt=n)
        latency_s = round(time.perf_counter() - t0, 3)

        # C1.3: record cost+latency per attempt. Latency is always measured here (wall
        # clock around the executor); tokens/cost ride along only when the adapter reported
        # usage. Stamp latency onto the Change report too so a single artifact is enough.
        report = dict(getattr(result, "report", {}) or {})
        report.setdefault("latency_s", latency_s)
        result.report = report
        run.put(result, name=f"change-{n}")        # persist Change per attempt
        run.record_attempt(
            n, latency_s=latency_s, agent=report.get("agent"), model=report.get("model"),
            exit_code=report.get("exit_code"), tokens=_usage_tokens(report),
            cost=report.get("cost"))
        return {"sandbox": sandbox, "result": result, "prepare_error": None}

    def verify(state: dict) -> dict:
        attempt_n = state["attempt"] + 1
        run.append_event("verify", "start", attempt=attempt_n)
        change = state["result"]
        prep_err = state.get("prepare_error")
        stage_err = state.get("stage_error")
        exec_err = _execution_error(change)
        if prep_err is not None:
            # WP-A: dependencies never installed, so nothing downstream (executor,
            # stage, acceptance) is trustworthy either — block directly, same
            # fail-closed discipline as the executor/empty-diff hardening below.
            verdict = Verdict(
                status="BLOCK",
                reasons=[f"sandbox prepare failed ({prep_err}) — dependencies could not be "
                         "installed; the task was not implemented"],
                raw={"prepare_error": prep_err, "report": getattr(change, "report", {})})
        elif exec_err is not None:
            # C1 hardening: a hard executor failure (timeout / crash) is not a verdict the
            # gate can issue — the gate checks a *change*, not process health. Block directly
            # so a timed-out or crashed run never sails through as PASS, and hand the executor
            # actionable feedback on retry. (No gate call: there's nothing trustworthy to
            # verify.)
            verdict = Verdict(
                status="BLOCK",
                reasons=[f"executor failed ({exec_err}) — the task was not implemented; "
                         "check the executor/model output"],
                raw={"execution_error": exec_err, "report": getattr(change, "report", {})})
        elif _is_empty_change(change):
            # C1 hardening: a no-op execution (empty diff — e.g. the executor errored, hit a
            # dead model, or wrote nothing) must NOT pass. The gate verifies a *change*; with
            # no change there is nothing that satisfies the task, so block and tell the
            # executor it produced nothing (actionable feedback on retry).
            verdict = Verdict(
                status="BLOCK",
                reasons=["executor produced no changes (empty diff) — the task was not "
                         "implemented; check the executor/model output"],
                raw={"empty_diff": True, "report": getattr(change, "report", {})})
        elif stage_err is not None:
            # WP-B: the stage failed to boot in the sandbox — fail-closed, mirroring the
            # acceptance runners' discipline (a declared-but-unusable surface blocks rather
            # than being silently ignored). The diff itself may be fine; what's missing is
            # the ability to observe it running.
            verdict = Verdict(
                status="BLOCK",
                reasons=[f"stage failed to boot ({stage_err}) — the app under change could "
                         "not be observed; check the stage server output"],
                raw={"stage_error": stage_err, "report": getattr(change, "report", {})})
        else:
            # O12: forward the acceptance fold input ONLY when a contract actually ran this
            # attempt (never on the no-op-skip path) — this is what keeps a `verify` adapter
            # that doesn't know the `acceptance` kwarg (an older/pinned gate, a stub in an
            # existing test) working exactly as before when no behavioral axis is declared.
            acceptance_kwargs = {}
            contract = state.get("acceptance")
            if contract is not None:
                report = state.get("acceptance_report")
                acceptance_kwargs["acceptance"] = {
                    "declared": contract.to_contract()["checks"],
                    "results": list(getattr(report, "results", []) or []),
                }
            with tracer.span("L5.verify"):
                verdict = cfg.verify.verify(state["bounds"], change, cfg.strict,
                                            **acceptance_kwargs)
            rc = _nonzero_exit(change)
            if rc is not None and verdict.status == "PASS":
                # The change passed the gate but the executor process exited non-zero — it
                # did not complete cleanly. Don't report an unqualified PASS: downgrade to
                # WARN and record why, so a half-finished run is never mistaken for success.
                verdict = Verdict(
                    status="WARN",
                    reasons=list(verdict.reasons)
                    + [f"executor exited non-zero (exit_code={rc}); the change was applied "
                       "but the run did not complete cleanly"],
                    raw={**(getattr(verdict, "raw", {}) or {}), "exit_code": rc})
        # Bind the verdict to the exact diff it judged (also for BLOCKs — harmless),
        # so merge/apply can later refuse a verdict issued for a different change.
        bind_verdict(verdict, getattr(change, "diff", "") or "")
        attempt = attempt_n
        run.append_event("verify", "done", attempt=attempt)
        run.put(verdict, name=f"verdict-{attempt}")
        return {
            "verdict": verdict,
            "attempt": attempt,
            "feedback": verdict.feedback(),
            "history": state.get("history", []) + [(attempt, verdict.status)],
        }

    def route(state: dict) -> str:
        if state["verdict"].status in ("PASS", "WARN"):
            return "done"
        return "retry" if state["attempt"] < cfg.max_attempts else "done"

    return plan, execute, verify, route


def run(cfg: StackConfig, task: Task, *, stage_hold: bool = False) -> LoopResult:
    """`stage_hold` is D-S3's `--stage-hold`: normally every attempt's stage server
    comes down when its attempt ends (retry or run completion); with `stage_hold`
    the FINAL attempt's server is left running and its handle comes back on
    `LoopResult.stage_handle` (`.url` is what a caller prints) instead of being
    closed here — the caller now owns closing it."""
    tracer = get_tracer(cfg.langfuse)
    run_rec = RunStore(task.repo).new_run(task)
    bus_root = Path(task.repo).resolve()
    publish(bus_root, {
        "kind": "run.started", "run_id": run_rec.id,
        "summary": f"run started: {task.text[:80]}",
        "data": {"task": task.text}})
    # L4 isolation guard: snapshot the source tree BEFORE any sandbox/executor runs.
    tree_before = _source_tree_status(task.repo)
    holder: dict = {"sandbox": None, "stage": None}
    plan, execute, verify, route = _nodes(cfg, task, tracer, run_rec, holder)
    stage = _stage_node(cfg, task, tracer, run_rec, holder)      # L4.5, between execute/acceptance
    acceptance = _acceptance_node(cfg, task, tracer, run_rec)    # L4.5, between stage/verify
    init = {"attempt": 0, "feedback": None, "history": []}

    try:
        try:
            final, engine = _run_langgraph(plan, execute, stage, acceptance, verify, route, init)
        except ImportError:
            final, engine = (_run_fallback(plan, execute, stage, acceptance, verify, route, init),
                             "fallback")
    except Exception as exc:
        # A crash in plan/verify (executor crashes are already converted in-node) must not
        # leave the run stuck at "started" with an open sandbox on disk. Close the cage,
        # record the failure, then re-raise so the caller still sees the real error.
        sb = holder.get("sandbox")
        if sb is not None:
            try:
                sb.close()
            except Exception:
                pass
        st = holder.get("stage")
        if st is not None:
            _close_stage(st, bus_root, run_rec.id, holder.get("stage_attempt", 0))
        run_rec.set_status("failed", error=repr(exc)[:500])
        tracer.flush()
        raise

    sandbox = final.get("sandbox")
    workdir = getattr(sandbox, "workdir", None) if sandbox else None
    if sandbox is not None:
        sandbox.close()
    tracer.flush()

    # L4 isolation guard: re-snapshot the source tree now that the run is over. If it
    # changed (outside .sembl/), the executor escaped the sandbox and edited the SOURCE repo
    # — a containment breach the gate can't see. Fail LOUD: force the final verdict to BLOCK
    # so the breach is never mistaken for a clean PASS/WARN.
    verdict = final["verdict"]
    breach = _isolation_breach(tree_before, _source_tree_status(task.repo))
    if breach is not None:
        verdict = Verdict(
            status="BLOCK",
            reasons=[breach, *getattr(verdict, "reasons", [])],
            raw={**(getattr(verdict, "raw", {}) or {}), "isolation_breach": True})

    # Persist the final accepted change under a stable name, then the final verdict, a
    # trace, and the run status. Per-attempt artifacts remain as change-1/verdict-1...
    run_rec.put(final["result"], name="change")
    run_rec.put(verdict)
    # Bus: publish the BOUND verdict (never recomputed) — same object just persisted above.
    n_reasons = len(verdict.reasons)
    publish(bus_root, {
        "kind": "run.verdict", "run_id": run_rec.id,
        "summary": f"gate verdict: {verdict.status}"
                   + (f" ({n_reasons} reason{'s' if n_reasons != 1 else ''})" if n_reasons else ""),
        "data": {"status": verdict.status, "reasons": list(verdict.reasons)}})
    run_rec.put(Trace(steps=[{"attempt": a, "status": s} for a, s in final["history"]]))
    log = run_rec.manifest().get("attempts_log", [])             # C1.3 per-attempt metrics
    total_latency_s = round(sum(e.get("latency_s", 0) for e in log), 3)
    run_rec.set_status(verdict.status,
                       attempts=final["attempt"], engine=engine,
                       total_latency_s=total_latency_s)
    publish(bus_root, {
        "kind": "run.finished", "run_id": run_rec.id,
        "summary": f"run finished: {verdict.status}",
        "data": {"status": verdict.status}})

    # D-S3: the final attempt's stage comes down like every other attempt's did,
    # UNLESS `--stage-hold` asked to keep it up — then the handle rides back on the
    # result instead (the caller prints `.url` and owns closing it later).
    stage_handle = final.get("stage_handle")
    held_handle = None
    if stage_handle is not None:
        if stage_hold:
            held_handle = stage_handle
        else:
            _close_stage(stage_handle, bus_root, run_rec.id, final.get("attempt", 0))

    return LoopResult(
        verdict=verdict, attempts=final["attempt"],
        history=final["history"], workdir=workdir, engine=engine,
        run_id=run_rec.id, stage_handle=held_handle,
    )


def _run_langgraph(plan, execute, stage, acceptance, verify, route, init):
    from langgraph.graph import StateGraph, END   # raises ImportError if absent

    g = StateGraph(LoopState)
    g.add_node("plan", plan)
    g.add_node("execute", execute)
    g.add_node("stage", stage)
    g.add_node("acceptance", acceptance)
    g.add_node("verify", verify)
    g.set_entry_point("plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "stage")
    g.add_edge("stage", "acceptance")
    g.add_edge("acceptance", "verify")
    g.add_conditional_edges("verify", route, {"retry": "execute", "done": END})
    app = g.compile()
    return app.invoke(init, {"recursion_limit": 50}), "langgraph"


def _run_fallback(plan, execute, stage, acceptance, verify, route, init):
    state = dict(init)
    state.update(plan(state))
    while True:
        state.update(execute(state))
        state.update(stage(state))
        state.update(acceptance(state))
        state.update(verify(state))
        if route(state) == "done":
            return state
