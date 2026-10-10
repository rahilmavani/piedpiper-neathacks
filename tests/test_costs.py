"""export-costs splits a run's victim runs and cost by stage: baseline, bisect, localise, fix."""

import csv
import io
from pathlib import Path

import pytest

from culprit.costs import run_costs, stage, write_csv
from culprit.ledger import Ledger, TaskRun


@pytest.mark.parametrize(("kind", "expected"), [
    ("baseline", "baseline"), ("baseline:full", "baseline"),
    ("bisect", "bisect"), ("resample:1", "bisect"), ("resample:2", "bisect"),
    ("localise:h4", "localise"), ("localise:h4+h3", "localise"),
    ("fix:1", "fix"), ("fix:revert", "fix"), ("verify:heldout", "fix"),
    ("something-new", "other"),
])
def test_stage_of_each_step_kind(kind, expected):
    assert stage(kind) == expected


def add_runs(ledger: Ledger, run_id: str, kind: str, sha: str, n: int, cost: float) -> None:
    step = ledger.open_step(run_id, kind, sha)
    for i in range(n):
        ledger.record_task_run(step, TaskRun(f"t{i}", 0, True, cost, 1.0, 10, 5, None))


def test_localise_and_fix_runs_are_not_bisect_runs(tmp_path: Path):
    """The shape of run ff50e3620fdd: 156 baseline + 84 bisect + 84 localise + 132 fix = 456 runs."""
    ledger = Ledger(tmp_path / "l.sqlite")
    run_id = ledger.create_run("/r", "good", "bad", "h", '{"k": 3}')
    add_runs(ledger, run_id, "baseline", "g" * 40, 78, 0.002)
    add_runs(ledger, run_id, "baseline", "b" * 40, 78, 0.002)
    add_runs(ledger, run_id, "bisect", "c" * 40, 63, 0.003)
    add_runs(ledger, run_id, "resample:1", "c" * 40, 21, 0.003)
    add_runs(ledger, run_id, "localise:h4", "d" * 40, 42, 0.002)
    add_runs(ledger, run_id, "localise:h4+h3", "d" * 40, 42, 0.002)
    add_runs(ledger, run_id, "verify:heldout", "g" * 40, 18, 0.002)
    add_runs(ledger, run_id, "fix:2", "b" * 40, 114, 0.002)
    ledger.record_llm_call(run_id, None, "localise_rank", "m", 1, 1, 0.01, None)
    ledger.record_llm_call(run_id, None, "fix_propose", "m", 1, 1, 0.02, None)
    ledger.record_llm_call(run_id, None, "fix_propose", "m", 1, 1, 0.02, None)

    c = run_costs(ledger, run_id)
    assert (c.victim_runs, c.baseline_runs, c.bisect_runs, c.localise_runs, c.fix_runs, c.other_runs) == \
        (456, 156, 84, 84, 132, 0)
    assert c.baseline_cost_usd == pytest.approx(156 * 0.002)
    assert c.bisect_cost_usd == pytest.approx(84 * 0.003)
    assert c.localise_cost_usd == pytest.approx(84 * 0.002 + 0.01)  # victim runs + ranking call
    assert c.fix_cost_usd == pytest.approx(132 * 0.002 + 0.04)  # victim runs + two proposals
    assert c.llm_cost_usd == pytest.approx(0.05)
    stages = c.baseline_cost_usd + c.bisect_cost_usd + c.localise_cost_usd + c.fix_cost_usd + c.other_cost_usd
    assert stages == pytest.approx(c.cost_usd) == pytest.approx(ledger.run_cost(run_id))

    out = io.StringIO()
    write_csv([c], out)
    row = next(csv.DictReader(io.StringIO(out.getvalue())))
    assert (row["bisect_runs"], row["localise_runs"], row["fix_runs"]) == ("84", "84", "132")
    assert float(row["localise_cost_usd"]) == pytest.approx(c.localise_cost_usd)


def test_unknown_kinds_and_unstaged_calls_land_in_other(tmp_path: Path):
    ledger = Ledger(tmp_path / "l.sqlite")
    run_id = ledger.create_run("/r", "good", "bad", "h", '{"k": 3}')
    add_runs(ledger, run_id, "something-new", "a" * 40, 3, 0.01)
    ledger.record_llm_call(run_id, None, "select_tasks", "m", 1, 1, 0.005, None)
    c = run_costs(ledger, run_id)
    assert (c.victim_runs, c.other_runs, c.bisect_runs) == (3, 3, 0)
    assert c.other_cost_usd == pytest.approx(0.035) == pytest.approx(c.cost_usd)


def test_reused_runs_are_counted_apart_and_cost_nothing(tmp_path: Path):
    ledger = Ledger(tmp_path / "l.sqlite")
    first = ledger.create_run("/r", "good", "bad", "h", '{"k": 3}')
    add_runs(ledger, first, "baseline", "g" * 40, 5, 0.01)
    second = ledger.create_run("/r", "good", "bad", "h", '{"k": 3}')
    step = ledger.open_step(second, "baseline", "g" * 40)
    for row in ledger.conn.execute("SELECT id FROM task_runs").fetchall():
        ledger.copy_task_run(step, row["id"], first)
    c = run_costs(ledger, second)
    assert (c.victim_runs, c.baseline_runs, c.reused_runs, c.cost_usd) == (0, 0, 5, 0.0)
