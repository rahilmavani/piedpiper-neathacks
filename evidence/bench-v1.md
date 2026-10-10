# Culprit bench v1

- Generated: 2026-10-10T13:21:55+00:00
- Mode: scored existing runs from `/Volumes/DevSSD/Projects/piedpiper-neathacks/.culprit/ledger.sqlite`
- Culprit code: `4b4f826d5cbb2cf8e2f028b028cf195587077cdc + uncommitted changes`
- Victim repo: `/Volumes/DevSSD/Projects/piedpiper-neathacks-refunddesk`
- Victim model(s): `z-ai/glm-5.3`

## Summary

- **Culprit accuracy: 6/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 1140 (190 per scenario)
- Cost: $2.70 ($0.45 per scenario)
- Wall time: 49m 27s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **correct_no_regression** | no_regression | – | `c4f2401` | 156 | $0.37 | 6m 09s | – | `z-ai/glm-5.3` | `c35e241d27e0` |
| hist/b | **correct** | found | `397c427` | `397c427` | 240 | $0.60 | 12m 28s | `22a37db` | `z-ai/glm-5.3` | `ff50e3620fdd` |
| hist/c | **correct** | found | `acf3b7d` | `acf3b7d` | 180 | $0.43 | 8m 30s | – | `z-ai/glm-5.3` | `61e567f792c4` |
| hist/d | **correct_no_regression** | no_regression | – | `441058e` | 156 | $0.34 | 5m 55s | – | `z-ai/glm-5.3` | `bc1019babecf` |
| hist/e | **correct_no_regression** | no_regression | – | `8ae122d` | 156 | $0.33 | 6m 01s | – | `z-ai/glm-5.3` | `07ef56df395f` |
| hist/f | **correct** | found | `1777d44` | `1777d44` | 252 | $0.61 | 10m 24s | `2ad118e` | `z-ai/glm-5.3` | `2a355484b100` |

## Runs

### hist/a: run `c35e241d27e0`

- Range: `0479c273fbd3..6a2f05ad5b5c`
- Summary: No significant regression to bisect: good 78/78 vs bad 78/78, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `851077c16289680e6bf3b7b07455eacc` (session = run ID `c35e241d27e0`)

### hist/b: run `ff50e3620fdd`

- Range: `0479c273fbd3..f6511b8e6bb0`
- Summary: Culprit: 397c42743be8cd80ae1d1e30c058772c1bd16add 'perf(agent): run tool calls in parallel and drop per-result validation' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `d80e61a81918c7eb3ffd917a2509efb0` (session = run ID `ff50e3620fdd`)

### hist/c: run `61e567f792c4`

- Range: `0479c273fbd3..30960fe9d716`
- Summary: Culprit: acf3b7df9fb4bf83761787e5f16dbcebc6f004bd 'perf(agent): shorten the history window to 6 messages' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `ed3c0d768895933ef77599ed58694410` (session = run ID `61e567f792c4`)

### hist/d: run `bc1019babecf`

- Range: `0479c273fbd3..819d692b677e`
- Summary: No significant regression to bisect: good 78/78 vs bad 78/78, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `2dd7899a4c406576e022d25907315b6f` (session = run ID `bc1019babecf`)

### hist/e: run `07ef56df395f`

- Range: `0479c273fbd3..255f40c54e0e`
- Summary: No significant regression to bisect: good 78/78 vs bad 78/78, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `cf641747c092456c11249b1847391589` (session = run ID `07ef56df395f`)

### hist/f: run `2a355484b100`

- Range: `0479c273fbd3..3b0938b9da37`
- Summary: Culprit: 1777d44476fc5bfd298d96d296b9d97b6c80b258 'perf(agent): disable tool-call retries' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `22cf8fbf2da34aa1eadc1d66517f33b5` (session = run ID `2a355484b100`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
