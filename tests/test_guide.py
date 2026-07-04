"""The guided surface's pure core (guide.py) — provider detection, bounds
suggestion, artifact writing, and the rail/verdict rendering. The Textual App is
pilot-tested locally (tests/local/); everything here is deterministic logic."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from sembl_stack import guide, scaffold
from sembl_stack.artifacts import Change, Verdict
from sembl_stack.store import RunStore


class TestDetectProviders:
    def test_mock_is_always_available(self, monkeypatch):
        monkeypatch.setattr(guide.shutil, "which", lambda name: None)
        rows = {p.runner: p for p in guide.detect_providers(environ={})}
        assert rows["mock"].ok
        assert not rows["claude-login"].ok
        assert not rows["api-key"].ok
        assert not rows["local"].ok

    def test_missing_options_say_what_is_needed(self, monkeypatch):
        monkeypatch.setattr(guide.shutil, "which", lambda name: None)
        rows = {p.runner: p for p in guide.detect_providers(environ={})}
        assert rows["claude-login"].hint      # install + login guidance
        assert rows["api-key"].hint           # which env var to set
        assert rows["local"].hint

    def test_found_cli_and_set_key_read_as_ok(self, monkeypatch):
        monkeypatch.setattr(guide.shutil, "which",
                            lambda name: f"C:/bin/{name}.cmd")
        rows = {p.runner: p for p in guide.detect_providers(
            environ={"ANTHROPIC_API_KEY": "x"})}
        assert rows["claude-login"].ok and "claude" in rows["claude-login"].status
        assert rows["api-key"].ok and "ANTHROPIC_API_KEY" in rows["api-key"].status
        assert rows["local"].ok


class TestRepoAndBounds:
    def test_repo_state(self, tmp_path):
        root, is_git = guide.repo_state(str(tmp_path))
        assert not is_git
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        _, is_git = guide.repo_state(str(tmp_path))
        assert is_git

    def test_suggest_editable_skips_noise_and_dotdirs(self, tmp_path):
        for d in ("src", "app", ".git", "node_modules", "__pycache__"):
            (tmp_path / d).mkdir()
        assert guide.suggest_editable(tmp_path) == ["app/", "src/"]

    def test_parse_paths(self):
        assert guide.parse_paths(" app/,  src/lib ,") == ["app/", "src/lib"]
        assert guide.parse_paths("") == []


class TestWriteTaskAndBounds:
    def test_writes_loadable_artifacts(self, tmp_path):
        guide.write_task_and_bounds(tmp_path, "Add a toggle", ["app/"], ["infra/"])
        bounds = json.loads((tmp_path / "bounds.json").read_text(encoding="utf-8"))
        assert bounds["editable_paths"] == ["app/"]
        assert bounds["forbidden_areas"] == ["infra/"]
        # task.yaml is written as JSON — valid YAML, loadable by the runner.
        import yaml
        task = yaml.safe_load((tmp_path / "task.yaml").read_text(encoding="utf-8"))
        assert task["text"] == "Add a toggle"

    def test_refuses_empty_task_or_bounds(self, tmp_path):
        for text, editable in (("", ["app/"]), ("do it", [])):
            try:
                guide.write_task_and_bounds(tmp_path, text, editable, [])
                raise AssertionError("expected ValueError")
            except ValueError:
                pass

    def test_round_trips_into_prefill(self, tmp_path):
        guide.write_task_and_bounds(tmp_path, "Add a toggle", ["app/", "src/"], [])
        text, editable, forbidden = guide.existing_answers(tmp_path)
        assert text == "Add a toggle"
        assert editable == "app/, src/"
        assert forbidden == ""


class TestRendering:
    def test_rail_marks_states(self):
        text = guide.rail_text({
            "plan": {"state": "done", "detail": ""},
            "execute": {"state": "running", "detail": "attempt 1"},
        })
        assert "[+] bounds" in text
        assert "[>] execute" in text and "attempt 1" in text
        assert "[ ] gate" in text

    def test_verdict_includes_receipt_and_apply_on_pass(self):
        result = SimpleNamespace(
            verdict=SimpleNamespace(status="PASS", reasons=["in scope"]),
            attempts=2, run_id="r1")
        text = guide.verdict_text(result)
        assert "PASS" in text and "in scope" in text
        assert ".sembl/runs/r1/" in text and "apply" in text

    def test_verdict_block_has_no_apply(self):
        result = SimpleNamespace(
            verdict=SimpleNamespace(status="BLOCK", reasons=["forbidden edit"]),
            attempts=3, run_id="r2")
        text = guide.verdict_text(result)
        assert "BLOCK" in text and "apply" not in text


class TestEventLine:
    def test_fast_stages_only_print_outcomes(self):
        ev = SimpleNamespace(stage="plan", state="running", detail="")
        assert guide.event_line(ev) is None
        ev = SimpleNamespace(stage="plan", state="done", detail="")
        assert "[+] bounds" in guide.event_line(ev)

    def test_runner_stage_names_map_to_user_words(self):
        # the live runner emits "loop", the user reads "execute" (2026-07-04 field bug)
        ev = SimpleNamespace(stage="loop", state="done", detail="attempt 1")
        assert "[+] execute" in guide.event_line(ev)
        ev = SimpleNamespace(stage="loop", state="running", detail="attempt 2")
        assert "attempt 2" in guide.event_line(ev)

    def test_execute_announces_start_and_gate_fail_shows_detail(self):
        ev = SimpleNamespace(stage="execute", state="running", detail="attempt 2")
        assert "execute" in guide.event_line(ev) and "attempt 2" in guide.event_line(ev)
        ev = SimpleNamespace(stage="verify", state="fail", detail="BLOCK")
        line = guide.event_line(ev)
        assert "[x] gate" in line and "BLOCK" in line

    def test_sandbox_layer_is_felt_not_a_direct_jump(self):
        # L4 must render as its own line between bounds and execute, not vanish
        # (2026-07-04 field feedback: "l1-l5 shouldn't appear like the direct jump")
        ev = SimpleNamespace(stage="sandbox", state="done",
                             detail="attempt 1 — disposable clone")
        line = guide.event_line(ev)
        assert "[+] sandbox" in line and "disposable clone" in line
        ev = SimpleNamespace(stage="sandbox", state="fail", detail="attempt 1")
        assert "[x] sandbox" in guide.event_line(ev)


class TestContextStatusLine:
    def test_none_configured(self):
        cfg = SimpleNamespace(context=None, raw={"layers": {"context": "none"}, "loop": {}})
        line = guide.context_status_line(cfg)
        assert "[·]" in line and "none configured" in line

    def test_configured_but_expand_bounds_off(self):
        cfg = SimpleNamespace(
            context=SimpleNamespace(available=lambda: True),
            raw={"layers": {"context": "symgraph"}, "loop": {"expand_bounds": False}})
        line = guide.context_status_line(cfg)
        assert "[·]" in line and "symgraph" in line and "not widening" in line

    def test_configured_and_enabled_but_unavailable(self):
        cfg = SimpleNamespace(
            context=SimpleNamespace(available=lambda: False),
            raw={"layers": {"context": "symgraph"}, "loop": {"expand_bounds": True}})
        line = guide.context_status_line(cfg)
        assert "[·]" in line and "unavailable" in line

    def test_configured_enabled_and_available_shows_real_activity(self):
        cfg = SimpleNamespace(
            context=SimpleNamespace(available=lambda: True),
            raw={"layers": {"context": "symgraph"}, "loop": {"expand_bounds": True}})
        line = guide.context_status_line(cfg)
        assert "[+]" in line and "widening bounds via symgraph" in line


class TestPathTypoHint:
    def test_close_typo_gets_a_suggestion(self, tmp_path):
        (tmp_path / "src" / "components").mkdir(parents=True)
        hint = guide.path_typo_hint(tmp_path, ["src/componenets"])
        assert hint and "src/components/" in hint

    def test_existing_and_genuinely_new_paths_pass(self, tmp_path):
        (tmp_path / "src").mkdir()
        assert guide.path_typo_hint(tmp_path, ["src/"]) is None
        assert guide.path_typo_hint(tmp_path, ["totally_new_dir/"]) is None


class TestEventPrinter:
    def test_consecutive_duplicate_lines_are_dropped(self, capsys):
        printer = guide._event_printer()
        done = SimpleNamespace(stage="verify", state="done", detail="PASS", diff="")
        printer(done)
        printer(done)      # the runner's re-emit of the final verify state
        out = capsys.readouterr().out
        assert out.count("PASS") == 1

    def test_execute_done_prints_the_live_diff_summary(self, capsys):
        printer = guide._event_printer()
        diff = ("diff --git a/app/x.py b/app/x.py\n--- a/app/x.py\n+++ b/app/x.py\n"
                "@@ -0,0 +1,2 @@\n+one\n+two\n-old\n")
        printer(SimpleNamespace(stage="loop", state="done", detail="attempt 1", diff=diff))
        out = capsys.readouterr().out
        assert "app/x.py" in out and "+2 -1" in out
        assert "1 file changed, +2 -1" in out


class TestDiffStat:
    def test_counts_adds_removes_per_file(self):
        diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                "@@\n+x\n+y\n-z\n"
                "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@\n+q\n")
        rows, add, rem = guide.diff_stat(diff)
        assert dict((p, (a, r)) for p, a, r in rows) == {"a.py": (2, 1), "b.py": (1, 0)}
        assert (add, rem) == (3, 1)

    def test_new_file_dev_null_is_ignored_as_source(self):
        diff = ("diff --git a/new.py b/new.py\n--- /dev/null\n+++ b/new.py\n@@\n+hello\n")
        rows, add, rem = guide.diff_stat(diff)
        assert rows == [("new.py", 1, 0)] and (add, rem) == (1, 0)

    def test_empty_diff_yields_no_summary(self):
        assert guide.diff_stat("") == ([], 0, 0)
        assert guide.diff_summary_lines("") == []


class TestInlineFlow:
    def test_full_journey_demo_scaffold_to_verdict(self, tmp_path, monkeypatch, capsys):
        """The whole guided run, scripted: empty dir -> demo scaffold -> mock agent ->
        task -> real loop -> verdict. This is the product surface's smoke test."""
        answers = {"confirm": [True], "select": ["mock", "quit"],
                   "text": ["add a greeting banner", "app/", ""]}

        class _Answer:
            def __init__(self, value):
                self._value = value

            def ask(self):
                return self._value

        monkeypatch.setattr(guide, "questionary", SimpleNamespace(
            confirm=lambda *a, **k: _Answer(answers["confirm"].pop(0)),
            select=lambda *a, **k: _Answer(answers["select"].pop(0)),
            text=lambda *a, **k: _Answer(answers["text"].pop(0))))
        saved = {}
        monkeypatch.setattr(guide.profile, "load", lambda: None)
        monkeypatch.setattr(guide.profile, "save",
                            lambda prof: saved.update(runner=prof.runner))

        guide.launch(str(tmp_path))

        assert saved == {"runner": "mock"}
        assert (tmp_path / "task.yaml").is_file()
        assert (tmp_path / "bounds.json").is_file()
        out = capsys.readouterr().out
        assert "PASS" in out                    # the mock loop's verdict printed
        assert ".sembl/runs/" in out            # with its receipt

    def test_persistent_session_runs_task_after_task(self, tmp_path, monkeypatch, capsys):
        """The cockpit stays open: after a run, 'again' loops back to a new task; the
        loop only ends on 'quit'. Two runs, then stop."""
        answers = {
            "confirm": [True],
            # agent=mock, after run 1 = again, after run 2 = quit
            "select": ["mock", "again", "quit"],
            "text": ["first task", "app/", "",
                     "second task", "app/", ""],
        }

        class _Answer:
            def __init__(self, value):
                self._value = value

            def ask(self):
                return self._value

        monkeypatch.setattr(guide, "questionary", SimpleNamespace(
            confirm=lambda *a, **k: _Answer(answers["confirm"].pop(0)),
            select=lambda *a, **k: _Answer(answers["select"].pop(0)),
            text=lambda *a, **k: _Answer(answers["text"].pop(0))))
        monkeypatch.setattr(guide.profile, "load", lambda: None)
        monkeypatch.setattr(guide.profile, "save", lambda prof: None)

        guide.launch(str(tmp_path))

        # both select pools fully consumed -> both runs happened and we quit cleanly
        assert answers["select"] == []
        assert answers["text"] == []
        assert capsys.readouterr().out.count("PASS") >= 2

    def test_declining_the_demo_exits_cleanly(self, tmp_path, monkeypatch, capsys):
        class _No:
            def ask(self):
                return False

        monkeypatch.setattr(guide, "questionary", SimpleNamespace(
            confirm=lambda *a, **k: _No()))
        guide.launch(str(tmp_path))
        assert not (tmp_path / ".git").exists()
        assert "git" in capsys.readouterr().out


