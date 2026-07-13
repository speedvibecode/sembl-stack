"""The dashboard's local backend — FastAPI + one WebSocket for live run streaming.

Zero business logic lives here. Every endpoint is a thin wrapper around the exact
same pure/deterministic functions `guide.py`'s inline CLI already calls
(profile.py, runner.py, onboarding.py, the gate) — a dashboard run and a headless
`sembl-stack loop` run are byte-identical in behavior and artifacts, same as the
CLI's own guarantee. This module only renders/streams and never re-implements a
decision the cores already make.

Single repo per process, single run at a time — this is a personal cockpit, not a
multi-tenant service; `init_app(repo)` binds the process to one directory for its
whole life, same as `sembl-stack gui` launched inside a project.
"""
from __future__ import annotations

import argparse
import asyncio
import atexit
import dataclasses
import json
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import guide, onboarding, profile as profile_mod, runner
from ..bus import read_since
from ..config import load_acceptance
from ..store import RunStore

STATIC_DIR = Path(__file__).parent / "static"


# Request bodies MUST be module-level: with `from __future__ import annotations`,
# FastAPI resolves each field's string annotation back to a real type via the
# model's module globals — a class nested inside `create_app()` has no such
# module-level entry, so resolution silently fails and FastAPI falls back to
# treating the whole body as a required *query* parameter (a real bug hit while
# verifying this in the browser: every POST endpoint 422'd with "body: field
# required" in `query`, not `body`).
class AgentChoice(BaseModel):
    runner: str
    key_env: str | None = None
    model: str | None = None
    strict: bool = True


class TaskBody(BaseModel):
    text: str
    editable: list[str]
    forbidden: list[str] = []


class SuggestBody(BaseModel):
    text: str
    kind: str = "editable"
    editable: list[str] = []


class ShipBody(BaseModel):
    run_id: str
    allow_warn: bool = False
    commit: bool = False


class _State:
    """Everything mutable, in one place — the repo this process is bound to, and
    whether a run is currently in flight (only one at a time: a second WS connect
    while a run is live gets a clear error instead of silently starting a second
    concurrent run against the same sandboxed clone).

    `held_stage_handle` is D7: the live preview server kept alive by a
    `?stage_hold=1` run. At most one is ever alive at a time — a new run closes
    whatever the previous one left open before it starts."""
    root: Path
    run_lock: threading.Lock
    held_stage_handle: object | None

    def __init__(self, repo: str):
        self.root = Path(repo).resolve()
        self.run_lock = threading.Lock()
        self.held_stage_handle = None

    def close_held_stage(self) -> None:
        """Never raises — a teardown failure can't be allowed to break the next run
        or process exit (mirrors every other adapter-teardown call in this codebase).
        Closes the handle's `owned_sandbox` too: with `stage_hold` the loop leaves
        the final sandbox alive for the held server and transfers ownership here."""
        if self.held_stage_handle is not None:
            try:
                self.held_stage_handle.close()
            except Exception:
                pass
            sandbox = getattr(self.held_stage_handle, "owned_sandbox", None)
            if sandbox is not None:
                try:
                    sandbox.close()
                except Exception:
                    pass
            self.held_stage_handle = None


def _safe_get(run, name: str):
    """`run.get(name)`, but a missing OR malformed artifact degrades to `None`
    instead of raising — a crashed/corrupt run directory must never 500 an
    endpoint (a crashed run may have only `run.json`)."""
    try:
        return run.get(name)
    except Exception:
        return None


def _last_change_meta(run, man: dict) -> tuple[str | None, str | None]:
    """Best-effort `(executor, model)` from the LAST attempt's `change-N.json`
    report, else `(None, None)` — never raises."""
    n = len(man.get("attempts_log") or [])
    if n < 1:
        return None, None
    change = _safe_get(run, f"change-{n}")
    if change is None:
        return None, None
    report = getattr(change, "report", None) or {}
    return report.get("agent"), report.get("model")


def _acceptance_results(acc_report) -> list[dict] | None:
    """An `AcceptanceReport` artifact -> `[{id, outcome, duration_s, detail}, ...]`,
    or `None` when no report exists for this attempt."""
    if acc_report is None:
        return None
    results = getattr(acc_report, "results", None) or []
    return [{"id": r.get("id"), "outcome": r.get("outcome"),
             "duration_s": r.get("duration_s"), "detail": r.get("detail")}
            for r in results if isinstance(r, dict)]


def _read_stage_manifest(run, attempt: int) -> dict | None:
    """`stage-{attempt}.json` (a plain JSON file, not an `_Serializable` artifact) ->
    `{ok, url, port, diff_sha256, routes}`, or `None` if absent/unreadable."""
    path = run.dir / f"stage-{attempt}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    ready = data.get("ready") or {}
    return {
        "ok": ready.get("ok"),
        "url": data.get("url"),
        "port": data.get("port"),
        "diff_sha256": data.get("diff_sha256"),
        "routes": data.get("routes") or {},
    }


