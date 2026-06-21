import json

from click.testing import CliRunner

from sembl_stack.artifacts import SpecGraph
from sembl_stack.cli import main
from sembl_stack.reconciliation import reconcile_spec_code


def test_reconcile_reports_aligned_when_spec_concepts_are_in_code_graph():
    spec = SpecGraph(nodes=[
        {"id": "route:POST:/api/feedback", "type": "route", "name": "/api/feedback"},
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback_item"},
    ])
    code = {"nodes": [
        {"name": "FeedbackItem", "file_path": "src/models/feedback_item.ts"},
        {"name": "createFeedback", "route": "/api/feedback"},
    ]}

    report = reconcile_spec_code(spec, code)

    assert report.status == "ALIGNED"
    assert report.findings == []


def test_reconcile_reports_divergent_for_missing_spec_concept():
    spec = SpecGraph(nodes=[
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback_item"},
    ])
    code = {"nodes": [{"name": "User", "file_path": "src/user.ts"}]}

    report = reconcile_spec_code(spec, code)

    assert report.status == "DIVERGENT"
    assert report.findings[0]["kind"] == "spec_concept_without_code_match"


def test_reconcile_reports_unknown_without_code_graph_nodes():
    report = reconcile_spec_code(SpecGraph(nodes=[]), {})

    assert report.status == "UNKNOWN"
    assert report.findings[0]["kind"] == "missing_code_graph"


def test_reconcile_live_is_advisory_when_codegraph_unavailable(monkeypatch, tmp_path):
    """--live must never gate: a missing/failed code graph -> UNKNOWN report at exit 0."""
    # Force the configured codegraph adapter to look unavailable / degrade to an empty graph.
    monkeypatch.setattr(
        "sembl_stack.adapters.codegraph_cbm.CbmCodeGraph.code_graph",
        lambda self, repo: {})

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(SpecGraph(nodes=[{"id": "e:x", "type": "entity", "name": "x"}]).to_json(),
                         encoding="utf-8")
    out_path = tmp_path / "report.json"

    result = CliRunner().invoke(main, [
        "reconcile", "--specgraph", str(spec_path), "--live", "--repo", str(tmp_path),
        "--out", str(out_path),
    ])

    assert result.exit_code == 0                      # advisory: never a non-zero gate
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["status"] == "UNKNOWN"
