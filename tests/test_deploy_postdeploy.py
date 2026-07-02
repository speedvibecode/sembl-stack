from types import SimpleNamespace

from click.testing import CliRunner

from sembl_stack.adapters.deploy_vercel import VercelDeployAdapter, _last_url
from sembl_stack.adapters.postdeploy_http import HttpPostDeployGate
from sembl_stack.artifacts import Delivery, Verdict
from sembl_stack.cli import _resolve_config, main


def test_resolve_config_prefers_cwd_then_falls_back_to_repo(tmp_path):
    """`deploy`/`postdeploy` take --repo separate from CWD (orchestrating a target repo
    from elsewhere is supported) — a bare default config must still find the *target
    repo's* config, not silently fall back to built-in defaults, when --repo != CWD.
    Live-proof finding: running postdeploy from the sembl-stack root against the flagship
    example silently loaded no config and skipped its expect_json health contract."""
    repo_dir = tmp_path / "target-repo"
    repo_dir.mkdir()
    (repo_dir / "some.stack.yaml").write_text("layers: {}\n", encoding="utf-8")

    # Not found anywhere -> None (caller's `load(None)` uses built-in defaults).
    assert _resolve_config("some.stack.yaml", str(tmp_path / "nowhere")) is None

    # Found only under --repo (the common case when CWD isn't the target repo).
    assert _resolve_config("some.stack.yaml", str(repo_dir)) == str(
        repo_dir / "some.stack.yaml")

    # An explicit path that already exists (e.g. CWD-relative) wins outright.
    cwd_cfg = tmp_path / "explicit.yaml"
    cwd_cfg.write_text("layers: {}\n", encoding="utf-8")
    assert _resolve_config(str(cwd_cfg), str(repo_dir)) == str(cwd_cfg)


def test_last_url_prefers_the_deployment_over_dashboard_and_api_links():
    """Real `vercel --prod --yes` output observed in a live-proof run (2026-07-01): stdout
    interleaves a `vercel.com` dashboard "Inspect" link and (on some CLI versions) an
    `api.vercel.com` status-poll call alongside the actual `*.vercel.app` deployment URL.
    Picking the textually-last match without filtering returned the dashboard/API link
    instead — silently pointing every downstream health check at the wrong host."""
    stdout = (
        "Vercel CLI 54.6.1 (Node.js 20.19.4)\n"
        "🔍  Inspect: https://vercel.com/speedvibecodes-projects/"
        "sembl-flagship-feedback-board/8mFDrkVKsNwwaC3TPTVrNv49kfLf [2s]\n"
        "✅  Production: https://sembl-flagship-feedback-board-hr152fgvo-"
        "speedvibecodes-projects.vercel.app [33s]\n"
    )
    assert _last_url(stdout) == (
        "https://sembl-flagship-feedback-board-hr152fgvo-speedvibecodes-projects.vercel.app")

    # Observed variant: a trailing api.vercel.com status-poll line, quoted, textually last.
    noisy = stdout + '{"url":"https://api.vercel.com/v13/deployments/dpl_6JSNofSiZMp1qy1xjciFtVes53GZ"}\n'
    assert _last_url(noisy) == (
        "https://sembl-flagship-feedback-board-hr152fgvo-speedvibecodes-projects.vercel.app")

    # No .vercel.app match at all -> falls back to whatever URL there is.
    assert _last_url("only https://vercel.com/team/project/dpl_x here") == (
        "https://vercel.com/team/project/dpl_x")

    assert _last_url(None) is None
    assert _last_url("") is None


def test_resolve_vercel_wraps_windows_shims(monkeypatch):
    from sembl_stack.adapters import deploy_vercel as dv

    monkeypatch.setattr(dv.shutil, "which", lambda _: r"C:\x\vercel.CMD")
    assert dv._resolve_vercel() == ["cmd", "/c", r"C:\x\vercel.CMD"]

    monkeypatch.setattr(dv.shutil, "which", lambda _: r"C:\x\vercel.ps1")
    assert dv._resolve_vercel()[:2] == ["powershell", "-NoProfile"]

    monkeypatch.setattr(dv.shutil, "which", lambda _: "/usr/local/bin/vercel")
    assert dv._resolve_vercel() == ["/usr/local/bin/vercel"]

    monkeypatch.setattr(dv.shutil, "which", lambda _: None)
    assert dv._resolve_vercel() == []


def test_vercel_deploy_adapter_captures_url_without_secret(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout="Preview: https://feedback-board.vercel.app\n",
            stderr="",
        )

    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel._resolve_vercel", lambda: ["vercel"])
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


def test_http_postdeploy_redacts_response_body(monkeypatch):
    """A 500 health body must never be serialized raw into the artifact."""
    secret = "TOKEN_sk_live_LEAKED_abc123"

    class Response:
        status = 500

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, n):
            return (secret + " internal error").encode("utf-8")[:n]

    monkeypatch.setattr("sembl_stack.adapters.postdeploy_http.urlopen",
                        lambda req, timeout: Response())

    verdict = HttpPostDeployGate().verify(
        Delivery(target="vercel", url="https://app.example", status="deployed"),
        health_path="/api/health")

    assert verdict.status == "BLOCK"
    assert secret not in verdict.to_json()                # content redacted...
    assert verdict.raw["body"]["sha256"]                  # ...fingerprint kept


