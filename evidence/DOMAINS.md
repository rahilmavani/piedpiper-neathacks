# Culprit on two more domains, two victim models

Does Culprit work beyond RefundDesk, and on a weak model as well as a strong one? On 11 Oct we ran it on two new victim agents built the same way. Each has a good version, six history branches with one planted regression each, and broken-install commits on two branches. Both were calibrated on GLM 5.3 and Llama 3.1 8B, so that some regressions are visible only on the weaker model.

- **OpsDesk** ([repo](https://github.com/ayushgml/opsdesk)): an incident-response agent (metrics, deploys, rollbacks, restarts, paging).
- **ClinicDesk** ([repo](https://github.com/ayushgml/clinicdesk)): a clinic front-desk agent (scheduling, red-flag escalation, identity checks, privacy).

The answer keys stay outside the victim repos. They were converted into `bench/opsdesk/` and `bench/clinicdesk/` by `scripts/import_answer_key.py`. "Visible" there is the calibration's own measurement on the public suite (one-sided Fisher p < 0.05 vs the good version), separate from Culprit's runs. Every number below comes from `evidence/bench-<domain>-<model>.md` and `.json`, with chart data in `evidence/domains.json`.

Setup: Culprit at `3afa407`; `culprit run --no-reuse` (staged baseline), k = 3, suite pinned at each repo's `main` (= `good-v1.0`), `--eval-module opsdesk.eval` / `clinicdesk.eval`, via OpenRouter. The two repos ran in parallel.

## Results

| Domain | Victim model | Correct | Missed | **Wrong culprit** | Victim runs | Cost |
|---|---|---:|---:|---:|---:|---:|
| OpsDesk | GLM 5.3 | **6/6** | 0 | **0** | 520 | $0.17 |
| OpsDesk | Llama 3.1 8B | **6/6** | 0 | **0** | 814 | $0.07 |
| ClinicDesk | GLM 5.3 | **6/6** | 0 | **0** | 512 | $0.53 |
| ClinicDesk | Llama 3.1 8B | 3/6 | 3 | **0** | 800 | $0.13 |
| **Total** | | **21/24** | 3 | **0** | 2,646 | **$0.90** |

**Across all 54 scored bisect runs so far, Culprit has never named a wrong commit: 51 correct, 3 missed, 0 wrong.** That covers RefundDesk v1 and v2 on GLM, RefundDesk on Qwen, DeepSeek and Gemini, and these two domains on two models (`evidence/bench-*.json`).

## Same commit, different verdict, both right

| Domain · branch | What the planted commit did | GLM 5.3 | Llama 3.1 8B |
|---|---|---|---|
| OpsDesk · b | Skips the policy guard before tool dispatch | no regression ✅ | **found `5a54888`** ✅ |
| OpsDesk · d | Coerces replica arguments instead of strict validation | no regression ✅ | **found `5559976`** ✅ |
| OpsDesk · e | Removes the pre-computed CPU/deploy facts | no regression ✅ | **found `afa3143`** ✅ |
| ClinicDesk · c | Shrinks the red-flag synonym detector to four literal terms | no regression ✅ | **found `c972a0a`** ✅ |

Each of these commits removes a safety net. GLM never makes the mistake the net catches, so for GLM the code change really is harmless, and Culprit says so. Llama does make the mistake, so the same change breaks it, and Culprit names the exact commit. With the same repo and the same commit, the right answer depends on the model the agent runs on.

Visible on both models, found on both: OpsDesk a (retries off; both runs SKIPped the planted broken install `387d69a`) and c (history window → 1 message); ClinicDesk a and b on GLM. The controls (OpsDesk f, ClinicDesk e and f) gave no regression everywhere.

## The three misses: ClinicDesk on Llama 3.1 8B

Culprit missed a, b and d on ClinicDesk + Llama: the gate reported no significant regression (p = 0.42, 0.65 and 0.20). It named no commit at all, so there was no false accusation. The cause is visible in the baselines:

- **Llama passed only 162/352 (46%) of ClinicDesk's tasks on the good version** across these six runs (per run: 24/54, 26/52, 35/68, 35/70, 22/54, 20/54). The calibration had measured 47/60 (78%) on the same public tasks a few hours earlier.
- With the good version itself failing more than half the time, a regression that costs a few more tasks is statistically indistinguishable from noise at k = 3, so the gate correctly declined to search.
- The failures are the agent's own: 432 of 447 errors are failed deterministic checks, and the rest are the agent not recovering from injected faults or mangling arguments. None are provider or API errors, so Culprit's infrastructure-error handling didn't hide anything.

What this shows: on a very noisy victim, Culprit trades recall for never blaming the wrong commit. The 46% vs 78% gap between the calibration and today is exactly what `culprit drift` exists to flag. We report it as observed and haven't investigated its cause (for example, which provider OpenRouter routed Llama to).

## Cost

All 24 bisects together cost **$0.90**: about $0.03 per bisect on OpsDesk with GLM, $0.09 on ClinicDesk with GLM, and $0.01–0.02 on Llama. GLM was costed at its current input price of $0.07 per million tokens ($0.039 on 10 Oct).
