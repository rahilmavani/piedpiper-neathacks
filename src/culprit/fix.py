"""Fixer and Verifier (PRD §8.4, §10): `culprit fix <run_id>` on a localised run.

The Fixer (one structured LLM call per attempt) sees the responsible hunks, the commit's leak-filtered
intent, the telling tasks' results and the affected files at the bad head. It names the gain the
commit was after (latency, tokens, cost or none) and returns exact search-and-replace edits that
restore the lost behaviour without reverting the commit. Edits may touch only the responsible
hunks' files, never the suite.

The Verifier applies the patch at the bad head and runs the full suite plus the held-out tasks × k.
A fix is verified only if all three gates hold (PRD §10):
1. quality: its Wilson interval reaches the good baseline's (upper bound ≥ good's lower bound);
2. intended gain kept: the named metric is no worse than at bad by more than the tolerance;
3. no new failures: no task that passes every repetition at good fails every repetition with the fix.
A failed attempt is fed back to the next one. After the last attempt fails, the responsible hunks'
revert is verified at the bad head the same way, as the fallback.
"""

from __future__ import annotations

import difflib
import json
import statistics
from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel

from culprit import finished, gitops, llm, tracing
from culprit.evalrunner import discover_tasks
from culprit.finished import RunContext, evidence_text
from culprit.ledger import Ledger, TaskRun
from culprit.localise import Hunk, culprit_hunks, patch_for
from culprit.orchestrator import BudgetExceeded, InfraError, Log
from culprit.stats import wilson

LOCALISED = {"hunk", "pair", "single_hunk", "whole_commit"}
MAX_FILE_CHARS = 20000
Metric = Literal["latency", "tokens", "cost", "none"]


class Edit(BaseModel):
    file: str
    old: str  # an exact snippet that occurs once in the file at the bad head
    new: str


class FixProposal(BaseModel):
    intended_gain: Metric
    gain_reason: str
    explanation: str
    edits: list[Edit]


SYSTEM = (
    "You fix a behaviour regression in an LLM agent's code. A commit made for a good reason (its intended "
    "gain) also broke behaviour that evaluation tasks check. Write the smallest change to the current code that "
    "restores the lost behaviour while keeping the intended gain. Do not simply revert the commit. Each edit "
    "replaces one exact snippet `old`, which must occur exactly once in that file as shown, with `new`. Also "
    "name the intended gain: latency, tokens, cost, or none if the commit's reason is none of those."
)


# edits → patch -------------------------------------------------------------------------------
def edits_to_patch(files: dict[str, str], edits: list[Edit], allowed: set[str]) -> str:
    """A git patch for the edits, or ValueError naming the first edit that can't be applied."""
    changed = dict(files)
    for i, e in enumerate(edits, 1):
        if e.file not in allowed:
            raise ValueError(f"edit {i}: {e.file!r} is not one of the files you may change ({', '.join(sorted(allowed))})")
        count = changed[e.file].count(e.old) if e.old else 0
        if count != 1:
            raise ValueError(f"edit {i}: the `old` snippet occurs {count} times in {e.file}; it must occur exactly once")
        changed[e.file] = changed[e.file].replace(e.old, e.new)
    patch = []
    for name in sorted(changed):
        if changed[name] == files[name]:
            continue
        lines = difflib.unified_diff(files[name].splitlines(keepends=True), changed[name].splitlines(keepends=True),
                                     f"a/{name}", f"b/{name}")
        body = "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)
        patch.append(f"diff --git a/{name} b/{name}\n{body}")
    if not patch:
        raise ValueError("the edits change nothing")
    return "".join(patch)


# gates -----------------------------------------------------------------------------------------
METRICS = {
    "latency": lambda r: r.latency_ms,
    "tokens": lambda r: None if r.tokens_in is None or r.tokens_out is None else r.tokens_in + r.tokens_out,
    "cost": lambda r: r.cost_usd,
}


