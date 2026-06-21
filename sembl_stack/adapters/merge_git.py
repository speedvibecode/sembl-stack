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

from ._redact import summarize
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

        # Switching to the target MUST succeed before we merge. A dirty tree, a locked branch,
        # or any refusal returns non-zero; if we ignored it the merge would run on whatever
        # branch is currently checked out while the record claims `into` was merged — a false
        # accountability record (and it could mutate the source branch). Fail loudly instead.
        co = _git(["checkout", into])
        if co.returncode != 0:
            return MergeRecord(
                target_branch=into, source_ref=source, status="failed",
                data={"reason": "checkout of target branch failed",
                      "returncode": co.returncode, "previous_branch": prev,
                      "latency_s": round(time.perf_counter() - t0, 3),
                      "stderr": summarize(co.stderr)})
        # Defense in depth: confirm HEAD actually moved to the target before merging.
        cur = _git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        if cur != into:
            return MergeRecord(
                target_branch=into, source_ref=source, status="failed",
                data={"reason": f"expected to be on '{into}' but on '{cur}' after checkout",
                      "previous_branch": prev,
                      "latency_s": round(time.perf_counter() - t0, 3)})

        msg = message or f"merge {source} into {into} (sembl-gated)"
        merge_cmd = ["merge", *(["--no-ff"] if no_ff else []), "-m", msg, source]
        m = _git(merge_cmd)

        if m.returncode != 0:
            _git(["merge", "--abort"])     # best-effort cleanup of a conflicted merge
            self._restore(_git, prev, into)
            return MergeRecord(
                target_branch=into, source_ref=source, status="failed",
                data={"reason": "merge failed", "returncode": m.returncode,
                      "previous_branch": prev,
                      "latency_s": round(time.perf_counter() - t0, 3),
                      "command": _safe_command(["git", *merge_cmd]),
                      "stdout": summarize(m.stdout), "stderr": summarize(m.stderr)})

        sha = _git(["rev-parse", "HEAD"]).stdout.strip()
        restored = self._restore(_git, prev, into)
        return MergeRecord(
            target_branch=into, source_ref=source, commit=sha or None, status="merged",
            data={"no_ff": no_ff, "previous_branch": prev, "restored_to_branch": restored,
                  "latency_s": round(time.perf_counter() - t0, 3),
                  "command": _safe_command(["git", *merge_cmd]),
                  "stdout": summarize(m.stdout), "stderr": summarize(m.stderr)})

    @staticmethod
    def _restore(_git, prev: str, into: str) -> str | None:
        """Best-effort: leave the repo on the branch it started on (the merge commit stays on
        `into` regardless). Returns the branch we ended on, or None if restore was skipped."""
        if not prev or prev in ("HEAD", into):
            return None
        return prev if _git(["checkout", prev]).returncode == 0 else None


def _safe_command(cmd: list[str]) -> list[str]:
    safe, redact_next = [], False
    for part in cmd:
        if redact_next:
            safe.append("<redacted>"); redact_next = False; continue
        safe.append(part)
        if part == "--token":
            redact_next = True
    return safe
