"""sembl-stack CLI.

Each stage is independently invokable and reads/writes artifacts, so you can run the
whole loop OR any subset, enter at any point (supply the upstream artifact), and slot a
custom step between two stages (read the upstream artifact, write the downstream one):

    sembl-stack bounds  --task t.yaml                 --out bounds.json
    sembl-stack specgraph --task t.yaml --bounds b.json --out specgraph.json
    sembl-stack reconcile --specgraph specgraph.json --codegraph codegraph.json
    sembl-stack merge --verdict verdict.json --out merge_record.json
    sembl-stack deploy --verdict verdict.json --out delivery.json
    sembl-stack postdeploy --delivery delivery.json --out prod-verdict.json
    sembl-stack execute --task t.yaml --bounds b.json --out change.json
    sembl-stack verify  --change change.json --bounds b.json     # the gate, standalone
    sembl-stack loop    t.yaml                                    # the full wiring
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from . import artifacts, doctor as doctor_mod, drift, presets, registry
from .artifacts import Bounds, Change, Delivery, SpecGraph, Task, Verdict
from .config import load
from .loop import run as run_loop
from .reconciliation import reconcile_spec_code
from .specgraph import build_spec_graph
from .store import RunStore


# --- helpers ------------------------------------------------------------------

def _resolve(base: Path, p: str | None) -> str | None:
    if not p:
        return p
    pp = Path(p)
    return str(pp if pp.is_absolute() else (base / pp).resolve())


def _load_task(task_file, repo, spec, text) -> Task:
    if task_file:
        data = yaml.safe_load(Path(task_file).read_text(encoding="utf-8")) or {}
        base = Path(task_file).resolve().parent
        return Task(text=data.get("text", ""),
                    repo=_resolve(base, data.get("repo", ".")),
                    spec_path=_resolve(base, data.get("spec_path")))
    return Task(text=text or "",
                repo=str(Path(repo).resolve()),
                spec_path=(str(Path(spec).resolve()) if spec else None))


def _emit(artifact, out: str | None):
    """Write an artifact to --out, or to stdout."""
    if out:
        Path(out).write_text(artifact.to_json(), encoding="utf-8")
        click.echo(f"wrote {artifact.KIND} -> {out}")
    else:
        click.echo(artifact.to_json())


def _read_bounds(path: str) -> Bounds:
    return Bounds.from_json(Path(path).read_text(encoding="utf-8-sig"))


def _read_specgraph(path: str) -> SpecGraph:
    artifact = artifacts.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))
    if not isinstance(artifact, SpecGraph):
        raise click.UsageError(f"{path} is not a SpecGraph artifact")
    return artifact


def _read_verdict(path: str) -> Verdict:
    artifact = artifacts.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))
    if not isinstance(artifact, Verdict):
        raise click.UsageError(f"{path} is not a Verdict artifact")
    return artifact


def _read_delivery(path: str) -> Delivery:
    artifact = artifacts.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))
    if not isinstance(artifact, Delivery):
        raise click.UsageError(f"{path} is not a Delivery artifact")
    return artifact


def _resolve_config(config_path: str, repo: str) -> str | None:
    """Resolve --config: as given (CWD-relative) first, then <repo>/<config_path>.

    `deploy`/`postdeploy` take `--repo` as a separate argument from CWD (orchestrating a
    target repo from elsewhere is a supported use), but the bare default `sembl.stack.yaml`
    only ever resolved against CWD — so pointing `--repo` at another repo silently loaded
    no config (built-in defaults) instead of that repo's own layer/health contract, with no
    error. Falling back to the repo dir closes that gap without changing the CWD-relative
    behavior anyone already relies on.
    """
    if Path(config_path).is_file():
        return config_path
    repo_relative = Path(repo) / config_path
    if repo_relative.is_file():
        return str(repo_relative)
    return None


# --- full loop ----------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.option("--reconfigure", is_flag=True,
              help="Redo the agent & keys step even if a profile exists.")
@click.version_option()
@click.pass_context
def main(ctx, reconfigure):
    """sembl-stack — an open, swappable spec-driven coding factory.

    Run bare (no subcommand) in your repo directory to launch the guided run:
    repo -> agent & keys (live status) -> describe the task -> watch the gated run.
    Every subcommand below is the same machinery, scriptable.
    """
    if ctx.invoked_subcommand is not None:
        return
    from . import guide
    if not guide.available():
        raise click.UsageError(
            "the guided run needs questionary (a core dependency — this install is "
            "broken): `pip install -U sembl-stack`.\n"
            "  (or run a stage directly, e.g. `sembl-stack loop task.yaml`)")
    guide.launch(".", reconfigure=reconfigure)


@main.command()
@click.option("--repo", default=".")
@click.option("--port", type=int, default=8765, show_default=True)
@click.option("--browser", is_flag=True,
              help="Open in your default browser instead of a native window.")
def gui(repo, port, browser):
    """O7: the graphical dashboard — a native window (or --browser) over the same
    deterministic cores `loop`/the guided run already use. Needs the 'gui' extra."""
    from .gui.launcher import available, launch_gui
    if not available():
        raise click.UsageError(
            "the GUI needs extra deps: `pip install \"sembl-stack[gui]\"`\n"
            "  (or run the scriptable path instead, e.g. `sembl-stack loop task.yaml`)")
    launch_gui(repo, port=port, browser=browser)


@click.argument("task_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--config", "config_path", default="sembl.stack.yaml")
def _loop_cmd(task_file: str, config_path: str):
    """Run the full wiring: plan -> execute -> verify (retry on BLOCK)."""
    task = _load_task(task_file, None, None, None)
    # Resolve against the task's repo too — an explicit sembl.stack.yaml there must win
    # over the profile even when the loop is launched from a different directory.
    cfg_file = _resolve_config(config_path, task.repo)
    overrides = None
    if cfg_file is None:                 # no repo config: the onboarded profile is the default
        from . import profile as profile_mod
        prof = profile_mod.load()
        if prof is not None:
            overrides = profile_mod.to_stack_overrides(prof)
            click.echo(f"(no {config_path} — using your profile: "
                       f"runner={prof.runner}, executor={prof.executor})")
    cfg = load(cfg_file, overrides)
    click.echo(f"layers: {cfg.raw['layers']}")
    click.echo(f"task: {task.text!r}\nrepo: {task.repo}\n")

    try:
        result = run_loop(cfg, task)
    except RuntimeError as exc:
        # Stage adapters raise RuntimeError with an "L<n>: ..." prefix. A stranger's
        # first failure should be a diagnosis, not a stack trace.
        click.secho(f"error: {exc}", fg="red")
        click.echo("hint: `sembl-stack doctor` checks your environment. The loop needs\n"
                   "  - the task's repo to be a git repository with at least one commit\n"
                   "    (the sandbox clones it), and\n"
                   "  - a bounds source: a task spec_path, or a bounds.json next to the\n"
                   "    task file (`sembl-stack init` scaffolds a working starter).")
        raise SystemExit(1)

    click.echo(f"engine: {result.engine}")
    for attempt, status in result.history:
        mark = {"PASS": "OK", "WARN": "~", "BLOCK": "X"}.get(status, "?")
        click.echo(f"  attempt {attempt}: [{mark}] {status}")
    v = result.verdict
    click.echo("")
    click.secho(f"FINAL: {v.status}  (after {result.attempts} attempt(s))",
                fg="green" if v.status == "PASS" else
                   "yellow" if v.status == "WARN" else "red")
    for r in v.reasons:
        click.echo(f"  - {r}")
    if result.run_id:
        click.echo(f"\nrun: {result.run_id}  (.sembl/runs/{result.run_id}/)")
        click.echo(f"inspect: sembl-stack runs {result.run_id} --repo {task.repo}")
        if v.status in ("PASS", "WARN"):
            click.echo(f"apply:   sembl-stack apply {result.run_id} --repo {task.repo}")
    raise SystemExit(0 if v.status in ("PASS", "WARN") else 1)


main.command(name="loop")(_loop_cmd)
main.command(name="run")(_loop_cmd)   # alias


# --- individual stages --------------------------------------------------------

@main.command()
@click.option("--task", "task_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--repo", default=".")
@click.option("--spec", default=None, help="Spec Kit tasks.md / feature dir.")
@click.option("--text", default=None, help="Task text (if no --task file).")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--expand/--no-expand", default=False,
              help="Widen editable_paths along the L1 context graph's coupling closure "
                   "(EXP-05: recovers legitimate sibling files; hops=1, closure-capped).")
@click.option("--hops", default=1, show_default=True, help="Coupling hops when --expand.")
@click.option("--out", default=None, help="Write the Bounds artifact here (else stdout).")
def bounds(task_file, repo, spec, text, config_path, expand, hops, out):
    """L2: Task -> Bounds. Derive the scope contract from a spec."""
    task = _load_task(task_file, repo, spec, text)
    cfg = load(_resolve_config(config_path, repo))
    bnds = cfg.spec.plan(task)
    if expand:
        bnds = _expand_bounds(bnds, task.repo, cfg, hops)
    _emit(bnds, out)


@main.command()
@click.option("--task", "task_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--repo", default=".")
@click.option("--spec", default=None, help="Spec Kit tasks.md / feature dir.")
@click.option("--text", default=None, help="Task text (if no --task file).")
@click.option("--bounds", "bounds_path", type=click.Path(exists=True),
              help="Optional Bounds artifact to include declared scope.")
@click.option("--out", default=None, help="Write the SpecGraph artifact here (else stdout).")
def specgraph(task_file, repo, spec, text, bounds_path, out):
    """L2: Task(+Bounds) -> SpecGraph. Emit the spec-side reconciliation graph."""
    task = _load_task(task_file, repo, spec, text)
    bnds = _read_bounds(bounds_path) if bounds_path else None
    _emit(build_spec_graph(task, bnds), out)


@main.command()
@click.option("--specgraph", "specgraph_path", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--codegraph", "codegraph_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Code graph JSON (hand-passed). Omit and pass --live to build it from CBM.")
@click.option("--live", is_flag=True,
              help="Build the code graph live from a real codebase-memory-mcp index.")
@click.option("--repo", default=".", help="Repo to index/graph when --live.")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None,
              help="Write the ReconciliationReport artifact here (else stdout).")
def reconcile(specgraph_path, codegraph_path, live, repo, config_path, out):
    """L5.5: SpecGraph+CodeGraph -> advisory ReconciliationReport (advisory, never a gate)."""
    spec_graph = _read_specgraph(specgraph_path)
    if live:
        # Advisory, never a gate: a missing/failed code graph yields an empty graph -> UNKNOWN
        # report at exit 0 (the adapter already degrades internally). Never raise on CBM
        # absence — only genuinely contradictory input below is a usage error.
        cfg = load(_resolve_config(config_path, repo))
        code_graph = cfg.codegraph.code_graph(repo) if cfg.codegraph is not None else {}
    elif codegraph_path:
        code_graph = json.loads(Path(codegraph_path).read_text(encoding="utf-8-sig"))
    else:
        raise click.UsageError("supply --codegraph <file> or --live")
    _emit(reconcile_spec_code(spec_graph, code_graph), out)


@main.command(name="drift-check")
@click.option("--specgraph", "specgraph_path", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--codegraph", "codegraph_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Code graph JSON (hand-passed). Omit and pass --live to build it from CBM.")
@click.option("--live", is_flag=True,
              help="Build the code graph live from a real codebase-memory-mcp index.")
@click.option("--repo", default=".", help="Repo to index/graph when --live.")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--state", "state_path", default=drift.DEFAULT_STATE_PATH,
              help="Where to persist drift-check state across runs (default .sembl/drift-state.json).")
@click.option("--out", default=None,
              help="Write the full check payload (report + new/pending/resolved) here (else stdout).")
def drift_check(specgraph_path, codegraph_path, live, repo, config_path, state_path, out):
    """Track 5 item 3: ambient drift check — advisory, never a gate, never blocks.

    Same SpecGraph/code-graph sources as `reconcile`, plus a persisted state file so
    repeated checks only surface what's NEW since the last review, instead of
    re-reporting the same drift forever.
    """
    spec_graph = _read_specgraph(specgraph_path)
    if live:
        cfg = load(_resolve_config(config_path, repo))
        code_graph = cfg.codegraph.code_graph(repo) if cfg.codegraph is not None else {}
    elif codegraph_path:
        code_graph = json.loads(Path(codegraph_path).read_text(encoding="utf-8-sig"))
    else:
        raise click.UsageError("supply --codegraph <file> or --live")

    result = drift.check_drift(spec_graph, code_graph, state_path=state_path)
    payload = {
        "report": result.report.to_dict(),
        "new": result.new,
        "pending": result.pending,
        "resolved": result.resolved,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        click.echo(f"wrote drift-check -> {out}")
    else:
        click.echo(text)
    click.echo(
        f"drift: {len(result.new)} new, {len(result.pending)} pending, "
        f"{len(result.resolved)} resolved (state: {state_path})", err=True)


@main.command(name="drift-review")
@click.option("--state", "state_path", default=drift.DEFAULT_STATE_PATH,
              help="Drift state file to read (default .sembl/drift-state.json).")
@click.option("--ack", is_flag=True,
              help="Acknowledge everything shown — the batched review checkpoint.")
def drift_review(state_path, ack):
    """Track 5 item 3: the batched review checkpoint for ambient drift.

    Shows every currently-unacknowledged finding without recomputing reconciliation.
    `--ack` marks what's shown as reviewed, so the next `drift-check` stays quiet about it
    unless it changes again.
    """
    pending = drift.pending_drift(state_path=state_path)
    if not pending:
        click.echo("no pending drift")
        return
    for n, finding in enumerate(pending, start=1):
        click.echo(f"{n}. [{finding.get('kind')}] {finding.get('message')}")
    if ack:
        n = drift.acknowledge_drift(state_path=state_path)
        click.echo(f"acknowledged {n} finding(s)", err=True)


def _resolve_drift_key(key: str, state_path: str) -> str:
    """KEY is either a full `finding_key()` string or a 1-based index into the same
    ordering `drift-review` numbers (`drift.pending_drift_items`). Errors loudly rather
    than silently picking the wrong finding."""
    items = drift.pending_drift_items(state_path=state_path)
    if key.isdigit():
        idx = int(key)
        if idx < 1 or idx > len(items):
            raise click.UsageError(
                f"index {idx} out of range — {len(items)} pending finding(s) (state: {state_path})")
        return items[idx - 1][0]
    if any(k == key for k, _ in items):
        return key
    raise click.UsageError(
        f"unknown finding key {key!r} — {len(items)} pending finding(s) (state: {state_path})")


@main.command(name="drift-resolve")
@click.argument("key")
@click.option("--state", "state_path", default=drift.DEFAULT_STATE_PATH,
              help="Drift state file to read/write (default .sembl/drift-state.json).")
@click.option("--mark-exception", is_flag=True,
              help="Record a permanent, human-issued exception for this finding.")
@click.option("--reason", default=None, help="Required with --mark-exception.")
@click.option("--update-code", is_flag=True,
              help="Seed a loop task file to reconcile the code with the spec.")
@click.option("--update-spec", is_flag=True,
              help="Print the finding for manual spec-source editing (v1: no LLM, O8).")
def drift_resolve(key, state_path, mark_exception, reason, update_code, update_spec):
    """Track 5 item 4: resolve one pending drift finding, tri-state.

    KEY is either a full finding key (the `finding_key()` string, as persisted in
    drift-state.json) or the 1-based index `drift-review` prints for the same finding.
    Exactly one mode is required:

      --mark-exception --reason TEXT   Record a permanent exception in drift-state.json.
        This is a genuine, human-issued decision, recorded permanently there — NOT via
        CBM's manage_adr (that tool replaces a whole-project doc wholesale; see this
        module's docstring in drift.py for why it's the wrong fit for a per-finding log).

      --update-code   Seed `.sembl/drift-tasks/<ts>-<hash>.yaml` for the existing loop
        to reconcile code with spec, and print the `sembl-stack loop <path>` command to
        run it. Does NOT run the loop and does NOT acknowledge the finding — resolution
        happens naturally when the next `drift-check` no longer sees the drift.

      --update-spec   v1 is deliberately non-LLM (O8: only three sanctioned LLM-in-the-
        loop uses exist; a fourth needs a ledger diff, not a silent addition here).
        Prints the finding for a human to edit the spec source by hand. Acknowledges
        nothing.
    """
    modes = [m for m in (mark_exception, update_code, update_spec) if m]
    if len(modes) != 1:
        raise click.UsageError(
            "exactly one of --mark-exception, --update-code, --update-spec is required")

    resolved_key = _resolve_drift_key(key, state_path)

    if mark_exception:
        if not reason:
            raise click.UsageError("--reason TEXT is required with --mark-exception")
        drift.resolve_exception(resolved_key, reason, state_path=state_path)
        click.echo(f"exception recorded for {resolved_key!r}: {reason}")
        return

    entry = drift.entry_for_key(resolved_key, state_path=state_path)
    finding = entry["finding"]

    if update_code:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        short_hash = hashlib.sha1(resolved_key.encode("utf-8")).hexdigest()[:8]
        task_path = Path(".sembl") / "drift-tasks" / f"{ts}-{short_hash}.yaml"
        task_path.parent.mkdir(parents=True, exist_ok=True)
        task_text = (
            f"reconcile code with spec for drift finding "
            f"[{finding.get('kind')}] {finding.get('spec_node')}: {finding.get('message')!r}"
        )
        task_data = {"text": task_text, "repo": "."}
        task_path.write_text(yaml.safe_dump(task_data, sort_keys=False), encoding="utf-8")
        click.echo(f"wrote task -> {task_path}")
        click.echo(f"run:  sembl-stack loop {task_path}")
        click.echo(
            "not acknowledged — this resolves itself when the drift disappears at the "
            "next drift-check.")
        return

    # --update-spec
    click.echo(f"kind:           {finding.get('kind')}")
    click.echo(f"spec_node:      {finding.get('spec_node')}")
    click.echo(f"message:        {finding.get('message')}")
    click.echo(f"first_detected: {entry.get('first_detected')}")
    click.echo("edit the spec source manually to reconcile this — nothing acknowledged.")


@main.command()
@click.option("--diff", "diff_path", required=True, type=click.Path(exists=True, dir_okay=False),
              help="Unified diff / .patch to review.")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None, help="Write the ReviewReport artifact here (else stdout).")
def review(diff_path, config_path, out):
    """L5.5 (quality): diff -> advisory ReviewReport (advisory, never a gate)."""
    cfg = load(config_path if Path(config_path).is_file() else None)
    diff = Path(diff_path).read_text(encoding="utf-8-sig")
    _emit(cfg.review.review(diff), out)


@main.command()
@click.option("--repo", default=".")
@click.option("--verdict", "verdict_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Final gate Verdict artifact. Must be PASS unless --allow-warn.")
@click.option("--into", default="main", show_default=True, help="Target branch to merge into.")
@click.option("--source", default="HEAD", show_default=True, help="Ref to merge.")
@click.option("--allow-warn", is_flag=True,
              help="Allow merging a WARN verdict. BLOCK is never merged.")
@click.option("--no-ff/--ff", default=True, help="Create a merge commit (default) vs fast-forward.")
@click.option("--skip-binding-check", is_flag=True,
              help="Merge even when the verdict's judged file set can't be matched "
                   "against the source ref (recorded in the MergeRecord).")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None, help="Write the MergeRecord artifact here.")
def merge(repo, verdict_path, into, source, allow_warn, no_ff, skip_binding_check,
          config_path, out):
    """L6.5: Verdict(PASS) -> MergeRecord. Gated merge into the target branch."""
    verdict = _read_verdict(verdict_path)
    if verdict.status == "BLOCK":
        raise click.UsageError("refusing to merge a BLOCK verdict")
    if verdict.status == "WARN" and not allow_warn:
        raise click.UsageError("refusing to merge WARN without --allow-warn")
    if verdict.status not in ("PASS", "WARN"):
        raise click.UsageError(f"unsupported verdict status: {verdict.status}")

    # Verdict-to-source binding: the verdict names the files it judged; the merge
    # must ship exactly those. Otherwise any PASS verdict file green-lights merging
    # any branch. Unbound (pre-binding) verdicts pass through with a note.
    binding = _check_merge_binding(verdict, repo, into, source) \
        if not skip_binding_check else {"status": "skipped (--skip-binding-check)"}
    if binding.get("mismatch") and not skip_binding_check:
        raise click.UsageError(
            "verdict/source mismatch — the verdict did not judge what this merge "
            f"would ship: {binding['mismatch']} "
            "(re-gate the branch, or --skip-binding-check to override; overrides "
            "are recorded)")

    cfg = load(_resolve_config(config_path, repo))
    record = cfg.merge.merge(repo, into=into, source=source, no_ff=no_ff)
    record.data["source_binding"] = binding
    _emit(record, out)
    raise SystemExit(0 if record.status == "merged" else 1)


def _check_merge_binding(verdict, repo, into, source) -> dict:
    """Compare the verdict's judged file set to what `into...source` would merge."""
    subject = (getattr(verdict, "raw", {}) or {}).get("subject") or {}
    judged = subject.get("files")
    if judged is None:
        judged = verdict.raw.get("changed_files") if isinstance(
            verdict.raw.get("changed_files"), list) else None
    if judged is None:
        return {"status": "unbound (verdict predates source binding)"}
    proc = subprocess.run(
        ["git", "-C", str(Path(repo).resolve()), "diff", "--name-only",
         f"{into}...{source}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return {"mismatch": f"could not diff {into}...{source} "
                            f"({proc.stderr.strip() or 'git diff failed'})"}
    actual = {p.strip() for p in proc.stdout.splitlines() if p.strip()}
    judged_set = set(judged)
    extra, missing = sorted(actual - judged_set), sorted(judged_set - actual)
    if extra or missing:
        bits = []
        if extra:
            bits.append(f"unjudged in merge: {', '.join(extra[:5])}")
        if missing:
            bits.append(f"judged but absent: {', '.join(missing[:5])}")
        return {"mismatch": "; ".join(bits), "extra": extra, "missing": missing}
    return {"status": "verified", "files": sorted(judged_set)}


@main.command()
@click.option("--repo", default=".")
@click.option("--verdict", "verdict_path", required=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Final gate Verdict artifact. Must be PASS unless --allow-warn.")
@click.option("--allow-warn", is_flag=True,
              help="Allow deploying a WARN verdict. BLOCK is never deployed.")
@click.option("--prod/--preview", "production", default=False,
              help="Deploy to production instead of preview.")
@click.option("--prebuilt/--no-prebuilt", default=False,
              help="Deploy existing Vercel build output with `vercel deploy --prebuilt`.")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None, help="Write the Delivery artifact here.")
@click.option("--allow-dirty", is_flag=True,
              help="Deploy even when the target working tree has uncommitted changes.")
def deploy(repo, verdict_path, allow_warn, production, prebuilt, config_path, out, allow_dirty):
    """L7: Verdict(PASS) -> Delivery. Deploy via the configured adapter."""
    verdict = _read_verdict(verdict_path)
    if verdict.status == "BLOCK":
        raise click.UsageError("refusing to deploy a BLOCK verdict")
    if verdict.status == "WARN" and not allow_warn:
        raise click.UsageError("refusing to deploy WARN without --allow-warn")
    if verdict.status != "PASS" and verdict.status != "WARN":
        raise click.UsageError(f"unsupported verdict status: {verdict.status}")

    # Dirty-tree guard, same convention as `apply`: a verdict only judged what was
    # committed, so deploying over further uncommitted edits would ship unjudged
    # content under cover of an old PASS/WARN (codex review finding). This repo may
    # not be the tool's own root (it can be any Vercel-linked project dir), so the
    # tool-owned-root-files allowance in `_tree_is_dirty` still applies correctly.
    if not allow_dirty and _tree_is_dirty(Path(repo).resolve()):
        raise click.UsageError(
            "the repo has uncommitted changes — commit them first (so the deploy "
            "matches exactly what the verdict judged), or pass --allow-dirty")

    cfg = load(_resolve_config(config_path, repo))
    delivery = cfg.deploy.deploy(repo, production=production, prebuilt=prebuilt)
    _emit(delivery, out)
    raise SystemExit(0 if delivery.status == "deployed" else 1)


@main.command()
@click.option("--delivery", "delivery_path", required=True,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--health-path", default=None,
              help="Override the configured health path (default from options.postdeploy).")
@click.option("--timeout", "timeout_s", default=10.0, show_default=True, type=float)
@click.option("--rollback/--no-rollback", "do_rollback", default=False,
              help="On a BLOCK verdict, fire a rollback via the deploy adapter (promote previous).")
@click.option("--repo", default=".", help="Repo dir for the rollback call (linked Vercel project).")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None, help="Write the production Verdict artifact here.")
def postdeploy(delivery_path, health_path, timeout_s, do_rollback, repo, config_path, out):
    """L8: Delivery -> Verdict. Deterministic post-deploy health gate (+ optional rollback)."""
    delivery = _read_delivery(delivery_path)
    cfg = load(_resolve_config(config_path, repo))
    # health_path=None lets the adapter use its configured default (options.postdeploy.health_path
    # + expect_json payload contract); an explicit --health-path overrides per-call.
    verdict = cfg.postdeploy.verify(delivery, health_path=health_path, timeout_s=timeout_s,
                                    repo=repo)

    # L8 rollback trigger: a BLOCK means the live deploy is bad — revert it. Opt-in so default
    # behavior is unchanged. The rollback outcome is recorded in the prod Verdict, never hidden.
    if do_rollback and verdict.status == "BLOCK":
        rollback = cfg.deploy.rollback(repo)
        verdict.raw["rollback"] = rollback.to_dict()
        verdict.reasons.append(f"rollback triggered: {rollback.status}")

    _emit(verdict, out)
    raise SystemExit(0 if verdict.status in ("PASS", "WARN") else 1)


