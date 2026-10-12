#!/bin/bash
# Benchmark one victim model end to end: the strength check, then Culprit on all six branches.
#
#   VICTIM_MODEL=<model> [BUDGET=3] bash scripts/bench_model.sh <model>
#
# Run from piedpiper-neathacks. The victim repo is $CULPRIT_VICTIM_REPO (default ../refunddesk).
# The suite is pinned at RefundDesk ba86ed0, like every recorded run. Bisects use --no-reuse, as the GLM v2
# benchmark did. Afterwards: visibility_from_strength.py, then `culprit bench --tag <slug> --score-runs ...`,
# then models_json.py. Results are summarised in evidence/MODELS.md.
set -u
MODEL="$1"; SLUG="${MODEL//\//-}"; BUDGET="${BUDGET:-3}"
VICTIM="${CULPRIT_VICTIM_REPO:-../refunddesk}"
export VICTIM_MODEL="$MODEL"
echo "######## $MODEL strength check $(date +%H:%M:%S)"
uv run --locked python scripts/strength_check.py "$VICTIM" \
  good-v1.0,origin/hist/a,origin/hist/b,origin/hist/c,origin/hist/d,origin/hist/e,origin/hist/f \
  ALL 3-5 ba86ed0 "evidence/models/$SLUG-strength.json" 2>&1 | grep -v '^{"ref"' | grep -v "neatlogs - INFO"
for b in a b c d e f; do
  echo "######## $MODEL hist/$b $(date +%H:%M:%S)"
  uv run --locked culprit run --repo "$VICTIM" --good good-v1.0 --bad "origin/hist/$b" --suite-ref ba86ed0 \
    --no-reuse --budget-usd "$BUDGET" 2>&1 | grep -v "neatlogs - INFO"
done
echo "######## $MODEL done $(date +%H:%M:%S)"
