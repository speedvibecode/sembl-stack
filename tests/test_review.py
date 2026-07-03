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


def test_coderabbit_invokes_real_agent_review_shape(monkeypatch):
    """The real CLI has no stdin/diff flag (confirmed via `coderabbit review --help`) -- it
    only reviews git working-tree state. review() must materialize the diff into a throwaway
    repo and invoke `coderabbit review --agent --type uncommitted --dir <tmp>`."""
    from types import SimpleNamespace
    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.shutil.which", lambda b: "cr.exe")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "git":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"findings": []}), stderr="")

    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.subprocess.run", fake_run)
    r = CodeRabbitReviewAdapter().review(_CLEAN)

    assert r.status == "CLEAN"
    final = calls[-1]
    assert final[0] == "cr.exe"
    assert final[1] == "review"
    assert "--agent" in final and "--dir" in final
    assert final[final.index("--type") + 1] == "uncommitted"


def test_coderabbit_unknown_when_diff_does_not_apply(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.shutil.which", lambda b: "cr.exe")

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git" and "apply" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="patch does not apply")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.subprocess.run", fake_run)
    r = CodeRabbitReviewAdapter().review("not a real diff")
    assert r.status == "UNKNOWN"
    assert "did not apply" in r.data["reason"]


def test_coderabbit_unknown_on_bad_json():
    assert _parse("not json").status == "UNKNOWN"
    assert _parse("").status == "UNKNOWN"


def test_coderabbit_unknown_on_error_envelope_not_false_clean():
    """Live-proof finding: an unauthenticated run prints {"type":"error",...} on stdout with
    no "findings" key -- must not be misread as CLEAN (a false-clean would silently blind the
    quality axis while looking healthy)."""
    payload = json.dumps({"type": "error", "phase": "auth",
                          "status": "environment_unsupported", "message": "sign in again"})
    r = _parse(payload)
    assert r.status == "UNKNOWN"
    assert r.data["reason"] == "sign in again"


def test_coderabbit_redacts_unparseable_stdout():
    """Unparseable reviewer stdout (may carry diff snippets/auth errors) must not be persisted raw."""
    secret = "token_ghp_LEAKED_999"
    r = _parse(secret + " <not json>")
    assert r.status == "UNKNOWN"
    assert secret not in r.to_json()
    assert r.data["raw"]["sha256"]


_NDJSON_STREAM = "\n".join([
    json.dumps({"type": "review_context", "reviewType": "uncommitted",
                "baseBranch": "sembl-review-base"}),
    json.dumps({"type": "status", "phase": "analyzing", "status": "reviewing"}),
    json.dumps({"type": "finding", "severity": "critical", "fileName": "src/orders.js",
                "codegenInstructions": "SQL injection: parameterize u.id.",
                "suggestions": ["db.query('... WHERE id = ?', [u.id])"]}),
    json.dumps({"type": "complete", "status": "review_completed", "findings": 1}),
])


def test_coderabbit_parses_real_agent_ndjson_stream():
    """Live-proof finding (2026-07-03, first real authenticated run): `--agent` streams
    NDJSON events (context/status/finding/complete lines), NOT one {"findings":[...]} doc."""
    r = _parse(_NDJSON_STREAM)
    assert r.status == "FINDINGS"
    assert r.findings[0]["file"] == "src/orders.js"
    assert r.findings[0]["severity"] == "critical"
    assert "SQL injection" in r.findings[0]["message"]


def test_coderabbit_ndjson_clean_needs_complete_event():
    clean = "\n".join([
        json.dumps({"type": "status", "phase": "analyzing", "status": "reviewing"}),
        json.dumps({"type": "complete", "status": "review_completed", "findings": 0}),
    ])
    assert _parse(clean).status == "CLEAN"


def test_coderabbit_ndjson_truncated_stream_is_unknown_not_clean():
    """A stream that dies before the `complete` event must not read as a clean review."""
    truncated = json.dumps({"type": "status", "phase": "analyzing", "status": "reviewing"})
    # a lone status line parses as a single JSON dict with no findings key — guard both paths
    assert _parse(truncated).status == "UNKNOWN"
    two_lines = truncated + "\n" + json.dumps({"type": "review_context"})
    assert _parse(two_lines).status == "UNKNOWN"


def test_coderabbit_ndjson_error_event_is_unknown():
    stream = "\n".join([
        json.dumps({"type": "status", "phase": "connecting", "status": "connecting"}),
        json.dumps({"type": "error", "phase": "review", "message": "rate limited"}),
    ])
    r = _parse(stream)
    assert r.status == "UNKNOWN" and r.data["reason"] == "rate limited"


def test_coderabbit_passes_pinned_base_branch(monkeypatch):
    """Live-proof finding: the real CLI refuses to review without a resolvable base branch —
    the throwaway repo pins its branch name and review() passes it via --base."""
    from types import SimpleNamespace
    from sembl_stack.adapters.review_coderabbit import _BASE_BRANCH
    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.shutil.which", lambda b: "cr.exe")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"findings": []}), stderr="")

    monkeypatch.setattr("sembl_stack.adapters.review_coderabbit.subprocess.run", fake_run)
    CodeRabbitReviewAdapter().review(_CLEAN)
    init = calls[0]
    assert init[:2] == ["git", "init"] and _BASE_BRANCH in init
    final = calls[-1]
    assert final[final.index("--base") + 1] == _BASE_BRANCH


