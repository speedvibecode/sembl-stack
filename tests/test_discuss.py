"""The discuss panel's task-parse block (O8 use #2 of 3) — pure core: the fixed
proposal schema parser (with its candidate-path value filter), the bounded LLM
call, the deterministic confirm step, and the `discuss` CLI end to end. Same
mocking convention as `tests/test_ideation.py`/`tests/test_guide.py`'s AI call
tests: the executor subprocess boundary is faked, never a real model."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from sembl_stack import discuss, guide
from sembl_stack.cli import main


class TestParseReply:
    def test_full_valid_reply(self):
        candidates = ["src/", "docs/", ".env"]
        reply = json.dumps({
            "task_text": "Add a login form to src/.",
            "editable_paths": ["src/"],
            "forbidden_areas": [".env"],
            "clarifying_questions": ["Which auth provider?"],
        })
        proposal = discuss._parse_reply(reply, candidates)
        assert proposal["task_text"] == "Add a login form to src/."
        assert proposal["editable_paths"] == ["src/"]
        assert proposal["forbidden_areas"] == [".env"]
        assert proposal["clarifying_questions"] == ["Which auth provider?"]

    def test_garbage_reply_falls_back(self):
        proposal = discuss._parse_reply("not json at all", ["src/"])
        assert proposal == {
            "task_text": "", "editable_paths": [], "forbidden_areas": [],
            "clarifying_questions": [],
        }

    def test_falls_back_when_json_is_not_an_object(self):
        proposal = discuss._parse_reply(json.dumps(["just", "a", "list"]), ["src/"])
        assert proposal["task_text"] == ""

    def test_extra_keys_dropped(self):
        reply = json.dumps({
            "task_text": "Fix the bug.", "editable_paths": [], "forbidden_areas": [],
            "clarifying_questions": [], "extra_key": "should not survive",
        })
        proposal = discuss._parse_reply(reply, [])
        assert set(proposal.keys()) == set(discuss.SCHEMA_KEYS)

    def test_out_of_candidate_paths_are_dropped(self):
        reply = json.dumps({
            "task_text": "Add a thing.",
            "editable_paths": ["src/", "made-up-dir/"],
            "forbidden_areas": ["also-made-up/"],
            "clarifying_questions": [],
        })
        proposal = discuss._parse_reply(reply, ["src/", "docs/"])
        assert proposal["editable_paths"] == ["src/"]
        assert proposal["forbidden_areas"] == []

    def test_questions_capped_at_three(self):
        reply = json.dumps({
            "task_text": "x", "editable_paths": [], "forbidden_areas": [],
            "clarifying_questions": ["a?", "b?", "c?", "d?", "e?"],
        })
        proposal = discuss._parse_reply(reply, [])
        assert proposal["clarifying_questions"] == ["a?", "b?", "c?"]

    def test_tolerates_prose_around_the_json_object(self):
        reply = 'Sure, here you go:\n{"task_text": "Do the thing."}\nhope that helps'
        proposal = discuss._parse_reply(reply, [])
        assert proposal["task_text"] == "Do the thing."

    def test_missing_keys_default_safely(self):
        proposal = discuss._parse_reply(json.dumps({"task_text": "x"}), [])
        assert proposal["editable_paths"] == []
        assert proposal["forbidden_areas"] == []
        assert proposal["clarifying_questions"] == []


class TestProposeTask:
    def test_end_to_end_with_mocked_executor(self, tmp_path, monkeypatch):
        (tmp_path / "src").mkdir()
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (
                0, json.dumps({"result": json.dumps({
                    "task_text": "Add a widget.",
                    "editable_paths": ["src/"],
                    "forbidden_areas": [],
                    "clarifying_questions": [],
                })}), "", False))
        proposal = discuss.propose_task(tmp_path, "claude", "add a widget to src")
        assert proposal["task_text"] == "Add a widget."
        assert proposal["editable_paths"] == ["src/"]

    def test_falls_back_when_executor_unsupported(self, tmp_path):
        proposal = discuss.propose_task(tmp_path, "aider", "add a thing")
        assert proposal["task_text"] == ""

    def test_falls_back_on_nonzero_exit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (1, "", "boom", False))
        proposal = discuss.propose_task(tmp_path, "claude", "add a thing")
        assert proposal["task_text"] == ""

    def test_never_raises_on_executor_exception(self, tmp_path, monkeypatch):
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")

        def _boom(*a, **kw):
            raise OSError("no such binary")
        monkeypatch.setattr("sembl_stack.adapters.base.run_executor", _boom)
        proposal = discuss.propose_task(tmp_path, "claude", "add a thing")
        assert proposal["task_text"] == ""


class TestConfirmTask:
    def test_writes_task_and_bounds_byte_compatible_with_guide_writer(self, tmp_path):
        proposal = {
            "task_text": "Add a login form.",
            "editable_paths": ["src/"],
            "forbidden_areas": [".env"],
            "clarifying_questions": [],
        }
        (tmp_path / "src").mkdir()
        task_path, bounds_path = discuss.confirm_task(tmp_path, proposal)
        assert task_path == tmp_path / "task.yaml"
        assert bounds_path == tmp_path / "bounds.json"

        # a second repo written directly via guide.write_task_and_bounds must produce
        # byte-identical artifacts, proving confirm_task is just that writer.
        other = tmp_path.parent / (tmp_path.name + "-direct")
        other.mkdir()
        guide.write_task_and_bounds(other, proposal["task_text"],
                                    proposal["editable_paths"], proposal["forbidden_areas"])
        assert task_path.read_text(encoding="utf-8") == \
            (other / "task.yaml").read_text(encoding="utf-8")
        assert bounds_path.read_text(encoding="utf-8") == \
            (other / "bounds.json").read_text(encoding="utf-8")

    def test_raises_without_editable_paths(self, tmp_path):
        proposal = {"task_text": "x", "editable_paths": [], "forbidden_areas": [],
                    "clarifying_questions": []}
        try:
            discuss.confirm_task(tmp_path, proposal)
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestDiscussCli:
    def test_yes_materializes_end_to_end_with_mocked_executor(self, tmp_path, monkeypatch):
        (tmp_path / "src").mkdir()
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (
                0, json.dumps({"result": json.dumps({
                    "task_text": "Add a login form.",
                    "editable_paths": ["src/"],
                    "forbidden_areas": [],
                    "clarifying_questions": [],
                })}), "", False))
        result = CliRunner().invoke(main, [
            "discuss", "add a login form", "--repo", str(tmp_path),
            "--executor", "claude", "--yes"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "task.yaml").is_file()
        assert (tmp_path / "bounds.json").is_file()
        data = json.loads((tmp_path / "task.yaml").read_text(encoding="utf-8"))
        assert data["text"] == "Add a login form."
        assert "sembl-stack loop" in result.output

    def test_without_yes_only_prints_the_proposal(self, tmp_path):
        result = CliRunner().invoke(main, [
            "discuss", "add a thing", "--repo", str(tmp_path), "--executor", "mock"])
        assert result.exit_code == 0, result.output
        assert not (tmp_path / "task.yaml").is_file()
        assert "review/edit" in result.output

    def test_mock_executor_falls_back_without_external_call(self, tmp_path):
        # "mock" isn't a supported executor in guide._suggest_cmd, so this must never
        # attempt a real subprocess call — it degrades straight to the fallback proposal.
        result = CliRunner().invoke(main, [
            "discuss", "add a thing", "--repo", str(tmp_path), "--executor", "mock"])
        assert result.exit_code == 0, result.output
        printed = result.output.split("\n\n")[0]
        proposal = json.loads(printed)
        assert proposal == {
            "task_text": "", "editable_paths": [], "forbidden_areas": [],
            "clarifying_questions": [],
        }
