# Culprit

**`git bisect` for agent behaviour, with receipts.**

[![PyPI](https://img.shields.io/pypi/v/culprit-cli)](https://pypi.org/project/culprit-cli/)
[![Python](https://img.shields.io/pypi/pyversions/culprit-cli)](https://pypi.org/project/culprit-cli/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

When your agent's eval suite gets worse, Culprit finds the commit that did it. Evals are noisy, so it
runs each step several times, decides with 95% confidence intervals, and resamples when the answer is
unclear. It then reads why the change was made, finds the responsible lines, and writes a fix that it
verifies on held-out tasks. Every verdict is recorded in a local ledger and can be traced in neatlogs.

A real run, abridged:

```
gate     good 78/78 · bad 57/78 · Fisher p = 1.0e-7 → regression
skip     22a37db  build(deps): pin python-dotenv to 1.2.99   (won't install)
good     81c0753  21/21  CI [0.85, 1.00]
bad      c9a132f   3/21  CI [0.05, 0.35]
good     8793325  21/21  CI [0.85, 1.00]
bad      397c427   1/21  CI [0.01, 0.23]
culprit  397c427  perf(agent): run tool calls in parallel and drop per-result validation
```

Website and documentation: **https://culprit-site.vercel.app** ([docs](https://culprit-site.vercel.app/docs/))

## Why

Agent quality can degrade quietly over many commits: a prompt tweak here, a "make it faster" refactor
there, often written by a coding agent. Finding the commit responsible is hard:

- **Evals are noisy.** The same commit can pass a task once and fail it the next time, so plain
  `git bisect` with one run per commit can blame the wrong commit.
- **Old commits break.** A bad dependency pin in the middle of the range stops a naive bisect.
- **Nobody remembers why.** Reverting the culprit also throws away whatever it was meant to improve.

## Install

```bash
uv tool install culprit-cli     # puts the `culprit` command on your PATH
uvx culprit-cli --help          # or run it without installing
```

Culprit needs Python 3.12+, [uv](https://docs.astral.sh/uv/) and git. The
[Entire CLI](https://docs.entire.io) is optional; with it, Culprit can read why a commit was made.

## Quickstart

Your agent's repo needs:

- **a git history** with a known-good ref (a tag or commit) and a worse one;
- **a uv project with a committed `uv.lock`**, since each commit is installed with `uv sync --locked`;
- **an eval suite**: one file per task in a directory (default `evals/`);
- **an eval module** that runs one task and prints one JSON line:

  ```bash
  python -m myagent.eval --task refund_small_order --seed 0
  # {"passed": true}          optional: "cost", "latency_ms", "tokens", "error"
  ```

Then:

```bash
cd my-agent
culprit init                                       # your keys (once), eval module and suite
culprit run --good v1.0 --bad HEAD --budget-usd 3  # 1. find the commit
culprit localise <run_id>                          # 2. find the responsible lines
culprit fix <run_id>                               # 3. write and verify a minimal fix
culprit report <run_id>                            # 4. markdown and HTML report
```

`culprit help` lists every command in the order you use them.

### Keys

Culprit runs on your machine with your own model key. `culprit init` asks once for an Anthropic or
OpenRouter key, and optionally a neatlogs key for tracing, and saves them in
`~/.config/culprit/credentials.env`, readable only by you. A key in your shell overrides a repo's
`.env`, which overrides the saved one.

With an Anthropic key, Claude Sonnet 5.5 is used; otherwise GLM 5.3 via OpenRouter. Set
`VICTIM_MODEL` or `CULPRIT_MODEL` to pick other models from the same provider.

Culprit runs the repo's code at every commit it tests, as the repo's own test suite would, so only
run it on repos you trust. It only creates git worktrees under `.culprit/`; it never edits your
checkout.

## Commands

| Command | What it answers |
|---|---|
| `culprit run --good <ref> --bad <ref>` | Which commit made the agent worse? |
| `culprit localise <run_id>` | Which hunks of that commit are responsible? |
| `culprit fix <run_id>` | What's the smallest fix that keeps the change's intent? Verified on held-out tasks |
| `culprit report <run_id>` | The run's receipts, as markdown and a static HTML page |
| `culprit ci --base <ref> --head <ref>` | Does this pull request regress the agent? Exit 0 clean, 1 regression (with a PR comment), 2 undecided. Example workflow: [`examples/github-action/culprit.yml`](examples/github-action/culprit.yml) |
| `culprit comment <run_id>` | The PR comment for a finished run, from the ledger alone ($0, no network) |
| `culprit drift --ref <ref>` | Did the model change underneath us? Re-runs a known-good ref with the same suite and seeds, and compares |
| `culprit audit --ref <ref>` | Which realistic regressions would the suite miss? Mutation testing for agents |
| `culprit resume <run_id>` | Continue a stopped run (budget cap, API outage) without redoing finished work |
| `culprit verify-trace <run_id>` | Read a run's traces back from neatlogs and check them |
| `culprit export-costs` | Cost, agent runs and wall time per run, as CSV |

## How it works

1. **Pins the eval suite.** One snapshot of the suite judges every commit in the range, and the
   ledger records its SHA.
2. **Checks there is something to find.** It measures both ends, and a one-sided Fisher exact test
   (p < 0.05) must show that good really beats bad. Otherwise it reports `no_regression` instead of
   chasing noise.
3. **Bisects with statistics.** Each step runs only the tasks that dropped, k times each. A 95% Wilson
   interval wholly above or below the threshold decides GOOD or BAD. If it straddles, Culprit
   resamples, and it flags any verdict it had to guess (`low_confidence`).
4. **Skips what won't install.** A commit that fails `uv sync --locked` is skipped and a neighbour is
   tested, as `git bisect skip` does.
5. **Explains the culprit.** It reads the commit's [Entire](https://entire.io) checkpoint, the
   coding-agent session that wrote it, and falls back to the commit message and diff.
6. **Localises and fixes.** It reverts hunks, singly and then in pairs, until the agent recovers. It
   then writes a minimal fix and verifies it on the full and held-out suites. The fix must keep the
   change's intended gain.

Temporary API errors (429, 5xx, timeouts) are retried and never counted against a commit. A bad key
or a budget cap stops the run cleanly, and `culprit resume` continues it.

## Results

All results come from three agents we wrote for testing, each with six planted regressions, so every
verdict can be checked against a known answer. Every number is in [`evidence/`](evidence/).

- **60 scored bisects across 3 agents and 6 victim models: 57 correct, 3 missed, 0 wrong commits.**
  The 3 misses are ClinicDesk on Llama 3.1 8B, which passed only 46% of its suite even on the good
  version; there, the gate didn't call a regression.
  ([`evidence/MODELS.md`](evidence/MODELS.md), [`evidence/DOMAINS.md`](evidence/DOMAINS.md))
- **Whether a commit is a regression depends on the model.** Several planted commits remove a safety
  net that only a weaker model needs. Culprit reported no regression on GLM 5.3 and named the exact
  commit on Llama 3.1 8B. Both are correct.
- **The hero bug, end to end:** Culprit found `397c427`, localised it to two hunks that only matter
  together, and verified a fix at 96/96 (held-out 18/18, against 15/18 for the broken head), for
  $1.13. ([`evidence/RUNS.md`](evidence/RUNS.md), [report](evidence/reports/report-978624283c27.md))
- **v1 → v2:** staged baselines cut agent runs by 48% and cost by 44%, with the same 6/6 accuracy.
  ([`evidence/bench-v1.md`](evidence/bench-v1.md), [`evidence/bench-v2.md`](evidence/bench-v2.md))
- **Cost per bisect** on a 26-task suite with 3 runs per task: $0.04 (DeepSeek V4.1 Flash) to $1.74
  (Claude Sonnet 5.5), with the same 6/6 accuracy on all five models tested on it.
- **`culprit drift`** on the known-good release: STABLE, 78/78 then 78/78, for $0.19.
- **`culprit audit`:** the suite catches 4 of 8 realistic regressions, and each miss comes with a
  task that would catch it. ([report](evidence/audit-refunddesk-glm.md))

## Limitations

- **The bugs are planted.** We wrote the test agents and their regressions, through real coding-agent
  sessions, so that answers can be scored. Culprit hasn't yet been measured on someone else's
  production agent.
- **Culprit can't find what your evals don't measure.** A regression the suite can't see is reported
  as `no_regression`. `culprit audit` helps you find those gaps.
- **A weak or very noisy model can hide a real drop.** The gate then reports no regression rather
  than guess.
- **Localise and fix have one fully measured case,** the hero bug. Its claimed speed-up didn't exist
  (median latency 7,086 ms good vs 7,138 ms bad), so the "keeps the intended gain" check hasn't yet
  been tested against a real gain.
- **The staged baseline can miss a task** that dropped but passed its single screening run. The other
  dropped tasks still carry the signal.
- **Budgets are checked per batch,** so a run can overshoot its cap by up to one batch of agent runs.

## Integrations

- **[neatlogs](https://docs.neatlogs.com):** each Culprit run is one trace (session = run ID), and
  each agent run is its own trace, tagged with run, commit, task and repetition. `culprit verify-trace`
  audits a run's traces, and the localiser reads failing runs' tool-call sequences back to rank hunks.
  Tracing is optional. Details: [`docs/neatlogs.md`](docs/neatlogs.md) and
  [`evidence/NEATLOGS.md`](evidence/NEATLOGS.md).
- **[Entire](https://entire.io):** Culprit reads the culprit commit's checkpoint to recover the
  developer's intent. Only that commit's checkpoint is read, and a filter strips anything that could
  leak benchmark answers.
- **cfo.ai:** the business model was built from Culprit's measured costs (`culprit export-costs`).
  See [`business/cfo-plan.md`](business/cfo-plan.md); the prices in it are hypotheses.

## Development

```bash
git clone https://github.com/rahilmavani/piedpiper-neathacks.git culprit
cd culprit
uv sync
uv run pytest -q          # no model calls, no network, tracing off
```

Try a full bisect for free on a generated fake agent:

```bash
uv run python tests/fixtures/make_victim.py /tmp/victim --commits 14 --breaks-at 10 \
    --unbuildable-at 7 --noisy-from 9 --noisy-pass 0.6
uv run culprit run --repo /tmp/victim --good good-v1.0 --bad main
```

| Path | What |
|---|---|
| `src/culprit/` | The CLI and engine: `orchestrator.py` (run loop), `bisect.py`, `stats.py`, `baseline.py` + `reuse.py`, `localise.py`, `fix.py`, `drift.py`, `audit.py`, `ci.py`, `report.py`, `entire.py`, `tracing.py`, `ledger.py` |
| `tests/` | Unit and end-to-end tests on generated fake agents (`tests/fixtures/make_victim.py`) |
| `bench/` | Benchmark scenarios and ground truth for `culprit bench` |
| `evidence/` | Every published number: run register, benchmarks, reports, ledger snapshots |
| `business/` | Cost exports and the cfo.ai business plan |
| `docs/` | The neatlogs tracing contract |
| `examples/` | A GitHub Actions workflow for `culprit ci` |
| `scripts/` | Benchmark and evidence helpers |

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, conventions and how to
propose a change, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). To report a security issue, follow
[SECURITY.md](SECURITY.md) instead of opening a public issue.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE).

Culprit was built by Team PiedPiper at neatHack 2026.
