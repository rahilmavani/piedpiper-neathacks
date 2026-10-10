"""`culprit` command line (PRD §13)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import typer
from dotenv import load_dotenv

from culprit import providers, tracing
from culprit.config import DEFAULT_DB, PROJECT_ROOT, STATE_DIR, Config
from culprit.ledger import Ledger
from culprit.orchestrator import Orchestrator

app = typer.Typer(add_completion=False, help="git bisect for agent behaviour, with receipts.")


@app.command()
def run(
    good: str = typer.Option(..., help="Known-good ref"),
    bad: str = typer.Option(..., help="Known-bad ref"),
    repo: Path = typer.Option(PROJECT_ROOT.parent / "refunddesk", envvar="CULPRIT_VICTIM_REPO",
                              help="Victim repo (only worktrees are created)"),
    suite: str = typer.Option("evals", help="Suite directory in the victim (taken at --suite-ref), "
                              "or a directory on disk (absolute or containing '/')"),
    suite_ref: str = typer.Option("main", help="Victim ref whose suite judges every commit"),
    k: int = typer.Option(3, help="Repetitions per task"),
    budget_usd: float = typer.Option(3.00, help="Hard cost cap for this run"),
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
    reuse: bool = typer.Option(True, help="Reuse matching baseline results from earlier runs in the ledger"),
    staged: bool = typer.Option(True, help="Screen every task ×1 before running the full k on the ends"),
) -> None:
    """Find the commit between GOOD and BAD that broke the agent. `--no-reuse --no-staged` is v1."""
    try:
        victim = providers.select("VICTIM_MODEL")
    except providers.ProviderError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    cfg = Config(repo=str(repo.resolve()), good_ref=good, bad_ref=bad, suite=suite, suite_ref=suite_ref, k=k,
                 budget_usd=budget_usd, victim_provider=victim.name, victim_model=victim.model,
                 reuse_baselines=reuse, staged_baseline=staged)
    orch = Orchestrator(Ledger(db), cfg, log=typer.echo, workers=workers)
    run_id = orch.start()
    typer.echo(f"run_id {run_id}")
    outcome = orch.run(run_id)
    typer.echo(f"neatlogs session: {run_id}" if tracing.enabled() else "neatlogs tracing off (no NEATLOGS_API_KEY)")
    raise typer.Exit(0 if outcome.status in {"found", "no_regression"} else 1)


@app.command()
def resume(
    run_id: str,
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
    budget_usd: float | None = typer.Option(None, help="Raise the per-run cost cap (e.g. after budget_exceeded)"),
) -> None:
    """Continue a run without re-executing completed steps."""
    ledger = Ledger(db)
    row = ledger.get_run(run_id)
    cfg = Config.from_json(row["config_json"])
    if budget_usd is not None:
        cfg = replace(cfg, budget_usd=budget_usd)
        ledger.update_config(run_id, row["suite_hash"], cfg.to_json())
    outcome = Orchestrator(ledger, cfg, log=typer.echo, workers=workers).run(run_id)
    raise typer.Exit(0 if outcome.status in {"found", "no_regression"} else 1)


@app.command("verify-trace")
def verify_trace(
    run_id: str,
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
) -> None:
    """Read a run's Culprit traces back from neatlogs and audit them against the trace contract."""
    from culprit.readback import audit

    traces = (Ledger(db).get_artifact(run_id, "neatlogs_traces") or "").split()
    if not traces:
        typer.echo(f"no neatlogs trace recorded for run {run_id}")
        raise typer.Exit(1)
    failed = False
    for trace_id in traces:
        result = audit(trace_id, run_id)
        typer.echo(f"trace {trace_id}: finalized={result.finalized} workflow={result.workflow} "
                   f"session={result.session} spans={result.span_count}")
        typer.echo("  " + ", ".join(f"{k}×{v}" for k, v in sorted(result.by_name.items())))
        for problem in result.problems:
            typer.echo(f"  PROBLEM {problem}")
        typer.echo("  PASS" if result.ok else "  FAIL")
        failed |= not result.ok
    raise typer.Exit(1 if failed else 0)


@app.command()
def report(
    run_id: str,
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    out: Path = typer.Option(STATE_DIR / "reports", help="Directory for report-<run_id>.md and .html"),
) -> None:
    """Write a run's report as markdown and a static HTML page."""
    from culprit.report import write

    md, html = write(Ledger(db), run_id, out)
    typer.echo(f"{md}\n{html}")


@app.command("export-costs")
def export_costs(
    format: str = typer.Option("csv", "--format", help="Output format (csv)"),
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    out: Path | None = typer.Option(None, help="Write to this file instead of stdout"),
) -> None:
    """Per-run cost, victim runs and wall time for every run in the ledger (input for cfo.ai)."""
    import sys

    from culprit.costs import all_runs, write_csv

    if format != "csv":
        typer.echo(f"error: unsupported format {format!r} (supported: csv)", err=True)
        raise typer.Exit(2)
    rows = all_runs(Ledger(db))
    if out is None:
        write_csv(rows, sys.stdout)
    else:
        with out.open("w", newline="") as f:
            write_csv(rows, f)
        typer.echo(f"{len(rows)} runs → {out}")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    tracing.init()
    try:
        app()
    finally:
        tracing.shutdown()
