#!/usr/bin/env python3
"""B3 — the WITH/WITHOUT eval harness over the B2 corpus.

Runs every `eval/corpus/<case>/case.json` through the REAL gate
(`sembl.mcp_server.verify_change`, in-process — deterministic, no model, no MCP server)
and computes the O3 metrics from docs/eval-metric-O3.md:

  * caught rate           — bad changes the gate BLOCKed / all bad cases
  * bad-merge rate        — bad changes that still reached "merged", WITHOUT vs WITH
  * false-alarm rate      — clean changes the gate blocked, WITHOUT vs WITH
  * (flagged)             — bad changes the gate WARNed (merged-with-warning; honest limit)

It also checks each case's actual verdict against the `expect` the corpus declares — a
correctness / no-harm control: a mismatch means the gate's behaviour drifted, and the
harness exits non-zero so it doubles as a regression guard.

The cost / iterations-to-green arm (O3 §3.4–3.5) is fed by live-loop runs via the C1.3
run-store `attempts_log`; the captured-diff corpus here is single-shot, so this harness
reports the catch / bad-merge / false-alarm headline that captured diffs support exactly.

Usage:  python eval/harness.py [--json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# sembl is installed in the shared venv; import the real gate in-process.
from sembl.mcp_server import verify_change

CORPUS = Path(__file__).resolve().parent / "corpus"
MERGED = ("PASS", "WARN")            # O3 §2: WARN/PASS ⇒ merged; BLOCK ⇒ not merged


def _load_cases() -> list[dict]:
    return [json.loads((d / "case.json").read_text(encoding="utf-8"))
            for d in sorted(CORPUS.iterdir()) if (d / "case.json").is_file()]


def _gate_verdict(case: dict) -> str:
    b = case["bounds"]
    out = verify_change(
        diff=case["diff"], report=case.get("report"),
        editable_paths=b.get("editable_paths"), forbidden_areas=b.get("forbidden_areas"),
        churn_budget=b.get("churn_budget"), strict=case.get("strict", True))
    return out["summary"]["verdict"]


def run_corpus() -> dict:
    cases = _load_cases()
    rows, mismatches = [], []
    n_bad = n_clean = 0
    caught_bad = merged_bad = warned_bad = blocked_clean = 0

    for c in cases:
        verdict = _gate_verdict(c)
        is_bad = c["label"] != "clean"
        merged = verdict in MERGED
        rows.append({"name": c["name"], "label": c["label"],
                     "expect": c["expect"], "actual": verdict})
        if c["expect"] != verdict:
            mismatches.append((c["name"], c["expect"], verdict))
        if is_bad:
            n_bad += 1
            caught_bad += verdict == "BLOCK"
            warned_bad += verdict == "WARN"
            merged_bad += merged
        else:
            n_clean += 1
            blocked_clean += verdict == "BLOCK"

    def rate(n, d):
        return round(n / d, 3) if d else None

    return {
        "n_cases": len(cases), "n_bad": n_bad, "n_clean": n_clean,
        "caught_rate": rate(caught_bad, n_bad),
        "flagged_warn_bad": warned_bad,
        "bad_merge_rate": {"without": 1.0 if n_bad else None,
                           "with": rate(merged_bad, n_bad)},
        "false_alarm_rate": {"without": 0.0 if n_clean else None,
                             "with": rate(blocked_clean, n_clean)},
        "rows": rows, "mismatches": mismatches,
    }


def _print(res: dict) -> None:
    print(f"corpus: {res['n_cases']} cases  ({res['n_bad']} bad, {res['n_clean']} clean)\n")
    print(f"  {'case':32} {'label':14} {'expect':6} {'gate':6}")
    for r in res["rows"]:
        flag = "" if r["expect"] == r["actual"] else "  <-- MISMATCH"
        print(f"  {r['name']:32} {r['label']:14} {r['expect']:6} {r['actual']:6}{flag}")

    bm, fa = res["bad_merge_rate"], res["false_alarm_rate"]
    print("\n  metric                  WITHOUT      WITH")
    print(f"  bad-merge rate          {bm['without']!s:>7}    {bm['with']!s:>7}"
          "   (lower is better - the headline)")
    print(f"  false-alarm rate        {fa['without']!s:>7}    {fa['with']!s:>7}"
          "   (must stay low - the cost)")
    print(f"  caught rate (BLOCK)         {'-':>4}    {res['caught_rate']!s:>7}"
          f"   ({res['flagged_warn_bad']} more WARN-flagged but merged)")

    if res["mismatches"]:
        print(f"\n  {len(res['mismatches'])} verdict mismatch(es) vs corpus expectations:")
        for name, exp, act in res["mismatches"]:
            print(f"    {name}: expected {exp}, got {act}")


def main() -> int:
    res = run_corpus()
    if "--json" in sys.argv:
        print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=2))
    else:
        _print(res)
    return 1 if res["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
