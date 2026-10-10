"""Localiser: which hunk of the culprit commit is responsible (PRD §8.3).

1. Split the culprit diff into hunks.
2. An LLM ranks them from the diff, the commit's (leak-filtered) intent and the failing tasks.
3. The top-N hunks are reverse-applied one at a time on the culprit commit and re-tested on the
   discriminating tasks; the first revert that flips BAD → GOOD is the responsible hunk. If none
   does, pairs are tried (capped), then the answer falls back to the whole commit.

`culprit localise <run_id>` runs this on a finished run whose culprit was found. Baselines and
bisect steps come from the ledger; each revert is judged like a bisect step (Wilson rule,
resampling, budget, resume) under its own step kinds, `localise:h<N>`.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from pydantic import BaseModel

from culprit import gitops, llm, sandbox, tracing
from culprit.bisect import Verdict
from culprit.config import Config
from culprit.ledger import Ledger, TaskRun
from culprit.orchestrator import Baselines, BudgetExceeded, InfraError, Log, Orchestrator, is_bisect_kind
from culprit.providers import ProviderError

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
MAX_HUNK_CHARS = 3000


@dataclass(frozen=True)
class Hunk:
    id: int  # 1-based, in diff order
    file: str
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    header: str  # the file's `diff --git` … `+++` lines
    body: str  # the `@@` line and the hunk's lines

    def changed_lines(self) -> tuple[str, int, int]:
        """("new", first, last) added lines after the commit, or ("old", …) removed lines when nothing was added."""
        old, new = self.old_start, self.new_start
        added: list[int] = []
        removed: list[int] = []
        for line in self.body.splitlines()[1:]:
            if line.startswith("+"):
                added.append(new)
                new += 1
            elif line.startswith("-"):
                removed.append(old)
                old += 1
            elif not line.startswith("\\"):
                old, new = old + 1, new + 1
        side, lines = ("new", added) if added else ("old", removed)
        return side, min(lines, default=0), max(lines, default=0)

    @property
    def where(self) -> str:
        side, first, last = self.changed_lines()
        span = f"{first}" if first == last else f"{first}-{last}"
        return f"{self.file}:{span}" if side == "new" else f"{self.file}: lines {span} removed"


def split_hunks(diff: str) -> list[Hunk]:
    """Hunks of a `git show --patch` diff. Binary and mode-only changes have no hunks and are left out."""
    hunks: list[Hunk] = []
    header: list[str] = []
    file = ""
    body: list[str] | None = None
    nums: tuple[int, int, int, int] = (0, 0, 0, 0)

    def close() -> None:
        if body is not None:
            hunks.append(Hunk(len(hunks) + 1, file, *nums, "".join(header), "".join(body)))

    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            close()
            header, body, file = [line], None, ""
        elif body is None and not line.startswith("@@"):
            header.append(line)
            if line.startswith("--- a/"):
                file = line[6:].rstrip("\n")
            elif line.startswith("+++ b/"):
                file = line[6:].rstrip("\n")
        elif (m := HUNK_HEADER.match(line)) is not None:
            close()
            old_s, old_l, new_s, new_l = m.groups()
            nums = (int(old_s), int(old_l or 1), int(new_s), int(new_l or 1))
            body = [line]
        elif body is not None:
            body.append(line)
    close()
    return hunks


def patch_for(hunks: list[Hunk]) -> str:
    """One patch holding the given hunks, each file's header once and its hunks in order."""
    by_file: dict[str, list[Hunk]] = {}
    for h in hunks:
        by_file.setdefault(h.header, []).append(h)
    parts = []
    for header, group in by_file.items():
        parts.append(header + "".join(h.body if h.body.endswith("\n") else h.body + "\n"
                                      for h in sorted(group, key=lambda h: h.old_start)))
    return "".join(parts)


# ranking ---------------------------------------------------------------------------------
class RankedHunk(BaseModel):
    hunk: int
    reason: str


class HunkRanking(BaseModel):
    ranking: list[RankedHunk]


SYSTEM = (
    "You localise behaviour regressions in an LLM agent's code. A commit made the agent fail evaluation "
    "tasks it used to pass. Rank the commit's hunks from most to least likely to cause those failures. "
    "Changes to tests, docs and comments rarely change behaviour."
)


