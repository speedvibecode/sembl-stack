"""The guided surface — what bare `sembl-stack` launches.

The owner's UX spec (2026-07-04): guide the user step by step in the cleanest
possible manner, like the Claude Code / Codex CLIs. Those tools are NOT
full-screen apps — they are inline prompts in the user's own terminal: arrow-key
pick lists, a text input, output that scrolls naturally. This module is exactly
that (the 2026-07-04 full-screen Textual attempt was rejected as slop):

  repo   — confirm the cwd repo; a non-git dir is offered the safe demo scaffold
  agent  — one arrow-key list of every way to run AI work, with LIVE status and
           the concrete fix for anything missing (mock always works, zero keys)
  task   — plain-English task + which paths the agent may touch (prefilled from
           the repo); the tool writes task.yaml / bounds.json, the user never does
  run    — stage lines stream as they happen, then the verdict + the one next command

All judgment stays in the deterministic cores (profile.py, runner.py, the gate);
this module only prompts and prints. A guided run and a headless
`sembl-stack loop` are byte-identical — same adapters, same artifacts.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import click
import yaml

from . import onboarding, profile, registry, runner, scaffold
from .artifacts import diff_sha256
from .config import DEFAULTS
from .store import RunStore

try:
    import questionary
    from questionary import Choice
    _HAVE_QUESTIONARY = True
except ImportError:                  # pragma: no cover — questionary is a core dep
    _HAVE_QUESTIONARY = False


def available() -> bool:
    return _HAVE_QUESTIONARY


# --------------------------------------------------------------------------- pure core


@dataclass
class Provider:
    """One row of the agent list: live detection + what's needed if missing."""
    runner: str          # profile runner id
    label: str
    ok: bool
    status: str          # e.g. "found: C:\\...\\claude.CMD" / "ANTHROPIC_API_KEY set"
    hint: str = ""       # what to do when not ok


_NOISE_DIRS = {"node_modules", "dist", "build", "target", "__pycache__", "venv"}


def detect_providers(environ=None) -> list[Provider]:
    """Live status for every way sembl-stack can run AI work. Pure given `environ`."""
    env = os.environ if environ is None else environ
    rows: list[Provider] = []

    claude = shutil.which("claude")
    rows.append(Provider(
        "claude-login", "Claude Code (your login)", claude is not None,
        f"found: {claude}" if claude else "not found on PATH",
        "" if claude else "install Claude Code, then run `claude` once to log in"))

    set_vars = [v for v in profile._KEY_ENV_VARS if env.get(v)]
    rows.append(Provider(
        "api-key", "API key (env var)", bool(set_vars),
        f"{set_vars[0]} is set" if set_vars else
        f"none of {', '.join(profile._KEY_ENV_VARS)} are set",
        "" if set_vars else "set one (e.g. $env:ANTHROPIC_API_KEY = \"...\") and relaunch"))

    opencode = shutil.which("opencode")
    rows.append(Provider(
        "local", "OpenCode (local/BYO model)", opencode is not None,
        f"found: {opencode}" if opencode else "not found on PATH",
        "" if opencode else "install OpenCode and ensure `opencode` is on PATH"))

    rows.append(Provider(
        "mock", "No AI — preview the mechanics", True,
        "always available (deterministic demo executor)"))
    return rows


def repo_state(path: str) -> tuple[Path, bool]:
    """Resolve the target directory and whether it's a git repo."""
    root = Path(path).resolve()
    return root, (root / ".git").exists()


def suggest_editable(repo: Path) -> list[str]:
    """Bounds suggestion: the repo's top-level directories, noise excluded."""
    if not repo.is_dir():
        return []
    return sorted(
        f"{p.name}/" for p in repo.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in _NOISE_DIRS)


def parse_paths(raw: str) -> list[str]:
    """'app/, src/lib' -> ['app/', 'src/lib'] (whitespace/empties dropped)."""
    return [p.strip() for p in raw.split(",") if p.strip()]


