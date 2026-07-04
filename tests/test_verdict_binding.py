"""Verdict-to-source binding (deep-audit item 1) + the apply dirty-tree guard (item 2).

The accountability gap: `merge`/`apply` used to accept ANY PASS verdict file — a
verdict issued for one change could green-light merging/applying another. Binding
stamps the judged diff's hash + file set onto the Verdict; merge/apply verify it.
"""
import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from sembl_stack.artifacts import Change, Verdict, bind_verdict, diff_sha256
from sembl_stack.cli import main
from sembl_stack.store import RunStore

DIFF = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 x = 1
+y = 2
"""

OTHER_DIFF = DIFF.replace("y = 2", "z = 3")


def _git(repo, *args):
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout


@pytest.fixture
def repo(tmp_path):
    """A real repo: master has src/app.py; branch `feature` edits it (matching DIFF)."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "master")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "src").mkdir()
    (r / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "base")
    _git(r, "checkout", "-b", "feature")
    (r / "src" / "app.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    _git(r, "commit", "-am", "feature work")
    _git(r, "checkout", "master")
    return r


# ── bind_verdict ────────────────────────────────────────────────────────────────

def test_bind_stamps_hash_and_files_from_diff():
    v = bind_verdict(Verdict(status="PASS"), DIFF)
    assert v.raw["subject"]["diff_sha256"] == diff_sha256(DIFF)
    assert v.raw["subject"]["files"] == ["src/app.py"]


def test_bind_prefers_the_gate_payloads_changed_files():
    v = Verdict(status="PASS", raw={"changed_files": ["b.py", "a.py"]})
    assert bind_verdict(v, DIFF).raw["subject"]["files"] == ["a.py", "b.py"]


def test_bound_verdict_round_trips_through_the_store(tmp_path):
    run = RunStore(str(tmp_path)).new_run()
    run.put(bind_verdict(Verdict(status="PASS"), DIFF))
    assert run.get("verdict").raw["subject"]["diff_sha256"] == diff_sha256(DIFF)


# ── apply: verdict must match the patch it green-lights ────────────────────────

def _make_run(repo, *, diff=DIFF, verdict=None):
    run = RunStore(str(repo)).new_run()
    run.put(Change(diff=diff), name="change")
    run.put(verdict or bind_verdict(Verdict(status="PASS"), diff))
    run.set_status("PASS")
    return run.id


def test_apply_accepts_a_verdict_bound_to_this_patch(repo):
    rid = _make_run(repo)
    res = CliRunner().invoke(main, ["apply", rid, "--repo", str(repo)])
    assert res.exit_code == 0, res.output
    assert "y = 2" in (repo / "src" / "app.py").read_text(encoding="utf-8")


def test_apply_refuses_a_verdict_issued_for_another_diff(repo):
    swapped = bind_verdict(Verdict(status="PASS"), OTHER_DIFF)
    rid = _make_run(repo, diff=DIFF, verdict=swapped)
    res = CliRunner().invoke(main, ["apply", rid, "--repo", str(repo)])
    assert res.exit_code != 0
    assert "verdict/patch mismatch" in res.output
    # and nothing was applied
    assert "y = 2" not in (repo / "src" / "app.py").read_text(encoding="utf-8")


def test_apply_unbound_verdict_still_applies(repo):
    # back-compat: runs recorded before binding existed have no subject
    rid = _make_run(repo, verdict=Verdict(status="PASS"))
    res = CliRunner().invoke(main, ["apply", rid, "--repo", str(repo)])
    assert res.exit_code == 0, res.output


# ── apply: dirty-tree guard ─────────────────────────────────────────────────────

def test_apply_refuses_a_dirty_tree(repo):
    rid = _make_run(repo)
    (repo / "src" / "unrelated.py").write_text("wip\n", encoding="utf-8")
    res = CliRunner().invoke(main, ["apply", rid, "--repo", str(repo)])
    assert res.exit_code != 0
    assert "uncommitted changes" in res.output


def test_apply_allow_dirty_overrides(repo):
    rid = _make_run(repo)
    (repo / "src" / "unrelated.py").write_text("wip\n", encoding="utf-8")
    res = CliRunner().invoke(main, ["apply", rid, "--repo", str(repo), "--allow-dirty"])
    assert res.exit_code == 0, res.output


def test_apply_check_ignores_dirty_tree(repo):
    # --check never touches the tree, so the guard must not block it
    rid = _make_run(repo)
    (repo / "src" / "unrelated.py").write_text("wip\n", encoding="utf-8")
    res = CliRunner().invoke(main, ["apply", rid, "--repo", str(repo), "--check"])
    assert res.exit_code == 0, res.output


def test_run_store_noise_does_not_count_as_dirty(repo):
    # .sembl/ (the run store itself) is expected noise, not user work
    rid = _make_run(repo)
    res = CliRunner().invoke(main, ["apply", rid, "--repo", str(repo)])
    assert res.exit_code == 0, res.output


def test_guided_runs_control_files_do_not_count_as_dirty(repo):
    # task.yaml/bounds.json/sembl.stack.yaml are the guided run's own control files
    # (guide.py rewrites them every task step) — their presence must never block
    # applying an already-gated patch (2026-07-04 field bug: every guided apply failed).
    (repo / "task.yaml").write_text('{"text": "x"}', encoding="utf-8")
    (repo / "bounds.json").write_text('{"editable_paths": ["src/"]}', encoding="utf-8")
    (repo / "sembl.stack.yaml").write_text("layers:\n  context: none\n", encoding="utf-8")
    rid = _make_run(repo)
    res = CliRunner().invoke(main, ["apply", rid, "--repo", str(repo)])
    assert res.exit_code == 0, res.output
    assert "y = 2" in (repo / "src" / "app.py").read_text(encoding="utf-8")


def test_a_genuinely_unrelated_file_named_like_a_control_file_still_blocks(repo):
    # the exclusion is root-relative only — src/bounds.json is real user work
    (repo / "src" / "bounds.json").write_text("{}", encoding="utf-8")
    rid = _make_run(repo)
    res = CliRunner().invoke(main, ["apply", rid, "--repo", str(repo)])
    assert res.exit_code != 0
    assert "uncommitted changes" in res.output


# ── merge: verdict's judged file set must match what the merge ships ────────────

def _verdict_file(tmp_path, verdict):
    p = tmp_path / "verdict.json"
    p.write_text(verdict.to_json(), encoding="utf-8")
    return p


def test_merge_verifies_a_matching_bound_verdict(repo, tmp_path):
    vp = _verdict_file(tmp_path, bind_verdict(Verdict(status="PASS"), DIFF))
    res = CliRunner().invoke(main, [
        "merge", "--verdict", str(vp), "--repo", str(repo),
        "--into", "master", "--source", "feature",
        "--out", str(tmp_path / "record.json"),
    ])
    assert res.exit_code == 0, res.output
    record = json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))
    assert record["status"] == "merged"
    assert record["data"]["source_binding"]["status"] == "verified"


