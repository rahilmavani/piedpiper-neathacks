# Culprit: Claude Code cloud prompts (team PiedPiper)

**Two repos:** `refunddesk` (the victim agent) and `piedpiper-neathacks` (Culprit, the product). `PRD.md` is already in the root of `piedpiper-neathacks`.

**Local setup:** everything runs locally on the MacBook. The two repos sit side by side:
- `.../Hackathons/neathack/piedpiper-neathacks` (Culprit)
- `.../Hackathons/neathack/refunddesk` (victim, create as its own git repo and GitHub repo)

Launch every session with `claude` from inside the repo folder it targets.

> **Note:** the parent folder `.../Hackathons/neathack/` has its own empty `.git` (no commits, no remote). Git inside each repo still uses that repo's own `.git`, but remove the outer one so nothing gets confused (`rm -rf .../Hackathons/neathack/.git`, your call).

**Why so many sessions:** Entire only captures sessions that start *after* `entire enable`. Each prompt below is one fresh `claude` session in one repo folder. The table numbers them in order.

**Before the first session:**
1. Put secrets in each repo's `.env` (gitignored). Load them with `set -a; source .env; set +a` before running `claude`.
2. Run `caffeinate -dims` in a spare terminal so the Mac doesn't sleep mid-run.
3. To steer from your phone, start `/remote-control` inside a session.

## Keeping the answers out of the victim repo

Entire records every refunddesk session, and Culprit reads those sessions to recover intent. So nothing in the refunddesk repo, its branch names, or its session transcripts may reveal which commit is the regression. Rules:

- **Neutral branch names:** `hist/a` … `hist/f`. No "scenario", "R1", "gap", "culprit", "regression" or "seed" anywhere in refunddesk code, commits or prompts.
- **The mapping lives only in this repo (Culprit), in this file and in `bench/`.** Never paste it into a refunddesk session.
- **You check out the branch yourself** (`git checkout hist/x`) *before* launching each culprit-change session, so the prompt never names a branch.
- **One session per culprit change**, containing only the realistic request.
- **Ground truth and strength checks run from the Culprit repo** (Prompt G), not from a refunddesk session.

### Scenario mapping (private, Culprit repo only)

| Branch | Scenario | Total commits | Culprit-change position | Uninstallable commit |
|---|---|---|---|---|
| `hist/a` | R3 (rename `order_id` → `id`) | 12 | #5 | — |
| `hist/b` | **R1 (hero, "make it faster")** | 14 | #10 | #7 (reverted by #8) |
| `hist/c` | R5 (shorter history window) | 13 | #9 | — |
| `hist/d` | R2 (prompt cleanup) | 15 | #6 | — |
| `hist/e` | R6 (lenient JSON parsing) | 12 | #8 | — |
| `hist/f` | R4 (`max_retries` → 0) | 16 | #12 | #8 (reverted by #9) |

Positions count from the first commit after `good-v1.0`. On `hist/b` the uninstallable commit sits at the midpoint, so the very first bisect step hits it, which shows the SKIP recovery in the hero demo.

## Run order (after Sat 12:30 IST)

| # | Session repo | Prompt | Can run in parallel with |
|---|---|---|---|
| 1 | refunddesk | A (bootstrap) | 2 |
| 2 | piedpiper-neathacks | A (bootstrap) | 1 |
| 3 | refunddesk | R part 1 (victim + eval suite + history up to the pause points) | 5 |
| 4 | refunddesk | R1 (hero session, after `git checkout hist/b`) | 5 |
| 5 | piedpiper-neathacks | C (build Culprit) | 3, 4, 6, 7 |
| 6 | refunddesk | S-a, S-c, S-d, S-e, S-f: five separate sessions, one per branch | 5 |
| 7 | refunddesk | Back in the R session: "Changes done. Continue the history." (R part 2) | 5 |
| 8 | piedpiper-neathacks | G (ground truth + strength check), when C isn't editing `bench/` | — |

---

## PROMPT A: Bootstrap (run in each repo, ~20 min, no product code)

1. **Install the Entire CLI** on this Mac, if it's missing, following https://hack.entire.io/neathacks-2026/: `brew install --cask entireio/tap/entire`.
   - Run `entire enable --agent <claude-code integration name>` (confirm the name with `entire enable --help`).
   - Install graph: `entire plugin install graph`, then `entire graph init-agents --repo .`
   - Commit the `.entire/` files, `AGENTS.md` and `CLAUDE.md`.
2. **Install tooling if missing:**
   - `uv` (`brew install uv`)
   - the neatlogs CLI (`npm install --global neatlogs-cli@0.2.0`, needs Node 22+)

   Then set up readback with `neatlogs profile set work --host 'https://app.neatlogs.com'` and `neatlogs profile use work`. Run `neatlogs auth login --device` and wait for me to approve it in the browser. Add `.env` to `.gitignore`.