def _acceptance_descriptions(root: Path) -> dict:
    """`{check_id: description}` from the bound repo's declared `acceptance.json`
    (best-effort — `{}` when absent/unparseable, NEVER an exception)."""
    try:
        acc = load_acceptance(str(root))
    except Exception:
        return {}
    if acc is None:
        return {}
    return {c.get("id"): c.get("description", "")
            for c in acc.checks if isinstance(c, dict) and c.get("id")}


def create_app(repo: str = ".") -> FastAPI:
    state = _State(repo)
    atexit.register(state.close_held_stage)
    app = FastAPI(title="sembl-stack")

    # ------------------------------------------------------------------ status

    @app.get("/api/status")
    def status():
        root = state.root
        is_git = (root / ".git").exists()
        prof = profile_mod.load()
        text, editable, forbidden = guide.existing_answers(root)
        return {
            "repo": str(root),
            "is_git": is_git,
            "profile": dataclasses.asdict(prof) if prof is not None else None,
            "providers": [dataclasses.asdict(p) for p in guide.detect_providers()],
            "layers": guide.existing_layers_config(root),
            "task": {"text": text, "editable": editable, "forbidden": forbidden},
        }

    # ------------------------------------------------------------------- agent

    @app.post("/api/agent")
    def set_agent(body: AgentChoice):
        try:
            candidate = onboarding.profile_for_runner(
                body.runner, key_env=body.key_env, model=body.model, strict=body.strict)
        except ValueError as exc:
            return {"ok": False, "hint": str(exc)}
        ok, hint = onboarding.first_fix_hint(candidate)
        if not ok:
            return {"ok": False, "hint": hint}
        profile_mod.save(candidate)
        return {"ok": True, "profile": dataclasses.asdict(candidate)}

    # -------------------------------------------------------------------- task

    @app.post("/api/task")
    def set_task(body: TaskBody):
        warning = guide.path_typo_hint(state.root, body.editable + body.forbidden)
        try:
            guide.write_task_and_bounds(state.root, body.text, body.editable, body.forbidden)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "warning": warning}

    @app.post("/api/suggest-paths")
    def suggest_paths(body: SuggestBody):
        prof = profile_mod.load()
        if prof is None:
            return {"paths": None, "reason": "no agent configured yet"}
        paths = guide.ai_suggest_paths(
            state.root, prof.executor, body.text, model=prof.model,
            kind=body.kind, editable=body.editable or None)
        return {"paths": paths}

    # -------------------------------------------------------------------- runs

    @app.get("/api/runs")
    def list_runs():
        store = RunStore(str(state.root))
        out = []
        for run_id in store.list_runs():
            run = store.open(run_id)
            man = run.manifest()
            verdict = _safe_get(run, "verdict")
            executor, model = _last_change_meta(run, man)
            out.append({
                "id": run_id,
                "status": man.get("status"),
                "task": (man.get("task") or {}).get("text", ""),
                "attempts": len(man.get("attempts_log", [])),
                "verdict": verdict.status if verdict is not None else None,
                "created": man.get("created"),
                "executor": executor,
                "model": model,
                "error": man.get("error"),
            })
        out.sort(key=lambda r: r["created"] or 0, reverse=True)
        return out

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        store = RunStore(str(state.root))
        try:
            run = store.open(run_id)
        except ValueError as exc:
            return {"error": str(exc)}
        man = run.manifest()
        verdict = _safe_get(run, "verdict")
        bounds_artifact = _safe_get(run, "bounds")
        bounds = ({"editable_paths": bounds_artifact.editable_paths,
                   "forbidden_areas": bounds_artifact.forbidden_areas}
                  if bounds_artifact is not None else None)
        attempts = []
        for n in range(1, len(man.get("attempts_log", [])) + 1):
            change = _safe_get(run, f"change-{n}")
            v = _safe_get(run, f"verdict-{n}")
            acc_report = _safe_get(run, f"acceptance-{n}")
            report = (getattr(change, "report", None) or {}) if change else {}
            attempts.append({
                "attempt": n,
                "diff": getattr(change, "diff", "") if change else "",
                "files": guide._changed_files_from_diff(getattr(change, "diff", "") or "")
                        if change else [],
                "status": v.status if v is not None else None,
                "reasons": v.reasons if v is not None else [],
                "acceptance": _acceptance_results(acc_report),
                "stage": _read_stage_manifest(run, n),
                "cost_usd": report.get("cost"),
                "model": report.get("model"),
            })
        return {
            "id": run_id,
            "status": man.get("status"),
            "task": man.get("task", {}),
            "verdict": {"status": verdict.status, "reasons": verdict.reasons}
                       if verdict is not None else None,
            "attempts": attempts,
            "created": man.get("created"),
            "error": man.get("error"),
            "bounds": bounds,
            "acceptance_descriptions": _acceptance_descriptions(state.root),
        }

    @app.get("/api/runs/{run_id}/stage/{attempt}")
    def stage_snapshot(run_id: str, attempt: int):
        store = RunStore(str(state.root))
        try:
            run = store.open(run_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        manifest_path = run.dir / f"stage-{attempt}.json"
        if not manifest_path.is_file():
            return JSONResponse(
                {"error": "no stage evidence for this attempt"}, status_code=404)
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return JSONResponse(
                {"error": "stage manifest is unreadable"}, status_code=404)
        routes = data.get("routes") or {}
        if not routes:
            return JSONResponse(
                {"error": "no routes recorded for this attempt"}, status_code=404)
        first = next(iter(routes.values()))
        rel = first.get("file") if isinstance(first, dict) else None
        if not rel:
            return JSONResponse(
                {"error": "no snapshot file recorded for this attempt"}, status_code=404)
        run_dir = run.dir.resolve()
        candidate = (run.dir / rel).resolve()
        try:
            candidate.relative_to(run_dir)
        except ValueError:
            # A `file` path that escapes the run directory (e.g. "../../secret.html")
            # is never served — treated the same as "not found", not a 403, so a
            # crafted path can't be used to probe what exists on disk.
            return JSONResponse(
                {"error": "snapshot path escapes the run directory"}, status_code=404)
        if not candidate.is_file():
            return JSONResponse(
                {"error": "snapshot file is missing"}, status_code=404)
        return HTMLResponse(candidate.read_text(encoding="utf-8"))

    @app.get("/api/events")
    def events(cursor: int = 0):
        evs, new_cursor = read_since(state.root, cursor)
        return {"events": evs, "cursor": new_cursor}

    # --------------------------------------------------------------- run (WS)

    @app.websocket("/ws/run")
    async def ws_run(websocket: WebSocket):
        await websocket.accept()
        if not state.run_lock.acquire(blocking=False):
            await websocket.send_json({
                "type": "error", "message": "a run is already in progress"})
            await websocket.close()
            return

        # D7: `?stage_hold=1` keeps the final attempt's stage server alive after the
        # loop finishes; whatever the PREVIOUS run left held is torn down before
        # this one starts — at most one live preview process at a time.
        stage_hold = websocket.query_params.get("stage_hold") == "1"
        state.close_held_stage()

        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(ev) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "stage", "stage": ev.stage, "state": ev.state,
                "detail": ev.detail, "diff": ev.diff,
            })

        def worker() -> None:
            try:
                task = runner.load_task(str(state.root))
                if task is None:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "error", "message": "could not load task.yaml — "
                                                     "set a task first"})
                    return
                cfg = runner.resolve_config(str(state.root))
                result = runner.run_stages(cfg, task, emit, stage_hold=stage_hold)
                state.held_stage_handle = result.stage_handle
                stage_url = (getattr(result.stage_handle, "url", None)
                            if result.stage_handle is not None else None)
                loop.call_soon_threadsafe(queue.put_nowait, {
                    "type": "done", "run_id": result.run_id,
                    "status": result.verdict.status, "reasons": result.verdict.reasons,
                    "attempts": result.attempts, "stage_url": stage_url,
                })
            except Exception as exc:                      # noqa: BLE001 — surfaced, not swallowed
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "error", "message": str(exc)})
            finally:
                state.run_lock.release()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            while True:
                msg = await queue.get()
                await websocket.send_json(msg)
                if msg["type"] in ("done", "error"):
                    break
        except WebSocketDisconnect:
            pass

    # -------------------------------------------------------------------- ship

    @app.post("/api/ship")
    def ship(body: ShipBody):
        store = RunStore(str(state.root))
        try:
            run = store.open(body.run_id)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        verdict = run.get("verdict")
        if verdict is None:
            return {"ok": False, "error": "no verdict on this run"}
        try:
            files = guide._apply_diff(state.root, run, verdict, allow_warn=body.allow_warn)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        commit_error = None
        if body.commit:
            man = run.manifest()
            task_text = (man.get("task") or {}).get("text", "").strip()
            msg = task_text.splitlines()[0][:72] if task_text else "sembl-stack: applied change"
            commit_error = guide._git_commit(state.root, msg)
        return {"ok": True, "files": files, "commit_error": commit_error}

    # ---------------------------------------------------------------- frontend

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    app = create_app(args.repo)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
