from types import SimpleNamespace

from click.testing import CliRunner

from sembl_stack.adapters.merge_git import GitMergeAdapter
from sembl_stack.artifacts import Verdict
from sembl_stack.cli import main


def _fake_git(mapping, calls):
    """Return a subprocess.run stub keyed by the git subcommand (args after `-C <repo>`)."""
    def run(cmd, **kwargs):
        sub = cmd[3] if len(cmd) > 3 else ""
        calls.append(cmd)
        rc, out = mapping.get(sub, (0, ""))
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")
    return run


def test_merge_adapter_merges_on_success(monkeypatch, tmp_path):
    calls = []
    mapping = {
        "rev-parse": (0, "deadbeef\n"),   # both --verify and HEAD return 0
        "checkout": (0, ""),
        "merge": (0, "Merge made by the 'ort' strategy.\n"),
    }
    monkeypatch.setattr("sembl_stack.adapters.merge_git.subprocess.run",
                        _fake_git(mapping, calls))

    rec = GitMergeAdapter(timeout=5).merge(str(tmp_path), into="main", source="feature")

    assert rec.status == "merged"
    assert rec.commit == "deadbeef"
    assert rec.target_branch == "main"
    assert "token" not in rec.to_json().lower()


def test_merge_adapter_fails_on_conflict(monkeypatch, tmp_path):
    calls = []
    mapping = {
        "rev-parse": (0, "main\n"),
        "checkout": (0, ""),
        "merge": (1, "CONFLICT (content): Merge conflict\n"),
    }
    monkeypatch.setattr("sembl_stack.adapters.merge_git.subprocess.run",
                        _fake_git(mapping, calls))

    rec = GitMergeAdapter(timeout=5).merge(str(tmp_path), into="main", source="feature")

    assert rec.status == "failed"
    assert rec.commit is None
    # a conflicted merge must be aborted
    assert any(c[3:] == ["merge", "--abort"] for c in calls)


def test_merge_cli_refuses_block_verdict(tmp_path):
    verdict_path = tmp_path / "verdict.json"
    verdict_path.write_text(Verdict(status="BLOCK").to_json(), encoding="utf-8")

    result = CliRunner().invoke(main, [
        "merge", "--verdict", str(verdict_path), "--repo", str(tmp_path),
    ])

    assert result.exit_code != 0
    assert "refusing to merge a BLOCK" in result.output