def _expand_bounds(bnds, repo, cfg, hops):
    """Grow bounds.editable_paths via the configured context graph (no-op if unavailable)."""
    from .contextgraph import expand_bounds as _eb
    g = cfg.context
    if g is None or not getattr(g, "available", lambda: False)():
        click.echo("(context graph unavailable — bounds left as-is)", err=True)
        return bnds
    opts = (cfg.raw.get("options", {}) or {}).get("context", {}) or {}
    g.index(repo)
    fg = g.file_graph(repo)
    before = list(bnds.editable_paths)
    bnds.editable_paths = _eb(before, fg, hops=hops,
                              min_strength=opts.get("min_strength", 0),
                              max_fraction=opts.get("max_fraction", 0.4))
    click.echo(f"(context: {len(fg.nodes)} files; editable_paths "
               f"{len(before)} -> {len(bnds.editable_paths)})", err=True)
    return bnds


@main.command()
@click.option("--repo", default=".")
@click.option("--config", "config_path", default="sembl.stack.yaml")
def context(repo, config_path):
    """L1: index the repo with the context graph and show its size + densest files."""
    cfg = load(_resolve_config(config_path, repo))
    g = cfg.context
    if g is None or not getattr(g, "available", lambda: False)():
        raise click.UsageError("no context adapter configured/available "
                               "(set layers.context: symgraph, install symgraph)")
    repo = str(Path(repo).resolve())
    g.index(repo)
    fg = g.file_graph(repo)
    click.echo(f"files: {len(fg.nodes)}   edges: {len(fg.edges)}")
    top = sorted(fg.edges, key=lambda e: e.get("strength", 0), reverse=True)[:8]
    for e in top:
        click.echo(f"  {e['from']} -> {e['to']}  (strength {e.get('strength','?')})")


