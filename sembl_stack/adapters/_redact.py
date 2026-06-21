"""Redaction helper for adapter artifacts.

Third-party process output (HTTP health bodies, CLI stdout/stderr, reviewer output) can carry
debug pages, stack traces, env-shaped values, diff snippets, or auth errors. Persisting it raw
into `.sembl/runs/<id>/` would violate the no-secrets-in-artifacts invariant. We keep only a
non-reversible fingerprint: byte count + sha256. That preserves "output existed / did it change"
signal without ever serializing the content.
"""
from __future__ import annotations

import hashlib


def summarize(text) -> dict:
    """Reduce arbitrary third-party text to {bytes, sha256} — never the content itself."""
    if text is None:
        return {"bytes": 0, "sha256": None}
    raw = text if isinstance(text, bytes) else str(text).encode("utf-8", "replace")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
