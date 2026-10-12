"""`--replay` on localise and fix: replay only what the ledger holds, never start new work."""

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit.ledger import Ledger  # noqa: E402



@pytest.fixture()
def recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A fixture hero story in a ledger: bisect, localise and fix, with a fake model."""
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.finished
    import culprit.fix
    import culprit.localise
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator, culprit.finished,
                culprit.localise, culprit.fix):
        importlib.reload(mod)
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None, break_hunks="multi")
    db = tmp_path / "ledger.sqlite"
    ledger = Ledger(db)
    orch = culprit.orchestrator.Orchestrator(
        ledger, culprit.config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main"), log=lambda _: None)
    run_id = orch.start()
    assert orch.run(run_id).status == "found"
    return culprit, ledger, db, run_id


def test_replay_refuses_work_the_ledger_does_not_hold(recorded):
    c, ledger, db, run_id = recorded  # bisected, but never localised
    with pytest.raises(c.finished.StageError, match="needs a hunk ranking"):
        c.localise.localise_run(ledger, run_id, log=lambda _: None, replay=True)
    assert ledger.get_artifact(run_id, "localisation") is None


def test_replay_never_runs_an_unrecorded_victim_batch(recorded):
    c, ledger, _, run_id = recorded
    # A ranking is recorded but no revert was ever run: replay must stop before starting any victim run.
    ledger.put_artifact(run_id, "hunk_ranking", json.dumps({"order": [3, 4, 1], "reasons": {}, "source": "llm"}))
    before = ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]
    with pytest.raises(c.finished.StageError, match="needs victim runs for the reverts"):
        c.localise.localise_run(ledger, run_id, log=lambda _: None, replay=True)
    assert ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0] == before
    assert ledger.get_artifact(run_id, "localisation") is None
