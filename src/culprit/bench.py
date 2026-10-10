"""`culprit bench`: run scenarios through the orchestrator and score them against ground truth (PRD §10, §13).

Leakage guard: the orchestrator only ever receives a scenario's good and bad SHAs, never its name
or its answer. The ground truth is read for scoring after the runs, and must live outside the victim repo.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from culprit import gitops
from culprit.bisect import Verdict, bounds
from culprit.config import PROJECT_ROOT, Config
from culprit.ledger import Ledger
from culprit.orchestrator import Orchestrator

Log = Callable[[str], None]

# Outcomes of scoring one run. Accuracy counts CORRECT and CORRECT_NO_REGRESSION.
CORRECT = "correct"
WRONG = "wrong"
CORRECT_NO_REGRESSION = "correct_no_regression"  # gate said no regression, and the bug is known to be invisible
MISSED = "missed"  # gate said no regression, but the bug is known to be visible on this victim model
NO_REGRESSION_UNVERIFIED = "no_regression_unverified"  # gate said no regression; visibility not measured
AMBIGUOUS_CONTAINS = "ambiguous_contains"
AMBIGUOUS_MISSES = "ambiguous_misses"
INCOMPLETE = "incomplete"  # budget_exceeded, infra_error, error or still running
ACCURATE = {CORRECT, CORRECT_NO_REGRESSION}


class BenchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Scenario:
    name: str
    good: str
    bad: str


@dataclass(frozen=True)
class Truth:
    culprit_sha: str | None  # None: no regression planted in the range
    bad_sha: str | None = None
    uninstallable: tuple[str, ...] = ()
    hunks: tuple[dict[str, Any], ...] = ()
    intended_gain: dict[str, Any] = field(default_factory=dict)
    visible: dict[str, bool] = field(default_factory=dict)  # victim model -> can the gate see the bug?


@dataclass(frozen=True)
class RunFacts:
    run_id: str
    status: str
    culprit_sha: str | None
    suspects: list[str]
    good_sha: str | None
    bad_sha: str | None
    victim_model: str
    victim_runs: int
    cost_usd: float
    wall_s: float | None
    skipped: list[str]
    confidence: str | None
    summary: str | None
    traces: list[str]


@dataclass(frozen=True)
class Row:
    scenario: str
    outcome: str
    facts: RunFacts
    expected: str | None
    note: str = ""


# loading ---------------------------------------------------------------------------------
def load_scenarios(path: Path) -> list[Scenario]:
    data = yaml.safe_load(path.read_text()) or {}
    items = data.get("scenarios")
    if not isinstance(items, list) or not items:
        raise BenchError(f"{path}: expected a non-empty `scenarios` list")
    scenarios = []
    for i, item in enumerate(items):
        missing = [k for k in ("name", "good", "bad") if not isinstance(item, dict) or not item.get(k)]
        if missing:
            raise BenchError(f"{path}: scenario #{i + 1} is missing {', '.join(missing)}")
        scenarios.append(Scenario(str(item["name"]), str(item["good"]), str(item["bad"])))
    names = [s.name for s in scenarios]
    if len(set(names)) != len(names):
        raise BenchError(f"{path}: duplicate scenario names")
    return scenarios


def load_ground_truth(path: Path) -> dict[str, Truth]:
    data = json.loads(path.read_text())
    items = data.get("scenarios")
    if not isinstance(items, dict):
        raise BenchError(f"{path}: expected a `scenarios` object keyed by scenario name")
    truth = {}
    for name, item in items.items():
        if "culprit_sha" not in item:
            raise BenchError(f"{path}: {name} has no culprit_sha (use null for 'no regression planted')")
        truth[name] = Truth(
            culprit_sha=item["culprit_sha"], bad_sha=item.get("bad_sha"),
            uninstallable=tuple(item.get("uninstallable", ())), hunks=tuple(item.get("hunks", ())),
            intended_gain=dict(item.get("intended_gain", {})), visible=dict(item.get("visible", {})),
        )
    return truth


def guard_outside_repo(repo: Path, *paths: Path) -> None:
    """The answer key and scenario mapping must never live in the victim repo."""
    root = repo.resolve()
    for path in paths:
        if path.resolve().is_relative_to(root):
            raise BenchError(f"{path} is inside the victim repo {root}; keep bench files in the Culprit repo")


# running ---------------------------------------------------------------------------------
def run_scenarios(ledger: Ledger, repo: Path, scenarios: list[Scenario], log: Log = print, workers: int = 4,
                  **cfg: Any) -> dict[str, str]:
    """Run each scenario once, in order; returns scenario name -> run_id.

    Only the resolved SHAs go into the run's Config, so neither the scenario name nor the ground
    truth can reach the ledger config, a trace, an LLM prompt or Entire text.
    """
    run_ids = {}
    for s in scenarios:
        good, bad = gitops.resolve(repo, s.good), gitops.resolve(repo, s.bad)
        orch = Orchestrator(ledger, Config(repo=str(repo), good_ref=good, bad_ref=bad, **cfg), log=log,
                            workers=workers)
        run_id = orch.start()
        run_ids[s.name] = run_id
        log(f"== {s.name}: run {run_id} ({good[:10]}..{bad[:10]})")
        try:
            orch.run(run_id)
        except Exception as exc:  # recorded as status `error`; the bench moves on to the next scenario
            log(f"   run {run_id} stopped with {type(exc).__name__}: {exc}")
    return run_ids


def match_runs(ledger: Ledger, repo: Path, scenarios: list[Scenario], run_ids: list[str] | None
               ) -> dict[str, str]:
    """Pair existing runs with scenarios by their recorded good and bad SHAs.

    With `run_ids`, each one must match a scenario. Without, each scenario gets its latest
    finished matching run (or its latest unfinished one when none has finished).
    """
    by_range = {(gitops.resolve(repo, s.good), gitops.resolve(repo, s.bad)): s.name for s in scenarios}
    if run_ids:
        matched = {}
        for run_id in run_ids:
            row = ledger.get_run(run_id)
            name = by_range.get((row["good_sha"], row["bad_sha"]))
            if name is None:
                raise BenchError(f"run {run_id} ({row['good_ref']}..{row['bad_ref']}) matches no scenario")
            if name in matched:
                raise BenchError(f"runs {matched[name]} and {run_id} both match {name}")
            matched[name] = run_id
        return matched
    latest: dict[str, Any] = {}
    for row in ledger.runs():
        name = by_range.get((row["good_sha"], row["bad_sha"]))
        if name is not None and (name not in latest or row["finished_at"] or not latest[name]["finished_at"]):
            latest[name] = row
    return {name: row["run_id"] for name, row in latest.items()}


# scoring ---------------------------------------------------------------------------------
def _seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def run_facts(ledger: Ledger, repo: Path, run_id: str) -> RunFacts:
    row = ledger.get_run(run_id)
    cfg = Config.from_json(row["config_json"])
    steps = ledger.steps(run_id)
    # A commit's final verdict is the last decided one across its bisect and resample steps.
    final: dict[str, str] = {}
    for s in steps:
        if s["kind"] != "baseline" and s["decision"] in {v.value for v in Verdict}:
            final[s["commit_sha"]] = s["decision"]
    suspects: list[str] = []
    if row["good_sha"] and row["bad_sha"] and row["status"] != "no_regression":
        candidates = gitops.first_parent_range(repo, row["good_sha"], row["bad_sha"])
        tested = [(sha, Verdict(v)) for sha, v in final.items() if sha in candidates]
        lo, hi = bounds(candidates, tested)
        suspects = candidates[lo + 1 : hi + 1]
    return RunFacts(
        run_id=run_id, status=row["status"], culprit_sha=row["culprit_sha"], suspects=suspects,
        good_sha=row["good_sha"], bad_sha=row["bad_sha"], victim_model=cfg.victim_model or "victim default",
        victim_runs=ledger.task_run_count(run_id), cost_usd=ledger.run_cost(run_id),
        wall_s=_seconds(row["started_at"], row["finished_at"]),
        skipped=[sha for sha, v in final.items() if v == Verdict.SKIP],
        confidence=row["confidence"], summary=row["summary"],
        traces=(ledger.get_artifact(run_id, "neatlogs_traces") or "").split(),
    )


def score(truth: Truth, facts: RunFacts) -> str:
    if facts.status == "found":
        return CORRECT if facts.culprit_sha == truth.culprit_sha else WRONG
    if facts.status == "no_regression":
        if truth.culprit_sha is None:
            return CORRECT_NO_REGRESSION
        visible = truth.visible.get(facts.victim_model)
        if visible is None:
            return NO_REGRESSION_UNVERIFIED
        return MISSED if visible else CORRECT_NO_REGRESSION
    if facts.status == "ambiguous":
        return AMBIGUOUS_CONTAINS if truth.culprit_sha in facts.suspects else AMBIGUOUS_MISSES
    return INCOMPLETE


def score_runs(ledger: Ledger, repo: Path, truth: dict[str, Truth], run_ids: dict[str, str]) -> list[Row]:
    rows = []
    for name, run_id in run_ids.items():
        if name not in truth:
            raise BenchError(f"no ground truth for scenario {name}")
        t, facts = truth[name], run_facts(ledger, repo, run_id)
        note = ""
        if t.bad_sha and facts.bad_sha != t.bad_sha:
            note = f"run's bad SHA {str(facts.bad_sha)[:10]} differs from the ground truth's {t.bad_sha[:10]}"
        rows.append(Row(name, score(t, facts), facts, t.culprit_sha, note))
    return rows


# report ----------------------------------------------------------------------------------
def culprit_version() -> str:
    """Culprit's own commit, so v1 and v2 reports name the code that produced them."""
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(PROJECT_ROOT), *args], capture_output=True, text=True).stdout.strip()

    sha = git("rev-parse", "HEAD")
    return f"{sha}{' + uncommitted changes' if git('status', '--porcelain', '--untracked-files=no') else ''}"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def _short(sha: str | None) -> str:
    return f"`{sha[:7]}`" if sha else "none"


