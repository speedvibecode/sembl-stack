"""A hard executor failure (auth error, crashed CLI, rate limit...) must surface its
actual reason, not the generic "executor produced no changes" message. Regression
coverage for a real manual-run finding: `claude -p` failed to authenticate, exited 1,
produced an empty diff, and the gate reported it identically to "the agent chose not
to change anything" — hiding the one piece of information (a 401) someone would need
to actually fix it.
"""
from __future__ import annotations

import json

from sembl_stack.adapters.execute_claude import _error_from_result_json
from sembl_stack.artifacts import Change
from sembl_stack.loop import _execution_error, _first_line


class TestExecutionErrorSurfacesNonzeroExit:
    def test_nonzero_exit_with_empty_diff_is_an_execution_error(self):
        change = Change(diff="", report={"exit_code": 1, "output": "401 unauthorized"})
        assert _execution_error(change) == "exit code 1 — 401 unauthorized"

    def test_nonzero_exit_with_a_real_diff_is_not_an_execution_error(self):
        """A nonzero exit that still produced content is a *different* signal (handled
        by `_nonzero_exit`'s PASS->WARN downgrade) — not a hard failure with nothing to
        show for it."""
        diff = "diff --git a/x.py b/x.py\n+++ b/x.py\n+VALUE = 1\n"
        change = Change(diff=diff, report={"exit_code": 1, "output": "partial failure"})
        assert _execution_error(change) is None

    def test_zero_exit_with_empty_diff_is_not_an_execution_error(self):
        """A clean exit with nothing changed is a genuine no-op, not a crash — keep the
        existing "executor produced no changes" wording for that case."""
        change = Change(diff="", report={"exit_code": 0})
        assert _execution_error(change) is None

    def test_explicit_error_key_still_wins(self):
        change = Change(diff="", report={"error": "timeout", "exit_code": 1})
        assert _execution_error(change) == "timeout"

    def test_no_report_at_all(self):
        change = Change(diff="", report={})
        assert _execution_error(change) is None


class TestFirstLine:
    def test_picks_first_nonempty_line(self):
        assert _first_line("\n\n  hello world  \nsecond line") == "hello world"

    def test_truncates_long_lines(self):
        assert _first_line("x" * 500) == "x" * 300

    def test_none_for_empty_or_non_string(self):
        assert _first_line("") is None
        assert _first_line(None) is None
        assert _first_line(123) is None


class TestClaudeErrorFromResultJson:
    def test_extracts_the_result_message_on_is_error(self):
        out = json.dumps({
            "type": "result", "is_error": True,
            "result": "Failed to authenticate. API Error: 401 Invalid authentication credentials",
        })
        assert _error_from_result_json(out) == (
            "Failed to authenticate. API Error: 401 Invalid authentication credentials")

    def test_none_when_not_an_error(self):
        out = json.dumps({"type": "result", "is_error": False, "result": "ok"})
        assert _error_from_result_json(out) is None

    def test_none_on_unparseable_output(self):
        assert _error_from_result_json("not json") is None
        assert _error_from_result_json("") is None

    def test_fallback_message_when_error_has_no_result_text(self):
        out = json.dumps({"type": "result", "is_error": True})
        assert _error_from_result_json(out) == "the agent CLI reported an error with no message"
