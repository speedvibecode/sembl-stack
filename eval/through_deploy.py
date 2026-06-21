#!/usr/bin/env python3
import json
import sys
from pathlib import Path

from sembl.mcp_server import verify_change

CORPUS = Path(__file__).resolve().parent / "corpus"

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

def main() -> int:
    cases = _load_cases()
    mismatches = []
    
    n_bad = 0
    n_clean = 0
    
    blocked_pre_deploy = 0
    rolled_back_post_deploy = 0
    live_bad = 0
    
    blocked_clean = 0
    
    for c in cases:
        verdict = _gate_verdict(c)
        if c["expect"] != verdict:
            mismatches.append((c["name"], c["expect"], verdict))
        
        is_bad = c["label"] != "clean"
        breaks_health = c.get("deploy", {}).get("breaks_health", False)
        
        if is_bad:
            n_bad += 1
            if verdict == "BLOCK":
                blocked_pre_deploy += 1
            else:
                # slips the gate
                if breaks_health:
                    rolled_back_post_deploy += 1
                else:
                    live_bad += 1
        else:
            n_clean += 1
            if verdict == "BLOCK" or breaks_health:
                blocked_clean += 1

    bad_live_rate_without = 1.0 if n_bad else 0.0
    bad_live_rate_with = round(live_bad / n_bad, 3) if n_bad else 0.0
    
    false_alarm_rate_without = 0.0
    false_alarm_rate_with = round(blocked_clean / n_clean, 3) if n_clean else 0.0
    
    if "--json" in sys.argv:
        # Support --json (dump the funnel counts + rates)
        res = {
            "n_cases": len(cases),
            "n_bad": n_bad,
            "n_clean": n_clean,
            "blocked_pre_deploy": blocked_pre_deploy,
            "rolled_back_post_deploy": rolled_back_post_deploy,
            "live_bad": live_bad,
            "bad_live_rate": {
                "without": bad_live_rate_without,
                "with": bad_live_rate_with
            },
            "false_alarm_rate": {
                "without": false_alarm_rate_without,
                "with": false_alarm_rate_with
            },
            "mismatches": len(mismatches)
        }
        print(json.dumps(res, indent=2))
    else:
        # Print table exactly as specified in section 4
        print(f"through-deploy funnel over {n_bad} bad changes:")
        print(f"  blocked pre-deploy (gate)        : {blocked_pre_deploy}")
        print(f"  rolled back post-deploy (L8)     : {rolled_back_post_deploy}")
        print(f"  still live (bad)                 : {live_bad}")
        print()
        print("  metric                  WITHOUT      WITH(chain)")
        print(f"  bad-live rate              {bad_live_rate_without:.1f}        {bad_live_rate_with:.3f}   (lower is better - the headline)")
        print(f"  false-alarm rate           {false_alarm_rate_without:.1f}          {false_alarm_rate_with:.1f}   (clean changes never blocked/rolled-back)")
        print()
        
        # Also print the summary line exactly as in Section 5
        print(f"blocked pre-deploy {blocked_pre_deploy}, rolled back post-deploy {rolled_back_post_deploy}, still live {live_bad}; "
              f"bad-live rate WITHOUT {bad_live_rate_without:.1f} -> WITH {bad_live_rate_with:.3f}; "
              f"false-alarm {false_alarm_rate_with:.1f}; {len(mismatches)} mismatches.")
        
        if mismatches:
            print(f"\n  {len(mismatches)} verdict mismatch(es) vs corpus expectations:")
            for name, exp, act in mismatches:
                print(f"    {name}: expected {exp}, got {act}")
                
    return 1 if mismatches else 0

if __name__ == "__main__":
    raise SystemExit(main())
