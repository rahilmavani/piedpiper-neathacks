"""Eval blind-spot audit: `culprit audit --ref <ref>`. "Which realistic regressions would our evals miss?"

Mutation testing for agents. Culprit makes realistic, plausible-looking changes to the agent at `ref`
(mutants), each in its own throwaway worktree, never committed anywhere, and runs the eval suite on
each. A mutant is **caught** when the suite passes significantly less than at the unchanged ref
(one-sided Fisher p < alpha) and **missed** otherwise. The mutation score is caught / valid mutants;
every missed mutant comes with an idea for an eval task that would catch it.

Mutants come from:
- `--operators`: a catalogue of regression patterns (below). For each, one structured model call
  reads the agent's source and returns exact search-and-replace edits (the Fixer's safe edit format),
  plus a one-line summary and a task idea, or says the pattern doesn't apply.
- `--patches DIR`: your own `*.patch` files (deterministic, no model).

Proposals are stored in the run before anything is evaluated, so a rerun with `--run-id` resumes
without asking the model again. A mutant that doesn't apply or no longer installs is reported
`invalid` and left out of the score.
"""

from __future__ import annotations

import json
import subprocess
import fnmatch
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pydantic import BaseModel

from culprit import llm, reuse, tracing
from culprit.config import Config
from culprit.finished import PrepareError, apply_patch
from culprit.fix import Edit, edits_to_patch
from culprit.ledger import Ledger, TaskRun
from culprit.orchestrator import BudgetExceeded, InfraError, Log
from culprit.standalone import Patched, Standalone, open_run, workflow
from culprit.stats import fisher_one_sided

ARTIFACT_MUTANTS = "audit_mutants"
ARTIFACT_RESULT = "audit"
MAX_FILE_CHARS = 20000
MAX_SOURCE_CHARS = 60000
# The eval harness must never be mutated: a change to the grader is not an agent regression. Only offered
# files can be edited, so excluding these makes it impossible, not just discouraged.
DEFAULT_EXCLUDE = ("*eval.py", "*checks.py", "*tasks.py", "*suite.py", "*grader*.py", "*judge*.py")


@dataclass(frozen=True)
class Operator:
    name: str
    title: str
    instruction: str


# Regression patterns seen in real agent codebases. Each is a change a developer (or a coding agent)
# might make on purpose for a plausible reason, which quietly removes a behaviour the agent relies on.
OPERATORS = [
    Operator("drop_result_validation", "Drop tool-result validation",
             "Remove the step that checks or validates a tool's result before the agent acts on it, so failed or "
             "malformed results go straight back to the model. Plausible reason: it adds latency."),
    Operator("disable_retries", "Disable retries",
             "Stop retrying failed or timed-out tool calls: the first failure becomes final. Plausible reason: "
             "retries add latency."),
    Operator("shrink_history", "Shrink the conversation history",
             "Reduce how much earlier conversation the model sees on each call to the last 2-4 messages. Plausible "
             "reason: token cost."),
    Operator("drop_prompt_rule", "Drop a business rule from the prompt",
             "Delete the single most consequential business or safety rule from the system prompt, in a cleanup that "
             "shortens the prompt. Plausible reason: the prompt is too long."),
    Operator("remove_code_guard", "Remove a code-level guard",
             "Remove a check in code that blocks a disallowed or unsafe action (for example a limit or a precondition "
             "enforced before a tool runs). Plausible reason: the prompt already says it."),
    Operator("lenient_tool_args", "Accept malformed tool calls",
             "Make tool-call argument parsing lenient: fill missing required arguments with defaults instead of "
             "rejecting the call. Plausible reason: fewer rejected calls."),
    Operator("half_renamed_param", "Half-done parameter rename",
             "Rename one tool parameter in the tool's schema or description only, leaving the code that reads it "
             "unchanged, as an incomplete refactor would. Plausible reason: naming consistency."),
    Operator("vague_tool_description", "Vague tool description",
             "Rewrite one tool's description so it no longer says when or how to use it (keep the name and "
             "parameters). Plausible reason: simplify the tool list."),
]
BY_NAME = {o.name: o for o in OPERATORS}


class MutationProposal(BaseModel):
    applicable: bool
    summary: str  # one line: what was changed
    edits: list[Edit]
    task_idea: str  # an eval task that would catch this change


