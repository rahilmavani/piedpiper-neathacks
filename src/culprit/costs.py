"""Per-run cost accounting from the ledger: `culprit export-costs` and the v1→v2 comparison.

A victim run "made" by a run is a task run it executed and paid for. Task runs copied from an
earlier run (culprit.reuse) are counted separately as `reused_runs` and cost nothing here; their
cost stays with the run that measured them, so summing `cost_usd` over runs never double-counts.

Executed runs are split by stage, so `victim_runs` = baseline + bisect + localise + fix + other:
baseline (both ends, `baseline*` steps), bisect (bisect and resample steps), localise (`culprit
localise` reverts) and fix (`culprit fix` verification, including held-out runs). Each stage's cost
is its victim runs plus the Culprit model calls made for it (hunk ranking, fix proposals).
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import TextIO

from culprit.ledger import Ledger
from culprit.orchestrator import is_bisect_kind


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
    bisect_runs: int  # of victim_runs, bisect steps and resamples only
    localise_runs: int  # of victim_runs, `culprit localise` hunk reverts
    fix_runs: int  # of victim_runs, `culprit fix` verification (fix:*, verify:*)
    other_runs: int  # of victim_runs, any other step kind (0 today; keeps the sum exact)
    reused_runs: int  # copied from earlier runs, not executed
    baseline_cost_usd: float
    bisect_cost_usd: float
    localise_cost_usd: float  # victim runs + hunk-ranking model calls
    fix_cost_usd: float  # victim runs + fix-proposal model calls
    other_cost_usd: float  # other step kinds + model calls with no stage; stage costs sum to cost_usd
    victim_cost_usd: float
    llm_cost_usd: float
    cost_usd: float
    cost_per_victim_run_usd: float | None
    wall_time_s: float | None  # started → finished; includes any pause before a resume
    started_at: str
    finished_at: str | None
    culprit_sha: str | None


STAGES = ("baseline", "bisect", "localise", "fix", "other")

_BY_KIND = """
SELECT s.kind, COUNT(*) AS executed, COALESCE(SUM(t.cost_usd), 0) AS cost
FROM task_runs t JOIN steps s USING (step_id)
WHERE s.run_id = ? AND t.reused_from_run IS NULL
GROUP BY s.kind
"""
_REUSED = """
SELECT COUNT(*) FROM task_runs t JOIN steps s USING (step_id) WHERE s.run_id = ? AND t.reused_from_run IS NOT NULL
"""


def stage(kind: str) -> str:
    """Which stage of a run a step kind belongs to."""
    if kind.startswith("baseline"):
        return "baseline"
    if is_bisect_kind(kind):
        return "bisect"
    if kind.startswith("localise:"):
        return "localise"
    if kind.startswith(("fix:", "verify:")):
        return "fix"
    return "other"


def llm_stage(purpose: str) -> str | None:
    """Stage a Culprit model call is charged to (`localise_rank`, `fix_propose`); None if no stage."""
    for name in ("localise", "fix"):
        if purpose.startswith(name):
            return name
    return None


def _wall_time(started: str, finished: str | None) -> float | None:
    if not finished:
        return None
    return (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()


def run_costs(ledger: Ledger, run_id: str) -> RunCosts:
    row = ledger.get_run(run_id)
    cfg = json.loads(row["config_json"])
    runs = dict.fromkeys(STAGES, 0)
    cost = dict.fromkeys(STAGES, 0.0)
    for row_ in ledger.conn.execute(_BY_KIND, (run_id,)):
        runs[stage(row_["kind"])] += int(row_["executed"])
        cost[stage(row_["kind"])] += float(row_["cost"])
    victim_cost, executed = sum(cost.values()), sum(runs.values())
    llm = 0.0
    for purpose, spent in ledger.conn.execute(
            "SELECT purpose, COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE run_id = ? GROUP BY purpose", (run_id,)):
        llm += float(spent)
        cost[llm_stage(purpose) or "other"] += float(spent)
    reused = int(ledger.conn.execute(_REUSED, (run_id,)).fetchone()[0])
    return RunCosts(
        run_id=run_id, repo=row["repo"], good_ref=row["good_ref"], bad_ref=row["bad_ref"], status=row["status"],
        victim_provider=cfg.get("victim_provider", ""), victim_model=cfg.get("victim_model", ""),
        k=int(cfg.get("k", 0)), victim_runs=executed, baseline_runs=runs["baseline"], bisect_runs=runs["bisect"],
        localise_runs=runs["localise"], fix_runs=runs["fix"], other_runs=runs["other"], reused_runs=reused,
        baseline_cost_usd=round(cost["baseline"], 6), bisect_cost_usd=round(cost["bisect"], 6),
        localise_cost_usd=round(cost["localise"], 6), fix_cost_usd=round(cost["fix"], 6),
        other_cost_usd=round(cost["other"], 6),
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
