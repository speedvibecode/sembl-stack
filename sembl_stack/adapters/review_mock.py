"""Deterministic mock code-quality reviewer (L5.5) — the stand-in for CodeRabbit until the
trial opens. Signature-based: it flags a couple of well-known antipatterns in added (`+`) diff
lines. Advisory only; it never blocks. Good enough to prove the 2×2 (quality vs process axis)."""
from __future__ import annotations

import re

from .base import ReviewReport

_LOOP = re.compile(r"\bfor\s*\(|\bwhile\s*\(|\.map\(|\.forEach\(", re.I)
_QUERY = re.compile(r"db\.\w+\(|\.query\(|\.find\(|\bSELECT\b|\bfetch\(", re.I)
_UNSAFE = re.compile(r"\beval\(|innerHTML\s*=|dangerouslySetInnerHTML", re.I)


class MockReviewAdapter:
    def review(self, diff: str, *, reviewer_hint: str = "") -> ReviewReport:
        # Collect ADDED ('+') lines per file (N+1 is a file-level, not line-level, signal).
        per_file: dict[str, list[str]] = {}
        cur = ""
        for line in diff.splitlines():
            if line.startswith("+++ "):
                cur = line[4:]
                if cur.startswith("b/"):
                    cur = cur[2:]
                cur = cur.split("\t", 1)[0].strip()
                per_file.setdefault(cur, [])
                continue
            if line.startswith("+") and not line.startswith("+++"):
                per_file.setdefault(cur, []).append(line[1:])

        findings: list[dict] = []
        for f, lines in per_file.items():
            blob = "\n".join(lines)
            if _LOOP.search(blob) and _QUERY.search(blob):
                findings.append({"severity": "warn", "kind": "n_plus_one", "file": f,
                                 "message": "query/db call inside a loop (possible N+1)"})
            for ln in lines:
                if _UNSAFE.search(ln):
                    findings.append({"severity": "error", "kind": "unsafe_input", "file": f,
                                     "message": f"unsafe input sink: {ln.strip()[:80]}"})
        status = "FINDINGS" if findings else "CLEAN"
        return ReviewReport(reviewer="mock", status=status, findings=findings)
