# Contributing to Culprit

Thanks for your interest in Culprit. Bug reports, fixes, docs and new ideas are all welcome.

By contributing, you agree that your contributions are licensed under the
[Apache License, Version 2.0](LICENSE), the same license as the project. Please also follow our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to help

- **Report a bug.** Open an issue with the command you ran, what you expected, what happened, and
  your Culprit, Python and OS versions (`uv tool list` or `pip show culprit-cli` shows Culprit's).
  Please remove keys and private paths from any output.
- **Suggest a feature.** Open an issue describing the problem first, before the solution. Culprit's
  verdicts have to stay defensible, so changes to the statistics need a short argument for why the
  new rule is still correct under noise.
- **Try it on your agent.** Results on real agents are the evidence Culprit lacks most. An issue
  describing what worked and what didn't is very useful, even without code.
- **Security issues:** don't open a public issue. Follow [SECURITY.md](SECURITY.md).

## Development setup

You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and git.

```bash
git clone https://github.com/rahilmavani/piedpiper-neathacks.git culprit
cd culprit
uv sync
uv run pytest -q
```

The test suite makes no model calls, needs no API keys or network, and keeps tracing off. Tests build
throwaway fake agents with `tests/fixtures/make_victim.py`, so you can also exercise the whole CLI for
free:

```bash
uv run python tests/fixtures/make_victim.py /tmp/victim --commits 14 --breaks-at 10 \
    --unbuildable-at 7 --noisy-from 9 --noisy-pass 0.6
uv run culprit run --repo /tmp/victim --good good-v1.0 --bad main
```

Anything that runs a real agent against a model costs money. Never run a paid command from a test,
and set `--budget-usd` when you try one by hand.

## Making a change

1. Fork the repo and create a branch from `main`.
2. Keep the change focused: one fix or feature per pull request.
3. Add or update tests. Every behaviour change needs a test that fails without it, on a fake agent
   from `tests/fixtures/`, with any model call replaced by a fake.
4. Run `uv run pytest -q` and make sure it passes.
5. Update the docs the change affects: `README.md`, `PYPI.md` (the PyPI page) or the CLI help text.
6. Add a line under "Unreleased" in [CHANGELOG.md](CHANGELOG.md) if users will notice the change.
7. Open a pull request that explains what changed and why, and how you tested it.

## Conventions

- **Match the surrounding code.** Follow the style, naming and comment density of the module you're
  editing. Keep functions small and side effects explicit.
- **Every verdict must be reproducible from the ledger.** If you add a decision, record its inputs in
  the ledger (`src/culprit/ledger.py`) so `culprit report` can show why it was made.
- **Never count an infrastructure error as an agent failure.** API errors, timeouts and broken
  installs must be retried, skipped or stop the run; they must never become a failed task.
- **Keep answers away from models.** Benchmark ground truth (`bench/`) must never be sent to a model,
  written into a victim repo, or included in a prompt.
- **Numbers in docs need a source.** Any result quoted in the README or docs must come from a file in
  `evidence/` or a command anyone can re-run.
- **Write plainly.** User-facing text (CLI output, errors, docs) should say what happened and what to
  do next, in short sentences.

## Commit messages

Use a short, imperative summary line, optionally with a scope, for example
`fix(bisect): skip commits whose lockfile fails to install`. Explain the why in the body when it isn't
obvious from the diff.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml` and move "Unreleased" entries in `CHANGELOG.md` under the new
   version.
2. Run `uv run pytest -q`, then `uv build`.
3. Publish with `uv publish`, tag the release `vX.Y.Z`, and push the tag.
