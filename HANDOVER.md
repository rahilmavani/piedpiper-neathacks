# Handover: Culprit (team PiedPiper, neatHack 2026)

Written Sat 10 Oct 2026, 21:30 IST, by the second builder's session, for whoever picks the project up next (human or Claude Code). Everything below is on GitHub `main`. Nothing lives only on the old machine except the API keys.

**Read order:** this file → [`evidence/RUNS.md`](evidence/RUNS.md) (every number) → [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md) (full design) → [`DEMO.md`](DEMO.md) (the video script).

---

## 1. Where things stand (TL;DR)

**The product is built and proven on the real agent. All mandatory submission evidence exists except the Monday items.**

| | Result | Evidence |
|---|---|---|
| Bisect accuracy, benchmark v1 | **6/6 correct**: found the 3 planted bugs the suite can see (b, c, f) and correctly reported no regression for the 3 it can't (a, d, e; confirmed by an independent strength check) | `evidence/bench-v1.md`, `bench/strength.md` |
| Before/after: v1 → v2 | **6/6 again, 1,140 → 588 victim runs (−48%), $2.70 → $1.51 (−44%)**, 49 → 29 min | `evidence/bench-v2.md`, `evidence/RUNS.md` |
| Localise, hero bug `hist/b` | Named the exact hunk pair (retry loop + removed `validate_tool_result`), matching the answer key; 84 runs, $0.20 | `evidence/RUNS.md` |
| Fix + verify, hero bug | `verified_fix`: 96/96 like good, held-out 18/18 vs bad 15/18, parallel execution kept; 132 runs, $0.33 | `evidence/RUNS.md` |
| Recovery from failed actions | Real SKIP of the planted broken install (`hist/b` `22a37db`, `hist/f` `2ad118e`); the Fixer's first attempt rejected and the second verified | report and replay output |
| neatlogs | Every run traced and audited (`verify-trace` PASS × 12); a detection created (3,738 hits); Investigate run and assessed; 7 screenshots | `evidence/NEATLOGS.md`, `evidence/screenshots/` |
| Entire | The "why" for the hero commit comes from checkpoint `01M4JM8P2C4NDS2AAQ0MPVR8YR` ("RefundDesk is too slow. Make it faster…"); Culprit's own commits are checkpointed | `evidence/reports/report-978624283c27.md` |
| cfo.ai | Business plan: pricing comparison, break-even and cash runway exports, built from measured cost per bisect ($0.252) | `business/cfo-plan.md`, `business/cfo-ai-*.xlsx` |
| Tests | **156 pass** (`uv run pytest -q`, ~100 s, free, no network) | |

**Left to do (Monday 12 Oct):** the demo video (≤ 3 min), #neatHack posts, and the X quote-post of the official neatlogs post with team, project, repo and demo link. The submission window is **Mon 12 Oct, 19:00–23:55 IST**. See §9.

---

## 2. The two repos

| Repo | GitHub | Visibility | Role |
|---|---|---|---|
| `piedpiper-neathacks` | github.com/rahilmavani/piedpiper-neathacks | **public** | Culprit, the product |
| `piedpiper-neathacks-refunddesk` | github.com/rahilmavani/piedpiper-neathacks-refunddesk | **private** (decided: stays private) | RefundDesk, the victim agent with the six planted-bug branches |

### Branches

**Culprit** (`main` = `HEAD`, everything merged):

| Branch | State |
|---|---|
| `main` | **The one to use.** All work merged |
| `fix/decision-gates`, `feat/bench`, `feat/v2-efficiency` | Feature branches, fully merged into `main`; kept for history |
| `entire/*` (local only) | Entire CLI's internal snapshot branches. Leave them alone |

**RefundDesk:**

| Branch | State |
|---|---|
| `main` (`e0f2b06`) | Agent + 26-task suite (+6 held-out) + the OpenRouter fallback. Culprit pins its test suite from here |
| `hist/a` … `hist/f` | **Frozen benchmark history. Never commit to these** |
| `good-v1.0` tag (`0479c27`) | The known-good ref |
| `feat/openrouter-fallback` | Merged into `main` |

---

## 3. What changed since the first builder's last commit (`28a805e`, the HOW_IT_WORKS guide)

The second builder took over Saturday afternoon. In order:

1. **Decision gates (code review fixes)**
   - **Regression gate:** a one-sided Fisher exact test (α = 0.05) replaced "the 95% intervals don't overlap", which is far stricter. It would have called `hist/c` (78/78 vs 72/78) noise; Fisher p = 0.014 let it bisect, and it found the right commit.
   - **Infrastructure errors** (429, 5xx, timeouts, no JSON) are retried with backoff and never counted as agent failures. Bad keys or config stop the run with status `infra_error`; `culprit resume` continues it.
   - **Widening** in resamples only adds tasks that actually dropped.
   - **Resume** keeps the run's resolved SHAs, and an empty range stops before the baselines.
