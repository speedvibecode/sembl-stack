import json

import pytest
from click.testing import CliRunner

from sembl_stack.adapters.codegraph_cbm import CbmCodeGraph, _parse_json
from sembl_stack.artifacts import SpecGraph
from sembl_stack.cli import main


def _cbm_stub(results, slug="C-Users-x-repo", root="/x/repo"):
    """Fake subprocess.run keyed by the CBM tool name (cmd = [exe, 'cli', <tool>, <json>])."""
    from types import SimpleNamespace

    def run(cmd, **kwargs):
        tool = cmd[2]
        if tool == "index_repository":
            out = {"ok": True}
        elif tool == "list_projects":
            out = {"projects": [{"name": slug, "root_path": root, "nodes": len(results)}]}
        elif tool == "search_graph":
            out = {"total": len(results), "results": results, "has_more": False}
        else:
            out = {}
        # CBM prefixes a log line before the JSON — exercise the robust parser.
        return SimpleNamespace(returncode=0, stdout="level=info msg=mem.init\n" + json.dumps(out),
                               stderr="")
    return run


def test_parse_json_tolerates_log_prefix():
    assert _parse_json('level=info msg=mem.init\n{"a": 1}') == {"a": 1}
    assert _parse_json("not json at all") == {}
    assert _parse_json("") == {}


def test_code_graph_resolves_slug_and_returns_results(monkeypatch, tmp_path):
    results = [{"name": "FeedbackItem", "file_path": "src/models/feedback_item.ts"}]
    root = str(tmp_path).replace("\\", "/")
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.shutil.which",
                        lambda b: "cbm.exe")
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.subprocess.run",
                        _cbm_stub(results, slug="proj-slug", root=root))

    graph = CbmCodeGraph().code_graph(str(tmp_path))

    assert graph["results"] == results


def test_code_graph_empty_when_project_not_indexed(monkeypatch, tmp_path):
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.shutil.which",
                        lambda b: "cbm.exe")
    # list_projects reports a DIFFERENT root than the repo -> no slug -> {}
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.subprocess.run",
                        _cbm_stub([{"name": "X"}], root="/some/other/repo"))

    assert CbmCodeGraph().code_graph(str(tmp_path)) == {}


def test_code_graph_empty_when_binary_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.shutil.which", lambda b: None)
    cg = CbmCodeGraph()
    assert cg.available() is False
    assert cg.code_graph(str(tmp_path)) == {}


def test_reconcile_cli_live_builds_report(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sembl_stack.adapters.codegraph_cbm.CbmCodeGraph.available",
        lambda self: True)
    monkeypatch.setattr(
        "sembl_stack.adapters.codegraph_cbm.CbmCodeGraph.code_graph",
        lambda self, repo, **kw: {"results": [
            {"name": "FeedbackItem", "file_path": "src/models/feedback_item.ts"}]})

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(SpecGraph(nodes=[
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback_item"},
    ]).to_json(), encoding="utf-8")
    out_path = tmp_path / "report.json"

    result = CliRunner().invoke(main, [
        "reconcile", "--specgraph", str(spec_path), "--live",
        "--repo", str(tmp_path), "--out", str(out_path),
    ])

    assert result.exit_code == 0, result.output
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["status"] == "ALIGNED"


def test_reconcile_cli_requires_a_source(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(SpecGraph(nodes=[]).to_json(), encoding="utf-8")
    result = CliRunner().invoke(main, ["reconcile", "--specgraph", str(spec_path)])
    assert result.exit_code != 0
    assert "supply --codegraph" in result.output


@pytest.mark.skipif(
    __import__("shutil").which("codebase-memory-mcp") is None,
    reason="codebase-memory-mcp not installed")
def test_cbm_available_when_installed():
    assert CbmCodeGraph().available()


def test_index_payload_uses_repo_path_contract(monkeypatch, tmp_path):
    # CBM's index_repository REQUIRES `repo_path`; sending `path` silently no-ops the
    # live index and reconcile degrades to UNKNOWN (codex audit finding 7).
    captured = {}

    def run(cmd, **kwargs):
        from types import SimpleNamespace
        captured.setdefault(cmd[2], json.loads(cmd[3]))
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.shutil.which",
                        lambda b: "cbm.exe")
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.subprocess.run", run)
    CbmCodeGraph().code_graph(str(tmp_path))

    payload = captured["index_repository"]
    assert "repo_path" in payload and "path" not in payload
    assert payload["mode"] == "fast"
