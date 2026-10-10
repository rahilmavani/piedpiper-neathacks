# Run register

Every paid run against the real victim (RefundDesk), plus the free checks that back a claim. Numbers come from the Culprit ledger (`.culprit/ledger.sqlite`) or from the check's own log, never estimates. Costs use our price table (GLM 5.3 via OpenRouter: $0.039/$4.80 per MTok), not neatlogs' figures (see `BLOCKERS.md`).

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

## Localise and fix on the real victim (hist/b, run `ff50e3620fdd`)

| Stage | Result | Victim runs | Model calls | Cost |
|---|---|---:|---|---:|
| `culprit localise` | GLM ranked 16 hunks. Single reverts of h4 (0/21), h3 (1/21) and h5 (0/21) stayed BAD; the **pair h4+h3 → 21/21 GOOD**. Responsible: `agent.py:144-148` (retry loop) + `agent.py` lines 98–123 removed (`validate_tool_result`), which **matches `bench/ground_truth.json`**. The parallel-execution hunks were not blamed. | 84 | 3 ranking calls (2 were cut off at the 4,000-token cap and repaired) | $0.20 |
| `culprit fix` (replayed after v2 to add the latency fields: 0 new victim runs, 0 model calls) | Attempt 1 was rejected before running: its edit referred to a snippet that isn't in the file. Attempt 2 restores validation and retry-on-failure and leaves the thread pool alone: **96/96** on full suite + held-out × 3, the same as good (96/96). Held-out alone: good 18/18, bad 15/18, fix 18/18. No new failures. Status `verified_fix`. | 132 | 2 proposals | $0.33 |

Latency caveat: the planted "make it faster" commit didn't make the agent measurably faster (baseline median latency good 7086 ms vs bad 7138 ms; time is dominated by model calls, and the tools are mocks). The "intended gain kept" gate passed (fix 7992 ms vs bad 9288 ms over the verify runs), but there was no real speed-up to keep.

## Checks (scripts, not Culprit runs)

| Date (IST) | Check | Refs | Tasks × seeds | Result | Runs | Cost | Errors |
|---|---|---|---|---|---:|---:|---:|
| 10 Oct, before 17:17 | GLM smoke run | RefundDesk `main` | `refund_small_order` × seed 0 | passed, 4 LLM calls, trace `1f030e85f50030b93391d1a90a669a69` | 1 | $0.0066 | 0 |
| 10 Oct, before 17:17 | Hero visibility on GLM | `good-v1.0` vs `397c427` | 6 harder tasks × seeds 0–2 | **18/18 vs 0/18** | 36 | $0.134 | 0 |
| 10 Oct, evening | Strength check (independent of Culprit's baselines) | `good-v1.0` vs heads of `hist/a`, `d`, `e` | 26 tasks × seeds 3–5 | **all four 78/78**, Fisher p = 1.00 for a, d, e: the planted changes are invisible to this suite on GLM 5.3 | 312 | $0.711 | 0 |

## Test suite

| Date (IST) | Commit | Tests | Result |
|---|---|---:|---|
| 10 Oct | `3983fb8` | 68 | pass |
| 10 Oct | `94d0a26` (feat/bench) | 86 | pass (clean checkout) |
| 10 Oct | `a72210e` | 71 (fix/decision-gates) | pass |
