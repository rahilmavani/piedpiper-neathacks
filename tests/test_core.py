from pathlib import Path

import pytest

from culprit.bisect import Verdict, bisect, probe_order
from culprit.entire import intent_line, leak_filter
from culprit.ledger import Ledger, TaskRun
from culprit.stats import Decision, decide, wilson


# Wilson decision ---------------------------------------------------------------
def test_wilson_matches_reference_values():
    low, high = wilson(8, 10)
    assert low == pytest.approx(0.4902, abs=1e-4)
    assert high == pytest.approx(0.9433, abs=1e-4)
    assert wilson(0, 0) == (0.0, 1.0)


def test_decide_good_bad_inconclusive():
    assert decide(24, 24, 0.5)[0] is Decision.GOOD
    assert decide(0, 24, 0.5)[0] is Decision.BAD
    assert decide(3, 5, 0.5)[0] is Decision.INCONCLUSIVE


def test_wilson_rejects_impossible_counts():
    with pytest.raises(ValueError):
        wilson(4, 3)


# Bisect controller ---------------------------------------------------------------
def make_classifier(first_bad: int, skips: set[int] = frozenset()):
    calls = []

    def classify(sha: str) -> Verdict:
        idx = int(sha)
        calls.append(idx)
        if idx in skips:
            return Verdict.SKIP
        return Verdict.BAD if idx >= first_bad else Verdict.GOOD

    return classify, calls


@pytest.mark.parametrize("first_bad", range(14))
def test_bisect_finds_every_position(first_bad):
    shas = [str(i) for i in range(14)]
    classify, calls = make_classifier(first_bad)
    result = bisect(shas, classify)
    assert result.first_bad == str(first_bad)
    assert len(calls) <= 4  # ceil(log2(14))


def test_bisect_skip_tests_neighbour_and_still_finds_culprit():
    shas = [str(i) for i in range(14)]
    classify, calls = make_classifier(first_bad=9, skips={6})
    result = bisect(shas, classify)
    assert calls[0] == 6 and calls[1] == 7  # midpoint skipped → nearest neighbour
    assert result.first_bad == "9"


def test_bisect_reports_range_when_skip_sits_on_boundary():
    shas = [str(i) for i in range(10)]
    classify, _ = make_classifier(first_bad=5, skips={4, 5})
    result = bisect(shas, classify)
    assert result.first_bad is None
    assert result.suspects == ["4", "5", "6"]  # 6 is BAD; 4 and 5 are unknown


def test_probe_order_alternates_around_midpoint():
    assert probe_order(-1, 7) == [3, 4, 2, 5, 1, 6, 0]


# Ledger idempotence ----------------------------------------------------------------
def test_ledger_writes_are_idempotent(tmp_path: Path):
    ledger = Ledger(tmp_path / "l.sqlite")
    run_id = ledger.create_run("repo", "g", "b", "h", "{}")
    step = ledger.open_step(run_id, "bisect", "abc")
    assert ledger.open_step(run_id, "bisect", "abc") == step
    tr = TaskRun("t1", 0, True, 0.01, 10.0, 5, 5, "trace")
    ledger.record_task_run(step, tr)
    ledger.record_task_run(step, tr)
    assert len(ledger.task_runs(step)) == 1
    assert ledger.run_cost(run_id) == pytest.approx(0.01)


# Leakage filter ----------------------------------------------------------------------
def test_leak_filter_strips_labels_and_refs():
    text = "\n".join([
        "Make it faster",
        "on branch hist/b",
        "this is R1",
        "the Scenario mapping",
        "found the regression",
        "use --seed 3",
        "branch exp-x merged",
        "drop RR1 marker",
        "keep this line",
    ])
    kept, removed = leak_filter(text, ["exp-x"])
    assert kept.splitlines() == ["Make it faster", "drop RR1 marker", "keep this line"]
    assert removed == 6


# Entire intent parsing ------------------------------------------------------------
def explain_text(intent: str) -> str:
    return f"● Checkpoint 01ABCDEFGHJKMNPQRSTVWXYZ00\n## Intent\n\n{intent}\n\n## Summary\n\n*Not generated yet.*\n"


def test_intent_line_keeps_real_prompts_and_drops_placeholders():
    assert intent_line(explain_text("RefundDesk is too slow. Make it faster.")) == "RefundDesk is too slow. Make it faster."
    assert intent_line(explain_text("<task-notification>")) == ""
    assert intent_line(explain_text("*(no prompt recorded)*")) == ""
    assert intent_line("no intent section at all") == ""