@main.command()
@click.option("--task", "task_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--repo", default=".")
@click.option("--text", default=None)
@click.option("--bounds", "bounds_path", required=True, type=click.Path(exists=True))
@click.option("--feedback", default=None, help="Gate feedback to act on (retry).")
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None, help="Write the Change artifact here (else stdout).")
def execute(task_file, repo, text, bounds_path, feedback, config_path, out):
    """L3: Task+Bounds -> Change. Run the executor in a sandbox, capture the diff."""
    task = _load_task(task_file, repo, None, text)
    cfg = load(_resolve_config(config_path, repo))
    bnds = _read_bounds(bounds_path)
    sandbox = cfg.sandbox.open(task.repo)
    try:
        change = cfg.execute.run(task, bnds, sandbox, feedback)
    finally:
        sandbox.close()       # diff is captured in the artifact; cage is disposable
    _emit(change, out)


@main.command()
@click.option("--change", "change_path", type=click.Path(exists=True),
              help="A Change artifact to gate.")
@click.option("--diff", "diff_path", type=click.Path(exists=True),
              help="A raw unified diff / .patch (the adoption wedge: gate any diff).")
@click.option("--report", "report_path", type=click.Path(exists=True),
              help="An executor self-report JSON (used with --diff).")
@click.option("--bounds", "bounds_path", required=True, type=click.Path(exists=True))
@click.option("--strict/--no-strict", default=True)
@click.option("--config", "config_path", default="sembl.stack.yaml")
@click.option("--out", default=None, help="Write the Verdict artifact here.")
def verify(change_path, diff_path, report_path, bounds_path, strict, config_path, out):
    """L5: Change+Bounds -> Verdict. The deterministic gate, standalone."""
    cfg = load(config_path if Path(config_path).is_file() else None)
    bnds = _read_bounds(bounds_path)
    if change_path:
        change = Change.from_json(Path(change_path).read_text(encoding="utf-8"))
    elif diff_path:
        report = (json.loads(Path(report_path).read_text(encoding="utf-8"))
                  if report_path else {})
        change = Change(diff=Path(diff_path).read_text(encoding="utf-8"), report=report)
    else:
        raise click.UsageError("provide --change or --diff")

    verdict = cfg.verify.verify(bnds, change, strict)
    if out:
        _emit(verdict, out)
    click.secho(f"{verdict.status}", fg="green" if verdict.status == "PASS" else
                "yellow" if verdict.status == "WARN" else "red")
    for r in verdict.reasons:
        click.echo(f"  - {r}")
    raise SystemExit(0 if verdict.status in ("PASS", "WARN") else 1)