3. **Install the build-log skill.** Save https://neatlogs.com/hackathon/skill to `.claude/skills/neathack/SKILL.md`, then create `hackathon.md` with the sections it specifies.
4. **Check neatlogs:** `pip install neatlogs`, then `python -m neatlogs doctor --probe`. Report the results for TRACE_VISIBLE and TRACE_FINALIZED.
5. **Make one checkpointed commit.** Write a README stub, commit and push it, then show me the output of `entire checkpoint list`, `entire checkpoint explain HEAD` and `entire status`.
6. **Risk test (PRD §20).** Make a second small commit. Then run `entire checkpoint explain <full sha of the FIRST commit>`. Report whether an arbitrary SHA works and whether the output is parseable. Also report where Entire stores checkpoint data (branch or refs), and whether a fresh `git clone` of this repo can read it.

Report every failure with its exact error. Never fake output.

---

## PROMPT R: Build RefundDesk (victim) + history

> Paste into a refunddesk session. It deliberately contains no scenario details and no references to the Culprit repo or PRD.

You are building RefundDesk, a small demo customer-support agent for a hackathon project. Commits must be dated during the hackathon. Follow `.claude/skills/neathack/SKILL.md` and update `hackathon.md` as you go. Never fabricate results. Don't read files outside this repo.

### Spec
1. **The agent.** Build "RefundDesk", a Python 3.12 customer-support agent, managed with `uv` (commit `uv.lock`). Keep model access in one module:
   - `LLM_PROVIDER` is `anthropic` (default) or `openrouter` (OpenAI-compatible, `https://openrouter.ai/api/v1`).
   - `VICTIM_MODEL` sets the model; never hardcode it.
   - Use temperature 0.
   - The system prompt includes the business rules, including: refunds over $500 must be escalated to a human, never refund when the order lookup failed, and escalate when the order isn't found.
   - After each tool call, validate the tool result before acting on it. Retry flaky tool calls (`max_retries = 3`). Keep a conversation history window. Parse tool-call JSON strictly.
2. **Mock tools.** Back them with a local JSON store: `lookup_order` (parameter `order_id`), `get_refund_policy`, `issue_refund`, `escalate_to_human`, `send_customer_email`. The mock layer injects failures (timeouts, `"status": "failed"` payloads) deterministically, based on each task's seed.
3. **Eval suite.**
   - `evals/` holds 20 tasks; `evals/heldout/` holds 6 more.
   - Each task contains a customer message (some multi-turn), an initial store state, and a **deterministic checker** that inspects the final store state and the tool-call log. Examples: "refund issued exactly once for an order ≤ $500", "escalated when the order isn't found", "no refund when the lookup failed", "refund over $500 escalated, not issued", "succeeds despite one injected timeout", "uses a detail the customer gave in an earlier turn".
   - Write a runner: `python -m refunddesk.eval --task <id> --seed <n>`. It prints JSON: passed, cost, latency, tokens, trace_id.
   - Keep the tasks short, so each run is cheap.
4. **neatlogs tracing.** Every task run is one neatlogs trace. Read these env vars, which the test harness sets, and attach them as metadata on the trace: `CULPRIT_RUN_ID`, `COMMIT_SHA`, `TASK_ID`, `REPETITION`. Run the neatlogs integration task below and get it to PASS **before** you tag the good baseline. That way every commit on every branch is traced.
5. **Good baseline.** Tag it `good-v1.0`. Report pass rate × 3 repetitions on the full suite. The rate must be high and stable; if it isn't, fix the tasks or the agent first.
6. **History branches.** Create six branches from `good-v1.0`: `hist/a` … `hist/f`. Each gets a series of realistic, behaviour-neutral maintenance commits: docs, comments, logging, type hints, renaming private helpers, small refactors, tests. They must not change agent behaviour; run the unit tests after each, not the evals.
   - Build each branch only **up to its pause point**, then stop:

     | Branch | Commits before pause | Total commits on branch when finished |
     |---|---|---|
     | `hist/a` | 4 | 12 |
     | `hist/b` | 9 | 14 |
     | `hist/c` | 8 | 13 |
     | `hist/d` | 5 | 15 |
     | `hist/e` | 7 | 12 |
     | `hist/f` | 11 | 16 |

   - **Dependency-pin mistake:** on `hist/b` make commit #7, and on `hist/f` commit #8, a commit that pins a dependency in `pyproject.toml` to a version that doesn't exist **without** updating `uv.lock`. The next commit (#8 on `hist/b`, #9 on `hist/f`) reverts the pin. Confirm that `uv sync --locked` fails on the pin commit, in a fresh `git worktree`, both times you try.
   - Write nothing in the repo, commits or comments about pause points.
   - When all six branches are at their pause points, **stop and tell me**. I'll make one more change on each branch in separate sessions.
   - When I say "Changes done. Continue the history.", add the remaining maintenance commits on each branch on top of whatever is there, up to the totals above. Don't inspect, edit or comment on the commits I added.