SYSTEM = (
    "You are a mutation-testing tool for LLM agents. Introduce ONE realistic regression into the agent's code, "
    "following the regression pattern you are given: the smallest change a developer might plausibly make on "
    "purpose, which keeps the code importable and running but quietly removes a behaviour. Do not touch tests or "
    "evaluation files. Each edit replaces one exact snippet `old`, which must occur exactly once in that file as "
    "shown, with `new`. If the pattern does not apply to this code, set applicable to false and edits to []. "
    "Also give a one-line summary of the change and an idea for an evaluation task that would catch it."
)


@dataclass
class Mutant:
    name: str
    source: str  # "operator" or "patch"
    title: str = ""
    summary: str = ""
    patch: str | None = None
    task_idea: str = ""
    error: str | None = None  # why there is no usable patch (not applicable, bad edits, model failure)


@dataclass
class MutantResult:
    name: str
    title: str
    summary: str
    verdict: str  # caught, missed, invalid
    passes: tuple[int, int] = (0, 0)
    p_value: float | None = None
    caught_by: list[str] = field(default_factory=list)  # tasks whose pass rate dropped, most first
    task_idea: str = ""
    note: str = ""


@dataclass
class AuditResult:
    status: str  # audited, incomplete
    run_id: str
    sha: str
    baseline: tuple[int, int]
    mutants: list[MutantResult]
    note: str = ""

    @property
    def valid(self) -> list[MutantResult]:
        return [m for m in self.mutants if m.verdict in ("caught", "missed")]

    @property
    def score(self) -> tuple[int, int]:
        return sum(m.verdict == "caught" for m in self.valid), len(self.valid)


# source given to the model ----------------------------------------------------------------------
def source_files(st: Standalone, exclude: tuple[str, ...] = DEFAULT_EXCLUDE) -> dict[str, str]:
    """The agent's own Python source at the ref: not tests, the suite, tooling or the eval harness; capped.

    The eval module itself (e.g. `refunddesk.eval`) is always excluded, whatever `exclude` says.
    """
    harness = st.orch.cfg.eval_module.replace(".", "/") + ".py"
    out = subprocess.run(["git", "-C", str(st.orch.repo), "ls-tree", "-r", "--name-only", st.sha],
                         capture_output=True, text=True, check=True).stdout.split()
    skip = ("tests/", "test/", "scripts/", "docs/", f"{st.orch.cfg.suite_target}/", ".")
    names = [n for n in out if n.endswith(".py") and not n.startswith(skip) and "/test_" not in n
             and not n.split("/")[-1].startswith("test_") and n.split("/")[-1] != "conftest.py"
             and not n.endswith(harness) and not any(fnmatch.fnmatch(n, pat) for pat in exclude)]
    files: dict[str, str] = {}
    for name in names:
        text = subprocess.run(["git", "-C", str(st.orch.repo), "show", f"{st.sha}:{name}"],
                              capture_output=True, text=True, check=True).stdout
        if text.strip():
            files[name] = text
    chosen, total = {}, 0
    for name in sorted(files, key=lambda n: -len(files[n])):
        if total + min(len(files[name]), MAX_FILE_CHARS) > MAX_SOURCE_CHARS:
            continue
        chosen[name] = files[name]
        total += min(len(files[name]), MAX_FILE_CHARS)
    return dict(sorted(chosen.items()))


def mutation_prompt(op: Operator, files: dict[str, str]) -> str:
    parts = [f"## Regression pattern: {op.title}\n\n{op.instruction}\n\n## The agent's source\n"]
    for name, text in files.items():
        shown = text if len(text) <= MAX_FILE_CHARS else text[:MAX_FILE_CHARS] + "\n… (truncated)\n"
        parts.append(f"\n### {name}\n```python\n{shown}```\n")
    return "".join(parts)


def propose(st: Standalone, op: Operator, files: dict[str, str]) -> Mutant:
    with tracing.span(f"propose_mutant:{op.name}", "AGENT", commit_sha=st.sha, input={"operator": op.name}) as sp:
        try:
            reply = llm.structured(SYSTEM, mutation_prompt(op, files), MutationProposal)
        except llm.LLMError as exc:
            sp.output({"error": str(exc)})
            return Mutant(op.name, "operator", op.title, error=f"model: {exc}")
        for u in reply.usage:
            st.ledger.record_llm_call(st.run_id, None, f"audit_propose:{op.name}", u.model, u.tokens_in,
                                      u.tokens_out, u.cost_usd, tracing.current_trace_id())
        p = reply.value
        if not p.applicable or not p.edits:
            sp.output({"applicable": False, "summary": p.summary})
            return Mutant(op.name, "operator", op.title, p.summary, task_idea=p.task_idea,
                          error="not applicable to this code")
        try:
            patch = edits_to_patch(files, p.edits, set(files))
        except ValueError as exc:
            sp.output({"error": str(exc)})
            return Mutant(op.name, "operator", op.title, p.summary, task_idea=p.task_idea, error=f"edits: {exc}")
        sp.output({"summary": p.summary, "patch_lines": patch.count("\n")})
        return Mutant(op.name, "operator", op.title, p.summary, patch, p.task_idea)


