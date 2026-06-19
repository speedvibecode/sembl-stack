"""Run-store presentation layer — pure functions shared by the CLI and the TUI (O6).

Keeping the "what to show" logic here (no click, no textual) means the run list and the
single-run detail render identically whether you type `sembl-stack runs` or watch the live
dashboard, and the formatting is unit-testable without spinning up either UI.
"""
from __future__ import annotations


def list_rows(store) -> list[dict]:
    """One summary row per recorded run, newest first."""
    rows = []
    for rid in store.list_runs():
        m = store.open(rid).manifest()
        lat = m.get("total_latency_s")
        rows.append({
            "id": rid,
            "status": m.get("status", "?"),
            "attempts": m.get("attempts", "-"),
            "latency": f"{lat:.2f}s" if isinstance(lat, (int, float)) else "-",
            "task": (m.get("task", {}) or {}).get("text", ""),
        })
    return rows


def detail_lines(store, run_id: str) -> list[str] | None:
    """Plain-text detail for one run (task, bounds, per-attempt verdicts, final), or None."""
    run = store.open(run_id)
    m = run.manifest()
    if not m:
        return None
    lat = m.get("total_latency_s")
    lat_s = f"{lat:.2f}s" if isinstance(lat, (int, float)) else "-"
    out = [
        f"run {run_id}",
        f"  status:  {m.get('status','?')}   attempts={m.get('attempts','-')}   "
        f"engine={m.get('engine','-')}   latency={lat_s}",
    ]
    task = m.get("task", {}) or {}
    if task:
        out.append(f"  task:    {task.get('text','')}")
        out.append(f"  repo:    {task.get('repo','')}")
    bounds = run.get("bounds")
    if bounds is not None:
        out.append(f"  bounds:  editable={bounds.editable_paths}  "
                   f"forbidden={bounds.forbidden_areas}  churn={bounds.churn_budget}")

    log = {e.get("attempt"): e for e in m.get("attempts_log", [])}
    n = m.get("attempts") or 0
    if n:
        out.append("  attempts:")
    for i in range(1, n + 1):
        v = run.get(f"verdict-{i}")
        meta = log.get(i, {})
        status = v.status if v else "?"
        extra = f"  model={meta['model']}" if meta.get("model") else ""
        out.append(f"    {i}: [{status}]  latency={meta.get('latency_s','-')}s{extra}")
        out += [f"         - {r}" for r in (v.reasons if v else [])]

    fv = run.get("verdict")
    if fv is not None:
        out.append(f"  final:   {fv.status}")
    change = run.get("change")
    if change is None and n:
        change = run.get(f"change-{n}")
    if change is not None:
        files = (getattr(change, "report", {}) or {}).get("files_modified") or []
        suffix = f"  files={files}" if files else ""
        out.append(f"  patch:   change.json{suffix}")
        if fv is not None and fv.status in ("PASS", "WARN"):
            warn = " --allow-warn" if fv.status == "WARN" else ""
            out.append(f"  apply:   sembl-stack apply {run_id} --repo {task.get('repo','.')}{warn}")
    out.append(f"  artifacts: {run.dir}")
    return out
