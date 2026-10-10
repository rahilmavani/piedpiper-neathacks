"""`culprit bench`: loaders, scoring, the leakage guard, and an end-to-end bench on two fixture scenarios."""

import importlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit import bench  # noqa: E402
from culprit.ledger import Ledger  # noqa: E402

BENCH_DIR = Path(__file__).resolve().parents[1] / "bench"
SHA = re.compile(r"^[0-9a-f]{40}$")


def facts(status: str, culprit: str | None = None, suspects=(), model: str = "m") -> bench.RunFacts:
    return bench.RunFacts(
        run_id="r", status=status, culprit_sha=culprit, suspects=list(suspects), good_sha="g", bad_sha="b",
        victim_model=model, victim_runs=0, cost_usd=0.0, wall_s=None, skipped=[], confidence=None,
        summary=None, traces=[],
    )


# loaders --------------------------------------------------------------------------------
def test_shipped_scenarios_and_ground_truth_agree():
    scenarios = bench.load_scenarios(BENCH_DIR / "scenarios.yaml")
    truth = bench.load_ground_truth(BENCH_DIR / "ground_truth.json")
    assert [s.name for s in scenarios] == [f"hist/{x}" for x in "abcdef"]
    assert all(s.good == "good-v1.0" and s.bad == f"origin/{s.name}" for s in scenarios)
    assert set(truth) == {s.name for s in scenarios}
    for t in truth.values():
        assert SHA.match(t.culprit_sha) and SHA.match(t.bad_sha)
        assert all(SHA.match(u) for u in t.uninstallable)
        assert t.hunks and all("file" in h and ("lines" in h or "parent_lines" in h) for h in t.hunks)
        assert t.intended_gain.get("metric") in {None, "latency", "tokens", "cost"}
    assert truth["hist/b"].culprit_sha.startswith("397c427")
    assert [len(t.uninstallable) for t in truth.values()] == [0, 1, 0, 0, 0, 1]


def test_load_scenarios_rejects_bad_files(tmp_path: Path):
    path = tmp_path / "s.yaml"
    path.write_text("scenarios:\n  - name: x\n    good: g\n")
    with pytest.raises(bench.BenchError, match="missing bad"):
        bench.load_scenarios(path)
    path.write_text("scenarios:\n  - {name: x, good: g, bad: b}\n  - {name: x, good: g, bad: c}\n")
    with pytest.raises(bench.BenchError, match="duplicate"):
        bench.load_scenarios(path)
    path.write_text("other: 1\n")
    with pytest.raises(bench.BenchError, match="non-empty"):
        bench.load_scenarios(path)


def test_load_ground_truth_requires_culprit_key(tmp_path: Path):
    path = tmp_path / "gt.json"
    path.write_text(json.dumps({"scenarios": {"x": {"bad_sha": "b"}}}))
    with pytest.raises(bench.BenchError, match="culprit_sha"):
        bench.load_ground_truth(path)
    path.write_text(json.dumps({"scenarios": {"x": {"culprit_sha": None}}}))
    assert bench.load_ground_truth(path)["x"].culprit_sha is None


def test_ground_truth_must_live_outside_the_victim_repo(tmp_path: Path):
    repo = tmp_path / "victim"
    (repo / "bench").mkdir(parents=True)
    with pytest.raises(bench.BenchError, match="inside the victim repo"):
        bench.guard_outside_repo(repo, tmp_path / "s.yaml", repo / "bench" / "ground_truth.json")
    bench.guard_outside_repo(repo, tmp_path / "s.yaml", tmp_path / "ground_truth.json")


# scoring --------------------------------------------------------------------------------
@pytest.mark.parametrize(("truth", "run", "outcome"), [
    (bench.Truth("abc"), facts("found", "abc"), bench.CORRECT),
    (bench.Truth("abc"), facts("found", "def"), bench.WRONG),
    (bench.Truth(None), facts("found", "def"), bench.WRONG),
    (bench.Truth(None), facts("no_regression"), bench.CORRECT_NO_REGRESSION),
    (bench.Truth("abc", visible={"m": False}), facts("no_regression"), bench.CORRECT_NO_REGRESSION),
    (bench.Truth("abc", visible={"m": True}), facts("no_regression"), bench.MISSED),
    (bench.Truth("abc", visible={"other": True}), facts("no_regression"), bench.NO_REGRESSION_UNVERIFIED),
    (bench.Truth("abc"), facts("ambiguous", suspects=["x", "abc"]), bench.AMBIGUOUS_CONTAINS),
    (bench.Truth("abc"), facts("ambiguous", suspects=["x", "y"]), bench.AMBIGUOUS_MISSES),
    (bench.Truth("abc"), facts("budget_exceeded", suspects=["abc"]), bench.INCOMPLETE),
    (bench.Truth("abc"), facts("infra_error"), bench.INCOMPLETE),
    (bench.Truth("abc"), facts("running"), bench.INCOMPLETE),
])
def test_score(truth, run, outcome):
    assert bench.score(truth, run) == outcome


