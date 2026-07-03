"""RSI-L1 readout — measured selection over a synthetic run store.

Locks in the honesty rules: every aggregate traces back to persisted run-store artifacts,
iterations-to-green comes from the per-attempt verdict artifacts, and cost is reported ONLY
where an executor recorded usage — old/usage-less runs read "not yet recorded", never a number.
"""
from __future__ import annotations

import json

from click.testing import CliRunner

from sembl_stack import rsi
from sembl_stack.artifacts import Verdict
from sembl_stack.cli import main
from sembl_stack.store import RunStore


def _mk_run(store, *, agent, statuses, cost=None, tokens=None, model=None,
            latency=1.0, final=None):
    """A synthetic run: one attempts_log entry + one verdict artifact per attempt."""
    run = store.new_run()
    for i, status in enumerate(statuses, start=1):
        run.record_attempt(i, latency_s=latency, agent=agent, model=model,
                           cost=cost, tokens=tokens)
        run.put(Verdict(status=status), name=f"verdict-{i}")
    final = final or statuses[-1]
    run.put(Verdict(status=final))
    run.set_status(final, attempts=len(statuses),
                   total_latency_s=round(latency * len(statuses), 3))
    return run


def test_iters_to_green_is_first_accepted_verdict(tmp_path):
    store = RunStore(str(tmp_path))
    run = _mk_run(store, agent="claude-code", statuses=["BLOCK", "BLOCK", "PASS"])
    rec = rsi.run_record(store.open(run.id))
    assert rec["status"] == "PASS"
    assert rec["attempts"] == 3
    assert rec["iters_to_green"] == 3


def test_blocked_run_has_no_iters_to_green(tmp_path):
    store = RunStore(str(tmp_path))
    run = _mk_run(store, agent="claude-code", statuses=["BLOCK", "BLOCK"])
    rec = rsi.run_record(store.open(run.id))
    assert rec["status"] == "BLOCK"
    assert rec["iters_to_green"] is None


def test_warn_counts_as_accepted_but_separately(tmp_path):
    store = RunStore(str(tmp_path))
    _mk_run(store, agent="aider", statuses=["WARN"])
    summary = rsi.aggregate(store)
    (e,) = summary["executors"]
    assert e["warn"] == 1 and e["pass"] == 0
    assert e["green_rate"] == 1.0
    assert e["iters_to_green"]["mean"] == 1


def test_aggregate_groups_by_executor_and_never_invents_cost(tmp_path):
    store = RunStore(str(tmp_path))
    # claude: usage recorded on one run, absent on the other — cost covers ONLY the first.
    _mk_run(store, agent="claude-code", statuses=["PASS"], cost=0.02, tokens=1000,
            model="haiku")
    _mk_run(store, agent="claude-code", statuses=["BLOCK", "PASS"])
    # opencode: never reported usage.
    _mk_run(store, agent="opencode", statuses=["BLOCK"], model="tokenrouter/MiniMax-M3")

    summary = rsi.aggregate(store)
    by = {e["executor"]: e for e in summary["executors"]}
    assert summary["n_runs"] == 3
    assert set(by) == {"claude-code", "opencode"}

    cc = by["claude-code"]
    assert cc["runs"] == 2 and cc["pass"] == 2 and cc["block"] == 0
    assert cc["green_rate"] == 1.0
    assert cc["iters_to_green"]["mean"] == 1.5      # (1 + 2) / 2
    assert cc["cost_usd"] == {"runs_recorded": 1, "total": 0.02}
    assert cc["tokens"] == {"runs_recorded": 1, "total": 1000}
    assert cc["models"] == ["haiku"]

    oc = by["opencode"]
    assert oc["block_rate"] == 1.0 and oc["green_rate"] == 0.0
    assert oc["cost_usd"]["total"] is None          # nothing recorded -> no number

    text = rsi.render(summary)
    assert "claude-code" in text and "opencode" in text
    assert "not yet recorded" in text               # the honest cost line
    assert "0.02" in text


def test_run_without_agent_lands_in_unrecorded_bucket(tmp_path):
    store = RunStore(str(tmp_path))
    run = store.new_run()
    run.set_status("failed", attempts=0)            # e.g. a crash before any attempt
    summary = rsi.aggregate(store)
    (e,) = summary["executors"]
    assert e["executor"] == rsi.UNKNOWN_EXECUTOR
    assert e["other"] == 1


def test_empty_store_renders_hint(tmp_path):
    summary = rsi.aggregate(RunStore(str(tmp_path)))
    assert summary["n_runs"] == 0
    assert "no runs recorded yet" in rsi.render(summary)


def test_cli_rsi_table_and_json(tmp_path):
    store = RunStore(str(tmp_path))
    _mk_run(store, agent="claude-code", statuses=["PASS"], cost=0.01)
    runner = CliRunner()

    r = runner.invoke(main, ["rsi", "--repo", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "RSI-L1" in r.output and "claude-code" in r.output

    r = runner.invoke(main, ["rsi", "--repo", str(tmp_path), "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["n_runs"] == 1
    assert data["executors"][0]["cost_usd"]["total"] == 0.01
