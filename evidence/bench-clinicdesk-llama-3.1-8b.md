# Culprit bench clinicdesk-llama-3.1-8b

- Generated: 2026-10-11T11:15:23+00:00
- Mode: scored existing runs from `/Volumes/DevSSD/Projects/piedpiper-neathacks/.culprit/ledger.sqlite`
- Culprit code: `829fa13366dd19eb0a402ed249e907ad41889552`
- Victim repo: `/Volumes/DevSSD/Projects/clinicdesk`
- Victim model(s): `meta-llama/llama-3.1-8b-instruct`

## Summary

- **Culprit accuracy: 3/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 800 (133 per scenario)
- Cost: $0.13 ($0.02 per scenario)
- Wall time: 38m 01s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **missed** | no_regression | – | `cd35228` | 108 | $0.02 | 4m 14s | – | `meta-llama/llama-3.1-8b-instruct` | `7d33e16f8324` |
| hist/b | **missed** | no_regression | – | `72bdad2` | 104 | $0.02 | 6m 31s | – | `meta-llama/llama-3.1-8b-instruct` | `c4937ce01a67` |
| hist/c | **correct** | found | `c972a0a` | `c972a0a` | 232 | $0.05 | 13m 17s | – | `meta-llama/llama-3.1-8b-instruct` | `6a07e1766790` |
| hist/d | **missed** | no_regression | – | `d82a940` | 140 | $0.02 | 7m 40s | – | `meta-llama/llama-3.1-8b-instruct` | `93d18871e3fe` |
| hist/e | **correct_no_regression** | no_regression | – | `8b6efe3` | 108 | $0.02 | 4m 38s | – | `meta-llama/llama-3.1-8b-instruct` | `3f6bf9ac7de9` |
| hist/f | **correct_no_regression** | no_regression | – | `4e0d36c` | 108 | $0.02 | 1m 41s | – | `meta-llama/llama-3.1-8b-instruct` | `168dc7730e14` |

## Runs

### hist/a: run `7d33e16f8324`

- Range: `b753586e7743..3e722395f3ad`
- Summary: No significant regression to bisect: good 24/54 vs bad 22/54, one-sided Fisher p=0.4229 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `815824785f276496b6930c98c1bb7157` (session = run ID `7d33e16f8324`)

### hist/b: run `c4937ce01a67`

- Range: `b753586e7743..ac5205fd2ba5`
- Summary: No significant regression to bisect: good 26/52 vs bad 27/52, one-sided Fisher p=0.6525 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `80ef3c51d921057558185ea5f4b32398` (session = run ID `c4937ce01a67`)

### hist/c: run `6a07e1766790`

- Range: `b753586e7743..b08aa7ea5c22`
- Summary: Culprit: c972a0aac725ea8c90ed514f79414a7011fd746a 'refactor: streamline symptom keyword matching' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `be6abfcbd25b89852e67f0b7a61922c1` (session = run ID `6a07e1766790`)

### hist/d: run `93d18871e3fe`

- Range: `b753586e7743..17811020b1a2`
- Summary: No significant regression to bisect: good 35/70 vs bad 29/70, one-sided Fisher p=0.1982 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `f2a36b8650b6837c9b78257fa5b8dce9` (session = run ID `93d18871e3fe`)

### hist/e: run `3f6bf9ac7de9`

- Range: `b753586e7743..81bf118cfe16`
- Summary: No significant regression to bisect: good 22/54 vs bad 18/54, one-sided Fisher p=0.2751 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `1c10f0ecccaa4ef6b601177257d1ffb5` (session = run ID `3f6bf9ac7de9`)

### hist/f: run `168dc7730e14`

- Range: `b753586e7743..4e5dc63f9b90`
- Summary: No significant regression to bisect: good 20/54 vs bad 21/54, one-sided Fisher p=0.6540 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `945a11038189cc19c87adde63b17f356` (session = run ID `168dc7730e14`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
