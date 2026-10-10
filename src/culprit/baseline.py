"""Measure both ends of the range (v2: staged and reused).

v1 ran every task × k on the good and the bad commit: 26 tasks × 3 × 2 = 156 victim runs, the most
expensive part of a run. v2 does it in two stages:

1. **Screen**: every task × 1 (repetition 0) on both ends (step kind `baseline`).
2. **Full k**: repetitions 1..k-1, on both ends, only for tasks that did not pass on both ends in
   the screen (step kind `baseline:full`). Those are the tasks that differ, and the ones that may be
   flaky or broken on both sides. A task that passed once on each end gets no more runs.

Both ends always run the same (task, repetition) set, so the regression gate compares like with
like, and it uses exactly the runs that were made: n is the real count, not tasks × k. The
selection rule is symmetric in good and bad (swap the labels and the same tasks are chosen), so
under "no regression" it can't favour one side. It can miss a task that drops from good to bad but
happened to pass once on the bad end; the other dropped tasks still carry the signal.

Before each stage, results already measured for the same commit in an earlier matching run are
copied in (culprit.reuse), so only the gaps run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from culprit import reuse, tracing

if TYPE_CHECKING:
    from culprit.orchestrator import Baselines, Orchestrator, StepResult

SCREEN = "baseline"
FULL = "baseline:full"


def screen_failures(good: StepResult, bad: StepResult) -> list[str]:
    """Tasks that did not pass on both ends of the screen: these get the full k."""
    g, b = good.task_rates(), bad.task_rates()
    return sorted(t for t in g if not (g[t] == 1.0 and b.get(t, 0.0) == 1.0))


def _measure(orch: Orchestrator, run_id: str, kind: str, sha: str, tasks: list[str], reps: range) -> StepResult:
    copied = reuse.import_runs(orch.ledger, orch.cfg, run_id, kind, sha, [(t, r) for t in tasks for r in reps])
    if copied:
        with tracing.span("reuse_baseline", "TOOL", commit_sha=sha, input={"kind": kind}) as sp:
            sp.output({"copied_from": copied})
        orch.log(f"  {sha[:10]} {kind}: reused " + ", ".join(f"{n} runs from {src}" for src, n in copied.items()))
    return orch.evaluate(run_id, kind, sha, tasks, reps)


def measure(orch: Orchestrator, run_id: str, good: str, bad: str, tasks: list[str]) -> Baselines:
    from culprit.orchestrator import Baselines, StepResult

    k = orch.cfg.k
    if not orch.cfg.staged_baseline or k <= 1:
        return Baselines(_measure(orch, run_id, SCREEN, good, tasks, range(k)),
                         _measure(orch, run_id, SCREEN, bad, tasks, range(k)))
    g1 = _measure(orch, run_id, SCREEN, good, tasks, range(1))
    b1 = _measure(orch, run_id, SCREEN, bad, tasks, range(1))
    if g1.skipped or b1.skipped:
        return Baselines(g1, b1)
    deep = screen_failures(g1, b1)
    with tracing.span("baseline_screen", "TOOL", input={"tasks": len(tasks), "k": k}) as sp:
        sp.output({"full_k": deep, "screen": [[g1.passes, g1.n], [b1.passes, b1.n]]})
    orch.log(f"  screen ×1: good {g1.passes}/{g1.n}, bad {b1.passes}/{b1.n}; full k={k} on {len(deep)} tasks")
    if not deep:
        return Baselines(g1, b1)
    g2 = _measure(orch, run_id, FULL, good, deep, range(1, k))
    b2 = _measure(orch, run_id, FULL, bad, deep, range(1, k))
    return Baselines(StepResult(good, False, g1.runs + g2.runs), StepResult(bad, False, b1.runs + b2.runs))
