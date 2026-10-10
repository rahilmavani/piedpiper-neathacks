# Blockers, unsupported features and known discrepancies

Each entry lists what the PRD assumed, what the tool actually supports (sources in `docs/research.md`), and the fallback we chose.

## Known discrepancies

### neatlogs cost for `claude-sonnet-5-5` differs from the list price

- **Observed:** for one call of 131 input and 18 output tokens, neatlogs reported `costUsd = 0.000663` (trace `ffdf497989747bf30856935f187e6013`, LLM span). That matches $3/$15 per MTok.
- **List price:** Anthropic's published list price for `claude-sonnet-5-5` is $2/$10 per MTok (cached 2026-10-06), which gives $0.000442 for the same call.
- **Decision:** Culprit's ledger (`culprit.llm.ANTHROPIC_PRICES`, $2/$10) is the only source of truth for cost, `export-costs` and cfo.ai. neatlogs' cost fields are not used in any cost number. Evidence tables that show neatlogs costs label them "neatlogs-reported, not used".

## Unsupported or changed vs the PRD

| PRD assumption | Reality | Fallback |
|---|---|---|
| Look up victim traces by `run_id` / `commit_sha` metadata (§14.1) | The read API and CLI can't filter on, or return, custom span attributes | Culprit stores every trace ID in the ledger. Its own traces use `session_id = run_id`, and run context also goes into each span's input JSON so readback can verify it |
| Read the current trace ID in code (§14.1 open question) | No getter in the SDK | `inject_trace_context()` W3C traceparent; verified to equal the read API's `traceId` |
| Investigate on v1 benchmark runs (§14.1) | No way to *start* an investigation from the API, CLI or MCP. They start from the dashboard ("Ask neat AI → Investigate") or automatically; the MCP can list, read and update the resulting fix cards (`triage_*`) | Ran one from the dashboard on a hero-run trace, and assessed the auto-triggered card too: `evidence/NEATLOGS.md` §3, screenshots in `evidence/screenshots/` |
| Detection "`status: failed` followed by `issue_refund`" (§14.1) | Checked on neatlogs CLI 0.2.0 (read-only: help, embedded API schema, `detections list/get`; nothing created). `detections create` accepts only four types: `classifier` (jailbreaking, nsfw, hate, refusals), `regex` (input/output pattern, AND/OR), `conditional` (field/operator rules, nested) and `pii`. Each runs per trace, span type or span name. Responses also know `trace_rules` (config `trace-rules.v1`: rows of span matches with quantifiers and a `relation` field), and the project already has one, created from a detection suggestion. But neither create nor update accepts `trace_rules`, and a suggestion run takes only `traceContextLimit`, so it can't be steered to a specific sequence. `preview`, `hits`, `trends` and `backfill` exist | A sequence rule can't be created from the CLI. Options: a `regex` rule on `issue_refund` spans plus a Culprit-side sequence check; the dashboard, if it can author `trace_rules`; or accepting a suggestion. Meanwhile the Localiser reads failing runs' tool sequences from traces directly (`victim_traces.py`) |
| `entire checkpoint explain` intent | The `## Intent` field can be a harness event (`<task-notification>`) or `*(no prompt recorded)*`, and `--json` carries no intent | Culprit reads the session's typed prompts from `--transcript` when Intent is a placeholder; commit message and diff when there is no checkpoint |
| OpenRouter provider | Dropped at first, then reinstated as the fallback (Sat evening) | Anthropic (Sonnet 5.5) when `ANTHROPIC_API_KEY` is set, otherwise OpenRouter (GLM 5.3). Culprit picks the victim model once per run and records it, so all commits are judged by the same model |
| Regex detection on LLM inputs (10 Oct, via MCP) | `preview_detection` with an `input_pattern` on LLM spans matched 0 spans, although the full LLM input of a failing hero trace contains `"status":"failed"`. The same pattern on TOOL span outputs works | Created the TOOL-output detection "Upstream tool failure (failed payload)" instead (`evidence/NEATLOGS.md` §2); Culprit's statistics do the discriminating |
| MCP `get_trace_context` | Returns `not_enabled` (NL-1924 migration pending) | Read trace payloads with the neatlogs CLI (`traces raw-spans`, `traces payload`) |