# end to end on the fixture ----------------------------------------------------------------
@pytest.fixture()
def mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.bench
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator, culprit.bench):
        importlib.reload(mod)
    return culprit.bench


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def test_bench_end_to_end_on_two_fixture_scenarios(mods, tmp_path: Path):
    b = mods
    repo = build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7)
    culprit = git(repo, "log", "--format=%H", "--grep=speed up tool handling")
    files = tmp_path / "bench"
    files.mkdir()
    # "broken" contains the planted break; "clean" stops at commit 6, before the pin and the break.
    (files / "scenarios.yaml").write_text(
        "scenarios:\n  - {name: broken, good: good-v1.0, bad: main}\n  - {name: clean, good: good-v1.0, bad: main~8}\n"
    )
    (files / "ground_truth.json").write_text(json.dumps({"scenarios": {
        "broken": {"culprit_sha": culprit, "bad_sha": git(repo, "rev-parse", "main")},
        "clean": {"culprit_sha": None},
    }}))
    b.guard_outside_repo(repo, files / "scenarios.yaml", files / "ground_truth.json")
    scenarios = b.load_scenarios(files / "scenarios.yaml")
    truth = b.load_ground_truth(files / "ground_truth.json")

    db = tmp_path / "state" / "ledger.sqlite"
    ledger = Ledger(db)
    run_ids = b.run_scenarios(ledger, repo, scenarios, log=lambda _: None)
    rows = {r.scenario: r for r in b.score_runs(ledger, repo, truth, run_ids)}

    assert rows["broken"].outcome == b.CORRECT
    assert rows["broken"].facts.culprit_sha == culprit
    assert rows["broken"].facts.skipped  # the unbuildable commit was hit and skipped
    assert rows["clean"].outcome == b.CORRECT_NO_REGRESSION
    for r in rows.values():
        assert r.facts.victim_runs > 0 and r.facts.cost_usd > 0 and r.facts.wall_s is not None

    # Leakage guard: only SHAs reach the run; neither scenario names nor answers appear in its record.
    for name, run_id in run_ids.items():
        row = ledger.get_run(run_id)
        assert SHA.match(row["good_ref"]) and SHA.match(row["bad_ref"])
        assert name not in row["config_json"] and "main" not in json.loads(row["config_json"])["bad_ref"]

    md = b.write_report(tmp_path / "out", "v1", list(rows.values()), "test", repo)
    text = md.read_text()
    assert "**Culprit accuracy: 2/2 scored correct**" in text
    assert f"| broken | **correct** | found | `{culprit[:7]}` | `{culprit[:7]}` |" in text
    assert run_ids["broken"] in text and run_ids["clean"] in text
    data = json.loads((tmp_path / "out" / "bench-v1.json").read_text())
    assert {r["outcome"] for r in data["rows"]} == {b.CORRECT, b.CORRECT_NO_REGRESSION}

    # Scoring existing runs: read-only, matched by SHA, explicitly or as the latest per scenario.
    ro = Ledger(db, readonly=True)
    assert b.match_runs(ro, repo, scenarios, None) == run_ids
    assert b.match_runs(ro, repo, scenarios, [run_ids["clean"]]) == {"clean": run_ids["clean"]}
    with pytest.raises(sqlite3.OperationalError):
        ro.conn.execute("UPDATE runs SET status = 'x'")

    from culprit.cli import app

    result = CliRunner().invoke(app, [
        "bench", "--tag", "rescore", "--scenarios", str(files / "scenarios.yaml"), "--repo", str(repo),
        "--db", str(db), "--out-dir", str(tmp_path / "out"), "--score-runs", f"{run_ids['broken']},{run_ids['clean']}",
    ])
    assert result.exit_code == 0, result.output
    assert "accuracy 2/2 scored correct" in result.output
    assert (tmp_path / "out" / "bench-rescore.md").exists()


def test_tests_never_export_traces():
    import os

    from culprit import tracing

    tracing.init()
    assert "NEATLOGS_API_KEY" not in os.environ and not tracing.enabled()


def test_accuracy_excludes_runs_that_cannot_be_scored_yet():
    from types import SimpleNamespace

    rows = [SimpleNamespace(outcome=o) for o in (
        bench.CORRECT, bench.CORRECT, bench.CORRECT,
        bench.NO_REGRESSION_UNVERIFIED, bench.NO_REGRESSION_UNVERIFIED, bench.NO_REGRESSION_UNVERIFIED)]
    assert bench.accuracy(rows) == {"correct": 3, "scored": 3, "unverified": 3, "incomplete": 0}
    assert bench.accuracy_text(rows) == "3/3 scored correct; 3 no_regression awaiting a strength check"
    rows += [SimpleNamespace(outcome=bench.MISSED), SimpleNamespace(outcome=bench.INCOMPLETE)]
    assert bench.accuracy_text(rows) == "3/4 scored correct; 3 no_regression awaiting a strength check, 1 incomplete"
