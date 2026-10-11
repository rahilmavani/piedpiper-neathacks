"""Turn a victim repo's calibration answer key into `bench/<name>/scenarios.yaml` and `ground_truth.json`.

    uv run python scripts/import_answer_key.py opsdesk ../opsdesk-answer-key.json ../opsdesk
    uv run python scripts/import_answer_key.py clinicdesk ../clinicdesk-answer-key.json ../clinicdesk

Visibility per model comes from the key's calibration (a measurement separate from Culprit's runs),
recomputed on the public suite only, the tasks Culprit runs: one-sided Fisher p < 0.05 versus the
good version. The answer key stays outside the victim repo; only this repo holds the converted copy.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from culprit.stats import fisher_one_sided

ALPHA = 0.05


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def counts(cell: dict) -> tuple[int, int]:
    """Public-suite pass counts of a calibration cell (both answer-key dialects)."""
    if "public_passed" in cell:
        return cell["public_passed"], cell["public_total"]
    return cell["passed"], cell["total"]


def convert(name: str, key: dict, repo: Path) -> tuple[str, dict]:
    good_sha = git(repo, "rev-parse", "good-v1.0^{commit}")
    matrix = key["matrix"]
    good_cell = matrix.get("baseline") or matrix.get("calibrated-good")
    scenarios, truth = [], {}
    for branch, info in sorted(key["branches"].items()):
        letter = branch.split("/")[-1]
        cells = matrix.get(letter) or matrix.get(f"calibrated-{letter}")
        culprit = info.get("regression_commit") or info.get("regression_sha")
        uninstallable = info.get("uninstallable_commit") or info.get("uninstallable_sha")
        visible, measured = {}, {}
        for model, cell in cells.items():
            gp, gn = counts(good_cell[model])
            bp, bn = counts(cell)
            p = fisher_one_sided(gp, gn, bp, bn)
            visible[model] = p < ALPHA
            measured[model] = {"good": [gp, gn], "bad": [bp, bn], "p": round(p, 6)}
        changed = info.get("changed_file")
        truth[branch] = {
            "bad_sha": git(repo, "rev-parse", f"{branch}^{{commit}}"),
            "commits": info.get("commit_count"),
            "culprit_sha": culprit,
            "position": info.get("position"),
            "subject": git(repo, "log", "-1", "--format=%s", culprit),
            "uninstallable": [uninstallable] if uninstallable else [],
            "hunks": [{"file": changed, "what": info.get("what_changed", "")}] if changed else [],
            "what_changed": info.get("what_changed") or info.get("changes", ""),
            "intended_gain": {},
            "visible": visible,
            "calibration": measured,
        }
        scenarios.append(f"  - name: {branch}\n    good: good-v1.0\n    bad: {branch}\n")
    yaml = (f"# {name}: benchmark scenarios for `culprit bench`, one per history branch.\n"
            f"# Run with --repo <path to {name}> --eval-module {name}.eval. Answers in ground_truth.json.\n"
            "scenarios:\n" + "".join(scenarios))
    about = (f"Answer key for the {name} victim, converted by scripts/import_answer_key.py from the repo's own "
             "calibration (kept outside the victim repo). `visible` is the calibration's measurement on the public "
             "suite (one-sided Fisher p < 0.05 vs good-v1.0; seeds "
             f"{key.get('seeds')}), separate from Culprit's runs; `calibration` holds the counts.")
    return yaml, {"_about": about, "good_sha": good_sha, "scenarios": truth}


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    name, key_path, repo = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]).resolve()
    yaml, truth = convert(name, json.loads(key_path.read_text()), repo)
    out = Path(__file__).resolve().parents[1] / "bench" / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "scenarios.yaml").write_text(yaml)
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    for branch, t in truth["scenarios"].items():
        print(f"{name} {branch}: culprit {t['culprit_sha'][:7]} visible {t['visible']}")
