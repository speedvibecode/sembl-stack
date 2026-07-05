"""L0.5 idea-to-spec (Track 5 item 1) — pure core: pitch detection, the fixed
slot schema parser, the bounded LLM draft call, and the spec.json/spec.md
round-trip. The interactive Q&A step itself (`guide._ideation_step`) is
questionary-driven and pilot-tested locally, same convention as `_task_step`."""
from __future__ import annotations

import json

from sembl_stack import ideation
from sembl_stack.artifacts import Spec


class TestDetectPitchDoc:
    def test_finds_product_md(self, tmp_path):
        (tmp_path / "product.md").write_text("a pitch", encoding="utf-8")
        assert ideation.detect_pitch_doc(tmp_path) == tmp_path / "product.md"

    def test_finds_prd_md(self, tmp_path):
        (tmp_path / "PRD.md").write_text("a pitch", encoding="utf-8")
        assert ideation.detect_pitch_doc(tmp_path) == tmp_path / "PRD.md"

    def test_none_when_no_pitch_doc(self, tmp_path):
        assert ideation.detect_pitch_doc(tmp_path) is None

    def test_ignores_directory_named_like_a_pitch_doc(self, tmp_path):
        (tmp_path / "idea.md").mkdir()
        assert ideation.detect_pitch_doc(tmp_path) is None


class TestParseSlots:
    def test_full_valid_reply(self):
        reply = json.dumps({
            "stack_candidates": [{"name": "Next.js + Supabase", "why": "fast to ship"}],
            "open_questions": ["multi-tenant?"],
            "data_model_sketch": "User has many Posts",
            "non_goals_guess": ["mobile app"],
        })
        slots = ideation._parse_slots(reply)
        assert slots["stack_candidates"] == [
            {"name": "Next.js + Supabase", "why": "fast to ship"}]
        assert slots["open_questions"] == ["multi-tenant?"]
        assert slots["data_model_sketch"] == "User has many Posts"
        assert slots["non_goals_guess"] == ["mobile app"]

    def test_accepts_plain_string_stack_candidates(self):
        reply = json.dumps({"stack_candidates": ["Django"]})
        slots = ideation._parse_slots(reply)
        assert slots["stack_candidates"] == [{"name": "Django", "why": ""}]

    def test_tolerates_prose_around_the_json_object(self):
        reply = 'Sure, here you go:\n{"open_questions": ["auth?"]}\nhope that helps'
        slots = ideation._parse_slots(reply)
        assert slots["open_questions"] == ["auth?"]

    def test_missing_keys_default_safely(self):
        slots = ideation._parse_slots(json.dumps({"open_questions": ["a?"]}))
        assert slots["stack_candidates"] == []
        assert slots["data_model_sketch"] == ""
        assert slots["non_goals_guess"] == []

    def test_falls_back_on_unparseable_text(self):
        slots = ideation._parse_slots("not json at all")
        assert slots["stack_candidates"] == []
        assert slots["open_questions"]           # fallback question present
        assert "AI reading" in slots["open_questions"][0]

    def test_falls_back_when_json_is_not_an_object(self):
        slots = ideation._parse_slots(json.dumps(["just", "a", "list"]))
        assert slots["open_questions"]
        assert "AI reading" in slots["open_questions"][0]

    def test_non_dict_stack_candidate_entries_are_dropped(self):
        reply = json.dumps({"stack_candidates": [123, {"name": ""}, "Rails"]})
        slots = ideation._parse_slots(reply)
        assert slots["stack_candidates"] == [{"name": "Rails", "why": ""}]


class TestDraftSpecSlots:
    def test_end_to_end(self, tmp_path, monkeypatch):
        from sembl_stack import guide
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (
                0, json.dumps({"result": json.dumps({"open_questions": ["auth?"]})}),
                "", False))
        slots = ideation.draft_spec_slots(tmp_path, "claude", "a pitch")
        assert slots["open_questions"] == ["auth?"]

    def test_falls_back_when_executor_unsupported(self, tmp_path):
        slots = ideation.draft_spec_slots(tmp_path, "aider", "a pitch")
        assert "AI reading" in slots["open_questions"][0]

    def test_falls_back_on_nonzero_exit(self, tmp_path, monkeypatch):
        from sembl_stack import guide
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (1, "", "boom", False))
        slots = ideation.draft_spec_slots(tmp_path, "claude", "a pitch")
        assert "AI reading" in slots["open_questions"][0]

    def test_never_raises_on_executor_exception(self, tmp_path, monkeypatch):
        from sembl_stack import guide
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")

        def _boom(*a, **kw):
            raise OSError("no such binary")
        monkeypatch.setattr("sembl_stack.adapters.base.run_executor", _boom)
        slots = ideation.draft_spec_slots(tmp_path, "claude", "a pitch")
        assert "AI reading" in slots["open_questions"][0]


class TestSpecRoundTrip:
    def test_write_then_read_back(self, tmp_path):
        spec = Spec(pitch="a todo app", stack="Next.js + Supabase",
                    stack_why="fast to ship", data_model="User has many Todos",
                    non_goals=["mobile app"], questions_resolved={"auth?": "email link"},
                    sources=["product.md"])
        ideation.write_spec(tmp_path, spec)
        assert (tmp_path / "spec.json").is_file()
        assert (tmp_path / "spec.md").is_file()
        loaded = ideation.existing_spec(tmp_path)
        assert loaded == spec

    def test_none_when_no_spec_yet(self, tmp_path):
        assert ideation.existing_spec(tmp_path) is None

    def test_none_on_corrupt_spec_json(self, tmp_path):
        (tmp_path / "spec.json").write_text("not json", encoding="utf-8")
        assert ideation.existing_spec(tmp_path) is None

    def test_markdown_includes_key_sections(self, tmp_path):
        spec = Spec(pitch="A todo app for teams.", stack="Next.js + Supabase",
                    non_goals=["mobile"], questions_resolved={"auth?": "email link"})
        md = ideation.render_markdown(spec)
        assert "Next.js + Supabase" in md
        assert "mobile" in md
        assert "auth?" in md


class TestSplitList:
    def test_splits_and_strips(self):
        assert ideation.split_list("a, b ,c") == ["a", "b", "c"]

    def test_empty_string_yields_empty_list(self):
        assert ideation.split_list("") == []


class TestSpecToTaskText:
    def test_includes_stack_and_pitch(self):
        spec = Spec(pitch="A todo app for teams.", stack="Next.js + Supabase")
        text = ideation.spec_to_task_text(spec)
        assert "Next.js + Supabase" in text
        assert "A todo app for teams." in text

    def test_includes_stack_why_data_model_non_goals_and_resolved(self):
        spec = Spec(
            pitch="A todo app.", stack="Django", stack_why="fast to ship",
            data_model="User has many Todos", non_goals=["mobile app"],
            questions_resolved={"auth?": "email link"})
        text = ideation.spec_to_task_text(spec)
        assert "fast to ship" in text
        assert "User has many Todos" in text
        assert "mobile app" in text
        assert "auth?" in text and "email link" in text

    def test_omits_optional_sections_when_unset(self):
        spec = Spec(pitch="A todo app.", stack="Django")
        text = ideation.spec_to_task_text(spec)
        assert "Already resolved" not in text
        assert "Explicitly out of scope" not in text
