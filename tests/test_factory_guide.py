"""The factory guide (O9, the second and last sanctioned LLM-in-the-loop pattern)
— pure core: context gathering (read-only), the fixed reply schema parser, the
bounded LLM call, the `explain` CLI end to end. Same mocking convention as
`tests/test_discuss.py`: the executor subprocess boundary is faked, never a
real model."""
from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from sembl_stack import drift, factory_guide, guide
from sembl_stack.artifacts import SpecGraph
from sembl_stack.cli import main

_UNRELATED_CODE_GRAPH = {"results": [{"name": "Something", "file_path": "src/something.ts"}]}


def _two_concept_spec() -> SpecGraph:
    return SpecGraph(nodes=[
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback item"},
        {"id": "entity:vote", "type": "entity", "name": "vote"},
    ])


def _seed_run(tmp_path: Path, run_id: str = "20260101-000000-abc123",
              status: str = "BLOCK", reasons=None) -> Path:
    run_dir = tmp_path / ".sembl" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({
        "id": run_id, "created": 1234.0, "status": "done",
        "task": {"text": "Add a login form.", "repo": str(tmp_path)},
        "attempts_log": [{"attempt": 1}],
    }), encoding="utf-8")
    (run_dir / "verdict.json").write_text(json.dumps({
        "status": status, "reasons": reasons or ["diff touched a forbidden path"],
    }), encoding="utf-8")
    return run_dir


class TestGatherContext:
    def test_includes_run_id_task_and_verdict_status(self, tmp_path):
        _seed_run(tmp_path)
        ctx = factory_guide.gather_context(tmp_path)
        assert "20260101-000000-abc123" in ctx
        assert "Add a login form." in ctx
        assert "BLOCK" in ctx

    def test_includes_pending_drift_kind_and_message(self, tmp_path):
        state_path = tmp_path / ".sembl" / "drift-state.json"
        drift.check_drift(_two_concept_spec(), _UNRELATED_CODE_GRAPH, state_path=state_path)
        ctx = factory_guide.gather_context(tmp_path)
        items = drift.pending_drift_items(state_path=state_path)
        assert items, "expected seeded drift to be pending"
        kind, finding = items[0]
        assert finding["kind"] in ctx
        assert finding["message"] in ctx

    def test_empty_repo_returns_no_state_line_and_never_raises(self, tmp_path):
        ctx = factory_guide.gather_context(tmp_path)
        assert ctx == "no factory state recorded in this repo yet."


class TestParseReply:
    def test_good_reply_returns_answer_and_suggestions(self):
        reply = json.dumps({
            "answer": "The last run blocked because it touched a forbidden path.",
            "suggestions": [
                {"command": "sembl-stack drift-review", "why": "check pending drift"},
            ],
        })
        parsed = factory_guide._parse_reply(reply)
        assert parsed["fallback"] is False
        assert "blocked" in parsed["answer"]
        assert parsed["suggestions"] == [
            {"command": "sembl-stack drift-review", "why": "check pending drift"},
        ]

    def test_caps_suggestions_at_three_and_drops_malformed(self):
        reply = json.dumps({
            "answer": "x",
            "suggestions": [
                {"command": "a", "why": "1"},
                "not a dict",
                {"why": "missing command"},
                {"command": "b", "why": "2"},
                {"command": "c", "why": "3"},
                {"command": "d", "why": "4"},
            ],
        })
        parsed = factory_guide._parse_reply(reply)
        assert len(parsed["suggestions"]) == 3
        assert [s["command"] for s in parsed["suggestions"]] == ["a", "b", "c"]

    def test_garbage_reply_falls_back_without_exception(self):
        parsed = factory_guide._parse_reply("not json at all")
        assert parsed == {"answer": "", "suggestions": [], "fallback": True}


class TestAsk:
    def test_claude_executor_with_model_none_defaults_to_haiku(self, tmp_path, monkeypatch):
        captured = {}

        def _fake_suggest_cmd(executor, prompt, model):
            captured["model"] = model
            return None  # short-circuit: no real subprocess needed for this assertion
        monkeypatch.setattr(guide, "_suggest_cmd", _fake_suggest_cmd)
        factory_guide.ask(tmp_path, "claude", "why did it block?")
        assert captured["model"] == "haiku"

    def test_ask_returns_fallback_when_run_executor_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")

        def _boom(*a, **kw):
            raise OSError("no such binary")
        monkeypatch.setattr("sembl_stack.adapters.base.run_executor", _boom)
        reply = factory_guide.ask(tmp_path, "claude", "why did it block?")
        assert reply["fallback"] is True

    def test_ask_never_writes_to_the_repo(self, tmp_path, monkeypatch):
        _seed_run(tmp_path)
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (
                0, json.dumps({"result": json.dumps({
                    "answer": "It blocked on a forbidden path.",
                    "suggestions": [],
                })}), "", False))

        def _snapshot():
            snap = {}
            for dirpath, _dirnames, filenames in os.walk(tmp_path):
                for fname in filenames:
                    p = Path(dirpath) / fname
                    snap[str(p)] = p.stat().st_mtime_ns
            return snap

        before = _snapshot()
        reply = factory_guide.ask(tmp_path, "claude", "why did it block?")
        after = _snapshot()
        assert reply["fallback"] is False
        assert before == after


class TestExplainCli:
    def test_json_flag_round_trips_and_human_form_prints_answer_and_try(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (
                0, json.dumps({"result": json.dumps({
                    "answer": "It blocked because the diff touched a forbidden path.",
                    "suggestions": [
                        {"command": "sembl-stack drift-review", "why": "check drift first"},
                    ],
                })}), "", False))

        json_result = CliRunner().invoke(main, [
            "explain", "why blocked?", "--repo", str(tmp_path),
            "--executor", "claude", "--json"])
        assert json_result.exit_code == 0, json_result.output
        data = json.loads(json_result.output)
        assert "answer" in data
        assert len(data["suggestions"]) <= 3

        human_result = CliRunner().invoke(main, [
            "explain", "why blocked?", "--repo", str(tmp_path), "--executor", "claude"])
        assert human_result.exit_code == 0, human_result.output
        assert "It blocked because the diff touched a forbidden path." in human_result.output
        assert "try:" in human_result.output
        assert "sembl-stack drift-review" in human_result.output
