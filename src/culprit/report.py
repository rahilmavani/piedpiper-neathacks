"""`culprit report <run_id>`: a run's receipts as markdown and a static HTML page (PRD M6).

Everything comes from the ledger: verdict, baselines and the regression gate, the bisect timeline
with each commit's Wilson interval against its threshold, skipped commits, the culprit's intent and
diff, neatlogs trace IDs, costs, and where reused baseline results came from. The victim repo is
only read for commit subjects and positions; without it the report still renders.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment

from culprit import gitops, reuse
from culprit.costs import RunCosts, run_costs
from culprit.ledger import Ledger, TaskRun
from culprit.stats import fisher_one_sided, wilson

DIFF_MAX_LINES = 400


@dataclass(frozen=True)
class Round:
    kind: str
    passes: int  # cumulative over this commit's rounds so far
    n: int
    low: float
    high: float
    decision: str | None


@dataclass(frozen=True)
class CommitEval:
    sha: str
    subject: str
    position: int | None  # 1-based in good..bad
    decision: str  # GOOD / BAD / SKIP / INCONCLUSIVE
    flags: str | None
    rounds: list[Round]
    threshold: float | None
    error: str | None  # install log tail for a SKIP
    trace_ids: list[str]

    @property
    def last(self) -> Round | None:
        return self.rounds[-1] if self.rounds else None


@dataclass(frozen=True)
class End:
    label: str
    sha: str
    passes: int
    n: int
    low: float
    high: float
    screen: tuple[int, int] | None  # v2 screen (passes, n), None for a v1 baseline
    reused: int
    trace_ids: list[str]


@dataclass
class Report:
    run_id: str
    repo: str
    good_ref: str
    bad_ref: str
    status: str
    summary: str
    confidence: str | None
    culprit_sha: str | None
    culprit_subject: str
    victim: str
    k: int
    z: float
    suite: str
    candidates: int | None
    good: End | None
    bad: End | None
    fisher_p: float | None
    gate_alpha: float
    discriminating: list[str]
    timeline: list[CommitEval]
    intent: str | None
    intent_meta: dict
    diff: str | None
    diff_truncated: int
    culprit_traces: list[str]
    costs: RunCosts
    reuse: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def skips(self) -> list[CommitEval]:
        return [c for c in self.timeline if c.decision == "SKIP"]

    @property
    def victim_trace_count(self) -> int:
        ends = [e for e in (self.good, self.bad) if e]
        return sum(len(e.trace_ids) for e in ends) + sum(len(c.trace_ids) for c in self.timeline)


def _subject(repo: Path, sha: str) -> str:
    try:
        return gitops.subject(repo, sha)
    except (gitops.GitError, OSError):
        return ""


def _threshold(good: list[TaskRun], bad: list[TaskRun], runs: list[TaskRun]) -> float | None:
    """Midpoint of good and bad pass rates over the same task mix (as Baselines.threshold)."""
    def rates(rs: list[TaskRun]) -> dict[str, float]:
        by: dict[str, list[bool]] = {}
        for r in rs:
            by.setdefault(r.task_id, []).append(r.passed)
        return {t: sum(v) / len(v) for t, v in by.items()}

    g, b = rates(good), rates(bad)
    usable = [r for r in runs if r.task_id in g]
    return sum((g[r.task_id] + b.get(r.task_id, 0.0)) / 2 for r in usable) / len(usable) if usable else None


def collect(ledger: Ledger, run_id: str) -> Report:
    row = ledger.get_run(run_id)
    cfg = json.loads(row["config_json"])
    repo, z = Path(row["repo"]), float(cfg.get("z", 1.96))
    steps = ledger.steps(run_id)
    runs_of = {s["step_id"]: list(ledger.task_runs(s["step_id"]).values()) for s in steps}
    reused_of = {s["step_id"]: ledger.conn.execute(
        "SELECT COUNT(*) FROM task_runs WHERE step_id = ? AND reused_from_run IS NOT NULL",
        (s["step_id"],)).fetchone()[0] for s in steps}

    def end(label: str, sha: str | None) -> tuple[End | None, list[TaskRun]]:
        mine = [s for s in steps if s["kind"].startswith("baseline") and s["commit_sha"] == sha]
        rs = [r for s in mine for r in runs_of[s["step_id"]]]
        if not rs:
            return None, []
        staged = bool(cfg.get("staged_baseline")) and int(cfg.get("k", 0)) > 1
        screen_runs = [r for r in rs if r.repetition == 0]
        passes = sum(r.passed for r in rs)
        low, high = wilson(passes, len(rs), z)
        return End(label, sha, passes, len(rs), low, high,
                   (sum(r.passed for r in screen_runs), len(screen_runs)) if staged else None,
                   sum(reused_of[s["step_id"]] for s in mine), [r.trace_id for r in rs if r.trace_id]), rs

    good, good_runs = end("good", row["good_sha"])
    bad, bad_runs = end("bad", row["bad_sha"])
    fisher_p = fisher_one_sided(good.passes, good.n, bad.passes, bad.n) if good and bad else None

    try:
        candidates = gitops.first_parent_range(repo, row["good_sha"], row["bad_sha"]) if row["good_sha"] else []
    except (gitops.GitError, OSError):
        candidates = []
    position = {sha: i + 1 for i, sha in enumerate(candidates)}

    timeline: list[CommitEval] = []
    by_commit: dict[str, list] = {}
    for s in steps:
        if not s["kind"].startswith("baseline"):
            by_commit.setdefault(s["commit_sha"], []).append(s)
    discriminating: list[str] = []
    for sha, commit_steps in by_commit.items():  # dict order = step order = test order
        rounds, cumulative = [], []
        for s in commit_steps:
            cumulative += runs_of[s["step_id"]]
            if s["kind"] == "bisect":
                discriminating = discriminating or sorted({r.task_id for r in runs_of[s["step_id"]]})
            if s["status"] == "skip":
                continue
            passes = sum(r.passed for r in cumulative)
            low, high = wilson(passes, len(cumulative), z)
            rounds.append(Round(s["kind"], passes, len(cumulative), low, high, s["decision"]))
        last = commit_steps[-1]
        skipped = any(s["status"] == "skip" for s in commit_steps)
        timeline.append(CommitEval(
            sha=sha, subject=_subject(repo, sha), position=position.get(sha),
            decision="SKIP" if skipped else (last["decision"] or "INCONCLUSIVE"), flags=last["flags"],
            rounds=rounds, threshold=_threshold(good_runs, bad_runs, cumulative) if cumulative else None,
            error=next((s["error"] for s in commit_steps if s["error"]), None),
            trace_ids=[r.trace_id for r in cumulative if r.trace_id],
        ))

    diff = ledger.get_artifact(run_id, "diff")
    truncated = 0
    if diff:
        lines = diff.splitlines()
        if len(lines) > DIFF_MAX_LINES:
            truncated, diff = len(lines) - DIFF_MAX_LINES, "\n".join(lines[:DIFF_MAX_LINES])
    intent = ledger.get_artifact(run_id, "intent")
    if intent and "\n\nDiff:\n" in intent:  # the fallback carries the diff; it has its own section
        intent = intent.split("\n\nDiff:\n", 1)[0]
    meta = ledger.get_artifact(run_id, "intent_meta")
    suite = f"{row['suite_source'] or cfg.get('suite', '')} @ {(row['suite_sha'] or '')[:19]}"
    return Report(
        run_id=run_id, repo=row["repo"], good_ref=row["good_ref"], bad_ref=row["bad_ref"], status=row["status"],
        summary=row["summary"] or "", confidence=row["confidence"], culprit_sha=row["culprit_sha"],
        culprit_subject=_subject(repo, row["culprit_sha"]) if row["culprit_sha"] else "",
        victim=" via ".join(x for x in (cfg.get("victim_model"), cfg.get("victim_provider")) if x) or "victim env",
        k=int(cfg.get("k", 0)), z=z, suite=suite, candidates=len(candidates) or None, good=good, bad=bad,
        fisher_p=fisher_p, gate_alpha=float(cfg.get("gate_alpha", 0.05)), discriminating=discriminating,
        timeline=timeline, intent=intent, intent_meta=json.loads(meta) if meta else {}, diff=diff,
        diff_truncated=truncated, culprit_traces=(ledger.get_artifact(run_id, "neatlogs_traces") or "").split(),
        costs=run_costs(ledger, run_id), reuse=reuse.provenance(ledger, run_id),
    )


# markdown ---------------------------------------------------------------------------------
def _ci(low: float, high: float) -> str:
    return f"[{low:.2f}, {high:.2f}]"


def _money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:.4f}" if x < 1 else f"${x:.2f}"


def _duration(s: float | None) -> str:
    if s is None:
        return "unfinished"
    return f"{s / 60:.1f} min" if s >= 90 else f"{s:.0f} s"


def to_markdown(r: Report) -> str:
    c = r.costs
    out = [f"# Culprit report: run `{r.run_id}`", ""]
    out += [f"**Verdict: {r.status}.** {r.summary}", ""]
    if r.culprit_sha:
        out += [f"- Culprit: `{r.culprit_sha}` {r.culprit_subject!r}", f"- Confidence: {r.confidence}"]
    out += [f"- Range: `{r.good_ref}..{r.bad_ref}` ({r.candidates or '?'} commits) in `{r.repo}`",
            f"- Victim: {r.victim}; k = {r.k}; suite {r.suite}",
            f"- Cost: {_money(c.cost_usd)} for {c.victim_runs} victim runs"
            + (f" (+{c.reused_runs} reused)" if c.reused_runs else "") + f"; wall time {_duration(c.wall_time_s)}", ""]

    out += ["## Baselines and regression gate", "",
            "| End | SHA | Passes | 95% Wilson | Screen ×1 | Reused |", "|---|---|---:|---|---:|---:|"]
    for e in (r.good, r.bad):
        if e:
            screen = f"{e.screen[0]}/{e.screen[1]}" if e.screen else "—"
            out.append(f"| {e.label} | `{e.sha[:10]}` | {e.passes}/{e.n} | {_ci(e.low, e.high)} | {screen} | {e.reused} |")
    if r.fisher_p is not None:
        verdict = "significant" if r.fisher_p < r.gate_alpha else "not significant"
        out += ["", f"One-sided Fisher exact p = {r.fisher_p:.4g} (alpha {r.gate_alpha}): {verdict}, "
                    "computed on the runs actually made."]
    if r.discriminating:
        out += ["", f"Discriminating tasks: {', '.join(f'`{t}`' for t in r.discriminating)}"]

    out += ["", "## Bisect timeline", ""]
    if r.timeline:
        out += ["| # | Pos | Commit | Subject | Passes | 95% Wilson | Threshold | Rounds | Verdict |",
                "|---:|---:|---|---|---:|---|---:|---|---|"]
        for i, ce in enumerate(r.timeline, 1):
            last = ce.last
            verdict = ce.decision + (f" ({ce.flags})" if ce.flags else "")
            out.append(
                f"| {i} | {ce.position or '?'} | `{ce.sha[:10]}` | {ce.subject.replace('|', '/')} | "
                + (f"{last.passes}/{last.n} | {_ci(last.low, last.high)} | " if last else "— | — | ")
                + (f"{ce.threshold:.2f}" if ce.threshold is not None else "—")
                + f" | {' → '.join(x.kind for x in ce.rounds) or 'install'} | **{verdict}** |")
    else:
        out.append("No commit was bisected.")

    out += ["", "## Skipped commits", ""]
    if r.skips:
        for ce in r.skips:
            tail = (ce.error or "").strip().splitlines()[-3:]
            out += [f"- `{ce.sha[:10]}` {ce.subject!r}: install failed, treated like `git bisect skip`."]
            out += [f"  > {line}" for line in tail]
    else:
        out.append("None.")

    out += ["", "## Intent", ""]
    if r.intent:
        meta = r.intent_meta
        if meta:
            out += [f"Source: {meta.get('source')}" + (f"; checkpoint `{meta['checkpoint_id']}`"
                                                        if meta.get("checkpoint_id") else "")
                    + f"; leakage filter removed {meta.get('lines_removed', 0)} lines.", ""]
        out += ["```text", r.intent.strip(), "```"]
    else:
        out.append("Not available (no single culprit).")

    out += ["", "## Diff", ""]
    if r.diff:
        out += ["```diff", r.diff.rstrip(), "```"]
        if r.diff_truncated:
            out.append(f"*{r.diff_truncated} more lines not shown.*")
    else:
        out.append("Not available.")

    out += ["", "## Trace IDs", ""]
    out += [f"- Culprit run (neatlogs, workflow `culprit`, session `{r.run_id}`): "
            + (", ".join(f"`{t}`" for t in r.culprit_traces) or "tracing was off")]
    out += [f"- Victim task runs: {r.victim_trace_count} traces"]
    for e in (r.good, r.bad):
        if e and e.trace_ids:
            out.append(f"  - {e.label} `{e.sha[:10]}`: " + ", ".join(f"`{t}`" for t in e.trace_ids))
    for ce in r.timeline:
        if ce.trace_ids:
            out.append(f"  - `{ce.sha[:10]}`: " + ", ".join(f"`{t}`" for t in ce.trace_ids))

    out += ["", "## Costs", "", "| Item | Value |", "|---|---:|",
            f"| Victim runs executed | {c.victim_runs} |", f"| … measuring the ends | {c.baseline_runs} |",
            f"| … bisecting | {c.bisect_runs} |", f"| … localising | {c.localise_runs} |",
            f"| … fixing and verifying | {c.fix_runs} |", f"| Reused from earlier runs (not paid again) | {c.reused_runs} |",
            f"| Victim cost | {_money(c.victim_cost_usd)} |", f"| Culprit LLM cost | {_money(c.llm_cost_usd)} |",
            f"| **Total** | **{_money(c.cost_usd)}** |", f"| Per victim run | {_money(c.cost_per_victim_run_usd)} |",
            f"| Wall time | {_duration(c.wall_time_s)} |"]
    if r.reuse:
        out += ["", "Reused baseline results (provenance):", ""]
        for key, sources in sorted(r.reuse.items()):
            kind, _, sha = key.rpartition(":")
            out.append(f"- {kind} `{sha[:10]}`: " + ", ".join(f"{n} from run `{src}`" for src, n in sources.items()))
    return "\n".join(out) + "\n"


# HTML -------------------------------------------------------------------------------------
_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Culprit report {{ r.run_id }}</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1c1a;--muted:#6b675f;--line:#e4e0d7;--card:#ffffff;--good:#2f7d4f;--bad:#b4402f;
--skip:#8a6d1f;--accent:#3a5fb0;--code:#f3f0ea}
@media (prefers-color-scheme:dark){:root{--bg:#161514;--fg:#ece9e2;--muted:#a19c92;--line:#34312c;--card:#1f1e1c;
--good:#6cc08e;--bad:#e88573;--skip:#d9b65a;--accent:#8fb0f0;--code:#26241f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 64px}h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:36px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.muted{color:var(--muted)}code,pre{font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:var(--code);padding:12px;border-radius:6px;overflow:auto;max-height:480px;white-space:pre}
.verdict{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;
padding:16px 18px;margin:18px 0}.verdict.found{border-left-color:var(--bad)}.verdict.no_regression{border-left-color:var(--good)}
.verdict b{font-size:17px}.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin-top:10px}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:middle}
th{font-weight:600;color:var(--muted);font-size:12.5px}td.num{text-align:right;font-variant-numeric:tabular-nums}
.GOOD{color:var(--good);font-weight:600}.BAD{color:var(--bad);font-weight:600}.SKIP{color:var(--skip);font-weight:600}
.INCONCLUSIVE{color:var(--muted);font-weight:600}svg .ci{stroke:var(--fg);stroke-width:2}
svg .axis{stroke:var(--line)}svg .t{stroke:var(--accent);stroke-width:2;stroke-dasharray:3 2}
svg .pt{fill:var(--fg)}.ci-cell{white-space:nowrap}details{margin:6px 0}summary{cursor:pointer;color:var(--accent)}
</style></head><body><main>
<h1>Culprit report</h1>
<div class="muted">run <code>{{ r.run_id }}</code> · <code>{{ r.good_ref }}..{{ r.bad_ref }}</code>
{% if r.candidates %}({{ r.candidates }} commits){% endif %} · {{ r.victim }} · k = {{ r.k }}</div>

<div class="verdict {{ r.status }}"><b>{{ r.status }}</b> · {{ r.summary }}
<div class="kv">
{% if r.culprit_sha %}<span class="muted">Culprit</span><span><code>{{ r.culprit_sha }}</code> {{ r.culprit_subject }}</span>
<span class="muted">Confidence</span><span>{{ r.confidence }}</span>{% endif %}
<span class="muted">Suite</span><span><code>{{ r.suite }}</code></span>
<span class="muted">Cost</span><span>{{ money(c.cost_usd) }} for {{ c.victim_runs }} victim runs{% if c.reused_runs %}
 (+{{ c.reused_runs }} reused){% endif %} · {{ duration(c.wall_time_s) }}</span>
</div></div>

<h2>Baselines and regression gate</h2>
<div class="wrap"><table><tr><th>End</th><th>SHA</th><th>Passes</th><th>95% Wilson</th><th></th><th>Screen ×1</th><th>Reused</th></tr>
{% for e in ends %}<tr><td>{{ e.label }}</td><td><code>{{ e.sha[:10] }}</code></td><td class="num">{{ e.passes }}/{{ e.n }}</td>
<td>{{ ci(e.low, e.high) }}</td><td>{{ bar(e.low, e.high, e.passes / e.n, None) }}</td>
<td class="num">{% if e.screen %}{{ e.screen[0] }}/{{ e.screen[1] }}{% else %}—{% endif %}</td><td class="num">{{ e.reused }}</td></tr>{% endfor %}
</table></div>
{% if r.fisher_p is not none %}<p>One-sided Fisher exact p = <b>{{ '%.4g' % r.fisher_p }}</b> (alpha {{ r.gate_alpha }}):
{{ 'significant' if r.fisher_p < r.gate_alpha else 'not significant' }}, computed on the runs actually made.</p>{% endif %}
{% if r.discriminating %}<p class="muted">Discriminating tasks: {% for t in r.discriminating %}<code>{{ t }}</code>{{ ', ' if not loop.last }}{% endfor %}</p>{% endif %}

<h2>Bisect timeline</h2>
{% if r.timeline %}<div class="wrap"><table><tr><th>#</th><th>Pos</th><th>Commit</th><th>Subject</th><th>Passes</th>
<th>95% Wilson vs threshold</th><th>Rounds</th><th>Verdict</th></tr>
{% for ce in r.timeline %}{% set last = ce.last %}<tr><td class="num">{{ loop.index }}</td><td class="num">{{ ce.position or '?' }}</td>
<td><code>{{ ce.sha[:10] }}</code></td><td>{{ ce.subject }}</td>
<td class="num">{% if last %}{{ last.passes }}/{{ last.n }}{% else %}—{% endif %}</td>
<td class="ci-cell">{% if last %}{{ bar(last.low, last.high, last.passes / last.n, ce.threshold) }} <span class="muted">{{ ci(last.low, last.high) }}
{% if ce.threshold is not none %} t={{ '%.2f' % ce.threshold }}{% endif %}</span>{% else %}<span class="muted">install failed</span>{% endif %}</td>
<td>{% for x in ce.rounds %}{{ x.kind }}{{ ' → ' if not loop.last }}{% endfor %}</td>
<td class="{{ ce.decision }}">{{ ce.decision }}{% if ce.flags %} <span class="muted">({{ ce.flags }})</span>{% endif %}</td></tr>{% endfor %}
</table></div>
<p class="muted">Bars: 95% Wilson interval (line), pass rate (dot), threshold (dashed). GOOD needs the whole interval above
the threshold, BAD the whole interval below it.</p>{% else %}<p>No commit was bisected.</p>{% endif %}

<h2>Skipped commits</h2>
{% if r.skips %}{% for ce in r.skips %}<p><code>{{ ce.sha[:10] }}</code> {{ ce.subject }}: install failed, treated like
<code>git bisect skip</code>.</p>{% if ce.error %}<details><summary>install log tail</summary><pre>{{ ce.error[-1500:] }}</pre></details>{% endif %}
{% endfor %}{% else %}<p>None.</p>{% endif %}

<h2>Intent</h2>
{% if r.intent %}{% if r.intent_meta %}<p class="muted">Source: {{ r.intent_meta.source }}{% if r.intent_meta.checkpoint_id %};
checkpoint <code>{{ r.intent_meta.checkpoint_id }}</code>{% endif %}; leakage filter removed {{ r.intent_meta.lines_removed }} lines.</p>{% endif %}
<pre>{{ r.intent.strip() }}</pre>{% else %}<p>Not available (no single culprit).</p>{% endif %}

<h2>Diff</h2>
{% if r.diff %}<pre>{{ r.diff.rstrip() }}</pre>{% if r.diff_truncated %}<p class="muted">{{ r.diff_truncated }} more lines not shown.</p>{% endif %}
{% else %}<p>Not available.</p>{% endif %}

<h2>Trace IDs</h2>
<p>Culprit run (neatlogs workflow <code>culprit</code>, session <code>{{ r.run_id }}</code>):
{% for t in r.culprit_traces %}<code>{{ t }}</code>{{ ', ' if not loop.last }}{% else %}tracing was off{% endfor %}</p>
<details><summary>{{ r.victim_trace_count }} victim task-run traces</summary><ul>
{% for e in ends %}{% if e.trace_ids %}<li>{{ e.label }} <code>{{ e.sha[:10] }}</code>: {% for t in e.trace_ids %}<code>{{ t }}</code> {% endfor %}</li>{% endif %}{% endfor %}
{% for ce in r.timeline %}{% if ce.trace_ids %}<li><code>{{ ce.sha[:10] }}</code>: {% for t in ce.trace_ids %}<code>{{ t }}</code> {% endfor %}</li>{% endif %}{% endfor %}
</ul></details>

<h2>Costs</h2>
<div class="wrap"><table>
<tr><td>Victim runs executed</td><td class="num">{{ c.victim_runs }}</td></tr>
<tr><td>… measuring the ends</td><td class="num">{{ c.baseline_runs }}</td></tr>
<tr><td>… bisecting</td><td class="num">{{ c.bisect_runs }}</td></tr>
<tr><td>… localising</td><td class="num">{{ c.localise_runs }}</td></tr>
<tr><td>… fixing and verifying</td><td class="num">{{ c.fix_runs }}</td></tr>
<tr><td>Reused from earlier runs (not paid again)</td><td class="num">{{ c.reused_runs }}</td></tr>
<tr><td>Victim cost</td><td class="num">{{ money(c.victim_cost_usd) }}</td></tr>
<tr><td>Culprit LLM cost</td><td class="num">{{ money(c.llm_cost_usd) }}</td></tr>
<tr><td><b>Total</b></td><td class="num"><b>{{ money(c.cost_usd) }}</b></td></tr>
<tr><td>Per victim run</td><td class="num">{{ money(c.cost_per_victim_run_usd) }}</td></tr>
<tr><td>Wall time</td><td class="num">{{ duration(c.wall_time_s) }}</td></tr>
</table></div>
{% if r.reuse %}<p>Reused baseline results (provenance):</p><ul>{% for key, sources in r.reuse|dictsort %}
<li>{{ key.rpartition(':')[0] }} <code>{{ key.rpartition(':')[2][:10] }}</code>: {% for src, n in sources.items() %}{{ n }} from run
<code>{{ src }}</code>{{ ', ' if not loop.last }}{% endfor %}</li>{% endfor %}</ul>{% endif %}
</main></body></html>
"""


