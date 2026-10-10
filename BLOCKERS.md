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
| Investigate on v1 benchmark runs (§14.1) | Dashboard only; no API or CLI | Use Investigate by hand in the dashboard; record findings and screenshots in `evidence/` |
| Detection "`status: failed` followed by `issue_refund`" (§14.1) | Detections are per-span regex or conditional rules; a cross-span sequence can't be expressed in one rule | Not built yet (M4). Plan: regex on `issue_refund` tool spans plus a Culprit-side sequence check |
| `entire checkpoint explain` intent | The `## Intent` field can be a harness event (`<task-notification>`) or `*(no prompt recorded)*`, and `--json` carries no intent | Culprit reads the session's typed prompts from `--transcript` when Intent is a placeholder; commit message and diff when there is no checkpoint |
| OpenRouter provider | Dropped at first, then reinstated as the fallback (Sat evening) | Anthropic (Sonnet 5.5) when `ANTHROPIC_API_KEY` is set, otherwise OpenRouter (GLM 5.3). Culprit picks the victim model once per run and records it, so all commits are judged by the same model |
