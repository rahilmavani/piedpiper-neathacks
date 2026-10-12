"""Localiser: which hunk of the culprit commit is responsible.

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
from dataclasses import dataclass, field

from pydantic import BaseModel

from culprit import finished, gitops, llm, tracing, victim_traces
from culprit.bisect import Verdict
from culprit.entire import ref_names
from culprit.finished import TaskEvidence, evidence_text
from culprit.ledger import Ledger
from culprit.orchestrator import BudgetExceeded, InfraError, Log

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


def rank_prompt(hunks: list[Hunk], intent: str, evidence: list[TaskEvidence], traces: str = "") -> str:
    parts = ["## Why the commit was made\n", intent.strip()[:4000] or "(unknown)", "\n\n## Failing tasks\n",
             evidence_text(evidence)]
    if traces:
        parts += ["\n## Tool calls in failing runs after the commit (from their neatlogs traces)\n", traces]
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


def rank(hunks: list[Hunk], intent: str, evidence: list[TaskEvidence], traces: str = "") -> Ranking:
    """LLM ranking; ids it leaves out keep diff order after the ones it ranked. Falls back to diff order."""
    ids = [h.id for h in hunks]
    try:
        reply = llm.structured(SYSTEM, rank_prompt(hunks, intent, evidence, traces), HunkRanking)
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
def describe(loc: Localisation, by_id: dict[int, Hunk]) -> str:
    where = ", ".join(f"hunk {i} ({by_id[i].where})" for i in loc.hunks if i in by_id)
    return {"hunk": where, "pair": f"hunk pair {where}", "single_hunk": f"its only hunk, {where}",
            "whole_commit": "the whole commit (no single hunk or pair restores it)", "no_hunks": "no text hunks",
            "incomplete": f"not localised ({loc.note})"}[loc.status]


def localise_run(ledger: Ledger, run_id: str, log: Log = print, workers: int = 4, top_n: int = 3,
                 max_pairs: int = 3, budget_usd: float = 1.50, replay: bool = False) -> tuple[Localisation, str]:
    """Localise a found run's culprit. `budget_usd` is what localisation may add to the run's cost;
    `replay` uses only what the ledger holds and fails if anything else would be needed."""
    with finished.workflow(ledger, run_id, "culprit_localise", top_n=top_n, max_pairs=max_pairs) as sp:
        ctx = finished.load(ledger, run_id, log, workers, budget_usd, replay)
        loc, text = _localise(ctx, top_n, max_pairs)
        sp.output({"status": loc.status, "hunks": loc.hunks, "tried": loc.tried})
    log(f"responsible: {text}")
    return loc, text


def culprit_hunks(ctx: finished.RunContext) -> list[Hunk]:
    """The culprit's hunks, without those in the suite directory, which the pinned suite replaces anyway."""
    target = f"{ctx.orch.cfg.suite_target}/"
    return [h for h in split_hunks(gitops.diff(ctx.orch.repo, ctx.culprit)) if not h.file.startswith(target)]


def _localise(ctx: finished.RunContext, top_n: int, max_pairs: int) -> tuple[Localisation, str]:
    hunks = culprit_hunks(ctx)
    by_id = {h.id: h for h in hunks}
    ranking = _ranking(ctx, hunks)

    def verdict(ids: tuple[int, ...]) -> Verdict:
        label = "localise:" + "+".join(f"h{i}" for i in ids)
        rev = finished.Prepared(ctx, label, finished.apply_patch(patch_for([by_id[i] for i in ids]), reverse=True))
        try:
            return rev.classify(ctx.run_id, ctx.culprit, ctx.base, ctx.subset, ctx.ranked, prefix=label)
        except finished.PrepareError as exc:
            ctx.orch.log(f"  {label} does not reverse-apply → SKIP ({exc})")
            return Verdict.SKIP

    with tracing.span("localise_search", "TOOL", commit_sha=ctx.culprit,
                      input={"ranking": ranking["order"], "top_n": top_n, "max_pairs": max_pairs}) as sp:
        try:
            loc = search(ranking["order"], verdict, top_n, max_pairs)
        except (BudgetExceeded, InfraError) as exc:
            loc = Localisation("incomplete", [], note=f"{type(exc).__name__}: {exc}")
        sp.output({"status": loc.status, "hunks": loc.hunks, "tried": loc.tried, "note": loc.note})
    if ctx.replay and loc.status == "incomplete":  # before anything is written
        raise ctx.unrecorded(f"victim runs for the reverts ({loc.note})")
    text = describe(loc, by_id)
    ctx.ledger.put_artifact(ctx.run_id, "localisation", json.dumps({
        "commit": ctx.culprit, "status": loc.status, "summary": text, "note": loc.note,
        "hunks": [{"id": i, "file": by_id[i].file, "where": by_id[i].where,
                   "reason": ranking["reasons"].get(str(i), "")} for i in loc.hunks],
        "tried": [{"hunks": list(ids), "verdict": v} for ids, v in loc.tried],
        "ranking": ranking, "top_n": top_n, "max_pairs": max_pairs,
    }))
    return loc, text


def _ranking(ctx: finished.RunContext, hunks: list[Hunk]) -> dict:
    """The stored ranking if there is one (resume never asks the model twice), else a new one."""
    recorded = ctx.ledger.get_artifact(ctx.run_id, "hunk_ranking")
    if recorded is not None:
        return json.loads(recorded)
    if ctx.replay:
        raise ctx.unrecorded("a hunk ranking (a model call)")
    traces = victim_traces.Summary("", "not needed")
    with tracing.span("localise_rank", "AGENT", commit_sha=ctx.culprit, input={"hunks": len(hunks)}) as sp:
        if len(hunks) < 2:  # nothing to rank, so no model call
            result = Ranking([h.id for h in hunks], {}, "not needed")
        else:
            traces = _failing_traces(ctx)
            result = rank(hunks, ctx.ledger.get_artifact(ctx.run_id, "intent") or "", ctx.evidence(), traces.text)
        sp.output({"order": result.order, "source": result.source})
    ctx.record_usage("localise_rank", result.reply)
    ranking = {"order": result.order, "reasons": {str(k): v for k, v in result.reasons.items()},
               "source": result.source,
               "traces": {"note": traces.note, "trace_ids": traces.trace_ids, "lines_removed": traces.lines_removed}}
    ctx.ledger.put_artifact(ctx.run_id, "hunk_ranking", json.dumps(ranking))
    ctx.orch.log(f"  hunk ranking ({result.source}): {', '.join(f'h{i}' for i in result.order)}")
    return ranking


def _failing_traces(ctx: finished.RunContext) -> victim_traces.Summary:
    """Tool-call sequences of failing runs at the culprit, telling tasks first. Never fails the stage."""
    order = {t: i for i, t in enumerate(ctx.subset)}
    failing = sorted((r for r in ctx.runs_at(ctx.culprit) if not r.passed),
                     key=lambda r: (order.get(r.task_id, len(order)), r.task_id, r.repetition))
    with tracing.span("neatlogs_readback", "TOOL", commit_sha=ctx.culprit, input={"failing_runs": len(failing)}) as sp:
        summary = victim_traces.summarise(failing, ref_names(ctx.orch.repo))
        sp.output({"note": summary.note, "trace_ids": summary.trace_ids, "lines_removed": summary.lines_removed})
    ctx.orch.log(f"  victim traces: {summary.note}")
    return summary

