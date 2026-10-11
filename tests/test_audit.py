"""`culprit audit`: mutation testing of the eval suite (which realistic regressions would it miss?)."""

import difflib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from make_victim import build  # noqa: E402

from culprit import llm  # noqa: E402
from culprit.ledger import Ledger  # noqa: E402

AGENT = "refunddesk/agent.py"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CULPRIT_STATE_DIR", str(tmp_path / "state"))
    import culprit.config
    import culprit.orchestrator
    import culprit.sandbox
    import culprit.suite

    for mod in (culprit.config, culprit.sandbox, culprit.suite, culprit.orchestrator):
        importlib.reload(mod)
    repo = build(tmp_path / "victim", commits=2, breaks_at=99, unbuildable_at=None)
    cfg = culprit.config.Config(repo=str(repo), good_ref="good-v1.0", bad_ref="good-v1.0")
    return repo, tmp_path / "l.sqlite", cfg


def agent_source(repo: Path) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "show", f"good-v1.0:{AGENT}"], text=True)


def patch(repo: Path, old: str, new: str) -> str:
    before = agent_source(repo)
    assert before.count(old) == 1
    after = before.replace(old, new)
    body = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{AGENT}", f"b/{AGENT}"))
    return f"diff --git a/{AGENT} b/{AGENT}\n{body}"


def audit(db, cfg, **kw):
    from culprit import audit as a

    return a.audit_run(Ledger(db), cfg, "good-v1.0", log=lambda _: None, **kw)


def test_patch_mutants_are_caught_missed_or_invalid(env, tmp_path):
    repo, db, cfg = env
    d = tmp_path / "mutants"
    d.mkdir()
    (d / "disable_retries.patch").write_text(patch(repo, "RETRY_PASS = 0.95", "RETRY_PASS = 0.05"))
    (d / "longer_timeout.patch").write_text(patch(repo, "TOOL_TIMEOUT_S = 30", "TOOL_TIMEOUT_S = 60"))
    (d / "broken_import.patch").write_text(patch(repo, "TOOL_TIMEOUT_S = 30", "TOOL_TIMEOUT_S = = 30"))
    (d / "wrong_file.patch").write_text("diff --git a/nope.py b/nope.py\n--- a/nope.py\n+++ b/nope.py\n@@ -1 +1 @@\n-x\n+y\n")

    result = audit(db, cfg, patches=d)
    verdicts = {m.name: m.verdict for m in result.mutants}
    assert verdicts == {"disable_retries": "caught", "longer_timeout": "missed",
                        "broken_import": "invalid", "wrong_file": "invalid"}
    assert result.score == (1, 2)
    caught = next(m for m in result.mutants if m.name == "disable_retries")
    assert caught.p_value < 0.05 and set(caught.caught_by) <= {"t01", "t02", "t03", "t04", "t05"} and caught.caught_by
    assert Ledger(db).get_run(result.run_id)["status"] == "audited"

    # The victim repo itself is untouched: mutants live only in throwaway worktrees.
    assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True) == ""
    assert agent_source(repo).count("RETRY_PASS = 0.95") == 1


def fake_model(monkeypatch, replies: dict[str, dict]):
    prompts = []

    def complete(system, messages, max_tokens):
        prompt = messages[0]["content"]
        prompts.append(prompt)
        op = next(name for name in replies if f"Regression pattern: {name}" in prompt)
        return json.dumps(replies[op]), llm.Usage("fake-model", 300, 80, 0.0003)

    monkeypatch.setattr(llm, "_complete", complete)
    return prompts


def test_operator_mutants_from_the_model(env, monkeypatch):
    from culprit import audit as a

    repo, db, cfg = env
    edit = {"file": AGENT, "old": "RETRY_PASS = 0.95", "new": "RETRY_PASS = 0.05"}
    prompts = fake_model(monkeypatch, {
        a.BY_NAME["disable_retries"].title: {"applicable": True, "summary": "no retries", "edits": [edit],
                                             "task_idea": "a tool that fails once then succeeds"},
        a.BY_NAME["shrink_history"].title: {"applicable": False, "summary": "no history here", "edits": [],
                                            "task_idea": "multi-turn task"},
        a.BY_NAME["remove_code_guard"].title: {"applicable": True, "summary": "x", "task_idea": "y",
                                               "edits": [{"file": AGENT, "old": "NOT IN FILE", "new": "z"}]},
    })
    result = audit(db, cfg, operators=["disable_retries", "shrink_history", "remove_code_guard"])
    by = {m.name: m for m in result.mutants}
    assert by["disable_retries"].verdict == "caught"
    assert by["shrink_history"].verdict == "invalid" and "not applicable" in by["shrink_history"].note
    assert by["remove_code_guard"].verdict == "invalid" and "occurs 0 times" in by["remove_code_guard"].note
    # The model sees the agent, never the eval harness, so it can't mutate the grader.
    assert all(AGENT in p and "refunddesk/eval.py" not in p for p in prompts)
    calls = Ledger(db).conn.execute("SELECT COUNT(*) FROM llm_calls WHERE run_id = ?", (result.run_id,)).fetchone()[0]
    assert calls == 3

    # Resume: stored proposals are reused, no new model call, no new victim run.
    before = Ledger(db).conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]
    again = audit(db, cfg, run_id=result.run_id)
    assert {m.name: m.verdict for m in again.mutants} == {m.name: m.verdict for m in result.mutants}
    assert len(prompts) == 3
    assert Ledger(db).conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0] == before

    md = a.to_markdown(again)
    assert "Mutation score: 1/1" in md and "no retries" in md


def test_unknown_operator_is_refused(env):
    from culprit import audit as a

    _, db, cfg = env
    with pytest.raises(a.AuditError, match="unknown operators"):
        audit(db, cfg, operators=["nope"])
