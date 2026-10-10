# neatlogs: how Culprit uses it, and what we found

Project: `Rahil's project` (`97d7e411-52c1-4c80-81d8-bd780d3ff71e`, free tier). Workflows: `culprit` (Culprit's own runs, session = run ID) and `refunddesk-eval` (one trace per victim task run, tagged `culprit_run_id`, `commit_sha`, `task_id`, `repetition`).

## 1. Tracing and readback (in the product)

- Every Culprit run is one `culprit` trace: git, worktree, install, every victim run, the regression gate, each `decision_rule`, the Entire call, Localiser and Fixer stages.
- `culprit verify-trace <run_id>` reads the trace back through the neatlogs CLI and checks it: finalized, one root, every parent present, span count matches, and `run_id` / `commit_sha` on every span. **All 12 benchmark runs pass** (trace IDs and span counts in `evidence/RUNS.md`).
- The Localiser reads failing victim runs' traces back through the CLI (`culprit/victim_traces.py`): the tool-call sequence (tool, arguments, outcome) for up to 3 failing runs. It is leak-filtered and goes into the hunk-ranking prompt. If readback fails, ranking proceeds without it.

## 2. Detection: "Upstream tool failure (failed payload)"

Created 10 Oct via the neatlogs MCP server (`create_detection`, after `preview_detection`). ID `94b590fe-54d4-40ad-829a-6194daca745c`, group Negative.

- **Rule:** regex on TOOL span output `"status":\s*"failed"`, run per TOOL span.
- **Preview:** it matched `issue_refund` spans returning `{"status":"failed","error":"issue_refund: upstream service error"}` (5 samples shown).
- **Why this rule:** a failed tool payload is the event RefundDesk must validate and retry. The hero regression (`397c427`) removed that validation and passed these results straight to the model.
- **Limit found:** the rule we wanted, one that fires only when a failed result *reaches the model*, isn't expressible.
  - A regex on LLM span **input** matched 0 spans with two different patterns.
  - Yet the full LLM input payload of a failing hero trace (`4482c66d66f01ec1d28104e99dfc15d0`, read back with `neatlogs traces payload`) contains `"status":"failed"`.
  - So the regex doesn't seem to scan the full LLM input. Cross-span sequences ("failed, then the model acts") aren't supported either (`BLOCKERS.md`).
  - The detection therefore fires on injected faults at good and bad commits alike. It documents the failure mode; it does not discriminate the regression. Culprit's statistics do that.
- **Result after the 14-day backfill:** **3,738 hits** on 10 Oct (`get_detection_trend`). The dashboard shows the badge on the hero run's victim traces (`screenshots/1-detection-firing-in-hero-run.png`, `2-trace-failed-tool-spans.png`).

## 3. Investigate

### 3a. Auto-triggered card (dismissed)

neatlogs opened a card by itself: **"Immediate timeouts in `lookup_order` and `issue_refund` tool calls"** (`da2eae02-…`, critical, `latency_anomaly`, confidence 0.71, 10 linked baseline traces).
- **Its hypothesis:** a misconfigured 0 ms timeout or a network rejection.
- **Actual cause:** RefundDesk's deliberately injected faults. `FaultPlan` raises `ToolTimeout` before the tool runs.
- **Action:** dismissed via MCP (`triage_dismiss`) as a false positive, with that explanation.

### 3b. Investigate run by hand on a hero-run trace (`screenshots/3-` to `7-`)

From the trace view, "Ask neat AI → Investigate the trace" ran **15 steps in about 1 minute** and produced **"Investigate Upstream Service Failures in lookup_order Tool"** (`d3ad23c8-0877-4c12-b619-4083d838c737`; high, category tool, label `silent_degradation`, confidence 0.63, 6 linked traces).
- **What it found:** four consecutive `lookup_order` calls returning `{"status":"failed",…}` in 0 ms. The agent then escalated and emailed the customer. It recommends checking the upstream service and adding exponential backoff.
- **What the trace really is:** `d5853d09…` is from Culprit run `978624283c27`, **baseline at `good-v1.0`**, task `lookup_failed_no_refund`, repetition 0. **That run passed.** The task makes every lookup fail on purpose, and the correct behaviour is to retry, refuse the refund and escalate, which is what the agent did.
- **Takeaway:** neatlogs Investigate flagged *correct, expected* behaviour of the known-good version as a high-severity degradation. Observability sees failures, but without a definition of "correct" it can't separate a regression from a designed-for failure.
  - Culprit supplies that missing piece: deterministic checkers define correct, and bisecting against a known-good ref names the commit that broke it.
  - On the same run, Culprit's verdict was the planted commit `397c427`, with the full Entire intent.

## 4. MCP limitations met

- `get_trace_context` returns `not_enabled` ("Selective trace context is disabled until the NL-1924 preview-column migration and API-first rollout are verified"), so trace contents were read with the CLI instead.

## 5. Cost discrepancy

neatlogs prices `claude-sonnet-5-5` at $3/$15 per MTok against Anthropic's $2/$10 list price. Culprit's own price table is the only cost source used (`BLOCKERS.md`, `evidence/neatlogs-cost-discrepancy.md`).
