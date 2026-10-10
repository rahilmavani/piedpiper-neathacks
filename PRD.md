# Culprit — Product Requirements Document

**Team:** PiedPiper · **Event:** neatHack 2026 (Oct 10–12, IST) · **Status:** Final for build · **Version:** 1.0 (Oct 10, pre-kickoff)

> One line: **`git bisect` for agent behaviour, with receipts.** Give Culprit a good ref, a bad ref and an eval suite. It finds the commit that broke your agent, explains *why* that change was made (from the Entire session), writes the smallest fix that restores quality while keeping the intended gain, and proves it statistically.

---

## 1. Problem

Teams shipping LLM agents change prompts, swap models, tweak tools and merge coding-agent commits many times a week. Quality degrades silently. When the eval pass rate drops from 90% to 60% across 15 commits:

- Re-running evals by hand at each commit takes hours to a day.
- LLM evals are noisy, so a single run per commit gives misleading answers. Classic `git bisect` assumes a deterministic test.
- Even after finding the commit, nobody remembers *why* it was made. Reverting it throws away the intended improvement (e.g. a latency win).

**Why now:** Coding agents write a growing share of agent code. Entire captures the session intent behind each commit, and neatlogs captures the traces of every agent run. Culprit is the first workflow that joins **intent (Entire) + behaviour (neatlogs) + statistics** to answer "what broke, why, and how do we fix it without losing the gain?"

## 2. Users and buyer

| Persona | Situation | What they want |
|---|---|---|
| **Agent engineer** (primary user) | Pass rate dropped after a week of changes | The culprit commit and a verified fix in minutes, not a day |
| **Eng lead / AI platform owner** (buyer) | Regressions reach production; nobody owns eval hygiene | A regression gate + root-cause report attached to every PR |
| **Coding-agent-heavy teams** | Many commits come from agent sessions with thin commit messages | The "why" behind each change, recovered from session context |

## 3. Goals and non-goals

### Goals (hackathon)
1. **G1** — Correctly identify the culprit commit on a seeded-regression benchmark with known ground truth.
2. **G2** — Make noisy evals usable: statistical decision rule, resampling, explicit "inconclusive" state.
3. **G3** — Recover from real failures: uninstallable commits, flaky tools, killed process, budget exhaustion.
4. **G4** — Localise to the responsible hunk and produce a minimal fix that restores quality and preserves the intended gain, verified on held-out tasks.
5. **G5** — Deep, natural use of neatlogs, Entire and cfo.ai, with a measured v1 → v2 improvement of Culprit itself.

### Non-goals
- Not a general eval framework (we consume a simple suite format).
- No hosted multi-tenant SaaS, auth or billing during the hackathon.
- No support for arbitrary languages/frameworks: Python victim agents only.
- No automatic PR merging. Culprit proposes; humans merge.

## 4. Hackathon fit

| Rubric item (weight) | How Culprit scores |
|---|---|
| **The agent (30%)** | Plans a search, uses tools (git, worktrees, eval runner, neatlogs readback, Entire CLI), keeps state (SQLite ledger), recovers (skip/resample/resume/budget), verifies (CI-based decision + held-out suite) |
| **Required tools (25%)** | neatlogs and Entire are *inputs to the product*, not decoration; cfo.ai is fed measured cost-per-bisect from the ledger |
| **Demo (20%)** | "Make it faster" → validation removed → Culprit finds it, keeps the speedup, restores quality |
| **Building in public (15%)** | Honest v1 failures, recovery clip, before/after card (§16) |
| **Usefulness/originality (10%)** | Real, recurring pain for the exact audience of neatlogs/Entire |

**Mandatory submission items** (from neatlogs.com/hackathon): demo video ≤ 3 min covering all three tools · cfo.ai business plan · before/after run with compared numbers · neatlogs traces/screenshots · Entire checkpoints (link + ID) · a run showing recovery from a failed action · public share links tagged #neatHack · public repo with commits dated during the hackathon · X quote-post of the official neatlogs post with team name, project name, repo and demo.

