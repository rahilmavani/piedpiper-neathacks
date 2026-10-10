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


@app.command()
def bench(
    tag: str = typer.Option(..., help="Label for this benchmark (e.g. v1, v2); names evidence/bench-<tag>.md"),
    scenarios: Path = typer.Option(PROJECT_ROOT / "bench" / "scenarios.yaml", help="Scenario list"),
    ground_truth: Path | None = typer.Option(None, help="Answer key [default: ground_truth.json next to "
                                             "--scenarios]"),
    repo: Path = typer.Option(PROJECT_ROOT.parent / "refunddesk", envvar="CULPRIT_VICTIM_REPO",
                              help="Victim repo (only worktrees are created)"),
    only: list[str] = typer.Option([], help="Run or score only these scenarios (repeatable)"),
    score_runs: list[str] = typer.Option([], help="Score these existing run IDs instead of running "
                                         "(repeatable or comma-separated); matched to scenarios by good/bad SHA"),
    score_latest: bool = typer.Option(False, help="Score each scenario's latest matching run in the ledger "
                                      "instead of running"),
    k: int = typer.Option(3, help="Repetitions per task"),
    budget_usd: float = typer.Option(3.00, help="Hard cost cap per scenario run"),
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
    out_dir: Path = typer.Option(PROJECT_ROOT / "evidence", help="Where bench-<tag>.md/.json are written"),
) -> None:
    """Run each scenario through Culprit and score it against ground truth (or score existing runs)."""
    from culprit import bench as b

    if not tag.replace("-", "").replace("_", "").replace(".", "").isalnum():
        typer.echo("error: --tag may contain only letters, digits, '.', '-' and '_'", err=True)
        raise typer.Exit(2)
    ids = [i for item in score_runs for i in item.split(",") if i]
    if ids and score_latest:
        typer.echo("error: use --score-runs or --score-latest, not both", err=True)
        raise typer.Exit(2)
    repo = repo.resolve()
    truth_path = ground_truth or scenarios.parent / "ground_truth.json"
    try:
        b.guard_outside_repo(repo, scenarios, truth_path)
        selected = b.load_scenarios(scenarios)
        truth = b.load_ground_truth(truth_path)
        if only:
            unknown = set(only) - {s.name for s in selected}
            if unknown:
                raise b.BenchError(f"unknown scenario(s): {', '.join(sorted(unknown))}")
            selected = [s for s in selected if s.name in only]
        if ids or score_latest:
            ledger = Ledger(db, readonly=True)  # scoring never writes, so it is safe on a ledger in use
            run_ids = b.match_runs(ledger, repo, selected, ids or None)
            mode = f"scored existing runs from `{db}`"
        else:
            victim = providers.select("VICTIM_MODEL")
            ledger = Ledger(db)
            typer.echo(f"bench {tag}: {len(selected)} scenarios, victim {victim.model} via {victim.name}, "
                       f"cap ${budget_usd:.2f} each")
            run_ids = b.run_scenarios(ledger, repo, selected, log=typer.echo, workers=workers, k=k,
                                      budget_usd=budget_usd, victim_provider=victim.name,
                                      victim_model=victim.model)
            mode = "fresh runs (`culprit bench`)"
        rows = b.score_runs(ledger, repo, truth, {s.name: run_ids[s.name] for s in selected if s.name in run_ids})
    except (b.BenchError, providers.ProviderError, KeyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    for row in rows:
        typer.echo(f"{row.scenario}: {row.outcome} ({row.facts.status}, run {row.facts.run_id}, "
                   f"{row.facts.victim_runs} runs, ${row.facts.cost_usd:.2f})")
    missing = [s.name for s in selected if s.name not in run_ids]
    if missing:
        typer.echo(f"no run found for: {', '.join(missing)}")
    path = b.write_report(out_dir, tag, rows, mode, repo, missing)
    typer.echo(f"accuracy {b.accuracy_text(rows)}; report {path}")


@app.command()
def localise(
    run_id: str,
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
    top_n: int = typer.Option(3, help="Hunks whose single revert is tested, in rank order"),
    max_pairs: int = typer.Option(3, help="Pairs of those hunks tried when no single revert restores the agent"),
    budget_usd: float = typer.Option(1.50, help="Cost cap for localisation, on top of the run's cost so far"),
) -> None:
    """Find which hunk of a found run's culprit commit is responsible (PRD §8.3). Re-running resumes."""
    from culprit import localise as loc
    from culprit.finished import StageError

    try:
        result, _ = loc.localise_run(Ledger(db), run_id, log=typer.echo, workers=workers, top_n=top_n,
                                     max_pairs=max_pairs, budget_usd=budget_usd)
    except (StageError, KeyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    raise typer.Exit(1 if result.status == "incomplete" else 0)


@app.command()
def fix(
    run_id: str,
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
    attempts: int = typer.Option(2, help="Fix proposals verified before falling back to the hunk revert"),
    tolerance: float = typer.Option(0.10, help="How much worse than bad the intended-gain metric may get"),
    budget_usd: float = typer.Option(2.00, help="Cost cap for fixing, on top of the run's cost so far"),
) -> None:
    """Write and verify a minimal fix for a localised run (PRD §8.4, §10). Re-running resumes."""
    from culprit import fix as fixer
    from culprit.finished import StageError

    try:
        result = fixer.fix_run(Ledger(db), run_id, log=typer.echo, workers=workers, attempts=attempts,
                               tolerance=tolerance, budget_usd=budget_usd)
    except (StageError, KeyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    raise typer.Exit(0 if result.status in {"verified_fix", "verified_revert"} else 1)


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
