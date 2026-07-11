"""L6 orchestration: the short loop as a state machine.

plan (L2) -> execute (L3, in a fresh sandbox L4) -> verify (L5) ->
  BLOCK & attempts left? feed the gate's reasons back and retry
  PASS/WARN? accept.

Driven by LangGraph when installed (real retry graph + checkpointable), with a
built-in fallback runner of identical semantics so the loop boots with zero extra
installs. Every node is wrapped in a Langfuse span via the tracer.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

from .adapters.base import Task, Verdict
from .artifacts import AcceptanceReport, Change, Trace, bind_verdict
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
        run.put(report, name=f"acceptance-{attempt_n}")
        run.append_event("acceptance", "done", attempt=attempt_n)
        return {"acceptance": contract, "acceptance_report": report}

    return acceptance


def _nodes(cfg: StackConfig, task: Task, tracer, run, holder: dict | None = None):
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
        if prev is not None:
            prev.close()                           # fresh cage per attempt
        run.append_event("sandbox", "start", attempt=n)
        sandbox = cfg.sandbox.open(task.repo)
        run.append_event("sandbox", "done", attempt=n)
        if holder is not None:
            holder["sandbox"] = sandbox            # so run() can close it on a crash
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
        return {"sandbox": sandbox, "result": result}

    def verify(state: dict) -> dict:
        attempt_n = state["attempt"] + 1
        run.append_event("verify", "start", attempt=attempt_n)
        change = state["result"]
        exec_err = _execution_error(change)
        if exec_err is not None:
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


def run(cfg: StackConfig, task: Task) -> LoopResult:
    tracer = get_tracer(cfg.langfuse)
    run_rec = RunStore(task.repo).new_run(task)
    bus_root = Path(task.repo).resolve()
    publish(bus_root, {
        "kind": "run.started", "run_id": run_rec.id,
        "summary": f"run started: {task.text[:80]}",
        "data": {"task": task.text}})
    # L4 isolation guard: snapshot the source tree BEFORE any sandbox/executor runs.
    tree_before = _source_tree_status(task.repo)
    holder: dict = {"sandbox": None}
    plan, execute, verify, route = _nodes(cfg, task, tracer, run_rec, holder)
    acceptance = _acceptance_node(cfg, task, tracer, run_rec)   # L4.5, between execute/verify
    init = {"attempt": 0, "feedback": None, "history": []}

    try:
        try:
            final, engine = _run_langgraph(plan, execute, acceptance, verify, route, init)
        except ImportError:
            final, engine = (_run_fallback(plan, execute, acceptance, verify, route, init),
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

    return LoopResult(
        verdict=verdict, attempts=final["attempt"],
        history=final["history"], workdir=workdir, engine=engine,
        run_id=run_rec.id,
    )


def _run_langgraph(plan, execute, acceptance, verify, route, init):
    from langgraph.graph import StateGraph, END   # raises ImportError if absent

    g = StateGraph(LoopState)
    g.add_node("plan", plan)
    g.add_node("execute", execute)
    g.add_node("acceptance", acceptance)
    g.add_node("verify", verify)
    g.set_entry_point("plan")
    g.add_edge("plan", "execute")
    g.add_edge("execute", "acceptance")
    g.add_edge("acceptance", "verify")
    g.add_conditional_edges("verify", route, {"retry": "execute", "done": END})
    app = g.compile()
    return app.invoke(init, {"recursion_limit": 50}), "langgraph"


def _run_fallback(plan, execute, acceptance, verify, route, init):
    state = dict(init)
    state.update(plan(state))
    while True:
        state.update(execute(state))
        state.update(acceptance(state))
        state.update(verify(state))
        if route(state) == "done":
            return state