def from_patches(directory: Path) -> list[Mutant]:
    patches = sorted(directory.glob("*.patch"))
    if not patches:
        raise AuditError(f"no *.patch files in {directory}")
    return [Mutant(p.stem, "patch", p.stem.replace("_", " "), f"patch {p.name}", p.read_text()) for p in patches]


class AuditError(RuntimeError):
    pass


# evaluation ---------------------------------------------------------------------------------------
def by_task(runs: list[TaskRun]) -> dict[str, tuple[int, int]]:
    out: dict[str, list[bool]] = {}
    for r in runs:
        out.setdefault(r.task_id, []).append(r.passed)
    return {t: (sum(v), len(v)) for t, v in out.items()}


def judge(base: list[TaskRun], mutant: list[TaskRun], alpha: float) -> tuple[str, float, list[str]]:
    bp, bn, mp, mn = sum(r.passed for r in base), len(base), sum(r.passed for r in mutant), len(mutant)
    p = fisher_one_sided(bp, bn, mp, mn)
    b, m = by_task(base), by_task(mutant)
    drops = sorted(((b[t][0] / b[t][1] - m[t][0] / m[t][1], t) for t in b.keys() & m.keys()), reverse=True)
    return ("caught" if p < alpha else "missed"), p, [t for d, t in drops if d > 0]


def audit_run(ledger: Ledger, cfg: Config, ref: str, log: Log = print, workers: int = 4,
              operators: list[str] | None = None, patches: Path | None = None, run_id: str | None = None,
              exclude: tuple[str, ...] = DEFAULT_EXCLUDE) -> AuditResult:
    if run_id is None and not operators and patches is None:
        operators = [o.name for o in OPERATORS]
    unknown = [o for o in operators or [] if o not in BY_NAME]
    if unknown:
        raise AuditError(f"unknown operators {unknown}; choose from {', '.join(BY_NAME)}")
    st = open_run(ledger, cfg, ref, log, workers, run_id=run_id)
    cfg = st.orch.cfg
    log(f"run {st.run_id}: blind-spot audit of {st.sha[:10]}, {len(st.tasks)} tasks × {cfg.k}")
    with workflow(st, "culprit_audit", ref=ref, operators=operators, patches=str(patches) if patches else None) as sp:
        try:
            result = _audit(st, cfg, operators or [], patches, exclude)
        except (BudgetExceeded, InfraError) as exc:
            result = AuditResult("incomplete", st.run_id, st.sha, (0, 0), [], note=str(exc))
        sp.output({"status": result.status, "score": list(result.score)})
    ledger.put_artifact(st.run_id, ARTIFACT_RESULT, json.dumps(asdict(result)))
    caught, valid = result.score
    summary = (f"Audit incomplete: {result.note}" if result.status == "incomplete" else
               f"Blind-spot audit of {st.sha[:10]}: the suite caught {caught} of {valid} valid mutants"
               + (f"; it misses {valid - caught}" if valid - caught else ""))
    ledger.finish_run(st.run_id, result.status, None, None, summary)
    log(summary)
    return result


def _mutants(st: Standalone, operators: list[str], patches: Path | None, exclude: tuple[str, ...]) -> list[Mutant]:
    """Stored proposals on resume; otherwise new ones, stored before anything is evaluated."""
    stored = st.ledger.get_artifact(st.run_id, ARTIFACT_MUTANTS)
    if stored:
        return [Mutant(**m) for m in json.loads(stored)]
    mutants: list[Mutant] = from_patches(patches) if patches is not None else []
    if operators:
        files = source_files(st, exclude)
        if not files:
            raise AuditError(f"no agent source files found at {st.sha[:10]}")
        st.orch.log(f"  proposing {len(operators)} mutants from {len(files)} source files: {', '.join(files)}")
        mutants += [propose(st, BY_NAME[name], files) for name in operators]
    st.ledger.put_artifact(st.run_id, ARTIFACT_MUTANTS, json.dumps([asdict(m) for m in mutants]))
    return mutants


