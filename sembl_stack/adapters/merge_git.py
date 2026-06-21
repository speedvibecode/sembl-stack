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