def test_postdeploy_config_threads_payload_contract(monkeypatch, tmp_path):
    """options.postdeploy.expect_json must be enforced by default (no CLI flag needed)."""
    from sembl_stack.config import load

    cfg_path = tmp_path / "sembl.stack.yaml"
    cfg_path.write_text(
        "layers: {postdeploy: http}\n"
        "options:\n  postdeploy:\n    health_path: /api/health\n"
        "    expect_json: {ok: true, supabaseConfigured: true}\n",
        encoding="utf-8")
    cfg = load(str(cfg_path))
    assert cfg.postdeploy.health_path == "/api/health"
    assert cfg.postdeploy.expect_json == {"ok": True, "supabaseConfigured": True}

    # A 200 that fails the contract (supabaseConfigured:false) must BLOCK via config alone.
    monkeypatch.setattr(
        "sembl_stack.adapters.postdeploy_http.urlopen",
        lambda req, timeout: _json_response(200, {"ok": True, "supabaseConfigured": False})(),
    )
    verdict = cfg.postdeploy.verify(
        Delivery(target="vercel", url="https://app.example", status="deployed"))
    assert verdict.status == "BLOCK"
    assert "payload mismatch" in verdict.reasons[0]


def test_deploy_cli_refuses_block_verdict(tmp_path):
    verdict_path = tmp_path / "verdict.json"
    verdict_path.write_text(Verdict(status="BLOCK").to_json(), encoding="utf-8")

    result = CliRunner().invoke(main, [
        "deploy", "--verdict", str(verdict_path), "--repo", str(tmp_path),
    ])

    assert result.exit_code != 0
    assert "refusing to deploy a BLOCK" in result.output


def test_vercel_rollback_resolves_and_promotes_previous(monkeypatch, tmp_path):
    """No `to` given: must look up the previous production deployment and target it
    explicitly. Locks in the live-proof finding that bare `vercel rollback` (no target)
    only reports rollback *status* on current CLI versions — it never rolls anything back."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1:] == ["ls", "--prod"]:
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "  Age   Project   Deployment   Status\n"
                    "  5m    x         https://feedback-board-bad123.vercel.app   Ready\n"
                    "  10d   x         https://feedback-board-good999.vercel.app  Ready\n"
                    "\n"
                    "https://feedback-board-bad123.vercel.app\n"
                    "https://feedback-board-good999.vercel.app\n"
                ),
                stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout="Success! Rolled back to https://feedback-board-good999.vercel.app\n",
            stderr="",
        )

    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel._resolve_vercel", lambda: ["vercel"])
    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel.subprocess.run", fake_run)

    delivery = VercelDeployAdapter(timeout=5).rollback(str(tmp_path))

    assert delivery.status == "rolled_back"
    assert delivery.url == "https://feedback-board-good999.vercel.app"
    assert calls[0] == ["vercel", "ls", "--prod"]
    assert calls[1] == ["vercel", "rollback", "https://feedback-board-good999.vercel.app", "--yes"]
    assert "token" not in delivery.to_json().lower()


def test_vercel_rollback_explicit_target_skips_lookup(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(
            returncode=0,
            stdout="Success! Rolled back to https://feedback-board.vercel.app\n",
            stderr="",
        )

    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel._resolve_vercel", lambda: ["vercel"])
    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel.subprocess.run", fake_run)

    delivery = VercelDeployAdapter(timeout=5).rollback(
        str(tmp_path), to="https://feedback-board.vercel.app")

    assert delivery.status == "rolled_back"
    assert calls == [["vercel", "rollback", "https://feedback-board.vercel.app", "--yes"]]


def test_vercel_rollback_no_previous_deployment(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(
            returncode=0,
            stdout="https://feedback-board-onlyone.vercel.app\n",
            stderr="",
        )

    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel._resolve_vercel", lambda: ["vercel"])
    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel.subprocess.run", fake_run)

    delivery = VercelDeployAdapter(timeout=5).rollback(str(tmp_path))

    assert delivery.status == "rollback_failed"
    assert delivery.data["reason"] == "no previous production deployment found"
    assert len(calls) == 1                # never attempts a rollback with nothing to target


def test_vercel_rollback_records_failure(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        if cmd[1:] == ["ls", "--prod"]:
            return SimpleNamespace(
                returncode=0,
                stdout="https://a.vercel.app\nhttps://b.vercel.app\n",
                stderr="",
            )
        return SimpleNamespace(returncode=1, stdout="", stderr="no previous deployment")

    monkeypatch.setattr("sembl_stack.adapters.deploy_vercel._resolve_vercel", lambda: ["vercel"])
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

