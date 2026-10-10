"""`culprit` command line (PRD §13)."""

from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv

from culprit.config import DEFAULT_DB, PROJECT_ROOT, Config
from culprit.ledger import Ledger
from culprit.orchestrator import Orchestrator

app = typer.Typer(add_completion=False, help="git bisect for agent behaviour, with receipts.")


@app.command()
def run(
    good: str = typer.Option(..., help="Known-good ref"),
    bad: str = typer.Option(..., help="Known-bad ref"),
    repo: Path = typer.Option(PROJECT_ROOT.parent / "refunddesk", help="Victim repo (only worktrees are created)"),
    suite: str = typer.Option("evals", help="Suite directory inside the victim repo"),
    k: int = typer.Option(3, help="Repetitions per task"),
    budget_usd: float = typer.Option(3.00, help="Hard cost cap for this run"),
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
) -> None:
    """Find the commit between GOOD and BAD that broke the agent."""
    cfg = Config(repo=str(repo.resolve()), good_ref=good, bad_ref=bad, suite=suite, k=k, budget_usd=budget_usd)
    orch = Orchestrator(Ledger(db), cfg, log=typer.echo, workers=workers)
    run_id = orch.start()
    typer.echo(f"run_id {run_id}")
    outcome = orch.run(run_id)
    raise typer.Exit(0 if outcome.status in {"found", "no_regression"} else 1)


@app.command()
def resume(
    run_id: str,
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
) -> None:
    """Continue a run without re-executing completed steps."""
    ledger = Ledger(db)
    cfg = Config.from_json(ledger.get_run(run_id)["config_json"])
    outcome = Orchestrator(ledger, cfg, log=typer.echo, workers=workers).run(run_id)
    raise typer.Exit(0 if outcome.status in {"found", "no_regression"} else 1)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    app()
