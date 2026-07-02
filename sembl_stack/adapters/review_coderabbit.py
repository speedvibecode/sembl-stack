"""L5.5 CodeRabbit review shell — PROVISIONAL: contract confirmed against a real, locally
installed CLI (`coderabbit --help` / `coderabbit review --help`, v0.6.4), but not yet proven
end-to-end against a real authenticated review (auth is blocked: this account only has a
"User" API key, and CLI auth requires either a paid "Agentic" API key — behind CodeRabbit's
usage-based add-on — or a working browser OAuth flow, which is broken on the unofficial
Windows CLI port used here). Any auth/subprocess failure returns an UNKNOWN ReviewReport
(advisory, never blocks).

Contract note: the real CLI has NO stdin/diff-text input — it only reviews git working-tree
state (`--dir`, `--base`, `-t/--type all|committed|uncommitted`), unlike the original
provisional `--stdin` design. To keep the `ReviewAdapter.review(diff: str)` protocol uniform
across mock/real (and keep the diff-corpus 2x2 eval git-free), this materializes the diff into
a throwaway git repo (empty base commit + `git apply`) so `coderabbit review --agent --type
uncommitted --dir <tmp>` has something to diff.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ._redact import summarize
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
            with tempfile.TemporaryDirectory(prefix="sembl-review-") as tmp:
                failure = _materialize_diff(tmp, diff)
                if failure is not None:
                    return failure
                proc = subprocess.run(
                    [exe, "review", "--agent", "--type", "uncommitted", "--dir", tmp],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                                data={"error": type(exc).__name__})
        return _parse(proc.stdout)


def _materialize_diff(repo_dir: str, diff: str) -> ReviewReport | None:
    """Stand up a throwaway git repo with `diff` applied as its sole uncommitted change.

    Returns a ReviewReport (short-circuiting review()) on setup/apply failure, else None.
    """
    setup = (
        ["git", "init", "-q", repo_dir],
        ["git", "-C", repo_dir, "config", "user.email", "sembl@local"],
        ["git", "-C", repo_dir, "config", "user.name", "sembl"],
        ["git", "-C", repo_dir, "commit", "-q", "--allow-empty", "-m", "base"],
    )
    for cmd in setup:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                                data={"reason": "could not stage a throwaway repo for review",
                                      "stderr": summarize(r.stderr)})

    patch_path = Path(repo_dir) / "_sembl_review.patch"
    patch_path.write_text(diff, encoding="utf-8")
    applied = subprocess.run(
        ["git", "-C", repo_dir, "apply", "--whitespace=nowarn", str(patch_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    patch_path.unlink(missing_ok=True)
    if applied.returncode != 0:
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                            data={"reason": "diff did not apply cleanly",
                                  "stderr": summarize(applied.stderr)})
    return None


def _parse(text: str | None) -> ReviewReport:
    """Map CodeRabbit JSON `{"findings":[{severity,file,message,...}]}` to a ReviewReport.

    Live-proof finding: an unauthenticated/failed run prints a `{"type":"error",...}` envelope
    to STDOUT (not stderr) with exit code 1 — e.g. `{"type":"error","phase":"auth",
    "status":"environment_unsupported","message":"..."}`. That shape has no "findings" key, so
    treating "findings" absence as CLEAN silently turned a real auth failure into a false-clean
    review. Must special-case `type == "error"` before falling through to the findings mapping.
    """
    if not text:
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Never persist raw reviewer stdout (may carry diff snippets / auth errors) — fingerprint only.
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                            data={"raw": summarize(text)})
    if isinstance(payload, dict) and payload.get("type") == "error":
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                            data={"reason": payload.get("message", "coderabbit reported an error"),
                                  "phase": payload.get("phase", ""),
                                  "error_status": payload.get("status", "")})
    raw = payload.get("findings", []) if isinstance(payload, dict) else []
    findings = [{"severity": f.get("severity", "warn"), "kind": f.get("kind", "quality"),
                 "file": f.get("file", ""), "message": f.get("message", "")}
                for f in raw if isinstance(f, dict)]
    return ReviewReport(reviewer="coderabbit",
                        status="FINDINGS" if findings else "CLEAN", findings=findings)
