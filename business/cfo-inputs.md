# cfo.ai inputs: Culprit unit economics and pricing hypotheses

Written 2026-10-10. This file gathers the numbers to type into cfo.ai by hand. Every figure is
marked **measured** (from a run's ledger or the build log), **projected** (derived from measured
numbers with a stated assumption) or **assumption**. Pricing scenarios A, B and C are
**hypotheses**: no customer has seen or validated any of them.

To refresh the measured inputs from the ledger:

```bash
uv run culprit export-costs --format csv --out business/runs.csv   # per run: cost, victim runs, wall time
```

## 1. Measured (real victim, 10 Oct; sources `evidence/RUNS.md`, `business/runs.csv`)

| Input | Value | Source |
|---|---|---|
| Bisect `hist/b`, GLM 5.3 victim, **v1** | 240 victim runs, **$0.60**, 12.5 min | run `ff50e3620fdd` |
| Bisect `hist/b`, GLM 5.3 victim, **v2** (staged) | **164 victim runs, $0.46**, 8 min | run `978624283c27` |
| All 6 scenarios, v1 → v2 | 1,140 → 588 victim runs, **$2.70 → $1.51** (avg $0.45 → $0.25 per bisect) | `evidence/bench-v1.md`, `bench-v2.md` |
| Localise (hunk) on `hist/b` | 84 victim runs + 3 model calls, **$0.20** | `business/runs.csv` |
| Fix + verify on `hist/b` | 132 victim runs + 2 model calls, **$0.33** | `business/runs.csv` |
| Full investigation on `hist/b` (bisect v1 + localise + fix) | 456 victim runs, **$1.13**, of which Culprit's own model calls $0.063 | `business/runs.csv` |
| Cost per victim run, GLM 5.3 | **$0.0024** ($2.6957 / 1,140) | `evidence/bench-v1.json` |
| Cost per victim run, Claude Sonnet 5.5 | $0.0163 | RefundDesk baseline, 78 runs for $1.27, at $2/$10 per MTok |
| Accuracy | 6/6 in both v1 and v2 | `culprit bench` |

## 2. Projected (cost of goods per bisect)

The v2 count for `hist/b` is now **measured** (164 runs, run `978624283c27`). The 124-run figure with
the good end reused is still a projection. Compute is an **assumption** of $0.04 per
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

- Baseline reuse on the real victim (the 124-run case). On our ledger it would copy v1's baselines, so it wasn't a fair test.
- Real usage: bisects per repo per month (the 10 and 30 above are assumptions).