## 5. User stories (MVP)

1. *As an agent engineer*, I run `culprit run --good v1.0 --bad HEAD --suite evals/` and get the culprit commit with a confidence statement.
2. *As an agent engineer*, I see each tested commit's pass rate with a 95% Wilson interval, cost and latency, plus links to the neatlogs traces of the failing runs.
3. *As an agent engineer*, I read *why* the culprit commit was made (the Entire session prompt/summary) next to the diff.
4. *As an agent engineer*, I get a minimal patch (one or more hunks) that restores quality, with evidence that the intended gain (e.g. latency) is retained.
5. *As an agent engineer*, if Culprit is killed mid-run, `culprit resume <run_id>` continues without re-running completed work.
6. *As a lead*, I get a shareable HTML report I can attach to a PR.

## 6. Scope

### MVP (must ship)
- `culprit` CLI: `run`, `resume`, `report`, `bench`.
- Victim agent + 20-task eval suite with deterministic checkers.
- Victim repo history with **6 seeded regressions** and noise commits, including one uninstallable commit.
- Noise-aware bisect: Wilson interval decision rule, resampling, skip semantics, budget caps.
- SQLite run ledger; resumable.
- neatlogs tracing of every victim run and of Culprit's own reasoning; trace links in the report.
- Entire checkpoint context for the culprit commit (with a documented fallback).
- Hunk localisation + fix + verification on full suite + held-out tasks.
- Markdown and static HTML report.
- Benchmark harness (`culprit bench`) scoring Culprit against ground truth, used for the v1 → v2 comparison.
- Cost export (CSV/Google Sheet) for cfo.ai.

### Stretch (only after MVP is frozen)
- GitHub Action: run Culprit on a PR when the eval pass rate drops.
- Entire Trail for the v1 → v2 fix of Culprit (requires Trails access from the Entire team).
- Entire Graph used by our coding agent during the build.
- Multi-culprit detection (two independent regressions in one range).
- Small web viewer for reports.

### Cut order (drop first → last)
1. Web viewer → 2. GitHub Action → 3. Multi-culprit → 4. HTML report (keep markdown) → 5. Held-out tasks (keep full-suite verification) → 6. Automatic fix writing (fall back to "revert hunk X" + re-verification).

**Never cut:** seeded benchmark with ground truth, ledger, decision rule, recovery paths, neatlogs traces, Entire checkpoints, cfo.ai plan.

## 7. System design

```
                ┌──────────────────────────── Culprit (orchestrator agent) ───────────────────────────┐
 culprit run ──▶│ Planner ─▶ Bisect Controller ─▶ Commit Evaluator ─▶ Decision Rule ─▶ Localiser ─▶ Fixer │
                │     │              │                   │                               │           │
                │     ▼              ▼                   ▼                               ▼           │
                │  Task Selector   Worktree Sandbox    Eval Runner ──▶ Victim Agent    Verifier      │
                │     ▲                                   │  (mock tools)                │           │
                │     └── neatlogs readback ◀─────────────┘                              ▼           │
                │                                                     Entire context   Report        │
                └───────────────────────────────── SQLite Run Ledger ─────────────────────────────────┘
```

