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

- **Done:** Bootstrap (Prompt A). Entire is enabled with `git-refs` checkpoints, and the neathack build-log skill is installed at `.claude/skills/neathack/SKILL.md`.
- **Entire risk test (PRD §20), result:** `entire checkpoint explain <full 40-char sha>` works on an arbitrary commit (`8d1cc81…`, checkpoint `01M4JC8F8S4VQVRD1ACZBQR8F4`). `--json` gives parseable metadata (session, model, files, token usage) but **no intent text**. The intent and prompts only appear in the default text view or the `--transcript` JSONL. A commit made before Entire was enabled returns exit 1 with "no Entire-Checkpoint trailer", which is our fallback trigger.
- **Where checkpoints live:** each commit carries an `Entire-Checkpoint: <id>` trailer, and the data sits under git refs `refs/entire/checkpoints/<XX>/<id>`, pushed to `origin` by Entire's hook. A plain `git clone` has none of these refs, but `entire checkpoint explain` fetched the single ref it needed on demand and worked in the fresh clone.
- **Finding worth posting:** Entire's `--json` export omits the human intent on purpose (no transcript bytes), so tools that want the "why" must parse the text view or the transcript.
- **Done (Prompt C, in progress):** Culprit core slice: SQLite ledger (idempotent writes), worktree sandbox with `uv sync --locked`, eval runner, deterministic bisect with `git bisect skip` semantics, and resume by memoised replay. Tested against a throwaway fixture victim (`tests/fixtures/make_victim.py`, no LLM): culprit found in ~2.5 s, with the unbuildable midpoint commit SKIPped. 25 unit tests pass.
- **Moment worth screenshotting:** the first fixture run, where the midpoint commit failed `uv sync --locked` and was skipped, its neighbour was tested, and the bisect still landed on the breaking commit.
- **Decision:** the leakage filter ignores `main`, `master` and `HEAD` as ref names because they carry no benchmark information and would strip ordinary prose. In the commit-message+diff fallback, only the message is filtered, because the diff is code, not Entire text.
- **Planned:** neatlogs integration of Culprit, and the hour-1 gates against the real victim once `refunddesk` has checkpointed commits (it currently has one commit with no checkpoint).

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
