"""The stranger quickstart: `init` in a fresh directory must yield a runnable loop.

Regression suite for the two live stranger-blockers found 2026-07-04: `init` scaffolded a
task with no bounds source, in a non-git directory — so `loop task.yaml` crashed at L2
("could not derive bounds") and, once bounds existed, at L4 ("git clone failed"). Now
`init` scaffolds bounds.json + a committed git repo, `doctor` diagnoses both gaps, and
`loop` reports stage failures as clean errors instead of tracebacks.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from sembl_stack import doctor
from sembl_stack.cli import main
from sembl_stack.config import load


def _init_in(tmp: Path, runner: CliRunner):
    return runner.invoke(main, ["init", "--preset", "gate+sandbox"], catch_exceptions=False)


class TestInitScaffoldsRunnableDemo:
    def test_fresh_dir_gets_bounds_and_git_repo(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        res = _init_in(tmp_path, CliRunner())
        assert res.exit_code == 0
        bounds = json.loads((tmp_path / "bounds.json").read_text(encoding="utf-8"))
        assert bounds["editable_paths"] and bounds["forbidden_areas"]
        assert (tmp_path / ".git").exists()
        assert (tmp_path / "app" / "__init__.py").is_file()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                              capture_output=True, text=True)
        assert head.returncode == 0, "init must leave a first commit for the clone sandbox"

    def test_existing_git_repo_left_alone(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        res = _init_in(tmp_path, CliRunner())
        assert res.exit_code == 0
        assert not (tmp_path / "app").exists(), "must not write demo files into a real repo"
        # bounds.json is still scaffolded — the starter task needs a contract anywhere.
        assert (tmp_path / "bounds.json").is_file()

    def test_existing_bounds_not_overwritten(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "bounds.json").write_text('{"editable_paths": ["mine/"]}',
                                              encoding="utf-8")
        res = _init_in(tmp_path, CliRunner())
        assert res.exit_code == 0
        kept = json.loads((tmp_path / "bounds.json").read_text(encoding="utf-8"))
        assert kept["editable_paths"] == ["mine/"]

    def test_scaffold_loop_runs_end_to_end(self, tmp_path, monkeypatch):
        """The actual stranger journey: init then loop, PASS after the mock's BLOCK."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        assert _init_in(tmp_path, runner).exit_code == 0
        res = runner.invoke(main, ["loop", "task.yaml"])
        assert "FINAL: PASS" in res.output, res.output
        assert res.exit_code == 0


class TestDoctorDiagnosesStrangerGaps:
    def test_flags_non_git_dir_and_missing_bounds(self, tmp_path):
        (tmp_path / "task.yaml").write_text('text: "t"\nrepo: "."\n', encoding="utf-8")
        checks = {c.name: c for c in doctor.run_checks(None, repo=str(tmp_path))}
        assert not checks["repo (git)"].ok
        assert not checks["bounds source"].ok

    def test_green_on_scaffolded_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _init_in(tmp_path, CliRunner()).exit_code == 0
        cfg = load(tmp_path / "sembl.stack.yaml")
        checks = {c.name: c for c in doctor.run_checks(cfg, repo=str(tmp_path))}
        assert checks["repo (git)"].ok
        assert checks["bounds source"].ok

    def test_spec_path_counts_as_bounds_source(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "task.yaml").write_text(
            'text: "t"\nrepo: "."\nspec_path: "./specs/001"\n', encoding="utf-8")
        checks = {c.name: c for c in doctor.run_checks(None, repo=str(tmp_path))}
        assert checks["bounds source"].ok


class TestLoopFailsClean:
    def test_stage_runtimeerror_is_a_diagnosis_not_a_traceback(self, tmp_path, monkeypatch):
        """A missing bounds source must produce the hint, not a LangGraph traceback."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        assert _init_in(tmp_path, runner).exit_code == 0
        (tmp_path / "bounds.json").unlink()          # recreate the original stranger state
        res = runner.invoke(main, ["loop", "task.yaml"])
        assert res.exit_code == 1
        assert "error: L2" in res.output
        assert "sembl-stack doctor" in res.output
        assert "Traceback" not in res.output
