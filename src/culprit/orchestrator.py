"""Culprit's run loop: baselines → discriminating tasks → noise-aware bisect → intent (PRD §7, §8).

The loop is deterministic and memoised in the ledger, so running it again for an existing
run_id resumes it: completed steps and task runs are reused, never re-executed.
"""

from __future__ import annotations

import contextvars
import hashlib
import statistics
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from culprit import gitops, sandbox, suite, tracing
from culprit.bisect import BisectResult, Verdict, bisect, bounds
from culprit.config import Config
from culprit.entire import commit_intent
from culprit.evalrunner import discover_tasks, infra_failure, run_task, victim_env
from culprit.ledger import Ledger, TaskRun
from culprit.providers import Provider, ProviderError
from culprit.stats import Decision, decide, fisher_one_sided, wilson

Log = Callable[[str], None]


class BudgetExceeded(RuntimeError):
    pass


class InfraError(RuntimeError):
    """A victim run failed for infrastructure reasons (API, config, timeout), not because of the commit."""


def is_bisect_kind(kind: str) -> bool:
    """Steps that decide a commit's bisect verdict (not baselines, not Localiser reverts)."""
    return kind == "bisect" or kind.startswith("resample:")


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


@dataclass(frozen=True)
class Baselines:
    good: StepResult
    bad: StepResult

    def threshold(self, runs: list[TaskRun]) -> float:
        """Midpoint of the good and bad pass rates over the same task mix as `runs` (PRD §8.1 step 2)."""
        g, b = self.good.task_rates(), self.bad.task_rates()
        return sum((g[r.task_id] + b[r.task_id]) / 2 for r in runs) / len(runs)

    def drop(self, task_id: str) -> float:
        """How much a task's pass rate fell from good to bad."""
        return self.good.task_rates()[task_id] - self.bad.task_rates().get(task_id, 0.0)


def suite_hash(tasks: list[str]) -> str:
    return hashlib.sha256("\n".join(tasks).encode()).hexdigest()[:16]


