# Culprit across victim models

Does Culprit still find the culprit when the agent under test runs on a different model? We re-ran the full RefundDesk benchmark with the agent on three more models through OpenRouter (11 Oct 2026), next to GLM 5.3 from 10 Oct, and then on **Claude Sonnet 5.5** through the Anthropic API (11 Oct evening, following `evidence/SONNET_RUN.md`). The comparison now covers these **five models**.

Machine-readable data for the charts: [`models.json`](models.json), built by `scripts/models_json.py` from the files listed below.

## Results

| Model | $/MTok in/out | Good baseline (seeds 3–5) | Bugs visible | Culprit accuracy | Victim runs (6 bisects) | Cost (6 bisects) | Cost per bisect | Cost per victim run | Median victim-run latency |
|---|---|---|---|---|---:|---:|---:|---:|---:|
| GLM 5.3 (`z-ai/glm-5.3`) | $0.039/$4.8 | 78/78 | 3/6 (b, c, f) | **6/6** | 588 | $1.51 | $0.252 | $0.00257 | 7.7 s |
| DeepSeek V4.1 Flash (`deepseek/deepseek-v4.1-flash`) | $0.3/$1.2 | 78/78 | 3/6 (b, c, f) | **6/6** | 536 | $0.24 | $0.040 | $0.00044 | 7.5 s |
| Gemini 3.8 Flash (`google/gemini-3.8-flash`) | $0.75/$3.75 | 78/78 | 2/6 (b, f) | **6/6** | 560 | $2.48 | $0.413 | $0.00442 | 10.7 s |
| Qwen 3.8 Flash (`qwen/qwen3.8-flash`) | $0.15/$0.47 | 78/78 | 3/6 (b, c, f) | **6/6** | 592 | $0.26 | $0.044 | $0.00045 | 15.6 s |
| Claude Sonnet 5.5 (`claude-sonnet-5-5`, Anthropic) | $2/$10 | 78/78 | 3/6 (b, c, f) | **6/6** | 584 | $10.42 | $1.737 | $0.01785 | 8.0 s |

- **Culprit is 6/6 on every model: 30 of 30 bisects correct.** It names the planted commit wherever the suite can see the bug, and reports "no regression" wherever it can't.
- **Cost per bisect varies more than 40×** (v2, averaged over the six branches): DeepSeek $0.040, Qwen $0.044, GLM $0.252, Gemini $0.413, Sonnet $1.737. Accuracy is the same, so DeepSeek and Qwen are about 6× cheaper per bisect than GLM, and about 40× cheaper than Sonnet.
- **Speed:** DeepSeek and GLM answer a task in about 7.5 s (median), Sonnet in 8.0 s, Gemini in 10.7 s and Qwen in 15.6 s.

## Which planted bugs each model's suite can see

Strength check: the full suite (26 tasks × seeds 3–5 = 78 runs) at `good-v1.0` and at each branch head. Visible = one-sided Fisher p < 0.05.

| Bug | GLM 5.3 | DeepSeek V4.1 Flash | Gemini 3.8 Flash | Qwen 3.8 Flash | Claude Sonnet 5.5 |
|---|---|---|---|---|---|
| a · rename `order_id` → `id` | – 78/78 | – 78/78, p=1.000 | – 78/78, p=1.000 | – 78/78, p=1.000 | – 78/78, p=1.000 |
| b · parallel tools, validation dropped (hero) | ✅ — (hero_check) | ✅ 63/78, p<0.001 | ✅ 57/78, p<0.001 | ✅ 57/78, p<0.001 | ✅ 57/78, p<0.001 |
| c · history window 24 → 6 | ✅ — (culprit_baseline) | ✅ 72/78, p=0.014 | – 75/78, p=0.123 | ✅ 72/78, p=0.014 | ✅ 72/78, p=0.014 |
| d · system prompt shortened | – 78/78 | – 78/78, p=1.000 | – 78/78, p=1.000 | – 77/78, p=0.500 | – 78/78, p=1.000 |
| e · lenient tool arguments | – 78/78 | – 78/78, p=1.000 | – 78/78, p=1.000 | – 78/78, p=1.000 | – 78/78, p=1.000 |
| f · `MAX_RETRIES` 3 → 0 | ✅ — (culprit_baseline) | ✅ 52/78, p<0.001 | ✅ 50/78, p<0.001 | ✅ 48/78, p<0.001 | ✅ 51/78, p<0.001 |