2. **Provider fallback:** Anthropic (`claude-sonnet-5-5`) when `ANTHROPIC_API_KEY` is set, otherwise OpenRouter **GLM 5.3** (`z-ai/glm-5.3`). Culprit picks the victim model once per run, records it, and passes it to every victim commit. **All real runs used GLM 5.3**: the old machine only had an OpenRouter key, and runs cost about 4× less.
3. **Entire intent:** the truncated `## Intent` preview is replaced by the full prompt from the transcript.
4. **M3 `culprit bench`** with `bench/ground_truth.json` and `bench/scenarios.yaml`. Accuracy counts only scorable runs.
5. **M5 `culprit localise` and `culprit fix`** (Localiser, Fixer, Verifier), with `--replay` for $0 replays. The Localiser reads failing runs' tool calls back from neatlogs.
6. **v2 efficiency:** staged baselines (screen ×1, then the full k only on tasks that differ) and baseline reuse.
7. **M6 `culprit report`** (markdown + HTML) and **`culprit export-costs`** (per-stage split).
8. **M7:** README, DEMO, and `scripts/demo_replay.sh`, an offline $0 replay of report → localise → fix.
9. **Evidence:** the run register, both benchmarks, the strength check, reports, neatlogs evidence and screenshots, and the cfo.ai plan.
10. **Bugs found and fixed after merging:**
    - `localise`/`fix` were topping up staged baselines with extra paid runs.
    - Read-only ledgers skipped migrations.
    - The report timeline mixed Localiser and Fixer steps into bisect rows; it showed the culprit as GOOD.

All of it is in `git log` with explanatory commit messages. Three parallel Claude sessions built it: two coded in their own worktrees, and the main one integrated, tested, ran paid jobs and pushed.

---

## 4. Setting up on your machine

```bash
# 1. Clone both side by side (Culprit defaults to ../refunddesk; otherwise set CULPRIT_VICTIM_REPO)
git clone https://github.com/rahilmavani/piedpiper-neathacks.git
git clone https://github.com/rahilmavani/piedpiper-neathacks-refunddesk.git
cd piedpiper-neathacks && uv sync --locked

# 2. Keys: copy the template and fill it in (never commit .env)
cp .env.example .env
#   ANTHROPIC_API_KEY=...       → Claude Sonnet 5.5 (if set, it wins)
#   OPENROUTER_API_KEY=...      → GLM 5.3 (what every recorded run used)
#   NEATLOGS_API_KEY=...        → neatlogs project key of "Rahil's project"
#   CULPRIT_VICTIM_REPO=../piedpiper-neathacks-refunddesk
#   leave CULPRIT_MODEL / VICTIM_MODEL empty
cp .env ../piedpiper-neathacks-refunddesk/.env   # only needed to run RefundDesk by hand

# 3. Get the recorded runs (the ledger is gitignored; a snapshot is committed)
uv run python scripts/relocate_ledger.py evidence/ledger-snapshot.sqlite .culprit/ledger.sqlite ../piedpiper-neathacks-refunddesk

# 4. Check
uv run pytest -q                                   # 156 pass, free
DEMO_PAUSE=1 bash scripts/demo_replay.sh           # hero story from the ledger: 0 runs, 0 model calls, $0
```

Optional tools:
- **Entire CLI** (`brew install --cask entireio/tap/entire`): needed for intent on *new* runs, and so your Claude Code sessions get checkpointed. Recorded runs already store their intent.
- **neatlogs CLI** (`npm install --global neatlogs-cli@0.2.0`; it says it wants Node 22 or 24, but 25 worked). Then `neatlogs profile set work --host https://app.neatlogs.com`, `neatlogs profile use work` and `neatlogs auth login`. That's needed for `culprit verify-trace`.
- **neatlogs MCP in Claude Code:** `claude mcp add --scope user --transport http neatlogs https://ingest.neatlogs.com/mcp --header "Authorization: Bearer <NEATLOGS project key>"`, then start a new session.

Gotchas:
- Run `culprit` as **`uv run culprit …`**. It isn't on your PATH.
- `scripts/demo_replay.sh` reads `.culprit/ledger.sqlite` by default; set `CULPRIT_DB=<path>` to use another one.
- Without step 3, `report`, `bench --score-latest`, `verify-trace` and replays have no runs to read.

---

## 5. Key IDs (for the video, posts and submission)