@dataclass(frozen=True)
class TaskEvidence:
    task_id: str
    good: tuple[int, int]  # passes, runs at the known-good commit
    culprit: tuple[int, int]  # passes, runs at the culprit commit
    errors: tuple[str, ...] = ()
    definition: str = ""


def rank_prompt(hunks: list[Hunk], intent: str, evidence: list[TaskEvidence]) -> str:
    parts = ["## Why the commit was made\n", intent.strip()[:4000] or "(unknown)", "\n\n## Failing tasks\n"]
    for e in evidence:
        parts.append(f"\n### {e.task_id}: passed {e.good[0]}/{e.good[1]} before the commit, "
                     f"{e.culprit[0]}/{e.culprit[1]} after\n")
        if e.definition:
            parts.append(f"Task definition:\n```\n{e.definition[:1200]}\n```\n")
        for err in e.errors:
            parts.append(f"Error: {err[:300]}\n")
    parts.append("\n## Hunks of the commit\n")
    for h in hunks:
        body = h.body if len(h.body) <= MAX_HUNK_CHARS else h.body[:MAX_HUNK_CHARS] + "\n… (truncated)\n"
        parts.append(f"\n### Hunk {h.id}: {h.where}\n```diff\n{body}```\n")
    parts.append(f"\nRank all {len(hunks)} hunks by id, most likely cause first, with a one-sentence reason each.")
    return "".join(parts)


@dataclass(frozen=True)
class Ranking:
    order: list[int]  # every hunk id exactly once
    reasons: dict[int, str]
    source: str  # "llm" or "fallback: <why>"
    reply: llm.Reply[HunkRanking] | None = None


def rank(hunks: list[Hunk], intent: str, evidence: list[TaskEvidence]) -> Ranking:
    """LLM ranking; ids it leaves out keep diff order after the ones it ranked. Falls back to diff order."""
    ids = [h.id for h in hunks]
    try:
        reply = llm.structured(SYSTEM, rank_prompt(hunks, intent, evidence), HunkRanking)
    except llm.LLMError as exc:
        return Ranking(ids, {}, f"fallback: {exc}")
    order: list[int] = []
    reasons: dict[int, str] = {}
    for item in reply.value.ranking:
        if item.hunk in ids and item.hunk not in order:
            order.append(item.hunk)
            reasons[item.hunk] = item.reason
    return Ranking(order + [i for i in ids if i not in order], reasons, "llm", reply)


# search ----------------------------------------------------------------------------------
@dataclass
class Localisation:
    status: str  # "hunk", "pair", "whole_commit", "single_hunk", "no_hunks" or "incomplete"
    hunks: list[int]  # the responsible hunk ids (all of them for whole_commit)
    tried: list[tuple[tuple[int, ...], Verdict]] = field(default_factory=list)
    note: str = ""


def search(ranked: list[int], verdict: Callable[[tuple[int, ...]], Verdict], top_n: int = 3,
           max_pairs: int = 3) -> Localisation:
    """Revert single hunks in rank order, then pairs of the top-N, until one flips the commit to GOOD."""
    if not ranked:
        return Localisation("no_hunks", [])
    if len(ranked) == 1:  # reverting the only hunk is reverting the commit, whose parent is known GOOD
        return Localisation("single_hunk", list(ranked))
    top = ranked[:top_n]
    found = Localisation("whole_commit", list(ranked))
    for ids in [(h,) for h in top] + list(itertools.combinations(top, 2))[:max_pairs]:
        v = verdict(ids)
        found.tried.append((ids, v))
        if v == Verdict.GOOD:
            found.status, found.hunks = ("hunk" if len(ids) == 1 else "pair"), list(ids)
            return found
    return found


# a finished run ------------------------------------------------------------------------------
class LocaliseError(RuntimeError):
    pass


class RevertError(RuntimeError):
    pass


class _Reverting(Orchestrator):
    """Evaluates a commit with `patch` reverse-applied, in a worktree of its own."""

    def __init__(self, ledger: Ledger, cfg: Config, log: Log, workers: int, label: str, patch: str):
        super().__init__(ledger, cfg, log=log, workers=workers)
        self.label, self.patch = label, patch

    def _worktree(self, sha: str) -> Path:
        with tracing.span("git_worktree_add", "TOOL", input={"sha": sha, "label": self.label}) as sp:
            path = sandbox.add_worktree(self.repo, sha, self.label.replace(":", "-"))
            applied, out = sandbox.reverse_apply(path, self.patch)
            sp.output({"worktree": path.name, "reverse_applied": applied, "log": out[-1500:]})
        if not applied:
            raise RevertError(out.strip() or "git apply -R failed")
        return path


