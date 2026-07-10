"""The artifact contract — the substrate the whole platform stands on.

Artifacts are the *only* thing stages agree on. They are plain dataclasses that are
JSON-serializable and round-trippable, so a run can be inspected, resumed, or entered
at any stage by supplying the right artifact. (See docs/PLATFORM-MAP.md §2.)

Stages transform artifacts: `inputs (typed artifacts) -> output (typed artifact)`.
Enter anywhere you can supply the inputs; exit anywhere you want the output.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

ARTIFACT_VERSION = 1


class _Serializable:
    """Mixin: JSON round-trip for any dataclass artifact. `KIND` tags the payload."""
    KIND = "artifact"

    def to_dict(self) -> dict:
        d = asdict(self)               # dataclass fields only; KIND is a class attr
        d["_kind"] = self.KIND
        d["_v"] = ARTIFACT_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict):
        fields = {k: v for k, v in d.items() if not k.startswith("_")}
        return cls(**fields)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str):
        return cls.from_dict(json.loads(s))


# --- Artifacts ---------------------------------------------------------------

@dataclass
class Task(_Serializable):
    """What the user wants. `repo` is the target working copy."""
    KIND = "task"
    text: str
    repo: str
    spec_path: str | None = None


@dataclass
class Context(_Serializable):
    """Repo intelligence + pulled knowledge (L1/Brain). Optional in the short loop."""
    KIND = "context"
    summary: str = ""
    files: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class SpecGraph(_Serializable):
    """Graph form of the spec for advisory spec/code reconciliation."""
    KIND = "specgraph"
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class Bounds(_Serializable):
    """The governed scope of a change — the four-field contract Sembl verifies."""
    KIND = "bounds"
    editable_paths: list[str] = field(default_factory=list)
    forbidden_areas: list[str] = field(default_factory=list)
    churn_budget: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)

    def to_contract(self) -> dict:
        """The shape `sembl verify --wo-file` consumes (no metadata)."""
        return {
            "editable_paths": self.editable_paths,
            "forbidden_areas": self.forbidden_areas,
            "churn_budget": self.churn_budget,
        }


_ACCEPTANCE_CHECK_KINDS = ("example", "property", "invariant")
_ACCEPTANCE_CHECK_PROFILES = ("command", "web", "contract")
_ACCEPTANCE_MAX_TIMEOUT_S = 600   # declared timeouts are capped here; DEFAULTS live in the runners


def _coerce_acceptance_check(raw) -> dict | None:
    """One AcceptanceCheck dict -> a validated dict, or `None` if malformed.

    Same coercion discipline as `discuss.py`'s `SCHEMA_KEYS`: a check that's missing a
    required field or shaped wrong is DROPPED here, never raised — a malformed check
    (hand-edited acceptance.json, a bad O8 proposal) must never crash the loop; it
    simply doesn't run and isn't counted as declared.
    """
    if not isinstance(raw, dict):
        return None
    cid = raw.get("id")
    kind = raw.get("kind")
    if not isinstance(cid, str) or not cid.strip():
        return None
    if kind not in _ACCEPTANCE_CHECK_KINDS:
        return None
    profile = raw.get("profile", "command")
    if profile not in _ACCEPTANCE_CHECK_PROFILES:
        return None
    run = raw.get("run")
    run = dict(run) if isinstance(run, dict) else {}
    expect = raw.get("expect")
    expect = dict(expect) if isinstance(expect, dict) else {}
    seed = raw.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        seed = None
    timeout_s = raw.get("timeout_s")
    if not isinstance(timeout_s, int) or isinstance(timeout_s, bool) or timeout_s <= 0:
        # Absent (or unusably declared) stays None: the declaration layer records
        # what was declared; the RUNNER owns execution policy, so its
        # profile-specific `default_timeout` applies (command 120s, web 300s). A
        # default injected here would silently override every profile's.
        timeout_s = None
    else:
        timeout_s = min(timeout_s, _ACCEPTANCE_MAX_TIMEOUT_S)
    return {
        "id": cid,
        "kind": kind,
        "profile": profile,
        "description": str(raw.get("description") or ""),
        "run": run,
        "expect": expect,
        "seed": seed,
        "timeout_s": timeout_s,
    }


@dataclass
class Acceptance(_Serializable):
    """The declared behavioral contract (O12). Sibling to `Bounds`: Bounds governs
    *where* a change may go; Acceptance governs *what must hold*. Produced at plan
    time / spec time, consumed by the runner (L4.5) and the gate (L5)."""
    KIND = "acceptance"
    checks: list[dict] = field(default_factory=list)   # AcceptanceCheck dicts
    sources: list[str] = field(default_factory=list)
    # Declared-but-unusable check ids (malformed kind/shape, corrupt source file).
    # These stay DECLARED in `to_contract()` so the gate's declared-vs-ran integrity
    # check BLOCKs on them — a contract entry we cannot run must fail closed, never
    # silently vanish (the O8 drop-malformed discipline is for LLM *proposals*; a
    # human-authored contract is never silently narrowed).
    invalid_ids: list[str] = field(default_factory=list)

    def __post_init__(self):
        # Coerce on construction (including from_dict, which calls cls(**fields)) so a
        # malformed check never survives into a round-trip or into the runner/gate.
        # A malformed check that still carries a usable id is remembered in
        # `invalid_ids` (fail-closed); only an id-less blob is truly droppable
        # (there is nothing to declare it by).
        kept: list[dict] = []
        dropped: list[str] = list(self.invalid_ids)   # survive a from_dict round-trip
        for raw in self.checks:
            c = _coerce_acceptance_check(raw)
            if c is not None:
                kept.append(c)
                continue
            rid = raw.get("id") if isinstance(raw, dict) else None
            if isinstance(rid, str) and rid.strip():
                dropped.append(rid.strip())
        self.checks = kept
        self.invalid_ids = list(dict.fromkeys(dropped))

    def to_contract(self) -> dict:
        """The shape the gate consumes for the declared-vs-ran integrity check: just
        the check ids + kinds, never the run/expect internals. Invalid-but-identifiable
        checks are declared too — the runner produces no result for them, so the gate's
        `behavioral_missing` integrity check BLOCKs (fail-closed by design)."""
        return {"checks": [{"id": c["id"], "kind": c["kind"],
                            "profile": c.get("profile", "command")}
                           for c in self.checks]
                + [{"id": iid, "kind": "invalid", "profile": "command"}
                   for iid in self.invalid_ids]}


@dataclass
class AcceptanceReport(_Serializable):
    """The runner's deterministic output (L4.5) — never a gate verdict itself, just
    the declared checks' outcomes for the gate to fold."""
    KIND = "acceptance_report"
    results: list[dict] = field(default_factory=list)   # AcceptanceResult dicts
    runner: str = ""                                     # adapter id + version
    data: dict = field(default_factory=dict)

    @property
    def any_failed(self) -> bool:
        return any(r.get("outcome") in ("FAIL", "ERROR") for r in self.results)


