"""Strength check: pass rate of tasks at victim commits, using Culprit's own sandbox code.

Independent of Culprit's runs (pick seeds the runs didn't use). The victim model comes from the keys and
`VICTIM_MODEL`, like `culprit run` (Anthropic Sonnet 5.5, else OpenRouter GLM 5.3 or `VICTIM_MODEL`).

    uv run python scripts/strength_check.py <victim repo> <ref,ref,...> <task,task,...|ALL> <seeds, e.g. 3-5> \
        [suite ref, default main] [summary.json]

The first ref is the reference; each other ref gets a one-sided Fisher test against it. Victim runs that
fail for infrastructure reasons (rate limits, 5xx, timeouts, no JSON) are retried twice and, if they
still fail, left out of the pass rates and counted separately, as Culprit does.
"""
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from culprit import providers, sandbox, suite
from culprit.config import PROJECT_ROOT
from culprit.evalrunner import discover_tasks, infra_failure, run_task, victim_env
from culprit.gitops import resolve
from culprit.stats import fisher_one_sided, wilson

load_dotenv(PROJECT_ROOT / ".env")
repo = Path(sys.argv[1]).resolve()
refs = sys.argv[2].split(",")
tasks = sys.argv[3].split(",") if sys.argv[3] != "ALL" else None
lo, hi = map(int, sys.argv[4].split("-"))
seeds = range(lo, hi + 1)
suite_ref = sys.argv[5] if len(sys.argv) > 5 else "main"
summary_path = Path(sys.argv[6]) if len(sys.argv) > 6 else None

victim = providers.select("VICTIM_MODEL")
env = victim_env(repo, victim)
pinned = suite.pin(repo, "evals", suite_ref)
tasks = tasks or discover_tasks(pinned.path)
tag = "strength-" + victim.model.replace("/", "-")
print(f"model {victim.model} via {victim.name}; suite {pinned.sha[:12]} ({suite_ref}); {len(tasks)} tasks; "
      f"seeds {lo}-{hi}; tag {tag}", flush=True)


def one(wt: Path, sha: str, task: str, seed: int):
    for attempt in range(3):
        tr = run_task(wt, env, "refunddesk.eval", task, seed, run_id=tag, commit_sha=sha, timeout_s=300)
        kind = infra_failure(tr)
        if kind is None or kind == "fatal":
            return tr, kind
        time.sleep(5 * 4**attempt)
    return tr, "transient"


results, infra = defaultdict(list), defaultdict(list)
shas = {}
for ref in refs:
    sha = shas[ref] = resolve(repo, ref)
    wt = sandbox.add_worktree(repo, sha)
    suite.install_into(pinned, wt, "evals")
    inst = sandbox.install(wt, "refunddesk.eval", 600)
    assert inst.ok, inst.log[-800:]
    jobs = [(t, s) for t in tasks for s in seeds]
    with ThreadPoolExecutor(4) as pool:
        for (t, s), (tr, kind) in zip(jobs, pool.map(lambda j: one(wt, sha, j[0], j[1]), jobs)):
            (infra if kind else results)[ref].append(tr)
            print(json.dumps({"ref": ref, "task": t, "seed": s, "passed": tr.passed, "cost": tr.cost_usd,
                              "error": tr.error, "infra": kind}), flush=True)
            if kind == "fatal":
                raise SystemExit(f"fatal infrastructure error, stopping: {tr.error}")

print("== summary")
summary = {"model": victim.model, "provider": victim.name, "suite_ref": suite_ref, "suite_sha": pinned.sha,
           "seeds": [lo, hi], "tasks": len(tasks), "tag": tag, "refs": {}}
total = 0.0
reference = refs[0]
gp, gn = sum(r.passed for r in results[reference]), len(results[reference])
for ref in refs:
    trs = results[ref]
    passes, n = sum(r.passed for r in trs), len(trs)
    cost = sum(r.cost_usd or 0 for r in trs + infra[ref])
    total += cost
    low, high = wilson(passes, n) if n else (0.0, 1.0)
    failing = sorted({r.task_id for r in trs if not r.passed})
    row = {"sha": shas[ref], "passes": passes, "n": n, "wilson": [round(low, 4), round(high, 4)],
           "cost_usd": round(cost, 6), "infra_errors": len(infra[ref]), "failing_tasks": failing}
    if ref != reference:
        row["fisher_p_vs_reference"] = fisher_one_sided(gp, gn, passes, n)
    summary["refs"][ref] = row
    print(f"{ref}: {passes}/{n} CI [{low:.3f}, {high:.3f}]"
          + (f" Fisher p={row['fisher_p_vs_reference']:.4f}" if ref != reference else "")
          + f", ${cost:.4f}, infra {len(infra[ref])}, failing {failing}")
summary["total_cost_usd"] = round(total, 6)
print(f"total ${total:.4f}")
if summary_path:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
