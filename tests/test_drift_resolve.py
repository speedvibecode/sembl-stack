import json

import yaml
from click.testing import CliRunner

from sembl_stack import drift
from sembl_stack.artifacts import SpecGraph
from sembl_stack.cli import main

_UNRELATED_CODE_GRAPH = {"results": [{"name": "Something", "file_path": "src/something.ts"}]}


def _two_concept_spec() -> SpecGraph:
    return SpecGraph(nodes=[
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback item"},
        {"id": "entity:vote", "type": "entity", "name": "vote"},
    ])


def _seed_two_pending(state_path):
    drift.check_drift(_two_concept_spec(), _UNRELATED_CODE_GRAPH, state_path=state_path)
    return drift.pending_drift_items(state_path=state_path)


# --- drift.resolve_exception (headless) --------------------------------------

def test_resolve_exception_sets_acknowledged_and_exception(tmp_path):
    state_path = tmp_path / "drift-state.json"
    items = _seed_two_pending(state_path)
    key = items[0][0]

    ok = drift.resolve_exception(key, "legacy route kept intentionally", state_path=state_path)

    assert ok is True
    state = json.loads(state_path.read_text(encoding="utf-8"))
    entry = state["findings"][key]
    assert entry["acknowledged"] is True
    assert entry["exception"]["reason"] == "legacy route kept intentionally"
    assert "decided_at" in entry["exception"]

    pending = drift.pending_drift(state_path=state_path)
    assert len(pending) == 1
    assert drift.finding_key(pending[0]) != key


def test_resolve_exception_unknown_key_is_a_noop(tmp_path):
    state_path = tmp_path / "drift-state.json"
    _seed_two_pending(state_path)

    ok = drift.resolve_exception("not-a-real-key", "whatever", state_path=state_path)

    assert ok is False
    assert len(drift.pending_drift(state_path=state_path)) == 2


def test_resolve_exception_missing_state_file_is_a_noop(tmp_path):
    ok = drift.resolve_exception("k", "r", state_path=tmp_path / "missing.json")
    assert ok is False


def test_exception_survives_subsequent_check_drift(tmp_path):
    """The exception record is a permanent human decision — a later check_drift on the
    same still-present drift must carry it (and acknowledged) forward, not rebuild the
    entry without it."""
    state_path = tmp_path / "drift-state.json"
    items = _seed_two_pending(state_path)
    key = items[0][0]
    drift.resolve_exception(key, "kept intentionally", state_path=state_path)

    # same graphs → same findings still present on the next ambient check
    drift.check_drift(_two_concept_spec(), _UNRELATED_CODE_GRAPH, state_path=state_path)

    entry = drift.entry_for_key(key, state_path=state_path)
    assert entry["acknowledged"] is True
    assert entry["exception"]["reason"] == "kept intentionally"
    assert len(drift.pending_drift(state_path=state_path)) == 1


# --- CLI: drift-resolve --mark-exception --------------------------------------

def test_cli_mark_exception_by_index_drops_from_pending(tmp_path):
    state_path = tmp_path / "drift-state.json"
    _seed_two_pending(state_path)

    before = CliRunner().invoke(main, ["drift-review", "--state", str(state_path)])
    assert before.exit_code == 0
    assert "1." in before.output and "2." in before.output

    result = CliRunner().invoke(main, [
        "drift-resolve", "1", "--state", str(state_path),
        "--mark-exception", "--reason", "legacy route kept intentionally",
    ])
    assert result.exit_code == 0, result.output
    assert "legacy route kept intentionally" in result.output

    after = CliRunner().invoke(main, ["drift-review", "--state", str(state_path)])
    assert after.exit_code == 0
    assert len(drift.pending_drift(state_path=state_path)) == 1


def test_cli_mark_exception_requires_reason(tmp_path):
    state_path = tmp_path / "drift-state.json"
    _seed_two_pending(state_path)

    result = CliRunner().invoke(main, [
        "drift-resolve", "1", "--state", str(state_path), "--mark-exception",
    ])
    assert result.exit_code != 0
    assert "--reason" in result.output


