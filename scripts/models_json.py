"""Build evidence/models.json (victim-model comparison, for the website charts) from evidence files only.

A model is included when both of these exist (slug = model id with "/" replaced by "-"):
  evidence/models/<slug>-strength.json   from scripts/strength_check.py (good-v1.0 + six hist heads, seeds 3-5)
  evidence/bench-<slug>.json             from `culprit bench --tag <slug> --score-runs ...`
GLM 5.3 (benchmarked first) is built from bench-v2.json and its earlier checks. To add a model, produce those
two files and run:  uv run python scripts/models_json.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
BRANCHES = ["a", "b", "c", "d", "e", "f"]
ALPHA = 0.05
# Runs stopped by the OpenRouter key's $10 limit on 11 Oct and resumed after it was raised. Their wall time
# includes the pause; victim runs and cost are unaffected (nothing is re-run or counted twice).
RESUMED = {"706b51fa91d9", "2797e84bcc15", "8ace75bdc6fa", "57052ac18acd", "25ed0ebed07b", "e2473ed6f0e9",
           "30e9f8e6a19f", "41056dd52750", "0e6caa11ae4b", "48f6b3ba137a", "9656aba229d2"}
LABELS = {
    "z-ai/glm-5.3": "GLM 5.3",
    "qwen/qwen3.8-flash": "Qwen 3.8 Flash",
    "deepseek/deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    "google/gemini-3.8-flash": "Gemini 3.8 Flash",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
}


def slug(model: str) -> str:
    return model.replace("/", "-")


def prices() -> dict[str, tuple[float, float]]:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from culprit.providers import PRICES

    return PRICES


def bugs() -> dict:
    truth = json.loads((ROOT / "bench" / "ground_truth.json").read_text())["scenarios"]
    return {b: {"culprit_sha": truth[f"hist/{b}"]["culprit_sha"], "subject": truth[f"hist/{b}"]["subject"],
                "intended_gain": truth[f"hist/{b}"]["intended_gain"]["claim"]} for b in BRANCHES}


def ledger_for(model: str) -> Path | None:
    """Committed ledger snapshot holding this model's runs (GLM and Qwen: the main snapshot)."""
    own = EVIDENCE / "models" / f"{slug(model)}-ledger.sqlite"
    return own if own.exists() else EVIDENCE / "ledger-snapshot.sqlite"


def timing(ledger: Path, run_ids: list[str]) -> dict[str, dict]:
    """Per run: the victim runs' own latencies. A step stopped by an infrastructure error stays open until it
    is resumed, so step or run durations include any pause; the victim runs' latencies don't (runs cut off
    by the error are never recorded)."""
    import sqlite3
    conn = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    out = {}
    for run_id in run_ids:
        lat = [r[0] for r in conn.execute("SELECT t.latency_ms FROM task_runs t JOIN steps s USING (step_id) "
                                          "WHERE s.run_id = ? AND t.latency_ms IS NOT NULL", (run_id,))]
        out[run_id] = {"latencies": lat}
    return out


def culprit_block(bench_file: Path, method: str) -> dict:
    import statistics

    data = json.loads(bench_file.read_text())
    runs = []
    for r in sorted(data["rows"], key=lambda r: r["scenario"]):
        runs.append({"branch": r["scenario"].split("/")[1], "run_id": r["run_id"], "status": r["status"],
                     "found": r["culprit_sha"], "expected": r["expected"], "outcome": r["outcome"],
                     "victim_runs": r["victim_runs"], "cost_usd": round(r["cost_usd"], 6),
                     "wall_s": r["wall_s"], "resumed": r["run_id"] in RESUMED, "skipped": r["skipped"],
                     "traces": r["traces"]})
    model = data["rows"][0]["victim_model"]
    times = timing(ledger_for(model), [r["run_id"] for r in runs])
    for r in runs:
        r["victim_latency_sum_s"] = round(sum(times[r["run_id"]]["latencies"]) / 1000, 1)
    latencies = [x for t in times.values() for x in t["latencies"]]
    victim_runs = sum(r["victim_runs"] for r in runs)
    cost = sum(r["cost_usd"] for r in runs)
    found = [r for r in runs if r["status"] == "found"]
    return {
        "method": method, "bench_file": str(bench_file.relative_to(ROOT)), "culprit_code": data["culprit"],
        "accuracy": data["accuracy"], "victim_runs": victim_runs, "cost_usd": round(cost, 6),
        "wall_s": sum(r["wall_s"] or 0 for r in runs),
        "wall_s_comparable": not any(r["resumed"] for r in runs),
        "victim_latency_sum_s": round(sum(r["victim_latency_sum_s"] for r in runs), 1),
        "median_victim_run_latency_ms": round(statistics.median(latencies)) if latencies else None,
        "cost_per_bisect_usd": round(cost / len(runs), 6) if runs else None,
        "cost_per_found_bisect_usd": round(sum(r["cost_usd"] for r in found) / len(found), 6) if found else None,
        "cost_per_victim_run_usd": round(cost / victim_runs, 6) if victim_runs else None,
        "runs": runs,
    }


