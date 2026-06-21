# SPEC — L8 rollback trigger (post-deploy BLOCK → Vercel rollback)

> Pinned, owner-authored spec. Implement it EXACTLY. Mirror the existing **deploy** stage
> (`sembl_stack/adapters/deploy_vercel.py`, the `deploy`/`postdeploy` CLI commands). Do NOT
> invent new patterns, rename fields, or change signatures. Keep all 77 existing tests green and
> add the 4 new ones. After implementing, run `.venv\Scripts\python.exe -m pytest -q` and confirm
> **81 passed, 1 skipped** before finishing.

## 0. Why
The chain is `… → merge → deploy (L7) → post-deploy gate (L8)`. Today L8 (`HttpPostDeployGate`)
already returns a `BLOCK` Verdict when a deployed app is unhealthy — but **nothing reacts to it**.
This spec adds the reaction: when the post-deploy gate BLOCKs, the spine fires a **Vercel
rollback** (promote the previous good production deployment) and records the rollback outcome in
the production `Verdict`.

Two locked design rules you MUST preserve:
1. **The gate stays mechanism-free and deterministic.** Do NOT call Vercel from inside
   `HttpPostDeployGate.verify`. The gate only judges health and returns a Verdict.
2. **The rollback mechanism lives on the deploy adapter** (`VercelDeployAdapter`), because deploy
   and rollback are both Vercel-CLI operations (forward + reverse are symmetric). The **trigger**
   (the "if BLOCK, roll back" decision) lives in the `postdeploy` CLI command and is **opt-in**
   behind a `--rollback` flag so default behavior — and every existing test — is unchanged.

## 1. New adapter method — `VercelDeployAdapter.rollback` (in `sembl_stack/adapters/deploy_vercel.py`)
Add a `rollback` method to the existing `VercelDeployAdapter` class. Mirror the existing `deploy`
method exactly: same `_tail` / `_safe_command` helpers (reuse them — do NOT duplicate),
same `data` dict shape, same timeout/redaction discipline, capture-output via `subprocess.run`
so tests can monkeypatch it. Place it directly **after** the `deploy` method:

```python
    def rollback(self, repo: str, *, to: str | None = None) -> Delivery:
        """Promote the previous production deployment (Vercel rollback).

        Mechanism only: the decision to roll back is the caller's (the L8 gate Verdict).
        `to` optionally names a specific deployment URL/id to roll back to; omitted, Vercel
        reverts to the immediately previous production deployment.
        """
        repo_path = str(Path(repo).resolve())
        cmd = ["vercel", "rollback"]
        if to:
            cmd.append(to)
        if self.yes:
            cmd.append("--yes")

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            return Delivery(
                target="vercel",
                status="rollback_failed",
                data={
                    "reason": "timeout",
                    "latency_s": round(time.perf_counter() - t0, 3),
                    "command": _safe_command(cmd),
                    "stdout": _tail(exc.stdout),
                    "stderr": _tail(exc.stderr),
                },
            )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        url = _last_url(stdout) or _last_url(stderr)
        status = "rolled_back" if proc.returncode == 0 else "rollback_failed"
        return Delivery(
            target="vercel",
            url=url,
            status=status,
            data={
                "rolled_back_to": to,
                "returncode": proc.returncode,
                "latency_s": round(time.perf_counter() - t0, 3),
                "command": _safe_command(cmd),
                "stdout": _tail(stdout),
                "stderr": _tail(stderr),
            },
        )
```
Do NOT add new imports — `Path`, `subprocess`, `time`, `Delivery`, `_last_url`, `_tail`,
`_safe_command` are all already in this module.

## 2. Protocol — `DeployAdapter` (in `sembl_stack/adapters/base.py`)
Add the `rollback` method to the existing `DeployAdapter` Protocol so the capability is part of
the deploy-layer contract (do NOT create a new Protocol):
```python
@runtime_checkable
class DeployAdapter(Protocol):       # L7: Verdict(PASS) -> Delivery; rollback reverts it
    def deploy(self, repo: str, *, production: bool = False,
               prebuilt: bool = False) -> Delivery:
        ...

    def rollback(self, repo: str, *, to: str | None = None) -> Delivery:
        ...
```

## 3. CLI — `sembl_stack/cli.py` `postdeploy` command
Modify the existing `postdeploy` command to add the opt-in rollback trigger. The signature gains
`--rollback/--no-rollback` (default **off**) and `--repo` (needed to locate the linked Vercel
project for the rollback call). Replace the existing `postdeploy` command body with EXACTLY:

```python
@main.command()
@click.option("--delivery", "delivery_path", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--health-path", default="/", show_default=True)
@click.option("--timeout", "timeout_s", default=10.0, show_default=True, type=float)
@click.option("--rollback/--no-rollback", "do_rollback", default=False,
              help="On a BLOCK verdict, fire a rollback via the deploy adapter (promote previous).")
@click.option("--repo", default=".", help="Repo dir for the rollback call (linked Vercel project).")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None, help="Write the production Verdict artifact here.")
def postdeploy(delivery_path, health_path, timeout_s, do_rollback, repo, config_path, out):
    """L8: Delivery -> Verdict. Deterministic post-deploy health gate (+ optional rollback)."""
    delivery = _read_delivery(delivery_path)
    cfg = load(config_path if Path(config_path).is_file() else None)
    verdict = cfg.postdeploy.verify(delivery, health_path=health_path, timeout_s=timeout_s)

    # L8 rollback trigger: a BLOCK means the live deploy is bad — revert it. Opt-in so default
    # behavior is unchanged. The rollback outcome is recorded in the prod Verdict, never hidden.
    if do_rollback and verdict.status == "BLOCK":
        rollback = cfg.deploy.rollback(repo)
        verdict.raw["rollback"] = rollback.to_dict()
        verdict.reasons.append(f"rollback triggered: {rollback.status}")

    _emit(verdict, out)
    raise SystemExit(0 if verdict.status in ("PASS", "WARN") else 1)
```
Notes:
- The exit code is unchanged: a BLOCK still exits non-zero even after a successful rollback — the
  deploy *was* bad; rollback is remediation, not a pass.
- The module-docstring usage block (top of `cli.py`) may optionally gain a `--rollback` note on
  the `postdeploy` line; do not change anything else.

## 4. Tests — `tests/test_deploy_postdeploy.py` (extend the existing file)
Append these **4** tests to the existing file. Reuse the existing import block at the top (it
already imports `SimpleNamespace`, `CliRunner`, `VercelDeployAdapter`, `HttpPostDeployGate`,
`Delivery`, `Verdict`, `main`). Use EXACTLY these:

```python
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
```

## 5. Acceptance
- `.venv\Scripts\python.exe -m pytest -q` → **81 passed, 1 skipped** (77 prior + 4 new).
- No secret/token ever appears in a rollback `Delivery` (the `token` assertion covers it).
- `--rollback` is strictly opt-in: with it off, a BLOCK verdict triggers no rollback call
  (the `no_rollback_by_default` test locks this).

## 6. Do NOT
- Do NOT call Vercel (or any network/promote) from inside `HttpPostDeployGate.verify` — the gate
  stays deterministic and mechanism-free.
- Do NOT change the `deploy` or `merge` CLI commands, the gate logic, or any existing test.
- Do NOT make rollback automatic/default-on, change the exit-code semantics, or rename
  `rollback`, the `--rollback` flag, the `rolled_back` / `rollback_failed` status strings, or the
  `verdict.raw["rollback"]` key.
- Do NOT perform a real network or destructive action in tests (subprocess.run / urlopen / the
  rollback method are all monkeypatched).