def test_coderabbit_materializes_modification_diffs(tmp_path):
    """Live-proof finding (real 2x2 run): a diff that MODIFIES an existing file cannot
    `git apply` against an empty base commit — the base must synthesize the pre-image from
    the diff's own hunks. Only greenfield diffs applied before this, so 12/14 corpus cases
    silently degraded to UNKNOWN."""
    from sembl_stack.adapters.review_coderabbit import _materialize_diff
    mod_diff = ("diff --git a/src/app.js b/src/app.js\n"
                "--- a/src/app.js\n+++ b/src/app.js\n"
                "@@ -2,3 +2,3 @@\n"
                " export function run() {\n"
                "-  return legacy();\n"
                "+  return modern();\n"
                " }\n")
    assert _materialize_diff(str(tmp_path), mod_diff) is None   # applied cleanly
    body = (tmp_path / "src" / "app.js").read_text(encoding="utf-8")
    assert "return modern();" in body and "legacy" not in body


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


def test_llm_unknown_when_binary_missing(monkeypatch):
    from sembl_stack.adapters.review_llm import LLMReviewAdapter
    monkeypatch.setattr("sembl_stack.adapters.review_llm.shutil.which", lambda b: None)
    r = LLMReviewAdapter().review(_N1)
    assert r.status == "UNKNOWN" and "not installed" in r.data["reason"]


def test_llm_pipes_prompt_with_diff_on_stdin(monkeypatch):
    """Default engine is `claude -p` with the reviewer prompt (diff embedded) on STDIN —
    argv would hit the Windows ~32K limit on real diffs."""
    from types import SimpleNamespace
    from sembl_stack.adapters.review_llm import LLMReviewAdapter
    monkeypatch.setattr("sembl_stack.adapters.review_llm.shutil.which", lambda b: "claude.exe")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["stdin"] = cmd, kwargs.get("input")
        return SimpleNamespace(returncode=0, stdout='{"findings": []}', stderr="")

    monkeypatch.setattr("sembl_stack.adapters.review_llm.subprocess.run", fake_run)
    r = LLMReviewAdapter(model="claude-haiku-4-5-20251001").review(_N1)
    assert r.status == "CLEAN"
    assert seen["cmd"][0] == "claude.exe" and "-p" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert _N1 in seen["stdin"] and "code reviewer" in seen["stdin"]


def test_llm_parses_findings_even_inside_markdown_fences(monkeypatch):
    """Models ignore the no-fence rule; the parser must still find the JSON."""
    from types import SimpleNamespace
    from sembl_stack.adapters.review_llm import LLMReviewAdapter
    monkeypatch.setattr("sembl_stack.adapters.review_llm.shutil.which", lambda b: "claude.exe")
    reply = ('Here is my review:\n```json\n{"findings": [{"severity": "warn", '
             '"kind": "n_plus_one", "file": "src/orders.js", "message": "query in loop"}]}\n```')
    monkeypatch.setattr("sembl_stack.adapters.review_llm.subprocess.run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=reply, stderr=""))
    r = LLMReviewAdapter().review(_N1)
    assert r.status == "FINDINGS" and r.findings[0]["kind"] == "n_plus_one"


def test_llm_unknown_on_prose_reply_never_false_clean(monkeypatch):
    """A reply with no parsable findings JSON is UNKNOWN, not CLEAN — and the raw model
    output (which may quote the diff) is fingerprinted, never persisted."""
    from types import SimpleNamespace
    from sembl_stack.adapters.review_llm import LLMReviewAdapter
    monkeypatch.setattr("sembl_stack.adapters.review_llm.shutil.which", lambda b: "claude.exe")
    monkeypatch.setattr("sembl_stack.adapters.review_llm.subprocess.run",
                        lambda *a, **k: SimpleNamespace(
                            returncode=0, stdout="Looks fine to me! secret_ghp_LEAK", stderr=""))
    r = LLMReviewAdapter().review(_N1)
    assert r.status == "UNKNOWN"
    assert "secret_ghp_LEAK" not in r.to_json()


def test_llm_unknown_on_nonzero_exit_and_timeout(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from sembl_stack.adapters.review_llm import LLMReviewAdapter
    monkeypatch.setattr("sembl_stack.adapters.review_llm.shutil.which", lambda b: "claude.exe")
    monkeypatch.setattr("sembl_stack.adapters.review_llm.subprocess.run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="rate limit"))
    assert LLMReviewAdapter().review(_N1).status == "UNKNOWN"

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr("sembl_stack.adapters.review_llm.subprocess.run", boom)
    assert LLMReviewAdapter().review(_N1).status == "UNKNOWN"


def test_llm_empty_diff_is_clean_without_spending_tokens(monkeypatch):
    from sembl_stack.adapters.review_llm import LLMReviewAdapter

    def boom(*a, **k):
        raise AssertionError("must not invoke the CLI on an empty diff")

    monkeypatch.setattr("sembl_stack.adapters.review_llm.subprocess.run", boom)
    assert LLMReviewAdapter().review("   \n").status == "CLEAN"


def test_llm_registered_as_review_adapter():
    from sembl_stack.registry import build, names
    assert "llm" in names("review")
    adapter = build("review", "llm", "stdio", [], {"model": "claude-haiku-4-5-20251001"})
    assert adapter.model == "claude-haiku-4-5-20251001"


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
