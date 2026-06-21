"""L5.5 CodeRabbit review shell — PROVISIONAL until the 14-day trial opens.

Drives the `coderabbit` CLI as a subprocess (never a package dep). The exact subcommand/flags
and JSON shape are unverified (no account yet) and will be finalized on day 1 of the trial; this
shell is tested ONLY against a mock. Advisory: any failure returns an UNKNOWN ReviewReport.
"""
from __future__ import annotations

import json
import shutil
import subprocess

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
            proc = subprocess.run(
                [exe, "review", "--plain", "--stdin"], input=diff,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                                data={"error": type(exc).__name__})
        return _parse(proc.stdout)


def _parse(text: str | None) -> ReviewReport:
    """Map CodeRabbit JSON `{"findings":[{severity,file,message,...}]}` to a ReviewReport."""
    if not text:
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Never persist raw reviewer stdout (may carry diff snippets / auth errors) — fingerprint only.
        return ReviewReport(reviewer="coderabbit", status="UNKNOWN",
                            data={"raw": summarize(text)})
    raw = payload.get("findings", []) if isinstance(payload, dict) else []
    findings = [{"severity": f.get("severity", "warn"), "kind": f.get("kind", "quality"),
                 "file": f.get("file", ""), "message": f.get("message", "")}
                for f in raw if isinstance(f, dict)]
    return ReviewReport(reviewer="coderabbit",
                        status="FINDINGS" if findings else "CLEAN", findings=findings)
