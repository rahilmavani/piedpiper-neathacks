# Run register

Every paid run against the real victim (RefundDesk), plus the free checks that back a claim. Numbers come from the Culprit ledger (`.culprit/ledger.sqlite`) or from the check's own log, never estimates. Costs use our price table (GLM 5.3 via OpenRouter: $0.039/$4.80 per MTok), not neatlogs' figures (see `evidence/neatlogs-cost-discrepancy.md`).

- **Culprit traces** (workflow `culprit`): the neatlogs session ID is the run ID.
- **Victim traces** (workflow `refunddesk-eval`): tagged with `culprit_run_id`, `commit_sha`, `task_id` and `repetition`.

## Culprit runs (benchmark v1, code `3c75be9`)

Victim model `z-ai/glm-5.3`, k = 3, suite pinned at RefundDesk `main` `ba86ed0` (26 tasks), good ref `good-v1.0` (78/78 in every run).

| Date (IST) | Run | Range | Status | Found | Bad baseline | Gate p | Victim runs | Errors | Cost | Time | Culprit trace | `verify-trace` |
|---|---|---|---|---|---|---|---:|---:|---:|---:|---|---|
| 10 Oct 17:17 | `ff50e3620fdd` | `good-v1.0..hist/b` | found | `397c427` ✅ | 57/78 | ≈0 | 240 | 0 | $0.60 | 12 min | `d80e61a81918c7eb3ffd917a2509efb0` | PASS (272 spans) |
| 10 Oct 17:41 | `c35e241d27e0` | `good-v1.0..hist/a` | no_regression | – | 78/78 | 1.00 | 156 | 0 | $0.37 | 6 min | `851077c16289680e6bf3b7b07455eacc` | PASS (167 spans) |
| 10 Oct 17:47 | `61e567f792c4` | `good-v1.0..hist/c` | found | `acf3b7d` ✅ | 72/78 | 0.014 | 180 | 0 | $0.43 | 8 min | `ed3c0d768895933ef77599ed58694410` | PASS (209 spans) |
| 10 Oct 17:56 | `bc1019babecf` | `good-v1.0..hist/d` | no_regression | – | 78/78 | 1.00 | 156 | 0 | $0.34 | 5 min | `2dd7899a4c406576e022d25907315b6f` | PASS (167 spans) |
| 10 Oct 18:02 | `07ef56df395f` | `good-v1.0..hist/e` | no_regression | – | 78/78 | 1.00 | 156 | 0 | $0.33 | 6 min | `cf641747c092456c11249b1847391589` | PASS (167 spans) |
| 10 Oct 18:08 | `2a355484b100` | `good-v1.0..hist/f` | found | `1777d44` ✅ | 51/78 | ≈0 | 252 | 0 | $0.61 | 10 min | `22cf8fbf2da34aa1eadc1d66517f33b5` | PASS (284 spans) |
| | | **Total** | | **6/6 correct** | | | **1,140** | **0** | **$2.70** | 49 min 27 s | | |

Notes:
- `hist/b` and `hist/f` each SKIPped their uninstallable commit (`22a37db`, `2ad118e`) on the first bisect step and then landed on the planted commit.
- `hist/c`: the 95% intervals of 78/78 and 72/78 overlap, so the original gate would have reported no regression. The Fisher gate (p = 0.014) let the bisect run.
- All decisions were clear at the first sample: no step needed resampling on the real victim.
- `hist/a`, `d`, `e`: the independent strength check (below; different seeds) also gives 78/78 on every bad head. The three `no_regression` results are therefore correct for GLM 5.3 with this suite, not misses.

## Culprit runs (benchmark v2, staged baseline, reuse off, code `ec72b65`)

Same victim model, k, suite and good ref as v1. `--no-reuse`, so no results were copied from v1. This measures staging alone.

