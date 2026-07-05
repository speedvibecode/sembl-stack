"""Track 5 item 3 — ambient fused graph + drift daemon (advisory, never a gate).

Fuses the SpecGraph (doc side) with a live CBM code graph via the existing, unchanged
`reconcile_spec_code` (reconciliation.py) and adds the one thing that function doesn't have:
memory across checks. A bare `reconcile` call re-derives the same DIVERGENT/ALIGNED verdict
every time with no notion of "already told the owner about this." `check_drift` persists a
small state file (`.sembl/drift-state.json` by default) keyed by a stable finding fingerprint,
so repeated ambient checks only ever surface what's genuinely NEW since the last review
checkpoint — the "cheap immediate flag" from docs/SPEC-ideation-and-chat-shell.md §3 /
PROCESS-ACTION-PLAN.md Track 5 item 3.

Correction vs. the plan text as first written: that doc assumed the "flag" would be a CBM
`manage_adr` entry. Empirically (probed 2026-07-05 against a disposable scratch project),
`manage_adr` is a single whole-project architecture document (PURPOSE/STACK/ARCHITECTURE/
PATTERNS/TRADEOFFS/PHILOSOPHY sections, read/replace-wholesale, not an append-only log).
Overwriting that on every drift tick would be neither cheap (a CBM subprocess round-trip)
nor safe (it would clobber any real architecture notes already stored there). The local
state file is the actual cheap+immediate flag; `manage_adr` stays reserved for Track 5 item
4's `mark exception` (a genuine, human-issued permanent decision) — not built here.

"Ambient" here means "cheap enough to call at every natural checkpoint" (opening the IDE,
`drift-check`, a pre-commit hook) — not a literal always-running OS process. Nothing in this
module starts a background thread or watches the filesystem.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import ReconciliationReport, SpecGraph
from .reconciliation import reconcile_spec_code

STATE_SCHEMA_VERSION = 1
DEFAULT_STATE_PATH = ".sembl/drift-state.json"

# Only these finding severities are genuine drift signal worth tracking across checks;
# "info" findings (scope_without_code_match, missing_code_graph) are FYI-only noise today
# (see reconciliation.py) and would make every ambient check "new" forever on any repo
# whose code graph is simply absent.
_DRIFT_SEVERITIES = {"warn"}


def finding_key(finding: dict) -> str:
    """A stable fingerprint for a finding, used to detect NEW vs. already-seen drift."""
    return "|".join([
        str(finding.get("kind", "")),
        str(finding.get("spec_node", "")),
        str(finding.get("message", "")),
    ])


@dataclass
class DriftCheck:
    """The result of one `check_drift` call — what changed since the last check."""
    report: ReconciliationReport
    new: list[dict] = field(default_factory=list)       # never flagged before
    pending: list[dict] = field(default_factory=list)   # unacknowledged (new + carried over)
    resolved: list[dict] = field(default_factory=list)  # drift that disappeared since last check


def _load_state(state_path: Path) -> dict:
    if not state_path.is_file():
        return {"schema_version": STATE_SCHEMA_VERSION, "findings": {}}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": STATE_SCHEMA_VERSION, "findings": {}}
    if not isinstance(data, dict) or not isinstance(data.get("findings"), dict):
        return {"schema_version": STATE_SCHEMA_VERSION, "findings": {}}
    return data


def _save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def check_drift(spec_graph: SpecGraph, code_graph: dict, *,
                 state_path: str | Path = DEFAULT_STATE_PATH) -> DriftCheck:
    """Reconcile spec vs. code, diff against the persisted state, flag what's new.

    Never raises, never blocks — advisory like every other reconcile call (a bad/missing
    code graph degrades to `reconcile_spec_code`'s own UNKNOWN report, not an exception here).
    Persists the updated state as a side effect (a single-file overwrite, not append-only).
    """
    report = reconcile_spec_code(spec_graph, code_graph)
    path = Path(state_path)
    state = _load_state(path)
    prior: dict = state["findings"]

    now = datetime.now(timezone.utc).isoformat()
    current = {
        finding_key(f): f
        for f in report.findings
        if f.get("severity") in _DRIFT_SEVERITIES
    }

    new: list[dict] = []
    pending: list[dict] = []
    next_findings: dict = {}
    for key, finding in current.items():
        entry = prior.get(key)
        if entry is None:
            acknowledged = False
            first_detected = now
            new.append(finding)
        else:
            acknowledged = bool(entry.get("acknowledged", False))
            first_detected = entry.get("first_detected", now)
        next_findings[key] = {
            "finding": finding,
            "first_detected": first_detected,
            "last_seen": now,
            "acknowledged": acknowledged,
        }
        if not acknowledged:
            pending.append(finding)

    resolved = [entry["finding"] for key, entry in prior.items() if key not in current]

    state["findings"] = next_findings
    state["generated_at"] = now
    _save_state(path, state)

    return DriftCheck(report=report, new=new, pending=pending, resolved=resolved)


def pending_drift(*, state_path: str | Path = DEFAULT_STATE_PATH) -> list[dict]:
    """Read-only: everything currently unacknowledged, without recomputing reconciliation."""
    state = _load_state(Path(state_path))
    return [e["finding"] for e in state["findings"].values() if not e.get("acknowledged")]


def acknowledge_drift(keys: list[str] | None = None, *,
                       state_path: str | Path = DEFAULT_STATE_PATH) -> int:
    """Mark pending findings as reviewed (a batched review checkpoint).

    `keys=None` acknowledges everything currently pending. Returns the count newly
    acknowledged (already-acknowledged or unknown keys are no-ops, not errors).
    """
    path = Path(state_path)
    state = _load_state(path)
    target = set(keys) if keys is not None else set(state["findings"])
    count = 0
    for key, entry in state["findings"].items():
        if key in target and not entry.get("acknowledged"):
            entry["acknowledged"] = True
            count += 1
    _save_state(path, state)
    return count
