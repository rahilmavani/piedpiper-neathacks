# Running the victim-model benchmark on Claude Sonnet 5.5

GLM 5.3, Qwen 3.8 Flash, DeepSeek V4.1 Flash and Gemini 3.8 Flash were benchmarked through OpenRouter (`evidence/MODELS.md`). This file is for running **Claude Sonnet 5.5** the same way, on a machine with an Anthropic key, and adding it to `evidence/models.json` and the charts.

**Cost:** about **$15–20**. Sonnet costs about $0.0163 per victim run (measured on the RefundDesk baseline), and the full benchmark is about 1,150 victim runs: 546 for the strength check plus about 600 for six bisects. **Time:** about 1–1.5 hours.

## 0. Prerequisites

- Both repos cloned side by side and up to date (`git pull` in each). See `HANDOVER.md` §4.
- In `piedpiper-neathacks/.env`:
  - `ANTHROPIC_API_KEY=...`. With this key set, Culprit and RefundDesk use `claude-sonnet-5-5` automatically.
  - `VICTIM_MODEL` empty, or exactly `claude-sonnet-5-5`.
  - `CULPRIT_VICTIM_REPO=<path to the RefundDesk clone>`.
  - `NEATLOGS_API_KEY=...`, if you want the runs traced.
- The RefundDesk clone needs the `good-v1.0` tag and `origin/hist/a`…`f`, which a normal clone has.
- Sonnet 5.5 rejects `temperature`. RefundDesk's Anthropic client already detects that and retries without it.

## 1. Smoke test (1 run, ~$0.02)

```bash
cd piedpiper-neathacks
set -a; source .env; set +a
uv run --locked python scripts/strength_check.py "$CULPRIT_VICTIM_REPO" good-v1.0 refund_small_order 0-0 ba86ed0
```

Expect `model claude-sonnet-5-5 via anthropic` on the first line and `1/1` in the summary. If the run fails, stop and fix it before spending more.

## 2. Full benchmark (strength check + 6 bisects)

```bash
VICTIM_MODEL=claude-sonnet-5-5 BUDGET=6 bash scripts/bench_model.sh claude-sonnet-5-5 | tee sonnet-bench.log
```

- `BUDGET=6` raises the per-bisect cost cap. At Sonnet prices, the hist/b and hist/f bisects cost about $2.7–3, which is right at the default $3 cap.
- The strength check writes `evidence/models/claude-sonnet-5-5-strength.json`.
- Note the six `run_id` lines from the log: `grep '^run_id' sonnet-bench.log`.

If a run stops with `budget_exceeded` or `infra_error`, continue it with `uv run culprit resume <run_id> --budget-usd 8`. Don't start a new one.

## 3. Score and add to the comparison

```bash
uv run python scripts/visibility_from_strength.py evidence/models/claude-sonnet-5-5-strength.json
uv run culprit bench --tag claude-sonnet-5-5 --score-runs <id_a>,<id_b>,<id_c>,<id_d>,<id_e>,<id_f>
sqlite3 .culprit/ledger.sqlite ".backup evidence/models/claude-sonnet-5-5-ledger.sqlite" \
  && sqlite3 evidence/models/claude-sonnet-5-5-ledger.sqlite "pragma journal_mode=DELETE;"   # latencies for the charts
uv run python scripts/models_json.py        # should now list 5 models
uv run culprit export-costs --format csv --out business/runs.csv
```

- The first command records which bugs Sonnet can see, in `bench/ground_truth.json`. It must come before scoring.
- `bench` writes `evidence/bench-claude-sonnet-5-5.md` and `.json`.
- The ledger snapshot is what `models_json.py` reads latencies from. Check it contains no keys before committing: `strings evidence/models/claude-sonnet-5-5-ledger.sqlite | grep -c sk-ant` must print 0.

## 4. Record it

1. `evidence/MODELS.md`: add a Sonnet row to each table, copying the numbers from the `claude-sonnet-5-5` entry in `evidence/models.json`. Don't round in our favour.
2. `evidence/RUNS.md`: add a "Claude Sonnet 5.5" table with the six runs, the same columns as the other models.
3. Run the tests and check the exit code (`uv run pytest -q; echo $?` must print 0). Then commit `evidence/`, `bench/ground_truth.json` and `business/runs.csv`, and push to `main`.

## Notes

- **Ask before running.** It's the most expensive run of the project.
- Don't change `--suite-ref ba86ed0`, the seeds (3–5) or `--no-reuse`, or the numbers stop being comparable.
- The global $75 cap counts every run in your ledger, including the snapshot's (about $5).