# --- onboarding (C4) -----------------------------------------------------------

@main.command()
@click.option("--preset", type=click.Choice(presets.names()),
              default=presets.DEFAULT_PRESET, show_default=True,
              help="just-gate (wedge) | gate+sandbox (mock loop) | full-loop (real agent).")
@click.option("--config", "config_path", default="sembl.stack.yaml", show_default=True)
@click.option("--task/--no-task", "with_task", default=True,
              help="Also scaffold a starter task.yaml.")
@click.option("--force", is_flag=True, help="Overwrite existing files.")
def init(preset, config_path, with_task, force):
    """Scaffold a sembl.stack.yaml (+ a starter task.yaml) from a preset."""
    cfg_p = Path(config_path)
    if cfg_p.exists() and not force:
        raise click.UsageError(f"{config_path} already exists (use --force to overwrite)")
    cfg_p.write_text(presets.render(preset), encoding="utf-8")
    click.secho(f"wrote {config_path}  (preset: {preset})", fg="green")
    if with_task:
        # The starter task has no spec_path, so the L2 spec adapter needs a
        # bounds.json beside it; the clone sandbox needs a committed git repo.
        from . import scaffold
        here = Path(".")
        for msg in scaffold.write_starter_files(here, preset, force=force,
                                                include_config=False):
            click.secho(msg, fg="green")
        for msg in scaffold.ensure_demo_repo(here):
            click.secho(msg, fg="green")
    click.echo("\nnext:\n  sembl-stack doctor          # check your environment\n"
               "  sembl-stack loop task.yaml  # run the loop\n"
               "  sembl-stack                 # or the guided TUI")


