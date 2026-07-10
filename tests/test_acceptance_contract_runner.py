"""O12 WP4: the `contract` acceptance runner adapter + its Foundry live-proof.

`contract` is a thin profile-specific layer over `CommandAcceptanceRunner` (WP2):
it adds a Foundry (`forge`) toolchain preflight (fail-closed, actionable ERROR), a
longer default timeout (a `forge test` invariant/fuzz campaign can run far longer
than a bare command), and pins a declared `seed` onto a `forge` invocation as
`--fuzz-seed <seed>` for deterministic replay. Everything else (shim resolution,
evidence scrubbing, expect-matching, never-reject) is inherited unchanged from the
already-proven command machinery.

The planted-break test is the real given/when/then flow against
`examples/contract-invariant`: it drives the actual runner via a real `forge test`
invocation, temporarily doubling `Vault.sol`'s deposit accounting (a one-line
accounting bug: `totalDeposited += msg.value * 2` instead of `+= msg.value`) so the
cap invariant breaks under fuzzing, and restores the original file in a `finally` —
the break exists ONLY for the duration of this test and is never committed. It is
skipped when `forge` is not on PATH (this dev box does not have Foundry installed
by default; see the WP4 report for the exact live-proof commands run with it
temporarily on PATH).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sembl_stack.adapters import acceptance_command as ac_mod
from sembl_stack.adapters import acceptance_contract as ac_contract_mod
from sembl_stack.adapters.acceptance_contract import ContractAcceptanceRunner
from sembl_stack.artifacts import Acceptance

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _REPO_ROOT / "examples" / "contract-invariant"
_VAULT_SOL = _FIXTURE / "src" / "Vault.sol"
_GOOD_ACCOUNTING = "totalDeposited += msg.value;"
_BROKEN_ACCOUNTING = "totalDeposited += msg.value * 2;"


class _Sandbox:
    def __init__(self, workdir):
        self.workdir = workdir


def _check(cid, command, expect=None, seed=None, timeout_s=90):
    return {"id": cid, "kind": "invariant", "profile": "contract",
            "run": {"command": command}, "expect": expect or {},
            "seed": seed, "timeout_s": timeout_s}


def _bypass_forge_preflight(monkeypatch):
    """`forge` genuinely is not on this dev box's PATH; these pure exit-code tests
    exercise the inherited command machinery, not the toolchain preflight itself, so
    fake only the `forge` lookup (this module's own `shutil.which`) and leave every
    other name resolving through the REAL `shutil.which` — `shutil` is a singleton
    module, so patching it here affects every `import shutil` reference process-
    wide; a blanket `lambda *_: None` would also break the base runner's shim
    resolution for `sys.executable`."""
    real_which = ac_contract_mod.shutil.which
    monkeypatch.setattr(
        ac_contract_mod.shutil, "which",
        lambda name: "C:/fake/forge.exe" if name == "forge" else real_which(name))


def test_contract_runner_exit_zero_is_pass(monkeypatch):
    _bypass_forge_preflight(monkeypatch)
    runner = ContractAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "ok", [sys.executable, "-c", "print('hi')"], {"exit_code": 0})])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "PASS"
    assert report.runner == "contract@1"
    assert report.any_failed is False


def test_contract_runner_exit_nonzero_is_fail(monkeypatch):
    _bypass_forge_preflight(monkeypatch)
    runner = ContractAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "bad", [sys.executable, "-c", "import sys; sys.exit(1)"], {"exit_code": 0})])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "FAIL"
    assert "exit_code" in r["detail"]
    assert report.any_failed is True


def test_contract_runner_missing_forge_errors_with_actionable_detail(monkeypatch):
    # Simulate an environment with no Foundry toolchain on PATH, without
    # uninstalling anything: monkeypatch the module's own `shutil.which` lookup.
    monkeypatch.setattr(ac_contract_mod.shutil, "which", lambda name: None)
    runner = ContractAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "needs-forge", [sys.executable, "-c", "print(1)"], {"exit_code": 0})])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "ERROR"
    assert "forge" in r["detail"].lower()
    assert "install" in r["detail"].lower()


def test_contract_runner_rejects_check_with_no_command():
    runner = ContractAcceptanceRunner()
    acc = Acceptance(checks=[_check("no-cmd", None)])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "ERROR"
    assert "run.command" in r["detail"]


def test_contract_runner_pins_and_forwards_fuzz_seed(monkeypatch):
    # `forge` doesn't need to really be installed for this test: fake the
    # `forge` lookup so it resolves to a deterministic fake path (both the
    # toolchain preflight AND the base runner's shim resolution see the same
    # `shutil.which`, since `shutil` is a singleton module — one patch covers
    # both call sites and keeps this hermetic regardless of whether `forge`
    # really is on this box's PATH) and capture the argv the base runner
    # actually hands to `subprocess.run` (the cleanest seam — mirrors
    # `test_command_runner_never_rejects_on_internal_crash`'s pattern of
    # monkeypatching the base module's subprocess entry point).
    monkeypatch.setattr(
        ac_contract_mod.shutil, "which",
        lambda name: "C:/fake/forge.exe" if name == "forge" else None)

    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(ac_mod.subprocess, "run", fake_run)

    runner = ContractAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "seeded", ["forge", "test", "--match-contract", "VaultInvariant"],
        {"exit_code": 0}, seed=42)])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "PASS"
    assert r["seed"] == 42
    assert "--fuzz-seed" in captured["argv"]
    assert "42" in captured["argv"]


def test_contract_runner_no_seed_declared_gets_no_fuzz_seed_flag(monkeypatch):
    monkeypatch.setattr(
        ac_contract_mod.shutil, "which",
        lambda name: "C:/fake/forge.exe" if name == "forge" else None)

    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(ac_mod.subprocess, "run", fake_run)

    runner = ContractAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "unseeded", ["forge", "test", "--match-contract", "VaultInvariant"],
        {"exit_code": 0}, seed=None)])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "PASS"
    assert r["seed"] is None
    assert "--fuzz-seed" not in captured["argv"]


def test_contract_runner_never_injects_fuzz_seed_into_non_forge_command(monkeypatch):
    # A seeded check whose command is NOT a forge invocation must not get a
    # foundry-specific flag appended to an arbitrary command.
    monkeypatch.setattr(
        ac_contract_mod.shutil, "which",
        lambda name: "C:/fake/forge.exe" if name == "forge" else None)

    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(ac_mod.subprocess, "run", fake_run)

    runner = ContractAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "seeded-not-forge", [sys.executable, "-c", "print(1)"],
        {"exit_code": 0}, seed=7)])
    report = runner.run(acc, _Sandbox("."), task=None, bounds=None)

    r = report.results[0]
    assert r["outcome"] == "PASS"
    assert r["seed"] == 7
    assert "--fuzz-seed" not in captured["argv"]


@pytest.mark.skipif(shutil.which("forge") is None, reason="requires Foundry (forge) on PATH")
def test_contract_runner_planted_break_fails_real_invariant():
    """The real given/when/then flow, driven through the actual runner: Given the
    Vault contract's deposit accounting matches the amount actually transferred,
    When it is planted to double-count each deposit (a one-line in-bounds
    accounting bug) and the invariant is fuzzed via a real `forge test` invocation,
    Then the runner reports FAIL because totalDeposited exceeds CAP."""
    assert _VAULT_SOL.is_file(), "contract fixture file missing"
    original = _VAULT_SOL.read_text(encoding="utf-8")
    assert original.count(_GOOD_ACCOUNTING) == 1, "fixture assumption changed upstream"
    broken = original.replace(_GOOD_ACCOUNTING, _BROKEN_ACCOUNTING)
    assert broken != original

    runner = ContractAcceptanceRunner()
    acc = Acceptance(checks=[_check(
        "vault-invariant-holds",
        ["forge", "test", "--match-contract", "VaultInvariant"],
        {"exit_code": 0}, seed=42, timeout_s=300)])

    try:
        _VAULT_SOL.write_text(broken, encoding="utf-8")
        report = runner.run(acc, _Sandbox(str(_FIXTURE)), task=None, bounds=None)
    finally:
        _VAULT_SOL.write_text(original, encoding="utf-8")

    r = report.results[0]
    assert r["outcome"] == "FAIL"
