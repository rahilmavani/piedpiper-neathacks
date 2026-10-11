"""`culprit` command line (PRD §13)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import typer
from dotenv import load_dotenv

from culprit import providers, tracing
from culprit.config import DEFAULT_DB, PROJECT_ROOT, SOURCE_CHECKOUT, STATE_DIR, Config
from culprit.ledger import Ledger
from culprit.orchestrator import Orchestrator
from culprit.project import ProjectError, Settings
from culprit.project import resolve as resolve_project

app = typer.Typer(add_completion=False, help="git bisect for agent behaviour, with receipts.")
EVAL_MODULE_OPTION = typer.Option(None, "--eval-module", envvar="CULPRIT_EVAL_MODULE", show_default=False,
                                  help="The victim's eval runner module (python -m <module> --task <id> --seed <n>) "
                                  "(default: from culprit.toml)")
REPO_OPTION = typer.Option(None, "--repo", envvar="CULPRIT_VICTIM_REPO", show_default=False,
                           help="Victim repo; only worktrees are created (default: the repo holding culprit.toml, "
                           "else the current directory)")
SUITE_OPTION = typer.Option(None, "--suite", show_default=False,
                            help="Suite directory in the victim (taken at --suite-ref), or a directory on disk "
                            "(absolute or containing '/') (default: from culprit.toml, else evals)")
SUITE_REF_OPTION = typer.Option(None, "--suite-ref", show_default=False,
                                help="Victim ref whose suite judges every commit (default: from culprit.toml, else main)")


def _settings(repo: Path | None, eval_module: str | None, suite: str | None = None,
              suite_ref: str | None = None) -> Settings:
    try:
        return resolve_project(repo, eval_module, suite, suite_ref)
    except ProjectError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc


@app.command()
def run(
    good: str = typer.Option(..., help="Known-good ref"),
    bad: str = typer.Option(..., help="Known-bad ref"),
    repo: Path | None = REPO_OPTION,
    suite: str | None = SUITE_OPTION,
    suite_ref: str | None = SUITE_REF_OPTION,
    k: int = typer.Option(3, help="Repetitions per task"),
    budget_usd: float = typer.Option(3.00, help="Hard cost cap for this run"),
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
    reuse: bool = typer.Option(True, help="Reuse matching baseline results from earlier runs in the ledger"),
    staged: bool = typer.Option(True, help="Screen every task ×1 before running the full k on the ends"),
    eval_module: str | None = EVAL_MODULE_OPTION,
) -> None:
    """Find the commit between GOOD and BAD that broke the agent. `--no-reuse --no-staged` is v1."""
    project = _settings(repo, eval_module, suite, suite_ref)
    try:
        victim = providers.select("VICTIM_MODEL")
    except providers.ProviderError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    cfg = Config(repo=str(project.repo), good_ref=good, bad_ref=bad, suite=project.suite,
                 suite_ref=project.suite_ref, k=k, budget_usd=budget_usd, victim_provider=victim.name,
                 victim_model=victim.model, reuse_baselines=reuse, staged_baseline=staged,
                 eval_module=project.eval_module)
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
    ground_truth: Path | None = typer.Option(None, help="Answer key (default: ground_truth.json next to "
                                             "--scenarios)"),
    repo: Path | None = REPO_OPTION,
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
    eval_module: str | None = EVAL_MODULE_OPTION,
) -> None:
    """Run each scenario through Culprit and score it against ground truth (or score existing runs)."""
    from culprit import bench as b

    project = _settings(repo, eval_module)
    repo, eval_module = project.repo, project.eval_module

    if not tag.replace("-", "").replace("_", "").replace(".", "").isalnum():
        typer.echo("error: --tag may contain only letters, digits, '.', '-' and '_'", err=True)
        raise typer.Exit(2)
    ids = [i for item in score_runs for i in item.split(",") if i]
    if ids and score_latest:
        typer.echo("error: use --score-runs or --score-latest, not both", err=True)
        raise typer.Exit(2)
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
                                      victim_model=victim.model, eval_module=eval_module)
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
    replay: bool = typer.Option(False, help="Only replay what the ledger holds: no key, model call or victim run; "
                                "fails if anything else is needed"),
) -> None:
    """Find which hunk of a found run's culprit commit is responsible (PRD §8.3). Re-running resumes."""
    from culprit import localise as loc
    from culprit.finished import StageError

    try:
        result, _ = loc.localise_run(Ledger(db), run_id, log=typer.echo, workers=workers, top_n=top_n,
                                     max_pairs=max_pairs, budget_usd=budget_usd, replay=replay)
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
    replay: bool = typer.Option(False, help="Only replay what the ledger holds: no key, model call or victim run; "
                                "fails if anything else is needed"),
) -> None:
    """Write and verify a minimal fix for a localised run (PRD §8.4, §10). Re-running resumes."""
    from culprit import fix as fixer
    from culprit.finished import StageError

    try:
        result = fixer.fix_run(Ledger(db), run_id, log=typer.echo, workers=workers, attempts=attempts,
                               tolerance=tolerance, budget_usd=budget_usd, replay=replay)
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