@main.command()
@click.argument("text")
@click.option("--repo", default=".")
@click.option("--executor", default="mock", show_default=True,
              help="claude | opencode | mock (mock always falls back to an empty "
                   "proposal for manual entry — no external call).")
@click.option("--model", default=None)
@click.option("--timeout", default=90, show_default=True, type=int)
@click.option("--yes", is_flag=True,
              help="Materialize the proposal immediately via confirm_task "
                   "(task.yaml + bounds.json), skipping human review.")
def discuss(text, repo, executor, model, timeout, yes):
    """O8 use #2: plain-English change request -> a reviewed Task+Bounds proposal.

    Bounded-LLM-into-fixed-schema (see PROCESS-ACTION-PLAN.md O8): one read-only
    call proposes task_text/editable_paths/forbidden_areas/clarifying_questions
    into a fixed schema it cannot extend; nothing is written until confirmed
    (here, via --yes; in the IDE, via the discuss panel's confirm step).
    """
    from . import discuss as discuss_mod
    root = Path(repo).resolve()
    proposal = discuss_mod.propose_task(root, executor, text, model=model, timeout=timeout)
    click.echo(json.dumps(proposal, indent=2))
    if yes:
        try:
            task_path, bounds_path = discuss_mod.confirm_task(root, proposal)
        except ValueError as e:
            # write_task_and_bounds refuses empty text / no editable paths — surface
            # that as usage guidance, not a traceback (the fallback proposal is empty).
            raise click.UsageError(f"{e} — review the proposal and fill it in first")
        click.secho(f"\nwrote {task_path} + {bounds_path}", fg="green")
        click.echo("next:\n  sembl-stack loop task.yaml")
    else:
        click.echo(
            "\n(review/edit this proposal, then confirm it — via the IDE discuss "
            "panel, or re-run with --yes to materialize it as-is)")