| What | ID |
|---|---|
| Hero planted commit (RefundDesk) | `397c42743be8cd80ae1d1e30c058772c1bd16add`: "perf(agent): run tool calls in parallel and drop per-result validation" |
| Entire checkpoint behind it (the "why") | `01M4JM8P2C4NDS2AAQ0MPVR8YR` |
| Hero run v1 (also has localise + fix) | `ff50e3620fdd`, trace `d80e61a81918c7eb3ffd917a2509efb0` |
| Hero run v2 (has the full Entire intent; **use its report in the video**) | `978624283c27`, trace `a9ae3f8ce2b7283129b1e9074c3deac1`, report `evidence/reports/report-978624283c27.html` |
| Culprit checkpoint for the v1→v2 work (headline Entire evidence) | commit `69e6b6051097c57bb189b8e82b85d40ff5ca9755`, checkpoint `01M4JYTGY8EAX1NK5JMS066Y4K`: https://entire.io/gh/rahilmavani/piedpiper-neathacks/commit/69e6b6051097c57bb189b8e82b85d40ff5ca9755 |
| Another Culprit checkpoint (full-intent fix) | commit `a72210ed45703aa2f30349d2ab4dd1a2712226a2`, checkpoint `01M4JY4MX6XVBA39VNJVQFME6N` |
| neatlogs project | "Rahil's project", `97d7e411-52c1-4c80-81d8-bd780d3ff71e`; workflows `culprit` and `refunddesk-eval` |
| neatlogs detection | "Upstream tool failure (failed payload)", `94b590fe-54d4-40ad-829a-6194daca745c` |
| neatlogs Investigate card | "Investigate Upstream Service Failures in lookup_order Tool", `d3ad23c8-0877-4c12-b619-4083d838c737` |

All 12 run IDs with their traces are in `evidence/RUNS.md`.

**Finding traces in the dashboard:** the search box is a full-text search, not an ID lookup. Use the **Session ID** filter with the run ID (e.g. `978624283c27`). Victim traces have session `<run_id>:<task_id>`.

---

## 6. The story and the honest caveats (for the video and posts)

**The pitch:** "`git bisect` for agent behaviour, with receipts." We planted six regressions in a refund agent through real coding-agent sessions (recorded by Entire). Culprit:
- found every one the test suite can detect, and refused to blame anyone where the suite saw no difference (6/6);
- named the exact two hunks behind the hero bug;
- wrote a fix that passed 96/96, kept the parallelism the developer asked for, and got verified on held-out tasks;
- did all of it for $1.13 on GLM 5.3.

v2 then cut the bisect cost by 44% with identical accuracy.

**Say these plainly. They're true, and judges like it:**
1. **The bugs are planted on purpose.** Each was explicitly requested in a Claude Code session with a realistic reason (speed, cost, consistency).
2. **3 of the 6 planted bugs are invisible to the suite:**
   - `a`: the rename was done consistently;
   - `d`: the >$500 rule survived the prompt cleanup, and a code guard blocks large refunds anyway;
   - `e`: the model never omits a tool argument, so lenient parsing never runs.

   An independent strength check (seeds 3–5, 312 runs) confirmed 78/78 on each. Culprit reporting "no regression" there is correct.
3. **The "make it faster" commit didn't make the agent faster.** Median latency was 7,086 vs 7,138 ms: time is dominated by model calls, and the tools are mocks. The fix "keeps the parallel execution", but there was no real speed-up to keep. `culprit fix` now prints this note itself.
4. **No resample happened on the real agent:** every decision was clear at the first sample. The resample demo is on the fixture (fake victim), so label it as such.
5. **neatlogs Investigate flagged correct behaviour.** Its "high-severity silent degradation" card is from a *passing good-v1.0 run* where every lookup fails by design. That's the angle: observability sees failures; Culprit knows what "correct" is and which commit broke it.
6. **Some numbers are measured, others assumed.** cfo.ai prices and growth are hypotheses; the cost per bisect is measured.

---

## 7. Commands (all from `piedpiper-neathacks/`)

```bash
uv run culprit run --good good-v1.0 --bad origin/hist/b            # real bisect, ~$0.46 on GLM (v2)
uv run culprit run ... --no-reuse --no-staged                       # = v1 behaviour
uv run culprit resume <run_id> [--budget-usd 5]
uv run culprit localise <run_id> [--replay]                          # replay = $0, no network
uv run culprit fix <run_id> [--replay]
uv run culprit report <run_id> --out evidence/reports               # markdown + HTML
uv run culprit verify-trace <run_id>                                 # neatlogs readback audit
uv run culprit bench --tag vN [--score-runs id,...|--score-latest]   # score against bench/ground_truth.json
uv run culprit export-costs --format csv --out business/runs.csv
uv run python scripts/strength_check.py <victim> good-v1.0,origin/hist/a ALL 3-5   # visibility check (paid)
DEMO_PAUSE=1 bash scripts/demo_replay.sh                             # $0 hero replay, offline
uv run culprit comment ff50e3620fdd                                  # PR comment for a finished run, $0
uv run culprit ci --base <ref> --head <ref> [--fix]                  # PR regression gate (paid)
uv run culprit drift --ref good-v1.0                                 # did the model drift? (paid)
uv run culprit audit --ref good-v1.0 --out evidence/audit.md         # eval blind spots (paid)
```