def _victim_config(project: Settings, ref: str, k: int, budget_usd: float) -> Config:
    try:
        victim = providers.select("VICTIM_MODEL")
    except providers.ProviderError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    return Config(repo=str(project.repo), good_ref=ref, bad_ref=ref, suite=project.suite,
                  suite_ref=project.suite_ref, k=k, budget_usd=budget_usd, victim_provider=victim.name,
                  victim_model=victim.model, eval_module=project.eval_module)


@app.command()
def drift(
    ref: str = typer.Option(..., help="A known-good ref whose baseline is already recorded in the ledger"),
    against: str | None = typer.Option(None, help="Compare with this run's recorded baseline (default: the oldest)"),
    repo: Path | None = REPO_OPTION,
    k: int = typer.Option(3, help="Repetitions per task (must match the recorded baseline)"),
    budget_usd: float = typer.Option(2.00, help="Hard cost cap for the check"),
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
    eval_module: str | None = EVAL_MODULE_OPTION,
) -> None:
    """Did we break it, or did the world change? Re-run a known-good ref now and compare it with its record."""
    from culprit.drift import DriftError, drift_run

    cfg = _victim_config(_settings(repo, eval_module), ref, k, budget_usd)
    try:
        result = drift_run(Ledger(db), cfg, ref, log=typer.echo, workers=workers, against=against)
    except DriftError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    raise typer.Exit({"stable": 0, "improved": 0, "drifted": 1}.get(result.status, 2))


@app.command()
def audit(
    ref: str = typer.Option("HEAD", help="The version of the agent to mutate"),
    operators: str | None = typer.Option(None, help="Comma-separated mutation operators (default: all); "
                                         "see `culprit audit --list`"),
    patches: Path | None = typer.Option(None, help="A directory of your own *.patch mutants (no model calls)"),
    run_id: str | None = typer.Option(None, "--run-id", help="Resume this audit run (stored mutants are reused)"),
    repo: Path | None = REPO_OPTION,
    suite: str | None = SUITE_OPTION,
    suite_ref: str | None = SUITE_REF_OPTION,
    k: int = typer.Option(3, help="Repetitions per task"),
    budget_usd: float = typer.Option(3.00, help="Hard cost cap for the audit"),
    out: Path | None = typer.Option(None, help="Write the markdown report here"),
    list_operators: bool = typer.Option(False, "--list", help="List the mutation operators and exit"),
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
    eval_module: str | None = EVAL_MODULE_OPTION,
) -> None:
    """Which realistic regressions would your eval suite miss? Mutation testing for agents."""
    from culprit import audit as a

    if list_operators:
        for op in a.OPERATORS:
            typer.echo(f"{op.name:24} {op.title}: {op.instruction}")
        raise typer.Exit(0)
    cfg = _victim_config(_settings(repo, eval_module, suite, suite_ref), ref, k, budget_usd)
    try:
        result = a.audit_run(Ledger(db), cfg, ref, log=typer.echo, workers=workers,
                             operators=operators.split(",") if operators else None, patches=patches, run_id=run_id)
    except (a.AuditError, KeyError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    markdown = a.to_markdown(result)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown)
        typer.echo(f"report → {out}")
    raise typer.Exit(0 if result.status == "audited" else 2)


@app.command()
def ci(
    base: str = typer.Option(..., help="The PR's base (known good)"),
    head: str = typer.Option(..., help="The PR's head"),
    repo: Path | None = REPO_OPTION,
    suite: str | None = SUITE_OPTION,
    suite_ref: str | None = SUITE_REF_OPTION,
    k: int = typer.Option(3, help="Repetitions per task"),
    budget_usd: float = typer.Option(3.00, help="Hard cost cap for the gate and bisect"),
    localise: bool = typer.Option(True, help="Name the responsible hunk when a culprit is found"),
    fix: bool = typer.Option(False, help="Also propose and verify a fix (costs more)"),
    comment_file: Path = typer.Option(Path("culprit-comment.md"), "--comment-file", help="PR comment (markdown)"),
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    workers: int = typer.Option(4, help="Parallel victim task runs"),
    eval_module: str | None = EVAL_MODULE_OPTION,
) -> None:
    """Regression gate for a pull request. Exit 0 clean, 1 regression (comment names the culprit), 2 stopped."""
    from culprit.ci import ci_run

    cfg = replace(_victim_config(_settings(repo, eval_module, suite, suite_ref), base, k, budget_usd),
                  good_ref=base, bad_ref=head)
    result = ci_run(Ledger(db), cfg, log=typer.echo, workers=workers, localise=localise, fix=fix)
    comment_file.write_text(result.comment)
    typer.echo(f"{result.status}: comment → {comment_file}")
    raise typer.Exit(result.exit_code)