| Date (IST) | Run | Range | Status | Found | Baseline screen ×1 (good / bad) | Tasks given full k | Victim runs | Errors | Cost | Time | Culprit trace | `verify-trace` |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|
| 10 Oct 19:15 | `e937df6dadbb` | `good-v1.0..hist/a` | no_regression | – | 26/26 / 26/26 | 0 | 52 | 0 | $0.13 | 2 min | `051267132a5d2b6f3528dc050b8b5c9e` | PASS (64 spans) |
| 10 Oct 19:17 | `978624283c27` | `good-v1.0..hist/b` | found | `397c427` ✅ | 26/26 / 19/26 | 7 | 164 | 0 | $0.46 | 8 min | `a9ae3f8ce2b7283129b1e9074c3deac1` | PASS (203 spans) |
| 10 Oct 19:25 | `cd5641dd3a46` | `good-v1.0..hist/c` | found | `acf3b7d` ✅ | 26/26 / 24/26 | 2 | 84 | 0 | $0.24 | 4 min | `0a44a8ea2d4e463983afaf56eaf6d6c9` | PASS (120 spans) |
| 10 Oct 19:30 | `61217e8fb2ea` | `good-v1.0..hist/d` | no_regression | – | 26/26 / 26/26 | 0 | 52 | 0 | $0.12 | 2 min | `0d5cf2fae2214e6a4cf4c653c99a86a3` | PASS (64 spans) |
| 10 Oct 19:33 | `57c1f7da7b61` | `good-v1.0..hist/e` | no_regression | – | 26/26 / 26/26 | 0 | 52 | 0 | $0.12 | 2 min | `7deea3d2d7aa0623fb9d417beab6e822` | PASS (64 spans) |
| 10 Oct 19:36 | `7caf109c2b88` | `good-v1.0..hist/f` | found | `1777d44` ✅ | 26/26 / 17/26 | 9 | 184 | 0 | $0.45 | 8 min | `e8a5d2e5f9519344aab44e0bbfb7ca38` | PASS (223 spans) |
| | | **Total** | | **6/6 correct** | | | **588** | **0** | **$1.51** | 29 min 09 s | | |

`hist/f` v2 also SKIPped the uninstallable `2ad118e`. The v2 hero run has the full Entire intent (checkpoint `01M4JM8P2C4NDS2AAQ0MPVR8YR`), because Entire was installed by then. Report: `evidence/reports/report-978624283c27.md`.

## v1 → v2 (the before/after)

| | v1 | v2 (staged) | Change |
|---|---:|---:|---:|
| Correct (`culprit bench`) | 6/6 | 6/6 | same |
| Victim runs | 1,140 | 588 | **−48%** |
| Cost | $2.70 | $1.51 | **−44%** |
| Time (sum of run wall times) | 49 min 27 s | 29 min 09 s | −41% |
| Errors | 0 | 0 | |

Per branch, victim runs v1 → v2: a 156 → 52, b 240 → 164, c 180 → 84, d 156 → 52, e 156 → 52, f 252 → 184. Only the baselines changed; the bisect steps ran the same number of runs. Totals are exact sums from `evidence/bench-v1.json` and `bench-v2.json` ($2.6957 and $1.5123). Scored by `culprit bench`: `evidence/bench-v1.md`, `evidence/bench-v2.md`.

Not measured: baseline reuse (`--reuse`, on by default). On this ledger it would copy both ends' baselines from v1 and run almost nothing, which isn't a fair comparison. The fixture measurement is in `evidence/v2-efficiency-fixture.md`.

## Victim-model comparison (11 Oct; Culprit v2, `--no-reuse`, suite `ba86ed0`)

Full write-up: `evidence/MODELS.md`. Data for the charts: `evidence/models.json`. The three models ran in parallel, each in its own `CULPRIT_STATE_DIR`. All 18 bisects were scored with `culprit bench`, and every model got **6/6**.

