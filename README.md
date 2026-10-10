# Culprit

**`git bisect` for agent behaviour, with receipts.**

Give Culprit a good ref, a bad ref and an eval suite. It finds the commit that made your LLM agent
worse, even though evals are noisy and some commits won't install. It then reads *why* that change was
made from the coding-agent session recorded by Entire. Every step is traced in neatlogs and recorded in
a ledger, so each verdict can be audited.

Team PiedPiper, neatHack 2026. Build log: [`hackathon.md`](hackathon.md). Full technical guide:
[`HOW_IT_WORKS.md`](HOW_IT_WORKS.md). Spec: [`PRD.md`](PRD.md). Demo script: [`DEMO.md`](DEMO.md).

## The problem

Agent quality can degrade quietly over many commits: a prompt tweak here, a "make it faster" refactor
there, often written by a coding agent. Finding the commit responsible is hard for three reasons:

- **Evals are noisy.** The same commit can pass a task once and fail it the next time, so plain
  `git bisect` with one run per commit can blame the wrong commit.
- **Old commits break.** A bad dependency pin in the middle of the range stops a naive bisect.
- **Nobody remembers why.** Reverting the culprit also throws away whatever it was meant to improve.

## What Culprit does

1. **Pins the eval suite.** One snapshot of the suite judges every commit in the range, and the ledger
   records its SHA.
2. **Checks there is something to find.** It measures both ends, and a one-sided Fisher exact test
   (p < 0.05) must say good really beats bad. Otherwise it stops with `no_regression` rather than hunt
   for noise.
3. **Bisects with statistics.** Each step runs the tasks that dropped from good to bad, k times each.
   A 95% Wilson interval wholly above or below the threshold decides GOOD or BAD; if it straddles,
   Culprit resamples, and it flags any verdict it had to guess (`low_confidence`).
4. **Skips what won't install.** A commit that fails `uv sync --locked` is SKIPped and a neighbour is
   tested, as `git bisect skip` does.
5. **Explains the culprit.** It reads the commit's Entire checkpoint for the intent, passed through a
   leakage filter, and falls back to the commit message and diff when there is no checkpoint.
