# Culprit bench opsdesk-llama-3.1-8b

- Generated: 2026-10-11T10:38:38+00:00
- Mode: scored existing runs from `/Volumes/DevSSD/Projects/piedpiper-neathacks/.culprit/ledger.sqlite`
- Culprit code: `829fa13366dd19eb0a402ed249e907ad41889552`
- Victim repo: `/Volumes/DevSSD/Projects/opsdesk`
- Victim model(s): `meta-llama/llama-3.1-8b-instruct`

## Summary

- **Culprit accuracy: 6/6 scored correct** (correct commit, or a correct `no_regression`)
- Victim runs: 814 (136 per scenario)
- Cost: $0.07 ($0.01 per scenario)
- Wall time: 10m 35s (sum of runs)
- Hunk accuracy and fix verification: not scored by bench (see `culprit localise` / `culprit fix`)

## Results

| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| hist/a | **correct** | found | `95eca63` | `95eca63` | 124 | $0.01 | 1m 13s | `387d69a` | `meta-llama/llama-3.1-8b-instruct` | `c0641d8444e7` |
| hist/b | **correct** | found | `5a54888` | `5a54888` | 196 | $0.02 | 2m 46s | – | `meta-llama/llama-3.1-8b-instruct` | `cc521c355be3` |
| hist/c | **correct** | found | `3262e83` | `3262e83` | 156 | $0.02 | 2m 21s | – | `meta-llama/llama-3.1-8b-instruct` | `94b8cbcfa90c` |
| hist/d | **correct** | found | `5559976` | `5559976` | 132 | $0.01 | 1m 35s | – | `meta-llama/llama-3.1-8b-instruct` | `45d96cbedd13` |
| hist/e | **correct** | found | `afa3143` | `afa3143` | 138 | $0.01 | 1m 48s | – | `meta-llama/llama-3.1-8b-instruct` | `9c55a7cc8f99` |
| hist/f | **correct_no_regression** | no_regression | – | `142e5fb` | 68 | $0.01 | 52s | – | `meta-llama/llama-3.1-8b-instruct` | `bd8e36efeb29` |

## Runs

### hist/a: run `c0641d8444e7`

- Range: `6c09d9762d43..d90fcb4cc216`
- Summary: Culprit: 95eca63dc4fd5bfa498bafe36392c6000801ee47 'perf: reduce tool dispatch latency' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `032ccc6c206eb8b69a3e9ed8857df5ca` (session = run ID `c0641d8444e7`)

### hist/b: run `cc521c355be3`

- Range: `6c09d9762d43..d6cd7886a31d`
- Summary: Culprit: 5a54888ae805bec8b0003be1b3a137431cbe18f8 'refactor: streamline tool dispatch checks' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `16b4a73332577d826499d42232ad730b` (session = run ID `cc521c355be3`)

### hist/c: run `94b8cbcfa90c`

- Range: `6c09d9762d43..0b902b9b7fd1`
- Summary: Culprit: 3262e8316a6e2ea0354b9d0df85d07c7f862efd3 'perf: bound incident prompt size' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `00ca98cd1b625ae100bdc0161cb4b15a` (session = run ID `94b8cbcfa90c`)

### hist/d: run `45d96cbedd13`

- Range: `6c09d9762d43..b8f648cb7fe2`
- Summary: Culprit: 55599763178f8e5441a9d7ae4315a50549253550 'refactor: accept numeric values at the tool boundary' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `f691100b5798ad7ba3c1057b335a842b` (session = run ID `45d96cbedd13`)

### hist/e: run `9c55a7cc8f99`

- Range: `6c09d9762d43..1ab4311604ba`
- Summary: Culprit: afa31438c16e22238d66e2ddc4bc88164542647f 'refactor: simplify telemetry context assembly' (confidence: 95% Wilson)
- Confidence: 95% Wilson
- neatlogs Culprit trace(s): `52f3b1f8a4130b67bef2a8182e76f646` (session = run ID `9c55a7cc8f99`)

### hist/f: run `bd8e36efeb29`

- Range: `6c09d9762d43..2739ba933e72`
- Summary: No significant regression to bisect: good 32/34 vs bad 34/34, one-sided Fisher p=1.0000 ≥ 0.05
- Confidence: –
- neatlogs Culprit trace(s): `59a8c1250ceac6dab6755cd408cbd441` (session = run ID `bd8e36efeb29`)

Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no significant regression and none was expected (no bug planted in the range, or a measurement showed this bug is invisible on this model); `missed` means it is known to be visible; `no_regression_unverified` means its visibility on this model has not been measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped (budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, so it includes any pause before a resume.