| Component | Type | Responsibility |
|---|---|---|
| **Planner** | LLM | Reads suite + good/bad baselines, sets sampling plan (k, task subset) within budget |
| **Task Selector** | Deterministic + LLM | Deterministically ranks tasks by pass-rate delta (good vs bad); LLM inspects failing traces to choose a small *discriminating* subset and avoid flaky tasks |
| **Bisect Controller** | Deterministic | Midpoint selection over `git rev-list --first-parent good..bad`, skip semantics, state transitions |
| **Worktree Sandbox** | Deterministic | `git worktree add` per commit, isolated venv install (`uv`), timeouts, cleanup |
| **Eval Runner** | Deterministic | Runs victim agent on tasks × k, applies checkers, records pass/fail, cost, latency, trace ID |
| **Decision Rule** | Deterministic | Wilson 95% interval vs threshold → GOOD / BAD / INCONCLUSIVE (§8.2) |
| **Localiser** | LLM + deterministic check | Ranks culprit hunks using diff + Entire intent + failing traces; tests single-hunk reverts |
| **Fixer** | LLM | Writes a minimal patch that restores behaviour while keeping the intent (e.g. keep caching, restore validation) |
| **Verifier** | Deterministic | Full suite + held-out tasks × k on `bad+fix`; checks quality CI and intended-gain metric (§10) |
| **Ledger** | SQLite | Every step, result, cost; enables resume and cfo.ai export |
| **Report** | Deterministic | Markdown/HTML with timeline, CIs, diff, intent, trace links, checkpoint links, costs |

### Stack
Python 3.12 · `uv` · Typer (CLI) · SQLite (`sqlite3`) · Anthropic SDK (Claude) · neatlogs Python SDK + CLI/Public API · Entire CLI · Jinja2 (report) · pytest.
Models: a cheap, fast model for the victim agent (temperature 0) and a stronger model for Culprit's reasoning steps. Exact model IDs chosen at kickoff from current pricing.

## 8. Core algorithms

### 8.1 Noise-aware bisect
1. Evaluate `good` and `bad` refs on the full suite × k. Abort with a clear message if the gap isn't significant (CIs overlap) — "no regression to bisect".
2. Threshold `t = (p_good + p_bad) / 2`.
3. Task Selector picks the discriminating subset `D` (default 8 tasks) from tasks that pass on good and fail on bad.
4. Loop over the candidate range (first-parent history):
   - Pick midpoint `m`. Create worktree, install.
   - **Install/import fails** → mark `SKIP`, test the nearest untested neighbour (alternate left/right), like `git bisect skip`.
   - Run `D × k` (default k=3). Apply decision rule.
   - **INCONCLUSIVE** → resample (add k more runs, then widen to more tasks) up to a per-commit cap. If still inconclusive, decide by point estimate and flag the step `low_confidence`.
5. Output: first BAD commit after the last GOOD commit. If a SKIP commit sits on the boundary, report the range (as `git bisect` does).

### 8.2 Decision rule (deterministic)
For a commit with `s` passes in `n` runs, compute the 95% Wilson score interval `[L, U]`.
- `L ≥ t` → **GOOD**
- `U ≤ t` → **BAD**
- otherwise → **INCONCLUSIVE**

Constants (`z = 1.96`, k, caps) live in config and are recorded in the ledger for every run.

### 8.3 Localisation
1. Split the culprit diff into hunks.
2. LLM ranks hunks using: the diff, the Entire session intent for that commit, and the failing traces (tool calls, errors) pulled from neatlogs.
3. For the top-N hunks (default 3), apply the reverse of that single hunk on `bad` and run `D × k`. The first hunk whose revert flips BAD → GOOD is the responsible hunk. If none do, try pairs (cap), then fall back to "whole commit".

### 8.4 Fix
The Fixer gets: the responsible hunk, the commit intent (e.g. "make it faster"), and the intended-gain metric. It writes a patch that restores the lost behaviour **without** reverting the whole commit (e.g. keep the parallel tool calls, restore result validation). If its patch fails verification twice, fall back to the single-hunk revert, which is already verified.

## 9. Victim agent and seeded benchmark

### 9.1 Victim agent: "RefundDesk"
A customer-support agent that resolves refund requests using **mock tools** backed by a local JSON store:
`lookup_order`, `get_refund_policy`, `issue_refund`, `escalate_to_human`, `send_customer_email`.
The mock layer can inject failures (timeouts, `status: failed` payloads) deterministically per task seed.

