"""The dashboard backend (sembl_stack/gui/server.py) — every endpoint is a thin
wrapper over the same cores guide.py's inline CLI already exercises, so these
tests check the wrapping (request/response shape, error handling, the WS stream),
not the underlying business logic (already covered by test_loop_smoke.py etc).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sembl_stack import guide
from sembl_stack import profile as profile_module
from sembl_stack import scaffold
from sembl_stack.artifacts import AcceptanceReport, Bounds, Change, Task, Verdict, diff_sha256
from sembl_stack.bus import publish
from sembl_stack.gui.server import create_app
from sembl_stack.store import RunStore


@pytest.fixture(autouse=True)
def _isolated_profile(tmp_path_factory, monkeypatch):
    """Every profile.load()/save() in these tests must hit a throwaway file, never
    the real operator's ~/.sembl/profile.json — and never inside the test repo
    itself, or it shows up as an untracked file and trips the dirty-tree guard."""
    profile_dir = tmp_path_factory.mktemp("profile-home")
    monkeypatch.setattr(profile_module, "path", lambda: profile_dir / "profile.json")


@pytest.fixture
def repo(tmp_path) -> Path:
    """A real, loop-runnable repo: scaffold_demo's mock-executor preset — the same
    fixture `TestScaffoldDemo` uses, so a run here is fast and deterministic
    (misbehaves once -> BLOCK, then complies -> PASS)."""
    scaffold.scaffold_demo(tmp_path)
    return tmp_path


@pytest.fixture
def client(repo) -> TestClient:
    return TestClient(create_app(str(repo)))


# --------------------------------------------------------------------------- WP-A fixtures
#
# Real artifact shapes (appendix, docs/SPEC-demo-shell.md), written via the actual
# artifact dataclasses / RunStore — never hand-rolled JSON — so a shape drift in the
# real engine would break these fixtures too, not silently diverge from them.

_DIFF = ("diff --git a/app/x.py b/app/x.py\n--- a/app/x.py\n+++ b/app/x.py\n"
        "@@ -0,0 +1 @@\n+x = 1\n")


def _seed_run(repo: Path, *, attempts: int = 2, final_status: str = "PASS",
             executor: str = "claude-code", model: str = "claude-sonnet-5",
             cost: float = 0.42, with_acceptance: bool = True, with_stage: bool = True,
             created: float | None = None) -> str:
    """A run with `attempts` attempts (every one but the last BLOCKed), real
    change/verdict/acceptance artifacts, a stage-N.json + snapshot per attempt, and a
    run-level Bounds artifact — the full enriched shape WP-A reads."""
    store = RunStore(str(repo))
    run = store.new_run(Task(text="add a greeting", repo="."))
    for n in range(1, attempts + 1):
        status = final_status if n == attempts else "BLOCK"
        run.put(Change(diff=_DIFF, report={
            "agent": executor, "model": model, "exit_code": 0, "cost": cost}),
            name=f"change-{n}")
        run.put(Verdict(status=status,
                        reasons=[] if status != "BLOCK" else ["touched infra/"]),
                name=f"verdict-{n}")
        if with_acceptance:
            run.put(AcceptanceReport(
                results=[{"id": "check-1", "outcome": "PASS", "duration_s": 1.2,
                          "detail": ""}],
                runner="command@1"), name=f"acceptance-{n}")
        if with_stage:
            stage_dir = run.dir / f"stage-{n}"
            stage_dir.mkdir(parents=True, exist_ok=True)
            (stage_dir / "root.html").write_text("<html>ok</html>", encoding="utf-8")
            manifest = {
                "attempt": n, "serve": {"cmd": "x"}, "url": "http://127.0.0.1:9999",
                "port": 9999,
                "ready": {"ok": True, "detail": None, "boot_s": 0.5, "stderr": None},
                "snapshot_s": 0.1, "diff_sha256": diff_sha256(_DIFF),
                "routes": {"/": {"status": "OK", "file": f"stage-{n}/root.html",
                                "http_status": 200}},
            }
            (run.dir / f"stage-{n}.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8")
        run.record_attempt(n, agent=executor, model=model, cost=cost)
    run.put(Bounds(editable_paths=["app/"], forbidden_areas=["infra/"],
                   churn_budget={"max_files": 20, "max_lines": 1000}))
    run.put(Verdict(status=final_status,
                    reasons=[] if final_status != "BLOCK" else ["touched infra/"]))
    extra = {}
    if created is not None:
        extra["created"] = created
    run.set_status("completed", **extra)
    return run.id


def _seed_crashed_run(repo: Path, *, error: str = "executor timed out",
                      created: float | None = None) -> str:
    """A run that died before ANY attempt artifact was written — only run.json,
    per the spec's crashed-run tolerance requirement."""
    store = RunStore(str(repo))
    run = store.new_run(Task(text="a doomed task", repo="."))
    extra = {"error": error}
    if created is not None:
        extra["created"] = created
    run.set_status("failed", **extra)
    return run.id


