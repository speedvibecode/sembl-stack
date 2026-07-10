"""O12 artifact contract: `Acceptance` + `AcceptanceReport` (sembl_stack/artifacts.py).

Mirrors the discuss.py `SCHEMA_KEYS` coercion discipline: a malformed AcceptanceCheck
dict is dropped silently, never raised — a hand-edited acceptance.json or a bad O8
proposal must not crash the loop.
"""
from __future__ import annotations

from sembl_stack import artifacts
from sembl_stack.artifacts import Acceptance, AcceptanceReport


def test_acceptance_roundtrip_drops_malformed_check():
    good = {"id": "c1", "kind": "example", "profile": "command",
            "run": {"command": "true"}, "expect": {"exit_code": 0},
            "seed": None, "timeout_s": 30}
    missing_id = {"kind": "example"}
    bad_kind = {"id": "c2", "kind": "bogus"}
    not_a_dict = "nope"

    acc = Acceptance(checks=[good, missing_id, bad_kind, not_a_dict],
                     sources=["acceptance.json"])
    assert len(acc.checks) == 1
    assert acc.checks[0]["id"] == "c1"
    assert acc.checks[0]["timeout_s"] == 30

    again = artifacts.from_dict(acc.to_dict())
    assert isinstance(again, Acceptance)
    assert len(again.checks) == 1
    assert again.checks[0]["id"] == "c1"
    assert again.sources == ["acceptance.json"]


def test_acceptance_to_contract_surfaces_only_id_kind_profile():
    acc = Acceptance(checks=[
        {"id": "c1", "kind": "example", "profile": "command",
         "run": {"command": "true"}, "expect": {}},
    ])
    contract = acc.to_contract()
    assert contract == {"checks": [{"id": "c1", "kind": "example", "profile": "command"}]}
    # the run/expect internals never leak into the gate-facing contract shape
    assert "run" not in contract["checks"][0]
    assert "expect" not in contract["checks"][0]


def test_acceptance_check_timeout_absence_preserved_and_clamped():
    # Absence is DATA here: the artifact records what was declared, and the runner
    # applies its profile-specific default_timeout. A default injected at coercion
    # would silently override every runner profile's (that bug shipped once).
    acc = Acceptance(checks=[
        {"id": "a", "kind": "example"},                          # no timeout_s -> None (runner defaults)
        {"id": "b", "kind": "invariant", "timeout_s": 99999},     # over the cap -> clamped
        {"id": "c", "kind": "property", "timeout_s": -5},         # invalid -> None (runner defaults)
    ])
    assert acc.checks[0]["timeout_s"] is None
    assert acc.checks[1]["timeout_s"] == 600
    assert acc.checks[2]["timeout_s"] is None


def test_acceptance_check_profile_defaults_to_command_and_rejects_unknown():
    acc = Acceptance(checks=[
        {"id": "a", "kind": "example"},                            # no profile -> "command"
        {"id": "b", "kind": "example", "profile": "carrier-pigeon"},  # unknown -> dropped
    ])
    assert len(acc.checks) == 1
    assert acc.checks[0]["profile"] == "command"


def test_acceptance_report_any_failed_and_roundtrip():
    all_pass = AcceptanceReport(results=[{"id": "a", "outcome": "PASS"}])
    assert all_pass.any_failed is False

    with_fail = AcceptanceReport(
        results=[{"id": "a", "outcome": "PASS"}, {"id": "b", "outcome": "FAIL"}],
        runner="command@1")
    assert with_fail.any_failed is True

    with_error = AcceptanceReport(results=[{"id": "a", "outcome": "ERROR"}])
    assert with_error.any_failed is True

    again = artifacts.from_dict(with_fail.to_dict())
    assert isinstance(again, AcceptanceReport)
    assert again.any_failed is True
    assert again.runner == "command@1"


def test_acceptance_report_empty_is_not_failed():
    assert AcceptanceReport().any_failed is False


def test_malformed_check_with_id_stays_declared_as_invalid():
    # Lead review fix: a malformed check that still has a usable id must not silently
    # vanish from the contract — it stays declared (kind "invalid") so the gate's
    # declared-vs-ran integrity check BLOCKs on it. Only an id-less blob is dropped.
    acc = Acceptance(checks=[
        {"id": "good", "kind": "example"},
        {"id": "typo-kind", "kind": "exmaple"},     # malformed but identifiable
        {"kind": "example"},                          # id-less: truly droppable
    ])
    assert [c["id"] for c in acc.checks] == ["good"]
    assert acc.invalid_ids == ["typo-kind"]
    declared = acc.to_contract()["checks"]
    assert {"id": "typo-kind", "kind": "invalid", "profile": "command"} in declared

    # invalid_ids must survive a JSON round-trip.
    again = artifacts.from_dict(acc.to_dict())
    assert again.invalid_ids == ["typo-kind"]


def test_corrupt_acceptance_json_fails_closed(tmp_path):
    # Lead review fix: acceptance.json PRESENT but unreadable is not "no contract" —
    # it returns a contract whose synthetic invalid entry the gate will BLOCK on.
    from sembl_stack.config import load_acceptance

    (tmp_path / "acceptance.json").write_text("{not json", encoding="utf-8")
    acc = load_acceptance(str(tmp_path))
    assert acc is not None
    assert acc.checks == []
    assert len(acc.invalid_ids) == 1 and "acceptance.json" in acc.invalid_ids[0]
    assert acc.to_contract()["checks"][0]["kind"] == "invalid"


def test_absent_and_empty_acceptance_json_stay_no_op(tmp_path):
    from sembl_stack.config import load_acceptance

    assert load_acceptance(str(tmp_path)) is None            # no file at all
    (tmp_path / "acceptance.json").write_text('{"checks": []}', encoding="utf-8")
    assert load_acceptance(str(tmp_path)) is None            # well-formed, zero checks
