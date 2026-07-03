"""L5.5 CodeRabbit review shell — LIVE-PROVEN 2026-07-03 against a real authenticated review
(CLI v0.6.4, Pro+ seat; CodeRabbit fixed their backend auth bug after our report). The real
`--agent` output is an NDJSON event stream, and the CLI requires an explicit `--base` branch —
both discovered live and handled below. Any auth/subprocess failure returns an UNKNOWN
ReviewReport (advisory, never blocks).

Contract note: the real CLI has NO stdin/diff-text input — it only reviews git working-tree
state (`--dir`, `--base`, `-t/--type all|committed|uncommitted`), unlike the original
provisional `--stdin` design. To keep the `ReviewAdapter.review(diff: str)` protocol uniform
across mock/real (and keep the diff-corpus 2x2 eval git-free), this materializes the diff into
a throwaway git repo (empty base commit + `git apply`) so `coderabbit review --agent --type
uncommitted --dir <tmp>` has something to diff.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ._redact import summarize
from .base import ReviewReport

# The throwaway repo's branch name; also passed as `--base` (the CLI requires one).
_BASE_BRANCH = "sembl-review-base"


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
                    [exe, "review", "--agent", "--type", "uncommitted", "--dir", tmp,
                     "--base", _BASE_BRANCH],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                                data={"error": type(exc).__name__})
        return _parse(proc.stdout)


def _materialize_diff(repo_dir: str, diff: str) -> ReviewReport | None:
    """Stand up a throwaway git repo with `diff` applied as its sole uncommitted change.

    Live-proof finding (real 2x2 run): diffs that MODIFY existing files cannot `git apply`
    against an empty base commit — only greenfield (new-file) diffs applied, silently turning
    most of the corpus into UNKNOWNs. So the base commit first synthesizes each touched file's
    pre-image from the diff's own hunks (context + removed lines at their stated offsets,
    blank-padded in between) — exactly the lines `git apply` verifies.

    Returns a ReviewReport (short-circuiting review()) on setup/apply failure, else None.
    """
    _synthesize_bases(repo_dir, diff)
    setup = (
        # Live-proof finding: the real CLI refuses to review without a resolvable base branch
        # ("Unable to determine base branch ... pass --base"), so the throwaway repo pins its
        # branch name and review() passes it explicitly.
        ["git", "init", "-q", "-b", _BASE_BRANCH, repo_dir],
        ["git", "-C", repo_dir, "config", "user.email", "sembl@local"],
        ["git", "-C", repo_dir, "config", "user.name", "sembl"],
        ["git", "-C", repo_dir, "add", "-A"],
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


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


def _synthesize_bases(repo_dir: str, diff: str) -> None:
    """Write a minimal pre-image for every existing file the diff touches.

    A unified diff carries each hunk's old lines (context ``' '`` + removals ``'-'``) and their
    1-based start offset; lines between/before hunks are unknown, so they're blank-padded —
    `git apply` only verifies the hunk lines themselves. New files (old side ``/dev/null``)
    are skipped.
    """
    files: dict[str, list[tuple[int, list[str]]]] = {}
    cur: str | None = None
    remaining = 0
    for line in diff.splitlines():
        if line.startswith("--- "):
            old = line[4:].split("\t")[0].strip()
            cur = None if old in ("/dev/null", "dev/null") else (
                old[2:] if old.startswith("a/") else old)
            remaining = 0
        elif line.startswith("@@") and cur is not None:
            m = _HUNK.match(line)
            if m:
                remaining = int(m.group(2)) if m.group(2) is not None else 1
                files.setdefault(cur, []).append((int(m.group(1)), []))
        elif remaining > 0 and cur is not None:
            if line.startswith("\\"):          # "\ No newline at end of file"
                continue
            if line == "" or line[0] in (" ", "-"):
                files[cur][-1][1].append(line[1:] if line else "")
                remaining -= 1
    for path, hunks in files.items():
        lines: list[str] = []
        for start, old_lines in sorted(hunks):
            while len(lines) < start - 1:
                lines.append("")
            lines.extend(old_lines)
        target = Path(repo_dir) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse(text: str | None) -> ReviewReport:
    """Map CodeRabbit `--agent` output to a ReviewReport.

    Live-proof finding (real authenticated run, CLI v0.6.4): `--agent` streams NDJSON events —
    one JSON object per line: `review_context` / `status` lines, then zero or more
    `{"type":"finding","severity":...,"fileName":...,"codegenInstructions":...}` lines, then
    `{"type":"complete","status":"review_completed","findings":N}`. There is NO single
    `{"findings":[...]}` document (that provisional shape is kept for back-compat only).

    Earlier live-proof finding still holds: a failed run prints a `{"type":"error",...}`
    envelope to STDOUT (not stderr) — must be UNKNOWN, never false-clean. Likewise a stream
    with no `complete` event is UNKNOWN (truncated review), not CLEAN.
    """
    if not text:
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _parse_stream(text)
    if isinstance(payload, dict) and payload.get("type") == "error":
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                            data={"reason": payload.get("message", "coderabbit reported an error"),
                                  "phase": payload.get("phase", ""),
                                  "error_status": payload.get("status", "")})
    if isinstance(payload, dict) and "type" in payload and "findings" not in payload:
        # A lone stream event (e.g. one status line) — not a findings document; route it
        # through the stream parser so a truncated one-line stream can't read as CLEAN.
        return _parse_stream(text)
    raw = payload.get("findings", []) if isinstance(payload, dict) else []
    findings = [{"severity": f.get("severity", "warn"), "kind": f.get("kind", "quality"),
                 "file": f.get("file", ""), "message": f.get("message", "")}
                for f in raw if isinstance(f, dict)]
    return ReviewReport(reviewer="coderabbit",
                        status="FINDINGS" if findings else "CLEAN", findings=findings)


def _parse_stream(text: str) -> ReviewReport:
    """Parse the real `--agent` NDJSON event stream (one JSON object per line)."""
    findings: list[dict] = []
    complete = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            # Never persist raw reviewer stdout (may carry diff snippets / auth errors) —
            # fingerprint only.
            return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                                data={"raw": summarize(text)})
        if not isinstance(evt, dict):
            continue
        kind = evt.get("type")
        if kind == "error":
            return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                                data={"reason": evt.get("message", "coderabbit reported an error"),
                                      "phase": evt.get("phase", ""),
                                      "error_status": evt.get("status", "")})
        if kind == "finding":
            findings.append({"severity": evt.get("severity", "warn"), "kind": "quality",
                             "file": evt.get("fileName", ""),
                             "message": str(evt.get("codegenInstructions", ""))[:1000]})
        elif kind == "complete":
            complete = True
    if findings:
        return ReviewReport(reviewer="coderabbit", status="FINDINGS", findings=findings)
    if complete:
        return ReviewReport(reviewer="coderabbit", status="CLEAN")
    # No findings AND no completion marker: a cut-off stream must not read as clean.
    return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                        data={"reason": "review stream ended without a complete event"})