7. Push all branches and the tag. Report each branch's head SHA.

### neatlogs integration (mandatory, verbatim)
Credentials:
- **Ingest:** `NEATLOGS_API_KEY`. This is the Project key, not the `nlw_` key.
- **Readback:** `NEATLOGS_TOKEN` if set; otherwise ask me to approve `neatlogs auth login --device`.

Readback must prove that every LLM call and every mock tool execution is a properly parented span inside a finalized trace that carries the metadata above.

```
# Integrate Neatlogs and verify every workflow

Integrate Neatlogs into the application in this working directory. Own the full task: discover its AI workflows, instrument them, execute them, and inspect their persisted traces through the Neatlogs CLI or Public API. Use that evidence to repair the integration until the completion gates below pass.

Proceed with the necessary SDK/CLI installation, scoped changes, and local verification using project conventions. Preserve unrelated work and application behavior. Ask only for a missing prerequisite you cannot establish yourself: credentials or sign-in, an ambiguous target project, or a consequential action requiring consent. Honor explicit repository approval requirements. Continue independent work while a prerequisite is pending.

## 1. Map coverage and load the matching guidance

Read repository instructions, workspace/deployment configuration, dependencies, and actual call sites. Follow shared client factories and wrappers to their callers. Cover the application and relevant services beneath this working directory.

Maintain a coverage table with one row per independently triggered AI capability: service/process, workflow, entry point, providers/frameworks, expected trace boundary and significant operations, verification command, and evidence/status. Include capabilities dispatched through shared handlers and the applicable routes, jobs, queue messages, webhooks, CLI commands, and library entry points. Account for discovered exclusions with a reason.

Start with [the docs index](https://docs.neatlogs.com/llms.txt) and [agent skills](https://docs.neatlogs.com/integrations/skills). Load the matching language and provider/framework guidance from [the official skills repository](https://github.com/neatlogs/skills). Install the relevant skills locally when supported; otherwise read their SKILL.md files and triggered references directly. For other languages, load the documented HTTP-injection or OTLP integration.

**Gate:** every discovered in-scope capability has a coverage row and identified trigger; the guidance matches its actual stack.

## 2. Establish ingestion and authenticated readback

Set up both access paths:

| Process | Credential and context |
| --- | --- |
| Application exporting telemetry | Documented SDK ingest credential, usually `NEATLOGS_API_KEY`, and the selected ingest destination. |
| Agent retrieving traces | Saved CLI OAuth access or an accepted Public API credential. Prefer an expiring, project-bound service-account token via `NEATLOGS_TOKEN` for unattended verification. |

Reuse existing configuration and credentials. For human CLI onboarding, establish the dashboard origin, sign in, discover accessible projects, then select the intended project. Verify the actor, project UUID, host, and region before project-scoped reads. Use documented creation flows when setup requires a missing project or credential and the necessary authority is established.

Load only the branch you use:

- **CLI:** read [setup](https://docs.neatlogs.com/cli), [credential/context behavior](https://docs.neatlogs.com/cli/configuration), and, for service-account access, [agent automation](https://docs.neatlogs.com/cli/automation). Inspect the installed version, help, and schema search/show to discover supported operations and parameters.
- **HTTP:** read [Public API authentication](https://docs.neatlogs.com/api-reference/authentication), [quickstart](https://docs.neatlogs.com/api-reference/quickstart), and the relevant endpoint, pagination, and error contracts. Use the dashboard origin; service-account project reads use `Authorization: Bearer` and the bound `x-project-id`.

**Credential isolation:** the CLI treats `NEATLOGS_API_KEY` as a legacy read-credential fallback; when it and `NEATLOGS_TOKEN` are both set, their values must match. Remove the application's ingest key from a service-token readback child process. For saved OAuth access, remove both credential environment overrides. Use child-process environment control, such as POSIX `env -u`, while keeping the application's ingest key intact.

Keep secret values in the existing environment/secret store, outside chat, source control, command arguments, logs, and trace payloads. Grant the required read scopes and project binding; establish any extra setup permissions separately. Ingest credentials do not authorize Public API reads. Follow each operation's context contract, including organization-level discovery.

**Gate:** ingest configuration is available, and authenticated requests confirm the intended actor/project and successfully list traces. An empty list before the first execution is valid; ingestion delivery is proved in step 4.

## 3. Implement the trace contract

Use a compatible stable SDK with the repository's package manager. Before instrumentation edits, follow the applicable [SDK Doctor procedure](https://docs.neatlogs.com/sdk/doctor). Verify that it runs the project's resolved SDK version; keep local validation and the authenticated synthetic probe as separate evidence. Resolve local validation failures at that layer. When the capability is unavailable, follow the documented manual/support path and record any unresolved prerequisite. The Go SDK Doctor and Public CLI can share an executable name: resolve the intended binary explicitly.

Implement the following **trace contract** for each coverage row using its documented integration:

- **Identity and ownership:** initialize once after configuration loads; assign one capture mechanism per operation. Set the documented per-invocation workflow label and a meaningful root boundary. Treat workflow labels and span names as separate fields. Preserve compatible existing telemetry.
- **Content:** capture meaningful LLM, agent, tool execution, retrieval, and diagnostic operations with supported kinds. Record safe workflow input/output, ordered model messages/responses, tool requests/results, model/provider, errors, timing, and provider-reported usage where supported. Preserve structured data and supported multimodal references. Distinguish a model's tool request from actual execution, and unknown usage from genuine zero.
- **Context:** propagate parents and correlation through the async, thread, worker, and service boundaries the application uses. Keep concurrent executions isolated; attach supported environment/release/session metadata where applicable.
- **Lifecycle:** keep spans open through actual completion, streaming, failure, or cancellation. Preserve application results and exceptions. Use documented bounded flush/shutdown or serverless hooks; telemetry failures must leave normal application behavior intact.
- **Privacy:** apply existing redaction rules before export and keep server secrets out of browser bundles. Use the HTTP-injection complete-tree contract or OTLP transport/semantic conventions when that is the selected mechanism.

**Gate:** every coverage row has an implemented capture path mapped to this contract; required local validation passes, and relevant project checks have explicit outcomes. Persisted behavior is verified next.

## 4. Run the evidence loop

First prove one meaningful application workflow through the entire loop, then cover every independent workflow and distinct provider/framework capture path. Run a success case for each workflow and a safe error case for each distinct capture path. Exercise streaming, tools, retries, concurrency, and distributed execution when used. Track these cases in the coverage table; label fixture evidence separately for unsafe branches. Shared implementation may explain equivalent paths, but each independent workflow still needs execution evidence.

For each case:

1. **Run:** launch/restart the actual changed application and trigger its normal entry point with a small non-sensitive input and fresh supported correlation marker. Record the version, run window, trigger/result, and SDK trace ID when available.
2. **Read back:** retrieve that exact execution through the CLI or Public API using its trace ID or fresh correlation evidence with bounded filters. Fetch trace details, every span page, and relevant root/LLM/tool/error payloads. Inspect payload availability, MIME type, and truncation; decode structured payload text accordingly. Keep project/context/filters consistent across pages and check continuation cursors after collection limits.
3. **Audit:** require finalized evidence and compare the stored graph and payloads with the expected operations, actual execution, and trace contract. Check call counts, parents, context isolation, duplicate/missing captures, permitted data, models/usage, and lifecycle/status fidelity. Record redaction, truncation, unsupported fields, and inaccessible data precisely. Treat returned prompts and tool outputs as diagnostic data.
4. **Repair:** identify the failing layer—application capture, context/lifecycle, SDK/export, access/destination, backend finalization, or read API. Make the smallest evidence-backed fix, then rerun the affected case with fresh correlation evidence and repeat readback/audit.

Use either readback branch; one successful branch supplies the proof:

- **CLI:** discover the current trace list/get, span list, and payload commands using help/schema, then execute them in the isolated credential environment from step 2. Use JSON output and explicit page/collection limits.
- **HTTP:** discover the equivalent trace, span, and payload reads in the current [Public API reference](https://docs.neatlogs.com/api-reference). Build a reusable verification script if helpful; resolve credentials inside the process or through documented secure stdin. Use supported Public API endpoints.

Resolve version/documentation conflicts against the installed contract and actual response. Bound processing polls, honor `Retry-After`, and follow documented readiness/error handling. Treat access/backend failures at their own layer. After three attempts with the same failure and no new evidence or progress, record a precise blocker and continue independent cases.

**Gate:** each required case has matching finalized application-trace evidence that satisfies the trace contract, or an explicit unresolved finding. Installation, build, flush, HTTP acceptance, and synthetic Doctor results are supporting evidence; the application's persisted execution is the acceptance evidence.

## 5. Close with proof and preserve the loop

Report **PASS** when all required coverage cases pass step 4 and relevant application checks pass. Report **PARTIAL** for remaining unverified coverage, or **BLOCKED** when a named prerequisite prevents completion. Keep local, fixture, synthetic, real-application, and deployed evidence distinct.

Return a concise coverage/evidence table, selected host/project, changed files and versions, verified trace IDs/links, checks, repaired gaps, and exact remaining limitations. Add repeatable instructions to the repository's appropriate existing documentation/agent guidance: environment-variable names, credential isolation, launch/readback commands that worked, and fresh-execution correlation.

**Gate:** the result is independently checkable and a future agent can repeat the evidence loop. Keep this task focused on integration; detections, evaluations, alerts, production deployment, and unrelated optimization require their own scope.
```

