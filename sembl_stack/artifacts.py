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


# --- The seven artifacts (PLATFORM-MAP §2) ------------------------------------

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


# ExecutionResult is the legacy name for Change; kept so existing adapters import cleanly.
ExecutionResult = Change

KINDS = {c.KIND: c for c in (Task, Context, Bounds, Change, Verdict, Trace, Delivery)}


def from_dict(d: dict):
    """Reconstruct the right artifact from a tagged dict (uses `_kind`)."""
    kind = d.get("_kind")
    cls = KINDS.get(kind)
    if cls is None:
        raise ValueError(f"unknown artifact kind: {kind!r}")
    return cls.from_dict(d)
