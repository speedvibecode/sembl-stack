from types import SimpleNamespace

from click.testing import CliRunner

from sembl_stack.adapters.merge_git import GitMergeAdapter
from sembl_stack.artifacts import Verdict
from sembl_stack.cli import main


class _FakeGit:
    """Stateful `git -C <repo> ...` stub: checkout actually moves HEAD, so the adapter's
    post-checkout branch verification is exercised faithfully (not value-agnostic)."""

    def __init__(self, *, start="feature", checkout=(0, ""), merge=(0, ""),
                 verify=(0, "ref\n"), head_sha="deadbeef\n", merge_stderr=""):
        self.branch = start
        self._checkout = checkout
        self._merge = merge
        self._verify = verify
        self._head_sha = head_sha
        self._merge_stderr = merge_stderr
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        args = cmd[3:]                      # drop ["git", "-C", repo]
        sub = args[0] if args else ""
        if sub == "checkout":
            rc, out = self._checkout
            if rc == 0:
                self.branch = args[1]
            return SimpleNamespace(returncode=rc, stdout=out, stderr="checkout failed")
        if sub == "rev-parse":
            if "--abbrev-ref" in args:
                return SimpleNamespace(returncode=0, stdout=self.branch + "\n", stderr="")
            if "--verify" in args:
                rc, out = self._verify
                return SimpleNamespace(returncode=rc, stdout=out, stderr="")
            return SimpleNamespace(returncode=0, stdout=self._head_sha, stderr="")  # rev-parse HEAD
        if sub == "merge":
            rc, out = self._merge
            return SimpleNamespace(returncode=rc, stdout=out, stderr=self._merge_stderr)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def subs(self):
        return [c[3:] for c in self.calls]


def _patch(monkeypatch, fake):
    monkeypatch.setattr("sembl_stack.adapters.merge_git.subprocess.run", fake)


def test_merge_adapter_merges_on_success(monkeypatch, tmp_path):
    fake = _FakeGit(start="feature", merge=(0, "Merge made by the 'ort' strategy.\n"))
    _patch(monkeypatch, fake)

    rec = GitMergeAdapter(timeout=5).merge(str(tmp_path), into="main", source="feature")

    assert rec.status == "merged"
    assert rec.commit == "deadbeef"
    assert rec.target_branch == "main"
    # the merge actually ran on the target branch...
    assert ["merge", "--no-ff", "-m", "merge feature into main (sembl-gated)", "feature"] in fake.subs()
    # ...and the repo was restored to the branch we started on.
    assert rec.data["restored_to_branch"] == "feature"
    assert fake.branch == "feature"
    assert "token" not in rec.to_json().lower()


def test_merge_adapter_fails_when_checkout_fails(monkeypatch, tmp_path):
    """The P0 fix: a failed checkout must NOT silently merge on the current branch."""
    fake = _FakeGit(start="feature", checkout=(1, ""))
    _patch(monkeypatch, fake)

    rec = GitMergeAdapter(timeout=5).merge(str(tmp_path), into="main", source="feature")

    assert rec.status == "failed"
    assert rec.commit is None
    assert "checkout" in rec.data["reason"]
    # crucially, no merge was attempted, and we never left the source branch
    assert not any(s and s[0] == "merge" for s in fake.subs())
    assert fake.branch == "feature"
    # redacted: no raw third-party text in the artifact
    assert isinstance(rec.data["stderr"], dict) and "sha256" in rec.data["stderr"]


def test_merge_adapter_fails_on_conflict(monkeypatch, tmp_path):
    fake = _FakeGit(start="feature", merge=(1, "CONFLICT (content): Merge conflict\n"))
    _patch(monkeypatch, fake)

    rec = GitMergeAdapter(timeout=5).merge(str(tmp_path), into="main", source="feature")

    assert rec.status == "failed"
    assert rec.commit is None
    assert ["merge", "--abort"] in fake.subs()      # a conflicted merge must be aborted
    assert fake.branch == "feature"                 # and restored to the start branch


def test_merge_record_round_trips():
    from sembl_stack.artifacts import MergeRecord, from_dict
    m = MergeRecord(target_branch="main", source_ref="feature", commit="abc", status="merged",
                    data={"no_ff": True})
    back = from_dict(m.to_dict())
    assert isinstance(back, MergeRecord)
    assert back.target_branch == "main" and back.status == "merged" and back.commit == "abc"


def test_merge_cli_refuses_block_verdict(tmp_path):
    verdict_path = tmp_path / "verdict.json"
    verdict_path.write_text(Verdict(status="BLOCK").to_json(), encoding="utf-8")

    result = CliRunner().invoke(main, [
        "merge", "--verdict", str(verdict_path), "--repo", str(tmp_path),
    ])

    assert result.exit_code != 0
    assert "refusing to merge a BLOCK" in result.output