class TestStatus:
    def test_shape_with_no_profile_configured(self, client, repo):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["repo"] == str(repo.resolve())
        assert body["is_git"] is True
        assert body["profile"] is None
        assert len(body["providers"]) == 4
        assert body["task"]["text"]           # scaffold_demo wrote a starter task.yaml

    def test_reflects_a_saved_profile(self, client):
        client.post("/api/agent", json={"runner": "mock"})
        body = client.get("/api/status").json()
        assert body["profile"]["runner"] == "mock"
        assert body["profile"]["executor"] == "mock"


class TestAgent:
    def test_mock_runner_always_succeeds(self, client):
        resp = client.post("/api/agent", json={"runner": "mock"})
        body = resp.json()
        assert body["ok"] is True
        assert body["profile"]["executor"] == "mock"

    def test_unknown_runner_is_rejected(self, client):
        resp = client.post("/api/agent", json={"runner": "not-a-real-runner"})
        body = resp.json()
        assert body["ok"] is False
        assert "unknown runner" in body["hint"]


class TestTask:
    def test_writes_task_and_bounds(self, client, repo):
        resp = client.post("/api/task", json={
            "text": "add a health check endpoint", "editable": ["app/"], "forbidden": [],
        })
        assert resp.json()["ok"] is True
        assert (repo / "task.yaml").read_text(encoding="utf-8").find(
            "add a health check endpoint") != -1

    def test_rejects_blank_text(self, client):
        resp = client.post("/api/task", json={"text": "   ", "editable": ["app/"]})
        body = resp.json()
        assert body["ok"] is False
        assert "describe the task" in body["error"]

    def test_warns_on_a_typo_path(self, client, repo):
        (repo / "src").mkdir()
        resp = client.post("/api/task", json={
            "text": "do something", "editable": ["scr/"],
        })
        assert resp.json()["ok"] is True
        assert "did you mean" in resp.json()["warning"]