class TestAfterRunMenu:
    def test_ship_is_offered_only_for_pass_or_warn(self, tmp_path, monkeypatch):
        captured = {}

        def fake_select(msg, choices, **k):
            captured["choices"] = [c.value for c in choices]
            return _Answer("quit")

        monkeypatch.setattr(guide, "questionary", SimpleNamespace(select=fake_select))

        result = SimpleNamespace(run_id="r1", verdict=SimpleNamespace(status="PASS"))
        guide._after_run(tmp_path, result)
        assert "ship" in captured["choices"]

        result = SimpleNamespace(run_id="r2", verdict=SimpleNamespace(status="WARN"))
        guide._after_run(tmp_path, result)
        assert "ship" in captured["choices"]

        result = SimpleNamespace(run_id="r3", verdict=SimpleNamespace(status="BLOCK"))
        guide._after_run(tmp_path, result)
        assert "ship" not in captured["choices"]


class TestShipStep:
    def _git_repo(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
        return tmp_path

    def test_apply_and_commit_then_declines_review_and_deploy(self, tmp_path, monkeypatch):
        repo = self._git_repo(tmp_path)
        (repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
        diff = subprocess.run(["git", "diff", "--no-color", "a.txt"], cwd=repo,
                              capture_output=True, text=True).stdout
        subprocess.run(["git", "checkout", "--", "a.txt"], cwd=repo, check=True)

        run = RunStore(str(repo)).new_run()
        run.put(Change(diff=diff, workdir="", report={}))
        run.put(Verdict(status="PASS", reasons=["in scope"]))

        # apply, commit, review(no), deploy(no)
        answers = {"confirm": [True, True, False, False]}
        monkeypatch.setattr(guide, "questionary", SimpleNamespace(
            confirm=lambda *a, **k: _Answer(answers["confirm"].pop(0))))
        monkeypatch.setattr(guide.runner, "resolve_config", lambda repo_str: SimpleNamespace(
            review=SimpleNamespace(review=lambda d: None), deploy=None, postdeploy=None))
        monkeypatch.setattr(guide.runner, "load_task",
                            lambda repo_str: SimpleNamespace(text="fix the thing"))

        guide._ship_step(repo, run.id)

        assert (repo / "a.txt").read_text(encoding="utf-8") == "one\ntwo\n"
        log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=repo,
                             capture_output=True, text=True).stdout
        assert "fix the thing" in log
        assert answers["confirm"] == []

    def test_declining_apply_touches_nothing(self, tmp_path, monkeypatch):
        repo = self._git_repo(tmp_path)
        diff = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1,2 @@\n one\n+two\n"
        run = RunStore(str(repo)).new_run()
        run.put(Change(diff=diff, workdir="", report={}))
        run.put(Verdict(status="PASS", reasons=[]))

        monkeypatch.setattr(guide, "questionary",
                            SimpleNamespace(confirm=lambda *a, **k: _Answer(False)))
        guide._ship_step(repo, run.id)

        assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"

    def test_missing_verdict_reports_and_returns(self, tmp_path, capsys):
        repo = self._git_repo(tmp_path)
        run = RunStore(str(repo)).new_run()
        guide._ship_step(repo, run.id)
        assert "no verdict" in capsys.readouterr().out


class TestLayersConfig:
    def test_write_and_read_round_trip(self, tmp_path):
        guide.write_layers_config(tmp_path, context="symgraph", review="llm", strict=False)
        data = guide.existing_layers_config(tmp_path)
        assert data["layers"]["context"] == "symgraph"
        assert data["layers"]["review"] == "llm"
        assert data["loop"]["strict"] is False

    def test_merges_into_an_existing_file_without_clobbering_other_keys(self, tmp_path):
        (tmp_path / "sembl.stack.yaml").write_text(
            "layers:\n  execute: claude\noptions:\n  execute:\n    model: foo\n",
            encoding="utf-8")
        guide.write_layers_config(tmp_path, context="none", review="mock", strict=True)
        data = guide.existing_layers_config(tmp_path)
        assert data["layers"]["execute"] == "claude"          # preserved
        assert data["layers"]["context"] == "none"            # added by this call
        assert data["options"]["execute"]["model"] == "foo"   # preserved

    def test_existing_layers_config_is_empty_dict_when_absent(self, tmp_path):
        assert guide.existing_layers_config(tmp_path) == {}


class _Answer:
    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


class TestLayersStep:
    def test_skips_prompting_when_config_already_exists(self, tmp_path, monkeypatch):
        guide.write_layers_config(tmp_path, context="none", review="mock", strict=True)

        def _boom(*a, **k):
            raise AssertionError("should not prompt when a config already exists")

        monkeypatch.setattr(guide, "questionary",
                            SimpleNamespace(select=_boom, confirm=_boom))
        prof = SimpleNamespace(executor="mock", strict=True)
        assert guide._layers_step(tmp_path, prof, reconfigure=False) is True

    def test_prompts_and_persists_when_no_config_yet(self, tmp_path, monkeypatch):
        answers = {"select": ["symgraph", "llm"], "confirm": [False]}
        monkeypatch.setattr(guide, "questionary", SimpleNamespace(
            select=lambda *a, **k: _Answer(answers["select"].pop(0)),
            confirm=lambda *a, **k: _Answer(answers["confirm"].pop(0))))
        prof = SimpleNamespace(executor="mock", strict=True)
        assert guide._layers_step(tmp_path, prof, reconfigure=False) is True
        data = guide.existing_layers_config(tmp_path)
        assert data["layers"]["context"] == "symgraph"
        assert data["layers"]["review"] == "llm"
        assert data["loop"]["strict"] is False

    def test_reconfigure_reprompts_even_with_existing_config(self, tmp_path, monkeypatch):
        guide.write_layers_config(tmp_path, context="none", review="mock", strict=True)
        answers = {"select": ["none", "coderabbit"], "confirm": [True]}
        monkeypatch.setattr(guide, "questionary", SimpleNamespace(
            select=lambda *a, **k: _Answer(answers["select"].pop(0)),
            confirm=lambda *a, **k: _Answer(answers["confirm"].pop(0))))
        prof = SimpleNamespace(executor="mock", strict=True)
        assert guide._layers_step(tmp_path, prof, reconfigure=True) is True
        data = guide.existing_layers_config(tmp_path)
        assert data["layers"]["review"] == "coderabbit"

    def test_ctrl_c_on_any_prompt_aborts_without_writing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(guide, "questionary",
                            SimpleNamespace(select=lambda *a, **k: _Answer(None)))
        prof = SimpleNamespace(executor="mock", strict=True)
        assert guide._layers_step(tmp_path, prof, reconfigure=False) is False
        assert guide.existing_layers_config(tmp_path) == {}


class TestAiSuggestPaths:
    def test_parse_ai_paths_drops_hallucinated_and_keeps_real(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "app").mkdir()
        text = "some preamble the model shouldn't have said\nsrc/, app/, totally/made/up/\n"
        assert guide._parse_ai_paths(tmp_path, text) == ["src/", "app/"]

    def test_parse_ai_paths_empty_when_nothing_survives(self, tmp_path):
        assert guide._parse_ai_paths(tmp_path, "made/up/, also/fake/") == []

    def test_extract_result_text_parses_claude_json_envelope(self):
        out = json.dumps({"type": "result", "result": "src/, app/"})
        assert guide._extract_result_text("claude", out) == "src/, app/"

    def test_extract_result_text_falls_back_to_raw_on_non_json(self):
        assert guide._extract_result_text("claude", "src/, app/") == "src/, app/"
        assert guide._extract_result_text("opencode", "src/, app/") == "src/, app/"

    def test_suggest_cmd_none_when_binary_missing(self, monkeypatch):
        monkeypatch.setattr(guide.shutil, "which", lambda name: None)
        assert guide._suggest_cmd("claude", "prompt", None) is None
        assert guide._suggest_cmd("unknown-executor", "prompt", None) is None

    def test_suggest_cmd_claude_never_skips_permissions(self, monkeypatch):
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        cmd = guide._suggest_cmd("claude", "prompt text", None)
        assert "--dangerously-skip-permissions" not in cmd
        assert cmd[-1] == "prompt text"

    def test_ai_suggest_paths_end_to_end(self, tmp_path, monkeypatch):
        (tmp_path / "src").mkdir()
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (0, json.dumps({"result": "src/"}), "", False))
        assert guide.ai_suggest_paths(tmp_path, "claude", "add a thing") == ["src/"]

    def test_ai_suggest_paths_none_on_nonzero_exit(self, tmp_path, monkeypatch):
        (tmp_path / "src").mkdir()
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (1, "", "boom", False))
        assert guide.ai_suggest_paths(tmp_path, "claude", "add a thing") is None

    def test_ai_suggest_paths_none_when_executor_unsupported(self, tmp_path):
        (tmp_path / "src").mkdir()
        assert guide.ai_suggest_paths(tmp_path, "aider", "add a thing") is None

    def test_forbidden_prompt_mentions_the_chosen_editable_scope(self):
        prompt = guide._paths_prompt(
            "add a thing", ["src/", ".env", "infra/"],
            kind="forbidden", editable=["src/"])
        assert "must NOT touch" in prompt
        assert "already be limited to editing: src/" in prompt

    def test_forbidden_prompt_omits_scope_line_when_no_editable_yet(self):
        prompt = guide._paths_prompt("add a thing", ["src/"], kind="forbidden")
        assert "already be limited" not in prompt

    def test_ai_suggest_paths_forbidden_end_to_end(self, tmp_path, monkeypatch):
        (tmp_path / "infra").mkdir()
        (tmp_path / "src").mkdir()
        monkeypatch.setattr(guide.shutil, "which", lambda name: "C:/bin/claude.cmd")
        monkeypatch.setattr(
            "sembl_stack.adapters.base.run_executor",
            lambda cmd, cwd, timeout, **kw: (0, json.dumps({"result": "infra/"}), "", False))
        result = guide.ai_suggest_paths(
            tmp_path, "claude", "add a thing", kind="forbidden", editable=["src/"])
        assert result == ["infra/"]


