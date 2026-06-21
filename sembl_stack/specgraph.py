"""Build a deterministic SpecGraph artifact from task/spec inputs.

The graph is intentionally structural and local: no model call, no repo scan, no
network. It gives the reconciliation stage a stable spec-side artifact before a
heavier spec parser exists.
"""
from __future__ import annotations

import re
from pathlib import Path

from .artifacts import Bounds, SpecGraph, Task

SCHEMA_VERSION = 1

_ROUTE_RE = re.compile(
    r"(?:route|endpoint|path)\s*[:=-]\s*(?:(GET|POST|PUT|PATCH|DELETE)\s+)?"
    r"(/[A-Za-z0-9_./{}:-]+)",
    re.IGNORECASE,
)
_ENTITY_RE = re.compile(
    r"(?:entity|model|table)\s*[:=-]\s*([A-Za-z][A-Za-z0-9_ -]{1,80})",
    re.IGNORECASE,
)
_RULE_RE = re.compile(r"\b(must|only|never|required|requires|should)\b", re.IGNORECASE)

_SPEC_FILENAMES = (
    "tasks.md",
    "spec.md",
    "plan.md",
    "requirements.md",
    "README.md",
)


def build_spec_graph(task: Task, bounds: Bounds | None = None) -> SpecGraph:
    """Build a JSON-serializable graph of declared spec intent."""
    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()

    def add_node(node_id: str, node_type: str, name: str, **attrs) -> None:
        if node_id in seen:
            return
        seen.add(node_id)
        node = {"id": node_id, "type": node_type, "name": name}
        node.update({k: v for k, v in attrs.items() if v not in (None, "", [], {})})
        nodes.append(node)

    def add_edge(src: str, dst: str, rel: str) -> None:
        edges.append({"from": src, "to": dst, "type": rel})

    add_node("task", "task", "task", text=task.text, repo=task.repo)

    sources = _read_sources(getattr(task, "spec_path", None))
    if task.text:
        sources.insert(0, ("task.text", task.text))

    for idx, (source, text) in enumerate(sources):
        source_id = f"source:{idx}"
        add_node(source_id, "source", source, path=None if source == "task.text" else source)
        add_edge("task", source_id, "declares")
        _extract_concepts(text, source_id, add_node, add_edge)

    if bounds is not None:
        for path in bounds.editable_paths:
            node_id = f"scope:editable:{path}"
            add_node(node_id, "editable_path", path)
            add_edge("task", node_id, "allows")
        for path in bounds.forbidden_areas:
            node_id = f"scope:forbidden:{path}"
            add_node(node_id, "forbidden_area", path)
            add_edge("task", node_id, "forbids")

    return SpecGraph(
        nodes=nodes,
        edges=edges,
        sources=[source for source, _ in sources],
        data={"schema_version": SCHEMA_VERSION},
    )


def _read_sources(spec_path: str | None) -> list[tuple[str, str]]:
    if not spec_path:
        return []
    root = Path(spec_path)
    if root.is_file():
        return [(str(root), _read_text(root))]
    if not root.is_dir():
        return []

    paths: list[Path] = []
    for name in _SPEC_FILENAMES:
        p = root / name
        if p.is_file():
            paths.append(p)
    for p in sorted(root.glob("*.md")):
        if p not in paths:
            paths.append(p)
    return [(str(p), _read_text(p)) for p in paths]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _extract_concepts(text: str, source_id: str, add_node, add_edge) -> None:
    for match in _ROUTE_RE.finditer(text):
        method, route = match.groups()
        route = _clean_route(route)
        method = (method or "ANY").upper()
        node_id = f"route:{method}:{route}"
        add_node(node_id, "route", route, method=method)
        add_edge(source_id, node_id, "mentions")

    for match in _ENTITY_RE.finditer(text):
        entity = _clean_label(match.group(1))
        if not entity:
            continue
        node_id = f"entity:{_slug(entity)}"
        add_node(node_id, "entity", entity)
        add_edge(source_id, node_id, "mentions")

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip(" -*\t")
        if not stripped or not _RULE_RE.search(stripped):
            continue
        node_id = f"rule:{source_id}:{line_no}"
        add_node(node_id, "data_rule", stripped, line=line_no)
        add_edge(source_id, node_id, "declares")


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .:-")


def _clean_route(value: str) -> str:
    return value.rstrip(".,;:)")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unnamed"