def _bar(low: float, high: float, rate: float, threshold: float | None) -> str:
    w, pad = 160, 4
    x = lambda v: pad + v * (w - 2 * pad)  # noqa: E731
    t = f'<line class="t" x1="{x(threshold):.1f}" y1="2" x2="{x(threshold):.1f}" y2="16"/>' if threshold is not None else ""
    return (f'<svg width="{w}" height="18" role="img" aria-label="Wilson interval {low:.2f} to {high:.2f}">'
            f'<line class="axis" x1="{pad}" y1="9" x2="{w - pad}" y2="9"/>{t}'
            f'<line class="ci" x1="{x(low):.1f}" y1="9" x2="{x(high):.1f}" y2="9"/>'
            f'<circle class="pt" cx="{x(rate):.1f}" cy="9" r="3.5"/></svg>')


def to_html(r: Report) -> str:
    from markupsafe import Markup

    env = Environment(autoescape=True)
    env.globals.update(ci=_ci, money=_money, duration=_duration,
                       bar=lambda *a: Markup(_bar(*a)))  # noqa: S704 - numbers only
    return env.from_string(_HTML).render(r=r, c=r.costs, ends=[e for e in (r.good, r.bad) if e])


def write(ledger: Ledger, run_id: str, out_dir: Path) -> tuple[Path, Path]:
    report = collect(ledger, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    md, html = out_dir / f"report-{run_id}.md", out_dir / f"report-{run_id}.html"
    md.write_text(to_markdown(report))
    html.write_text(to_html(report))
    return md, html