**Eval suite:** 20 tasks + 6 held-out tasks. Each task = customer message + initial store state + **deterministic checker** on the final store state and tool-call log (e.g. "refund issued exactly once for ≤ $500", "escalated when order not found", "no refund when lookup failed").

### 9.2 Seeded regressions (ground truth)
Each scenario is a commit range of ~12–16 commits in the separate victim repo, with noise commits (docs, refactors, logging) around one culprit.

| ID | Culprit change | Intended gain | Symptom |
|---|---|---|---|
| **R1 (hero)** | "Make it faster": coding agent parallelises tool calls and **removes tool-result validation** | Lower latency | Refunds issued when `lookup_order` failed |
| R2 | Prompt cleanup drops the "> $500 needs escalation" rule | Shorter prompt / cost | Large refunds issued without escalation |
| R3 | Tool schema renames `order_id` → `id` without updating the description | API consistency | Wrong/missing arguments on lookup |
| R4 | `max_retries` 3 → 0 "to reduce latency" | Latency | Fails on flaky-tool tasks |
| R5 | Conversation history window shortened | Token cost | Loses customer details from earlier turns |
| R6 | Lenient JSON parsing of tool calls | Fewer parse errors | Malformed calls executed with defaults |

Plus **one uninstallable commit** (broken dependency pin) placed near the midpoint of at least two scenarios, to exercise skip recovery.

**Honesty rule:** The regressions are deliberately seeded. R1 is created through a real coding-agent session (captured by Entire) given the instruction "make it faster". We say this plainly in the demo and README.

## 10. Verification

A fix is **verified** only if all hold:
1. **Quality:** On full suite + held-out tasks × k, the Wilson interval for `bad+fix` overlaps or exceeds the `good` baseline interval.
2. **Intended gain kept:** The intent metric (latency / tokens / cost, taken from the commit intent) for `bad+fix` is no worse than `bad` by more than a configured tolerance.
3. **No new failures:** No task that passes on `good` fails consistently (all k) on `bad+fix`.

**Benchmark verification of Culprit itself** (`culprit bench`): for each of R1–R6, record whether the culprit commit was correct, whether the hunk was correct, whether the fix verified, victim runs used, cost, wall time. Ground truth is stored in `bench/ground_truth.json` in the Culprit repo (never in the victim repo). Victim history branches use neutral names (`hist/a`…`hist/f`); the scenario mapping lives only in the Culprit repo.

## 11. Failure handling and recovery

| Failure | Detection | Recovery | Shown in demo? |
|---|---|---|---|
| Commit won't install/import | Non-zero exit / import error in worktree | Mark SKIP, test neighbours | **Yes** |
| Noisy result (e.g. 3/5) | Wilson interval straddles threshold | Resample up to cap; flag `low_confidence` | **Yes** |
| Process killed | Ledger has incomplete run | `culprit resume <run_id>` skips completed steps | Yes (short) |
| LLM/API rate limit or 5xx | Exception from SDK | Exponential backoff, then mark step retryable | Trace only |
| Budget cap hit | Ledger cost ≥ cap | Stop, report best current range + what remains | Trace only |
| Fixer patch fails verification | Verifier fails | Retry once with failure evidence, then fall back to verified hunk revert | If it happens |
| Entire context unavailable | CLI error / empty output | Use commit message + diff; report states "intent unavailable" | No |
| No significant regression | good/bad CIs overlap | Exit cleanly with explanation | No |

## 12. Data model (SQLite ledger)

- `runs(run_id, repo, good_ref, bad_ref, suite_hash, config_json, status, started_at, finished_at, total_cost_usd, culprit_sha, confidence)`
- `steps(step_id, run_id, kind[baseline|bisect|resample|localise|fix|verify], commit_sha, status, decision, wilson_low, wilson_high, n, passes, cost_usd, latency_ms_p50, started_at, finished_at, error)`
- `task_runs(id, step_id, task_id, repetition, passed, cost_usd, latency_ms, tokens_in, tokens_out, neatlogs_trace_id)`
- `llm_calls(id, run_id, step_id, purpose, model, tokens_in, tokens_out, cost_usd, neatlogs_trace_id)`
- `artifacts(id, run_id, kind[intent|diff|patch|report], path_or_text)`