- **Visibility depends on the model.** Bug **c** (history window cut from 24 to 6 messages) is visible on GLM, DeepSeek and Qwen, but **not on Gemini**: 75/78, p = 0.12. Gemini handles the shortened history well enough that only 3 of 78 runs fail.
  - On Gemini, Culprit's own baseline agreed: 30/30 vs 27/30, p = 0.12. It declined to bisect, which the bench scores as `correct_no_regression`.
- **Bugs a, d and e are invisible on all five models.** It's a property of the suite, not of the model:
  - a: the rename was done consistently.
  - d: the >$500 rule survived the prompt cleanup, and a code guard blocks large refunds anyway.
  - e: no model omits a tool argument, so lenient parsing never runs.
- Qwen's single failure on d (77/78, `refund_500_01_escalated`) is noise (p = 0.50).
- Sonnet sees the same three bugs as GLM, DeepSeek and Qwen: b, c and f.
- GLM's column comes from older checks: a, d and e from the full-suite strength check (`strength-check-glm.jsonl`); b from the hero check (6 harder tasks, 18/18 vs 0/18); c and f only from Culprit's own baselines (72/78 and 51/78 vs 78/78). It had no full strength check on b, c and f.

## All runs

| Model | Run | Branch | Outcome | Found | Victim runs | Cost | Resumed |
|---|---|---|---|---|---:|---:|---|
| GLM 5.3 | `e937df6dadbb` | hist/a | correct_no_regression | – | 52 | $0.126 |  |
| GLM 5.3 | `978624283c27` | hist/b | correct | `397c427` | 164 | $0.455 |  |
| GLM 5.3 | `cd5641dd3a46` | hist/c | correct | `acf3b7d` | 84 | $0.242 |  |
| GLM 5.3 | `61217e8fb2ea` | hist/d | correct_no_regression | – | 52 | $0.116 |  |
| GLM 5.3 | `57c1f7da7b61` | hist/e | correct_no_regression | – | 52 | $0.123 |  |
| GLM 5.3 | `7caf109c2b88` | hist/f | correct | `1777d44` | 184 | $0.450 |  |
| DeepSeek V4.1 Flash | `65ee52ef08c3` | hist/a | correct_no_regression | – | 52 | $0.019 |  |
| DeepSeek V4.1 Flash | `2797e84bcc15` | hist/b | correct | `397c427` | 132 | $0.061 | yes |
| DeepSeek V4.1 Flash | `8ace75bdc6fa` | hist/c | correct | `acf3b7d` | 84 | $0.050 | yes |
| DeepSeek V4.1 Flash | `57052ac18acd` | hist/d | correct_no_regression | – | 52 | $0.020 | yes |
| DeepSeek V4.1 Flash | `25ed0ebed07b` | hist/e | correct_no_regression | – | 52 | $0.018 | yes |
| DeepSeek V4.1 Flash | `e2473ed6f0e9` | hist/f | correct | `1777d44` | 164 | $0.070 | yes |
| Gemini 3.8 Flash | `60285a42358c` | hist/a | correct_no_regression | – | 52 | $0.220 |  |
| Gemini 3.8 Flash | `30e9f8e6a19f` | hist/b | correct | `397c427` | 164 | $0.754 | yes |
| Gemini 3.8 Flash | `41056dd52750` | hist/c | correct_no_regression | – | 60 | $0.277 | yes |
| Gemini 3.8 Flash | `0e6caa11ae4b` | hist/d | correct_no_regression | – | 52 | $0.209 | yes |
| Gemini 3.8 Flash | `48f6b3ba137a` | hist/e | correct_no_regression | – | 52 | $0.216 | yes |
| Gemini 3.8 Flash | `9656aba229d2` | hist/f | correct | `1777d44` | 180 | $0.801 | yes |
| Qwen 3.8 Flash | `aeb5eafc26cd` | hist/a | correct_no_regression | – | 52 | $0.021 |  |
| Qwen 3.8 Flash | `7b4085c566bd` | hist/b | correct | `397c427` | 164 | $0.078 |  |
| Qwen 3.8 Flash | `3fd5b81ea6a5` | hist/c | correct | `acf3b7d` | 84 | $0.042 |  |
| Qwen 3.8 Flash | `130ec8ed6488` | hist/d | correct_no_regression | – | 52 | $0.021 |  |
| Qwen 3.8 Flash | `661cd6012df1` | hist/e | correct_no_regression | – | 52 | $0.020 |  |
| Qwen 3.8 Flash | `706b51fa91d9` | hist/f | correct | `1777d44` | 188 | $0.082 | yes |
| Claude Sonnet 5.5 | `0df8e0ab7965` | hist/a | correct_no_regression | – | 52 | $0.851 |  |
| Claude Sonnet 5.5 | `fa6964ed6234` | hist/b | correct | `397c427` | 164 | $2.991 |  |
| Claude Sonnet 5.5 | `fe716a4fb735` | hist/c | correct | `acf3b7d` | 84 | $1.681 |  |
| Claude Sonnet 5.5 | `2cb364e47630` | hist/d | correct_no_regression | – | 52 | $0.802 |  |
| Claude Sonnet 5.5 | `2a5037a4c2d7` | hist/e | correct_no_regression | – | 52 | $0.850 |  |
| Claude Sonnet 5.5 | `bbdd1db92beb` | hist/f | correct | `1777d44` | 180 | $3.248 |  |

