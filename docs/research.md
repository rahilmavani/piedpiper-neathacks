# Research notes: neatlogs, Entire, cfo.ai (for Culprit)

Researched 2026-10-10. Sources: `https://docs.neatlogs.com/llms-full.txt` (full docs bundle), the locally installed `neatlogs` CLI v0.2.0 (`--help` and the offline `schema` commands), `https://github.com/neatlogs/skills`, the PyPI metadata and wheel for `neatlogs` 1.4.26, `https://docs.entire.io/llms-full.txt`, the local `entire` CLI 0.11.4 (read-only), `https://cfo.ai/llms.txt` and `https://docs.cfo.ai`.
Anything marked **unconfirmed** is not stated in the docs.

---

## 1. neatlogs

### 1.1 Python SDK: install, versions, init
Source: https://docs.neatlogs.com/sdk/python

- Package `neatlogs` on PyPI. The latest version per the PyPI JSON is **1.4.26**, with `requires_python >=3.10,<3.14`. The local `pip index` showed only 1.1.8, so it is probably a stale mirror. Pin to `>=1.4`.
- Extras: `neatlogs[openai]`, `neatlogs[anthropic]`, `neatlogs[langchain]`, `[google-genai]`, `[litellm]`, `[mcp]` and others. The PyPI extras list has **no `openrouter` extra**. The OpenRouter docs install `pip install -U neatlogs openrouter`.
- `init()` is single-shot per process. A second call is a no-op and does not switch `workflow_name` or the key. After `shutdown()` you may init a new "generation".
- `init()` parameters (all documented):

| param | default | note |
|---|---|---|
| `api_key` | `NEATLOGS_API_KEY` env | if unset, spans are created but **silently not exported** |
| `endpoint` | `https://ingest.neatlogs.com` | EU: `https://eu.ingest.neatlogs.com` |
| `workflow_name` | script filename | process-wide label |
| `instrumentations` | — | e.g. `["anthropic"]`; init **before** importing the lib |
| `tags` | — | list[str] on every trace from the process |
| `user_id` | — | operator/service identity (`user.id`) |
| `capture_logs`, `log_level` | False, "INFO" | LOG spans |
| `sample_rate` | 1.0 | |
| `flush_interval` | 5.0 s | |
| `batch_size` | 100 | |
| `mask` | — | client-side transform |
| `pii_enabled`, `pii_entities`, `pii_span_types` | project setting | persisted server-side |
| `debug` | False | |
| `tracer_provider`, `isolate`(deprecated), `register_shutdown_handlers`(True), `uploads_enabled`(False) | | |

