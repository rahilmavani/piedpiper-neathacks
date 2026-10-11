"""`culprit drift`: re-measure a known-good ref with everything unchanged except time."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit.ledger import Ledger, TaskRun  # noqa: E402


@pytest.fixture()
def recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A fixture victim and a ledger holding one finished run, whose good baseline is the reference."""
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None)
    db = tmp_path / "l.sqlite"
    cfg = culprit.config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main", staged_baseline=False)
    orch = culprit.orchestrator.Orchestrator(Ledger(db), cfg, log=lambda _: None)
    first = orch.start()
    orch.run(first)
    return repo, db, cfg, first


def drift(db, cfg, monkeypatch, quality: str | None, **kw):
    from culprit import drift as d

    if quality is not None:
        monkeypatch.setenv("FIXTURE_MODEL_QUALITY", quality)
    return d.drift_run(Ledger(db), cfg, "good-v1.0", log=lambda _: None, **kw)


def test_same_world_is_stable(recorded, monkeypatch):
    _, db, cfg, first = recorded
    result = drift(db, cfg, monkeypatch, None)
    assert result.status == "stable"
    assert result.reference_run == first
    assert result.then == result.now  # deterministic fixture: identical seeds, identical results
    assert Ledger(db).get_run(result.run_id)["status"] == "stable"


def test_worse_model_is_drift(recorded, monkeypatch):
    _, db, cfg, _ = recorded
    result = drift(db, cfg, monkeypatch, "0.4")
    assert result.status == "drifted"
    assert result.now[0] < result.then[0] and result.p_worse < 0.05
    assert result.changes and all(c.now[0] <= c.then[0] for c in result.changes[:3])
    assert "DRIFTED" in result.summary()


def test_drift_measures_fresh_never_reuses(recorded, monkeypatch):
    _, db, cfg, _ = recorded
    result = drift(db, cfg, monkeypatch, "0.4")
    rows = Ledger(db).conn.execute(
        "SELECT COUNT(*), SUM(t.reused_from_run IS NOT NULL) FROM task_runs t JOIN steps s USING (step_id)"
        " WHERE s.run_id = ? AND s.kind = 'drift'", (result.run_id,)).fetchone()
    assert rows[0] == result.now[1] and not rows[1]


def test_no_recorded_baseline_is_a_clear_error(recorded, monkeypatch):
    from dataclasses import replace

    from culprit import drift as d

    _, db, cfg, _ = recorded
    with pytest.raises(d.DriftError, match="no recorded baseline"):
        d.drift_run(Ledger(db), replace(cfg, k=5), "good-v1.0", log=lambda _: None)
    with pytest.raises(d.DriftError, match="in run nope"):
        d.drift_run(Ledger(db), cfg, "good-v1.0", log=lambda _: None, against="nope")


def test_compare_directions():
    from culprit.drift import compare

    def runs(spec):
        return [TaskRun(t, i, p, None, None, None, None, None) for i, (t, p) in enumerate(spec)]

    then = runs([("a", True)] * 30 + [("b", True)] * 30)
    worse = runs([("a", True)] * 30 + [("b", False)] * 30)
    assert compare(then, worse, 0.05)[0] == "drifted"
    assert compare(worse, then, 0.05)[0] == "improved"
    assert compare(then, then, 0.05)[0] == "stable"
    assert [c.task_id for c in compare(then, worse, 0.05)[3]] == ["b"]
