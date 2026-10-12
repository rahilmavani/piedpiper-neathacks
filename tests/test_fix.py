"""Fixer and Verifier: edits → patch, the three gates, and `culprit fix` on the fixture."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit import llm  # noqa: E402
from culprit.entire import ref_names  # noqa: E402
from culprit.fix import Edit, edits_to_patch, gates  # noqa: E402
from culprit.ledger import Ledger, TaskRun  # noqa: E402


# edits → patch ---------------------------------------------------------------------------------
def test_edits_become_a_patch_git_can_apply(tmp_path: Path):
    files = {"a.py": "x = 1\ny = 2\n", "b.py": "no newline"}
    patch = edits_to_patch(files, [Edit(file="a.py", old="y = 2", new="y = 3"),
                                   Edit(file="b.py", old="no newline", new="still none")], {"a.py", "b.py"})
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "apply", "-"], cwd=tmp_path, input=patch, text=True, check=True)
    assert (tmp_path / "a.py").read_text() == "x = 1\ny = 3\n"
    assert (tmp_path / "b.py").read_text() == "still none"


@pytest.mark.parametrize(("edit", "message"), [
    (Edit(file="evals/t.json", old="x", new="y"), "not one of the files"),
    (Edit(file="a.py", old="z = 9", new="z = 1"), "occurs 0 times"),
    (Edit(file="a.py", old="= ", new="=  "), "occurs 2 times"),
    (Edit(file="a.py", old="", new="w = 0\n"), "occurs 0 times"),
    (Edit(file="a.py", old="x = 1", new="x = 1"), "change nothing"),
])
def test_edits_that_cannot_apply_are_rejected(edit, message):
    with pytest.raises(ValueError, match=message):
        edits_to_patch({"a.py": "x = 1\ny = 2\n"}, [edit], {"a.py"})


# gates ---------------------------------------------------------------------------------------
def runs(spec, latency=100.0):
    return [TaskRun(t, i, p, 0.001, latency, 10, 5, None) for t, ps in spec.items() for i, p in enumerate(ps)]


GOOD = runs({"a": [True] * 3, "b": [True] * 3, "c": [True, True, False]})


def test_gates_pass_a_fix_that_restores_quality_and_keeps_the_gain():
    g = gates(GOOD, runs({"a": [False] * 3, "b": [False] * 3, "c": [True] * 3}, 50.0),
              runs({"a": [True] * 3, "b": [True] * 3, "c": [True] * 3}, 52.0), "latency", 0.10)
    assert g.verified and g.quality and g.gain and not g.new_failures and g.failures() == []


def test_gates_catch_lost_gain_lost_quality_and_new_failures():
    bad = runs({"a": [False] * 3, "b": [False] * 3, "c": [True] * 3}, 50.0)
    slow = gates(GOOD, bad, runs({"a": [True] * 3, "b": [True] * 3, "c": [True] * 3}, 100.0), "latency", 0.10)
    assert not slow.verified and slow.gain is False and "intended gain lost" in slow.failures()[0]
    broken = gates(GOOD, bad, runs({"a": [False] * 3, "b": [False] * 3, "c": [True, False, False]}, 50.0), "none", 0.1)
    assert not broken.quality and broken.gain is None and broken.new_failures == ["a", "b"]
    assert any("always fail: a, b" in f for f in broken.failures())
    # The quality gate: the fix's interval only has to reach the good one's, so 4/9 vs 8/9 passes.
    lenient = gates(GOOD, bad, runs({"a": [False] * 3, "b": [True, False, False], "c": [True] * 3}), "none", 0.1)
    assert lenient.quality and lenient.new_failures == ["a"] and not lenient.verified


def test_gates_say_when_the_commit_never_delivered_its_gain():
    # The real hero run: "make it faster" left the agent no faster (7086 vs 7138 ms median).
    bad = runs({"a": [False] * 3, "b": [False] * 3, "c": [True] * 3}, 7138.0)
    g = gates(runs({"a": [True] * 3, "b": [True] * 3, "c": [True] * 3}, 7086.0), bad,
              runs({"a": [True] * 3, "b": [True] * 3, "c": [True] * 3}, 7100.0), "latency", 0.10)
    assert g.verified and g.gain is True and g.gain_at_bad is False
    assert g.latency_ms == {"good": 7086.0, "bad": 7138.0, "fix": 7100.0}
    assert g.baselines_line() == "median latency per run: good 7086 ms, bad 7138 ms, fix 7100 ms"
    assert g.gain_note() == ("the commit's latency gain is not visible: mean latency good 7086 vs bad 7138, "
                             "so the gain gate passes trivially")

    faster = gates(GOOD, runs({"a": [False] * 3, "b": [False] * 3, "c": [True] * 3}, 50.0),
                   runs({"a": [True] * 3, "b": [True] * 3, "c": [True] * 3}, 52.0), "tokens", 0.10)
    assert faster.gain_at_bad is False and "mean tokens: good 15, bad 15, fix 15" in faster.baselines_line()
    assert gates(GOOD, runs({"a": [True] * 9}, 50.0), runs({"a": [True] * 9}, 50.0), "latency", 0.1).gain_at_bad
    assert gates(GOOD, GOOD, GOOD, "none", 0.1).gain_note() == ""


def test_gates_without_a_measurable_metric_do_not_judge_the_gain():
    fix = runs({"a": [True] * 3, "b": [True] * 3, "c": [True] * 3})
    assert gates(GOOD, GOOD, fix, "none", 0.1).gain is None
    no_tokens = [TaskRun(r.task_id, r.repetition, r.passed, None, None, None, None, None) for r in fix]
    assert gates(GOOD, GOOD, no_tokens, "tokens", 0.1).gain is None


# end to end on the fixture: bisect → localise → fix --------------------------------------------
@pytest.fixture()
def mods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.finished
    import culprit.fix
    import culprit.localise
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator, culprit.finished,
                culprit.localise, culprit.fix):
        importlib.reload(mod)
    return culprit


def localised(c, tmp_path: Path):
    """A found and localised run on the multi-hunk fixture: the culprit also made the agent faster."""
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None, break_hunks="multi")
    ledger = Ledger(tmp_path / "l.sqlite")
    orch = c.orchestrator.Orchestrator(ledger, c.config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main"),
                                       log=lambda _: None)
    run_id = orch.start()
    assert orch.run(run_id).status == "found"
    loc, _ = c.localise.localise_run(ledger, run_id, log=lambda _: None)  # no model: diff order
    assert loc.status == "hunk"
    return repo, ledger, run_id


def fake_model(monkeypatch, proposals: list[dict]):
    prompts = []

    def complete(system, messages, max_tokens):
        prompts.append(messages[0]["content"])
        return json.dumps(proposals[len(prompts) - 1]), llm.Usage("fake-model", 200, 50, 0.0002)

    monkeypatch.setattr(llm, "_complete", complete)
    return prompts


def proposal(*edits, gain="latency"):
    return {"intended_gain": gain, "gain_reason": "faster tool handling", "explanation": "restore the pass rate",
            "edits": [{"file": "refunddesk/agent.py", "old": old, "new": new} for old, new in edits]}


RESTORE = ("RETRY_PASS = 0.05", "RETRY_PASS = 0.95")
UNDO_SPEEDUP = ("TOOL_TIMEOUT_S = 10", "TOOL_TIMEOUT_S = 30")


def test_fix_is_verified_on_the_suite_and_heldout_tasks(mods, tmp_path: Path, monkeypatch):
    repo, ledger, run_id = localised(mods, tmp_path)
    prompts = fake_model(monkeypatch, [proposal(RESTORE)])
    result = mods.fix.fix_run(ledger, run_id, log=lambda _: None)

    assert result.status == "verified_fix" and result.metric == "latency" and not result.patch_reverse
    # The fixture's culprit really is faster (timeout 30 → 10), and the report says so next to the gate.
    assert result.baselines == "median latency per run: good 300 ms, bad 100 ms, fix 100 ms"
    assert result.gain_note == "" and result.attempts[0].gates["gain_at_bad"] is True
    assert "-RETRY_PASS = 0.05\n+RETRY_PASS = 0.95\n" in result.patch and "TOOL_TIMEOUT_S" not in result.patch
    gates_ = result.attempts[0].gates
    assert gates_["quality"] and gates_["gain"] and gates_["fix_value"] == gates_["bad_value"] == 100.0
    # 10 suite + 2 held-out tasks × k=3; held-out baselines were run at both ends.
    kinds = {(s["kind"], s["n"]) for s in ledger.steps(run_id)}
    assert ("fix:1", 36) in kinds and sum(k == "verify:heldout" for k, _ in kinds) >= 1
    record = json.loads(ledger.get_artifact(run_id, "fix"))
    assert record["status"] == "verified_fix" and record["commit"] == ledger.get_run(run_id)["bad_sha"]
    assert [tuple(r) for r in ledger.conn.execute("SELECT purpose FROM llm_calls")] == [("fix_propose",)]
    assert not any(ref in prompts[0] for ref in ref_names(repo)) and "RETRY_PASS" in prompts[0]

    # Running again resumes: no new proposal, no new victim runs.
    before = ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]
    again = mods.fix.fix_run(ledger, run_id, log=lambda _: None)
    assert again.status == "verified_fix" and len(prompts) == 1
    assert ledger.conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0] == before


def test_failed_attempts_are_fed_back_until_one_keeps_the_gain(mods, tmp_path: Path, monkeypatch):
    _, ledger, run_id = localised(mods, tmp_path)
    prompts = fake_model(monkeypatch, [
        proposal(("RETRY_PASS = 0.5", "RETRY_PASS = 0.95")),  # snippet not in the file
        proposal(RESTORE, UNDO_SPEEDUP),  # restores quality but gives the speed-up back
        proposal(RESTORE),
    ])
    result = mods.fix.fix_run(ledger, run_id, log=lambda _: None, attempts=3)

    assert result.status == "verified_fix" and len(result.attempts) == 3
    first, second, third = result.attempts
    assert "occurs 0 times" in first.error and first.patch is None
    assert second.gates["quality"] and second.gates["gain"] is False and not second.verified
    assert third.verified
    assert "attempt 1: edit 1" in prompts[1]
    assert "attempt 2: intended gain lost: mean latency 300 with the fix vs 100" in prompts[2]


def test_without_a_verified_fix_the_hunk_revert_is_verified_instead(mods, tmp_path: Path):
    from typer.testing import CliRunner

    from culprit.cli import app

    _, ledger, run_id = localised(mods, tmp_path)
    db = tmp_path / "l.sqlite"
    out = CliRunner().invoke(app, ["fix", run_id, "--db", str(db)])  # no model: both attempts fail
    assert out.exit_code == 0, out.output
    assert "fix: verified_revert" in out.output
    assert "  median latency per run: good 300 ms, bad 100 ms, fix 100 ms" in out.output
    record = json.loads(ledger.get_artifact(run_id, "fix"))
    assert record["patch_reverse"] and "RETRY_PASS" in record["patch"]
    assert all(a["error"].startswith("no proposal") for a in record["attempts"])


def test_fix_needs_a_localisation(mods, tmp_path: Path):
    repo = build(tmp_path / "victim", commits=6, breaks_at=4, unbuildable_at=None, break_hunks="multi")
    orch = mods.orchestrator.Orchestrator(Ledger(tmp_path / "l.sqlite"),
                                          mods.config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="main"),
                                          log=lambda _: None)
    run_id = orch.start()
    orch.run(run_id)
    with pytest.raises(mods.finished.StageError, match="culprit localise"):
        mods.fix.fix_run(orch.ledger, run_id, log=lambda _: None)
