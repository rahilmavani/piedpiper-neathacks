# Culprit bench v2

- Generated: 2026-10-10T14:15:04+00:00
- Mode: scored existing runs from `/Volumes/DevSSD/Projects/piedpiper-neathacks/.culprit/ledger.sqlite`
- Culprit code: `e4a4add6c4f5f455a79e0f52390925dba0c2dcec`
- Victim repo: `/Volumes/DevSSD/Projects/piedpiper-neathacks-refunddesk`
- Victim model(s): `z-ai/glm-5.3`

## Summary

- **Culprit accuracy: 6/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 588 (98 per scenario)
- Cost: $1.51 ($0.25 per scenario)
- Wall time: 29m 09s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **correct_no_regression** | no_regression | – | `c4f2401` | 52 | $0.13 | 2m 09s | – | `z-ai/glm-5.3` | `e937df6dadbb` |
| hist/b | **correct** | found | `397c427` | `397c427` | 164 | $0.46 | 8m 16s | `22a37db` | `z-ai/glm-5.3` | `978624283c27` |
| hist/c | **correct** | found | `acf3b7d` | `acf3b7d` | 84 | $0.24 | 4m 43s | – | `z-ai/glm-5.3` | `cd5641dd3a46` |
| hist/d | **correct_no_regression** | no_regression | – | `441058e` | 52 | $0.12 | 2m 42s | – | `z-ai/glm-5.3` | `61217e8fb2ea` |
| hist/e | **correct_no_regression** | no_regression | – | `8ae122d` | 52 | $0.12 | 2m 49s | – | `z-ai/glm-5.3` | `57c1f7da7b61` |
| hist/f | **correct** | found | `1777d44` | `1777d44` | 184 | $0.45 | 8m 30s | `2ad118e` | `z-ai/glm-5.3` | `7caf109c2b88` |

## Runs

### hist/a: run `e937df6dadbb`

- Range: `0479c273fbd3..6a2f05ad5b5c`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `051267132a5d2b6f3528dc050b8b5c9e` (session = run ID `e937df6dadbb`)

### hist/b: run `978624283c27`

- Range: `0479c273fbd3..f6511b8e6bb0`
- Summary: Culprit: 397c42743be8cd80ae1d1e30c058772c1bd16add 'perf(agent): run tool calls in parallel and drop per-result validation' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `a9ae3f8ce2b7283129b1e9074c3deac1` (session = run ID `978624283c27`)

### hist/c: run `cd5641dd3a46`

- Range: `0479c273fbd3..30960fe9d716`
- Summary: Culprit: acf3b7df9fb4bf83761787e5f16dbcebc6f004bd 'perf(agent): shorten the history window to 6 messages' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `0a44a8ea2d4e463983afaf56eaf6d6c9` (session = run ID `cd5641dd3a46`)

### hist/d: run `61217e8fb2ea`

- Range: `0479c273fbd3..819d692b677e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `0d5cf2fae2214e6a4cf4c653c99a86a3` (session = run ID `61217e8fb2ea`)

### hist/e: run `57c1f7da7b61`

- Range: `0479c273fbd3..255f40c54e0e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `7deea3d2d7aa0623fb9d417beab6e822` (session = run ID `57c1f7da7b61`)

### hist/f: run `7caf109c2b88`

- Range: `0479c273fbd3..3b0938b9da37`
- Summary: Culprit: 1777d44476fc5bfd298d96d296b9d97b6c80b258 'perf(agent): disable tool-call retries' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `e8a5d2e5f9519344aab44e0bbfb7ca38` (session = run ID `7caf109c2b88`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
