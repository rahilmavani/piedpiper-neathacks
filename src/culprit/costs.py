"""Per-run cost accounting from the ledger: `culprit export-costs` and the v1→v2 comparison.

A victim run "made" by a run is a task run it executed and paid for. Task runs copied from an
earlier run (culprit.reuse) are counted separately as `reused_runs` and cost nothing here; their
cost stays with the run that measured them, so summing `cost_usd` over runs never double-counts.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import TextIO

from culprit.ledger import Ledger


@dataclass(frozen=True)
class RunCosts:
    run_id: str
    repo: str
    good_ref: str
    bad_ref: str
    status: str
    victim_provider: str
    victim_model: str
    k: int
    victim_runs: int  # executed by this run
    baseline_runs: int  # of victim_runs, measuring the two ends
    bisect_runs: int  # of victim_runs, bisect steps and resamples
    reused_runs: int  # copied from earlier runs, not executed
    victim_cost_usd: float
    llm_cost_usd: float
    cost_usd: float
    cost_per_victim_run_usd: float | None
    wall_time_s: float | None  # started → finished; includes any pause before a resume
    started_at: str
    finished_at: str | None
    culprit_sha: str | None


_COUNTS = """
SELECT
  COALESCE(SUM(t.reused_from_run IS NULL), 0) AS executed,
  COALESCE(SUM(t.reused_from_run IS NULL AND s.kind LIKE 'baseline%'), 0) AS baseline,
  COALESCE(SUM(t.reused_from_run IS NOT NULL), 0) AS reused,
  COALESCE(SUM(CASE WHEN t.reused_from_run IS NULL THEN t.cost_usd END), 0) AS cost
FROM task_runs t JOIN steps s USING (step_id) WHERE s.run_id = ?
"""


def _wall_time(started: str, finished: str | None) -> float | None:
    if not finished:
        return None
    return (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()


def run_costs(ledger: Ledger, run_id: str) -> RunCosts:
    row = ledger.get_run(run_id)
    cfg = json.loads(row["config_json"])
    c = ledger.conn.execute(_COUNTS, (run_id,)).fetchone()
    llm = float(ledger.conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE run_id = ?", (run_id,)).fetchone()[0])
    victim_cost = float(c["cost"])
    executed = int(c["executed"])
    return RunCosts(
        run_id=run_id, repo=row["repo"], good_ref=row["good_ref"], bad_ref=row["bad_ref"], status=row["status"],
        victim_provider=cfg.get("victim_provider", ""), victim_model=cfg.get("victim_model", ""),
        k=int(cfg.get("k", 0)), victim_runs=executed, baseline_runs=int(c["baseline"]),
        bisect_runs=executed - int(c["baseline"]), reused_runs=int(c["reused"]),
        victim_cost_usd=round(victim_cost, 6), llm_cost_usd=round(llm, 6), cost_usd=round(victim_cost + llm, 6),
        cost_per_victim_run_usd=round(victim_cost / executed, 6) if executed else None,
        wall_time_s=_wall_time(row["started_at"], row["finished_at"]),
        started_at=row["started_at"], finished_at=row["finished_at"], culprit_sha=row["culprit_sha"],
    )


def all_runs(ledger: Ledger) -> list[RunCosts]:
    ids = [r[0] for r in ledger.conn.execute("SELECT run_id FROM runs ORDER BY started_at, run_id")]
    return [run_costs(ledger, run_id) for run_id in ids]


def write_csv(rows: list[RunCosts], out: TextIO) -> None:
    writer = csv.DictWriter(out, fieldnames=[f.name for f in fields(RunCosts)], lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: "" if v is None else v for k, v in asdict(r).items()})