Every write is idempotent by `(run_id, step kind, commit_sha, task_id, repetition)` so resume never double-counts.

## 13. CLI

```bash
culprit run --repo ../refunddesk --good <ref> --bad <ref> --suite evals/ \
            [--k 3] [--budget-usd 3.00] [--heldout evals/heldout/] [--no-fix]
culprit resume <run_id>
culprit report <run_id> [--html out/report.html]
culprit bench --scenarios bench/scenarios.yaml [--tag v1|v2]
culprit export-costs [--format csv] > costs.csv     # input for cfo.ai
```

**Report contents:** verdict + confidence · bisect timeline (commit, decision, Wilson interval, n, cost, latency) · skipped commits · culprit diff with responsible hunk highlighted · Entire intent + checkpoint link/ID · links to failing neatlogs traces · proposed patch · verification table (good / bad / bad+fix: quality CI, latency, cost) · total cost and victim runs.

## 14. Required tools

### 14.1 neatlogs
- **Tracing:** every victim task run is a trace tagged `commit_sha`, `task_id`, `repetition`, `run_id`. Culprit's own LLM calls are traced separately.
- **Readback:** Task Selector and Localiser pull failing traces via the neatlogs CLI/Public API.
- **Detections:** regex rule on tool results containing `"status": "failed"` followed by `issue_refund`; condition rules such as `cost_usd > <cap>` for runaway runs.
- **Investigate:** used on Culprit **v1** benchmark runs to find why it misidentified or wasted runs.
- **Experiments (prompt versions):** Culprit's Localiser/Task Selector prompts versioned; v1 → v2 promoted by label.
- **Before/after:** `culprit bench --tag v1` and `--tag v2` on the same 6 scenarios. Metrics: culprit accuracy (x/6), hunk accuracy, fix verified (x/6), victim runs per bisect, cost per bisect, wall time. **Numbers are whatever the runs produce; nothing is estimated or rounded in our favour.**

**Instrumentation plan (apply at 12:30, from docs.neatlogs.com/sdk/python):**
- Install `pip install -U "neatlogs[anthropic]"` (Python ≥ 3.10, < 3.14). Key from `NEATLOGS_API_KEY` in `.env` (gitignored), never hardcoded. Default endpoint `https://ingest.neatlogs.com`.
- Two workflow names, one per entry point: `culprit-bisect` (Culprit CLI `run`/`resume`/`bench`) and `refunddesk-support-agent` (each victim task run, launched as a subprocess in a worktree).
- Capture Anthropic calls with **one** mechanism only: `neatlogs.wrap(Anthropic())` (the docs example uses OpenAI; Anthropic auto-detection is stated, not shown), or `instrumentations=["anthropic"]` with `init()` before the import. Never both.
- `@neatlogs.span(kind="WORKFLOW")` on each CLI command and on the victim's task entry point; `kind="TOOL"` on mock tools and on Culprit's git/worktree/eval tools; `kind="AGENT"` on Selector/Localiser/Fixer.
- Per-run metadata via `wrap()` kwargs (`commit_sha`, `task_id`, `repetition`, `run_id`), which become `neatlogs.workflow.<key>`. This is inferred from the docs, so verify in the dashboard.
- Both entry points are one-shot processes, so call `neatlogs.flush()` then `neatlogs.shutdown()` at exit (in `finally`).
- Open: the docs don't show how to read the current trace ID. Ask on Discord or use the CLI/Public API to look traces up by `run_id`/`task_id` metadata.

