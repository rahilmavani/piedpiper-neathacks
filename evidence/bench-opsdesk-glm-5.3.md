# Culprit bench opsdesk-glm-5.3

- Generated: 2026-10-11T10:38:38+00:00
- Mode: scored existing runs from `/Volumes/DevSSD/Projects/piedpiper-neathacks/.culprit/ledger.sqlite`
- Culprit code: `829fa13366dd19eb0a402ed249e907ad41889552`
- Victim repo: `/Volumes/DevSSD/Projects/opsdesk`
- Victim model(s): `z-ai/glm-5.3`

## Summary

- **Culprit accuracy: 6/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 520 (87 per scenario)
- Cost: $0.17 ($0.03 per scenario)
- Wall time: 9m 20s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **correct** | found | `95eca63` | `95eca63` | 124 | $0.03 | 1m 50s | `387d69a` | `z-ai/glm-5.3` | `a8f7546313ac` |
| hist/b | **correct_no_regression** | no_regression | – | `5a54888` | 60 | $0.02 | 1m 07s | – | `z-ai/glm-5.3` | `4675ccf9d5e2` |
| hist/c | **correct** | found | `3262e83` | `3262e83` | 156 | $0.07 | 3m 02s | – | `z-ai/glm-5.3` | `dac65a670075` |
| hist/d | **correct_no_regression** | no_regression | – | `5559976` | 60 | $0.02 | 1m 09s | – | `z-ai/glm-5.3` | `a72192519026` |
| hist/e | **correct_no_regression** | no_regression | – | `afa3143` | 60 | $0.02 | 1m 05s | – | `z-ai/glm-5.3` | `53d35e7a4ba8` |
| hist/f | **correct_no_regression** | no_regression | – | `142e5fb` | 60 | $0.02 | 1m 07s | – | `z-ai/glm-5.3` | `1394a1e20fc9` |

## Runs

### hist/a: run `a8f7546313ac`

- Range: `6c09d9762d43..d90fcb4cc216`
- Summary: Culprit: 95eca63dc4fd5bfa498bafe36392c6000801ee47 'perf: reduce tool dispatch latency' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `15f9520b232ffe9b9cda43f7a8b89177` (session = run ID `a8f7546313ac`)

### hist/b: run `4675ccf9d5e2`

- Range: `6c09d9762d43..d6cd7886a31d`
- Summary: No significant regression to bisect: good 30/30 vs bad 30/30, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `18fc48edcca01bbf50118319c71c75db` (session = run ID `4675ccf9d5e2`)

### hist/c: run `dac65a670075`

- Range: `6c09d9762d43..0b902b9b7fd1`
- Summary: Culprit: 3262e8316a6e2ea0354b9d0df85d07c7f862efd3 'perf: bound incident prompt size' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `8e0e86d7d3c746959e2b71ee170722d7` (session = run ID `dac65a670075`)

### hist/d: run `a72192519026`

- Range: `6c09d9762d43..b8f648cb7fe2`
- Summary: No significant regression to bisect: good 30/30 vs bad 30/30, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `36fcde769d581386439c6b5f5011162f` (session = run ID `a72192519026`)

### hist/e: run `53d35e7a4ba8`

- Range: `6c09d9762d43..1ab4311604ba`
- Summary: No significant regression to bisect: good 30/30 vs bad 30/30, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `b8460e37dfd6dd629a7600b0cad54476` (session = run ID `53d35e7a4ba8`)

### hist/f: run `1394a1e20fc9`

- Range: `6c09d9762d43..2739ba933e72`
- Summary: No significant regression to bisect: good 30/30 vs bad 30/30, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `47e0c9c087768324520eca810bc90089` (session = run ID `1394a1e20fc9`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
