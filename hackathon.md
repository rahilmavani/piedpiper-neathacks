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
- **Handover:** the second builder took over from `HOW_IT_WORKS.md` (Sat evening).
- **Fixed: decision gates, from review (branch `fix/decision-gates`, fixture only, $0):**
  - **Regression gate.** It now uses a one-sided Fisher exact test (p < 0.05) instead of "95% intervals don't overlap".
    - The overlap rule called 57/60 vs 48/60 noise (Fisher p = 0.012), so a planted bug that breaks 3 of 20 tasks would have ended as `no_regression`.
    - On a perfect 78/78 baseline, 1–2 flaky failures still count as noise (p = 0.50 / 0.25).
  - **Infrastructure failures are no longer agent failures.**
    - Victim runs that hit 429/5xx/overloaded/connection errors, time out, or print no JSON are retried twice with backoff, and are never recorded as failed tasks.
    - Bad keys, bad config and unknown models stop the run with `infra_error`, which `culprit resume` continues.
    - The commit's own crashes (e.g. `KeyError`) still count as failures.
  - **Widening only adds tasks that dropped from good to bad.** If none did, it adds more repetitions of the same tasks instead. Before, it added tasks that pass on both ends: they can't tell good from bad, and they push the threshold up.
  - **Resume reuses the run's recorded good and bad SHAs**, so a branch that moves mid-run can't change the range. An empty range stops before the baselines.
  - 57 tests pass (19 new).