@main.command("discuss-confirm")
@click.option("--repo", default=".")
@click.option("--proposal-file", "proposal_file", default=None,
              help="Read the (possibly human-edited) proposal JSON from this file; "
                   "reads stdin when omitted (the IDE discuss panel's confirm step).")
def discuss_confirm(repo, proposal_file):
    """Materialize a (possibly human-edited) discuss proposal -> task.yaml + bounds.json.

    No LLM work here — `sanitize_proposal` coerces/filters the incoming JSON to the
    fixed schema exactly like `_parse_reply` does for a model reply, then
    `confirm_task` writes the artifacts through the same tool-owned writer every
    other entry point uses.
    """
    from . import discuss as discuss_mod
    root = Path(repo).resolve()
    raw = (Path(proposal_file).read_text(encoding="utf-8-sig") if proposal_file
           else click.get_text_stream("stdin").read())
    try:
        data = json.loads(raw.lstrip("﻿"))
    except (ValueError, TypeError) as e:
        raise click.UsageError(f"invalid proposal JSON: {e}")
    sanitized = discuss_mod.sanitize_proposal(root, data)
    try:
        task_path, bounds_path = discuss_mod.confirm_task(root, sanitized)
    except ValueError as e:
        raise click.UsageError(f"{e} — review the proposal and fill it in first")
    click.secho(f"wrote {task_path} + {bounds_path}", fg="green")


@main.command()
@click.argument("question")
@click.option("--repo", default=".")
@click.option("--executor", default="claude", show_default=True,
              help="claude | opencode | mock (mock makes no external call and "
                   "always yields the \"guide unavailable\" fallback).")
@click.option("--model", default=None,
              help="Defaults to a Haiku-class model when --executor claude "
                   "(O9: the factory guide is cheap-model-only).")
@click.option("--timeout", default=60, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True,
              help="Print the raw reply dict as JSON (the seam an IDE panel spawns).")
