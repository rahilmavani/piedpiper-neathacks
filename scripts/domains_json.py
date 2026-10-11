"""Build evidence/domains.json: Culprit across victim domains × victim models, for the website charts.

    uv run python scripts/domains_json.py

Reads each domain's answer key (bench/<domain>/ground_truth.json, or bench/ground_truth.json for
RefundDesk) and the scored bench reports evidence/bench-<domain>-<model>.json. Every number comes
from those files; nothing is estimated here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = {
    "opsdesk": {"title": "OpsDesk", "what": "incident-response agent (metrics, rollbacks, restarts, paging)",
                "repo": "https://github.com/ayushgml/opsdesk"},
    "clinicdesk": {"title": "ClinicDesk", "what": "clinic front-desk agent (scheduling, red-flag escalation, privacy)",
                   "repo": "https://github.com/ayushgml/clinicdesk"},
}
MODELS = {"glm-5.3": "z-ai/glm-5.3", "llama-3.1-8b": "meta-llama/llama-3.1-8b-instruct"}
LABELS = {"z-ai/glm-5.3": "GLM 5.3", "meta-llama/llama-3.1-8b-instruct": "Llama 3.1 8B"}


def main() -> None:
    out = {"schema_version": 1, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
           "description": "Culprit bisects on two extra victim domains, each with six planted regressions, on two "
                          "victim models. `expected_visible` is the domain's calibration (a separate measurement); "
                          "`outcome` is culprit bench's score against the answer key.",
           "models": [{"id": m, "label": LABELS[m]} for m in MODELS.values()], "domains": []}
    for domain, meta in DOMAINS.items():
        truth = json.loads((ROOT / "bench" / domain / "ground_truth.json").read_text())["scenarios"]
        entry = {"id": domain, **meta, "branches": [], "summary": {}}
        for slug, model in MODELS.items():
            report = json.loads((ROOT / "evidence" / f"bench-{domain}-{slug}.json").read_text())
            rows = {r["scenario"]: r for r in report["rows"]}
            for branch, t in truth.items():
                r = rows[branch]
                entry["branches"].append({
                    "branch": branch, "model": model, "what_changed": t.get("what_changed", ""),
                    "planted_commit": t["culprit_sha"], "expected_visible": t["visible"].get(model),
                    "status": r["status"], "found": r.get("culprit_sha"), "outcome": r["outcome"],
                    "run_id": r["run_id"], "victim_runs": r["victim_runs"], "cost_usd": round(r["cost_usd"], 6),
                    "wall_s": r.get("wall_s"),
                })
            acc = report["accuracy"]
            entry["summary"][model] = {
                "correct": acc["correct"], "scored": acc["scored"],
                "wrong_culprit": sum(r["outcome"] == "wrong" for r in report["rows"]),
                "missed": sum(r["outcome"] == "missed" for r in report["rows"]),
                "victim_runs": sum(r["victim_runs"] for r in report["rows"]),
                "cost_usd": round(sum(r["cost_usd"] for r in report["rows"]), 4),
            }
        out["domains"].append(entry)
    path = ROOT / "evidence" / "domains.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    for d in out["domains"]:
        print(d["id"], {LABELS[m]: f"{s['correct']}/{s['scored']} (missed {s['missed']}, wrong {s['wrong_culprit']}, "
                        f"${s['cost_usd']})" for m, s in d["summary"].items()})
    print(f"→ {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