def render(tag: str, rows: list[Row], mode: str, repo: Path, missing: Sequence[str] = ()) -> str:
    accurate = sum(r.outcome in ACCURATE for r in rows)
    runs = sum(r.facts.victim_runs for r in rows)
    cost = sum(r.facts.cost_usd for r in rows)
    wall = sum(r.facts.wall_s or 0 for r in rows)
    models = sorted({r.facts.victim_model for r in rows})
    lines = [
        f"# Culprit bench {tag}",
        "",
        f"- Generated: {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- Mode: {mode}",
        f"- Culprit code: `{culprit_version()}`",
        f"- Victim repo: `{repo}`",
        f"- Victim model(s): {', '.join(f'`{m}`' for m in models)}",
        "",
        "## Summary",
        "",
        f"- **Culprit accuracy: {accurate}/{len(rows)}** (correct commit, or a correct `no_regression`)",
        f"- Victim runs: {runs} ({runs / len(rows):.0f} per scenario)" if rows else "- Victim runs: 0",
        f"- Cost: ${cost:.2f} (${cost / len(rows):.2f} per scenario)" if rows else "- Cost: $0.00",
        f"- Wall time: {_duration(wall)} (sum of runs)",
        "- Hunk accuracy and fix verification: not measured (localiser and fixer not built yet)",
        *([f"- Not scored (no run): {', '.join(missing)}"] if missing else []),
        "",
        "## Results",
        "",
        "| Scenario | Outcome | Status | Found | Expected | Victim runs | Cost | Wall time | Skipped | Model | Run |",
        "|---|---|---|---|---|---:|---:|---:|---|---|---|",
    ]
    for r in rows:
        f = r.facts
        found = _short(f.culprit_sha) if f.status == "found" else \
            ", ".join(_short(s) for s in f.suspects) if f.status in {"ambiguous", "budget_exceeded"} else "–"
        lines.append(
            f"| {r.scenario} | **{r.outcome}** | {f.status} | {found} | {_short(r.expected)} | {f.victim_runs} | "
            f"${f.cost_usd:.2f} | {_duration(f.wall_s)} | {', '.join(_short(s) for s in f.skipped) or '–'} | "
            f"`{f.victim_model}` | `{f.run_id}` |"
        )
    lines += ["", "## Runs", ""]
    for r in rows:
        f = r.facts
        lines += [
            f"### {r.scenario}: run `{f.run_id}`",
            "",
            f"- Range: `{(f.good_sha or '?')[:12]}..{(f.bad_sha or '?')[:12]}`",
            f"- Summary: {f.summary or '(none)'}",
            f"- Confidence: {f.confidence or '–'}",
            f"- neatlogs Culprit trace(s): {', '.join(f'`{t}`' for t in f.traces) or 'none recorded'}"
            f" (session = run ID `{f.run_id}`)",
        ]
        if r.note:
            lines.append(f"- Note: {r.note}")
        lines.append("")
    lines += [
        "Outcomes: `correct` names the planted commit; `correct_no_regression` means the gate found no "
        "significant regression and none was expected (no bug planted in the range, or a measurement showed "
        "this bug is invisible on this model); `missed` means "
        "it is known to be visible; `no_regression_unverified` means its visibility on this model has not been "
        "measured; `ambiguous_*` means skipped commits hid the boundary; `incomplete` means the run stopped "
        "(budget, infrastructure or error). Wall time is from the run's start to its finish in the ledger, "
        "so it includes any pause before a resume.",
        "",
    ]
    return "\n".join(lines)


def write_report(out_dir: Path, tag: str, rows: list[Row], mode: str, repo: Path,
                 missing: Sequence[str] = ()) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / f"bench-{tag}.md"
    md.write_text(render(tag, rows, mode, repo, missing))
    (out_dir / f"bench-{tag}.json").write_text(json.dumps(
        {"tag": tag, "mode": mode, "culprit": culprit_version(), "not_scored": list(missing),
         "rows": [{**asdict(r.facts), "scenario": r.scenario, "outcome": r.outcome, "expected": r.expected,
                   "note": r.note} for r in rows]},
        indent=2) + "\n")
    return md
