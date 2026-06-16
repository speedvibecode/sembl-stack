"""sembl-stack CLI.

Each stage is independently invokable and reads/writes artifacts, so you can run the
whole loop OR any subset, enter at any point (supply the upstream artifact), and slot a
custom step between two stages (read the upstream artifact, write the downstream one):

    sembl-stack bounds  --task t.yaml                 --out bounds.json
    sembl-stack execute --task t.yaml --bounds b.json --out change.json
    sembl-stack verify  --change change.json --bounds b.json     # the gate, standalone
    sembl-stack loop    t.yaml                                    # the full wiring
"""
from __future__ import annotations

import json
from pathlib import Path

import click
import yaml

from . import artifacts, registry
from .artifacts import Bounds, Change, Task, Verdict
from .config import load
from .loop import run as run_loop
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
    return Bounds.from_json(Path(path).read_text(encoding="utf-8"))


# --- full loop ----------------------------------------------------------------

@click.group()
@click.version_option()
def main():
    """sembl-stack — an open, swappable spec-driven coding factory."""


@click.argument("task_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--config", "config_path", default="sembl.stack.yaml")
def _loop_cmd(task_file: str, config_path: str):
    """Run the full wiring: plan -> execute -> verify (retry on BLOCK)."""
    task = _load_task(task_file, None, None, None)
    cfg = load(config_path if Path(config_path).is_file() else None)
    click.echo(f"layers: {cfg.raw['layers']}")
    click.echo(f"task: {task.text!r}\nrepo: {task.repo}\n")

    result = run_loop(cfg, task)

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
@click.option("--out", default=None, help="Write the Bounds artifact here (else stdout).")
def bounds(task_file, repo, spec, text, config_path, out):
    """L2: Task -> Bounds. Derive the scope contract from a spec."""
    task = _load_task(task_file, repo, spec, text)
    cfg = load(config_path if Path(config_path).is_file() else None)
    _emit(cfg.spec.plan(task), out)


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
    cfg = load(config_path if Path(config_path).is_file() else None)
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


# --- introspection ------------------------------------------------------------

@main.command()
def layers():
    """List the available adapters per layer."""
    for layer in ("spec", "execute", "sandbox", "verify"):
        click.echo(f"{layer:9}: {', '.join(registry.names(layer))}")


@main.command()
@click.option("--repo", default=".")
def runs(repo):
    """List recorded runs (the run store) — the signal source for self-improvement."""
    store = RunStore(repo)
    ids = store.list_runs()
    if not ids:
        click.echo("no runs yet")
        return
    for rid in ids:
        m = store.open(rid).manifest()
        click.echo(f"{rid}  {m.get('status','?'):6}  "
                   f"attempts={m.get('attempts','-')}  {m.get('task',{}).get('text','')}")


if __name__ == "__main__":
    main()