class TestRunsAndWebSocket:
    def test_no_runs_yet(self, client):
        assert client.get("/api/runs").json() == []

    def test_full_run_streams_and_lands_in_history(self, client, repo):
        client.post("/api/agent", json={"runner": "mock"})
        client.post("/api/task", json={
            "text": "add a greeting", "editable": ["app/"], "forbidden": ["infra/"],
        })

        with client.websocket_connect("/ws/run") as ws:
            messages = []
            while True:
                msg = ws.receive_json()
                messages.append(msg)
                if msg["type"] in ("done", "error"):
                    break

        assert messages[-1]["type"] == "done"
        assert messages[-1]["status"] == "PASS"          # mock: BLOCK then PASS
        stage_types = [m["stage"] for m in messages if m["type"] == "stage"]
        assert "loop" in stage_types
        assert any(m["type"] == "stage" and m["state"] == "fail" for m in messages)

        runs = client.get("/api/runs").json()
        assert len(runs) == 1
        assert runs[0]["verdict"] == "PASS"

        detail = client.get(f"/api/runs/{runs[0]['id']}").json()
        assert detail["verdict"]["status"] == "PASS"
        assert len(detail["attempts"]) == 2              # BLOCK attempt, then PASS attempt

    def test_second_concurrent_run_is_refused(self, client, repo):
        client.post("/api/agent", json={"runner": "mock"})
        client.post("/api/task", json={"text": "x", "editable": ["app/"]})

        with client.websocket_connect("/ws/run") as ws1:
            with client.websocket_connect("/ws/run") as ws2:
                msg2 = ws2.receive_json()
                assert msg2 == {"type": "error", "message": "a run is already in progress"}
            # drain the first run so the lock is released before the fixture tears down
            while ws1.receive_json()["type"] not in ("done", "error"):
                pass

    def test_missing_task_yaml_is_a_clean_error(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.com",
                       "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
        client = TestClient(create_app(str(tmp_path)))
        with client.websocket_connect("/ws/run") as ws:
            msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "task.yaml" in msg["message"]


class TestShip:
    def test_applies_a_pass_verdict(self, client, repo):
        client.post("/api/agent", json={"runner": "mock"})
        client.post("/api/task", json={
            "text": "add a greeting", "editable": ["app/"], "forbidden": ["infra/"],
        })
        with client.websocket_connect("/ws/run") as ws:
            while True:
                msg = ws.receive_json()
                if msg["type"] == "done":
                    run_id = msg["run_id"]
                    break

        resp = client.post("/api/ship", json={"run_id": run_id})
        body = resp.json()
        assert body["ok"] is True
        assert "patch.py" in body["files"]

    def test_unknown_run_id_is_a_clean_error(self, client):
        resp = client.post("/api/ship", json={"run_id": "does-not-exist"})
        body = resp.json()
        assert body["ok"] is False
        assert "error" in body


# --------------------------------------------------------------------------- WP-A: enrichment


class TestRunsListEnriched:
    def test_empty_store_returns_empty_list(self, client):
        assert client.get("/api/runs").json() == []

    def test_enriched_fields_from_real_artifacts(self, client, repo):
        _seed_run(repo, attempts=2, final_status="PASS", created=2000.0)
        rows = client.get("/api/runs").json()
        assert len(rows) == 1
        row = rows[0]
        assert row["verdict"] == "PASS"
        assert row["attempts"] == 2
        assert row["executor"] == "claude-code"
        assert row["model"] == "claude-sonnet-5"
        assert row["created"] == 2000.0
        assert row["error"] is None

    def test_tolerates_a_crashed_run(self, client, repo):
        """A run with only run.json (plus an `error` key) must never 500 — every
        enriched field degrades to null instead."""
        _seed_crashed_run(repo, error="executor timed out", created=1000.0)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        row = resp.json()[0]
        assert row["status"] == "failed"
        assert row["error"] == "executor timed out"
        assert row["verdict"] is None
        assert row["executor"] is None
        assert row["model"] is None
        assert row["attempts"] == 0

    def test_sorts_newest_first_by_created(self, client, repo):
        older = _seed_run(repo, attempts=1, created=1000.0)
        newer = _seed_run(repo, attempts=1, created=5000.0)
        rows = client.get("/api/runs").json()
        assert [r["id"] for r in rows] == [newer, older]


class TestRunDetailEnriched:
    def test_detail_with_acceptance_and_stage(self, client, repo):
        run_id = _seed_run(repo, attempts=2, final_status="PASS",
                           with_acceptance=True, with_stage=True, created=42.0)
        detail = client.get(f"/api/runs/{run_id}").json()

        assert detail["created"] == 42.0
        assert detail["error"] is None
        assert detail["bounds"] == {"editable_paths": ["app/"], "forbidden_areas": ["infra/"]}
        assert detail["acceptance_descriptions"] == {}     # no repo acceptance.json declared
        assert len(detail["attempts"]) == 2

        last = detail["attempts"][-1]
        assert last["status"] == "PASS"
        assert last["cost_usd"] == 0.42
        assert last["model"] == "claude-sonnet-5"
        assert last["acceptance"] == [
            {"id": "check-1", "outcome": "PASS", "duration_s": 1.2, "detail": ""}]
        assert last["stage"]["ok"] is True
        assert last["stage"]["url"] == "http://127.0.0.1:9999"
        assert last["stage"]["routes"]["/"]["file"] == "stage-2/root.html"

        first = detail["attempts"][0]
        assert first["status"] == "BLOCK"

    def test_detail_missing_both_degrades_to_null(self, client, repo):
        """A run missing acceptance/stage artifacts entirely (only the base change/
        verdict artifacts, as a real non-web-app task would leave) never 500s —
        those fields are null, not a crash."""
        run_id = _seed_run(repo, attempts=1, with_acceptance=False, with_stage=False)
        detail = client.get(f"/api/runs/{run_id}").json()
        attempt = detail["attempts"][0]
        assert attempt["acceptance"] is None
        assert attempt["stage"] is None

    def test_detail_for_crashed_run_degrades_to_null(self, client, repo):
        run_id = _seed_crashed_run(repo, error="boom")
        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["error"] == "boom"
        assert detail["verdict"] is None
        assert detail["bounds"] is None
        assert detail["attempts"] == []

    def test_unknown_run_id_is_a_clean_error(self, client):
        resp = client.get("/api/runs/does-not-exist")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestStageSnapshotEndpoint:
    def test_serves_the_snapshot_html(self, client, repo):
        run_id = _seed_run(repo, attempts=1, with_stage=True)
        resp = client.get(f"/api/runs/{run_id}/stage/1")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.text == "<html>ok</html>"

    def test_404_when_no_stage_evidence(self, client, repo):
        run_id = _seed_run(repo, attempts=1, with_stage=False)
        resp = client.get(f"/api/runs/{run_id}/stage/1")
        assert resp.status_code == 404
        assert "error" in resp.json()

    def test_404_when_attempt_does_not_exist(self, client, repo):
        run_id = _seed_run(repo, attempts=1, with_stage=True)
        resp = client.get(f"/api/runs/{run_id}/stage/99")
        assert resp.status_code == 404

    def test_path_escape_is_rejected(self, client, repo):
        """A `file` pointing outside the run directory (a corrupt or maliciously
        crafted stage-N.json) is refused, never served."""
        store = RunStore(str(repo))
        run = store.new_run(Task(text="x", repo="."))
        secret_dir = run.dir.parents[1]                    # <repo>/.sembl/
        secret_dir.mkdir(parents=True, exist_ok=True)
        (secret_dir / "secret.html").write_text("TOP SECRET", encoding="utf-8")
        (run.dir / "stage-1.json").write_text(json.dumps({
            "attempt": 1, "serve": None, "url": None, "port": None,
            "ready": {"ok": True, "detail": None, "boot_s": 0.1, "stderr": None},
            "snapshot_s": None, "diff_sha256": diff_sha256(""),
            "routes": {"/": {"status": "OK", "file": "../../secret.html",
                             "http_status": 200}},
        }), encoding="utf-8")

        resp = client.get(f"/api/runs/{run.id}/stage/1")
        assert resp.status_code == 404
        assert "TOP SECRET" not in resp.text


class TestEventsEndpoint:
    def test_cursor_advances_and_new_events_are_returned(self, client, repo):
        assert client.get("/api/events?cursor=0").json() == {"events": [], "cursor": 0}

        publish(repo, {"kind": "run.started", "run_id": "r1"})
        first = client.get("/api/events?cursor=0").json()
        assert len(first["events"]) == 1
        assert first["events"][0]["kind"] == "run.started"
        assert first["cursor"] > 0

        publish(repo, {"kind": "run.finished", "run_id": "r1"})
        second = client.get(f"/api/events?cursor={first['cursor']}").json()
        assert len(second["events"]) == 1
        assert second["events"][0]["kind"] == "run.finished"
        assert second["cursor"] > first["cursor"]


class TestGuideMergePreservesCuratedKeys:
    def test_bounds_merge_preserves_churn_budget(self, tmp_path):
        (tmp_path / "bounds.json").write_text(json.dumps({
            "editable_paths": ["old/"], "forbidden_areas": [],
            "churn_budget": {"max_files": 5, "max_lines": 50},
        }), encoding="utf-8")

        guide.write_task_and_bounds(tmp_path, "do the thing", ["app/"], ["infra/"])

        data = json.loads((tmp_path / "bounds.json").read_text(encoding="utf-8"))
        assert data["editable_paths"] == ["app/"]
        assert data["forbidden_areas"] == ["infra/"]
        assert data["churn_budget"] == {"max_files": 5, "max_lines": 50}

    def test_task_write_preserves_spec_path(self, tmp_path):
        (tmp_path / "task.yaml").write_text(json.dumps({
            "text": "old text", "repo": ".", "spec_path": "spec.md",
        }), encoding="utf-8")

        guide.write_task_and_bounds(tmp_path, "new text", ["app/"], [])

        data = json.loads((tmp_path / "task.yaml").read_text(encoding="utf-8"))
        assert data["text"] == "new text"
        assert data["spec_path"] == "spec.md"


class TestRunnerStageHoldPassthrough:
    def test_run_stages_passes_stage_hold_through(self, monkeypatch):
        from types import SimpleNamespace

        from sembl_stack import runner as runner_module
        from sembl_stack.loop import LoopResult

        captured = {}

        def fake_run_loop(cfg, task, *, stage_hold=False):
            captured["stage_hold"] = stage_hold
            return LoopResult(verdict=Verdict(status="PASS"), attempts=1, run_id="fake-run")

        monkeypatch.setattr(runner_module, "run_loop", fake_run_loop)
        cfg = SimpleNamespace(spec=object(), sandbox=object(), execute=object(),
                              verify=object())
        task = Task(text="x", repo=".")

        result = runner_module.run_stages(cfg, task, lambda ev: None, stage_hold=True)

        assert captured["stage_hold"] is True
        assert result.run_id == "fake-run"