6. **Localises and fixes** (`culprit localise`, `culprit fix`). It finds the responsible hunk(s) by
   reverting them, writes a minimal fix, and verifies it on the full and held-out suites. The fix must
   keep the intended gain. These have been tested on the fixture victim only; see
   [Limitations](#limitations).
7. **Reports.** `culprit report <run_id>` writes markdown and static HTML. `culprit export-costs`
   writes per-run cost, victim runs and wall time as CSV for the business model.

Infrastructure failures (429, 5xx, timeouts) are retried and never counted against a commit. Budget
caps stop a run with the best current range. `culprit resume` continues any stopped run without
redoing finished work.

## Results so far (benchmark v1, real victim)

Six planted-bug branches of RefundDesk (see [the honesty note](#honesty-note-the-bugs-are-planted)).
Victim model GLM 5.3 via OpenRouter, k = 3, 26-task suite pinned at RefundDesk `main` `ba86ed0`.
Sources: [`evidence/bench-v1.md`](evidence/bench-v1.md), [`evidence/RUNS.md`](evidence/RUNS.md).

| Branch | Outcome | Found | Bad baseline | Victim runs | Cost | Run | Culprit trace (neatlogs) |
|---|---|---|---|---:|---:|---|---|
| `hist/a` | correct `no_regression` | – | 78/78 | 156 | $0.37 | `c35e241d27e0` | `851077c16289680e6bf3b7b07455eacc` |
| `hist/b` (hero) | **correct** | `397c427` | 57/78 | 240 | $0.60 | `ff50e3620fdd` | `d80e61a81918c7eb3ffd917a2509efb0` |
| `hist/c` | **correct** | `acf3b7d` | 72/78 | 180 | $0.43 | `61e567f792c4` | `ed3c0d768895933ef77599ed58694410` |
| `hist/d` | correct `no_regression` | – | 78/78 | 156 | $0.34 | `bc1019babecf` | `2dd7899a4c406576e022d25907315b6f` |
| `hist/e` | correct `no_regression` | – | 78/78 | 156 | $0.33 | `07ef56df395f` | `cf641747c092456c11249b1847391589` |
| `hist/f` | **correct** | `1777d44` | 51/78 | 252 | $0.61 | `2a355484b100` | `22cf8fbf2da34aa1eadc1d66517f33b5` |

- **Accuracy: 6/6 scored correct.** That breaks down as all **3 visible** planted bugs found exactly,
  plus 3 correct `no_regression` results on bugs that an independent check showed the suite can't see
  (see [the honesty note](#honesty-note-the-bugs-are-planted)).
- **Total:** 1,140 victim runs, 0 infrastructure errors, $2.70, 49m 27s of run time (bench-v1 totals
  from the ledger). The good end was 78/78 in every run.
- **Recovery on the real victim:** `hist/b` and `hist/f` SKIPped their uninstallable commit (`22a37db`,
  `2ad118e`) on the first bisect step and still landed on the planted commit. No step on the real victim
  needed resampling. The resample path is shown on the fixture victim instead.
- **The gate mattered:** on `hist/c`, 78/78 vs 72/78 have overlapping 95% intervals, so our original
  "intervals don't overlap" gate would have said `no_regression`. The Fisher gate gave p = 0.014 and
  the bisect found `acf3b7d`.
- **Every Culprit trace passed `culprit verify-trace`** (one root, no orphans, run ID and commit SHA on
  every span).

Not measured yet: hunk accuracy and fix verification on the real victim, and the v2 benchmark. See
[Limitations](#limitations).

### v1 → v2: cheaper baselines

Measuring both ends was the most expensive part of every run: 156 of `hist/b`'s 240 victim runs. v2
makes it cheaper in two ways:

- **Staged baseline.** Every task runs ×1 on both ends, and only tasks that didn't pass on both get the
  full k. Both ends run the same set, and the Fisher gate counts the runs actually made.
- **Baseline reuse.** Results at a commit are copied from an earlier run with the same commit SHA,
  suite SHA, victim model and k. Each copied row records the run it came from and isn't counted as
  spend again.

On the fixture victim, over 4 scenarios: **510 victim runs (v1) → 430 (v2) → 335 (v2, good end reused)
→ 270 (v2, both ends reused)**. Every run found the planted commit, and bisect runs were unchanged
([`evidence/v2-efficiency-fixture.md`](evidence/v2-efficiency-fixture.md)).

TODO: the v2 benchmark on the real victim (`evidence/bench-v2.md`). Its numbers will replace this
fixture-only comparison.

## Setup

You need Python ≥ 3.12, [`uv`](https://docs.astral.sh/uv/), git, and (for intent) the
[Entire CLI](https://docs.entire.io) (we used 0.11.4).

Clone both repos side by side:

```bash
git clone https://github.com/rahilmavani/piedpiper-neathacks.git              # Culprit
git clone https://github.com/rahilmavani/piedpiper-neathacks-refunddesk.git   # RefundDesk, the victim
cd piedpiper-neathacks && uv sync
```

Culprit only ever creates worktrees of the victim under `.culprit/worktrees/`. It never edits your
victim checkout. If the victim isn't at `../refunddesk`, set `CULPRIT_VICTIM_REPO` or pass `--repo`.

Create a `.env` in **each** repo. Both are gitignored, and RefundDesk's needs the same model key:

```bash
NEATLOGS_API_KEY=...        # tracing (optional; without it tracing is off)
ANTHROPIC_API_KEY=...       # if set: Claude Sonnet 5.5 (claude-sonnet-5-5)
OPENROUTER_API_KEY=...      # otherwise: GLM 5.3 (z-ai/glm-5.3) via OpenRouter
# optional overrides, which must belong to the selected provider:
# VICTIM_MODEL=...  CULPRIT_MODEL=...
```

The provider is chosen from the keys present: Anthropic first, then OpenRouter. A run records its
victim provider and model, and passes them to every commit, so all commits are judged by the same
model. All published numbers were measured on GLM 5.3.

## How to run

```bash
set -a; source .env; set +a
uv run pytest -q                       # free: no model calls, tracing off

# Free demo on a generated fake victim (no LLM)
uv run python tests/fixtures/make_victim.py /tmp/victim --commits 14 --breaks-at 10 --unbuildable-at 7 --noisy-from 9 --noisy-pass 0.6
uv run culprit run --repo /tmp/victim --good good-v1.0 --bad main

# Real victim (costs money: hist/b cost $0.60 on GLM 5.3)
uv run culprit run --repo ../piedpiper-neathacks-refunddesk --good good-v1.0 --bad origin/hist/b --budget-usd 5
uv run culprit resume <run_id> [--budget-usd 6]     # continue a stopped run
uv run culprit localise <run_id>                    # responsible hunk(s)
uv run culprit fix <run_id>                         # minimal fix + verification
uv run culprit report <run_id>                      # .culprit/reports/report-<run_id>.{md,html}
uv run culprit verify-trace <run_id>                # audit the run's neatlogs traces
uv run culprit bench --tag v1 --score-latest        # score runs against bench/ground_truth.json
uv run culprit export-costs --format csv --out business/runs.csv
```

`culprit run --no-reuse --no-staged` reproduces v1's baseline behaviour.

## How the three tools are used

### neatlogs

- **Culprit is traced.** Each run is one trace in workflow `culprit`, with the neatlogs session ID set
  to the run ID. Git, worktree, install, victim runs, decisions and Entire calls are spans, and each span
  carries the run ID and commit SHA.
- **The victim is traced.** Every RefundDesk task run is its own trace (workflow `refunddesk-eval`),
  tagged with Culprit's run ID, commit, task and repetition, so each data point in a bisect links to
  the agent run behind it.
- **Readback audit.** `culprit verify-trace <run_id>` pulls a run back through the neatlogs CLI and
  checks it against the trace contract. All six v1 runs pass (167–284 spans each).
- **A finding:** neatlogs prices `claude-sonnet-5-5` at $3/$15 per MTok against the $2/$10 list price.
  Culprit's own price table is the only cost source
  ([`evidence/neatlogs-cost-discrepancy.md`](evidence/neatlogs-cost-discrepancy.md),
  [`BLOCKERS.md`](BLOCKERS.md)).
- TODO: Investigate and Detections on the v1 runs (dashboard only; see `BLOCKERS.md`).

### Entire

- **In the product:** for the culprit commit, Culprit runs `entire checkpoint explain <sha>` in the
  victim repo and takes the Intent. When the Intent is a placeholder, it uses the session's typed
  prompts from `--transcript`. When there is no checkpoint, it uses the commit message and diff. Only
  the examined commit's checkpoint is read, and a leakage filter strips anything that could reveal the
  benchmark answers.
- **In the build:** both repos have Entire enabled, so Culprit's own commits and every planted-bug
  commit in RefundDesk carry `Entire-Checkpoint` trailers.
- In run `ff50e3620fdd` the intent fell back to the commit message and diff, because the Entire CLI
  wasn't installed on the machine that ran it. TODO: the hero commit's intent read through Entire on
  a recorded run.

### cfo.ai

- [`business/cfo-inputs.md`](business/cfo-inputs.md) holds measured unit costs from the ledger and
  three pricing scenarios, all labelled hypotheses: (A) flat per-repo subscription, (B) bring your own
  model key plus a platform fee, and (C) metered per bisect.
- `culprit export-costs --format csv` produces the per-run inputs.
- TODO: the cfo.ai business plan (pricing, costs, revenue, runway), exported to `business/`.

## Honesty note: the bugs are planted

RefundDesk and its six bugs were built by us, on purpose, so that Culprit's answers can be checked
against a known truth (PRD §9.2).

- **How they were made.** Each planted commit was **explicitly requested** from a Claude Code session
  in the RefundDesk repo, with a realistic reason (speed, cost, consistency), and Entire recorded those
  sessions. The hero bug on `hist/b` came from a session told to make RefundDesk faster by running
  tool calls in parallel and dropping per-result validation. That session first measured the code and
  pushed back. We told it to proceed.
- **Answers are kept out of reach.** Branch names are neutral (`hist/a`…`hist/f`). The answer key
  lives only in this repo ([`bench/ground_truth.json`](bench/ground_truth.json)), and Culprit never
  feeds this repo's files to a model.
- **Three of the six bugs turned out invisible to the suite**, which we didn't plan. On `hist/a`, `d`
  and `e`, Culprit's baselines gave 78/78 at the bad head and the gate said `no_regression`. A clean
  result could also mean Culprit missed something, so we didn't take Culprit's word for it. A separate
  strength check ([`bench/strength.md`](bench/strength.md)) ran the full 26-task suite at seeds 3–5,
  which no Culprit baseline uses, on `good-v1.0` and each bad head: **78/78 on all four**, one-sided
  Fisher p = 1.00, 312 runs, $0.711, 0 errors. The raw per-run results are in
  [`evidence/strength-check-glm.jsonl`](evidence/strength-check-glm.jsonl). Reading the code explains
  why:
  - **a:** the `order_id` → `id` rename is consistent across schema, agent, checker and tests.
  - **d:** the shortened prompt kept the over-$500 rule, and a code guard blocks such refunds anyway.
  - **e:** lenient argument defaults only fire when the model omits an argument, and GLM 5.3 never did.

  The benchmark scores a `no_regression` as correct only when such an independent measurement exists.
  Otherwise it's `no_regression_unverified`. So the honest headline is **3 of 3 visible bugs found,
  and 3 correct "nothing to find" results**.
- **The hero bug's visibility was also measured independently:** on the 6 harder retry tasks × 3 seeds,
  `good-v1.0` passed 18/18 and the hero commit `397c427` passed 0/18.

## Limitations

- **Localise and fix are unproven on the real victim.** They have been tested on the fixture only.
  TODO: `culprit localise` / `culprit fix` on `hist/b`.
- **The v2 savings are measured on the fixture only.** The real-victim v2 benchmark isn't done yet.
  The fixture has 5 of 10 tasks sensitive to the planted bug, against 7 of 26 on RefundDesk.
- **The staged baseline can miss a task.** A task that dropped from good to bad but happened to pass
  its single screen run on the bad end gets no further runs. The other dropped tasks still carry the
  signal.
- **One model, one suite.** All published runs used GLM 5.3. Only the hero bug's visibility is
  measured on Claude Sonnet 5.5. A bug the suite can't see is reported as `no_regression`; Culprit
  can't find what the evals don't measure.
- **Task selection is a plain ranking.** It ranks tasks by pass-rate drop. The planned
  neatlogs-trace-based selection isn't built.
- **Budget overshoot.** The budget is checked per batch, so a run can overshoot its cap by up to one
  batch of victim runs (4 by default).
- **The leakage filter is deliberately broad.** It drops harmless lines containing words like "seed".
- **Wall time includes pauses.** It runs from start to finish in the ledger, so it includes any pause
  before a resume.

## Repo map

| Path | What |
|---|---|
| `src/culprit/` | The product: `orchestrator.py` (run loop), `bisect.py`, `stats.py`, `baseline.py` + `reuse.py` (v2), `localise.py`, `fix.py`, `bench.py`, `report.py`, `costs.py`, `entire.py`, `tracing.py` / `readback.py`, `ledger.py` |
| `tests/` | Unit and end-to-end tests on a generated fake victim (`tests/fixtures/make_victim.py`); no model calls, tracing off |
| `bench/` | Scenarios, ground truth, strength checks |
| `evidence/` | Run register, benchmark results, raw check data |
| `business/` | cfo.ai inputs |
| `docs/` | `research.md` (what the neatlogs, Entire and cfo.ai docs support), `neatlogs.md` (tracing contract and readback) |
| `scripts/` | Strength check, v1 vs v2 fixture comparison, trace helpers |
