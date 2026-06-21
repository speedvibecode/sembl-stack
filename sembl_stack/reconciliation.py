"""Advisory SpecGraph-to-code-graph reconciliation.

This is not a gate. It gives a human a compact drift report from two already
materialized graphs. The code graph is supplied as JSON so the current stage can
consume codebase-memory-mcp output without making that MCP a package dependency.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from .artifacts import ReconciliationReport, SpecGraph


def reconcile_spec_code(spec_graph: SpecGraph, code_graph: dict) -> ReconciliationReport:
    """Compare declared spec concepts against a supplied code graph JSON payload."""
    spec_concepts = _spec_concepts(spec_graph)
    code_terms, code_files = _code_terms(code_graph)

    findings: list[dict] = []
    if not code_terms and not code_files:
        return ReconciliationReport(
            status="UNKNOWN",
            summary="code graph had no comparable nodes or files",
            findings=[{
                "severity": "info",
                "kind": "missing_code_graph",
                "message": "No code graph concepts were supplied for reconciliation.",
            }],
            data=_counts(spec_graph, code_graph),
        )

    for concept in spec_concepts:
        if concept["type"] in ("editable_path", "forbidden_area"):
            if concept["type"] == "editable_path" and not _path_covered(
                    concept["name"], code_files):
                findings.append({
                    "severity": "info",
                    "kind": "scope_without_code_match",
                    "spec_node": concept["id"],
                    "message": f"Editable path not present in code graph: {concept['name']}",
                })
            continue

        if not _term_covered(concept["name"], code_terms):
            findings.append({
                "severity": "warn",
                "kind": "spec_concept_without_code_match",
                "spec_node": concept["id"],
                "concept_type": concept["type"],
                "message": f"Spec concept not found in code graph: {concept['name']}",
            })

    status = "DIVERGENT" if any(f["severity"] == "warn" for f in findings) else "ALIGNED"
    summary = (
        "spec/code divergence found"
        if status == "DIVERGENT"
        else "spec concepts are represented in the supplied code graph"
    )
    return ReconciliationReport(
        status=status,
        summary=summary,
        findings=findings,
        data=_counts(spec_graph, code_graph),
    )


def _spec_concepts(spec_graph: SpecGraph) -> list[dict]:
    keep = {"route", "entity", "data_rule", "editable_path", "forbidden_area"}
    return [
        {"id": n.get("id", ""), "type": n.get("type", ""), "name": n.get("name", "")}
        for n in spec_graph.nodes
        if n.get("type") in keep and n.get("name")
    ]


def _code_terms(code_graph: dict) -> tuple[set[str], set[str]]:
    nodes = _nodes_from_payload(code_graph)
    terms: set[str] = set()
    files: set[str] = set()
    for node in nodes:
        for key in ("name", "qualified_name", "label", "route", "path"):
            value = node.get(key)
            if isinstance(value, str):
                terms.update(_tokens(value))
        for key in ("file", "file_path", "path"):
            value = node.get(key)
            if isinstance(value, str):
                files.add(_norm_path(value))
                terms.update(_tokens(value))
    return terms, files


def _nodes_from_payload(payload) -> list[dict]:
    if isinstance(payload, list):
        return [n for n in payload if isinstance(n, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("nodes"), list):
        return [n for n in payload["nodes"] if isinstance(n, dict)]
    if isinstance(payload.get("results"), list):
        return [n for n in payload["results"] if isinstance(n, dict)]
    return []


def _term_covered(name: str, code_terms: set[str]) -> bool:
    tokens = _tokens(name)
    return bool(tokens) and all(token in code_terms for token in tokens)


def _path_covered(path: str, code_files: set[str]) -> bool:
    needle = _norm_path(path)
    if not needle:
        return True
    if needle.endswith("/"):
        return any(p.startswith(needle) for p in code_files)
    return needle in code_files or any(PurePosixPath(p).match(needle) for p in code_files)


def _tokens(value: str) -> set[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return {
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if token and token not in {"api", "src", "app", "py", "ts", "tsx", "js", "jsx"}
    }


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("./")


def _counts(spec_graph: SpecGraph, code_graph: dict) -> dict:
    return {
        "spec_nodes": len(spec_graph.nodes),
        "spec_edges": len(spec_graph.edges),
        "code_nodes": len(_nodes_from_payload(code_graph)),
    }
