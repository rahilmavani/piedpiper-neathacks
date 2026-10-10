# neatHack 2026 build log: Culprit

## Project

- **Name:** Culprit
- **Purpose:** `git bisect` for agent behaviour, with receipts. Given a good ref, a bad ref and an eval suite, Culprit finds the commit that broke an LLM agent, explains why that change was made (from its Entire session), writes the smallest fix that restores quality while keeping the intended gain, and proves it statistically.
- **Problem:** LLM agent quality degrades silently across many commits. Evals are noisy, so classic `git bisect` gives misleading answers, and nobody remembers why a breaking change was made. Reverting it also throws away the intended gain.

## Team

- Team PiedPiper. Member names/handles: *pending, the builder will choose what to publish.*

## Stack

Planned (from `PRD.md`); move items to "used" as they are integrated.

- **Used so far:** Entire CLI 0.11.4 (checkpoints on git refs), neatlogs CLI 0.2.0, `uv`, Claude Code.
- **Planned:** Python + `uv`, SQLite ledger, neatlogs Python SDK for tracing, Anthropic or OpenRouter for LLM calls, cfo.ai for the business plan. The victim agent is `refunddesk`, a separate repo.

## Build log

### 2026-10-10

- **Done:** Bootstrap (Prompt A). Entire is enabled with `git-refs` checkpoints, and the neathack build-log skill is installed at `.claude/skills/neathack/SKILL.md`. Results from the README commit and the `checkpoint explain` risk test are recorded below once they've been run.
- **Planned:** Prompt C, starting with M1 (vertical slice) and the hour-1 risk gates (Entire `checkpoint explain` on a victim commit, plus neatlogs trace readback).

## Demo

- *Pending.* No demo URL yet.

## Known limitations and next steps

- Culprit hasn't been built yet. Next: M1 vertical slice per `PROMPTS.md` (Prompt C).

## Submission

Requirements confirmed from https://neatlogs.com/hackathon (read 2026-10-10):

- [ ] Uses neatlogs, Entire and cfo.ai (cfo.ai business plan covering pricing, costs, revenue, runway)
- [ ] Before/after run of the agent with compared numbers (e.g., two neatlogs traces)
- [ ] neatlogs trace links or screenshots
- [ ] Entire checkpoints or entire-graph output
- [ ] A run where an action failed, showing what the agent did next
- [ ] Building-in-public links tagged #neatHack
- [ ] Public repo with commits dated during the hackathon
- [ ] Demo video (the length limit isn't on the page; the PRD says ≤ 3 min, *pending confirmation*)
- [ ] Submit on X by quoting the official neatlogs post with team, name, project, public repo and demo. Window: Mon 12 Oct 2026, 7:00–11:55 PM IST

Judging weights (published): agent 30%, use of neatlogs/Entire/cfo.ai 25%, demo video 20%, building in public 15%, usefulness/originality 10%.
