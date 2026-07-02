"""L5.5 code-graph source — drive codebase-memory-mcp (CBM) headlessly.

reconcile (S9) compares a SpecGraph against a code graph. Previously the code graph was a
hand-passed JSON file; this adapter produces it LIVE from a real CBM index so a per-PR reconcile
needs no manual step. CBM is driven via its single-shot CLI (`cbm cli <tool> <json-args>`) — the
same subprocess containment as the symgraph adapter, never a package dependency. Advisory only: a
failure returns an empty graph (reconcile then reports UNKNOWN), never an exception that could be
mistaken for a gate.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class CbmCodeGraph:
    """Drives the codebase-memory-mcp binary to export a code graph for reconciliation."""

    def __init__(self, binary: str = "codebase-memory-mcp", timeout: int = 600,
                 limit: int = 5000):
        self.binary = binary
        self.timeout = timeout
        self.limit = limit

    def _exe(self) -> str | None:
        return shutil.which(self.binary)

    def available(self) -> bool:
        return self._exe() is not None

    def _run(self, tool: str, payload: dict) -> dict:
        exe = self._exe()
        if not exe:
            return {}
        try:
            proc = subprocess.run(
                [exe, "cli", tool, json.dumps(payload)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return {}
        return _parse_json(proc.stdout)

    def _project_slug(self, repo: str) -> str | None:
        target = _norm(str(Path(repo).resolve()))
        listing = self._run("list_projects", {})
        for proj in listing.get("projects", []):
            if _norm(proj.get("root_path", "")) == target and proj.get("name"):
                return proj["name"]
        return None

    def code_graph(self, repo: str, *, index: bool = True) -> dict:
        """Return a CBM code-graph payload `{"results":[...]}` reconcile can consume.

        Indexes the repo (idempotent refresh), resolves the project slug via CBM's own
        list_projects mapping, then pulls every node with a broad pattern. Returns `{}` on any
        failure — reconcile degrades to UNKNOWN, never blocks.
        """
        if index:
            # CBM's tool contract requires `repo_path` (`path` is silently rejected);
            # `mode: fast` skips similarity/semantic edges — reconcile only needs symbols.
            self._run("index_repository",
                      {"repo_path": str(Path(repo).resolve()), "mode": "fast"})
        slug = self._project_slug(repo)
        if not slug:
            return {}
        return self._run(
            "search_graph",
            {"project": slug, "name_pattern": ".", "limit": self.limit})


def _norm(p: str) -> str:
    return p.replace("\\", "/").strip().rstrip("/").lower()


def _parse_json(text: str | None) -> dict:
    """Parse CBM stdout, tolerating a leading `level=info ...` log line."""
    if not text:
        return {}
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out = json.loads(line)
                return out if isinstance(out, dict) else {}
            except json.JSONDecodeError:
                continue
    return {}
