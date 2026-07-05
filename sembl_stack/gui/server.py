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
import dataclasses
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import guide, onboarding, profile as profile_mod, runner
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
    concurrent run against the same sandboxed clone)."""
    root: Path
    run_lock: threading.Lock

    def __init__(self, repo: str):
        self.root = Path(repo).resolve()
        self.run_lock = threading.Lock()


def create_app(repo: str = ".") -> FastAPI:
    state = _State(repo)
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
            verdict = run.get("verdict")
            out.append({
                "id": run_id,
                "status": man.get("status"),
                "task": (man.get("task") or {}).get("text", ""),
                "attempts": len(man.get("attempts_log", [])),
                "verdict": verdict.status if verdict is not None else None,
            })
        return out

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        store = RunStore(str(state.root))
        try:
            run = store.open(run_id)
        except ValueError as exc:
            return {"error": str(exc)}
        man = run.manifest()
        verdict = run.get("verdict")
        attempts = []
        for n in range(1, len(man.get("attempts_log", [])) + 1):
            change = run.get(f"change-{n}")
            v = run.get(f"verdict-{n}")
            attempts.append({
                "attempt": n,
                "diff": getattr(change, "diff", "") if change else "",
                "files": guide._changed_files_from_diff(getattr(change, "diff", "") or "")
                        if change else [],
                "status": v.status if v is not None else None,
                "reasons": v.reasons if v is not None else [],
            })
        return {
            "id": run_id,
            "status": man.get("status"),
            "task": man.get("task", {}),
            "verdict": {"status": verdict.status, "reasons": verdict.reasons}
                       if verdict is not None else None,
            "attempts": attempts,
        }

    # --------------------------------------------------------------- run (WS)

    @app.websocket("/ws/run")
    async def ws_run(websocket: WebSocket):
        await websocket.accept()
        if not state.run_lock.acquire(blocking=False):
            await websocket.send_json({
                "type": "error", "message": "a run is already in progress"})
            await websocket.close()
            return

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
                result = runner.run_stages(cfg, task, emit)
                loop.call_soon_threadsafe(queue.put_nowait, {
                    "type": "done", "run_id": result.run_id,
                    "status": result.verdict.status, "reasons": result.verdict.reasons,
                    "attempts": result.attempts,
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