class TestApplyDiff:
    def _git_repo(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
        return tmp_path

    def _make_diff(self, repo, new_content):
        (repo / "a.txt").write_text(new_content, encoding="utf-8")
        diff = subprocess.run(["git", "diff", "--no-color", "a.txt"], cwd=repo,
                              capture_output=True, text=True).stdout
        subprocess.run(["git", "checkout", "--", "a.txt"], cwd=repo, check=True)
        return diff

    def test_refuses_block_verdict(self, tmp_path):
        repo = self._git_repo(tmp_path)
        verdict = SimpleNamespace(status="BLOCK", raw={})
        try:
            guide._apply_diff(repo, run=None, verdict=verdict, allow_warn=False)
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "BLOCK" in str(e)

    def test_refuses_warn_without_allow(self, tmp_path):
        repo = self._git_repo(tmp_path)
        verdict = SimpleNamespace(status="WARN", raw={})
        try:
            guide._apply_diff(repo, run=None, verdict=verdict, allow_warn=False)
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "WARN" in str(e)

    def test_refuses_a_dirty_tree(self, tmp_path):
        repo = self._git_repo(tmp_path)
        diff = self._make_diff(repo, "one\ntwo\n")
        run = RunStore(str(repo)).new_run()
        run.put(Change(diff=diff, workdir="", report={}))
        (repo / "untracked.txt").write_text("oops", encoding="utf-8")   # dirties the tree
        verdict = SimpleNamespace(status="PASS", raw={})
        try:
            guide._apply_diff(repo, run=run, verdict=verdict, allow_warn=False)
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "uncommitted" in str(e)

    def test_applies_a_clean_patch(self, tmp_path):
        repo = self._git_repo(tmp_path)
        diff = self._make_diff(repo, "one\ntwo\n")
        run = RunStore(str(repo)).new_run()
        run.put(Change(diff=diff, workdir="", report={}))
        verdict = SimpleNamespace(status="PASS", raw={})
        files = guide._apply_diff(repo, run=run, verdict=verdict, allow_warn=False)
        assert "a.txt" in files
        assert (repo / "a.txt").read_text(encoding="utf-8") == "one\ntwo\n"

    def test_refuses_a_sha_mismatched_patch(self, tmp_path):
        repo = self._git_repo(tmp_path)
        diff = self._make_diff(repo, "one\ntwo\n")
        run = RunStore(str(repo)).new_run()
        run.put(Change(diff=diff, workdir="", report={}))
        verdict = SimpleNamespace(
            status="PASS", raw={"subject": {"diff_sha256": "0" * 64}})
        try:
            guide._apply_diff(repo, run=run, verdict=verdict, allow_warn=False)
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "mismatch" in str(e)


class TestScaffoldDemo:
    def test_scaffold_demo_is_loop_runnable(self, tmp_path):
        msgs = scaffold.scaffold_demo(tmp_path)
        assert (tmp_path / "sembl.stack.yaml").is_file()
        assert (tmp_path / "bounds.json").is_file()
        assert (tmp_path / ".git").exists()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                              capture_output=True, text=True)
        assert head.returncode == 0
        assert any("git repo" in m for m in msgs)

    def test_scaffold_never_touches_existing_repo(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        scaffold.scaffold_demo(tmp_path)
        assert not (tmp_path / "app").exists()
