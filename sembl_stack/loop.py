"""L6 orchestration: the short loop as a state machine.

plan (L2) -> execute (L3, in a fresh sandbox L4) -> verify (L5) ->
  BLOCK & attempts left? feed the gate's reasons back and retry
  PASS/WARN? accept.

Driven by LangGraph when installed (real retry graph + checkpointable), with a
built-in fallback runner of identical semantics so the loop boots with zero extra
installs. Every node is wrapped in a Langfuse span via the tracer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from .adapters.base import Task, Verdict
from .artifacts import Trace
from .config import StackConfig
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
    verdict: Any


@dataclass
class LoopResult:
    verdict: Verdict
    attempts: int
    history: list = field(default_factory=list)   # [(attempt, status), ...]
    workdir: str | None = None
    engine: str = "fallback"
    run_id: str | None = None


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


def _maybe_expand(cfg: StackConfig, task: Task, bounds, tracer) -> None:
    """L1 context stage (in-loop): widen `bounds.editable_paths` along the coupling closure.

    Opt-in via `loop.expand_bounds`. This makes the running loop the fuller pipeline
    (L1→L2→L3→L4→L5) instead of only the `bounds --expand` CLI. It is a no-op — and so leaves
    the gate exactly as strict — when no context adapter is configured/available or the seed
    has no indexed files. Mutates `bounds` in place (one hop, closure-capped; EXP-05).
    """
    if not (cfg.raw.get("loop", {}) or {}).get("expand_bounds"):
        return
    g = cfg.context
    if g is None or not getattr(g, "available", lambda: False)():
        return
    from .contextgraph import expand_bounds as _eb

    opts = (cfg.raw.get("options", {}) or {}).get("context", {}) or {}
    with tracer.span("L1.context"):
        g.index(task.repo)
        fg = g.file_graph(task.repo)
    bounds.editable_paths = _eb(
        list(bounds.editable_paths), fg, hops=opts.get("hops", 1),
        min_strength=opts.get("min_strength", 0), max_fraction=opts.get("max_fraction", 0.4))


def _nodes(cfg: StackConfig, task: Task, tracer, run):
    def plan(state: dict) -> dict:
        with tracer.span("L2.plan"):
            bounds = cfg.spec.plan(task)
        _maybe_expand(cfg, task, bounds, tracer)   # L1: widen along the context graph
        run.put(bounds)                            # persist Bounds artifact (post-expansion)
        return {"bounds": bounds}

    def execute(state: dict) -> dict:
        n = state["attempt"] + 1
        with tracer.span("L3.execute", attempt=n):
            prev = state.get("sandbox")
            if prev is not None:
                prev.close()                       # fresh cage per attempt
            sandbox = cfg.sandbox.open(task.repo)
            result = cfg.execute.run(task, state["bounds"], sandbox,
                                     state.get("feedback"))
        run.put(result, name=f"change-{n}")        # persist Change per attempt
        return {"sandbox": sandbox, "result": result}

    def verify(state: dict) -> dict:
        change = state["result"]
        if _is_empty_change(change):
            # C1 hardening: a no-op execution (empty diff — e.g. the executor errored, hit a
            # dead model, or wrote nothing) must NOT pass. The gate verifies a *change*; with
            # no change there is nothing that satisfies the task, so block and tell the
            # executor it produced nothing (actionable feedback on retry).
            verdict = Verdict(
                status="BLOCK",
                reasons=["executor produced no changes (empty diff) — the task was not "
                         "implemented; check the executor/model output"],
                raw={"empty_diff": True, "report": getattr(change, "report", {})})
        else:
            with tracer.span("L5.verify"):
                verdict = cfg.verify.verify(state["bounds"], change, cfg.strict)
        attempt = state["attempt"] + 1
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


def run(cfg: StackConfig, task: Task) -> LoopResult:
    tracer = get_tracer(cfg.langfuse)
    run_rec = RunStore(task.repo).new_run(task)
    plan, execute, verify, route = _nodes(cfg, task, tracer, run_rec)
    init = {"attempt": 0, "feedback": None, "history": []}

    try:
        final, engine = _run_langgraph(plan, execute, verify, route, init)
    except ImportError:
        final, engine = _run_fallback(plan, execute, verify, route, init), "fallback"

    sandbox = final.get("sandbox")
    workdir = getattr(sandbox, "workdir", None) if sandbox else None
    if sandbox is not None:
        sandbox.close()
    tracer.flush()

    # persist the final verdict, a trace, and the run status
    verdict = final["verdict"]
    run_rec.put(verdict)
    run_rec.put(Trace(steps=[{"attempt": a, "status": s} for a, s in final["history"]]))
    run_rec.set_status("PASS" if verdict.status in ("PASS", "WARN") else "BLOCK",
                       attempts=final["attempt"], engine=engine)

    return LoopResult(
        verdict=verdict, attempts=final["attempt"],
        history=final["history"], workdir=workdir, engine=engine,
        run_id=run_rec.id,
    )


def _run_langgraph(plan, execute, verify, route, init):
    from langgraph.graph import StateGraph, END   # raises ImportError if absent

    g = StateGraph(LoopState)
    g.add_node("plan", plan)
    g.add_node("execute", execute)
    g.add_node("verify", verify)
    g.set_entry_point("plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", route, {"retry": "execute", "done": END})
    app = g.compile()
    return app.invoke(init, {"recursion_limit": 50}), "langgraph"


def _run_fallback(plan, execute, verify, route, init):
    state = dict(init)
    state.update(plan(state))
    while True:
        state.update(execute(state))
        state.update(verify(state))
        if route(state) == "done":
            return state