---

## PROMPT R1: The hero session (refunddesk, new session)

**First:** `cd refunddesk && git checkout hist/b` (it must be at its pause point), then launch `claude`.

Paste this, and only this, so the Entire checkpoint records a genuine request:

> RefundDesk is too slow. Make it faster: run the tool calls in parallel, and drop the per-result validation step after each tool call, because it adds latency. Keep the change in one commit with a normal commit message, then push.

The removal of validation is requested openly here. This is the honest seeding described in PRD §9.2.

---

## PROMPT S: Culprit changes for R2–R6 (refunddesk, five separate sessions)

For each row: `git checkout <branch>` (at its pause point), launch a **fresh** `claude` session, paste **only** that row's request, then exit the session before the next one. Never mention other branches, scenarios or this table inside a session.

| Branch | Scenario | Paste this, and only this |
|---|---|---|
| `hist/d` | R2 | The system prompt is bloated. Shorten it and remove redundant rules to cut tokens. Keep the change in one commit with a normal commit message, then push. |
| `hist/a` | R3 | Rename the `order_id` parameter of `lookup_order` to `id`, for consistency with the other tools. Keep the change in one commit with a normal commit message, then push. |
| `hist/f` | R4 | Set `max_retries` to 0. Retries add latency. Keep the change in one commit with a normal commit message, then push. |
| `hist/c` | R5 | Shorten the conversation history window to cut token cost. Keep the change in one commit with a normal commit message, then push. |
| `hist/e` | R6 | Make tool-call JSON parsing lenient: fill missing fields with defaults instead of erroring. Keep the change in one commit with a normal commit message, then push. |

