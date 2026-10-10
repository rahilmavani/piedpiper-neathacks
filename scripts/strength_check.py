"""Strength check: pass rate of tasks at victim commits on GLM 5.3, using Culprit's own sandbox code.

Independent of Culprit's runs (pick seeds the runs didn't use). Usage:
    uv run python scripts/strength_check.py <victim repo> <ref,ref,...> <task,task,...|ALL> <seed range, e.g. 3-5>
The first ref is the reference; each other ref gets a one-sided Fisher test against it.
"""
import json, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from culprit import sandbox, suite
from culprit.config import PROJECT_ROOT
from culprit.evalrunner import run_task, victim_env
from culprit.gitops import resolve
from culprit.providers import Provider

load_dotenv(PROJECT_ROOT / ".env")
repo = Path(sys.argv[1]).resolve()
refs = sys.argv[2].split(",")
tasks = sys.argv[3].split(",") if sys.argv[3] != "ALL" else None
lo, hi = map(int, sys.argv[4].split("-")); seeds = range(lo, hi + 1)
victim = Provider("openrouter", "z-ai/glm-5.3")
env = victim_env(repo, victim)
pinned = suite.pin(repo, "evals", "main")
from culprit.evalrunner import discover_tasks
tasks = tasks or discover_tasks(pinned.path)
print("suite", pinned.sha[:12], len(tasks), "tasks", flush=True)

results = defaultdict(list)
for ref in refs:
    sha = resolve(repo, ref)
    wt = sandbox.add_worktree(repo, sha)
    suite.install_into(pinned, wt, "evals")
    inst = sandbox.install(wt, "refunddesk.eval", 600)
    assert inst.ok, inst.log[-800:]
    jobs = [(t, s) for t in tasks for s in seeds]
    with ThreadPoolExecutor(4) as pool:
        for (t, s), tr in zip(jobs, pool.map(lambda j: run_task(wt, env, "refunddesk.eval", j[0], j[1],
                                run_id="strength-check", commit_sha=sha, timeout_s=300), jobs)):
            results[ref].append(tr)
            print(json.dumps({"ref": ref, "task": t, "seed": s, "passed": tr.passed, "cost": tr.cost_usd,
                              "error": tr.error}), flush=True)
print("== summary")
total = 0.0
for ref, trs in results.items():
    cost = sum(r.cost_usd or 0 for r in trs)
    total += cost
    print(f"{ref}: {sum(r.passed for r in trs)}/{len(trs)} passed, ${cost:.4f}, "
          f"errors={sum(1 for r in trs if r.error)}")
    by = defaultdict(list)
    for r in trs:
        by[r.task_id].append(r.passed)
    for t, v in sorted(by.items()):
        print(f"   {t}: {sum(v)}/{len(v)}")
print(f"total ${total:.4f}")
from culprit.stats import fisher_one_sided, wilson
g = results[refs[0]]
gp, gn = sum(r.passed for r in g), len(g)
print(f"== vs {refs[0]} {gp}/{gn}")
for ref in refs[1:]:
    b = results[ref]
    bp, bn = sum(r.passed for r in b), len(b)
    lo, hi = wilson(bp, bn)
    print(f"{ref}: {bp}/{bn} CI [{lo:.3f}, {hi:.3f}] Fisher p={fisher_one_sided(gp, gn, bp, bn):.4f} "
          f"failing tasks: {sorted({r.task_id for r in b if not r.passed})}")
