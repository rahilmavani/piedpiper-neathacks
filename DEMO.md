# Demo script (≤ 3:00)

This follows PRD §17. Every number on screen must come from `evidence/` (`RUNS.md`, `bench-v1.md`),
`bench/strength.md`, or a command run on camera. **TODO** marks numbers that don't exist yet; the main
session is producing them. Don't record those scenes until the TODOs are filled.

Run IDs below are the real benchmark v1 runs from [`evidence/RUNS.md`](evidence/RUNS.md). All of
them are in the main checkout's ledger (`.culprit/ledger.sqlite`), so every command here is
**free**: it reads the ledger, git or neatlogs, and makes no victim runs. The only exception is the
fixture run in scene 2, which costs $0.

## Before recording

```bash
cd piedpiper-neathacks                       # main checkout (has the ledger)
set -a; source .env; set +a
VICTIM=../piedpiper-neathacks-refunddesk
uv run culprit report ff50e3620fdd           # → .culprit/reports/report-ff50e3620fdd.{md,html}
uv run culprit verify-trace ff50e3620fdd     # expect PASS, 272 spans (evidence/RUNS.md)
uv run python tests/fixtures/make_victim.py /tmp/victim --commits 14 --breaks-at 10 --unbuildable-at 7 \
    --noisy-from 9 --noisy-pass 0.6          # fake victim for the resample beat (fails if /tmp/victim exists)
```

Open these in tabs: the HTML report; the neatlogs trace `d80e61a81918c7eb3ffd917a2509efb0`
(session `ff50e3620fdd`); one victim trace from the report's "Trace IDs" list; the Entire checkpoint
page for the hero commit; and cfo.ai.

## Scenes

### 0:00–0:20 · Problem

On screen: RefundDesk's suite at `good-v1.0` vs the head of `hist/b`.

```bash
git -C $VICTIM rev-list --count good-v1.0..origin/hist/b    # number of commits in the range
```

> "Our support agent passed 78 of 78 eval runs at `good-v1.0`. On this branch it passes 57 of 78.
> Somewhere in these commits, something broke, and the evals are noisy."

Numbers: 78/78 → 57/78 (100% → 73%), run `ff50e3620fdd`, `evidence/RUNS.md`.

### 0:20–1:10 · `culprit run`: baselines, gate, bisect, skip, resample

1. Show the real run's report, `report-ff50e3620fdd.html` (rendered from the ledger):
   - **Baselines:** good 78/78, bad 57/78; Fisher gate p ≈ 0, so bisect.
   - **Discriminating tasks:** ranked by how much each task's pass rate dropped from good to bad in
     the baselines. Say it that way: selection from neatlogs traces is **not built**.
   - **Timeline:** `22a37db` install failed → **SKIP**, its neighbour tested, then four decisions down
     to `397c427` BAD. Point at the Wilson bars against the threshold.
2. **Resample beat, live on the fake victim** (about 3 s, $0). No real-victim step needed resampling
   (`evidence/RUNS.md`), so this beat is shown on the fixture, and the narration says so.

   ```bash
   uv run culprit run --repo /tmp/victim --good good-v1.0 --bad main
   ```

   Lines to highlight:
   - `install failed → SKIP`
   - `10/15 CI [0.42, 0.85] vs t=0.50 → INCONCLUSIVE`
   - `resample 1`
   - `resample 2`
   - `25/45 … → GOOD (low_confidence)`
   - `Culprit: … 'speed up tool handling'`

> "Culprit only commits to a verdict when the interval clears the threshold. When it can't, it
> samples more, and if it still has to guess, it says so."

### 1:10–1:40 · Culprit found it; Entire says why; the responsible hunk

```bash
cd $VICTIM && entire checkpoint explain 397c42743be8cd80ae1d1e30c058772c1bd16add; cd -
```

- Show the Intent: the request to make RefundDesk faster by running tool calls in parallel and
  dropping per-result validation, and the session's pushback before proceeding.
- Honesty line: "We planted this bug on purpose, through a real coding-agent session, so we know the
  right answer."