class Orchestrator:
    def __init__(self, ledger: Ledger, cfg: Config, log: Log = print, workers: int = 4):
        self.ledger = ledger
        self.cfg = cfg
        self.repo = Path(cfg.repo).resolve()
        self.log = log
        self.workers = workers
        self.victim = Provider(cfg.victim_provider, cfg.victim_model) if cfg.victim_provider else None
        self.env = victim_env(self.repo, self.victim)
        self.pinned: suite.PinnedSuite | None = None

    # one commit ---------------------------------------------------------------
    def evaluate(self, run_id: str, kind: str, sha: str, tasks: list[str], reps: range) -> StepResult:
        with tracing.span(f"evaluate_commit:{kind}", "CHAIN", commit_sha=sha,
                          input={"kind": kind, "tasks": tasks, "repetitions": [reps.start, reps.stop]}) as sp:
            result = self._evaluate(run_id, kind, sha, tasks, reps)
            sp.output({"skipped": result.skipped, "passes": result.passes, "n": result.n})
            return result

    def _evaluate(self, run_id: str, kind: str, sha: str, tasks: list[str], reps: range) -> StepResult:
        existing = self.ledger.get_step(run_id, kind, sha)
        if existing is not None and existing["status"] == "skip":
            return StepResult(sha, True, [])
        step_id = self.ledger.open_step(run_id, kind, sha)
        done = self.ledger.task_runs(step_id)
        todo = [(t, r) for t in tasks for r in reps if (t, r) not in done]
        if todo:
            worktree = self._worktree(sha)
            assert self.pinned is not None, "suite must be pinned before evaluating"
            suite.install_into(self.pinned, worktree, self.cfg.suite_target)
            with tracing.span("uv_sync_locked", "TOOL", input={"worktree": worktree.name}) as sp:
                installed = sandbox.install(worktree, self.cfg.eval_module, self.cfg.install_timeout_s)
                sp.output({"ok": installed.ok, "log_tail": installed.log[-1500:]})
            if not installed.ok:
                self.ledger.close_step(step_id, "skip", decision=Verdict.SKIP, error=installed.log[-2000:])
                self.log(f"  {sha[:10]} install failed → SKIP")
                return StepResult(sha, True, [])
            self._run_tasks(run_id, step_id, worktree, sha, todo)
        runs = [r for r in self.ledger.task_runs(step_id).values() if r.task_id in tasks and r.repetition in reps]
        result = StepResult(sha, False, runs)
        low, high = wilson(result.passes, result.n, self.cfg.z)
        latencies = [r.latency_ms for r in runs if r.latency_ms is not None]
        self.ledger.close_step(
            step_id, "done", decision=existing["decision"] if existing is not None else None,
            wilson_low=low, wilson_high=high, n=result.n, passes=result.passes,
            cost_usd=sum(r.cost_usd or 0.0 for r in runs),
            latency_ms_p50=statistics.median(latencies) if latencies else None,
        )
        return result

    def _worktree(self, sha: str) -> Path:
        with tracing.span("git_worktree_add", "TOOL", input={"sha": sha}) as sp:
            path = sandbox.add_worktree(self.repo, sha)
            sp.output({"worktree": path.name})
            return path

    def _check_budget(self, run_id: str) -> None:
        if self.ledger.run_cost(run_id) >= self.cfg.budget_usd:
            raise BudgetExceeded(f"run cost reached the ${self.cfg.budget_usd:.2f} per-run cap")
        if self.ledger.total_cost() >= self.cfg.global_budget_usd:
            raise BudgetExceeded(f"ledger total reached the ${self.cfg.global_budget_usd:.2f} global cap")

    def _run_tasks(self, run_id: str, step_id: int, worktree: Path, sha: str, todo: list[tuple[str, int]]) -> None:
        """Workers only run subprocesses; ledger writes and budget checks stay on this thread."""

        def attempt(item: tuple[str, int], n: int) -> TaskRun:
            with tracing.span("victim_eval_run", "TOOL", input={"task_id": item[0], "repetition": item[1],
                                                               "attempt": n}) as sp:
                tr = run_task(worktree, self.env, self.cfg.eval_module, item[0], item[1], run_id=run_id,
                              commit_sha=sha, timeout_s=self.cfg.task_timeout_s)
                sp.output({"passed": tr.passed, "cost_usd": tr.cost_usd, "latency_ms": tr.latency_ms,
                           "victim_trace_id": tr.trace_id, "error": tr.error, "infra": infra_failure(tr)})
                return tr

        def one(item: tuple[str, int]) -> TaskRun:
            """Retry transient infrastructure failures; they are never recorded as failed tasks."""
            for n in range(self.cfg.infra_retries + 1):
                tr = attempt(item, n)
                kind = infra_failure(tr)
                if kind is None:
                    return tr
                if kind == "fatal":
                    raise InfraError(f"{item[0]} rep {item[1]}: {tr.error}")
                if n < self.cfg.infra_retries:
                    time.sleep(self.cfg.infra_backoff_s * 4**n)
            raise InfraError(f"{item[0]} rep {item[1]} still failing after {self.cfg.infra_retries} retries: "
                             f"{tr.error}")

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for start in range(0, len(todo), self.workers):
                self._check_budget(run_id)
                batch = todo[start : start + self.workers]
                # Copy the context per task so each span parents under the current step.
                futures = [pool.submit(contextvars.copy_context().run, one, item) for item in batch]
                errors: list[InfraError] = []
                for fut in futures:  # record every finished run before surfacing an error
                    try:
                        self.ledger.record_task_run(step_id, fut.result())
                    except InfraError as exc:
                        errors.append(exc)
                if errors:
                    raise errors[0]

    # noise-aware classification (PRD §8.1 step 4, §8.2) ------------------------------
    def classify(self, run_id: str, sha: str, base: Baselines, subset: list[str], ranked: list[str],
                 prefix: str = "") -> Verdict:
        """Wilson decision on D × k; INCONCLUSIVE → k more repetitions, then more tasks, up to the cap.

        If the cap is reached and it is still inconclusive, the point estimate decides and the
        step is flagged `low_confidence`. A `prefix` (e.g. the Localiser's "localise:h3") names the
        steps instead of "bisect" and "resample:N", so other judgements of the same commit stay apart.
        """
        kind = prefix or "bisect"
        first = self.evaluate(run_id, kind, sha, subset, range(self.cfg.k))
        if first.skipped:
            return Verdict.SKIP
        runs = list(first.runs)
        k = self.cfg.k
        # Only tasks that dropped from good to bad carry signal; a task that passes on both ends
        # adds cost and pulls the threshold towards 1. With none left, resample the subset again.
        widened = [t for t in ranked if t not in subset and base.drop(t) > 0][: self.cfg.discriminating_size]
        plans = [(subset, range(k, 2 * k)), (widened, range(k)) if widened else (subset, range(2 * k, 3 * k))]
        for round_ in range(self.cfg.max_resample_rounds + 1):
            threshold = base.threshold(runs)
            passes = sum(r.passed for r in runs)
            decision, low, high = decide(passes, len(runs), threshold, self.cfg.z)
            capped = round_ == self.cfg.max_resample_rounds or round_ >= len(plans) or not plans[round_][0]
            final = decision is not Decision.INCONCLUSIVE or capped
            with tracing.span("decision_rule", "TOOL", commit_sha=sha, input={
                "passes": passes, "n": len(runs), "threshold": threshold, "z": self.cfg.z, "round": round_,
            }) as sp:
                if decision is Decision.INCONCLUSIVE and capped:
                    verdict, flag = (Verdict.GOOD if passes / len(runs) >= threshold else Verdict.BAD), "low_confidence"
                elif decision is Decision.INCONCLUSIVE:
                    verdict, flag = None, None
                else:
                    verdict, flag = Verdict(decision.value), None
                sp.output({"decision": decision, "wilson": [low, high], "verdict": verdict, "flag": flag})
            step = self.ledger.get_step(run_id, kind, sha)
            self.ledger.set_decision(step["step_id"], verdict or Decision.INCONCLUSIVE, flag, low, high,
                                     len(runs), passes)
            self.log(f"  {prefix or f'{sha[:10]} {gitops.subject(self.repo, sha)[:44]!r}'}: {passes}/{len(runs)} "
                     f"CI [{low:.2f}, {high:.2f}] vs t={threshold:.2f} → {decision}"
                     + (f" → {verdict} ({flag})" if flag else ""))
            if final:
                return verdict  # type: ignore[return-value]
            tasks, reps = plans[round_]
            kind = f"{prefix}/resample:{round_ + 1}" if prefix else f"resample:{round_ + 1}"
            self.log(f"    resample {round_ + 1}: {len(tasks)} tasks × reps {reps.start}..{reps.stop - 1}")
            extra = self.evaluate(run_id, kind, sha, tasks, reps)
            if extra.skipped:  # cannot happen after a successful install, but stay safe
                return Verdict.SKIP
            runs += extra.runs
        raise AssertionError("unreachable")

    # whole run -----------------------------------------------------------------
    def start(self) -> str:
        return self.ledger.create_run(str(self.repo), self.cfg.good_ref, self.cfg.bad_ref,
                                      suite_hash(list(self.cfg.task_ids)), self.cfg.to_json())

    def run(self, run_id: str) -> Outcome:
        bad_sha = self.ledger.get_run(run_id)["bad_sha"] or gitops.resolve(self.repo, self.cfg.bad_ref)
        with tracing.run_context(run_id=run_id), tracing.span(
            "culprit_run", "WORKFLOW", commit_sha=bad_sha,
            input={"good": self.cfg.good_ref, "bad": self.cfg.bad_ref, "k": self.cfg.k},
        ) as sp:
            trace_id = tracing.current_trace_id()
            if trace_id:
                previous = self.ledger.get_artifact(run_id, "neatlogs_traces")
                self.ledger.put_artifact(run_id, "neatlogs_traces", f"{previous}\n{trace_id}" if previous else trace_id)
                self.log(f"neatlogs trace {trace_id}")
            try:
                outcome = self._run(run_id)
            except Exception as exc:
                self.ledger.finish_run(run_id, "error", None, None, f"{type(exc).__name__}: {exc}")
                raise
            sp.output({"status": outcome.status, "summary": outcome.summary})
            return outcome

    def _pin_suite(self, run_id: str) -> suite.PinnedSuite:
        """First run: snapshot the suite and record it. Resume: rebuild the recorded snapshot."""
        row = self.ledger.get_run(run_id)
        with tracing.span("pin_suite", "TOOL", input={"suite": self.cfg.suite, "suite_ref": self.cfg.suite_ref,
                                                      "recorded": row["suite_sha"]}) as sp:
            if row["suite_sha"]:
                pinned = suite.restore(self.repo, row["suite_source"], row["suite_sha"])
            else:
                pinned = suite.pin(self.repo, self.cfg.suite, self.cfg.suite_ref)
                self.ledger.set_suite(run_id, pinned.source, pinned.sha)
            sp.output({"source": pinned.source, "sha": pinned.sha})
        self.log(f"  suite pinned: {pinned.source} @ {pinned.sha[:12]}")
        return pinned

    def _ensure_tasks(self, run_id: str, good: str) -> list[str]:
        if not self.cfg.task_ids:
            assert self.pinned is not None
            with tracing.span("discover_tasks", "TOOL", commit_sha=good, input={"suite": self.cfg.suite}) as sp:
                tasks = discover_tasks(self.pinned.path)
                sp.output({"tasks": tasks})
            self.cfg = replace(self.cfg, task_ids=tuple(tasks))
            self.ledger.update_config(run_id, suite_hash(tasks), self.cfg.to_json())
        return list(self.cfg.task_ids)

    def _run(self, run_id: str) -> Outcome:
        cfg, repo = self.cfg, self.repo
        with tracing.span("git_rev_list", "TOOL", input={"good": cfg.good_ref, "bad": cfg.bad_ref}) as sp:
            good, bad = self._range(run_id)
            candidates = gitops.first_parent_range(repo, good, bad)
            sp.output({"good": good, "bad": bad, "candidates": candidates})
        if self.victim is not None:
            try:
                self.victim.require_key()  # e.g. a run started with Anthropic, resumed without the key
            except ProviderError as exc:
                return self._finish(run_id, "infra_error", None, f"Stopped: {exc}")
            self.log(f"  victim model: {self.victim.model} via {self.victim.name}")
        if not candidates:  # before the baselines, which are the most expensive part of a run
            return self._finish(run_id, "error", None, f"empty range: {cfg.good_ref}..{cfg.bad_ref} has no commits")
        tested: list[tuple[str, Verdict]] = []
        try:
            return self._bisect(run_id, good, bad, candidates, tested)
        except BudgetExceeded as exc:
            return self._budget_stop(run_id, exc, candidates, tested)
        except InfraError as exc:
            return self._finish(run_id, "infra_error", None,
                                f"Stopped: {exc}. Nothing was counted against the commit. Fix the cause, then "
                                f"`culprit resume {run_id}` continues where it stopped.")

    def _range(self, run_id: str) -> tuple[str, str]:
        """Good and bad SHAs, resolved once; resume keeps them even if the refs have moved since."""
        row = self.ledger.get_run(run_id)
        if row["good_sha"] and row["bad_sha"]:
            return row["good_sha"], row["bad_sha"]
        good, bad = gitops.resolve(self.repo, self.cfg.good_ref), gitops.resolve(self.repo, self.cfg.bad_ref)
        self.ledger.set_range(run_id, good, bad)
        return good, bad

    def _bisect(self, run_id: str, good: str, bad: str, candidates: list[str],
                tested: list[tuple[str, Verdict]]) -> Outcome:
        cfg, repo = self.cfg, self.repo
        self.pinned = self._pin_suite(run_id)
        tasks = self._ensure_tasks(run_id, good)
        self.log(f"run {run_id}: {len(candidates)} commits in {cfg.good_ref}..{cfg.bad_ref}, "
                 f"{len(tasks)} tasks × {cfg.k}")

        base = Baselines(self.evaluate(run_id, "baseline", good, tasks, range(cfg.k)),
                         self.evaluate(run_id, "baseline", bad, tasks, range(cfg.k)))
        if base.good.skipped or base.bad.skipped:
            return self._finish(run_id, "error", None, "good or bad ref failed to install; cannot bisect")
        ci_good = wilson(base.good.passes, base.good.n, cfg.z)
        ci_bad = wilson(base.bad.passes, base.bad.n, cfg.z)
        self.log(f"  good {base.good.passes}/{base.good.n} CI [{ci_good[0]:.2f}, {ci_good[1]:.2f}]  "
                 f"bad {base.bad.passes}/{base.bad.n} CI [{ci_bad[0]:.2f}, {ci_bad[1]:.2f}]")
        p_value = fisher_one_sided(base.good.passes, base.good.n, base.bad.passes, base.bad.n)
        with tracing.span("regression_gate", "TOOL", input={
            "good": [base.good.passes, base.good.n], "bad": [base.bad.passes, base.bad.n], "alpha": cfg.gate_alpha,
        }) as sp:
            significant = base.good.rate > base.bad.rate and p_value < cfg.gate_alpha
            sp.output({"p_value": p_value, "significant": significant})
        self.log(f"  regression gate: one-sided Fisher p={p_value:.4f} (alpha {cfg.gate_alpha})")
        if not significant:
            return self._finish(run_id, "no_regression", None,
                                f"No significant regression to bisect: good {base.good.passes}/{base.good.n} vs "
                                f"bad {base.bad.passes}/{base.bad.n}, one-sided Fisher p={p_value:.4f} "
                                f"≥ {cfg.gate_alpha}")
        with tracing.span("select_discriminating_tasks", "TOOL", input={"size": cfg.discriminating_size}) as sp:
            ranked = self.ranked_tasks(base)
            subset = [t for t in ranked if base.drop(t) > 0]
            subset = subset[: cfg.discriminating_size] or ranked[: cfg.discriminating_size]
            sp.output({"tasks": subset, "ranked": ranked})
        self.log(f"  discriminating tasks: {', '.join(subset)}")

        result = bisect(candidates, lambda sha: self.classify(run_id, sha, base, subset, ranked), tested)
        low_conf = [s["commit_sha"][:10] for s in self.ledger.steps(run_id)
                    if s["flags"] == "low_confidence" and is_bisect_kind(s["kind"])]
        confidence = "95% Wilson" if not low_conf else f"low: point estimate decided {', '.join(low_conf)}"
        if result.first_bad is None:
            summary = f"Culprit is one of {len(result.suspects)} commits (skipped commits hide the boundary): " + \
                ", ".join(s[:10] for s in result.suspects)
            return self._finish(run_id, "ambiguous", result, summary, confidence)

        with tracing.span("entire_checkpoint_explain", "TOOL", commit_sha=result.first_bad,
                          input={"sha": result.first_bad}) as sp:
            intent = commit_intent(repo, result.first_bad)
            sp.output({"available": intent.available, "checkpoint_id": intent.checkpoint_id,
                       "source": intent.source, "lines_removed": intent.lines_removed})
        self.ledger.put_artifact(run_id, "intent", intent.text)
        self.ledger.put_artifact(run_id, "diff", gitops.diff(repo, result.first_bad))
        self.log(f"  intent source: {intent.source}; leakage filter removed {intent.lines_removed} lines")
        summary = f"Culprit: {result.first_bad} {gitops.subject(repo, result.first_bad)!r} (confidence: {confidence})"
        return self._finish(run_id, "found", result, summary, confidence)

    def ranked_tasks(self, base: Baselines) -> list[str]:
        """Tasks ranked by pass-rate drop from good to bad (deterministic part of the Task Selector)."""
        g, b = base.good.task_rates(), base.bad.task_rates()
        return [t for _, t in sorted(((g[t] - b.get(t, 0.0), t) for t in g), key=lambda x: (-x[0], x[1]))]

    def _budget_stop(self, run_id: str, exc: BudgetExceeded, candidates: list[str],
                     tested: list[tuple[str, Verdict]]) -> Outcome:
        lo, hi = bounds(candidates, tested)
        suspects = candidates[lo + 1 : hi + 1]
        summary = (f"Stopped: {exc}. Best current range: {len(suspects)} commits "
                   f"{suspects[0][:10]}..{suspects[-1][:10]}; tested {len(tested)} so far. "
                   f"Resume with `culprit resume {run_id} --budget-usd <higher>` to continue.")
        result = BisectResult(first_bad=None, suspects=suspects, tested=tested)
        return self._finish(run_id, "budget_exceeded", result, summary)

    def _finish(self, run_id: str, status: str, result: BisectResult | None, summary: str,
                confidence: str | None = None) -> Outcome:
        self.ledger.finish_run(run_id, status, result.first_bad if result else None, confidence, summary)
        self.log(summary)
        return Outcome(run_id, status, result, summary)