@dataclass
class Gates:
    fix: tuple[int, int]  # passes, runs
    good: tuple[int, int]
    fix_ci: tuple[float, float]
    good_ci: tuple[float, float]
    quality: bool
    metric: str
    fix_value: float | None
    bad_value: float | None
    gain: bool | None  # None: no metric named, or not measured
    new_failures: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.quality and not self.new_failures and self.gain is not False

    def failures(self) -> list[str]:
        out = []
        if not self.quality:
            out.append(f"quality: {self.fix[0]}/{self.fix[1]} passed, CI [{self.fix_ci[0]:.2f}, {self.fix_ci[1]:.2f}] "
                       f"is below the good baseline's CI [{self.good_ci[0]:.2f}, {self.good_ci[1]:.2f}]")
        if self.gain is False:
            out.append(f"intended gain lost: mean {self.metric} {self.fix_value:.4g} with the fix vs {self.bad_value:.4g} "
                       "at the bad commit")
        if self.new_failures:
            out.append(f"tasks that always pass at good now always fail: {', '.join(self.new_failures)}")
        return out


def _mean(runs: list[TaskRun], metric: str) -> float | None:
    values = [v for r in runs if (v := METRICS[metric](r)) is not None]
    return statistics.fmean(values) if values else None


def gates(good: list[TaskRun], bad: list[TaskRun], fix: list[TaskRun], metric: str, tolerance: float,
          z: float = 1.96) -> Gates:
    fix_ci, good_ci = wilson(sum(r.passed for r in fix), len(fix), z), wilson(sum(r.passed for r in good), len(good), z)
    fix_value = bad_value = None
    gain = None
    if metric in METRICS:
        fix_value, bad_value = _mean(fix, metric), _mean(bad, metric)
        if fix_value is not None and bad_value is not None:
            gain = fix_value <= bad_value * (1 + tolerance)

    def by_task(runs: list[TaskRun]) -> dict[str, list[bool]]:
        out: dict[str, list[bool]] = {}
        for r in runs:
            out.setdefault(r.task_id, []).append(r.passed)
        return out

    g, f = by_task(good), by_task(fix)
    new_failures = sorted(t for t, v in g.items() if all(v) and t in f and not any(f[t]))
    return Gates((sum(r.passed for r in fix), len(fix)), (sum(r.passed for r in good), len(good)), fix_ci, good_ci,
                 fix_ci[1] >= good_ci[0], metric, fix_value, bad_value, gain, new_failures)


# prompt ----------------------------------------------------------------------------------------
def fix_prompt(intent: str, hunks: list[Hunk], evidence: str, files: dict[str, str], feedback: list[str]) -> str:
    parts = ["## Why the commit was made\n", intent.strip()[:4000] or "(unknown)",
             "\n\n## The commit's hunks that caused the failures (reverting them restores the behaviour)\n"]
    parts += [f"\n### {h.where}\n```diff\n{h.body}```\n" for h in hunks]
    parts += ["\n## Failing tasks\n", evidence, "\n## Files you may change, as they are now\n"]
    for name, text in files.items():
        shown = text if len(text) <= MAX_FILE_CHARS else text[:MAX_FILE_CHARS] + "\n… (truncated)\n"
        parts.append(f"\n### {name}\n```\n{shown}```\n")
    if feedback:
        parts.append("\n## Your previous attempts failed\n" + "".join(f"- {line}\n" for line in feedback))
    return "".join(parts)


# a localised run -------------------------------------------------------------------------------
@dataclass
class Attempt:
    n: int
    proposal: dict | None = None
    patch: str | None = None
    error: str | None = None  # model failure or an edit that doesn't apply
    gates: dict | None = None
    failures: list[str] = field(default_factory=list)  # gate failures, fed back to the next attempt
    verified: bool = False


