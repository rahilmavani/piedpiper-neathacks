"""Record which planted bugs a victim model can see, from its strength check, in bench/ground_truth.json.

    uv run python scripts/visibility_from_strength.py evidence/models/<slug>-strength.json

Visible means the bad head's pass rate is significantly below good-v1.0's (one-sided Fisher p < 0.05).
This is the only allowed source of `visible`: Culprit's own runs must never set it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
summary = json.loads(Path(sys.argv[1]).read_text())
model = summary["model"]
truth_path = ROOT / "bench" / "ground_truth.json"
truth = json.loads(truth_path.read_text())
for b in "abcdef":
    row = summary["refs"][f"origin/hist/{b}"]
    visible = row["fisher_p_vs_reference"] < 0.05
    truth["scenarios"][f"hist/{b}"]["visible"][model] = visible
    print(f"hist/{b}: {row['passes']}/{row['n']} vs good {summary['refs']['good-v1.0']['passes']}/"
          f"{summary['refs']['good-v1.0']['n']}, p={row['fisher_p_vs_reference']:.4f} → visible={visible}")
truth_path.write_text(json.dumps(truth, indent=2) + "\n")
