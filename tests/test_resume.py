"""End-to-end on the fixture victim: finds the culprit, skips the unbuildable commit, resumes idempotently."""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    repo = build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7)
    return repo, tmp_path / "state" / "ledger.sqlite", culprit.orchestrator, culprit.config


def count_task_runs(ledger) -> int:
    return ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]


def test_finds_culprit_and_resume_reuses_work(env):
    from culprit.ledger import Ledger

    repo, db, orchestrator, config = env
    ledger = Ledger(db)
    cfg = config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main")
    orch = orchestrator.Orchestrator(ledger, cfg, log=lambda _: None)
    run_id = orch.start()
    outcome = orch.run(run_id)

    expected = subprocess.check_output(
        ["git", "-C", str(repo), "log", "--format=%H", "--grep=speed up tool handling"], text=True
    ).strip()
    assert outcome.status == "found"
    assert outcome.result.first_bad == expected
    assert any(v == "SKIP" for _, v in outcome.result.tested)

    # Simulate a kill mid-step: forget one task run and mark the run unfinished.
    total = count_task_runs(ledger)
    ledger.conn.execute("DELETE FROM task_runs WHERE id = (SELECT MAX(id) FROM task_runs)")
    ledger.conn.execute("UPDATE runs SET status = 'running' WHERE run_id = ?", (run_id,))

    resumed = orchestrator.Orchestrator(
        ledger, config.Config.from_json(ledger.get_run(run_id)["config_json"]), log=lambda _: None
    ).run(run_id)
    assert resumed.result.first_bad == outcome.result.first_bad
    assert count_task_runs(ledger) == total  # only the forgotten run was re-executed
