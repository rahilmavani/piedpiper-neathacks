# Culprit

git bisect for AI agent behaviour. When your agent's eval suite gets worse, Culprit finds the commit
that did it. Evals are noisy, so it runs each step several times, decides with 95% confidence
intervals, and resamples when the answer is unclear. It then reads why the change was made, finds the
responsible lines, and writes a fix that it verifies on held-out tasks.

You bring your own model key. Culprit runs on your machine and only creates git worktrees under
`.culprit/`; it never edits your checkout.

## Install

```bash
uv tool install culprit-cli     # puts the `culprit` command on your PATH
```

Just trying it? `uvx culprit-cli init` runs it without installing.

Needs Python 3.12+, [uv](https://docs.astral.sh/uv/) and git.

## What your agent's repo needs

- **A git history** with a known-good ref (a tag or commit) and a worse one.
- **A uv project with a committed `uv.lock`.** Each commit is installed with `uv sync --locked`; a
  commit that won't install is skipped, as `git bisect skip` does.
- **An eval suite**: one file per task in a directory (default `evals/`).
- **An eval module** that runs one task and prints one JSON line:

  ```bash
  python -m myagent.eval --task refund_small_order --seed 0
  # {"passed": true}          optional: "cost", "latency_ms", "tokens", "error"
  ```

## Set up and run

```bash
cd my-agent
culprit init                                       # your keys (once), eval module and suite
culprit run --good v1.0 --bad HEAD --budget-usd 3  # find the commit
culprit fix <run_id>                               # localise the lines and verify a fix
culprit report <run_id>                            # markdown and HTML report
```

## Keys

`culprit init` asks once for an Anthropic or OpenRouter key, and optionally a neatlogs key for
tracing. It saves them in `~/.config/culprit/credentials.env`, readable only by you, so every repo you
set up uses them. Run `culprit init --keys` to change them.

To override a saved key, set it in your repo's `.env` (for that repo only) or in your shell. The shell
wins, then the repo's `.env`, then the saved setup. The settings Culprit reads are `ANTHROPIC_API_KEY`,
`OPENROUTER_API_KEY`, `NEATLOGS_API_KEY`, `VICTIM_MODEL` and `CULPRIT_MODEL`. It ignores everything
else in a repo's `.env`, but your agent's own runs get the whole file. When a repo's `.env` supplies one of
these settings, Culprit prints which ones, so a cloned repo can't switch your keys silently.

With an Anthropic key, Claude Sonnet 5.5 is used; otherwise GLM 5.3 via OpenRouter. Set
`VICTIM_MODEL` or `CULPRIT_MODEL` to choose other models from the same provider.

Run Culprit only on repos you trust. It runs the repo's code at every commit it tests, just as running
its test suite would.

## Other commands

| Command | What it answers |
|---|---|
| `culprit ci --base main --head HEAD` | Is this pull request a regression? Exit 0 clean, 1 regression (writes a PR comment), 2 undecided |
| `culprit drift --ref v1.0` | Did the model change underneath us? Re-runs a recorded good ref with the same seeds |
| `culprit audit --ref HEAD` | Which realistic regressions would our suite miss? Mutation testing for agents |
| `culprit resume <run_id>` | Continue a stopped run, for example after it hit `--budget-usd` |

## Cost

You pay your model provider for your agent's runs and Culprit's own model calls. On our test agent
(26 tasks, 3 runs each) a bisect cost between $0.04 and $1.74 depending on the model. `--budget-usd`
is a hard cap; a run stops there and can be resumed.

Documentation: https://culprit-site.vercel.app/docs/

Licensed under the Apache License, Version 2.0.