def test_merge_refuses_a_verdict_for_a_different_change(repo, tmp_path):
    other = OTHER_DIFF.replace("src/app.py", "src/other.py")
    vp = _verdict_file(tmp_path, bind_verdict(Verdict(status="PASS"), other))
    res = CliRunner().invoke(main, [
        "merge", "--verdict", str(vp), "--repo", str(repo),
        "--into", "master", "--source", "feature",
    ])
    assert res.exit_code != 0
    assert "verdict/source mismatch" in res.output
    # nothing merged
    assert "y = 2" not in (repo / "src" / "app.py").read_text(encoding="utf-8")


def test_merge_skip_binding_check_is_recorded(repo, tmp_path):
    other = OTHER_DIFF.replace("src/app.py", "src/other.py")
    vp = _verdict_file(tmp_path, bind_verdict(Verdict(status="PASS"), other))
    res = CliRunner().invoke(main, [
        "merge", "--verdict", str(vp), "--repo", str(repo),
        "--into", "master", "--source", "feature", "--skip-binding-check",
        "--out", str(tmp_path / "record.json"),
    ])
    assert res.exit_code == 0, res.output
    record = json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))
    assert "skipped" in record["data"]["source_binding"]["status"]


def test_merge_unbound_verdict_passes_with_a_note(repo, tmp_path):
    vp = _verdict_file(tmp_path, Verdict(status="PASS"))
    res = CliRunner().invoke(main, [
        "merge", "--verdict", str(vp), "--repo", str(repo),
        "--into", "master", "--source", "feature",
        "--out", str(tmp_path / "record.json"),
    ])
    assert res.exit_code == 0, res.output
    record = json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))
    assert "unbound" in record["data"]["source_binding"]["status"]