### 14.2 Entire
- Both repos (`piedpiper-neathacks` = Culprit, `refunddesk` = victim) connected via the Entire GitHub App; `entire enable` in each.
- **Product use:** Culprit reads the culprit commit's session context (`entire checkpoint explain <sha>`) to recover intent.
- **Build use:** every meaningful commit of Culprit is checkpointed; the checkpoint for the v1 → v2 fix is the headline evidence (Sessions → Changes).
- **Trails** (if access granted): the v1 → v2 fix done as a Trail. **Graph** optional.
- Submission includes checkpoint link `https://entire.io/gh/OWNER/REPO/commit/FULL_SHA` and checkpoint ID.

### 14.3 cfo.ai
- **Input:** `culprit export-costs` → Google Sheet (cfo.ai lists Google Sheets as a data connection; fall back to manual upload/entry if the import doesn't work).
- **Measured actuals:** cost per victim run, victim runs per bisect, Culprit LLM cost per bisect, wall time.
- **Pricing scenarios to model** (hypotheses, not facts):
  - **A. Flat SaaS:** $49 / $199 per repo/month with a bisect quota.
  - **B. Customer's own model key + platform fee** (recommended hypothesis): customer pays victim-run LLM cost; we charge a platform fee.
  - **C. Metered:** platform fee + per-bisect charge.
- **Questions for Ari:** gross margin per customer under A vs B at 10/50/200 bisects/month · break-even repos with 2 founders · runway under base/upside/downside acquisition · stress test with a 10× more expensive victim agent.
- **Deliverable:** exported business plan (pricing, costs, revenue, runway) in `/business/` and linked from the README.

## 15. Success metrics

| Metric | Target for submission |
|---|---|
| Culprit accuracy on R1–R6 | Reported for v1 and v2 (aim: v2 ≥ v1 and ≥ 5/6) |
| Fix verified on R1 | Required for the demo |
| Recovery shown | ≥ 1 skip and ≥ 1 resample in a recorded run |
| Cost per bisect | Measured and within the per-bisect budget cap |
| Evidence complete | All mandatory submission items in §4 present |

Targets are aims, not claims. The README reports actual values only.

## 16. Building in public (drafts, not published)
1. **"Our bisect agent blamed the wrong commit 2/6 times. Here's the trace that showed why."** (use whatever v1 actually scored)
2. **15-second clip:** a midpoint commit fails to install → SKIP → neighbour tested → bisect continues; a 3/5 result → INCONCLUSIVE → resampled.
3. **Before/after card:** v1 vs v2 benchmark table + Entire checkpoint link of the fixing session + "one bisect costs us $__" from the cfo.ai model.

## 17. Demo video (≤ 3:00)

| Time | Scene |
|---|---|
| 0:00–0:20 | Problem: RefundDesk pass rate fell from __% to __% across 14 commits |
| 0:20–1:10 | `culprit run`: baselines, discriminating tasks chosen from neatlogs traces, bisect timeline with Wilson intervals; **uninstallable commit skipped; 3/5 result resampled** |
| 1:10–1:40 | Culprit found: Entire checkpoint shows the request "make it faster"; responsible hunk = removed validation |
| 1:40–2:05 | Fix keeps parallel tool calls, restores validation; verification table: quality back to baseline, latency gain kept |
| 2:05–2:30 | neatlogs: v1 failure investigation → change → v2 benchmark numbers |
| 2:30–2:50 | cfo.ai: measured cost per bisect → pricing scenario → margin and runway |
| 2:50–3:00 | Repo, checkpoint link, #neatHack |

## 18. Build plan (IST)

**Before 12:30 Sat (planning only — no code):** accounts (neatlogs, Entire GitHub App, **Trails access form**, cfo.ai signup + immediate cancellation in Settings → Billing, Crustdata email signup with promo code if wanted); create the two empty GitHub repos; finalise this PRD.

| Window | Deliverable | Exit criterion |
|---|---|---|
| Sat 12:30–14:00 | Repos initialised, `entire enable`, neatlogs SDK traced hello-world, `hackathon.md`; **test `entire checkpoint explain <sha>` and neatlogs readback** | Both risks resolved or fallback chosen |
| Sat 14:00–19:00 | **Vertical slice:** RefundDesk + 10 tasks + 2 regressions (R1, R4); simple bisect (no resampling); ledger with cost | `culprit run` finds R1 end-to-end, traced |
| Sat 19:00–01:00 | Wilson rule, resample, skip, resume; all 20 tasks + R1–R6 + uninstallable commit; `culprit bench`; **freeze v1, run `bench --tag v1`** | v1 numbers recorded |
| Sun 09:00–13:00 | neatlogs Investigate on v1 failures; Detections; improve Selector/Localiser; **run `bench --tag v2`** | v1 vs v2 table |
| Sun 13:00–17:00 | Localiser + Fixer + Verifier; held-out tasks; HTML report | R1 fix verified |
| Sun 17:00–21:00 | `export-costs` → sheet → cfo.ai model (A/B/C + stress test); office hours | Business plan exported |
| Sun 21:00–23:00 | README, reproducible demo script; **feature freeze 23:00** | Clean run from fresh clone |
| Mon 10:00–15:00 | Evidence pack: traces, Detections, checkpoint link + ID, bench tables, recovery run, business plan | Submission checklist ✔ |
| Mon 15:00–18:00 | Record + edit video | ≤ 3:00, all three tools covered |
| Mon 18:00–19:00 | Buffer; **quote-post at 19:00** (first 50 get engagement) | Submitted |

## 19. Budget

- **LLM:** hard cap per bisect in config (start at $3.00); global cap $75 across the event, tracked in the ledger. If exceeded: reduce k, shrink D, or use a cheaper victim model.
- **Victim runs:** temperature 0, prompt caching, short tasks to keep cost per run low.
- **AWS ($25 shared):** not on the critical path; use only for hosting the report if it arrives.
- **Crustdata:** not used (no natural fit). Stated explicitly so it isn't mistaken for an omission.

## 20. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| `entire checkpoint explain <sha>` may not accept arbitrary SHAs or give parseable output (only `explain HEAD` is documented in the hackathon guide) | Loses the "why" | Test in hour 1; fallback to commit message + diff; check `entire --help` / docs |
| neatlogs readback API details not visible in the setup guide fetch | Selector can't read traces | Test in hour 1; fallback: Culprit records tool logs locally and links trace IDs only |
| Eval noise too high | Wrong culprit | Temperature 0, deterministic mock tools, strong seeded regressions, resampling |
| Cost per bisect higher than expected | Budget | Caps, smaller D, k=2 with resampling only when needed |
| Trails access not granted in time | Lose optional evidence | Checkpoints are mandatory and sufficient; Trails is stretch |
| Two repos complicate Entire setup | Setup time | Do it before the vertical slice |
| cfo.ai sheet import unclear | Delay | Manual entry of measured numbers |

**Open questions to confirm on Discord:** team-size limits, whether pre-written planning documents may be committed, and the submission form (marked "opening soon").

## 21. Submission checklist
- [ ] Public `piedpiper-neathacks` repo (Culprit) and `refunddesk` victim repo, with commits dated Oct 10–12
- [ ] README: problem, setup, run, demo script, limitations, honesty note on seeded regressions
- [ ] Demo video ≤ 3 min covering neatlogs, Entire, cfo.ai
- [ ] neatlogs: trace screenshots/links, Detections, Investigate finding, v1 vs v2 table
- [ ] Entire: checkpoint link + ID (fix session), Sessions/Changes screenshots
- [ ] Recovery run (skip + resample) recorded
- [ ] cfo.ai business plan in `/business/`
- [ ] `hackathon.md` build log up to date
- [ ] ≥ 3 #neatHack posts
- [ ] X quote-post of the official neatlogs post with team name, project name, repo, demo
