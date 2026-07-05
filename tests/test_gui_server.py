"""The dashboard backend (sembl_stack/gui/server.py) — every endpoint is a thin
wrapper over the same cores guide.py's inline CLI already exercises, so these
tests check the wrapping (request/response shape, error handling, the WS stream),
not the underlying business logic (already covered by test_loop_smoke.py etc).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sembl_stack import profile as profile_module
from sembl_stack import scaffold
from sembl_stack.gui.server import create_app


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