def describe(loc: Localisation, by_id: dict[int, Hunk]) -> str:
    where = ", ".join(f"hunk {i} ({by_id[i].where})" for i in loc.hunks if i in by_id)
    return {"hunk": where, "pair": f"hunk pair {where}", "single_hunk": f"its only hunk, {where}",
            "whole_commit": "the whole commit (no single hunk or pair restores it)", "no_hunks": "no text hunks",
            "incomplete": f"not localised ({loc.note})"}[loc.status]


def localise_run(ledger: Ledger, run_id: str, log: Log = print, workers: int = 4, top_n: int = 3,
                 max_pairs: int = 3, budget_usd: float = 1.50) -> tuple[Localisation, str]:
    """Localise a found run's culprit. `budget_usd` is what localisation may add to the run's cost."""
    row = ledger.get_run(run_id)
    if row["status"] != "found" or not row["culprit_sha"]:
        raise LocaliseError(f"run {run_id} has status {row['status']!r}; only a found culprit can be localised")
    sha = row["culprit_sha"]
    cfg = Config.from_json(row["config_json"])
    cfg = replace(cfg, budget_usd=ledger.run_cost(run_id) + budget_usd)
    orch = Orchestrator(ledger, cfg, log=log, workers=workers)
    if orch.victim is not None:
        try:
            orch.victim.require_key()
        except ProviderError as exc:
            raise LocaliseError(str(exc)) from exc
    with tracing.run_context(run_id=run_id), tracing.span(
        "culprit_localise", "WORKFLOW", commit_sha=sha, input={"top_n": top_n, "max_pairs": max_pairs}
    ) as sp:
        trace_id = tracing.current_trace_id()
        if trace_id:
            previous = ledger.get_artifact(run_id, "neatlogs_traces")
            ledger.put_artifact(run_id, "neatlogs_traces", f"{previous}\n{trace_id}" if previous else trace_id)
        loc, text = _localise(orch, run_id, sha, top_n, max_pairs)
        sp.output({"status": loc.status, "hunks": loc.hunks, "tried": loc.tried})
    log(f"responsible: {text}")
    return loc, text


def _localise(orch: Orchestrator, run_id: str, sha: str, top_n: int, max_pairs: int) -> tuple[Localisation, str]:
    ledger, cfg = orch.ledger, orch.cfg
    orch.pinned = orch._pin_suite(run_id)  # the run's own suite snapshot
    tasks = list(cfg.task_ids)
    good, bad = ledger.get_run(run_id)["good_sha"], ledger.get_run(run_id)["bad_sha"]
    base = Baselines(orch.evaluate(run_id, "baseline", good, tasks, range(cfg.k)),
                     orch.evaluate(run_id, "baseline", bad, tasks, range(cfg.k)))  # recorded, so no runs
    ranked = orch.ranked_tasks(base)
    at_culprit = _runs_at(ledger, run_id, sha)
    subset = _subset(ledger, run_id, sha, base, ranked, cfg)

    target = f"{cfg.suite_target}/"  # the pinned suite replaces these files, so reverting them is moot
    hunks = [h for h in split_hunks(gitops.diff(orch.repo, sha)) if not h.file.startswith(target)]
    by_id = {h.id: h for h in hunks}
    ranking = _ranking(orch, run_id, sha, hunks, _evidence(orch, base, subset, at_culprit))

    def verdict(ids: tuple[int, ...]) -> Verdict:
        label = "localise:" + "+".join(f"h{i}" for i in ids)
        rev = _Reverting(ledger, cfg, orch.log, orch.workers, label, patch_for([by_id[i] for i in ids]))
        rev.pinned = orch.pinned
        try:
            return rev.classify(run_id, sha, base, subset, ranked, prefix=label)
        except RevertError as exc:
            orch.log(f"  {label} does not reverse-apply → SKIP ({exc})")
            return Verdict.SKIP

    with tracing.span("localise_search", "TOOL", commit_sha=sha,
                      input={"ranking": ranking["order"], "top_n": top_n, "max_pairs": max_pairs}) as sp:
        try:
            loc = search(ranking["order"], verdict, top_n, max_pairs)
        except (BudgetExceeded, InfraError) as exc:
            loc = Localisation("incomplete", [], note=f"{type(exc).__name__}: {exc}")
        sp.output({"status": loc.status, "hunks": loc.hunks, "tried": loc.tried, "note": loc.note})
    text = describe(loc, by_id)
    ledger.put_artifact(run_id, "localisation", json.dumps({
        "commit": sha, "status": loc.status, "summary": text, "note": loc.note,
        "hunks": [{"id": i, "file": by_id[i].file, "where": by_id[i].where,
                   "reason": ranking["reasons"].get(str(i), "")} for i in loc.hunks],
        "tried": [{"hunks": list(ids), "verdict": v} for ids, v in loc.tried],
        "ranking": ranking, "top_n": top_n, "max_pairs": max_pairs,
    }))
    return loc, text