def explain(question, repo, executor, model, timeout, as_json):
    """O9: the factory guide — a read-only, cheap-model advisor for OPERATING sembl.

    Explains a verdict, narrates a stuck run, suggests which drift resolution
    fits. Strictly read-only (see PROCESS-ACTION-PLAN.md O9): it never writes a
    file, never executes anything, and never touches L5/L8 — anything it wants
    done is only ever a printed suggestion, routed through an existing command.
    """
    from . import factory_guide
    root = Path(repo).resolve()
    reply = factory_guide.ask(root, executor, question, model=model, timeout=timeout)
    if as_json:
        click.echo(json.dumps(reply))
        return
    if reply.get("fallback"):
        click.echo(
            "guide unavailable (model call failed or unparseable) — check that "
            "your executor CLI is logged in, or try --executor opencode")
        return
    click.echo(reply.get("answer") or "")
    suggestions = reply.get("suggestions") or []
    if suggestions:
        click.echo("")
        click.secho("try:", dim=True)
        for i, s in enumerate(suggestions, 1):
            click.echo(f"  {i}. {s.get('command', '')}  ", nl=False)
            click.secho(f"— {s.get('why', '')}", dim=True)


@main.command()
@click.option("--config", "config_path", default="sembl.stack.yaml")
def doctor(config_path):
    """Preflight: check the environment for the layers your config selects."""
    cfg = load(config_path) if Path(config_path).is_file() else None
    if cfg is None:
        click.echo(f"(no {config_path} — checking defaults; `sembl-stack init` first)\n")
    checks = doctor_mod.run_checks(cfg)
    for c in checks:
        mark, color = ("OK", "green") if c.ok else \
            (("X", "red") if c.required else ("~", "yellow"))
        click.secho(f"  [{mark}] {c.name:26} {c.detail}", fg=color)
        if not c.ok and c.hint:
            click.echo(f"         -> {c.hint}")
    ready, blocking, warnings = doctor_mod.summarize(checks)
    click.echo("")
    if ready:
        extra = f" ({len(warnings)} optional not installed)" if warnings else ""
        click.secho(f"doctor: ready{extra}", fg="green")
    else:
        click.secho(f"doctor: NOT ready — {len(blocking)} required item(s) missing", fg="red")
    raise SystemExit(0 if ready else 1)


# --- introspection ------------------------------------------------------------

@main.command()
def layers():
    """List the available adapters per layer."""
    for layer in ("spec", "execute", "sandbox", "verify", "context", "merge", "deploy", "postdeploy", "review"):
        click.echo(f"{layer:9}: {', '.join(registry.names(layer))}")


@main.command()
@click.argument("run_id", required=False)
@click.option("--repo", default=".")
@click.option("-v", "--verbose", is_flag=True, help="Show per-attempt latency/cost.")
def runs(run_id, repo, verbose):
    """List recorded runs, or inspect one in detail: `sembl-stack runs <id>`."""
    store = RunStore(repo)
    if run_id:
        _show_run(store, run_id)
        return
    ids = store.list_runs()
    if not ids:
        click.echo("no runs yet — try `sembl-stack loop task.yaml`")
        return
    for rid in ids:
        m = store.open(rid).manifest()
        lat = m.get("total_latency_s")
        lat_s = f"{lat:.2f}s" if isinstance(lat, (int, float)) else "-"
        click.echo(f"{rid}  {m.get('status','?'):6}  "
                   f"attempts={m.get('attempts','-')}  {lat_s:>8}  "
                   f"{m.get('task',{}).get('text','')}")
        if verbose:
            for e in m.get("attempts_log", []):
                bits = [f"latency={e.get('latency_s','-')}s"]
                for k in ("model", "exit_code", "tokens", "cost"):
                    if e.get(k) is not None:
                        bits.append(f"{k}={e[k]}")
                click.echo(f"    attempt {e.get('attempt','?')}: " + "  ".join(bits))


@main.command()
@click.option("--repo", default=".")
@click.option("--json", "as_json", is_flag=True, help="Emit the full summary as JSON.")
def rsi(repo, as_json):
    """RSI-L1 readout: per-executor iterations-to-green + cost over the recorded runs.

    The "measured selection" artifact (north-star first rung): every number is read back
    from run-store artifacts the loop persisted — cost shows "not yet recorded" for runs
    whose executor reported no usage, never an invented number.
    """
    from . import rsi as rsi_mod
    summary = rsi_mod.aggregate(RunStore(repo))
    if as_json:
        click.echo(json.dumps(summary, indent=2))
    else:
        click.echo(rsi_mod.render(summary))


@main.command(name="apply")
@click.argument("run_id")
@click.option("--repo", default=".")
@click.option("--allow-warn", is_flag=True,
              help="Allow applying a final WARN verdict. BLOCK is never applied.")
@click.option("--allow-dirty", is_flag=True,
              help="Apply even when the target working tree has uncommitted changes.")
@click.option("--check", "check_only", is_flag=True,
              help="Only verify that the patch applies; do not change the working tree.")
def apply_run(run_id, repo, allow_warn, allow_dirty, check_only):
    """Apply a run's final accepted patch to the source repo working tree."""
    repo_path = Path(repo).resolve()
    store = RunStore(str(repo_path))
    run = store.open(run_id)
    m = run.manifest()
    if not m:
        raise click.UsageError(f"no run '{run_id}' under {store.root}")

    verdict = run.get("verdict")
    status = getattr(verdict, "status", m.get("status", "BLOCK"))
    if status == "BLOCK":
        raise click.UsageError("refusing to apply a BLOCKed run")
    if status == "WARN" and not allow_warn:
        raise click.UsageError("refusing to apply WARN without --allow-warn")

    change = run.get("change")
    if change is None:
        attempts = m.get("attempts")
        change = run.get(f"change-{attempts}") if attempts else None
    if change is None or not (getattr(change, "diff", "") or "").strip():
        raise click.UsageError("run has no final patch to apply")

    # Verdict-to-source binding: the verdict must have been issued for THIS patch.
    # Without it, any PASS verdict file (edited, or copied from another run) would
    # green-light applying an unjudged diff.
    subject = (getattr(verdict, "raw", {}) or {}).get("subject") or {}
    want = subject.get("diff_sha256")
    if want:
        from .artifacts import diff_sha256
        have = diff_sha256(change.diff)
        if have != want:
            raise click.UsageError(
                "verdict/patch mismatch: the run's verdict was not issued for this "
                f"patch (judged sha256 {want[:12]}…, patch is {have[:12]}…) — "
                "the run's artifacts have diverged; re-run the loop")

    # Dirty-tree guard: applying over uncommitted edits mixes judged and unjudged
    # changes in one tree (and a failed apply can't be cleanly undone). Opt out
    # explicitly with --allow-dirty.
    if not check_only and not allow_dirty and _tree_is_dirty(repo_path):
        raise click.UsageError(
            "target working tree has uncommitted changes — commit/stash them "
            "first, or pass --allow-dirty")

    _git_apply(repo_path, change.diff, check_only=check_only)
    action = "checked" if check_only else "applied"
    click.secho(f"{action} {run_id} -> {repo_path}", fg="green")


