# cfo.ai inputs: Culprit unit economics and pricing hypotheses

Written 2026-10-10. This file gathers the numbers to type into cfo.ai by hand. Every figure is
marked **measured** (from a run's ledger or the build log), **projected** (derived from measured
numbers with a stated assumption) or **assumption**. Pricing scenarios A, B and C are
**hypotheses**: no customer has seen or validated any of them.

To refresh the measured inputs from the ledger:

```bash
uv run culprit export-costs --format csv --out business/runs.csv   # per run: cost, victim runs, wall time
```

## 1. Measured

| Input | Value | Source |
|---|---|---|
| Real bisect, `hist/b`, GLM 5.3 victim (v1) | 240 victim runs, **$0.60**, 12.5 min | run `ff50e3620fdd` (hackathon.md) |
| … of which baseline / bisect | 156 / 84 runs | same run |
| Cost per victim run, GLM 5.3 | $0.0025 | $0.60 / 240 |
| Cost per victim run, Claude Sonnet 5.5 | $0.0163 | RefundDesk baseline, 78 runs for $1.27, at $2/$10 per MTok |
| Culprit's own LLM cost per bisect | $0 | no Culprit LLM stage runs in `culprit run` yet |
| v1 → v2 victim runs per bisect, fixture | −16% (staging alone), −34% (good end reused), −47% (both ends reused) | `evidence/v2-efficiency-fixture.md` |

## 2. Projected (cost of goods per bisect)

The v2 run counts are a projection for `hist/b` (see `evidence/v2-efficiency-fixture.md`): 164 runs
with a staged baseline, 124 when the good end is reused. Compute is an **assumption** of $0.04 per
bisect: one 4-vCPU runner at about $0.17/hour for about 12.5 minutes.

| Victim model | v1 (240 runs) | v2 (164 runs) | v2 + good reused (124 runs) |
|---|---:|---:|---:|
| Claude Sonnet 5.5 | $3.95 | $2.71 | $2.06 |
| GLM 5.3 | $0.64 | $0.45 | $0.35 |

These include the $0.04 compute. They exclude fixed costs (hosting, neatlogs plan, support), which
cfo.ai should take as separate monthly lines; we have no measured values for them.

## 3. Pricing scenarios (hypotheses)

Bisects per repo per month is unknown. The tables use 10 and 30 as **assumptions**.

### A. Flat subscription per repo, Culprit pays the model

- Starter: **$49/repo/month**, 10 bisects included.
- Team: **$199/repo/month**, 30 bisects included.

| Plan | Model | COGS / month | Gross margin |
|---|---|---:|---:|
| Starter (10) | Sonnet, v1 | $39.48 | 19% |
| Starter (10) | Sonnet, v2 | $27.10 | 45% |
| Starter (10) | GLM, v2 | $4.50 | 91% |
| Team (30) | Sonnet, v1 | $118.43 | 40% |
| Team (30) | Sonnet, v2 | $81.31 | 59% |
| Team (30) | GLM, v2 | $13.50 | 93% |

Risk: margin depends on the customer's victim model and on usage. A cap on included bisects is needed.

### B. Bring your own key, plus a platform fee

The customer's own model key pays for victim runs (about $2.67 per bisect on Sonnet 5.5, v2). Culprit charges
**$99/repo/month**.

| Bisects / month | Culprit COGS (compute only) | Gross margin |
|---|---:|---:|
| 10 | $0.40 | 99.6% |
| 30 | $1.20 | 98.8% |
| 100 | $4.00 | 96.0% |

Risk: there's no model-cost exposure, but the customer sees two bills. v2's efficiency lowers *their*
bill, not ours.

### C. Metered per bisect, Culprit pays the model

Charge **$5 per completed bisect**. A run that ends as `no_regression` or `budget_exceeded` costs less,
and charging for it is an open question.

| Model / version | COGS per bisect | Gross margin at $5 |
|---|---:|---:|
| Sonnet 5.5, v1 | $3.95 | 21% |
| Sonnet 5.5, v2 | $2.71 | 46% |
| GLM 5.3, v1 | $0.64 | 87% |
| GLM 5.3, v2 | $0.45 | 91% |

This is the scenario where v2's efficiency matters most: on Sonnet it roughly doubles the margin
(21% → 46%).

## 4. Still to measure

- A real v2 run on `hist/b`, to replace the projected 164 runs with a measured number.
- The other five branches (`hist/a`, `c`–`f`), to get an average bisect cost rather than one run.
- Runs per bisect with Culprit's own LLM stages (localiser, fixer, verifier) once they're built.
- Fixed monthly costs and the expected bisects per repo per month. Both are needed before cfo.ai's
  runway and break-even figures mean anything.