def _runs_at(ledger: Ledger, run_id: str, sha: str) -> list[TaskRun]:
    """Every recorded run of the commit itself: its bisect steps, or its baseline when it is the bad end."""
    runs: list[TaskRun] = []
    for step in ledger.steps(run_id):
        if step["commit_sha"] == sha and (is_bisect_kind(step["kind"]) or step["kind"] == "baseline"):
            runs += ledger.task_runs(step["step_id"]).values()
    return runs


def _subset(ledger: Ledger, run_id: str, sha: str, base: Baselines, ranked: list[str], cfg: Config) -> list[str]:
    """The discriminating tasks the bisect used: those of a recorded bisect step, else the same rule."""
    for step in ledger.steps(run_id):
        if step["kind"] == "bisect" and step["status"] == "done":
            used = {r.task_id for r in ledger.task_runs(step["step_id"]).values()}
            return [t for t in ranked if t in used]
    dropped = [t for t in ranked if base.drop(t) > 0]  # as in Orchestrator._bisect
    return dropped[: cfg.discriminating_size] or ranked[: cfg.discriminating_size]


def _evidence(orch: Orchestrator, base: Baselines, subset: list[str], at_culprit: list[TaskRun]) -> list[TaskEvidence]:
    """Pass counts before and at the culprit, its errors, and each task's definition from the pinned suite."""
    assert orch.pinned is not None
    evidence = []
    for task in subset:
        good = [r.passed for r in base.good.runs if r.task_id == task]
        mine = [r for r in at_culprit if r.task_id == task]
        errors = tuple(dict.fromkeys(r.error for r in mine if r.error))[:3]
        files = sorted(orch.pinned.path.glob(f"{task}.*"))
        evidence.append(TaskEvidence(task, (sum(good), len(good)), (sum(r.passed for r in mine), len(mine)),
                                     errors, files[0].read_text() if files else ""))
    return evidence


def _ranking(orch: Orchestrator, run_id: str, sha: str, hunks: list[Hunk], evidence: list[TaskEvidence]) -> dict:
    """The stored ranking if there is one (resume never asks the model twice), else a new one."""
    recorded = orch.ledger.get_artifact(run_id, "hunk_ranking")
    if recorded is not None:
        return json.loads(recorded)
    with tracing.span("localise_rank", "AGENT", commit_sha=sha, input={"hunks": len(hunks)}) as sp:
        if len(hunks) < 2:  # nothing to rank, so no model call
            result = Ranking([h.id for h in hunks], {}, "not needed")
        else:
            result = rank(hunks, orch.ledger.get_artifact(run_id, "intent") or "", evidence)
        sp.output({"order": result.order, "source": result.source})
    if result.reply is not None:
        for u in result.reply.usage:
            orch.ledger.record_llm_call(run_id, None, "localise_rank", u.model, u.tokens_in, u.tokens_out,
                                        u.cost_usd, tracing.current_trace_id())
    ranking = {"order": result.order, "reasons": {str(k): v for k, v in result.reasons.items()},
               "source": result.source}
    orch.ledger.put_artifact(run_id, "hunk_ranking", json.dumps(ranking))
    orch.log(f"  hunk ranking ({result.source}): {', '.join(f'h{i}' for i in result.order)}")
    return ranking
