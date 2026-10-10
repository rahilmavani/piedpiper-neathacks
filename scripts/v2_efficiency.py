"""Victim runs per bisect, v1 vs v2, on the free fixture victim (no LLM, no network, $0).

    uv run python scripts/v2_efficiency.py [--out evidence/v2-efficiency-fixture.md]

For each scenario it builds a fixture repo and runs:
  v1          every task × k on both ends (reuse and staging off)
  v2          staged baseline, fresh ledger (nothing to reuse)
  v2 branch2  a second bad branch from the same good ref, same ledger: the good end is reused
  v2 rerun    the same range again, same ledger: both ends are reused
and checks every run names the planted commit.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

SCENARIOS = [  # (name, build kwargs)
    ("break #10 of 14, unbuildable #7", {"commits": 14, "breaks_at": 10, "unbuildable_at": 7}),
    ("break #4 of 14", {"commits": 14, "breaks_at": 4, "unbuildable_at": None}),
    ("break #12 of 16, unbuildable #8", {"commits": 16, "breaks_at": 12, "unbuildable_at": 8}),
    ("break #10 of 14, noisy #9 (p=0.6)", {"commits": 14, "breaks_at": 10, "unbuildable_at": 7,
                                           "noisy_from": 9, "noisy_pass": 0.6}),
]
V1 = {"reuse_baselines": False, "staged_baseline": False}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, help="also write the markdown table here")
    a = p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CULPRIT_STATE_DIR"] = str(Path(tmp) / "state")
        from make_victim import build

        from culprit.config import Config
        from culprit.costs import run_costs
        from culprit.ledger import Ledger
        from culprit.orchestrator import Orchestrator

        def run(repo: Path, db: Path, bad: str = "main", **overrides):
            cfg = Config(repo=str(repo), good_ref="good-v1.0", bad_ref=bad, victim_provider="fixture",
                         victim_model="fixture", **overrides)
            orch = Orchestrator(Ledger(db), cfg, log=lambda _: None)
            orch.victim = None
            run_id = orch.start()
            outcome = orch.run(run_id)
            return run_costs(orch.ledger, run_id), outcome

        lines = ["| Scenario | Run | Baseline runs | Bisect runs | **Victim runs** | Reused | vs v1 | Culprit |",
                 "|---|---|---:|---:|---:|---:|---:|---|"]
        totals: dict[str, int] = {}
        for i, (name, kwargs) in enumerate(SCENARIOS):
            repo = build(Path(tmp) / f"victim{i}", **kwargs)
            subprocess.run(["git", "-C", str(repo), "branch", "branch2", "main~1"], check=True)
            truth = subprocess.check_output(["git", "-C", str(repo), "log", "--format=%H",
                                             "--grep=speed up tool handling"], text=True).strip()
            v1_db, v2_db = Path(tmp) / f"v1-{i}.sqlite", Path(tmp) / f"v2-{i}.sqlite"
            rows = [("v1", *run(repo, v1_db, **V1)),
                    ("v2", *run(repo, v2_db)),
                    ("v2 branch2 (good reused)", *run(repo, v2_db, bad="branch2")),
                    ("v2 rerun (both reused)", *run(repo, v2_db))]
            base = rows[0][1].victim_runs
            for label, c, outcome in rows:
                totals[label] = totals.get(label, 0) + c.victim_runs
                ok = "✓" if outcome.result and outcome.result.first_bad == truth else f"✗ {outcome.status}"
                lines.append(f"| {name} | {label} | {c.baseline_runs} | {c.bisect_runs} | **{c.victim_runs}** | "
                             f"{c.reused_runs} | {c.victim_runs / base - 1:+.0%} | {ok} |")
        lines.append("")
        lines.append("| Total over scenarios | Victim runs | vs v1 |")
        lines.append("|---|---:|---:|")
        for label, n in totals.items():
            lines.append(f"| {label} | {n} | {n / totals['v1'] - 1:+.0%} |")
    table = "\n".join(lines)
    print(table)
    if a.out:
        a.out.write_text(table + "\n")


if __name__ == "__main__":
    main()