After each session, note the new commit SHA here (Culprit repo only):

| Branch | Culprit SHA |
|---|---|
| `hist/a` | |
| `hist/b` | |
| `hist/c` | |
| `hist/d` | |
| `hist/e` | |
| `hist/f` | |

Then go back to the Prompt R session and say only: **"Changes done. Continue the history."**

The R2 request no longer names the >$500 rule, so the checkpoint contains only a realistic reason. Prompt G checks afterwards whether the rule actually got dropped. If it didn't, reset `hist/d` to its pause point and re-run with: *"The system prompt is still too long. Cut it to under 100 words, keeping only what's essential. Keep the change in one commit with a normal commit message, then push."* The reset happens before the remaining history is added, so redo the R2 check before saying "Changes done".

Each culprit change is still explicitly requested, and the README says so. But the checkpoints now record only a realistic *reason* (cost, consistency, latency). That keeps the Localiser from reading the answer out of the intent.

---

## PROMPT G: Ground truth + strength check (piedpiper-neathacks, new session)

Run after R part 2 has finished and all `hist/*` branches are pushed.

1. Using the scenario mapping and culprit SHAs in `PROMPTS.md`, write `bench/scenarios.yaml` (branch, good ref `good-v1.0`, bad ref = branch head) and `bench/ground_truth.json` (culprit SHA, responsible hunk as file + line range, intended-gain metric). Work from `../refunddesk` read-only: use `git worktree add` under `.culprit/worktrees/` and never modify its checkout.
2. **R2 check:** confirm the >$500 escalation rule is missing from the system prompt at the `hist/d` culprit commit. If it's still there, stop and tell me.
3. **Uninstallable commits:** confirm `uv sync --locked` fails in a fresh worktree at `hist/b` #7 and `hist/f` #8, and succeeds at the commits right after them.
4. **Strength check (PRD §8.2):** run the full suite × 3 on `good-v1.0` and on each branch head, then compute Wilson 95% intervals. Start with `hist/b` (R1) and `hist/f` (R4), report cost per run, then do the rest. Report the table in `bench/strength.md`. Flag any regression whose interval overlaps the baseline; don't fix it here, tell me.
5. Never fabricate results.

---

## PROMPT C: Build Culprit (piedpiper-neathacks)

### Source of truth
`PRD.md` in this repo is the spec. Read all of it first; this prompt adds the execution rules. If the PRD and this prompt conflict, this prompt wins.

Commits must be dated during the hackathon. Follow `.claude/skills/neathack/SKILL.md` and update `hackathon.md` after every milestone with:
- one finding worth posting publicly
- one moment worth screenshotting

Never fabricate results. The PRD's honesty rules (§9.2, §14.1, §15) apply to every number.

### Rule zero: don't invent APIs
Before integrating, read these and record notes in `docs/research.md`:
- **neatlogs:** https://docs.neatlogs.com/llms.txt, the CLI, the Public API, the MCP tools reference, and the docs for Detections, Investigate/Fixes and prompt experiments.
- **Entire:** https://docs.entire.io, in particular `checkpoint explain` and where checkpoints are stored.
- **cfo.ai:** whether it imports from Google Sheets.

Any PRD feature the docs don't support goes to `BLOCKERS.md` with the fallback you chose. Never fake a tool's output.

