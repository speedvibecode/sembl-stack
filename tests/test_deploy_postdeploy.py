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
