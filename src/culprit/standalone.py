"""Shared setup for commands that examine one ref on its own: `culprit drift` and `culprit audit`.

They are runs in the ledger like any other (so costs, budget caps, resume, traces and export-costs
work unchanged), with good = bad = the ref, and their own statuses. Each is one neatlogs WORKFLOW
trace in the run's session.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from culprit import gitops, sandbox, tracing
from culprit.config import Config
from culprit.ledger import Ledger
from culprit.orchestrator import Log, Orchestrator


@dataclass
class Standalone:
    orch: Orchestrator
    run_id: str
    sha: str
    tasks: list[str]

    @property
    def ledger(self) -> Ledger:
        return self.orch.ledger


def open_run(ledger: Ledger, cfg: Config, ref: str, log: Log, workers: int,
             suite: tuple[str, str] | None = None, run_id: str | None = None) -> Standalone:
    """A new run on `ref` (or `run_id` resumed), with its suite pinned and its tasks discovered.

    `suite` = (source, sha) pins a recorded snapshot instead of taking a new one, so a comparison
    with an earlier run uses exactly the same tasks.
    """
    orch = Orchestrator(ledger, replace(cfg, good_ref=ref, bad_ref=ref), log=log, workers=workers)
    if run_id is None:
        run_id = orch.start()
        sha = gitops.resolve(orch.repo, ref)
        ledger.set_range(run_id, sha, sha)
        if suite is not None:
            ledger.set_suite(run_id, *suite)
    else:
        row = ledger.get_run(run_id)
        orch.cfg = Config.from_json(row["config_json"])
        sha = row["good_sha"]
    orch.pinned = orch._pin_suite(run_id)
    tasks = orch._ensure_tasks(run_id, sha)
    return Standalone(orch, run_id, sha, tasks)


@contextmanager
def workflow(st: Standalone, name: str, **inputs: object) -> Iterator[tracing.Span]:
    """The command's neatlogs WORKFLOW trace, session = run ID, added to the run's trace list."""
    with tracing.run_context(run_id=st.run_id), tracing.span(name, "WORKFLOW", commit_sha=st.sha,
                                                               input=inputs) as sp:
        trace_id = tracing.current_trace_id()
        if trace_id:
            previous = st.ledger.get_artifact(st.run_id, "neatlogs_traces")
            st.ledger.put_artifact(st.run_id, "neatlogs_traces", f"{previous}\n{trace_id}" if previous else trace_id)
        yield sp


class Patched(Orchestrator):
    """Evaluates a commit in its own worktree (`label`) after `prepare(worktree)` changes its files."""

    def __init__(self, base: Orchestrator, label: str, prepare: Callable[[Path], None]):
        super().__init__(base.ledger, base.cfg, log=base.log, workers=base.workers)
        self.label, self.prepare = label, prepare
        self.pinned = base.pinned

    def _worktree(self, sha: str) -> Path:
        with tracing.span("git_worktree_add", "TOOL", input={"sha": sha, "label": self.label}) as sp:
            path = sandbox.add_worktree(self.repo, sha, self.label.replace(":", "-"))
            sp.output({"worktree": path.name})
        with tracing.span("prepare_worktree", "TOOL", input={"label": self.label}) as sp:
            self.prepare(path)
            sp.output({"ok": True})
        return path