| Model | Run | Branch | Outcome | Found | Victim runs | Cost | Resumed | Culprit trace |
|---|---|---|---|---|---:|---:|---|---|
| DeepSeek V4.1 Flash | `65ee52ef08c3` | hist/a | correct_no_regression | – | 52 | $0.019 |  | `90479185e8c79606a813e2f1b3e3c51f` |
| DeepSeek V4.1 Flash | `2797e84bcc15` | hist/b | correct | `397c427` | 132 | $0.061 | yes | `ab7ca70945db8f49e6e480be99c8b14e`, `0525ff4ee71c39e3036f72b350da63dd` |
| DeepSeek V4.1 Flash | `8ace75bdc6fa` | hist/c | correct | `acf3b7d` | 84 | $0.050 | yes | `1ed9ecf5db5c9adc82a167879f00904b`, `00e5b5dd82cd18d09c2ca824d9d17e42` |
| DeepSeek V4.1 Flash | `57052ac18acd` | hist/d | correct_no_regression | – | 52 | $0.020 | yes | `2ca268d78f103e7b4f459bca648e5c37`, `a4379b5a105e816407353eacb29fe152` |
| DeepSeek V4.1 Flash | `25ed0ebed07b` | hist/e | correct_no_regression | – | 52 | $0.018 | yes | `9de99829157165820397dc596a9bb383`, `81744d53c39ad9bd4c04e1e76947aea2` |
| DeepSeek V4.1 Flash | `e2473ed6f0e9` | hist/f | correct | `1777d44` | 164 | $0.070 | yes | `2befe2af221e7cc25e6a6df87c5de430`, `240a1ce7064d085e7f619365ae255af0` |
| Gemini 3.8 Flash | `60285a42358c` | hist/a | correct_no_regression | – | 52 | $0.220 |  | `9f3ceaf2c99784e7e3432096f8d64de2` |
| Gemini 3.8 Flash | `30e9f8e6a19f` | hist/b | correct | `397c427` | 164 | $0.754 | yes | `746ca0b749797e297f5547e478ed0bd1`, `b39fa42d12e819f97458524f226cd8e7` |
| Gemini 3.8 Flash | `41056dd52750` | hist/c | correct_no_regression | – | 60 | $0.277 | yes | `36809df50226a6e209ce0b5c55306df2`, `5dfedce15a4f595914697b13c04a1974` |
| Gemini 3.8 Flash | `0e6caa11ae4b` | hist/d | correct_no_regression | – | 52 | $0.209 | yes | `5e6c179396ee175a9865068631fb57ef`, `fa3674d92725acdc0adf380ce173bc9e` |
| Gemini 3.8 Flash | `48f6b3ba137a` | hist/e | correct_no_regression | – | 52 | $0.216 | yes | `30a6a5aa5cbe1b599e4789a8d4228e00`, `e21504878d16210d0197dbb0cc361a80` |
| Gemini 3.8 Flash | `9656aba229d2` | hist/f | correct | `1777d44` | 180 | $0.801 | yes | `8f37061827261bf09d3f4f77f84593d5`, `64fedbb69b7f7633fe0d233a8f854227` |
| Qwen 3.8 Flash | `aeb5eafc26cd` | hist/a | correct_no_regression | – | 52 | $0.021 |  | `8be2a0031d0a5d43e0a0565386c1434d` |
| Qwen 3.8 Flash | `7b4085c566bd` | hist/b | correct | `397c427` | 164 | $0.078 |  | `e050b655a8654f073c252904d03b1d03` |
| Qwen 3.8 Flash | `3fd5b81ea6a5` | hist/c | correct | `acf3b7d` | 84 | $0.042 |  | `497fd7ee121f98a8213f21079c6d5965` |
| Qwen 3.8 Flash | `130ec8ed6488` | hist/d | correct_no_regression | – | 52 | $0.021 |  | `dc624bd40233c4305dcbd79e79a21a83` |
| Qwen 3.8 Flash | `661cd6012df1` | hist/e | correct_no_regression | – | 52 | $0.020 |  | `76eace739469d1214407ab23902ebb70` |
| Qwen 3.8 Flash | `706b51fa91d9` | hist/f | correct | `1777d44` | 188 | $0.082 | yes | `545d5e26c58ac904e4005759c57969f9`, `0be1c54de1303262ca59bbbead60ce94` |

Resumed runs had stopped on the OpenRouter key's $10 limit (`infra_error`, nothing counted) and were resumed after it was raised. Their wall time includes the pause.

### Claude Sonnet 5.5 (11 Oct 20:15–21:06 IST; Anthropic API directly; Culprit `e0d80c9`)

