# How Culprit and RefundDesk work: complete guide

> Team PiedPiper · neatHack 2026 · written Sat 10 Oct 2026, ~17:00 IST.
> This describes the code **as it exists now**, not the plan. Where the plan (PRD.md) and the code differ, this guide says so. Anything not built yet is marked **NOT BUILT**.

---

## Contents

1. [The idea in one minute](#1-the-idea-in-one-minute)
2. [Words used in this guide](#2-words-used-in-this-guide)
3. [The two repos and why there are two](#3-the-two-repos-and-why-there-are-two)
4. [RefundDesk, the test subject](#4-refunddesk-the-test-subject)
5. [The planted bugs (the six branches)](#5-the-planted-bugs-the-six-branches)
6. [Culprit, the detective](#6-culprit-the-detective)
7. [A complete run, step by step](#7-a-complete-run-step-by-step)
8. [The statistics, explained simply](#8-the-statistics-explained-simply)
9. [Recovery: what happens when things go wrong](#9-recovery-what-happens-when-things-go-wrong)
10. [The ledger (Culprit's memory)](#10-the-ledger-culprits-memory)
11. [How the three required tools are used](#11-how-the-three-required-tools-are-used)
12. [Keeping the answers secret (leakage guard)](#12-keeping-the-answers-secret-leakage-guard)
13. [Money: what things cost](#13-money-what-things-cost)
14. [Commands you can run](#14-commands-you-can-run)
15. [What is built and what is not](#15-what-is-built-and-what-is-not)
16. [Known issues and oddities](#16-known-issues-and-oddities)
17. [What happens next](#17-what-happens-next)
18. [Appendix A: every RefundDesk test task](#appendix-a-every-refunddesk-test-task)
19. [Appendix B: every commit on every branch](#appendix-b-every-commit-on-every-branch)
20. [Appendix C: file-by-file map](#appendix-c-file-by-file-map)
21. [Appendix D: environment variables and runtime paths](#appendix-d-environment-variables-and-runtime-paths)

---

## 1. The idea in one minute

Teams that build AI agents keep changing them: prompts, models, tools, retry settings. Often a coding agent writes the change. Sometimes the agent quietly gets worse. Finding *which* change broke it is painful, for two reasons:

- You have to re-run the tests at many old versions.
- AI agents are **random**: the same version can pass a test one time and fail it the next. A single run per version can't be trusted.

**Culprit** does that search automatically. You give it:

- a version you know was **good** (here, git tag `good-v1.0`)
- a version you know is **bad** (for example, branch `hist/b`)
- a set of **test tasks** (the "eval suite")

Culprit then:

1. **Confirms something really broke.** It runs every test task several times on both versions and checks the difference isn't just luck.
2. **Searches the history by halving it**, like `git bisect`: test the middle commit, keep the half that contains the break, repeat. 14 commits need about 4 tests instead of 14.
3. **Copes with randomness.** It runs each test several times, uses a statistics rule to decide "good", "bad" or "not sure yet", and runs more tests when it isn't sure.
4. **Copes with broken commits.** If a commit won't even install, it skips it and tests a neighbour.
5. **Names the guilty commit**, then asks **Entire** *why* that change was made, using the recorded coding-agent session behind the commit.
6. **Records everything**: every test run, cost and decision goes into a database, and every step is traced in **neatlogs**.

Planned but **NOT BUILT** yet:

- pointing at the exact guilty lines inside the commit
- writing a minimal fix and proving it works
- generating a report

Built but not yet run on all six branches: **scoring itself on a benchmark** (`culprit bench`, [§14](#14-commands-you-can-run)).

To show it working, we built a realistic victim, **RefundDesk**, and planted six bugs in its history. In each case we know the right answer, so we can check Culprit honestly.

---

## 2. Words used in this guide

| Word | Meaning here |
|---|---|
| **Agent** | A program where an AI model decides which tools to call, e.g. "look up order", "issue refund". |
| **Victim** | The agent being investigated, here RefundDesk. |
| **Eval / task / test task** | One scripted customer situation plus an automatic pass/fail check. Example: "customer wants a refund for an $89 order; the refund tool fails once; the refund must still happen exactly once." |
| **Eval suite** | All the tasks together: 26 main tasks and 6 "held-out" tasks. |
| **Repetition (k)** | How many times each task runs on a commit. Default 3. Each repetition uses a different seed (0, 1, 2). |
| **Seed** | A number that makes the fake tool failures repeatable. The same task with the same seed always gets the same injected failures. |
| **Pass rate** | Passes divided by runs, e.g. 28/30. |
| **Bisect** | Finding the first bad commit by repeatedly testing the middle of the remaining range. |
| **Commit / SHA** | One saved change in git; the SHA is its ID (e.g. `397c427`). |
| **Branch** | A named line of commits. Our six test histories are `hist/a` … `hist/f`. |
| **Tag** | A permanent label on one commit. `good-v1.0` marks the known-good version. |
| **Worktree** | An extra checkout of the same git repo in a separate folder. Culprit uses one per commit, so it never touches your real folder. |
| **Wilson interval / CI** | A range like `[0.70, 0.99]`: "we're 95% sure the true pass rate is somewhere in here". See [§8](#8-the-statistics-explained-simply). |
| **Threshold (t)** | The halfway line between the good and bad pass rates. Above it means "good", below it means "bad". |
| **GOOD / BAD / INCONCLUSIVE / SKIP** | Culprit's verdict on a commit. SKIP means "couldn't even install it". |
| **Ledger** | Culprit's SQLite database of everything it did (`.culprit/ledger.sqlite`). |
| **Trace / span** | neatlogs' record of a run: a tree of steps (spans), each with inputs, outputs, timing and errors. |
| **Checkpoint** | Entire's record linking a git commit to the coding-agent session that produced it, including what was asked and why. |
| **Intent** | The "why" behind a commit, taken from its Entire checkpoint. |
| **Planted bug / regression** | A change we deliberately made to RefundDesk that makes it worse. |
| **Fixture** | A tiny fake victim repo that Culprit's tests generate. It has no AI calls, so it's free. |

---

## 3. The two repos and why there are two

```
neathack/
├── piedpiper-neathacks/   ← Culprit (the product)  → github.com/rahilmavani/piedpiper-neathacks (public)
└── refunddesk/            ← RefundDesk (the victim) → github.com/rahilmavani/piedpiper-neathacks-refunddesk (private)
```

**Why separate?**

1. **Clean history.** Culprit bisects RefundDesk's commits. If Culprit's own code lived in the same history, every bisect step would wade through unrelated commits.
2. **Entire records each repo separately.** Culprit reads Entire sessions from the victim repo to find intent. Our planning sessions (which mention the answers) happen in the Culprit repo, so they can never leak into the victim's records.
3. **Parallel work.** One coding session can switch branches in RefundDesk while another builds Culprit, without stepping on each other.
4. **Realism.** A customer would point Culprit at *their* agent repo: `culprit run --repo ../refunddesk …`.

**How they connect at run time.** Culprit never edits the RefundDesk folder. For each commit it wants to test, it:

- creates a worktree under `piedpiper-neathacks/.culprit/worktrees/<sha>`
- installs it with `uv sync --locked`
- runs RefundDesk's own test runner there as a subprocess: `python -m refunddesk.eval --task <id> --seed <n>`
- reads the one line of JSON it prints, which includes passed, cost, latency, tokens and trace ID

Both repos have:
- Entire enabled (`.entire/settings.json`, checkpoints stored as git refs)
- Claude Code hooks that let Entire record sessions (`.claude/settings.json`)
- co-author lines turned off (`includeCoAuthoredBy: false`, empty `attribution`)
- a gitignored `.env` holding `NEATLOGS_API_KEY`, `ANTHROPIC_API_KEY`, `LLM_PROVIDER=anthropic`, `VICTIM_MODEL=claude-sonnet-5-5` and, in the Culprit repo, `CULPRIT_MODEL=claude-sonnet-5-5`

---

## 4. RefundDesk, the test subject

### 4.1 What it is

RefundDesk is a customer-support agent for an online store. A customer writes something like "Order A1009, wrong size shoes, I want my money back". The agent uses tools to look up the order, apply the refund policy, refund or escalate to a human, and email the customer.

- Python 3.12, managed with `uv`. Package `refunddesk` v0.1.0.
- Model: **Claude Sonnet 5.5** (`claude-sonnet-5-5`) via the Anthropic API when `ANTHROPIC_API_KEY` is set, otherwise **GLM 5.3** (`z-ai/glm-5.3`) via OpenRouter. All baseline numbers below were measured on Sonnet 5.5; a GLM run needs its own baseline.
- Temperature 0 is requested. Sonnet 5.5 rejects the temperature setting, so the client detects that and stops sending it (cached in `.cache/refunddesk/sampling.json`).
- The tools are **mocks**: they read and write a JSON file, not a real store. That makes every test fast, free of side effects and repeatable.

### 4.2 The rules the agent follows (system prompt, on `main` and `good-v1.0`)

```
1. Always look up the order with lookup_order before acting on it.
2. Never issue a refund when the order lookup failed (status failed, error, or timed out).
   In that case do not refund; escalate to a human with escalate_to_human and tell the customer.
3. If the order is not found, do not refund; escalate to a human (order_id "unknown" is allowed).
4. Refunds over $500 must be escalated to a human. Never call issue_refund for more than $500.
   A refund of exactly $500.00 or less may be issued by you.
5. At most one refund per order; never refund an already-"refunded" order; refund the full
   amount unless the customer asks for a specific smaller amount.
6. After a refund or escalation, send the customer one short email (to the address they asked
   for, otherwise the order's customer_email).
7. No refund/escalation when the customer only asks a question; use get_refund_policy for policy.
8. Remember details the customer gave earlier in the conversation.
9. Act within policy without asking for confirmation unless information is missing.
Reply to the customer in two or three short sentences.
```

### 4.3 How one conversation turn runs (`src/refunddesk/agent.py`)

1. The customer message is added to the conversation history.
2. The agent calls the model with the system prompt, the recent history and the tool definitions. This repeats up to **12 steps per turn**.
3. If the model replies with plain text and no tool calls, the turn ends and that text goes to the customer.
4. If the model asks for tools, each tool call goes through:
   1. **Strict argument check** (`parse_tool_arguments`). Unknown tool, broken JSON, duplicate keys, missing or extra fields, wrong types, NaN or booleans-as-numbers are all rejected with an error result.
   2. **Policy guard in code** (`_policy_block`, refunds only). The refund is blocked if the order wasn't successfully looked up first, or if the lookup failed, or if the amount is over $500. This guard is code, not prompt, so the model can't talk its way past it.
   3. **Run with retries** (`_execute_with_retries`). Up to **4 attempts** (`MAX_RETRIES = 3`):
      - a timeout is retried
      - a result that fails validation is retried; see the next step
      - if all attempts fail, the model gets `{"status":"error", "error":"… failed after 3 retries …"}`
   4. **Result validation** (`validate_tool_result`). A result with `status: "failed"`, a malformed result, or a lookup missing order fields counts as invalid and gets retried. **This is the safety net that the hero bug removes.**
   5. A successful lookup is remembered (`verified_orders`); a failed lookup is remembered too (`failed_lookups`).
5. All tool results go back to the model, and the loop continues.
6. After 12 steps with no final answer, the agent gives up politely: "A human agent will follow up."

**History window.** Only the last 24 messages are sent to the model. The cut always starts at a customer message, so a tool call is never separated from its result. Configurable via `REFUNDDESK_HISTORY_WINDOW`.

### 4.4 The mock tools (`src/refunddesk/tools.py`)

| Tool | Inputs | What it does |
|---|---|---|
| `lookup_order` | `order_id` | Returns the order, or `not_found` |
| `get_refund_policy` | none | Returns the policy: $500 agent limit, 30-day window, partial refunds allowed, no duplicates |
| `issue_refund` | `order_id`, `amount`, `reason` | Rejects unknown orders and amounts ≤ 0 or above what's left to refund; otherwise records refund `RF-nnnn` and marks the order refunded when fully refunded |
| `escalate_to_human` | `order_id`, `reason` | Records ticket `ESC-nnnn` (`order_id "unknown"` allowed) |
| `send_customer_email` | `to`, `subject`, `body` | Records email `MSG-nnnn` |

Every tool call is written to a **call log** (`seq`, tool, args, outcome, result), which the checkers inspect afterwards. Outcomes are `ok`, `not_found`, `rejected`, `timeout`, `failed`, `blocked` and `invalid_arguments`.

### 4.5 Fake failures, on purpose (`src/refunddesk/faults.py`)

To test whether the agent is robust, tasks can make tools misbehave:

- **`timeout`**: the tool raises a timeout. In neatlogs the span is marked ERROR.
- **`failed`**: the tool returns `{"status":"failed","error":"<tool>: upstream service error"}`.

A fault rule says which tool fails and when:

- `calls: [1,2]` means the 1st and 2nd attempts
- `always: true`
- `rate: 0.5` means randomly, but repeatably, decided by a hash of (task, seed, tool, call number)
- `max: N` means at most N times

Attempts include retries. So `calls: [1,2,3]` with 3 retries means the **4th attempt succeeds**. The fault fires *before* the tool touches the store, so a failed call has no side effects.

### 4.6 The test tasks and checkers

Each task is a JSON file in `evals/` containing:
- an `id`
- the customer message(s) (`turns`)
- the starting store (orders)
- optional `faults`
- `checks`, the pass/fail rules

The checkers (`src/refunddesk/checks.py`) are plain code; no AI judges anything:

| Checker | Passes when |
|---|---|
| `refund_count(order_id, count)` | exactly *count* refunds for that order |
| `refund_amount(order_id, amount)` | refunds add up to that amount (±0.005) |
| `no_refund([order_id])` | no refund (for that order, or at all) |
| `escalated([order_id])` | at least one escalation |
| `not_escalated` | no escalations |
| `email_sent([to])` | at least one email (to that address) |
| `tool_called(tool, min, max)` | the tool was attempted between min and max times (failed and timed-out attempts count) |
| `refunds_follow_successful_lookup` | every refund came after a successful lookup of the same order |
| `injected_fault_seen(tool, kind)` | the planned fault really happened |
| `no_refund_over`, `tool_not_called` | exist, but no task uses them |

A task **passes** only if the run had no crash and every check passed.

There are **26 main tasks and 6 held-out tasks**; all are listed in [Appendix A](#appendix-a-every-refunddesk-test-task).
- **20 main tasks** existed at `good-v1.0`.
- **6 harder tasks** were added on `main` later (commit `ba86ed0`), after we found the hero bug was too subtle. In these, a tool fails 2–3 times in a row and must be retried. They check the exact number of attempts (e.g. `issue_refund` attempted exactly 4 times), which only the original retry-plus-validation code produces.

### 4.7 Running a task (`python -m refunddesk.eval`)

```
uv run python -m refunddesk.eval --task refund_small_order --seed 1 [--tool-log]
```

This creates a temporary store, runs the conversation, runs the checks, and prints **one line of JSON** with:
- `passed`, `cost` (USD), `latency` (s), `tokens`
- `trace_id` (neatlogs)
- `llm_calls`, `tool_executions`, `tool_outcomes`
- `checks`, `error`, `metadata`

It exits 0 even when the task fails; exit 2 means it couldn't start.

`python -m refunddesk.suite --reps 3` runs the whole suite in parallel (4 workers), saves results under `.cache/refunddesk/runs/`, and prints pass counts and total cost.

### 4.8 RefundDesk's neatlogs tracing (`src/refunddesk/tracing.py`)

Every task run is **one trace** in neatlogs, workflow `refunddesk-eval`:

```
WORKFLOW refunddesk.run_task            ← tagged with culprit_run_id, commit_sha, task_id, repetition, seed
└─ AGENT refunddesk.handle_turn         ← one per customer turn
   ├─ LLM anthropic.messages.create     ← every model call (captured by neatlogs.wrap)
   └─ TOOL <tool name>                  ← every tool attempt; timeouts show as ERROR
```

When Culprit runs a task, it passes `CULPRIT_RUN_ID`, `COMMIT_SHA`, `TASK_ID` and `REPETITION` as environment variables, so every RefundDesk trace can be matched to the Culprit run, commit and repetition that caused it.

`scripts/neatlogs_readback.py` reads traces back through the neatlogs CLI and checks that they're complete: one root, correct parents, span counts that match, metadata present, model and token data present. **All 78 baseline traces passed** that check.

### 4.9 Baseline numbers (measured)

| What | Result |
|---|---|
| Full suite (20+6 tasks) × 3 repetitions at the baseline code | **78/78 passed** |
| Cost of those 78 runs | **$1.27** (about $0.016 per run) |
| Average run time | 6.9 s, almost all of it waiting for the model |
| Cheapest / most expensive task | ~$0.007 (status question) / ~$0.028 (multi-turn) |
| Unit tests (no AI calls) | 27 pass |
| Readback check of all 78 traces | 78/78 pass |

---

## 5. The planted bugs (the six branches)

### 5.1 How the history was built

- **`good-v1.0`** points at commit `0479c27` on `main`. The agent code there is identical to `a89cc91`, where the 78/78 baseline was measured.
- From `good-v1.0`, six branches `hist/a` … `hist/f` were created. Each one has:
  - harmless "maintenance" commits: docs, comments, logging, type hints, renames, small refactors, tests
  - **one planted bug commit**, at a planned position
  - more maintenance commits after it
- On `hist/b` and `hist/f`, one commit **breaks installation**: it pins `python-dotenv==1.2.99`, a version that doesn't exist, without updating `uv.lock`. The very next commit reverts it. This tests Culprit's "skip and try a neighbour" recovery.

Branch names are deliberately neutral (`hist/x`), so nothing in the victim repo hints at which bug is where.

### 5.2 The answer key

| Branch | Commits | Planted bug (position, SHA) | What changed | Expected effect |
|---|---|---|---|---|
| `hist/a` | 12 | #5 `c4f2401` | Renamed `lookup_order`'s parameter `order_id` → `id`; the tool description still says "order" | Model may still send `order_id` and get rejected by the strict parser (depends on the model) |
| **`hist/b`** | 14 | **#10 `397c427`** | **"Make it faster"**: tool calls run in parallel, and result validation is removed | A `failed` tool result is no longer retried. It goes straight to the model, which usually gives up or escalates |
| `hist/c` | 13 | #9 `acf3b7d` | History window 24 → **6** messages | Forgets details from earlier turns in multi-turn conversations |
| `hist/d` | 15 | #6 `441058e` | System prompt shortened from 9 rules to 7 | The $500 rule survived (shorter wording), so the effect may be weak; the code guard still blocks >$500 |
| `hist/e` | 12 | #8 `8ae122d` | Lenient argument parsing: missing fields become `""`, `0` or `{}` instead of errors | Malformed tool calls run with empty values |
| `hist/f` | 16 | #12 `1777d44` | `MAX_RETRIES` 3 → **0** | Any timeout or failure is final |

Broken-install commits: `hist/b` #7 `22a37db` (reverted by #8 `81c0753`); `hist/f` #8 `2ad118e` (reverted by #9 `9428a94`).

On `hist/b`, the broken commit sits exactly at the midpoint, so Culprit's **first** bisect step hits it. That gives the demo a recovery moment.

### 5.3 How each bug was made (the honesty note)

Each bug was **explicitly requested** from a Claude Code session in the RefundDesk repo, with a realistic reason (speed, cost, consistency). Entire recorded those sessions. So the checkpoint for each bug commit contains a real human request, which is exactly what Culprit retrieves as intent.

- **Hero bug (`hist/b`)** came from a dedicated session given only: *"RefundDesk is too slow. Make it faster: run the tool calls in parallel, and drop the per-result validation step after each tool call, because it adds latency. Keep the change in one commit with a normal commit message, then push."*
  - The session first measured the code and **pushed back**: validation costs about 0.37 µs per call, tools have no real latency, and dropping validation breaks a passing eval.
  - We told it to proceed anyway, with locks to keep parallel calls safe and fault injection deterministic, and explicitly accepted the failing eval.
  - That exchange is recorded in checkpoint `01M4JM8P2C4NDS2AAQ0MPVR8YR`. It makes a realistic demo story: the developer chose speed over the safety check.
- **`hist/d`** came from its own session ("The system prompt is bloated. Shorten it…").
- **`hist/a`, `hist/c`, `hist/e`, `hist/f`** came from **one** session that received all four requests. So each of those four checkpoints contains all four requests. Their intent is noisier, but the hero checkpoint is clean.

### 5.4 Is each bug actually visible? (measured so far)

Hero bug, original 3 failure tasks × 3 seeds:

| Version | Passed |
|---|---|
| Before (`good-v1.0`) | 9/9 |
| After (`397c427`) | 8/9 |

**Too subtle**: the model usually retries on its own.

Hero bug, the 6 new harder tasks × 3 seeds:

| Version | Passed |
|---|---|
| Before (`good-v1.0` code) | **18/18** |
| After (`397c427` code) | **0/18** |

**Very clear.**

Branches `a`, `c`, `d`, `e` and `f` have **not been measured yet**. Some may turn out too weak to detect. That's still useful: Culprit should then answer "no significant regression", which shows its safety gate working.

**Important:** the 6 new tasks exist only on `main`. That's why Culprit now **pins the suite**: every commit is tested with the same task files taken from `main` (see [§7.2](#72-pin-the-test-suite)).

---

## 6. Culprit, the detective

### 6.1 Code map (`src/culprit/`)

| File | Job |
|---|---|
| `cli.py` | Commands: `run`, `resume`, `bench`, `verify-trace` |
| `orchestrator.py` | Runs the whole investigation |
| `bench.py` | Runs scenarios and scores them against `bench/ground_truth.json`; writes `evidence/bench-<tag>.md` |
| `bisect.py` | The halving search, including skip handling |
| `stats.py` | Wilson interval and good/bad/unsure decision |
| `sandbox.py` | Worktrees, `uv sync --locked` install, import check |
| `evalrunner.py` | Runs one victim task as a subprocess and parses its JSON |
| `suite.py` | Pins the test suite and copies it into each worktree |
| `entire.py` | Gets the commit's intent from Entire, plus the leakage filter |
| `ledger.py` | SQLite database of runs, steps, task runs, artifacts |
| `tracing.py` | neatlogs setup and span helper |
| `readback.py` | Reads traces back from neatlogs and audits them |
| `llm.py` | The only place that calls Claude; validated JSON with automatic repair (**not used by `run` yet**) |
| `config.py` | Settings and defaults |
| `gitops.py` | Small git helpers (resolve ref, commit range, subject, diff) |

About 2,700 lines of Python, with **86 tests passing** (no AI calls, about 30 s).

### 6.2 Key settings (`config.py`)

| Setting | Default | Meaning |
|---|---|---|
| `k` | 3 | Repetitions per task |
| `z` | 1.96 | 95% confidence |
| `discriminating_size` (D) | 8 | Tasks used per bisect step |
| `max_resample_rounds` | 2 | Extra rounds when unsure |
| `budget_usd` | **$3.00** | Hard cap per run (`--budget-usd` overrides) |
| `global_budget_usd` | **$75.00** | Hard cap across all runs in the ledger |
| `install_timeout_s` | 600 | Max install time |
| `task_timeout_s` | 300 | Max time per task run |
| `suite` / `suite_ref` | `evals` / `main` | Which tests judge every commit |
| `eval_module` | `refunddesk.eval` | Victim's runner module |

---

## 7. A complete run, step by step

Command:
```
uv run culprit run --repo ../refunddesk --good good-v1.0 --bad hist/b
```

### 7.1 Set up
- Create a run in the ledger (`run_id` = 12 random hex characters, status `running`).
- Open the neatlogs root span `culprit_run` and record its trace ID.
- List the candidate commits: `git rev-list --first-parent --reverse good..bad`. Oldest first; excludes good, includes bad. For `hist/b` that's 14 commits.

### 7.2 Pin the test suite
- Take one snapshot of `evals/` from the victim's `main` (via `git archive`) into `.culprit/suites/…`.
- Record its source and commit SHA in the ledger.
- Before each commit is tested, that snapshot **replaces** the commit's own `evals/`. So every commit faces the same 26 tasks.
- A resumed run reuses the recorded snapshot, even if `main` has moved on since.
- Alternatively, `--suite /some/folder` uses a folder; its contents are fingerprinted, and a changed folder makes resume refuse.

### 7.3 Find the tasks
- Read the task names from the snapshot (top level only, so `heldout/` is excluded) and save them in the run's config.

### 7.4 Measure both ends (the baseline)
- Run **every task × k** on the good commit and on the bad commit. With 26 tasks and k=3, that's 78 runs each, 156 total. **This is the most expensive part of a run.**
- If either end fails to install, stop: "cannot bisect".
- Compute each end's pass rate and 95% range.
- **Safety gate:** a one-sided Fisher exact test asks whether good really passes more often than bad. If p ≥ 0.05 (`gate_alpha`), stop with status **`no_regression`**: Culprit refuses to hunt for a bug that might just be noise.
  - This replaced an "intervals overlap" rule, which was much stricter than a 5% test. Under it, 57/60 vs 48/60 (about 3 broken tasks out of 20) was called noise. On a perfect 78/78 baseline, the Fisher gate bisects once about 5 runs fail, while 1–2 flaky failures still count as noise.

### 7.5 Choose the "telling" tasks
- Rank tasks by how much worse they did on the bad version (good rate minus bad rate).
- Keep the top **8** that actually dropped. These are the tasks most likely to reveal the bug, so each bisect step runs only these.
- This is plain code today; the planned AI-assisted selection is **NOT BUILT**.

### 7.6 Bisect
- Start with "the last good commit is before #1, the first bad commit is #14".
- Repeatedly test the middle of that range:
  1. Make a worktree for the commit, copy in the pinned suite, run `uv sync --locked`.
     - **If the install fails, the commit is SKIP**, and the next candidate is tested: middle+1, then middle−1, then +2, −2 and so on.
  2. Run the 8 telling tasks × 3 repetitions (24 runs), in parallel with 4 workers.
  3. Decide GOOD, BAD or INCONCLUSIVE ([§8](#8-the-statistics-explained-simply)).
  4. If INCONCLUSIVE, resample:
     - **Round 1:** 3 more repetitions of the same 8 tasks.
     - **Round 2:** up to 8 *other* tasks × 3, but only tasks that also dropped from good to bad. If there are none, 3 more repetitions of the same 8 instead. A task that passes on both ends tells good from bad apart no better than a coin, and it pulls the threshold up.
     - Still unsure: decide by the plain pass rate and mark the step **`low_confidence`**.
     - At most 72 runs per commit.
  5. GOOD moves the "last good" marker up; BAD moves the "first bad" marker down.
- Stop when the two markers are adjacent. The first bad commit is the culprit.
- If skipped commits sit exactly on the boundary, the result is a **range** of suspects (status `ambiguous`), the same way `git bisect skip` reports it.

### 7.7 Ask Entire why
- Run `entire checkpoint explain <sha>` in the victim repo and take the **Intent** section.
- If the Intent is empty or is a system message, read the session's typed prompts from `--transcript`.
- If the commit has no checkpoint, fall back to the commit message plus the diff, and say "intent unavailable".
- Pass the text through the **leakage filter** ([§12](#12-keeping-the-answers-secret-leakage-guard)) and store it with the diff in the ledger.

### 7.8 Finish
- Print and store the result. Example from the free demo:
  `Culprit: a419a7d… 'speed up tool handling' (confidence: 95% Wilson)`
- Possible statuses: `found`, `no_regression`, `ambiguous`, `budget_exceeded`, `infra_error`, `error`.
- Output is the terminal log plus the ledger. A report file is **NOT BUILT**.

### 7.9 What the free demo run looked like (fake victim, $0)

```
run 6256751aa062: 14 commits in good-v1.0..main, 10 tasks × 3
  good 28/30 CI [0.79, 0.98]  bad 15/30 CI [0.33, 0.67]
  discriminating tasks: t02, t04, t05, t01, t03
  cd37425ba0 install failed → SKIP
  f85bf2b1a3 'revert requests pin': 14/15 CI [0.70, 0.99] vs t=0.50 → GOOD
  2db04bf27e 'docs: maintenance note 11': 1/15 CI [0.01, 0.30] vs t=0.50 → BAD
  f1ef9a8429 'tune tool timeouts': 13/15 CI [0.62, 0.96] vs t=0.50 → GOOD
  a419a7d89a 'speed up tool handling': 1/15 CI [0.01, 0.30] vs t=0.50 → BAD
  intent source: fallback: ✗ No associated Entire checkpoint; leakage filter removed 0 lines
Culprit: a419a7d89ad254ff3a5174500f0a03d75aaf1c5c 'speed up tool handling' (confidence: 95% Wilson)
```

It tested 4 of 14 commits, skipped the broken one, and found the planted break at #10. The fake repo has no Entire checkpoints, so the intent fell back to the commit message and diff.

---

## 8. The statistics, explained simply

**The problem.** If a commit passes 13 of 15 runs, is it good? Probably, but with only 15 runs, luck matters.

**Wilson interval.** From passes and runs, Culprit computes a range where the true pass rate almost certainly lies (95% sure):
- 14/15 gives `[0.70, 0.99]`: the true rate is somewhere between 70% and 99%.
- 1/15 gives `[0.01, 0.30]`.
- More runs make the range narrower.

The formula (`stats.wilson`), with p = passes/n and z = 1.96:
```
centre = (p + z²/2n) / (1 + z²/n)
half   = z·√(p(1−p)/n + z²/4n²) / (1 + z²/n)
range  = [centre − half, centre + half], clipped to [0, 1]
```

**Threshold.** The halfway point between the good and bad pass rates, calculated for the **same tasks** the commit ran. This matters because some tasks fail more on the bad version than others.

**Decision (`stats.decide`):**
- whole range at or above the threshold → **GOOD**
- whole range at or below the threshold → **BAD**
- range straddles the threshold → **INCONCLUSIVE**, so run more tests

**Why it matters.** A naive bisect that runs each test once would sometimes blame the wrong commit because of one unlucky failure. Culprit only commits to a verdict when the evidence is strong, and it labels any verdict it had to guess (`low_confidence`).

---

## 9. Recovery: what happens when things go wrong

| Problem | How Culprit notices | What it does |
|---|---|---|
| Victim run hit an API problem (429, 5xx, overloaded, connection), timed out, or printed no JSON | Error text from the victim runner | Retries it twice with backoff (5 s, 20 s). It is never recorded as a failed task. If it keeps failing, the run stops with `infra_error`, and `culprit resume` continues |
| Bad key, missing config or unknown model | `AuthenticationError`, `ConfigError`, … | Stops at once with `infra_error`, without recording anything against the commit |
| Commit won't install | `uv sync --locked` fails | Marks it SKIP and tests a neighbour |
| Unsure result (e.g. 3/5) | Range straddles the threshold | Runs more repetitions, then more tasks, then decides by point estimate and flags `low_confidence` |
| Process killed mid-run | The ledger has partial work | `culprit resume <run_id>` redoes only the missing task runs; no duplicates (tested by kill −9 and resume) |
| Budget reached | Cost total ≥ cap, checked before each batch | Stops, reports the best current suspect range, tells you how to resume with a higher cap |
| Good and bad not really different | Ranges overlap | Stops with `no_regression` |
| Victim crashes because of the commit's own code (e.g. `KeyError`) | Error text is not an infrastructure error | Counts as a failed task: that's the commit's behaviour |
| No Entire checkpoint | `explain` finds no checkpoint | Uses commit message + diff; says "intent unavailable" |
| Entire Intent is a system tag | Intent starts with `<` or `*(` | Reads the session's typed prompts from `--transcript` |

Also: `culprit resume` re-uses the good and bad SHAs recorded at the start of the run, so moving a branch mid-run can't change the range. An empty range (good = bad) stops before the expensive baselines.

---

## 10. The ledger (Culprit's memory)

File: `piedpiper-neathacks/.culprit/ledger.sqlite` (SQLite, WAL mode, gitignored).

| Table | One row per | Key columns |
|---|---|---|
| `runs` | Culprit run | `run_id`, `repo`, `good_ref`, `bad_ref`, `suite_source`, `suite_sha`, `config_json`, `status`, `total_cost_usd`, `culprit_sha`, `confidence`, `summary` |
| `steps` | commit evaluation | `kind` (baseline / bisect / resample:1 / resample:2), `commit_sha`, `status` (running/done/skip), `decision`, `wilson_low/high`, `n`, `passes`, `cost_usd`, `latency_ms_p50`, `flags` (low_confidence), `error` |
| `task_runs` | single victim task run | `task_id`, `repetition`, `passed`, `cost_usd`, `latency_ms`, `tokens_in/out`, `neatlogs_trace_id`, `error` |
| `llm_calls` | Culprit AI call | exists but is **never written yet** (no AI stages built) |
| `artifacts` | run + kind | `neatlogs_traces`, `intent`, `diff` |

Uniqueness rules make resume safe:
- a step is unique per (run, kind, commit)
- a task run is unique per (step, task, repetition)

Re-running a step never double-counts.

**Cost** for budget purposes = the sum of task run costs plus AI call costs. Costs come from RefundDesk's own price table: Sonnet 5.5 at $2 input / $10 output per million tokens.

Right now the ledger holds only the 2 free demo runs.

---

## 11. How the three required tools are used

### neatlogs (tracing, failure investigation, before/after)

- **Culprit is traced** as workflow `culprit`. The neatlogs session ID is the `run_id`.

  ```
  WORKFLOW culprit_run
  ├─ TOOL git_rev_list, pin_suite, discover_tasks, select_discriminating_tasks
  ├─ CHAIN evaluate_commit:<baseline|bisect|resample:N>
  │   ├─ TOOL git_worktree_add, uv_sync_locked
  │   └─ TOOL victim_eval_run   (one per task run)
  ├─ TOOL decision_rule         (inputs: passes, n, threshold, z, round → verdict)
  └─ TOOL entire_checkpoint_explain
  ```

  - Every span carries `run_id` and `commit_sha`. neatlogs' read API doesn't return custom attributes, so they're also written into each span's input.
  - Failures mark spans as ERROR, with the error message.
- **RefundDesk is traced** separately, one trace per task run ([§4.8](#48-refunddesks-neatlogs-tracing)), tagged with the Culprit run, commit and repetition.
- **Readback audit:** `culprit verify-trace <run_id>` pulls the run's traces back through the neatlogs CLI and checks:
  - the trace is finalized, with the right workflow and session
  - there's one root and no orphan spans
  - the span count matches
  - every span has the right `run_id` and a valid commit SHA

  This has passed on every fixture run so far.
- **Cost discrepancy found:** neatlogs prices Sonnet 5.5 at $3/$15, while Anthropic lists $2/$10. We use $2/$10 for all cost numbers. The discrepancy is documented in `BLOCKERS.md` and `evidence/neatlogs-cost-discrepancy.md`.
- **Still to do (M4):** use neatlogs Investigate and Detections on Culprit v1's benchmark mistakes, improve Culprit, and show v1-vs-v2 numbers. This is a required before/after.

### Entire (checkpoints, intent)

- Both repos are connected and enabled. Every Claude Code session started inside a repo is recorded. Each commit made in a session gets an `Entire-Checkpoint:` trailer, e.g. hero commit `397c427` → checkpoint `01M4JM8P2C4NDS2AAQ0MPVR8YR`.
- **As part of the product:** Culprit reads the culprit commit's checkpoint to explain *why* the change was made.
- **As build evidence:** Culprit's own commits are checkpointed too. The submission needs a checkpoint link (`https://entire.io/gh/rahilmavani/piedpiper-neathacks/commit/<full sha>`) and ID.
- Checkpoints are stored as git refs. A fresh clone of the Culprit repo fetched them automatically, according to the Culprit session's test.

### cfo.ai (business plan), NOT STARTED

The plan:
- Take measured costs from the ledger: cost per victim run, runs per bisect, cost per bisect.
- Model pricing options, all hypotheses:
  - (A) flat $49/$199 per repo per month
  - (B) customer uses their own model key, plus a platform fee
  - (C) metered per bisect
- Then margin, break-even and runway.

You do this step by hand in cfo.ai. Culprit's `export-costs` command, which would feed it, is **NOT BUILT** yet.

---

## 12. Keeping the answers secret (leakage guard)

We know which commit is guilty on each branch. If Culprit's AI parts could see that, the benchmark would be meaningless. The protections:

1. **Neutral names in the victim repo:** `hist/a`…`hist/f`. No commit or comment mentions scenarios, gaps or regressions (scanned; clean).
2. **The answer key lives only in the Culprit repo** (`PROMPTS.md`, this file, and `bench/ground_truth.json`). Culprit never feeds its own repo's files to an AI. `culprit bench` refuses to run if the scenario or ground-truth file sits inside the victim repo, resolves each scenario's refs to SHAs and passes **only those SHAs** to the orchestrator, so neither the scenario name nor its answer reaches the ledger config, a trace, an AI prompt or Entire text. The ground truth is read only to score runs that have already finished.
3. **Only the examined commit's checkpoint is read**, never its neighbours'.
4. **Leakage filter** (`entire.leak_filter`): before any Entire text is stored or used, it drops every line containing any of:
   - `R1`–`R6` as whole words
   - `hist/`, `scenario`, `culprit`, `regression`, `seed`, `gap` or `pause` (any case, even inside longer words)
   - the name of any branch or tag in the victim repo except main, master, origin and HEAD

   The number of removed lines is logged.
5. **One accident, cleaned up:** an early RefundDesk session read `PROMPTS.md`. It stopped before building anything, and its Entire record was deleted before it made any commit.

The filter is deliberately broad. It also drops harmless lines containing words like "seeded".

---

## 13. Money: what things cost

All cost figures here use Anthropic's list price for Sonnet 5.5 ($2 / $10 per million tokens).

| Item | Runs | Cost |
|---|---|---|
| RefundDesk baseline (78 runs) | 78 | $1.27 |
| Hero check #1 (3 tasks × 3 seeds × 2 versions) | 18 | $0.31 |
| Hero check #2 (6 new tasks × 3 seeds × 2 versions) | 36 | $0.68 |
| RefundDesk's own checks of its new tasks, plus a few hero-session evals | ~24 | ~$0.40 (estimate) |
| Culprit AI test call | 1 | $0.0004 |
| Culprit demo runs (fake victim) | 180 | $0 (fake costs only) |
| **Total so far** | | **about $2–2.7.** Your Anthropic dashboard showed $1.88; it can lag. |

**Typical costs going forward:**
- 1 victim task run: about **$0.016** (from $0.007 to $0.028)
- 1 real Culprit run on one branch:
  - baselines: 26 tasks × 3 × 2 ends = 156 runs ≈ $2.50
  - bisect: about 4 steps × 24 runs, plus any resampling, ≈ $1.50+
  - **total ≈ $3.70–6**
- The Culprit session estimated **~$3.70** for `hist/b`, which is just above the $3 default cap. It suggested `--budget-usd 5` for that one run.
- All 6 branches, run once: ≈ $25–35. The benchmark needs v1 *and* v2, so roughly double.

**Built-in safety:** each run stops at its cap ($3 by default), and everything together stops at $75. Spending can overshoot by at most one batch (4 task runs, about $0.07).

---

## 14. Commands you can run

From `piedpiper-neathacks/` (load keys first: `set -a; source .env; set +a`):

```bash
uv run pytest -q                                   # 86 tests, free, ~30 s
uv run culprit --help

# Free demo on a fake victim (no AI calls)
uv run python tests/fixtures/make_victim.py /tmp/victim --commits 14 --breaks-at 10 --unbuildable-at 7 --noisy-from 9
uv run culprit run --repo /tmp/victim --good good-v1.0 --bad main

# Real run on the hero branch (COSTS MONEY, ~$3.70; ask first)
uv run culprit run --repo ../refunddesk --good good-v1.0 --bad hist/b --budget-usd 5

# Continue a stopped run, optionally with a higher cap
uv run culprit resume <run_id> [--budget-usd 6]

# Check a run's neatlogs traces
uv run culprit verify-trace <run_id>

# Benchmark: run every scenario in bench/scenarios.yaml and score it (COSTS MONEY, ~$0.60+ per branch on GLM; ask first)
uv run culprit bench --tag v1 [--only hist/b] [--budget-usd 3]

# Score runs that already exist instead of running again (free; opens the ledger read-only)
uv run culprit bench --tag v1 --score-runs ff50e3620fdd,<run_id>...   # matched to scenarios by good/bad SHA
uv run culprit bench --tag v1 --score-latest                          # latest finished run per scenario
```

**`culprit bench`** (M3, PRD §10 and §13):
- `bench/scenarios.yaml`: one scenario per branch (`name`, `good`, `bad`); here `good-v1.0` and `origin/hist/<x>`.
- `bench/ground_truth.json`: per scenario, the culprit SHA, branch head, uninstallable commits, the responsible hunks (file + line range at the culprit commit, or at its parent for removed code), the intended-gain metric (`latency`, `tokens`, `cost`, or null for hist/a and hist/e, whose claimed gains aren't one of those), and `visible`: per victim model, whether a **separate** measurement showed the bug is detectable. It must come from a strength check with its own runs (PROMPTS.md Prompt G step 4, recorded with run IDs in `bench/strength.md`), never from a Culprit run's own baselines, which would let Culprit grade itself. Only hist/b is set so far, from the separate hero check; a, c, d, e and f are unmeasured.
- Scenarios run one after another through the normal orchestrator. A run that stops (budget, infra error) doesn't stop the bench; resume it with `culprit resume`, then re-score with `--score-runs`.
- Each run gets an outcome: `correct` (planted SHA found), `wrong`, `correct_no_regression` (the gate said no regression and none was expected: nothing planted, or the bug is known to be invisible on that model), `missed` (no regression, but the bug is known to be visible), `no_regression_unverified` (visibility not measured), `ambiguous_contains` / `ambiguous_misses`, or `incomplete`. **Accuracy** = `correct` + `correct_no_regression`.
- Output: `evidence/bench-<tag>.md` (summary, table with outcome, found vs expected, victim runs, cost, wall time, skipped commits, model and run ID, then each run's summary and neatlogs trace IDs) and `evidence/bench-<tag>.json`. The report names Culprit's own commit, so v1 and v2 can be told apart.
- Wall time is the run's start-to-finish in the ledger, so it includes any pause before a resume. Hunk accuracy and fix verification are not scored yet (no localiser or fixer).
- Flags: `--tag` (required), `--scenarios` (default `bench/scenarios.yaml`), `--ground-truth` (default next to it), `--repo`, `--only` (repeatable), `--score-runs` (repeatable or comma-separated), `--score-latest`, `--k`, `--budget-usd` (per scenario), `--db`, `--workers`, `--out-dir` (default `evidence/`).

`culprit run` flags: `--good`, `--bad` (required), `--repo` (default `../refunddesk`), `--suite` (default `evals`), `--suite-ref` (default `main`), `--k` (3), `--budget-usd` (3.00), `--db`, `--workers` (4).

From `refunddesk/`:

```bash
uv run pytest -q                                              # 27 tests, free
uv run python -m refunddesk.eval --task refund_small_order --seed 1   # ~$0.016
uv run python -m refunddesk.suite --reps 3                    # whole suite ×3, ~$1.30+ (COSTS MONEY)
uv run python scripts/neatlogs_readback.py <results.jsonl>    # verify traces
```

---

## 15. What is built and what is not

| Part | Status |
|---|---|
| RefundDesk agent, tools, faults, 32 tasks, checkers, runner, tracing, readback | ✅ Built; baseline 78/78 |
| Six branches with planted bugs and broken-install commits | ✅ Built and pushed |
| Harder failure tasks so the hero bug is visible | ✅ Built (18/18 → 0/18) |
| Culprit: ledger, worktrees, locked install, eval runner | ✅ Built |
| Culprit: bisect with skip | ✅ Built |
| Culprit: Wilson decision, resampling, low-confidence flag | ✅ Built |
| Culprit: budget caps, resume | ✅ Built |
| Culprit: suite pinning | ✅ Built |
| Culprit: Entire intent with transcript fallback and leakage filter | ✅ Built |
| Culprit: neatlogs tracing and `verify-trace` audit | ✅ Built (fixture runs) |
| **First real Culprit run on RefundDesk** | ✅ Run `ff50e3620fdd` on `hist/b` with GLM 5.3: found `397c427` (95% Wilson), skipped `22a37db`; 240 runs, $0.60, 12.5 min |
| Localiser: find the exact guilty lines | ❌ NOT BUILT |
| Fixer: write a minimal fix; Verifier: prove it on held-out tasks | ❌ NOT BUILT |
| AI-assisted task selection / planner | ❌ NOT BUILT (plain ranking used) |
| Report (markdown/HTML) | ❌ NOT BUILT |
| `culprit bench` + ground truth (`bench/`) | ✅ Built and tested on the fixture (2 scenarios: one planted break, one clean range); `--score-runs` / `--score-latest` score existing runs |
| Benchmark v1 vs v2 numbers | ❌ Not run yet; this is the required before/after evidence |
| neatlogs Detections / Investigate used to improve Culprit | ❌ Not done |
| `export-costs` and the cfo.ai business plan | ❌ Not done |
| Demo video, README polish, X posts | ❌ Not done (Monday) |

---

## 16. Known issues and oddities

### Culprit
- No AI calls happen in `culprit run` yet. `llm.py` is tested but unused, and `llm_calls` is always empty.
- Budget is checked per batch, so a run can overshoot its cap by up to 4 task runs. A victim that reports no cost is never capped. Retried infrastructure attempts aren't costed either.
- Some errors aren't caught cleanly: Entire `--transcript` timeout, import-probe timeout, `verify-trace` readback errors.
- The leakage filter's substring matching is broad: "seeded", "gaps" and "Culprit" lines get dropped too.
- The victim's `.env` is read from the main checkout, not from each worktree. Culprit's own environment, keys included, is passed to victim runs.
- `scripts/nl-read` and `readback.py` handle `NEATLOGS_TOKEN` differently.
- Worktrees are never cleaned up after runs (12 exist now).
- Stale docs: the README says "Bootstrap complete", and hackathon.md says "Culprit hasn't been built yet". The test count has grown from 25 to 57.
- `pyproject.toml` description is still "Add your description here". `jinja2` is a dependency but unused (`pyyaml` is now used by `culprit bench`).
- **Fixed today:** the fake-repo builder lost the "revert pin" commit when a noisy commit followed the pin (`1d43403`).

### RefundDesk
- hackathon.md still says "20 tasks" and describes the branches as maintenance-only. Both were written before the later changes.
- The 6 new tasks check *exact* attempt counts. They will also fail on `hist/f` (retries 0), which is fine, since that's a separate scenario.
- `seeded_lookup_timeouts_then_refund` injects **no** fault at seed 0 (the random draws were above 0.5). It's harmless, but it doesn't test what its name says.
- The error message says "failed after 3 retries" even when it stopped earlier, and "after 0 retries" on `hist/f`.
- All ID prefixes share one counter (RF-0001, MSG-0002, …).
- `claude-haiku-5-5` is priced at $0.10/$0.50 in the table (unused here).
- On `hist/a`, the bug commit also changed the grader (`checks.py`), because the checker reads the renamed argument. Only `evals/` is pinned, so each commit grades with its own `checks.py`.
- Behaviour on branches a, c, d, e and f is **unmeasured** so far.

### Process
- Two harmless leftovers from a wrong-branch attempt in refunddesk: a git stash on `main`, and an ended Entire session record `cd90e28d…`. Neither is attached to any commit. You can remove them with `git stash drop` and `entire clean --session cd90e28d-60be-4298-a36d-87d11dcd7ac6 --force`.
- The Anthropic and neatlogs keys were pasted in chat. Rotate them after the event.

---

## 17. What happens next

1. **First real run on `hist/b`** (~$3.70, cap $5). You watch it. The expected result is that Culprit names `397c427` and shows your "make it faster" request as the intent.
2. **Measure the other five branches** cheaply (start with 2), then run Culprit on them.
3. **Build the missing pieces** (each one free to build and test on the fake repo):
   - Localiser: which lines of the commit caused it
   - Fixer + Verifier: minimal fix, proven on held-out tasks
   - report
   - `bench` with ground truth
   - `export-costs`
4. **Benchmark v1 → investigate in neatlogs → improve → benchmark v2.** This is the required before/after evidence. Roughly $25–60 depending on scope; it will be confirmed with you before running.
5. **cfo.ai business plan** from the measured costs (by hand).
6. **Monday:** evidence pack, README, video (≤ 3 min), X quote-post at 7:00 PM IST.

---

## Appendix A: every RefundDesk test task

"none" in the Faults column means no faults are injected.

### Main suite (`evals/`, 26 tasks)

| Task | What it tests | Faults |
|---|---|---|
| already_refunded_no_duplicate | Order already refunded; must not refund again | none |
| email_failed_payload_three_times* | $79 refund; email fails 3× then succeeds; email attempted exactly 4×; not escalated | email failed calls 1–3 |
| escalate_failed_payload_three_times* | Order not found; escalation fails 3× then succeeds; attempted exactly 4× | escalate failed 1–3 |
| escalate_failed_payload_twice* | $1,149 order; escalation fails 2×; attempted exactly 3×; email sent | escalate failed 1–2 |
| lookup_failed_customer_insists | Lookup always fails; customer insists over 2 turns; no refund; escalate | lookup always failed |
| lookup_failed_no_refund | Lookup always fails; no refund; escalate | lookup always failed |
| lookup_timeout_once_then_refund | Lookup times out once; $19.99 refunded exactly | lookup timeout call 1 |
| multiturn_email_from_turn1 | Alternate email given in turn 1 must get the confirmation | none |
| multiturn_order_id_from_turn1 | Order ID from turn 1 refunded; decoy order not | none |
| multiturn_over_500_escalated | $650, refund asked in turn 2; escalate | none |
| multiturn_refund_and_email_failed_repeatedly* | 2 turns; refund fails 2×, email fails 3×; refund once; email to turn-1 address | refund failed 1–2, email failed 1–3 |
| order_not_found_escalated | Unknown order; no refund; escalate | none |
| partial_refund_requested_amount | Customer asks $20 of $120; exactly $20 | none |
| policy_question_no_action | Policy question; policy tool used; no action | none |
| refund_500_01_escalated | $500.01 must be escalated | none |
| refund_exactly_500 | $500.00 refunded, not escalated | none |
| refund_failed_payload_once | Refund fails once; refunded once | refund failed call 1 |
| refund_failed_payload_three_times* | Refund fails 3×; attempted exactly 4×; refunded once | refund failed 1–3 |
| refund_failed_payload_twice* | Refund fails 2×; attempted exactly 3×; refunded once | refund failed 1–2 |
| refund_only_requested_order | Refund only the order asked for | none |
| refund_over_500_escalated | $899; escalate; email | none |
| refund_sends_confirmation_email | $29 refund plus email | none |
| refund_small_order | $79.99 refunded exactly once | none |
| refund_timeout_once | Refund times out once; refunded once | refund timeout call 1 |
| seeded_lookup_timeouts_then_refund | Random lookup timeouts (rate 0.5, max 2); refunded once | lookup timeout rate 0.5 |
| status_question_no_action | Status question; no action | none |

\* = added on `main` in `ba86ed0` (not present at `good-v1.0` or on any `hist/*` branch; reaches them through suite pinning).

### Held-out suite (`evals/heldout/`, 6 tasks; reserved for verifying fixes, NOT used yet)

| Task | What it tests | Faults |
|---|---|---|
| heldout_escalate_email_timeout | $1,200 escalated; email after a timeout | email timeout call 1 |
| heldout_lookup_failed_once_then_refund | Lookup fails once; $59.99 refunded | lookup failed call 1 |
| heldout_multiturn_partial_amount | Partial $35.50 from turn 1 refunded in turn 2 | none |
| heldout_not_found_multiturn | Unknown order given in turn 2; escalate | none |
| heldout_over_500_with_timeout | $720 escalated after a lookup timeout | lookup timeout call 1 |
| heldout_refund_499_99 | $499.99 refunded, not escalated | none |

---

## Appendix B: every commit on every branch

`main`, oldest first:

| SHA | Message |
|---|---|
| 595fd28 | setup |
| 8a60444 | README stub |
| 4cfc31e | README status |
| 819b630 | agent, tools, eval suite |
| a89cc91 | tracing verified (**baseline measured here**) |
| 3790548 | readback retries |
| fcb5f15 | build log |
| **0479c27** | **= good-v1.0** |
| 91c772d | build log |
| ba86ed0 | 6 harder failure tasks |

Branches (position after `good-v1.0`; **bold** = planted bug; *italic* = broken install / revert):

- **hist/a (12):** 1 eaf02cb editorconfig · 2 63741e4 docstring · 3 0ddce1a store test · 4 1977647 rename `_draw` · **5 c4f2401 rename lookup_order param → id** · 6 8621a7d · 7 4d48697 · 8 5da2d21 · 9 d1ea030 · 10 089559f · 11 970749e · 12 6a2f05a
- **hist/b (14):** 1 d0c7fd1 · 2 699eb56 · 3 21ce275 · 4 1a9a92d · 5 59116f9 · 6 88226de · *7 22a37db pin python-dotenv 1.2.99* · *8 81c0753 revert* · 9 8793325 · **10 397c427 parallel tools + no validation (hero)** · 11 c9a132f · 12 e3a28dc · 13 e547ab7 · 14 f6511b8
- **hist/c (13):** 1 0d66033 · 2 65f2b98 · 3 f0f25db · 4 510fdcc · 5 9842b0a · 6 23cd8cb · 7 43c7ea7 · 8 5780896 · **9 acf3b7d history window 24 → 6** · 10 feda4f6 · 11 2e70ef0 · 12 2beb852 · 13 30960fe
- **hist/d (15):** 1 2fe9877 · 2 7ff4556 · 3 a5aab4a · 4 c00fd10 · 5 9a5bafd · **6 441058e tighten system prompt** · 7 6ffc19d · 8 d168a12 · 9 2884af8 · 10 8ad03f6 · 11 269ff40 · 12 b94037d · 13 06e2ac9 · 14 050fb2d · 15 819d692
- **hist/e (12):** 1 05ea5da · 2 0afe538 · 3 9005b58 · 4 69a3dae · 5 5614cb8 · 6 195966d · 7 d92552a · **8 8ae122d lenient argument defaults** · 9 078ffb9 · 10 62a2e88 · 11 e4a644a · 12 255f40c
- **hist/f (16):** 1 e53530f · 2 0970538 · 3 b418f7d rename `_policy_block` · 4 4f5a7ab · 5 8a724ba · 6 42efee1 · 7 2649e5c · *8 2ad118e pin python-dotenv 1.2.99* · *9 9428a94 revert* · 10 f0c0a9d · 11 4fa91ba · **12 1777d44 MAX_RETRIES 3 → 0** · 13 aee85a3 · 14 13c5197 · 15 99558b6 · 16 3b0938b

All maintenance commits were checked by reading their diffs: renames, helper extractions, logging, docstrings and tests, with no behaviour changes.

---

## Appendix C: file-by-file map

### `piedpiper-neathacks/` (Culprit)

| Path | What |
|---|---|
| `PRD.md` | Original product spec (the plan) |
| `PROMPTS.md` | Session prompts used to build everything, including the **answer key** table |
| `HOW_IT_WORKS.md` | This guide |
| `hackathon.md` | Dated build log (required by the hackathon skill) |
| `BLOCKERS.md` | Things the tools don't support, and the fallbacks chosen |
| `README.md` | Short intro (stale) |
| `docs/research.md` | What the neatlogs, Entire and cfo.ai docs really support |
| `docs/neatlogs.md` | Tracing contract, coverage table, how to repeat the readback |
| `evidence/neatlogs-cost-discrepancy.md` | $3/$15 vs $2/$10 finding |
| `src/culprit/*.py` | The product ([§6.1](#61-code-map-srcculprit)) |
| `bench/scenarios.yaml`, `bench/ground_truth.json` | Benchmark scenarios and the **answer key** (Culprit repo only) |
| `evidence/bench-<tag>.md/.json` | `culprit bench` reports (none for the real victim yet) |
| `tests/test_core.py` | Wilson, decide, bisect (all 14 positions), skip, ledger idempotency, leak filter, intent parsing |
| `tests/test_m2.py` | Threshold, resample + low_confidence, no_regression, budget stop + resume, global cap |
| `tests/test_resume.py` | End-to-end resume without duplicates |
| `tests/test_suite.py` | Suite pinning, resume keeps suite, worktree reset, folder suite fingerprint |
| `tests/test_fixture.py` | Fake repo's pin/revert commits install correctly |
| `tests/test_llm.py` | JSON repair and give-up logic |
| `tests/conftest.py` | Autouse guard: unsets `NEATLOGS_API_KEY` and keeps tracing off, so tests never export traces |
| `tests/test_bench.py` | Bench loaders, scoring outcomes, leakage guard, read-only scoring, end-to-end bench on 2 fixture scenarios |
| `tests/fixtures/make_victim.py` | Builds the free fake victim repo |
| `scripts/nl-read` | Runs the neatlogs CLI with OAuth only |
| `scripts/llm_capture_check.py` | One-off check that AI calls appear in neatlogs |
| `.claude/settings.json` | Entire hooks; co-author lines off |
| `.claude/skills/neathack/SKILL.md` | Hackathon build-log skill |
| `.entire/settings.json` | Entire on, git-ref checkpoints |
| `.culprit/` (ignored) | Ledger, worktrees, pinned suites |

### `refunddesk/` (victim)

| Path | What |
|---|---|
| `src/refunddesk/agent.py` | Agent loop, prompt, parsing, policy guard, validation, retries, history window |
| `src/refunddesk/llm.py` | Anthropic/OpenRouter client, prices, cost and token accounting |
| `src/refunddesk/config.py` | Settings from env |
| `src/refunddesk/tools.py` | Mock tools, call log, IDs |
| `src/refunddesk/store.py` | JSON store with atomic writes |
| `src/refunddesk/faults.py` | Deterministic fault injection |
| `src/refunddesk/tasks.py` | Task loading |
| `src/refunddesk/checks.py` | Pass/fail checkers |
| `src/refunddesk/eval.py` | One-task runner (prints JSON) |
| `src/refunddesk/suite.py` | Whole-suite runner |
| `src/refunddesk/tracing.py` | neatlogs setup and metadata |
| `evals/*.json`, `evals/heldout/*.json` | Test tasks |
| `scripts/neatlogs_readback.py` | Trace verification |
| `tests/` | 27 unit tests |
| `hackathon.md`, `README.md` | Build log, intro |

---

## Appendix D: environment variables and runtime paths

| Variable | Used by | Purpose |
|---|---|---|
| `NEATLOGS_API_KEY` | both | Sends traces (project key). Removed when reading traces back |
| `NEATLOGS_TOKEN` | readback | Optional read credential (otherwise OAuth login) |
| `NEATLOGS_CLI` | readback | Path to the neatlogs CLI if not found automatically |
| `ANTHROPIC_API_KEY` | both | Claude API. When set, both apps use Claude Sonnet 5.5 |
| `OPENROUTER_API_KEY` | both | Fallback when there's no Anthropic key: GLM 5.3 (`z-ai/glm-5.3`) via OpenRouter |
| `LLM_PROVIDER` | RefundDesk | Optional override. Culprit always sets it for victim runs |
| `VICTIM_MODEL` | both | Optional override; must belong to the selected provider. Culprit records the victim model in the run's config and passes it to every commit |
| `CULPRIT_MODEL` | Culprit `llm.py` | Optional override for Culprit's own model calls |
| `CULPRIT_VICTIM_REPO` | Culprit | Victim repo path when it isn't `../refunddesk` |
| `REFUNDDESK_HISTORY_WINDOW` | RefundDesk | History window size (default 24) |
| `VICTIM_PRICE_IN/OUT` | RefundDesk | Override prices |
| `CULPRIT_STATE_DIR` | Culprit | Where `.culprit/` lives |
| `CULPRIT_RUN_ID`, `COMMIT_SHA`, `TASK_ID`, `REPETITION` | set by Culprit, read by RefundDesk | Tag each victim trace |

| Path | Contents |
|---|---|
| `piedpiper-neathacks/.culprit/ledger.sqlite` | The ledger |
| `piedpiper-neathacks/.culprit/worktrees/<sha12>/` | One checkout per tested commit, each with its own `.venv` |
| `piedpiper-neathacks/.culprit/suites/…` | Pinned suite snapshots |
| `refunddesk/.cache/refunddesk/runs/*.jsonl` | Suite results (e.g. the 78-run baseline) |
| `refunddesk/.cache/refunddesk/sampling.json` | Remembers that Sonnet 5.5 rejects temperature |
| `*/.entire/metadata/<session>/` | Entire's local session transcripts (ignored) |
