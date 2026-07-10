"""The event bus (`D5`) — one append-only `.sembl/bus.jsonl` per repo.

Generalizes the per-run `events.jsonl` pattern (`store.py`) to a repo-wide, cross-process
feed: engine stages publish typed events here; any subscriber (operator wrapper, IDE
extension, `tail -f`) reads from a byte-offset cursor. File-based because it must cross
process boundaries (a VS Code extension is a separate process from the Python engine) and
survive crashes.

Never raises: a bus write/read failure can never affect the loop or the gate (mirrors
`store.Run.append_event`'s own never-raise contract).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

BUS_PATH = ".sembl/bus.jsonl"   # repo-relative, like .sembl/runs/

# Closed set for this build (SPEC-O11 §2.2). An event with any other `kind` (or none) is
# rewritten to kind="other" with the original value preserved under `raw_kind`.
_KNOWN_KINDS = {
    "run.started", "run.stage", "run.verdict", "run.finished",
    "drift.new", "deploy.status", "postdeploy.status", "other",
}


def publish(root: Path, event: dict) -> None:
    """Append one event line to `<root>/.sembl/bus.jsonl`. NEVER raises (mirror
    `store.append_event`): a bus write failure can never affect the loop or the gate.

    Injects `ts` (`time.time()`) and validates `event["kind"]` against the closed kind
    set; an unknown/missing kind is written as `kind="other"` with the original value
    preserved under `raw_kind`. Creates the `.sembl` directory if missing. One `f.write`
    call per event, `encoding="utf-8"`.
    """
    try:
        ev = dict(event)
        kind = ev.get("kind")
        if kind not in _KNOWN_KINDS:
            ev["raw_kind"] = kind
            ev["kind"] = "other"
        ev["ts"] = time.time()
        path = Path(root) / BUS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        # default=str: a non-serializable value in `data` (a Path, an exception) must
        # degrade to its string form, not silently drop the whole event.
        line = json.dumps(ev, ensure_ascii=False, default=str)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def read_since(root: Path, cursor: int = 0) -> tuple[list[dict], int]:
    """Read events after byte-offset `cursor`; return `(events, new_cursor)`.

    Reads in binary so byte offsets are exact on Windows (CRLF risk sidestepped by
    splitting on b"\\n" directly rather than relying on text-mode universal newlines).
    A torn/corrupt trailing line — the file ends mid-write, with no terminating
    newline yet — is skipped WITHOUT advancing the cursor past it, so the next call
    retries it once the writer finishes the line. A corrupt but complete (newline-
    terminated) line is skipped but the cursor DOES advance past it. Missing file =>
    `([], 0)`. Never raises.
    """
    try:
        path = Path(root) / BUS_PATH
        if not path.is_file():
            return [], 0
        with path.open("rb") as f:
            f.seek(cursor)
            data = f.read()
    except Exception:
        return [], cursor

    if not data:
        return [], cursor

    events: list[dict] = []
    consumed = 0
    start = 0
    while True:
        idx = data.find(b"\n", start)
        if idx == -1:
            break                              # remaining bytes are a torn trailing line
        raw_line = data[start:idx]
        consumed += (idx - start) + 1          # + the newline itself
        start = idx + 1
        if not raw_line.strip():
            continue
        try:
            events.append(json.loads(raw_line.decode("utf-8", errors="replace")))
        except Exception:
            pass                                # corrupt but complete: skip, cursor still advances

    return events, cursor + consumed