def from_strength(summary: dict) -> tuple[dict, dict]:
    refs = summary["refs"]
    good = refs["good-v1.0"]
    heads, visible = {}, {}
    for b in BRANCHES:
        row = refs[f"origin/hist/{b}"]
        p = row["fisher_p_vs_reference"]
        heads[b] = {"passes": row["passes"], "n": row["n"], "fisher_p": p, "failing_tasks": row["failing_tasks"],
                    "infra_errors": row["infra_errors"]}
        visible[b] = {"visible": p < ALPHA, "source": "strength_check"}
    strength = {"seeds": summary["seeds"], "suite_sha": summary["suite_sha"], "tasks": summary["tasks"],
                "good": {"passes": good["passes"], "n": good["n"], "failing_tasks": good["failing_tasks"]},
                "heads": heads, "cost_usd": summary["total_cost_usd"]}
    return strength, visible


def glm_entry() -> dict:
    from collections import defaultdict

    from_log = defaultdict(lambda: [0, 0])
    for line in (EVIDENCE / "strength-check-glm.jsonl").read_text().splitlines():
        r = json.loads(line)
        ref = r["ref"].removeprefix("origin/hist/")
        from_log[ref][0] += r["passed"]
        from_log[ref][1] += 1
    good = from_log.pop("good-v1.0")
    heads = {b: {"passes": v[0], "n": v[1]} for b, v in from_log.items()}
    visible = {b: {"visible": False, "source": "strength_check"} for b in heads}
    visible["b"] = {"visible": True, "source": "hero_check (6 harder tasks x seeds 0-2: 18/18 vs 0/18)"}
    visible["c"] = {"visible": True, "source": "culprit_baseline only (72/78 vs 78/78, Fisher p=0.014)"}
    visible["f"] = {"visible": True, "source": "culprit_baseline only (51/78 vs 78/78)"}
    return {
        "strength": {"seeds": [3, 5], "tasks": 26, "good": {"passes": good[0], "n": good[1]}, "heads": heads,
                     "note": "Independent full-suite check covered a, d, e only (evidence/strength-check-glm.jsonl)"},
        "visible": {b: visible[b] for b in BRANCHES},
        "culprit": culprit_block(EVIDENCE / "bench-v2.json", "v2 staged baseline, --no-reuse, k=3"),
    }


def entry(model: str, strength: dict | None, visible: dict, culprit: dict) -> dict:
    price = prices().get(model)
    good = (strength or {}).get("good", {})
    return {
        "model": model, "label": LABELS.get(model, model),
        "provider": "anthropic" if model.startswith("claude-") else "openrouter",
        "price_per_mtok_usd": {"input": price[0], "output": price[1]} if price else None,
        "baseline_pass_rate": round(good["passes"] / good["n"], 4) if good.get("n") else None,
        "visible_bugs": sum(v["visible"] for v in visible.values()),
        "strength": strength, "visible": visible, "culprit": culprit,
    }


def build() -> dict:
    models = []
    glm = glm_entry()
    models.append(entry("z-ai/glm-5.3", glm["strength"], glm["visible"], glm["culprit"]))
    for strength_file in sorted((EVIDENCE / "models").glob("*-strength.json")):
        summary = json.loads(strength_file.read_text())
        model = summary["model"]
        bench_file = EVIDENCE / f"bench-{slug(model)}.json"
        if model == "z-ai/glm-5.3" or not bench_file.exists():
            continue
        strength, visible = from_strength(summary)
        models.append(entry(model, strength, visible,
                            culprit_block(bench_file, "v2 staged baseline, --no-reuse, k=3, suite ba86ed0")))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "description": "Culprit across victim models on RefundDesk: which planted bugs each model's test suite can "
                       "see (strength check, seeds 3-5), and Culprit's accuracy and cost finding them (6 bisects).",
        "suite": {"repo": "piedpiper-neathacks-refunddesk", "ref": "ba86ed0", "tasks": 26, "k": 3},
        "visibility_rule": f"one-sided Fisher exact p < {ALPHA}, bad head vs good-v1.0",
        "bugs": bugs(),
        "models": models,
    }


if __name__ == "__main__":
    out = EVIDENCE / "models.json"
    data = build()
    out.write_text(json.dumps(data, indent=2) + "\n")
    print(f"{len(data['models'])} models → {out.relative_to(ROOT)}: " + ", ".join(m["label"] for m in data["models"]))
