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


def test_coderabbit_redacts_unparseable_stdout():
    """Unparseable reviewer stdout (may carry diff snippets/auth errors) must not be persisted raw."""
    secret = "token_ghp_LEAKED_999"
    r = _parse(secret + " <not json>")
    assert r.status == "UNKNOWN"
    assert secret not in r.to_json()
    assert r.data["raw"]["sha256"]


def test_coderabbit_unknown_on_timeout(monkeypatch):
    import subprocess
    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.shutil.which", lambda b: "cr.exe")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="cr", timeout=1)

    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.subprocess.run", boom)
    r = CodeRabbitReviewAdapter().review(_N1)
    assert r.status == "UNKNOWN" and r.findings == []


def test_coderabbit_unknown_on_oserror(monkeypatch):
    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.shutil.which", lambda b: "cr.exe")

    def boom(*a, **k):
        raise OSError("spawn failed")

    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.subprocess.run", boom)
    r = CodeRabbitReviewAdapter().review(_N1)
    assert r.status == "UNKNOWN"


def test_review_report_round_trips():
    from sembl_stack.artifacts import from_dict
    rep = ReviewReport(reviewer="mock", status="FINDINGS",
                       findings=[{"severity": "warn", "kind": "n_plus_one", "file": "a.js"}])
    back = from_dict(rep.to_dict())
    assert isinstance(back, ReviewReport)
    assert back.status == "FINDINGS" and back.findings[0]["kind"] == "n_plus_one"


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
    # each catches what the other misses...
    assert res["gate_only"] > 0 and res["quality_only"] > 0
    # ...with no overlap, and the review-only catch is exactly the planted quality defect
    # (guards against a mock that false-positives clean cases into `both`/`quality_only`).
    assert res["both"] == 0
    assert res["quality_only_cases"] == ["14-quality-defect-passes-gate"]
