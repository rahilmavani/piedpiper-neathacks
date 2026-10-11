"""Drift check: `culprit drift --ref <known-good ref>`. "Did we break it, or did the world change?"

A victim run is determined by the commit, the suite, the victim model, the eval runner and the seed.
When a commit that once passed now fails with all of those unchanged, the cause is outside the repo:
the model behind the API, a provider or tool service. So the check re-runs the ref fresh, with the
same suite snapshot, model, k and seeds as a recorded baseline of it, and compares the two with
one-sided Fisher tests in both directions:

- `drifted`: the ref passes less now than it did (p_worse < alpha). Bisecting your history won't help;
  the same code got worse.
- `improved`: it passes more now (p_better < alpha).
- `stable`: neither.

Per-task changes say where. Nothing from the recorded baseline is reused: the point is to measure again.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from culprit import gitops, tracing
from culprit.config import Config
from culprit.ledger import Ledger, TaskRun
from culprit.orchestrator import BudgetExceeded, InfraError, Log
from culprit.standalone import open_run, workflow
from culprit.stats import fisher_one_sided, wilson

KIND = "drift"

# Baseline task runs of `sha` in earlier runs with the same victim model, eval runner and k. Original
# measurements only (not reused copies), so the reference is the run that actually measured them.
_REFERENCES = """
SELECT s.run_id, r.suite_source, r.suite_sha, r.started_at, COUNT(*) AS n
FROM task_runs t
JOIN steps s USING (step_id)
JOIN runs r ON r.run_id = s.run_id
WHERE s.commit_sha = :sha
  AND s.kind LIKE 'baseline%'
  AND t.reused_from_run IS NULL
  AND r.suite_sha IS NOT NULL
  AND json_extract(r.config_json, '$.victim_provider') = :provider
  AND json_extract(r.config_json, '$.victim_model') = :model
  AND json_extract(r.config_json, '$.eval_module') = :eval_module
  AND json_extract(r.config_json, '$.k') = :k
