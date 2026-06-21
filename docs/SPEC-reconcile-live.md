# SPEC — Reconcile-live (S9): drive the code graph from a real CBM index

> Pinned, owner-authored spec. Implement it EXACTLY. Mirror the existing **symgraph** context
> adapter (`sembl_stack/contextgraph.py` `SymgraphGraph`) for the subprocess pattern and the
> **registry/config** wiring of the `context` layer. Do NOT invent new patterns, rename fields, or
> change signatures. Keep all 81 existing tests green and add the new ones. After implementing, run
> `.venv\Scripts\python.exe -m pytest -q` and confirm **87 passed, 1 skipped** before finishing.

## 0. Why
Action-plan §9 item 2. `reconcile` (L5.5, S9) compares a `SpecGraph` against a **code graph** and
emits an advisory `ReconciliationReport` (NEVER a gate). Today the `reconcile` CLI requires a
**hand-passed `--codegraph <file>.json`**. This spec wires the code graph to a **real
codebase-memory-mcp (CBM) index**, so a per-PR reconcile needs no manual step.

The `reconcile_spec_code` function and `ReconciliationReport` are DONE and unchanged — its
`_nodes_from_payload` already consumes a `{"results": [...]}` payload (CBM's `search_graph` shape).
This spec only adds the **live code-graph source** + a `--live` path on the CLI.

**Locked design rules:**
- **Advisory, never a gate.** Any CBM failure returns an empty graph `{}` (reconcile then reports
  `UNKNOWN`); it must NEVER raise into the loop or look like a BLOCK.
- **Subprocess containment.** CBM is driven via its single-shot CLI (`cbm cli <tool> <json-args>`),
  exactly like the symgraph adapter drives `symgraph`. CBM is NOT a package dependency.
- The empirically-verified CBM contract (do not change it):
  - `cbm cli index_repository '{"path": "<abs repo>"}'` → indexes (idempotent refresh).
  - `cbm cli list_projects '{}'` → `{"projects":[{"name":"<slug>","root_path":"<path>",...}]}`.
    The **slug** is CBM's own project name; resolve it by matching `root_path` to the repo.
  - `cbm cli search_graph '{"project":"<slug>","name_pattern":".","limit":5000}'` →
    `{"total":N,"results":[{"name","qualified_name","label","file_path",...}],"has_more":...}`.
    A `name_pattern` of `"."` with a high `limit` returns the full node set in one call.
  - CBM may emit a leading `level=info msg=mem.init ...` log line before the JSON — parse robustly.

## 1. New adapter — `sembl_stack/adapters/codegraph_cbm.py` (NEW FILE)
Create the file with EXACTLY this content:
```python
"""L5.5 code-graph source — drive codebase-memory-mcp (CBM) headlessly.

reconcile (S9) compares a SpecGraph against a code graph. Previously the code graph was a
hand-passed JSON file; this adapter produces it LIVE from a real CBM index so a per-PR reconcile
needs no manual step. CBM is driven via its single-shot CLI (`cbm cli <tool> <json-args>`) — the
same subprocess containment as the symgraph adapter, never a package dependency. Advisory only: a
failure returns an empty graph (reconcile then reports UNKNOWN), never an exception that could be
mistaken for a gate.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class CbmCodeGraph:
    """Drives the codebase-memory-mcp binary to export a code graph for reconciliation."""

    def __init__(self, binary: str = "codebase-memory-mcp", timeout: int = 600,
                 limit: int = 5000):
        self.binary = binary
        self.timeout = timeout
        self.limit = limit

    def _exe(self) -> str | None:
        return shutil.which(self.binary)

    def available(self) -> bool:
        return self._exe() is not None

    def _run(self, tool: str, payload: dict) -> dict:
        exe = self._exe()
        if not exe:
            return {}
        try:
            proc = subprocess.run(
                [exe, "cli", tool, json.dumps(payload)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return {}
        return _parse_json(proc.stdout)

    def _project_slug(self, repo: str) -> str | None:
        target = _norm(str(Path(repo).resolve()))
        listing = self._run("list_projects", {})
        for proj in listing.get("projects", []):
            if _norm(proj.get("root_path", "")) == target and proj.get("name"):
                return proj["name"]
        return None

    def code_graph(self, repo: str, *, index: bool = True) -> dict:
        """Return a CBM code-graph payload `{"results":[...]}` reconcile can consume.

        Indexes the repo (idempotent refresh), resolves the project slug via CBM's own
        list_projects mapping, then pulls every node with a broad pattern. Returns `{}` on any
        failure — reconcile degrades to UNKNOWN, never blocks.
        """
        if index:
            self._run("index_repository", {"path": str(Path(repo).resolve())})
        slug = self._project_slug(repo)
        if not slug:
            return {}
        return self._run(
            "search_graph",
            {"project": slug, "name_pattern": ".", "limit": self.limit})


def _norm(p: str) -> str:
    return p.replace("\\", "/").strip().rstrip("/").lower()


def _parse_json(text: str | None) -> dict:
    """Parse CBM stdout, tolerating a leading `level=info ...` log line."""
    if not text:
        return {}
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out = json.loads(line)
                return out if isinstance(out, dict) else {}
            except json.JSONDecodeError:
                continue
    return {}
```

## 2. Registry — `sembl_stack/registry.py`
Import the adapter (next to the other adapter imports):
```python
from .adapters.codegraph_cbm import CbmCodeGraph
```
Add a `codegraph` layer to `_REGISTRY` (place it right after the `"context"` block, since both
are graph sources):
```python
    "codegraph": {                                        # L5.5 code graph for reconcile
        "cbm": lambda t, s, o: CbmCodeGraph(
            binary=o.get("binary", "codebase-memory-mcp"),
            timeout=o.get("timeout", 600), limit=o.get("limit", 5000)),
        "none": lambda t, s, o: None,
    },
```

## 3. Config — `sembl_stack/config.py`
- In `DEFAULTS["layers"]`, add `"codegraph": "cbm"` (place it after `"context": "none"`).
- Add a field to `StackConfig`: `codegraph: object = None` (place it after `context`).
- In `load(...)`'s `StackConfig(...)` call, add (place it after the `context=` line):
```python
        codegraph=registry.build("codegraph", layers.get("codegraph", "cbm"), "cli", server,
                                 opts.get("codegraph")),
```

## 4. CLI — `sembl_stack/cli.py` `reconcile` command
Replace the existing `reconcile` command (the one with required `--codegraph`) with EXACTLY:
```python
@main.command()
@click.option("--specgraph", "specgraph_path", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--codegraph", "codegraph_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Code graph JSON (hand-passed). Omit and pass --live to build it from CBM.")
@click.option("--live", is_flag=True,
              help="Build the code graph live from a real codebase-memory-mcp index.")
@click.option("--repo", default=".", help="Repo to index/graph when --live.")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None,
              help="Write the ReconciliationReport artifact here (else stdout).")
def reconcile(specgraph_path, codegraph_path, live, repo, config_path, out):
    """L5.5: SpecGraph+CodeGraph -> advisory ReconciliationReport (advisory, never a gate)."""
    spec_graph = _read_specgraph(specgraph_path)
    if live:
        cfg = load(config_path if Path(config_path).is_file() else None)
        if cfg.codegraph is None or not cfg.codegraph.available():
            raise click.UsageError(
                "--live needs a codegraph adapter (codebase-memory-mcp on PATH)")
        code_graph = cfg.codegraph.code_graph(repo)
    elif codegraph_path:
        code_graph = json.loads(Path(codegraph_path).read_text(encoding="utf-8-sig"))
    else:
        raise click.UsageError("supply --codegraph <file> or --live")
    _emit(reconcile_spec_code(spec_graph, code_graph), out)
```
(`load`, `json`, `Path`, `_read_specgraph`, `_emit`, `reconcile_spec_code` are already imported in
`cli.py` — do not add imports.)

## 5. Tests — `tests/test_codegraph_cbm.py` (NEW FILE)
Mirror the monkeypatch-subprocess style of `tests/test_deploy_postdeploy.py`. Use EXACTLY:
```python
import json

import pytest
from click.testing import CliRunner

from sembl_stack.adapters.codegraph_cbm import CbmCodeGraph, _parse_json
from sembl_stack.artifacts import SpecGraph
from sembl_stack.cli import main


def _cbm_stub(results, slug="C-Users-x-repo", root="/x/repo"):
    """Fake subprocess.run keyed by the CBM tool name (cmd = [exe, 'cli', <tool>, <json>])."""
    from types import SimpleNamespace

    def run(cmd, **kwargs):
        tool = cmd[2]
        if tool == "index_repository":
            out = {"ok": True}
        elif tool == "list_projects":
            out = {"projects": [{"name": slug, "root_path": root, "nodes": len(results)}]}
        elif tool == "search_graph":
            out = {"total": len(results), "results": results, "has_more": False}
        else:
            out = {}
        # CBM prefixes a log line before the JSON — exercise the robust parser.
        return SimpleNamespace(returncode=0, stdout="level=info msg=mem.init\n" + json.dumps(out),
                               stderr="")
    return run


def test_parse_json_tolerates_log_prefix():
    assert _parse_json('level=info msg=mem.init\n{"a": 1}') == {"a": 1}
    assert _parse_json("not json at all") == {}
    assert _parse_json("") == {}


def test_code_graph_resolves_slug_and_returns_results(monkeypatch, tmp_path):
    results = [{"name": "FeedbackItem", "file_path": "src/models/feedback_item.ts"}]
    root = str(tmp_path).replace("\\", "/")
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.shutil.which",
                        lambda b: "cbm.exe")
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.subprocess.run",
                        _cbm_stub(results, slug="proj-slug", root=root))

    graph = CbmCodeGraph().code_graph(str(tmp_path))

    assert graph["results"] == results


def test_code_graph_empty_when_project_not_indexed(monkeypatch, tmp_path):
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.shutil.which",
                        lambda b: "cbm.exe")
    # list_projects reports a DIFFERENT root than the repo -> no slug -> {}
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.subprocess.run",
                        _cbm_stub([{"name": "X"}], root="/some/other/repo"))

    assert CbmCodeGraph().code_graph(str(tmp_path)) == {}


def test_code_graph_empty_when_binary_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("sembl_stack.adapters.codegraph_cbm.shutil.which", lambda b: None)
    cg = CbmCodeGraph()
    assert cg.available() is False
    assert cg.code_graph(str(tmp_path)) == {}


def test_reconcile_cli_live_builds_report(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sembl_stack.adapters.codegraph_cbm.CbmCodeGraph.available",
        lambda self: True)
    monkeypatch.setattr(
        "sembl_stack.adapters.codegraph_cbm.CbmCodeGraph.code_graph",
        lambda self, repo, **kw: {"results": [
            {"name": "FeedbackItem", "file_path": "src/models/feedback_item.ts"}]})

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(SpecGraph(nodes=[
        {"id": "entity:feedback-item", "type": "entity", "name": "feedback_item"},
    ]).to_json(), encoding="utf-8")
    out_path = tmp_path / "report.json"

    result = CliRunner().invoke(main, [
        "reconcile", "--specgraph", str(spec_path), "--live",
        "--repo", str(tmp_path), "--out", str(out_path),
    ])

    assert result.exit_code == 0, result.output
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["status"] == "ALIGNED"


def test_reconcile_cli_requires_a_source(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(SpecGraph(nodes=[]).to_json(), encoding="utf-8")
    result = CliRunner().invoke(main, ["reconcile", "--specgraph", str(spec_path)])
    assert result.exit_code != 0
    assert "supply --codegraph" in result.output


@pytest.mark.skipif(
    __import__("shutil").which("codebase-memory-mcp") is None,
    reason="codebase-memory-mcp not installed")
def test_cbm_available_when_installed():
    assert CbmCodeGraph().available()
```

## 6. Acceptance (agy — automated)
- `.venv\Scripts\python.exe -m pytest -q` → **87 passed, 1 skipped** (81 prior + 6 new; the last
  test skips unless CBM is on PATH).
- `.venv\Scripts\python.exe -m sembl_stack.cli reconcile --help` shows `--live` and `--repo`.
- The hand-passed `--codegraph <file>` path still works (back-compat); `--codegraph` is now
  optional but valid.

## 7. Live proof (OWNER runs after agy — NOT agy; needs CBM + the flagship)
This is the real-PR divergence report the acceptance calls for; agy's mocked tests cannot prove it.
The owner runs, from the repo root with `codebase-memory-mcp` on PATH:
```bash
# 1) build the spec-side graph for the flagship (adjust --spec to the flagship's spec dir/file)
.venv\Scripts\python.exe -m sembl_stack.cli specgraph --repo examples/flagship-feedback-board \
    --text "feedback board: submit feedback, list items, vote" --out fg-spec.json
# 2) reconcile LIVE against a real CBM index of the flagship
.venv\Scripts\python.exe -m sembl_stack.cli reconcile --specgraph fg-spec.json \
    --live --repo examples/flagship-feedback-board --out fg-report.json
```
Expected: `fg-report.json` is a readable `ReconciliationReport` (ALIGNED/DIVERGENT/UNKNOWN) a
haiku-class model can read; status is advisory and the command exits 0 regardless. Hand the report
to Claude for review.

## 8. Do NOT
- Do NOT make reconcile block, raise, or return a Verdict — it stays advisory (`ReconciliationReport`).
- Do NOT change `reconcile_spec_code`, `ReconciliationReport`, or any existing test.
- Do NOT add CBM as a package dependency or import it — it is a subprocess only.
- Do NOT rename `CbmCodeGraph`, `code_graph`, the `codegraph` layer, the `cbm`/`none` names, the
  `--live`/`--repo` flags, or change the verified CBM CLI payloads in §0.
- Do NOT perform a real CBM/subprocess call in tests (subprocess.run / shutil.which are monkeypatched).
