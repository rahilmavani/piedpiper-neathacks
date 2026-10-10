"""Pinned eval suite: every commit is judged by the same snapshot, recorded in the ledger."""

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit.ledger import Ledger  # noqa: E402


@pytest.fixture()
def mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    return culprit.orchestrator, culprit.config, culprit.suite


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def start(mods, repo: Path, db: Path, **overrides):
    orchestrator, config, _ = mods
    cfg = config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main", **overrides)
    orch = orchestrator.Orchestrator(Ledger(db), cfg, log=lambda _: None)
    return orch, orch.start()


def test_task_added_on_main_is_used_for_every_commit(mods, tmp_path: Path):
    repo = build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7, late_task=True)
    orch, run_id = start(mods, repo, tmp_path / "l.sqlite")
    outcome = orch.run(run_id)

    assert outcome.status == "found"
    row = orch.ledger.get_run(run_id)
    assert row["suite_sha"] == git(repo, "rev-parse", "main")
    assert row["suite_source"] == "git:main:evals"
    assert "t11" in orch.cfg.task_ids
    errors = orch.ledger.conn.execute("SELECT COUNT(*) FROM task_runs WHERE error IS NOT NULL").fetchone()[0]
    assert errors == 0  # t11 did not exist at good-v1.0, but the pinned suite supplied it


def test_without_the_task_file_the_old_commit_fails_it(mods, tmp_path: Path):
    """Control for the test above: the fixture really fails tasks it can't find."""
    repo = build(tmp_path / "victim", commits=4, breaks_at=99, unbuildable_at=None, late_task=True)
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "--detach", str(wt), "good-v1.0")
    out = subprocess.run([sys.executable, "-m", "refunddesk.eval", "--task", "t11"], cwd=wt,
                         capture_output=True, text=True).stdout
    assert '"passed": false' in out and "no task named" in out


def test_resume_reuses_recorded_suite_after_main_moves(mods, tmp_path: Path):
    repo = build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7)
    db = tmp_path / "l.sqlite"
    orch, run_id = start(mods, repo, db, budget_usd=0.09)
    assert orch.run(run_id).status == "budget_exceeded"
    pinned_sha = orch.ledger.get_run(run_id)["suite_sha"]

    (repo / "evals" / "t12.json").write_text('{"message": "new task"}\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "evals: add t12")

    orchestrator, config, _ = mods
    ledger = Ledger(db)
    cfg = config.Config.from_json(ledger.get_run(run_id)["config_json"])
    cfg = config.Config(**{**cfg.__dict__, "budget_usd": 3.0})
    orch2 = orchestrator.Orchestrator(ledger, cfg, log=lambda _: None)
    orch2.run(run_id)
    assert ledger.get_run(run_id)["suite_sha"] == pinned_sha
    assert not (orch2.pinned.path / "t12.json").exists()
    assert "t12" not in orch2.cfg.task_ids


def test_worktree_reuse_restores_then_reinstalls_the_pinned_suite(mods, tmp_path: Path):
    _, _, suite = mods
    import culprit.sandbox as sandbox

    repo = build(tmp_path / "victim", commits=4, breaks_at=99, unbuildable_at=None, late_task=True)
    pinned = suite.pin(repo, "evals", "main")
    sha = git(repo, "rev-parse", "good-v1.0")
    wt = sandbox.add_worktree(repo, sha)
    suite.install_into(pinned, wt, "evals")
    assert (wt / "evals" / "t11.json").exists()
    wt_again = sandbox.add_worktree(repo, sha)
    assert wt_again == wt and not (wt / "evals" / "t11.json").exists()  # back to the commit's own tree
    assert git(wt, "status", "--porcelain") == ""


def test_path_suite_records_digest_and_rejects_changes_on_resume(mods, tmp_path: Path):
    _, _, suite = mods
    repo = build(tmp_path / "victim", commits=4, breaks_at=99, unbuildable_at=None)
    src = tmp_path / "my-suite"
    shutil.copytree(repo / "evals", src)
    pinned = suite.pin(repo, str(src), "main")
    assert pinned.source == f"path:{src}" and pinned.sha.startswith("sha256:")
    assert suite.restore(repo, pinned.source, pinned.sha).path == pinned.path

    (src / "t01.json").write_text('{"message": "edited"}\n')
    with pytest.raises(suite.SuiteError):
        suite.restore(repo, pinned.source, pinned.sha)