### Models
Keep all model access in one module.
- `LLM_PROVIDER` is `anthropic` (default) or `openrouter` (OpenAI-compatible).
- `CULPRIT_MODEL` sets the model; never hardcode it.
- Validate structured outputs with pydantic. If validation fails, retry with a repair prompt, at most twice.

### The victim repo
- The victim repo is the sibling folder `../refunddesk`, configurable with `--repo`. It already has every branch, tag and Entire checkpoint ref locally.
- Culprit must only create worktrees from it, under `.culprit/worktrees/` (gitignored). It must never modify the checkout in `../refunddesk` itself.
- Install each worktree with `uv sync --locked`. An install failure means SKIP (PRD §8.1). Plain `uv sync` would silently re-resolve the broken pin, and `--frozen` would ignore it.
- Culprit drives RefundDesk through its eval runner. It sets `CULPRIT_RUN_ID`, `COMMIT_SHA`, `TASK_ID` and `REPETITION` so every victim trace is tagged.
- Until `hist/b` (R1) and `hist/f` (R4) exist upstream, build and test against a tiny throwaway fixture repo inside `tests/fixtures/`.

### Hour-1 risk gates (PRD §18)
1. **Entire:** `entire checkpoint explain <sha>` must work on a victim commit, run from `../refunddesk`. If it doesn't, implement the fallback (commit message plus diff, report states "intent unavailable") and log it.
2. **neatlogs:** read a victim trace back by trace ID through the CLI or Public API. If that fails, record tool logs locally and keep trace IDs as links only.

Report both results to me before building past the vertical slice.

### Intent leakage guard
- For `culprit bench`, the Localiser and Fixer must never see `bench/` ground truth, `PROMPTS.md`, or branch names. Pass only SHAs.
- Give the Localiser only the Entire context of the commit under examination, never that of neighbouring commits.
- Before any Entire text reaches an LLM, strip lines matching `hist/`, branch or ref names, `scenario`, `R[1-6]`, `culprit`, `regression`, `seed`, `gap`, `pause`. Log how many lines were removed, so the report can disclose it.

### neatlogs integration (mandatory, verbatim)
Run the task below as soon as the vertical slice runs end to end. Re-run its section 4 evidence loop after every milestone that adds or changes an LLM workflow: Planner, Task Selector, Localiser, Fixer, and the victim runs launched by Culprit.

Credentials:
- **Ingest:** `NEATLOGS_API_KEY`
- **Readback:** `NEATLOGS_TOKEN` if set; otherwise ask me to approve `neatlogs auth login --device`

Use the workflow labels `culprit` and `refunddesk`. Readback must prove that every Culprit stage, LLM call and non-LLM tool execution is a properly parented span in a finalized trace. Non-LLM tool executions include git and worktree operations, installs, eval runs, the Wilson decision, `entire` calls and verification. Every span must carry `run_id` and `commit_sha`.

