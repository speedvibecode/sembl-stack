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
from .config import StackConfig
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


def _nodes(cfg: StackConfig, task: Task, tracer):
    def plan(state: dict) -> dict:
        with tracer.span("L2.plan"):
            bounds = cfg.spec.plan(task)
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
        return {"sandbox": sandbox, "result": result}

    def verify(state: dict) -> dict:
        with tracer.span("L5.verify"):
            verdict = cfg.verify.verify(state["bounds"], state["result"], cfg.strict)
        attempt = state["attempt"] + 1
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
    plan, execute, verify, route = _nodes(cfg, task, tracer)
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

    return LoopResult(
        verdict=final["verdict"], attempts=final["attempt"],
        history=final["history"], workdir=workdir, engine=engine,
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