Run with the same commands as `scripts/bench_model.sh`, with `BUDGET=6`. It ran on a separate machine, with one state folder and no parallel models. Scored with `culprit bench --tag claude-sonnet-5-5`: **6/6**.

| Model | Run | Branch | Outcome | Found | Victim runs | Cost | Resumed | Culprit trace |
|---|---|---|---|---|---:|---:|---|---|
| Claude Sonnet 5.5 | `0df8e0ab7965` | hist/a | correct_no_regression | – | 52 | $0.851 |  | `c1ad36130eb55a7ed870fbee36196a67` |
| Claude Sonnet 5.5 | `fa6964ed6234` | hist/b | correct | `397c427` | 164 | $2.991 |  | `e398e17d55bbdc845e5d75176c340ad8` |
| Claude Sonnet 5.5 | `fe716a4fb735` | hist/c | correct | `acf3b7d` | 84 | $1.681 |  | `6dd58a42b95a87c5cea0df1bb5f975fe` |
| Claude Sonnet 5.5 | `2cb364e47630` | hist/d | correct_no_regression | – | 52 | $0.802 |  | `87cfc7234621ba30ac9612acd70ef078` |
| Claude Sonnet 5.5 | `2a5037a4c2d7` | hist/e | correct_no_regression | – | 52 | $0.850 |  | `9cde87347e46c361f18c1fa3f4cc8fbe` |
| Claude Sonnet 5.5 | `bbdd1db92beb` | hist/f | correct | `1777d44` | 180 | $3.248 |  | `90096fa1d66c482656a80c10a9ca70f2` |
| | | **Total** | | **6/6 correct** | **584** | **$10.42** | | |

- `hist/b` and `hist/f` both skipped their uninstallable commit (`22a37db`, `2ad118e`).
- No run hit its $6 cap, none stopped with `infra_error`, and none was resumed.
- The strength check before the bisects (546 runs, seeds 3–5) cost $9.07, and the smoke run $0.017. Total Sonnet spend: **$19.50**.
- Costs use the agent's price table ($2/$10 per MTok, Anthropic list price), not neatlogs' $3/$15.

## Localise and fix on the real victim (hist/b, run `ff50e3620fdd`)

| Stage | Result | Victim runs | Model calls | Cost |
|---|---|---:|---|---:|
| `culprit localise` | GLM ranked 16 hunks. Single reverts of h4 (0/21), h3 (1/21) and h5 (0/21) stayed BAD; the **pair h4+h3 → 21/21 GOOD**. Responsible: `agent.py:144-148` (retry loop) + `agent.py` lines 98–123 removed (`validate_tool_result`), which **matches `bench/ground_truth.json`**. The parallel-execution hunks were not blamed. | 84 | 3 ranking calls (2 were cut off at the 4,000-token cap and repaired) | $0.20 |
| `culprit fix` (replayed after v2 to add the latency fields: 0 new victim runs, 0 model calls) | Attempt 1 was rejected before running: its edit referred to a snippet that isn't in the file. Attempt 2 restores validation and retry-on-failure and leaves the thread pool alone: **96/96** on full suite + held-out × 3, the same as good (96/96). Held-out alone: good 18/18, bad 15/18, fix 18/18. No new failures. Status `verified_fix`. | 132 | 2 proposals | $0.33 |

Latency caveat: the planted "make it faster" commit didn't make the agent measurably faster (baseline median latency good 7086 ms vs bad 7138 ms; time is dominated by model calls, and the tools are mocks). The "intended gain kept" gate passed (fix 7992 ms vs bad 9288 ms over the verify runs), but there was no real speed-up to keep.

## Drift check and blind-spot audit (11 Oct, GLM 5.3, code `c173861`)

