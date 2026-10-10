#!/usr/bin/env bash
# Replays the recorded hero story at $0, for screen recording:
#   culprit report → culprit localise --replay → culprit fix --replay
# Everything comes from a copy of the ledger. No model call, no victim run, no trace export, and no
# network: the keys are blanked, uv runs offline, and scripts/no_network blocks internet sockets in
# the culprit process. The real ledger is only read (an SQLite backup), never written.
#
#   scripts/demo_replay.sh [run_id]          # default: the hero run ff50e3620fdd
#   CULPRIT_DB=/path/ledger.sqlite DEMO_PAUSE=0 scripts/demo_replay.sh <run_id>
set -euo pipefail

RUN_ID="${1:-ff50e3620fdd}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DB="${CULPRIT_DB:-$ROOT/.culprit/ledger.sqlite}"
PAUSE="${DEMO_PAUSE:-2}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/culprit-replay.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

[ -f "$SOURCE_DB" ] || { echo "no ledger at $SOURCE_DB (set CULPRIT_DB)" >&2; exit 2; }

# Empty values, not unset: the CLI loads .env, which would otherwise put the keys back.
export ANTHROPIC_API_KEY="" OPENROUTER_API_KEY="" NEATLOGS_API_KEY="" NEATLOGS_TOKEN=""
export CULPRIT_STATE_DIR="$WORK/state" PYTHONPATH="$ROOT/scripts/no_network" PYTHONUNBUFFERED=1
DB="$WORK/ledger.sqlite"

py() { uv run --project "$ROOT" --frozen --offline --quiet python "$@"; }
culprit() { uv run --project "$ROOT" --frozen --offline --quiet culprit "$@"; }
stage() { printf '\n\033[1m━━ %s\033[0m\n' "$1"; sleep "$PAUSE"; }
counts() {
  py - "$DB" "$RUN_ID" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
runs = c.execute("SELECT COUNT(*) FROM task_runs t JOIN steps s USING (step_id) WHERE s.run_id = ?", (sys.argv[2],)).fetchone()[0]
calls = c.execute("SELECT COUNT(*) FROM llm_calls WHERE run_id = ?", (sys.argv[2],)).fetchone()[0]
print(f"{runs} {calls}")
PY
}

py - "$SOURCE_DB" "$DB" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)  # consistent even while another process writes
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
PY
read -r RUNS_BEFORE CALLS_BEFORE < <(counts)

stage "1/3  culprit report $RUN_ID: what broke, and which commit did it"
culprit report "$RUN_ID" --db "$DB" --out "$WORK/reports" > /dev/null
REPORT="$WORK/reports/report-$RUN_ID.md"
awk '/^## Intent/ { intent = 1 } intent && ++n > 9 { exit } { print }' "$REPORT"

stage "2/3  culprit localise $RUN_ID --replay: which hunk of that commit is responsible"
culprit localise "$RUN_ID" --db "$DB" --replay | grep -v "suite pinned"

stage "3/3  culprit fix $RUN_ID --replay: a minimal fix, verified on the suite and held-out tasks"
culprit fix "$RUN_ID" --db "$DB" --replay | grep -v "suite pinned"

read -r RUNS_AFTER CALLS_AFTER < <(counts)
printf '\nreplayed from the ledger: %d new victim runs, %d new model calls, $0\n' \
  "$((RUNS_AFTER - RUNS_BEFORE))" "$((CALLS_AFTER - CALLS_BEFORE))"
[ "$RUNS_AFTER" -eq "$RUNS_BEFORE" ] && [ "$CALLS_AFTER" -eq "$CALLS_BEFORE" ]
