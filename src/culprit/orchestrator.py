"""Culprit's run loop: baselines → discriminating tasks → bisect → intent (PRD §7, §8.1).

The loop is deterministic and memoised in the ledger, so running it again for an existing
run_id resumes it: completed steps and task runs are reused, never re-executed.
"""

from __future__ import annotations

import hashlib
import statistics
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from culprit import gitops, sandbox
from culprit.bisect import BisectResult, Verdict, bisect
from culprit.config import Config
from culprit.entire import commit_intent
from culprit.evalrunner import discover_tasks, run_task, victim_env
from culprit.ledger import Ledger, TaskRun
from culprit.stats import wilson

Log = Callable[[str], None]


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class StepResult:
    sha: str
    skipped: bool
    runs: list[TaskRun]

    @property
    def n(self) -> int:
        return len(self.runs)

    @property
    def passes(self) -> int:
        return sum(r.passed for r in self.runs)

    @property
    def rate(self) -> float:
        return self.passes / self.n if self.n else 0.0

    def task_rates(self) -> dict[str, float]:
        by_task: dict[str, list[bool]] = {}
        for r in self.runs:
            by_task.setdefault(r.task_id, []).append(r.passed)
        return {t: sum(v) / len(v) for t, v in by_task.items()}


@dataclass(frozen=True)
class Outcome:
    run_id: str
    status: str
    result: BisectResult | None
    summary: str


def suite_hash(tasks: list[str]) -> str:
    return hashlib.sha256("\n".join(tasks).encode()).hexdigest()[:16]


