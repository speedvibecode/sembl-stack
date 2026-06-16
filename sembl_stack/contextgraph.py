"""L1 Context: a swappable semantic code graph + graph-based bounds expansion.

Two contender tools (both local, deterministic, MIT) sit behind one protocol:
  * symgraph  (Rust; tree-sitter + SQLite; `--format json`; has a file-level module
    dependency graph) — the default.
  * codegraph (Node; tree-sitter + SQLite/FTS5) — a second adapter (TODO).

The capability the gate actually needs is **bounds expansion**: given the seed paths a
spec/issue names, add the files they are genuinely coupled to (the dependency closure),
so a legitimate multi-file change does not false-alarm the scope check. EXP-04 showed the
scope check over-fires precisely because a real fix touches sibling modules the spec never
named; the coupling graph recovers exactly those. (It does NOT recover changelog/docs/test
files — those are not code edges and are handled by the separate docs-auto-in-scope rule.)

`expand_paths()` is a pure function over a file graph, so it is unit-testable without the
binary; the adapter only has to produce the graph.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class FileGraph:
    """A directed file-dependency graph: edge from -> to means `from` uses `to`."""
    nodes: list[str] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)   # {"from","to","strength",...}

    def neighbors(self, path: str, min_strength: int = 0) -> set[str]:
        """Files directly coupled to `path` in EITHER direction (callers + callees)."""
        out: set[str] = set()
        for e in self.edges:
            if e.get("strength", 1) < min_strength:
                continue
            if e["from"] == path:
                out.add(e["to"])
            elif e["to"] == path:
                out.add(e["from"])
        return out


class ContextGraph(Protocol):
    def available(self) -> bool: ...
    def index(self, repo: str) -> None: ...
    def file_graph(self, repo: str) -> FileGraph: ...


# --- helpers ------------------------------------------------------------------

def _norm(p: str) -> str:
    return p.replace("\\", "/").strip().lstrip("./")


def expand_paths(seed: list[str], graph: FileGraph, *, hops: int = 1,
                 min_strength: int = 0, max_fraction: float = 0.4) -> list[str]:
    """Grow a seed set of files along the coupling graph, up to `hops` away.

    Returns the union of the seed and every file reachable within `hops` edges of any seed
    file (whose coupling strength clears `min_strength`). Deterministic; the seed is always
    included even if it has no edges.

    Defaults are deliberately conservative (EXP-05): `hops=1` keeps the closure tight
    (~10-22% of a real repo) while still recovering a third to a half of the legitimate
    sibling files; two hops balloons to ~the whole repo and destroys the gate. The
    `max_fraction` cap is the safety net for small, densely-cyclic repos (e.g. flask) where
    even one hop engulfs the codebase: if the closure would exceed `max_fraction` of the
    indexed files, expansion is **abandoned and the bare seed is returned** — better a
    noisier scope check than a gate that silently whitelists everything.
    """
    seed_n = {_norm(p) for p in seed if p}
    g = FileGraph(
        nodes=[_norm(n) for n in graph.nodes],
        edges=[{**e, "from": _norm(e["from"]), "to": _norm(e["to"])} for e in graph.edges],
    )
    frontier = set(seed_n)
    seen = set(seed_n)
    for _ in range(max(0, hops)):
        nxt: set[str] = set()
        for f in frontier:
            nxt |= g.neighbors(f, min_strength)
        nxt -= seen
        if not nxt:
            break
        seen |= nxt
        frontier = nxt
    if g.nodes and len(seen) > max_fraction * len(g.nodes):
        return sorted(seed_n)   # too dense to be informative — don't whitelist the repo
    return sorted(seen)


def _under(path: str, prefix: str) -> bool:
    path, prefix = _norm(path), _norm(prefix).rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def expand_bounds(editable_paths: list[str], graph: FileGraph, *, hops: int = 1,
                  min_strength: int = 0, max_fraction: float = 0.4) -> list[str]:
    """Expand a bounds `editable_paths` list along the coupling graph (EXP-05).

    Each declared path (file or directory prefix) seeds the indexed files it covers; those
    are grown one hop (by default) into their coupling closure. The ORIGINAL entries are
    always preserved (so directory bounds keep working even if no file under them is
    indexed); the recovered sibling FILES are added. Returns a de-duplicated, sorted list.
    """
    seed_files = [n for n in graph.nodes
                  if any(_under(n, p) for p in editable_paths)]
    if not seed_files:
        return sorted({_norm(p) for p in editable_paths})
    grown = expand_paths(seed_files, graph, hops=hops, min_strength=min_strength,
                         max_fraction=max_fraction)
    return sorted({_norm(p) for p in editable_paths} | set(grown))


# --- symgraph adapter ---------------------------------------------------------

class SymgraphGraph:
    """Drives the `symgraph` Rust binary. Index once, then read the file module-graph."""

    def __init__(self, binary: str = "symgraph", timeout: int = 300):
        self.binary = binary
        self.timeout = timeout

    def _exe(self) -> str | None:
        return shutil.which(self.binary)

    def available(self) -> bool:
        return self._exe() is not None

    def _run(self, args: list[str], repo: str) -> subprocess.CompletedProcess:
        exe = self._exe()
        if not exe:
            raise RuntimeError(
                f"L1: `{self.binary}` not found on PATH. Install it, or disable graph expansion.")
        return subprocess.run([exe, *args], cwd=repo, capture_output=True,
                              text=True, timeout=self.timeout)

    def index(self, repo: str) -> None:
        self._run(["index", "."], repo)

    def file_graph(self, repo: str) -> FileGraph:
        proc = self._run(
            ["module-graph", "--granularity", "file", "--format", "json"], repo)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return FileGraph()
        return FileGraph(
            nodes=[n["id"] for n in data.get("nodes", [])],
            edges=data.get("edges", []),
        )