@app.command()
def comment(
    run_id: str,
    db: Path = typer.Option(DEFAULT_DB, help="Ledger path"),
    out: Path | None = typer.Option(None, help="Write here instead of stdout"),
) -> None:
    """The pull-request comment for a finished run, from the ledger alone ($0, no network)."""
    from culprit.ci import comment as render

    try:
        text = render(Ledger(db, readonly=True), run_id)
    except KeyError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if out is None:
        typer.echo(text, nl=False)
    else:
        out.write_text(text)
        typer.echo(f"comment → {out}")


@app.command()
def init(
    repo: Path = typer.Option(Path("."), help="Your agent's repo (any directory inside it)"),
    eval_module: str | None = typer.Option(None, "--eval-module", help="Module that runs one task "
                                           "(python -m <module> --task <id> --seed <n>) (default: detected)"),
    suite: str | None = typer.Option(None, help="Directory with one file per task (default: evals)"),
    suite_ref: str | None = typer.Option(None, help="Ref whose suite judges every commit (default: current branch)"),
    check: bool | None = typer.Option(None, "--check/--no-check", help="Run one task to check its output "
                                      "(calls your model once) (default: ask; no with --yes)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept the defaults without asking"),
) -> None:
    """Set up your agent's repo: model key, eval module and suite, saved to culprit.toml and .env."""
    from culprit import onboard
    from culprit.project import FILENAME, write

    def ask(question: str, default: str) -> str:
        return default if yes else typer.prompt(question, default=default)

    try:
        root = onboard.git_root(repo.resolve())
    except onboard.SetupError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"Setting up {root}")
    if not (root / "uv.lock").is_file():
        typer.echo("  warning: no uv.lock. Culprit installs each commit with `uv sync --locked`, so commit a "
                   "uv.lock (run `uv lock`) or every commit will be skipped.")

    keys = onboard.key_status(root)
    if keys:
        typer.echo("  model key: " + ", ".join(f"{name} ({where})" for name, where in keys.items()))
    elif yes:
        typer.echo("error: no model key. Set ANTHROPIC_API_KEY or OPENROUTER_API_KEY, or run without --yes",
                   err=True)
        raise typer.Exit(2)
    else:
        provider = ""
        while provider not in onboard.KEY_NAMES:
            provider = typer.prompt(f"Which provider do you have a key for? ({' or '.join(onboard.KEY_NAMES)})",
                                    default="openrouter").strip().lower()
        name = onboard.KEY_NAMES[provider]
        value = typer.prompt(f"{name}", hide_input=True).strip()
        path = onboard.save_key(root, name, value)
        typer.echo(f"  saved {name} to {path} (readable only by you)")
    providers.load_repo_env(root / ".env")
    try:
        victim = providers.select("VICTIM_MODEL")
        typer.echo(f"  your agent will run on {victim.model} via {victim.name} during a bisect")
    except providers.ProviderError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc

    candidates = onboard.eval_modules(root)
    default_module = eval_module or (candidates[0] if candidates else "")
    if candidates and not eval_module:
        typer.echo("  eval modules found: " + ", ".join(candidates))
    if yes and not default_module:
        typer.echo("error: no eval module found; pass --eval-module", err=True)
        raise typer.Exit(2)
    eval_module = eval_module or (default_module if yes else typer.prompt(
        "Eval module (python -m <module> --task <id> --seed <n> prints one JSON line)",
        default=default_module or None))
    suite = suite or ask("Suite directory (one file per task)", "evals")
    tasks = onboard.suite_tasks(root, suite)
    typer.echo(f"  {len(tasks)} tasks in {suite}/" + (f": {', '.join(tasks[:5])}{' …' if len(tasks) > 5 else ''}"
                                                       if tasks else " (add one file per task before a run)"))
    suite_ref = suite_ref or ask("Ref whose suite judges every commit", onboard.current_branch(root))

    added = onboard.ignore_local_files(root)
    if added:
        typer.echo(f"  added {', '.join(added)} to .gitignore")
    path = write(root, eval_module, suite, suite_ref)
    typer.echo(f"  wrote {path}")

    if check is None:
        check = False if yes else bool(tasks) and typer.confirm(
            f"Run task {tasks[0]} once now to check its output? It calls your model once", default=True)
    if check:
        if not tasks:
            typer.echo("error: no tasks to check", err=True)
            raise typer.Exit(2)
        result = onboard.check_eval(root, eval_module, tasks[0], victim)
        typer.echo(("  check passed: " if result.ok else "  check FAILED: ") + result.message)
        if not result.ok:
            raise typer.Exit(1)
    typer.echo(f"\nReady. From {root}:\n  culprit run --good <a good tag or commit> --bad HEAD --budget-usd 3\n"
               f"Commit {FILENAME} so your team and CI use the same settings.")


def main() -> None:
    # Keys: the environment wins, then the model keys and models (only those) from the current directory's
    # .env, then, in a clone of this repo, all of Culprit's own .env. Nothing overrides a variable already set.
    providers.load_repo_env(Path.cwd() / ".env")
    if SOURCE_CHECKOUT:
        load_dotenv(PROJECT_ROOT / ".env")
    tracing.init()
    try:
        app()
    finally:
        tracing.shutdown()