```python
import os, neatlogs
neatlogs.init(api_key=os.environ["NEATLOGS_API_KEY"], workflow_name="culprit", tags=["v1"])
from anthropic import Anthropic            # import after init (needed only for instrumentations=[...])
client = neatlogs.wrap(Anthropic())        # Anthropic is explicitly documented (sync, async, streaming, AnthropicBedrock)
try:
    ...
finally:
    neatlogs.flush(timeout_millis=10_000)
    neatlogs.shutdown(timeout_millis=10_000)
```
- Lifecycle (https://docs.neatlogs.com/sdk/lifecycle): scripts and CLIs should call flush and then shutdown in `finally`. `flush_all()` drains every Neatlogs client. `flush`/`shutdown` are synchronous; in async code use `await asyncio.to_thread(neatlogs.flush)` (skill troubleshooting).
- Use **one capture owner per operation**: `wrap()` or `instrumentations=[...]`, never both (skill rule).

### 1.2 `wrap()` and per-trace metadata
- `neatlogs.wrap(client, **kwargs)`: "Extra keyword arguments to `wrap()` are stamped on the resulting trace root as `neatlogs.workflow.<key>` attributes, so they show in the metadata drawer and are searchable."
  ```python
  client = neatlogs.wrap(Anthropic(), run_id=rid, commit_sha=sha, task_id=t, repetition=r)
  ```
  - Caveat: kwargs are bound once per wrapped client, so a new wrapped client per task run would be needed to vary them (inference, **unconfirmed**).
  - **These attributes are NOT returned by the Public API/CLI trace or span schemas** and are not filterable there (see 1.6). "Searchable" refers to the dashboard. The MCP `search_traces` says it matches "trace names, error messages, span names, and metadata".
- Per-root attributes: `neatlogs.trace(name, kind=None, ..., session_id=None, end_user_id=None, end_user_metadata=None, **attributes)`. The signature comes from the SDK source `core/context.py`; the docs show the subset `name, kind, system_prompt_template, user_prompt_template, version, mask`. The context manager yields a span with `.set_attribute(k, v)`.
- **Workflow label per trace** (https://docs.neatlogs.com/sdk/multiple-workflows): the process default comes from `init(workflow_name=)`. Override it per root with
  ```python
  with neatlogs.trace("Culprit bisect", kind="WORKFLOW") as root:
      root.set_attribute("neatlogs.workflow_name", "Culprit bisect")
  ```
  The span name alone does **not** change the Workflow column.
- **Session** (https://docs.neatlogs.com/sdk/sessions): `@neatlogs.span(kind="WORKFLOW", session_id=...)`, `neatlogs.trace("x", session_id=...)`, or `with neatlogs.identify(session_id=..., parent_session_id=..., session_custom_fields={...}, end_user_id=...)`. If no session is given, `session_id = trace_id`. **`sessionId` is a first-class, filterable field in the Public API/CLI** (`--session`), which makes it the most practical carrier for `run_id`.
- Tags: only `init(tags=[...])` (process-wide). They can be changed after the fact with `neatlogs traces update-metadata` / `PATCH /traces/{id}`, which takes `tags`, `traceName` and `expectedRevision` and needs a service-account/OAuth token. Tags are returned in trace reads but are **not a list filter**.

### 1.3 `@span` decorator and kinds
- `@neatlogs.span(kind=..., name=None, role=, goal=, tool_name=, parameters=, description=, capture_input=True, capture_output=True, mask=, capture_stdout=False, session_id=)`. Works on sync and async functions. It captures args as `input.value` and the return value as `output.value`.
- Kinds accepted by `@span`: `WORKFLOW, AGENT, CHAIN, TOOL, RETRIEVER, EMBEDDING, GUARDRAIL, MCP_TOOL` (anything else raises `ValueError`). `RERANKER` and `VECTOR_STORE` are available only through `trace()`. `LLM` comes from `wrap()` or auto-instrumentation.
- Decorate the entry point with `kind="WORKFLOW"` to get one trace root. Otherwise each wrapped call becomes its own trace.
- Stacking: `@neatlogs.span` goes **below** transforming decorators (`@tool`, `@function_tool`).
- **Manual TOOL span for a non-LLM operation** (https://docs.neatlogs.com/sdk/custom-attributes):
  ```python
  @neatlogs.span(kind="TOOL", tool_name="git_checkout", description="checkout commit in worktree")
  def git_checkout(sha: str) -> str: ...

  with neatlogs.trace("run_eval", kind="TOOL") as span:
      span.set_attribute("neatlogs.tool.name", "run_eval")
      span.set_attribute("neatlogs.tool.description", "run victim suite")
      span.set_attribute("neatlogs.tool.parameters", json.dumps(schema))
  ```
  A standalone non-root `TOOL` span gets an automatic workflow parent.
- Logs: with `init(capture_logs=True)`, `neatlogs.log("msg {k}", level="info", k=v)` creates LOG spans. It must be called inside an active span.

### 1.4 Current trace ID in code
- **There is no documented `get_current_trace_id()`.** The public exports in `neatlogs/__init__.py` (1.4.26) include `init, flush, shutdown, flush_all, span, trace, identify, inject_trace_context, extract_trace_context, log, wrap, Client, get_prompt, ...`, but nothing named like a trace-id getter.
- **A documented workaround** uses `neatlogs.inject_trace_context(carrier) -> bool`. It writes W3C `traceparent` into any mutable mapping when a Neatlogs span is active (https://docs.neatlogs.com/sdk/distributed-tracing). The trace ID is field 2 of `traceparent` (`00-<32hex trace_id>-<16hex span_id>-<flags>`):
  ```python
  with neatlogs.trace("task_run", kind="WORKFLOW") as root:
      carrier: dict = {}
      trace_id = carrier["traceparent"].split("-")[1] if neatlogs.inject_trace_context(carrier) else None
  ```
  - Whether this 32-hex OTel trace ID equals the `traceId` used by the Public API is **unconfirmed**, though it is likely: the Doctor probe compares "captured and read-back trace IDs ... exactly" and its sample shows a 32-hex id.
  - `span.get_span_context().trace_id` on the yielded span is **unconfirmed** (the span looks like an OTel span from the source, but this is not documented).

### 1.5 Context propagation (threads, subprocesses)
- Cross-process propagation is explicit through W3C `traceparent`/`tracestate`. Neatlogs uses a **private** propagator, so a bare `opentelemetry.propagate.inject` writes nothing.
  - Caller: `neatlogs.inject_trace_context(carrier)`. It returns False and leaves the carrier untouched if no span is active, and it never overwrites an existing `traceparent`.
  - Callee: `with neatlogs.extract_trace_context(carrier, *, session_id=None, parent_session_id=None, session_custom_fields=None, end_user_id=None, end_user_metadata=None):`. The next `trace()`, `@span` or `wrap()` root inside it joins the remote trace. With no valid `traceparent` it is a no-op.
  - Session and end-user identity do **not** travel with `traceparent`; re-bind them on the callee.
- **Subprocess joining the parent trace:** this is supported mechanically, since the carrier is "any mutable header mapping". Passing it through an env var is our own convention and is **not documented**:
  ```python
  # parent
  env = dict(os.environ); c = {}; neatlogs.inject_trace_context(c); env["TRACEPARENT"] = c.get("traceparent", "")
  subprocess.run([...], env=env)
  # child (separate init() in the child process)
  with neatlogs.extract_trace_context({"traceparent": os.environ.get("TRACEPARENT", "")}, session_id=run_id):
      with neatlogs.trace("victim_task", kind="AGENT"): ...
  ```
  The child must call its own `init()` and `flush()`/`shutdown()` before exiting.
- Threads: **unconfirmed** for the default pipeline. `identify()` "is backed by context propagation so it flows across await/async boundaries". Secondary-client `activate()` uses `contextvars` per thread/task. Plain `ThreadPoolExecutor` workers do not inherit contextvars by default (general Python behaviour). Use `contextvars.copy_context().run(...)`, or open a root per task inside the worker.

### 1.6 Public CLI (`neatlogs` v0.2.0, npm package `neatlogs-cli`) for trace readback
Source: https://docs.neatlogs.com/cli/commands/traces and local `--help`

- Auth for automation (https://docs.neatlogs.com/cli/automation): use env `NEATLOGS_TOKEN` (service-account token `nlsa_...`, scope `observability:read`), `NEATLOGS_HOST=https://app.neatlogs.com` and `NEATLOGS_PROJECT_ID=<uuid>`. `NEATLOGS_API_KEY` is a "legacy fallback". **The auth page says SDK ingest credentials do not authorize Public API reads.** Plan for a separate service-account token.
- Global options go **before** the command: `--json | --jsonl`, `--fields <paths>` (≤32), `--project <uuid>`, `--host`, `--profile`, `--debug`.
- Exit codes: 0 ok, 2 usage, 3 auth, 4 denied, 5 not found, 6 conflict, 7 rate-limited, 8 network, 11 server.

Commands (exact flags):
```bash
neatlogs --json traces list [--from RFC3339] [--to RFC3339] [--status S] [--workflow NAME] [--session ID] \
         [--limit 1-50] [--cursor C] [--all --max-items 1-1000]
neatlogs --json traces search "<query>" [--from] [--to] [--workflow] [--session] [--limit] [--cursor] [--all --max-items]
neatlogs --json traces semantic-search "<query>"  (same flags as search)
neatlogs --json traces get <trace-id>                       # trace metadata only, no span tree
neatlogs --json traces spans list <trace-id> [--type T] [--status S] [--limit 1-50] [--cursor] [--all --max-items]
neatlogs --json traces spans get <trace-id> <span-id>
neatlogs --json traces raw-spans <trace-id> [--type] [--status] [--limit] [--cursor] [--all --max-items]  # input/output/error previews
neatlogs --json traces payload <trace-id> <span-id> --fields input,output,error   # full I/O values (required flag)
neatlogs --json traces export <trace-id> [--format json|markdown|csv]
neatlogs --json traces evaluations <trace-id>
neatlogs traces update-metadata <trace-id> --body-stdin [--idempotency-key UUID]   # WRITE: {tags, traceName, expectedRevision}
neatlogs sessions list | get <session-id> | export <session-id>
neatlogs schema list | search <q> | show <operationId>       # offline, no auth
```
- **There is no metadata filter** (no run_id or commit_sha filter) on list or search. The available filters are time, status, workflow and session.
- Python SDK side: `python -m neatlogs trace get <trace_id> [--json]` exists in SDK 1.4.26 (`trace_cli.py`, default host `https://app.neatlogs.com`), but the `neatlogs-public-api-cli` skill says not to use it: "Do not substitute the SDK PR's proposed `neatlogs trace get` command". Treat it as **unofficial**.

### 1.7 Public API
Sources: https://docs.neatlogs.com/api-reference/authentication and `neatlogs schema show`

- Base URL `https://app.neatlogs.com/api/v1/public` (EU: `https://eu.app.neatlogs.com/...`). Never use the ingest host for reads.
- Headers: `Authorization: Bearer <nlsa_ service-account | nloa_ OAuth token>` plus `x-project-id: <project-uuid>`. A legacy project key also works through `x-api-key` or Bearer on endpoints that list it, and all the trace reads below list it. Read scope: `observability:read`.
- Endpoints:
  - `GET /traces?from&to&status&workflowName&sessionId&limit(≤50)&cursor` returns `data.traces[]` + `data.page{hasMore,limit,nextCursor}`.
    Trace fields: `traceId, traceName, workflowName, sessionId, status, finalizationStatus, startedAt, completedAt, ingestedAt, durationMs, spansCount, llmCallsCount, toolCallsCount, totalTokens, totalCostUsd, tags[], framework`.
  - `GET /traces/{traceId}` returns the same fields plus `metadataRevision, metadataUpdatedAt`.
  - `GET /traces/{traceId}/spans?type&status&limit&cursor` returns spans with `spanId, parentSpanId, spanName, spanType, status, startedAt, endedAt, durationMs, model, provider, promptTokens, completionTokens, totalTokens, costUsd`. **No attributes and no I/O.**
  - `GET /traces/{traceId}/spans/{spanId}` returns the same fields for one span.
  - `GET /traces/{traceId}/raw-spans` returns spans with `input.preview`, `output.preview`, `error.messagePreview` (truncated flags).
  - `GET /traces/{traceId}/spans/{spanId}/payload?fields=input,output,error` returns `data.fields.{input,output,error}.{available,value,mimeType,truncated}`.
  - `GET /traces/{traceId}/export?format=json|markdown|csv`
  - `POST /search/traces` (body `q, from, to, workflowName, sessionId, limit, cursor`) and `POST /search/traces/semantic` return `results[].{trace, score, matchedSpans[]}`.
  - `PATCH /traces/{traceId}` (body `tags, traceName, expectedRevision`) requires a service-account/OAuth token.
  - `GET /sessions`, `GET /sessions/{id}`, `GET /sessions/{id}/export`.
- Pagination: `page.nextCursor`. Treat incomplete pagination as incomplete evidence (skill rule). Retry pending (not yet finalized) traces a bounded number of times.

### 1.8 MCP server
Sources: https://docs.neatlogs.com/integrations/mcp and https://docs.neatlogs.com/integrations/mcp-tools

- Streamable HTTP at `https://ingest.neatlogs.com/mcp`, with `Authorization: Bearer <PROJECT_KEY>`. This uses the project key, not a service-account token. Setup: `npx @neatlogs/wizard mcp --api-key KEY` or `.mcp.json`.
- Tools:
  - `ping`, `whoami`
  - `search_traces{query, limit, offset, filters{framework,status,min/max_latency_ms,min/max_cost,date_range}}`, which matches names, errors, span names and **metadata**
  - `get_trace_context{trace_id}`: full span tree **with inputs, outputs, metadata, code locations and the detections that fired**
  - `list_detections`, `get_detection_trend`
  - `log_trace`
  - `triage_list`, `triage_get`, `triage_get_investigation`, `triage_list_steps`, `triage_accept`, `triage_dismiss`, `triage_update_status`, `triage_update`
- The `neatlogs mcp` CLI group (`status/list/connect/...`) manages MCP *connections* for Tools & MCPs. It is not the server.

### 1.9 Detections
Sources: https://docs.neatlogs.com/docs/features/detections, https://docs.neatlogs.com/cli/commands/detections and the schema

- There are four types: **regex, condition (`conditional`), PII, classifier**. They are evaluated on spans as they arrive, are shown as badges, and the traces list can be filtered by them in the UI.
- They can be created through the **UI, CLI or API**. The API is `POST /api/v1/public/detections` and needs a service-account/OAuth token, `x-project-id` and (per the auth page) the `configuration:write` scope.
  ```bash
  neatlogs detections create --group <group-uuid> --name "tool failed" --type regex \
    --config '{"output_pattern":"\"status\":\\s*\"failed\"","case_sensitive":false}' \
    [--run-on '{"frequency":"span_type","span_types":["TOOL"]}'] [--threshold 0.5] [--inactive]
  ```
  - regex config: `{input_pattern?, output_pattern?, operator: AND|OR (default OR), case_sensitive: false}`
  - conditional config: `{conditions:[{field, operator(=,!=,>,<,>=,<=,contains,not_contains,in,not_in,is_empty,is_not_empty), value}], logic: AND|OR}` or a `root` tree. The valid `field` names (e.g. `cost_usd`, `total_tokens`) are **unconfirmed**; the feature page uses `total_tokens`, `latency_ms`, `tool_call_count`, `cost_usd` as examples.
  - pii config: `{entities: [EMAIL_ADDRESS|PHONE_NUMBER|CREDIT_CARD|IP_ADDRESS|URL]}`
  - classifier config: `{classifier_slug: jailbreaking|nsfw|hate|refusals}`
  - `runOn.frequency`: `trace | span_type | span_name`
  - A detection group is required: `neatlogs groups` / `POST /detection-groups`.
- Other commands: `detections list|get|hits <id>` (hits return `traceId, spanId, score, detectedAt`), `preview --request-stdin`, `generate --request-stdin`, `backfill <id> --body-stdin --confirm <id>`, `trends <id> --from --to`.
- A single regex matches one span's input or output. A rule like "`status: failed` *followed by* `issue_refund`" across spans is **not expressible as one regex rule** (**unconfirmed**, but nothing in the schema supports sequencing).

### 1.10 Investigate, Fixes, Experiments, prompts
- **Investigate** (https://docs.neatlogs.com/docs/features/ai-search) is a dashboard chat agent (Fast/Pro modes) with saved threads. **There is no Public API or CLI endpoint to start an investigation** (the schema list has nothing for it). Investigations behind fixes can be *read* through the MCP tools `triage_get_investigation` and `triage_list_steps`.
- **Fixes** (https://docs.neatlogs.com/docs/features/triage) are AI suggestions on a board and can be dispatched to Cursor Cloud Agents (Claude Code and Codex are "planned"). Read and manage them through the MCP `triage_*` tools only; they are not in the Public API.
- **Experiments** (https://docs.neatlogs.com/docs/features/experiments) has three parts:
  - Prompts: versioned and labelled.
  - Playground: UI only, BYOK.
  - Datasets: "coming soon".
- Managed prompts in the SDK: `neatlogs.get_prompt(name, label="production")`, `update_prompt(name=, version=, new_labels=[...])`, plus `create_prompt`, `list_prompts`, `save_as_version`, `fetch_prompt`, `aget_prompt`. See https://docs.neatlogs.com/sdk/prompt-templates.
- Prompts in the CLI: `neatlogs prompts list|create|get|history|labels|label <id> <label>|label-remove|bulk-labels|diff <from> <to>|changelog|tags|tag-add|tag-remove|comments|delete`. API: `/api/v1/public/prompts/...`.
- Template tracking: `with neatlogs.trace("x", kind="LLM", system_prompt_template=SystemPromptTemplate([...]), user_prompt_template=...)`.

### 1.11 SDK Doctor
Source: https://docs.neatlogs.com/sdk/doctor

- `python -m neatlogs doctor --local --json` is network-free and needs no key.
- `python -m neatlogs doctor --probe --json` needs `NEATLOGS_API_KEY` in the env. It sends a four-span trace (`POST /v1/traces`, header `x-neatlogs-doctor: v1`) and reads it back (`GET /api/traces/v3/{trace_id}`).
- Requirements: `format_version: "neatlogs.doctor/v2"`, `runtime.language: "python"`, `runtime.schema_version: "2"`.
- Output includes `capture.trace_id` and `probe.readback_trace_id`.
- A pass does not prove that the real workflow is instrumented.

### 1.12 Agent skills
Sources: https://docs.neatlogs.com/integrations/skills and https://github.com/neatlogs/skills

- Install: `npx skills add neatlogs/skills --skill "neatlogs-py" --agent "claude-code"`, which links into `.claude/skills/neatlogs-py/`. Alternatively use the Claude Code plugin: `/plugin marketplace add neatlogs/skills` then `/plugin install neatlogs-py@neatlogs`.
- Relevant SKILL.md files:
  - `skills/neatlogs-py/SKILL.md`, with references `decorators-and-traces.md`, `framework-integrations.md`, `troubleshooting.md`
  - `skills/neatlogs-py-setup/SKILL.md`
  - `skills/neatlogs-public-api-cli/SKILL.md`, with references `auth-and-operations.md`, `trace-readback.md`
  - `skills/neatlogs-multi-workflow/SKILL.md`
  - `skills/neatlogs-py-openai/SKILL.md` (there is no Anthropic-specific Python skill; Anthropic is covered in `neatlogs-py`)
- Key `neatlogs-py` rules:
  1. Order is `import neatlogs` → `load_dotenv()` → `neatlogs.init()` → LLM library imports.
  2. Scripts call `flush()` then `shutdown()`. Servers do not flush per request.
  3. One capture owner per operation, and never two capture layers for the same call. Use `@span` for your own orchestration and `trace(kind="LLM")` only when no wrapper owns the call.
  4. Prefer provider or framework integrations over manual spans.
  5. `init()` is single-shot. Use a secondary `Client` for a different project.
  6. Set an EU endpoint only for EU projects.
  7. Safety gate: run `python -m neatlogs doctor --local --json` before editing, and verify a real trace afterwards (completion gate). Do not claim success from a flush or an HTTP 2xx.
  8. Use `inject_trace_context`/`extract_trace_context`, never a bare OTel inject.
  9. Never put keys in commands, files or output.
- `neatlogs-public-api-cli` rules:
  - Read from the app origin, never the ingest host.
  - `traces get` returns metadata only; page through `traces spans list` for spans.
  - Use a service account with `observability:read` through `NEATLOGS_TOKEN`, `NEATLOGS_HOST` and `NEATLOGS_PROJECT_ID`.
  - Retry pending traces a bounded number of times.

### 1.13 OpenRouter / OpenAI-compatible
- Documented path (https://docs.neatlogs.com/integrations/openrouter): the `openrouter` Python SDK.
  ```python
  client = neatlogs.wrap(OpenRouter(api_key=...))
  client.chat.send(...)
  ```
  This traces `chat.send`, `beta.responses.send`, embeddings and rerank, with `provider="openrouter"`. `instrumentations=["openrouter"]` is also listed.
- `neatlogs.wrap(OpenAI(base_url="https://openrouter.ai/api/v1"))` is **unconfirmed**. The docs never mention `base_url` and OpenAI-compatible endpoints. It would probably be captured as an OpenAI span, but the provider/model attribution is untested.

---

## 2. Entire
Sources: https://docs.entire.io/cli-reference/checkpoint, https://docs.entire.io/guides/checkpoints/checkpoint-storage, https://docs.entire.io/guides/checkpoints/inspect-in-cli and https://docs.entire.io/guides/checkpoints/inspect-in-entire-io

- `entire checkpoint explain [CHECKPOINT_ID | COMMIT_SHA]` auto-detects the argument type. Force it with `-c/--checkpoint ID` or `--commit SHA` (any commit-ish, e.g. `HEAD~3`). A commit resolves through its `Entire-Checkpoint` trailer. Aliases are `entire cp` and `entire checkpoints`.
- Flags:
  - `--json`: metadata only. With no target it lists checkpoints (`--limit N`, default 100); with a target it returns a single envelope including `tasks`.
  - `--transcript`: streams the stored transcript JSONL to stdout. Combine with `--session-index N` or `--task TOOL_USE_ID`.
  - `--raw-transcript`, `--full`, `-s/--short`, `--generate [--force] [--summary-timeout-seconds N]` (needs a configured, authenticated provider CLI), `--search-all`, `--session ID`, `--no-pager`, `--repo gh/OWNER/REPO|et/PROJECT/REPO` (reads through the Entire API and needs the full ID of a pushed checkpoint).
- The `--json` fields were observed locally on 0.11.4 for commit `555c052`:
  - top level: `checkpoint_id, strategy, branch, checkpoints_count, files_touched[], session_count, sessions[], tasks[]`
  - each session: `index, session_id, agent, model, created_at, turn_id, files_touched[], token_usage{input_tokens, cache_creation_tokens, cache_read_tokens, output_tokens, api_call_count}`
  - **There is no intent, prompt or summary field in the JSON.** Intent appears in the default and `--short` text output (`## Intent`, `## Summary`), and the prompts are in `--transcript`.
- Storage:
  - The default backend since 0.10.0 is `git-refs`, with refs at `refs/entire/checkpoints/<shard>/<id>`. **`<shard>` is the last two characters of the ID**; this was confirmed locally, e.g. `refs/entire/checkpoints/X4/01M4JC93J3J3HGVCRVXZRDD4X4`.
  - IDs are 26-character ULIDs.
  - The legacy `git-branch` backend uses the `entire/checkpoints/v1` branch with 12-hex IDs.
  - The backend is set in `.entire/settings.json` under `checkpoints.primary.type`; this repo uses `git-refs`.
  - List refs with `git for-each-ref refs/entire/checkpoints/`. Check the remote with `git ls-remote origin 'refs/entire/checkpoints/*'`.
- Commits carry the trailer `Entire-Checkpoint: <id>`. Read it with `git log --format='%(trailers:key=Entire-Checkpoint,valueonly)'`.
- Fresh clone:
  - The docs say "Metadata missing locally is fetched from the checkpoint remote" for `checkpoint tokens`, and add that it resolves "through the same path as `checkpoint explain`". This is consistent with on-demand fetch during explain, but that is stated **indirectly**, not on the explain section itself.
  - Checkpoints are pushed with `git push` through the pre-push hook to one elected "checkpoint sync remote". `entire status` names it.
- Web URL format: `https://entire.io/gh/<org>/<repo>/commit/<commit-sha>` (documented). A direct checkpoint-ID URL is **unconfirmed**; the docs only show opening a checkpoint from the commit URL or from a session. Project URLs look like `https://entire.io/et/<project>/<repo>`.

---

## 3. cfo.ai
Sources: https://cfo.ai/llms.txt, https://docs.cfo.ai/integrations/integrations-directory.md, https://docs.cfo.ai/integrations/connect-and-sync-data.md and https://docs.cfo.ai/workspace-settings/file-attachments-in-chat.md

- **Google Sheets: yes.** It is a "Standard" connector under Integrations → Data upload. You pick one spreadsheet with the Google picker. The sheet is read as an Excel workbook of up to 50 MB with all tabs and formulas, and it re-syncs nightly (02:00 UTC) or on request to Ari. Google Drive also works for one Sheet, Excel or CSV file (≤10 MB).
- **CSV: yes.** "CSV / Raw File Upload" is a first-class source and not a billable integration. The file must have a `.csv` extension and be ≤50 MB, uploaded with the Upload button on the Integrations tab. A CSV attached in Ari chat can either become a data source or stay chat-only. An Excel upload is not accepted as a data source; attach it in chat or import it as a model instead.
- Column typing: numeric columns become summed Variables unless the name ends in "id" or similar, in which case they become a text Dimension. An untyped CSV column follows this name rule.

---

## Gaps / unsupported (vs PRD §14)
1. **Reading the current trace ID:** there is no documented getter. Use `inject_trace_context(dict)` and parse `traceparent` (documented API, our own parsing). That this ID equals the Public API `traceId` is likely but **unconfirmed**.
2. **Per-run metadata lookup (run_id, commit_sha, task_id, repetition through `wrap()` kwargs):** the attributes are written, but the **Public API/CLI cannot filter by them or return them**. Filters are limited to time, status, workflow and session. Options:
   - store the trace ID from (1) in the ledger, or
   - put `run_id` (or `run_id:sha`) into `session_id` and use `traces list --session`, or
   - use the per-root `neatlogs.workflow_name` override, or
   - try keyword search, though whether it matches attribute values is **unconfirmed** for the Public API.
3. **Readback credentials:** the SDK `NEATLOGS_API_KEY` (ingest) "does not authorize Public API reads". A service-account token (`NEATLOGS_TOKEN`, `observability:read`) plus the project UUID is needed. The MCP server, by contrast, accepts the project key.
4. **Span I/O and attributes** are not in `traces get` or `spans list`. You need `traces raw-spans` (previews) or `traces payload --fields input,output,error` per span, or MCP `get_trace_context` for the full tree.
5. **Detections via API:** supported (CLI and API), but this needs a write-scoped service-account/OAuth token and a detection group UUID. Cross-span sequencing ("failed *followed by* issue_refund") is not expressible in one regex rule. Condition field names are **unconfirmed**.
6. **Investigate via API/CLI:** **not supported** (UI only). Fixes and investigations are readable only through the MCP `triage_*` tools.
7. **Prompt experiments:** prompt versioning and labels are supported through the SDK, CLI and API. The Playground is UI only. Datasets are "coming soon". There is no programmatic A/B run against a prompt version.
8. **Thread propagation:** not documented for the Python default pipeline (**unconfirmed**). Subprocess joining through an env-var traceparent is our convention on top of documented helpers.
9. **OpenRouter through an OpenAI client with `base_url`:** **unconfirmed**. The docs cover the `openrouter` SDK only.
10. **Dashboard trace URL format:** **unconfirmed**. The MCP examples show `https://neatlogs.com/traces/<id>`, which looks illustrative, so take real links from the dashboard.
11. **Entire:** `--json` has no intent field (parse the text `## Intent` section or the transcript). A direct entire.io checkpoint URL is **unconfirmed**; use the documented commit URL.