Per-model bench reports: `bench-v2.md` (GLM), `bench-qwen-qwen3.8-flash.md`, `bench-deepseek-deepseek-v4.1-flash.md`, `bench-google-gemini-3.8-flash.md`, `bench-claude-sonnet-5-5.md`. Strength summaries: `models/<slug>-strength.json`. Ledgers: `ledger-snapshot.sqlite` (GLM + Qwen) and `models/<slug>-ledger.sqlite`.

## Method (the same for every model)

- **Suite** pinned at RefundDesk `ba86ed0` (26 tasks), good ref `good-v1.0`, k = 3. Bisects with Culprit v2 (staged baseline) and `--no-reuse`, so no results are copied between runs or models.
- **Strength check** with `scripts/strength_check.py` on seeds 3–5, separate from the bisects' seeds 0–2. Visibility is recorded in `bench/ground_truth.json` from the strength check only (`scripts/visibility_from_strength.py`), never from Culprit's runs.
- **Scoring** with `culprit bench --tag <slug> --score-runs …`.
- **Costs** are what OpenRouter billed per victim run, as reported by the agent. For Qwen and DeepSeek that's below list price, probably from prompt caching. Smoke runs: Qwen $0.00050, DeepSeek $0.00047 and Gemini $0.00374 per run, against list prices of $0.00095, $0.00187 and $0.00374.
- **Run order:** the three OpenRouter models ran in parallel, each in its own state folder (`CULPRIT_STATE_DIR`), so their working copies and ledgers were isolated. Sonnet ran later, alone, on a separate machine (11 Oct 20:15–21:06 IST).
- **Sonnet costs** are computed by the agent from Anthropic's list price ($2/$10 per MTok). They are not an OpenRouter bill. Sonnet 5.5 rejects `temperature`, so its runs were sent without it; the agent detects this.

## Caveats

- **Stopped and resumed runs.** The OpenRouter key hit its $10 lifetime limit during the runs. 11 bisects stopped cleanly with `infra_error`, with nothing counted against any commit, and were resumed after the limit was raised. Their victim runs and costs are unaffected. Their **wall time includes the pause**, so `models.json` marks them `resumed` and the model's `wall_s_comparable: false`. Use median latency or `victim_latency_sum_s` to compare speed.
- **GLM's price changed.** On 11 Oct OpenRouter lists GLM 5.3 at $0.07/$4.80; our GLM runs on 10 Oct used $0.039/$4.80. Its recorded costs are what was billed then.
- **One run per model per branch.** The accuracy figures are counts, not rates with confidence intervals.

## Spend on 11 Oct (OpenRouter models)

**$5.76** in total:
- strength checks: Qwen $0.23, DeepSeek $0.23, Gemini $2.33
- the 18 bisects
- 3 smoke runs

## Spend on Claude Sonnet 5.5 (11 Oct evening)

**$19.50** in total:
- strength check: $9.07 (546 runs)
- 6 bisects: $10.42 (584 runs); no cap hit, no resumes
- 1 smoke run: $0.017

`models.json` lists the Sonnet bench's code as `e0d80c9 + uncommitted changes`. The only uncommitted change at scoring time was the visibility update to `bench/ground_truth.json`, which `SONNET_RUN.md` §3 runs just before scoring. Culprit's source code was unchanged.
