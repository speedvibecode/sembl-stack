# SPEC — L6.5 merge stage (gated merge to the target branch)

> Pinned, owner-authored spec. Implement it EXACTLY. Mirror the existing **deploy** stage
> (`sembl_stack/adapters/deploy_vercel.py`, the `deploy` CLI command, registry/config entries).
> Do NOT invent new patterns, rename fields, or change signatures. Keep all 74 existing tests
> green and add the new ones. After implementing, run `.venv\Scripts\python.exe -m pytest -q`
> and confirm everything passes before finishing.

## 0. Why
The chain is `… → Sembl gate → quality review → MERGE → deploy → post-deploy`. The merge stage
sits at **L6.5**, between the gate (`Verdict`) and deploy. It is a **gated merge**: a `PASS`
verdict merges the change into the target branch; `WARN` merges only with `--allow-warn`;
`BLOCK` is refused (held). It mirrors the deploy stage exactly: the CLI guards the verdict, the
adapter owns the artifact, git is the mechanism, and no secrets enter the artifact.

## 1. New artifact — `MergeRecord` (in `sembl_stack/artifacts.py`)
Add this dataclass next to `Delivery`, and register it in `KINDS`:
```python
@dataclass
class MergeRecord(_Serializable):
    """Gated-merge record (L6.5). PASS/WARN -> merged; BLOCK -> held."""
    KIND = "merge_record"
    target_branch: str = ""
    source_ref: str = ""
    commit: str | None = None          # merge/HEAD sha when status == "merged"
    status: str = "pending"            # merged | held | failed
    data: dict = field(default_factory=dict)
```
Then add `MergeRecord` to the `KINDS = {c.KIND: c for c in (...)}` tuple.

## 2. New Protocol — `MergeAdapter` (in `sembl_stack/adapters/base.py`)
Import `MergeRecord` in the `from ..artifacts import (...)` re-export block, and add:
```python
@runtime_checkable
class MergeAdapter(Protocol):        # L6.5: Verdict(PASS) -> MergeRecord
    def merge(self, repo: str, *, into: str = "main", source: str = "HEAD",
              no_ff: bool = True, message: str | None = None) -> MergeRecord:
        ...
```

## 3. New adapter — `sembl_stack/adapters/merge_git.py`
Mirror `deploy_vercel.py` (same `_tail` / `_safe_command` helpers, same redaction discipline,
same `data` dict shape, capture-output via `subprocess.run` so tests can monkeypatch it).
Behaviour:
```python
"""L6.5 gated merge adapter using local git.

The stage owns the MergeRecord, not the VCS mechanism. PASS/WARN verdicts are gated at the
CLI; this adapter performs the merge into the target branch and records the merge commit.
No credentials ever enter the artifact.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from .base import MergeRecord


class GitMergeAdapter:
    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    def available(self) -> bool:
        return shutil.which("git") is not None

    def merge(self, repo: str, *, into: str = "main", source: str = "HEAD",
              no_ff: bool = True, message: str | None = None) -> MergeRecord:
        repo_path = str(Path(repo).resolve())

        def _git(args: list[str]):
            return subprocess.run(
                ["git", "-C", repo_path, *args], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout)

        t0 = time.perf_counter()
        # target branch must exist
        check = _git(["rev-parse", "--verify", "--quiet", into])
        if check.returncode != 0:
            return MergeRecord(
                target_branch=into, source_ref=source, status="failed",
                data={"reason": "target branch not found",
                      "latency_s": round(time.perf_counter() - t0, 3)})

        prev = _git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        _git(["checkout", into])
        msg = message or f"merge {source} into {into} (sembl-gated)"
        merge_cmd = ["merge", *(["--no-ff"] if no_ff else []), "-m", msg, source]
        m = _git(merge_cmd)

        if m.returncode != 0:
            _git(["merge", "--abort"])     # best-effort cleanup of a conflicted merge
            return MergeRecord(
                target_branch=into, source_ref=source, status="failed",
                data={"reason": "merge failed", "returncode": m.returncode,
                      "previous_branch": prev,
                      "latency_s": round(time.perf_counter() - t0, 3),
                      "command": _safe_command(["git", *merge_cmd]),
                      "stdout": _tail(m.stdout), "stderr": _tail(m.stderr)})

        sha = _git(["rev-parse", "HEAD"]).stdout.strip()
        return MergeRecord(
            target_branch=into, source_ref=source, commit=sha or None, status="merged",
            data={"no_ff": no_ff, "previous_branch": prev,
                  "latency_s": round(time.perf_counter() - t0, 3),
                  "command": _safe_command(["git", *merge_cmd]),
                  "stdout": _tail(m.stdout), "stderr": _tail(m.stderr)})


def _tail(text, limit: int = 4000) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return str(text)[-limit:]


def _safe_command(cmd: list[str]) -> list[str]:
    safe, redact_next = [], False
    for part in cmd:
        if redact_next:
            safe.append("<redacted>"); redact_next = False; continue
        safe.append(part)
        if part == "--token":
            redact_next = True
    return safe
```

