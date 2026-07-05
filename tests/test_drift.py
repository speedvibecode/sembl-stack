import json

from click.testing import CliRunner

from sembl_stack import drift
from sembl_stack.artifacts import SpecGraph
from sembl_stack.cli import main

_UNRELATED_CODE_GRAPH = {"results": [{"name": "Something", "file_path": "src/something.ts"}]}


def _one_concept_spec() -> SpecGraph:
    return SpecGraph(nodes=[
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback item"},
    ])


def _two_concept_spec() -> SpecGraph:
    return SpecGraph(nodes=[
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback item"},
        {"id": "entity:vote", "type": "entity", "name": "vote"},
    ])


def test_check_drift_flags_new_and_persists_state(tmp_path):
    state_path = tmp_path / "drift-state.json"

    result = drift.check_drift(_one_concept_spec(), _UNRELATED_CODE_GRAPH, state_path=state_path)

    assert len(result.new) == 1
    assert result.new[0]["kind"] == "spec_concept_without_code_match"
    assert result.pending == result.new
    assert result.resolved == []
    assert state_path.is_file()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["findings"]) == 1


def test_check_drift_does_not_reflag_acknowledged(tmp_path):
    state_path = tmp_path / "drift-state.json"
    spec = _two_concept_spec()

    first = drift.check_drift(spec, _UNRELATED_CODE_GRAPH, state_path=state_path)
    assert len(first.new) == 2
    acked = drift.acknowledge_drift(state_path=state_path)
    assert acked == 2

    second = drift.check_drift(spec, _UNRELATED_CODE_GRAPH, state_path=state_path)
    assert second.new == []
    assert second.pending == []


def test_check_drift_clears_resolved_findings(tmp_path):
    state_path = tmp_path / "drift-state.json"
    spec = _two_concept_spec()

    drift.check_drift(spec, _UNRELATED_CODE_GRAPH, state_path=state_path)
    matching_code_graph = {"results": [
        {"name": "FeedbackItem", "file_path": "a.ts"},
        {"name": "Vote", "file_path": "b.ts"},
    ]}
    resolved_now = drift.check_drift(spec, matching_code_graph, state_path=state_path)

    assert len(resolved_now.resolved) == 2
    assert resolved_now.new == []
    assert drift.pending_drift(state_path=state_path) == []


def test_pending_and_acknowledge_are_scoped_by_key(tmp_path):
    state_path = tmp_path / "drift-state.json"
    drift.check_drift(_two_concept_spec(), _UNRELATED_CODE_GRAPH, state_path=state_path)

    pending = drift.pending_drift(state_path=state_path)
    assert len(pending) == 2

    keys = [drift.finding_key(pending[0])]
    acked = drift.acknowledge_drift(keys, state_path=state_path)
    assert acked == 1
    assert len(drift.pending_drift(state_path=state_path)) == 1


def test_acknowledge_unknown_key_is_a_noop(tmp_path):
    state_path = tmp_path / "drift-state.json"
    drift.check_drift(_one_concept_spec(), _UNRELATED_CODE_GRAPH, state_path=state_path)

    acked = drift.acknowledge_drift(["not-a-real-key"], state_path=state_path)
    assert acked == 0
    assert len(drift.pending_drift(state_path=state_path)) == 1


def test_drift_check_cli_writes_state_and_reports_new(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sembl_stack.adapters.codegraph_cbm.CbmCodeGraph.available", lambda self: True)
    monkeypatch.setattr(
        "sembl_stack.adapters.codegraph_cbm.CbmCodeGraph.code_graph",
        lambda self, repo, **kw: _UNRELATED_CODE_GRAPH)

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(_two_concept_spec().to_json(), encoding="utf-8")
    state_path = tmp_path / "drift-state.json"

    result = CliRunner().invoke(main, [
        "drift-check", "--specgraph", str(spec_path), "--live",
        "--repo", str(tmp_path), "--state", str(state_path),
    ])

    assert result.exit_code == 0, result.output
    assert "2 new" in result.output
    assert state_path.is_file()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["findings"]) == 2


def test_drift_check_cli_requires_a_source(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(SpecGraph(nodes=[]).to_json(), encoding="utf-8")
    result = CliRunner().invoke(main, ["drift-check", "--specgraph", str(spec_path)])
    assert result.exit_code != 0
    assert "supply --codegraph" in result.output


def test_drift_review_cli_shows_and_acks(tmp_path):
    state_path = tmp_path / "drift-state.json"
    drift.check_drift(_two_concept_spec(), _UNRELATED_CODE_GRAPH, state_path=state_path)

    shown = CliRunner().invoke(main, ["drift-review", "--state", str(state_path)])
    assert shown.exit_code == 0
    assert "spec_concept_without_code_match" in shown.output

    acked = CliRunner().invoke(main, ["drift-review", "--state", str(state_path), "--ack"])
    assert acked.exit_code == 0
    assert drift.pending_drift(state_path=state_path) == []


def test_drift_review_cli_reports_when_empty(tmp_path):
    result = CliRunner().invoke(main, [
        "drift-review", "--state", str(tmp_path / "missing-state.json"),
    ])
    assert result.exit_code == 0
    assert "no pending drift" in result.output