def test_cli_mark_exception_by_full_key(tmp_path):
    state_path = tmp_path / "drift-state.json"
    items = _seed_two_pending(state_path)
    full_key = items[0][0]

    result = CliRunner().invoke(main, [
        "drift-resolve", full_key, "--state", str(state_path),
        "--mark-exception", "--reason", "ok as-is",
    ])
    assert result.exit_code == 0, result.output
    assert len(drift.pending_drift(state_path=state_path)) == 1


def test_cli_mark_exception_unknown_index_errors_with_pending_count(tmp_path):
    state_path = tmp_path / "drift-state.json"
    _seed_two_pending(state_path)

    result = CliRunner().invoke(main, [
        "drift-resolve", "99", "--state", str(state_path),
        "--mark-exception", "--reason", "x",
    ])
    assert result.exit_code != 0
    assert "2 pending" in result.output


def test_cli_mark_exception_unknown_key_errors(tmp_path):
    state_path = tmp_path / "drift-state.json"
    _seed_two_pending(state_path)

    result = CliRunner().invoke(main, [
        "drift-resolve", "totally-unknown-key", "--state", str(state_path),
        "--mark-exception", "--reason", "x",
    ])
    assert result.exit_code != 0
    assert "unknown finding key" in result.output


# --- CLI: drift-resolve --update-code -----------------------------------------

def test_cli_update_code_writes_task_and_does_not_acknowledge(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_path = tmp_path / "drift-state.json"
    items = _seed_two_pending(state_path)
    full_key = items[0][0]

    result = CliRunner().invoke(main, [
        "drift-resolve", full_key, "--state", str(state_path), "--update-code",
    ])
    assert result.exit_code == 0, result.output
    assert "sembl-stack loop" in result.output
    assert "not acknowledged" in result.output

    # still both pending — nothing was acknowledged
    assert len(drift.pending_drift(state_path=state_path)) == 2

    task_dir = tmp_path / ".sembl" / "drift-tasks"
    yaml_files = list(task_dir.glob("*.yaml"))
    assert len(yaml_files) == 1
    task_data = yaml.safe_load(yaml_files[0].read_text(encoding="utf-8"))
    assert task_data["repo"] == "."
    assert "text" in task_data and task_data["text"]
    assert str(yaml_files[0]) in result.output or yaml_files[0].name in result.output


# --- CLI: drift-resolve --update-spec -----------------------------------------

def test_cli_update_spec_prints_finding_and_acknowledges_nothing(tmp_path):
    state_path = tmp_path / "drift-state.json"
    items = _seed_two_pending(state_path)
    full_key = items[0][0]
    _, finding = items[0]

    result = CliRunner().invoke(main, [
        "drift-resolve", "1", "--state", str(state_path), "--update-spec",
    ])
    assert result.exit_code == 0, result.output
    assert str(finding.get("kind")) in result.output
    assert str(finding.get("message")) in result.output
    assert "first_detected" in result.output

    assert len(drift.pending_drift(state_path=state_path)) == 2


# --- CLI: mode mutual exclusion -------------------------------------------------

def test_cli_requires_exactly_one_mode(tmp_path):
    state_path = tmp_path / "drift-state.json"
    _seed_two_pending(state_path)

    none_given = CliRunner().invoke(main, ["drift-resolve", "1", "--state", str(state_path)])
    assert none_given.exit_code != 0

    two_given = CliRunner().invoke(main, [
        "drift-resolve", "1", "--state", str(state_path),
        "--update-code", "--update-spec",
    ])
    assert two_given.exit_code != 0


# --- index resolution matches drift-review numbering ----------------------------

def test_index_resolution_matches_drift_review_numbering(tmp_path):
    state_path = tmp_path / "drift-state.json"
    items = _seed_two_pending(state_path)

    review = CliRunner().invoke(main, ["drift-review", "--state", str(state_path)])
    assert review.exit_code == 0
    lines = [l for l in review.output.splitlines() if l.strip()]
    assert lines[0].startswith("1. ")
    assert lines[1].startswith("2. ")

    # index 2 should resolve to items[1]'s key
    result = CliRunner().invoke(main, [
        "drift-resolve", "2", "--state", str(state_path),
        "--mark-exception", "--reason", "second one",
    ])
    assert result.exit_code == 0, result.output
    assert items[1][0] in result.output
