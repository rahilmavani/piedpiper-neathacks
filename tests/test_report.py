"""M6: `culprit report` (markdown + static HTML) and `culprit export-costs --format csv`, on the fixture."""

import csv
import importlib
import io
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit.ledger import Ledger  # noqa: E402


@pytest.fixture()
def finished(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two fixture runs in one ledger: the second reuses the first one's baselines."""
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    repo = build(tmp_path / "victim", commits=14, breaks_at=10, unbuildable_at=7, noisy_from=9, noisy_pass=0.6)
    db = tmp_path / "l.sqlite"
    ids = []
    for _ in range(2):
        cfg = culprit.config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main")
        orch = culprit.orchestrator.Orchestrator(Ledger(db), cfg, log=lambda _: None)
        run_id = orch.start()
        orch.run(run_id)
        ids.append(run_id)
    orch.ledger.put_artifact(ids[0], "neatlogs_traces", "3e8d50b4584b831185c65a33007c7533")
    culprit_sha = subprocess.check_output(
        ["git", "-C", str(repo), "log", "--format=%H", "--grep=speed up tool handling"], text=True).strip()
    return db, ids, culprit_sha


def test_report_has_every_section(finished, tmp_path: Path):
    from culprit.report import collect, to_markdown

    db, (first, _), culprit_sha = finished
    r = collect(Ledger(db), first)
    md = to_markdown(r)
    assert r.status == "found" and r.culprit_sha == culprit_sha
    assert f"`{culprit_sha}` 'speed up tool handling'" in md
    for heading in ("## Baselines and regression gate", "## Bisect timeline", "## Skipped commits", "## Intent",
                    "## Diff", "## Trace IDs", "## Costs"):
        assert heading in md
    # Timeline: test order, Wilson intervals, the skip, the low-confidence resampled commit, the culprit.
    assert [c.decision for c in r.timeline][0] == "SKIP" and "pin requests" in r.timeline[0].subject
    assert any(c.flags == "low_confidence" and len(c.rounds) == 3 for c in r.timeline)
    assert r.timeline[-1].sha == culprit_sha and r.timeline[-1].decision == "BAD"
    for c in r.timeline[1:]:
        assert c.last and c.last.low <= c.last.passes / c.last.n <= c.last.high and c.threshold is not None
    assert "install failed, treated like `git bisect skip`" in md
    assert "fallback" in r.intent_meta["source"] and "speed up tool handling" in r.intent
    assert "diff --git" not in r.intent and "diff --git" in r.diff  # the diff has its own section
    assert "`3e8d50b4584b831185c65a33007c7533`" in md
    # Gate numbers are the runs actually made (staged baseline: fewer than 10 tasks × 3).
    assert r.good.n < 30 and r.good.n == r.bad.n and r.good.screen == (r.good.screen[0], 10)
    assert f"| {r.costs.victim_runs} |" in md


def test_report_shows_reuse_provenance_and_unpaid_runs(finished):
    from culprit.report import collect, to_markdown

    db, (first, second), _ = finished
    r = collect(Ledger(db), second)
    assert r.costs.baseline_runs == 0 and r.costs.reused_runs == r.good.n + r.bad.n
    assert r.good.reused == r.good.n
    md = to_markdown(r)
    assert f"from run `{first}`" in md and "Reused baseline results (provenance)" in md


class _Tags(HTMLParser):
    VOID = {"meta", "br", "circle", "line", "img", "hr", "input", "link"}

    def __init__(self):
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> with open {self.stack[-3:]}")
        else:
            self.stack.pop()


def test_cli_report_writes_balanced_static_html(finished, tmp_path: Path):
    from culprit.cli import app

    db, (first, _), culprit_sha = finished
    out = tmp_path / "reports"
    result = CliRunner().invoke(app, ["report", first, "--db", str(db), "--out", str(out)])
    assert result.exit_code == 0, result.output
    html = (out / f"report-{first}.html").read_text()
    assert (out / f"report-{first}.md").exists()
    assert culprit_sha in html and "<svg" in html and "<script" not in html and "http" not in html.split("</style>")[0]
    parser = _Tags()
    parser.feed(html)
    assert parser.errors == [] and parser.stack == []
    assert "&lt;" not in html.split("<h2>Diff</h2>")[0].split("<h2>Intent</h2>")[0]  # nothing double-escaped


def test_export_costs_csv(finished):
    from culprit.cli import app
    from culprit.costs import run_costs

    db, (first, second), _ = finished
    result = CliRunner().invoke(app, ["export-costs", "--format", "csv", "--db", str(db)])
    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(io.StringIO(result.output)))
    assert [r["run_id"] for r in rows] == [first, second]
    ledger = Ledger(db)
    for r in rows:
        c = run_costs(ledger, r["run_id"])
        assert int(r["victim_runs"]) == c.victim_runs == sum(
            int(r[f"{stage}_runs"]) for stage in ("baseline", "bisect", "localise", "fix", "other"))
        assert float(r["cost_usd"]) == pytest.approx(ledger.run_cost(r["run_id"]))
        assert float(r["wall_time_s"]) >= 0
    assert sum(float(r["cost_usd"]) for r in rows) == pytest.approx(ledger.total_cost())
    assert int(rows[1]["reused_runs"]) > 0

    bad = CliRunner().invoke(app, ["export-costs", "--format", "xlsx", "--db", str(db)])
    assert bad.exit_code == 2


def test_timeline_ignores_localise_and_fix_steps(finished):
    """Localiser reverts run at the culprit commit and verification at the ends; neither is a bisect row."""
    from culprit import report
    from culprit.ledger import TaskRun

    db, ids, culprit_sha = finished
    ledger = Ledger(db)
    run = ledger.get_run(ids[0])
    before = report.collect(ledger, ids[0])
    culprit_row = next(c for c in before.timeline if c.sha == culprit_sha)

    for kind, sha in (("localise:h1", culprit_sha), ("verify:heldout", run["good_sha"]), ("fix:1", run["bad_sha"])):
        step = ledger.open_step(ids[0], kind, sha)
        for rep in range(3):
            ledger.record_task_run(step, TaskRun("t01", rep, True, 0.001, 1.0, 1, 1, None))
        ledger.close_step(step, "done", decision="GOOD", n=3, passes=3)

    after = report.collect(ledger, ids[0])
    assert [c.sha for c in after.timeline] == [c.sha for c in before.timeline]
    row = next(c for c in after.timeline if c.sha == culprit_sha)
    assert row.decision == culprit_row.decision == "BAD"
    assert [r.kind for r in row.rounds] == [r.kind for r in culprit_row.rounds]
