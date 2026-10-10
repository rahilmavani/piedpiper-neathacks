"""Shared plumbing for the commands that work on a finished run: `culprit localise` and `culprit fix`.

They read the run from the ledger (config, SHAs, pinned suite, recorded baselines, telling tasks)
instead of re-running anything, and evaluate modified copies of a commit through `Prepared`, an
Orchestrator whose worktree is changed (a patch applied) before the suite is installed and run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from culprit import baseline, llm, sandbox, tracing
from culprit.config import Config
from culprit.ledger import Ledger, TaskRun
from culprit.orchestrator import Baselines, Log, Orchestrator, is_bisect_kind
from culprit.providers import ProviderError


class StageError(RuntimeError):
    """The run can't be used by this command (wrong status, missing artifact, missing key)."""


class PrepareError(RuntimeError):
    """A worktree could not be modified as asked (e.g. a patch doesn't apply)."""


class Prepared(Orchestrator):
    """Evaluates a commit in its own worktree (named by `label`) after `prepare(worktree)` changes it."""

    def __init__(self, ctx: RunContext, label: str, prepare: Callable[[Path], None]):
        super().__init__(ctx.orch.ledger, ctx.orch.cfg, log=ctx.orch.log, workers=ctx.orch.workers)
        self.label, self.prepare = label, prepare
        self.pinned = ctx.orch.pinned

    def _worktree(self, sha: str) -> Path:
        with tracing.span("git_worktree_add", "TOOL", input={"sha": sha, "label": self.label}) as sp:
            path = sandbox.add_worktree(self.repo, sha, self.label.replace(":", "-"))
            sp.output({"worktree": path.name})
        with tracing.span("prepare_worktree", "TOOL", input={"label": self.label}) as sp:
            self.prepare(path)
            sp.output({"ok": True})
        return path


def apply_patch(patch: str, reverse: bool = False) -> Callable[[Path], None]:
    def prepare(worktree: Path) -> None:
        applied, out = sandbox.apply(worktree, patch, reverse)
        if not applied:
            raise PrepareError(out.strip() or "git apply failed")

    return prepare


@dataclass(frozen=True)
class TaskEvidence:
    task_id: str
    good: tuple[int, int]  # passes, runs at the known-good commit
    culprit: tuple[int, int]  # passes, runs at the culprit commit
    errors: tuple[str, ...] = ()
    definition: str = ""


def evidence_text(evidence: list[TaskEvidence]) -> str:
    parts = []
    for e in evidence:
        parts.append(f"\n### {e.task_id}: passed {e.good[0]}/{e.good[1]} before the commit, "
                     f"{e.culprit[0]}/{e.culprit[1]} after\n")
        if e.definition:
            parts.append(f"Task definition:\n```\n{e.definition[:1200]}\n```\n")
        for err in e.errors:
            parts.append(f"Error: {err[:300]}\n")
    return "".join(parts)


@dataclass
class RunContext:
    run_id: str
    orch: Orchestrator  # the run's own config, with the cost cap raised for this command
    culprit: str
    good: str
    bad: str
    base: Baselines
    ranked: list[str]  # tasks by drop from good to bad
    subset: list[str]  # the telling tasks the bisect used

    @property
    def ledger(self) -> Ledger:
        return self.orch.ledger

    def runs_at(self, sha: str) -> list[TaskRun]:
        """Every recorded run of `sha` itself: its bisect steps, and its baseline when it is an end."""
        runs: list[TaskRun] = []
        for step in self.ledger.steps(self.run_id):
            if step["commit_sha"] == sha and (is_bisect_kind(step["kind"]) or step["kind"] == "baseline"):
                runs += self.ledger.task_runs(step["step_id"]).values()
        return runs

    def evidence(self) -> list[TaskEvidence]:
        """Pass counts before and at the culprit, its errors, and each telling task's definition."""
        assert self.orch.pinned is not None
        at_culprit = self.runs_at(self.culprit)
        evidence = []
        for task in self.subset:
            good = [r.passed for r in self.base.good.runs if r.task_id == task]
            mine = [r for r in at_culprit if r.task_id == task]
            errors = tuple(dict.fromkeys(r.error for r in mine if r.error))[:3]
            files = sorted(self.orch.pinned.path.glob(f"{task}.*"))
            evidence.append(TaskEvidence(task, (sum(good), len(good)), (sum(r.passed for r in mine), len(mine)),
                                         errors, files[0].read_text() if files else ""))
        return evidence

    def record_usage(self, purpose: str, reply: llm.Reply | None) -> None:
        for u in reply.usage if reply is not None else []:
            self.ledger.record_llm_call(self.run_id, None, purpose, u.model, u.tokens_in, u.tokens_out,
                                        u.cost_usd, tracing.current_trace_id())


def load(ledger: Ledger, run_id: str, log: Log, workers: int, budget_usd: float) -> RunContext:
    """A found run, ready for a follow-up command that may spend `budget_usd` more than the run has."""
    row = ledger.get_run(run_id)
    if row["status"] != "found" or not row["culprit_sha"]:
        raise StageError(f"run {run_id} has status {row['status']!r}; this needs a run whose culprit was found")
    cfg = replace(Config.from_json(row["config_json"]), budget_usd=ledger.run_cost(run_id) + budget_usd)
    orch = Orchestrator(ledger, cfg, log=log, workers=workers)
    if orch.victim is not None:
        try:
            orch.victim.require_key()
        except ProviderError as exc:
            raise StageError(str(exc)) from exc
    orch.pinned = orch._pin_suite(run_id)  # the run's own suite snapshot
    tasks = list(cfg.task_ids)
    good, bad = row["good_sha"], row["bad_sha"]
    # The same function the run used, so a staged (v2) or full (v1) baseline is rebuilt exactly as
    # recorded and nothing is re-run; asking for every task × k would top up a staged baseline.
    base = baseline.measure(orch, run_id, good, bad, tasks)
    ranked = orch.ranked_tasks(base)
    return RunContext(run_id, orch, row["culprit_sha"], good, bad, base, ranked,
                      _telling_tasks(ledger, run_id, base, ranked, cfg))


def _telling_tasks(ledger: Ledger, run_id: str, base: Baselines, ranked: list[str], cfg: Config) -> list[str]:
    """The discriminating tasks the bisect used: those of a recorded bisect step, else the same rule."""
    for step in ledger.steps(run_id):
        if step["kind"] == "bisect" and step["status"] == "done":
            used = {r.task_id for r in ledger.task_runs(step["step_id"]).values()}
            return [t for t in ranked if t in used]
    dropped = [t for t in ranked if base.drop(t) > 0]  # as in Orchestrator._bisect
    return dropped[: cfg.discriminating_size] or ranked[: cfg.discriminating_size]


@contextmanager
def workflow(ledger: Ledger, run_id: str, name: str, **inputs: object) -> Iterator[tracing.Span]:
    """The command's own neatlogs trace in the run's session, added to the run's trace list for verify-trace."""
    sha = ledger.get_run(run_id)["culprit_sha"]
    with tracing.run_context(run_id=run_id), tracing.span(name, "WORKFLOW", commit_sha=sha, input=inputs) as sp:
        trace_id = tracing.current_trace_id()
        if trace_id:
            previous = ledger.get_artifact(run_id, "neatlogs_traces")
            ledger.put_artifact(run_id, "neatlogs_traces", f"{previous}\n{trace_id}" if previous else trace_id)
        yield sp