@dataclass
class Spec(_Serializable):
    """L0.5 output — the reviewed product spec/PRD (Track 5, see
    docs/SPEC-ideation-and-chat-shell.md). The doc a fused graph would eventually
    reconcile everything else against. Only authoritative once a human has
    reviewed/edited every field — see `ideation.py`."""
    KIND = "spec"
    pitch: str = ""
    stack: str = ""
    stack_why: str = ""
    data_model: str = ""
    non_goals: list[str] = field(default_factory=list)
    questions_resolved: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)


@dataclass
class Change(_Serializable):
    """What the executor produced, in the sandbox: a diff + its (untrusted) report."""
    KIND = "change"
    diff: str
    report: dict = field(default_factory=dict)
    workdir: str = ""


@dataclass
class Verdict(_Serializable):
    """The gate's deterministic answer."""
    KIND = "verdict"
    status: str = "BLOCK"              # PASS | WARN | BLOCK
    reasons: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.status == "BLOCK"

    def feedback(self) -> str:
        """A nudge the executor can act on, on retry."""
        if not self.reasons:
            return ""
        return ("Your previous attempt was blocked. Fix these and stay in scope:\n- "
                + "\n- ".join(self.reasons))


@dataclass
class ReconciliationReport(_Serializable):
    """Advisory spec/code drift report; never a gate verdict."""
    KIND = "reconciliation_report"
    status: str = "UNKNOWN"
    summary: str = ""
    findings: list[dict] = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class ReviewReport(_Serializable):
    """Advisory code-quality review signal (L5.5). Never a gate verdict."""
    KIND = "review_report"
    reviewer: str = ""
    status: str = "UNKNOWN"           # CLEAN | FINDINGS | UNKNOWN
    findings: list[dict] = field(default_factory=list)  # {severity, kind, file, message}
    data: dict = field(default_factory=dict)


@dataclass
class Trace(_Serializable):
    """Observability: the ordered steps of a run (L6)."""
    KIND = "trace"
    steps: list[dict] = field(default_factory=list)


@dataclass
class Delivery(_Serializable):
    """Deploy record (Plane B / L7-L8). Defined now, used in Phase 2+."""
    KIND = "delivery"
    target: str = ""
    url: str | None = None
    status: str = "pending"
    data: dict = field(default_factory=dict)


@dataclass
class MergeRecord(_Serializable):
    """Gated-merge record (L6.5). PASS/WARN -> merged; BLOCK -> held."""
    KIND = "merge_record"
    target_branch: str = ""
    source_ref: str = ""
    commit: str | None = None          # merge/HEAD sha when status == "merged"
    status: str = "pending"            # merged | held | failed
    data: dict = field(default_factory=dict)


def diff_sha256(diff: str) -> str:
    """The content hash that binds a Verdict to the exact diff it judged."""
    import hashlib
    return hashlib.sha256((diff or "").encode("utf-8")).hexdigest()


def bind_verdict(verdict: Verdict, diff: str) -> Verdict:
    """Bind a Verdict to the change it judged (deep-audit item 1).

    Without this, `merge`/`apply` accept ANY PASS verdict file — a verdict issued
    for one change could green-light merging another. `subject` records the judged
    diff's hash + file set so merge/apply can verify they act on the same change.
    Mutates and returns the same Verdict."""
    files = verdict.raw.get("changed_files")
    if not isinstance(files, list):
        try:
            from sembl.validator import parse_unified_diff
            files = parse_unified_diff(diff)[0]
        except Exception:
            files = []
    verdict.raw["subject"] = {
        "diff_sha256": diff_sha256(diff),
        "files": sorted(files),
    }
    return verdict


# ExecutionResult is the legacy name for Change; kept so existing adapters import cleanly.
ExecutionResult = Change

KINDS = {c.KIND: c for c in (
    Task, Context, SpecGraph, Spec, Bounds, Change, Verdict, ReconciliationReport,
    ReviewReport, Trace, Delivery, MergeRecord, Acceptance, AcceptanceReport)}


def from_dict(d: dict):
    """Reconstruct the right artifact from a tagged dict (uses `_kind`)."""
    kind = d.get("_kind")
    cls = KINDS.get(kind)
    if cls is None:
        raise ValueError(f"unknown artifact kind: {kind!r}")
    return cls.from_dict(d)
