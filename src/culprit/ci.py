"""CI regression gate: `culprit ci --base <ref> --head <ref>`, and the PR comment it posts.

On a pull request: measure the PR's head against its base (the regression gate). Clean → exit 0.
Regressed → bisect the PR's commits to the culprit, optionally localise the responsible hunk and
propose a verified fix, write a markdown comment for the PR, and exit 1 so the check fails. Anything
that stops the run (budget, infrastructure, error) → exit 2, so a flaky API never blames a commit.

`comment(ledger, run_id)` builds the comment from the ledger alone, so `culprit comment <run_id>`
renders it for any finished run at no cost. See `examples/github-action/culprit.yml`.
"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass

from culprit import gitops
from culprit.config import Config
from culprit.ledger import Ledger
from culprit.orchestrator import Log, Orchestrator

MAX_PATCH_CHARS = 6000
MAX_INTENT_CHARS = 700

EXIT_CLEAN, EXIT_REGRESSION, EXIT_STOPPED = 0, 1, 2
REGRESSION = {"found", "ambiguous"}
CLEAN = {"no_regression"}


@dataclass
class CiResult:
    run_id: str
    status: str
    exit_code: int
    comment: str


def exit_code(status: str) -> int:
    return EXIT_CLEAN if status in CLEAN else EXIT_REGRESSION if status in REGRESSION else EXIT_STOPPED


def ci_run(ledger: Ledger, cfg: Config, log: Log = print, workers: int = 4, localise: bool = True,
           fix: bool = False, localise_budget: float = 1.50, fix_budget: float = 2.00) -> CiResult:
    orch = Orchestrator(ledger, cfg, log=log, workers=workers)
    run_id = orch.start()
    log(f"run_id {run_id}")
    outcome = orch.run(run_id)
    if outcome.status == "found" and localise:
        from culprit import localise as loc

        loc.localise_run(ledger, run_id, log=log, workers=workers, budget_usd=localise_budget)
        located = ledger.get_artifact(run_id, "localisation")
        if fix and located and json.loads(located)["status"] in {"hunk", "pair", "single_hunk", "whole_commit"}:
            from culprit import fix as fx

            fx.fix_run(ledger, run_id, log=log, workers=workers, budget_usd=fix_budget)
    return CiResult(run_id, outcome.status, exit_code(outcome.status), comment(ledger, run_id))


def _baselines(ledger: Ledger, run_id: str, good: str, bad: str) -> dict[str, tuple[int, int]]:
    out: dict[str, list[int]] = {good: [0, 0], bad: [0, 0]}
    for step in ledger.steps(run_id):
        if step["kind"].startswith("baseline") and step["commit_sha"] in out:
            for r in ledger.task_runs(step["step_id"]).values():
                out[step["commit_sha"]][0] += r.passed
                out[step["commit_sha"]][1] += 1
    return {sha: (p, n) for sha, (p, n) in out.items()}


def _subject(repo: str, sha: str) -> str:
    try:

        return gitops.subject(Path(repo), sha)
    except Exception:  # noqa: BLE001 - a comment without a subject is still useful
        return ""


def comment(ledger: Ledger, run_id: str) -> str:
    """A pull-request comment for a finished run, from the ledger alone (no runs, no model calls)."""
    row = ledger.get_run(run_id)
    status, good, bad = row["status"], row["good_sha"] or "", row["bad_sha"] or ""
    cfg = json.loads(row["config_json"])
    base = _baselines(ledger, run_id, good, bad)
    (gp, gn), (bp, bn) = base.get(good, (0, 0)), base.get(bad, (0, 0))
    model = cfg.get("victim_model") or "the victim's own model"
    cost = ledger.run_cost(run_id)
    head = {"no_regression": "### ✅ Culprit: no significant regression",
            "found": "### ❌ Culprit: this PR regresses the agent",
            "ambiguous": "### ❌ Culprit: this PR regresses the agent (boundary partly hidden by skipped commits)",
            }.get(status, f"### ⚠️ Culprit couldn't finish ({status})")
    lines = [head, ""]
    if gn and bn:
        lines += [f"Eval suite on `{model}`: **base `{good[:7]}` {gp}/{gn}** → **head `{bad[:7]}` {bp}/{bn}**.", ""]
    if status == "found":
        sha = row["culprit_sha"]
        lines += [f"**Culprit commit:** `{sha[:10]}` {_subject(row['repo'], sha)}", ""]
        intent = ledger.get_artifact(run_id, "intent") or ""
        meta = json.loads(ledger.get_artifact(run_id, "intent_meta") or "{}")
        request = intent.split("Checkpoint context:")[0].removeprefix("Intent:").strip()
        if request and meta.get("source", "").startswith("entire"):
            shown = request if len(request) <= MAX_INTENT_CHARS else request[:MAX_INTENT_CHARS] + "…"
            lines += [f"**Why it was made** (Entire checkpoint `{meta.get('checkpoint_id', '?')}`):", "",
                      *[f"> {line}" for line in shown.splitlines()], ""]
        located = json.loads(ledger.get_artifact(run_id, "localisation") or "{}")
        if located.get("hunks"):
            lines += [f"**Responsible change** ({located['status']}):"]
            lines += [f"- `{h['where']}`: {h.get('reason', '')}" for h in located["hunks"]]
            lines += [""]
        fixed = json.loads(ledger.get_artifact(run_id, "fix") or "{}")
        if fixed.get("status") in ("verified_fix", "verified_revert") and fixed.get("patch"):
            kind = "a fix" if fixed["status"] == "verified_fix" else "reverting the responsible hunks"
            patch = fixed["patch"]
            shown = patch if len(patch) <= MAX_PATCH_CHARS else patch[:MAX_PATCH_CHARS] + "\n… (truncated)\n"
            lines += [f"**Verified:** {kind} restores the suite"
                      + (f" ({fixed['note']})" if fixed.get("note") else "") + ".", ""]
            if fixed.get("gain_note"):
                lines += [f"Note: {fixed['gain_note']}.", ""]
            lines += ["<details><summary>Proposed patch</summary>", "", "```diff", shown.rstrip(), "```", "",
                      "</details>", ""]
    elif row["summary"]:
        lines += [row["summary"], ""]
    lines += [f"<sub>Culprit run `{run_id}` · {cost and f'${cost:.2f}' or '$0'} · "
              f"`culprit report {run_id}` for the full timeline, Wilson intervals and traces</sub>"]
    return "\n".join(lines) + "\n"