@dataclass
class FixResult:
    status: str  # "verified_fix", "verified_revert", "unverified" or "incomplete"
    attempts: list[Attempt]
    patch: str | None = None
    patch_reverse: bool = False  # True for the fallback: the responsible hunks, to apply with `git apply -R`
    metric: str = "none"
    note: str = ""


def fix_run(ledger: Ledger, run_id: str, log: Log = print, workers: int = 4, attempts: int = 2,
            tolerance: float = 0.10, budget_usd: float = 2.00) -> FixResult:
    with finished.workflow(ledger, run_id, "culprit_fix", attempts=attempts, tolerance=tolerance) as sp:
        ctx = finished.load(ledger, run_id, log, workers, budget_usd)
        result = _fix(ctx, attempts, tolerance)
        sp.output({"status": result.status, "metric": result.metric, "note": result.note})
    ledger.put_artifact(run_id, "fix", json.dumps({**asdict(result), "commit": ctx.bad}))
    log(f"fix: {result.status}" + (f" ({result.note})" if result.note else ""))
    return result


def _fix(ctx: RunContext, attempts: int, tolerance: float) -> FixResult:
    record = json.loads(ctx.ledger.get_artifact(ctx.run_id, "localisation") or "null")
    if not record or record.get("commit") != ctx.culprit or record["status"] not in LOCALISED:
        raise finished.StageError(f"run {ctx.run_id} has no usable localisation; run `culprit localise {ctx.run_id}`")
    by_id = {h.id: h for h in culprit_hunks(ctx)}
    responsible = [by_id[h["id"]] for h in record["hunks"]] if record["status"] != "whole_commit" else list(by_id.values())
    allowed = {h.file for h in responsible}
    present = set(gitops.git(ctx.orch.repo, "ls-tree", "-r", "--name-only", ctx.bad, "--", *allowed).split())
    files = {f: gitops.git(ctx.orch.repo, "show", f"{ctx.bad}:{f}") for f in sorted(allowed & present)}
    recorded = [Attempt(**a) for a in json.loads(ctx.ledger.get_artifact(ctx.run_id, "fix_attempts") or "[]")]
    done: list[Attempt] = []
    metric = "none"
    try:
        good, bad = _verify_runs(ctx, ctx.good, "baseline"), _verify_runs(ctx, ctx.bad, "baseline")
        for n in range(1, attempts + 1):
            attempt = recorded[n - 1] if n <= len(recorded) else _propose(ctx, n, responsible, files, allowed, done)
            done.append(attempt)
            ctx.ledger.put_artifact(ctx.run_id, "fix_attempts", json.dumps([asdict(a) for a in done]))
            if attempt.proposal is not None:
                metric = attempt.proposal["intended_gain"]
            if attempt.patch is None:
                continue
            g = _verify(ctx, f"fix:{n}", attempt.patch, good, bad, metric, tolerance)
            if g is None:
                attempt.failures = ["the patch does not apply or install at the bad head"]
            else:
                attempt.gates, attempt.failures, attempt.verified = asdict(g), g.failures(), g.verified
            ctx.ledger.put_artifact(ctx.run_id, "fix_attempts", json.dumps([asdict(a) for a in done]))
            if attempt.verified:
                return FixResult("verified_fix", done, patch=attempt.patch, metric=metric)
        revert = patch_for(responsible)
        g = _verify(ctx, "fix:revert", revert, good, bad, metric, tolerance, reverse=True)
        if g is not None and g.verified:
            return FixResult("verified_revert", done, patch=revert, patch_reverse=True, metric=metric,
                             note="no attempt passed every gate; the responsible hunks' revert did")
        return FixResult("unverified", done, metric=metric, note="neither a fix nor the revert passed every gate"
                         if g else "the revert does not apply or install at the bad head")
    except (BudgetExceeded, InfraError) as exc:
        return FixResult("incomplete", done, metric=metric, note=f"{type(exc).__name__}: {exc}")