# Written at repo root by the guided run (guide.py) on every task/reconfigure — the
# tool's own per-run control files, not user work-in-progress. Their presence must
# never count as a dirty tree, or the guided flow would block its own `apply` on
# every single run (task.yaml/bounds.json are rewritten each task step).
_TOOL_OWNED_ROOT_FILES = {"task.yaml", "bounds.json", "sembl.stack.yaml"}


def _tree_is_dirty(repo: Path) -> bool:
    """Uncommitted changes in the working tree, ignoring the run store (.sembl/) and
    the tool's own control files (task.yaml/bounds.json/sembl.stack.yaml at repo root)."""
    proc = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if proc.returncode != 0:       # not a git repo etc. — git apply will say so
        return False
    # porcelain v1: `XY path` (rename: `XY old -> new`); path starts at column 3
    paths = (line[3:].strip().strip('"') for line in proc.stdout.splitlines() if len(line) > 3)
    return any(p and not p.startswith(".sembl") and p.lower() not in _TOOL_OWNED_ROOT_FILES
              for p in paths)


def _git_apply(repo: Path, diff: str, *, check_only: bool) -> None:
    check = subprocess.run(
        ["git", "apply", "--check", "-"], cwd=repo, input=diff,
        capture_output=True, text=True)
    if check.returncode != 0:
        raise click.ClickException(
            "patch does not apply cleanly: "
            + (check.stderr.strip() or check.stdout.strip() or "git apply --check failed"))
    if check_only:
        return
    proc = subprocess.run(
        ["git", "apply", "-"], cwd=repo, input=diff,
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise click.ClickException(
            proc.stderr.strip() or proc.stdout.strip() or "git apply failed")


@main.command()
@click.option("--repo", default=".")
@click.option("--refresh", default=3.0, show_default=True,
              help="Seconds between live refreshes (0 to disable).")
def dash(repo, refresh):
    """Live run dashboard (O6 TUI). Needs the tui extra: pip install 'sembl-stack[tui]'."""
    from . import tui
    if not tui.available():
        raise click.UsageError(
            "the TUI needs Textual — `pip install \"sembl-stack[tui]\"`.\n"
            "  (meanwhile `sembl-stack runs` and `runs <id>` give the same data as text.)")
    store = RunStore(repo)
    if not store.list_runs():
        click.echo("no runs yet — try `sembl-stack loop task.yaml`")
        return
    tui.run_dashboard(store, refresh_s=refresh)


def _show_run(store, run_id: str) -> None:
    """Detailed single-run view: task, bounds, per-attempt verdict+latency, final."""
    run = store.open(run_id)
    m = run.manifest()
    if not m:
        raise click.UsageError(f"no run '{run_id}' under {store.root}")
    click.secho(f"run {run_id}", bold=True)
    lat = m.get("total_latency_s")
    lat_s = f"{lat:.2f}s" if isinstance(lat, (int, float)) else "-"
    click.echo(f"  status:  {m.get('status','?')}   attempts={m.get('attempts','-')}   "
               f"engine={m.get('engine','-')}   latency={lat_s}")
    task = m.get("task", {})
    if task:
        click.echo(f"  task:    {task.get('text','')}")
        click.echo(f"  repo:    {task.get('repo','')}")
    bounds = run.get("bounds")
    if bounds is not None:
        click.echo(f"  bounds:  editable={bounds.editable_paths}  "
                   f"forbidden={bounds.forbidden_areas}  churn={bounds.churn_budget}")

    log = {e.get("attempt"): e for e in m.get("attempts_log", [])}
    n = m.get("attempts") or 0
    if n:
        click.echo("  attempts:")
    for i in range(1, n + 1):
        v = run.get(f"verdict-{i}")
        meta = log.get(i, {})
        status = v.status if v else "?"
        color = "green" if status == "PASS" else "yellow" if status == "WARN" else "red"
        extra = f"  model={meta['model']}" if meta.get("model") else ""
        click.secho(f"    {i}: [{status}]  latency={meta.get('latency_s','-')}s{extra}",
                    fg=color)
        for r in (v.reasons if v else []):
            click.echo(f"         - {r}")

    fv = run.get("verdict")
    if fv is not None:
        color = "green" if fv.status == "PASS" else "yellow" if fv.status == "WARN" else "red"
        click.secho(f"  final:   {fv.status}", fg=color)
    ch = run.get("change")
    if ch is None and n:
        ch = run.get(f"change-{n}")
    if ch is not None:
        files = (getattr(ch, "report", {}) or {}).get("files_modified") or []
        suffix = f"  files={files}" if files else ""
        click.echo(f"  patch:   change.json{suffix}")
        if fv is not None and fv.status in ("PASS", "WARN"):
            repo = (task or {}).get("repo", ".")
            warn = " --allow-warn" if fv.status == "WARN" else ""
            click.echo(f"  apply:   sembl-stack apply {run_id} --repo {repo}{warn}")
    click.echo(f"  artifacts: {run.dir}")


if __name__ == "__main__":
    main()
