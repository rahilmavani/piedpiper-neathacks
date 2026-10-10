"""Localiser (PRD §8.3): hunk splitting, LLM ranking behind a fake, the revert search, and fixture runs."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit import finished, gitops, llm, localise  # noqa: E402
from culprit.bisect import Verdict  # noqa: E402
from culprit.entire import ref_names  # noqa: E402
from culprit.ledger import Ledger  # noqa: E402

DIFF = """\
diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -1,4 +1,4 @@
 one
-two
+TWO
 three
 four
@@ -20 +20,2 @@ def f():
 keep
+added
diff --git a/new.txt b/new.txt
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/new.txt
@@ -0,0 +1 @@
+hello
\\ No newline at end of file
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
index 4444444..0000000
--- a/gone.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-x
-y
diff --git a/logo.png b/logo.png
index 5555555..6666666 100644
Binary files a/logo.png and b/logo.png differ
"""


def test_split_hunks():
    hunks = localise.split_hunks(DIFF)
    assert [(h.id, h.file) for h in hunks] == [(1, "a.py"), (2, "a.py"), (3, "new.txt"), (4, "gone.txt")]
    assert [h.where for h in hunks] == ["a.py:2", "a.py:21", "new.txt:1", "gone.txt: lines 1-2 removed"]
    assert hunks[1].body.startswith("@@ -20 +20,2 @@") and (hunks[1].old_len, hunks[1].new_len) == (1, 2)
    assert hunks[2].body.endswith("\\ No newline at end of file\n")
    assert hunks[3].header.startswith("diff --git a/gone.txt") and "deleted file mode" in hunks[3].header


def test_patch_for_groups_hunks_by_file():
    h = localise.split_hunks(DIFF)
    patch = localise.patch_for([h[1], h[2], h[0]])
    assert patch.count("diff --git a/a.py") == 1 and patch.count("diff --git a/new.txt") == 1
    assert patch.index("@@ -1,4") < patch.index("@@ -20 +20,2")


# ranking ------------------------------------------------------------------------------------
def fake_model(monkeypatch, reply: dict):
    prompts = []

    def complete(system, messages, max_tokens):
        prompts.append(messages[0]["content"])
        return json.dumps(reply), llm.Usage("fake-model", 100, 20, 0.0001)

    monkeypatch.setattr(llm, "_complete", complete)
    return prompts


EVIDENCE = [finished.TaskEvidence("t02", (3, 3), (0, 3), ("KeyError: 'x'",), '{"message": "refund"}')]


def test_rank_uses_the_model_order_and_completes_it(monkeypatch):
    hunks = localise.split_hunks(DIFF)
    prompts = fake_model(monkeypatch, {"ranking": [
        {"hunk": 3, "reason": "changes output"}, {"hunk": 99, "reason": "no such hunk"},
        {"hunk": 3, "reason": "duplicate"}, {"hunk": 1, "reason": "renames a value"},
    ]})
    ranking = localise.rank(hunks, "Intent: make it faster", EVIDENCE)
    assert ranking.order == [3, 1, 2, 4] and ranking.source == "llm"
    assert ranking.reasons == {3: "changes output", 1: "renames a value"}
    assert ranking.reply is not None and ranking.reply.cost_usd == pytest.approx(0.0001)
    prompt = prompts[0]
    assert "make it faster" in prompt and "t02: passed 3/3 before the commit, 0/3 after" in prompt
    assert "KeyError" in prompt and "### Hunk 4: gone.txt: lines 1-2 removed" in prompt


def test_rank_falls_back_to_diff_order_without_a_model():
    ranking = localise.rank(localise.split_hunks(DIFF), "", [])  # conftest blocks model calls
    assert ranking.order == [1, 2, 3, 4] and ranking.source.startswith("fallback: ") and ranking.reply is None


# search -------------------------------------------------------------------------------------
def verdicts(good: set[tuple[int, ...]], skip: set[tuple[int, ...]] = frozenset()):
    calls = []

    def verdict(ids):
        calls.append(ids)
        return Verdict.SKIP if ids in skip else Verdict.GOOD if ids in good else Verdict.BAD

    return verdict, calls


def test_search_stops_at_the_first_single_hunk_that_flips():
    verdict, calls = verdicts({(5,)})
    loc = localise.search([2, 5, 1, 4], verdict)
    assert (loc.status, loc.hunks, calls) == ("hunk", [5], [(2,), (5,)])


def test_search_tries_pairs_of_the_top_n_then_gives_the_whole_commit():
    verdict, calls = verdicts({(1, 3)}, skip={(2,)})
    loc = localise.search([2, 1, 3, 4], verdict, top_n=3, max_pairs=3)
    assert (loc.status, loc.hunks) == ("pair", [1, 3])
    assert calls == [(2,), (1,), (3,), (2, 1), (2, 3), (1, 3)]

    verdict, calls = verdicts(set())
    loc = localise.search([2, 1, 3, 4], verdict, top_n=3, max_pairs=1)
    assert (loc.status, loc.hunks, len(calls)) == ("whole_commit", [2, 1, 3, 4], 4)


def test_search_needs_no_runs_for_zero_or_one_hunk():
    verdict, calls = verdicts(set())
    assert localise.search([], verdict).status == "no_hunks"
    assert (localise.search([7], verdict).status, calls) == ("single_hunk", [])


# end to end on the fixture: bisect first, then `culprit localise` on the finished run -------------
@pytest.fixture()
def mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.finished
    import culprit.localise
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator, culprit.finished,
                culprit.localise):
        importlib.reload(mod)
    return culprit.orchestrator, culprit.config, culprit.localise


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def bisected(mods, repo: Path, db: Path):
    orchestrator, config, _ = mods
    orch = orchestrator.Orchestrator(Ledger(db), config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main"),
                                     log=lambda _: None)
    run_id = orch.start()
    outcome = orch.run(run_id)
    assert outcome.status == "found"
    return orch.ledger, run_id, outcome


def task_run_count(ledger: Ledger) -> int:
    return ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]


def test_localiser_rejects_the_decoy_and_finds_the_responsible_hunk(mods, tmp_path: Path, monkeypatch):
    loc_mod = mods[2]
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None, break_hunks="multi")
    ledger, run_id, outcome = bisected(mods, repo, tmp_path / "l.sqlite")
    culprit = outcome.result.first_bad
    hunks = {h.where: h.id for h in localise.split_hunks(gitops.diff(repo, culprit))}
    decoy, responsible = hunks["refunddesk/agent.py:23"], hunks["refunddesk/agent.py:3"]
    # The model is wrong on purpose: it ranks the harmless timeout change first.
    prompts = fake_model(monkeypatch, {"ranking": [{"hunk": decoy, "reason": "timeouts"},
                                                   {"hunk": responsible, "reason": "pass rate"}]})
    before = task_run_count(ledger)
    loc, text = loc_mod.localise_run(ledger, run_id, log=lambda _: None)

    assert (loc.status, loc.hunks) == ("hunk", [responsible])
    assert text == f"hunk {responsible} (refunddesk/agent.py:3)"
    record = json.loads(ledger.get_artifact(run_id, "localisation"))
    assert record["commit"] == culprit and record["summary"] == text
    assert record["tried"] == [{"hunks": [decoy], "verdict": "BAD"}, {"hunks": [responsible], "verdict": "GOOD"}]
    assert hunks["evals/t01.json:1"] not in record["ranking"]["order"]  # the pinned suite replaces evals/
    assert record["ranking"]["source"] == "llm"
    # conftest blocks neatlogs readback: the stage logs it and ranks without traces.
    assert record["ranking"]["traces"]["note"].startswith("read 0/3 failing traces from neatlogs; readback failed")
    assert record["ranking"]["traces"]["trace_ids"] == [] and "Tool calls in failing runs" not in prompts[0]
    calls = ledger.conn.execute("SELECT purpose, model, cost_usd FROM llm_calls").fetchall()
    assert [tuple(c) for c in calls] == [("localise_rank", "fake-model", 0.0001)]
    assert task_run_count(ledger) == before + 2 * 15  # two reverts × 5 telling tasks × k=3, baselines reused

    # Leakage: the prompt carries the diff, intent and task evidence, never a branch or tag name.
    assert len(prompts) == 1 and "RETRY_PASS" in prompts[0]
    assert not any(ref in prompts[0] for ref in ref_names(repo))

    # The run itself is untouched, and running again reuses every revert and the stored ranking.
    row = ledger.get_run(run_id)
    assert (row["status"], row["culprit_sha"], row["summary"]) == ("found", culprit, outcome.summary)
    again, _ = loc_mod.localise_run(ledger, run_id, log=lambda _: None)
    assert again.hunks == [responsible] and len(prompts) == 1 and task_run_count(ledger) == before + 30


def test_localiser_falls_back_to_a_pair_when_no_single_revert_flips(mods, tmp_path: Path):
    from typer.testing import CliRunner

    from culprit.cli import app

    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None, break_hunks="pair")
    db = tmp_path / "l.sqlite"
    ledger, run_id, _ = bisected(mods, repo, db)
    result = CliRunner().invoke(app, ["localise", run_id, "--db", str(db)])  # no model: diff-order fallback

    assert result.exit_code == 0, result.output
    assert "responsible: hunk pair" in result.output
    record = json.loads(ledger.get_artifact(run_id, "localisation"))
    assert record["ranking"]["source"].startswith("fallback: ")
    assert record["status"] == "pair"
    assert sorted(h["where"] for h in record["hunks"]) == ["refunddesk/agent.py:13", "refunddesk/agent.py:3"]
    assert [t["verdict"] for t in record["tried"]][-1] == "GOOD"
    assert all(t["verdict"] == "BAD" for t in record["tried"] if len(t["hunks"]) == 1)


def test_localise_needs_a_found_run(mods, tmp_path: Path):
    orchestrator, config, loc_mod = mods
    repo = build(tmp_path / "victim", commits=4, breaks_at=99, unbuildable_at=None)
    orch = orchestrator.Orchestrator(Ledger(tmp_path / "l.sqlite"),
                                     config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main"),
                                     log=lambda _: None)
    run_id = orch.start()
    assert orch.run(run_id).status == "no_regression"
    with pytest.raises(finished.StageError, match="no_regression"):
        loc_mod.localise_run(orch.ledger, run_id, log=lambda _: None)


def test_ranking_prompt_carries_failing_runs_tool_calls_from_neatlogs(mods, tmp_path: Path, monkeypatch):
    from culprit import readback

    loc_mod = mods[2]
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None, break_hunks="multi")
    ledger, run_id, outcome = bisected(mods, repo, tmp_path / "l.sqlite")
    asked = []

    def cli(*args, timeout_s):
        asked.append(args[2])
        tools = [("lookup_order", {"order_id": "A1"}, "failed"), ("lookup_order", {"order_id": "A1"}, "ok"),
                 ("issue_refund", {"order_id": "A1", "note": "good-v1.0"}, "ok")]
        return {"spans": [{"spanType": "TOOL", "spanName": n, "startedAt": f"{i}", "status": "OK",
                           "input": {"preview": json.dumps(a)}, "output": {"preview": json.dumps({"status": st})}}
                          for i, (n, a, st) in enumerate(tools)]}

    monkeypatch.setattr(readback, "cli", cli)
    prompts = fake_model(monkeypatch, {"ranking": []})
    loc_mod.localise_run(ledger, run_id, log=lambda _: None)

    culprit_failures = {r.trace_id for step in ledger.steps(run_id) if step["commit_sha"] == outcome.result.first_bad
                        for r in ledger.task_runs(step["step_id"]).values() if not r.passed}
    assert len(asked) == 3 and set(asked) <= culprit_failures  # at most 3 failing runs at the culprit
    assert "## Tool calls in failing runs after the commit (from their neatlogs traces)" in prompts[0]
    assert '1. lookup_order {"order_id": "A1"} → failed' in prompts[0]
    assert "issue_refund" not in prompts[0].split("## Tool calls")[1].split("## Hunks")[0]  # carried a ref name
    traces = json.loads(ledger.get_artifact(run_id, "localisation"))["ranking"]["traces"]
    assert traces["trace_ids"] == asked and traces["lines_removed"] == 3