def write_task_and_bounds(repo: Path, text: str, editable: list[str],
                          forbidden: list[str]) -> None:
    """Persist the step-3 answers as the loop's artifacts. Tool-owned files."""
    if not text.strip():
        raise ValueError("describe the task first")
    if not editable:
        raise ValueError("give the agent at least one editable path")
    (repo / "task.yaml").write_text(
        json.dumps({"text": text.strip(), "repo": "."}), encoding="utf-8")
    (repo / "bounds.json").write_text(json.dumps({
        "editable_paths": editable,
        "forbidden_areas": forbidden,
        "churn_budget": {"max_files": 20, "max_lines": 1000},
    }, indent=2), encoding="utf-8")


def _candidate_paths(root: Path, depth: int = 2) -> list[str]:
    """Repo paths (two levels deep, noise excluded) — the 'did you mean' pool."""
    out: list[str] = []

    def walk(d: Path, level: int) -> None:
        try:
            entries = list(d.iterdir())
        except OSError:
            return
        for p in entries:
            if p.name.startswith(".") or p.name in _NOISE_DIRS:
                continue
            rel = p.relative_to(root).as_posix()
            if p.is_dir():
                out.append(rel + "/")
                if level < depth:
                    walk(p, level + 1)
            else:
                out.append(rel)

    walk(root, 1)
    return out


def path_typo_hint(root: Path, paths: list[str]) -> str | None:
    """'did you mean' for a path that doesn't exist when something close does.

    Bounds pointing at a typo'd directory silently constrain the agent to nothing —
    catch it at the prompt. Genuinely-new paths (no close match) are allowed through.
    """
    import difflib
    candidates = None
    for raw in paths:
        norm = raw.strip().rstrip("/").replace("\\", "/")
        if not norm or (root / norm).exists():
            continue
        if candidates is None:
            candidates = _candidate_paths(root)
        close = (difflib.get_close_matches(norm + "/", candidates, n=1)
                 or difflib.get_close_matches(norm, candidates, n=1))
        if close:
            return f"{raw.strip()} doesn't exist — did you mean {close[0]}?"
    return None


_LAYER_DESC = {
    "spec": "task text -> editable/forbidden bounds",
    "execute": "the agent that actually writes the diff",
    "sandbox": "disposable clone the executor writes into",
    "verify": "judge the real diff against bounds (the gate)",
    "context": "widen bounds along a coupling graph (opt-in)",
    "review": "a second opinion on the diff (advisory, never blocks)",
    "merge": "PASS verdict -> merge commit",
    "deploy": "merged -> live delivery",
    "postdeploy": "delivery -> health verdict",
}
_LAYER_ORDER = ["spec", "execute", "sandbox", "verify", "context", "review",
                "merge", "deploy", "postdeploy"]