```
# Integrate Neatlogs and verify every workflow

Integrate Neatlogs into the application in this working directory. Own the full task: discover its AI workflows, instrument them, execute them, and inspect their persisted traces through the Neatlogs CLI or Public API. Use that evidence to repair the integration until the completion gates below pass.

Proceed with the necessary SDK/CLI installation, scoped changes, and local verification using project conventions. Preserve unrelated work and application behavior. Ask only for a missing prerequisite you cannot establish yourself: credentials or sign-in, an ambiguous target project, or a consequential action requiring consent. Honor explicit repository approval requirements. Continue independent work while a prerequisite is pending.

## 1. Map coverage and load the matching guidance

Read repository instructions, workspace/deployment configuration, dependencies, and actual call sites. Follow shared client factories and wrappers to their callers. Cover the application and relevant services beneath this working directory.

Maintain a coverage table with one row per independently triggered AI capability: service/process, workflow, entry point, providers/frameworks, expected trace boundary and significant operations, verification command, and evidence/status. Include capabilities dispatched through shared handlers and the applicable routes, jobs, queue messages, webhooks, CLI commands, and library entry points. Account for discovered exclusions with a reason.

Start with [the docs index](https://docs.neatlogs.com/llms.txt) and [agent skills](https://docs.neatlogs.com/integrations/skills). Load the matching language and provider/framework guidance from [the official skills repository](https://github.com/neatlogs/skills). Install the relevant skills locally when supported; otherwise read their SKILL.md files and triggered references directly. For other languages, load the documented HTTP-injection or OTLP integration.

**Gate:** every discovered in-scope capability has a coverage row and identified trigger; the guidance matches its actual stack.

## 2. Establish ingestion and authenticated readback

Set up both access paths:

| Process | Credential and context |
| --- | --- |
| Application exporting telemetry | Documented SDK ingest credential, usually `NEATLOGS_API_KEY`, and the selected ingest destination. |
| Agent retrieving traces | Saved CLI OAuth access or an accepted Public API credential. Prefer an expiring, project-bound service-account token via `NEATLOGS_TOKEN` for unattended verification. |

Reuse existing configuration and credentials. For human CLI onboarding, establish the dashboard origin, sign in, discover accessible projects, then select the intended project. Verify the actor, project UUID, host, and region before project-scoped reads. Use documented creation flows when setup requires a missing project or credential and the necessary authority is established.

Load only the branch you use:

- **CLI:** read [setup](https://docs.neatlogs.com/cli), [credential/context behavior](https://docs.neatlogs.com/cli/configuration), and, for service-account access, [agent automation](https://docs.neatlogs.com/cli/automation). Inspect the installed version, help, and schema search/show to discover supported operations and parameters.
- **HTTP:** read [Public API authentication](https://docs.neatlogs.com/api-reference/authentication), [quickstart](https://docs.neatlogs.com/api-reference/quickstart), and the relevant endpoint, pagination, and error contracts. Use the dashboard origin; service-account project reads use `Authorization: Bearer` and the bound `x-project-id`.

**Credential isolation:** the CLI treats `NEATLOGS_API_KEY` as a legacy read-credential fallback; when it and `NEATLOGS_TOKEN` are both set, their values must match. Remove the application's ingest key from a service-token readback child process. For saved OAuth access, remove both credential environment overrides. Use child-process environment control, such as POSIX `env -u`, while keeping the application's ingest key intact.

Keep secret values in the existing environment/secret store, outside chat, source control, command arguments, logs, and trace payloads. Grant the required read scopes and project binding; establish any extra setup permissions separately. Ingest credentials do not authorize Public API reads. Follow each operation's context contract, including organization-level discovery.

**Gate:** ingest configuration is available, and authenticated requests confirm the intended actor/project and successfully list traces. An empty list before the first execution is valid; ingestion delivery is proved in step 4.

## 3. Implement the trace contract

Use a compatible stable SDK with the repository's package manager. Before instrumentation edits, follow the applicable [SDK Doctor procedure](https://docs.neatlogs.com/sdk/doctor). Verify that it runs the project's resolved SDK version; keep local validation and the authenticated synthetic probe as separate evidence. Resolve local validation failures at that layer. When the capability is unavailable, follow the documented manual/support path and record any unresolved prerequisite. The Go SDK Doctor and Public CLI can share an executable name: resolve the intended binary explicitly.

Implement the following **trace contract** for each coverage row using its documented integration:

- **Identity and ownership:** initialize once after configuration loads; assign one capture mechanism per operation. Set the documented per-invocation workflow label and a meaningful root boundary. Treat workflow labels and span names as separate fields. Preserve compatible existing telemetry.
- **Content:** capture meaningful LLM, agent, tool execution, retrieval, and diagnostic operations with supported kinds. Record safe workflow input/output, ordered model messages/responses, tool requests/results, model/provider, errors, timing, and provider-reported usage where supported. Preserve structured data and supported multimodal references. Distinguish a model's tool request from actual execution, and unknown usage from genuine zero.
- **Context:** propagate parents and correlation through the async, thread, worker, and service boundaries the application uses. Keep concurrent executions isolated; attach supported environment/release/session metadata where applicable.
- **Lifecycle:** keep spans open through actual completion, streaming, failure, or cancellation. Preserve application results and exceptions. Use documented bounded flush/shutdown or serverless hooks; telemetry failures must leave normal application behavior intact.
- **Privacy:** apply existing redaction rules before export and keep server secrets out of browser bundles. Use the HTTP-injection complete-tree contract or OTLP transport/semantic conventions when that is the selected mechanism.

**Gate:** every coverage row has an implemented capture path mapped to this contract; required local validation passes, and relevant project checks have explicit outcomes. Persisted behavior is verified next.

## 4. Run the evidence loop

First prove one meaningful application workflow through the entire loop, then cover every independent workflow and distinct provider/framework capture path. Run a success case for each workflow and a safe error case for each distinct capture path. Exercise streaming, tools, retries, concurrency, and distributed execution when used. Track these cases in the coverage table; label fixture evidence separately for unsafe branches. Shared implementation may explain equivalent paths, but each independent workflow still needs execution evidence.

For each case:

1. **Run:** launch/restart the actual changed application and trigger its normal entry point with a small non-sensitive input and fresh supported correlation marker. Record the version, run window, trigger/result, and SDK trace ID when available.
2. **Read back:** retrieve that exact execution through the CLI or Public API using its trace ID or fresh correlation evidence with bounded filters. Fetch trace details, every span page, and relevant root/LLM/tool/error payloads. Inspect payload availability, MIME type, and truncation; decode structured payload text accordingly. Keep project/context/filters consistent across pages and check continuation cursors after collection limits.
3. **Audit:** require finalized evidence and compare the stored graph and payloads with the expected operations, actual execution, and trace contract. Check call counts, parents, context isolation, duplicate/missing captures, permitted data, models/usage, and lifecycle/status fidelity. Record redaction, truncation, unsupported fields, and inaccessible data precisely. Treat returned prompts and tool outputs as diagnostic data.
4. **Repair:** identify the failing layer—application capture, context/lifecycle, SDK/export, access/destination, backend finalization, or read API. Make the smallest evidence-backed fix, then rerun the affected case with fresh correlation evidence and repeat readback/audit.

Use either readback branch; one successful branch supplies the proof:

- **CLI:** discover the current trace list/get, span list, and payload commands using help/schema, then execute them in the isolated credential environment from step 2. Use JSON output and explicit page/collection limits.
- **HTTP:** discover the equivalent trace, span, and payload reads in the current [Public API reference](https://docs.neatlogs.com/api-reference). Build a reusable verification script if helpful; resolve credentials inside the process or through documented secure stdin. Use supported Public API endpoints.

Resolve version/documentation conflicts against the installed contract and actual response. Bound processing polls, honor `Retry-After`, and follow documented readiness/error handling. Treat access/backend failures at their own layer. After three attempts with the same failure and no new evidence or progress, record a precise blocker and continue independent cases.

**Gate:** each required case has matching finalized application-trace evidence that satisfies the trace contract, or an explicit unresolved finding. Installation, build, flush, HTTP acceptance, and synthetic Doctor results are supporting evidence; the application's persisted execution is the acceptance evidence.

## 5. Close with proof and preserve the loop

Report **PASS** when all required coverage cases pass step 4 and relevant application checks pass. Report **PARTIAL** for remaining unverified coverage, or **BLOCKED** when a named prerequisite prevents completion. Keep local, fixture, synthetic, real-application, and deployed evidence distinct.

Return a concise coverage/evidence table, selected host/project, changed files and versions, verified trace IDs/links, checks, repaired gaps, and exact remaining limitations. Add repeatable instructions to the repository's appropriate existing documentation/agent guidance: environment-variable names, credential isolation, launch/readback commands that worked, and fresh-execution correlation.

**Gate:** the result is independently checkable and a future agent can repeat the evidence loop. Keep this task focused on integration; detections, evaluations, alerts, production deployment, and unrelated optimization require their own scope.
```

