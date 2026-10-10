# Strength checks: is each planted bug visible to the suite?

`bench/ground_truth.json` → `visible` comes only from this file: a measurement with its own victim runs, never from a Culprit run's baselines. Otherwise Culprit would grade itself.

## GLM 5.3 (`z-ai/glm-5.3` via OpenRouter)

### hist/b: hero check (6 harder tasks × seeds 0–2)

| Ref | Passed | Cost |
|---|---|---|
| `good-v1.0` | 18/18 | $0.055 |
| `397c427` (planted commit) | 0/18 | $0.078 |

**Visible.** The same result was measured earlier on Claude Sonnet 5.5 (see `hackathon.md`).

### hist/a, hist/d, hist/e: full-suite check

Full pinned suite (RefundDesk `main` `ba86ed0`, 26 tasks) × seeds **3–5**, so it shares no runs with Culprit's baselines (seeds 0–2). That's 312 runs, $0.711, 0 errors.

| Ref | Passed | 95% Wilson | One-sided Fisher p vs good |
|---|---|---|---|
| `good-v1.0` | 78/78 | [0.953, 1.000] | – |
| `origin/hist/a` head `6a2f05a` | 78/78 | [0.953, 1.000] | 1.00 |
| `origin/hist/d` head `819d692` | 78/78 | [0.953, 1.000] | 1.00 |
| `origin/hist/e` head `255f40c` | 78/78 | [0.953, 1.000] | 1.00 |

**Invisible.** Not a single task failed on any bad head. Why, from the code:
- **a:** the `order_id` → `id` rename is consistent across the tool schema, agent, checker and tests, so the model sends `id` and nothing breaks.
- **d:** the shortened prompt kept the over-$500 rule, and the code guard `_policy_block` blocks refunds over $500 regardless.
- **e:** the default-filling code only runs when the model omits a required argument, and GLM never did.

Reproduce: `uv run python scripts/strength_check.py ../piedpiper-neathacks-refunddesk good-v1.0,origin/hist/a,origin/hist/d,origin/hist/e ALL 3-5`. Per-run results (task, seed, pass, cost, error) are in `evidence/strength-check-glm.jsonl`. Victim traces are tagged `culprit_run_id = strength-check`.

### hist/c, hist/f

Not measured separately. Culprit found both (see `evidence/RUNS.md`), so their scores don't depend on a visibility flag.

## Claude Sonnet 5.5

Only `hist/b` is measured (visible). The rest are not measured.
