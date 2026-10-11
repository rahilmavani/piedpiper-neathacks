# Culprit bench qwen-qwen3.8-flash

- Generated: 2026-10-11T08:37:54+00:00
- Mode: scored existing runs from `/Volumes/DevSSD/Projects/piedpiper-neathacks/.culprit/ledger.sqlite`
- Culprit code: `896fa64a46a92bfda231941c9ab83edeb452a786 + uncommitted changes`
- Victim repo: `/Volumes/DevSSD/Projects/piedpiper-neathacks-refunddesk`
- Victim model(s): `qwen/qwen3.8-flash`

## Summary

- **Culprit accuracy: 6/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 592 (99 per scenario)
- Cost: $0.26 ($0.04 per scenario)
- Wall time: 60m 45s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **correct_no_regression** | no_regression | – | `c4f2401` | 52 | $0.02 | 5m 17s | – | `qwen/qwen3.8-flash` | `aeb5eafc26cd` |
| hist/b | **correct** | found | `397c427` | `397c427` | 164 | $0.08 | 17m 51s | `22a37db` | `qwen/qwen3.8-flash` | `7b4085c566bd` |
| hist/c | **correct** | found | `acf3b7d` | `acf3b7d` | 84 | $0.04 | 10m 02s | – | `qwen/qwen3.8-flash` | `3fd5b81ea6a5` |
| hist/d | **correct_no_regression** | no_regression | – | `441058e` | 52 | $0.02 | 4m 21s | – | `qwen/qwen3.8-flash` | `130ec8ed6488` |
| hist/e | **correct_no_regression** | no_regression | – | `8ae122d` | 52 | $0.02 | 3m 39s | – | `qwen/qwen3.8-flash` | `661cd6012df1` |
| hist/f | **correct** | found | `1777d44` | `1777d44` | 188 | $0.08 | 19m 35s | `2ad118e` | `qwen/qwen3.8-flash` | `706b51fa91d9` |

## Runs

### hist/a: run `aeb5eafc26cd`

- Range: `0479c273fbd3..6a2f05ad5b5c`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `8be2a0031d0a5d43e0a0565386c1434d` (session = run ID `aeb5eafc26cd`)

### hist/b: run `7b4085c566bd`

- Range: `0479c273fbd3..f6511b8e6bb0`
- Summary: Culprit: 397c42743be8cd80ae1d1e30c058772c1bd16add 'perf(agent): run tool calls in parallel and drop per-result validation' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `e050b655a8654f073c252904d03b1d03` (session = run ID `7b4085c566bd`)

### hist/c: run `3fd5b81ea6a5`

- Range: `0479c273fbd3..30960fe9d716`
- Summary: Culprit: acf3b7df9fb4bf83761787e5f16dbcebc6f004bd 'perf(agent): shorten the history window to 6 messages' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `497fd7ee121f98a8213f21079c6d5965` (session = run ID `3fd5b81ea6a5`)

### hist/d: run `130ec8ed6488`

- Range: `0479c273fbd3..819d692b677e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `dc624bd40233c4305dcbd79e79a21a83` (session = run ID `130ec8ed6488`)

### hist/e: run `661cd6012df1`

- Range: `0479c273fbd3..255f40c54e0e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `76eace739469d1214407ab23902ebb70` (session = run ID `661cd6012df1`)

### hist/f: run `706b51fa91d9`

- Range: `0479c273fbd3..3b0938b9da37`
- Summary: Culprit: 1777d44476fc5bfd298d96d296b9d97b6c80b258 'perf(agent): disable tool-call retries' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `545d5e26c58ac904e4005759c57969f9`, `0be1c54de1303262ca59bbbead60ce94` (session = run ID `706b51fa91d9`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
