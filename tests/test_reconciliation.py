from sembl_stack.artifacts import SpecGraph
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
