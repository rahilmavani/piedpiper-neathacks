# neatlogs integration: coverage, evidence and how to repeat it

Host `https://app.neatlogs.com`, project "Rahil's project" (`97d7e411-52c1-4c80-81d8-bd780d3ff71e`).
SDK `neatlogs` 1.4.26 (Python 3.12), CLI `neatlogs-cli` 0.2.0. SDK Doctor `--local` and `--probe` both pass (synthetic evidence only).

## Trace contract as implemented (`src/culprit/tracing.py`)

- **Process init:** one `neatlogs.init(workflow_name="culprit", tracer_provider=...)` per CLI process (`culprit.cli:main`), followed by flush and shutdown in a `finally`.
- **Run root:** each run is one WORKFLOW root, `culprit_run`, whose `session_id` is the Culprit `run_id`. The read API cannot filter on custom metadata, so use `traces list --session <run_id>`.
- **Child spans:** CHAIN `evaluate_commit:<kind>` per evaluated commit. TOOL spans: `git_rev_list`, `pin_suite`, `discover_tasks`, `git_worktree_add`, `uv_sync_locked`, `victim_eval_run` (one per task × repetition), `select_discriminating_tasks`, `decision_rule` and `entire_checkpoint_explain`.
- **LLM calls:** captured only through `neatlogs.wrap(client)` in `culprit.llm`, each under the AGENT span of the stage that made it.
- **`run_id` / `commit_sha`:** a span processor stamps both as attributes on every span. Both are also written into every Culprit span's JSON input, because the read API returns no custom attributes and the input is the only place readback can verify them.
- **Errors:** a span that sees an exception records it and sets status `ERROR` (`trace()` alone leaves it `OK`). The run is also marked `error` in the ledger.
- **Thread pool:** victim runs execute in a thread pool. Each task is submitted with `contextvars.copy_context()`, so its span parents under the current step.

## Coverage

| Capability | Entry point | Capture | Verification | Status |
|---|---|---|---|---|
| Bisect run (git, worktree, install, eval runs, decision, Entire) | `culprit run` | WORKFLOW + CHAIN + TOOL spans | `culprit verify-trace <run_id>` | **PASS (fixture victim)**: trace `3e8d50b4584b831185c65a33007c7533`, 151 spans, finalized; counts match the ledger (120 victim runs, 7 steps, 4 decisions, 1 SKIP) |
| Bisect run, error path | `culprit run --suite <missing>` | same, status `ERROR` | `verify-trace` + `raw-spans` | **PASS**: trace `af423d7e5c1796cf4c7600dd29cc636b`, the failing span and the root are `ERROR` with type and message |
| Resume after budget stop | `culprit resume <run_id> --budget-usd 3` | new WORKFLOW root, same session | `verify-trace` audits every trace of the run | **PASS (fixture)**: run `d08379ebcc1e`. Stopped trace `951b10cc654b91c53d3e6fc7dbca3c81` (90 victim runs, status ERROR from the cap exception) and resume trace `3be78f457d6c3d4ab106deca2680c9df` (60 new victim runs only) |
| Noise-aware bisect (Wilson, resample, widen, low-confidence) | `culprit run` | `decision_rule` TOOL span per round, `evaluate_commit:resample:N` | `verify-trace` | **PASS (fixture)**: trace `3498c9e1e497ed665200cfaba3a2cb86`, 189 spans, 150 victim runs = ledger |
| LLM call path (`culprit.llm`, Anthropic) | `scripts/llm_capture_check.py` | `wrap()` under an AGENT span | `traces spans list <id> --type LLM` | **PASS (fixture)**: trace `ffdf497989747bf30856935f187e6013`, LLM span parented under AGENT, 131/18 tokens match the SDK usage |
| Planner, Task Selector (LLM), Localiser, Fixer | not built yet (M2–M5) | AGENT + LLM via `wrap()` | rerun the evidence loop after each milestone | Pending |
| Victim runs launched by Culprit (`refunddesk` workflow) | `victim_eval_run` → `python -m refunddesk.eval` | traced by the victim; Culprit records the returned `trace_id` | read back by trace ID | Pending: `../refunddesk` doesn't have the agent yet |

**Overall: PARTIAL.** Every implemented workflow passes. The rows still pending cover components that don't exist yet.

## Known differences

- **Cost:** neatlogs reported $0.000663 for 131 in / 18 out on `claude-sonnet-5-5`, which matches $3/$15 per MTok. Culprit's ledger uses Anthropic's $2/$10 list price, which is the source of truth for all cost numbers and cfo.ai; neatlogs' cost figures are not used (see `evidence/neatlogs-cost-discrepancy.md`).
- **Root output fill-in:** when a root span has no output (for example after an exception, before the fix), the backend showed a child span's output in its place.

- **SIGKILL:** a killed process cannot flush, so its trace never finalizes. The ledger still resumes it correctly (tested), and the resume gets its own finalized trace.

## Repeat the evidence loop

```bash
set -a; source .env; set +a                 # NEATLOGS_API_KEY (ingest), ANTHROPIC_API_KEY, CULPRIT_MODEL, ...
# readback credential: saved CLI OAuth (`neatlogs auth login --device`, profile `work`, project bound with
# `neatlogs profile set work --host https://app.neatlogs.com --project <uuid>`), or NEATLOGS_TOKEN.
# The ingest key must never be used for reads; scripts/nl-read and culprit.readback strip it.

uv run python tests/fixtures/make_victim.py /tmp/victim       # throwaway fixture victim
uv run culprit run --repo /tmp/victim --good good-v1.0 --bad main
uv run culprit verify-trace <run_id>                          # PASS/FAIL per trace
scripts/nl-read --json traces raw-spans <trace_id> --limit 50
scripts/nl-read --json traces list --session <run_id> --workflow culprit
```

Inside `uv run`, the name `neatlogs` resolves to the Python SDK's own script. `culprit.readback` therefore skips the venv's `bin/` directory when looking for the CLI, or uses `NEATLOGS_CLI` if it's set.