## 4. Registry — `sembl_stack/registry.py`
Import the adapter and add the layer:
```python
from .adapters.merge_git import GitMergeAdapter
```
Add to `_REGISTRY` (place the `"merge"` block right before `"deploy"` to reflect chain order):
```python
    "merge": {
        "git": lambda t, s, o: GitMergeAdapter(timeout=o.get("timeout", 300)),
    },
```

## 5. Config — `sembl_stack/config.py`
- In `DEFAULTS["layers"]`, add `"merge": "git"` (place it before `"deploy"`).
- Add a field to `StackConfig`: `merge: object = None` (place it before `deploy`).
- In `load(...)`'s `StackConfig(...)` call, add:
```python
        merge=registry.build("merge", layers.get("merge", "git"), "cli", server,
                             opts.get("merge")),
```

## 6. CLI — `sembl_stack/cli.py`
Add a `merge` command. Place it **immediately before** the `deploy` command, mirroring its
verdict-guard logic exactly:
```python
@main.command()
@click.option("--repo", default=".")
@click.option("--verdict", "verdict_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Final gate Verdict artifact. Must be PASS unless --allow-warn.")
@click.option("--into", default="main", show_default=True, help="Target branch to merge into.")
@click.option("--source", default="HEAD", show_default=True, help="Ref to merge.")
@click.option("--allow-warn", is_flag=True,
              help="Allow merging a WARN verdict. BLOCK is never merged.")
@click.option("--no-ff/--ff", default=True, help="Create a merge commit (default) vs fast-forward.")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None, help="Write the MergeRecord artifact here.")
def merge(repo, verdict_path, into, source, allow_warn, no_ff, config_path, out):
    """L6.5: Verdict(PASS) -> MergeRecord. Gated merge into the target branch."""
    verdict = _read_verdict(verdict_path)
    if verdict.status == "BLOCK":
        raise click.UsageError("refusing to merge a BLOCK verdict")
    if verdict.status == "WARN" and not allow_warn:
        raise click.UsageError("refusing to merge WARN without --allow-warn")
    if verdict.status not in ("PASS", "WARN"):
        raise click.UsageError(f"unsupported verdict status: {verdict.status}")

    cfg = load(config_path if Path(config_path).is_file() else None)
    record = cfg.merge.merge(repo, into=into, source=source, no_ff=no_ff)
    _emit(record, out)
    raise SystemExit(0 if record.status == "merged" else 1)
```
Also: in the `presets`/layer-list command (the line listing
`("spec", "execute", "sandbox", "verify", "context", "deploy", "postdeploy")`), insert
`"merge"` before `"deploy"` so `merge` shows up in the layer listing.
(The module docstring usage block may optionally gain a `sembl-stack merge --verdict ... ` line.)

## 7. Tests — `tests/test_merge_git.py` (NEW)
Mirror `tests/test_deploy_postdeploy.py`. Monkeypatch `sembl_stack.adapters.merge_git.subprocess.run`
with a fake that branches on the git subcommand. Use EXACTLY these three tests:
```python
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
```

## 8. Acceptance
- `.venv\Scripts\python.exe -m pytest -q` → all prior tests + 3 new = **77 passed** (1 skipped).
- `.venv\Scripts\python.exe -m sembl_stack.cli presets` (or the layer-listing command) shows a
  `merge` layer. `doctor` still runs.
- No secret/token ever appears in a `MergeRecord` (the `token` assertion covers it).

## 9. Do NOT
- Do not change the deploy/postdeploy stages or any existing test.
- Do not perform a real network or destructive action in tests (subprocess.run is monkeypatched).
- Do not rename `MergeRecord`, `GitMergeAdapter`, the `merge` layer name, or any CLI flag above.
- Do not add the merge stage into the retry loop — it is a post-gate CLI stage like deploy.