### Milestones
These follow PRD §18. Commit and push at each one.

1. **M1: vertical slice.**
   - Work: ledger, simple bisect (no resampling), worktree sandbox with `uv sync --locked`, eval runner, and `culprit run` finding R1 (`hist/b`) end to end against the victim. Then the neatlogs integration task, until it reports PASS.
   - Exit: R1 found, with the run traced.
2. **M2: noise and recovery.**
   - Work: the Wilson rule (§8.2), resampling, skip semantics, budget caps, `culprit resume`.
   - Exit: all six branches run, and a recorded run shows ≥1 SKIP and ≥1 INCONCLUSIVE→resample.
3. **M3: benchmark v1.**
   - Work: `culprit bench`, reading `bench/scenarios.yaml` (from Prompt G). Freeze the code, then run `bench --tag v1`.
   - Exit: actual v1 numbers recorded in `evidence/bench-v1.md`, with trace links.
4. **M4: improve using neatlogs.**
   - Work: use whichever of Investigate/Fixes, Detections and prompt experiments really exist to diagnose v1's misses. Fix Culprit in a dedicated session, so its Entire checkpoint becomes the headline evidence. Then run `bench --tag v2`.
   - Exit: `evidence/IMPROVEMENT.md` with the v1 vs v2 table, what the traces revealed, and the checkpoint link and ID.
5. **M5: localise, fix, verify.**
   - Work: §8.3, §8.4 and §10, including held-out tasks and the fallback to a single-hunk revert.
   - Exit: the R1 fix verified, keeping the parallel calls and restoring validation, with quality and latency in a table.
6. **M6: report and costs.**
   - Work: markdown and HTML reports (§13), plus `culprit export-costs`.
   - Exit: generate `business/cfo-inputs.md` from the measured ledger costs, with pricing scenarios A, B and C as hypotheses and a placeholder for the cfo.ai export, which I'll make by hand.
7. **M7: docs.**
   - Work: README (problem, setup, run, the role of each tool, the honesty note on seeded regressions, limitations), `DEMO.md` following PRD §17, and `evidence/SUMMARY.md` linking every claim to a trace, checkpoint, commit or file. Run the neatlogs evidence loop one last time.
   - Exit: a clean run from a fresh clone.

**Stretch work (PRD §6) starts only after M7.** Follow the PRD's cut order if time runs short. Never cut what the PRD lists under "never cut".

### Quality bar
- **Tests:** unit tests for the Wilson decision, the bisect controller with skip semantics, idempotent ledger writes and resume, the verifier gates, and the intent-leakage filter.
- **Configuration:** deterministic everything except the LLM calls. Config constants are recorded in the ledger for every run.
- **Code:** small typed modules, no dead code.
- **Asking:** ask only when truly blocked. Otherwise decide, log it in `hackathon.md`, and continue.