def existing_layers_config(root: Path) -> dict:
    """The repo's sembl.stack.yaml as a dict, or {} if absent/unreadable."""
    path = root / "sembl.stack.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_layers_config(root: Path, *, context: str, review: str, strict: bool) -> None:
    """Merge these layer choices into the repo's sembl.stack.yaml (creates it if absent).

    Tool-owned like task.yaml/bounds.json, but merged rather than overwritten: an existing
    file's other keys (options, transport, merge/deploy overrides a user hand-edited) survive.
    """
    data = existing_layers_config(root)
    layers = dict(data.get("layers") or {})
    layers["context"] = context
    layers["review"] = review
    data["layers"] = layers
    loop_cfg = dict(data.get("loop") or {})
    loop_cfg["strict"] = strict
    data["loop"] = loop_cfg
    (root / "sembl.stack.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _layers_step(root: Path, prof, *, reconfigure: bool) -> bool:
    """Show the full layer breakdown, one row per stage this factory runs; let the
    user pick the layers that are genuinely swappable today (context, review) plus
    the verify strictness toggle. Everything else has one real option — shown, not
    hidden, so the swappable shape of the factory stays visible even before a second
    adapter exists for it. Returns False on Ctrl-C/Esc."""
    existing = existing_layers_config(root)
    layers_cfg = existing.get("layers", {}) or {}
    cur_context = layers_cfg.get("context", DEFAULTS["layers"].get("context", "none"))
    cur_review = layers_cfg.get("review", DEFAULTS["layers"].get("review", "mock"))
    cur_strict = (existing.get("loop", {}) or {}).get("strict", prof.strict)

    if (root / "sembl.stack.yaml").is_file() and not reconfigure:
        _dim("  layers: configured (`sembl-stack --reconfigure` to change; "
             "`sembl-stack layers` lists every adapter)")
        return True

    click.echo()
    click.secho("  layers", bold=True)
    _dim("  every stage this factory runs, and what's swappable today:")
    for layer in _LAYER_ORDER:
        opts = registry.names(layer)
        desc = _LAYER_DESC[layer]
        if layer == "execute":
            _dim(f"    {layer:10} {desc:<44} -> {prof.executor}  (chosen above)")
        elif layer in ("context", "review", "verify"):
            continue                                    # prompted below
        else:
            adapter = opts[0] if opts else "?"
            _dim(f"    {layer:10} {desc:<44} -> {adapter}  (only option today)")
    click.echo()

    context = questionary.select(
        "context (L1) — widen bounds along a coupling graph before execute?",
        choices=[Choice(title=n, value=n) for n in registry.names("context")],
        default=cur_context).ask()
    if context is None:
        return False
    review = questionary.select(
        "review (L5.5) — a second opinion on the diff, offered after a run?",
        choices=[Choice(title=n, value=n) for n in registry.names("review")],
        default=cur_review).ask()
    if review is None:
        return False
    strict = questionary.confirm(
        "verify (L5) — strict gate (reject any out-of-bounds edit)?",
        default=cur_strict).ask()
    if strict is None:
        return False
    write_layers_config(root, context=context, review=review, strict=strict)
    return True


def _paths_prompt(task_text: str, candidates: list[str], *,
                  kind: str = "editable", editable: list[str] | None = None) -> str:
    listing = "\n".join(candidates[:400])
    common = (
        "You are SCOPING a code-change task, not implementing it. Do not edit, create, "
        "or delete any files.\n\n"
        f"Task: {task_text}\n\n"
        f"Repo paths (partial listing, relative to repo root):\n{listing}\n\n")
    if kind == "forbidden":
        scope = (f"The agent will already be limited to editing: {', '.join(editable)}.\n\n"
                 if editable else "")
        return (common + scope +
                "Reply with ONLY a comma-separated list of paths this agent must NOT "
                "touch even if it could — secrets/.env files, CI/deploy config, "
                "lockfiles, infra, build output, or anything else outside this task's "
                "real scope. If nothing in the listing looks sensitive, reply with "
                "an empty string. No prose, no explanation, no markdown.")
    return (common +
            "Reply with ONLY a comma-separated list of the paths (prefer top-level "
            "directories, end directories with '/') the agent should be allowed to edit "
            "to do this task. No prose, no explanation, no markdown — just the list.")


def _suggest_cmd(executor: str, prompt: str, model: str | None) -> list[str] | None:
    """The one-shot, read-only argv for asking `executor` to scope a task, or None if
    that executor has no headless query mode / isn't installed."""
    if executor == "claude":
        exe = shutil.which("claude")
        if not exe:
            return None
        # No --dangerously-skip-permissions here (unlike execute_claude.py): this call
        # is advisory-only and runs against the REAL repo, not a sandbox, so any
        # attempted write must fall back to an approval prompt instead of proceeding —
        # which, with stdin=DEVNULL, fails fast rather than mutating the repo.
        cmd = [exe, "-p", "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)
        return cmd
    if executor == "opencode":
        from .adapters.execute_opencode import _resolve_opencode
        launcher = _resolve_opencode()
        if not launcher:
            return None
        p = prompt
        if launcher[0].lower() == "cmd":
            p = " ".join(p.splitlines())
        cmd = launcher + ["run", "--pure", p]
        if model:
            cmd += ["--model", model]
        return cmd
    return None


def _extract_result_text(executor: str, out: str) -> str:
    if executor == "claude":
        try:
            data = json.loads(out)
        except (ValueError, TypeError):
            return out
        if isinstance(data, dict) and isinstance(data.get("result"), str):
            return data["result"]
    return out


def _parse_ai_paths(root: Path, text: str) -> list[str]:
    """The model's answer, filtered down to paths that actually exist in the repo —
    a hallucinated path is silently dropped rather than reaching the bounds prompt."""
    candidates = _candidate_paths(root)
    by_norm = {c.rstrip("/"): c for c in candidates}
    line = next((l for l in reversed(text.strip().splitlines()) if l.strip()), "")
    out: list[str] = []
    for raw in line.split(","):
        p = raw.strip().strip("`'\"").rstrip("/")
        if p and p in by_norm and by_norm[p] not in out:
            out.append(by_norm[p])
    return out


def ai_suggest_paths(root: Path, executor: str, task_text: str,
                      model: str | None = None, timeout: int = 60, *,
                      kind: str = "editable", editable: list[str] | None = None
                      ) -> list[str] | None:
    """Best-effort AI suggestion for editable OR forbidden paths (`kind`). Never
    raises — any failure (no binary, timeout, empty/unparseable reply, nothing
    survives filtering) yields None so the caller always has the manual entry to
    fall back on."""
    candidates = _candidate_paths(root)
    if not candidates:
        return None
    prompt = _paths_prompt(task_text, candidates, kind=kind, editable=editable)
    cmd = _suggest_cmd(executor, prompt, model)
    if cmd is None:
        return None
    from .adapters.base import run_executor
    try:
        rc, out, err, timed_out = run_executor(cmd, cwd=str(root), timeout=timeout)
    except Exception:
        return None
    if timed_out or rc != 0 or not out.strip():
        return None
    return _parse_ai_paths(root, _extract_result_text(executor, out)) or None


def existing_answers(repo: Path) -> tuple[str, str, str]:
    """Prefill the task step from artifacts of a previous run (text, editable, forbidden)."""
    text, editable, forbidden = "", "", ""
    task_file = repo / "task.yaml"
    if task_file.is_file():
        try:
            import yaml
            text = (yaml.safe_load(task_file.read_text(encoding="utf-8")) or {}).get(
                "text", "") or ""
        except Exception:
            pass
    bounds_file = repo / "bounds.json"
    if bounds_file.is_file():
        try:
            data = json.loads(bounds_file.read_text(encoding="utf-8-sig"))
            editable = ", ".join(data.get("editable_paths", []))
            forbidden = ", ".join(data.get("forbidden_areas", []))
        except Exception:
            pass
    return text, editable, forbidden


_STAGE_LABEL = {
    "plan": "bounds     declare the contract",
    "execute": "execute    the agent writes (sandboxed)",
    "verify": "gate       judge the real diff",
}

_LIVE_MARK = {"running": ">", "done": "+", "fail": "x"}

# the runner's live StageEvents use the rail names: "bounds" | "sandbox" | "loop" | "verify"
_STAGE_NAME = {"bounds": "bounds", "sandbox": "sandbox", "loop": "execute", "verify": "gate",
               "plan": "bounds", "execute": "execute"}


def diff_stat(diff: str) -> tuple[list[tuple[str, int, int]], int, int]:
    """Parse a unified diff into [(path, added, removed), ...] and (total+, total-).

    The 'what changed' summary the owner asked to see live — per file, without
    dumping raw hunks into the terminal (the full diff lives in change.json).
    """
    files: dict[str, list[int]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            if path != "/dev/null":
                current = path
                files.setdefault(current, [0, 0])
            continue
        if line.startswith("diff --git"):
            current = None
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            files[current][0] += 1
        elif line.startswith("-") and not line.startswith("---"):
            files[current][1] += 1
    rows = [(p, a, r) for p, (a, r) in files.items()]
    return rows, sum(a for _, a, _ in rows), sum(r for _, _, r in rows)


def diff_summary_lines(diff: str, *, max_files: int = 12) -> list[str]:
    """Indented 'changed files' block for the run output. Empty diff -> no lines."""
    rows, total_add, total_rem = diff_stat(diff)
    if not rows:
        return []
    width = min(max(len(p) for p, _, _ in rows), 52)
    lines: list[str] = []
    for path, add, rem in rows[:max_files]:
        shown = path if len(path) <= 52 else "…" + path[-51:]
        lines.append(f"       {shown:<{width}}  +{add} -{rem}")
    if len(rows) > max_files:
        lines.append(f"       … and {len(rows) - max_files} more file(s)")
    noun = "file" if len(rows) == 1 else "files"
    lines.append(f"       {len(rows)} {noun} changed, +{total_add} -{total_rem}")
    return lines


def rail_text(live: dict) -> str:
    lines = []
    for stage in ("plan", "execute", "verify"):
        state = live.get(stage, {})
        mark = _LIVE_MARK.get(state.get("state", ""), " ")
        detail = state.get("detail", "")
        suffix = f"   {detail}" if detail else ""
        lines.append(f"  [{mark}] {_STAGE_LABEL[stage]}{suffix}")
    return "\n".join(lines)


def context_status_line(cfg) -> str:
    """The honest L1 rail line, printed once before the attempt loop starts.

    `_maybe_expand` (loop.py) only ever widens bounds when the adapter is
    configured, `loop.expand_bounds` is on, AND the adapter reports itself
    available — otherwise it's a silent no-op today. Rather than let L1 vanish
    from the rail entirely when that's true (the "direct jump" the owner flagged
    2026-07-04), say so plainly instead of fabricating activity that didn't happen.
    """
    name = (cfg.raw.get("layers", {}) or {}).get("context", "none")
    expand = bool((cfg.raw.get("loop", {}) or {}).get("expand_bounds", False))
    g = cfg.context
    if g is None or name == "none":
        return "  [·] context     none configured — skipped"
    if not expand:
        return (f"  [·] context     {name} configured, not widening bounds this run "
               "(loop.expand_bounds: false)")
    if not getattr(g, "available", lambda: False)():
        return f"  [·] context     {name} configured but unavailable — skipped"
    return f"  [+] context     widening bounds via {name}"


def event_line(ev) -> str | None:
    """One scrolling terminal line per stage event, Claude-Code style.

    Sub-second stages only print their outcome; only `execute` (the slow, agent-run
    stage) announces that it started, so the user sees WHY the terminal is waiting.
    """
    name = _STAGE_NAME.get(ev.stage, ev.stage)
    if ev.state == "running":
        if name != "execute":
            return None
        detail = ev.detail or "agent writing (sandboxed)"
        return f"  [ ] execute    {detail}…"
    mark = "+" if ev.state == "done" else "x"
    detail = f"   {ev.detail}" if ev.detail else ""
    return f"  [{mark}] {name:<10}{detail}"


def verdict_text(result) -> str:
    v = result.verdict
    n = result.attempts
    lines = [f"  {v.status}  (after {n} attempt{'s' if n != 1 else ''})"]
    reasons = getattr(v, "reasons", []) or []
    if reasons:
        lines.append("")
    for r in reasons:
        lines.append(f"  - {r}")
    if result.run_id:
        lines += ["", f"  receipt: .sembl/runs/{result.run_id}/"]
        if v.status in ("PASS", "WARN"):
            lines.append(f"  apply:   sembl-stack apply {result.run_id}")
    return "\n".join(lines)


# ------------------------------------------------------------------- the inline flow


def _dim(text: str) -> None:
    click.secho(text, fg="bright_black")


def launch(repo: str = ".", *, reconfigure: bool = False) -> None:
    if not _HAVE_QUESTIONARY:
        raise RuntimeError(
            "the guided run needs the `questionary` package (a core dependency) — "
            "reinstall with `pip install sembl-stack`")
    root, is_git = repo_state(repo)

    click.echo()
    click.secho("  sembl-stack", bold=True, nl=False)
    _dim("  —  a task, an agent, a gate. one guided run.")
    _dim(f"  repo: {root}")
    click.echo()

    root, is_git = _repo_step(root, is_git)
    if root is None:
        return
    prof = _agent_step(reconfigure)
    if prof is None:
        return
    if not _layers_step(root, prof, reconfigure=reconfigure):
        return

    # a persistent session: describe a task, watch it run, then fire another —
    # the owner stays in the cockpit and monitors run after run
    while True:
        if not _task_step(root, prof):
            return
        result = _run_step(root)
        if _after_run(root, result) != "again":
            return


def _repo_step(root: Path, is_git: bool) -> tuple[Path | None, bool]:
    if is_git:
        return root, True
    ok = questionary.confirm(
        "This isn't a git repository. Set up the safe demo scaffold here?",
        default=True).ask()
    if not ok:
        _dim("  the loop clones your repo into a sandbox, so it needs git —")
        _dim("  run inside a git repo (or `git init` + commit) and relaunch.")
        return None, False
    for msg in scaffold.scaffold_demo(root):
        _dim(f"    {msg}")
    click.echo()
    return repo_state(str(root))


def _agent_step(reconfigure: bool):
    prof = profile.load()
    if prof is not None and not reconfigure:
        ok, _ = profile.ready(profile.preflight(prof))
        if ok:
            _dim(f"  agent: {prof.runner}  (saved — `sembl-stack --reconfigure` "
                 "to change)")
            return prof

    while True:
        choices = []
        for p in detect_providers():
            status = p.status if p.ok else f"{p.status} — {p.hint}"
            choices.append(Choice(
                title=f"{p.label:<30} {status}", value=p.runner,
                disabled=None if p.ok else p.hint))
        picked = questionary.select(
            "How should AI work run?", choices=choices,
            instruction="(status is live — greyed options say what they need)").ask()
        if picked is None:                       # Ctrl-C / Esc
            return None

        key_env = None
        if picked == "api-key":
            set_vars = [v for v in onboarding.env_var_options() if os.environ.get(v)]
            if len(set_vars) == 1:
                key_env = set_vars[0]
            else:
                key_env = questionary.select(
                    "Which env var holds the key?",
                    choices=set_vars or onboarding.env_var_options()).ask()
                if key_env is None:
                    return None

        try:
            candidate = onboarding.profile_for_runner(picked, key_env=key_env)
        except ValueError as exc:
            click.secho(f"  {exc}", fg="red")
            continue
        ok, hint = onboarding.first_fix_hint(candidate)
        if not ok:
            click.secho(f"  {hint}", fg="red")
            continue
        profile.save(candidate)
        return candidate


def _task_step(root: Path, prof) -> bool:
    text0, editable0, forbidden0 = existing_answers(root)

    text = questionary.text(
        "What should the agent do?", default=text0,
        validate=lambda t: True if t.strip() else "describe the change").ask()
    if text is None:
        return False

    ai_paths: list[str] | None = None
    if prof.executor in ("claude", "opencode"):
        if questionary.confirm(
                "Suggest editable paths with AI (asks your agent to scope this task)?",
                default=False).ask():
            _dim("  asking the agent to scope this task…")
            ai_paths = ai_suggest_paths(root, prof.executor, text, model=prof.model)
            if ai_paths:
                _dim(f"  suggested: {', '.join(ai_paths)}")
            else:
                _dim("  no usable AI suggestion — falling back to manual entry")

    if not editable0:
        editable0 = ", ".join(ai_paths or suggest_editable(root))

    def _check_editable(t: str):
        paths = parse_paths(t)
        if not paths:
            return "at least one path"
        return path_typo_hint(root, paths) or True

    editable = questionary.text(
        "Paths the agent may touch:", default=editable0,
        instruction="(comma-separated — this becomes the enforced contract)",
        validate=_check_editable).ask()
    if editable is None:
        return False

    ai_forbidden: list[str] | None = None
    if not forbidden0 and prof.executor in ("claude", "opencode"):
        if questionary.confirm(
                "Suggest do-not-touch paths with AI (secrets, infra, CI, lockfiles)?",
                default=False).ask():
            _dim("  asking the agent what to keep off-limits…")
            ai_forbidden = ai_suggest_paths(
                root, prof.executor, text, model=prof.model,
                kind="forbidden", editable=parse_paths(editable))
            if ai_forbidden:
                _dim(f"  suggested: {', '.join(ai_forbidden)}")
            else:
                _dim("  no AI suggestion — nothing flagged, or falling back to manual entry")

    if not forbidden0:
        forbidden0 = ", ".join(ai_forbidden or [])

    forbidden = questionary.text(
        "Paths it must NOT touch:", default=forbidden0,
        instruction="(optional)",
        validate=lambda t: path_typo_hint(root, parse_paths(t)) or True).ask()
    if forbidden is None:
        return False

    write_task_and_bounds(root, text, parse_paths(editable), parse_paths(forbidden))
    return True


def _event_printer():
    """Per-run printer: one scrolling line per stage event, plus the live 'what
    changed' summary under each execute attempt. Drops consecutive duplicate lines
    (the runner re-emits the final verify state after the proxy already reported it)."""
    last: list[str | None] = [None]

    def _print(ev) -> None:
        line = event_line(ev)
        if line and line != last[0]:
            click.echo(line)
            # show the files this attempt actually touched, the moment it finishes
            if _STAGE_NAME.get(ev.stage) == "execute" and ev.state == "done":
                for dl in diff_summary_lines(getattr(ev, "diff", "") or ""):
                    _dim(dl)
        last[0] = line

    return _print


def _run_step(root: Path) -> "object | None":
    task = runner.load_task(str(root))
    if task is None:
        click.secho("  could not load task.yaml", fg="red")
        return None
    cfg = runner.resolve_config(str(root))
    click.echo()
    click.echo(context_status_line(cfg))
    try:
        # blocking + emit on this thread is fine here: we ARE the terminal, each
        # event prints as its own scrolling line — no UI thread to marshal to
        result = runner.run_stages(cfg, task, _event_printer())
    except Exception as exc:
        click.secho(f"\n  run failed: {exc}", fg="red")
        _dim("  `sembl-stack doctor` shows exactly what's missing")
        return None
    click.echo()
    status = result.verdict.status
    color = {"PASS": "green", "WARN": "yellow"}.get(status, "red")
    click.secho(verdict_text(result), fg=color if status == "PASS" else None)
    return result


def _after_run(root: Path, result) -> str:
    """Post-run menu — keep the owner in the cockpit: fire another task, inspect the
    receipt, ship the change, or stop. Returns 'again' | 'quit'. Shipping (apply /
    review / deploy / postdeploy) reuses the exact guards `sembl-stack apply` has
    (verdict binding, dirty-tree check) — the menu is a shortcut to the same code
    path, never a bypass of it."""
    click.echo()
    choices = [Choice(title="Run another task (same repo)", value="again")]
    run_id = getattr(result, "run_id", "") if result else ""
    status = getattr(getattr(result, "verdict", None), "status", None)
    if run_id:
        choices.append(Choice(
            title=f"Inspect this run (sembl-stack runs {run_id})", value="inspect"))
    if run_id and status in ("PASS", "WARN"):
        choices.append(Choice(title="Ship this change (apply / review / deploy)",
                              value="ship"))
    choices.append(Choice(title="Quit", value="quit"))

    while True:
        pick = questionary.select("What next?", choices=choices).ask()
        if pick in (None, "quit"):
            return "quit"
        if pick == "again":
            return "again"
        if pick == "inspect":
            store = RunStore(str(root))
            run = store.open(run_id)
            man = run.manifest() or {}
            _dim(f"  receipt: {store.root}/{run_id}/")
            for k in ("status", "attempts", "executor"):
                if k in man:
                    _dim(f"    {k}: {man[k]}")
            change = run.get("change") or (
                run.get(f"change-{man.get('attempts')}") if man.get("attempts") else None)
            if change is not None and (getattr(change, "diff", "") or "").strip():
                for dl in diff_summary_lines(change.diff):
                    _dim(dl)
        if pick == "ship":
            _ship_step(root, run_id)


# --------------------------------------------------------------------------- ship it

def _apply_diff(root: Path, run, verdict, *, allow_warn: bool) -> str:
    """Apply the run's final patch to the real working tree. Mirrors `sembl-stack
    apply`'s guards exactly (verdict binding, dirty-tree check) — raises ValueError
    with a human reason on any refusal, never applies silently."""
    if verdict.status == "BLOCK":
        raise ValueError("refusing to apply a BLOCKed run")
    if verdict.status == "WARN" and not allow_warn:
        raise ValueError("refusing to apply WARN without confirming")

    man = run.manifest()
    change = run.get("change") or (
        run.get(f"change-{man.get('attempts')}") if man.get("attempts") else None)
    if change is None or not (getattr(change, "diff", "") or "").strip():
        raise ValueError("run has no final patch to apply")

    subject = (getattr(verdict, "raw", {}) or {}).get("subject") or {}
    want = subject.get("diff_sha256")
    if want and diff_sha256(change.diff) != want:
        raise ValueError(
            "verdict/patch mismatch — this run's artifacts have diverged, re-run the loop")

    # Same guard `sembl-stack apply` uses (imported, not duplicated, so a fix to one
    # fixes both): .sembl/ and the tool's own root control files never count as dirty.
    from .cli import _git_apply, _tree_is_dirty
    if _tree_is_dirty(root):
        raise ValueError(
            "the repo has uncommitted changes outside .sembl/ — commit or stash them first")
    try:
        _git_apply(root, change.diff, check_only=False)
    except click.ClickException as exc:
        raise ValueError(str(exc)) from exc
    return ", ".join(_changed_files_from_diff(change.diff)) or "(no files listed)"


def _changed_files_from_diff(diff: str) -> list[str]:
    from .adapters.base import changed_files_from_diff
    return changed_files_from_diff(diff)


def _git_commit(root: Path, message: str) -> str | None:
    """`git add -A && git commit`. Returns None on success, or a human reason it
    didn't happen (e.g. nothing to commit) — never raises."""
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, text=True)
    proc = subprocess.run(["git", "commit", "-m", message], cwd=root,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return (proc.stdout.strip() or proc.stderr.strip() or "git commit failed")
    return None


def _ship_step(root: Path, run_id: str) -> None:
    """Guided apply -> commit -> review -> deploy -> postdeploy, all through the SAME
    configured adapters the loop just used. Every stage confirms before acting;
    declining or Ctrl-C at any point stops without touching later stages. `merge`
    (a branch-based workflow) is deliberately not driven here yet — it needs the
    guided run to manage feature branches first, which this session doesn't do;
    `sembl-stack merge` remains available once you've branched by hand."""
    store = RunStore(str(root))
    run = store.open(run_id)
    verdict = run.get("verdict")
    if verdict is None:
        click.secho("  no verdict on this run — nothing to ship", fg="red")
        return

    click.echo()
    allow_warn = False
    if verdict.status == "WARN":
        allow_warn = questionary.confirm(
            "This run's verdict is WARN, not PASS. Ship it anyway?", default=False).ask()
        if not allow_warn:
            return

    if not questionary.confirm(f"Apply this change to {root}?", default=True).ask():
        return
    try:
        files = _apply_diff(root, run, verdict, allow_warn=allow_warn)
    except ValueError as exc:
        click.secho(f"  apply failed: {exc}", fg="red")
        return
    click.secho(f"  applied: {files}", fg="green")

    if questionary.confirm("Commit the applied change?", default=True).ask():
        task = runner.load_task(str(root))
        msg = (task.text.strip().splitlines()[0] if task and task.text.strip()
              else "sembl-stack: applied change")[:72]
        err = _git_commit(root, msg)
        if err:
            click.secho(f"  commit skipped: {err}", fg="yellow")
        else:
            click.secho("  committed.", fg="green")

    cfg = runner.resolve_config(str(root))
    man = run.manifest()
    change = run.get("change") or (
        run.get(f"change-{man.get('attempts')}") if man.get("attempts") else None)
    if change is not None and cfg.review is not None and questionary.confirm(
            "Get a second-opinion review of the diff (advisory, never blocks)?",
            default=False).ask():
        report = cfg.review.review(change.diff)
        _dim(f"  review ({report.reviewer or 'reviewer'}): {report.status}")
        for f in report.findings or []:
            loc = f.get("file", "")
            _dim(f"    - [{f.get('severity', '?')}] {loc}: {f.get('message', '')}")

    if not questionary.confirm("Deploy now?", default=False).ask():
        return
    target = questionary.select(
        "Deploy target?",
        choices=[Choice(title="Preview", value="preview"),
                 Choice(title="Production", value="production")],
        default="preview").ask()
    if target is None:
        return
    delivery = cfg.deploy.deploy(str(root), production=(target == "production"))
    color = "green" if delivery.status == "deployed" else "red"
    click.secho(f"  deploy: {delivery.status}"
               + (f"  {delivery.url}" if getattr(delivery, "url", None) else ""), fg=color)
    if delivery.status != "deployed":
        return

    if questionary.confirm("Run the post-deploy health check?", default=True).ask():
        prod_verdict = cfg.postdeploy.verify(delivery)
        color = {"PASS": "green", "WARN": "yellow"}.get(prod_verdict.status, "red")
        click.secho(f"  health: {prod_verdict.status}", fg=color)
        for r in getattr(prod_verdict, "reasons", []) or []:
            _dim(f"    - {r}")
        if prod_verdict.status == "BLOCK" and questionary.confirm(
                "Health check BLOCKed — roll back?", default=True).ask():
            rollback = cfg.deploy.rollback(str(root))
            _dim(f"  rollback: {rollback.status}")