`ci`, `comment`, `drift` and `audit` were added on 11 Oct (README "Beyond bisect"). They're tested on the
fixture only; no real-victim run yet.

**Costs on GLM 5.3:** about $0.0024 per victim run; a v2 bisect costs $0.12–0.46; the full hero investigation (v1 bisect + localise + fix) was $1.13. Spent so far: about $5.59 on GLM (checks $0.85, v1 $2.70, v2 $1.51, localise + fix $0.53; `evidence/RUNS.md`), plus about $2–3 of Sonnet 5.5 runs by the first builder (`HOW_IT_WORKS.md` §13). Per-run caps: `--budget-usd` (default $3); the global cap is $75 across the ledger.

---

## 8. Rules that matter

- **Never put the answer key into RefundDesk.** Don't write the branch→scenario mapping or words like scenario/regression/culprit/seed into its code, commits or sessions. Culprit reads Entire sessions from RefundDesk as "intent", so anything written there leaks into the benchmark. The key lives only in this repo (`PROMPTS.md`, `bench/`).
- **Never commit to `hist/*` or move `good-v1.0`.**
- **RefundDesk `main` pins the suite by commit SHA.** Any new commit there changes the suite SHA, so new runs can't reuse old baselines. Pass `--suite-ref ba86ed0` to match the recorded runs.
- **Ask before paid runs.** Every number in `evidence/` is measured. Don't round in our favour; when you add a run, add its row to `evidence/RUNS.md`.
- **Before committing, check pytest's own exit code.** `pytest | tail` hides failures, and that once let a red test reach `main`.
- **Secrets:** `.env` is gitignored. The Anthropic, OpenRouter and neatlogs keys were pasted in chats during the event; **rotate them all after the hackathon.** The neatlogs key is also stored in `~/.claude.json` (user-scope MCP).

---

## 9. Monday plan (12 Oct)

1. **Record the video (≤ 3:00)** following [`DEMO.md`](DEMO.md). It's written scene by scene, with commands and the real IDs.
   - Terminal parts: `DEMO_PAUSE=2 bash scripts/demo_replay.sh` ($0, deterministic).
   - The "why": open `evidence/reports/report-978624283c27.html` (Intent section), or run `entire checkpoint explain 397c427…` in the RefundDesk clone.
   - neatlogs: the dashboard plus `evidence/screenshots/1-…7-`.
   - cfo.ai: `business/cfo-plan.md` tables, or the two xlsx files.
2. **#neatHack posts** (≥ 3). The strongest real stories:
   - "We planted 6 bugs. Culprit found the 3 the tests can see and refused to blame anyone for the 3 they can't, and an independent check proved it right."
   - "v2: same 6/6 accuracy at 44% lower cost." (`evidence/RUNS.md`)
   - "neatlogs flagged correct behaviour as a regression. Here's why you need a known-good baseline." (`evidence/NEATLOGS.md` §3b)
   - "Our first regression gate would have called a real bug noise." (`hist/c`, Fisher vs interval overlap)
3. **Submission:** in the window Mon 12 Oct **19:00–23:55 IST**, quote-post the official neatlogs post on X with the team (PiedPiper), the project (Culprit), the public repo link and the demo link. The PRD suggests posting right at 19:00, because the first 50 posts get engagement.
4. Update `hackathon.md` (team names are still pending) and tick the checklist in `PRD.md` §21.

**Feature freeze:** don't change product code on Monday unless a demo step is broken. If you do, run `uv run pytest -q` and `scripts/demo_replay.sh` before pushing.

---

## 10. Known limitations (all documented)

- Benchmarks used one victim model (GLM 5.3). Sonnet 5.5 was only measured for the hero bug's visibility.
- Localise and fix have one real case (`hist/b`). `hist/c` and `hist/f` would cost about $0.50 each if wanted.
- Baseline reuse wasn't measured on the real victim. On our ledger it would copy v1's baselines, which isn't a fair test; the fixture numbers are in `evidence/v2-efficiency-fixture.md`.
- neatlogs limits: regex detections can't see tool results inside LLM inputs, cross-span rules can't be created via the API, the MCP `get_trace_context` is disabled, and neatlogs prices Sonnet at $3/$15 (we use $2/$10). See `BLOCKERS.md`.
- The PRD §10 quality gate (interval overlap) is lenient; the "no new failures" gate is what catches weak fixes.
- Full list: `HOW_IT_WORKS.md` §16 and `BLOCKERS.md`.
