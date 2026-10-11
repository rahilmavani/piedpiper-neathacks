# Culprit bench deepseek-deepseek-v4.1-flash

- Generated: 2026-10-11T09:00:25+00:00
- Mode: scored existing runs from `/Volumes/DevSSD/Projects/piedpiper-neathacks/.culprit-models/deepseek-deepseek-v4.1-flash/ledger.sqlite`
- Culprit code: `896fa64a46a92bfda231941c9ab83edeb452a786 + uncommitted changes`
- Victim repo: `/Volumes/DevSSD/Projects/piedpiper-neathacks-refunddesk`
- Victim model(s): `deepseek/deepseek-v4.1-flash`

## Summary

- **Culprit accuracy: 6/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 536 (89 per scenario)
- Cost: $0.24 ($0.04 per scenario)
- Wall time: 81m 10s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **correct_no_regression** | no_regression | – | `c4f2401` | 52 | $0.02 | 2m 28s | – | `deepseek/deepseek-v4.1-flash` | `65ee52ef08c3` |
| hist/b | **correct** | found | `397c427` | `397c427` | 132 | $0.06 | 14m 36s | `22a37db` | `deepseek/deepseek-v4.1-flash` | `2797e84bcc15` |
| hist/c | **correct** | found | `acf3b7d` | `acf3b7d` | 84 | $0.05 | 10m 29s | – | `deepseek/deepseek-v4.1-flash` | `8ace75bdc6fa` |
| hist/d | **correct_no_regression** | no_regression | – | `441058e` | 52 | $0.02 | 12m 44s | – | `deepseek/deepseek-v4.1-flash` | `57052ac18acd` |
| hist/e | **correct_no_regression** | no_regression | – | `8ae122d` | 52 | $0.02 | 14m 52s | – | `deepseek/deepseek-v4.1-flash` | `25ed0ebed07b` |
| hist/f | **correct** | found | `1777d44` | `1777d44` | 164 | $0.07 | 26m 01s | `2ad118e` | `deepseek/deepseek-v4.1-flash` | `e2473ed6f0e9` |

## Runs

### hist/a: run `65ee52ef08c3`

- Range: `0479c273fbd3..6a2f05ad5b5c`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `90479185e8c79606a813e2f1b3e3c51f` (session = run ID `65ee52ef08c3`)

### hist/b: run `2797e84bcc15`

- Range: `0479c273fbd3..f6511b8e6bb0`
- Summary: Culprit: 397c42743be8cd80ae1d1e30c058772c1bd16add 'perf(agent): run tool calls in parallel and drop per-result validation' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `ab7ca70945db8f49e6e480be99c8b14e`, `0525ff4ee71c39e3036f72b350da63dd` (session = run ID `2797e84bcc15`)

### hist/c: run `8ace75bdc6fa`

- Range: `0479c273fbd3..30960fe9d716`
- Summary: Culprit: acf3b7df9fb4bf83761787e5f16dbcebc6f004bd 'perf(agent): shorten the history window to 6 messages' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `1ed9ecf5db5c9adc82a167879f00904b`, `00e5b5dd82cd18d09c2ca824d9d17e42` (session = run ID `8ace75bdc6fa`)

### hist/d: run `57052ac18acd`

- Range: `0479c273fbd3..819d692b677e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `2ca268d78f103e7b4f459bca648e5c37`, `a4379b5a105e816407353eacb29fe152` (session = run ID `57052ac18acd`)

### hist/e: run `25ed0ebed07b`

- Range: `0479c273fbd3..255f40c54e0e`
- Summary: No significant regression to bisect: good 26/26 vs bad 26/26, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `9de99829157165820397dc596a9bb383`, `81744d53c39ad9bd4c04e1e76947aea2` (session = run ID `25ed0ebed07b`)

### hist/f: run `e2473ed6f0e9`

- Range: `0479c273fbd3..3b0938b9da37`
- Summary: Culprit: 1777d44476fc5bfd298d96d296b9d97b6c80b258 'perf(agent): disable tool-call retries' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `2befe2af221e7cc25e6a6df87c5de430`, `240a1ce7064d085e7f619365ae255af0` (session = run ID `e2473ed6f0e9`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
