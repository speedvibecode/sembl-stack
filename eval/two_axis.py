#!/usr/bin/env python3
"""The 2x2: Sembl gate (process/claim axis) x mock CodeRabbit (quality axis).

Shows each catches what the other misses: the process-class bad cases are BLOCKed by the gate
but CLEAN to the quality reviewer; the planted quality-defect case PASSES the gate but gets
FINDINGS from the reviewer. Complementary, not redundant.

Reviewers: mock (default, deterministic, no account), a REAL one via
`--reviewer llm [--model m]` — the BYO agent-CLI reviewer (review_llm.py) — or
`--reviewer coderabbit` (real authenticated CodeRabbit CLI, review_coderabbit.py).
Add `--patient` for real reviewers: waits out rate-limit windows instead of counting a
throttled review as UNKNOWN."""
import json
import sys
import time
from pathlib import Path

from sembl.mcp_server import verify_change
from sembl_stack.adapters.review_mock import MockReviewAdapter

CORPUS = Path(__file__).resolve().parent / "corpus"


def _cases():
    return [json.loads((d / "case.json").read_text(encoding="utf-8"))
            for d in sorted(CORPUS.iterdir()) if (d / "case.json").is_file()]


def _gate(case):
    b = case["bounds"]
    out = verify_change(
        diff=case["diff"], report=case.get("report"),
        editable_paths=b.get("editable_paths"), forbidden_areas=b.get("forbidden_areas"),
        churn_budget=b.get("churn_budget"), strict=case.get("strict", True))
    return out["summary"]["verdict"]


def _reviewer():
    name = (sys.argv[sys.argv.index("--reviewer") + 1]
            if "--reviewer" in sys.argv else "mock")
    if name == "llm":
        from sembl_stack.adapters.review_llm import LLMReviewAdapter
        model = (sys.argv[sys.argv.index("--model") + 1]
                 if "--model" in sys.argv else None)
        return name, LLMReviewAdapter(model=model, timeout=300)
    if name == "coderabbit":
        from sembl_stack.adapters.review_coderabbit import CodeRabbitReviewAdapter
        return name, CodeRabbitReviewAdapter()
    return "mock", MockReviewAdapter()


def _patient_review(review, diff, tries: int = 6, wait: int = 300):
    """Real reviewers rate-limit on back-to-back runs; with --patient, wait out the window
    and retry instead of counting a throttled review as UNKNOWN."""
    rep = review.review(diff)
    for _ in range(tries):
        if "rate limit" not in str(rep.data.get("reason", "")).lower():
            return rep
        time.sleep(wait)
        rep = review.review(diff)
    return rep


def main() -> int:
    name, review = _reviewer()
    patient = "--patient" in sys.argv
    gate_only = quality_only = both = neither = unknown = 0
    rows = []
    quality_only_cases = []
    for c in _cases():
        gate_bad = _gate(c) == "BLOCK"
        rep = _patient_review(review, c["diff"]) if patient else review.review(c["diff"])
        status = rep.status
        if status == "UNKNOWN":                # a real reviewer can fail; never count as clean
            unknown += 1
        quality_bad = status == "FINDINGS"
        rows.append((c["name"], gate_bad, quality_bad))
        if gate_bad and quality_bad: both += 1
        elif gate_bad: gate_only += 1
        elif quality_bad: quality_only += 1; quality_only_cases.append(c["name"])
        else: neither += 1

    res = {"reviewer": name, "gate_only": gate_only, "quality_only": quality_only,
           "both": both, "neither": neither, "unknown": unknown, "n": len(rows),
           "quality_only_cases": quality_only_cases}
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2)); return 0
    print(f"2x2 — Sembl gate (process) x {name} review (quality):")
    print(f"  caught by GATE only     : {gate_only}")
    print(f"  caught by REVIEW only   : {quality_only}   (the planted quality defect)")
    print(f"  caught by BOTH          : {both}")
    print(f"  caught by NEITHER       : {neither}   (clean cases)")
    if unknown:
        print(f"  review UNKNOWN          : {unknown}   (reviewer failures — not counted clean)")
    print()
    for name, g, q in rows:
        print(f"  {name:38} gate={'BLOCK' if g else 'pass '}  review={'FINDINGS' if q else 'clean'}")
    # The thesis: at least one case each side catches alone.
    return 0 if gate_only > 0 and quality_only > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
