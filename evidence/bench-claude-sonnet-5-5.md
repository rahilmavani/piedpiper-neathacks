# Culprit bench claude-sonnet-5-5

- Generated: 2026-10-11T15:36:34+00:00
- Mode: scored existing runs from `/Users/rahilmavani/RAHIL MAVANI/Personal Projects/Hackathons/neathack/piedpiper-neathacks/.culprit/ledger.sqlite`
- Culprit code: `e0d80c9a9a0fc129813d911279f6a89ded3aa926 + uncommitted changes`
- Victim repo: `/Users/rahilmavani/RAHIL MAVANI/Personal Projects/Hackathons/neathack/refunddesk`
- Victim model(s): `claude-sonnet-5-5`

## Summary

- **Culprit accuracy: 6/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 584 (97 per scenario)
- Cost: $10.42 ($1.74 per scenario)
- Wall time: 29m 15s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **correct_no_regression** | no_regression | – | `c4f2401` | 52 | $0.85 | 2m 30s | – | `claude-sonnet-5-5` | `0df8e0ab7965` |
| hist/b | **correct** | found | `397c427` | `397c427` | 164 | $2.99 | 8m 25s | `22a37db` | `claude-sonnet-5-5` | `fa6964ed6234` |
| hist/c | **correct** | found | `acf3b7d` | `acf3b7d` | 84 | $1.68 | 5m 06s | – | `claude-sonnet-5-5` | `fe716a4fb735` |
| hist/d | **correct_no_regression** | no_regression | – | `441058e` | 52 | $0.80 | 2m 25s | – | `claude-sonnet-5-5` | `2cb364e47630` |
| hist/e | **correct_no_regression** | no_regression | – | `8ae122d` | 52 | $0.85 | 2m 15s | – | `claude-sonnet-5-5` | `2a5037a4c2d7` |
| hist/f | **correct** | found | `1777d44` | `1777d44` | 180 | $3.25 | 8m 34s | `2ad118e` | `claude-sonnet-5-5` | `bbdd1db92beb` |

## Runs

### hist/a: run `0df8e0ab7965`

- Range: `0479c273fbd3..6a2f05ad5b5c`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `c1ad36130eb55a7ed870fbee36196a67` (session = run ID `0df8e0ab7965`)

### hist/b: run `fa6964ed6234`

- Range: `0479c273fbd3..f6511b8e6bb0`
- Summary: Culprit: 397c42743be8cd80ae1d1e30c058772c1bd16add 'perf(agent): run tool calls in parallel and drop per-result validation' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `e398e17d55bbdc845e5d75176c340ad8` (session = run ID `fa6964ed6234`)

### hist/c: run `fe716a4fb735`

- Range: `0479c273fbd3..30960fe9d716`
- Summary: Culprit: acf3b7df9fb4bf83761787e5f16dbcebc6f004bd 'perf(agent): shorten the history window to 6 messages' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `6dd58a42b95a87c5cea0df1bb5f975fe` (session = run ID `fe716a4fb735`)

### hist/d: run `2cb364e47630`

- Range: `0479c273fbd3..819d692b677e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `87cfc7234621ba30ac9612acd70ef078` (session = run ID `2cb364e47630`)

### hist/e: run `2a5037a4c2d7`

- Range: `0479c273fbd3..255f40c54e0e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `9cde87347e46c361f18c1fa3f4cc8fbe` (session = run ID `2a5037a4c2d7`)

### hist/f: run `bbdd1db92beb`

- Range: `0479c273fbd3..3b0938b9da37`
- Summary: Culprit: 1777d44476fc5bfd298d96d296b9d97b6c80b258 'perf(agent): disable tool-call retries' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `90096fa1d66c482656a80c10a9ca70f2` (session = run ID `bbdd1db92beb`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
