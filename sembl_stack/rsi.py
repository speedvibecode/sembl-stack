"""RSI-L1 readout — measured selection over the run store (north-star first rung).

The north star (docs/process-self-improvement.md) climbs L0 (manual swap) -> L1 (measured
selection): pick executors on RECORDED signal, not vibes. This module is that signal,
aggregated: per executor, over every run recorded in `.sembl/runs/`, how often the loop
went green, in how many iterations, and at what cost.

Honesty rules [LOCKED]:
  * everything here is read back from run-store artifacts the loop already persisted —
    nothing is estimated, sampled, or modeled;
  * cost/tokens appear ONLY when the executor adapter reported usage (the C1.3
    `attempts_log` hook in `loop.py`); runs recorded before an adapter reported usage
    show "not yet recorded" — never an invented number;
  * "green" = the loop accepted the run (final PASS or WARN; WARN is counted separately
    so a WARN-heavy executor can't hide). iterations-to-green = the first attempt whose
    verdict the loop accepted.

Pure and headless: no Textual, no click — `cli.py rsi` renders it.
"""
from __future__ import annotations

from .store import RunStore

GREEN = ("PASS", "WARN")          # statuses the loop accepts (WARN = accepted-with-caveat)
UNKNOWN_EXECUTOR = "(unrecorded)"  # runs whose attempts_log never named an agent


# --- per-run extraction ---------------------------------------------------------

def run_record(run) -> dict | None:
    """One run's manifest+artifacts distilled into the RSI row. None if no manifest."""
    m = run.manifest()
    if not m:
        return None
    log = m.get("attempts_log", []) or []
    agent = next((e.get("agent") for e in log if e.get("agent")), None) or UNKNOWN_EXECUTOR
    models = sorted({e["model"] for e in log if e.get("model")})
    status = m.get("status", "?")
    attempts = m.get("attempts")
    if not isinstance(attempts, int) or attempts < 1:
        attempts = len(log) or None

    tokens = [e["tokens"] for e in log if isinstance(e.get("tokens"), (int, float))]
    costs = [e["cost"] for e in log if isinstance(e.get("cost"), (int, float))]
    latency = m.get("total_latency_s")
    if not isinstance(latency, (int, float)):
        lat = [e["latency_s"] for e in log if isinstance(e.get("latency_s"), (int, float))]
        latency = round(sum(lat), 3) if lat else None

    return {
        "id": m.get("id", run.id),
        "agent": agent,
        "models": models,
        "status": status,
        "attempts": attempts,
        "iters_to_green": _iters_to_green(run, status, attempts),
        "latency_s": latency,
        "tokens": sum(tokens) if tokens else None,
        "cost": round(sum(costs), 6) if costs else None,
    }


def _iters_to_green(run, status: str, attempts: int | None) -> int | None:
    """First attempt whose verdict the loop accepted (PASS/WARN), from the per-attempt
    verdict artifacts; falls back to the manifest attempt count when the per-attempt
    verdicts are missing but the run ended green (the loop stops at the first accept,
    so the two agree by construction). None when the run never went green."""
    if attempts:
        for i in range(1, attempts + 1):
            v = run.get(f"verdict-{i}")
            if v is not None and getattr(v, "status", None) in GREEN:
                return i
    if status in GREEN and attempts:
        return attempts
    return None


# --- aggregation -----------------------------------------------------------------

def aggregate(store: RunStore) -> dict:
    """Group every recorded run by executor and compute the RSI-L1 measures."""
    rows = []
    for rid in store.list_runs():
        rec = run_record(store.open(rid))
        if rec is not None:
            rows.append(rec)

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["agent"], []).append(r)

    executors = []
    for agent in sorted(groups):
        rs = groups[agent]
        n = len(rs)
        n_pass = sum(1 for r in rs if r["status"] == "PASS")
        n_warn = sum(1 for r in rs if r["status"] == "WARN")
        n_block = sum(1 for r in rs if r["status"] == "BLOCK")
        n_other = n - n_pass - n_warn - n_block          # failed / started / unknown
        iters = [r["iters_to_green"] for r in rs if r["iters_to_green"] is not None]
        lats = [r["latency_s"] for r in rs if r["latency_s"] is not None]
        costed = [r for r in rs if r["cost"] is not None]
        tokened = [r for r in rs if r["tokens"] is not None]
        models = sorted({m for r in rs for m in r["models"]})
        executors.append({
            "executor": agent,
            "models": models,
            "runs": n,
            "pass": n_pass, "warn": n_warn, "block": n_block, "other": n_other,
            "green_rate": _rate(n_pass + n_warn, n),
            "block_rate": _rate(n_block, n),
            "iters_to_green": {
                "n": len(iters),
                "mean": round(sum(iters) / len(iters), 2) if iters else None,
                "min": min(iters) if iters else None,
                "max": max(iters) if iters else None,
            },
            "latency_s": {
                "n": len(lats),
                "total": round(sum(lats), 3) if lats else None,
                "mean": round(sum(lats) / len(lats), 3) if lats else None,
            },
            # Honest cost: sums cover ONLY the runs whose adapter reported usage.
            "cost_usd": {
                "runs_recorded": len(costed),
                "total": round(sum(r["cost"] for r in costed), 6) if costed else None,
            },
            "tokens": {
                "runs_recorded": len(tokened),
                "total": sum(r["tokens"] for r in tokened) if tokened else None,
            },
        })

    return {
        "store": str(store.root),
        "n_runs": len(rows),
        "executors": executors,
        "runs": rows,
    }


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


# --- rendering ---------------------------------------------------------------------

def render(summary: dict) -> str:
    """The self-explanatory table. Every number traces to a run-store artifact."""
    lines = [
        "RSI-L1 — measured selection (per-executor signal from the run store)",
        f"store: {summary['store']}   runs: {summary['n_runs']}",
        "",
        "  green      = the loop accepted the run (final PASS or WARN)",
        "  iters      = attempts until the first accepted verdict (mean over green runs)",
        "  cost       = USD summed over runs whose executor reported usage;",
        "               'not yet recorded' means the adapter surfaced no usage — no number",
        "               is ever invented for those runs.",
        "",
    ]
    if not summary["executors"]:
        lines.append("no runs recorded yet — `sembl-stack loop task.yaml` starts the feed.")
        return "\n".join(lines)

    hdr = (f"  {'executor':16} {'runs':>4} {'green':>6} {'block':>6} "
           f"{'iters':>6} {'latency':>9} {'cost (USD)':>18}")
    lines += [hdr, "  " + "-" * (len(hdr) - 2)]
    for e in summary["executors"]:
        iters = e["iters_to_green"]["mean"]
        lat = e["latency_s"]["mean"]
        cost = e["cost_usd"]
        if cost["total"] is not None:
            cost_s = f"{cost['total']:.4f} ({cost['runs_recorded']}/{e['runs']} runs)"
        else:
            cost_s = "not yet recorded"
        lines.append(
            f"  {e['executor']:16} {e['runs']:>4} "
            f"{_pct(e['green_rate']):>6} {_pct(e['block_rate']):>6} "
            f"{iters if iters is not None else '-':>6} "
            f"{(f'{lat:.1f}s' if lat is not None else '-'):>9} "
            f"{cost_s:>18}")
        if e["models"]:
            lines.append(f"  {'':16} models: {', '.join(e['models'])}")
    return "\n".join(lines)


def _pct(x: float | None) -> str:
    return f"{x * 100:.0f}%" if x is not None else "-"
