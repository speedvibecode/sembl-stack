"""`sembl_stack/operator_shell.py` — the operator REPL (SPEC-O11 §5/§7 WP-C).

Plain functions, called directly (no real `claude` subprocess in these tests,
same "tool bodies are plain testable functions" convention as
`tests/test_operator_mcp.py`).
"""
from __future__ import annotations

import json
import sys

import pytest
from click.testing import CliRunner

from sembl_stack import bus, operator_shell
from sembl_stack.cli import main as cli_main


# --- 1. MCP config content ---------------------------------------------------

class TestBuildMcpConfig:
    def test_uses_sys_executable_and_module_invocation(self):
        config = operator_shell.build_mcp_config()

        server = config["mcpServers"]["sembl-stack"]
        assert server["command"] == sys.executable
        assert server["args"] == ["-m", "sembl_stack.operator_mcp"]
        # PATH independence is the point: never the console script.
        assert "sembl-stack-mcp" not in json.dumps(config)

    def test_serializes_to_valid_json(self):
        config = operator_shell.build_mcp_config()
        text = json.dumps(config)
        assert json.loads(text) == config


# --- 2/3. turn text ------------------------------------------------------------

class TestBuildTurn:
    def test_new_events_prefix_a_bracketed_block_and_cursor_advances(self, tmp_path):
        bus.publish(tmp_path, {"kind": "run.started", "summary": "run started"})
        bus.publish(tmp_path, {"kind": "run.verdict", "summary": "verdict: BLOCK"})

        turn_text, new_cursor = operator_shell.build_turn(tmp_path, 0, "what happened?")

        assert turn_text == (
            "[factory events since last turn]\n"
            "- run started\n"
            "- verdict: BLOCK\n"
            "\n"
            "what happened?"
        )
        assert new_cursor > 0

    def test_no_events_leaves_human_text_unmodified(self, tmp_path):
        turn_text, new_cursor = operator_shell.build_turn(tmp_path, 0, "hello there")

        assert turn_text == "hello there"
        assert new_cursor == 0

    def test_cursor_advances_across_successive_calls(self, tmp_path):
        bus.publish(tmp_path, {"kind": "run.started", "summary": "one"})
        _, cursor1 = operator_shell.build_turn(tmp_path, 0, "first")

        bus.publish(tmp_path, {"kind": "run.finished", "summary": "two"})
        turn_text2, cursor2 = operator_shell.build_turn(tmp_path, cursor1, "second")

        assert "- two" in turn_text2
        assert "- one" not in turn_text2   # already consumed at cursor1
        assert cursor2 > cursor1


# --- 4. --print-mcp-config ------------------------------------------------------

class TestPrintMcpConfigCli:
    def test_prints_valid_json_and_exits_zero(self):
        result = CliRunner().invoke(cli_main, ["operator", "--print-mcp-config"],
                                    catch_exceptions=False)

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["mcpServers"]["sembl-stack"]["command"] == sys.executable

    def test_works_even_when_claude_is_not_on_path(self, monkeypatch):
        monkeypatch.setattr(operator_shell.shutil, "which", lambda name: None)

        result = CliRunner().invoke(cli_main, ["operator", "--print-mcp-config"],
                                    catch_exceptions=False)

        assert result.exit_code == 0
        json.loads(result.output)


# --- 5. claude missing from PATH -------------------------------------------------

class TestClaudeMissing:
    def test_actionable_message_nonzero_rc_no_traceback(self, tmp_path, monkeypatch, capsys):
        def _raise(*args, **kwargs):
            raise FileNotFoundError("claude CLI not found on PATH")

        monkeypatch.setattr(operator_shell, "resolve_claude", _raise)

        rc = operator_shell.run_repl(str(tmp_path))

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert rc != 0
        assert "install" in combined.lower()
        assert "--print-mcp-config" in combined
        assert "Traceback" not in combined

    def test_cli_operator_command_surfaces_nonzero_exit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def _raise(*args, **kwargs):
            raise FileNotFoundError("claude CLI not found on PATH")

        monkeypatch.setattr(operator_shell, "resolve_claude", _raise)

        result = CliRunner().invoke(cli_main, ["operator"], catch_exceptions=False)

        assert result.exit_code != 0
        assert "Traceback" not in result.output
