"""Regression gate, infrastructure failures, widening, empty ranges and pinned SHAs."""

import importlib
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit.evalrunner import infra_failure  # noqa: E402
from culprit.ledger import Ledger, TaskRun  # noqa: E402
from culprit.stats import fisher_one_sided  # noqa: E402


@pytest.fixture()
def mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    return culprit.orchestrator, culprit.config


def culprit_sha(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "log", "--format=%H", "--grep=speed up tool handling"], text=True
    ).strip()


def new_run(orchestrator, config, repo: Path, db: Path, **overrides):
    fields = {"good_ref": "good-v1.0", "bad_ref": "main", "infra_backoff_s": 0.0, **overrides}
    cfg = config.Config(repo=str(repo), **fields)
    orch = orchestrator.Orchestrator(Ledger(db), cfg, log=lambda _: None)
    return orch, orch.start()


def task_runs(ledger: Ledger) -> list:
    return ledger.conn.execute("SELECT * FROM task_runs").fetchall()


# Regression gate ------------------------------------------------------------------
def test_fisher_matches_known_values():
    assert fisher_one_sided(78, 78, 77, 78) == pytest.approx(0.5)
    assert fisher_one_sided(57, 60, 48, 60) == pytest.approx(0.0123, abs=1e-4)
    assert fisher_one_sided(78, 78, 60, 78) < 1e-5
    assert fisher_one_sided(10, 20, 10, 20) > 0.5


def test_gate_accepts_a_regression_that_breaks_a_few_tasks():
    # Overlapping 95% intervals (the old gate) but a clear one-sided test.
    assert fisher_one_sided(57, 60, 48, 60) < 0.05
    # One or two flaky failures on a perfect baseline stay "no regression".
    assert fisher_one_sided(78, 78, 76, 78) > 0.05


# Infrastructure failures --------------------------------------------------------------
@pytest.mark.parametrize(("error", "kind"), [
    ("RateLimitError: Error code: 429 - {'type': 'rate_limit_error'}", "transient"),
    ("InternalServerError: Error code: 500", "transient"),
    ("APIStatusError: Error code: 529 - overloaded_error", "transient"),
    ("APIConnectionError: Connection error.", "transient"),
    ("timeout after 300s", "transient"),
    ("exit 1: eval runner printed no JSON object: Traceback", "transient"),
    ("AuthenticationError: Error code: 401", "fatal"),
    ("ConfigError: VICTIM_MODEL must be set", "fatal"),
    ("KeyError: 'order_id'", None),  # the commit's own bug: a real failure
    (None, None),
])
def test_infra_failure_classification(error, kind):
    assert infra_failure(TaskRun("t", 0, False, None, None, None, None, None, error)) == kind


def test_passing_run_is_never_infra():
    assert infra_failure(TaskRun("t", 0, True, None, None, None, None, None, "RateLimitError")) is None


def test_transient_errors_are_retried_and_never_counted(mods, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    orchestrator, config = mods
    markers = tmp_path / "markers"
    markers.mkdir()
    monkeypatch.setenv("FIXTURE_INFRA", "rate_limit_once")
    monkeypatch.setenv("FIXTURE_INFRA_DIR", str(markers))
    repo = build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7)
    orch, run_id = new_run(orchestrator, config, repo, tmp_path / "l.sqlite")
    outcome = orch.run(run_id)

    assert outcome.status == "found"
    assert outcome.result.first_bad == culprit_sha(repo)
    rows = task_runs(orch.ledger)
    assert rows and not any(r["error"] for r in rows)  # every 429 was retried, none recorded
    assert len(list(markers.iterdir())) > 0


def test_fatal_error_stops_without_recording_then_resumes(mods, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    orchestrator, config = mods
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None)
    db = tmp_path / "l.sqlite"
    monkeypatch.setenv("FIXTURE_INFRA", "auth")
    orch, run_id = new_run(orchestrator, config, repo, db)
    stopped = orch.run(run_id)
    assert stopped.status == "infra_error"
    assert "AuthenticationError" in stopped.summary
    assert task_runs(orch.ledger) == []

    monkeypatch.delenv("FIXTURE_INFRA")
    ledger = Ledger(db)
    cfg = config.Config.from_json(ledger.get_run(run_id)["config_json"])
    resumed = orchestrator.Orchestrator(ledger, cfg, log=lambda _: None).run(run_id)
    assert resumed.status == "found"
    assert resumed.result.first_bad == culprit_sha(repo)


# Widening -------------------------------------------------------------------------------
def runs(spec: list[tuple[str, bool]]) -> list[TaskRun]:
    return [TaskRun(t, i, p, None, None, None, None, None) for i, (t, p) in enumerate(spec)]


@pytest.mark.parametrize(("subset", "expected_round2"), [
    (["a"], (["b"], range(0, 3))),  # b also dropped: widen to it
    (["a", "b"], (["a", "b"], range(6, 9))),  # nothing else dropped: more repetitions instead
])
def test_widening_only_adds_tasks_that_dropped(mods, tmp_path: Path, subset, expected_round2):
    orchestrator, config = mods
    repo = build(tmp_path / "victim", commits=3, breaks_at=2, unbuildable_at=None)
    orch, run_id = new_run(orchestrator, config, repo, tmp_path / "l.sqlite", discriminating_size=len(subset))
    good = orchestrator.StepResult("g", False, runs([(t, True) for t in "abcd" for _ in range(3)]))
    bad = orchestrator.StepResult("b", False, runs([(t, t in "cd") for t in "abcd" for _ in range(3)]))
    base = orchestrator.Baselines(good, bad)
    calls = []

    def fake_evaluate(run_id, kind, sha, tasks, reps):
        calls.append((tasks, reps))
        orch.ledger.open_step(run_id, kind, sha)
        # Half the runs pass: always INCONCLUSIVE, so every resample round happens.
        return orchestrator.StepResult(sha, False, runs([(t, i % 2 == 0) for t in tasks for i in reps]))

    orch.evaluate = fake_evaluate
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    orch.classify(run_id, sha, base, subset, orch.ranked_tasks(base))
    assert calls[2] == expected_round2
    assert all("c" not in tasks and "d" not in tasks for tasks, _ in calls)


# Range ---------------------------------------------------------------------------------
def test_empty_range_stops_before_any_victim_run(mods, tmp_path: Path):
    orchestrator, config = mods
    repo = build(tmp_path / "victim", commits=2, breaks_at=99, unbuildable_at=None)
    orch, run_id = new_run(orchestrator, config, repo, tmp_path / "l.sqlite", bad_ref="good-v1.0")
    outcome = orch.run(run_id)
    assert outcome.status == "error"
    assert "empty range" in outcome.summary
    assert task_runs(orch.ledger) == []


def test_resume_keeps_the_original_range_when_the_branch_moves(mods, tmp_path: Path):
    orchestrator, config = mods
    repo = build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7)
    db = tmp_path / "l.sqlite"
    orch, run_id = new_run(orchestrator, config, repo, db, budget_usd=0.09)
    assert orch.run(run_id).status == "budget_exceeded"
    bad_before = Ledger(db).get_run(run_id)["bad_sha"]

    (repo / "NOTES.md").write_text("moved on\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "later commit"], check=True)

    ledger = Ledger(db)
    cfg = replace(config.Config.from_json(ledger.get_run(run_id)["config_json"]), budget_usd=3.0)
    finished = orchestrator.Orchestrator(ledger, cfg, log=lambda _: None).run(run_id)
    assert finished.status == "found"
    assert finished.result.first_bad == culprit_sha(repo)
    assert ledger.get_run(run_id)["bad_sha"] == bad_before