GROUP BY s.run_id
ORDER BY r.started_at
"""


class DriftError(RuntimeError):
    pass


@dataclass
class TaskChange:
    task_id: str
    then: tuple[int, int]
    now: tuple[int, int]


@dataclass
class DriftResult:
    status: str  # drifted, stable, improved, incomplete
    run_id: str
    reference_run: str
    sha: str
    then: tuple[int, int]
    now: tuple[int, int]
    p_worse: float | None = None
    p_better: float | None = None
    changes: list[TaskChange] = field(default_factory=list)
    note: str = ""

    def summary(self) -> str:
        if self.status == "incomplete":
            return f"Drift check incomplete: {self.note}"
        verdict = {"drifted": "DRIFTED: the same code passes less than it did",
                   "improved": "IMPROVED: the same code passes more than it did",
                   "stable": "STABLE: no significant change"}[self.status]
        return (f"{verdict}. {self.sha[:10]}: then {self.then[0]}/{self.then[1]} (run {self.reference_run}), "
                f"now {self.now[0]}/{self.now[1]}; one-sided Fisher p(worse) = {self.p_worse:.4f}, "
                f"p(better) = {self.p_better:.4f}")


def references(ledger: Ledger, cfg: Config, sha: str) -> list[dict]:
    """Earlier runs holding a baseline of `sha` measured with this victim model, eval runner and k, oldest first."""
    return [dict(r) for r in ledger.conn.execute(_REFERENCES, {
        "sha": sha, "provider": cfg.victim_provider, "model": cfg.victim_model,
        "eval_module": cfg.eval_module, "k": cfg.k})]


def recorded_runs(ledger: Ledger, run_id: str, sha: str) -> list[TaskRun]:
    runs: list[TaskRun] = []
    for step in ledger.steps(run_id):
        if step["commit_sha"] == sha and step["kind"].startswith("baseline"):
            runs += ledger.task_runs(step["step_id"]).values()
    return runs


def compare(then: list[TaskRun], now: list[TaskRun], alpha: float) -> tuple[str, float, float, list[TaskChange]]:
    tp, tn, np_, nn = sum(r.passed for r in then), len(then), sum(r.passed for r in now), len(now)
    p_worse = fisher_one_sided(tp, tn, np_, nn)  # "then passed more than now"
    p_better = fisher_one_sided(np_, nn, tp, tn)
    status = "drifted" if p_worse < alpha else "improved" if p_better < alpha else "stable"

    def by_task(runs: list[TaskRun]) -> dict[str, tuple[int, int]]:
        out: dict[str, list[bool]] = {}
        for r in runs:
            out.setdefault(r.task_id, []).append(r.passed)
        return {t: (sum(v), len(v)) for t, v in out.items()}

    t, n = by_task(then), by_task(now)
    changes = [TaskChange(task, t[task], n[task]) for task in sorted(t.keys() & n.keys())
               if t[task][0] / t[task][1] != n[task][0] / n[task][1]]
    changes.sort(key=lambda c: c.now[0] / c.now[1] - c.then[0] / c.then[1])
    return status, p_worse, p_better, changes


def drift_run(ledger: Ledger, cfg: Config, ref: str, log: Log = print, workers: int = 4,
              against: str | None = None) -> DriftResult:
    """Re-measure `ref` now and compare it with a recorded baseline of the same commit (`against`, or the oldest)."""
    sha = gitops.resolve(Path(cfg.repo).resolve(), ref)
    candidates = references(ledger, cfg, sha)
    if against is not None:
        candidates = [c for c in candidates if c["run_id"] == against]
    if not candidates:
        raise DriftError(
            f"no recorded baseline of {sha[:10]} with victim model {cfg.victim_model!r} and k={cfg.k}"
            + (f" in run {against}" if against else "")
            + "; run `culprit run` with this ref as --good first (that records its baseline), then check for drift")
    reference = candidates[0]
    then = recorded_runs(ledger, reference["run_id"], sha)
    # Exactly the reference's tasks and repetitions (seeds): only time differs.
    items = sorted({(r.task_id, r.repetition) for r in then})
    wanted = set(items)
    tasks = sorted({t for t, _ in items})
    reps = range(max(rep for _, rep in items) + 1)

    st = open_run(ledger, replace(cfg, task_ids=tuple(tasks), reuse_baselines=False, staged_baseline=False),
                  ref, log, workers, suite=(reference["suite_source"], reference["suite_sha"]))
    log(f"run {st.run_id}: drift check of {sha[:10]} against run {reference['run_id']} "
        f"({len(then)} recorded task runs, suite {reference['suite_sha'][:12]})")
    with workflow(st, "culprit_drift", ref=ref, reference_run=reference["run_id"]) as sp:
        try:
            result = st.orch.evaluate(st.run_id, KIND, sha, tasks, reps)
        except (BudgetExceeded, InfraError) as exc:
            out = DriftResult("incomplete", st.run_id, reference["run_id"], sha,
                              (sum(r.passed for r in then), len(then)), (0, 0), note=str(exc))
            ledger.finish_run(st.run_id, "incomplete", None, None, out.summary())
            sp.output({"status": out.status, "note": out.note})
            log(out.summary())
            return out
        now = [r for r in result.runs if (r.task_id, r.repetition) in wanted]
        if result.skipped:
            raise DriftError(f"{sha[:10]} no longer installs; that is a change in the environment, not drift")
        with tracing.span("drift_compare", "TOOL", commit_sha=sha,
                          input={"then": [sum(r.passed for r in then), len(then)],
                                 "now": [sum(r.passed for r in now), len(now)], "alpha": cfg.gate_alpha}) as cp:
            status, p_worse, p_better, changes = compare(then, now, cfg.gate_alpha)
            cp.output({"status": status, "p_worse": p_worse, "p_better": p_better})
        out = DriftResult(status, st.run_id, reference["run_id"], sha,
                          (sum(r.passed for r in then), len(then)), (sum(r.passed for r in now), len(now)),
                          p_worse, p_better, changes)
        sp.output({"status": status, "p_worse": p_worse, "p_better": p_better})
    ledger.put_artifact(st.run_id, "drift", json.dumps(asdict(out)))
    ledger.finish_run(st.run_id, status, None, None, out.summary())
    log(out.summary())
    for c in out.changes:
        log(f"  {c.task_id}: then {c.then[0]}/{c.then[1]}, now {c.now[0]}/{c.now[1]}")
    lo, hi = wilson(*out.now)
    log(f"  now: 95% Wilson [{lo:.2f}, {hi:.2f}]")
    return out

