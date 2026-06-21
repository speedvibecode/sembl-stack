from types import SimpleNamespace

from click.testing import CliRunner

from sembl_stack.adapters.deploy_vercel import VercelDeployAdapter
from sembl_stack.adapters.postdeploy_http import HttpPostDeployGate
from sembl_stack.artifacts import Delivery, Verdict
from sembl_stack.cli import main


def test_vercel_deploy_adapter_captures_url_without_secret(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="Preview: https://feedback-board.vercel.app\n",
            stderr="",
        )

    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel.subprocess.run", fake_run)

    delivery = VercelDeployAdapter(timeout=5).deploy(
        str(tmp_path), production=True, prebuilt=True)

    assert delivery.status == "deployed"
    assert delivery.url == "https://feedback-board.vercel.app"
    assert calls[0][0] == ["vercel", "deploy", "--prebuilt", "--prod", "--yes"]
    assert "token" not in delivery.to_json().lower()


def test_vercel_deploy_adapter_records_failure(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="not linked")

    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel.subprocess.run", fake_run)

    delivery = VercelDeployAdapter(timeout=5).deploy(str(tmp_path))

    assert delivery.status == "failed"
    assert delivery.url is None
    assert delivery.data["returncode"] == 1


def test_http_postdeploy_gate_passes_on_2xx(monkeypatch):
    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, n):
            return b""

    monkeypatch.setattr("sembl_stack.adapters.postdeploy_http.urlopen",
                        lambda req, timeout: Response())

    verdict = HttpPostDeployGate().verify(
        Delivery(target="vercel", url="https://app.example", status="deployed"),
        health_path="/api/health",
    )

    assert verdict.status == "PASS"
    assert verdict.raw["url"] == "https://app.example/api/health"


def _json_response(status_code, payload):
    class Response:
        status = status_code

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, n):
            import json as _json
            return _json.dumps(payload).encode("utf-8")[:n]

    return Response


def test_http_postdeploy_gate_passes_on_matching_payload(monkeypatch):
    monkeypatch.setattr(
        "sembl_stack.adapters.postdeploy_http.urlopen",
        lambda req, timeout: _json_response(200, {"ok": True, "app": "feedback"})(),
    )

    verdict = HttpPostDeployGate().verify(
        Delivery(target="vercel", url="https://app.example", status="deployed"),
        health_path="/api/health",
        expect_json={"ok": True, "app": "feedback"},
    )

    assert verdict.status == "PASS"


def test_http_postdeploy_gate_blocks_on_payload_mismatch(monkeypatch):
    monkeypatch.setattr(
        "sembl_stack.adapters.postdeploy_http.urlopen",
        lambda req, timeout: _json_response(200, {"ok": False, "app": "feedback"})(),
    )

    verdict = HttpPostDeployGate().verify(
        Delivery(target="vercel", url="https://app.example", status="deployed"),
        health_path="/api/health",
        expect_json={"ok": True},
    )

    assert verdict.status == "BLOCK"
    assert "payload mismatch" in verdict.reasons[0]


def test_http_postdeploy_gate_blocks_missing_delivery_url():
    verdict = HttpPostDeployGate().verify(Delivery(target="vercel", status="failed"))

    assert verdict.status == "BLOCK"
    assert "no URL" in verdict.reasons[0]


def test_deploy_cli_refuses_block_verdict(tmp_path):
    verdict_path = tmp_path / "verdict.json"
    verdict_path.write_text(Verdict(status="BLOCK").to_json(), encoding="utf-8")

    result = CliRunner().invoke(main, [
        "deploy", "--verdict", str(verdict_path), "--repo", str(tmp_path),
    ])

    assert result.exit_code != 0
    assert "refusing to deploy a BLOCK" in result.output


def test_vercel_rollback_promotes_previous(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(
            returncode=0,
            stdout="Success! Rolled back to https://feedback-board.vercel.app\n",
            stderr="",
        )

    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel.subprocess.run", fake_run)

    delivery = VercelDeployAdapter(timeout=5).rollback(str(tmp_path))

    assert delivery.status == "rolled_back"
    assert delivery.url == "https://feedback-board.vercel.app"
    assert calls[0] == ["vercel", "rollback", "--yes"]
    assert "token" not in delivery.to_json().lower()


def test_vercel_rollback_records_failure(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="no previous deployment")

    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel.subprocess.run", fake_run)

    delivery = VercelDeployAdapter(timeout=5).rollback(str(tmp_path))

    assert delivery.status == "rollback_failed"
    assert delivery.data["returncode"] == 1


def test_postdeploy_cli_rolls_back_on_block(monkeypatch, tmp_path):
    # Gate sees an unhealthy deploy (HTTP 500) -> BLOCK.
    class Response:
        status = 500

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, n):
            return b"down"

    monkeypatch.setattr("sembl_stack.adapters.postdeploy_http.urlopen",
                        lambda req, timeout: Response())
    # Stub the rollback mechanism so the test never touches the network.
    monkeypatch.setattr(
        "sembl_stack.adapters.deploy_vercel.VercelDeployAdapter.rollback",
        lambda self, repo, **kw: Delivery(
            target="vercel", url="https://prev.vercel.app", status="rolled_back"),
    )

    delivery_path = tmp_path / "delivery.json"
    delivery_path.write_text(
        Delivery(target="vercel", url="https://app.example", status="deployed").to_json(),
        encoding="utf-8")
    out_path = tmp_path / "prod-verdict.json"

    result = CliRunner().invoke(main, [
        "postdeploy", "--delivery", str(delivery_path),
        "--health-path", "/api/health", "--rollback",
        "--repo", str(tmp_path), "--out", str(out_path),
    ])

    assert result.exit_code != 0          # BLOCK still fails the stage
    verdict = Verdict.from_json(out_path.read_text(encoding="utf-8"))
    assert verdict.status == "BLOCK"
    assert verdict.raw["rollback"]["status"] == "rolled_back"
    assert any("rollback triggered" in r for r in verdict.reasons)


def test_postdeploy_cli_no_rollback_by_default(monkeypatch, tmp_path):
    class Response:
        status = 500

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, n):
            return b"down"

    monkeypatch.setattr("sembl_stack.adapters.postdeploy_http.urlopen",
                        lambda req, timeout: Response())

    called = []
    monkeypatch.setattr(
        "sembl_stack.adapters.deploy_vercel.VercelDeployAdapter.rollback",
        lambda self, repo, **kw: called.append(repo),
    )

    delivery_path = tmp_path / "delivery.json"
    delivery_path.write_text(
        Delivery(target="vercel", url="https://app.example", status="deployed").to_json(),
        encoding="utf-8")
    out_path = tmp_path / "prod-verdict.json"

    result = CliRunner().invoke(main, [
        "postdeploy", "--delivery", str(delivery_path),
        "--health-path", "/api/health", "--repo", str(tmp_path), "--out", str(out_path),
    ])

    assert result.exit_code != 0
    assert called == []                   # default = no rollback fired
    verdict = Verdict.from_json(out_path.read_text(encoding="utf-8"))
    assert "rollback" not in verdict.raw

