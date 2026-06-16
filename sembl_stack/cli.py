"""sembl-stack CLI."""
from __future__ import annotations

from pathlib import Path

import click
import yaml

from . import registry
from .adapters.base import Task
from .config import load
from .loop import run as run_loop


@click.group()
@click.version_option()
def main():
    """sembl-stack — an open, swappable spec-driven coding factory."""


@main.command()
@click.argument("task_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--config", "config_path", default="sembl.stack.yaml",
              help="Path to sembl.stack.yaml (the swappable-layer config).")
def run(task_file: str, config_path: str):
    """Run the short loop on a task: plan -> execute -> verify (retry on BLOCK)."""
    spec = yaml.safe_load(Path(task_file).read_text(encoding="utf-8")) or {}
    base = Path(task_file).resolve().parent

    def _resolve(p):
        if not p:
            return p
        pp = Path(p)
        return str(pp if pp.is_absolute() else (base / pp).resolve())

    task = Task(
        text=spec.get("text", ""),
        repo=_resolve(spec.get("repo", ".")),
        spec_path=_resolve(spec.get("spec_path")),
    )

    cfg = load(config_path if Path(config_path).is_file() else None)
    click.echo(f"layers: {cfg.raw['layers']}  (engine resolves at runtime)")
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
    raise SystemExit(0 if v.status in ("PASS", "WARN") else 1)


@main.command()
def layers():
    """List the available adapters per layer."""
    for layer in ("spec", "execute", "sandbox", "verify"):
        click.echo(f"{layer:9}: {', '.join(registry.names(layer))}")


if __name__ == "__main__":
    main()