- **Finding worth posting:** "do the 95% intervals overlap?" sounds rigorous, but as a significance test it is far stricter than 5%. On our 26-task suite, any planted bug that breaks fewer than about 3 tasks would have been reported as noise. The other five branches haven't been measured yet, so we don't know how many that is.
- **Done: OpenRouter fallback.** With `ANTHROPIC_API_KEY` set, both apps use Claude Sonnet 5.5; with only `OPENROUTER_API_KEY`, they use GLM 5.3 (`z-ai/glm-5.3`, $0.039/$4.80 per MTok from OpenRouter's listing).
  - Culprit picks the victim model once per run, records it in the ledger and passes `LLM_PROVIDER`, `VICTIM_MODEL` and the price to every victim commit, so all commits are judged by the same model.
  - Resuming without that run's key stops with `infra_error`. 68 Culprit tests and 31 RefundDesk tests pass.
- **Measured: GLM 5.3 as the victim** (OpenRouter, temperature 0 accepted):
  - One smoke run passed for $0.0066.
  - Hero check, the 6 harder tasks × 3 seeds: `good-v1.0` **18/18**, hero commit `397c427` **0/18**, the same as on Sonnet 5.5. 36 runs, $0.134 total, about $0.0037 per run, 0 infrastructure errors.
- **Finding worth posting:** the hero bug is just as visible with a ~4× cheaper victim model, so the benchmark can run on GLM.
- **Done: first real Culprit run (M1 exit on the real victim).** Run `ff50e3620fdd`, trace `d80e61a81918c7eb3ffd917a2509efb0`, `good-v1.0..origin/hist/b`, GLM 5.3 victim, suite pinned at RefundDesk `main` `ba86ed0`.
  - Baselines: good 78/78 vs bad 57/78 (Fisher p ≈ 0).
  - Discriminating tasks: the 6 harder failed-payload tasks plus `refund_failed_payload_once`.
  - Bisect: `22a37db` install failed → SKIP; `81c0753` 21/21 GOOD; `c9a132f` 3/21 BAD; `8793325` 21/21 GOOD; `397c427` 1/21 BAD.
  - **Culprit: `397c427` "perf(agent): run tool calls in parallel and drop per-result validation"** (95% Wilson), which is the planted hero commit.
  - 240 victim runs, 0 infrastructure errors, **$0.60**, 12.5 min.
  - Intent fell back to the commit message and diff, because the `entire` CLI isn't installed on this machine. The leakage filter dropped 1 harmless line containing "seed".
- **Moment worth screenshotting:** the run log, from `22a37dbfff install failed → SKIP` to `Culprit: 397c427…`, in four decisions.
- **Done: M3 `culprit bench` (branch `feat/bench`, fixture only, $0).**
  - `bench/scenarios.yaml` (six branches, `good-v1.0` → `origin/hist/<x>`) and `bench/ground_truth.json`: full culprit SHAs, branch heads, uninstallable commits (`22a37db`, `2ad118e`), responsible hunks as file + line range from `git show`, and the intended-gain metric. All positions re-checked against `git rev-list` in the RefundDesk clone (read-only).
  - `culprit bench --tag v1|v2` runs each scenario through the normal orchestrator, one after another, and scores it: `correct`, `wrong`, `correct_no_regression`, `missed`, `no_regression_unverified`, `ambiguous_*` or `incomplete`, plus victim runs, cost, wall time, skipped commits, run ID and neatlogs trace IDs. It writes `evidence/bench-<tag>.md` and `.json`.
  - `--score-runs <id,...>` / `--score-latest` score runs already in the ledger, matched to scenarios by their recorded good/bad SHAs, so the paid runs on `hist/*` don't need repeating. Scoring opens the ledger **read-only**, so it is safe while another process is still writing it.
  - Leakage guard: only resolved SHAs reach the orchestrator (no scenario names, no answers); bench refuses ground-truth files inside the victim repo.
  - Fixture bench, 2 scenarios: the planted break was found (`correct`, with the unbuildable commit SKIPped), and a clean range ended `correct_no_regression` (Fisher p = 0.69). Accuracy 2/2, 180 fake runs. 86 tests pass (18 new).
  - Tests can no longer export traces: an autouse `tests/conftest.py` fixture unsets `NEATLOGS_API_KEY` and keeps tracing off. (The fixture traces that did reach neatlogs came from a manual `culprit bench` CLI demo, which loads `.env`.)
- **Decision:** a `no_regression` result is only scored as correct when ground truth says so: no bug planted in the range, or a measurement on that victim model showed the bug is invisible. Otherwise it's `no_regression_unverified` (not counted as accurate) until the strength check is done. Only `hist/b` has a visibility measurement (GLM 5.3 and Sonnet 5.5: 18/18 → 0/18). Visibility is never taken from a Culprit run's own baselines (that would be Culprit grading itself); it must come from the separate strength check (Prompt G step 4) recorded with run IDs in `bench/strength.md`.
- **Decision:** hist/a ("API consistency") and hist/e ("fewer rejected tool calls") get intended-gain metric `null`, because their claimed gain isn't latency, tokens or cost.

- **Done: `tests/conftest.py`** (committed with bench as `94d0a26`). Every test runs without `NEATLOGS_API_KEY`, with tracing off and with both provider calls blocked, so tests can't export traces or spend money.
- **Done: M5 part 1, the Localiser (PRD §8.3; branch `feat/bench`, fake victim only, $0).**
  - It splits the culprit diff into hunks, leaving out `evals/`, which the pinned suite replaces.
  - One AI call (`llm.structured`) ranks the hunks from the diff, the leak-filtered intent and the telling tasks' results. Its order is stored, so resume never asks twice, and diff order is the fallback if the call fails.
  - It is a separate command, `culprit localise <run_id>`, that reads a finished, found run from the ledger. The orchestrator gained only a step-kind prefix and a filter, because another session is changing it in parallel.
  - It reverse-applies the top 3 hunks one at a time on the culprit commit, each in its own worktree. Each revert is judged by the same Wilson rule, resampling, budget and resume as a bisect step, then pairs are tried (capped at 3), then the answer falls back to the whole commit.
  - **Fake-victim results:**
    - Multi-hunk culprit, with the fake model wrong on purpose (ranking a harmless timeout change first): that revert stayed BAD, the next one flipped the commit to GOOD, and the hunk was named correctly.
    - Culprit that needs two hunks together, with no model available (diff-order fallback): every single revert stayed BAD, and a pair flipped it.
    - Resume reran nothing and made no new model call.
  - 96 tests pass (10 new).
- **Dry check on the real culprit commits** (git archive trees, no victim runs): every hunk of all six commits reverse-applies on its own (9, 16, 3, 1, 6 and 3 hunks).
- **Finding worth posting:** on the hero commit, "revert one hunk at a time" can't work. The retry-loop hunk calls `validate_tool_result`, which another hunk of the same commit deleted, so only the pair restores behaviour. A localiser that stops at single hunks would blame the whole commit.
- **Decision:** reverts are applied on the culprit commit, not on the branch head, so later commits can't block a hunk. The Fixer will work on the head.
- **Not yet:** failing-trace contents from neatlogs in the ranking prompt. The prompt uses the ledger's pass counts, errors and task definitions for now.
- **Moment worth screenshotting:** the fake-victim log, `hunk ranking (llm): h4, h3, h1`, then `localise:h4: 1/15 … → BAD`, then `localise:h3: 14/15 … → GOOD`, then `responsible: hunk 3 (refunddesk/agent.py:3)`.

## Demo

- *Pending.* No demo URL yet.

## Known limitations and next steps

- Built: M1 and M2 (bisect, noise handling, recovery) and M3's `culprit bench`. Not built: localiser, fixer/verifier, report, `export-costs`. Next: score the `hist/*` runs with `culprit bench --tag v1 --score-latest`, then M4.

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