def _heldout(ctx: RunContext) -> list[str]:
    assert ctx.orch.pinned is not None
    directory = ctx.orch.pinned.path / "heldout"
    return discover_tasks(directory) if directory.is_dir() else []


def _verify_runs(ctx: RunContext, sha: str, kind: str) -> list[TaskRun]:
    """Full suite × k (the recorded baseline) plus held-out tasks × k (run once, then recorded)."""
    cfg = ctx.orch.cfg
    runs = list(ctx.ledger.task_runs(ctx.ledger.get_step(ctx.run_id, kind, sha)["step_id"]).values())
    heldout = _heldout(ctx)
    if heldout:
        runs += ctx.orch.evaluate(ctx.run_id, "verify:heldout", sha, heldout, range(cfg.k)).runs
    return runs


def _verify(ctx: RunContext, label: str, patch: str, good: list[TaskRun], bad: list[TaskRun], metric: str,
            tolerance: float, reverse: bool = False) -> Gates | None:
    """Gates for the bad head with `patch` applied; None when it doesn't apply."""
    cfg = ctx.orch.cfg
    tasks = list(cfg.task_ids) + _heldout(ctx)
    with tracing.span("verify_fix", "TOOL", commit_sha=ctx.bad, input={"label": label, "metric": metric}) as sp:
        variant = finished.Prepared(ctx, label, finished.apply_patch(patch, reverse))
        try:
            result = variant.evaluate(ctx.run_id, label, ctx.bad, tasks, range(cfg.k))
        except finished.PrepareError as exc:
            ctx.orch.log(f"  {label}: patch does not apply at the bad head ({exc})")
            sp.output({"applies": False})
            return None
        if result.skipped:
            sp.output({"installs": False})
            return None
        g = gates(good, bad, result.runs, metric, tolerance, cfg.z)
        sp.output(asdict(g) | {"verified": g.verified})
    ctx.orch.log(f"  {label}: {g.fix[0]}/{g.fix[1]} CI [{g.fix_ci[0]:.2f}, {g.fix_ci[1]:.2f}] vs good "
                 f"[{g.good_ci[0]:.2f}, {g.good_ci[1]:.2f}]; {metric} {_fmt(g.fix_value)} vs bad {_fmt(g.bad_value)}; "
                 + ("VERIFIED" if g.verified else "FAILED: " + "; ".join(g.failures())))
    return g


def _fmt(value: float | None) -> str:
    return "–" if value is None else f"{value:.4g}"


def _propose(ctx: RunContext, n: int, responsible: list[Hunk], files: dict[str, str], allowed: set[str],
             previous: list[Attempt]) -> Attempt:
    feedback = [f"attempt {a.n}: {line}" for a in previous for line in ([a.error] if a.error else a.failures)]
    prompt = fix_prompt(ctx.ledger.get_artifact(ctx.run_id, "intent") or "", responsible, evidence_text(ctx.evidence()),
                        files, feedback)
    with tracing.span("fix_propose", "AGENT", commit_sha=ctx.bad, input={"attempt": n}) as sp:
        try:
            reply = llm.structured(SYSTEM, prompt, FixProposal)
        except llm.LLMError as exc:
            sp.output({"error": str(exc)})
            ctx.orch.log(f"  fix attempt {n}: no proposal ({exc})")
            return Attempt(n, error=f"no proposal: {exc}")
        ctx.record_usage("fix_propose", reply)
        proposal = reply.value
        try:
            patch = edits_to_patch(files, proposal.edits, allowed)
        except ValueError as exc:
            sp.output({"error": str(exc)})
            ctx.orch.log(f"  fix attempt {n}: {exc}")
            return Attempt(n, proposal.model_dump(), error=str(exc))
        sp.output({"intended_gain": proposal.intended_gain, "edits": len(proposal.edits)})
    ctx.orch.log(f"  fix attempt {n}: {len(proposal.edits)} edit(s), intended gain {proposal.intended_gain}")
    return Attempt(n, proposal.model_dump(), patch)
