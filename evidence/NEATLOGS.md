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

## 3. Investigate (auto-triggered fix card)

neatlogs opened one card by itself: **"Immediate timeouts in `lookup_order` and `issue_refund` tool calls"** (`da2eae02-f910-42e4-88a6-cee30aa08d92`, severity critical, label `latency_anomaly`, confidence 0.71, 10 linked traces from 08:35–09:28 UTC).

- **Its hypothesis:** a misconfigured 0 ms timeout or a network rejection.
- **Actual cause:** the timeouts are RefundDesk's **deliberately injected faults**. `FaultPlan` raises `ToolTimeout` before the tool runs, so they take 0–1 ms. The linked traces are the baseline suite runs.
- **Verdict:** a false positive, and an understandable one. neatlogs can't know the faults are synthetic. The card is left open for the team to dismiss (dismissing needs a team member's email).
- **Takeaway:** neatlogs flags *that* something fails. It can't say *which commit* made it fail or whether it's expected. Culprit answers that by bisecting against a known-good ref.

## 4. MCP limitations met

- `get_trace_context` returns `not_enabled` ("Selective trace context is disabled until the NL-1924 preview-column migration and API-first rollout are verified"), so trace contents were read with the CLI instead.

## 5. Cost discrepancy

neatlogs prices `claude-sonnet-5-5` at $3/$15 per MTok against Anthropic's $2/$10 list price. Culprit's own price table is the only cost source used (`BLOCKERS.md`, `evidence/neatlogs-cost-discrepancy.md`).
