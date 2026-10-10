"""M2 on the fixture victim: Wilson decisions, resampling, low-confidence flag, budget stop and resume."""

import importlib
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit.ledger import Ledger, TaskRun  # noqa: E402


@pytest.fixture()
def mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox

    for mod in (culprit.config, culprit.sandbox, culprit.orchestrator):
        importlib.reload(mod)
    return culprit.orchestrator, culprit.config


def culprit_sha(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "log", "--format=%H", "--grep=speed up tool handling"], text=True
    ).strip()


def new_run(orchestrator, config, repo: Path, db: Path, **overrides):
    cfg = config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main", **overrides)
    orch = orchestrator.Orchestrator(Ledger(db), cfg, log=lambda _: None)
    return orch, orch.start()


def test_threshold_uses_the_same_task_mix(mods):
    orchestrator, _ = mods

    def runs(spec):
        return [TaskRun(t, i, p, None, None, None, None, None) for i, (t, p) in enumerate(spec)]

    base = orchestrator.Baselines(
        orchestrator.StepResult("g", False, runs([("a", True), ("a", True), ("b", True), ("b", True)])),
        orchestrator.StepResult("b", False, runs([("a", False), ("a", False), ("b", True), ("b", True)])),
    )
    assert base.threshold(runs([("a", True)])) == pytest.approx(0.5)
    assert base.threshold(runs([("a", True), ("b", True)])) == pytest.approx(0.75)


def test_inconclusive_commit_is_resampled_then_flagged(mods, tmp_path: Path):
    orchestrator, config = mods
    repo = build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7, noisy_from=9, noisy_pass=0.6)
    orch, run_id = new_run(orchestrator, config, repo, tmp_path / "l.sqlite")
    outcome = orch.run(run_id)

    assert outcome.status == "found"
    assert outcome.result.first_bad == culprit_sha(repo)
    steps = {(s["kind"], s["commit_sha"]): s for s in orch.ledger.steps(run_id)}
    kinds = {k for k, _ in steps}
    assert {"resample:1", "resample:2"} <= kinds
    assert any(s["flags"] == "low_confidence" for s in steps.values())
    assert any(s["decision"] == "SKIP" for s in steps.values())
    assert orch.ledger.get_run(run_id)["confidence"].startswith("low")


def test_no_regression_when_baselines_overlap(mods, tmp_path: Path):
    orchestrator, config = mods
    repo = build(tmp_path / "victim", commits=6, breaks_at=99, unbuildable_at=None)
    orch, run_id = new_run(orchestrator, config, repo, tmp_path / "l.sqlite")
    assert orch.run(run_id).status == "no_regression"


def test_budget_stop_reports_range_and_resume_finishes(mods, tmp_path: Path):
    orchestrator, config = mods
    repo = build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7)
    db = tmp_path / "l.sqlite"
    orch, run_id = new_run(orchestrator, config, repo, db, budget_usd=0.09)
    stopped = orch.run(run_id)
    assert stopped.status == "budget_exceeded"
    assert culprit_sha(repo) in stopped.result.suspects
    assert len(stopped.result.suspects) < 14

    ledger = Ledger(db)
    cfg = replace(config.Config.from_json(ledger.get_run(run_id)["config_json"]), budget_usd=3.0)
    finished = orchestrator.Orchestrator(ledger, cfg, log=lambda _: None).run(run_id)
    assert finished.status == "found"
    assert finished.result.first_bad == culprit_sha(repo)
    dupes = ledger.conn.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT step_id || ':' || task_id || ':' || repetition) FROM task_runs"
    ).fetchone()[0]
    assert dupes == 0


def test_global_cap_counts_every_run_in_the_ledger(mods, tmp_path: Path):
    orchestrator, config = mods
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None)
    db = tmp_path / "l.sqlite"
    orch, first = new_run(orchestrator, config, repo, db)
    orch.run(first)
    spent = Ledger(db).total_cost()
    orch2, second = new_run(orchestrator, config, repo, db, global_budget_usd=spent)
    assert orch2.run(second).status == "budget_exceeded"