def _audit(st: Standalone, cfg: Config, operators: list[str], patches: Path | None,
           exclude: tuple[str, ...]) -> AuditResult:
    reps = range(cfg.k)
    items = [(t, r) for t in st.tasks for r in reps]
    reuse.import_runs(st.ledger, cfg, st.run_id, "baseline", st.sha, items)  # matching earlier baselines
    base = st.orch.evaluate(st.run_id, "baseline", st.sha, st.tasks, reps)
    if base.skipped:
        raise AuditError(f"{st.sha[:10]} doesn't install, so there is nothing to mutate")
    st.orch.log(f"  baseline {base.passes}/{base.n}")
    results: list[MutantResult] = []
    for m in _mutants(st, operators, patches, exclude):
        if m.patch is None:
            results.append(MutantResult(m.name, m.title, m.summary, "invalid", task_idea=m.task_idea, note=m.error or ""))
            st.orch.log(f"  {m.name}: invalid ({m.error})")
            continue
        try:
            mutated = Patched(st.orch, f"mutant:{m.name}", apply_patch(m.patch)).evaluate(
                st.run_id, f"mutant:{m.name}", st.sha, st.tasks, reps)
        except PrepareError as exc:
            results.append(MutantResult(m.name, m.title, m.summary, "invalid", task_idea=m.task_idea,
                                        note=f"patch doesn't apply: {exc}"))
            st.orch.log(f"  {m.name}: invalid (patch doesn't apply)")
            continue
        if mutated.skipped:
            results.append(MutantResult(m.name, m.title, m.summary, "invalid", task_idea=m.task_idea,
                                        note="the mutated agent doesn't install or import"))
            st.orch.log(f"  {m.name}: invalid (doesn't install)")
            continue
        verdict, p, dropped = judge(base.runs, mutated.runs, cfg.gate_alpha)
        results.append(MutantResult(m.name, m.title, m.summary, verdict, (mutated.passes, mutated.n), p, dropped,
                                    m.task_idea))
        st.orch.log(f"  {m.name}: {mutated.passes}/{mutated.n}, p = {p:.4f} → {verdict.upper()}"
                    + (f" (by {', '.join(dropped[:3])})" if verdict == "caught" else ""))
    return AuditResult("audited", st.run_id, st.sha, (base.passes, base.n), results)


# report -------------------------------------------------------------------------------------------
def to_markdown(r: AuditResult) -> str:
    caught, valid = r.score
    lines = [f"# Eval blind-spot audit: `{r.sha[:10]}` (run `{r.run_id}`)", ""]
    if r.status == "incomplete":
        return "\n".join(lines + [f"**Incomplete:** {r.note}", ""])
    lines += [f"**Mutation score: {caught}/{valid}** valid mutants caught by the suite "
              f"(baseline {r.baseline[0]}/{r.baseline[1]}). A mutant is caught when the suite passes "
              "significantly less (one-sided Fisher p < 0.05).", "",
              "| Mutant | Change | Verdict | Passes | p | Caught by | Task that would catch it |",
              "|---|---|---|---:|---:|---|---|"]
    order = {"missed": 0, "caught": 1, "invalid": 2}
    for m in sorted(r.mutants, key=lambda m: order[m.verdict]):
        lines.append(
            f"| {m.title or m.name} | {m.summary or '–'} | **{m.verdict.upper()}** | "
            f"{f'{m.passes[0]}/{m.passes[1]}' if m.passes[1] else '–'} | "
            f"{f'{m.p_value:.3f}' if m.p_value is not None else '–'} | {', '.join(m.caught_by[:3]) or '–'} | "
            f"{(m.task_idea if m.verdict != 'caught' else '') or '–'} |")
    missed = [m for m in r.mutants if m.verdict == "missed"]
    if missed:
        lines += ["", "## Blind spots", ""]
        lines += [f"- **{m.title or m.name}**: {m.summary}. Add: {m.task_idea or 'a task that exercises this'}"
                  for m in missed]
    invalid = [m for m in r.mutants if m.verdict == "invalid"]
    if invalid:
        lines += ["", "Invalid mutants (not scored): " + "; ".join(f"{m.name} ({m.note})" for m in invalid)]
    return "\n".join(lines) + "\n"

