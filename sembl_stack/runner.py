"""TUI Phase 2 orchestration glue — run the REAL loop and stream stage transitions.

Pure, headless, no Textual: the wizard (and any future surface) drives `run_stages` in a
worker thread and receives `StageEvent`s as the loop's stage functions actually execute —
plan (L2 -> rail "bounds"), execute (L3+L4 -> rail "loop"), verify (L5 -> rail "verify").
No new core/gate logic: the events come from thin proxies wrapped around the SAME adapter
objects `loop.run` already calls, so a TUI run and a headless `sembl-stack loop` run are
byte-identical in behavior and artifacts.

Config resolution mirrors the CLI `loop` command exactly: an explicit repo
`sembl.stack.yaml` always wins; otherwise the onboarded profile is the default.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from .artifacts import Task
from .config import StackConfig, load as load_config
from .loop import LoopResult, run as run_loop

# loop stage -> Phase-0 stage-rail name (session.STAGES)
RAIL = {"plan": "bounds", "execute": "loop", "verify": "verify"}

Emit = Callable[["StageEvent"], None]


@dataclass
class StageEvent:
    stage: str          # rail stage name ("bounds" | "loop" | "verify")
    state: str          # "running" | "done" | "fail"
    detail: str = ""    # e.g. "attempt 2" or the verdict status
    diff: str = ""      # execute-done carries the attempt's unified diff (live view)


class _Proxy:
    """Base for the stage-event proxies. Signature-transparent by construction:
    the wrapped method forwards *args/**kwargs verbatim and every attribute not
    defined on the proxy resolves to the inner adapter — so an adapter method
    growing a kwarg (O12's `acceptance=` on verify did exactly this) or the loop
    reading an adapter attribute can never break only the streamed-run path
    while the headless path keeps working."""

    def __init__(self, inner, emit: Emit):
        self._inner, self._emit = inner, emit

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _SpecProxy(_Proxy):
    def plan(self, task, *args, **kwargs):
        self._emit(StageEvent("bounds", "running"))
        try:
            bounds = self._inner.plan(task, *args, **kwargs)
        except Exception:
            self._emit(StageEvent("bounds", "fail"))
            raise
        self._emit(StageEvent("bounds", "done"))
        return bounds


class _SandboxProxy(_Proxy):
    """L4 made visible: `loop.py`'s execute() node opens a fresh sandbox every
    attempt but nothing ever reported it — the rail jumped straight from bounds to
    execute as if the cage didn't exist. One line per attempt, real (fires exactly
    when `cfg.sandbox.open()` is actually called), never fabricated."""

    def __init__(self, inner, emit: Emit):
        super().__init__(inner, emit)
        self._attempt = 0

    def open(self, repo, *args, **kwargs):
        self._attempt += 1
        try:
            sandbox = self._inner.open(repo, *args, **kwargs)
        except Exception:
            self._emit(StageEvent("sandbox", "fail", f"attempt {self._attempt}"))
            raise
        self._emit(StageEvent(
            "sandbox", "done", f"attempt {self._attempt} — disposable clone"))
        return sandbox


class _ExecuteProxy(_Proxy):
    def __init__(self, inner, emit: Emit):
        super().__init__(inner, emit)
        self._attempt = 0

    def run(self, task, bounds, sandbox, feedback, *args, **kwargs):
        self._attempt += 1
        self._emit(StageEvent("loop", "running", f"attempt {self._attempt}"))
        try:
            result = self._inner.run(task, bounds, sandbox, feedback, *args, **kwargs)
        except Exception:
            # loop.execute converts the crash into a BLOCKed Change; mark the rail
            # anyway so the user sees which attempt died.
            self._emit(StageEvent("loop", "fail", f"attempt {self._attempt} crashed"))
            raise
        self._emit(StageEvent("loop", "done", f"attempt {self._attempt}",
                              diff=getattr(result, "diff", "") or ""))
        return result


class _VerifyProxy(_Proxy):
    def verify(self, bounds, change, strict, *args, **kwargs):
        self._emit(StageEvent("verify", "running"))
        try:
            verdict = self._inner.verify(bounds, change, strict, *args, **kwargs)
        except Exception:
            self._emit(StageEvent("verify", "fail"))
            raise
        status = getattr(verdict, "status", "?")
        self._emit(StageEvent(
            "verify", "done" if status in ("PASS", "WARN") else "fail", status))
        return verdict


def load_task(repo: str, name: str = "task.yaml") -> Task | None:
    """The repo's task.yaml as a Task (same resolution as `cli._load_task`), or None."""
    p = Path(repo).resolve() / name
    if not p.is_file():
        return None
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return None
    base = p.parent

    def _resolve(v):
        if not v:
            return v
        vp = Path(v)
        return str(vp if vp.is_absolute() else (base / vp).resolve())

    return Task(text=data.get("text", ""), repo=_resolve(data.get("repo", ".")),
                spec_path=_resolve(data.get("spec_path")))


def resolve_config(repo: str, config_name: str = "sembl.stack.yaml") -> StackConfig:
    """Repo sembl.stack.yaml wins; else the onboarded profile; else defaults —
    exactly the CLI `loop` precedence, so TUI and headless runs stay identical."""
    cfg_file = Path(repo).resolve() / config_name
    if cfg_file.is_file():
        return load_config(str(cfg_file))
    from . import profile as profile_mod
    prof = profile_mod.load()
    overrides = profile_mod.to_stack_overrides(prof) if prof is not None else None
    return load_config(None, overrides)


def run_stages(cfg, task: Task, emit: Emit, stage_hold: bool = False) -> LoopResult:
    """Run the real loop with stage events streamed to `emit`. Blocking — call it from a
    worker thread; `emit` fires on that thread (marshal to the UI thread yourself,
    e.g. Textual's `call_from_thread`).

    `stage_hold` is D7's passthrough of `loop.run`'s `--stage-hold`: the caller (the
    GUI's WS endpoint) owns closing the returned `LoopResult.stage_handle`, same
    contract as the CLI's `--stage-hold` flag."""
    wrapped = copy.copy(cfg)             # shallow: same adapters, four wrapped in proxies
    wrapped.spec = _SpecProxy(cfg.spec, emit)
    wrapped.sandbox = _SandboxProxy(cfg.sandbox, emit)
    wrapped.execute = _ExecuteProxy(cfg.execute, emit)
    wrapped.verify = _VerifyProxy(cfg.verify, emit)
    result = run_loop(wrapped, task, stage_hold=stage_hold)
    v = result.verdict
    emit(StageEvent("verify", "done" if v.status in ("PASS", "WARN") else "fail",
                    v.status))
    return result
