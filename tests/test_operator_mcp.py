"""The operator MCP server (`sembl_stack/operator_mcp.py`, SPEC-O11 §3, WP-B).

Tool bodies are plain functions — every test here calls them directly, no MCP
transport, same convention as `tests/test_discuss.py`/`../sembl/tests/test_mcp_
server.py`. Scratch repos are built the way `tests/test_init_stranger.py` and
`tests/test_drift_resolve.py` already do (real `sembl-stack init` scaffold /
`drift.check_drift` state files), not hand-rolled fixtures, so these tests exercise
the actual engine plumbing `operator_mcp` wraps.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from click.testing import CliRunner

from sembl_stack import bus, discuss, drift, guide, operator_mcp
from sembl_stack.artifacts import Verdict
from sembl_stack.cli import main as cli_main
from sembl_stack.store import RunStore

try:
    import mcp as _mcp  # noqa: F401
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


_UNRELATED_CODE_GRAPH = {"results": [{"name": "Something", "file_path": "src/something.ts"}]}


def _two_concept_spec():
    from sembl_stack.artifacts import SpecGraph
    return SpecGraph(nodes=[
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback item"},
        {"id": "entity:vote", "type": "entity", "name": "vote"},
    ])


def _seed_two_pending(repo: Path):
    state_path = operator_mcp._drift_state_path(str(repo))
    drift.check_drift(_two_concept_spec(), _UNRELATED_CODE_GRAPH, state_path=state_path)
    return drift.pending_drift_items(state_path=state_path)


def _scaffold_repo(tmp_path: Path, monkeypatch, max_attempts: int | None = None) -> Path:
    """A runnable `gate+sandbox` demo repo, the same shape
    `tests/test_init_stranger.py::test_scaffold_loop_runs_end_to_end` proves works
    end to end: `init` writes sembl.stack.yaml + task.yaml + bounds.json + a
    committed demo git repo. `max_attempts`, when given, overrides the preset's
    default 3 so a run_loop test can force a final BLOCK (no retry) deterministically."""
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(cli_main, ["init", "--preset", "gate+sandbox"],
                             catch_exceptions=False)
    assert res.exit_code == 0, res.output
    if max_attempts is not None:
        cfg_path = tmp_path / "sembl.stack.yaml"
        text = cfg_path.read_text(encoding="utf-8").replace(
            "max_attempts: 3", f"max_attempts: {max_attempts}")
        cfg_path.write_text(text, encoding="utf-8")
    return tmp_path


# --- 1/2/3. read_state -----------------------------------------------------------

class TestReadState:
    def test_list_mode(self, tmp_path):
        store = RunStore(str(tmp_path))
        run = store.new_run(task=SimpleNamespace(text="do a thing", repo=str(tmp_path)))
        run.set_status("PASS")

        result = operator_mcp.read_state(str(tmp_path))

        assert result["runs"] == [{
            "id": run.id, "status": "PASS", "task": "do a thing", "verdict_status": "PASS",
        }]

    def test_detail_mode_has_manifest_verdict_events_and_artifacts(self, tmp_path):
        store = RunStore(str(tmp_path))
        run = store.new_run(task=SimpleNamespace(text="do a thing", repo=str(tmp_path)))
        run.append_event("spec", "start")
        run.append_event("spec", "done")
        run.put(Verdict(status="PASS", reasons=["all good"]))
        run.set_status("PASS")

        result = operator_mcp.read_state(str(tmp_path), run_id=run.id)

        assert result["id"] == run.id
        assert result["manifest"]["status"] == "PASS"
        assert result["verdict"] == {"status": "PASS", "reasons": ["all good"]}
        assert [e["stage"] for e in result["events"]] == ["spec", "spec"]
        assert "verdict" in result["artifacts"]

    def test_unknown_run_id_is_a_clean_error_dict(self, tmp_path):
        result = operator_mcp.read_state(str(tmp_path), run_id="no-such-run")
        assert "error" in result
        assert "Traceback" not in result["error"]


# --- 4. read_events ----------------------------------------------------------------

class TestReadEvents:
    def test_bus_passthrough_with_cursor(self, tmp_path):
        bus.publish(tmp_path, {"kind": "run.started", "summary": "one"})
        bus.publish(tmp_path, {"kind": "run.finished", "summary": "two"})

        first = operator_mcp.read_events(str(tmp_path))
        assert [e["summary"] for e in first["events"]] == ["one", "two"]
        assert first["cursor"] > 0

        bus.publish(tmp_path, {"kind": "drift.new", "summary": "three"})
        second = operator_mcp.read_events(str(tmp_path), cursor=first["cursor"])
        assert [e["summary"] for e in second["events"]] == ["three"]


# --- 5. read_config ------------------------------------------------------------------

class TestReadConfig:
    def test_lists_layers_and_registry_options_leaks_no_secrets(self, tmp_path):
        (tmp_path / "sembl.stack.yaml").write_text(yaml.safe_dump({
            "layers": {"execute": "claude", "verify": "sembl"},
            "options": {"execute": {"model": "claude-opus-4"}},
        }, sort_keys=False), encoding="utf-8")

        result = operator_mcp.read_config(str(tmp_path))

        assert result["layers"] == {"execute": "claude", "verify": "sembl"}
        assert "claude" in result["available_adapters"]["execute"]
        assert "sembl" in result["available_adapters"]["verify"]

        blob = json.dumps(result)
        assert "env:" not in blob
        assert "ANTHROPIC_API_KEY" not in blob
        assert "sk-" not in blob
        # only the layers block travels — not the options/transport sections.
        assert "claude-opus-4" not in blob


# --- 6. run_loop ------------------------------------------------------------------

class TestRunLoop:
    def test_returns_run_id_and_pass_verdict(self, tmp_path, monkeypatch):
        repo = _scaffold_repo(tmp_path, monkeypatch)

        result = operator_mcp.run_loop(str(repo), "task.yaml")

        assert result["run_id"]
        assert result["verdict"]["status"] == "PASS"
        assert result["attempts"] >= 1
        assert RunStore(str(repo)).open(result["run_id"]).manifest()["status"] == "PASS"

    def test_missing_task_file_is_a_clean_error_dict(self, tmp_path):
        result = operator_mcp.run_loop(str(tmp_path), "no-such-task.yaml")
        assert "error" in result
        assert "not found" in result["error"]

    def test_blocking_task_returns_block_not_a_retry(self, tmp_path, monkeypatch):
        repo = _scaffold_repo(tmp_path, monkeypatch, max_attempts=1)

        result = operator_mcp.run_loop(str(repo), "task.yaml")

        assert result["verdict"]["status"] == "BLOCK"
        assert result["attempts"] == 1
        assert result["verdict"]["reasons"]


# --- 7. propose_task ----------------------------------------------------------------

class TestProposeTask:
    def test_returns_the_o8_fixed_schema(self, tmp_path, monkeypatch):
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

        proposal = operator_mcp.propose_task(str(tmp_path), "add a widget", executor="claude")

        assert proposal["task_text"] == "Add a widget."
        assert proposal["editable_paths"] == ["src/"]
        assert set(proposal.keys()) == set(discuss.SCHEMA_KEYS)


# --- 8. confirm_task -----------------------------------------------------------------

class TestConfirmTask:
    def test_writes_task_and_bounds(self, tmp_path):
        (tmp_path / "src").mkdir()
        proposal = {"task_text": "Add a thing.", "editable_paths": ["src/"],
                    "forbidden_areas": [], "clarifying_questions": []}

        result = operator_mcp.confirm_task(str(tmp_path), proposal)

        assert Path(result["task_file"]) == tmp_path / "task.yaml"
        assert Path(result["bounds_file"]) == tmp_path / "bounds.json"
        assert (tmp_path / "task.yaml").is_file()
        assert (tmp_path / "bounds.json").is_file()

    def test_empty_proposal_is_a_clean_error_not_a_raise(self, tmp_path):
        result = operator_mcp.confirm_task(str(tmp_path), {
            "task_text": "", "editable_paths": [], "forbidden_areas": [],
            "clarifying_questions": [],
        })
        assert "error" in result


# --- 9. list_drift ---------------------------------------------------------------

class TestListDrift:
    def test_lists_pending_keys_and_findings(self, tmp_path):
        seeded = _seed_two_pending(tmp_path)

        result = operator_mcp.list_drift(str(tmp_path))

        assert len(result["pending"]) == 2
        assert {item["key"] for item in result["pending"]} == {k for k, _ in seeded}
        assert all("finding" in item for item in result["pending"])


# --- 10/11/12. resolve_drift -----------------------------------------------------

class TestResolveDrift:
    def test_ack(self, tmp_path):
        items = _seed_two_pending(tmp_path)
        key = items[0][0]

        result = operator_mcp.resolve_drift(str(tmp_path), key, "ack")

        assert result == {"key": key, "action": "ack", "acknowledged": 1}
        state_path = operator_mcp._drift_state_path(str(tmp_path))
        assert len(drift.pending_drift(state_path=state_path)) == 1

    def test_exception_requires_reason(self, tmp_path):
        items = _seed_two_pending(tmp_path)
        key = items[0][0]

        result = operator_mcp.resolve_drift(str(tmp_path), key, "exception")

        assert "error" in result
        assert "reason" in result["error"]

    def test_exception_with_reason_records_permanent_exception(self, tmp_path):
        items = _seed_two_pending(tmp_path)
        key = items[0][0]

        result = operator_mcp.resolve_drift(str(tmp_path), key, "exception",
                                            reason="kept intentionally")

        assert result["resolved"] is True
        state_path = operator_mcp._drift_state_path(str(tmp_path))
        entry = drift.entry_for_key(key, state_path=state_path)
        assert entry["exception"]["reason"] == "kept intentionally"

    def test_unknown_key_is_a_clean_error(self, tmp_path):
        _seed_two_pending(tmp_path)

        result = operator_mcp.resolve_drift(str(tmp_path), "not-a-real-key", "ack")

        assert "error" in result
        assert "Traceback" not in result["error"]

    def test_unknown_action_lists_valid_options(self, tmp_path):
        items = _seed_two_pending(tmp_path)
        key = items[0][0]

        result = operator_mcp.resolve_drift(str(tmp_path), key, "delete")

        assert "error" in result
        assert result["valid_actions"] == ["ack", "exception"]


# --- 13/14. swap_adapter --------------------------------------------------------

class TestSwapAdapter:
    def test_happy_path_rewrites_exactly_one_key(self, tmp_path):
        cfg_path = tmp_path / "sembl.stack.yaml"
        cfg_path.write_text(yaml.safe_dump({
            "layers": {"execute": "mock", "verify": "sembl"},
            "loop": {"max_attempts": 3, "strict": True},
        }, sort_keys=False), encoding="utf-8")

        result = operator_mcp.swap_adapter(str(tmp_path), "execute", "claude")

        assert result["layer"] == "execute"
        assert result["adapter"] == "claude"
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert data["layers"]["execute"] == "claude"
        assert data["layers"]["verify"] == "sembl"          # untouched
        assert data["loop"] == {"max_attempts": 3, "strict": True}  # untouched

    def test_unknown_layer_and_unknown_adapter_list_valid_options(self, tmp_path):
        bad_layer = operator_mcp.swap_adapter(str(tmp_path), "not-a-layer", "mock")
        assert "error" in bad_layer
        assert "execute" in bad_layer["valid_layers"]

        bad_adapter = operator_mcp.swap_adapter(str(tmp_path), "execute", "not-an-adapter")
        assert "error" in bad_adapter
        assert "mock" in bad_adapter["valid_adapters"]


# --- 15. the boundary lock ---------------------------------------------------------

class TestBoundaryLock:
    _EXPECTED = (
        "read_state", "read_events", "read_config", "run_loop",
        "propose_task", "confirm_task", "list_drift", "resolve_drift",
        "swap_adapter",
    )

    def test_tool_names_is_exactly_the_nine(self):
        assert operator_mcp.TOOL_NAMES == self._EXPECTED

    def test_build_server_registration_source_iterates_tool_names(self):
        src = inspect.getsource(operator_mcp.build_server)
        assert "for name in TOOL_NAMES" in src

    def test_no_verdict_constructed_anywhere_in_the_module(self):
        src = Path(operator_mcp.__file__).read_text(encoding="utf-8")
        assert "Verdict(" not in src

    def test_no_factory_guide_import(self):
        # ast-based, not a substring check: the module's own docstring legitimately
        # *talks about* factory_guide (O9 separation) without importing it — only a
        # real import statement referencing it would violate the boundary.
        src = Path(operator_mcp.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_names.add(node.module)
                imported_names.update(a.name for a in node.names)
        assert not any("factory_guide" in name for name in imported_names)

    def test_module_imports_cleanly_without_mcp_installed(self, monkeypatch):
        # Null out the package AND its already-imported submodules: Python's import
        # machinery checks sys.modules for the *fully qualified* name first, so a
        # previously-cached "mcp.server.fastmcp" (e.g. from the FastMCP test below,
        # or another test module) would otherwise short-circuit past a None "mcp"
        # entry and this simulation would silently do nothing.
        for name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
            monkeypatch.setitem(sys.modules, name, None)
        if "sembl_stack.operator_mcp" in sys.modules:
            del sys.modules["sembl_stack.operator_mcp"]
        try:
            mod = importlib.import_module("sembl_stack.operator_mcp")
            assert mod.TOOL_NAMES == self._EXPECTED
            with pytest.raises(SystemExit):
                mod.build_server()
        finally:
            sys.modules["sembl_stack.operator_mcp"] = operator_mcp

    @pytest.mark.skipif(not HAS_MCP, reason="requires the 'mcp' extra")
    def test_fastmcp_server_registers_exactly_the_nine(self):
        import asyncio
        server = operator_mcp.build_server()
        names = {t.name for t in
                asyncio.new_event_loop().run_until_complete(server.list_tools())}
        assert names == set(self._EXPECTED)


# --- bonus: stdio discipline -----------------------------------------------------

class TestNoStdoutWrites:
    def test_read_only_tools_never_print_to_stdout(self, tmp_path, capsys):
        (tmp_path / "sembl.stack.yaml").write_text(
            yaml.safe_dump({"layers": {"execute": "mock"}}), encoding="utf-8")
        operator_mcp.read_config(str(tmp_path))
        operator_mcp.list_drift(str(tmp_path))
        operator_mcp.read_events(str(tmp_path))
        operator_mcp.read_state(str(tmp_path))

        captured = capsys.readouterr()
        assert captured.out == ""