- **Responsible hunk:** TODO from `uv run culprit localise ff50e3620fdd` (main session). Show the
  `localise:` log lines and the named hunk(s). Expected story, to be confirmed by the run: the
  validation removal and the retry loop only restore behaviour together.

### 1:40–2:05 · Fix that keeps the speed-up

```bash
uv run culprit fix ff50e3620fdd
```

- TODO (main session): the verification table, with quality on full + held-out suites vs good, the
  intended-gain metric (latency) vs bad, no new always-failing tasks, and the VERIFIED line.
- TODO: the fix diff (parallel tool calls kept, validation restored).

### 2:05–2:30 · neatlogs: v1 → change → v2

1. The Culprit trace `d80e61a81918c7eb3ffd917a2509efb0`: the span tree (git, install, victim runs,
   `decision_rule`, `regression_gate`). Then click into one `victim_eval_run` and its RefundDesk trace.
2. `uv run culprit verify-trace ff50e3620fdd` → PASS (272 spans).
3. **v1 numbers** (`evidence/bench-v1.md`): 6/6 correct (3 found, 3 correct `no_regression`),
   1,140 victim runs, $2.70, 190 runs per scenario.
4. **The change:** baselines were 156 of `hist/b`'s 240 runs, so v2 stages them (×1 screen, full k only
   where the ends differ) and reuses matching earlier results.
5. **v2 numbers:** TODO from `evidence/bench-v2.md` (accuracy x/6, victim runs, cost, wall time). If the
   real v2 bench isn't ready, show the fixture comparison instead and say "fixture":
   510 → 430 → 335 → 270 victim runs (`evidence/v2-efficiency-fixture.md`).
6. TODO: Investigate / Detections screenshot, if done by hand in the dashboard.

### 2:30–2:50 · cfo.ai

- Measured input: one bisect on `hist/b` = 240 victim runs, $0.60 on GLM 5.3; v1 average $0.45 per
  scenario (`evidence/bench-v1.md`). `uv run culprit export-costs --format csv` is the per-run input.
- Pricing scenarios A/B/C from `business/cfo-inputs.md`, called **hypotheses** on screen.
- TODO: cfo.ai margin and runway figures from the exported plan in `business/`.

### 2:50–3:00 · Close

- Repo: `https://github.com/rahilmavani/piedpiper-neathacks`
- Entire checkpoint link for the v1 → v2 change:
  `https://entire.io/gh/rahilmavani/piedpiper-neathacks/commit/<full sha>`. TODO: pick the commit and
  its checkpoint ID.
- `#neatHack`

## Numbers cheat sheet (sourced)

| Claim | Value | Source |
|---|---|---|
| Hero range, before → after | 78/78 → 57/78 | `evidence/RUNS.md`, run `ff50e3620fdd` |
| Hero bisect | 240 victim runs, $0.60, 0 errors, SKIP `22a37db`, found `397c427` | `evidence/RUNS.md`, `evidence/bench-v1.md` |
| Hero trace / audit | `d80e61a81918c7eb3ffd917a2509efb0`, PASS 272 spans | `evidence/RUNS.md` |
| Hero visibility, independent | 18/18 vs 0/18 (6 harder tasks × 3 seeds) | `bench/strength.md` |
| Benchmark v1 | 6/6 (3 found + 3 correct `no_regression`), 1,140 runs, $2.70 | `evidence/bench-v1.md` |
| Invisible bugs a, d, e | 78/78 on all four refs, seeds 3–5, 312 runs, $0.711 | `bench/strength.md` |
| Gate example `hist/c` | 78/78 vs 72/78, Fisher p = 0.014, found `acf3b7d` | `evidence/RUNS.md` |
| v2, fixture only | 510 → 430 → 335 → 270 victim runs | `evidence/v2-efficiency-fixture.md` |
| Localise / fix on `hist/b` | TODO | main session |
| Benchmark v2 | TODO | `evidence/bench-v2.md` (main session) |
| cfo.ai margin / runway | TODO | `business/` |
