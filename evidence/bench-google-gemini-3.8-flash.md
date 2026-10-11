# Culprit bench google-gemini-3.8-flash

- Generated: 2026-10-11T09:09:43+00:00
- Mode: scored existing runs from `/Volumes/DevSSD/Projects/piedpiper-neathacks/.culprit-models/google-gemini-3.8-flash/ledger.sqlite`
- Culprit code: `896fa64a46a92bfda231941c9ab83edeb452a786 + uncommitted changes`
- Victim repo: `/Volumes/DevSSD/Projects/piedpiper-neathacks-refunddesk`
- Victim model(s): `google/gemini-3.8-flash`

## Summary

- **Culprit accuracy: 6/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 560 (93 per scenario)
- Cost: $2.48 ($0.41 per scenario)
- Wall time: 113m 39s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **correct_no_regression** | no_regression | – | `c4f2401` | 52 | $0.22 | 3m 49s | – | `google/gemini-3.8-flash` | `60285a42358c` |
| hist/b | **correct** | found | `397c427` | `397c427` | 164 | $0.75 | 14m 28s | `22a37db` | `google/gemini-3.8-flash` | `30e9f8e6a19f` |
| hist/c | **correct_no_regression** | no_regression | – | `acf3b7d` | 60 | $0.28 | 16m 18s | – | `google/gemini-3.8-flash` | `41056dd52750` |
| hist/d | **correct_no_regression** | no_regression | – | `441058e` | 52 | $0.21 | 20m 21s | – | `google/gemini-3.8-flash` | `0e6caa11ae4b` |
| hist/e | **correct_no_regression** | no_regression | – | `8ae122d` | 52 | $0.22 | 23m 25s | – | `google/gemini-3.8-flash` | `48f6b3ba137a` |
| hist/f | **correct** | found | `1777d44` | `1777d44` | 180 | $0.80 | 35m 18s | `2ad118e` | `google/gemini-3.8-flash` | `9656aba229d2` |

## Runs

### hist/a: run `60285a42358c`

- Range: `0479c273fbd3..6a2f05ad5b5c`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `9f3ceaf2c99784e7e3432096f8d64de2` (session = run ID `60285a42358c`)

### hist/b: run `30e9f8e6a19f`

- Range: `0479c273fbd3..f6511b8e6bb0`
- Summary: Culprit: 397c42743be8cd80ae1d1e30c058772c1bd16add 'perf(agent): run tool calls in parallel and drop per-result validation' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `746ca0b749797e297f5547e478ed0bd1`, `b39fa42d12e819f97458524f226cd8e7` (session = run ID `30e9f8e6a19f`)

### hist/c: run `41056dd52750`

- Range: `0479c273fbd3..30960fe9d716`
- Summary: No significant regression to bisect: good 30/30 vs bad 27/30, one-sided Fisher p=0.1186 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `36809df50226a6e209ce0b5c55306df2`, `5dfedce15a4f595914697b13c04a1974` (session = run ID `41056dd52750`)

### hist/d: run `0e6caa11ae4b`

- Range: `0479c273fbd3..819d692b677e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `5e6c179396ee175a9865068631fb57ef`, `fa3674d92725acdc0adf380ce173bc9e` (session = run ID `0e6caa11ae4b`)

### hist/e: run `48f6b3ba137a`

- Range: `0479c273fbd3..255f40c54e0e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `30a6a5aa5cbe1b599e4789a8d4228e00`, `e21504878d16210d0197dbb0cc361a80` (session = run ID `48f6b3ba137a`)

### hist/f: run `9656aba229d2`

- Range: `0479c273fbd3..3b0938b9da37`
- Summary: Culprit: 1777d44476fc5bfd298d96d296b9d97b6c80b258 'perf(agent): disable tool-call retries' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `8f37061827261bf09d3f4f77f84593d5`, `64fedbb69b7f7633fe0d233a8f854227` (session = run ID `9656aba229d2`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
