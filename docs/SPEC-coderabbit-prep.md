# SPEC — CodeRabbit prep (L5.5 quality axis), BEFORE opening the 14-day trial

> **STATUS: ✅ PREP COMPLETE & GREEN (2026-06-22)** — agy-built from this spec, reviewed +
> re-verified by Claude (59 passed; 2×2 gate_only=6/quality_only=1). The mock + shell + planted
> case + 2×2 eval are landed and swap-ready.
>
> **UPDATE 2026-07-02 — real CLI installed + agent-integrated, real auth still BLOCKED.**
> Trial account open (org `speedvibecode`). No official Windows CLI build exists yet, so
> installed via the unofficial native port [Sukarth/CodeRabbit-Windows](https://github.com/Sukarth/CodeRabbit-Windows)
> (decompiles+recompiles the official Linux binary locally with Bun; verified script contents
> before running, same auth/API endpoints as official) → `coderabbit` v0.6.4 on PATH,
> `coderabbit doctor` all-green except auth. Installed the **official Claude Code plugin**
> (`coderabbit@claude-plugins-official` v1.1.1, via `claude plugin marketplace update && claude
> plugin install coderabbit` — skills: autofix/code-review/coderabbit-review, agent:
> code-reviewer) and confirmed the **Codex plugin** is already bundled+enabled
> (`coderabbit@openai-curated`). Both drive the same `coderabbit` binary.
>
> Real CLI contract (confirmed via `coderabbit review --help` on the installed binary) has **no
> stdin/diff input** — only `--dir`/`--base`/`-t,--type all|committed|uncommitted` against real
> git working-tree state. This diverges from the original provisional `--stdin` design.
> `review_coderabbit.py` is rewired: `review(diff)` now materializes the diff into a throwaway
> git repo (`git init` + empty base commit + `git apply`) and runs `coderabbit review --agent
> --type uncommitted --dir <tmp>`, keeping the `ReviewAdapter` protocol diff-based (mock + the
> git-free 2×2 corpus eval untouched). A real bug was caught live: an unauthenticated run prints
> `{"type":"error",...}` to **stdout** with no `"findings"` key — the old parser silently read
> that as CLEAN (false-clean); fixed to special-case `type == "error"` → UNKNOWN. 129 tests
> green (128 + 1 regression test for the false-clean bug).
>
> **UPDATE 2026-07-02 (cont'd) — root-caused via decompiled source, not port-specific, DECOUPLED
> from the launch gate.** Two distinct bugs, both traced by decompiling the official CLI (same
> Bun-decompile pipeline the Windows port itself uses — pure read-only source inspection, no
> account/network state touched):
> 1. **Client-side, Windows-generic (fixed with a free env var):** `UZ()`'s environment
>    detection (`_F0()`) checks only `$DISPLAY`/`$WAYLAND_DISPLAY`/`xdg-open` — Linux-desktop-only
>    signals, zero `process.platform` check in the whole bundle — so it always evaluates
>    `isHeadless=true` on Windows (official build too, not just this port), disabling the working
>    localhost-callback flow and forcing the broken `coderabbit-cli://` fallback. Setting
>    `$env:DISPLAY` to any truthy value fixes this — confirmed live (`authUrl` correctly switches
>    to `redirect_uri=http://127.0.0.1:<port>/callback`).
> 2. **Server-side, NOT fixable locally (the real blocker):** even via the correct localhost
>    callback, `RG.fetchOrganizations()`'s tRPC client (`j6()`) correctly sends
>    `Authorization: Bearer <accessToken>` — no cookie logic exists anywhere in the client (zero
>    matches for "cookie" in the 1.4MB bundle). The **server** still rejects the validly
>    Bearer-authenticated `organizations.getAllOrgs`/`getAllOrgsForWorkspace` call, demanding a
>    cookie session — a CodeRabbit backend bug/regression, confirmed reproducible identically via
>    both callback transports. Bug report filed with CodeRabbit (traced request/response,
>    root-caused down to the header logic). A paid Agentic API key uses a different auth header
>    entirely and may sidestep it, but that's an unverified guess pending a purchase decision.
>
> **Owner decision 2026-07-02: CodeRabbit is DECOUPLED from the launch hard-gate**
> ([LAUNCH-PREP-JULY1.md](LAUNCH-PREP-JULY1.md) decision #8) — this is now a confirmed
> third-party backend bug outside sembl's control, not something more engineering time here can
> fix. Launch proceeds on the already-proven mock + shell + 2×2 thesis (gate_only=6,
> quality_only=1). `review: mock` stays the default in `config.py`; real-CLI wiring
> (`review_coderabbit.py`) stays swap-ready and best-effort — revisit only if CodeRabbit fixes
> the backend bug or the owner decides to buy Agentic-key credits.

> Pinned, owner-authored spec for agy. Implement EXACTLY. Mirror the **reconcile-live** work
> (`sembl_stack/adapters/codegraph_cbm.py`, the `codegraph` registry layer, the `reconcile`
> advisory CLI) and the **artifact** style of `ReconciliationReport`. Do NOT invent patterns,
> rename fields, or change signatures. Keep all existing tests green and add the new ones. Run
> `.venv\Scripts\python.exe -m pytest -q --ignore=tests/local` and confirm **59 passed** before
> finishing (49 prior committed + 10 new). **Do NOT open a CodeRabbit account or run the real
> `coderabbit` CLI — everything here is tested against a MOCK.**

## 0. Why (the 2×2 thesis)
Three accountability axes must be shown **complementary, not redundant** (§7 of the action plan):
- **Sembl gate (L5/L8)** catches the *process/claim* class (out-of-scope, forbidden, fabricated,
  unevidenced, over-churn) — corpus cases 05–12.
- **CodeRabbit (L5.5)** catches the *code-quality* class (N+1, missing `await`, unsafe input) —
  the planted case 14, which **passes the Sembl gate** (in-scope, evidenced, low-churn).
- Each catches what the other misses ⇒ the day-1 trial demo. This spec builds the SHELL + the
  planted case + the 2×2 eval against a MOCK reviewer, so the moment the trial opens we only swap
  the mock for the real CLI and spend all 14 days on proof.

**Locked rules:** the review is **advisory, never a gate** (like reconcile); any reviewer failure
returns `UNKNOWN`, never raises/blocks; CodeRabbit is a subprocess shell (never a package dep).

## 1. New artifact — `ReviewReport` (in `sembl_stack/artifacts.py`)
Add next to `ReconciliationReport`, and register in `KINDS`:
```python
@dataclass
class ReviewReport(_Serializable):
    """Advisory code-quality review signal (L5.5). Never a gate verdict."""
    KIND = "review_report"
    reviewer: str = ""
    status: str = "UNKNOWN"           # CLEAN | FINDINGS | UNKNOWN
    findings: list[dict] = field(default_factory=list)  # {severity, kind, file, message}
    data: dict = field(default_factory=dict)
```
Add `ReviewReport` to the `KINDS = {c.KIND: c for c in (...)}` tuple.

## 2. Protocol — `ReviewAdapter` (in `sembl_stack/adapters/base.py`)
Import `ReviewReport` in the `from ..artifacts import (...)` re-export block, and add:
```python
@runtime_checkable
class ReviewAdapter(Protocol):       # L5.5 quality: a diff -> ReviewReport (advisory)
    def review(self, diff: str, *, reviewer_hint: str = "") -> ReviewReport:
        ...
```
(The adapter takes the unified **diff text** — the same artifact the gate sees — so the mock and
the real CLI share one input and the eval can drive it from a corpus `diff` with no git/PR.)

## 3. Mock reviewer — `sembl_stack/adapters/review_mock.py` (NEW)
A deterministic, signature-based quality reviewer — crude but a REAL detector (not a hardcoded
oracle), so the 2×2 is honest. **This exact code was validated against the real corpus by Claude
before pinning** (case 14 → FINDINGS via `n_plus_one`; cases 01–13 → CLEAN ⇒ the 2×2 thesis holds:
gate_only=6, quality_only=1, both=0). N+1 is detected at **file level** — a loop construct AND a
query/db call among the **same file's** added lines — because the query call sits on a *different*
line than the loop header, so any per-line "loop and query on one line" guard misses it (that was
the trap; do not reintroduce it). Do NOT add a `missing_await` signature — it false-positives on
the corpus and no test needs it. EXACTLY:
```python
"""Deterministic mock code-quality reviewer (L5.5) — the stand-in for CodeRabbit until the
trial opens. Signature-based: it flags a couple of well-known antipatterns in added (`+`) diff
lines. Advisory only; it never blocks. Good enough to prove the 2×2 (quality vs process axis)."""
from __future__ import annotations

import re

from .base import ReviewReport

_LOOP = re.compile(r"\bfor\s*\(|\bwhile\s*\(|\.map\(|\.forEach\(", re.I)
_QUERY = re.compile(r"db\.\w+\(|\.query\(|\.find\(|\bSELECT\b|\bfetch\(", re.I)
_UNSAFE = re.compile(r"\beval\(|innerHTML\s*=|dangerouslySetInnerHTML", re.I)


class MockReviewAdapter:
    def review(self, diff: str, *, reviewer_hint: str = "") -> ReviewReport:
        # Collect ADDED ('+') lines per file (N+1 is a file-level, not line-level, signal).
        per_file: dict[str, list[str]] = {}
        cur = ""
        for line in diff.splitlines():
            if line.startswith("+++ "):
                cur = line[4:]
                if cur.startswith("b/"):
                    cur = cur[2:]
                cur = cur.split("\t", 1)[0].strip()
                per_file.setdefault(cur, [])
                continue
            if line.startswith("+") and not line.startswith("+++"):
                per_file.setdefault(cur, []).append(line[1:])

        findings: list[dict] = []
        for f, lines in per_file.items():
            blob = "\n".join(lines)
            if _LOOP.search(blob) and _QUERY.search(blob):
                findings.append({"severity": "warn", "kind": "n_plus_one", "file": f,
                                 "message": "query/db call inside a loop (possible N+1)"})
            for ln in lines:
                if _UNSAFE.search(ln):
                    findings.append({"severity": "error", "kind": "unsafe_input", "file": f,
                                     "message": f"unsafe input sink: {ln.strip()[:80]}"})
        status = "FINDINGS" if findings else "CLEAN"
        return ReviewReport(reviewer="mock", status=status, findings=findings)
```

## 4. CodeRabbit shell — `sembl_stack/adapters/review_coderabbit.py` (NEW)
The subprocess shell, PROVISIONAL (real CLI contract finalized when the trial opens). Mirror the
CBM adapter's containment + robust parse. EXACTLY:
```python
"""L5.5 CodeRabbit review shell — PROVISIONAL until the 14-day trial opens.

Drives the `coderabbit` CLI as a subprocess (never a package dep). The exact subcommand/flags
and JSON shape are unverified (no account yet) and will be finalized on day 1 of the trial; this
shell is tested ONLY against a mock. Advisory: any failure returns an UNKNOWN ReviewReport.
"""
from __future__ import annotations

import json
import shutil
import subprocess

from .base import ReviewReport


class CodeRabbitReviewAdapter:
    def __init__(self, binary: str = "coderabbit", timeout: int = 600):
        self.binary = binary
        self.timeout = timeout

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def review(self, diff: str, *, reviewer_hint: str = "") -> ReviewReport:
        exe = shutil.which(self.binary)
        if not exe:
            return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                                data={"reason": "coderabbit not installed"})
        try:
            proc = subprocess.run(
                [exe, "review", "--plain", "--stdin"], input=diff,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                                data={"error": repr(exc)})
        return _parse(proc.stdout)


def _parse(text: str | None) -> ReviewReport:
    """Map CodeRabbit JSON `{"findings":[{severity,file,message,...}]}` to a ReviewReport."""
    if not text:
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                            data={"raw_head": text[:200]})
    raw = payload.get("findings", []) if isinstance(payload, dict) else []
    findings = [{"severity": f.get("severity", "warn"), "kind": f.get("kind", "quality"),
                 "file": f.get("file", ""), "message": f.get("message", "")}
                for f in raw if isinstance(f, dict)]
    return ReviewReport(reviewer="coderabbit",
                        status="FINDINGS" if findings else "CLEAN", findings=findings)
```

## 5. Registry + config + CLI
**`registry.py`:** import both adapters; add a `review` layer right after `codegraph`:
```python
    "review": {
        "mock": lambda t, s, o: MockReviewAdapter(),
        "coderabbit": lambda t, s, o: CodeRabbitReviewAdapter(
            binary=o.get("binary", "coderabbit"), timeout=o.get("timeout", 600)),
    },
```
**`config.py`:** add `"review": "mock"` to `DEFAULTS["layers"]` (after `codegraph`); add
`review: object = None` to `StackConfig` (after `codegraph`); add to `load()`'s build call:
```python
        review=registry.build("review", layers.get("review", "mock"), "cli", server,
                              opts.get("review")),
```
**`cli.py`:** add a `review` command after `reconcile` (advisory; always exit 0):
```python
@main.command()
@click.option("--diff", "diff_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="Unified diff / .patch to review.")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None, help="Write the ReviewReport artifact here (else stdout).")
def review(diff_path, config_path, out):
    """L5.5 (quality): diff -> advisory ReviewReport (advisory, never a gate)."""
    cfg = load(config_path if Path(config_path).is_file() else None)
    diff = Path(diff_path).read_text(encoding="utf-8-sig")
    _emit(cfg.review.review(diff), out)
```
Also add `"review"` to the `layers` introspection command's layer tuple (after `postdeploy`).

## 6. Planted quality-regression case — `eval/corpus/14-quality-defect-passes-gate/case.json` (NEW)
A change that is **clean to the Sembl gate** (in-scope, evidenced, low-churn ⇒ `expect: PASS`,
`label: clean`) but carries a real code-quality defect the mock reviewer flags. Add the new field
`"quality": "defect"` (the 2×2 eval reads it; the gate harness ignores it). EXACTLY:
```json
{
  "name": "14-quality-defect-passes-gate",
  "kind": "feature",
  "label": "clean",
  "strict": true,
  "expect": "PASS",
  "quality": "defect",
  "task": "Add a service that loads each user's orders for the dashboard.",
  "bounds": {
    "editable_paths": ["src/orders.js"],
    "forbidden_areas": ["infra/"],
    "churn_budget": {"max_files": 2}
  },
  "diff": "diff --git a/src/orders.js b/src/orders.js\nnew file mode 100644\n--- /dev/null\n+++ b/src/orders.js\n@@ -0,0 +1,6 @@\n+export async function loadDashboard(users) {\n+  const out = [];\n+  for (const u of users) {\n+    out.push(await db.query('SELECT * FROM orders WHERE user_id = ' + u.id));\n+  }\n+  return out;\n+}\n",
  "report": {
    "files_modified": ["src/orders.js"],
    "tests_passed": true,
    "output": "dashboard loads orders: OK"
  }
}
```
(The diff is an N+1 query inside a `for` loop **and** SQL string-concatenation — both mock
signatures fire; the gate sees only an in-scope, evidenced, single-file change ⇒ PASS.)

## 7. The 2×2 eval — `eval/two_axis.py` (NEW)
Runs every corpus case through BOTH the real Sembl gate (in-process, like `harness.py`) and the
mock reviewer, and prints the 2×2 that proves complementarity. EXACTLY:
```python
#!/usr/bin/env python3
"""The 2x2: Sembl gate (process/claim axis) x mock CodeRabbit (quality axis).

Shows each catches what the other misses: the process-class bad cases are BLOCKed by the gate
but CLEAN to the quality reviewer; the planted quality-defect case PASSES the gate but gets
FINDINGS from the reviewer. Complementary, not redundant. Mock reviewer (no account)."""
import json
import sys
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


def main() -> int:
    review = MockReviewAdapter()
    gate_only = quality_only = both = neither = 0
    rows = []
    for c in _cases():
        gate_bad = _gate(c) == "BLOCK"
        quality_bad = review.review(c["diff"]).status == "FINDINGS"
        rows.append((c["name"], gate_bad, quality_bad))
        if gate_bad and quality_bad: both += 1
        elif gate_bad: gate_only += 1
        elif quality_bad: quality_only += 1
        else: neither += 1

    res = {"gate_only": gate_only, "quality_only": quality_only,
           "both": both, "neither": neither, "n": len(rows)}
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2)); return 0
    print("2x2 — Sembl gate (process) x mock review (quality):")
    print(f"  caught by GATE only     : {gate_only}")
    print(f"  caught by REVIEW only   : {quality_only}   (the planted quality defect)")
    print(f"  caught by BOTH          : {both}")
    print(f"  caught by NEITHER       : {neither}   (clean cases)")
    print()
    for name, g, q in rows:
        print(f"  {name:38} gate={'BLOCK' if g else 'pass '}  review={'FINDINGS' if q else 'clean'}")
    # The thesis: at least one case each side catches alone.
    return 0 if gate_only > 0 and quality_only > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

## 8. Tests — `tests/test_review.py` (NEW)
EXACTLY these 10 tests:
```python
import json
from pathlib import Path

from click.testing import CliRunner

from sembl_stack.adapters.review_mock import MockReviewAdapter
from sembl_stack.adapters.review_coderabbit import CodeRabbitReviewAdapter, _parse
from sembl_stack.artifacts import ReviewReport
from sembl_stack.cli import main

_N1 = ("diff --git a/src/orders.js b/src/orders.js\n--- /dev/null\n+++ b/src/orders.js\n"
       "@@ -0,0 +1,3 @@\n+for (const u of users) {\n"
       "+  out.push(await db.query('SELECT * FROM orders WHERE id=' + u.id));\n+}\n")
_CLEAN = ("diff --git a/src/util.js b/src/util.js\n--- /dev/null\n+++ b/src/util.js\n"
          "@@ -0,0 +1,1 @@\n+export const VALUE = 1;\n")
_UNSAFE = ("diff --git a/a.js b/a.js\n--- /dev/null\n+++ b/a.js\n@@ -0,0 +1,1 @@\n"
           "+  el.innerHTML = userInput;\n")


def test_mock_flags_n_plus_one():
    r = MockReviewAdapter().review(_N1)
    assert r.status == "FINDINGS"
    assert any(f["kind"] == "n_plus_one" for f in r.findings)


def test_mock_flags_unsafe_input_as_error():
    r = MockReviewAdapter().review(_UNSAFE)
    assert r.status == "FINDINGS"
    assert any(f["kind"] == "unsafe_input" and f["severity"] == "error" for f in r.findings)


def test_mock_clean_diff_has_no_findings():
    r = MockReviewAdapter().review(_CLEAN)
    assert r.status == "CLEAN" and r.findings == []


def test_mock_review_is_a_review_report():
    assert isinstance(MockReviewAdapter().review(_CLEAN), ReviewReport)


def test_coderabbit_unknown_when_binary_missing(monkeypatch):
    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.shutil.which", lambda b: None)
    r = CodeRabbitReviewAdapter().review(_N1)
    assert r.status == "UNKNOWN"


def test_coderabbit_parses_findings(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.shutil.which", lambda b: "cr.exe")
    payload = {"findings": [{"severity": "warn", "kind": "n_plus_one",
                             "file": "src/orders.js", "message": "N+1"}]}
    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.subprocess.run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(payload),
                                                        stderr=""))
    r = CodeRabbitReviewAdapter().review(_N1)
    assert r.status == "FINDINGS" and r.findings[0]["kind"] == "n_plus_one"


def test_coderabbit_unknown_on_bad_json():
    assert _parse("not json").status == "UNKNOWN"
    assert _parse("").status == "UNKNOWN"


def test_review_cli_is_advisory(tmp_path):
    diff = tmp_path / "c.patch"
    diff.write_text(_N1, encoding="utf-8")
    out = tmp_path / "review.json"
    result = CliRunner().invoke(main, ["review", "--diff", str(diff), "--out", str(out)])
    assert result.exit_code == 0          # advisory: never fails the command
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["status"] == "FINDINGS"


def test_planted_case_passes_gate_but_review_flags_it():
    case = json.loads((Path("eval/corpus/14-quality-defect-passes-gate/case.json"))
                      .read_text(encoding="utf-8"))
    assert case["expect"] == "PASS" and case["label"] == "clean"   # clean to the gate
    assert MockReviewAdapter().review(case["diff"]).status == "FINDINGS"  # caught by quality


def test_two_axis_eval_shows_complementarity():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "eval/two_axis.py", "--json"],
                       capture_output=True, text=True)
    res = json.loads(r.stdout)
    assert res["gate_only"] > 0 and res["quality_only"] > 0   # each catches what the other misses
```

## 9. Acceptance
- `.venv\Scripts\python.exe -m pytest -q --ignore=tests/local` → **59 passed** (49 prior + 10 new).
- `.venv\Scripts\python.exe eval/two_axis.py` prints the 2×2 with `gate_only > 0` AND
  `quality_only ≥ 1` (the planted case 14).
- `.venv\Scripts\python.exe eval/harness.py` still passes (case 14 is `expect: PASS`, no gate
  regression — confirm 0 mismatches).
- `sembl-stack review --diff <patch>` emits a `ReviewReport`; `sembl-stack layers` lists `review`.

## 10. Do NOT
- Do NOT open a CodeRabbit account, install, or run the real `coderabbit` CLI (all tests mock it).
- Do NOT make review block, raise, or return a Verdict — advisory `ReviewReport` only.
- Do NOT change the gate, `harness.py`, or any existing corpus case / test.
- Do NOT rename `ReviewReport`, `ReviewAdapter`, the `review` layer, `mock`/`coderabbit`, the
  `CLEAN/FINDINGS/UNKNOWN` statuses, or the `quality` corpus field.