| Date (IST) | Run | Command | Result | Victim runs | Cost | Time |
|---|---|---|---|---:|---:|---:|
| 11 Oct 14:47 | `7d302133d9f5` | `culprit drift --ref good-v1.0` | **STABLE**: 78/78 now vs 78/78 in run `ff50e3620fdd` (10 Oct), p = 1.00 both ways. Same code, suite, model and seeds: GLM didn't drift overnight | 78 | $0.19 | 3.4 min |
| 11 Oct 14:50 | `463cde6de95a` | `culprit audit --ref good-v1.0 --suite-ref ba86ed0` | **Mutation score 4/8**: 4 realistic regressions caught, 4 missed (`evidence/audit-refunddesk-glm.md`). Baseline 78/78 reused from earlier runs (78 rows, $0) | 624 | $1.80 ($1.53 victim + $0.27 for 8 GLM proposals) | 35 min |

**Did the audit rediscover what we found by hand?** It made its own changes (GLM proposed the edits), so they aren't identical to the planted ones, but they fall into the same categories:

| Regression type | Planted by hand (GLM, `bench/strength.md`) | Found by `culprit audit` |
|---|---|---|
| Drop tool-result validation | `hist/b`: visible | **caught** (61/78) |
| Disable retries | `hist/f`: visible | **caught** (53/78) |
| Shrink the history window | `hist/c` (24 → 6): visible, 72/78 | **caught** (24 → 3): 72/78 |
| Drop the >$500 rule from the prompt | `hist/d`: invisible (the rule survived, and a code guard blocks large refunds anyway) | **missed**: the mutant removed the rule; the code guard still blocks, so the suite can't see it |
| Lenient tool-argument parsing | `hist/e`: invisible | **missed** |
| Rename a tool parameter | `hist/a`: a *complete* rename, invisible | a *half-done* rename (schema says `recipient`, code reads `to`): **caught**, 15/78. A different change, so not a contradiction |
| Remove the code-level $500 guard | not planted | **missed: a new blind spot** |
| Vague tool description | not planted | **missed: a new blind spot** |

So the audit agrees with the hand-planted results on every category where they're comparable, and finds two blind spots we hadn't planted. Each miss comes with a concrete task to add (see the report). The guard-only and prompt-only removals are invisible because they back each other up: each passes while the other is still there.

## Two more domains × two victim models (11 Oct, Culprit `3afa407`, `--no-reuse`, k = 3)

Summary and analysis: `evidence/DOMAINS.md`; chart data: `evidence/domains.json`. Answer keys: `bench/opsdesk/`, `bench/clinicdesk/`.

