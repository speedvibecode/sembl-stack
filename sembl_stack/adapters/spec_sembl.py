"""L2 spec adapter (ours): derive bounds from a spec, via Sembl.

MCP-first (`bounds_from_spec`), with a `sembl bounds` CLI fallback. If neither the
MCP server nor the CLI is reachable, falls back to a hand-written bounds.json next to
the task.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .base import Bounds, Task
from ..transport import mcp_client


def _extract_json(text: str) -> dict | None:
    """Pull a trailing JSON object out of CLI output that may be prefixed by a panel."""
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None


class SemblSpecAdapter:
    def __init__(self, transport: str = "mcp", mcp_server: list[str] | None = None):
        self.transport = transport
        self.mcp_server = mcp_server or ["uvx", "--from", "sembl[mcp]", "sembl-mcp"]

    def plan(self, task: Task) -> Bounds:
        spec = task.spec_path
        # 1) MCP path
        if self.transport == "mcp" and spec and mcp_client.available():
            try:
                out = mcp_client.call_tool(
                    self.mcp_server, "bounds_from_spec",
                    {"tasks_path": str(Path(spec).resolve()), "repo_path": task.repo},
                )
                bnds = self._from_payload(out)
                if bnds.editable_paths:
                    return bnds
            except Exception:
                pass
        # 2) CLI fallback (the CLI prints a panel then the JSON — extract the JSON)
        if spec:
            try:
                # Invoke via the running interpreter (`python -m sembl.cli`) rather than a
                # bare `sembl` on PATH — the shared venv has sembl installed but its Scripts
                # dir may not be on PATH, which made this fallback raise FileNotFoundError.
                proc = subprocess.run(
                    [sys.executable, "-m", "sembl.cli", "bounds",
                     "--spec-kit", spec, "--repo", task.repo],
                    capture_output=True, text=True, cwd=task.repo, timeout=120,
                )
                payload = _extract_json(proc.stdout)
                if payload is not None:
                    bnds = self._from_payload(payload)
                    if bnds.editable_paths:
                        return bnds
            except Exception:
                pass
        # 3) hand-written bounds.json beside the spec / task / repo. This is also the
        #    deliberate fallback when derivation yields NO editable_paths: a greenfield
        #    "create these files" spec names paths that don't exist in the repo yet, so the
        #    repo-tree-validated extractor drops them — an empty contract a strict gate
        #    would read as "everything is out of scope". An author-written bounds.json is
        #    the precise seed for exactly that case.
        candidates = []
        if spec:
            candidates += [Path(spec) / "bounds.json", Path(spec).parent / "bounds.json"]
        candidates.append(Path(task.repo) / "bounds.json")
        for cand in candidates:
            if cand.is_file():
                return self._from_payload(json.loads(cand.read_text(encoding="utf-8")))
        raise RuntimeError("L2: could not derive bounds (no MCP, no CLI, no bounds.json)")

    @staticmethod
    def _from_payload(payload: dict) -> Bounds:
        bounds = payload.get("bounds", payload)
        return Bounds(
            editable_paths=bounds.get("editable_paths", []),
            forbidden_areas=bounds.get("forbidden_areas", []),
            churn_budget=bounds.get("churn_budget", {}),
            sources=payload.get("sources", []),
        )