class Orchestrator:
    def __init__(self, ledger: Ledger, cfg: Config, log: Log = print, workers: int = 4):
        self.ledger = ledger
        self.cfg = cfg
        self.repo = Path(cfg.repo).resolve()
        self.log = log
        self.workers = workers
        self.env = victim_env(self.repo)

    # one commit ---------------------------------------------------------------
    def evaluate(
        self, run_id: str, kind: str, sha: str, tasks: list[str], reps: int,
        decide: Callable[[StepResult], str] | None = None,
    ) -> StepResult:
        existing = self.ledger.get_step(run_id, kind, sha)
        if existing is not None and existing["status"] == "skip":
            return StepResult(sha, True, [])
        step_id = self.ledger.open_step(run_id, kind, sha)
        done = self.ledger.task_runs(step_id)
        todo = [(t, r) for t in tasks for r in range(reps) if (t, r) not in done]
        if todo:
            worktree = sandbox.add_worktree(self.repo, sha)
            installed = sandbox.install(worktree, self.cfg.eval_module, self.cfg.install_timeout_s)
            if not installed.ok:
                self.ledger.close_step(step_id, "skip", decision=Verdict.SKIP, error=installed.log[-2000:])
                self.log(f"  {sha[:10]} install failed → SKIP")
                return StepResult(sha, True, [])
            self._run_tasks(run_id, step_id, worktree, sha, todo)
        runs = list(self.ledger.task_runs(step_id).values())
        result = StepResult(sha, False, [r for r in runs if r.task_id in tasks and r.repetition < reps])
        low, high = wilson(result.passes, result.n, self.cfg.z)
        latencies = [r.latency_ms for r in result.runs if r.latency_ms is not None]
        self.ledger.close_step(
            step_id, "done", decision=decide(result) if decide else None, wilson_low=low, wilson_high=high, n=result.n, passes=result.passes,
            cost_usd=sum(r.cost_usd or 0.0 for r in result.runs),
            latency_ms_p50=statistics.median(latencies) if latencies else None,
        )
        return result

    def _run_tasks(self, run_id: str, step_id: int, worktree: Path, sha: str, todo: list[tuple[str, int]]) -> None:
        """Workers only run subprocesses; ledger writes and budget checks stay on this thread."""

        def one(item: tuple[str, int]) -> TaskRun:
            return run_task(worktree, self.env, self.cfg.eval_module, item[0], item[1], run_id=run_id,
                            commit_sha=sha, timeout_s=self.cfg.task_timeout_s)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for start in range(0, len(todo), self.workers):
                if self.ledger.run_cost(run_id) >= self.cfg.budget_usd:
                    raise BudgetExceeded(f"run cost reached the ${self.cfg.budget_usd:.2f} cap")
                for tr in pool.map(one, todo[start : start + self.workers]):
                    self.ledger.record_task_run(step_id, tr)

    # whole run -----------------------------------------------------------------
    def start(self) -> str:
        good = gitops.resolve(self.repo, self.cfg.good_ref)
        tasks = list(self.cfg.task_ids) or discover_tasks(sandbox.add_worktree(self.repo, good), self.cfg.suite)
        cfg = Config(**{**self.cfg.__dict__, "task_ids": tuple(tasks)})
        self.cfg = cfg
        return self.ledger.create_run(str(self.repo), cfg.good_ref, cfg.bad_ref, suite_hash(tasks), cfg.to_json())

    def run(self, run_id: str) -> Outcome:
        try:
            return self._run(run_id)
        except BudgetExceeded as exc:
            summary = f"Stopped: {exc}. Resume with a higher --budget-usd to continue."
            self.ledger.finish_run(run_id, "budget_exceeded", None, None, summary)
            return Outcome(run_id, "budget_exceeded", None, summary)

    def _run(self, run_id: str) -> Outcome:
        cfg, repo, tasks = self.cfg, self.repo, list(self.cfg.task_ids)
        good, bad = gitops.resolve(repo, cfg.good_ref), gitops.resolve(repo, cfg.bad_ref)
        candidates = gitops.first_parent_range(repo, good, bad)
        self.log(f"run {run_id}: {len(candidates)} commits in {cfg.good_ref}..{cfg.bad_ref}, {len(tasks)} tasks × {cfg.k}")

        base_good = self.evaluate(run_id, "baseline", good, tasks, cfg.k)
        base_bad = self.evaluate(run_id, "baseline", bad, tasks, cfg.k)
        if base_good.skipped or base_bad.skipped:
            return self._finish(run_id, "error", None, "good or bad ref failed to install; cannot bisect")
        self.log(f"  good {base_good.passes}/{base_good.n}  bad {base_bad.passes}/{base_bad.n}")
        if base_good.rate <= base_bad.rate:
            return self._finish(run_id, "no_regression", None,
                                f"No regression to bisect: good {base_good.rate:.2f} ≤ bad {base_bad.rate:.2f}")
        threshold = (base_good.rate + base_bad.rate) / 2
        subset = self.discriminating(base_good, base_bad)
        self.log(f"  threshold {threshold:.2f}; discriminating tasks: {', '.join(subset)}")

        def point_estimate(res: StepResult) -> Verdict:
            return Verdict.GOOD if res.rate >= threshold else Verdict.BAD

        def classify(sha: str) -> Verdict:
            res = self.evaluate(run_id, "bisect", sha, subset, cfg.k, decide=point_estimate)
            if res.skipped:
                return Verdict.SKIP
            verdict = point_estimate(res)
            self.log(f"  {sha[:10]} {gitops.subject(repo, sha)[:50]!r}: {res.passes}/{res.n} → {verdict}")
            return verdict

        result = bisect(candidates, classify)
        if result.first_bad is None:
            summary = f"Culprit is one of {len(result.suspects)} commits (skipped commits hide the boundary): " + \
                ", ".join(s[:10] for s in result.suspects)
            return self._finish(run_id, "ambiguous", result, summary)

        intent = commit_intent(repo, result.first_bad)
        self.ledger.put_artifact(run_id, "intent", intent.text)
        self.ledger.put_artifact(run_id, "diff", gitops.diff(repo, result.first_bad))
        self.log(f"  intent source: {intent.source}; leakage filter removed {intent.lines_removed} lines")
        summary = f"Culprit: {result.first_bad} {gitops.subject(repo, result.first_bad)!r}"
        return self._finish(run_id, "found", result, summary, confidence="point-estimate")

    def discriminating(self, good: StepResult, bad: StepResult) -> list[str]:
        """Tasks ranked by pass-rate drop from good to bad (deterministic part of the Task Selector)."""
        g, b = good.task_rates(), bad.task_rates()
        ranked = sorted(((g[t] - b.get(t, 0.0), t) for t in g), key=lambda x: (-x[0], x[1]))
        subset = [t for delta, t in ranked if delta > 0][: self.cfg.discriminating_size]
        return subset or sorted(g)

    def _finish(self, run_id: str, status: str, result: BisectResult | None, summary: str,
                confidence: str | None = None) -> Outcome:
        self.ledger.finish_run(run_id, status, result.first_bad if result else None, confidence, summary)
        self.log(summary)
        return Outcome(run_id, status, result, summary)
