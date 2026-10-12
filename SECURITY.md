# Security policy

## Supported versions

Security fixes are made for the latest release of `culprit-cli` on PyPI.

## Reporting a vulnerability

Please don't open a public issue. Report it privately through GitHub's private vulnerability
reporting: go to the repository's **Security** tab and choose **Report a vulnerability**.

Include what you found, how to reproduce it, and the impact you expect. We aim to acknowledge reports
within 3 working days and to keep you updated until it's fixed. Please give us a reasonable time to
release a fix before disclosing it publicly.

## What Culprit does with your code and keys

Knowing this helps you judge what counts as a vulnerability:

- **Culprit runs the code it tests.** At every commit it examines, it installs the repo with
  `uv sync --locked` and runs your eval module, as running the repo's own test suite would. Only run
  Culprit on repositories you trust.
- **Keys stay on your machine.** `culprit init` saves keys in `~/.config/culprit/credentials.env`
  with permissions that only you can read. Keys are sent only to the model provider you chose and, if
  you set a neatlogs key, to neatlogs for tracing.
- **A repo's `.env` can supply settings.** Culprit reads only its own settings from a repo's `.env`
  and prints which ones the repo supplied, so a cloned repo can't switch your keys silently.
- **Code changes stay in worktrees.** Culprit creates git worktrees under `.culprit/` and never edits
  your checkout. Fixes are written as patches for you to review.
