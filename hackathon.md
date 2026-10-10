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
- **Done:** neatlogs integration of Culprit (details in `docs/neatlogs.md`). Every run is one `culprit` WORKFLOW trace with session = run_id, and git, worktree, install, victim-run, decision and Entire steps are TOOL spans. `culprit verify-trace` reads a run back through the CLI and audits it.
  - Fixture bisect trace `3e8d50b4584b831185c65a33007c7533`: finalized, 151 spans, all parented, counts match the ledger.
  - Error trace `af423d7e5c1796cf4c7600dd29cc636b`: failing span and root are ERROR.
  - LLM capture check `ffdf497989747bf30856935f187e6013`: LLM span under AGENT, tokens match.
  - Overall status: PARTIAL. Victim traces and the Culprit LLM stages don't exist yet.
- **Failures fixed:**
  - `neatlogs.trace()` left spans `OK` when an exception passed through, so the first error trace read back as healthy. Fixed by recording the exception and setting ERROR explicitly.
  - Inside `uv run`, `neatlogs` resolved to the Python SDK's script instead of the CLI. Readback now looks up the CLI binary explicitly.
- **Finding worth posting:** the neatlogs read API returns no custom span attributes, so "is run_id on every span?" can't be verified from attributes alone. We also put the run context into each span's input JSON so the audit can prove it.
- **Open question:** neatlogs priced a `claude-sonnet-5-5` call at $3/$15 per MTok, versus the $2/$10 list price Culprit uses. Both numbers are kept; to be raised with neatlogs.
- **Moment worth screenshotting:** `culprit verify-trace` printing PASS with span counts that match the ledger exactly.
- **Entire gate on the victim (re-run when `refunddesk` got checkpointed commits): PASS with a fix.** `entire checkpoint explain <full sha>` on `819b630` (run from `../refunddesk`) exits 0, resolves checkpoint `01M4JDJRHCWGDWM9CBHTY5Z2M5`, and `--json` parses. However, its `## Intent` was `<task-notification>`, and on `4cfc31e` it was `*(no prompt recorded)*`. Culprit now falls back to the session's typed prompts from `--transcript`. A commit with no checkpoint (`595fd28`) still takes the message+diff fallback.
- **Decisions (from the builder):** cost source of truth is Anthropic's list price ($2/$10 for `claude-sonnet-5-5`). neatlogs' $3/$15 is recorded in `BLOCKERS.md` and `evidence/neatlogs-cost-discrepancy.md` and not used. OpenRouter dropped; Anthropic only.
- **Done (M2, on the fixture victim):**
  - Wilson 95% decision rule against a threshold computed over the same task mix as the runs, with a baseline significance check (overlapping intervals → `no_regression`).
  - Resampling: k more repetitions, then widen to more tasks. At the cap the point estimate decides and the step is flagged `low_confidence`, which is reflected in the run's confidence.
  - Per-run and global ($75) budget caps that stop with the best current range; `culprit resume --budget-usd`.
  - SIGKILL mid-step, then resume: 78 → 150 task runs, 0 duplicates.
  - Recorded run `bcccdb9631a9` (trace `3498c9e1e497ed665200cfaba3a2cb86`) shows SKIP and INCONCLUSIVE → resample → widen → low_confidence in one run. All traces read back and PASS. 31 tests pass.
- **Finding worth posting:** a commit whose real pass rate sits right at the threshold (0.6 vs 0.5) stays INCONCLUSIVE after doubling the sample (18/30, CI [0.42, 0.75]). Widening to more tasks moved the threshold to 0.64, because the extra tasks pass on both sides. Culprit says "low confidence" instead of pretending.
- **Moment worth screenshotting:** the run log line `32/45 CI [0.57, 0.82] vs t=0.64 → INCONCLUSIVE → GOOD (low_confidence)`.
- **Real-victim interface check (read-only, one paid run):** `good-v1.0` installs, the `hist/b` pin commit `22a37db` fails `uv sync --locked` (python-dotenv==1.2.99 doesn't exist) and would be SKIPped, its revert installs, discovery finds 20 tasks, and one eval run passed ($0.0169, 15 s). Estimated R1 bisect: ~220 runs ≈ $3.70, over the $3 per-run cap; budget decision pending with the builder.
- **Fixed (fixture):** `--noisy-from` on the commit after `--unbuildable-at` displaced the pin revert, leaving every later commit uninstallable. Each commit now applies every change due at it; regression test added.
- **Done: pinned eval suite.** Every commit in a run is judged by one suite snapshot: `evals/` at the victim's `main` (`--suite-ref`), or a directory on disk (`--suite /path`). The snapshot is copied into each worktree before evaluation, and the ledger records `suite_source` + `suite_sha` (commit SHA, or a `sha256:` digest for a path). Resume rebuilds the recorded snapshot even if `main` has moved, and refuses a path suite that changed. Fixture run `4864e9e2df12` (trace `8992ef2cf8b254eb645bd6c1ef293695`, audit PASS): task `t11` exists only on `main` but ran at every commit with 0 errors. 38 tests pass. Not run on the real victim yet, by instruction.
- **Decision:** worktree reuse now does `git reset --hard` + `git clean -fd` (ignored `.venv` kept) to undo the copied suite, instead of discarding the worktree as dirty and reinstalling.
- **Waiting on:** M1's real-victim exit (R1 end to end) needs the R1 change on `hist/b` (still at its pause point) and the budget decision. M2's "all six branches run" needs `hist/a`…`hist/f` finished.

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
