# Culprit bench clinicdesk-glm-5.3

- Generated: 2026-10-11T11:15:23+00:00
- Mode: scored existing runs from `/Volumes/DevSSD/Projects/piedpiper-neathacks/.culprit/ledger.sqlite`
- Culprit code: `829fa13366dd19eb0a402ed249e907ad41889552`
- Victim repo: `/Volumes/DevSSD/Projects/clinicdesk`
- Victim model(s): `z-ai/glm-5.3`

## Summary

- **Culprit accuracy: 6/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 512 (85 per scenario)
- Cost: $0.53 ($0.09 per scenario)
- Wall time: 18m 36s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **correct** | found | `cd35228` | `cd35228` | 140 | $0.12 | 3m 59s | – | `z-ai/glm-5.3` | `b913470fa932` |
| hist/b | **correct** | found | `72bdad2` | `72bdad2` | 124 | $0.18 | 5m 48s | – | `z-ai/glm-5.3` | `6e1fe876ad3e` |
| hist/c | **correct_no_regression** | no_regression | – | `c972a0a` | 64 | $0.07 | 2m 19s | – | `z-ai/glm-5.3` | `f7af25b9e923` |
| hist/d | **correct_no_regression** | no_regression | – | `d82a940` | 64 | $0.06 | 2m 24s | – | `z-ai/glm-5.3` | `2a7f301b4378` |
| hist/e | **correct_no_regression** | no_regression | – | `8b6efe3` | 60 | $0.05 | 2m 01s | – | `z-ai/glm-5.3` | `bcb12aebabce` |
| hist/f | **correct_no_regression** | no_regression | – | `4e0d36c` | 60 | $0.05 | 2m 05s | – | `z-ai/glm-5.3` | `0bbfbbae2721` |

## Runs

### hist/a: run `b913470fa932`

- Range: `b753586e7743..3e722395f3ad`
- Summary: Culprit: cd35228cae410fbb4eaa9f886e93b7b39fdcc9c2 'perf: reduce service retry latency' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `d0ebdc58324e3005162049ad0e684377` (session = run ID `b913470fa932`)

### hist/b: run `6e1fe876ad3e`

- Range: `b753586e7743..ac5205fd2ba5`
- Summary: Culprit: 72bdad2290d0b187f53fa95ae1d52e1cd6268d69 'perf: bound conversation context per request' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `f2aa0a45c4ce80f1bb10415c8891012a` (session = run ID `6e1fe876ad3e`)

### hist/c: run `f7af25b9e923`

- Range: `b753586e7743..b08aa7ea5c22`
- Summary: No significant regression to bisect: good 32/32 vs bad 29/32, one-sided Fisher p=0.1190 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `3b51cda098b0bfd14fad46d7ed4b672e` (session = run ID `f7af25b9e923`)

### hist/d: run `2a7f301b4378`

- Range: `b753586e7743..17811020b1a2`
- Summary: No significant regression to bisect: good 32/32 vs bad 29/32, one-sided Fisher p=0.1190 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `a101974cfdb13ddd50cecec04d0df796` (session = run ID `2a7f301b4378`)

### hist/e: run `bcb12aebabce`

- Range: `b753586e7743..81bf118cfe16`
- Summary: No significant regression to bisect: good 30/30 vs bad 30/30, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `46d0a69b133496d63d39c33f227751ef` (session = run ID `bcb12aebabce`)

### hist/f: run `0bbfbbae2721`

- Range: `b753586e7743..4e5dc63f9b90`
- Summary: No significant regression to bisect: good 30/30 vs bad 30/30, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `ddfb156b6063b83f504eadff119a8bcc` (session = run ID `0bbfbbae2721`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
