# Culprit business plan (cfo.ai)

Built in **cfo.ai** on 10 Oct 2026 from our measured unit costs (`cfo-unit-costs.csv`, `runs.csv`). There are two exports:

- [`cfo-ai-pricing-comparison.xlsx`](cfo-ai-pricing-comparison.xlsx): unit costs, the pricing plans, gross margin per customer, and break-even repos
- [`cfo-ai-cash-runway.xlsx`](cfo-ai-cash-runway.xlsx): a 25-month cash runway for one plan mix

## What's measured and what's assumed

| | Value | Kind |
|---|---|---|
| Cost per bisect (v2, GLM 5.3 victim) | **$0.252** | **measured**: 6 real runs, $1.5123 / 6 (`evidence/bench-v2.md`) |
| Localise / fix per investigation | $0.20 / $0.33 | **measured** (hero bug). Loaded, but not used in this model (stage rate 0) |
| Prices: A $49 or $199 per repo, B $99 per repo with the customer's own key, C $5 per bisect | | **hypothesis**: not shown to any customer |
| Fixed costs: 2 founders × $5,000 + $500 other = **$10,500/month** | | **assumption** |
| Card fees: 2.9% + $0.30 per invoice | | **assumption** (typical card processor rates) |
| Runway model: $100k starting cash; 5 new customers in month 1, +10% a month; 3% monthly churn; 50 bisects per customer; **100% plan B** | | **assumption** |

## Gross margin per customer (`Gross margin per customer` sheet)

| Plan | 10 bisects/mo | 50 bisects/mo | 200 bisects/mo |
|---|---:|---:|---:|
| A · $199/repo | 96% | 91% | 72% |
| A · $49/repo | 91% | 71% | **−6%** |
| B · own key + $99/repo | 97% | 97% | 97% |
| C · $5/bisect | 91% | 92% | 92% |

- **B** carries no model-cost risk: the customer's key pays for the agent runs, and only card fees come out of the $99.
- **A at $49** loses money for a heavy user (200 bisects).
- **C** scales with usage at about a 92% margin.

## Break-even (`Break-even paying repos` sheet)

Repos needed to cover $10,500 a month:

| Plan | 10 bisects/mo | 50 | 200 |
|---|---:|---:|---:|
| A · $199 | 56 | 59 | 74 |
| A · $49 | 235 | 303 | never (negative margin) |
| B · $99 | 110 | 110 | 110 |
| C · $5/bisect | 230 | 46 | 12 |

## Cash runway (`Monthly cash runway` sheet, all customers on plan B)

- Starting cash $100,000. The low point is **$33,977 in Sep 2027**.
- Cash flow turns positive in **Oct 2027**, at about 121 paying customers.
- By Sep 2028 the model reaches about 399 customers and $39.5k monthly revenue.

These are scenario outputs from the assumptions above, not forecasts.

## Why v2 matters to the business: a stress test (our arithmetic, not cfo.ai's)

Ari's chat wasn't available to us, so the stress test isn't in the cfo.ai model. We computed it ourselves with the same card fees:
- **Measured inputs:** victim runs per bisect, v1 190 vs v2 98 (`evidence/bench-v*.md`); Claude Sonnet 5.5 at $0.0163 per run.
- **Resulting cost per bisect on Sonnet:** v1 $3.10, v2 $1.60. That's about 6× the GLM cost.

| Plan (we pay the model) | Bisects/mo | v1 margin | v2 margin |
|---|---:|---:|---:|
| A · $199/repo | 10 | 81% | 89% |
| A · $199/repo | 50 | 19% | **57%** |
| A · $199/repo | 200 | −214% | **−64%** |
| C · $5/bisect | any | 35% | **65%** |

- **On an expensive victim model, v2 is what makes plan C viable:** its margin nearly doubles.
- **Plan A needs a bisect cap:** at 200 bisects a month it loses money even with v2.
- **Plan B is unaffected,** because the customer's key pays for the runs.

That points to **B as the default** and **C for customers who don't want to bring their own key.**
