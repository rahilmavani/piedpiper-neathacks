"""v2 efficiency on the fixture victim: staged baselines and baseline reuse across runs."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit.ledger import Ledger, TaskRun  # noqa: E402

V1 = {"reuse_baselines": False, "staged_baseline": False}


@pytest.fixture()
def mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.baseline
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    return culprit.orchestrator, culprit.config


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7)


def culprit_sha(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "log", "--format=%H", "--grep=speed up tool handling"], text=True
    ).strip()


def run(mods, repo: Path, db: Path, log: list[str] | None = None, **overrides):
    orchestrator, config = mods
    fields = {"good_ref": "good-v1.0", "bad_ref": "main", "victim_provider": "anthropic",
              "victim_model": "claude-sonnet-5-5", **overrides}
    cfg = config.Config(repo=str(repo), **fields)
    orch = orchestrator.Orchestrator(Ledger(db), cfg, log=(log.append if log is not None else lambda _: None))
    orch.victim = None  # the fixture needs no key; the model is only part of the reuse key
    run_id = orch.start()
    return orch, run_id, orch.run(run_id)


def baseline_rows(ledger: Ledger, run_id: str, sha: str, executed_only: bool = False) -> list:
    return ledger.conn.execute(
        "SELECT t.* FROM task_runs t JOIN steps s USING (step_id) WHERE s.run_id = ? AND s.commit_sha = ?"
        " AND s.kind LIKE 'baseline%'" + (" AND t.reused_from_run IS NULL" if executed_only else ""),
        (run_id, sha),
    ).fetchall()


# Staged baseline -----------------------------------------------------------------------
def test_screen_sends_only_tasks_that_did_not_pass_on_both_ends_to_full_k(mods):
    orchestrator, _ = mods
    from culprit.baseline import screen_failures

    def step(spec):
        return orchestrator.StepResult("x", False, [TaskRun(t, 0, p, None, None, None, None, None) for t, p in spec])

    good = step([("a", True), ("b", True), ("c", False), ("d", True)])
    bad = step([("a", True), ("b", False), ("c", False), ("d", True)])
    assert screen_failures(good, bad) == ["b", "c"]  # b differs; c fails on both (flaky or broken)


def test_v1_baseline_runs_every_task_k_times(mods, repo: Path, tmp_path: Path):
    orch, run_id, outcome = run(mods, repo, tmp_path / "l.sqlite", **V1)
    assert outcome.result.first_bad == culprit_sha(repo)
    good, bad = orch.ledger.get_run(run_id)["good_sha"], orch.ledger.get_run(run_id)["bad_sha"]
    assert len(baseline_rows(orch.ledger, run_id, good)) == len(baseline_rows(orch.ledger, run_id, bad)) == 30


def test_staged_baseline_finds_the_same_culprit_with_fewer_runs(mods, repo: Path, tmp_path: Path):
    log: list[str] = []
    orch, run_id, outcome = run(mods, repo, tmp_path / "l.sqlite", log=log)
    assert outcome.status == "found"
    assert outcome.result.first_bad == culprit_sha(repo)
    row = orch.ledger.get_run(run_id)
    g = baseline_rows(orch.ledger, run_id, row["good_sha"])
    b = baseline_rows(orch.ledger, run_id, row["bad_sha"])
    # Both ends ran exactly the same (task, repetition) set: every task once, the rest at full k.
    assert {(r["task_id"], r["repetition"]) for r in g} == {(r["task_id"], r["repetition"]) for r in b}
    assert {r["task_id"] for r in g if r["repetition"] == 0} == {f"t{i:02d}" for i in range(1, 11)}
    full = {r["task_id"] for r in g if r["repetition"] > 0}
    assert {"t01", "t02", "t03", "t04", "t05"} <= full  # the fragile tasks differ, so they get full k
    assert len(g) + len(b) < 60

    # The gate's counts are the runs actually made, not tasks × k.
    line = next(x for x in log if x.startswith("  good "))
    assert f"good {sum(r['passed'] for r in g)}/{len(g)} " in line
    assert f"bad {sum(r['passed'] for r in b)}/{len(b)} " in line


def test_staged_baseline_still_says_no_regression_when_nothing_broke(mods, tmp_path: Path):
    repo = build(tmp_path / "victim", commits=6, breaks_at=99, unbuildable_at=None)
    _, _, outcome = run(mods, repo, tmp_path / "l.sqlite")
    assert outcome.status == "no_regression"


def test_staged_resume_after_kill_adds_no_runs(mods, repo: Path, tmp_path: Path):
    orchestrator, config = mods
    db = tmp_path / "l.sqlite"
    orch, run_id, outcome = run(mods, repo, db)
    ledger = orch.ledger
    total = ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]
    ledger.conn.execute("DELETE FROM task_runs WHERE id = (SELECT MIN(t.id) FROM task_runs t JOIN steps s"
                        " USING (step_id) WHERE s.kind = 'baseline:full')")
    again = orchestrator.Orchestrator(ledger, config.Config.from_json(ledger.get_run(run_id)["config_json"]),
                                      log=lambda _: None)
    again.victim = None
    assert again.run(run_id).result.first_bad == outcome.result.first_bad
    assert ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0] == total


def test_a_run_recorded_before_v2_resumes_as_v1(mods):
    _, config = mods
    old = json.loads(config.Config(repo="r", good_ref="g", bad_ref="b").to_json())
    del old["reuse_baselines"], old["staged_baseline"]
    cfg = config.Config.from_json(json.dumps(old))
    assert not cfg.reuse_baselines and not cfg.staged_baseline


# Reuse -----------------------------------------------------------------------------------
def test_second_run_reuses_both_baselines_and_records_provenance(mods, repo: Path, tmp_path: Path):
    db = tmp_path / "l.sqlite"
    orch1, first, out1 = run(mods, repo, db)
    orch2, second, out2 = run(mods, repo, db)
    ledger = orch2.ledger
    assert out2.result.first_bad == out1.result.first_bad == culprit_sha(repo)
    row = ledger.get_run(second)
    for sha in (row["good_sha"], row["bad_sha"]):
        rows = baseline_rows(ledger, second, sha)
        assert rows and baseline_rows(ledger, second, sha, executed_only=True) == []
        assert {r["reused_from_run"] for r in rows} == {first}
        sources = ledger.conn.execute(
            f"SELECT passed, cost_usd FROM task_runs WHERE id IN ({','.join(str(r['reused_from_id']) for r in rows)})"
        ).fetchall()
        assert sorted(tuple(s) for s in sources) == sorted((r["passed"], r["cost_usd"]) for r in rows)

    from culprit.costs import run_costs
    from culprit.reuse import provenance

    c1, c2 = run_costs(ledger, first), run_costs(ledger, second)
    assert c2.baseline_runs == 0 and c2.reused_runs == c1.baseline_runs
    assert ledger.run_cost(second) == pytest.approx(0.001 * c2.victim_runs)  # reused rows aren't spend
    assert ledger.total_cost() == pytest.approx(0.001 * (c1.victim_runs + c2.victim_runs))
    assert set(provenance(ledger, second)) == {f"baseline:{row['good_sha']}", f"baseline:{row['bad_sha']}",
                                               f"baseline:full:{row['good_sha']}", f"baseline:full:{row['bad_sha']}"}


def test_reuse_shares_the_good_end_across_branches(mods, repo: Path, tmp_path: Path):
    db = tmp_path / "l.sqlite"
    subprocess.run(["git", "-C", str(repo), "branch", "other", "main~1"], check=True)
    _, first, _ = run(mods, repo, db)
    orch, second, outcome = run(mods, repo, db, bad_ref="other")
    assert outcome.result.first_bad == culprit_sha(repo)
    row = orch.ledger.get_run(second)
    good = baseline_rows(orch.ledger, second, row["good_sha"])
    assert {r["reused_from_run"] for r in good if r["repetition"] == 0} == {first}  # the whole screen
    assert len(baseline_rows(orch.ledger, second, row["bad_sha"], executed_only=True)) > 0  # new bad end


@pytest.mark.parametrize("change", [{"k": 2}, {"victim_model": "z-ai/glm-5.3", "victim_provider": "openrouter"},
                                    {"reuse_baselines": False}])
def test_no_reuse_when_the_key_differs(mods, repo: Path, tmp_path: Path, change):
    db = tmp_path / "l.sqlite"
    run(mods, repo, db)
    orch, second, _ = run(mods, repo, db, **change)
    assert orch.ledger.conn.execute(
        "SELECT COUNT(*) FROM task_runs t JOIN steps s USING (step_id) WHERE s.run_id = ?"
        " AND t.reused_from_run IS NOT NULL", (second,)).fetchone()[0] == 0


def test_no_reuse_when_the_suite_differs(mods, repo: Path, tmp_path: Path):
    db = tmp_path / "l.sqlite"
    run(mods, repo, db)
    (repo / "evals" / "t11.json").write_text('{"message": "new"}\n')
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "evals: add t11"], check=True)
    orch, second, _ = run(mods, repo, db, bad_ref="main~1")  # same range, new suite at main
    assert orch.ledger.conn.execute(
        "SELECT COUNT(*) FROM task_runs t JOIN steps s USING (step_id) WHERE s.run_id = ?"
        " AND t.reused_from_run IS NOT NULL", (second,)).fetchone()[0] == 0


def test_victim_runs_per_bisect_before_and_after(mods, repo: Path, tmp_path: Path):
    """The headline numbers (also printed by scripts/v2_efficiency.py)."""
    from culprit.costs import run_costs

    o1, v1, _ = run(mods, repo, tmp_path / "v1.sqlite", **V1)
    o2, v2, _ = run(mods, repo, tmp_path / "v2.sqlite")
    o3, v2_again, _ = run(mods, repo, tmp_path / "v2.sqlite")
    before = run_costs(o1.ledger, v1).victim_runs
    staged = run_costs(o2.ledger, v2).victim_runs
    reused = run_costs(o3.ledger, v2_again).victim_runs
    assert reused < staged < before