| Domain | Model | Branch | Expected visible | Result | Found | Outcome | Victim runs | Cost | Run |
|---|---|---|---|---|---|---|---:|---:|---|
| OpsDesk | GLM 5.3 | hist/a | yes | found | `95eca63` | correct | 124 | $0.033 | `a8f7546313ac` |
| OpsDesk | GLM 5.3 | hist/b | no | no_regression | – | correct_no_regression | 60 | $0.019 | `4675ccf9d5e2` |
| OpsDesk | GLM 5.3 | hist/c | yes | found | `3262e83` | correct | 156 | $0.066 | `dac65a670075` |
| OpsDesk | GLM 5.3 | hist/d | no | no_regression | – | correct_no_regression | 60 | $0.019 | `a72192519026` |
| OpsDesk | GLM 5.3 | hist/e | no | no_regression | – | correct_no_regression | 60 | $0.018 | `53d35e7a4ba8` |
| OpsDesk | GLM 5.3 | hist/f | no | no_regression | – | correct_no_regression | 60 | $0.018 | `1394a1e20fc9` |
| OpsDesk | Llama 3.1 8B | hist/a | yes | found | `95eca63` | correct | 124 | $0.007 | `c0641d8444e7` |
| OpsDesk | Llama 3.1 8B | hist/b | yes | found | `5a54888` | correct | 196 | $0.018 | `cc521c355be3` |
| OpsDesk | Llama 3.1 8B | hist/c | yes | found | `3262e83` | correct | 156 | $0.018 | `94b8cbcfa90c` |
| OpsDesk | Llama 3.1 8B | hist/d | yes | found | `5559976` | correct | 132 | $0.009 | `45d96cbedd13` |
| OpsDesk | Llama 3.1 8B | hist/e | yes | found | `afa3143` | correct | 138 | $0.009 | `9c55a7cc8f99` |
| OpsDesk | Llama 3.1 8B | hist/f | no | no_regression | – | correct_no_regression | 68 | $0.006 | `bd8e36efeb29` |
| ClinicDesk | GLM 5.3 | hist/a | yes | found | `cd35228` | correct | 140 | $0.120 | `b913470fa932` |
| ClinicDesk | GLM 5.3 | hist/b | yes | found | `72bdad2` | correct | 124 | $0.175 | `6e1fe876ad3e` |
| ClinicDesk | GLM 5.3 | hist/c | no | no_regression | – | correct_no_regression | 64 | $0.071 | `f7af25b9e923` |
| ClinicDesk | GLM 5.3 | hist/d | no | no_regression | – | correct_no_regression | 64 | $0.058 | `2a7f301b4378` |
| ClinicDesk | GLM 5.3 | hist/e | no | no_regression | – | correct_no_regression | 60 | $0.051 | `bcb12aebabce` |
| ClinicDesk | GLM 5.3 | hist/f | no | no_regression | – | correct_no_regression | 60 | $0.054 | `0bbfbbae2721` |
| ClinicDesk | Llama 3.1 8B | hist/a | yes | no_regression | – | missed | 108 | $0.015 | `7d33e16f8324` |
| ClinicDesk | Llama 3.1 8B | hist/b | yes | no_regression | – | missed | 104 | $0.016 | `c4937ce01a67` |
| ClinicDesk | Llama 3.1 8B | hist/c | yes | found | `c972a0a` | correct | 232 | $0.046 | `6a07e1766790` |
| ClinicDesk | Llama 3.1 8B | hist/d | yes | no_regression | – | missed | 140 | $0.019 | `93d18871e3fe` |
| ClinicDesk | Llama 3.1 8B | hist/e | no | no_regression | – | correct_no_regression | 108 | $0.015 | `3f6bf9ac7de9` |
| ClinicDesk | Llama 3.1 8B | hist/f | no | no_regression | – | correct_no_regression | 108 | $0.015 | `168dc7730e14` |

Totals: 21/24 correct, 3 missed (ClinicDesk on Llama: a, b, d), 0 wrong culprits; 2,646 victim runs, $0.90. Two repos ran in parallel.

## Checks (scripts, not Culprit runs)

| Date (IST) | Check | Refs | Tasks × seeds | Result | Runs | Cost | Errors |
|---|---|---|---|---|---:|---:|---:|
| 10 Oct, before 17:17 | GLM smoke run | RefundDesk `main` | `refund_small_order` × seed 0 | passed, 4 LLM calls, trace `1f030e85f50030b93391d1a90a669a69` | 1 | $0.0066 | 0 |
| 10 Oct, before 17:17 | Hero visibility on GLM | `good-v1.0` vs `397c427` | 6 harder tasks × seeds 0–2 | **18/18 vs 0/18** | 36 | $0.134 | 0 |
| 10 Oct, evening | Strength check (independent of Culprit's baselines) | `good-v1.0` vs heads of `hist/a`, `d`, `e` | 26 tasks × seeds 3–5 | **all four 78/78**, Fisher p = 1.00 for a, d, e: the planted changes are invisible to this suite on GLM 5.3 | 312 | $0.711 | 0 |
| 11 Oct | Smoke runs, one per new model | `good-v1.0` | `refund_small_order` × seed 0 | all 3 passed: Qwen $0.00050, DeepSeek $0.00047, Gemini $0.00374 per run | 3 | $0.0047 | 0 |
| 11 Oct | Strength checks, 3 new models (`evidence/models/*-strength.json`) | `good-v1.0` + all six `hist/*` heads | 26 tasks × seeds 3–5 | good 78/78 on all; visible bugs Qwen b, c, f; DeepSeek b, c, f; Gemini b, f (c: 75/78, p = 0.12) | 1,638 | $2.780 | 0 infra |

## Test suite

| Date (IST) | Commit | Tests | Result |
|---|---|---:|---|
| 10 Oct | `3983fb8` | 68 | pass |
| 10 Oct | `94d0a26` (feat/bench) | 86 | pass (clean checkout) |
| 10 Oct | `a72210e` | 71 (fix/decision-gates) | pass |
