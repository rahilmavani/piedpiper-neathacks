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
| | | **Total** | | **3/3 visible** | | | **1,140** | **0** | **$2.68** | 47 min | | |

Notes:
- `hist/b` and `hist/f` each SKIPped their uninstallable commit (`22a37db`, `2ad118e`) on the first bisect step and then landed on the planted commit.
- `hist/c`: the 95% intervals of 78/78 and 72/78 overlap, so the original gate would have reported no regression. The Fisher gate (p = 0.014) let the bisect run.
- All decisions were clear at the first sample: no step needed resampling on the real victim.
- `hist/a`, `d`, `e`: the independent strength check (below; different seeds) also gives 78/78 on every bad head. The three `no_regression` results are therefore correct for GLM 5.3 with this suite, not misses.

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
